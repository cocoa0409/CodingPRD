"""Cascade side effects (PRD 2.8, 2.9, 3.2, 3.5, 3.8, 3.9).

Every cascade completes inside the originating request and bumps `version` on
every row it touches.
"""
import calc
import store

LIVE_WORK_ORDER_STATUSES = {"PENDING_DISPATCH", "DISPATCHED", "ACCEPTED", "IN_PROGRESS"}
COMMITTED_WORK_ORDER_STATUSES = {"PENDING_DISPATCH", "DISPATCHED", "ACCEPTED",
                                 "IN_PROGRESS", "COMPLETED"}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def market_of(home):
    return store.get("markets", home["market_id"])


def home_slots(home_id):
    return [s for s in store.all_rows("showing_slots") if s["home_id"] == home_id]


def project_work_orders(project_id):
    return [w for w in store.all_rows("work_orders") if w["project_id"] == project_id]


def home_projects(home_id):
    return [p for p in store.all_rows("renovation_projects") if p["home_id"] == home_id]


def approved_case(home_id):
    for case in store.all_rows("underwriting_cases"):
        if case["home_id"] == home_id and case["status"] == "APPROVED":
            return case
    return None


def executed_lease(home_id):
    for lease in store.all_rows("leases"):
        if lease["home_id"] == home_id and lease["status"] == "EXECUTED":
            return lease
    return None


# ---------------------------------------------------------------------------
# Posture recomputation and its showing-window cascade
# ---------------------------------------------------------------------------


def recompute_posture(home):
    """Recompute the posture and drive the AVAILABLE <-> BLOCKED_BY_POSTURE cascade."""
    posture = calc.leasing_posture(home)
    for slot in home_slots(home["id"]):
        if posture == "FROZEN":
            if slot["status"] == "AVAILABLE":
                slot["status"] = "BLOCKED_BY_POSTURE"
                store.touch(slot)
        else:
            if slot["status"] == "BLOCKED_BY_POSTURE":
                slot["status"] = "AVAILABLE"
                store.touch(slot)
    return posture


# ---------------------------------------------------------------------------
# Home derived money
# ---------------------------------------------------------------------------


def recompute_property_tax(home):
    market = market_of(home)
    home["property_tax_annual_cents"] = calc.property_tax_annual(
        home["assessed_value_cents"], market["millage_bps"])


def refresh_hold_sell(home, case):
    """PRD 3.2: hold_sell_score_bps and disposition_flagged follow the case."""
    market = market_of(home)
    if case is None:
        return
    basis_yield = case.get("realized_yield_on_cost_bps")
    if basis_yield is None:
        basis_yield = case.get("underwritten_yield_on_cost_bps") or 0
    score = int(basis_yield) - int(market["disposition_yield_floor_bps"])
    home["hold_sell_score_bps"] = score
    home["disposition_flagged"] = score < 0
    store.touch(home)


# ---------------------------------------------------------------------------
# Underwritten / realized variants
# ---------------------------------------------------------------------------


def scope_lines_for(case):
    """Resolve planned_scope_lines into benchmark-priced lines."""
    lines = []
    for line in case["planned_scope_lines"]:
        template = store.get("scope_templates", line["scope_template_id"])
        lines.append({
            "benchmark_unit_cost_cents": template["benchmark_unit_cost_cents"],
            "quantity": line["quantity"],
        })
    return lines


def recompute_underwritten(case):
    home = store.get("homes", case["home_id"])
    market = market_of(home)
    lines = scope_lines_for(case)
    case["planned_renovation_budget_cents"] = calc.scope_benchmark_total(
        lines, market["cost_index_bps"])
    result = calc.yield_on_cost(
        market, home,
        case["purchase_price_cents"],
        case["acquisition_closing_costs_cents"],
        case["planned_renovation_budget_cents"],
        case["estimated_monthly_rent_cents"],
        case["turn_reserve_annual_cents"],
    )
    case["underwritten_all_in_basis_cents"] = result["all_in_basis_cents"]
    case["underwritten_effective_gross_income_cents"] = result["effective_gross_income_cents"]
    case["underwritten_noi_cents"] = result["net_operating_income_cents"]
    case["underwritten_yield_on_cost_bps"] = result["yield_on_cost_bps"]
    return result


