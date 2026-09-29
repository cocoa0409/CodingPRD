"""Two exclusion regimes: a buffered press line and an unbuffered claim window."""

from test_helpers import (
    ApiErrorId,
    api_client,
    approved_version,
    book_press_check,
    clear_claim,
    clearance_payload,
    legal,
    new_claim,
    new_printer,
    new_proof,
    press_check_payload,
    quality,
    read_claim,
    read_proof,
    reject_claim,
    validate_error,
    validate_success,
)

INCUMBENT_START = "2026-09-10T08:00:00Z"
INCUMBENT_END = "2026-09-10T12:00:00Z"

# PRD §2.4: "Timestamps are rendered as ISO 8601 UTC with three fractional digits."
# A stored *_utc instant is re-rendered under that rule, not echoed verbatim.
INCUMBENT_START_RENDERED = "2026-09-10T08:00:00.000Z"
INCUMBENT_END_RENDERED = "2026-09-10T12:00:00.000Z"


class TestPressCheckBufferOnASharedLine:
    """A four-hour booking that reserves eight hours of the line."""

    def _line_with_an_incumbent_booking(self):
        _brief, _asset, version = approved_version(
            asset_overrides={"brand_critical_color": True}
        )
        printer_a = new_printer(name="Cascade Print Co")
        printer_b = new_printer(name="Riverside Litho")
        proofs = [new_proof(version["id"], printer_a) for _ in range(3)]
        far_proof = new_proof(version["id"], printer_b)
        for proof in proofs + [far_proof]:
            assert proof["press_check_required"] is True
            assert proof["press_check_status"] == "PRESS_CHECK_REQUIRED"

        incumbent = book_press_check(
            proofs[0]["id"],
            press_line_code="LINE-A",
            press_check_start_utc=INCUMBENT_START,
            press_check_end_utc=INCUMBENT_END,
            attended_by_user_id="u_qa",
        )
        assert incumbent["press_check_status"] == "PRESS_CHECK_ATTENDED"
        return proofs, far_proof

    def test_a_gap_narrower_than_the_buffer_is_refused_and_a_touching_one_is_not(self):
        """13:00 collides with a booking that ended at 12:00; 16:00 does not.

        PRD §3.6: "The booked line is a shared physical resource, so the requested
        window is checked for collision: widened by two hours on **both** sides, it
        must not overlap the equally widened window of any other proof that shares the
        same vendor and the same `press_line_code` and whose `press_check_status` is
        `PRESS_CHECK_SCHEDULED` or `PRESS_CHECK_ATTENDED`."

        Design: Difficulty/resource_temporal_overlap/press_check_buffer_blocks_a_three_hour_gap_but_admits_a_four_hour_one
        """
        proofs, _far_proof = self._line_with_an_incumbent_booking()
        contender = proofs[1]

        refused = api_client.book_press_check(
            contender["id"],
            press_check_payload(
                press_line_code="LINE-A",
                press_check_start_utc="2026-09-10T13:00:00Z",
                press_check_end_utc="2026-09-10T15:00:00Z",
                attended_by_user_id="u_qa",
            ),
            quality(),
        )
        validate_error(refused, ApiErrorId.ERR_PRESS_CHECK_OVERLAP.value, 409)

        untouched = read_proof(contender["id"])
        assert untouched["press_check_status"] == "PRESS_CHECK_REQUIRED"
        assert untouched["press_check_start_utc"] is None

        booked = book_press_check(
            contender["id"],
            press_line_code="LINE-A",
            press_check_start_utc="2026-09-10T16:00:00Z",
            press_check_end_utc="2026-09-10T18:00:00Z",
            attended_by_user_id="u_qa",
        )
        assert booked["press_check_status"] == "PRESS_CHECK_ATTENDED"
        assert booked["press_check_start_utc"] == "2026-09-10T16:00:00.000Z"
        assert booked["press_line_code"] == "LINE-A"
        assert booked["attended_by_user_id"] == "u_qa"

    def test_the_reserved_resource_is_the_vendor_and_the_line_together(self):
        """The refused slot is free on another line, and at another vendor.

        PRD §3.6: "The comparison is half-open, so two bookings whose raw endpoints
        are separated by at least the two-hour buffer on each side are permitted, while
        a genuine collision is `ERR_PRESS_CHECK_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/press_check_buffer_blocks_a_three_hour_gap_but_admits_a_four_hour_one
        """
        proofs, far_proof = self._line_with_an_incumbent_booking()
        window = {
            "press_check_start_utc": "2026-09-10T13:00:00Z",
            "press_check_end_utc": "2026-09-10T15:00:00Z",
            "attended_by_user_id": "u_qa",
        }

        other_line = book_press_check(
            proofs[2]["id"], press_line_code="LINE-B", **window
        )
        assert other_line["press_check_status"] == "PRESS_CHECK_ATTENDED"
        assert other_line["press_line_code"] == "LINE-B"

        other_vendor = book_press_check(
            far_proof["id"], press_line_code="LINE-A", **window
        )
        assert other_vendor["press_check_status"] == "PRESS_CHECK_ATTENDED"
        assert other_vendor["press_line_code"] == "LINE-A"

        incumbent = read_proof(proofs[0]["id"])
        assert incumbent["press_check_start_utc"] == INCUMBENT_START_RENDERED
        assert incumbent["press_check_end_utc"] == INCUMBENT_END_RENDERED


