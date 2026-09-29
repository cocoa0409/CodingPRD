"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because each test starts against an empty database. Setup calls use
the lenient validator so a broken precondition surfaces as "Setup failed".
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CANONICAL,
    CANONICAL_SIZE_CURVE,
    CLOCK_STARTUP_UTC,
    DIRECTOR_USER_ID,
    PLANNER_USER_ID,
)
from .factories import (
    actuals_post_payload,
    assortment_item_payload,
    category_payload,
    category_plan_payload,
    chase_cancel_decision_payload,
    department_payload,
    localization_overlay_payload,
    option_plan_payload,
    plan_month_payload,
    receipt_commitment_payload,
    reforecast_payload,
    size_curve_payload,
    store_cluster_payload,
    vendor_authorization_payload,
    vendor_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    BUYER_HEADERS,
    DIRECTOR_HEADERS,
    PLANNER_HEADERS,
    make_director_headers,
    make_planner_headers,
    make_vendor_rep_headers,
)


# ─── Logical clock ────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Reposition the server's logical clock."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN_HEADERS)
    )


# ─── Reference spine ──────────────────────────────────

def create_department(**overrides) -> dict:
    return get_success_data(
        api_client.create_department(department_payload(**overrides), ADMIN_HEADERS)
    )


def create_category(department_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_category(
            category_payload(department_id, **overrides), ADMIN_HEADERS
        )
    )


def create_store_cluster(**overrides) -> dict:
    return get_success_data(
        api_client.create_store_cluster(store_cluster_payload(**overrides), ADMIN_HEADERS)
    )


def create_vendor(authorized: bool = True, **overrides) -> dict:
    """Create a vendor (PENDING by design) and optionally move it to AUTHORIZED."""
    vendor = get_success_data(
        api_client.create_vendor(vendor_payload(**overrides), ADMIN_HEADERS)
    )
    if authorized:
        vendor = set_vendor_status(vendor["id"], "AUTHORIZED")
    return vendor


def set_vendor_status(vendor_id: str, status: str) -> dict:
    return get_success_data(
        api_client.set_vendor_status(vendor_id, {"status": status}, ADMIN_HEADERS)
    )


def create_vendor_authorization(vendor_id: str, category_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_vendor_authorization(
            vendor_authorization_payload(vendor_id, category_id, **overrides),
            ADMIN_HEADERS,
        )
    )


def setup_reference_spine(
    clock: str = CLOCK_STARTUP_UTC,
    department_overrides: dict = None,
    category_overrides: dict = None,
    cluster_overrides: dict = None,
    vendor_overrides: dict = None,
    vendor_authorized: bool = True,
    authorize_category: bool = True,
    max_open_units: int = None,
) -> dict:
    """Department -> Category -> StoreCluster -> Vendor (+ category authorization).

    Returns {"department", "category", "store_cluster", "vendor", "authorization"}.
    """
    if clock:
        set_clock(clock)
    department = create_department(**(department_overrides or {}))
    category = create_category(department["id"], **(category_overrides or {}))
    store_cluster = create_store_cluster(**(cluster_overrides or {}))
    vendor = create_vendor(authorized=vendor_authorized, **(vendor_overrides or {}))
    authorization = None
    if authorize_category:
        extra = {} if max_open_units is None else {"max_open_units": max_open_units}
        authorization = create_vendor_authorization(vendor["id"], category["id"], **extra)
    return {
        "department": department,
        "category": category,
        "store_cluster": store_cluster,
        "vendor": vendor,
        "authorization": authorization,
    }


# ─── Plan authoring ───────────────────────────────────

def create_category_plan(category_id: str, planner_user_id: str = PLANNER_USER_ID,
                         **overrides) -> dict:
    return get_success_data(
        api_client.create_category_plan(
            category_plan_payload(category_id, **overrides),
            make_planner_headers(planner_user_id),
        )
    )


def create_plan_month(category_plan_id: str, planner_user_id: str = PLANNER_USER_ID,
                      **overrides) -> dict:
    return get_success_data(
        api_client.create_plan_month(
            plan_month_payload(category_plan_id, **overrides),
            make_planner_headers(planner_user_id),
        )
    )


