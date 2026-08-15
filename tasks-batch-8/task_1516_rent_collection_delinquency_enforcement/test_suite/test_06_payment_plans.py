"""Payment plans: setup-fee pre-evaluation, installment split rounding,
schedule validation, approval gates, supersede, sweep-driven default/cure, and
the cooling-off boundary."""
from test_helpers import (
    ApiErrorId,
    add_charge,
    approve_plan,
    create_notice,
    create_payment_plan_payload,
    create_plan,
    get_plan,
    issue_notice,
    lease_version,
    list_charges,
    post_payment,
    record_and_post_payment,
    record_payment,
    return_payment,
    run_sweep,
    serve_notice,
    set_clock,
    setup_property_tenant_lease,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, make_property_manager_headers

PM = TEST_USERS["property_manager_headers"]
PM2 = TEST_USERS["property_manager_2_headers"]
AGENT = TEST_USERS["leasing_agent_headers"]


def test_installment_split_rounding_order(api):
    """PRD 3.8: "The schedule itself divides the scheduled total across the
    installments by whole-cent floor division: each installment's base amount is the
    scheduled total divided by the installment count, rounded down to whole cents, and
    the leftover cents are then distributed one cent each to the earliest installments
    in sequence order. The pinned order — floor the per-installment share first, then
    distribute the remainder — matters, because summing exact fractional shares and
    rounding afterward yields a different first installment."
    PRD 3.8: "The sum of the installment amounts always equals the scheduled total."

    Design: Difficulty/combinatorial_formula/installment_split_rounding_order
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    plan = create_plan(lease_id, [charge["id"]], installment_count=3)
    assert plan["setup_fee_cents"] == 0
    assert plan["scheduled_total_cents"] == 10000

    read_back = get_plan(plan["id"])
    schedule = [(i["sequence_number"], i["due_date"], i["amount_cents"]) for i in read_back["installments"]]
    assert schedule == [
        (1, "2026-08-15", 3334),
        (2, "2026-09-15", 3333),
        (3, "2026-10-15", 3333),
    ], f"floor-then-remainder distribution of 10000 over 3 must be [3334, 3333, 3333], got {schedule}"
    assert sum(i["amount_cents"] for i in read_back["installments"]) == read_back["scheduled_total_cents"]


def test_setup_fee_preevaluation_below_threshold(api):
    """PRD 3.8: "A balance one cent below the threshold incurs no fee even though
    notionally adding the fee would have carried the total past the threshold, because
    the fee was already fixed at zero."
    PRD 3.8: "Second, the setup fee is fixed: when that pre-fee balance is at least
    the property's `plan_setup_fee_threshold_cents` — a balance exactly equal to the
    threshold qualifies — the plan's `setup_fee_cents` equals the property's
    `plan_setup_fee_cents`; otherwise it is zero."

    Design: Difficulty/combinatorial_formula/setup_fee_preevaluation_order
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=19000)

    plan = create_plan(lease_id, [charge["id"]], installment_count=2)
    assert plan["setup_fee_cents"] == 0, (
        "A 19000 pre-fee balance sits below the 20000 threshold even though balance + fee would cross it"
    )
    assert plan["scheduled_total_cents"] == 19000
    fee_charges = list_charges(lease_id, params={"kind": "PLAN_SETUP_FEE"})
    assert fee_charges == []


