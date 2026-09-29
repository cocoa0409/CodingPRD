"""Every calculation rule in the PRD, implemented exactly.

All arithmetic that can produce a fraction runs on decimal.Decimal at full
precision and is rounded exactly once, half away from zero (ROUND_HALF_UP),
at the moment the PRD says a value becomes observable.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from services import lookup

ZERO = Decimal(0)

# --------------------------------------------------------------------------
# Constant tables
# --------------------------------------------------------------------------
BODY_BUILD_LEAD_DAYS = {"SERVICE": 21, "DUMP": 18, "FLATBED": 12, "VAN": 25}
PTO_INTEGRATION_DAYS = 5
AUX_INTEGRATION_DAYS = 2

LABOR_HOURS = {"SERVICE": 18, "DUMP": 14, "FLATBED": 10, "VAN": 22}
LABOR_RATE_CENTS_PER_HOUR = 11500

STANDARDIZATION_DISCOUNT_PCT = {
    "TIER_A": Decimal("0.08"),
    "TIER_B": Decimal("0.04"),
    "CUSTOM": Decimal("0.00"),
}

# (interface_method, ChassisModel.electrical_bus) -> warranty_impact
ELECTRICAL_WARRANTY_IMPACT = {
    ("BODY_BUILDER_MODULE", "J1939_CAN"): "NONE",
    ("BODY_BUILDER_MODULE", "DISCRETE"): "NONE",
    ("CAN_GATEWAY", "J1939_CAN"): "CONDITIONAL",
    ("CAN_GATEWAY", "DISCRETE"): "NONE",
    ("DIRECT_SPLICE", "J1939_CAN"): "VOIDS",
    ("DIRECT_SPLICE", "DISCRETE"): "CONDITIONAL",
}

WARRANTY_STATUS_RANK = {"INTACT": 0, "CONDITIONAL": 1, "VOIDED": 2}
IMPACT_TO_STATUS = {"NONE": "INTACT", "CONDITIONAL": "CONDITIONAL", "VOIDS": "VOIDED"}

# failure_system -> (chassis_pct, upfitter_pct, goodwill_pct)
BASE_SPLIT_PCT = {
    "CHASSIS_ENGINE": (95, 0, 5),
    "CHASSIS_TRANSMISSION": (95, 0, 5),
    "CHASSIS_BRAKES": (95, 0, 5),
    "CHASSIS_ELECTRICAL": (60, 35, 5),
    "BODY_STRUCTURE": (0, 95, 5),
    "BODY_ELECTRICAL": (0, 95, 5),
    "HYDRAULICS": (0, 95, 5),
}
CHASSIS_FAILURE_SYSTEMS = (
    "CHASSIS_ENGINE",
    "CHASSIS_TRANSMISSION",
    "CHASSIS_BRAKES",
    "CHASSIS_ELECTRICAL",
)
MAX_TAINT_SHIFT_PCT = 45

WEIGHT_ACTIVE_INSTALL_STATUSES = ("PLANNED", "INSTALLED", "COMMISSIONED")
PHYSICAL_INSTALL_STATUSES = ("INSTALLED", "COMMISSIONED")
POSTED_CLAIM_STATUSES = ("ADJUDICATED", "PAID")


def round_half_up(value):
    """Round a Decimal to a whole number; an exact midpoint rounds away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# axle_load_distribution  +  payload_capacity
# --------------------------------------------------------------------------
def _inclusion_items(order, basis):
    """The (weight, distance-behind-front-axle) pairs that participate."""
    items = []
    body = db.body_specs.get(order.get("body_spec_id"))
    offset = Decimal(order.get("body_mount_offset_from_front_axle_in") or 0)
    if body is not None:
        body_distance = offset + Decimal(body["cg_from_body_front_in"])
        if basis == "AS_DESIGNED":
            items.append((Decimal(body["weight_lb"]), body_distance))
        elif order.get("body_install_status") == "INSTALLED":
            actual = order.get("body_actual_weight_lb")
            weight = Decimal(actual) if actual is not None else Decimal(body["weight_lb"])
            items.append((weight, body_distance))

    statuses = (
        WEIGHT_ACTIVE_INSTALL_STATUSES if basis == "AS_DESIGNED" else PHYSICAL_INSTALL_STATUSES
    )
    for inst in lookup.installations_of(order["id"]):
        if inst["status"] not in statuses:
            continue
        spec = db.equipment_specs.get(inst["equipment_spec_id"])
        if spec is None:
            continue
        if basis == "AS_DESIGNED":
            weight = Decimal(spec["weight_lb"])
        else:
            actual = inst.get("actual_weight_lb")
            weight = Decimal(actual) if actual is not None else Decimal(spec["weight_lb"])
        items.append((weight, Decimal(inst["mount_cg_from_front_axle_in"])))
    return items


