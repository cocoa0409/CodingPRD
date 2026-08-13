"""Business logic: pricing, tiers, co-op accruals, allocation, compliance
standing, coverage and rebate qualification calculations, and lazy sweeps."""
from datetime import timedelta
from decimal import Decimal

import clock
import db
import utils
from utils import touch, round_half_up_cents, add_months

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TIER_ORDER = {"STANDARD": 0, "SILVER": 1, "GOLD": 2, "PLATINUM": 3}
TIER_DISCOUNT = {
    "STANDARD": Decimal("0.00"),
    "SILVER": Decimal("0.03"),
    "GOLD": Decimal("0.05"),
    "PLATINUM": Decimal("0.07"),
}
SILVER_THRESHOLD = 5000000
GOLD_THRESHOLD = 20000000
PLATINUM_THRESHOLD = 50000000
ACCRUAL_RATE = Decimal("0.02")
HEEL_MIN_FRACTION = Decimal("0.90")
OVERDUE_DAYS = 30
REBATE_TIER_AMOUNT = {"PREMIUM": 200000, "HIGH": 100000, "STANDARD": 0}
FEDERAL_COST_CAP_PCT = Decimal("0.30")
ORDER_TERMINAL = {"DELIVERED", "CANCELLED"}

# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def entity(store, entity_id):
    return store.get(entity_id)


def mutate_if_changed(entity, field, new_value):
    if entity.get(field) != new_value:
        entity[field] = new_value
        return True
    return False


# ---------------------------------------------------------------------------
# Tier / pricing
# ---------------------------------------------------------------------------


def tier_for_ytd(ytd):
    if ytd >= PLATINUM_THRESHOLD:
        return "PLATINUM"
    if ytd >= GOLD_THRESHOLD:
        return "GOLD"
    if ytd >= SILVER_THRESHOLD:
        return "SILVER"
    return "STANDARD"


def line_component_models(line):
    """Equipment models whose family_code an order line draws allocation on."""
    if line.get("equipment_model_id"):
        m = db.equipment_models.get(line["equipment_model_id"])
        return [m] if m else []
    rating = db.ahri_ratings.get(line.get("ahri_rating_id") or "")
    if not rating:
        return []
    models = []
    for key in ("outdoor_unit_id", "indoor_unit_id", "furnace_id"):
        mid = rating.get(key)
        if mid:
            m = db.equipment_models.get(mid)
            if m:
                models.append(m)
    return models


def line_list_price_cents(line):
    """List-price basis for a line: model price for part lines, sum of
    component list prices for AHRI system lines."""
    return sum(m["list_price_cents"] for m in line_component_models(line))


def resolve_line_pricing(order, line):
    """Resolve unit_price_cents / line_discount_cents / line_total_cents for a
    line under the order's current terms (tier discount vs pre-buy terms)."""
    contractor = db.contractors.get(order["contractor_id"])
    tier = contractor["tier"] if contractor else "STANDARD"
    list_price = line_list_price_cents(line)
    program = None
    if order.get("prebuy_program_id"):
        program = db.prebuy_programs.get(order["prebuy_program_id"])
    if program is not None:
        # Pre-buy: no tier discount; unit price is list price.
        unit_price = list_price
        gross = unit_price * line["quantity"]
        discount = round_half_up_cents(Decimal(gross) * program["discount_pct"])
    else:
        unit_price = round_half_up_cents(
            Decimal(list_price) * (Decimal("1") - TIER_DISCOUNT[tier]))
        gross = unit_price * line["quantity"]
        discount = 0
    line["unit_price_cents"] = unit_price
    line["line_discount_cents"] = discount
    line["line_total_cents"] = gross - discount


