"""Ownership disputes: forked resolutions, uniqueness guards, filer-scoped
withdrawal, terminal lockdown, and the 7-day review SLA checkpoint."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    create_account,
    create_assignment,
    create_geo_rule,
    create_plan,
    create_rep,
    add_territory,
    activate_territory,
    open_plan,
    file_dispute,
    get_account,
    get_dispute,
    get_territory,
    make_manager_headers,
    make_sales_rep_headers,
    set_clock,
    setup_two_territory_communicated,
    validate_error,
    validate_paginated,
    validate_success,
    walk_to_communicated,
)

MGR = make_manager_headers("mgr-1")


def _setup_two_disputes_under_review(api):
    """Plan COMMUNICATED; TX owns accounts A1 and A2 via a GEO rule; TY staffed
    by rep R, who files both disputes claiming TY; both UNDER_REVIEW."""
    ns = setup_two_territory_communicated(label="FY27-DSP", owner_name="TX",
                                          claimant_name="TY",
                                          account_potential=60000)
    plan_id = ns["plan"]["id"]
    acc2 = create_account(plan_id, name="A2", annual_potential_cents=60000)
    d1 = file_dispute(plan_id, ns["acc"]["id"], ns["ty"]["id"],
                      ns["rep"]["id"], reason="named in CRM")
    d2 = file_dispute(plan_id, acc2["id"], ns["ty"]["id"], ns["rep"]["id"],
                      reason="named in CRM")
    validate_success(api.start_dispute_review(d1["id"], MGR), 200)
    validate_success(api.start_dispute_review(d2["id"], MGR), 200)
    ns["acc2"] = acc2
    ns["d1"] = d1
    ns["d2"] = d2
    ns["tx_before"] = get_territory(ns["tx"]["id"])
    ns["ty_before"] = get_territory(ns["ty"]["id"])
    return ns


def test_dispute_upheld_reassigns_without_moving_quota(api):
    """PRD: "Upholding moves the dispute to `RESOLVED_UPHELD` and reassigns the
    account: its `assigned_territory_id` becomes the claimant territory, its
    `assignment_source` becomes `DISPUTE_RESOLUTION`, and its
    `assignment_rule_id` clears to null; deliberately, no quota moves with a
    dispute resolution — `final_quota_cents` and `assigned_quota_cents` stand
    unchanged on both territories — and only future bookings route to the
    claimant territory's reps."

    Design: Difficulty/non_linear_state_machine/dispute_fork_divergent_side_effects
    """
    ns = _setup_two_disputes_under_review(api)
    resolved = validate_success(
        api.resolve_dispute(ns["d1"]["id"], "UPHELD", MGR), 200)
    assert resolved["status"] == "RESOLVED_UPHELD"

    acc = get_account(ns["acc"]["id"])
    assert acc["assigned_territory_id"] == ns["ty"]["id"]
    assert acc["assignment_source"] == "DISPUTE_RESOLUTION"
    assert acc["assignment_rule_id"] is None

    tx_after = get_territory(ns["tx"]["id"])
    ty_after = get_territory(ns["ty"]["id"])
    assert tx_after["final_quota_cents"] == ns["tx_before"]["final_quota_cents"], \
        "disputes never move quota"
    assert ty_after["final_quota_cents"] == ns["ty_before"]["final_quota_cents"]
    assert tx_after["assigned_quota_cents"] == \
        ns["tx_before"]["assigned_quota_cents"]
    assert ty_after["assigned_quota_cents"] == \
        ns["ty_before"]["assigned_quota_cents"]


def test_dispute_overruled_leaves_account_untouched(api):
    """PRD: "Overruling moves the dispute to `RESOLVED_OVERRULED` and changes
    nothing about the account."

    The fork's other arm: identical review shape, no account side effect —
    A2 stays on TX with source GEO_RULE and its rule id intact.

    Design: Difficulty/non_linear_state_machine/dispute_fork_divergent_side_effects
    """
    ns = _setup_two_disputes_under_review(api)
    resolved = validate_success(
        api.resolve_dispute(ns["d2"]["id"], "OVERRULED", MGR), 200)
    assert resolved["status"] == "RESOLVED_OVERRULED"

    acc = get_account(ns["acc2"]["id"])
    assert acc["assigned_territory_id"] == ns["tx"]["id"]
    assert acc["assignment_source"] == "GEO_RULE"
    assert acc["assignment_rule_id"] == ns["rule"]["id"]
    assert get_territory(ns["tx"]["id"])["final_quota_cents"] == \
        ns["tx_before"]["final_quota_cents"]
    assert get_territory(ns["ty"]["id"])["final_quota_cents"] == \
        ns["ty_before"]["final_quota_cents"]


def test_dispute_already_open_rejected(api):
    """PRD: "the account may have at most one open dispute — one in `FILED`,
    `UNDER_REVIEW`, or `ESCALATED` — a second filing failing with
    `ERR_DISPUTE_ALREADY_OPEN`."

    Design: Corner/validations/dispute_already_open_rejected
    """
    ns = setup_two_territory_communicated(label="FY27-DUP")
    plan_id = ns["plan"]["id"]
    d1 = file_dispute(plan_id, ns["acc"]["id"], ns["ty"]["id"],
                      ns["rep"]["id"], reason="first")
    resp = api.create_dispute(
        {"plan_year_id": plan_id, "account_id": ns["acc"]["id"],
         "claimant_territory_id": ns["ty"]["id"], "reason": "second"},
        make_sales_rep_headers(ns["rep"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN, 409)
    data, meta = validate_paginated(api.list_disputes(
        ADMIN, params={"account_id": ns["acc"]["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == d1["id"]


def test_dispute_claimant_is_current_owner_rejected(api):
    """PRD: "it must differ from the account's current territory, since
    claiming what you already own is `ERR_CLAIMANT_TERRITORY_INVALID`"

    Design: Corner/validations/dispute_claimant_is_current_owner_rejected
    """
    plan = create_plan(label="FY27-OWN")
    plan_id = plan["id"]
    tx = add_territory(plan_id, name="TX")
    activate_territory(tx["id"])
    open_plan(plan_id)
    rep = create_rep()
    create_assignment(plan_id, rep["id"], tx["id"])
    create_geo_rule(plan_id, tx["id"])
    acc = create_account(plan_id, name="A")
    walk_to_communicated(plan_id)

    resp = api.create_dispute(
        {"plan_year_id": plan_id, "account_id": acc["id"],
         "claimant_territory_id": tx["id"], "reason": "already mine"},
        make_sales_rep_headers(rep["id"]))
    validate_error(resp, ApiErrorId.ERR_CLAIMANT_TERRITORY_INVALID, 422)


def test_dispute_withdraw_terminal_lockdown(api):
    """PRD: "The filer may also walk away: withdrawing — permitted only to the
    rep whose id matches `filed_by_rep_id`, anyone else drawing
    `ERR_FORBIDDEN_FOR_ROLE` — moves a dispute to `WITHDRAWN` from `FILED`,
    from `UNDER_REVIEW`, or from `ESCALATED` alike."
    PRD: "Then the entity's own from-state is checked against the requested
    transition (`ERR_INVALID_STATE_TRANSITION`)"

    A WITHDRAWN dispute is terminal: start-review afterwards is rejected.

    Design: Corner/state_machines/dispute_withdraw_terminal_lockdown
    """
    ns = setup_two_territory_communicated(label="FY27-WD")
    dispute = file_dispute(ns["plan"]["id"], ns["acc"]["id"], ns["ty"]["id"],
                           ns["rep"]["id"], reason="mine")
    withdrawn = validate_success(api.withdraw_dispute(
        dispute["id"], make_sales_rep_headers(ns["rep"]["id"])), 200)
    assert withdrawn["status"] == "WITHDRAWN"

    validate_error(api.start_dispute_review(dispute["id"], MGR),
                   ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
    assert get_dispute(dispute["id"])["status"] == "WITHDRAWN"


def test_sla_escalation_day7_not_day8_boundary(api):
    """PRD: "A dispute still in `FILED` status whose `filed_date` lies strictly
    more than seven days before the current logical date is overdue: a dispute
    filed on a given day is not escalated on the seventh day after filing and
    is escalated from the eighth day after filing onward."
    PRD: "The checkpoint answers with an `escalated_count` and the
    `escalated_dispute_ids`, ordered by dispute creation timestamp ascending."

    Filed 2027-02-10: the processor at 2027-02-17 (exactly +7) escalates
    nothing; at 2027-02-18 (+8) it escalates the dispute.

    Design: Corner/calculations/sla_escalation_day7_not_day8_boundary
    """
    ns = setup_two_territory_communicated(label="FY27-SLA",
                                          lock_date="2027-12-15")
    plan_id = ns["plan"]["id"]
    set_clock("2027-02-10T09:00:00Z")
    dispute = file_dispute(plan_id, ns["acc"]["id"], ns["ty"]["id"],
                           ns["rep"]["id"], reason="mine")
    assert dispute["status"] == "FILED"

    set_clock("2027-02-17T23:59:00Z")
    result1 = validate_success(api.process_dispute_slas(plan_id, MGR), 200)
    assert result1["escalated_count"] == 0
    assert get_dispute(dispute["id"])["status"] == "FILED", \
        "strictly-greater comparison: day +7 does not escalate"

    set_clock("2027-02-18T00:00:00Z")
    result2 = validate_success(api.process_dispute_slas(plan_id, MGR), 200)
    assert result2["escalated_count"] == 1
    assert result2["escalated_dispute_ids"] == [dispute["id"]]
    assert get_dispute(dispute["id"])["status"] == "ESCALATED"
