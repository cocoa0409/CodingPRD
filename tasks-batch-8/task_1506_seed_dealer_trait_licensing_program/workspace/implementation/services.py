"""Business logic: calculations (PRD section 3), state-machine side effects,
cascades, and the season sweeps. All money math uses round-half-up whole cents
via util.rhu_div; per-unit rounding precedes multiplication (pinned order)."""

from decimal import Decimal, ROUND_CEILING

import db
from errors import ApiError, ERR_TRAIT_AGREEMENT_NOT_ACTIVE, ERR_INSUFFICIENT_INVENTORY
from util import rhu_div, rhu_1dp, ceil_nonneg, dt_of

MIN_ORDER_UNITS_FOR_DISCOUNT = 20

DRAINAGE_RANK = {"POOR": 1, "MODERATE": 2, "WELL": 3}

W_SOIL = Decimal("0.35")
W_DRAINAGE = Decimal("0.25")
W_MATURITY = Decimal("0.25")
W_ROTATION = Decimal("0.15")


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def lines_of_order(order_id):
    return [l for l in db.all_of("order_lines") if l["order_id"] == order_id]


def orders_of_program(program_id):
    return [o for o in db.all_of("orders") if o["program_id"] == program_id]


def tickets_of_order(order_id):
    return [t for t in db.all_of("delivery_tickets") if t["order_id"] == order_id]


def returns_of_line(line_id):
    return [r for r in db.all_of("returns") if r["order_line_id"] == line_id]


# ---------------------------------------------------------------------------
# Stewardship gate (priority 9)
# ---------------------------------------------------------------------------

def check_trait_gate(grower_id, variety):
    """Traited seed (package with requires_stewardship_agreement) needs an
    ACTIVE in-window TraitAgreement for (grower, package)."""
    pkg_id = variety.get("trait_package_id")
    if not pkg_id:
        return
    pkg = db.get("trait_packages", pkg_id)
    if pkg is None or not pkg.get("requires_stewardship_agreement"):
        return
    clock = db.now()
    for ag in db.all_of("trait_agreements"):
        if (
            ag["grower_id"] == grower_id
            and ag["trait_package_id"] == pkg_id
            and ag["status"] == "ACTIVE"
            and dt_of(ag, "effective_from") <= clock <= dt_of(ag, "effective_to")
        ):
            return
    raise ApiError(
        ERR_TRAIT_AGREEMENT_NOT_ACTIVE,
        409,
        "no ACTIVE in-window trait agreement for grower and trait package",
    )


# ---------------------------------------------------------------------------
# Pricing calculations
# ---------------------------------------------------------------------------

def early_order_discount_bps(order, program, total_units):
    """calculations.early_order_discount_bps."""
    if order.get("is_replacement"):
        return program["replant_replacement_discount_bps"]
    if total_units < MIN_ORDER_UNITS_FOR_DISCOUNT:
        return 0
    clock = db.now()
    for tier in program.get("early_order_tiers", []):
        if clock <= dt_of(tier, "cutoff_at"):
            return tier["discount_bps"]
    return 0


def treatment_adder(line):
    topt_id = line.get("treatment_option_id")
    if not topt_id:
        return 0
    topt = db.get("treatment_options", topt_id)
    return topt["adder_cents_per_unit"] if topt else 0


def price_line(line, locked_discount_bps):
    """calculations.order_line_pricing: round the discounted UNIT price first,
    then multiply by units. Treatment adders are never discounted."""
    disc_unit = rhu_div(line["unit_price_cents"] * (10000 - locked_discount_bps), 10000)
    adder = treatment_adder(line)
    line_total = disc_unit * line["units"] + adder * line["units"]
    return disc_unit, line_total


def select_rebate_bps(order, program, total_units):
    if order.get("is_replacement"):
        return 0
    best = 0
    for tier in program.get("volume_rebate_tiers", []):
        if tier["min_units"] <= total_units and tier["rebate_bps"] > best:
            best = tier["rebate_bps"]
    return best


def compute_order_totals(order, program, lines, locked_bps):
    """calculations.order_totals. Returns dict of computed fields plus the
    per-line pricing plan [(line, discounted_unit_price, line_total)]."""
    plan = []
    gross = 0
    total_units = 0
    for line in lines:
        disc_unit, line_total = price_line(line, locked_bps)
        plan.append((line, disc_unit, line_total))
        gross += line_total
        total_units += line["units"]
    rebate_bps = select_rebate_bps(order, program, total_units)
    rebate_amount = rhu_div(gross * rebate_bps, 10000)
    net = gross - rebate_amount - order.get("prepay_discount_cents", 0)
    return {
        "plan": plan,
        "total_units": total_units,
        "gross_amount_cents": gross,
        "rebate_bps_applied": rebate_bps,
        "rebate_amount_cents": rebate_amount,
        "net_amount_cents": net,
    }