def recompute_order_totals(order):
    """Recompute subtotal/discount/total/deposit from current lines. Discounts
    are pinned per-line (rounded per line, then summed); the deposit is rounded
    once on the summed total."""
    lines = [l for l in db.order_lines.values() if l["order_id"] == order["id"]]
    subtotal = sum(l["unit_price_cents"] * l["quantity"] for l in lines)
    discount = sum(l["line_discount_cents"] for l in lines)
    total = subtotal - discount
    deposit = 0
    if order.get("prebuy_program_id"):
        program = db.prebuy_programs.get(order["prebuy_program_id"])
        if program is not None:
            deposit = round_half_up_cents(Decimal(total) * program["deposit_pct"])
    order["subtotal_cents"] = subtotal
    order["discount_cents"] = discount
    order["total_cents"] = total
    order["deposit_due_cents"] = deposit


def reprice_order(order):
    for line in db.order_lines.values():
        if line["order_id"] == order["id"]:
            resolve_line_pricing(order, line)
    recompute_order_totals(order)


# ---------------------------------------------------------------------------
# Co-op accruals and YTD
# ---------------------------------------------------------------------------

_PROVISIONAL_STATUSES = {"SUBMITTED", "BACKORDERED", "ALLOCATED", "SHIPPED", "DELIVERED"}


def compute_provisional_accrual(contractor_id):
    base = 0
    for o in db.orders.values():
        if o["contractor_id"] != contractor_id:
            continue
        if o["status"] not in _PROVISIONAL_STATUSES:
            continue
        for l in db.order_lines.values():
            if l["order_id"] == o["id"]:
                base += l["line_total_cents"]
    return round_half_up_cents(Decimal(base) * ACCRUAL_RATE)


def compute_final_accrual(contractor_id):
    base = 0
    for o in db.orders.values():
        if o["contractor_id"] != contractor_id or o["status"] != "DELIVERED":
            continue
        for l in db.order_lines.values():
            if l["order_id"] == o["id"]:
                base += l["line_total_cents"]
    accrued = round_half_up_cents(Decimal(base) * ACCRUAL_RATE)
    paid = sum(c["approved_amount_cents"] or 0
               for c in db.coop_claims.values()
               if c["contractor_id"] == contractor_id and c["status"] == "PAID")
    return accrued - paid


def compute_ytd(contractor_id):
    year = clock.now().year
    total = 0
    for o in db.orders.values():
        if o["contractor_id"] != contractor_id or o["status"] != "DELIVERED":
            continue
        submitted = o.get("submitted_at")
        if submitted is not None and submitted.year == year:
            total += o["total_cents"]
    return total


def refresh_contractor_commercials(contractor):
    """Recompute ytd, tier, and both accrual balances; a single mutation
    (one version bump) if anything changed."""
    changed = False
    changed |= mutate_if_changed(contractor, "ytd_purchase_cents",
                                 compute_ytd(contractor["id"]))
    changed |= mutate_if_changed(contractor, "tier",
                                 tier_for_ytd(contractor["ytd_purchase_cents"]))
    changed |= mutate_if_changed(contractor, "coop_accrual_provisional_cents",
                                 compute_provisional_accrual(contractor["id"]))
    changed |= mutate_if_changed(contractor, "coop_accrual_final_cents",
                                 compute_final_accrual(contractor["id"]))
    if changed:
        touch(contractor)
    return changed


def refresh_provisional(contractor_id):
    contractor = db.contractors.get(contractor_id)
    if contractor is None:
        return
    new_val = compute_provisional_accrual(contractor_id)
    if mutate_if_changed(contractor, "coop_accrual_provisional_cents", new_val):
        touch(contractor)


# ---------------------------------------------------------------------------
# Training credit balance
# ---------------------------------------------------------------------------


def compute_training_balance(contractor_id):
    now = clock.now()
    total = 0
    for t in db.training_credits.values():
        if t["contractor_id"] != contractor_id:
            continue
        if t["status"] not in ("ACTIVE", "PARTIALLY_CONSUMED"):
            continue
        if t["expires_at"] <= now:
            continue
        total += t["credit_hours"] - t["consumed_hours"]
    return total