def create_option_plan(category_plan_id: str, store_cluster_id: str,
                       planner_user_id: str = PLANNER_USER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.create_option_plan(
            option_plan_payload(category_plan_id, store_cluster_id, **overrides),
            make_planner_headers(planner_user_id),
        )
    )


def replace_size_curve(option_plan_id: str, cells=None,
                       planner_user_id: str = PLANNER_USER_ID) -> dict:
    return get_success_data(
        api_client.replace_size_curve(
            option_plan_id, size_curve_payload(cells), make_planner_headers(planner_user_id)
        )
    )


def submit_plan(plan_id: str, submission_note: str = "seasonal plan v1",
                planner_user_id: str = PLANNER_USER_ID) -> dict:
    payload = {} if submission_note is None else {"submission_note": submission_note}
    return get_success_data(
        api_client.submit_category_plan(
            plan_id, payload, make_planner_headers(planner_user_id)
        )
    )


def approve_plan(plan_id: str, approval_note: str = "approved",
                 director_user_id: str = DIRECTOR_USER_ID) -> dict:
    payload = {} if approval_note is None else {"approval_note": approval_note}
    return get_success_data(
        api_client.approve_category_plan(
            plan_id, payload, make_director_headers(director_user_id)
        )
    )


def reject_plan(plan_id: str, rejection_reason: str = "rework the months",
                director_user_id: str = DIRECTOR_USER_ID) -> dict:
    return get_success_data(
        api_client.reject_category_plan(
            plan_id, {"rejection_reason": rejection_reason},
            make_director_headers(director_user_id),
        )
    )


def close_plan(plan_id: str, director_user_id: str = DIRECTOR_USER_ID) -> dict:
    return get_success_data(
        api_client.close_category_plan(plan_id, {}, make_director_headers(director_user_id))
    )


def open_season(month_id: str, planner_user_id: str = PLANNER_USER_ID) -> dict:
    return get_success_data(
        api_client.open_season(month_id, {}, make_planner_headers(planner_user_id))
    )


# ─── Reads ────────────────────────────────────────────

def get_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_category_plan(plan_id, PLANNER_HEADERS))


def get_month(month_id: str) -> dict:
    return get_success_data(api_client.get_plan_month(month_id, PLANNER_HEADERS))


def get_option_plan(option_plan_id: str) -> dict:
    return get_success_data(api_client.get_option_plan(option_plan_id, PLANNER_HEADERS))


def get_item(item_id: str) -> dict:
    return get_success_data(api_client.get_assortment_item(item_id, PLANNER_HEADERS))


def get_commitment(commitment_id: str) -> dict:
    return get_success_data(
        api_client.get_receipt_commitment(commitment_id, PLANNER_HEADERS)
    )


def get_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_reforecast_cycle(cycle_id, PLANNER_HEADERS))


def get_decision(decision_id: str) -> dict:
    return get_success_data(
        api_client.get_chase_cancel_decision(decision_id, PLANNER_HEADERS)
    )


def get_overlay(overlay_id: str) -> dict:
    return get_success_data(
        api_client.get_localization_overlay(overlay_id, PLANNER_HEADERS)
    )


def get_size_curve_cells(option_plan_id: str) -> list:
    body = api_client.list_size_curve_cells(option_plan_id, PLANNER_HEADERS,
                                            params={"limit": 100})
    return get_success_data(body)


def month_version(month_id: str) -> int:
    return get_month(month_id)["version"]


def plan_version(plan_id: str) -> int:
    return get_plan(plan_id)["version"]


# ─── Composite planning scenarios ─────────────────────