# ---------------------------------------------------------------------------
# Inventory allocation (calculations.inventory_allocation): FEFO, no splitting
# ---------------------------------------------------------------------------

def _lot_eligible(lot, line, extra_reserved):
    if lot["variety_id"] != line["variety_id"]:
        return False
    if lot.get("treatment_option_id") != line.get("treatment_option_id"):
        return False
    if lot["status"] != "AVAILABLE":
        return False
    if not (dt_of(lot, "expiry_date") > db.now()):
        return False
    available = lot["on_hand_units"] - lot["reserved_units"] - extra_reserved.get(lot["id"], 0)
    return available >= line["units"]


def plan_allocation(lines):
    """Simulate FEFO allocation for all lines atomically. Returns
    [(line, lot)] or raises ERR_INSUFFICIENT_INVENTORY."""
    plan = []
    extra_reserved = {}
    for line in lines:
        pool = [l for l in db.all_of("inventory_lots") if _lot_eligible(l, line, extra_reserved)]
        if not pool:
            raise ApiError(
                ERR_INSUFFICIENT_INVENTORY,
                409,
                "no eligible lot can cover the full line",
            )
        pool.sort(key=lambda l: (dt_of(l, "expiry_date"), l["_seq"]))
        chosen = pool[0]
        extra_reserved[chosen["id"]] = extra_reserved.get(chosen["id"], 0) + line["units"]
        plan.append((line, chosen))
    return plan


def apply_allocation(plan):
    for line, lot in plan:
        lot["reserved_units"] += line["units"]
        line["reserved_units"] = line["units"]
        line["inventory_lot_id"] = lot["id"]
        db.touch(lot)
        db.touch(line)


def release_line_reservation(line):
    lot_id = line.get("inventory_lot_id")
    if lot_id and line.get("reserved_units", 0) > 0:
        lot = db.get("inventory_lots", lot_id)
        if lot is not None:
            lot["reserved_units"] -= line["reserved_units"]
            recompute_lot_status(lot)
            db.touch(lot)
    line["reserved_units"] = 0
    line["inventory_lot_id"] = None
    db.touch(line)


def recompute_lot_status(lot):
    if lot["status"] == "AVAILABLE" and lot["on_hand_units"] == 0:
        lot["status"] = "DEPLETED"
    elif lot["status"] == "DEPLETED" and lot["on_hand_units"] > 0:
        lot["status"] = "AVAILABLE"


# ---------------------------------------------------------------------------
# Fulfillment dimension (computed from line counters)
# ---------------------------------------------------------------------------

def recompute_fulfillment(order):
    lines = lines_of_order(order["id"])
    if not lines:
        status = "NONE"
    else:
        total_units = sum(l["units"] for l in lines)
        total_delivered = sum(l["delivered_units"] for l in lines)
        total_returned = sum(l["returned_units"] for l in lines)
        if total_delivered == 0 and total_returned == 0:
            status = "NONE"
        elif total_returned == 0:
            if all(l["delivered_units"] == l["units"] for l in lines):
                status = "DELIVERED"
            else:
                status = "PARTIAL"
        else:
            full = all(
                l["returned_units"] == l["delivered_units"]
                for l in lines
                if l["delivered_units"] > 0
            )
            status = "RETURNED_FULL" if full else "RETURNED_PARTIAL"
        _ = total_units
    if order["fulfillment_status"] != status:
        order["fulfillment_status"] = status


# ---------------------------------------------------------------------------
# Placement score (calculations.placement_score)
# ---------------------------------------------------------------------------

def compute_placement_score(field, variety):
    soil_match = Decimal("1") if field["soil_type"] in variety.get("preferred_soils", []) else Decimal("0.5")
    drainage_match = (
        Decimal("1")
        if DRAINAGE_RANK[field["drainage"]] >= DRAINAGE_RANK[variety["min_drainage"]]
        else Decimal("0")
    )
    rm_gap = abs(variety["relative_maturity_days"] - field["maturity_zone"] * 10)
    if rm_gap <= 5:
        maturity_fit = Decimal("1")
    elif rm_gap <= 15:
        maturity_fit = Decimal("0.5")
    else:
        maturity_fit = Decimal("0")
    rotation_bonus = Decimal("1") if field["prev_crop"] != variety["crop"] else Decimal("0")
    raw = Decimal(100) * (
        W_SOIL * soil_match
        + W_DRAINAGE * drainage_match
        + W_MATURITY * maturity_fit
        + W_ROTATION * rotation_bonus
    )
    return rhu_1dp(raw)


# ---------------------------------------------------------------------------
# Commission accrual (calculations.commission_accrual)
# ---------------------------------------------------------------------------

