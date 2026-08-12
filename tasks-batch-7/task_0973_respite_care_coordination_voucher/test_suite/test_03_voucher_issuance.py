"""Voucher issuance: caps, budget, boundaries, revocation identity, posture of funds."""
from test_helpers import (
    ADMIN,
    COORD,
    ApiErrorId,
    add_window,
    assert_allocation_hours_identity,
    assert_hours,
    create_active_caregiver,
    create_active_provider,
    create_booking_payload,
    create_program,
    create_voucher_payload,
    api_client,
    get_success_data,
    issue_voucher,
    make_caregiver_headers,
    run_ops_run,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVoucherIssueAvailableHoursBoundary:
    def test_voucher_issue_at_exact_available_hours(self, api):
        """PRD §3.4: "The maximum issuable is the smallest of three quantities: the
        allocation's `available_hours`, the program's `quarterly_cap_hours` minus the
        quarter load, and the program's `annual_cap_hours` minus the annual load. If
        `authorized_hours` exceeds that maximum, the rejection is chosen by which bound
        is binding: when `authorized_hours` exceeds `available_hours` the error is
        `ERR_INSUFFICIENT_HOURS`"
        PRD §3.4: "The allocation's `available_hours` is reduced by `authorized_hours`
        and its `reserved_hours` is increased by the same amount"

        Design: Difficulty/boundary_precision_check/voucher_issue_exactly_available_hours_boundary
        """
        ctx = create_active_caregiver()
        alloc = ctx["allocation"]
        # 80.00 exactly equals both available_hours and the quarterly cap: equal passes.
        voucher = validate_success(
            api.create_voucher(
                create_voucher_payload(alloc["id"], ctx["caregiver"]["id"], 80),
                make_caregiver_headers(ctx["caregiver"]["id"])),
            201)
        assert_hours(voucher["authorized_hours"], 80.00, "authorized_hours")
        after = validate_success(api.get_allocation(alloc["id"], COORD), 200)
        assert_hours(after["available_hours"], 0.00, "available_hours")
        assert_hours(after["reserved_hours"], 80.00, "reserved_hours")

    def test_voucher_issue_above_available_rejected(self, api):
        """PRD §3.4: "If `authorized_hours` exceeds that maximum, the rejection is
        chosen by which bound is binding: when `authorized_hours` exceeds
        `available_hours` the error is `ERR_INSUFFICIENT_HOURS`"

        Design: Difficulty/boundary_precision_check/voucher_issue_exactly_available_hours_boundary
        """
        ctx = create_active_caregiver()
        alloc = ctx["allocation"]
        issue_voucher(alloc["id"], ctx["caregiver"]["id"], 80)
        res = api.create_voucher(
            create_voucher_payload(alloc["id"], ctx["caregiver"]["id"], 1),
            make_caregiver_headers(ctx["caregiver"]["id"]))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_HOURS, expected_status=422)


def test_quarterly_cap_exceeded_with_grant_headroom(api):
    """PRD §3.4: "If `authorized_hours` exceeds that maximum, the rejection is chosen
    by which bound is binding: when `authorized_hours` exceeds `available_hours` the
    error is `ERR_INSUFFICIENT_HOURS`; otherwise when the quarterly cap is the binding
    constraint the error is `ERR_QUARTERLY_CAP_EXCEEDED`"

    Design: Corner/validations/quarterly_cap_exceeded_with_grant_headroom
    """
    ctx = create_active_caregiver()
    alloc = ctx["allocation"]
    cg_id = ctx["caregiver"]["id"]
    issue_voucher(alloc["id"], cg_id, 60)
    alloc_after_issue = validate_success(api.get_allocation(alloc["id"], COORD), 200)
    validate_success(
        api.create_grant_adjustment(
            alloc["id"],
            {"delta_hours": 20, "reason": "pilot top-up",
             "expected_allocation_version": alloc_after_issue["version"]},
            COORD),
        201)
    # granted 100.00 / available 40.00; 30h fits availability but 60+30 = 90 > 80 cap.
    res = api.create_voucher(
        create_voucher_payload(alloc["id"], cg_id, 30),
        make_caregiver_headers(cg_id))
    validate_error(res, ApiErrorId.ERR_QUARTERLY_CAP_EXCEEDED, expected_status=422)
    after = validate_success(api.get_allocation(alloc["id"], COORD), 200)
    assert_hours(after["available_hours"], 40.00, "available_hours")


