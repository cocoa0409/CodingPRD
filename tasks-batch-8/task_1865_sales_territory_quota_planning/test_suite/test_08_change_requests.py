"""Mid-year territory change requests: lifecycle cycle, OCC guard, validation
family, quota transfer, and the four-hop apply cascade with credit transition."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    activate_territory,
    add_territory,
    approve_change_request,
    create_account,
    create_change_request,
    create_change_request_payload,
    create_plan,
    get_account,
    get_assignment,
    get_change_request,
    get_territory,
    make_analyst_headers,
    make_manager_headers,
    plan_version,
    set_clock,
    setup_change_apply_scenario,
    setup_two_territory_communicated,
    validate_error,
    validate_paginated,
    validate_success,
)

MGR = make_manager_headers("mgr-1")


def _dual_policy_plans(api):
    """Plan D (PRORATE_BY_DAY, 2027) and plan M (MONTH_SNAPSHOT, 2029), each
    with an approved change request effective the 10th of July after June and
    July bookings of 5000 and 10000 on the old rep. Clock ends at July 25 of
    plan M's year, at or after both effective dates."""
    ns_d = setup_change_apply_scenario(
        year=2027, label="FY27-D", credit_transition_policy="PRORATE_BY_DAY",
        bookings=[("2027-06-05", 5000), ("2027-07-05", 10000)],
        effective_date="2027-07-10")
    ns_m = setup_change_apply_scenario(
        year=2029, label="FY27-M", credit_transition_policy="MONTH_SNAPSHOT",
        bookings=[("2029-06-05", 5000), ("2029-07-05", 10000)],
        effective_date="2029-07-10")
    set_clock("2029-07-25T00:00:00Z")
    return ns_d, ns_m


def test_prorate_by_day_splits_transition_month(api):
    """PRD: "Under `PRORATE_BY_DAY`, an event booked in the transition month
    transfers the fraction of the month remaining from the effective date
    onward — the count of days from the effective date through the month's
    last day, inclusive, over the month's total days — while events booked in
    later months transfer in full."
    PRD: "Hop two transfers quota: the transfer amount is the account's
    `annual_potential_cents` multiplied by the number of plan months remaining
    after the effective month — twelve minus the one-based index of the
    effective date's month within the plan year — divided by twelve, rounded
    half-up to whole cents, and the result is stored in the request's
    `quota_transfer_cents`"

    Effective 2027-07-10: the July 10000 booking transfers
    round_half_up(10000 x 22/31) == 7097 to the new rep while the June 5000
    stays; the 100000 quota transfer (240000 x 5/12) is policy-independent.

    Design: Difficulty/dual_variant_calc/credit_transition_day_proration_vs_month_snapshot
    """
    ns_d, _ = _dual_policy_plans(api)
    cr = validate_success(
        api.apply_change_request(ns_d["cr"]["id"], MGR), 200)
    assert cr["status"] == "APPLIED"
    assert cr["quota_transfer_cents"] == 100000

    old = get_assignment(ns_d["asg_old"]["id"])
    new = get_assignment(ns_d["asg_new"]["id"])
    assert old["attainment_cents"] == 7903, \
        "5000 June intact + 10000 - 7097 prorated out of July"
    assert new["attainment_cents"] == 7097
    assert get_territory(ns_d["tf"]["id"])["final_quota_cents"] == 200000
    assert get_territory(ns_d["tt"]["id"])["final_quota_cents"] == 300000