def refresh_training_balance(contractor):
    new_val = compute_training_balance(contractor["id"])
    if mutate_if_changed(contractor, "training_credit_balance_hours", new_val):
        touch(contractor)


# ---------------------------------------------------------------------------
# Compliance standing / heel violations
# ---------------------------------------------------------------------------


def heel_violation_count(contractor_id):
    """Heel-shortfall events recorded in the trailing 12 months (logical clock)."""
    now = clock.now()
    window_start = add_months(now, -12)
    return sum(1 for v in db.heel_violations
               if v["contractor_id"] == contractor_id
               and v["recorded_at"] >= window_start)


def contractor_has_overdue_cylinder(contractor_id):
    now = clock.now()
    for c in db.refrigerant_cylinders.values():
        if c.get("holder_contractor_id") != contractor_id:
            continue
        if c["status"] in ("ISSUED", "RETURN_PENDING"):
            issued = c.get("issued_at")
            if issued is not None and now > issued + timedelta(days=OVERDUE_DAYS):
                return True
    return False


def recompute_compliance_standing(contractor, overdue_return_just_cleared=False):
    """refrigerant_net_balance standing rule:
    HOLD if any held cylinder overdue or >= 2 heel violations in 12m;
    WATCH if exactly 1 heel violation or an overdue return just cleared
    (sticky); otherwise GOOD."""
    if overdue_return_just_cleared:
        contractor["_had_overdue_return"] = True
    if contractor_has_overdue_cylinder(contractor["id"]):
        new_standing = "HOLD"
    elif heel_violation_count(contractor["id"]) >= 2:
        new_standing = "HOLD"
    elif heel_violation_count(contractor["id"]) == 1:
        new_standing = "WATCH"
    elif contractor.get("_had_overdue_return"):
        new_standing = "WATCH"
    else:
        new_standing = "GOOD"
    changed = mutate_if_changed(contractor, "compliance_standing", new_standing)
    new_count = heel_violation_count(contractor["id"])
    changed |= mutate_if_changed(contractor, "heel_violation_count_12m", new_count)
    if changed:
        touch(contractor)


# ---------------------------------------------------------------------------
# Allocation (waterfall)
# ---------------------------------------------------------------------------


def pool_effective_status(pool):
    if pool.get("_manually_closed"):
        return "CLOSED"
    now = clock.now()
    if pool["season_start"] <= now < pool["season_end"]:
        return "OPEN"
    return "CLOSED"


def pool_available(pool):
    return pool["total_qty"] - pool["reserved_qty"] - pool["committed_qty"]


def select_pool(family_code):
    """Most recent season_start first, ties by created_at ASC; only pools that
    are OPEN and whose season covers the logical clock."""
    now = clock.now()
    candidates = [
        p for p in db.allocation_pools.values()
        if p["family_code"] == family_code
        and pool_effective_status(p) == "OPEN"
        and p["season_start"] <= now < p["season_end"]
    ]
    candidates.sort(key=lambda p: (p["created_at"], p["_seq"]))
    candidates.sort(key=lambda p: p["season_start"], reverse=True)
    return candidates[0] if candidates else None


def line_reservation_plan(line):
    """[(pool, qty), ...] for every component family of the line, aggregated per
    pool (several components may share a family), or an empty list when the
    line is unrestricted (no component has an eligible pool)."""
    by_pool = {}
    for model in line_component_models(line):
        pool = select_pool(model["family_code"])
        if pool is not None:
            by_pool[pool["id"]] = (pool, by_pool.get(pool["id"], (pool, 0))[1]
                                   + line["quantity"])
    return list(by_pool.values())


