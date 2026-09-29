"""Entity lifecycles, terminal states and closure cascades.

Every test in this module builds its own world from scratch against an empty
database and drives one declared lifecycle edge (or one declared refusal) of the
Assortment Planning & Open-to-Buy API.
"""
from test_helpers import (
    ADMIN_HEADERS,
    BUYER_HEADERS,
    CANONICAL,
    CLOCK_STARTUP_UTC,
    DIRECTOR_HEADERS,
    DIRECTOR_USER_ID,
    PLANNER_HEADERS,
    PLANNER_USER_ID,
    SECOND_DIRECTOR_USER_ID,
    SECOND_PLANNER_USER_ID,
    ApiErrorId,
    activate_item,
    adopt_item,
    category_plan_payload,
    create_category,
    create_department,
    create_overlay,
    create_plan_month,
    create_vendor,
    create_vendor_authorization,
    get_commitment,
    get_cycle,
    get_decision,
    get_item,
    get_month,
    get_option_plan,
    get_overlay,
    get_plan,
    make_director_headers,
    make_planner_headers,
    make_vendor_rep_headers,
    month_version,
    open_reforecast_cycle,
    option_plan_payload,
    plan_month_payload,
    propose_commitment,
    propose_decision,
    propose_item,
    receipt_commitment_payload,
    set_clock,
    setup_plan_scenario,
    setup_reference_spine,
    validate_error,
    validate_paginated,
    validate_success,
    vendor_authorization_payload,
    vendor_payload,
)

# A two-row balanced curve: 40/60 over the canonical BETTER cell allocates
# 110 and 166 of the cell's 276 units, so no row rounds to zero.
TWO_CELL_CURVE = [
    {"size_label": "S", "size_sort_order": 1, "pct_bps": 4000},
    {"size_label": "L", "size_sort_order": 2, "pct_bps": 6000},
]

SINGLE_MONTH = [dict(CANONICAL["month_1"])]

LATE_SHIP_WINDOW = {
    "ship_window_start": "2027-02-01T00:00:00Z",
    "ship_window_end": "2027-02-15T00:00:00Z",
}


# ─────────────────────────────────────────────────────────────────────────────
# Declared initial states
# ─────────────────────────────────────────────────────────────────────────────

def test_vendor_starts_pending_and_its_authorization_starts_active(api):
    """PRD §3.2: "The vendor's `status` is server-owned and is initialised to `PENDING`."

    PRD §3.2: "Its `status` is server-owned, initialised to `ACTIVE`, and only ever `ACTIVE` or `REVOKED` thereafter, moving between the two only through the vendor's suspension and reinstatement described above."

    PRD §2.4: "`version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row"

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    set_clock(CLOCK_STARTUP_UTC)
    department = create_department()
    category = create_category(department["id"])

    vendor = validate_success(
        api.create_vendor(vendor_payload(), ADMIN_HEADERS), 201
    )
    assert vendor["status"] == "PENDING", (
        f"A newly created vendor must start PENDING, got {vendor['status']}"
    )
    assert vendor["version"] == 1, (
        f"A newly created vendor must be at version 1, got {vendor['version']}"
    )

    authorization = validate_success(
        api.create_vendor_authorization(
            vendor_authorization_payload(vendor["id"], category["id"]), ADMIN_HEADERS
        ),
        201,
    )
    assert authorization["status"] == "ACTIVE", (
        "A vendor authorization must start ACTIVE even while its vendor is still "
        f"PENDING, got {authorization['status']}"
    )
    assert authorization["version"] == 1, (
        f"A new authorization must be at version 1, got {authorization['version']}"
    )


def test_category_plan_starts_draft_with_every_governance_default(api):
    """PRD §3.3: "`status` starts at `DRAFT`."

    PRD §3.3: "`receipt_budget_cents` starts as null and stays null until the plan's first approval computes it."

    PRD §3.3: "`otb_posture` starts at `OPEN`, `open_ratio_bps` at 10000, `variance_status` at `ON_PLAN` and `sales_variance_bps` at 0."

    PRD §3.3: "Both actor records, `submitted_by_user_id` and `approved_by_user_id`, start null and are written by the submit and approve steps respectively."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    spine = setup_reference_spine()

    plan = validate_success(
        api.create_category_plan(
            category_plan_payload(spine["category"]["id"]), PLANNER_HEADERS
        ),
        201,
    )

    assert plan["status"] == "DRAFT", f"A new plan must start DRAFT, got {plan['status']}"
    assert plan["reforecast_round"] == 0, (
        f"reforecast_round must start at 0, got {plan['reforecast_round']}"
    )
    assert plan["receipt_budget_cents"] is None, (
        "receipt_budget_cents must stay null until the first approval, got "
        f"{plan['receipt_budget_cents']}"
    )
    assert plan["otb_posture"] == "OPEN", (
        f"otb_posture must start OPEN, got {plan['otb_posture']}"
    )
    assert plan["open_ratio_bps"] == 10000, (
        f"open_ratio_bps must start at 10000, got {plan['open_ratio_bps']}"
    )
    assert plan["variance_status"] == "ON_PLAN", (
        f"variance_status must start ON_PLAN, got {plan['variance_status']}"
    )
    assert plan["sales_variance_bps"] == 0, (
        f"sales_variance_bps must start at 0, got {plan['sales_variance_bps']}"
    )
    assert plan["submitted_by_user_id"] is None, (
        "submitted_by_user_id must start null, got "
        f"{plan['submitted_by_user_id']}"
    )
    assert plan["approved_by_user_id"] is None, (
        "approved_by_user_id must start null, got "
        f"{plan['approved_by_user_id']}"
    )
    assert plan["version"] == 1, f"A new plan must be at version 1, got {plan['version']}"


