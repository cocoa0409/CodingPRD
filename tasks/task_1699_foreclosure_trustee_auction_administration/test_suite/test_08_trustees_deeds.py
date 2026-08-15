"""Trustee's deed drafting, the fifteen-day recording window, and void blocking."""
from test_helpers import (
    AUCT,
    CM,
    ApiErrorId,
    get_case,
    set_clock,
    setup_case_at_sale_scheduled,
    setup_closed_sale,
    validate_error,
    validate_success,
)


def _closed_beneficiary_win(api, reference_code, loan_reference, venue):
    return setup_closed_sale(
        reference_code, venue_name=venue, loan_reference=loan_reference,
        opening_bid_cents=42_000_000, max_bid_cents=43_000_000,
        strategy="OPENING_ONLY", bid_amount_cents=None,
    )


class TestDeedCreation:
    def test_deed_create_before_close_rejected(self, api):
        """PRD §3.9: "A sale carries at most one live deed: drafting is rejected with `ERR_INVALID_DEED_STATE` (HTTP 409) when a deed in any status other than `VOIDED` already exists for the sale, and a sale that is not `CLOSED` yields `ERR_INVALID_SALE_STATE`."

        Design: Corner/endpoints/deed_create_before_close_rejected
        """
        ctx = setup_case_at_sale_scheduled("BEN-E2", venue_name="VEN-E2",
                                           loan_reference="LN-E2")
        resp = api.create_trustees_deed(ctx["sale"]["id"],
                                        CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_SALE_STATE, 409)


class TestDeedRecording:
    def test_deed_record_twice_rejected(self, api):
        """PRD §3.9: "A `CaseManager` records a deed while the case is in `SOLD` (`ERR_INVALID_CASE_STATE` otherwise) and the deed is in `DRAFTED` status (`ERR_INVALID_DEED_STATE` otherwise); these state checks run before the deadline test."
        PRD §3.9: "On recording, the deed becomes `RECORDED` with `recorded_at` stamped, the case moves to `DEED_RECORDED`, and the case's `version` increments."

        Design: Corner/state_machines/deed_record_twice_rejected
        """
        ctx = _closed_beneficiary_win(api, "BEN-S9", "LN-S9", "VEN-S9")
        deed = validate_success(
            api.create_trustees_deed(ctx["sale"]["id"], CM), 201
        )
        validate_success(
            api.record_trustees_deed(deed["id"], {}, CM), 200
        )
        resp = api.record_trustees_deed(deed["id"], {}, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_DEED_STATE, 409)
        case = get_case(ctx["case"]["id"])
        assert case["lifecycle_status"] == "DEED_RECORDED", (
            "the first record took effect exactly once"
        )

    def test_deed_record_late_requires_court_order_extension(self, api):
        """PRD §3.9: "The recording must occur no later than fifteen days after the sale's `closed_at` — unless the request carries `court_order_extension` set to true, in which case the deadline is waived; a late recording without the extension is rejected with `ERR_DEED_RECORDING_LATE` (HTTP 422)."

        Design: Corner/validations/deed_record_late_requires_court_order_extension
        """
        ctx = _closed_beneficiary_win(api, "BEN-VL5", "LN-VL5", "VEN-VL5")
        deed = validate_success(
            api.create_trustees_deed(ctx["sale"]["id"], CM), 201
        )
        # Close was 2026-11-23; fifteen days later is 2026-12-08.
        set_clock("2026-12-09T00:00:00Z")
        resp = api.record_trustees_deed(deed["id"], {}, CM)
        validate_error(resp, ApiErrorId.ERR_DEED_RECORDING_LATE, 422)
        recorded = validate_success(
            api.record_trustees_deed(
                deed["id"], {"court_order_extension": True}, CM
            ),
            200,
        )
        assert recorded["status"] == "RECORDED"
        assert get_case(ctx["case"]["id"])["lifecycle_status"] == "DEED_RECORDED"

    def test_void_after_deed_recorded_rejected(self, api):
        """PRD §3.8: "Two conditions make a sale un-voidable, surfacing `ERR_SALE_NOT_VOIDABLE` (HTTP 409): a trustee's deed in `RECORDED` status already exists for the sale, or surplus distribution has begun — that is, any disbursement of recipient type `CLAIMANT` or `BORROWER_RESIDUE` exists for the case."

        Design: Corner/errors/void_after_deed_recorded_rejected
        """
        ctx = _closed_beneficiary_win(api, "BEN-ER4", "LN-ER4", "VEN-ER4")
        deed = validate_success(
            api.create_trustees_deed(ctx["sale"]["id"], CM), 201
        )
        validate_success(
            api.record_trustees_deed(deed["id"], {}, CM), 200
        )
        resp = api.void_sale(
            ctx["sale"]["id"], {"reason": "late-discovered defect"}, AUCT
        )
        validate_error(resp, ApiErrorId.ERR_SALE_NOT_VOIDABLE, 409)
        assert get_case(ctx["case"]["id"])["lifecycle_status"] == "DEED_RECORDED"
        sale = validate_success(api.get_auction_sale(ctx["sale"]["id"], AUCT), 200)
        assert sale["status"] == "CLOSED"