def test_setup_fee_preevaluation_at_threshold(api):
    """PRD 3.8: "Second, the setup fee is fixed: when that pre-fee balance is at least
    the property's `plan_setup_fee_threshold_cents` — a balance exactly equal to the
    threshold qualifies — the plan's `setup_fee_cents` equals the property's
    `plan_setup_fee_cents`; otherwise it is zero. Third, when the fee is greater than
    zero, a `PLAN_SETUP_FEE` charge is created on the lease, due on the
    `first_installment_date` and stamped with source `PLAN`."

    Design: Difficulty/combinatorial_formula/setup_fee_preevaluation_order
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=20000)

    plan = create_plan(lease_id, [charge["id"]], installment_count=2)
    assert plan["setup_fee_cents"] == 2500
    assert plan["scheduled_total_cents"] == 22500
    fee_charges = list_charges(lease_id, params={"kind": "PLAN_SETUP_FEE"})
    assert len(fee_charges) == 1
    assert fee_charges[0]["amount_cents"] == 2500
    assert fee_charges[0]["due_date"] == "2026-08-15"
    assert fee_charges[0]["source"] == "PLAN"


def test_plan_schedule_total_conservation_with_remainder(api):
    """PRD 3.8: "The sum of the installment amounts always equals the scheduled
    total."
    PRD 3.8: "The schedule itself divides the scheduled total across the installments
    by whole-cent floor division: each installment's base amount is the scheduled total
    divided by the installment count, rounded down to whole cents, and the leftover
    cents are then distributed one cent each to the earliest installments in sequence
    order."

    Design: Difficulty/compensating_invariant/plan_schedule_total_conservation
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    plan = create_plan(lease_id, [charge["id"]], installment_count=3)
    read_back = get_plan(plan["id"])
    amounts = [i["amount_cents"] for i in read_back["installments"]]
    assert read_back["scheduled_total_cents"] == 10000
    assert amounts == [3334, 3333, 3333]
    assert sum(amounts) == read_back["scheduled_total_cents"]


def test_plan_schedule_total_conservation_fee_inclusive(api):
    """PRD 3.8: "Fourth, the plan's `scheduled_total_cents` is the pre-fee covered
    balance plus the setup fee."
    PRD 3.8: "The sum of the installment amounts always equals the scheduled total."

    Design: Difficulty/compensating_invariant/plan_schedule_total_conservation
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=20000)

    plan = create_plan(lease_id, [charge["id"]], installment_count=4)
    read_back = get_plan(plan["id"])
    amounts = [i["amount_cents"] for i in read_back["installments"]]
    assert read_back["scheduled_total_cents"] == 22500
    assert amounts == [5625, 5625, 5625, 5625]
    assert sum(amounts) == read_back["scheduled_total_cents"]


def test_plan_approve_twice_rejected(api):
    """PRD 3.8: "Approval is a segregated duty: a `PropertyManager` moves the plan
    from `DRAFT` to `ACTIVE` — approving from any other status is rejected with
    `ERR_PLAN_INVALID_TRANSITION` — but the approver's `X-User-ID` must differ from
    the plan's `drafted_by_user_id`, or the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/state_machines/plan_approve_twice_rejected
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)
    plan = create_plan(lease_id, [charge["id"]])

    approved = approve_plan(plan["id"])
    assert approved["status"] == "ACTIVE"

    response = api.transition_payment_plan(plan["id"], {"action": "APPROVE"}, PM)
    validate_error(response, ApiErrorId.ERR_PLAN_INVALID_TRANSITION)


def test_plan_first_installment_today_rejected(api):
    """PRD 3.8: "The schedule must be sensible: the installment count must lie between
    two and twelve inclusive, and the first installment date must fall strictly after
    the current date; either violation is rejected with
    `ERR_INVALID_INSTALLMENT_SCHEDULE`."

    Design: Corner/validations/plan_first_installment_today_rejected
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)
    lv = lease_version(lease_id)

    response = api.create_payment_plan(
        create_payment_plan_payload(lease_id, [charge["id"]], lv, first_installment_date="2026-08-01"),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_INSTALLMENT_SCHEDULE)


def test_second_plan_rejected_while_active(api):
    """PRD 3.8: "At most one plan per lease may be `ACTIVE` — drafting while an active
    plan exists is rejected with `ERR_PLAN_EXISTS` — and a lease whose previous plan
    defaulted is under a cooling-off period: while the number of days since that plan's
    `defaulted_date` remains less than the property's `plan_cooling_off_days`, a new
    plan is rejected with `ERR_PLAN_COOLING_OFF`."

    Design: Corner/validations/second_plan_rejected_while_active
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    plan = create_plan(lease_id, [charge["id"]])
    approved = approve_plan(plan["id"])
    assert approved["status"] == "ACTIVE"

    lv = lease_version(lease_id)
    response = api.create_payment_plan(
        create_payment_plan_payload(lease_id, [charge["id"]], lv, installment_count=3, first_installment_date="2026-08-20"),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_PLAN_EXISTS)


