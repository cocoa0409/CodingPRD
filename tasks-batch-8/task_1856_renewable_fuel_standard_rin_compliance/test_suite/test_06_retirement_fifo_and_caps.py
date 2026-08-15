"""Retirement batches: FIFO allocation, carryover cap, decide cascades (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    CM,
    OPS,
    create_account,
    create_account_and_year,
    create_approved_vendor,
    create_batch,
    create_delivered_trade,
    create_generated_lot,
    create_separated_lot,
    create_trade,
    create_vendor,
    decide_batch,
    get_success_data,
    make_trader_headers,
    pay_trade,
    deliver_trade,
    separate_lot,
    set_clock,
    submit_batch,
    validate_error,
    validate_success,
    api_client,
)


class TestCarryoverCapWaterfall:
    def _setup_cap_exhausted(self, api, epa_id):
        """Year with TOTAL cap 80; batch A (80 prior-vintage) ACCEPTED; batch B (1 prior) DRAFT."""
        acct, yr = create_account_and_year(epa_registration_id=epa_id)
        create_separated_lot(acct["id"], d_code="D6", vintage_year=2025,
                             gallon_qty=100)
        b_a = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                           rin_qty=80)
        submit_batch(b_a["id"])
        decide_batch(b_a["id"], "ACCEPT")
        b_b = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                           rin_qty=1)
        return yr, b_a, b_b

    def test_cap_includes_accepted_prior_retirements(self, api):
        """PRD §3.5: "Submission passes only while the batch's `prior_vintage_qty` plus the year's already-retired prior-vintage counter for that category stays at or below the cap — a batch landing exactly at the cap passes, while one RIN beyond it fails with `ERR_CARRYOVER_CAP_EXCEEDED`."

        Design: Difficulty/combinatorial_formula/carryover_cap_waterfall_mode_a
        """
        yr, _b_a, b_b = self._setup_cap_exhausted(api, "EPA-ACME-3")
        resp = api.submit_retirement_batch(b_b["id"], CM)
        validate_error(resp, ApiErrorId.ERR_CARRYOVER_CAP_EXCEEDED)

    def test_rejected_submit_leaves_counters_and_batch_unchanged(self, api):
        """PRD §3.5: "Current-vintage RINs are uncapped, and the prior-vintage counters count only `ACCEPTED` batches."
        PRD §3.5: "New batches stand `DRAFT` with `allocations` empty and `prior_vintage_qty` zero."

        Design: Difficulty/combinatorial_formula/carryover_cap_waterfall_mode_a
        """
        yr, _b_a, b_b = self._setup_cap_exhausted(api, "EPA-ACME-3B")
        resp = api.submit_retirement_batch(b_b["id"], CM)
        validate_error(resp, ApiErrorId.ERR_CARRYOVER_CAP_EXCEEDED)
        yr_after = validate_success(api.get_obligation_year(yr["id"], CM))
        assert yr_after["retired_prior_total_rins"] == 80
        b_after = validate_success(api.get_retirement_batch(b_b["id"], CM))
        assert b_after["status"] == "DRAFT"


class TestCarryoverCapBoundary:
    def _setup_boundary(self, api, epa_id):
        acct, yr = create_account_and_year(epa_registration_id=epa_id)
        # Supply must cover both batches (80 + 81) so the only gate that can
        # fire on the 81-RIN submission is the carryover cap (PRD §3.5) —
        # ERR_INSUFFICIENT_RINS is listed before ERR_CARRYOVER_CAP_EXCEEDED in
        # the §2.8 final tier and would otherwise pre-empt it.
        create_separated_lot(acct["id"], d_code="D6", vintage_year=2025,
                             gallon_qty=200)
        b_ok = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                            rin_qty=80)
        b_over = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                              rin_qty=81)
        return yr, b_ok, b_over

    def test_exactly_at_cap_passes(self, api):
        """PRD §3.5: "The carryover allowance for a category is twenty percent of the active RVO for that category, rounded half-up to a whole RIN."
        PRD §3.5: "a batch landing exactly at the cap passes, while one RIN beyond it fails with `ERR_CARRYOVER_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/carryover_cap_at_exactly_20_percent_allowed
        """
        _yr, b_ok, _b_over = self._setup_boundary(api, "EPA-ACME-11")
        data = get_success_data(api.submit_retirement_batch(b_ok["id"], CM))
        assert data["status"] == "SUBMITTED"
        assert data["prior_vintage_qty"] == 80

    def test_one_beyond_cap_fails(self, api):
        """PRD §3.5: "a batch landing exactly at the cap passes, while one RIN beyond it fails with `ERR_CARRYOVER_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/carryover_cap_at_exactly_20_percent_allowed
        """
        _yr, b_ok, b_over = self._setup_boundary(api, "EPA-ACME-11B")
        get_success_data(api.submit_retirement_batch(b_ok["id"], CM))
        resp = api.submit_retirement_batch(b_over["id"], CM)
        validate_error(resp, ApiErrorId.ERR_CARRYOVER_CAP_EXCEEDED)
        after = validate_success(api.get_retirement_batch(b_over["id"], CM))
        assert after["status"] == "DRAFT"


class TestBatchResubmitStateBeatsFiscal:
    def _setup(self, api, epa_id):
        """Batch A ACCEPTED (cap exhausted at 80); batch B SUBMITTED, still pending."""
        acct, yr = create_account_and_year(epa_registration_id=epa_id)
        create_separated_lot(acct["id"], d_code="D6", vintage_year=2025,
                             gallon_qty=200)
        b_a = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                           rin_qty=80)
        submit_batch(b_a["id"])
        b_b = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                           rin_qty=80)
        submit_batch(b_b["id"])
        decide_batch(b_a["id"], "ACCEPT")
        return b_b

    def test_resubmit_of_submitted_batch_returns_invalid_state(self, api):
        """PRD §2.8: "The optimistic-concurrency check on report creation comes next (`ERR_STALE_VERSION`), then state-machine admissibility (`ERR_INVALID_STATE`, which covers the FINALIZED-year gates, the trade payment/transfer cross-guards, and the same-type non-draft report that blocks a new report)."
        PRD §2.8: "and finally quantity sufficiency and caps (`ERR_SEPARATION_EXCEEDS_ATTACHED`, `ERR_INSUFFICIENT_RINS`, `ERR_CARRYOVER_CAP_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/batch_resubmit_state_beats_carryover_fiscal
        """
        b_b = self._setup(api, "EPA-ACME-9")
        resp = api.submit_retirement_batch(b_b["id"], CM)
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert err["error_id"] != ApiErrorId.ERR_CARRYOVER_CAP_EXCEEDED

    def test_resubmit_leaves_batch_submitted(self, api):
        """PRD §3.5: "Submission is where the machinery runs. The year must be `OPEN` or `VOLUME_CLOSED` — a `FINALIZED` year rejects submission with `ERR_INVALID_STATE`"

        Design: Difficulty/priority_pair_validation_conflict/batch_resubmit_state_beats_carryover_fiscal
        """
        b_b = self._setup(api, "EPA-ACME-9B")
        resp = api.submit_retirement_batch(b_b["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_retirement_batch(b_b["id"], CM))
        assert after["status"] == "SUBMITTED"


class TestLotRinConservationSubmitReject:
    def _setup(self, api, epa_id):
        acct, yr = create_account_and_year(epa_registration_id=epa_id)
        lot = create_separated_lot(acct["id"], d_code="D6", vintage_year=2026,
                                   gallon_qty=100)
        batch = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                             rin_qty=40)
        submit_batch(batch["id"])
        return lot, batch

    def test_reject_releases_pending_allocations_back(self, api):
        """PRD §3.5: "Rejection instead releases the pending allocations back onto each lot's `separated_qty`, restoring the lot's conservation balance."

        Design: Difficulty/compensating_invariant/lot_rin_conservation_submit_reject
        """
        lot, batch = self._setup(api, "EPA-ACME-17")
        data = decide_batch(batch["id"], "REJECT")
        assert data["status"] == "REJECTED"
        lot_after = validate_success(api.get_rin_lot(lot["id"], CM))
        assert lot_after["separated_qty"] == 100
        assert lot_after["pending_retired_qty"] == 0
        assert lot_after["retired_qty"] == 0

    def test_conservation_holds_exactly_after_reject(self, api):
        """PRD §3.2: "Throughout a lot's life its `rin_qty` is fully accounted for as the sum of those six buckets, and `available_qty` — the retirement-eligible balance — is always what remains of `rin_qty` after subtracting the attached, pending, retired, invalidated, and expired quantities."

        Design: Difficulty/compensating_invariant/lot_rin_conservation_submit_reject
        """
        lot, batch = self._setup(api, "EPA-ACME-17B")
        decide_batch(batch["id"], "REJECT")
        lot_after = validate_success(api.get_rin_lot(lot["id"], CM))
        assert lot_after["rin_qty"] == 100
        assert lot_after["attached_qty"] == 0
        assert lot_after["available_qty"] == 100


class TestRetirementAcceptanceCascade:
    def _setup(self, api, epa_id):
        acct, yr = create_account_and_year(epa_registration_id=epa_id)
        create_separated_lot(acct["id"], d_code="D3", vintage_year=2026,
                             gallon_qty=100)
        create_separated_lot(acct["id"], d_code="D4", vintage_year=2026,
                             gallon_qty=200)
        lot_d6 = create_separated_lot(acct["id"], d_code="D6", vintage_year=2026,
                                      gallon_qty=100)
        b1 = create_batch(yr["id"], category="CELLULOSIC", d_code="D3",
                          rin_qty=100)
        submit_batch(b1["id"])
        decide_batch(b1["id"], "ACCEPT")
        b2 = create_batch(yr["id"], category="BIOMASS_DIESEL", d_code="D4",
                          rin_qty=200)
        submit_batch(b2["id"])
        decide_batch(b2["id"], "ACCEPT")
        b3 = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                          rin_qty=100)
        submit_batch(b3["id"])
        return yr, lot_d6, b3

    def test_acceptance_debits_lots_to_exhaustion(self, api):
        """PRD §3.5: "On acceptance each allocated lot's pending quantity converts into `retired_qty`; a lot whose available balance thereby reaches zero becomes `EXHAUSTED` and leaves all further separation and allocation."

        Design: Difficulty/transitive_cascade/retirement_acceptance_cascade_to_satisfied
        """
        _yr, lot_d6, b3 = self._setup(api, "EPA-ACME-8")
        decide_batch(b3["id"], "ACCEPT")
        lot_after = validate_success(api.get_rin_lot(lot_d6["id"], CM))
        assert lot_after["status"] == "EXHAUSTED"
        assert lot_after["retired_qty"] == 100

    def test_nested_counters_and_posture_flip_to_satisfied(self, api):
        """PRD §3.5: "the categories nest: a retired RIN counts toward every category its D-code maps to. `D3` counts toward `CELLULOSIC`, `ADVANCED`, and `TOTAL_RENEWABLE`; `D4` toward `BIOMASS_DIESEL`, `ADVANCED`, and `TOTAL_RENEWABLE`; `D5` toward `ADVANCED` and `TOTAL_RENEWABLE`; `D6` toward `TOTAL_RENEWABLE` only."
        PRD §2.6: "A year's `compliance_posture` is `SATISFIED` when, for every one of the four categories, the year's retired-RIN counter is at least the active RVO for that category — a counter exactly equal to its RVO counts as satisfied."

        Design: Difficulty/transitive_cascade/retirement_acceptance_cascade_to_satisfied
        """
        yr, _lot_d6, b3 = self._setup(api, "EPA-ACME-8B")
        decide_batch(b3["id"], "ACCEPT")
        yr_after = validate_success(api.get_obligation_year(yr["id"], CM))
        assert yr_after["retired_cellulosic_rins"] == 100
        assert yr_after["retired_biomass_diesel_rins"] == 200
        assert yr_after["retired_advanced_rins"] == 300
        assert yr_after["retired_total_rins"] == 400
        assert yr_after["compliance_posture"] == "SATISFIED"


class TestFifoAllocation:
    def _setup(self, api, epa_id):
        acct, yr = create_account_and_year(epa_registration_id=epa_id)
        lot1 = create_separated_lot(acct["id"], d_code="D6", vintage_year=2026,
                                    gallon_qty=100)
        # Make lot1 strictly older than lot2 under the logical clock (PRD §2.4:
        # the service never falls back to wall-clock time, so two lots created
        # at the same clock instant tie on created_at and §3.5 breaks the tie
        # by rin_qty ascending — which would put the 50-RIN lot first).
        set_clock("2026-08-02T00:00:00Z")
        lot2 = create_separated_lot(acct["id"], d_code="D6", vintage_year=2026,
                                    gallon_qty=50)
        batch = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                             rin_qty=120)
        return lot1, lot2, batch

    def test_fifo_draws_older_lot_first_with_partial_final(self, api):
        """PRD §3.5: "Eligible lots are ordered by `created_at` ascending with ties broken by `rin_qty` ascending (never by lot id), and the draw takes from each lot the smaller of its available balance and the remaining need until the batch is filled"
        PRD §3.5: "The resulting draw list is recorded as the batch's `allocations` in draw order"

        Design: Corner/calculations/fifo_allocation_order_and_partial_final_lot
        """
        lot1, lot2, batch = self._setup(api, "EPA-CALC-1")
        data = get_success_data(api.submit_retirement_batch(batch["id"], CM))
        assert data["allocations"] == [
            {"rin_lot_id": lot1["id"], "qty": 100},
            {"rin_lot_id": lot2["id"], "qty": 20},
        ]

    def test_fifo_moves_drawn_quantities_into_pending(self, api):
        """PRD §3.5: "each allocated lot moves the drawn quantity from `separated_qty` into `pending_retired_qty`"

        Design: Corner/calculations/fifo_allocation_order_and_partial_final_lot
        """
        lot1, lot2, batch = self._setup(api, "EPA-CALC-1B")
        get_success_data(api.submit_retirement_batch(batch["id"], CM))
        l1 = validate_success(api.get_rin_lot(lot1["id"], CM))
        l2 = validate_success(api.get_rin_lot(lot2["id"], CM))
        assert l1["pending_retired_qty"] == 100 and l1["separated_qty"] == 0
        assert l2["pending_retired_qty"] == 20 and l2["separated_qty"] == 30


class TestInsufficientEligibleRins:
    def _setup(self, api, epa_id):
        acct, yr = create_account_and_year(epa_registration_id=epa_id)
        create_separated_lot(acct["id"], d_code="D6", vintage_year=2026,
                             gallon_qty=10)
        ven = create_vendor(acct["id"], qap_audited=False)
        trd = create_trade(acct["id"], ven["id"], rin_qty=100,
                           price_per_rin_cents=90)
        pay_trade(trd["id"])
        deliver_trade(trd["id"])  # delivered but NOT verified
        batch = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                             rin_qty=120)
        return batch

    def test_unverified_purchased_lot_excluded_from_eligible_supply(self, api):
        """PRD §3.5: "generated lots contribute their separated, available balance, while purchased lots qualify only when their source trade stands `VERIFIED`."
        PRD §3.5: "if the eligible supply totals less than `rin_qty`, submission fails with `ERR_INSUFFICIENT_RINS`."

        Design: Corner/calculations/insufficient_eligible_rins_at_submit
        """
        batch = self._setup(api, "EPA-CALC-2")
        resp = api.submit_retirement_batch(batch["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_RINS)

    def test_failed_submit_leaves_batch_in_draft(self, api):
        """PRD §3.5: "New batches stand `DRAFT` with `allocations` empty and `prior_vintage_qty` zero."

        Design: Corner/calculations/insufficient_eligible_rins_at_submit
        """
        batch = self._setup(api, "EPA-CALC-2B")
        resp = api.submit_retirement_batch(batch["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_RINS)
        after = validate_success(api.get_retirement_batch(batch["id"], CM))
        assert after["status"] == "DRAFT"


class TestSeparationBoundary:
    def _setup(self, api, epa_id):
        acct = create_account(epa_registration_id=epa_id)
        lot = create_generated_lot(acct["id"], d_code="D4", vintage_year=2026,
                                   gallon_qty=101, equivalence_value=1.5)
        return lot

    def test_separating_exactly_attached_qty_succeeds(self, api):
        """PRD §3.2: "the quantity must be positive and must not exceed the lot's `attached_qty` — blending exactly the remaining attached quantity succeeds, while one gallon more is rejected with `ERR_SEPARATION_EXCEEDS_ATTACHED`."

        Design: Corner/calculations/separation_boundary_exactly_attached
        """
        lot = self._setup(api, "EPA-CALC-3")
        data = get_success_data(
            api.create_separation(lot["id"], {"blended_gallons": 152}, CM),
        )
        assert data["blended_gallons"] == 152
        lot_after = validate_success(api.get_rin_lot(lot["id"], CM))
        assert lot_after["attached_qty"] == 0
        assert lot_after["separated_qty"] == 152

    def test_one_beyond_attached_qty_fails_and_conservation_holds(self, api):
        """PRD §3.2: "blending exactly the remaining attached quantity succeeds, while one gallon more is rejected with `ERR_SEPARATION_EXCEEDS_ATTACHED`."
        PRD §3.2: "Throughout a lot's life its `rin_qty` is fully accounted for as the sum of those six buckets"

        Design: Corner/calculations/separation_boundary_exactly_attached
        """
        lot = self._setup(api, "EPA-CALC-3B")
        get_success_data(
            api.create_separation(lot["id"], {"blended_gallons": 152}, CM),
        )
        resp = api.create_separation(lot["id"], {"blended_gallons": 1}, CM)
        validate_error(resp, ApiErrorId.ERR_SEPARATION_EXCEEDS_ATTACHED)
        lot_after = validate_success(api.get_rin_lot(lot["id"], CM))
        assert lot_after["rin_qty"] == 152


class TestDCodeCategoryMismatch:
    def test_d6_batch_toward_advanced_rejected(self, api):
        """PRD §3.5: "the category must be one the D-code maps to, or creation fails with `ERR_D_CODE_NOT_ELIGIBLE`."

        Design: Corner/validations/d_code_category_mismatch
        """
        _acct, yr = create_account_and_year(epa_registration_id="EPA-VAL-4")
        payload = {
            "obligation_year_id": yr["id"],
            "category": "ADVANCED",
            "d_code": "D6",
            "rin_qty": 10,
        }
        resp = api.create_retirement_batch(payload, CM)
        validate_error(resp, ApiErrorId.ERR_D_CODE_NOT_ELIGIBLE)


class TestRetirementDeadlineExactInstant:
    def _setup(self, api, epa_id):
        acct, yr = create_account_and_year(epa_registration_id=epa_id)
        create_separated_lot(acct["id"], d_code="D6", vintage_year=2026,
                             gallon_qty=100)
        b1 = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                          rin_qty=10)
        b2 = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                          rin_qty=10)
        return b1, b2

    def test_submit_at_exactly_deadline_succeeds(self, api):
        """PRD §2.10: "Retirement batches for an obligation year must be submitted at or before 23:59:59 UTC on March 31 of the year following the compliance year; a later submission is rejected with `ERR_DEADLINE_PASSED`."

        Design: Corner/validations/retirement_deadline_exact_instant
        """
        b1, _b2 = self._setup(api, "EPA-VAL-3")
        set_clock("2027-03-31T23:59:59Z")
        data = get_success_data(api.submit_retirement_batch(b1["id"], CM))
        assert data["status"] == "SUBMITTED"

    def test_submit_one_second_past_deadline_fails(self, api):
        """PRD §2.10: "Retirement batches for an obligation year must be submitted at or before 23:59:59 UTC on March 31 of the year following the compliance year; a later submission is rejected with `ERR_DEADLINE_PASSED`."

        Design: Corner/validations/retirement_deadline_exact_instant
        """
        b1, b2 = self._setup(api, "EPA-VAL-3B")
        set_clock("2027-03-31T23:59:59Z")
        get_success_data(api.submit_retirement_batch(b1["id"], CM))
        set_clock("2027-04-01T00:00:00Z")
        resp = api.submit_retirement_batch(b2["id"], CM)
        validate_error(resp, ApiErrorId.ERR_DEADLINE_PASSED)


class TestBatchDecideAfterLotExpiry:
    def _setup(self, api, epa_id):
        acct, yr = create_account_and_year(epa_registration_id=epa_id)
        lot = create_separated_lot(acct["id"], d_code="D6", vintage_year=2025,
                                   gallon_qty=50)
        batch = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                             rin_qty=50)
        submit_batch(batch["id"])
        # Jump past (2025+2)-03-31 so the lot expires while batch is SUBMITTED.
        set_clock("2028-04-01T00:00:00Z")
        return lot, batch

    def test_lot_expires_via_clock_sweep(self, api):
        """PRD §2.10: "Once the logical clock passes 23:59:59 UTC on March 31 of the year two years after a lot's vintage, every still-`ACTIVE` lot of that vintage expires in the sweep."

        Design: Corner/endpoints/batch_decide_fails_when_lot_expired_pending
        """
        lot, _batch = self._setup(api, "EPA-EP-3")
        lot_after = validate_success(api.get_rin_lot(lot["id"], CM))
        assert lot_after["status"] == "EXPIRED"

    def test_decide_fails_with_insufficient_rins_and_batch_stays_submitted(self, api):
        """PRD §3.5: "Acceptance requires every allocated lot to still stand `ACTIVE` with a pending balance covering its allocation — a lot that expired or was invalidated while the batch sat `SUBMITTED` fails the decision with `ERR_INSUFFICIENT_RINS`."
        PRD §2.10: "Pending retirement allocations on an expiring lot are not released into retirement: any batch holding them remains `SUBMITTED` and will fail its eventual decision with `ERR_INSUFFICIENT_RINS`."

        Design: Corner/endpoints/batch_decide_fails_when_lot_expired_pending
        """
        _lot, batch = self._setup(api, "EPA-EP-3B")
        resp = api.decide_retirement_batch(batch["id"], {"decision": "ACCEPT"}, OPS)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_RINS)
        after = validate_success(api.get_retirement_batch(batch["id"], CM))
        assert after["status"] == "SUBMITTED"


class TestImmediateCascadeVisibility:
    def _setup(self, api, epa_id):
        acct, yr = create_account_and_year(epa_registration_id=epa_id)
        lot = create_separated_lot(acct["id"], d_code="D6", vintage_year=2026,
                                   gallon_qty=100)
        batch = create_batch(yr["id"], category="TOTAL_RENEWABLE", d_code="D6",
                             rin_qty=100)
        submit_batch(batch["id"])
        return yr, lot, batch

    def test_decide_response_and_reads_show_cascade_immediately(self, api):
        """PRD §3.5: "On acceptance each allocated lot's pending quantity converts into `retired_qty`; a lot whose available balance thereby reaches zero becomes `EXHAUSTED` and leaves all further separation and allocation. The year's counters are then re-derived per the nested mapping"

        Design: Corner/consistency_model/immediate_visibility_of_cascade_in_same_request
        """
        yr, lot, batch = self._setup(api, "EPA-CON-1")
        data = get_success_data(
            api.decide_retirement_batch(batch["id"], {"decision": "ACCEPT"}, OPS),
        )
        assert data["status"] == "ACCEPTED"
        yr_after = validate_success(api.get_obligation_year(yr["id"], CM))
        assert yr_after["retired_total_rins"] == 100

    def test_lot_exhausted_immediately_after_accept(self, api):
        """PRD §3.5: "a lot whose available balance thereby reaches zero becomes `EXHAUSTED`"

        Design: Corner/consistency_model/immediate_visibility_of_cascade_in_same_request
        """
        _yr, lot, batch = self._setup(api, "EPA-CON-1B")
        get_success_data(
            api.decide_retirement_batch(batch["id"], {"decision": "ACCEPT"}, OPS),
        )
        lot_after = validate_success(api.get_rin_lot(lot["id"], CM))
        assert lot_after["status"] == "EXHAUSTED"
        assert lot_after["retired_qty"] == 100
