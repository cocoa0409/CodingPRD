"""Charge schedules: OCC on creation, the two allocation variants and their
rounding residual, the approval cascade into arrears, and refinancing."""
from test_helpers import (
    ADMIN,
    OFFICER,
    ApiErrorId,
    assert_maintenance_charge,
    charge_for_month,
    create_charge_schedule_payload,
    create_cooperative,
    get_shareholder,
    list_charges,
    make_charge_past_due,
    open_resolution,
    pass_resolution,
    setup_approved_schedule,
    setup_multi_unit_approved_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestScheduleCreationOCC:
    def test_create_schedule_with_stale_cooperative_version_rejected(self, api):
        """PRD §2.8: "Creating a charge schedule, and recording the
        transfer of an approved purchase application, each require the request
        body to carry `expected_cooperative_version`, a non-optional field
        holding the cooperative's `version` as the client last observed it. If
        the cooperative's current `version` no longer matches — because another
        writer has since created units, opened a schedule, changed policy,
        recorded a transfer, or advanced the clock — the request is rejected
        with `ERR_STALE_COOP_VERSION` (HTTP 412) and nothing is written."

        Design: Corner/complexity_layers/schedule_create_occ_stale_version_rejected
        """
        coop = create_cooperative(name="OCC2")
        stale_version = coop["version"]
        # A unit creation advances the cooperative's version (PRD §2.7).
        validate_success(api.create_unit(
            coop["id"], {"unit_label": "1A", "shares_allocated": 100}, ADMIN), 201)
        resp = api.create_charge_schedule(
            coop["id"],
            create_charge_schedule_payload(
                stale_version,
                fiscal_year=2027,
                annual_operating_budget_cents=1000000,
                effective_from="2027-01-01T00:00:00Z",
                effective_to="2028-01-01T00:00:00Z"),
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_STALE_COOP_VERSION, expected_status=412)
        data, meta = validate_paginated(api.list_charge_schedules(coop["id"], OFFICER))
        assert meta["total_count"] == 0, "nothing is written on a stale-version rejection"


class TestMaintenanceAllocationVariants:
    def test_pro_rata_allocation_weights_charges_by_shares(self, api):
        """PRD §3.3: "Under `PRO_RATA_SHARES`, a unit's monthly charge is
        found by first computing the unit's annual share of the budget — the
        annual budget multiplied by the unit's `shares_allocated` and divided by
        the cooperative's `total_shares` — and then dividing that annual share
        by twelve months; only the final monthly figure is rounded, half-up to
        whole cents."

        Design: Difficulty/dual_variant_calc/maintenance_pro_rata_vs_equal_split_divergence
        """
        env = setup_multi_unit_approved_schedule(
            shares_list=(100, 200, 300),
            annual_budget_cents=120000000,
            allocation_method="PRO_RATA_SHARES")
        coop_id = env["coop"]["id"]
        unit_a, unit_b, unit_c = env["units"]
        # 120000000 * 100 / (600 * 12) = 1666666.67 -> 1666667 (round half-up)
        assert charge_for_month(coop_id, "2027-01", unit_a["id"])["base_amount_cents"] \
            == 1666667
        # 120000000 * 200 / (600 * 12) = 3333333.33 -> 3333333
        assert charge_for_month(coop_id, "2027-01", unit_b["id"])["base_amount_cents"] \
            == 3333333
        # 120000000 * 300 / (600 * 12) = 5000000 exactly
        assert charge_for_month(coop_id, "2027-01", unit_c["id"])["base_amount_cents"] \
            == 5000000

    def test_equal_split_diverges_from_pro_rata_on_identical_inputs(self, api):
        """PRD §3.3: "Under `EQUAL_SPLIT`, every unit pays the same
        monthly figure: the annual budget divided by the product of the unit
        count and twelve, rounded half-up to whole cents."
        PRD §3.3: "under `EQUAL_SPLIT` the absorber is the
        earliest-created unit."

        Design: Difficulty/dual_variant_calc/maintenance_pro_rata_vs_equal_split_divergence
        """
        env = setup_multi_unit_approved_schedule(
            shares_list=(100, 200, 300),
            annual_budget_cents=120000000,
            allocation_method="EQUAL_SPLIT")
        coop_id = env["coop"]["id"]
        unit_a, unit_b, unit_c = env["units"]
        # 120000000 / (3 * 12) = 3333333.33 -> 3333333 per unit; residual
        # 120000000 - 12 * 9999999 = 12 -> 12 / 12 = 1 absorbed by unit_a.
        assert charge_for_month(coop_id, "2027-01", unit_a["id"])["base_amount_cents"] \
            == 3333334
        assert charge_for_month(coop_id, "2027-01", unit_b["id"])["base_amount_cents"] \
            == 3333333
        assert charge_for_month(coop_id, "2027-01", unit_c["id"])["base_amount_cents"] \
            == 3333333
        # Divergence proof: identical budget and units, but pro-rata would give
        # unit_a 1666667 and unit_c 5000000 — the variants disagree.


class TestResidualReconciliation:
    def test_pro_rata_residual_absorbed_by_largest_share_unit(self, api):
        """PRD §3.3: "the residual, defined as the budget minus twelve
        times that sum, is divided by twelve, rounded half-up to whole cents,
        and added to the monthly charge of a single absorber unit. Under
        `PRO_RATA_SHARES` the absorber is the unit with the largest
        `shares_allocated`, ties broken by the earliest `created_at`; under
        `EQUAL_SPLIT` the absorber is the earliest-created unit."

        Design: Difficulty/combinatorial_formula/maintenance_pro_rata_residual_absorption
        """
        env = setup_multi_unit_approved_schedule(
            shares_list=(100, 100, 100),
            labels=("A", "B", "C"),
            annual_budget_cents=100000001,
            allocation_method="PRO_RATA_SHARES")
        coop_id = env["coop"]["id"]
        unit_a, unit_b, unit_c = env["units"]
        # Per unit: round_half_up(100000001 * 100 / (300 * 12)) = 2777778.
        # Residual = 100000001 - 12 * 8333334 = -7 -> round_half_up(-7/12) = -1,
        # absorbed by the tied-largest unit with earliest created_at (unit A).
        assert charge_for_month(coop_id, "2027-01", unit_a["id"])["base_amount_cents"] \
            == 2777777
        assert charge_for_month(coop_id, "2027-01", unit_b["id"])["base_amount_cents"] \
            == 2777778
        assert charge_for_month(coop_id, "2027-01", unit_c["id"])["base_amount_cents"] \
            == 2777778

    def test_residual_applied_once_at_approval_not_reapplied(self, api):
        """PRD §3.3: "The allocation formula runs once, at approval, and
        fixes each unit's `base_amount_cents` for every month of the schedule."
        PRD §3.3: "The residual is never re-applied at later billings."

        Design: Difficulty/combinatorial_formula/maintenance_pro_rata_residual_absorption
        """
        env = setup_multi_unit_approved_schedule(
            shares_list=(100, 100, 100),
            labels=("A", "B", "C"),
            annual_budget_cents=100000001,
            allocation_method="PRO_RATA_SHARES")
        coop_id = env["coop"]["id"]
        unit_a, unit_b, unit_c = env["units"]
        months = [f"2027-{m:02d}" for m in range(1, 13)]
        for month in months:
            assert charge_for_month(coop_id, month, unit_a["id"])["base_amount_cents"] \
                == 2777777, f"absorber base drifted in {month}"
            assert charge_for_month(coop_id, month, unit_b["id"])["base_amount_cents"] \
                == 2777778, f"unit B base drifted in {month}"
            assert charge_for_month(coop_id, month, unit_c["id"])["base_amount_cents"] \
                == 2777778, f"unit C base drifted in {month}"


class TestApprovalCascadeToArrears:
    def test_schedule_approval_generates_one_charge_per_unit_per_month(self, api):
        """PRD §3.3: "Approval of the new schedule then triggers charge
        generation: one `MaintenanceCharge` per unit per billing month within
        the window, each stamped with its `schedule_id`, a `billing_month` in
        YYYY-MM (UTC) form, and a `due_date` — typically the first of the month
        — computed per the maintenance allocation formula."
        PRD §3.3: "the schedule moves from `DRAFT` to `APPROVED`, records
        that resolution in `approving_resolution_id`, and increments the
        cooperative's `version`."

        Design: Difficulty/transitive_cascade/charge_schedule_approval_cascade_to_arrears
        """
        env = setup_approved_schedule(annual_budget_cents=12000000)
        coop_id = env["coop"]["id"]
        schedule = env["schedule"]
        assert schedule["schedule_status"] == "APPROVED", "link 1: DRAFT -> APPROVED"
        assert schedule["approving_resolution_id"] == env["schedule_resolution"]["id"]

        charges = list_charges(coop_id, schedule_id=schedule["id"])
        assert len(charges) == 12, (
            f"one charge per billing month within [2026-08, 2027-08), "
            f"got {len(charges)}")
        months = sorted(c["billing_month"] for c in charges)
        assert months == [f"2026-{m:02d}" for m in range(8, 13)] + \
                         [f"2027-{m:02d}" for m in range(1, 8)]
        august = charge_for_month(coop_id, "2026-08", env["unit"]["id"])
        # round_half_up(12000000 * 100 / (100 * 12)) = 1000000
        assert august["base_amount_cents"] == 1000000
        for charge in charges:
            assert_maintenance_charge(charge)
            assert charge["unit_id"] == env["unit"]["id"]

    def test_clock_past_grace_moves_charge_past_due_and_owner_delinquent(self, api):
        """PRD §3.4: "When the logical clock passes a charge's `due_date`
        by more than the cooperative's `arrears_grace_days` and money is still
        owed, an `ISSUED` or `PARTIALLY_PAID` charge becomes `PAST_DUE`."
        PRD §3.4: "Entering `PAST_DUE` applies exactly one flat late fee
        — `late_fee_cents` is set to the cooperative's
        `arrears_late_fee_flat_cents`, a one-time charge that never recurs — and
        sets the interest meter running."
        PRD §3.4: "When any charge attached to a unit the shareholder
        owns becomes `PAST_DUE` and the shareholder's `arrears_balance_cents` is
        positive, `standing` moves from `GOOD_STANDING` to `DELINQUENT`."

        Design: Difficulty/transitive_cascade/charge_schedule_approval_cascade_to_arrears
        """
        env = setup_approved_schedule(annual_budget_cents=12000000)
        coop_id = env["coop"]["id"]
        # Default grace is 10 days; land exactly one day past the grace window.
        charge = make_charge_past_due(coop_id, grace_days=10, days_past_grace=1)
        assert charge["charge_status"] == "PAST_DUE", "link 3a: ISSUED -> PAST_DUE"
        assert charge["late_fee_cents"] == 5000, "exactly one flat late fee"
        # One day of interest on principal (1000000 + 5000) at 600 bps / 365:
        # round_half_up(1005000 * (600 / 365) / 10000) = round_half_up(165.2) = 165
        assert charge["interest_cents"] == 165
        assert charge["outstanding_cents"] == 1000000 + 5000 + 165

        owner = get_shareholder(coop_id, env["owner"]["id"])
        assert owner["standing"] == "DELINQUENT", "link 3b: standing follows arrears"
        assert owner["arrears_balance_cents"] == 1005165


class TestRefinanceCascade:
    def test_refinance_resolution_rewrites_mortgage_rate(self, api):
        """PRD §3.2: "`APPROVE_REFINANCE` rewrites the cooperative's
        `underlying_mortgage_rate_bps` and principal from `payload_json` and
        runs the refinance payment estimator: the projected new annual payment
        is the cooperative's outstanding underlying-mortgage principal
        multiplied by the proposed new rate, rounded half-up to whole cents — a
        deliberately simple interest-only approximation — and the delta versus
        the current annual payment, computed the same way from the existing
        `underlying_mortgage_principal_cents` and `underlying_mortgage_rate_bps`,
        is persisted in `payload_json` for audit."
        PRD §3.2: "for a refinance, the proposed `rate_bps_new`".

        Design: Difficulty/transitive_cascade/refinance_resolution_cascade_to_cooperative_fields
        """
        coop = create_cooperative(name="Refi Coop",
                                  underlying_mortgage_principal_cents=100000000,
                                  underlying_mortgage_rate_bps=500)
        resolution = open_resolution(coop["id"], "APPROVE_REFINANCE", "Cooperative",
                                     coop["id"], payload_json={"rate_bps_new": 400})
        resolution = pass_resolution(coop["id"], resolution["id"])
        assert resolution["resolution_status"] == "PASSED", "link 1 trigger"
        fetched = validate_success(api.get_cooperative(coop["id"], OFFICER))
        assert fetched["underlying_mortgage_rate_bps"] == 400, (
            f"link 1: rate rewritten from payload_json, got "
            f"{fetched['underlying_mortgage_rate_bps']}")

    def test_refinance_does_not_rebudget_approved_schedule(self, api):
        """PRD §3.2: "Refinancing is forward-looking: it does not
        re-budget the current fiscal year, and every `APPROVED` charge schedule
        stays exactly in place."

        Design: Difficulty/transitive_cascade/refinance_resolution_cascade_to_cooperative_fields
        """
        env = setup_approved_schedule(
            coop_overrides={"underlying_mortgage_principal_cents": 100000000,
                            "underlying_mortgage_rate_bps": 500},
            annual_budget_cents=1200000)
        coop_id = env["coop"]["id"]
        august_before = charge_for_month(coop_id, "2026-08", env["unit"]["id"])

        resolution = open_resolution(coop_id, "APPROVE_REFINANCE", "Cooperative",
                                     coop_id, payload_json={"rate_bps_new": 400})
        resolution = pass_resolution(coop_id, resolution["id"])
        assert resolution["resolution_status"] == "PASSED"

        schedule = validate_success(
            api.get_charge_schedule(coop_id, env["schedule"]["id"], OFFICER))
        assert schedule["schedule_status"] == "APPROVED", \
            "refinance leaves APPROVED schedules in place"
        august_after = charge_for_month(coop_id, "2026-08", env["unit"]["id"])
        assert august_after["base_amount_cents"] == august_before["base_amount_cents"]
        assert august_after["id"] == august_before["id"], "no re-budget regeneration"