def realized_renovation_cost(home_id):
    """Sum of actual_cost_cents over COMPLETED work orders inside the home's projects."""
    project_ids = {p["id"] for p in home_projects(home_id)}
    completed = [w for w in store.all_rows("work_orders")
                 if w["status"] == "COMPLETED" and w["project_id"] in project_ids]
    if not completed:
        return None
    return sum(int(w["actual_cost_cents"]) for w in completed)


def recompute_realized(home):
    """Re-run the realized variant on the home's APPROVED case, then hold/sell."""
    case = approved_case(home["id"])
    if case is None:
        return None
    market = market_of(home)
    renovation = realized_renovation_cost(home["id"])
    if renovation is None:
        case["realized_renovation_cost_cents"] = None
        case["realized_all_in_basis_cents"] = None
        case["realized_noi_cents"] = None
        case["realized_yield_on_cost_bps"] = None
    else:
        lease = executed_lease(home["id"])
        rent = lease["monthly_rent_cents"] if lease else case["estimated_monthly_rent_cents"]
        result = calc.yield_on_cost(
            market, home,
            case["purchase_price_cents"],
            case["acquisition_closing_costs_cents"],
            renovation,
            rent,
            case["turn_reserve_annual_cents"],
        )
        case["realized_renovation_cost_cents"] = renovation
        case["realized_all_in_basis_cents"] = result["all_in_basis_cents"]
        case["realized_noi_cents"] = result["net_operating_income_cents"]
        case["realized_yield_on_cost_bps"] = result["yield_on_cost_bps"]
    store.touch(case)
    refresh_hold_sell(home, case)
    return case


# ---------------------------------------------------------------------------
# Project ledger (conserved money identity)
# ---------------------------------------------------------------------------


def commit_project_cost(project, amount):
    project["committed_cost_cents"] = int(project["committed_cost_cents"]) + int(amount)
    project["budget_remaining_cents"] = (int(project["approved_budget_cents"])
                                         - int(project["committed_cost_cents"]))
    store.touch(project)


def release_project_cost(project, amount):
    commit_project_cost(project, -int(amount))


# ---------------------------------------------------------------------------
# The five-hop make-ready cascade (fires from completion and from void)
# ---------------------------------------------------------------------------


def maybe_make_ready(project):
    """Hops 1..5 of PRD 3.5, as one atomic unit, when the live queue is drained."""
    if project is None or project["status"] != "IN_PROGRESS":
        return False
    orders = project_work_orders(project["id"])
    if any(w["status"] in LIVE_WORK_ORDER_STATUSES for w in orders):
        return False
    completed = [w for w in orders if w["status"] == "COMPLETED"]
    if not completed:
        return False

    # Hop 1 — project reaches rent-ready.
    project["status"] = "RENT_READY"
    project["rent_ready_on"] = store.clock_date().isoformat()

    # Hop 2 — the turn-holdback settlement.
    home = store.get("homes", project["home_id"])
    market = market_of(home)
    gross = sum(int(w["actual_cost_cents"]) for w in completed)
    settlement = calc.turn_holdback(market, project, gross)
    project.update(settlement)
    store.touch(project)

    # Hop 3 — the home stabilises.
    if home["asset_status"] == "RENOVATING":
        home["asset_status"] = "STABILIZED"
        store.touch(home)

    # Hop 4 — posture recomputation releases blocked windows.
    recompute_posture(home)

    # Hop 5 — realized yield, hold/sell score and disposition flag.
    recompute_realized(home)
    return True


# ---------------------------------------------------------------------------
# Booking count invariant
# ---------------------------------------------------------------------------


def release_booked_slots_for_prospect(prospect_id):
    """VERIFIED -> REJECTED fall-back: booked windows return to the calendar."""
    for slot in store.all_rows("showing_slots"):
        if slot["prospect_id"] != prospect_id or slot["status"] != "BOOKED":
            continue
        slot["status"] = "AVAILABLE"
        slot["prospect_id"] = ""
        store.touch(slot)
        home = store.get("homes", slot["home_id"])
        if home is not None:
            home["booked_showing_count"] = max(0, int(home["booked_showing_count"]) - 1)
            store.touch(home)
