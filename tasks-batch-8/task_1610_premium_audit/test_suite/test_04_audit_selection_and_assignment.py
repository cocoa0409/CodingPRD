"""Audit selection runs: tier thresholds (inclusive), run counters, work-order
genesis, and auditor-territory assignment."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_work_order,
    create_auditor,
    create_class_code,
    create_policy,
    find_work_order,
    parse_ts,
    run_selection,
    setup_selected_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["audit_manager_headers"]


def _setup_tier_boundary_book(api):
    """Four policies straddling the two inclusive selection thresholds plus a
    not-yet-expired policy."""
    cc = create_class_code()
    pol_phys = create_policy("WC-EDGE-PHYS", [cc["id"]],
                             estimated_annual_premium_cents=1000000,
                             minimum_premium_cents=100000)
    pol_vol = create_policy("WC-EDGE-VOL", [cc["id"]],
                            estimated_annual_premium_cents=999999,
                            minimum_premium_cents=100000)
    pol_exempt = create_policy("WC-EXEMPT", [cc["id"]],
                               estimated_annual_premium_cents=499999,
                               minimum_premium_cents=100000)
    pol_future = create_policy("WC-FUTURE", [cc["id"]],
                               expiration_date="2026-12-31T00:00:00Z",
                               estimated_annual_premium_cents=5000000,
                               minimum_premium_cents=100000)
    return cc, pol_phys, pol_vol, pol_exempt, pol_future


class TestSelectionTierBoundaries:
    def test_selection_run_counters_at_tier_boundaries(self, api):
        """PRD: "the system scans the book for policies that are `ACTIVE` and
        whose `expiration_date` is at or before the current logical clock."
        PRD: "The run itself is persisted with the clock time in `run_at` and
        four counters: `evaluated_count` (policies scanned), `physical_count`
        and `voluntary_count` (work orders created at each tier), and
        `exempt_count` (evaluated policies exempted)."

        Design: Difficulty/boundary_precision_check/selection_tier_premium_threshold_exact
        """
        _setup_tier_boundary_book(api)

        run = validate_success(api.run_audit_selection(MANAGER), 201)

        assert run["evaluated_count"] == 3, (
            "WC-FUTURE expires 2026-12-31, after the default clock "
            "2026-08-01, so it must not be evaluated")
        assert run["physical_count"] == 1
        assert run["voluntary_count"] == 1
        assert run["exempt_count"] == 1

    def test_selection_tier_assignment_at_inclusive_thresholds(self, api):
        """PRD: "Both thresholds are inclusive: a policy at exactly 1,000,000
        cents is physical, and one at exactly 500,000 cents — and not
        otherwise physical — is voluntary-report."
        PRD: "Everything else is exempt: no work order is created and the
        policy simply stays `ACTIVE`."

        Design: Difficulty/boundary_precision_check/selection_tier_premium_threshold_exact
        """
        _cc, pol_phys, pol_vol, pol_exempt, pol_future = \
            _setup_tier_boundary_book(api)

        run_selection()

        wo_phys = find_work_order(pol_phys["id"])
        assert wo_phys["audit_type"] == "PHYSICAL", (
            "Exactly 1,000,000 cents selects PHYSICAL (inclusive threshold)")

        wo_vol = find_work_order(pol_vol["id"])
        assert wo_vol["audit_type"] == "VOLUNTARY_REPORT", (
            "999,999 cents is below the physical threshold and at or above "
            "the voluntary threshold")

        exempt_orders, meta_ex = validate_paginated(
            api.list_work_orders(MANAGER,
                                 params={"policy_id": pol_exempt["id"]}))
        assert exempt_orders == [] and meta_ex["total_count"] == 0
        future_orders, _ = validate_paginated(
            api.list_work_orders(MANAGER,
                                 params={"policy_id": pol_future["id"]}))
        assert future_orders == []

        pol_ex_after = validate_success(api.get_policy(pol_exempt["id"],
                                                       MANAGER))
        assert pol_ex_after["status"] == "ACTIVE"


class TestWorkOrderGenesis:
    def test_work_order_created_with_policy_period_and_tier(self, api):
        """PRD: "For each selected policy the system creates an
        **AuditWorkOrder** in the `SELECTED` state, stamped with the run via
        `selection_run_id`, linked to the policy via `policy_id`, carrying an
        `audit_type` of `PHYSICAL` or `VOLUNTARY_REPORT`, with
        `reaudit_of_work_order_id` null, `assigned_auditor_id` null,
        `no_show_count` zero, and `audit_period_start` and `audit_period_end`
        copied from the policy's term dates."
        PRD: "Selecting a policy flips it from `ACTIVE` to `AUDIT_PENDING`
        and increments `Policy.version`."
        PRD: "Failing that, a policy whose estimated annual premium is at
        least 500,000 cents (five thousand dollars) is selected at the
        `VOLUNTARY_REPORT` tier."

        Design: Corner/entities/work_order_created_with_policy_period_and_tier
        """
        cc = create_class_code()
        policy = create_policy("WC-C2", [cc["id"]],
                               estimated_annual_premium_cents=600000)

        run_selection()
        wo = find_work_order(policy["id"])

        assert_work_order(wo)
        assert wo["audit_type"] == "VOLUNTARY_REPORT"
        assert wo["status"] == "SELECTED"
        assert wo["no_show_count"] == 0
        assert wo["assigned_auditor_id"] is None
        assert wo["reaudit_of_work_order_id"] is None
        assert wo["selection_run_id"] is not None
        assert parse_ts(wo["audit_period_start"]) == parse_ts(
            "2026-01-01T00:00:00Z")
        assert parse_ts(wo["audit_period_end"]) == parse_ts(
            "2026-07-31T00:00:00Z")

        pol_after = validate_success(api.get_policy(policy["id"], MANAGER))
        assert pol_after["status"] == "AUDIT_PENDING"


class TestAssignment:
    def test_assign_auditor_territory_mismatch(self, api):
        """PRD: "the auditor's `territory_states` must include the audited
        policy's `state_code`, failing which the assignment is rejected with
        `ERR_AUDITOR_TERRITORY_MISMATCH`."

        Design: Corner/validations/assign_auditor_territory_mismatch
        """
        ctx = setup_selected_work_order(policy_number="WC-V5",
                                        estimated_annual_premium_cents=2000000,
                                        minimum_premium_cents=100000,
                                        with_auditor=False, assign=False,
                                        request_types=())
        ny_auditor = create_auditor(full_name="New Yorker",
                                    territory_states=("NY",))

        resp = api.assign_work_order(ctx["work_order"]["id"],
                                     {"auditor_id": ny_auditor["id"]}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_AUDITOR_TERRITORY_MISMATCH)

        wo_after = validate_success(
            api.get_work_order(ctx["work_order"]["id"], MANAGER))
        assert wo_after["assigned_auditor_id"] is None
