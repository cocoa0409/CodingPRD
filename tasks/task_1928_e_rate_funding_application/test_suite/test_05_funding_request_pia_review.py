"""Funding request filing and PIA review: pinned rounding, the C2 allocation
waterfall, the review cycle, validation priority, and OCC (PRD §2.7, §2.10,
§3.5)."""
from test_helpers import (
    ApiErrorId,
    begin_review,
    budget_summary,
    decide_request,
    get_request,
    make_commitment_officer_headers,
    new_request,
    pia_response,
    request_info,
    set_clock,
    setup_applicant_base,
    setup_certified_contract,
    setup_committed_scenario,
    setup_request_with_lines,
    validate_error,
)


class TestPerLineRoundingThenSum:
    """Queue A: combinatorial_formula/commitment_per_line_rounding_then_sum."""

    def _committed_pair_of_999(self):
        return setup_committed_scenario(
            category="CATEGORY_TWO", bid_price=100000, contract_total=100000,
            line_amounts=(999, 999),  # C2 rate 50% (share 30.00, band [20,35))
        )

    def test_each_line_share_rounded_half_up_individually(self, api):
        """PRD §3.5: "Each surviving line then gets its share:
        `committed_share_cents` is the committed pre-discount amount multiplied by
        the request's pinned discount rate for the line's category and divided by
        100, rounded half up to integer cents — computed per line, never on
        aggregates."
        PRD §3.5: "Two 999-cent lines at a 50 percent rate illustrate why —
        per-line rounding yields 500 plus 500, a 1,000-cent total, where sum-first
        rounding would yield 999."

        Design: Difficulty/combinatorial_formula/commitment_per_line_rounding_then_sum
        """
        ctx = self._committed_pair_of_999()
        l1, l2 = ctx["lines"]
        # round_half_up(999 * 50 / 100) = round_half_up(499.5) = 500 per line
        assert l1["committed_share_cents"] == 500, (
            f"line 1 share must be 500, got {l1['committed_share_cents']}"
        )
        assert l2["committed_share_cents"] == 500, (
            f"line 2 share must be 500, got {l2['committed_share_cents']}"
        )
        assert l1["status"] == "COMMITTED" and l2["status"] == "COMMITTED"

    def test_request_total_is_sum_of_per_line_shares(self, api):
        """PRD §3.5: "The request's `committed_total_share_cents` is the sum of
        the per-line `committed_share_cents` values over its `COMMITTED` lines.
        The rounding order is pinned: per-line rounding first, then summation;
        summing pre-discount amounts and rounding once afterward is forbidden."

        Design: Difficulty/combinatorial_formula/commitment_per_line_rounding_then_sum
        """
        ctx = self._committed_pair_of_999()
        request = get_request(ctx["request"]["id"])
        # Per-line-then-sum: 500 + 500 = 1000 (sum-first would give 999).
        assert request["committed_total_share_cents"] == 1000, (
            f"request total must be 1000 (500+500 per-line), "
            f"got {request['committed_total_share_cents']}"
        )