def test_plan_referential_beats_temporal(api):
    """PRD 2.9: "Every request is evaluated against an ordered validation pipeline.
    The first failing check produces the error response; later checks are not
    evaluated."
    PRD 2.9 rule 9: "Every element of `charge_ids` must belong to the lease the
    request targets, and a dispute's charge must belong to the dispute's lease;
    otherwise `ERR_CHARGE_NOT_ON_LEASE`."
    PRD 2.9 rule 12: "At plan-creation time, a `first_installment_date` that is not
    strictly after today, or an `installment_count` outside the permitted range, yields
    the dedicated `ERR_INVALID_INSTALLMENT_SCHEDULE`."

    Design: Difficulty/priority_pair_validation_conflict/plan_referential_beats_temporal
    """
    ctx = setup_property_tenant_lease()
    lease1 = ctx["lease"]
    # Second ACTIVE lease on another unit holding the foreign charge.
    from test_helpers import create_lease
    lease2 = create_lease(ctx["property"]["id"], ctx["tenant"]["id"], unit_label="102", activate=True)
    foreign = add_charge(lease2["id"], kind="DAMAGE_FEE", amount_cents=30000)

    lv = lease_version(lease1["id"])
    response = api.create_payment_plan(
        create_payment_plan_payload(
            lease1["id"], [foreign["id"]], lv,
            installment_count=3, first_installment_date="2026-07-01",
        ),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_CHARGE_NOT_ON_LEASE)


def test_plan_self_approval_segregation_rejected(api):
    """PRD 3.8: "Approval is a segregated duty: a `PropertyManager` moves the plan
    from `DRAFT` to `ACTIVE` — approving from any other status is rejected with
    `ERR_PLAN_INVALID_TRANSITION` — but the approver's `X-User-ID` must differ from
    the plan's `drafted_by_user_id`, or the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/plan_self_approval_segregation_rejected
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    pm1 = make_property_manager_headers("pm-1")
    lv = lease_version(lease_id)
    plan = validate_success(
        api.create_payment_plan(create_payment_plan_payload(lease_id, [charge["id"]], lv), pm1), 201
    )
    assert plan["drafted_by_user_id"] == "pm-1"

    response = api.transition_payment_plan(plan["id"], {"action": "APPROVE"}, pm1)
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    approved = validate_success(
        api.transition_payment_plan(plan["id"], {"action": "APPROVE"}, make_property_manager_headers("pm-2"))
    )
    assert approved["status"] == "ACTIVE"


def test_plan_approval_blocked_by_served_notice(api):
    """PRD 3.8: "Approval is also blocked while any notice on the lease stands
    `SERVED`, rejected with `ERR_ACTIVE_NOTICE_BLOCKS_PLAN`."
    PRD 3.6: "The notice duty examines notices in `ISSUED` or `SERVED` status. A
    notice whose covered charges all show zero outstanding, while the current date is
    still on or before its `cure_deadline_date`, transitions to `CURED` — this holds
    whether the notice was merely `ISSUED` or already `SERVED`."

    Design: Difficulty/cross_entity_state_dependency/plan_approval_blocked_by_served_notice
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    rent = add_charge(lease_id, amount_cents=200000)
    damage = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    notice = create_notice(lease_id, [damage["id"]])
    issue_notice(notice["id"])
    set_clock("2026-08-02T00:00:00Z")
    served = serve_notice(notice["id"], "PERSONAL", "2026-08-02")
    assert served["status"] == "SERVED"

    plan = create_plan(lease_id, [rent["id"]], installment_count=2)
    assert plan["scheduled_total_cents"] == 202500

    response = api.transition_payment_plan(plan["id"], {"action": "APPROVE"}, PM)
    validate_error(response, ApiErrorId.ERR_ACTIVE_NOTICE_BLOCKS_PLAN)

    # Pay the full outstanding (rent 200000 + damage 10000 + setup fee 2500), then sweep.
    payment = record_payment(lease_id, ctx["tenant"]["id"], channel="CARD", amount_cents=212500, received_date="2026-08-02")
    post_payment(payment["id"])
    report = run_sweep()
    assert report["notices_cured_count"] == 1

    approved = approve_plan(plan["id"])
    assert approved["status"] == "ACTIVE"