def setup_plan_scenario(
    clock: str = CLOCK_STARTUP_UTC,
    month_specs: list = None,
    option_plan_specs: list = None,
    size_curve=None,
    plan_overrides: dict = None,
    spine: dict = None,
    submit: bool = False,
    approve: bool = False,
    open_season_month_indexes: tuple = (),
    planner_user_id: str = PLANNER_USER_ID,
    director_user_id: str = DIRECTOR_USER_ID,
    **spine_kwargs,
) -> dict:
    """Build a seasonal plan and carry it as far through governance as asked.

    month_specs: list of PlanMonth input dicts (defaults to the canonical M1+M2).
    option_plan_specs: list of OptionPlan input dicts (defaults to one BETTER cell).
    size_curve: cells submitted for every option plan created (None -> canonical
    five-cell curve; pass [] to leave the cell without a curve).

    Returns a dict with the spine, the plan, {"months": {month_index: row}},
    {"option_plans": [rows]} and convenience aliases m1/m2/option_plan.
    """
    if spine is None:
        spine = setup_reference_spine(clock=clock, **spine_kwargs)
    elif clock:
        set_clock(clock)

    plan = create_category_plan(
        spine["category"]["id"], planner_user_id=planner_user_id,
        **(plan_overrides or {})
    )

    if month_specs is None:
        month_specs = [dict(CANONICAL["month_1"]), dict(CANONICAL["month_2"])]
    months = {}
    for spec in month_specs:
        row = create_plan_month(plan["id"], planner_user_id=planner_user_id, **spec)
        months[row["month_index"]] = row

    if option_plan_specs is None:
        option_plan_specs = [dict(CANONICAL["option_plan"])]
    option_plans = []
    for spec in option_plan_specs:
        cluster_id = spec.pop("store_cluster_id", spine["store_cluster"]["id"])
        cell = create_option_plan(
            plan["id"], cluster_id, planner_user_id=planner_user_id, **spec
        )
        cells = CANONICAL_SIZE_CURVE if size_curve is None else size_curve
        if cells:
            replace_size_curve(cell["id"], cells, planner_user_id=planner_user_id)
        option_plans.append(get_option_plan(cell["id"]))

    if submit or approve:
        submit_plan(plan["id"], planner_user_id=planner_user_id)
    if approve:
        approve_plan(plan["id"], director_user_id=director_user_id)

    for month_index in open_season_month_indexes:
        open_season(months[month_index]["id"], planner_user_id=planner_user_id)

    scenario = {
        **spine,
        "plan": get_plan(plan["id"]),
        "months": {idx: get_month(row["id"]) for idx, row in months.items()},
        "option_plans": [get_option_plan(cell["id"]) for cell in option_plans],
    }
    scenario["plan_id"] = scenario["plan"]["id"]
    scenario["option_plan"] = scenario["option_plans"][0] if option_plans else None
    for idx, row in scenario["months"].items():
        scenario[f"m{idx}"] = row
    return scenario


def setup_canonical_approved_plan(**kwargs) -> dict:
    """The canonical spine plus an APPROVED SPRING 2027 plan: months M1/M2
    LOCKED_PLAN, one SLOTTED BETTER option plan on Cold-A."""
    kwargs.setdefault("approve", True)
    return setup_plan_scenario(**kwargs)


def setup_single_month_approved_plan(**kwargs) -> dict:
    """An APPROVED plan carrying only the canonical month M1."""
    kwargs.setdefault("month_specs", [dict(CANONICAL["month_1"])])
    kwargs.setdefault("approve", True)
    return setup_plan_scenario(**kwargs)


def setup_in_season_plan(**kwargs) -> dict:
    """An APPROVED plan whose month M1 has been opened for the season."""
    kwargs.setdefault("approve", True)
    kwargs.setdefault("open_season_month_indexes", (1,))
    return setup_plan_scenario(**kwargs)


def setup_draft_plan(**kwargs) -> dict:
    """A DRAFT plan with its months, one OPEN option plan and a balanced curve."""
    kwargs.setdefault("approve", False)
    kwargs.setdefault("submit", False)
    return setup_plan_scenario(**kwargs)


def setup_submitted_plan(**kwargs) -> dict:
    """A SUBMITTED plan ready for a director to adjudicate."""
    kwargs.setdefault("submit", True)
    kwargs.setdefault("approve", False)
    return setup_plan_scenario(**kwargs)


# ─── Assortment items ─────────────────────────────────

def propose_item(option_plan_id: str, vendor_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_assortment_item(
            assortment_item_payload(option_plan_id, vendor_id, **overrides),
            headers or PLANNER_HEADERS,
        )
    )


def adopt_item(item_id: str) -> dict:
    return get_success_data(api_client.adopt_assortment_item(item_id, {}, BUYER_HEADERS))


def activate_item(item_id: str) -> dict:
    return get_success_data(
        api_client.activate_assortment_item(item_id, {}, BUYER_HEADERS)
    )