def test_redetermination_blocks_new_voucher(api):
    """PRD §3.8: "When an ops-run observes that a caregiver in `ACTIVE` has
    `redetermination_due_at` at or before now, the caregiver transitions to
    `REDETERMINATION_PENDING`"
    PRD §3.4: "a caregiver in `REDETERMINATION_PENDING` is rejected with the more
    specific `ERR_REDETERMINATION_OVERDUE`."

    Design: Corner/validations/redetermination_blocks_new_voucher
    """
    program = create_program()
    ctx = create_active_caregiver(program=program)
    alloc_id = ctx["allocation"]["id"]
    cg_id = ctx["caregiver"]["id"]
    # Approval at the default clock sets redetermination due 2027-05-01.
    set_clock("2027-05-02T00:00:00Z")
    run_ops_run(program["id"], "STANDARD")
    caregiver = validate_success(api.get_caregiver(cg_id, COORD), 200)
    assert caregiver["status"] == "REDETERMINATION_PENDING"

    res = api.create_voucher(create_voucher_payload(alloc_id, cg_id, 5), COORD)
    validate_error(res, ApiErrorId.ERR_REDETERMINATION_OVERDUE, expected_status=422)


def test_booking_beyond_voucher_expiry_rejected(api):
    """PRD §3.6: "The booking's `end_at` must be at or before the voucher's
    `expires_at`, or the create is rejected with `ERR_BOOKING_BEYOND_VOUCHER_EXPIRY`."
    PRD §3.4: "`expires_at` set to `issued_at` plus the program's `voucher_expiry_days`
    (default 90 days)".

    Design: Corner/validations/booking_beyond_voucher_expiry_rejected
    """
    ctx = create_active_caregiver()
    provider = create_active_provider()
    window = add_window(provider["id"], "2026-08-03T08:00:00Z", "2026-08-07T20:00:00Z", 1)
    voucher = issue_voucher(ctx["allocation"]["id"], ctx["caregiver"]["id"], 10)
    # Voucher issued at the 2026-05-01 default clock expires 2026-07-30T00:00:00Z.
    res = api.create_booking(
        create_booking_payload(voucher["id"], ctx["caregiver"]["id"],
                               "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z",
                               match_mode="EXPLICIT",
                               provider_id=provider["id"], window_id=window["id"]),
        make_caregiver_headers(ctx["caregiver"]["id"]))
    validate_error(res, ApiErrorId.ERR_BOOKING_BEYOND_VOUCHER_EXPIRY, expected_status=422)
    voucher_after = validate_success(api.get_voucher(voucher["id"], COORD), 200)
    assert voucher_after["status"] == "ISSUED"


def test_immediate_bucket_visibility_after_issue(api):
    """PRD §3.4: "The allocation's `available_hours` is reduced by `authorized_hours`
    and its `reserved_hours` is increased by the same amount"

    Design: Corner/consistency_model/immediate_read_after_write_voucher_buckets
    """
    ctx = create_active_caregiver()
    issue_voucher(ctx["allocation"]["id"], ctx["caregiver"]["id"], 20)
    after = validate_success(api.get_allocation(ctx["allocation"]["id"], COORD), 200)
    assert_hours(after["available_hours"], 60.00, "available_hours")
    assert_hours(after["reserved_hours"], 20.00, "reserved_hours")