class TestC2AllocationWaterfall:
    """Queue A: combinatorial_formula/c2_budget_created_at_allocation_order."""

    def _committed_waterfall(self):
        # 1000-student school: C2 cap = 16,700 * 1000 = 16,700,000; rate 50%.
        return setup_committed_scenario(
            category="CATEGORY_TWO", bid_price=18000000, contract_total=18000000,
            line_amounts=(10000000, 8000000),  # created in this order
        )

    def test_created_at_order_serves_first_line_then_caps_second(self, api):
        """PRD §3.5: "the server first computes the applicant's Category Two
        available budget as of the decision, then walks the request's
        `CATEGORY_TWO` lines in `created_at` ascending order (millisecond
        timestamps on sequentially created lines, so no ties occur; identifiers
        are never used as tiebreakers). At each line's turn the allocation is the
        smaller of the line's `requested_pre_discount_cents` and the budget
        remaining at that turn; the allocation becomes the line's
        `committed_pre_discount_cents`, and the remaining budget is reduced by
        that amount before the next line's turn."
        PRD §3.2: "For a `SCHOOL`, the pool cap is the greater of 16,700 cents
        (that is, $167.00) per enrolled student times `student_count`, or a floor
        of 2,500,000 cents ($25,000)."

        Design: Difficulty/combinatorial_formula/c2_budget_created_at_allocation_order
        """
        ctx = self._committed_waterfall()
        l1, l2 = ctx["lines"]
        assert l1["status"] == "COMMITTED"
        assert l1["committed_pre_discount_cents"] == 10000000, (
            f"L1 (created first) commits in full, got "
            f"{l1['committed_pre_discount_cents']}"
        )
        # Remaining after L1: 16,700,000 - 10,000,000 = 6,700,000 < 8,000,000
        assert l2["committed_pre_discount_cents"] == 6700000, (
            f"L2 must be capped at the remaining 6,700,000, got "
            f"{l2['committed_pre_discount_cents']}"
        )
        # round_half_up(6,700,000 * 50 / 100)
        assert l2["committed_share_cents"] == 3350000
        assert l2["status"] == "COMMITTED"

    def test_waterfall_drains_budget_to_zero(self, api):
        """PRD §3.2: "The **committed** side of the pool is the sum of
        `committed_pre_discount_cents` over the applicant's `CATEGORY_TWO`
        funding lines currently in `COMMITTED` status — `PENDING` and `DENIED`
        lines never consume budget, and `CANCELLED` lines have released whatever
        they held. The **available** budget is the cap minus the committed
        amount, and the server maintains the invariant that the cap always equals
        committed plus available."

        Design: Difficulty/combinatorial_formula/c2_budget_created_at_allocation_order
        """
        ctx = self._committed_waterfall()
        summary = budget_summary(ctx["applicant"]["id"], ctx["cycle"]["id"])
        assert summary["c2_cap_cents"] == 16700000
        assert summary["c2_committed_cents"] == 16700000, (
            f"10,000,000 + 6,700,000 must commit the whole cap, got "
            f"{summary['c2_committed_cents']}"
        )
        assert summary["c2_available_cents"] == 0


class TestPiaReviewCycle:
    """Queue A: non_linear_state_machine/pia_information_request_cycle."""

    def _filed_request_in_review(self):
        ctx = setup_certified_contract()
        setup_request_with_lines(ctx, line_amounts=(50000,))
        ctx["request"] = begin_review(ctx, ctx["request"])
        return ctx

    def test_information_request_round_trip(self, api):
        """PRD §3.5: "From `PIA_REVIEW`, an information request carrying
        `info_request_text` moves the request to `INFORMATION_REQUESTED`" and "A
        successful response returns the request from `INFORMATION_REQUESTED` to
        `PIA_REVIEW` and increments its `version`."

        Design: Difficulty/non_linear_state_machine/pia_information_request_cycle
        """
        ctx = self._filed_request_in_review()
        in_review = ctx["request"]
        info = request_info(ctx, ctx["request"], "Provide contract pages 4-7")
        assert info["status"] == "INFORMATION_REQUESTED"
        assert info["version"] == in_review["version"] + 1

        answered = pia_response(ctx, ctx["request"], "Pages attached",
                                info["version"])
        assert answered["status"] == "PIA_REVIEW"
        assert answered["version"] == info["version"] + 1

    def test_cycle_traversed_twice_versions_advance_each_hop(self, api):
        """PRD §3.5: "a further information request from `INFORMATION_REQUESTED`
        is a self-loop within the same review round — the status does not change,
        but the caller is again appended to `pia_reviewer_user_ids` and the
        request's `version` advances by 1."
        PRD §2.5: "`version` — a system-managed integer that increments by
        exactly 1 on every mutation of the resource, including mutations the
        server applies as cascade side effects on a related resource"

        Design: Difficulty/non_linear_state_machine/pia_information_request_cycle
        """
        ctx = self._filed_request_in_review()
        v_start = ctx["request"]["version"]  # after begin-review

        # Cycle 1
        v4 = request_info(ctx, ctx["request"], "Provide contract pages 4-7")["version"]
        r5 = pia_response(ctx, ctx["request"], "Pages attached", v4)
        assert r5["status"] == "PIA_REVIEW"

        # Cycle 2 (a second reviewer opens another round)
        info6 = request_info(ctx, ctx["request"], "Clarify installation dates",
                             reviewer_id="usac-emp-11")
        assert info6["status"] == "INFORMATION_REQUESTED"
        r7 = pia_response(ctx, ctx["request"], "Dates clarified", info6["version"])
        assert r7["status"] == "PIA_REVIEW"

        # request-info x2 + pia-response x2 = 4 mutations, +1 version each.
        assert r7["version"] == v_start + 4, (
            f"two full cycles must advance the version by exactly 4: "
            f"{v_start} -> {r7['version']}"
        )


