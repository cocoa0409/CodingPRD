"""Territory hierarchy: creation defaults, guards on retire, cycle check,
computed-field rejection, and not-found handling."""
from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_territory,
    add_territory,
    assert_territory,
    create_account,
    create_assignment,
    create_geo_rule,
    create_plan,
    create_rep,
    create_territory_payload,
    get_territory,
    open_plan,
    setup_open_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_territory_create_initial_state(api):
    """PRD: "Territories may be created at any point before the plan is locked
    and are born in `DRAFT`."
    PRD: "Each territory also carries two computed money fields:
    `assigned_quota_cents`, the top-down quota landed on it by the latest
    applied allocation scoped at the territory itself or at its parent, null
    until any allocation has landed; and `final_quota_cents`, the reconciled
    quota written by the latest applied reconciliation run and later adjusted
    by mid-year quota transfers, null until reconciliation."

    Potential zero is legal ("a market-potential estimate `potential_cents`
    that may be zero but never negative").

    Design: Corner/entities/territory_create_initial_state
    """
    plan = create_plan(label="FY27")
    root = validate_success(api.create_territory(
        create_territory_payload(plan["id"], name="ROOT", potential_cents=0,
                                 headcount_capacity=2), ADMIN), 201)
    assert_territory(root)
    assert root["status"] == "DRAFT"
    assert root["assigned_quota_cents"] is None
    assert root["final_quota_cents"] is None
    assert root["version"] == 1

    child = validate_success(api.create_territory(
        create_territory_payload(plan["id"], name="CHILD", potential_cents=500,
                                 headcount_capacity=2,
                                 parent_territory_id=root["id"]), ADMIN), 201)
    assert child["parent_territory_id"] == root["id"]
    assert child["plan_year_id"] == plan["id"]


def test_get_nonexistent_territory_returns_not_found(api):
    """PRD: "Tier three checks existence: path identifiers first, then the
    foreign-key identifiers in the request body, each missing reference
    producing `ERR_NOT_FOUND`"

    Design: Corner/entities/get_nonexistent_territory_returns_not_found
    """
    validate_error(api.get_territory(NON_EXISTENT_UUID, ADMIN),
                   ApiErrorId.ERR_NOT_FOUND, 404)


def test_computed_or_unknown_field_in_input_rejected(api):
    """PRD: "Independently of this ordering, requests that are malformed at the
    body level fail with `ERR_INVALID_REQUEST` (HTTP 400): unparseable bodies,
    unknown or server-computed fields supplied by the client, invalid enum
    values, negative numbers where only non-negative values are allowed, bad
    date formats, a booking date in the future, violated conditional-field
    rules on assignment rules, or an invalid end window supplied when
    terminating an assignment."

    Sending the server-computed `assigned_quota_cents` in a create body is
    rejected and no territory is persisted.

    Design: Corner/entities/computed_or_unknown_field_in_input_rejected
    """
    plan = create_plan(label="FY27")
    payload = create_territory_payload(plan["id"], name="T")
    payload["assigned_quota_cents"] = 999
    validate_error(api.create_territory(payload, ADMIN),
                   ApiErrorId.ERR_INVALID_REQUEST, 400)
    data, meta = validate_paginated(
        api.list_territories(ADMIN, params={"plan_year_id": plan["id"]}))
    assert meta["total_count"] == 0 and data == []


def test_territory_retire_terminal_lockdown(api):
    """PRD: "`RETIRED` is terminal."
    PRD: "Then the entity's own from-state is checked against the requested
    transition (`ERR_INVALID_STATE_TRANSITION`)"

    A successfully retired territory cannot be retired again.

    Design: Corner/state_machines/territory_retire_terminal_lockdown
    """
    base = setup_open_plan(label="FY27")
    t = base["t"]
    retired = validate_success(api.retire_territory(t["id"], ADMIN), 200)
    assert retired["status"] == "RETIRED"
    validate_error(api.retire_territory(t["id"], ADMIN),
                   ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)


def test_territory_retire_blocked_by_account_rejected(api):
    """PRD: "no account in the plan is currently assigned to the territory
    (`ERR_TERRITORY_HAS_ACCOUNTS`)"

    Design: Corner/state_machines/territory_retire_blocked_by_account_rejected
    """
    plan = create_plan(label="FY27")
    t = add_territory(plan["id"], name="T")
    activate_territory(t["id"])
    create_geo_rule(plan["id"], t["id"])
    create_account(plan["id"], name="A")
    validate_error(api.retire_territory(t["id"], ADMIN),
                   ApiErrorId.ERR_TERRITORY_HAS_ACCOUNTS, 409)
    assert get_territory(t["id"])["status"] == "ACTIVE"


def test_territory_retire_blocked_by_active_assignment_rejected(api):
    """PRD: "no rep assignment on it is `ACTIVE`
    (`ERR_TERRITORY_HAS_ACTIVE_ASSIGNMENTS`)"

    Design: Corner/state_machines/territory_retire_blocked_by_active_assignment_rejected
    """
    base = setup_open_plan(label="FY27")
    plan_id = base["plan"]["id"]
    rep = create_rep()
    create_assignment(plan_id, rep["id"], base["t"]["id"])
    validate_error(api.retire_territory(base["t"]["id"], ADMIN),
                   ApiErrorId.ERR_TERRITORY_HAS_ACTIVE_ASSIGNMENTS, 409)
    assert get_territory(base["t"]["id"])["status"] == "ACTIVE"


def test_territory_retire_blocked_by_children_rejected(api):
    """PRD: "Retirement moves an `ACTIVE` territory to `RETIRED` while the plan
    is `DRAFT` or `OPEN` under those same two guards plus a third — every child
    territory must already be `RETIRED`, or the retire fails with
    `ERR_TERRITORY_HAS_CHILDREN`."

    Design: Corner/state_machines/territory_retire_blocked_by_children_rejected
    """
    plan = create_plan(label="FY27")
    parent = add_territory(plan["id"], name="P")
    child = add_territory(plan["id"], name="C",
                          parent_territory_id=parent["id"])
    activate_territory(parent["id"])
    activate_territory(child["id"])
    open_plan(plan["id"])

    validate_error(api.retire_territory(parent["id"], ADMIN),
                   ApiErrorId.ERR_TERRITORY_HAS_CHILDREN, 409)
    assert get_territory(parent["id"])["status"] == "ACTIVE"

    retired_child = validate_success(api.retire_territory(child["id"], ADMIN),
                                     200)
    assert retired_child["status"] == "RETIRED"
    retired_parent = validate_success(
        api.retire_territory(parent["id"], ADMIN), 200)
    assert retired_parent["status"] == "RETIRED"


def test_territory_reparent_cycle_rejected(api):
    """PRD: "every re-parent runs a cycle check: placing a territory beneath
    itself or one of its own descendants is rejected with
    `ERR_TERRITORY_CYCLE`."

    Re-parenting A under its own child B is rejected and A stays parentless.

    Design: Corner/validations/territory_reparent_cycle_rejected
    """
    plan = create_plan(label="FY27")
    a = add_territory(plan["id"], name="A")
    b = add_territory(plan["id"], name="B", parent_territory_id=a["id"])
    validate_error(
        api.patch_territory(a["id"], {"parent_territory_id": b["id"]}, ADMIN),
        ApiErrorId.ERR_TERRITORY_CYCLE, 409)
    assert get_territory(a["id"])["parent_territory_id"] is None