def attempt_allocation(order):
    """Reserve all-or-nothing per line; convert to committed when every line is
    covered. Mutates pool quantities and order reservation bookkeeping."""
    lines = [l for l in db.order_lines.values() if l["order_id"] == order["id"]]
    reservations = order.setdefault("_reservations", {})
    short_pool_ids = set(order.get("_short_pool_ids", []))
    touched_pools = {}

    for line in lines:
        if line["id"] in reservations:
            continue  # already holding a reservation from a prior attempt
        plan = line_reservation_plan(line)
        if not plan:
            continue  # unrestricted line
        if all(pool_available(pool) >= qty for pool, qty in plan):
            for pool, qty in plan:
                pool["reserved_qty"] += qty
                touched_pools[pool["id"]] = pool
            reservations[line["id"]] = [
                {"pool_id": pool["id"], "qty": qty} for pool, qty in plan]
        else:
            short_pool_ids.update(p["id"] for p, _ in plan)

    order["_short_pool_ids"] = sorted(short_pool_ids)

    fully_covered = True
    for line in lines:
        plan = line_reservation_plan(line)
        if plan and line["id"] not in reservations:
            fully_covered = False
            break

    if fully_covered and lines:
        # SUBMITTED -> ALLOCATED: every reservation converts to committed.
        committed = []
        for line_id, entries in reservations.items():
            for entry in entries:
                pool = db.allocation_pools.get(entry["pool_id"])
                if pool is not None:
                    pool["reserved_qty"] -= entry["qty"]
                    pool["committed_qty"] += entry["qty"]
                    touched_pools[pool["id"]] = pool
                    committed.append({"pool_id": pool["id"], "qty": entry["qty"]})
        order["_committed"] = committed
        order["_reservations"] = {}
        order["_short_pool_ids"] = []
        order["status"] = "ALLOCATED"
    elif lines:
        order["status"] = "BACKORDERED"

    for pool in touched_pools.values():
        touch(pool)
    return order["status"]


def release_reservations(order):
    """Release every reservation/commitment the order holds (cancel or
    pool-close reversion), preserving reserved+committed conservation."""
    touched = {}
    for line_id, entries in order.get("_reservations", {}).items():
        for entry in entries:
            pool = db.allocation_pools.get(entry["pool_id"])
            if pool is not None:
                pool["reserved_qty"] -= entry["qty"]
                touched[pool["id"]] = pool
    for entry in order.get("_committed", []):
        pool = db.allocation_pools.get(entry["pool_id"])
        if pool is not None:
            pool["committed_qty"] -= entry["qty"]
            touched[pool["id"]] = pool
    order["_reservations"] = {}
    order["_committed"] = []
    order["_short_pool_ids"] = []
    for pool in touched.values():
        touch(pool)


def rereservation_sweep():
    """Re-evaluate open (non-terminal, uncommitted) orders in allocation
    priority: tier rank, submitted_at ASC, created_at ASC."""
    candidates = [
        o for o in db.orders.values()
        if o["status"] in ("SUBMITTED", "BACKORDERED") and o.get("submitted_at")
    ]
    if not candidates:
        return

    def priority(o):
        contractor = db.contractors.get(o["contractor_id"])
        tier = contractor["tier"] if contractor else "STANDARD"
        return (-TIER_ORDER.get(tier, 0), o["submitted_at"], o["created_at"],
                o["_seq"])

    candidates.sort(key=priority)
    for order in candidates:
        before = order["status"]
        attempt_allocation(order)
        if order["status"] != before:
            touch(order)
        refresh_provisional(order["contractor_id"])


def revert_orders_shorted_by_pool(pool_id):
    """Pool close: BACKORDERED orders whose shortage traces to this pool revert
    to SUBMITTED with their partial reservations released."""
    for order in list(db.orders.values()):
        if order["status"] != "BACKORDERED":
            continue
        if pool_id not in order.get("_short_pool_ids", []):
            continue
        release_reservations(order)
        order["status"] = "SUBMITTED"
        touch(order)
        refresh_provisional(order["contractor_id"])


# ---------------------------------------------------------------------------
# Program / pool status recomputation
# ---------------------------------------------------------------------------