def test_month_snapshot_transfers_wholesale_when_day_le_15(api):
    """PRD: "Under `MONTH_SNAPSHOT`, the transition month transfers wholesale
    when the effective day is on or before the fifteenth and not at all when it
    falls after the fifteenth, with later months again transferring in full;
    identical ledgers therefore yield different rep attainments under the two
    policies."

    Effective 2029-07-10 (day 10 <= 15): the whole July 10000 transfers to the
    new rep while the June 5000 stays — a divergence from the day-proration
    outcome on identical ledgers.

    Design: Difficulty/dual_variant_calc/credit_transition_day_proration_vs_month_snapshot
    """
    _, ns_m = _dual_policy_plans(api)
    cr = validate_success(
        api.apply_change_request(ns_m["cr"]["id"], MGR), 200)
    assert cr["status"] == "APPLIED"
    assert cr["quota_transfer_cents"] == 100000

    old = get_assignment(ns_m["asg_old"]["id"])
    new = get_assignment(ns_m["asg_new"]["id"])
    assert old["attainment_cents"] == 5000
    assert new["attainment_cents"] == 10000
    assert get_territory(ns_m["tf"]["id"])["final_quota_cents"] == 200000
    assert get_territory(ns_m["tt"]["id"])["final_quota_cents"] == 300000


def _apply_four_hop_scenario(api):
    """Plan COMMUNICATED: root R target 480000; children TF (pot 600, final
    360000) and TT (pot 200, final 120000); veteran reps on both; account ACC
    (potential 288000) on TF with one July booking 12000; approved change
    request effective 2027-07-10; clock at 2027-07-25."""
    return setup_change_apply_scenario(
        label="FY27-CAS", target=480000, tf_potential=600, tt_potential=200,
        account_potential=288000, bookings=[("2027-07-15", 12000)],
        effective_date="2027-07-10", clock_final="2027-07-25T00:00:00Z")


def test_change_apply_moves_account_and_transfers_quota(api):
    """PRD: "Hop one moves the account: its `assigned_territory_id` becomes the
    destination, its `assignment_source` becomes `MANUAL_CHANGE`, and its
    `assignment_rule_id` clears to null."
    PRD: "Hop two transfers quota: the transfer amount is the account's
    `annual_potential_cents` multiplied by the number of plan months remaining
    after the effective month — twelve minus the one-based index of the
    effective date's month within the plan year — divided by twelve, rounded
    half-up to whole cents, and the result is stored in the request's
    `quota_transfer_cents`"

    round_half_up(288000 x 5/12) == 120000 moves TF 360000 -> 240000 and TT
    120000 -> 240000.

    Design: Difficulty/transitive_cascade/change_apply_four_hop_cascade
    """
    ns = _apply_four_hop_scenario(api)
    cr = validate_success(api.apply_change_request(ns["cr"]["id"], MGR), 200)
    assert cr["status"] == "APPLIED"
    assert cr["quota_transfer_cents"] == 120000

    acc = get_account(ns["acc"]["id"])
    assert acc["assigned_territory_id"] == ns["tt"]["id"]
    assert acc["assignment_source"] == "MANUAL_CHANGE"
    assert acc["assignment_rule_id"] is None

    assert get_territory(ns["tf"]["id"])["final_quota_cents"] == 240000
    assert get_territory(ns["tt"]["id"])["final_quota_cents"] == 240000


def test_change_apply_transitions_credit_and_recomputes_finals(api):
    """PRD: "Under `PRORATE_BY_DAY`, an event booked in the transition month
    transfers the fraction of the month remaining from the effective date
    onward" — round_half_up(12000 x 22/31) == 8516 here.
    PRD: "a `TRANSFER_OUT` event of the negated amount is created on the
    original credited rep, linked back to the source through
    `parent_credit_event_id` and to the request through
    `source_change_request_id`, and the equal positive amount is distributed
    among the destination territory's `ACTIVE` reps as `TRANSFER_IN` events"

    Hop four leaves both fully-ramped reps with final_quota_cents 240000
    (12 x 20000).

    Design: Difficulty/transitive_cascade/change_apply_four_hop_cascade
    """
    ns = _apply_four_hop_scenario(api)
    evt_jul = ns["events"][0]
    validate_success(api.apply_change_request(ns["cr"]["id"], MGR), 200)

    transfers, _ = validate_paginated(api.list_credit_events(
        ADMIN, params={"source_change_request_id": ns["cr"]["id"]}))
    assert len(transfers) == 2
    out_events = [e for e in transfers if e["event_type"] == "TRANSFER_OUT"]
    in_events = [e for e in transfers if e["event_type"] == "TRANSFER_IN"]
    assert len(out_events) == 1 and len(in_events) == 1
    assert out_events[0]["amount_cents"] == -8516
    assert out_events[0]["rep_id"] == ns["rep_old"]["id"]
    assert out_events[0]["parent_credit_event_id"] == evt_jul["id"]
    assert in_events[0]["amount_cents"] == 8516
    assert in_events[0]["rep_id"] == ns["rep_new"]["id"]

    old = get_assignment(ns["asg_old"]["id"])
    new = get_assignment(ns["asg_new"]["id"])
    assert old["attainment_cents"] == 3484
    assert new["attainment_cents"] == 8516
    assert old["final_quota_cents"] == 240000
    assert new["final_quota_cents"] == 240000


