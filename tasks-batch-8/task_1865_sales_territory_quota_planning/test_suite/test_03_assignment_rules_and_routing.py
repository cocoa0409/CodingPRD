"""Assignment rules and account routing: named vs GEO resolution, specificity
ranking, inert rule changes, and the on-demand re-evaluation sweep."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    activate_territory,
    add_territory,
    create_account,
    create_account_payload,
    create_geo_rule,
    create_named_rule,
    create_plan,
    evaluate_assignments,
    get_account,
    open_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_account_create_evaluates_geo_rule(api):
    """PRD: "The moment an account is created, assignment resolution runs
    against the plan's `ACTIVE` rules."
    PRD: "the winner's `territory_id` becomes the account's
    `assigned_territory_id`, the source becomes `GEO_RULE`, and the winner's id
    is recorded."

    Design: Corner/entities/account_create_evaluates_geo_rule
    """
    plan = create_plan(label="FY27")
    t = add_territory(plan["id"], name="T")
    activate_territory(t["id"])
    rule = create_geo_rule(plan["id"], t["id"], priority=10,
                           country_code="US")
    acc = validate_success(api.create_account(
        create_account_payload(plan["id"], name="A", country_code="US",
                               segment="SMB", annual_potential_cents=50000),
        ADMIN), 201)
    assert acc["assigned_territory_id"] == t["id"]
    assert acc["assignment_source"] == "GEO_RULE"
    assert acc["assignment_rule_id"] == rule["id"]


def test_account_unassigned_when_no_rule_matches(api):
    """PRD: "When no candidate matches at all, the account's
    `assigned_territory_id` stays null and its source is `UNASSIGNED`, with no
    rule recorded."

    A Canadian account under a US-only rule set is not an error.

    Design: Corner/entities/account_unassigned_when_no_rule_matches
    """
    plan = create_plan(label="FY27")
    t = add_territory(plan["id"], name="T")
    activate_territory(t["id"])
    create_geo_rule(plan["id"], t["id"], priority=10, country_code="US")
    acc = validate_success(api.create_account(
        create_account_payload(plan["id"], name="CA-Co", country_code="CA",
                               segment="SMB", annual_potential_cents=50000),
        ADMIN), 201)
    assert acc["assigned_territory_id"] is None
    assert acc["assignment_source"] == "UNASSIGNED"
    assert acc["assignment_rule_id"] is None


def test_account_invalid_segment_returns_invalid_request(api):
    """PRD: "`segment` values, here and on accounts, are exactly `ENTERPRISE`,
    `MID_MARKET`, or `SMB`."
    PRD: "requests that are malformed at the body level fail with
    `ERR_INVALID_REQUEST` (HTTP 400): unparseable bodies, unknown or
    server-computed fields supplied by the client, invalid enum values,
    negative numbers where only non-negative values are allowed, bad date
    formats, a booking date in the future, violated conditional-field rules on
    assignment rules, or an invalid end window supplied when terminating an
    assignment."

    Design: Corner/entities/account_invalid_segment_returns_invalid_request
    """
    plan = create_plan(label="FY27")
    validate_error(api.create_account(
        create_account_payload(plan["id"], name="A", segment="MEGA"), ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_duplicate_named_rule_rejected(api):
    """PRD: "At most one `ACTIVE` `NAMED_ACCOUNT` rule may exist per account
    per plan — creating a second, or re-enabling a disabled one while another
    is active, fails with `ERR_DUPLICATE_NAMED_RULE`."

    The lower priority value on the second attempt does not displace the
    existing ACTIVE named rule.

    Design: Corner/validations/duplicate_named_rule_rejected
    """
    plan = create_plan(label="FY27")
    t1 = add_territory(plan["id"], name="T1")
    t2 = add_territory(plan["id"], name="T2")
    acc = create_account(plan["id"], name="A")
    create_named_rule(plan["id"], t1["id"], acc["id"], priority=5)
    validate_error(api.create_assignment_rule(
        {"plan_year_id": plan["id"], "rule_type": "NAMED_ACCOUNT",
         "priority": 1, "territory_id": t2["id"],
         "named_account_id": acc["id"]}, ADMIN),
        ApiErrorId.ERR_DUPLICATE_NAMED_RULE, 409)


def test_rule_disable_enable_cycle_controls_evaluation(api):
    """PRD: "Deliberately, neither creation nor enablement nor disablement ever
    re-evaluates accounts that already exist — rule changes are inert until an
    account is created or an explicit re-evaluation is requested."
    PRD: "The moment an account is created, assignment resolution runs against
    the plan's `ACTIVE` rules."

    A DISABLED rule is skipped by the sweep (account becomes UNASSIGNED);
    re-enabling plus a sweep restores the assignment.

    Design: Corner/state_machines/rule_disable_enable_cycle_controls_evaluation
    """
    plan = create_plan(label="FY27")
    t = add_territory(plan["id"], name="T")
    activate_territory(t["id"])
    open_plan(plan["id"])
    rule = create_geo_rule(plan["id"], t["id"], priority=10)
    acc = create_account(plan["id"], name="A")
    assert get_account(acc["id"])["assigned_territory_id"] == t["id"]

    disabled = validate_success(
        api.disable_assignment_rule(rule["id"], ADMIN), 200)
    assert disabled["status"] == "DISABLED"
    # The rule change alone never touches the existing account.
    assert get_account(acc["id"])["assigned_territory_id"] == t["id"]

    evaluate_assignments(plan["id"])
    after_disable = get_account(acc["id"])
    assert after_disable["assigned_territory_id"] is None
    assert after_disable["assignment_source"] == "UNASSIGNED"

    enabled = validate_success(api.enable_assignment_rule(rule["id"], ADMIN),
                               200)
    assert enabled["status"] == "ACTIVE"
    evaluate_assignments(plan["id"])
    after_enable = get_account(acc["id"])
    assert after_enable["assigned_territory_id"] == t["id"]
    assert after_enable["assignment_source"] == "GEO_RULE"


def test_evaluate_assignments_reevaluates_only_on_demand(api):
    """PRD: "Deliberately, neither creation nor enablement nor disablement ever
    re-evaluates accounts that already exist — rule changes are inert until an
    account is created or an explicit re-evaluation is requested."
    PRD: "Re-evaluation happens only at account creation or when an
    administrator explicitly re-runs resolution for the whole plan; that sweep
    re-evaluates every account regardless of how it was last assigned —
    including manually moved and dispute-resolved accounts — answers with
    `evaluated_count`, `reassigned_count`, and `still_unassigned_count`, and
    increments the plan's `version` by one."

    The more specific R2 {US, SMB} (specificity 2) beats R1 {US}
    (specificity 1) only once the sweep runs.

    Design: Corner/calculations/evaluate_assignments_reevaluates_only_on_demand
    """
    plan = create_plan(label="FY27")
    t1 = add_territory(plan["id"], name="T1")
    t2 = add_territory(plan["id"], name="T2")
    activate_territory(t1["id"])
    activate_territory(t2["id"])
    open_plan(plan["id"])
    create_geo_rule(plan["id"], t1["id"], priority=20, country_code="US")
    acc = create_account(plan["id"], name="A", country_code="US",
                         segment="SMB")
    assert get_account(acc["id"])["assigned_territory_id"] == t1["id"]
    r2 = create_geo_rule(plan["id"], t2["id"], priority=30,
                         country_code="US", segment="SMB")
    # Creating the more specific rule does not move the account by itself.
    assert get_account(acc["id"])["assigned_territory_id"] == t1["id"]

    result = validate_success(api.evaluate_assignments(plan["id"], ADMIN), 200)
    assert result["evaluated_count"] == 1
    assert result["reassigned_count"] == 1
    assert result["still_unassigned_count"] == 0
    after = get_account(acc["id"])
    assert after["assigned_territory_id"] == t2["id"]
    assert after["assignment_source"] == "GEO_RULE"
    assert after["assignment_rule_id"] == r2["id"]


def test_selector_named_rule_overrides_geo(api):
    """PRD: "The named pass runs first: if a `NAMED_ACCOUNT` rule pinned to
    this account exists, it wins unconditionally, the account's
    `assignment_source` becomes `NAMED_RULE`, and the winning rule's id is
    recorded in `assignment_rule_id`."

    The named pin beats a GEO rule of higher specificity and lower priority
    value.

    Design: Corner/cross_cutting_complexity_layers/selector_named_rule_overrides_geo
    """
    plan = create_plan(label="FY27")
    tn = add_territory(plan["id"], name="TN")
    tg = add_territory(plan["id"], name="TG")
    acc = create_account(plan["id"], name="A", country_code="US",
                         segment="ENTERPRISE")
    assert get_account(acc["id"])["assignment_source"] == "UNASSIGNED"
    create_geo_rule(plan["id"], tg["id"], priority=1, country_code="US",
                    segment="ENTERPRISE")
    rn = create_named_rule(plan["id"], tn["id"], acc["id"], priority=99)
    evaluate_assignments(plan["id"])
    after = get_account(acc["id"])
    assert after["assigned_territory_id"] == tn["id"]
    assert after["assignment_source"] == "NAMED_RULE"
    assert after["assignment_rule_id"] == rn["id"]


def test_selector_specificity_then_priority_then_created_at(api):
    """PRD: "Candidates are ranked by specificity — the count of non-null
    criteria, more specific first — then by `priority` with the lower value
    winning, then by rule creation timestamp, earliest first; the winner's
    `territory_id` becomes the account's `assigned_territory_id`, the source
    becomes `GEO_RULE`, and the winner's id is recorded."

    R2 {US, ENTERPRISE} prio 20 beats R1 {US} prio 5 (specificity dominates)
    and beats R3 {US, ENTERPRISE} prio 20 created later (creation-order
    tie-break).

    Design: Corner/cross_cutting_complexity_layers/selector_specificity_then_priority_then_created_at
    """
    plan = create_plan(label="FY27")
    t1 = add_territory(plan["id"], name="T1")
    t2 = add_territory(plan["id"], name="T2")
    t3 = add_territory(plan["id"], name="T3")
    create_geo_rule(plan["id"], t1["id"], priority=5, country_code="US")
    r2 = create_geo_rule(plan["id"], t2["id"], priority=20,
                         country_code="US", segment="ENTERPRISE")
    create_geo_rule(plan["id"], t3["id"], priority=20, country_code="US",
                    segment="ENTERPRISE")
    acc = validate_success(api.create_account(
        create_account_payload(plan["id"], name="A", country_code="US",
                               segment="ENTERPRISE"), ADMIN), 201)
    assert acc["assigned_territory_id"] == t2["id"]
    assert acc["assignment_rule_id"] == r2["id"]
    assert acc["assignment_source"] == "GEO_RULE"


def test_accounts_list_filters_by_territory_and_source(api):
    """PRD: "The account list can be filtered by `plan_year_id`,
    `assigned_territory_id`, `assignment_rule_id`, or `assignment_source`;
    filtering to `UNASSIGNED` is how coverage gaps are surfaced."

    Design: Corner/endpoints/accounts_list_filters_by_territory_and_source
    """
    plan = create_plan(label="FY27")
    t1 = add_territory(plan["id"], name="T1")
    activate_territory(t1["id"])
    open_plan(plan["id"])
    create_geo_rule(plan["id"], t1["id"], priority=10, country_code="US")
    a1 = create_account(plan["id"], name="A1", country_code="US")
    a2 = create_account(plan["id"], name="A2", country_code="BR")

    data, _ = validate_paginated(api.list_accounts(
        ADMIN, params={"assigned_territory_id": t1["id"]}))
    assert [row["id"] for row in data] == [a1["id"]]

    data, _ = validate_paginated(api.list_accounts(
        ADMIN, params={"plan_year_id": plan["id"],
                       "assignment_source": "UNASSIGNED"}))
    assert [row["id"] for row in data] == [a2["id"]]