def program_effective_status(program):
    now = clock.now()
    closed = program.get("_manually_closed") or now >= program["window_end"]
    if not closed:
        if now >= program["window_start"]:
            return "OPEN"
        return "SCHEDULED"
    if now > program["ship_by_date"]:
        orders = [o for o in db.orders.values()
                  if o.get("prebuy_program_id") == program["id"]]
        if all(o["status"] in ORDER_TERMINAL for o in orders):
            return "SETTLED"
    return "CLOSED"


def recompute_program_status(program):
    new_status = program_effective_status(program)
    if mutate_if_changed(program, "status", new_status):
        touch(program)
        return True
    return False


def recompute_pool_status(pool):
    """Returns True when the pool flipped OPEN -> CLOSED (caller may need to
    revert backordered orders)."""
    old = pool["status"]
    new_status = pool_effective_status(pool)
    if old != new_status:
        pool["status"] = new_status
        touch(pool)
        if old == "OPEN" and new_status == "CLOSED":
            revert_orders_shorted_by_pool(pool["id"])
        return True
    return False


# ---------------------------------------------------------------------------
# Parts-claim auto-denial cascade (registration lapse / void)
# ---------------------------------------------------------------------------


def deny_open_claims_for_registration(registration_id):
    for claim in db.parts_claims.values():
        if claim["warranty_registration_id"] != registration_id:
            continue
        if claim["status"] in ("SUBMITTED", "MORE_INFO_REQUESTED"):
            claim["status"] = "DENIED"
            touch(claim)


# ---------------------------------------------------------------------------
# Lazy sweeps (PRD 2.4): evaluated on every read and every transition — never
# on the clock-setting call itself.
# ---------------------------------------------------------------------------


def run_lazy_sweeps():
    now = clock.now()

    # Cylinder overdue detection: ISSUED past issued_at + 30 days ->
    # RETURN_PENDING; overdue alone forces the holder's standing to HOLD.
    for cyl in list(db.refrigerant_cylinders.values()):
        if cyl["status"] == "ISSUED":
            issued = cyl.get("issued_at")
            if issued is not None and now > issued + timedelta(days=OVERDUE_DAYS):
                cyl["status"] = "RETURN_PENDING"
                touch(cyl)
                holder = db.contractors.get(cyl.get("holder_contractor_id") or "")
                if holder is not None:
                    recompute_compliance_standing(holder)

    # Warranty registration lapse, with parts-claim denial cascade.
    for reg in list(db.warranty_registrations.values()):
        if reg["status"] == "PENDING_REGISTRATION" and now > reg["registration_deadline"]:
            reg["status"] = "LAPSED"
            touch(reg)
            deny_open_claims_for_registration(reg["id"])

    # Rebate dossier expiry.
    for reb in list(db.rebate_submissions.values()):
        if reb["status"] == "QUALIFIED" and reb.get("decision_deadline") is not None \
                and now > reb["decision_deadline"]:
            reb["status"] = "EXPIRED"
            touch(reb)

    # Training credit expiry.
    for credit in list(db.training_credits.values()):
        if credit["status"] in ("ACTIVE", "PARTIALLY_CONSUMED") \
                and credit["expires_at"] <= now:
            credit["status"] = "EXPIRED"
            touch(credit)

    # Pre-buy deposit forfeiture: ship_by_date passed while the order (deposit
    # invoiced) has not reached SHIPPED/DELIVERED.
    for order in list(db.orders.values()):
        if order["billing_status"] != "DEPOSIT_INVOICED":
            continue
        if not order.get("prebuy_program_id"):
            continue
        program = db.prebuy_programs.get(order["prebuy_program_id"])
        if program is None:
            continue
        if now > program["ship_by_date"] and order["status"] not in ("SHIPPED", "DELIVERED"):
            order["billing_status"] = "FORFEITED"
            touch(order)

    # Program and pool window recomputation (pool close reverts backorders).
    for program in list(db.prebuy_programs.values()):
        recompute_program_status(program)
    for pool in list(db.allocation_pools.values()):
        recompute_pool_status(pool)

    # Refresh derived contractor figures that the sweeps may have moved.
    for contractor in list(db.contractors.values()):
        refresh_training_balance(contractor)
        new_count = heel_violation_count(contractor["id"])
        if mutate_if_changed(contractor, "heel_violation_count_12m", new_count):
            touch(contractor)