def _conservation_scenario(api):
    """Plan COMMUNICATED (PRORATE_BY_DAY): TF (final 300000) staffed by repOld,
    TT (final 200000) staffed by repNew; account ACC (potential 240000) on TF;
    bookings 5000 (2027-06-05) and 10000 (2027-07-05) credited to repOld;
    change request approved, effective 2027-07-10; clock at 2027-07-25."""
    return setup_change_apply_scenario(
        label="FY27-CONS", target=500000, tf_potential=600, tt_potential=400,
        account_potential=240000,
        bookings=[("2027-06-05", 5000), ("2027-07-05", 10000)],
        effective_date="2027-07-10", clock_final="2027-07-25T00:00:00Z")


def test_midyear_change_preserves_plan_wide_attainment(api):
    """PRD: "Per source event the transfer-ins and transfer-out net to zero,
    leaving plan-wide attainment unchanged"

    The July 10000 splits 7097 / 2903 between new and old rep (the June 5000
    predates the transition month), so plan-wide attainment is 15000 before
    and after the apply.

    Design: Difficulty/compensating_invariant/attainment_conservation_on_midyear_change
    """
    ns = _conservation_scenario(api)
    total_before = (
        get_assignment(ns["asg_old"]["id"])["attainment_cents"]
        + get_assignment(ns["asg_new"]["id"])["attainment_cents"])
    assert total_before == 15000

    validate_success(api.apply_change_request(ns["cr"]["id"], MGR), 200)
    old = get_assignment(ns["asg_old"]["id"])
    new = get_assignment(ns["asg_new"]["id"])
    assert old["attainment_cents"] == 7903
    assert new["attainment_cents"] == 7097
    assert old["attainment_cents"] + new["attainment_cents"] == 15000, \
        "plan-wide attainment unchanged by the apply"


def test_transfer_events_net_to_zero_and_are_listable(api):
    """PRD: "Per source event the transfer-ins and transfer-out net to zero,
    leaving plan-wide attainment unchanged"
    PRD: "Credit events can be listed filtered by `plan_year_id`, `account_id`,
    `rep_id`, `event_type`, `status`, `source_change_request_id`, or
    `parent_credit_event_id`."

    The change request's apply produces exactly two POSTED transfer events —
    TRANSFER_OUT -7097 linked to the July booking and TRANSFER_IN +7097 to the
    new rep — summing to zero.

    Design: Difficulty/compensating_invariant/attainment_conservation_on_midyear_change
    """
    ns = _conservation_scenario(api)
    evt_jul = ns["events"][1]
    validate_success(api.apply_change_request(ns["cr"]["id"], MGR), 200)

    transfers, _ = validate_paginated(api.list_credit_events(
        ADMIN, params={"source_change_request_id": ns["cr"]["id"]}))
    assert len(transfers) == 2
    assert all(e["status"] == "POSTED" for e in transfers)
    assert sum(e["amount_cents"] for e in transfers) == 0
    out_event = next(e for e in transfers
                     if e["event_type"] == "TRANSFER_OUT")
    in_event = next(e for e in transfers if e["event_type"] == "TRANSFER_IN")
    assert out_event["amount_cents"] == -7097
    assert out_event["rep_id"] == ns["rep_old"]["id"]
    assert out_event["parent_credit_event_id"] == evt_jul["id"]
    assert in_event["amount_cents"] == 7097
    assert in_event["rep_id"] == ns["rep_new"]["id"]