def close_item(item_id: str) -> dict:
    return get_success_data(api_client.close_assortment_item(item_id, {}, BUYER_HEADERS))


def setup_adopted_item(scenario: dict, **overrides) -> dict:
    """Propose an item on the scenario's first option plan and adopt it."""
    item = propose_item(
        scenario["option_plan"]["id"], scenario["vendor"]["id"], **overrides
    )
    return adopt_item(item["id"])


def setup_in_season_item(scenario: dict, month_index: int = 1, **overrides) -> dict:
    """Adopt an item and activate it, opening the given month for the season first
    when the plan has no IN_SEASON month yet."""
    month = scenario["months"][month_index]
    if get_month(month["id"])["status"] == "LOCKED_PLAN":
        open_season(month["id"])
    item = setup_adopted_item(scenario, **overrides)
    return activate_item(item["id"])


# ─── Receipt commitments ──────────────────────────────

def propose_commitment(
    plan_month_id: str,
    assortment_item_id: str,
    vendor_id: str,
    expected_plan_month_version: int = None,
    headers=None,
    **overrides,
) -> dict:
    """Propose a receipt commitment, reading the month's current version when the
    caller does not pin one."""
    if expected_plan_month_version is None:
        expected_plan_month_version = month_version(plan_month_id)
    payload = receipt_commitment_payload(
        plan_month_id, assortment_item_id, vendor_id,
        expected_plan_month_version, **overrides
    )
    return get_success_data(
        api_client.create_receipt_commitment(payload, headers or BUYER_HEADERS)
    )


def commit_commitment(commitment_id: str) -> dict:
    return get_success_data(
        api_client.commit_receipt_commitment(commitment_id, {}, BUYER_HEADERS)
    )


def cancel_commitment(commitment_id: str, cancel_reason: str = None) -> dict:
    payload = {} if cancel_reason is None else {"cancel_reason": cancel_reason}
    return get_success_data(
        api_client.cancel_receipt_commitment(commitment_id, payload, BUYER_HEADERS)
    )


def ship_commitment(commitment_id: str, vendor_id: str) -> dict:
    return get_success_data(
        api_client.ship_receipt_commitment(
            commitment_id, {}, make_vendor_rep_headers(vendor_id)
        )
    )


def post_receipt(commitment_id: str, vendor_id: str, received_units_delta: int) -> dict:
    return get_success_data(
        api_client.post_receipt(
            commitment_id, {"received_units_delta": received_units_delta},
            make_vendor_rep_headers(vendor_id),
        )
    )


def setup_committed_commitment(
    plan_month_id: str, assortment_item_id: str, vendor_id: str, **overrides
) -> dict:
    """Propose a commitment and drive it to COMMITTED so the month's committed and
    open figures move."""
    commitment = propose_commitment(
        plan_month_id, assortment_item_id, vendor_id, **overrides
    )
    return commit_commitment(commitment["id"])


def setup_month_with_committed_spend(
    scenario: dict, units: int, unit_cost_cents: int, month_index: int = 1, **overrides
) -> dict:
    """Drive a known amount of COMMITTED cost into one month of the scenario.

    Returns {"item", "commitment", "month", "plan"} with the refreshed rows.
    """
    month = scenario["months"][month_index]
    item = propose_item(
        scenario["option_plan"]["id"], scenario["vendor"]["id"],
        unit_cost_cents=unit_cost_cents,
        **{k: v for k, v in overrides.items() if k in ("lifecycle_stage", "sku_code",
                                                       "prior_season_sell_through_bps")},
    )
    commitment_overrides = {
        k: v for k, v in overrides.items()
        if k in ("ship_window_start", "ship_window_end")
    }
    commitment = setup_committed_commitment(
        month["id"], item["id"], scenario["vendor"]["id"],
        units=units, unit_cost_cents=unit_cost_cents, **commitment_overrides
    )
    return {
        "item": get_item(item["id"]),
        "commitment": commitment,
        "month": get_month(month["id"]),
        "plan": get_plan(scenario["plan_id"]),
    }


# ─── Weekly actuals ───────────────────────────────────

