"""The separate-service versus shared-metering study and its reversal."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    assert_utility_connection,
    setup_intake_project, setup_feasibility_cleared_project, setup_permitted_project,
    add_utility_connection, read_project, setup_approved_change_order,
    DESIGN_LEAD, PLAN_CHECKER,
)


def test_metering_study_clamps_the_score_at_one_hundred(api):
    """PRD §3.3: "Forty points are added when the jurisdiction's `separate_meter_required`
    is true. Twenty-five points are added when the electrical headroom is negative, meaning
    the existing service genuinely cannot carry both dwellings. Twenty points are added when
    `unit_type` is `DETACHED_NEW`. Fifteen points are added when `bedrooms` is 2 or more.
    Ten points are then subtracted when the parcel's `existing_water_meter_size_in` is 1.0
    inch or larger, since an oversized meter argues for sharing. The resulting total is
    clamped into the range 0 through 100 and stored as `separation_score`."

    Design: Difficulty/combinatorial_formula/utility_separation_score_nested_clamp
    """
    ctx = setup_feasibility_cleared_project(
        api, pathway="STATUTORY_MINISTERIAL", occupied_parcel=True)
    connection = add_utility_connection(api, ctx["project"]["id"], "ELECTRIC")

    decided = validate_success(api.decide_utility_connection(connection["id"], {}, DESIGN_LEAD))

    assert_utility_connection(decided)
    assert decided["separation_score"] == 100, (
        "40 (separate meter required) + 25 (negative headroom) + 20 (detached) + 15 "
        "(two bedrooms) clamps to 100")
    assert decided["decision"] == "SEPARATE"


def test_separate_decision_costs_the_capacity_fee_plus_the_meter_set(api):
    """PRD §3.3: "A `SEPARATE` decision costs the jurisdiction's `utility_capacity_fee_cents`
    plus a flat 850,000 cents of builder work for the new meter set, and moves the record from
    `PENDING_DECISION` to `SEPARATE_APPROVED`."
    PRD §3.3: "Either way `separation_cost_cents` is stamped with the chosen branch's figure
    and the record's `version` rises by 1 — and because that figure feeds the permit fee, the
    two branches produce materially different permits."

    Design: Difficulty/combinatorial_formula/utility_separation_score_nested_clamp
    """
    ctx = setup_feasibility_cleared_project(
        api, pathway="STATUTORY_MINISTERIAL", occupied_parcel=True)
    connection = add_utility_connection(api, ctx["project"]["id"], "ELECTRIC")
    assert connection["status"] == "PENDING_DECISION"
    assert connection["separation_cost_cents"] == 0

    decided = validate_success(api.decide_utility_connection(connection["id"], {}, DESIGN_LEAD))

    assert decided["separation_cost_cents"] == 1_265_000, (
        "415000 capacity fee plus the flat 850000 meter set")
    assert decided["status"] == "SEPARATE_APPROVED"
    assert decided["version"] == connection["version"] + 1


def test_score_of_exactly_fifty_resolves_to_separate(api):
    """PRD §3.3: "A score of 50 or more resolves the `decision` to `SEPARATE`; a score of 49
    or below resolves it to `SHARED`. The threshold is inclusive: a score landing exactly on
    50 is a separate service."

    Design: Corner/calculations/separation_score_exactly_fifty_resolves_separate
    """
    ctx = setup_feasibility_cleared_project(
        api, pathway="LOCAL_ORDINANCE",
        property_overrides={"address_line": "77 Juniper Ln", "lot_sqft": 7_200,
                            "existing_dwelling_sqft": 1_500, "electrical_service_amps": 200,
                            "existing_water_meter_size_in": 1.0,
                            "pre_adu_value_cents": 75_000_000})
    assert ctx["screening"]["verdict"] == "PASS_WITH_CONDITIONS"
    connection = add_utility_connection(api, ctx["project"]["id"], "ELECTRIC")

    decided = validate_success(api.decide_utility_connection(connection["id"], {}, DESIGN_LEAD))

    assert decided["separation_score"] == 50, "0 + 25 + 20 + 15 - 10 lands exactly on 50"
    assert decided["decision"] == "SEPARATE"
    assert decided["separation_cost_cents"] == 1_100_000
    assert decided["status"] == "SEPARATE_APPROVED"


def test_override_replaces_the_decision_but_never_the_score(api):
    """PRD §3.3: "An operator may supply an optional `override_decision` of `SEPARATE` or
    `SHARED` with the study; when present it replaces the resolved `decision` outright, but
    it never replaces `separation_score`, which is always stamped from the scored expression
    regardless."
    PRD §3.3: "A `SHARED` decision costs a flat 220,000 cents for the submeter and moves the
    record from `PENDING_DECISION` to `SHARED_APPROVED`."

    Design: Corner/calculations/utility_override_replaces_decision_but_not_score
    """
    ctx = setup_feasibility_cleared_project(
        api, pathway="STATUTORY_MINISTERIAL", occupied_parcel=True)
    connection = add_utility_connection(api, ctx["project"]["id"], "WATER")

    decided = validate_success(api.decide_utility_connection(
        connection["id"], {"override_decision": "SHARED"}, DESIGN_LEAD))

    assert decided["separation_score"] == 100, "the score is stamped from the scored expression"
    assert decided["decision"] == "SHARED"
    assert decided["separation_cost_cents"] == 220_000
    assert decided["status"] == "SHARED_APPROVED"


def test_second_record_for_the_same_service_type_is_rejected(api):
    """PRD §3.3: "A project may hold at most one record per service type; asking for a second
    `WATER` record on the same project is rejected with `ERR_DUPLICATE_UTILITY_SERVICE`
    (HTTP 409)."
    PRD §3.3: "Each utility service the ADU needs gets its own record on the project — a
    `UtilityConnection` — opened by a `DesignLead` who names the `service_type` — `WATER`,
    `SEWER`, or `ELECTRIC`."

    Design: Corner/validations/duplicate_utility_service_type_returns_conflict
    """
    ctx = setup_intake_project(api)
    add_utility_connection(api, ctx["project"]["id"], "ELECTRIC")

    validate_error(
        api.create_utility_connection(ctx["project"]["id"], {"service_type": "ELECTRIC"},
                                      DESIGN_LEAD),
        ApiErrorId.ERR_DUPLICATE_UTILITY_SERVICE)

    water = validate_success(api.create_utility_connection(
        ctx["project"]["id"], {"service_type": "WATER"}, DESIGN_LEAD), 201)
    assert water["service_type"] == "WATER"

    rows, meta = validate_paginated(
        api.list_utility_connections(ctx["project"]["id"], DESIGN_LEAD))
    assert meta["total_count"] == 2


def test_metering_study_before_pathway_selection_is_rejected(api):
    """PRD §3.3: "It also may not run before the project has locked in a pathway: if
    `approved_pathway` is still null, the request is rejected with `ERR_PATHWAY_NOT_SELECTED`
    (HTTP 409)."
    PRD §3.3: "A newly opened record starts in `PENDING_DECISION` with its `decision` null,
    its `separation_score` at 0, and its `separation_cost_cents` at 0."

    Design: Corner/validations/decide_utility_before_pathway_returns_pathway_not_selected
    """
    ctx = setup_intake_project(api)
    connection = add_utility_connection(api, ctx["project"]["id"], "ELECTRIC")

    validate_error(api.decide_utility_connection(connection["id"], {}, DESIGN_LEAD),
                   ApiErrorId.ERR_PATHWAY_NOT_SELECTED)

    rows, _ = validate_paginated(
        api.list_utility_connections(ctx["project"]["id"], DESIGN_LEAD))
    unchanged = rows[0]
    assert unchanged["status"] == "PENDING_DECISION"
    assert unchanged["separation_score"] == 0
    assert unchanged["decision"] is None


def test_first_approved_change_order_reverts_a_separate_decision(api):
    """PRD §3.3: "When the first change order on a project is approved and it carries a
    non-zero `cost_delta_cents`, the metering study is invalidated by the scope change: every
    utility record of that project sitting in `SEPARATE_APPROVED` reverts to
    `PENDING_DECISION`, its `decision` returns to null, its `separation_score` and
    `separation_cost_cents` return to 0, and its `version` rises by 1."
    PRD §3.6: "Separately from that chain, if `approved_change_order_count` was 0 immediately
    before this approval and this change order's `cost_delta_cents` is not 0, the metering
    reversal described in §3.3 fires as well."

    Design: Corner/state_machines/first_approved_change_order_reverts_separate_utility_decision
    """
    ctx = setup_permitted_project(api, pathway="STATUTORY_MINISTERIAL", occupied_parcel=True)
    assert ctx["utility"]["status"] == "SEPARATE_APPROVED"
    assert ctx["utility"]["separation_cost_cents"] == 1_265_000

    approved = setup_approved_change_order(
        api, ctx, title="Relocate the subpanel",
        scope_items=["Move subpanel to the north wall"],
        cost_delta_cents=1_000_000, schedule_delta_days=2)

    reverted, _ = validate_paginated(
        api.list_utility_connections(ctx["project"]["id"], DESIGN_LEAD))
    connection = reverted[0]
    assert connection["status"] == "PENDING_DECISION"
    assert connection["decision"] is None
    assert connection["separation_score"] == 0
    assert connection["separation_cost_cents"] == 0

    assert approved["builder_fee_cents"] == 100_000
    project = read_project(api, ctx["project"]["id"])
    assert project["contract_price_current_cents"] == 29_100_000

    submittal = validate_success(api.get_permit_submittal(ctx["submittal"]["id"], PLAN_CHECKER))
    assert submittal["utility_component_cents"] == 1_265_000, (
        "the already-priced submittal keeps the fee it was stamped with")