def test_month_snapshot_day16_keeps_transition_month(api):
    """PRD: "Under `MONTH_SNAPSHOT`, the transition month transfers wholesale
    when the effective day is on or before the fifteenth and not at all when it
    falls after the fifteenth, with later months again transferring in full"
    PRD: "For each source event, the transferred-out amount is its amount times
    the policy fraction, rounded half-up to whole cents, and when that rounds
    to zero no events are created for that source."

    Effective 2027-07-20 (day 20 > 15): the July 10000 booking spawns zero
    transfer events while the 100000 quota transfer still applies.

    Design: Corner/calculations/month_snapshot_day16_keeps_transition_month
    """
    ns = setup_change_apply_scenario(
        label="FY27-MS", credit_transition_policy="MONTH_SNAPSHOT",
        bookings=[("2027-07-05", 10000)], effective_date="2027-07-20",
        clock_final="2027-07-25T00:00:00Z")
    cr = validate_success(api.apply_change_request(ns["cr"]["id"], MGR), 200)
    assert cr["quota_transfer_cents"] == 100000, \
        "quota transfer ignores the credit policy variant"

    transfers, _ = validate_paginated(api.list_credit_events(
        ADMIN, params={"source_change_request_id": ns["cr"]["id"]}))
    assert transfers == [], \
        "transition month stays with the old rep: zero transfer events"
    assert get_assignment(ns["asg_old"]["id"])["attainment_cents"] == 10000
    assert get_assignment(ns["asg_new"]["id"])["attainment_cents"] == 0
    assert get_account(ns["acc"]["id"])["assigned_territory_id"] == \
        ns["tt"]["id"]


def test_quota_transfer_december_effective_is_zero(api):
    """PRD: "Hop two transfers quota: the transfer amount is the account's
    `annual_potential_cents` multiplied by the number of plan months remaining
    after the effective month — twelve minus the one-based index of the
    effective date's month within the plan year — divided by twelve, rounded
    half-up to whole cents, and the result is stored in the request's
    `quota_transfer_cents`"

    An effective date in plan month 12 leaves zero remaining months: the
    transfer is 0, both territory finals stand unchanged, and the account
    still moves.

    Design: Corner/calculations/quota_transfer_december_effective_is_zero
    """
    ns = setup_change_apply_scenario(
        label="FY27-DEC", effective_date="2027-12-05", bookings=(),
        staff_from=False, clock_final="2027-12-05T00:00:00Z")
    cr = validate_success(api.apply_change_request(ns["cr"]["id"], MGR), 200)
    assert cr["status"] == "APPLIED"
    assert cr["quota_transfer_cents"] == 0
    assert get_territory(ns["tf"]["id"])["final_quota_cents"] == 300000
    assert get_territory(ns["tt"]["id"])["final_quota_cents"] == 200000
    assert get_account(ns["acc"]["id"])["assigned_territory_id"] == \
        ns["tt"]["id"]


def test_change_request_return_clears_decider(api):
    """PRD: "An `APPROVED` request may also be returned by a manager to
    `PENDING` for rework, optionally annotated with a `return_reason`; the
    return clears `decided_by_user_id` back to null, reopening the
    segregation-of-duties check for the next approver."
    PRD: "Approval moves the request to `APPROVED`, records the approver in
    `decided_by_user_id`, and increments the plan's `version` by one."

    Design: Difficulty/non_linear_state_machine/change_request_approve_return_cycle
    """
    ns = setup_two_territory_communicated(
        label="FY27-CYC", owner_name="TF", claimant_name="TT",
        account_potential=120000)
    cr = create_change_request(ns["plan"]["id"], ns["acc"]["id"],
                               ns["tx"]["id"], ns["ty"]["id"], "2027-07-10",
                               creator="analyst-1", reason="realign")

    approved = approve_change_request(cr["id"], ns["plan"]["id"],
                                      approver="mgr-1")
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] == "mgr-1"

    returned = validate_success(api.return_change_request(
        cr["id"], make_manager_headers("mgr-1"),
        return_reason="rework dates"), 200)
    assert returned["status"] == "PENDING"
    assert returned["decided_by_user_id"] is None


