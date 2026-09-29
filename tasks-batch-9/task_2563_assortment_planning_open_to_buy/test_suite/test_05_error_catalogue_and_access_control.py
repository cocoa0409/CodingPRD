"""Error catalogue, access control, optimistic concurrency and immediate consistency.

Every test builds its own reference data from scratch and reasons only about
behaviour stated in PRD.md.
"""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    BUYER_HEADERS,
    CANONICAL,
    CANONICAL_M1_OTB_PLANNED_CENTS,
    CANONICAL_OPTION_SLOTS_TOTAL,
    CANONICAL_RECEIPT_BUDGET_CENTS,
    CANONICAL_TARGET_UNITS_PER_OPTION,
    DIRECTOR_USER_ID,
    NON_EXISTENT_UUID,
    PLANNER_USER_ID,
    ApiErrorId,
    activate_item,
    actuals_post_payload,
    adopt_item,
    approve_decision,
    approve_plan,
    assortment_item_payload,
    build_user_headers,
    chase_cancel_decision_payload,
    close_cycle,
    commit_commitment,
    create_category,
    create_department,
    create_store_cluster,
    create_vendor,
    create_vendor_authorization,
    get_commitment,
    get_cycle,
    get_item,
    get_month,
    get_option_plan,
    get_plan,
    get_size_curve_cells,
    department_payload,
    localization_overlay_payload,
    make_buyer_headers,
    make_director_headers,
    make_vendor_rep_headers,
    month_version,
    open_reforecast_cycle,
    open_season,
    option_plan_payload,
    post_receipt,
    propose_commitment,
    propose_decision,
    propose_item,
    receipt_commitment_payload,
    reforecast_payload,
    reject_decision,
    reject_plan,
    setup_plan_scenario,
    setup_reference_spine,
    ship_commitment,
    submit_plan,
    validate_error,
    validate_paginated,
    validate_success,
    vendor_payload,
)

M1_SPEC = dict(CANONICAL["month_1"])
M2_SPEC = dict(CANONICAL["month_2"])


def _single_month_approved(**kwargs):
    """An APPROVED plan with M1 LOCKED_PLAN, built entirely from scratch."""
    return setup_plan_scenario(month_specs=[dict(M1_SPEC)], approve=True, **kwargs)


def _two_month_approved(**kwargs):
    """An APPROVED plan with M1 and M2 LOCKED_PLAN, built entirely from scratch."""
    return setup_plan_scenario(
        month_specs=[dict(M1_SPEC), dict(M2_SPEC)], approve=True, **kwargs
    )


# ---------------------------------------------------------------------------
# Every addressed identifier answers with its own not-found code
# ---------------------------------------------------------------------------

NOT_FOUND_CASES = [
    ("get_department", ApiErrorId.ERR_DEPARTMENT_NOT_FOUND),
    ("get_category", ApiErrorId.ERR_CATEGORY_NOT_FOUND),
    ("get_store_cluster", ApiErrorId.ERR_STORE_CLUSTER_NOT_FOUND),
    ("get_vendor", ApiErrorId.ERR_VENDOR_NOT_FOUND),
    ("get_vendor_authorization", ApiErrorId.ERR_VENDOR_AUTHORIZATION_NOT_FOUND),
    ("get_category_plan", ApiErrorId.ERR_CATEGORY_PLAN_NOT_FOUND),
    ("get_plan_month", ApiErrorId.ERR_PLAN_MONTH_NOT_FOUND),
    ("get_option_plan", ApiErrorId.ERR_OPTION_PLAN_NOT_FOUND),
    ("get_assortment_item", ApiErrorId.ERR_ASSORTMENT_ITEM_NOT_FOUND),
    ("get_receipt_commitment", ApiErrorId.ERR_RECEIPT_COMMITMENT_NOT_FOUND),
    ("get_reforecast_cycle", ApiErrorId.ERR_REFORECAST_CYCLE_NOT_FOUND),
    ("get_chase_cancel_decision", ApiErrorId.ERR_CHASE_CANCEL_DECISION_NOT_FOUND),
    ("get_localization_overlay", ApiErrorId.ERR_LOCALIZATION_OVERLAY_NOT_FOUND),
]


@pytest.mark.parametrize(
    "getter_name,expected_error", NOT_FOUND_CASES, ids=[c[0] for c in NOT_FOUND_CASES]
)
def test_every_addressed_id_has_its_own_not_found_code(
    api, planner_headers, getter_name, expected_error
):
    """PRD §2.7: "Path identifiers are resolved first, left to right, and the first
    one that matches no row decides the response with that entity's own not-found
    code: `ERR_DEPARTMENT_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`,
    `ERR_STORE_CLUSTER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`,
    `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`, `ERR_CATEGORY_PLAN_NOT_FOUND`,
    `ERR_PLAN_MONTH_NOT_FOUND`, `ERR_OPTION_PLAN_NOT_FOUND`,
    `ERR_ASSORTMENT_ITEM_NOT_FOUND`, `ERR_RECEIPT_COMMITMENT_NOT_FOUND`,
    `ERR_REFORECAST_CYCLE_NOT_FOUND`, `ERR_CHASE_CANCEL_DECISION_NOT_FOUND` or
    `ERR_LOCALIZATION_OVERLAY_NOT_FOUND`, each returned with 404."

    Design: Corner/errors/every_addressed_id_has_its_own_not_found_code
    """
    # A populated reference spine proves the miss is about the addressed row and not
    # about an empty database.
    setup_reference_spine()

    response = getattr(api, getter_name)(NON_EXISTENT_UUID, planner_headers)
    validate_error(response, expected_error)


def test_not_found_codes_are_pairwise_distinct_and_real_ids_still_resolve(
    api, planner_headers
):
    """PRD §2.7: "Path identifiers are resolved first, left to right, and the first
    one that matches no row decides the response with that entity's own not-found
    code" — thirteen distinct codes, "each returned with 404."

    Design: Corner/errors/every_addressed_id_has_its_own_not_found_code
    """
    spine = setup_reference_spine()

    codes = []
    for getter_name, expected_error in NOT_FOUND_CASES:
        response = getattr(api, getter_name)(NON_EXISTENT_UUID, planner_headers)
        codes.append(validate_error(response, expected_error)["error_id"])

    assert len(set(codes)) == len(NOT_FOUND_CASES), (
        "each addressed entity must answer with its own not-found code, but the "
        f"observed codes were not pairwise distinct: {codes}"
    )

    # Real identifiers on the very same routes still resolve, so the 404s above are
    # keyed on the addressed row rather than on the route.
    department = validate_success(
        api.get_department(spine["department"]["id"], planner_headers)
    )
    assert department["code"] == "WAPP", (
        f"real department id must resolve, got code {department['code']}"
    )

    cluster = validate_success(
        api.get_store_cluster(spine["store_cluster"]["id"], planner_headers)
    )
    assert cluster["volume_tier"] == "A", (
        f"real store cluster id must resolve, got volume_tier {cluster['volume_tier']}"
    )

    authorization = validate_success(
        api.get_vendor_authorization(spine["authorization"]["id"], planner_headers)
    )
    assert authorization["status"] == "ACTIVE", (
        "real vendor authorization id must resolve to the ACTIVE row, got "
        f"{authorization['status']}"
    )


# ---------------------------------------------------------------------------
# Authentication runs before anything else, and before authorization
# ---------------------------------------------------------------------------

BAD_IDENTITY_HEADERS = {
    "empty_user_id": {"X-User-ID": "", "X-User-Role": "MerchandisePlanner"},
    "absent_user_id": {"X-User-Role": "MerchandisePlanner"},
    "empty_role": {"X-User-ID": PLANNER_USER_ID, "X-User-Role": ""},
    "absent_role": {"X-User-ID": PLANNER_USER_ID},
    "undeclared_role": {"X-User-ID": PLANNER_USER_ID, "X-User-Role": "MerchandiseKing"},
}