def compute_commission(program, final=False):
    included = [o for o in orders_of_program(program["id"]) if o["status"] in ("CONFIRMED", "CLOSED")]
    included_ids = {o["id"] for o in included}
    credited = [
        r for r in db.all_of("returns")
        if r["status"] == "CREDITED" and r["order_id"] in included_ids
    ]
    gross_sales = sum(o["net_amount_cents"] for o in included)
    return_credits = sum(r["credit_cents"] or 0 for r in credited)
    net_sales = gross_sales - return_credits
    volume_units = sum(o["total_units"] for o in included) - sum(r["units"] for r in credited)
    if final:
        volume_units -= sum(o["total_units"] for o in included if o.get("is_replacement"))
    base = rhu_div(net_sales * program["commission_base_bps"], 10000)
    bonus_bps = 0
    for tier in program.get("commission_volume_tiers", []):
        if tier["min_net_units"] <= volume_units and tier["bonus_bps"] > bonus_bps:
            bonus_bps = tier["bonus_bps"]
    bonus = rhu_div(net_sales * bonus_bps, 10000)
    return {
        "gross_sales_cents": gross_sales,
        "return_credits_cents": return_credits,
        "net_sales_cents": net_sales,
        "volume_units": volume_units,
        "base_commission_cents": base,
        "volume_bonus_bps": bonus_bps,
        "volume_bonus_cents": bonus,
        "total_commission_cents": base + bonus,
    }


def statement_of_program(program_id):
    for st in db.all_of("commission_statements"):
        if st["program_id"] == program_id:
            return st
    return None


# ---------------------------------------------------------------------------
# Trait agreement compliance-hold cascade (suspend / revoke from ACTIVE)
# ---------------------------------------------------------------------------

def hold_cascade(agreement):
    """CONFIRMED orders of the grower containing a line whose variety carries
    the agreement's trait package -> COMPLIANCE_HOLD; release reservations."""
    for order in db.all_of("orders"):
        if order["grower_id"] != agreement["grower_id"] or order["status"] != "CONFIRMED":
            continue
        lines = lines_of_order(order["id"])
        hit = False
        for line in lines:
            variety = db.get("varieties", line["variety_id"])
            if variety and variety.get("trait_package_id") == agreement["trait_package_id"]:
                hit = True
                break
        if not hit:
            continue
        for line in lines:
            release_line_reservation(line)
        order["status"] = "COMPLIANCE_HOLD"
        db.touch(order)


# ---------------------------------------------------------------------------
# Season sweeps (PRD section 3.9)
# ---------------------------------------------------------------------------

def close_sales_sweep(program):
    clock = db.now()
    for order in orders_of_program(program["id"]):
        if order["status"] == "DRAFT":
            order["status"] = "CANCELLED"
            db.touch(order)
        elif order["status"] == "CONFIRMED" and order["payment_status"] == "UNPAID":
            order["payment_status"] = "INVOICED"
            grower = db.get("growers", order["grower_id"])
            if grower is not None:
                grower["outstanding_balance_cents"] += order["net_amount_cents"]
                db.touch(grower)
            db.touch(order)
    for rec in db.all_of("recommendations"):
        if rec["program_id"] == program["id"] and rec["status"] in ("DRAFT", "PUBLISHED"):
            rec["status"] = "EXPIRED"
            db.touch(rec)
    for ag in db.all_of("trait_agreements"):
        if ag["status"] in ("ACTIVE", "SUSPENDED") and dt_of(ag, "effective_to") < clock:
            ag["status"] = "EXPIRED"
            db.touch(ag)


def settle_sweep(program):
    clock = db.now()
    for order in orders_of_program(program["id"]):
        if order["status"] == "CONFIRMED":
            order["status"] = "CLOSED"
            if order["payment_status"] == "PREPAID":
                grower = db.get("growers", order["grower_id"])
                if grower is not None:
                    grower["prepay_balance_cents"] -= order["net_amount_cents"]
                    db.touch(grower)
                order["payment_status"] = "SETTLED"
            db.touch(order)
    statement = statement_of_program(program["id"])
    if statement is not None:
        for k, v in compute_commission(program, final=True).items():
            statement[k] = v
        statement["status"] = "FINALIZED"
        statement["finalized_at"] = db.fmt_ts(clock)
        db.touch(statement)
    for lot in db.all_of("inventory_lots"):
        if (
            lot["status"] in ("AVAILABLE", "QUARANTINED")
            and dt_of(lot, "expiry_date") < clock
            and lot["on_hand_units"] > 0
        ):
            lot["written_off_units"] += lot["on_hand_units"]
            lot["on_hand_units"] = 0
            lot["status"] = "EXPIRED"
            db.touch(lot)


# ---------------------------------------------------------------------------
# Replant replacement sizing (calculations.replant_replacement_units)
# ---------------------------------------------------------------------------

def replant_replacement_units(line, field, acres_affected):
    raw_numer = Decimal(str(acres_affected)) * Decimal(int(line["units"]))
    raw = raw_numer / Decimal(str(field["acres"]))
    ceiled = int(raw.to_integral_value(rounding=ROUND_CEILING))
    remainder = line["delivered_units"] - line["returned_units"]
    return min(ceiled, remainder)