def _curb_weights(order, basis, model):
    if basis == "AS_DESIGNED":
        return (
            Decimal(model["curb_front_axle_lb"]),
            Decimal(model["curb_rear_axle_lb"]),
        )
    unit = db.chassis_units.get(order.get("chassis_id")) if order.get("chassis_id") else None
    front = (unit or {}).get("measured_front_axle_weight_lb")
    rear = (unit or {}).get("measured_rear_axle_weight_lb")
    return (
        Decimal(front if front is not None else 0),
        Decimal(rear if rear is not None else 0),
    )


def axle_load_distribution(order, basis):
    """Statically determinate two-axle beam.  Contributions accumulate at full
    precision; only the two axle totals are rounded, and gvw_lb is the sum of
    those two already-rounded integers."""
    model = lookup.governing_chassis_model(order)
    wheelbase = Decimal(model["wheelbase_in"])
    front_acc, rear_acc = _curb_weights(order, basis, model)
    items = _inclusion_items(order, basis)
    for weight, distance in items:
        rear_share = weight * distance / wheelbase
        front_acc += weight - rear_share
        rear_acc += rear_share
    front_axle_load_lb = round_half_up(front_acc)
    rear_axle_load_lb = round_half_up(rear_acc)
    return {
        "front_axle_load_lb": front_axle_load_lb,
        "rear_axle_load_lb": rear_axle_load_lb,
        "gvw_lb": front_axle_load_lb + rear_axle_load_lb,
        "included_component_count": len(items),
        "_model": model,
    }


def payload_capacity(order, loads, model):
    """The binding of three ceilings: gross vehicle mass, rear axle rating and
    front axle rating.  The minimum is taken over the unrounded candidates and
    rounded once; a negative result floors at zero."""
    body = db.body_specs.get(order.get("body_spec_id"))
    wheelbase = Decimal(model["wheelbase_in"])
    cargo_distance = Decimal(order.get("body_mount_offset_from_front_axle_in") or 0) + Decimal(
        (body or {}).get("cargo_cg_from_body_front_in") or 0
    )
    rear_share = cargo_distance / wheelbase
    front_share = Decimal(1) - rear_share

    candidates = [Decimal(model["gvwr_lb"]) - Decimal(loads["gvw_lb"])]
    if rear_share > 0:
        candidates.append(
            (Decimal(model["rear_gawr_lb"]) - Decimal(loads["rear_axle_load_lb"])) / rear_share
        )
    if front_share > 0:
        candidates.append(
            (Decimal(model["front_gawr_lb"]) - Decimal(loads["front_axle_load_lb"])) / front_share
        )
    binding = min(candidates)
    return max(0, round_half_up(binding))


def weight_projection(order, basis):
    """The full inline projection returned by the read-only projection endpoint
    and reused as the body of every weight certification."""
    loads = axle_load_distribution(order, basis)
    model = loads.pop("_model")
    result = {
        "basis": basis,
        "front_axle_load_lb": loads["front_axle_load_lb"],
        "rear_axle_load_lb": loads["rear_axle_load_lb"],
        "gvw_lb": loads["gvw_lb"],
        "payload_capacity_lb": payload_capacity(order, loads, model),
        "included_component_count": loads["included_component_count"],
        "front_gawr_lb": model["front_gawr_lb"],
        "rear_gawr_lb": model["rear_gawr_lb"],
        "gvwr_lb": model["gvwr_lb"],
    }
    return result


# --------------------------------------------------------------------------
# aux_electrical_load
# --------------------------------------------------------------------------
def committed_aux_amp_draw(order, extra_amps=0, ignore_interface_ids=()):
    """Body draw + every equipment item on the order that is not REMOVED +
    every APPROVED electrical interface.  Whole amps; nothing is rounded."""
    body = db.body_specs.get(order.get("body_spec_id"))
    total = int((body or {}).get("aux_amp_draw") or 0)
    for inst in lookup.installations_of(order["id"]):
        if inst["status"] not in WEIGHT_ACTIVE_INSTALL_STATUSES:
            continue
        spec = db.equipment_specs.get(inst["equipment_spec_id"])
        if spec is not None:
            total += int(spec.get("aux_amp_draw") or 0)
    for iface in lookup.interfaces_of(order["id"]):
        if iface["status"] != "APPROVED" or iface["id"] in ignore_interface_ids:
            continue
        total += int(iface.get("circuit_amp_draw") or 0)
    return total + int(extra_amps or 0)