def test_plan_month_starts_draft_on_planned_basis_with_zero_open_to_buy(api):
    """PRD §3.3: "A new month is created in `DRAFT` with `active_basis` set to `PLANNED_BASIS` and with every computed open-to-buy figure — `provisional_sell_through_bps`, `reserve_rate_bps`, `markdown_reserve_cents`, `otb_planned_cents`, `otb_committed_cents`, `otb_received_cents` and `otb_open_cents` — at 0."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    spine = setup_reference_spine()
    plan = validate_success(
        api.create_category_plan(
            category_plan_payload(spine["category"]["id"]), PLANNER_HEADERS
        ),
        201,
    )

    month = validate_success(
        api.create_plan_month(plan_month_payload(plan["id"]), PLANNER_HEADERS), 201
    )

    assert month["status"] == "DRAFT", (
        f"A new plan month must start DRAFT, got {month['status']}"
    )
    assert month["active_basis"] == "PLANNED_BASIS", (
        f"A new plan month must start on PLANNED_BASIS, got {month['active_basis']}"
    )
    for field in (
        "provisional_sell_through_bps",
        "reserve_rate_bps",
        "markdown_reserve_cents",
        "otb_planned_cents",
        "otb_committed_cents",
        "otb_received_cents",
        "otb_open_cents",
    ):
        assert month[field] == 0, (
            f"A new plan month must carry {field} == 0 before any approval locks it, "
            f"got {month[field]}"
        )
    assert month["version"] == 1, (
        f"A new plan month must be at version 1, got {month['version']}"
    )


def test_option_plan_starts_open_with_null_slot_counts(api):
    """PRD §3.3: "A new cell is created with `status` `OPEN`, `option_slots_assigned` at 0, and `option_slots_total`, `option_slots_open` and `target_units_per_option` all null."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    spine = setup_reference_spine()
    plan = validate_success(
        api.create_category_plan(
            category_plan_payload(spine["category"]["id"]), PLANNER_HEADERS
        ),
        201,
    )

    cell = validate_success(
        api.create_option_plan(
            option_plan_payload(plan["id"], spine["store_cluster"]["id"]),
            PLANNER_HEADERS,
        ),
        201,
    )

    assert cell["status"] == "OPEN", (
        f"A new option plan cell must start OPEN, got {cell['status']}"
    )
    assert cell["option_slots_assigned"] == 0, (
        f"option_slots_assigned must start at 0, got {cell['option_slots_assigned']}"
    )
    assert cell["option_slots_total"] is None, (
        f"option_slots_total must start null, got {cell['option_slots_total']}"
    )
    assert cell["option_slots_open"] is None, (
        f"option_slots_open must start null, got {cell['option_slots_open']}"
    )
    assert cell["target_units_per_option"] is None, (
        "target_units_per_option must start null, got "
        f"{cell['target_units_per_option']}"
    )
    assert cell["version"] == 1, (
        f"A new option plan must be at version 1, got {cell['version']}"
    )


def test_assortment_item_starts_proposed_with_a_neutral_overlay_multiplier(api):
    """PRD §3.5: "A newly proposed item has `status` `PROPOSED`, `sell_through_basis` and `sell_through_bps` and `planned_units` all null, and `effective_overlay_multiplier_bps` at 10000."

    PRD §3.5: "The optional `prior_season_sell_through_bps`, between 0 and 10000 and defaulting to 0 when omitted, is the option's own history"

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    spine = setup_reference_spine()
    plan = validate_success(
        api.create_category_plan(
            category_plan_payload(spine["category"]["id"]), PLANNER_HEADERS
        ),
        201,
    )
    cell = validate_success(
        api.create_option_plan(
            option_plan_payload(plan["id"], spine["store_cluster"]["id"]),
            PLANNER_HEADERS,
        ),
        201,
    )

    item = validate_success(
        api.create_assortment_item(
            {
                "option_plan_id": cell["id"],
                "vendor_id": spine["vendor"]["id"],
                "sku_code": "DR-1001",
                "color_code": "BLK",
                "lifecycle_stage": "NEW",
                "unit_cost_cents": 2600,
                "retail_price_cents": 7900,
            },
            BUYER_HEADERS,
        ),
        201,
    )

    assert item["status"] == "PROPOSED", (
        f"A newly proposed item must start PROPOSED, got {item['status']}"
    )
    assert item["sell_through_basis"] is None, (
        f"sell_through_basis must start null, got {item['sell_through_basis']}"
    )
    assert item["sell_through_bps"] is None, (
        f"sell_through_bps must start null, got {item['sell_through_bps']}"
    )
    assert item["planned_units"] is None, (
        f"planned_units must start null, got {item['planned_units']}"
    )
    assert item["effective_overlay_multiplier_bps"] == 10000, (
        "effective_overlay_multiplier_bps must start at the neutral 10000, got "
        f"{item['effective_overlay_multiplier_bps']}"
    )
    assert item["prior_season_sell_through_bps"] == 0, (
        "an omitted prior_season_sell_through_bps must default to 0, got "
        f"{item['prior_season_sell_through_bps']}"
    )
    assert item["version"] == 1, (
        f"A new assortment item must be at version 1, got {item['version']}"
    )


def test_localization_overlay_starts_draft(api):
    """PRD §3.5: "Overlays are created in `DRAFT` and can be listed narrowed by `category_plan_id`, `store_cluster_id`, `overlay_type` or `status`."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    spine = setup_reference_spine()
    plan = validate_success(
        api.create_category_plan(
            category_plan_payload(spine["category"]["id"]), PLANNER_HEADERS
        ),
        201,
    )
    validate_success(
        api.create_option_plan(
            option_plan_payload(plan["id"], spine["store_cluster"]["id"]),
            PLANNER_HEADERS,
        ),
        201,
    )

    overlay = validate_success(
        api.create_localization_overlay(
            {
                "category_plan_id": plan["id"],
                "store_cluster_id": spine["store_cluster"]["id"],
                "overlay_type": "CLIMATE",
                "effective_start": "2026-08-01T00:00:00Z",
                "effective_end": "2026-08-31T00:00:00Z",
                "unit_multiplier_bps": 11000,
            },
            PLANNER_HEADERS,
        ),
        201,
    )

    assert overlay["status"] == "DRAFT", (
        f"A new localization overlay must start DRAFT, got {overlay['status']}"
    )
    assert overlay["version"] == 1, (
        f"A new overlay must be at version 1, got {overlay['version']}"
    )


