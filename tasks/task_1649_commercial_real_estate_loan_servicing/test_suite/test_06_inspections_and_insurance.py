"""Inspector scheduling windows, inspection completion cascades, insurance
coverage windows, force-placed policies, and protective-advance reversal."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    cancel_inspection,
    complete_inspection,
    create_borrower,
    create_inspector,
    create_insurance_policy_payload,
    create_loan,
    create_property,
    create_reserve_account,
    force_place_insurance,
    get_loan,
    get_reserve,
    get_success_data,
    make_borrower_headers,
    newest_assessment,
    post_policy,
    schedule_inspection,
    schedule_inspection_payload,
    set_clock,
    setup_watchlist_via_poor_inspection,
    single_watchlist_entry,
    validate_error,
    validate_paginated,
    validate_success,
)

MS = TEST_USERS["master_servicer_headers"]
SS = TEST_USERS["special_servicer_headers"]


class TestInspectorScheduling:
    def _workspace(self, tax_id, loan_number):
        borrower = create_borrower(legal_name=f"{loan_number} Co", tax_id=tax_id,
                                   contact_email=f"{tax_id.lower()}@x.com")
        loan = create_loan(borrower["id"], loan_number=loan_number)
        prop = create_property(loan["id"], address=f"1 {loan_number} St",
                               property_type="RETAIL")
        inspector = create_inspector(full_name="Otto Verlap",
                                     license_no=f"LIC-{tax_id}")
        return borrower, loan, prop, inspector

    def test_adjacent_inspection_windows_permitted(self, api):
        """PRD §3.5: "Conflicts are evaluated per inspector across that
        inspector's `SCHEDULED` inspections under half-open semantics:
        back-to-back assignments, one beginning exactly when another ends, are
        permitted, while any true overlap is rejected with
        `ERR_INSPECTOR_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_adjacency
        """
        _b, _l, prop, inspector = self._workspace("TX-OV1", "LN-OV1")
        schedule_inspection(prop["id"], inspector["id"],
                            scheduled_start="2026-08-03T09:00:00Z",
                            scheduled_end="2026-08-03T11:00:00Z")
        # Half-open [09:00, 11:00) then [11:00, 13:00): adjacency is permitted.
        adjacent = api.schedule_inspection(
            prop["id"],
            schedule_inspection_payload(
                inspector["id"], scheduled_start="2026-08-03T11:00:00Z",
                scheduled_end="2026-08-03T13:00:00Z"), MS)
        validate_success(adjacent, 201)
        # [10:30, 12:00) truly overlaps both existing windows.
        conflict = api.schedule_inspection(
            prop["id"],
            schedule_inspection_payload(
                inspector["id"], scheduled_start="2026-08-03T10:30:00Z",
                scheduled_end="2026-08-03T12:00:00Z"), MS)
        validate_error(conflict, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT)

    def test_cancelled_inspection_frees_its_window(self, api):
        """PRD §3.5: "Conflicts are evaluated per inspector across that
        inspector's `SCHEDULED` inspections under half-open semantics"
        PRD §3.5: "A `MasterServicer` instead closes with outcome `CANCELLED`."

        Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_adjacency
        """
        _b, _l, prop, inspector = self._workspace("TX-OV1B", "LN-OV1B")
        first = schedule_inspection(prop["id"], inspector["id"],
                                    scheduled_start="2026-08-03T09:00:00Z",
                                    scheduled_end="2026-08-03T11:00:00Z")
        cancel_inspection(first["id"])
        # The CANCELLED inspection no longer participates in the conflict check.
        rebooked = api.schedule_inspection(
            prop["id"],
            schedule_inspection_payload(
                inspector["id"], scheduled_start="2026-08-03T09:30:00Z",
                scheduled_end="2026-08-03T10:30:00Z"), MS)
        validate_success(rebooked, 201)


class TestPoorInspectionCascade:
    def test_poor_inspection_creates_watchlist_entry(self, api):
        """PRD §3.5: "A completion rated `POOR` or `CRITICAL` immediately creates
        a watchlist entry with criterion `POOR_INSPECTION` whose `source_ref`
        points at the inspection"
        PRD §3.6: "a human-readable `source_ref` pointing at the origin (a
        period-and-type label such as 'period 2026Q2 OPERATING_STATEMENT' for
        reporting gaps, or an inspection id for condition findings)"

        Design: Difficulty/transitive_cascade/inspection_poor_creates_entry_watchlists_loan
        """
        ctx = setup_watchlist_via_poor_inspection(tax_id="TX-CAS2", rating="POOR")
        entry = ctx["entry"]
        assert entry["criterion"] == "POOR_INSPECTION"
        assert entry["status"] == "ACTIVE"
        assert entry["source_ref"] == ctx["inspection"]["id"], (
            "the entry's source_ref points at the originating inspection")

    def test_poor_inspection_lifts_loan_and_elevates_reserve(self, api):
        """PRD §3.5: "A completion rated `POOR` or `CRITICAL` immediately creates
        a watchlist entry with criterion `POOR_INSPECTION` whose `source_ref`
        points at the inspection, which re-evaluates the loan's servicing posture
        — potentially pushing a `PERFORMING` loan to `WATCHLIST` and elevating
        retainage on its reserves"

        Design: Difficulty/transitive_cascade/inspection_poor_creates_entry_watchlists_loan
        """
        ctx = setup_watchlist_via_poor_inspection(tax_id="TX-CAS2B", rating="POOR")
        assert get_loan(ctx["loan"]["id"])["servicing_status"] == "WATCHLIST", (
            "the ACTIVE entry lifts the loan to WATCHLIST")
        reserve = get_reserve(ctx["reserve"]["id"])
        assert reserve["elevated_retainage"] is True


class TestInsuranceCoverageWindows:
    def _workspace(self, tax_id, loan_number, balance=400_000_000):
        borrower = create_borrower(legal_name=f"{loan_number} Co", tax_id=tax_id,
                                   contact_email=f"{tax_id.lower()}@x.com")
        loan = create_loan(borrower["id"], loan_number=loan_number,
                           original_principal_cents=balance,
                           note_rate=0.06 if balance != 100_000_000 else 0.05)
        prop = create_property(loan["id"], address=f"1 {loan_number} St",
                               property_type="INDUSTRIAL",
                               appraised_value_cents=1_000_000_000)
        return borrower, loan, prop

    def test_touching_coverage_dates_overlap_but_next_day_adjacent(self, api):
        """PRD §3.5: "Referentially, the new policy's closed interval may not
        touch or overlap the interval of any other `ACTIVE`, non-force-placed
        policy of the same coverage type on the same property — touching dates
        count as overlap — else `ERR_COVERAGE_WINDOW_OVERLAP`; force-placed
        policies never participate in that check, so they can never block a
        borrower's replacement coverage."

        Design: Difficulty/resource_temporal_overlap/insurance_closed_interval_touching_overlap
        """
        borrower, _loan, prop = self._workspace("TX-OV2", "LN-OV2")
        post_policy(prop["id"], borrower["id"], 400_000_000,
                    start_date="2026-01-01T00:00:00Z",
                    end_date="2026-12-31T00:00:00Z")
        # Closed intervals: a policy starting 2026-12-31 shares that date.
        touching = api.create_insurance_policy(
            prop["id"],
            create_insurance_policy_payload(
                400_000_000, start_date="2026-12-31T00:00:00Z",
                end_date="2027-12-31T00:00:00Z"),
            make_borrower_headers(borrower["id"]))
        validate_error(touching, ApiErrorId.ERR_COVERAGE_WINDOW_OVERLAP)
        # Next-day adjacency is disjoint under date semantics.
        adjacent = api.create_insurance_policy(
            prop["id"],
            create_insurance_policy_payload(
                400_000_000, start_date="2027-01-01T00:00:00Z",
                end_date="2027-12-31T00:00:00Z"),
            make_borrower_headers(borrower["id"]))
        validate_success(adjacent, 201)

    def test_overlap_scope_is_per_coverage_type(self, api):
        """PRD §3.5: "the new policy's closed interval may not touch or overlap
        the interval of any other `ACTIVE`, non-force-placed policy of the same
        coverage type on the same property"
        PRD §3.5: "Fiscally, a `PROPERTY` policy's coverage must be at least the
        loan's `current_balance_cents`, else `ERR_COVERAGE_BELOW_MINIMUM`
        (HTTP 422)." (the minimum applies to PROPERTY policies only)

        Design: Difficulty/resource_temporal_overlap/insurance_closed_interval_touching_overlap
        """
        borrower, _loan, prop = self._workspace("TX-OV2B", "LN-OV2B")
        post_policy(prop["id"], borrower["id"], 400_000_000,
                    start_date="2026-01-01T00:00:00Z",
                    end_date="2026-12-31T00:00:00Z")
        liability = api.create_insurance_policy(
            prop["id"],
            create_insurance_policy_payload(
                100_000_000, coverage_type="LIABILITY",
                start_date="2026-06-01T00:00:00Z",
                end_date="2026-12-31T00:00:00Z"),
            make_borrower_headers(borrower["id"]))
        policy = validate_success(liability, 201)
        assert policy["status"] == "ACTIVE", (
            "a LIABILITY policy over the same dates does not conflict with PROPERTY")


class TestInsuranceFiscalGuards:
    def test_property_coverage_below_balance_rejected(self, api):
        """PRD §3.5: "Fiscally, a `PROPERTY` policy's coverage must be at least
        the loan's `current_balance_cents`, else `ERR_COVERAGE_BELOW_MINIMUM`
        (HTTP 422)."

        Design: Corner/validations/property_coverage_below_balance_rejected
        """
        borrower, _loan, prop = TestInsuranceCoverageWindows._workspace(
            self, "TX-MIN", "LN-MIN")
        low = api.create_insurance_policy(
            prop["id"],
            create_insurance_policy_payload(
                399_999_999, start_date="2026-08-01T00:00:00Z",
                end_date="2027-07-31T00:00:00Z"),
            make_borrower_headers(borrower["id"]))
        validate_error(low, ApiErrorId.ERR_COVERAGE_BELOW_MINIMUM)
        # Exactly equal to the balance passes: the minimum is inclusive.
        exact = api.create_insurance_policy(
            prop["id"],
            create_insurance_policy_payload(
                400_000_000, start_date="2026-08-01T00:00:00Z",
                end_date="2027-07-31T00:00:00Z"),
            make_borrower_headers(borrower["id"]))
        assert validate_success(exact, 201)["status"] == "ACTIVE"


class TestForcePlacement:
    def test_force_place_with_active_coverage_rejected(self, api):
        """PRD §3.5: "Force-placement is refused while any `ACTIVE`,
        non-force-placed policy of that coverage type already covers the property
        at the current moment — `ERR_FORCE_PLACEMENT_NOT_NEEDED`."

        Design: Corner/validations/force_place_with_active_coverage_rejected
        """
        borrower, loan, prop = TestInsuranceCoverageWindows._workspace(
            self, "TX-FPN", "LN-FPN")
        post_policy(prop["id"], borrower["id"], 400_000_000,
                    start_date="2026-01-01T00:00:00Z",
                    end_date="2026-12-31T00:00:00Z")
        resp = api.force_place_insurance(prop["id"], "PROPERTY", SS)
        validate_error(resp, ApiErrorId.ERR_FORCE_PLACEMENT_NOT_NEEDED)
        assert get_loan(loan["id"])["current_balance_cents"] == 400_000_000, (
            "a refused force-placement capitalizes nothing")

    def test_force_place_capitalizes_premium_single_pass(self, api):
        """PRD §3.5: "The protective advance is then capitalized in a single
        pinned pass, its order fixed to break the apparent circularity between
        premium and balance: first the loan's current balance is snapshotted;
        second, the premium is computed as that snapshot multiplied by two percent
        (0.02), rounded half-up to whole cents; third, the loan's
        `current_balance_cents` grows by the premium; fourth, the same premium
        accumulates into `capitalized_advances_cents`; fifth, the new policy's
        `coverage_amount_cents` is set to the pre-placement snapshot — not the
        grown balance — and its `premium_advance_cents` records the premium."
        PRD §3.5: "The policy is flagged `force_placed` and written for a term of
        365 days from placement."

        Design: Difficulty/combinatorial_formula/force_place_premium_evaluation_order
        """
        borrower = create_borrower(legal_name="Advance Corp", tax_id="TX-ADV-1",
                                   contact_email="adv@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-ADV",
                           original_principal_cents=500_000_000, note_rate=0.05,
                           ltv_covenant_threshold=0.75)
        prop = create_property(loan["id"], address="5 Advance Blvd",
                               property_type="INDUSTRIAL",
                               appraised_value_cents=800_000_000,
                               appraisal_date="2026-05-01T00:00:00Z")
        policy = force_place_insurance(prop["id"], "PROPERTY")
        assert policy["force_placed"] is True
        # 2% of the PRE-advance 500,000,000 snapshot: a single pass, no iteration.
        assert policy["premium_advance_cents"] == 10_000_000
        assert policy["coverage_amount_cents"] == 500_000_000, (
            "coverage is the pre-placement snapshot, not the grown balance")
        assert policy["start_date"].startswith("2026-08-01")
        assert policy["end_date"].startswith("2027-08-01"), (
            "the term is 365 days from placement at the 2026-08-01 clock")
        assert policy["status"] == "ACTIVE"

    def test_force_place_recomputes_balance_and_ltv_once(self, api):
        """PRD §3.5: "third, the loan's `current_balance_cents` grows by the
        premium; fourth, the same premium accumulates into
        `capitalized_advances_cents`"
        PRD §3.5: "Exactly one LTV recomputation follows, which may open an LTV
        breach, with the servicing posture and the risk score re-evaluated behind
        it."

        Design: Difficulty/combinatorial_formula/force_place_premium_evaluation_order
        """
        borrower = create_borrower(legal_name="Advance Corp 2", tax_id="TX-ADV-2",
                                   contact_email="adv2@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-ADV2",
                           original_principal_cents=500_000_000, note_rate=0.05,
                           ltv_covenant_threshold=0.75)
        prop = create_property(loan["id"], address="7 Advance Blvd",
                               property_type="INDUSTRIAL",
                               appraised_value_cents=800_000_000,
                               appraisal_date="2026-05-01T00:00:00Z")
        force_place_insurance(prop["id"], "PROPERTY")
        loan_after = get_loan(loan["id"])
        assert loan_after["current_balance_cents"] == 510_000_000
        assert loan_after["capitalized_advances_cents"] == 10_000_000
        # 510,000,000 / 800,000,000 = 0.6375 <= 0.75: conforming, no breach.
        assert loan_after["current_ltv"] == pytest.approx(0.6375, abs=1e-9)
        assessment = newest_assessment(loan["id"], params={"assessment_type": "LTV"})
        assert assessment["computed_value"] == pytest.approx(0.6375, abs=1e-9)
        assert assessment["breach"] is False
        assert assessment["status"] == "CONFORMING"

    def test_force_placed_cancel_without_replacement_rejected(self, api):
        """PRD §3.5: "A force-placed policy carries one further protection: it
        cannot be cancelled until another `ACTIVE`, non-force-placed policy of the
        same coverage type exists whose `start_date` is on or before the
        force-placed policy's own start date, otherwise
        `ERR_FORCE_PLACED_CANCEL_BLOCKED`."
        PRD §3.5: "Cancelling a force-placed policy reverses its protective
        advance exactly once" (a blocked cancellation reverses nothing).

        Design: Corner/validations/force_placed_cancel_without_replacement_rejected
        """
        borrower = create_borrower(legal_name="FPC Co", tax_id="TX-FPC",
                                   contact_email="fpc@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-FPC",
                           original_principal_cents=500_000_000, note_rate=0.05,
                           ltv_covenant_threshold=0.90)
        prop = create_property(loan["id"], address="1 Fpc St",
                               appraised_value_cents=1_000_000_000,
                               appraisal_date="2026-05-01T00:00:00Z")
        policy = force_place_insurance(prop["id"], "PROPERTY")
        resp = api.cancel_insurance_policy(policy["id"], SS)
        validate_error(resp, ApiErrorId.ERR_FORCE_PLACED_CANCEL_BLOCKED)
        loan_after = get_loan(loan["id"])
        assert loan_after["current_balance_cents"] == 510_000_000, (
            "the advance is NOT reversed on a blocked cancel")
        rows, _meta = validate_paginated(
            api.list_insurance_policies(prop["id"], MS))
        assert rows[0]["status"] == "ACTIVE"


class TestForcePlaceCancelInvariant:
    def _setup_force_placed(self, tax_id, loan_number):
        borrower = create_borrower(legal_name=f"{loan_number} Co", tax_id=tax_id,
                                   contact_email=f"{tax_id.lower()}@x.com")
        loan = create_loan(borrower["id"], loan_number=loan_number,
                           original_principal_cents=500_000_000, note_rate=0.05,
                           ltv_covenant_threshold=0.75)
        prop = create_property(loan["id"], address=f"1 {loan_number} Ct",
                               property_type="MULTIFAMILY",
                               appraised_value_cents=800_000_000,
                               appraisal_date="2026-05-01T00:00:00Z")
        policy = force_place_insurance(prop["id"], "PROPERTY")
        return borrower, loan, prop, policy

    def test_force_placed_policy_cancellable_with_replacement_coverage(self, api):
        """PRD §3.5: "force-placed policies never participate in that check, so
        they can never block a borrower's replacement coverage."
        PRD §3.5: "it cannot be cancelled until another `ACTIVE`, non-force-placed
        policy of the same coverage type exists whose `start_date` is on or before
        the force-placed policy's own start date, otherwise
        `ERR_FORCE_PLACED_CANCEL_BLOCKED`."

        Design: Difficulty/compensating_invariant/force_place_then_cancel_conserves_loan_balance
        """
        borrower, _loan, prop, policy = self._setup_force_placed(
            "TX-IV2", "LN-IV2")
        # The replacement posts 201 despite overlapping the force-placed window:
        # force-placed policies never block borrower replacements.
        replacement = post_policy(prop["id"], borrower["id"], 510_000_000,
                                  start_date="2026-08-01T00:00:00Z",
                                  end_date="2027-07-31T00:00:00Z")
        assert replacement["status"] == "ACTIVE"
        assert replacement["force_placed"] is False
        # Replacement start (2026-08-01) is on the force-placed start date.
        cancelled = validate_success(api.cancel_insurance_policy(policy["id"], SS))
        assert cancelled["status"] == "CANCELLED"

    def test_cancel_reverses_advance_conserving_balance(self, api):
        """PRD §3.5: "Cancelling a force-placed policy reverses its protective
        advance exactly once — the loan's `current_balance_cents` and
        `capitalized_advances_cents` each decrease by the recorded
        `premium_advance_cents`, the premium never being recomputed at
        cancellation — and advances the loan's `version`. Any cancellation then
        recomputes LTV: a conforming result auto-cures the loan's `OPEN` LTV
        assessments, and the servicing posture is re-evaluated."

        Design: Difficulty/compensating_invariant/force_place_then_cancel_conserves_loan_balance
        """
        borrower, loan, prop, policy = self._setup_force_placed(
            "TX-IV2B", "LN-IV2B")
        mid = get_loan(loan["id"])
        assert mid["current_balance_cents"] == 510_000_000
        assert mid["capitalized_advances_cents"] == 10_000_000

        post_policy(prop["id"], borrower["id"], 510_000_000,
                    start_date="2026-08-01T00:00:00Z",
                    end_date="2027-07-31T00:00:00Z")
        validate_success(api.cancel_insurance_policy(policy["id"], SS))

        after = get_loan(loan["id"])
        assert after["current_balance_cents"] == 500_000_000, (
            "forward advance + compensating reversal conserve the loan balance")
        assert after["capitalized_advances_cents"] == 0
        # LTV recomputed once on the reversal: 500,000,000 / 800,000,000.
        assert after["current_ltv"] == pytest.approx(0.6250, abs=1e-9)


class TestInsuranceSweep:
    def test_insurance_expiry_sweep_creates_lapse_entry(self, api):
        """PRD §3.5: "Posted policies are ordinary borrower coverage, with
        `force_placed` false and `premium_advance_cents` zero, and they open
        `ACTIVE`; the clock sweep moves a policy to `EXPIRED` once the clock
        passes its `end_date`, and if that expiry leaves no `ACTIVE` policy of the
        same coverage type covering the current moment, the sweep also opens a
        watchlist entry with criterion `INSURANCE_LAPSE` and re-evaluates the
        servicing posture."

        Design: Corner/state_machines/insurance_expiry_sweep_creates_lapse_entry
        """
        borrower = create_borrower(legal_name="Lapse Co", tax_id="TX-LAP",
                                   contact_email="lap@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-LAP",
                           original_principal_cents=400_000_000, note_rate=0.05,
                           origination_date="2026-08-01T00:00:00Z")
        prop = create_property(loan["id"], address="1 Lapse St")
        post_policy(prop["id"], borrower["id"], 400_000_000,
                    start_date="2026-01-01T00:00:00Z",
                    end_date="2026-07-31T00:00:00Z")

        set_clock("2026-08-02T00:00:00Z")

        rows, _meta = validate_paginated(
            api.list_insurance_policies(prop["id"], MS))
        assert rows[0]["status"] == "EXPIRED", (
            "the clock passing end_date sweeps the policy to EXPIRED")
        entry = single_watchlist_entry(loan["id"], criterion="INSURANCE_LAPSE",
                                       status="ACTIVE")
        assert entry["criterion"] == "INSURANCE_LAPSE"
        assert get_loan(loan["id"])["servicing_status"] == "WATCHLIST"