def refresh_committed_aux(order, ignore_interface_ids=()):
    order["committed_aux_amp_draw"] = committed_aux_amp_draw(
        order, ignore_interface_ids=ignore_interface_ids
    )
    return order["committed_aux_amp_draw"]


# --------------------------------------------------------------------------
# electrical_warranty_impact
# --------------------------------------------------------------------------
def electrical_warranty_impact(interface_method, electrical_bus):
    return ELECTRICAL_WARRANTY_IMPACT[(interface_method, electrical_bus)]


def derive_chassis_warranty_status(order):
    """INTACT while no interface is APPROVED; otherwise the worst posture among
    the APPROVED set."""
    worst = "INTACT"
    for iface in lookup.interfaces_of(order["id"]):
        if iface["status"] != "APPROVED":
            continue
        candidate = IMPACT_TO_STATUS[iface["warranty_impact"]]
        if WARRANTY_STATUS_RANK[candidate] > WARRANTY_STATUS_RANK[worst]:
            worst = candidate
    order["chassis_warranty_status"] = worst
    return worst


# --------------------------------------------------------------------------
# pto_flow_waterfall
# --------------------------------------------------------------------------
def pto_candidates(order):
    """Hydraulic claimants, ordered by duty_priority then created_at.  The row
    id never participates in the ordering."""
    rows = []
    for inst in lookup.installations_of(order["id"]):
        if inst["status"] not in WEIGHT_ACTIVE_INSTALL_STATUSES:
            continue
        spec = db.equipment_specs.get(inst["equipment_spec_id"])
        if spec is None or not spec.get("requires_pto"):
            continue
        rows.append((int(spec.get("duty_priority") or 1), inst.get("_seq") or 0, inst, spec))
    rows.sort(key=lambda t: (t[0], t[1]))
    return [(inst, spec) for _, _, inst, spec in rows]


def committed_pto_flow(order):
    return sum(int(spec.get("required_flow_gpm") or 0) for _, spec in pto_candidates(order))


def available_pto_flow(order):
    """The hydraulic pool belongs to the physical truck: while the order holds
    no chassis the available flow is exactly zero (PRD section 2.11)."""
    if not order.get("chassis_id"):
        return 0
    model = lookup.governing_chassis_model(order)
    return int((model or {}).get("pto_max_flow_gpm") or 0)


def run_pto_waterfall(order):
    """Recompute committed demand and pay it out in priority order."""
    candidates = pto_candidates(order)
    order["committed_pto_flow_gpm"] = sum(
        int(spec.get("required_flow_gpm") or 0) for _, spec in candidates
    )
    remaining = available_pto_flow(order)
    claimed_ids = set()
    for inst, spec in candidates:
        demand = int(spec.get("required_flow_gpm") or 0)
        granted = demand if demand <= remaining else remaining
        inst["allocated_flow_gpm"] = granted
        inst["hydraulic_status"] = "OK" if granted == demand else "DEFICIT"
        remaining -= granted
        claimed_ids.add(inst["id"])
    for inst in lookup.installations_of(order["id"]):
        if inst["id"] in claimed_ids:
            continue
        inst["allocated_flow_gpm"] = 0
        inst["hydraulic_status"] = "NOT_APPLICABLE"
    return order["committed_pto_flow_gpm"]


# --------------------------------------------------------------------------
# earliest_feasible_in_service_date
# --------------------------------------------------------------------------
def earliest_feasible_in_service_date(order):
    body = db.body_specs.get(order.get("body_spec_id"))
    total_days = BODY_BUILD_LEAD_DAYS[(body or {}).get("body_type")]
    for inst in lookup.installations_of(order["id"]):
        if inst["status"] not in WEIGHT_ACTIVE_INSTALL_STATUSES:
            continue
        spec = db.equipment_specs.get(inst["equipment_spec_id"])
        if spec is None:
            continue
        total_days += PTO_INTEGRATION_DAYS if spec.get("requires_pto") else AUX_INTEGRATION_DAYS
    start = db.clock_today()
    unit = db.chassis_units.get(order.get("chassis_id")) if order.get("chassis_id") else None
    if unit is not None and unit.get("availability_date"):
        from validation import as_date

        availability = as_date(unit["availability_date"])
        if availability > start:
            start = availability
    return start + timedelta(days=total_days)