# ---------------------------------------------------------------------------
# Warranty coverage calculation
# ---------------------------------------------------------------------------


def compute_warranty_coverage(claim, registration):
    """warranty_coverage_calculation: age-banded parts coverage, first-year
    labor only when registered on time."""
    delta_days = (claim["failure_date"] - registration["install_date"]).total_seconds() / 86400.0
    age_years = int(delta_days // 365.25)
    coverage_years = registration["extended_coverage_years"]
    if age_years > coverage_years:
        return 0, 0
    if age_years <= 1:
        part_pct = Decimal("1.00")
    elif age_years <= 5:
        part_pct = Decimal("0.75")
    else:
        part_pct = Decimal("0.50")
    labor_pct = Decimal("0.5") if (age_years <= 1 and registration.get("registered_at")) else Decimal("0")
    covered_part = round_half_up_cents(Decimal(claim["part_cost_cents"]) * part_pct)
    covered_labor = round_half_up_cents(Decimal(claim["labor_cost_cents"]) * labor_pct)
    return covered_part, covered_labor


# ---------------------------------------------------------------------------
# Rebate qualification calculation
# ---------------------------------------------------------------------------


def compute_rebate_qualification(submission, order, rating):
    tier_amount = REBATE_TIER_AMOUNT.get(rating["efficiency_class"], 0)
    installed_cost = sum(
        l["line_total_cents"] for l in db.order_lines.values()
        if l["order_id"] == order["id"]
        and l.get("ahri_rating_id") == submission["ahri_rating_id"])
    if submission["program_type"] == "FEDERAL_TAX_CREDIT":
        if not rating["tax_credit_eligible"]:
            return 0
        cap = round_half_up_cents(Decimal(installed_cost) * FEDERAL_COST_CAP_PCT)
        return min(tier_amount, cap)
    # UTILITY_REBATE
    if rating["efficiency_class"] == "STANDARD":
        return 0
    return tier_amount


# ---------------------------------------------------------------------------
# Co-op claim eligibility
# ---------------------------------------------------------------------------


def compute_coop_eligible(claim):
    contractor = db.contractors.get(claim["contractor_id"])
    final_accrual = compute_final_accrual(claim["contractor_id"])
    window = utils.period_window(claim["period"])
    cap = None
    if window is not None:
        start, end = window
        period_base = 0
        for o in db.orders.values():
            if o["contractor_id"] != claim["contractor_id"] or o["status"] != "DELIVERED":
                continue
            delivered_at = o.get("_delivered_at")
            if delivered_at is None or not (start <= delivered_at < end):
                continue
            for l in db.order_lines.values():
                if l["order_id"] == o["id"]:
                    period_base += l["line_total_cents"]
        period_final = round_half_up_cents(Decimal(period_base) * ACCRUAL_RATE)
        cap = round_half_up_cents(Decimal(period_final) * Decimal("0.5"))
        claimed = sum(
            c["approved_amount_cents"] or 0 for c in db.coop_claims.values()
            if c["contractor_id"] == claim["contractor_id"]
            and c["period"] == claim["period"]
            and c["status"] in ("APPROVED", "PAID")
            and c["id"] != claim["id"])
        cap = cap - claimed
    candidates = [claim["spend_cents"], final_accrual]
    if cap is not None:
        candidates.append(cap)
    eligible = min(candidates)
    return max(0, eligible)