def test_change_request_cycle_completes_to_applied(api):
    """PRD: "An `APPROVED` request may also be returned by a manager to
    `PENDING` for rework, optionally annotated with a `return_reason`; the
    return clears `decided_by_user_id` back to null, reopening the
    segregation-of-duties check for the next approver."
    PRD: "Hop one moves the account: its `assigned_territory_id` becomes the
    destination, its `assignment_source` becomes `MANUAL_CHANGE`, and its
    `assignment_rule_id` clears to null."

    The cyclic traversal PENDING -> APPROVED -> PENDING -> APPROVED -> APPLIED
    still completes and moves the account.

    Design: Difficulty/non_linear_state_machine/change_request_approve_return_cycle
    """
    ns = setup_two_territory_communicated(
        label="FY27-CYC2", owner_name="TF", claimant_name="TT",
        account_potential=120000)
    cr = create_change_request(ns["plan"]["id"], ns["acc"]["id"],
                               ns["tx"]["id"], ns["ty"]["id"], "2027-07-10",
                               creator="analyst-1")

    approve_change_request(cr["id"], ns["plan"]["id"], approver="mgr-1")
    validate_success(api.return_change_request(
        cr["id"], make_manager_headers("mgr-1")), 200)
    assert get_change_request(cr["id"])["status"] == "PENDING"

    reapproved = approve_change_request(cr["id"], ns["plan"]["id"],
                                        approver="mgr-1")
    assert reapproved["status"] == "APPROVED"
    assert reapproved["decided_by_user_id"] == "mgr-1"

    set_clock("2027-07-10T00:00:00Z")
    applied = validate_success(api.apply_change_request(cr["id"], MGR), 200)
    assert applied["status"] == "APPLIED"
    acc = get_account(ns["acc"]["id"])
    assert acc["assigned_territory_id"] == ns["ty"]["id"]
    assert acc["assignment_source"] == "MANUAL_CHANGE"


def test_change_from_territory_mismatch_rejected(api):
    """PRD: "The from-territory must equal the account's currently assigned
    territory at creation — and will be checked again at apply — failing with
    `ERR_FROM_TERRITORY_MISMATCH`"

    Design: Corner/validations/change_from_territory_mismatch_rejected
    """
    ns = setup_two_territory_communicated(label="FY27-FTM")
    resp = api.create_change_request(
        create_change_request_payload(ns["plan"]["id"], ns["acc"]["id"],
                                      ns["ty"]["id"], ns["tx"]["id"],
                                      "2027-07-01"),
        make_analyst_headers("analyst-1"))
    validate_error(resp, ApiErrorId.ERR_FROM_TERRITORY_MISMATCH, 409)


def test_change_same_territory_rejected(api):
    """PRD: "naming the same territory on both sides is
    `ERR_SAME_TERRITORY_TRANSFER`"

    Design: Corner/validations/change_same_territory_rejected
    """
    ns = setup_two_territory_communicated(label="FY27-SAME")
    resp = api.create_change_request(
        create_change_request_payload(ns["plan"]["id"], ns["acc"]["id"],
                                      ns["tx"]["id"], ns["tx"]["id"],
                                      "2027-07-01"),
        make_analyst_headers("analyst-1"))
    validate_error(resp, ApiErrorId.ERR_SAME_TERRITORY_TRANSFER, 422)


def test_change_already_pending_rejected(api):
    """PRD: "an account may carry at most one non-terminal change request at a
    time, so a second request while one sits in `PENDING` or `APPROVED` is
    `ERR_CHANGE_ALREADY_PENDING`."

    Design: Corner/validations/change_already_pending_rejected
    """
    ns = setup_two_territory_communicated(label="FY27-PEND")
    cr1 = create_change_request(ns["plan"]["id"], ns["acc"]["id"],
                                ns["tx"]["id"], ns["ty"]["id"], "2027-07-01")
    resp = api.create_change_request(
        create_change_request_payload(ns["plan"]["id"], ns["acc"]["id"],
                                      ns["tx"]["id"], ns["ty"]["id"],
                                      "2027-08-01"),
        make_analyst_headers("analyst-1"))
    validate_error(resp, ApiErrorId.ERR_CHANGE_ALREADY_PENDING, 409)
    assert get_change_request(cr1["id"])["status"] == "PENDING"