# --------------------------------------------------------------------------
# build_invoice_total
# --------------------------------------------------------------------------
def build_invoice_total(order):
    body = db.body_specs.get(order.get("body_spec_id"))
    config = db.build_configurations.get(order.get("build_configuration_id"))
    subtotal = int((body or {}).get("list_price_cents") or 0)
    for inst in lookup.installations_of(order["id"]):
        if inst["status"] not in WEIGHT_ACTIVE_INSTALL_STATUSES:
            continue
        spec = db.equipment_specs.get(inst["equipment_spec_id"])
        if spec is not None:
            subtotal += int(spec.get("list_price_cents") or 0)
    subtotal += LABOR_HOURS[(body or {}).get("body_type")] * LABOR_RATE_CENTS_PER_HOUR

    pct = ZERO
    if order.get("order_type") == "POOL_STOCK" and config is not None:
        pct = STANDARDIZATION_DISCOUNT_PCT[config["standardization_tier"]]
    discount_cents = round_half_up(Decimal(subtotal) * pct)
    discounted_subtotal = subtotal - discount_cents

    if discounted_subtotal < 2000000:
        fee = 45000
    elif discounted_subtotal < 4000000:
        fee = 72500
    else:
        fee = 98000
    return discounted_subtotal + fee


def refresh_invoice_total(order):
    order["invoice_total_cents"] = build_invoice_total(order)
    return order["invoice_total_cents"]


# --------------------------------------------------------------------------
# warranty_liability_split
# --------------------------------------------------------------------------
def warranty_liability_split(claim, order, split_basis):
    """Base percentages by failure system, then the taint shift, then cents.

    The goodwill share is the remainder of the claim cost after the two rounded
    shares, so the three amounts always sum to claim_cost_cents exactly.
    """
    chassis_pct, upfitter_pct, goodwill_pct = BASE_SPLIT_PCT[claim["failure_system"]]
    if (
        split_basis == "FINAL"
        and claim.get("taint_confirmed")
        and claim["failure_system"] in CHASSIS_FAILURE_SYSTEMS
        and order.get("chassis_warranty_status") in ("CONDITIONAL", "VOIDED")
    ):
        shift = min(MAX_TAINT_SHIFT_PCT, chassis_pct)
        chassis_pct -= shift
        upfitter_pct += shift

    cost = int(claim["claim_cost_cents"])
    cost_dec = Decimal(cost)
    chassis_cents = round_half_up(cost_dec * Decimal(chassis_pct) / Decimal(100))
    upfitter_cents = round_half_up(cost_dec * Decimal(upfitter_pct) / Decimal(100))
    goodwill_cents = cost - chassis_cents - upfitter_cents
    return {
        "chassis_pct": chassis_pct,
        "upfitter_pct": upfitter_pct,
        "goodwill_pct": goodwill_pct,
        "chassis_liability_cents": chassis_cents,
        "upfitter_liability_cents": upfitter_cents,
        "customer_goodwill_cents": goodwill_cents,
    }


def apply_split(claim, order, split_basis):
    result = warranty_liability_split(claim, order, split_basis)
    claim["split_basis"] = split_basis
    claim.update(result)
    return result


def order_liability_ledger(order, ignore_claim_id=None, extra=None):
    """The order's three ledger fields are the sums over its claims that sit at
    ADJUDICATED or PAID."""
    chassis_total = 0
    upfitter_total = 0
    goodwill_total = 0
    for claim in lookup.claims_of(order["id"]):
        if ignore_claim_id is not None and claim["id"] == ignore_claim_id:
            continue
        if claim["status"] not in POSTED_CLAIM_STATUSES:
            continue
        chassis_total += int(claim.get("chassis_liability_cents") or 0)
        upfitter_total += int(claim.get("upfitter_liability_cents") or 0)
        goodwill_total += int(claim.get("customer_goodwill_cents") or 0)
    if extra:
        chassis_total += int(extra.get("chassis_liability_cents") or 0)
        upfitter_total += int(extra.get("upfitter_liability_cents") or 0)
        goodwill_total += int(extra.get("customer_goodwill_cents") or 0)
    return {
        "chassis_liability_cents": chassis_total,
        "upfitter_liability_cents": upfitter_total,
        "customer_goodwill_cents": goodwill_total,
    }


def refresh_order_ledger(order):
    order.update(order_liability_ledger(order))
    return order


# --------------------------------------------------------------------------
# label_responsibility
# --------------------------------------------------------------------------
def installed_equipment_count(order):
    return len(
        [
            i
            for i in lookup.installations_of(order["id"])
            if i["status"] in PHYSICAL_INSTALL_STATUSES
        ]
    )


def label_responsibility(order):
    """How far the upfitter went determines which plate the truck wears."""
    if order.get("body_install_status") == "INSTALLED":
        if installed_equipment_count(order) >= 1:
            return ("FINAL_STAGE", "UPFITTER")
        return ("ALTERER", "UPFITTER")
    return ("INCOMPLETE_PASSTHROUGH", "CHASSIS_MANUFACTURER")