def test_plan_defaults_after_second_missed_installment(api):
    """PRD 3.6: "The plan's `missed_installment_count` is the number of installments
    marked `MISSED`: when two or more installments are missed, the plan flips from
    `ACTIVE` to `DEFAULTED` and records the current date as its `defaulted_date`, which
    anchors the cooling-off rule of §3.8."

    Design: Corner/calculations/plan_defaults_after_second_missed_installment
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    plan = create_plan(lease_id, [charge["id"]], installment_count=2, first_installment_date="2026-08-05")
    approve_plan(plan["id"])

    set_clock("2026-08-06T00:00:00Z")
    report1 = run_sweep()
    assert report1["installments_marked_missed_count"] == 1
    assert report1["plans_defaulted_count"] == 0, "The default threshold is 2 missed installments, not 1"

    set_clock("2026-09-06T00:00:00Z")
    report2 = run_sweep()
    assert report2["installments_marked_missed_count"] == 1
    assert report2["plans_defaulted_count"] == 1

    read_back = get_plan(plan["id"])
    assert read_back["status"] == "DEFAULTED"
    assert read_back["defaulted_date"] == "2026-09-06"


def test_plan_cured_when_schedule_fully_covered(api):
    """PRD 3.6: "The money counted toward the plan is the net applied cents — `APPLY`
    allocations minus `REVERSE` allocations — landing on the plan's covered charges
    from payments whose `posted_date` is on or after the plan's activation date. An
    installment is marked `PAID` when that running total reaches at least the
    cumulative scheduled amount through that installment; otherwise it is marked
    `MISSED` when the current date has passed its due date; otherwise it remains
    `PENDING`. ... When every installment is `PAID`, the plan flips from `ACTIVE` to
    `CURED`."

    Design: Corner/calculations/plan_cured_when_schedule_fully_covered
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    plan = create_plan(lease_id, [charge["id"]], installment_count=2, first_installment_date="2026-08-15")
    approve_plan(plan["id"])

    set_clock("2026-08-10T00:00:00Z")
    payment = record_payment(lease_id, ctx["tenant"]["id"], channel="CARD", amount_cents=10000, received_date="2026-08-10")
    post_payment(payment["id"])

    set_clock("2026-08-16T00:00:00Z")
    report = run_sweep()
    assert report["plans_cured_count"] == 1

    read_back = get_plan(plan["id"])
    assert read_back["status"] == "CURED"
    assert all(i["status"] == "PAID" for i in read_back["installments"])