def post_actuals(plan_month_id: str, week_index: int = 1, **overrides) -> dict:
    return get_success_data(
        api_client.create_actuals_post(
            actuals_post_payload(plan_month_id, week_index, **overrides), ADMIN_HEADERS
        )
    )


# ─── Reforecast governance ────────────────────────────

def open_reforecast_cycle(
    plan_id: str,
    expected_category_plan_version: int = None,
    reason_note: str = "in-season correction requested",
    planner_user_id: str = PLANNER_USER_ID,
) -> dict:
    if expected_category_plan_version is None:
        expected_category_plan_version = plan_version(plan_id)
    return get_success_data(
        api_client.open_reforecast_cycle(
            plan_id,
            reforecast_payload(expected_category_plan_version, reason_note=reason_note),
            make_planner_headers(planner_user_id),
        )
    )


def propose_decision(
    reforecast_cycle_id: str,
    assortment_item_id: str,
    action: str = "CHASE",
    requested_units: int = 500,
    rationale: str = "trading ahead of plan on this option",
    proposer_user_id: str = PLANNER_USER_ID,
) -> dict:
    return get_success_data(
        api_client.create_chase_cancel_decision(
            chase_cancel_decision_payload(
                reforecast_cycle_id, assortment_item_id, action=action,
                requested_units=requested_units, rationale=rationale,
            ),
            make_planner_headers(proposer_user_id),
        )
    )


def approve_decision(decision_id: str, decision_note: str = None,
                     director_user_id: str = DIRECTOR_USER_ID) -> dict:
    payload = {} if decision_note is None else {"decision_note": decision_note}
    return get_success_data(
        api_client.approve_chase_cancel_decision(
            decision_id, payload, make_director_headers(director_user_id)
        )
    )


def reject_decision(decision_id: str, decision_note: str = None,
                    director_user_id: str = DIRECTOR_USER_ID) -> dict:
    payload = {} if decision_note is None else {"decision_note": decision_note}
    return get_success_data(
        api_client.reject_chase_cancel_decision(
            decision_id, payload, make_director_headers(director_user_id)
        )
    )


def close_cycle(cycle_id: str, director_user_id: str = DIRECTOR_USER_ID) -> dict:
    return get_success_data(
        api_client.close_reforecast_cycle(cycle_id, {}, make_director_headers(director_user_id))
    )


def setup_open_reforecast_cycle(scenario: dict, month_index: int = 1,
                                item_overrides: dict = None) -> dict:
    """Carry a scenario to an OPEN director-requested cycle with one IN_SEASON item.

    Returns {"cycle", "item", "plan", "month"}.
    """
    item = setup_in_season_item(scenario, month_index=month_index,
                                **(item_overrides or {}))
    cycle = open_reforecast_cycle(scenario["plan_id"])
    return {
        "cycle": cycle,
        "item": get_item(item["id"]),
        "plan": get_plan(scenario["plan_id"]),
        "month": get_month(scenario["months"][month_index]["id"]),
    }


def complete_reforecast_round(scenario: dict) -> dict:
    """Open a cycle, close it with no decisions, resubmit and re-approve the plan.

    Used to walk the plan's reforecast_round up towards its cap.
    """
    cycle = open_reforecast_cycle(scenario["plan_id"])
    close_cycle(cycle["id"])
    submit_plan(scenario["plan_id"])
    approve_plan(scenario["plan_id"])
    return get_plan(scenario["plan_id"])


# ─── Localization overlays ────────────────────────────

def create_overlay(category_plan_id: str, store_cluster_id: str,
                   planner_user_id: str = PLANNER_USER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.create_localization_overlay(
            localization_overlay_payload(category_plan_id, store_cluster_id, **overrides),
            make_planner_headers(planner_user_id),
        )
    )


def activate_overlay(overlay_id: str, director_user_id: str = DIRECTOR_USER_ID) -> dict:
    return get_success_data(
        api_client.activate_localization_overlay(
            overlay_id, {}, make_director_headers(director_user_id)
        )
    )


def setup_active_overlay(scenario: dict, **overrides) -> dict:
    """Author an overlay on the scenario's cluster and activate it."""
    overlay = create_overlay(
        scenario["plan_id"], scenario["store_cluster"]["id"], **overrides
    )
    return activate_overlay(overlay["id"])