@pytest.mark.parametrize("identity_case", sorted(BAD_IDENTITY_HEADERS))
def test_missing_caller_identity_is_401_before_anything_else(api, identity_case):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting principal, and `X-User-Role`, declaring the capacity in which it acts."
    PRD §2.1: "If either header is absent or empty, or if `X-User-Role` is not one of
    the five declared role names, the request is rejected with `ERR_UNAUTHENTICATED`
    (401)."
    PRD §2.1: "The five roles are `MerchOpsAdmin`, `MerchandisePlanner`,
    `PlanningDirector`, `CategoryBuyer`, and `VendorRep`."

    Design: Corner/errors/missing_caller_identity_is_401_before_anything_else
    """
    spine = setup_reference_spine()

    response = api.get_department(
        spine["department"]["id"], BAD_IDENTITY_HEADERS[identity_case]
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_unauthenticated_outranks_not_found_and_unauthorized_role(api):
    """PRD §2.1: "If either header is absent or empty, or if `X-User-Role` is not one
    of the five declared role names, the request is rejected with
    `ERR_UNAUTHENTICATED` (401). If the role is declared but is not authorized for the
    endpoint being called, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (403).
    These two checks run before anything else in the system, in that order."
    PRD §2.8: "Implementers must not treat the checks below as an unordered set — a
    request that violates three of them returns the code of the lowest-numbered one."

    Design: Corner/errors/missing_caller_identity_is_401_before_anything_else
    """
    spine = setup_reference_spine()
    anonymous = {"X-User-ID": "", "X-User-Role": "MerchandisePlanner"}

    # An unknown department id would otherwise be ERR_DEPARTMENT_NOT_FOUND (404).
    validate_error(
        api.get_department(NON_EXISTENT_UUID, anonymous),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )

    # A CategoryBuyer is not authorized to create departments, but with an empty
    # `X-User-ID` the authentication check still decides first.
    validate_error(
        api.create_department(
            department_payload(code="ZZTP"),
            {"X-User-ID": "", "X-User-Role": "CategoryBuyer"},
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )

    # Once a non-empty identifier is supplied, the same buyer request reaches the
    # authorization check and no further.
    validate_error(
        api.create_department(
            department_payload(code="ZZTP"), build_user_headers("buyer-1", "CategoryBuyer")
        ),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE,
    )

    # And a fully identified caller on an authorized read still succeeds.
    department = validate_success(
        api.get_department(
            spine["department"]["id"], build_user_headers("buyer-1", "CategoryBuyer")
        )
    )
    assert department["code"] == "WAPP", (
        f"a fully identified CategoryBuyer must be able to read, got {department}"
    )

    # None of the refused requests wrote anything: PRD §3.1 refuses a duplicated
    # department code, so this create can only succeed if no `ZZTP` row was persisted.
    created = validate_success(
        api.create_department(department_payload(code="ZZTP"), ADMIN_HEADERS), 201
    )
    assert created["code"] == "ZZTP", (
        "the refused creates must have persisted nothing, so an authorized create of "
        f"the same code must succeed, got {created}"
    )


# ---------------------------------------------------------------------------
# Slot capacity bottoms out at two and then refuses the third adoption
# ---------------------------------------------------------------------------

def test_option_slots_run_out_at_the_floor_of_two(api):
    """PRD §3.4: "`option_slots_total` is then the larger of 2 and the smaller of the
    cell's `breadth_target` and that affordable count — every slotted tier is
    guaranteed a minimum of two options even when the arithmetic funds fewer."
    PRD §3.5: "Adoption is a `CategoryBuyer` act and it is where the option's numbers
    come to life. It advances the item `PROPOSED → ADOPTED` and requires that the cell
    holding the slot is `SLOTTED` (otherwise `ERR_OPTION_PLAN_NOT_SLOTTED`), that the
    cell has at least one open slot (otherwise `ERR_NO_OPTION_SLOT`), and that the
    governing category plan's `status` is either `APPROVED` or `REFORECAST_OPEN`."
    PRD §2.8: "29. The option plan has at least one open slot — `ERR_NO_OPTION_SLOT`
    (409), on `POST /otb/assortment-items/{id}/adopt`."

    Design: Corner/errors/option_slots_run_out_at_the_floor_of_two
    """
    # A depth of 500 units per option makes one option cost far more than the whole
    # BETTER share of the budget, so the affordable count floors to zero.
    scenario = _single_month_approved(
        option_plan_specs=[
            {
                "tier": "BETTER",
                "breadth_target": 14,
                "depth_units_per_option": 500,
                "assumed_unit_cost_cents": 2400,
            }
        ],
        size_curve=[
            {"size_label": "S", "size_sort_order": 1, "pct_bps": 4000},
            {"size_label": "L", "size_sort_order": 2, "pct_bps": 6000},
        ],
    )

    plan = scenario["plan"]
    assert plan["receipt_budget_cents"] == CANONICAL_RECEIPT_BUDGET_CENTS, (
        "the seasonal receipt budget must be 60000000, got "
        f"{plan['receipt_budget_cents']}"
    )

    cell = scenario["option_plan"]
    assert cell["option_slots_total"] == 2, (
        "the affordable option count is 0 here, so the floor of 2 must win: expected "
        f"option_slots_total 2, got {cell['option_slots_total']}"
    )
    assert cell["option_slots_open"] == 2, (
        f"expected option_slots_open 2 on a fresh cell, got {cell['option_slots_open']}"
    )
    assert cell["option_slots_assigned"] == 0, (
        f"expected option_slots_assigned 0, got {cell['option_slots_assigned']}"
    )
    assert cell["target_units_per_option"] == 23000, (
        "the cell's unit target depends only on depth, store count and sales index: "
        f"expected 23000, got {cell['target_units_per_option']}"
    )

    cells_by_label = {row["size_label"]: row for row in get_size_curve_cells(cell["id"])}
    assert cells_by_label["S"]["allocated_units"] == 9200, (
        f"expected S allocated_units 9200, got {cells_by_label['S']['allocated_units']}"
    )
    assert cells_by_label["L"]["allocated_units"] == 13800, (
        f"expected L allocated_units 13800, got {cells_by_label['L']['allocated_units']}"
    )

    vendor_id = scenario["vendor"]["id"]
    item_1 = propose_item(cell["id"], vendor_id)
    item_2 = propose_item(cell["id"], vendor_id)
    item_3 = propose_item(cell["id"], vendor_id)

    for label, item in (("first", item_1), ("second", item_2)):
        adopted = adopt_item(item["id"])
        assert adopted["status"] == "ADOPTED", (
            f"the {label} adoption must fit inside the two guaranteed slots, got "
            f"status {adopted['status']}"
        )
        assert adopted["planned_units"] == 23000, (
            f"the {label} adoption must take the cell's target_units_per_option, got "
            f"{adopted['planned_units']}"
        )

    filled = get_option_plan(cell["id"])
    assert filled["option_slots_assigned"] == 2, (
        f"expected option_slots_assigned 2 after two adoptions, got {filled}"
    )
    assert filled["option_slots_open"] == 0, (
        f"expected option_slots_open 0 after two adoptions, got {filled}"
    )
    assert filled["option_slots_total"] == 2, (
        "option_slots_total is untouched by adoption, got "
        f"{filled['option_slots_total']}"
    )

    # The floor of two is a floor, not a licence for a third option.
    validate_error(
        api.adopt_assortment_item(item_3["id"], {}, BUYER_HEADERS),
        ApiErrorId.ERR_NO_OPTION_SLOT,
    )

    untouched = get_item(item_3["id"])
    assert untouched["status"] == "PROPOSED", (
        f"the refused adoption must leave the item PROPOSED, got {untouched['status']}"
    )
    assert untouched["planned_units"] is None, (
        "the refused adoption must not derive planned_units, got "
        f"{untouched['planned_units']}"
    )


# ---------------------------------------------------------------------------
# Overlay scope is checked before the overlay window
# ---------------------------------------------------------------------------

def test_overlay_scope_error_outranks_overlay_window_error(api, planner_headers):
    """PRD §2.8: "21. The overlay's cluster is actually planned: at least one option
    plan exists for the overlay's `category_plan_id` and `store_cluster_id` pair —
    `ERR_CLUSTER_NOT_IN_PLAN` (422), on `POST /otb/localization-overlays`."
    PRD §2.8: "36. `effective_end` is greater than or equal to `effective_start` —
    `ERR_OVERLAY_WINDOW_INVERTED` (422), on `POST /otb/localization-overlays`."
    PRD §2.8: "Implementers must not treat the checks below as an unordered set — a
    request that violates three of them returns the code of the lowest-numbered one."
    PRD §3.5: "Overlay windows are **closed** intervals: both endpoints are inside the
    window, so a single-day overlay whose `effective_end` equals its `effective_start`
    is perfectly valid, while an `effective_end` earlier than `effective_start` is
    rejected with `ERR_OVERLAY_WINDOW_INVERTED`."

    Design: Corner/errors/overlay_scope_error_outranks_overlay_window_error
    """
    scenario = _single_month_approved()
    plan_id = scenario["plan_id"]
    planned_cluster_id = scenario["store_cluster"]["id"]

    # A second, real cluster that no option plan of this plan covers.
    unplanned_cluster = create_store_cluster(
        name="Rural-B",
        climate_zone="TEMPERATE",
        demographic_index_bps=9000,
        volume_tier="C",
        store_count=12,
        sales_index_bps=7000,
    )

    # Both defects at once: the lower-numbered scope rule decides.
    validate_error(
        api.create_localization_overlay(
            localization_overlay_payload(
                plan_id,
                unplanned_cluster["id"],
                effective_start="2027-03-20T00:00:00Z",
                effective_end="2027-03-10T00:00:00Z",
            ),
            planner_headers,
        ),
        ApiErrorId.ERR_CLUSTER_NOT_IN_PLAN,
    )

    # Scope defect alone: still the scope code, and never a not-found — the cluster row
    # exists, it is simply not planned for.
    validate_error(
        api.create_localization_overlay(
            localization_overlay_payload(
                plan_id,
                unplanned_cluster["id"],
                effective_start="2027-03-10T00:00:00Z",
                effective_end="2027-03-20T00:00:00Z",
            ),
            planner_headers,
        ),
        ApiErrorId.ERR_CLUSTER_NOT_IN_PLAN,
    )

    # Window defect alone, on a cluster the plan does cover.
    validate_error(
        api.create_localization_overlay(
            localization_overlay_payload(
                plan_id,
                planned_cluster_id,
                effective_start="2027-03-20T00:00:00Z",
                effective_end="2027-03-10T00:00:00Z",
            ),
            planner_headers,
        ),
        ApiErrorId.ERR_OVERLAY_WINDOW_INVERTED,
    )

    # Neither defect: a single-day closed window on a planned cluster is accepted.
    overlay = validate_success(
        api.create_localization_overlay(
            localization_overlay_payload(
                plan_id,
                planned_cluster_id,
                effective_start="2027-03-10T00:00:00Z",
                effective_end="2027-03-10T00:00:00Z",
            ),
            planner_headers,
        ),
        201,
    )
    assert overlay["status"] == "DRAFT", (
        f"overlays are created in DRAFT, got {overlay['status']}"
    )
    assert overlay["effective_start"] == overlay["effective_end"], (
        "the accepted overlay must be the single-day one, got "
        f"{overlay['effective_start']} .. {overlay['effective_end']}"
    )

    overlays, meta = validate_paginated(
        api.list_localization_overlays(planner_headers, {"category_plan_id": plan_id})
    )
    assert meta["total_count"] == 1, (
        "the three refused creates must have persisted nothing, so exactly one overlay "
        f"should exist for the plan, got total_count {meta['total_count']}"
    )
    assert overlays[0]["id"] == overlay["id"], (
        f"the surviving overlay must be the accepted one, got {overlays[0]}"
    )


# ---------------------------------------------------------------------------
# The vendor minimum and the receipt ceiling bracket the unit count
# ---------------------------------------------------------------------------

SHIP_WINDOW = {
    "ship_window_start": "2026-10-01T00:00:00Z",
    "ship_window_end": "2026-10-15T00:00:00Z",
}


def test_vendor_minimum_and_receipt_ceiling_bracket_the_unit_count(api):
    """PRD §3.6: "The quantity must reach the vendor's `min_order_units`
    (`ERR_BELOW_VENDOR_MINIMUM`) and must pass both vendor capacity tests of §3.2
    (`ERR_VENDOR_CAPACITY_EXCEEDED`)."
    PRD §3.6: "The same `VendorRep` posts arrivals by supplying
    `received_units_delta`, which must be at least 1 and must not push cumulative
    receipts above the ordered quantity — a delta that would is refused with
    `ERR_RECEIPT_OVER_COMMITMENT`."
    PRD §3.6: "When `received_units` plus the delta exactly equals `units`, the order
    is complete: `received_units` is set to `units`, `fulfillment_status` becomes
    `RECEIVED`, and this is the **first coupling point between the two dimensions** —
    `commit_status` simultaneously advances `COMMITTED → CLOSED`, with
    `open_cost_cents` zeroed and `received_cost_cents` set to `received_units`
    multiplied by `unit_cost_cents`."
    PRD §3.6: "The month's `otb_committed_cents` and `otb_received_cents` are
    recomputed while `otb_open_cents` is left unchanged, because the cost simply moved
    between two buckets that are both subtracted from the same planned figure."

    Design: Corner/errors/vendor_minimum_and_receipt_ceiling_bracket_the_unit_count
    """
    scenario = _single_month_approved(vendor_overrides={"min_order_units": 100})
    vendor_id = scenario["vendor"]["id"]
    month_id = scenario["m1"]["id"]
    item = propose_item(scenario["option_plan"]["id"], vendor_id, unit_cost_cents=2600)

    assert scenario["m1"]["otb_planned_cents"] == CANONICAL_M1_OTB_PLANNED_CENTS, (
        "the locked month's planned open-to-buy must be 18200000, got "
        f"{scenario['m1']['otb_planned_cents']}"
    )

    # One unit short of the vendor minimum: the lower bracket refuses the buy.
    validate_error(
        api.create_receipt_commitment(
            receipt_commitment_payload(
                month_id,
                item["id"],
                vendor_id,
                month_version(month_id),
                units=99,
                unit_cost_cents=2600,
                **SHIP_WINDOW,
            ),
            BUYER_HEADERS,
        ),
        ApiErrorId.ERR_BELOW_VENDOR_MINIMUM,
    )

    # Exactly at the minimum the buy is accepted: the bound is inclusive.
    commitment = propose_commitment(
        month_id, item["id"], vendor_id, units=100, unit_cost_cents=2600, **SHIP_WINDOW
    )
    assert commitment["cost_cents"] == 260000, (
        f"100 units at 2600 cents must cost 260000, got {commitment['cost_cents']}"
    )
    commit_commitment(commitment["id"])
    shipped = ship_commitment(commitment["id"], vendor_id)
    assert shipped["fulfillment_status"] == "SHIPPED", (
        f"the committed order must ship, got {shipped['fulfillment_status']}"
    )

    partial = post_receipt(commitment["id"], vendor_id, 60)
    assert partial["received_units"] == 60, (
        f"expected received_units 60 after the first delta, got {partial}"
    )
    assert partial["fulfillment_status"] == "PARTIALLY_RECEIVED", (
        f"expected PARTIALLY_RECEIVED, got {partial['fulfillment_status']}"
    )
    assert partial["open_cost_cents"] == 104000, (
        f"expected open_cost_cents 104000 with 40 units outstanding, got {partial}"
    )
    assert partial["received_cost_cents"] == 156000, (
        f"expected received_cost_cents 156000 for 60 units, got {partial}"
    )

    # One unit past the ordered quantity: the upper bracket refuses the delta.
    validate_error(
        api.post_receipt(
            commitment["id"],
            {"received_units_delta": 41},
            make_vendor_rep_headers(vendor_id),
        ),
        ApiErrorId.ERR_RECEIPT_OVER_COMMITMENT,
    )

    unchanged = get_commitment(commitment["id"])
    assert unchanged["received_units"] == 60, (
        f"the refused delta must not move received_units, got {unchanged}"
    )
    assert unchanged["fulfillment_status"] == "PARTIALLY_RECEIVED", (
        f"the refused delta must not move fulfillment_status, got {unchanged}"
    )

    # The exact remainder completes the order and couples the two dimensions.
    closed = post_receipt(commitment["id"], vendor_id, 40)
    assert closed["received_units"] == 100, (
        f"expected received_units 100 once the order completes, got {closed}"
    )
    assert closed["fulfillment_status"] == "RECEIVED", (
        f"expected RECEIVED, got {closed['fulfillment_status']}"
    )
    assert closed["commit_status"] == "CLOSED", (
        f"the first coupling point must close the financial dimension, got {closed}"
    )
    assert closed["open_cost_cents"] == 0, (
        f"expected open_cost_cents 0 once closed, got {closed['open_cost_cents']}"
    )
    assert closed["received_cost_cents"] == 260000, (
        f"expected received_cost_cents 260000 once closed, got {closed}"
    )

    month = get_month(month_id)
    assert month["otb_committed_cents"] == 0, (
        f"expected otb_committed_cents 0 once the order closed, got {month}"
    )
    assert month["otb_received_cents"] == 260000, (
        f"expected otb_received_cents 260000, got {month}"
    )
    assert month["otb_open_cents"] == 17940000, (
        "the cost moved between two buckets, so otb_open_cents must stay at 17940000, "
        f"got {month['otb_open_cents']}"
    )


# ---------------------------------------------------------------------------
# A cycle cannot be closed while one of its decisions is still PROPOSED
# ---------------------------------------------------------------------------

def test_cycle_close_blocked_while_a_decision_is_still_proposed(api, director_headers):
    """PRD §3.8: "Either close path is refused with `ERR_OPEN_DECISIONS_REMAIN` while
    any decision of the cycle is still `PROPOSED`."
    PRD §3.8: "As soon as an approval or a rejection leaves no decision of the cycle
    still `PROPOSED`, and provided the cycle holds at least one decision at all, the
    cycle bubbles `OPEN → DECIDED` and its version advances by 1 — the parent's state
    is derived from the aggregate state of its children."
    PRD §3.8: "A rejection sets `status` to `REJECTED` and `approved_units` to 0,
    changes no plan month and no item field at all, and advances the decision's version
    by 1."

    Design: Corner/errors/cycle_close_blocked_while_a_decision_is_still_proposed
    """
    scenario = _single_month_approved(open_season_month_indexes=(1,))
    item = propose_item(scenario["option_plan"]["id"], scenario["vendor"]["id"])
    adopt_item(item["id"])
    live_item = activate_item(item["id"])
    assert live_item["status"] == "IN_SEASON", (
        f"the option must be live before it can be corrected, got {live_item['status']}"
    )

    cycle = open_reforecast_cycle(scenario["plan_id"])
    assert cycle["status"] == "OPEN", f"a new cycle opens OPEN, got {cycle['status']}"
    assert cycle["round_index"] == 1, (
        f"the first cycle carries round_index 1, got {cycle['round_index']}"
    )
    assert cycle["trigger_reason"] == "DIRECTOR_REQUEST", (
        "an explicitly requested cycle records DIRECTOR_REQUEST, got "
        f"{cycle['trigger_reason']}"
    )

    decision = propose_decision(
        cycle["id"], item["id"], action="HOLD", requested_units=0
    )
    assert decision["status"] == "PROPOSED", (
        f"a fresh decision starts PROPOSED, got {decision['status']}"
    )

    cycle_before = get_cycle(cycle["id"])

    # The close is refused by the open-decision rule specifically — the cycle's own
    # status is a legal close source, so this is not a state error.
    validate_error(
        api.close_reforecast_cycle(cycle["id"], {}, director_headers),
        ApiErrorId.ERR_OPEN_DECISIONS_REMAIN,
    )

    blocked = get_cycle(cycle["id"])
    assert blocked["status"] == "OPEN", (
        f"the refused close must leave the cycle OPEN, got {blocked['status']}"
    )
    assert blocked["version"] == cycle_before["version"], (
        "the refused close must not advance the cycle's version, expected "
        f"{cycle_before['version']}, got {blocked['version']}"
    )

    # Adjudicating the last open decision is what unblocks the close.
    rejected = reject_decision(decision["id"])
    assert rejected["status"] == "REJECTED", (
        f"expected REJECTED, got {rejected['status']}"
    )
    assert rejected["approved_units"] == 0, (
        f"a rejection sets approved_units to 0, got {rejected['approved_units']}"
    )

    bubbled = get_cycle(cycle["id"])
    assert bubbled["status"] == "DECIDED", (
        "with no decision left PROPOSED the cycle must bubble to DECIDED, got "
        f"{bubbled['status']}"
    )

    closed = close_cycle(cycle["id"])
    assert closed["status"] == "CLOSED", (
        f"the replayed close must now succeed, got {closed['status']}"
    )

    # A rejection changes no plan month and no commitment.
    commitments, meta = validate_paginated(
        api.list_receipt_commitments(
            director_headers, {"plan_month_id": scenario["m1"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        "a rejected decision must create no commitments, got total_count "
        f"{meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# The reforecast round cap bites after the third cycle
# ---------------------------------------------------------------------------

def test_reforecast_round_cap_is_reached_after_three_cycles(api, planner_headers):
    """PRD §3.8: "An explicit request is refused unless the plan's `status` is
    `APPROVED` (`ERR_CATEGORY_PLAN_NOT_APPROVED`), unless `reforecast_round` is still
    below the cap of 3 (`ERR_REFORECAST_ROUND_LIMIT`), and unless no cycle of that plan
    is currently `OPEN` or `DECIDED` — one live cycle at a time."
    PRD §3.8: "Either way the plan advances `APPROVED → REFORECAST_OPEN`, its
    `reforecast_round` rises by 1, and the plan's version advances by 1."
    PRD §2.8: "18. The plan's `reforecast_round` is below 3 before a new cycle opens —
    `ERR_REFORECAST_ROUND_LIMIT` (409), on
    `POST /otb/category-plans/{id}/reforecasts`."

    Design: Corner/errors/reforecast_round_cap_is_reached_after_three_cycles
    """
    scenario = _single_month_approved()
    plan_id = scenario["plan_id"]
    assert scenario["plan"]["reforecast_round"] == 0, (
        f"a freshly approved plan has consumed no round, got {scenario['plan']}"
    )

    cycle_ids = []
    for expected_round in (1, 2, 3):
        cycle = open_reforecast_cycle(plan_id)
        cycle_ids.append(cycle["id"])
        assert cycle["status"] == "OPEN", (
            f"round {expected_round}: expected a new OPEN cycle, got {cycle['status']}"
        )
        assert cycle["round_index"] == expected_round, (
            f"round {expected_round}: expected round_index {expected_round}, got "
            f"{cycle['round_index']}"
        )
        assert cycle["trigger_reason"] == "DIRECTOR_REQUEST", (
            f"round {expected_round}: an explicit request records DIRECTOR_REQUEST, "
            f"got {cycle['trigger_reason']}"
        )

        opened_plan = get_plan(plan_id)
        assert opened_plan["status"] == "REFORECAST_OPEN", (
            f"round {expected_round}: expected REFORECAST_OPEN, got "
            f"{opened_plan['status']}"
        )
        assert opened_plan["reforecast_round"] == expected_round, (
            f"round {expected_round}: expected reforecast_round {expected_round}, got "
            f"{opened_plan['reforecast_round']}"
        )

        # An empty cycle closes straight from OPEN, then the loop closes through
        # resubmission and re-approval.
        assert close_cycle(cycle["id"])["status"] == "CLOSED", (
            f"round {expected_round}: the empty cycle must close"
        )
        assert submit_plan(plan_id)["status"] == "SUBMITTED", (
            f"round {expected_round}: the plan must resubmit once its cycle is closed"
        )
        reapproved = approve_plan(plan_id)
        assert reapproved["status"] == "APPROVED", (
            f"round {expected_round}: the plan must re-enter APPROVED"
        )
        assert reapproved["reforecast_round"] == expected_round, (
            f"round {expected_round}: re-approval must not rewind the round counter, "
            f"got {reapproved['reforecast_round']}"
        )

    capped = get_plan(plan_id)

    # The fourth request is refused on the cap, even though every other precondition
    # of an explicit request is satisfied.
    validate_error(
        api.open_reforecast_cycle(
            plan_id,
            reforecast_payload(capped["version"], reason_note="a fourth round"),
            planner_headers,
        ),
        ApiErrorId.ERR_REFORECAST_ROUND_LIMIT,
    )

    after = get_plan(plan_id)
    assert after["status"] == "APPROVED", (
        f"the refused request must leave the plan APPROVED, got {after['status']}"
    )
    assert after["reforecast_round"] == 3, (
        f"the refused request must not consume a round, got {after['reforecast_round']}"
    )
    assert after["version"] == capped["version"], (
        "the refused request must not advance the plan's version, expected "
        f"{capped['version']}, got {after['version']}"
    )

    cycles, meta = validate_paginated(
        api.list_reforecast_cycles(planner_headers, {"category_plan_id": plan_id})
    )
    assert meta["total_count"] == 3, (
        f"exactly three cycles may ever exist for this plan, got {meta['total_count']}"
    )
    assert sorted(row["round_index"] for row in cycles) == [1, 2, 3], (
        f"the three cycles must carry round_index 1, 2 and 3, got {cycles}"
    )
    assert all(row["status"] == "CLOSED" for row in cycles), (
        f"every cycle of the capped plan is CLOSED, got {cycles}"
    )
    assert sorted(row["id"] for row in cycles) == sorted(cycle_ids), (
        "the refused fourth request must not have created a cycle row"
    )


# ---------------------------------------------------------------------------
# A receipt budget that rounds to zero blocks the approval outright
# ---------------------------------------------------------------------------

def test_zero_receipt_budget_blocks_approval_at_the_rounding_boundary(
    api, director_headers
):
    """PRD §3.4: "Before anything is written, the **seasonal receipt budget** is
    computed, and if it resolves to zero the approval is refused with
    `ERR_RECEIPT_BUDGET_ZERO` and nothing changes."
    PRD §3.4: "Fourth, a **department ceiling** is the department's
    `sales_target_cents` multiplied by 1200 basis points and divided by ten thousand,
    rounded half up: no single category may claim more than 12% of its department's
    annual sales target as receipts."
    PRD §3.4: "Finally, `receipt_budget_cents` is the smaller of the department ceiling
    and the larger of the role capacity and the turn capacity."

    Design: Corner/errors/zero_receipt_budget_blocks_approval_at_the_rounding_boundary
    """
    # A department ceiling of round_half_up(4 * 1200 / 10000) resolves to 0 cents.
    zero_side = setup_plan_scenario(
        month_specs=[dict(M1_SPEC)],
        submit=True,
        department_overrides={"sales_target_cents": 4},
    )

    # One cent more of annual sales target rounds the ceiling up to 1 cent.
    positive_department = create_department(
        code="MENS", name="Menswear", sales_target_cents=5
    )
    positive_category = create_category(positive_department["id"], code="SHRT",
                                        name="Shirts")
    positive_side = setup_plan_scenario(
        month_specs=[dict(M1_SPEC)],
        submit=True,
        spine={
            "department": positive_department,
            "category": positive_category,
            "store_cluster": zero_side["store_cluster"],
            "vendor": zero_side["vendor"],
            "authorization": zero_side["authorization"],
        },
    )

    # Below the boundary the approval is refused and nothing changes.
    validate_error(
        api.approve_category_plan(
            zero_side["plan_id"], {"approval_note": "signed off"}, director_headers
        ),
        ApiErrorId.ERR_RECEIPT_BUDGET_ZERO,
    )

    refused_plan = get_plan(zero_side["plan_id"])
    assert refused_plan["status"] == "SUBMITTED", (
        f"the refused approval must leave the plan SUBMITTED, got {refused_plan}"
    )
    assert refused_plan["receipt_budget_cents"] is None, (
        "the refused approval must not pin a budget, got "
        f"{refused_plan['receipt_budget_cents']}"
    )
    assert refused_plan["approved_by_user_id"] is None, (
        "the refused approval must record no approver, got "
        f"{refused_plan['approved_by_user_id']}"
    )

    refused_month = get_month(zero_side["m1"]["id"])
    assert refused_month["status"] == "DRAFT", (
        f"cascade B never ran, so the month stays DRAFT, got {refused_month['status']}"
    )
    assert refused_month["otb_planned_cents"] == 0, (
        f"the month's open-to-buy must stay at 0, got {refused_month}"
    )
    assert refused_month["markdown_reserve_cents"] == 0, (
        f"the markdown reserve must stay at 0, got {refused_month}"
    )

    refused_cell = get_option_plan(zero_side["option_plan"]["id"])
    assert refused_cell["status"] == "OPEN", (
        f"no cell may slot when the budget is zero, got {refused_cell['status']}"
    )
    assert refused_cell["option_slots_total"] is None, (
        f"option_slots_total must stay null, got {refused_cell['option_slots_total']}"
    )

    # One cent above the boundary the very same approval succeeds.
    approved = validate_success(
        api.approve_category_plan(
            positive_side["plan_id"], {"approval_note": "signed off"}, director_headers
        )
    )
    assert approved["status"] == "APPROVED", (
        f"a positive budget must approve, got {approved['status']}"
    )
    assert approved["receipt_budget_cents"] == 1, (
        "the department ceiling of 1 cent is the smaller of the ceiling and the larger "
        f"of the two capacities, got {approved['receipt_budget_cents']}"
    )

    locked_month = get_month(positive_side["m1"]["id"])
    assert locked_month["status"] == "LOCKED_PLAN", (
        f"cascade B link 2 must lock the month, got {locked_month['status']}"
    )
    assert locked_month["otb_planned_cents"] == CANONICAL_M1_OTB_PLANNED_CENTS, (
        "the month's planned open-to-buy reads no budget figure at all, so it must be "
        f"18200000, got {locked_month['otb_planned_cents']}"
    )

    slotted_cell = get_option_plan(positive_side["option_plan"]["id"])
    assert slotted_cell["status"] == "SLOTTED", (
        f"cascade B link 4 must slot the cell, got {slotted_cell['status']}"
    )
    assert slotted_cell["option_slots_total"] == 2, (
        "one cent of budget funds no options, so the floor of 2 applies, got "
        f"{slotted_cell['option_slots_total']}"
    )
    assert slotted_cell["target_units_per_option"] == CANONICAL_TARGET_UNITS_PER_OPTION, (
        "the cell's unit target never reads the budget, so it must be 276, got "
        f"{slotted_cell['target_units_per_option']}"
    )


# ---------------------------------------------------------------------------
# Each role is refused every other role's exclusive operation
# ---------------------------------------------------------------------------

def _rbac_context():
    """One APPROVED plan (with a live month, item and proposal) plus one SUBMITTED
    plan, so every refusal below is attempted on a state-legal target."""
    spine = setup_reference_spine()
    approved = setup_plan_scenario(
        clock=None, spine=spine, month_specs=[dict(M1_SPEC)], approve=True
    )
    item = propose_item(approved["option_plan"]["id"], spine["vendor"]["id"])
    commitment = propose_commitment(
        approved["m1"]["id"], item["id"], spine["vendor"]["id"]
    )
    submitted = setup_plan_scenario(
        clock=None,
        spine=spine,
        month_specs=[dict(M1_SPEC)],
        submit=True,
        plan_overrides={"season_code": "SUMMER"},
    )
    return {
        "spine": spine,
        "vendor_id": spine["vendor"]["id"],
        "cluster_id": spine["store_cluster"]["id"],
        "approved_plan_id": approved["plan_id"],
        "option_plan_id": approved["option_plan"]["id"],
        "month_id": approved["m1"]["id"],
        "item_id": item["id"],
        "commitment_id": commitment["id"],
        "submitted_plan_id": submitted["plan_id"],
    }


def _op_approve_plan(api, ctx, headers):
    return api.approve_category_plan(
        ctx["submitted_plan_id"], {"approval_note": "signed off"}, headers
    )


def _op_reject_plan(api, ctx, headers):
    return api.reject_category_plan(
        ctx["submitted_plan_id"], {"rejection_reason": "rework the months"}, headers
    )


def _op_close_plan(api, ctx, headers):
    return api.close_category_plan(ctx["approved_plan_id"], {}, headers)


def _op_submit_plan(api, ctx, headers):
    return api.submit_category_plan(
        ctx["approved_plan_id"], {"submission_note": "resubmitting"}, headers
    )


def _op_create_option_plan(api, ctx, headers):
    return api.create_option_plan(
        option_plan_payload(ctx["approved_plan_id"], ctx["cluster_id"], tier="GOOD"),
        headers,
    )


def _op_create_vendor(api, ctx, headers):
    return api.create_vendor(vendor_payload(code="ZZVN", name="Zulu Mills"), headers)


def _op_create_department(api, ctx, headers):
    return api.create_department(department_payload(code="ZZDP"), headers)


def _op_post_actuals(api, ctx, headers):
    return api.create_actuals_post(actuals_post_payload(ctx["month_id"]), headers)


def _op_set_clock(api, ctx, headers):
    return api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, headers)


def _op_adopt_item(api, ctx, headers):
    return api.adopt_assortment_item(ctx["item_id"], {}, headers)


def _op_commit_commitment(api, ctx, headers):
    return api.commit_receipt_commitment(ctx["commitment_id"], {}, headers)


def _op_ship_commitment(api, ctx, headers):
    return api.ship_receipt_commitment(ctx["commitment_id"], {}, headers)


def _op_read_category_plan(api, ctx, headers):
    return api.get_category_plan(ctx["approved_plan_id"], headers)


def _op_read_plan_month(api, ctx, headers):
    return api.get_plan_month(ctx["month_id"], headers)


EXCLUSIVE_OPERATION_DENIALS = [
    ("approve_category_plan", "CategoryBuyer", _op_approve_plan),
    ("approve_category_plan", "MerchandisePlanner", _op_approve_plan),
    ("approve_category_plan", "MerchOpsAdmin", _op_approve_plan),
    ("reject_category_plan", "MerchandisePlanner", _op_reject_plan),
    ("close_category_plan", "CategoryBuyer", _op_close_plan),
    ("submit_category_plan", "PlanningDirector", _op_submit_plan),
    ("create_option_plan", "CategoryBuyer", _op_create_option_plan),
    ("create_vendor", "MerchandisePlanner", _op_create_vendor),
    ("create_department", "CategoryBuyer", _op_create_department),
    ("create_actuals_post", "MerchandisePlanner", _op_post_actuals),
    ("set_clock", "CategoryBuyer", _op_set_clock),
    ("adopt_assortment_item", "MerchandisePlanner", _op_adopt_item),
    ("commit_receipt_commitment", "PlanningDirector", _op_commit_commitment),
    ("ship_receipt_commitment", "MerchOpsAdmin", _op_ship_commitment),
    ("read_category_plan", "VendorRep", _op_read_category_plan),
    ("read_plan_month", "VendorRep", _op_read_plan_month),
]

DENIED_ROLE_USER_IDS = {
    "MerchOpsAdmin": "ops-admin-9",
    "MerchandisePlanner": "planner-9",
    "PlanningDirector": "director-9",
    "CategoryBuyer": "buyer-9",
    "VendorRep": "vendor-rep-9",
}


@pytest.mark.parametrize(
    "operation,role,runner",
    EXCLUSIVE_OPERATION_DENIALS,
    ids=[f"{op}-as-{role}" for op, role, _ in EXCLUSIVE_OPERATION_DENIALS],
)
def test_each_role_is_refused_every_other_roles_exclusive_operation(
    api, operation, role, runner
):
    """PRD §2.1: "If the role is declared but is not authorized for the endpoint being
    called, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
    PRD §2.1: "It maintains the reference spine — departments, categories, store
    clusters, vendors and vendor authorizations — posts the weekly actuals that drive
    in-season reforecasting, and drives the server's logical clock."
    PRD §2.1: "A `MerchandisePlanner` builds the plan: category plans, fiscal months,
    option plans and size curves, localization overlays, requested reforecast cycles,
    and proposed chase-or-cancel decisions; it may never approve its own work."
    PRD §2.1: "A `PlanningDirector` is the financial gatekeeper: it approves, rejects
    and closes plans, activates localization overlays, adjudicates chase-or-cancel
    decisions, and closes reforecast cycles."
    PRD §2.1: "A `CategoryBuyer` spends the open-to-buy: it adopts, activates and
    closes assortment items, and creates, commits and cancels receipt commitments."
    PRD §2.1: "A `VendorRep` is the supplier-side actor: it marks committed orders as
    shipped and posts received units."
    PRD §2.8: "2. The acting role is authorized for the endpoint —
    `ERR_UNAUTHORIZED_ROLE` (403), on every endpoint."

    Design: Corner/rbac/each_role_is_refused_every_other_roles_exclusive_operation
    """
    ctx = _rbac_context()
    headers = build_user_headers(DENIED_ROLE_USER_IDS[role], role)

    response = runner(api, ctx, headers)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_the_rightful_role_succeeds_where_every_other_role_is_refused(
    api, planner_headers, admin_headers, director_headers
):
    """PRD §2.1: "If the role is declared but is not authorized for the endpoint being
    called, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (403). These two checks
    run before anything else in the system, in that order."
    PRD §2.1: "A `PlanningDirector` is the financial gatekeeper: it approves, rejects
    and closes plans, activates localization overlays, adjudicates chase-or-cancel
    decisions, and closes reforecast cycles."
    PRD §2.1: "A `CategoryBuyer` spends the open-to-buy: it adopts, activates and
    closes assortment items, and creates, commits and cancels receipt commitments."
    PRD §2.1: "A `VendorRep` is the supplier-side actor: it marks committed orders as
    shipped and posts received units."
    PRD §3.7: "The target month must be `IN_SEASON`, or the post is refused with
    `ERR_PLAN_MONTH_NOT_OPEN`."

    Design: Corner/rbac/each_role_is_refused_every_other_roles_exclusive_operation
    """
    ctx = _rbac_context()

    # The refusals above are about the role, not about the request: the rightful role
    # drives every one of those operations through.
    approved = validate_success(
        api.approve_category_plan(
            ctx["submitted_plan_id"], {"approval_note": "signed off"}, director_headers
        )
    )
    assert approved["status"] == "APPROVED", (
        f"the PlanningDirector must be able to approve, got {approved['status']}"
    )
    assert approved["receipt_budget_cents"] == CANONICAL_RECEIPT_BUDGET_CENTS, (
        f"expected receipt_budget_cents 60000000, got {approved}"
    )

    committed = validate_success(
        api.commit_receipt_commitment(ctx["commitment_id"], {}, BUYER_HEADERS)
    )
    assert committed["commit_status"] == "COMMITTED", (
        f"the CategoryBuyer must be able to commit, got {committed['commit_status']}"
    )

    shipped = validate_success(
        api.ship_receipt_commitment(
            ctx["commitment_id"], {}, make_vendor_rep_headers(ctx["vendor_id"])
        )
    )
    assert shipped["fulfillment_status"] == "SHIPPED", (
        f"the owning VendorRep must be able to ship, got {shipped}"
    )

    # The role check runs ahead of the business ladder: the same weekly actuals post is
    # refused on the role for a planner and only then on the month's state for an admin.
    validate_error(
        api.create_actuals_post(actuals_post_payload(ctx["month_id"]), planner_headers),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE,
    )
    validate_error(
        api.create_actuals_post(actuals_post_payload(ctx["month_id"]), admin_headers),
        ApiErrorId.ERR_PLAN_MONTH_NOT_OPEN,
    )


# ---------------------------------------------------------------------------
# Shared operations span roles; the VendorRep's write scope stays narrow
# ---------------------------------------------------------------------------

def test_shared_operations_span_roles_while_vendor_scope_stays_narrow(api):
    """PRD §2.1: "Every role may read: all four planning roles are authorized on every
    read endpoint, and a `VendorRep` may additionally read vendors, individual receipt
    commitments and the receipt-commitment list."
    PRD §2.1: "When `X-User-Role` is `VendorRep`, `X-User-ID` is the `id` of the acting
    `Vendor` row; ownership checks on a receipt commitment compare the commitment's
    `vendor_id` field to `X-User-ID`, and a mismatch on either the ship or the
    receipt-posting operation is rejected with `ERR_NOT_COMMITMENT_VENDOR` (403)."
    PRD §3.5: "Either a `MerchandisePlanner` or a `CategoryBuyer` may propose an
    **AssortmentItem**, naming the `option_plan_id` of the cell that will hold its slot
    and the `vendor_id` of the supplier that will make it."
    PRD §2.8: "7. Vendor ownership: a `VendorRep` acts only on a commitment whose
    `vendor_id` equals its `X-User-ID` — `ERR_NOT_COMMITMENT_VENDOR` (403), on
    `POST /otb/receipt-commitments/{id}/ship` and
    `POST /otb/receipt-commitments/{id}/receipts`."

    Design: Corner/rbac/shared_operations_span_roles_while_vendor_scope_stays_narrow
    """
    scenario = _single_month_approved()
    plan_id = scenario["plan_id"]
    month_id = scenario["m1"]["id"]
    vendor_a = scenario["vendor"]["id"]

    vendor_b_row = create_vendor(code="BRVO", name="Bravo Mills")
    vendor_b = vendor_b_row["id"]
    create_vendor_authorization(vendor_b, scenario["category"]["id"])

    # Proposing an option is a shared operation: two different roles may both do it.
    item_a = propose_item(
        scenario["option_plan"]["id"],
        vendor_a,
        headers=build_user_headers(PLANNER_USER_ID, "MerchandisePlanner"),
    )
    item_b = propose_item(
        scenario["option_plan"]["id"], vendor_b, headers=BUYER_HEADERS
    )
    assert item_a["status"] == "PROPOSED" and item_b["status"] == "PROPOSED", (
        "both a MerchandisePlanner and a CategoryBuyer may propose an option, got "
        f"{item_a['status']} and {item_b['status']}"
    )

    # Reading is shared across all four planning roles.
    for user_id, role in (
        ("ops-admin-1", "MerchOpsAdmin"),
        (PLANNER_USER_ID, "MerchandisePlanner"),
        (DIRECTOR_USER_ID, "PlanningDirector"),
        ("buyer-1", "CategoryBuyer"),
    ):
        plan = validate_success(
            api.get_category_plan(plan_id, build_user_headers(user_id, role))
        )
        assert plan["status"] == "APPROVED", (
            f"{role} must be able to read the plan, got {plan['status']}"
        )

    rc_a = propose_commitment(month_id, item_a["id"], vendor_a)
    commit_commitment(rc_a["id"])
    rc_b = propose_commitment(month_id, item_b["id"], vendor_b)
    commit_commitment(rc_b["id"])

    rep_a_headers = make_vendor_rep_headers(vendor_a)

    # A VendorRep's READ scope is not narrowed to its own rows.
    other_commitment = validate_success(
        api.get_receipt_commitment(rc_b["id"], rep_a_headers)
    )
    assert other_commitment["vendor_id"] == vendor_b, (
        f"the read must return vendor B's commitment, got {other_commitment}"
    )
    assert other_commitment["commit_status"] == "COMMITTED", (
        f"vendor B's commitment must be COMMITTED, got {other_commitment}"
    )

    commitments, meta = validate_paginated(api.list_receipt_commitments(rep_a_headers))
    assert meta["total_count"] == 2, (
        "the receipt-commitment list is readable by a VendorRep and is not filtered to "
        f"its own rows, got total_count {meta['total_count']}"
    )

    other_vendor = validate_success(api.get_vendor(vendor_b, rep_a_headers))
    assert other_vendor["code"] == "BRVO", (
        f"a VendorRep may read vendors, got {other_vendor}"
    )

    # Its WRITE scope is narrowed to the commitments it owns.
    validate_error(
        api.ship_receipt_commitment(rc_b["id"], {}, rep_a_headers),
        ApiErrorId.ERR_NOT_COMMITMENT_VENDOR,
    )

    own = validate_success(api.ship_receipt_commitment(rc_a["id"], {}, rep_a_headers))
    assert own["fulfillment_status"] == "SHIPPED", (
        f"vendor A must be able to ship its own order, got {own}"
    )

    untouched = get_commitment(rc_b["id"])
    assert untouched["fulfillment_status"] == "AWAITING_SHIP", (
        "the refused ship must leave vendor B's order untouched, got "
        f"{untouched['fulfillment_status']}"
    )


# ---------------------------------------------------------------------------
# No operator may adjudicate what it submitted or proposed itself
# ---------------------------------------------------------------------------

def test_no_user_may_adjudicate_its_own_submission(api):
    """PRD §2.1: "Approving or rejecting a submitted category plan requires that the
    acting `X-User-ID` differ from the plan's recorded `submitted_by_user_id`; approving
    or rejecting a chase-or-cancel decision requires that the acting `X-User-ID` differ
    from the decision's recorded `proposed_by_user_id`."
    PRD §2.1: "Any of those four operations attempted by the originator is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (409)."
    PRD §2.8: "8. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES` (409), on
    `POST /otb/category-plans/{id}/approve`, `POST /otb/category-plans/{id}/reject`,
    `POST /otb/chase-cancel-decisions/{id}/approve` and
    `POST /otb/chase-cancel-decisions/{id}/reject`."

    Design: Corner/rbac/no_user_may_adjudicate_its_own_submission
    """
    scenario = setup_plan_scenario(
        month_specs=[dict(M1_SPEC)], submit=True, planner_user_id="dual-1"
    )
    plan_id = scenario["plan_id"]

    submitted = get_plan(plan_id)
    assert submitted["submitted_by_user_id"] == "dual-1", (
        f"the submitting operator must be recorded, got {submitted}"
    )

    # The same human wearing the director role cannot adjudicate its own submission,
    # on either verb, and the refusal is a conflict rather than an authorization error.
    validate_error(
        api.approve_category_plan(
            plan_id, {"approval_note": "signed off"}, make_director_headers("dual-1")
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    validate_error(
        api.reject_category_plan(
            plan_id, {"rejection_reason": "rework"}, make_director_headers("dual-1")
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    still_submitted = get_plan(plan_id)
    assert still_submitted["status"] == "SUBMITTED", (
        f"the refused adjudications must change nothing, got {still_submitted['status']}"
    )
    assert still_submitted["version"] == submitted["version"], (
        "the refused adjudications must not advance the plan's version, expected "
        f"{submitted['version']}, got {still_submitted['version']}"
    )

    # A different operator may.
    assert reject_plan(plan_id)["status"] == "DRAFT", (
        "a director who did not submit the plan must be able to reject it"
    )

    # Re-submission rewrites the recorded submitter, so the bar moves with it.
    resubmitted = submit_plan(plan_id, planner_user_id="dual-1")
    assert resubmitted["submitted_by_user_id"] == "dual-1", (
        f"the resubmission must rewrite submitted_by_user_id, got {resubmitted}"
    )
    validate_error(
        api.approve_category_plan(
            plan_id, {"approval_note": "signed off"}, make_director_headers("dual-1")
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    approved = approve_plan(plan_id)
    assert approved["status"] == "APPROVED", (
        f"a second operator must be able to approve, got {approved['status']}"
    )
    assert approved["approved_by_user_id"] == DIRECTOR_USER_ID, (
        f"the approving operator must be recorded, got {approved}"
    )

    # The same rule governs chase-or-cancel adjudication, against a different
    # recorded operator field.
    open_season(scenario["m1"]["id"], planner_user_id="dual-1")
    item = propose_item(scenario["option_plan"]["id"], scenario["vendor"]["id"])
    adopt_item(item["id"])
    activate_item(item["id"])

    cycle = open_reforecast_cycle(plan_id, planner_user_id="dual-1")

    proposed_by_buyer = validate_success(
        api.create_chase_cancel_decision(
            chase_cancel_decision_payload(
                cycle["id"],
                item["id"],
                action="HOLD",
                requested_units=0,
                rationale="hold this option while we watch it",
            ),
            make_buyer_headers("dual-2"),
        ),
        201,
    )
    assert proposed_by_buyer["proposed_by_user_id"] == "dual-2", (
        f"the proposing operator must be recorded, got {proposed_by_buyer}"
    )

    validate_error(
        api.approve_chase_cancel_decision(
            proposed_by_buyer["id"], {}, make_director_headers("dual-2")
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    adjudicated = approve_decision(proposed_by_buyer["id"])
    assert adjudicated["status"] == "APPROVED", (
        f"a second operator must be able to approve the decision, got {adjudicated}"
    )
    assert adjudicated["approved_units"] == 0, (
        f"a HOLD allocates nothing, got approved_units {adjudicated['approved_units']}"
    )

    # Rejection is guarded by the same comparison as approval.
    proposed_by_planner = propose_decision(
        cycle["id"],
        item["id"],
        action="HOLD",
        requested_units=0,
        rationale="hold this option for another week",
        proposer_user_id="dual-1",
    )
    assert proposed_by_planner["proposed_by_user_id"] == "dual-1", (
        f"the proposing operator must be recorded, got {proposed_by_planner}"
    )
    validate_error(
        api.reject_chase_cancel_decision(
            proposed_by_planner["id"], {}, make_director_headers("dual-1")
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    rejected = reject_decision(proposed_by_planner["id"])
    assert rejected["status"] == "REJECTED", (
        f"a second operator must be able to reject the decision, got {rejected}"
    )


# ---------------------------------------------------------------------------
# Both optimistic-concurrency rules, each on its own parent entity
# ---------------------------------------------------------------------------

def test_both_occ_rules_reject_a_stale_parent_version(api, planner_headers):
    """PRD §2.9: "The server compares that value to the stored `version` of the plan
    month named by `plan_month_id`; if the two differ, the create is rejected with
    `ERR_STALE_PLAN_MONTH_VERSION` (412)."
    PRD §3.6: "Creating the commitment advances the target plan month's version by 1
    even though a `PROPOSED` commitment has not yet entered the month's committed figure
    — which is exactly why the next buyer to size a buy from that month needs a fresh
    `expected_plan_month_version`."
    PRD §2.9: "The server compares that value to the stored `version` of the addressed
    category plan; if the two differ, the request is rejected with
    `ERR_STALE_CATEGORY_PLAN_VERSION` (412)."
    PRD §2.9: "The check is purely a comparison of the submitted number against the
    stored number; it never inspects request timing."

    Design: Corner/complexity_layers/both_occ_rules_reject_a_stale_parent_version
    """
    scenario = _two_month_approved()
    plan_id = scenario["plan_id"]
    month_id = scenario["m1"]["id"]
    vendor_id = scenario["vendor"]["id"]
    item = propose_item(scenario["option_plan"]["id"], vendor_id, unit_cost_cents=2600)

    before = get_month(month_id)
    month_version_0 = before["version"]
    assert before["otb_open_cents"] == CANONICAL_M1_OTB_PLANNED_CENTS, (
        f"expected an untouched otb_open_cents of 18200000, got {before}"
    )

    buy = {"units": 400, "unit_cost_cents": 2600}

    # First create against the observed version: accepted.
    first = validate_success(
        api.create_receipt_commitment(
            receipt_commitment_payload(
                month_id, item["id"], vendor_id, month_version_0, **buy
            ),
            BUYER_HEADERS,
        ),
        201,
    )
    assert first["commit_status"] == "PROPOSED", (
        f"a new commitment starts PROPOSED, got {first['commit_status']}"
    )

    after_first = get_month(month_id)
    month_version_1 = after_first["version"]
    assert month_version_1 == month_version_0 + 1, (
        "creating a commitment advances the month's version by 1, expected "
        f"{month_version_0 + 1}, got {month_version_1}"
    )
    assert after_first["otb_open_cents"] == CANONICAL_M1_OTB_PLANNED_CENTS, (
        "a PROPOSED commitment has not yet entered the month's committed figure, so "
        f"otb_open_cents must still be 18200000, got {after_first['otb_open_cents']}"
    )
    assert after_first["otb_committed_cents"] == 0, (
        f"expected otb_committed_cents 0 while the buy is only PROPOSED, got "
        f"{after_first['otb_committed_cents']}"
    )

    # A byte-identical create replaying the now-stale version: only the guard is at
    # fault, and the guard is a pure comparison.
    validate_error(
        api.create_receipt_commitment(
            receipt_commitment_payload(
                month_id, item["id"], vendor_id, month_version_0, **buy
            ),
            BUYER_HEADERS,
        ),
        ApiErrorId.ERR_STALE_PLAN_MONTH_VERSION,
    )

    # The same request refreshed against the current version succeeds, so a 412 is a
    # retryable staleness signal and not a permanent rejection.
    second = validate_success(
        api.create_receipt_commitment(
            receipt_commitment_payload(
                month_id, item["id"], vendor_id, month_version_1, **buy
            ),
            BUYER_HEADERS,
        ),
        201,
    )
    assert second["commit_status"] == "PROPOSED", (
        f"the refreshed create must be accepted, got {second['commit_status']}"
    )

    commitments, meta = validate_paginated(
        api.list_receipt_commitments(planner_headers, {"plan_month_id": month_id})
    )
    assert meta["total_count"] == 2, (
        "the rejected create must have persisted nothing, so only the two accepted "
        f"commitments may exist, got total_count {meta['total_count']}"
    )

    assert commit_commitment(first["id"])["commit_status"] == "COMMITTED", (
        "the first commitment must reach COMMITTED"
    )
    funded = get_month(month_id)
    assert funded["otb_committed_cents"] == 1040000, (
        f"400 units at 2600 cents must commit 1040000, got {funded}"
    )
    assert funded["otb_open_cents"] == 17160000, (
        f"expected otb_open_cents 17160000 after the commit, got {funded}"
    )

    after_commit = get_plan(plan_id)
    plan_version_0 = after_commit["version"]
    assert after_commit["open_ratio_bps"] == 9741, (
        f"expected open_ratio_bps 9741 across M1 and M2, got {after_commit}"
    )

    # Committing the second proposal moves the plan and strands plan_version_0.
    assert commit_commitment(second["id"])["commit_status"] == "COMMITTED", (
        "the second commitment must reach COMMITTED"
    )

    # A different guard field, a different parent entity and a different 412 code.
    validate_error(
        api.open_reforecast_cycle(
            plan_id,
            reforecast_payload(plan_version_0, reason_note="stale plan version"),
            planner_headers,
        ),
        ApiErrorId.ERR_STALE_CATEGORY_PLAN_VERSION,
    )

    stranded = get_plan(plan_id)
    assert stranded["version"] > plan_version_0, (
        "the second commit must have advanced the plan's version, expected more than "
        f"{plan_version_0}, got {stranded['version']}"
    )
    assert stranded["open_ratio_bps"] == 9482, (
        f"expected open_ratio_bps 9482 with both buys committed, got {stranded}"
    )
    assert stranded["status"] == "APPROVED", (
        f"the refused reforecast must leave the plan APPROVED, got {stranded['status']}"
    )
    assert stranded["reforecast_round"] == 0, (
        "the refused reforecast must not advance the round counter, got "
        f"{stranded['reforecast_round']}"
    )

    cycle = validate_success(
        api.open_reforecast_cycle(
            plan_id,
            reforecast_payload(stranded["version"], reason_note="fresh plan version"),
            planner_headers,
        ),
        201,
    )
    assert cycle["status"] == "OPEN", (
        f"the refreshed reforecast must open a cycle, got {cycle['status']}"
    )
    assert cycle["round_index"] == 1, (
        f"expected round_index 1, got {cycle['round_index']}"
    )

    reforecasting = get_plan(plan_id)
    assert reforecasting["status"] == "REFORECAST_OPEN", (
        f"expected REFORECAST_OPEN, got {reforecasting['status']}"
    )
    assert reforecasting["reforecast_round"] == 1, (
        f"expected reforecast_round 1, got {reforecasting['reforecast_round']}"
    )


# ---------------------------------------------------------------------------
# Every derived field is already readable in the response that wrote it
# ---------------------------------------------------------------------------

def test_every_derived_field_is_readable_in_the_same_response(api, director_headers):
    """PRD §2.10: "Consistency in this system is immediate: by the time a request
    returns, every derived field it touched has been rewritten."
    PRD §3.5: "For an item whose stage is `CARRYOVER`, `CORE` or `EXIT`, the **carryover
    basis** applies: the forecast is the item's own `prior_season_sell_through_bps`
    multiplied by the cluster's `demographic_index_bps`, divided by ten thousand,
    rounded half up, and then capped at 9800 basis points."
    PRD §3.5: "On success the item's `planned_units` is set to the cell's
    `target_units_per_option`, its `effective_overlay_multiplier_bps` is resolved, and
    its `sell_through_basis` and `sell_through_bps` are forecast."
    PRD §3.6: "On success the commitment's `open_cost_cents` is recomputed, the month's
    `otb_committed_cents` and `otb_open_cents` are recomputed and the month's version
    advances by 1, and the plan's `open_ratio_bps` and `otb_posture` are recomputed and
    the plan's version advances by 1."

    Design: Corner/consistency_model/every_derived_field_is_readable_in_the_same_response
    """
    scenario = setup_plan_scenario(
        month_specs=[dict(M1_SPEC), dict(M2_SPEC)], submit=True
    )
    plan_id = scenario["plan_id"]
    month_id = scenario["m1"]["id"]
    vendor_id = scenario["vendor"]["id"]
    cell_id = scenario["option_plan"]["id"]

    # The approval response itself already carries what cascade B's first and third
    # links wrote — no second call and no settling period.
    approve_response = validate_success(
        api.approve_category_plan(
            plan_id, {"approval_note": "signed off"}, director_headers
        )
    )
    assert approve_response["status"] == "APPROVED", (
        f"expected APPROVED in the action response, got {approve_response['status']}"
    )
    assert approve_response["receipt_budget_cents"] == CANONICAL_RECEIPT_BUDGET_CENTS, (
        "the approve response must already carry receipt_budget_cents 60000000, got "
        f"{approve_response['receipt_budget_cents']}"
    )
    assert approve_response["open_ratio_bps"] == 10000, (
        "the approve response must already carry open_ratio_bps 10000, got "
        f"{approve_response['open_ratio_bps']}"
    )
    assert approve_response["otb_posture"] == "OPEN", (
        f"the approve response must already carry otb_posture OPEN, got "
        f"{approve_response['otb_posture']}"
    )

    # And the month cascade is readable immediately, with no intermediate zero state.
    month_before = get_month(month_id)
    assert month_before["otb_planned_cents"] == CANONICAL_M1_OTB_PLANNED_CENTS, (
        f"expected otb_planned_cents 18200000 straight away, got {month_before}"
    )
    month_version_0 = month_before["version"]

    cell = get_option_plan(cell_id)
    assert cell["option_slots_total"] == CANONICAL_OPTION_SLOTS_TOTAL, (
        f"expected option_slots_total 14, got {cell['option_slots_total']}"
    )
    assert cell["target_units_per_option"] == CANONICAL_TARGET_UNITS_PER_OPTION, (
        f"expected target_units_per_option 276, got {cell}"
    )

    # A derived field that has not been computed yet is absent, which is different from
    # being stale.
    item = validate_success(
        api.create_assortment_item(
            assortment_item_payload(
                cell_id, vendor_id, unit_cost_cents=2600,
                prior_season_sell_through_bps=7100,
            ),
            BUYER_HEADERS,
        ),
        201,
    )
    assert item["planned_units"] is None, (
        f"a proposed item has no planned_units yet, got {item['planned_units']}"
    )
    assert item["sell_through_basis"] is None, (
        f"a proposed item has no sell_through_basis yet, got {item}"
    )
    assert item["sell_through_bps"] is None, (
        f"a proposed item has no sell_through_bps yet, got {item}"
    )
    assert item["effective_overlay_multiplier_bps"] == 10000, (
        "a proposed item starts at an unlocalized multiplier of 10000, got "
        f"{item['effective_overlay_multiplier_bps']}"
    )

    adopt_response = validate_success(
        api.adopt_assortment_item(item["id"], {}, BUYER_HEADERS)
    )
    assert adopt_response["status"] == "ADOPTED", (
        f"expected ADOPTED in the action response, got {adopt_response['status']}"
    )
    assert adopt_response["sell_through_basis"] == "CARRYOVER_BASIS", (
        "a CARRYOVER option is forecast on the carryover basis, got "
        f"{adopt_response['sell_through_basis']}"
    )
    assert adopt_response["sell_through_bps"] == 7455, (
        f"expected sell_through_bps 7455 in the adopt response, got {adopt_response}"
    )
    assert adopt_response["planned_units"] == CANONICAL_TARGET_UNITS_PER_OPTION, (
        f"expected planned_units 276 in the adopt response, got {adopt_response}"
    )

    # The immediate re-read is field-for-field identical: nothing settled in between.
    reread = get_item(item["id"])
    for field in ("status", "sell_through_basis", "sell_through_bps", "planned_units"):
        assert reread[field] == adopt_response[field], (
            f"the immediate re-read must match the action response on {field}: "
            f"{reread[field]} != {adopt_response[field]}"
        )

    commitment = validate_success(
        api.create_receipt_commitment(
            receipt_commitment_payload(
                month_id, item["id"], vendor_id, month_version_0,
                units=400, unit_cost_cents=2600,
            ),
            BUYER_HEADERS,
        ),
        201,
    )
    assert commitment["cost_cents"] == 1040000, (
        f"expected cost_cents 1040000 in the create response, got {commitment}"
    )
    assert commitment["open_cost_cents"] == 1040000, (
        f"expected open_cost_cents 1040000 in the create response, got {commitment}"
    )

    commit_response = validate_success(
        api.commit_receipt_commitment(commitment["id"], {}, BUYER_HEADERS)
    )
    assert commit_response["commit_status"] == "COMMITTED", (
        f"expected COMMITTED in the action response, got {commit_response}"
    )
    assert commit_response["open_cost_cents"] == 1040000, (
        f"expected open_cost_cents 1040000 in the commit response, got {commit_response}"
    )

    # One read after the write is sufficient, two entities away from it.
    month_after = get_month(month_id)
    assert month_after["otb_committed_cents"] == 1040000, (
        f"expected otb_committed_cents 1040000 on the first read, got {month_after}"
    )
    assert month_after["otb_open_cents"] == 17160000, (
        f"expected otb_open_cents 17160000 on the first read, got {month_after}"
    )
    assert month_after["version"] == month_version_0 + 2, (
        "the create advanced the month by 1 and the commit by 1, expected version "
        f"{month_version_0 + 2}, got {month_after['version']}"
    )

    plan_after = get_plan(plan_id)
    assert plan_after["open_ratio_bps"] == 9741, (
        f"expected open_ratio_bps 9741 on the first read, got {plan_after}"
    )
    assert plan_after["otb_posture"] == "OPEN", (
        f"expected otb_posture OPEN on the first read, got {plan_after}"
    )