def test_client_may_not_choose_a_server_owned_initial_state(api):
    """PRD §3.2: "The vendor's `status` is server-owned and is initialised to `PENDING`."

    PRD §2.8: "Request-body shape: every required field present, every value of its declared JSON type, every enum value a declared member, every integer within its declared range, every string within its declared length bounds, every ISO-8601 field parseable, and no unknown body field — `ERR_INVALID_REQUEST` (400), on every POST and PUT endpoint."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    set_clock(CLOCK_STARTUP_UTC)

    payload = vendor_payload()
    payload["status"] = "AUTHORIZED"

    validate_error(
        api.create_vendor(payload, ADMIN_HEADERS), ApiErrorId.ERR_INVALID_REQUEST
    )


# ─────────────────────────────────────────────────────────────────────────────
# The vendor's cyclic authorization loop
# ─────────────────────────────────────────────────────────────────────────────

def test_vendor_suspend_reinstate_cycle_drives_authorizations_both_ways(api):
    """PRD §3.2: "An `AUTHORIZED` vendor may be moved to `SUSPENDED`, which additionally revokes every one of that vendor's authorizations: each vendor authorization whose `status` is `ACTIVE` is set to `REVOKED`."

    PRD §3.2: "A `SUSPENDED` vendor may be reinstated to `AUTHORIZED`, and reinstatement is the exact mirror of suspension — every vendor authorization of that vendor whose `status` is `REVOKED` is restored to `ACTIVE`, so reinstatement returns precisely the authorizations the suspension took away."

    PRD §3.2: "There is no direct move from `PENDING` to `SUSPENDED`; requesting a transition the vendor's current status does not declare is rejected with `ERR_INVALID_STATE`."

    PRD §2.4: "`version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row"

    Design: Corner/state_machines/vendor_suspend_reinstate_authorization_cycle
    """
    set_clock(CLOCK_STARTUP_UTC)
    department = create_department()
    category_a = create_category(department["id"])
    category_b = create_category(
        department["id"], name="Knits", code="KNIT", role="CONVENIENCE",
        sales_share_bps=2000,
    )
    vendor = create_vendor()
    authorization_a = create_vendor_authorization(
        vendor["id"], category_a["id"], max_open_units=40000
    )
    authorization_b = create_vendor_authorization(
        vendor["id"], category_b["id"], max_open_units=15000
    )

    # ── lap one: AUTHORIZED -> SUSPENDED sweeps both authorizations to REVOKED
    suspended = validate_success(
        api.set_vendor_status(vendor["id"], {"status": "SUSPENDED"}, ADMIN_HEADERS)
    )
    assert suspended["status"] == "SUSPENDED", (
        f"An AUTHORIZED vendor must move to SUSPENDED, got {suspended['status']}"
    )
    assert suspended["version"] == 3, (
        "The vendor's version must be 3 after create, AUTHORIZED and SUSPENDED, got "
        f"{suspended['version']}"
    )

    _, revoked_meta = validate_paginated(
        api.list_vendor_authorizations(
            ADMIN_HEADERS, params={"vendor_id": vendor["id"], "status": "REVOKED"}
        )
    )
    assert revoked_meta["total_count"] == 2, (
        "Suspension must revoke every ACTIVE authorization of the vendor, expected 2 "
        f"REVOKED rows, got {revoked_meta['total_count']}"
    )
    _, active_meta = validate_paginated(
        api.list_vendor_authorizations(
            ADMIN_HEADERS, params={"vendor_id": vendor["id"], "status": "ACTIVE"}
        )
    )
    assert active_meta["total_count"] == 0, (
        "No authorization of a SUSPENDED vendor may remain ACTIVE, got "
        f"{active_meta['total_count']}"
    )

    # ── reinstatement is the exact mirror
    reinstated = validate_success(
        api.set_vendor_status(vendor["id"], {"status": "AUTHORIZED"}, ADMIN_HEADERS)
    )
    assert reinstated["status"] == "AUTHORIZED", (
        f"A SUSPENDED vendor must be reinstatable to AUTHORIZED, got {reinstated['status']}"
    )
    for authorization, ceiling in ((authorization_a, 40000), (authorization_b, 15000)):
        row = validate_success(
            api.get_vendor_authorization(authorization["id"], ADMIN_HEADERS)
        )
        assert row["status"] == "ACTIVE", (
            "Reinstatement must restore exactly the rows the suspension revoked, "
            f"authorization {authorization['id']} is {row['status']}"
        )
        assert row["max_open_units"] == ceiling, (
            "Reinstatement restores the same authorization row rather than recreating "
            f"it, expected max_open_units {ceiling}, got {row['max_open_units']}"
        )

    # ── lap two: the states loop, the versions do not
    validate_success(
        api.set_vendor_status(vendor["id"], {"status": "SUSPENDED"}, ADMIN_HEADERS)
    )
    after_two_laps = validate_success(
        api.set_vendor_status(vendor["id"], {"status": "AUTHORIZED"}, ADMIN_HEADERS)
    )
    assert after_two_laps["status"] == "AUTHORIZED", (
        "Two full laps must leave the vendor AUTHORIZED again, got "
        f"{after_two_laps['status']}"
    )
    assert after_two_laps["version"] == 6, (
        "Five status mutations on top of the create must leave the vendor at version 6, "
        f"got {after_two_laps['version']}"
    )
    for authorization in (authorization_a, authorization_b):
        row = validate_success(
            api.get_vendor_authorization(authorization["id"], ADMIN_HEADERS)
        )
        assert row["status"] == "ACTIVE", (
            f"After two laps authorization {authorization['id']} must be ACTIVE again, "
            f"got {row['status']}"
        )
        assert row["version"] == 5, (
            "Four cascade writes on top of the create must leave the authorization at "
            f"version 5, got {row['version']}"
        )

    # ── AUTHORIZED -> AUTHORIZED is not a declared transition
    validate_error(
        api.set_vendor_status(vendor["id"], {"status": "AUTHORIZED"}, ADMIN_HEADERS),
        ApiErrorId.ERR_INVALID_STATE,
    )
    unchanged = validate_success(api.get_vendor(vendor["id"], ADMIN_HEADERS))
    assert unchanged["status"] == "AUTHORIZED", (
        f"The rejected repeat must not change the status, got {unchanged['status']}"
    )
    assert unchanged["version"] == 6, (
        f"The rejected repeat must not advance the version, got {unchanged['version']}"
    )


def test_pending_vendor_cannot_be_suspended_directly(api):
    """PRD §3.2: "There is no direct move from `PENDING` to `SUSPENDED`; requesting a transition the vendor's current status does not declare is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/vendor_suspend_reinstate_authorization_cycle
    """
    set_clock(CLOCK_STARTUP_UTC)
    vendor = create_vendor(authorized=False)
    assert vendor["status"] == "PENDING", (
        f"Setup expects a PENDING vendor, got {vendor['status']}"
    )

    validate_error(
        api.set_vendor_status(vendor["id"], {"status": "SUSPENDED"}, ADMIN_HEADERS),
        ApiErrorId.ERR_INVALID_STATE,
    )

    unchanged = validate_success(api.get_vendor(vendor["id"], ADMIN_HEADERS))
    assert unchanged["status"] == "PENDING", (
        f"The rejected suspension must leave the vendor PENDING, got {unchanged['status']}"
    )
    assert unchanged["version"] == 1, (
        f"The rejected suspension must not advance the version, got {unchanged['version']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Closing a plan sweeps its children
# ─────────────────────────────────────────────────────────────────────────────

def test_plan_close_sweeps_months_option_plans_and_open_cycle(api):
    """PRD §3.9: "The plan's `status` becomes `CLOSED`, a terminal state from which nothing further is possible."

    PRD §3.9: "Every plan month of the plan whose `status` is `DRAFT`, `LOCKED_PLAN` or `IN_SEASON` moves to `CLOSED`, and every option plan of the plan whose `status` is `OPEN` or `SLOTTED` moves to `CLOSED`."

    PRD §3.9: "Every reforecast cycle of the plan whose `status` is `OPEN` advances `OPEN → ABANDONED`, and each of that cycle's decisions still sitting at `PROPOSED` is set to `REJECTED` with `approved_units` written as 0."

    Design: Corner/state_machines/plan_close_cascade_closes_children_and_abandons_open_cycle
    """
    scenario = setup_plan_scenario(approve=True, open_season_month_indexes=(1,))
    plan_id = scenario["plan_id"]
    m1_id = scenario["m1"]["id"]
    m2_id = scenario["m2"]["id"]
    option_plan_id = scenario["option_plan"]["id"]

    # A month added after the approval is still DRAFT — a third distinct source state.
    m3 = create_plan_month(
        plan_id, month_index=3, fiscal_month_label="2027-05",
        first_receipt_date="2027-05-07T00:00:00Z", bom_inventory_cents=24_000_000,
        planned_sales_cents=20_000_000, planned_markdown_cents=1_000_000,
        planned_eom_cents=20_000_000,
    )
    assert m3["status"] == "DRAFT", (
        f"A month added after approval must start DRAFT, got {m3['status']}"
    )
    assert get_month(m1_id)["status"] == "IN_SEASON", "Setup expects M1 IN_SEASON"
    assert get_month(m2_id)["status"] == "LOCKED_PLAN", "Setup expects M2 LOCKED_PLAN"

    item = propose_item(
        option_plan_id, scenario["vendor"]["id"], headers=BUYER_HEADERS,
        sku_code="DR-1001", color_code="BLK", lifecycle_stage="NEW",
        unit_cost_cents=2600, retail_price_cents=7900,
    )
    adopt_item(item["id"])
    activate_item(item["id"])

    cycle = open_reforecast_cycle(
        plan_id, reason_note="wholesale re-read of the spring buy"
    )
    decision = propose_decision(
        cycle["id"], item["id"], action="CHASE", requested_units=500,
        rationale="sell-through running ahead of plan",
        proposer_user_id=SECOND_PLANNER_USER_ID,
    )

    closed = validate_success(api.close_category_plan(plan_id, {}, DIRECTOR_HEADERS))

    assert closed["status"] == "CLOSED", (
        f"The close must land the plan in its only terminal state, got {closed['status']}"
    )
    for label, month_id in (("M1 (IN_SEASON)", m1_id), ("M2 (LOCKED_PLAN)", m2_id),
                            ("M3 (DRAFT)", m3["id"])):
        month = get_month(month_id)
        assert month["status"] == "CLOSED", (
            f"One close call must sweep {label} to CLOSED, got {month['status']}"
        )
    assert get_month(m1_id)["otb_planned_cents"] == 18200000, (
        "Closing a month freezes its ledger rather than zeroing it, expected M1 "
        f"otb_planned_cents 18200000, got {get_month(m1_id)['otb_planned_cents']}"
    )
    assert get_month(m2_id)["otb_planned_cents"] == 21970000, (
        "Closing a month freezes its ledger rather than zeroing it, expected M2 "
        f"otb_planned_cents 21970000, got {get_month(m2_id)['otb_planned_cents']}"
    )

    option_plan = get_option_plan(option_plan_id)
    assert option_plan["status"] == "CLOSED", (
        f"A SLOTTED option plan must be swept to CLOSED, got {option_plan['status']}"
    )
    assert option_plan["option_slots_total"] == 14, (
        f"Slot totals are frozen, not released, got {option_plan['option_slots_total']}"
    )
    assert option_plan["option_slots_assigned"] == 1, (
        "The adopted option keeps its slot through the close, got "
        f"{option_plan['option_slots_assigned']}"
    )
    assert option_plan["option_slots_open"] == 13, (
        f"Open slots are frozen, not released, got {option_plan['option_slots_open']}"
    )

    abandoned = get_cycle(cycle["id"])
    assert abandoned["status"] == "ABANDONED", (
        f"An OPEN reforecast cycle must be abandoned by the close, got {abandoned['status']}"
    )
    rejected = get_decision(decision["id"])
    assert rejected["status"] == "REJECTED", (
        f"A PROPOSED decision of the abandoned cycle must be REJECTED, got {rejected['status']}"
    )
    assert rejected["approved_units"] == 0, (
        f"The swept decision's approved_units must be written as 0, got {rejected['approved_units']}"
    )

    _, commitment_meta = validate_paginated(
        api.list_receipt_commitments(BUYER_HEADERS, params={"plan_month_id": m1_id})
    )
    assert commitment_meta["total_count"] == 0, (
        "The abandoned decision never allocated, so no commitment exists, got "
        f"{commitment_meta['total_count']}"
    )

    survivor = get_item(item["id"])
    assert survivor["status"] == "IN_SEASON", (
        "The close cascade names months, option plans and cycles only, so the item is "
        f"untouched, got {survivor['status']}"
    )
    assert survivor["planned_units"] == 276, (
        f"The item's planned units are untouched, got {survivor['planned_units']}"
    )
    assert survivor["sell_through_bps"] == 6325, (
        f"The item's forecast is untouched, got {survivor['sell_through_bps']}"
    )

    assert closed["receipt_budget_cents"] == 60000000, (
        "Closing does not unwind governance history, expected receipt_budget_cents "
        f"60000000, got {closed['receipt_budget_cents']}"
    )
    assert closed["reforecast_round"] == 1, (
        f"Closing does not unwind the reforecast round, got {closed['reforecast_round']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLOSED is terminal, and the refusals are not all the same code
# ─────────────────────────────────────────────────────────────────────────────

def _closed_single_month_plan(api):
    """A CLOSED plan with a CLOSED month M1, a CLOSED option plan and a PROPOSED item."""
    scenario = setup_plan_scenario(
        month_specs=SINGLE_MONTH, size_curve=TWO_CELL_CURVE
    )
    item = propose_item(
        scenario["option_plan"]["id"], scenario["vendor"]["id"], headers=BUYER_HEADERS,
        sku_code="DR-1001", color_code="BLK", lifecycle_stage="NEW",
        unit_cost_cents=2600, retail_price_cents=7900,
    )
    validate_success(
        api.submit_category_plan(
            scenario["plan_id"], {"submission_note": "spring build"}, PLANNER_HEADERS
        )
    )
    validate_success(
        api.approve_category_plan(
            scenario["plan_id"], {"approval_note": "signed off"}, DIRECTOR_HEADERS
        )
    )
    validate_success(api.close_category_plan(scenario["plan_id"], {}, DIRECTOR_HEADERS))
    scenario["item"] = item
    return scenario


def test_closed_plan_refuses_every_governance_trigger(api):
    """PRD §3.9: "The plan's `status` becomes `CLOSED`, a terminal state from which nothing further is possible."

    PRD §3.4: "Submission from any other status is rejected with `ERR_INVALID_STATE`."

    PRD §2.8: "9. The target row currently sits in a state from which the requested transition is declared — `ERR_INVALID_STATE` (409), on every action endpoint: plan submit, approve, reject and close; month open-season; item adopt, activate and close; commitment commit, cancel, ship and receipt posting; decision approve and reject; overlay activate; and reforecast-cycle close."

    Design: Corner/state_machines/closed_plan_terminal_state_lockdown
    """
    scenario = _closed_single_month_plan(api)
    plan_id = scenario["plan_id"]
    m1_id = scenario["m1"]["id"]

    closed_plan = get_plan(plan_id)
    assert closed_plan["status"] == "CLOSED", (
        f"Setup expects a CLOSED plan, got {closed_plan['status']}"
    )
    plan_v = closed_plan["version"]
    m1 = get_month(m1_id)
    assert m1["status"] == "CLOSED", f"Setup expects a CLOSED month, got {m1['status']}"
    m1_v = m1["version"]

    validate_error(
        api.submit_category_plan(
            plan_id, {"submission_note": "reopen please"}, PLANNER_HEADERS
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )
    # The acting director differs from the recorded submitter, so segregation of duties
    # passes and the terminal state is what answers.
    validate_error(
        api.approve_category_plan(plan_id, {"approval_note": "again"}, DIRECTOR_HEADERS),
        ApiErrorId.ERR_INVALID_STATE,
    )
    validate_error(
        api.close_category_plan(plan_id, {}, DIRECTOR_HEADERS),
        ApiErrorId.ERR_INVALID_STATE,
    )
    # The month's own terminal state answers before the plan's approval gate.
    validate_error(
        api.open_season(m1_id, {}, PLANNER_HEADERS),
        ApiErrorId.ERR_INVALID_STATE,
    )

    assert get_plan(plan_id)["version"] == plan_v, (
        f"Four rejected calls must not advance the plan's version from {plan_v}"
    )
    assert get_month(m1_id)["version"] == m1_v, (
        f"Four rejected calls must not advance the month's version from {m1_v}"
    )
    assert get_plan(plan_id)["status"] == "CLOSED", "The plan must remain CLOSED"
    assert get_month(m1_id)["status"] == "CLOSED", "The month must remain CLOSED"


def test_closed_children_refuse_spending_with_their_own_codes(api):
    """PRD §2.8: "10. The referenced plan month is in the status the operation requires — `ERR_PLAN_MONTH_NOT_OPEN` (409), on `POST /otb/receipt-commitments` and `POST /otb/receipt-commitments/{id}/commit` (which require `LOCKED_PLAN` or `IN_SEASON`) and on `POST /otb/actuals-posts` (which requires `IN_SEASON`)."

    PRD §2.8: "11. The option plan behind the item being adopted is `SLOTTED` — `ERR_OPTION_PLAN_NOT_SLOTTED` (409), on `POST /otb/assortment-items/{id}/adopt`."

    PRD §3.9: "Every plan month of the plan whose `status` is `DRAFT`, `LOCKED_PLAN` or `IN_SEASON` moves to `CLOSED`, and every option plan of the plan whose `status` is `OPEN` or `SLOTTED` moves to `CLOSED`."

    Design: Corner/state_machines/closed_plan_terminal_state_lockdown
    """
    scenario = _closed_single_month_plan(api)
    m1_id = scenario["m1"]["id"]
    option_plan_id = scenario["option_plan"]["id"]
    item_id = scenario["item"]["id"]

    m1 = get_month(m1_id)
    m1_v = m1["version"]
    option_plan = get_option_plan(option_plan_id)
    assert option_plan["status"] == "CLOSED", (
        f"Setup expects a CLOSED option plan, got {option_plan['status']}"
    )
    option_plan_v = option_plan["version"]

    # A commitment create declares no transition of its own, so the CLOSED month is
    # caught by the spend gate rather than by state legality.
    validate_error(
        api.create_receipt_commitment(
            receipt_commitment_payload(
                m1_id, item_id, scenario["vendor"]["id"], m1_v,
                units=400, unit_cost_cents=2600, **LATE_SHIP_WINDOW
            ),
            BUYER_HEADERS,
        ),
        ApiErrorId.ERR_PLAN_MONTH_NOT_OPEN,
    )
    # PROPOSED -> ADOPTED is a declared transition, so the CLOSED cell answers next.
    validate_error(
        api.adopt_assortment_item(item_id, {}, BUYER_HEADERS),
        ApiErrorId.ERR_OPTION_PLAN_NOT_SLOTTED,
    )

    assert get_month(m1_id)["version"] == m1_v, (
        f"The rejected commitment must not advance the month's version from {m1_v}"
    )
    assert get_option_plan(option_plan_id)["version"] == option_plan_v, (
        "The rejected adoption must not advance the option plan's version from "
        f"{option_plan_v}"
    )
    assert get_option_plan(option_plan_id)["option_slots_assigned"] == 0, (
        "The rejected adoption must not consume a slot, got "
        f"{get_option_plan(option_plan_id)['option_slots_assigned']}"
    )
    survivor = get_item(item_id)
    assert survivor["status"] == "PROPOSED", (
        f"The item must still be PROPOSED after both refusals, got {survivor['status']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Replaying an accepted governance action is a rejection, not a no-op
# ─────────────────────────────────────────────────────────────────────────────

def test_second_submit_is_rejected_and_does_not_restamp_the_submitter(api):
    """PRD §3.4: "A plan leaves the planner's hands by being submitted, which advances `DRAFT → SUBMITTED` and records the submitting operator's `X-User-ID` into `submitted_by_user_id`."

    PRD §3.4: "Submission from any other status is rejected with `ERR_INVALID_STATE`."

    PRD §2.4: "`version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row"

    Design: Corner/state_machines/submit_and_approve_are_not_idempotent
    """
    scenario = setup_plan_scenario(month_specs=SINGLE_MONTH, size_curve=TWO_CELL_CURVE)
    plan_id = scenario["plan_id"]

    submitted = validate_success(
        api.submit_category_plan(
            plan_id, {"submission_note": "first submit"}, PLANNER_HEADERS
        )
    )
    assert submitted["status"] == "SUBMITTED", (
        f"The first submit must advance DRAFT -> SUBMITTED, got {submitted['status']}"
    )
    assert submitted["submitted_by_user_id"] == PLANNER_USER_ID, (
        "The submit must record the submitting operator, expected "
        f"{PLANNER_USER_ID}, got {submitted['submitted_by_user_id']}"
    )
    assert submitted["version"] == 2, (
        f"Create wrote version 1 and the submit adds 1, got {submitted['version']}"
    )

    validate_error(
        api.submit_category_plan(
            plan_id, {"submission_note": "second submit"},
            make_planner_headers(SECOND_PLANNER_USER_ID),
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )

    replayed = get_plan(plan_id)
    assert replayed["submitted_by_user_id"] == PLANNER_USER_ID, (
        "The rejected replay must not restamp the submitter with the replaying "
        f"planner, got {replayed['submitted_by_user_id']}"
    )
    assert replayed["version"] == 2, (
        f"The rejected replay must not advance the version past 2, got {replayed['version']}"
    )
    assert replayed["status"] == "SUBMITTED", (
        f"The plan must still be SUBMITTED, got {replayed['status']}"
    )


def test_second_approve_is_rejected_and_does_not_recompute_the_budget(api):
    """PRD §3.4: "**Link 1** sets the plan's `status` to `APPROVED`, records the approving operator's `X-User-ID` into `approved_by_user_id`, pins `receipt_budget_cents` to the figure just computed, and advances the plan's version by 1."

    PRD §3.4: "**Link 3** is caused by link 2 creating the plan's first locked months: the plan's **posture** is recomputed and `open_ratio_bps` and `otb_posture` are written, advancing the plan's version by 1 a second time — so a single approval request raises the plan's `version` by 2 in total."

    PRD §2.8: "9. The target row currently sits in a state from which the requested transition is declared — `ERR_INVALID_STATE` (409), on every action endpoint: plan submit, approve, reject and close; month open-season; item adopt, activate and close; commitment commit, cancel, ship and receipt posting; decision approve and reject; overlay activate; and reforecast-cycle close."

    Design: Corner/state_machines/submit_and_approve_are_not_idempotent
    """
    scenario = setup_plan_scenario(
        month_specs=SINGLE_MONTH, size_curve=TWO_CELL_CURVE, submit=True
    )
    plan_id = scenario["plan_id"]
    m1_id = scenario["m1"]["id"]

    approved = validate_success(
        api.approve_category_plan(
            plan_id, {"approval_note": "first approve"}, DIRECTOR_HEADERS
        )
    )
    assert approved["status"] == "APPROVED", (
        f"The first approve must land APPROVED, got {approved['status']}"
    )
    assert approved["receipt_budget_cents"] == 60000000, (
        "The approval pins the seasonal receipt budget, expected 60000000, got "
        f"{approved['receipt_budget_cents']}"
    )
    assert approved["version"] == 4, (
        "One approval raises the version by 2 on top of create and submit, expected 4, "
        f"got {approved['version']}"
    )

    # A second director replays the approval: the acting operator differs from the
    # recorded submitter, so segregation of duties passes and the state decides.
    validate_error(
        api.approve_category_plan(
            plan_id, {"approval_note": "second approve"},
            make_director_headers(SECOND_DIRECTOR_USER_ID),
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )

    replayed = get_plan(plan_id)
    assert replayed["approved_by_user_id"] == DIRECTOR_USER_ID, (
        "The rejected replay must not restamp the approver, expected "
        f"{DIRECTOR_USER_ID}, got {replayed['approved_by_user_id']}"
    )
    assert replayed["receipt_budget_cents"] == 60000000, (
        f"The budget must not be recomputed, got {replayed['receipt_budget_cents']}"
    )
    assert replayed["version"] == 4, (
        f"There must be no third version increment, got {replayed['version']}"
    )

    month = get_month(m1_id)
    assert month["otb_planned_cents"] == 18200000, (
        "The rejected replay must not re-run the cascade over the month, expected "
        f"otb_planned_cents 18200000, got {month['otb_planned_cents']}"
    )
    assert month["version"] == 2, (
        f"The month must sit at version 2 after exactly one locking, got {month['version']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# A month added after approval never rides the approve cascade
# ─────────────────────────────────────────────────────────────────────────────

def test_open_season_refused_on_a_month_added_after_approval(api):
    """PRD §3.3: "Months may be added while the plan sits at any governance status; a month added after an approval starts in `DRAFT` and remains `DRAFT` until a subsequent approval locks it."

    PRD §3.7: "A locked month starts selling when a `MerchandisePlanner` opens it for the season, advancing it `LOCKED_PLAN → IN_SEASON`."

    PRD §3.7: "The month's `active_basis` remains `PLANNED_BASIS` until the first week of actuals lands against it."

    PRD §3.3: "Month listings can be narrowed by `category_plan_id` or by `status`."

    Design: Corner/state_machines/open_season_on_month_added_after_approval_rejected
    """
    scenario = setup_plan_scenario(
        month_specs=SINGLE_MONTH, size_curve=TWO_CELL_CURVE, approve=True
    )
    plan_id = scenario["plan_id"]
    m1_id = scenario["m1"]["id"]

    m2 = create_plan_month(plan_id, **dict(CANONICAL["month_2"]))
    assert m2["status"] == "DRAFT", (
        f"A month added after approval starts in DRAFT, got {m2['status']}"
    )
    assert m2["otb_planned_cents"] == 0, (
        "The late month never rode the approve cascade, so no open-to-buy was computed, "
        f"got {m2['otb_planned_cents']}"
    )
    assert get_plan(plan_id)["status"] == "APPROVED", (
        "The parent plan is APPROVED, so the cross-entity approval guard passes and only "
        "the month's own state can refuse"
    )

    validate_error(
        api.open_season(m2["id"], {}, PLANNER_HEADERS),
        ApiErrorId.ERR_INVALID_STATE,
    )

    opened = validate_success(api.open_season(m1_id, {}, PLANNER_HEADERS))
    assert opened["status"] == "IN_SEASON", (
        f"The LOCKED_PLAN month must open for the season, got {opened['status']}"
    )
    assert opened["active_basis"] == "PLANNED_BASIS", (
        "Opening alone does not switch the basis, got "
        f"{opened['active_basis']}"
    )

    validate_error(
        api.open_season(m1_id, {}, PLANNER_HEADERS),
        ApiErrorId.ERR_INVALID_STATE,
    )

    rows, meta = validate_paginated(
        api.list_plan_months(
            PLANNER_HEADERS, params={"category_plan_id": plan_id, "status": "DRAFT"}
        )
    )
    assert meta["total_count"] == 1, (
        f"Exactly one month must still be filterable as DRAFT, got {meta['total_count']}"
    )
    assert rows[0]["id"] == m2["id"], (
        "The stuck month is the one added after approval, got a different row"
    )


# ─────────────────────────────────────────────────────────────────────────────
# The commitment's two dimensions couple only where the PRD says they do
# ─────────────────────────────────────────────────────────────────────────────

def test_ship_and_receipts_refused_until_the_financial_dimension_commits(api):
    """PRD §3.6: "A `VendorRep` whose `X-User-ID` equals the commitment's `vendor_id` marks an order shipped, advancing `AWAITING_SHIP → SHIPPED`; this requires the commitment's `commit_status` to be `COMMITTED`, and beyond that guard the financial dimension is neither read nor written."

    PRD §3.6: "A posting is accepted while `fulfillment_status` is `SHIPPED` or `PARTIALLY_RECEIVED`."

    PRD §3.6: "Committing a proposal advances `PROPOSED → COMMITTED` on the financial dimension and leaves `fulfillment_status` untouched at `AWAITING_SHIP`."

    PRD §2.8: "9. The target row currently sits in a state from which the requested transition is declared — `ERR_INVALID_STATE` (409), on every action endpoint: plan submit, approve, reject and close; month open-season; item adopt, activate and close; commitment commit, cancel, ship and receipt posting; decision approve and reject; overlay activate; and reforecast-cycle close."

    Design: Corner/state_machines/ship_before_commit_rejected_on_independent_dimension
    """
    scenario = setup_plan_scenario(
        month_specs=SINGLE_MONTH, size_curve=TWO_CELL_CURVE, approve=True
    )
    m1_id = scenario["m1"]["id"]
    vendor_id = scenario["vendor"]["id"]
    item = propose_item(
        scenario["option_plan"]["id"], vendor_id, headers=BUYER_HEADERS,
        sku_code="DR-1001", color_code="BLK", unit_cost_cents=2600,
        retail_price_cents=7900,
    )
    commitment = propose_commitment(
        m1_id, item["id"], vendor_id, units=400, unit_cost_cents=2600,
        **LATE_SHIP_WINDOW
    )
    assert commitment["commit_status"] == "PROPOSED", (
        f"A new commitment starts PROPOSED, got {commitment['commit_status']}"
    )
    assert commitment["fulfillment_status"] == "AWAITING_SHIP", (
        "A new commitment starts AWAITING_SHIP on the independent fulfillment "
        f"dimension, got {commitment['fulfillment_status']}"
    )

    vendor_headers = make_vendor_rep_headers(vendor_id)

    # The caller IS the commitment's vendor, so ownership passes and only the
    # cross-dimension precondition can refuse.
    validate_error(
        api.ship_receipt_commitment(commitment["id"], {}, vendor_headers),
        ApiErrorId.ERR_INVALID_STATE,
    )
    # A receipt posting has no edge out of AWAITING_SHIP at all.
    validate_error(
        api.post_receipt(commitment["id"], {"received_units_delta": 100}, vendor_headers),
        ApiErrorId.ERR_INVALID_STATE,
    )

    untouched = get_commitment(commitment["id"])
    assert untouched["received_units"] == 0, (
        f"The refused posting must not receive units, got {untouched['received_units']}"
    )
    assert untouched["fulfillment_status"] == "AWAITING_SHIP", (
        f"The fulfillment dimension must not move, got {untouched['fulfillment_status']}"
    )
    assert untouched["open_cost_cents"] == 1040000, (
        f"400 units at 2600 cents remain fully open, got {untouched['open_cost_cents']}"
    )
    assert get_month(m1_id)["otb_committed_cents"] == 0, (
        "A PROPOSED commitment has not entered the month's committed figure, got "
        f"{get_month(m1_id)['otb_committed_cents']}"
    )

    committed = validate_success(
        api.commit_receipt_commitment(commitment["id"], {}, BUYER_HEADERS)
    )
    assert committed["commit_status"] == "COMMITTED", (
        f"The commit must advance the financial dimension, got {committed['commit_status']}"
    )
    assert committed["fulfillment_status"] == "AWAITING_SHIP", (
        "The commit deliberately leaves the fulfillment dimension alone, got "
        f"{committed['fulfillment_status']}"
    )

    shipped = validate_success(
        api.ship_receipt_commitment(commitment["id"], {}, vendor_headers)
    )
    assert shipped["fulfillment_status"] == "SHIPPED", (
        "The identical ship call must now succeed, got "
        f"{shipped['fulfillment_status']}"
    )
    assert shipped["commit_status"] == "COMMITTED", (
        "Shipping neither reads nor writes the financial dimension, got "
        f"{shipped['commit_status']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# The item close edge and its financial precondition
# ─────────────────────────────────────────────────────────────────────────────

def test_item_close_blocked_by_an_open_commitment_then_released(api):
    """PRD §3.9: "Closing also requires that the item has no financial loose ends: if any receipt commitment of the item still has a `commit_status` of `PROPOSED` or `COMMITTED`, the close is refused."

    PRD §3.6: "A commitment that is still `PROPOSED` is **withdrawn**: it advances `PROPOSED → WITHDRAWN`, its `fulfillment_status` moves to `VOID`, its `cancelled_units` is set equal to its `units` and its `open_cost_cents` to 0."

    PRD §3.6: "Because a proposal had never entered the month's committed figure, withdrawal touches no month and no plan field whatsoever — only the commitment's own version advances."

    PRD §3.9: "On success `status` becomes `CLOSED` and the cell's slot counters move as the conserved pair they are — `option_slots_assigned` falls by 1 and `option_slots_open` rises by 1, with `option_slots_total` untouched — and the item's and the cell's versions each advance by 1."

    Design: Corner/state_machines/item_close_blocked_by_open_commitment_then_released
    """
    scenario = setup_plan_scenario(
        month_specs=SINGLE_MONTH, size_curve=TWO_CELL_CURVE, approve=True
    )
    m1_id = scenario["m1"]["id"]
    option_plan_id = scenario["option_plan"]["id"]
    vendor_id = scenario["vendor"]["id"]

    item = propose_item(
        option_plan_id, vendor_id, headers=BUYER_HEADERS, sku_code="DR-1001",
        color_code="BLK", unit_cost_cents=2600, retail_price_cents=7900,
    )
    adopted = adopt_item(item["id"])
    assert adopted["status"] == "ADOPTED", (
        f"Adoption must land the item in ADOPTED, got {adopted['status']}"
    )
    slotted = get_option_plan(option_plan_id)
    assert slotted["option_slots_assigned"] == 1, (
        f"The adoption consumes one slot, got {slotted['option_slots_assigned']}"
    )
    assert slotted["option_slots_open"] == 13, (
        f"Thirteen of fourteen slots remain open, got {slotted['option_slots_open']}"
    )

    commitment = propose_commitment(
        m1_id, item["id"], vendor_id, units=400, unit_cost_cents=2600,
        **LATE_SHIP_WINDOW
    )
    # The create itself advanced the month's version, so the baseline for "the
    # withdrawal touches no month" is read after the create.
    m1_v = month_version(m1_id)

    # ADOPTED is one of the four states the close accepts, so the refusal can only be
    # the financial precondition. The PRD states that this close is refused but does
    # not name a code for it, so only the refusal itself is asserted here.
    blocked = api.close_assortment_item(item["id"], {}, BUYER_HEADERS)
    assert blocked.status_code >= 400, (
        "Closing an item that still carries a PROPOSED commitment must be refused, got "
        f"HTTP {blocked.status_code}"
    )
    assert blocked.json().get("response_type") == "error", (
        "The refused close must come back as an error envelope, got "
        f"{blocked.json().get('response_type')}"
    )

    still_adopted = get_item(item["id"])
    assert still_adopted["status"] == "ADOPTED", (
        f"The refused close must leave the item ADOPTED, got {still_adopted['status']}"
    )
    assert get_option_plan(option_plan_id)["option_slots_open"] == 13, (
        "No partial slot release may happen on a refused close, got "
        f"{get_option_plan(option_plan_id)['option_slots_open']}"
    )

    withdrawn = validate_success(
        api.cancel_receipt_commitment(
            commitment["id"], {"cancel_reason": "buy pulled before commitment"},
            BUYER_HEADERS,
        )
    )
    assert withdrawn["commit_status"] == "WITHDRAWN", (
        f"A PROPOSED commitment is withdrawn, got {withdrawn['commit_status']}"
    )
    assert withdrawn["fulfillment_status"] == "VOID", (
        f"Withdrawal voids the fulfillment dimension, got {withdrawn['fulfillment_status']}"
    )
    assert withdrawn["cancelled_units"] == 400, (
        f"cancelled_units must equal the full order of 400, got {withdrawn['cancelled_units']}"
    )
    assert withdrawn["open_cost_cents"] == 0, (
        f"Withdrawal zeroes the open cost, got {withdrawn['open_cost_cents']}"
    )

    month = get_month(m1_id)
    assert month["otb_committed_cents"] == 0, (
        "A proposal never entered the committed bucket, got "
        f"{month['otb_committed_cents']}"
    )
    assert month["otb_open_cents"] == 18200000, (
        f"The month's open budget is untouched, got {month['otb_open_cents']}"
    )
    assert month["version"] == m1_v, (
        f"The withdrawal must not touch the month row, expected version {m1_v}, got "
        f"{month['version']}"
    )

    closed = validate_success(api.close_assortment_item(item["id"], {}, BUYER_HEADERS))
    assert closed["status"] == "CLOSED", (
        f"With no loose ends the same close must succeed, got {closed['status']}"
    )
    released = get_option_plan(option_plan_id)
    assert released["option_slots_assigned"] == 0, (
        f"The close returns the slot, got {released['option_slots_assigned']}"
    )
    assert released["option_slots_open"] == 14, (
        f"All fourteen slots are open again, got {released['option_slots_open']}"
    )
    assert released["option_slots_total"] == 14, (
        f"option_slots_total is untouched, got {released['option_slots_total']}"
    )

    _, meta = validate_paginated(
        api.list_receipt_commitments(
            BUYER_HEADERS,
            params={"assortment_item_id": item["id"], "commit_status": "PROPOSED"},
        )
    )
    assert meta["total_count"] == 0, (
        "The guard's own condition — no PROPOSED commitment for the item — must now "
        f"read empty, got {meta['total_count']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# An overlay's expiry is driven by the clock and lands on the item
# ─────────────────────────────────────────────────────────────────────────────

def test_overlay_expiry_on_clock_advance_recomputes_the_item_forecast(api):
    """PRD §3.5: "Overlays are created in `DRAFT` and can be listed narrowed by `category_plan_id`, `store_cluster_id`, `overlay_type` or `status`."

    PRD §3.5: "An overlay applies when its `category_plan_id` matches the plan of the item's cell, its `store_cluster_id` matches the cluster of the item's cell, its `status` is `ACTIVE`, and the logical clock falls inside its closed window — at or after `effective_start` and at or before `effective_end`."

    PRD §3.5: "Activation immediately re-resolves the affected assortment: every item whose `status` is `ADOPTED` or `IN_SEASON`, and whose cell belongs to both the overlay's plan and the overlay's cluster, has its `effective_overlay_multiplier_bps` re-resolved and its `sell_through_bps` re-forecast, with each affected item's version advancing by 1."

    PRD §2.6: "Repositioning the clock has one governed side effect: every `ACTIVE` localization overlay whose `effective_end` now lies strictly in the past transitions to `EXPIRED`, and the assortment items that were carrying it have their localization multiplier and sell-through forecast recomputed without it."

    PRD §2.6: "`expired_overlay_count` reports how many overlays that request expired."

    Design: Corner/state_machines/overlay_expiry_on_clock_advance_recomputes_item_forecast
    """
    scenario = setup_plan_scenario(
        month_specs=SINGLE_MONTH, size_curve=TWO_CELL_CURVE, approve=True,
        open_season_month_indexes=(1,),
    )
    item = propose_item(
        scenario["option_plan"]["id"], scenario["vendor"]["id"], headers=BUYER_HEADERS,
        sku_code="DR-2001", color_code="IVY", lifecycle_stage="NEW",
        unit_cost_cents=2600, retail_price_cents=7900,
    )

    adopted = adopt_item(item["id"])
    assert adopted["effective_overlay_multiplier_bps"] == 10000, (
        "With no ACTIVE overlay the multiplier is the neutral 10000, got "
        f"{adopted['effective_overlay_multiplier_bps']}"
    )
    assert adopted["sell_through_bps"] == 6325, (
        "The un-overlaid new-item forecast for a BETTER cell on a 11500 index cluster "
        f"is 6325, got {adopted['sell_through_bps']}"
    )
    assert adopted["sell_through_basis"] == "NEW_ITEM_BASIS", (
        f"A NEW item is forecast on the new-item basis, got {adopted['sell_through_basis']}"
    )
    activated = activate_item(item["id"])
    version_before_overlay = activated["version"]

    overlay = create_overlay(
        scenario["plan_id"], scenario["store_cluster"]["id"], overlay_type="CLIMATE",
        effective_start="2026-08-05T00:00:00Z", effective_end="2026-08-31T00:00:00Z",
        unit_multiplier_bps=11000,
    )
    assert overlay["status"] == "DRAFT", (
        f"A planner authors an overlay in DRAFT, got {overlay['status']}"
    )

    # The overlay only applies while the clock sits inside its closed window, so the
    # clock is moved into the window before the director switches the overlay on.
    set_clock("2026-08-10T00:00:00Z")

    active = validate_success(
        api.activate_localization_overlay(overlay["id"], {}, DIRECTOR_HEADERS)
    )
    assert active["status"] == "ACTIVE", (
        f"Only a director may switch an overlay on, got {active['status']}"
    )

    overlaid = get_item(item["id"])
    assert overlaid["effective_overlay_multiplier_bps"] == 11000, (
        "The single CLIMATE overlay carries the multiplier to 11000, got "
        f"{overlaid['effective_overlay_multiplier_bps']}"
    )
    assert overlaid["sell_through_bps"] == 6958, (
        "5500 * 11500 * 11000 / 100000000 is 6957.5, which rounds half up away from "
        f"zero to 6958, got {overlaid['sell_through_bps']}"
    )
    assert overlaid["version"] == version_before_overlay + 1, (
        "Activating the overlay bumps the item exactly once even though the request "
        f"named no item, expected {version_before_overlay + 1}, got {overlaid['version']}"
    )

    # Expiry is strictly after effective_end, so the boundary reading changes nothing.
    at_end = set_clock("2026-08-31T00:00:00Z")
    assert at_end["expired_overlay_count"] == 0, (
        "A clock reading exactly at effective_end expires nothing, got "
        f"{at_end['expired_overlay_count']}"
    )
    assert get_overlay(overlay["id"])["status"] == "ACTIVE", (
        "The overlay must still be ACTIVE at exactly effective_end, got "
        f"{get_overlay(overlay['id'])['status']}"
    )

    past_end = set_clock("2026-09-01T00:00:00Z")
    assert past_end["expired_overlay_count"] == 1, (
        "One overlay must expire on the advance past effective_end, got "
        f"{past_end['expired_overlay_count']}"
    )
    assert get_overlay(overlay["id"])["status"] == "EXPIRED", (
        f"The overlay must now be EXPIRED, got {get_overlay(overlay['id'])['status']}"
    )

    unoverlaid = get_item(item["id"])
    assert unoverlaid["effective_overlay_multiplier_bps"] == 10000, (
        "Expiry restores the neutral multiplier, got "
        f"{unoverlaid['effective_overlay_multiplier_bps']}"
    )
    assert unoverlaid["sell_through_bps"] == 6325, (
        "Expiry restores exactly the pre-activation forecast, got "
        f"{unoverlaid['sell_through_bps']}"
    )
    assert unoverlaid["version"] == overlaid["version"] + 1, (
        "The values returned to their originals but the row's history did not rewind, "
        f"expected version {overlaid['version'] + 1}, got {unoverlaid['version']}"
    )