def test_voucher_list_filter_pagination_envelope(api):
    """PRD §2.3: "`limit` defaults to 10, must be at least 1, and may not exceed 100.
    `offset` defaults to 0. The `meta` block of a list response always carries
    `limit`, `offset`, `total_count`, and `has_more`."
    PRD §4: GET /respite/vouchers lists vouchers "filtered by
    allocation/caregiver/program/status".

    Design: Corner/endpoints/voucher_list_filter_pagination_envelope
    """
    ctx = create_active_caregiver()
    for _ in range(3):
        issue_voucher(ctx["allocation"]["id"], ctx["caregiver"]["id"], 10)
    data, meta = validate_paginated(
        api.list_vouchers(COORD, params={"caregiver_id": ctx["caregiver"]["id"],
                                         "limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


class TestIssueThenRevokeIdentity:
    def test_issue_then_revoke_bucket_identity(self, api):
        """PRD §3.4: "The allocation's `available_hours` is reduced by
        `authorized_hours` and its `reserved_hours` is increased by the same amount"
        PRD §3.4: "The revocation sets the voucher's `forfeited_hours` to
        `authorized_hours` minus `consumed_hours`, moves the voucher to `REVOKED`,
        decrements the allocation's `reserved_hours` by `forfeited_hours` and
        increments its `revoked_hours` by the same, and appends a `RELEASE` ledger
        entry for the remaining provisional encumbrance."

        Design: Difficulty/compensating_invariant/allocation_hours_identity_issue_then_revoke
        """
        ctx = create_active_caregiver()
        alloc_id = ctx["allocation"]["id"]
        voucher = issue_voucher(alloc_id, ctx["caregiver"]["id"], 20)
        mid = validate_success(api.get_allocation(alloc_id, COORD), 200)
        assert_hours(mid["available_hours"], 60.00, "mid available_hours")
        assert_hours(mid["reserved_hours"], 20.00, "mid reserved_hours")

        validate_success(
            api.revoke_voucher(voucher["id"], {"reason": "plan change"}, COORD), 200)
        after = validate_success(api.get_allocation(alloc_id, COORD), 200)
        assert_hours(after["granted_hours"], 80.00, "granted_hours")
        assert_hours(after["available_hours"], 60.00, "available_hours")
        assert_hours(after["reserved_hours"], 0.00, "reserved_hours")
        assert_hours(after["consumed_hours"], 0.00, "consumed_hours")
        assert_hours(after["expired_hours"], 0.00, "expired_hours")
        assert_hours(after["revoked_hours"], 20.00, "revoked_hours")
        assert_allocation_hours_identity(after)

    def test_revoke_sets_voucher_forfeiture(self, api):
        """PRD §3.4: "The revocation sets the voucher's `forfeited_hours` to
        `authorized_hours` minus `consumed_hours`, moves the voucher to `REVOKED`"

        Design: Difficulty/compensating_invariant/allocation_hours_identity_issue_then_revoke
        """
        ctx = create_active_caregiver()
        voucher = issue_voucher(ctx["allocation"]["id"], ctx["caregiver"]["id"], 20)
        revoked = validate_success(
            api.revoke_voucher(voucher["id"], {"reason": "plan change"}, COORD), 200)
        assert revoked["status"] == "REVOKED"
        assert_hours(revoked["forfeited_hours"], 20.00, "forfeited_hours")


class TestCaregiverStateBeatsBudget:
    def test_suspended_caregiver_error_beats_budget_error(self, api):
        """PRD §2.9: "(8) caregiver-active requirements for voucher, booking, and
        emergency creation (`ERR_CAREGIVER_NOT_ACTIVE`)" precedes "(24) budget
        encumbrance (`ERR_BUDGET_EXCEEDED`)".
        PRD §2.9: "A request that fails several of these surfaces the error whose rule
        sits earliest in this list."

        Design: Difficulty/priority_pair_validation_conflict/caregiver_state_beats_insufficient_budget
        """
        program = create_program(total_budget_cents=1000)
        ctx = create_active_caregiver(program=program)
        alloc_id = ctx["allocation"]["id"]
        cg_id = ctx["caregiver"]["id"]
        validate_success(
            api.transition_caregiver(cg_id, {"target_status": "SUSPENDED"}, COORD), 200)
        # Both violations hold: caregiver SUSPENDED (rule 8) and 2h x 3000 = 6000
        # cents provisional > 1000 unencumbered (rule 24).
        res = api.create_voucher(create_voucher_payload(alloc_id, cg_id, 2), COORD)
        validate_error(res, ApiErrorId.ERR_CAREGIVER_NOT_ACTIVE, expected_status=422)

    def test_budget_exceeded_when_caregiver_active(self, api):
        """PRD §3.4: "A further fiscal check applies: the provisional encumbrance,
        computed as `authorized_hours` multiplied by the program's
        `standard_rate_cents_per_hour`, must not exceed the program's
        `unencumbered_cents`, or the issue is rejected with `ERR_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/caregiver_state_beats_insufficient_budget
        """
        program = create_program(total_budget_cents=1000)
        ctx = create_active_caregiver(program=program)
        res = api.create_voucher(
            create_voucher_payload(ctx["allocation"]["id"], ctx["caregiver"]["id"], 2),
            make_caregiver_headers(ctx["caregiver"]["id"]))
        validate_error(res, ApiErrorId.ERR_BUDGET_EXCEEDED, expected_status=422)