def test_plan_cooling_off_window_boundary(api):
    """PRD 3.8: "At most one plan per lease may be `ACTIVE` — drafting while an active
    plan exists is rejected with `ERR_PLAN_EXISTS` — and a lease whose previous plan
    defaulted is under a cooling-off period: while the number of days since that plan's
    `defaulted_date` remains less than the property's `plan_cooling_off_days`, a new
    plan is rejected with `ERR_PLAN_COOLING_OFF`."

    Design: Corner/validations/plan_cooling_off_window_boundary
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    plan = create_plan(lease_id, [charge["id"]], installment_count=2, first_installment_date="2026-08-05")
    approve_plan(plan["id"])

    set_clock("2026-08-06T00:00:00Z")
    run_sweep()
    set_clock("2026-09-06T00:00:00Z")
    report = run_sweep()
    assert report["plans_defaulted_count"] == 1, "Plan 1 must default on 2026-09-06 after two missed installments"

    # 14 days into the 30-day cooling-off window: rejected.
    set_clock("2026-09-20T00:00:00Z")
    lv = lease_version(lease_id)
    response = api.create_payment_plan(
        create_payment_plan_payload(lease_id, [charge["id"]], lv, installment_count=2, first_installment_date="2026-09-25"),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_PLAN_COOLING_OFF)

    # Exactly 30 days after the 2026-09-06 default: the strict < window has elapsed.
    set_clock("2026-10-06T00:00:00Z")
    lv3 = lease_version(lease_id)
    created = validate_success(
        api.create_payment_plan(
            create_payment_plan_payload(lease_id, [charge["id"]], lv3, installment_count=2, first_installment_date="2026-10-15"),
            AGENT,
        ),
        201,
    )
    assert created["status"] == "DRAFT"


def test_occ_plan_create_stale_version_rejected(api):
    """PRD 2.8: "Exactly two write operations participate in optimistic concurrency
    control: drafting a delinquency notice and drafting a payment plan. Each of these
    creation requests must carry `expected_lease_version`, a non-optional field holding
    the `version` of the target lease as the client last observed it. If the lease's
    current `version` no longer matches — because another writer has advanced it since
    the client last read the lease — the creation is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_plan_create_stale_version_rejected
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)
    lv = lease_version(lease_id)

    first = validate_success(
        api.create_payment_plan(create_payment_plan_payload(lease_id, [charge["id"]], lv), AGENT), 201
    )
    assert first["status"] == "DRAFT"

    response = api.create_payment_plan(
        create_payment_plan_payload(lease_id, [charge["id"]], lv, installment_count=3, first_installment_date="2026-08-20"),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)

    from test_helpers import list_plans
    plans = list_plans(lease_id)
    assert len(plans) == 1
    assert plans[0]["status"] == "DRAFT", "The rejected creation must neither cancel nor create anything"


def test_supersede_cancels_existing_draft_plan(api):
    """PRD 3.8: "Like notice drafting, plan drafting is create-with-supersede: any
    existing `DRAFT` plan on the lease moves to `CANCELLED` with `cancel_reason`
    `SUPERSEDED`, and the lease's `version` increments."

    Design: Corner/cross_cutting_layers/supersede_cancels_existing_draft_plan
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    p1 = create_plan(lease_id, [charge["id"]])
    p2 = create_plan(lease_id, [charge["id"]], installment_count=3, first_installment_date="2026-08-20")

    first = get_plan(p1["id"])
    second = get_plan(p2["id"])
    assert first["status"] == "CANCELLED"
    assert first["cancel_reason"] == "SUPERSEDED"
    assert second["status"] == "DRAFT"


def test_installment_split_monthly_due_dates(api):
    """PRD 3.8: "The installments are embedded on the plan as an `installments`
    schedule of entries carrying a `sequence_number`, a `due_date`, an `amount_cents`,
    and a `status` of `PENDING`, `PAID`, or `MISSED`; the first falls due on
    `first_installment_date` and each subsequent installment one calendar month after
    the previous one."

    Design: Difficulty/combinatorial_formula/installment_split_rounding_order
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    plan = create_plan(lease_id, [charge["id"]], installment_count=3, first_installment_date="2026-08-15")
    read_back = get_plan(plan["id"])
    installments = read_back["installments"]
    assert [i["due_date"] for i in installments] == ["2026-08-15", "2026-09-15", "2026-10-15"], (
        "Each subsequent installment falls due one calendar month after the previous one"
    )
    assert all(i["status"] == "PENDING" for i in installments), (
        "New installments begin PENDING until the sweep evaluates them"
    )
    assert [i["sequence_number"] for i in installments] == [1, 2, 3]