def test_change_apply_before_effective_date_rejected(api):
    """PRD: "Applying an `APPROVED` request is a manager's act with five
    preconditions: the plan gate above; the current logical date must have
    reached the `effective_date`, earlier attempts failing with
    `ERR_CHANGE_NOT_YET_EFFECTIVE`"

    Apply one day before the effective date is rejected; apply on the
    effective date itself succeeds.

    Design: Corner/validations/change_apply_before_effective_date_rejected
    """
    ns = setup_two_territory_communicated(label="FY27-NYE", owner_name="TF",
                                          claimant_name="TT")
    cr = create_change_request(ns["plan"]["id"], ns["acc"]["id"],
                               ns["tx"]["id"], ns["ty"]["id"], "2027-07-10")
    approve_change_request(cr["id"], ns["plan"]["id"], approver="mgr-1")

    set_clock("2027-07-09T00:00:00Z")
    validate_error(api.apply_change_request(cr["id"], MGR),
                   ApiErrorId.ERR_CHANGE_NOT_YET_EFFECTIVE, 409)
    set_clock("2027-07-10T00:00:00Z")
    applied = validate_success(api.apply_change_request(cr["id"], MGR), 200)
    assert applied["status"] == "APPLIED"


def test_change_cancel_at_effective_date_rejected(api):
    """PRD: "an `APPROVED` request can be clawed back to `CANCELLED` only while
    the current logical date is still before its `effective_date`; once the
    effective date has been reached the cancel fails with
    `ERR_INVALID_STATE_TRANSITION`."

    With the clock at 2027-07-10 for a 2027-07-10 effective date, the APPROVED
    request can only be applied.

    Design: Corner/state_machines/change_cancel_at_effective_date_rejected
    """
    ns = setup_two_territory_communicated(label="FY27-CXL", owner_name="TF",
                                          claimant_name="TT")
    cr = create_change_request(ns["plan"]["id"], ns["acc"]["id"],
                               ns["tx"]["id"], ns["ty"]["id"], "2027-07-10")
    approve_change_request(cr["id"], ns["plan"]["id"], approver="mgr-1")
    set_clock("2027-07-10T00:00:00Z")
    validate_error(api.cancel_change_request(
        cr["id"], make_analyst_headers("analyst-1")),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
    assert get_change_request(cr["id"])["status"] == "APPROVED"


def test_change_create_cross_plan_account_beats_date_check(api):
    """PRD: "Every request is validated against an eight-tier pipeline, and the
    tiers are evaluated in strict order — a failure in an earlier tier masks
    everything behind it."
    PRD: "Tier five enforces cross-references, with `ERR_CROSS_PLAN_REFERENCE`
    always checked first inside the tier, followed by the change-request
    ownership alignment check `ERR_FROM_TERRITORY_MISMATCH`; both are 409."

    The request references an account owned by a different plan year (tier 5)
    AND supplies an effective_date outside the request plan's year (tier 6);
    the cross-reference error wins.

    Design: Difficulty/priority_pair_validation_conflict/change_create_referential_beats_temporal
    """
    ns = setup_two_territory_communicated(label="FY27-A", owner_name="T1",
                                          claimant_name="T2")
    plan_b = create_plan(label="FY28-B", start_date="2028-01-01",
                         end_date="2028-12-31", lock_date="2028-01-15")
    acc_b = create_account(plan_b["id"], name="ACC-B")

    resp = api.create_change_request(
        create_change_request_payload(ns["plan"]["id"], acc_b["id"],
                                      ns["tx"]["id"], ns["ty"]["id"],
                                      "2028-06-01"),
        make_analyst_headers("analyst-1"))
    validate_error(resp, ApiErrorId.ERR_CROSS_PLAN_REFERENCE, 409)

    data, meta = validate_paginated(api.list_change_requests(
        ADMIN, params={"plan_year_id": ns["plan"]["id"]}))
    assert meta["total_count"] == 0 and data == [], \
        "no change request may be persisted"


def test_change_create_cross_plan_territory_beats_date_check(api):
    """PRD: "Every request is validated against an eight-tier pipeline, and the
    tiers are evaluated in strict order — a failure in an earlier tier masks
    everything behind it."
    PRD: "Tier five enforces cross-references, with `ERR_CROSS_PLAN_REFERENCE`
    always checked first inside the tier, followed by the change-request
    ownership alignment check `ERR_FROM_TERRITORY_MISMATCH`; both are 409."
    PRD: "Every plan-scoped reference in a request must belong to the plan year
    the request names: ... the account and both territories of a change
    request"

    A to-territory from another plan plus an out-of-plan-year effective date
    still reports the cross-reference error.

    Design: Difficulty/priority_pair_validation_conflict/change_create_referential_beats_temporal
    """
    ns = setup_two_territory_communicated(label="FY27-A2", owner_name="T1",
                                          claimant_name="T2")
    plan_b = create_plan(label="FY28-B2", start_date="2028-01-01",
                         end_date="2028-12-31", lock_date="2028-01-15")
    tb = add_territory(plan_b["id"], name="TB")
    activate_territory(tb["id"])

    resp = api.create_change_request(
        create_change_request_payload(ns["plan"]["id"], ns["acc"]["id"],
                                      ns["tx"]["id"], tb["id"],
                                      "2028-06-01"),
        make_analyst_headers("analyst-1"))
    validate_error(resp, ApiErrorId.ERR_CROSS_PLAN_REFERENCE, 409)


def test_occ_change_approve_stale_version_rejected(api):
    """PRD: "Each of these requests must carry the field
    `expected_plan_year_version`, holding the plan version the client last
    observed; the field is non-optional on exactly these three operations. When
    the supplied value does not match the plan's current `version`, the request
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Stale approve is rejected 412 with the request still PENDING; the observed
    version approves and records the approver.

    Design: Corner/cross_cutting_complexity_layers/occ_change_approve_stale_version_rejected
    """
    ns = setup_two_territory_communicated(label="FY27-OCCC", owner_name="TF",
                                          claimant_name="TT")
    cr = create_change_request(ns["plan"]["id"], ns["acc"]["id"],
                               ns["tx"]["id"], ns["ty"]["id"], "2027-07-01")
    pv = plan_version(ns["plan"]["id"])

    validate_error(api.approve_change_request(cr["id"], pv - 1, MGR),
                   ApiErrorId.ERR_STALE_VERSION, 412)
    assert get_change_request(cr["id"])["status"] == "PENDING"

    approved = validate_success(api.approve_change_request(cr["id"], pv, MGR),
                                200)
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] == "mgr-1"


def test_change_requests_list_filter_by_account(api):
    """PRD: "Change requests can be listed filtered by `plan_year_id`,
    `account_id`, `from_territory_id`, `to_territory_id`, or `status`."

    GET change-requests?account_id returns exactly the requests for that
    account.

    Design: Corner/endpoints/change_requests_list_filter_by_account
    """
    ns = setup_two_territory_communicated(label="FY27-LIST", owner_name="TF",
                                          claimant_name="TT")
    plan_id = ns["plan"]["id"]
    acc2 = create_account(plan_id, name="A2", annual_potential_cents=60000)
    cr1 = create_change_request(plan_id, ns["acc"]["id"], ns["tx"]["id"],
                                ns["ty"]["id"], "2027-07-01")
    create_change_request(plan_id, acc2["id"], ns["tx"]["id"],
                          ns["ty"]["id"], "2027-07-01")

    data, meta = validate_paginated(api.list_change_requests(
        ADMIN, params={"account_id": ns["acc"]["id"]}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in data] == [cr1["id"]]