class TestCertifyValidationOrder:
    """Queue A: priority_pair_validation_conflict/certify_state_beats_temporal."""

    def test_state_error_beats_temporal_on_recertify_after_window(self, api):
        """PRD §2.10: "When several checks could reject the same call, the server
        evaluates them in a fixed priority order so that the surfaced error is
        deterministic" — with "6. **State gates** — the target resource must be
        in a from-state of the invoked transition" listed before "9. **Temporal
        windows** — the window and deadline rules of §2.4".

        Design: Difficulty/priority_pair_validation_conflict/certify_state_beats_temporal
        """
        ctx = setup_certified_contract()
        setup_request_with_lines(ctx, line_amounts=(50000,))  # FILED 2026-10-15
        assert ctx["request"]["status"] == "FILED"

        # Past the filing window: both the state gate (not DRAFT) and the
        # temporal gate (outside the window) are violated; state wins.
        set_clock("2027-04-01T00:00:00Z")
        resp = api.certify_funding_request(ctx["request"]["id"], ctx["cert_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_certify_outside_filing_window_rejected(self, api):
        """PRD §2.4: "The **filing window** of a funding cycle is the closed
        interval from `window_open_date` through `window_close_date`. Certifying
        a funding request on the closing date itself is allowed; anything outside
        the interval is `ERR_FILING_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/certify_state_beats_temporal
        """
        ctx = setup_certified_contract()
        # DRAFT request with one line and a snapshot — only the temporal gate fails.
        setup_request_with_lines(ctx, line_amounts=(50000,), certify=False)
        set_clock("2027-04-01T00:00:00Z")
        resp = api.certify_funding_request(ctx["request"]["id"], ctx["cert_headers"])
        validate_error(resp, ApiErrorId.ERR_FILING_WINDOW_CLOSED)


class TestDecidePreconditions:
    def test_decide_blocked_while_information_requested(self, api):
        """PRD §3.5: "Deciding requires the request to be in `PIA_REVIEW` — an
        outstanding `INFORMATION_REQUESTED` blocks any decision until the
        applicant responds".

        Design: Corner/state_machines/decide_blocked_while_information_requested
        """
        ctx = setup_certified_contract()
        setup_request_with_lines(ctx, line_amounts=(50000,))
        begin_review(ctx, ctx["request"])
        info = request_info(ctx, ctx["request"], "Provide contract pages 4-7")
        assert info["status"] == "INFORMATION_REQUESTED"

        resp = api.decide_funding_request(
            ctx["request"]["id"], {"outcome": "COMMITTED"},
            make_commitment_officer_headers("usac-emp-7"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        # The applicant's response returns the request to PIA_REVIEW, unblocking.
        answered = pia_response(ctx, ctx["request"], "Pages attached",
                                info["version"])
        assert answered["status"] == "PIA_REVIEW"

    def test_snapshot_missing_blocks_certify(self, api):
        """PRD §3.5: "Three gates guard the transition, and they sit in their
        usual tiers: the clock's date must fall within the cycle's closed filing
        window (otherwise `ERR_FILING_WINDOW_CLOSED`); the request must contain
        at least one `PENDING` line (otherwise `ERR_EMPTY_REQUEST`); and an NSLP
        snapshot must exist for the applicant-and-cycle pair (otherwise
        `ERR_DISCOUNT_SNAPSHOT_MISSING`)."

        Design: Corner/validations/snapshot_missing_blocks_certify
        """
        ctx = setup_certified_contract(with_snapshot=False)
        # In-window, DRAFT, one line — only the snapshot gate can fail.
        setup_request_with_lines(ctx, line_amounts=(50000,), certify=False)
        resp = api.certify_funding_request(ctx["request"]["id"], ctx["cert_headers"])
        validate_error(resp, ApiErrorId.ERR_DISCOUNT_SNAPSHOT_MISSING)

    def test_certify_empty_request_rejected(self, api):
        """PRD §3.5: "the request must contain at least one `PENDING` line
        (otherwise `ERR_EMPTY_REQUEST`)".

        Design: Corner/validations/certify_empty_request_rejected
        """
        ctx = setup_applicant_base()  # snapshot recorded for (applicant, cycle)
        set_clock("2026-10-15T00:00:00Z")  # inside the filing window
        request = new_request(ctx)  # zero lines
        resp = api.certify_funding_request(request["id"], ctx["cert_headers"])
        validate_error(resp, ApiErrorId.ERR_EMPTY_REQUEST)

    def test_sod_commitment_officer_who_reviewed_cannot_decide(self, api):
        """PRD §2.8: "Symmetrically, every `PIAReviewer` who opens review or
        issues an information request on a funding request is recorded in the
        request's `pia_reviewer_user_ids`; the commitment decision must come from
        a `CommitmentOfficer` whose identifier does not appear in that list, and
        otherwise the decision is rejected with `ERR_SOD_COMMITMENT_OFFICER`
        (HTTP 409)."

        Design: Corner/rbac/sod_commitment_officer_who_reviewed_cannot_decide
        """
        ctx = setup_certified_contract()
        setup_request_with_lines(ctx, line_amounts=(50000,))
        begin_review(ctx, ctx["request"], reviewer_id="usac-emp-42")

        # The same operator id that ran begin-review may not issue the decision.
        resp = api.decide_funding_request(
            ctx["request"]["id"], {"outcome": "COMMITTED"},
            make_commitment_officer_headers("usac-emp-42"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_COMMITMENT_OFFICER)

        decided = decide_request(ctx, ctx["request"], outcome="COMMITTED",
                                 officer_id="usac-emp-7")
        assert decided["status"] == "COMMITTED"


class TestPiaResponseOcc:
    def test_occ_pia_response_stale_version(self, api):
        """PRD §2.7: "A `POST /erate/funding-requests/{id}/pia-responses` request
        must carry `expected_request_version`, holding the applicant's
        last-observed `version` of the funding request. If the request's current
        `version` has advanced beyond that value — for instance because a
        reviewer issued a further information request, a self-loop that
        legitimately advances `version` while leaving the `INFORMATION_REQUESTED`
        status unchanged — the response is predicated on a stale review round and
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_pia_response_stale_version
        """
        ctx = setup_certified_contract()
        setup_request_with_lines(ctx, line_amounts=(50000,))
        begin_review(ctx, ctx["request"])
        v4 = request_info(ctx, ctx["request"], "Provide contract pages 4-7")["version"]
        # Follow-up self-loop: status unchanged, version advances.
        follow_up = request_info(ctx, ctx["request"], "Also provide the site survey")
        assert follow_up["status"] == "INFORMATION_REQUESTED"
        assert follow_up["version"] == v4 + 1

        # Response predicated on the pre-self-loop version is stale.
        resp = api.submit_pia_response(
            ctx["request"]["id"],
            {"response_text": "Pages attached", "expected_request_version": v4},
            ctx["coord_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        # The same response against the current version succeeds.
        answered = pia_response(ctx, ctx["request"], "Pages and survey attached",
                                follow_up["version"])
        assert answered["status"] == "PIA_REVIEW"
