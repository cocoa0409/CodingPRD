"""Lease settlement statements: dual settlement bases, usage measurement,
overage tiers, segregation of duties, amendment floor, and OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_lease,
    assert_aum,
    assert_lease_statement,
    assert_money,
    complete_assignment,
    create_and_activate_lease,
    create_assignment,
    create_herd_group,
    create_lease,
    create_lease_statement,
    create_pasture,
    create_ranch,
    get_success_data,
    issue_statement,
    make_ranch_manager_headers,
    set_clock,
    setup_issued_statement,
    validate_error,
    validate_success,
)

RANCH_MGR = TEST_USERS["ranch_manager_headers"]
RANGE_MGR = TEST_USERS["range_manager_headers"]

LEASE_TERMS = dict(rate_per_aum_cents=2500, minimum_commit_aum=300,
                   overage_tier1_cap_aum=75, overage_tier1_rate_cents=3000,
                   overage_tier2_rate_cents=3750)


def _setup_two_bases(api):
    """One pasture, two identically-termed ACTIVE leases differing only in
    settlement basis, plus a completed 400.0-AUM assignment."""
    ranch = create_ranch(name="DV Ranch", hq_state="MT")
    pasture = create_pasture(ranch["id"], name="Section 12", acreage=3000,
                             tenure="LEASED", base_capacity_aum=1000)
    lease_a = create_and_activate_lease(
        ranch["id"], pasture["id"], lessor_name="Bureau of Land Mgmt",
        aum_allotment=500, settlement_basis="ALLOTMENT", **LEASE_TERMS)
    lease_b = create_and_activate_lease(
        ranch["id"], pasture["id"], lessor_name="Bureau of Land Mgmt",
        aum_allotment=500, settlement_basis="ACTUAL_USE", **LEASE_TERMS)
    group = create_herd_group(ranch["id"], group_name="Cows", head_count=200,
                              avg_weight_lbs=1000)
    asg = create_assignment(pasture["id"], group["id"], ranch["id"],
                            start_date="2026-03-01", planned_end_date="2026-04-30")
    set_clock("2026-05-01T00:00:00Z")
    complete_assignment(asg["id"], "2026-04-30")  # 60 days -> 400.0 AUM
    return ranch, pasture, lease_a, lease_b


class TestSettlementBasisVariants:
    def test_allotment_bills_full_allotment_regardless_of_usage(self, api):
        """PRD §3.2: "Under the `ALLOTMENT` basis the `base_charge_cents` is the
        full take-or-pay amount — the `aum_allotment` multiplied by
        `rate_per_aum_cents` — regardless of how little was actually grazed."
        PRD §3.2: "The `total_due_cents` is the base charge plus the overage
        charge."

        Design: Difficulty/dual_variant_calc/lease_settlement_allotment_vs_actual_use
        """
        ranch, _p, lease_a, _lb = _setup_two_bases(api)
        stmt = validate_success(api.create_lease_statement(
            {"lease_id": lease_a["id"], "ranch_id": ranch["id"],
             "period_year": 2026}, RANGE_MGR), 201)
        assert_lease_statement(stmt)
        assert_aum(stmt["actual_aum_used"], 400.0, "measured usage")
        assert_money(stmt["base_charge_cents"], 1250000.0,
                     "500 allotment x 2500c, usage ignored")
        assert_money(stmt["overage_charge_cents"], 0.0, "usage below allotment")
        assert_money(stmt["total_due_cents"], 1250000.0)

    def test_actual_use_bills_measured_usage_above_floor(self, api):
        """PRD §3.2: "Under the `ACTUAL_USE` basis the `base_charge_cents` is
        the greater of `actual_aum_used` and the `minimum_commit_aum` floor,
        multiplied by `rate_per_aum_cents` and rounded half-up to 2 decimal
        places; identical usage below the allotment therefore yields a lower
        total under `ACTUAL_USE` than under `ALLOTMENT`."

        Design: Difficulty/dual_variant_calc/lease_settlement_allotment_vs_actual_use
        """
        ranch, _p, lease_a, lease_b = _setup_two_bases(api)
        stmt_b = validate_success(api.create_lease_statement(
            {"lease_id": lease_b["id"], "ranch_id": ranch["id"],
             "period_year": 2026}, RANGE_MGR), 201)
        assert_lease_statement(stmt_b)
        assert_aum(stmt_b["actual_aum_used"], 400.0, "same pasture, same usage")
        assert_money(stmt_b["base_charge_cents"], 1000000.0,
                     "max(400.0, 300) x 2500c")
        assert_money(stmt_b["total_due_cents"], 1000000.0)
        # Identical usage, different basis, different money.
        stmt_a = validate_success(api.create_lease_statement(
            {"lease_id": lease_a["id"], "ranch_id": ranch["id"],
             "period_year": 2026}, RANGE_MGR), 201)
        assert stmt_a["total_due_cents"] > stmt_b["total_due_cents"]


class TestStatementSegregation:
    def test_recorder_cannot_approve_own_statement(self, api):
        """PRD §2.10: "A lease statement is born with `recorded_by_user_id`
        stamped from the `RangeManager` who generated it; approval requires a
        `RanchManager` whose `X-User-ID` is different from that recorder, and
        the approval stamps `approved_by_user_id`."
        PRD §2.10: "Either comparison failing rejects the request with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/segregation_vs_terminal_state_auth_wins
        """
        ctx = setup_issued_statement(recorder_user_id="u-range-1")
        stmt = ctx["statement"]
        assert stmt["statement_status"] == "ISSUED"
        assert stmt["recorded_by_user_id"] == "u-range-1"

        resp = api.approve_statement(
            stmt["id"], make_ranch_manager_headers("u-range-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)
        after = get_success_data(api.get_lease_statement(stmt["id"], RANGE_MGR))
        assert after["statement_status"] == "ISSUED"

        approved = validate_success(api.approve_statement(
            stmt["id"], make_ranch_manager_headers("u-ranch-1")))
        assert approved["statement_status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "u-ranch-1"

    def test_segregation_preempts_state_on_approved_statement(self, api):
        """PRD §2.8: "Every request is validated against an ordered cascade, and
        the first failing check determines the returned error — later checks are
        never evaluated once an earlier one has failed."
        PRD §2.8: "3. Segregation-of-duties comparisons, where the endpoint
        defines one (`ERR_SEGREGATION_OF_DUTIES`)."
        PRD §2.8: "7. Terminal-state rejection: a resource that has reached a
        terminal state refuses all further transitions (`ERR_ALREADY_TERMINAL`)."

        Design: Difficulty/priority_pair_validation_conflict/segregation_vs_terminal_state_auth_wins
        """
        ctx = setup_issued_statement(recorder_user_id="u-range-1")
        stmt = ctx["statement"]
        validate_success(api.approve_statement(
            stmt["id"], make_ranch_manager_headers("u-ranch-1")))
        # On the now-APPROVED statement the recorder's retry violates the
        # segregation rule at cascade step 3, before any state check can fire.
        resp = api.approve_statement(
            stmt["id"], make_ranch_manager_headers("u-range-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)


class TestUsageMeasurement:
    def test_statement_usage_counts_only_ended_assignments(self, api):
        """PRD §3.2: "Every grazing assignment on the lease's pasture that ended
        `COMPLETED` or `SHORTENED` contributes: the overlap in days between the
        assignment's actual grazing window — from its `start_date` up to but not
        including its `actual_end_date` — and the measurement window is
        multiplied by that assignment's `daily_demand_aum`, each contribution
        rounded half-up to 2 decimal places, and the contributions are summed
        and rounded half-up to 2 decimal places. Assignments still `ACTIVE` and
        assignments that were `CANCELLED` are excluded from the measurement
        entirely."

        Design: Corner/calculations/statement_usage_input_set_filtering
        """
        ranch = create_ranch(name="R")
        set_clock("2026-04-01T00:00:00Z")
        pasture = create_pasture(ranch["id"], name="P", acreage=2400,
                                 tenure="LEASED", base_capacity_aum=600,
                                 min_rest_days=45)
        lease = create_and_activate_lease(
            ranch["id"], pasture["id"], aum_allotment=500, minimum_commit_aum=10,
            overage_tier1_cap_aum=75)
        group = create_herd_group(ranch["id"], group_name="G", head_count=20,
                                  avg_weight_lbs=1000)
        a1 = create_assignment(pasture["id"], group["id"], ranch["id"],
                               start_date="2026-05-01",
                               planned_end_date="2026-05-31")
        create_assignment(pasture["id"], group["id"], ranch["id"],
                          start_date="2026-07-16", planned_end_date="2026-08-15")
        a3 = create_assignment(pasture["id"], group["id"], ranch["id"],
                               start_date="2026-10-01",
                               planned_end_date="2026-10-31")
        from test_helpers import cancel_assignment
        cancel_assignment(a3["id"])
        set_clock("2026-05-21T00:00:00Z")
        complete_assignment(a1["id"], "2026-05-21")  # 20 days -> 13.33 AUM

        stmt = create_lease_statement(lease["id"], ranch["id"], 2026)
        assert_aum(stmt["actual_aum_used"], 13.33,
                   "only the ended assignment counts")
        assert_money(stmt["base_charge_cents"], 33325.0, "max(13.33, 10) x 2500")
        assert_money(stmt["overage_charge_cents"], 0.0)
        assert_money(stmt["total_due_cents"], 33325.0)


class TestOverageTiers:
    def test_overage_exactly_at_tier1_cap_bills_entirely_at_tier1(self, api):
        """PRD §3.2: "The `overage_charge_cents` bills the portion of that
        overage up to `overage_tier1_cap_aum` at `overage_tier1_rate_cents`, and
        any remaining overage beyond the tier-1 cap at `overage_tier2_rate_cents`,
        the sum rounded half-up to 2 decimal places."
        PRD §3.2: "Under the `ACTUAL_USE` basis the `base_charge_cents` is the
        greater of `actual_aum_used` and the `minimum_commit_aum` floor,
        multiplied by `rate_per_aum_cents` and rounded half-up to 2 decimal
        places"

        Design: Corner/calculations/lease_overage_tier_boundary
        """
        ranch = create_ranch(name="R")
        pasture = create_pasture(ranch["id"], name="P", acreage=2400,
                                 tenure="LEASED", base_capacity_aum=600,
                                 min_rest_days=45)
        lease = create_and_activate_lease(
            ranch["id"], pasture["id"], aum_allotment=500, **LEASE_TERMS)
        group = create_herd_group(ranch["id"], group_name="G", head_count=50,
                                  avg_weight_lbs=1000)
        asg = create_assignment(pasture["id"], group["id"], ranch["id"],
                                start_date="2026-01-01",
                                planned_end_date="2026-12-12")
        set_clock("2026-12-12T00:00:00Z")
        complete_assignment(asg["id"], "2026-12-12")  # 345 days -> 575.0 AUM

        stmt = create_lease_statement(lease["id"], ranch["id"], 2026)
        assert_aum(stmt["actual_aum_used"], 575.0)
        # Overage 75.0 == tier1 cap 75: entirely tier-1 priced, tier-2 untouched.
        assert_money(stmt["overage_charge_cents"], 225000.0, "75 x 3000c")
        assert_money(stmt["base_charge_cents"], 1437500.0, "max(575, 300) x 2500")
        assert_money(stmt["total_due_cents"], 1662500.0)


class TestStatementUniqueness:
    def test_duplicate_statement_period_rejected(self, api):
        """PRD §3.2: "One statement may exist per lease per calendar year; a
        second attempt for the same pairing fails with
        `ERR_DUPLICATE_STATEMENT_PERIOD` (HTTP 409)."
        PRD §3.2: "a `period_year` that must fall within the calendar years
        spanned by the lease — from the year of its `start_date` through the
        year of its `end_date` inclusive"

        Design: Corner/validations/duplicate_statement_period_rejected
        """
        ranch = create_ranch(name="R")
        pasture = create_pasture(ranch["id"], name="P", acreage=1600,
                                 tenure="LEASED", base_capacity_aum=500)
        lease = create_and_activate_lease(
            ranch["id"], pasture["id"], aum_allotment=500,
            start_date="2026-01-01", end_date="2027-12-31")
        first = create_lease_statement(lease["id"], ranch["id"], 2026)
        assert first["statement_status"] == "DRAFT"

        resp = api.create_lease_statement(
            {"lease_id": lease["id"], "ranch_id": ranch["id"],
             "period_year": 2026}, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATEMENT_PERIOD,
                       expected_status=409)

        second = create_lease_statement(lease["id"], ranch["id"], 2027)
        assert second["period_year"] == 2027, "uniqueness is per (lease, year)"


class TestAmendmentFloor:
    def test_allotment_below_recorded_usage_rejected(self, api):
        """PRD §3.2: "the new `aum_allotment` may not fall below the largest
        `actual_aum_used` recorded on any non-draft statement of the lease, or
        the amendment is rejected with `ERR_ALLOTMENT_BELOW_RECORDED_USAGE`
        (HTTP 422)."

        Design: Corner/validations/allotment_below_recorded_usage_rejected
        """
        ranch = create_ranch(name="R")
        pasture = create_pasture(ranch["id"], name="P", acreage=2400,
                                 tenure="LEASED", base_capacity_aum=600,
                                 min_rest_days=45)
        lease = create_lease(ranch["id"], pasture["id"], aum_allotment=100,
                             minimum_commit_aum=10, overage_tier1_cap_aum=75)
        lease = activate_lease(lease["id"])
        group = create_herd_group(ranch["id"], group_name="G", head_count=20,
                                  avg_weight_lbs=1000)
        asg = create_assignment(pasture["id"], group["id"], ranch["id"],
                                start_date="2026-05-01",
                                planned_end_date="2026-05-31")
        complete_assignment(asg["id"], "2026-05-21")  # usage 13.33
        stmt = create_lease_statement(lease["id"], ranch["id"], 2026)
        assert_aum(stmt["actual_aum_used"], 13.33)
        issue_statement(stmt["id"])  # non-DRAFT statement anchors the floor

        resp = api.patch_lease(
            lease["id"], {"expected_lease_version": lease["version"],
                          "aum_allotment": 10}, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_ALLOTMENT_BELOW_RECORDED_USAGE,
                       expected_status=422)

        amended = validate_success(api.patch_lease(
            lease["id"], {"expected_lease_version": lease["version"],
                          "aum_allotment": 14}, RANGE_MGR))
        assert amended["aum_allotment"] == 14, "14 >= 13.33 recorded usage"
        assert amended["version"] == lease["version"] + 1, (
            "the rejected PATCH left the version untouched"
        )


class TestLeaseAmendOcc:
    def test_occ_lease_amend_stale_version_rejected(self, api):
        """PRD §2.7: "Amending the terms of a grazing lease requires the request
        to carry `expected_lease_version`, holding the `version` of the lease
        the client last observed."
        PRD §2.7: "When the supplied expectation does not equal the parent
        resource's current `version` — because another write has advanced that
        version since the client last read it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_lease_amend_stale_version_rejected
        """
        ranch = create_ranch(name="R")
        pasture = create_pasture(ranch["id"], name="P", acreage=1600,
                                 tenure="LEASED", base_capacity_aum=500)
        lease = create_lease(ranch["id"], pasture["id"], aum_allotment=100,
                             minimum_commit_aum=10, overage_tier1_cap_aum=10)
        stale_version = lease["version"]
        active = activate_lease(lease["id"])
        assert active["version"] == stale_version + 1

        resp = api.patch_lease(
            lease["id"], {"expected_lease_version": stale_version,
                          "rate_per_aum_cents": 2600}, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        amended = validate_success(api.patch_lease(
            lease["id"], {"expected_lease_version": active["version"],
                          "rate_per_aum_cents": 2600}, RANGE_MGR))
        assert amended["rate_per_aum_cents"] == 2600
        assert amended["version"] == active["version"] + 1