class TestClaimClearanceWindowsExcludePerCodeAndMarket:
    """The same overlap idea calibrated with no buffer at all."""

    def _library_with_one_cleared_window(self):
        claim_a = new_claim()
        claim_b = new_claim()
        claim_c = new_claim()
        claim_d = new_claim(market_code="CA")
        claim_e = new_claim(claim_code="CLM-SRC-02")
        for claim in (claim_a, claim_b, claim_c, claim_d, claim_e):
            assert claim["legal_status"] == "DRAFT"

        cleared = clear_claim(
            claim_a["id"],
            cleared_from_utc="2026-09-01T00:00:00Z",
            cleared_until_utc="2026-10-01T00:00:00Z",
        )
        assert cleared["legal_status"] == "CLEARED"
        return claim_a, claim_b, claim_c, claim_d, claim_e

    def test_an_intersecting_window_is_refused_but_a_touching_start_is_accepted(self):
        """No buffer at all: 2026-10-01 abuts the incumbent's exclusive end.

        PRD §3.2: "The interval comparison carries **no** buffer whatsoever, so a
        window that begins exactly at another window's `cleared_until_utc` is accepted,
        while any genuine intersection is refused with `ERR_CLAIM_CLEARANCE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/claim_clearance_intervals_exclude_per_code_and_market_with_no_buffer
        """
        _claim_a, claim_b, claim_c, _claim_d, _claim_e = (
            self._library_with_one_cleared_window()
        )

        refused = api_client.decide_claim_clearance(
            claim_b["id"],
            clearance_payload(
                "CLEARED",
                cleared_from_utc="2026-09-15T00:00:00Z",
                cleared_until_utc="2026-11-01T00:00:00Z",
            ),
            legal(),
        )
        validate_error(refused, ApiErrorId.ERR_CLAIM_CLEARANCE_OVERLAP.value, 409)
        assert read_claim(claim_b["id"])["legal_status"] == "DRAFT"
        assert read_claim(claim_b["id"])["cleared_from_utc"] is None

        abutting = clear_claim(
            claim_b["id"],
            cleared_from_utc="2026-10-01T00:00:00Z",
            cleared_until_utc="2026-11-01T00:00:00Z",
        )
        assert abutting["legal_status"] == "CLEARED"
        assert abutting["cleared_from_utc"] == "2026-10-01T00:00:00.000Z"
        assert abutting["cleared_by_user_id"] == "u_legal"

        contained = api_client.decide_claim_clearance(
            claim_c["id"],
            clearance_payload(
                "CLEARED",
                cleared_from_utc="2026-09-15T00:00:00Z",
                cleared_until_utc="2026-09-20T00:00:00Z",
            ),
            legal(),
        )
        validate_error(contained, ApiErrorId.ERR_CLAIM_CLEARANCE_OVERLAP.value, 409)

    def test_the_scope_key_is_the_pair_and_only_cleared_rows_participate(self):
        """Another market, another code, and a withdrawn incumbent all step aside.

        PRD §3.2: "The resulting clearance window is half-open — inclusive of
        `cleared_from_utc` and exclusive of `cleared_until_utc` — and it must not
        intersect the window of any other claim that shares both the same `claim_code`
        and the same `market_code` and whose `legal_status` is currently `CLEARED`."

        Design: Difficulty/resource_temporal_overlap/claim_clearance_intervals_exclude_per_code_and_market_with_no_buffer
        """
        claim_a, _claim_b, claim_c, claim_d, claim_e = (
            self._library_with_one_cleared_window()
        )
        straddling = {
            "cleared_from_utc": "2026-09-15T00:00:00Z",
            "cleared_until_utc": "2026-11-01T00:00:00Z",
        }

        other_market = clear_claim(claim_d["id"], **straddling)
        assert other_market["legal_status"] == "CLEARED"
        assert other_market["market_code"] == "CA"

        other_code = clear_claim(claim_e["id"], **straddling)
        assert other_code["legal_status"] == "CLEARED"
        assert other_code["claim_code"] == "CLM-SRC-02"

        refused = api_client.decide_claim_clearance(
            claim_c["id"],
            clearance_payload(
                "CLEARED",
                cleared_from_utc="2026-09-15T00:00:00Z",
                cleared_until_utc="2026-09-20T00:00:00Z",
            ),
            legal(),
        )
        validate_error(refused, ApiErrorId.ERR_CLAIM_CLEARANCE_OVERLAP.value, 409)

        withdrawn = reject_claim(claim_a["id"])
        assert withdrawn["legal_status"] == "REJECTED"
        assert withdrawn["cleared_from_utc"] == "2026-09-01T00:00:00.000Z"
        assert withdrawn["cleared_until_utc"] == "2026-10-01T00:00:00.000Z"

        retried = validate_success(
            api_client.decide_claim_clearance(
                claim_c["id"],
                clearance_payload(
                    "CLEARED",
                    cleared_from_utc="2026-09-15T00:00:00Z",
                    cleared_until_utc="2026-09-20T00:00:00Z",
                ),
                legal(),
            ),
            200,
        )
        assert retried["legal_status"] == "CLEARED"