def test_payment_cycle_representment_reallocates_live_ledger(api):
    """PRD 3.4: "Re-presentment — requesting the posting transition again on a
    `RETURNED` payment — is permitted once the lease is `ACTIVE` and the payment clears
    the same two acceptance rules against the current outstanding. The waterfall then
    re-runs against the live ledger rather than the original target set; in particular,
    the returned-payment fee charge created by the earlier return is itself a
    fee-class target waiting to be satisfied. The payment records the new `posted_date`
    and returns to `POSTED`, completing the cycle `POSTED` → `RETURNED` → `POSTED`,
    which may repeat for as long as the bank keeps returning the item."

    Design: Difficulty/non_linear_state_machine/payment_posted_returned_posted_cycle
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    payment = record_and_post_payment(lease_id, ctx["tenant"]["id"], channel="ACH", amount_cents=200000)

    set_clock("2026-08-03T00:00:00Z")
    return_payment(payment["id"], nsf_fee_cents=3000)
    set_clock("2026-08-04T00:00:00Z")
    reposted = post_payment(payment["id"])

    # The second run's order-1 allocation lands on the NSF fee, not the original rent target.
    from test_helpers import list_allocations, list_charges
    nsf = list_charges(lease_id, params={"kind": "NSF_FEE"})[0]
    run2 = [a for a in list_allocations(params={"payment_id": payment["id"]})
            if a["direction"] == "APPLY" and a["charge_id"] == nsf["id"]]
    assert len(run2) == 1 and run2[0]["amount_cents"] == 3000 and run2[0]["allocation_order"] == 1, (
        "Re-presentment pays the live NSF fee first under FEES_FIRST, not the original target set"
    )
    assert reposted["posted_date"] == "2026-08-04"


def test_plan_referential_beats_temporal_notice_path(api):
    """PRD 2.9: "Every request is evaluated against an ordered validation pipeline.
    The first failing check produces the error response; later checks are not
    evaluated."
    PRD 2.9 rule 9: "Every element of `charge_ids` must belong to the lease the
    request targets, and a dispute's charge must belong to the dispute's lease;
    otherwise `ERR_CHARGE_NOT_ON_LEASE`."
    PRD 3.7: "Every element of `charge_ids` must belong to the named lease; a charge
    from another lease is rejected with `ERR_CHARGE_NOT_ON_LEASE`."

    Design: Difficulty/priority_pair_validation_conflict/plan_referential_beats_temporal
    """
    from test_helpers import create_lease, create_notice_payload
    ctx = setup_property_tenant_lease()
    lease1 = ctx["lease"]
    lease2 = create_lease(ctx["property"]["id"], ctx["tenant"]["id"], unit_label="102", activate=True)
    foreign = add_charge(lease2["id"], kind="DAMAGE_FEE", amount_cents=30000)

    lv = lease_version(lease1["id"])
    response = api.create_notice(create_notice_payload(lease1["id"], [foreign["id"]], lv), PM)
    validate_error(response, ApiErrorId.ERR_CHARGE_NOT_ON_LEASE)


def test_plan_approval_blocked_gate_reads_notice_state(api):
    """PRD 3.8: "Approval is also blocked while any notice on the lease stands
    `SERVED`, rejected with `ERR_ACTIVE_NOTICE_BLOCKS_PLAN`."
    PRD 3.7: "From there the notice awaits the sweep's verdict — `CURED` if the debt
    clears in time, `EXPIRED` if it does not — while a draft that never issued may
    still be cancelled, its `cancel_reason` reading `SUPERSEDED` when a newer draft
    replaced it or `MOVE_OUT` when the lease ended beneath it."

    Design: Difficulty/cross_entity_state_dependency/plan_approval_blocked_by_served_notice
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    rent = add_charge(lease_id, amount_cents=200000)
    damage = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    notice = create_notice(lease_id, [damage["id"]])
    issue_notice(notice["id"])
    set_clock("2026-08-02T00:00:00Z")
    serve_notice(notice["id"], "PERSONAL", "2026-08-02")

    plan = create_plan(lease_id, [rent["id"]], installment_count=2)
    response = api.transition_payment_plan(plan["id"], {"action": "APPROVE"}, PM)
    validate_error(response, ApiErrorId.ERR_ACTIVE_NOTICE_BLOCKS_PLAN)

    # Let the SERVED notice expire past its cure deadline; approval is still blocked
    # while a notice stands SERVED, but once it leaves SERVED the gate opens.
    set_clock("2026-08-12T00:00:00Z")
    report = run_sweep()
    assert report["notices_expired_count"] == 1
    from test_helpers import list_notices
    assert list_notices(lease_id)[0]["status"] == "EXPIRED"

    approved = approve_plan(plan["id"])
    assert approved["status"] == "ACTIVE"
