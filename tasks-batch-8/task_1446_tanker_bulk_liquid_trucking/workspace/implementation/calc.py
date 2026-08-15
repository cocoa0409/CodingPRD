"""Calculation rules (scaffold 1.3 / PRD 3). Money is integer cents;
gallonage is 1-decimal round-half-up; weights are integer pounds. No float
arithmetic anywhere — every computation runs through Decimal."""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from db import store

# net60_temperature_correction constants
REFERENCE_TEMP_F = Decimal("60")

# billing_totals / customer_credit_exposure constants
RACK_FEE_CENTS = 15000
FUEL_SURCHARGE_PCT = Decimal("0.04")

# allowed_delivery_loss constants
LOSS_BASE_GAL = Decimal("5.0")
LOSS_PER_MILE_GAL = Decimal("0.02")
LOSS_CAP_GAL = Decimal("50.0")

# axle_load_compliance constants
WEIGHT_SUM_TOLERANCE_PCT = Decimal("0.03")

# wash_requirement_resolution constants
WASH_RANK = {"NONE": 0, "FLUSH": 1, "DETERGENT_WASH": 2, "CHEMICAL_KOSHER": 3}
WASH_VALIDITY_HOURS = {"FLUSH": 48, "DETERGENT_WASH": 96, "CHEMICAL_KOSHER": 168}

# dedicated_shortfall_settlement constants
COMMITMENT_FLOOR_PCT = Decimal("0.8")
SHORTFALL_FEE_PER_LOAD_CENTS = 25000
FLAG_SUSPEND_THRESHOLD = 2

# spill_severity_classification constants
MAJOR_THRESHOLD_GAL = Decimal("10")
REPORTABLE_THRESHOLD_GAL = Decimal("100")
REPORTABLE_DEADLINE = timedelta(hours=12)

# RetainSample / SpillResponsePlan validity constants
RETAIN_SAMPLE_DAYS = 90
SPILL_PLAN_VALIDITY_DAYS = 365

# Shipment statuses that count toward credit exposure (provisional basis).
EXPOSURE_PROVISIONAL_STATUSES = (
    "PLANNED", "LOADING", "LOADED", "IN_TRANSIT", "DELIVERING",
    "DELIVERED", "VARIANCE_REVIEW",
)


def D(v):
    """Coerce an int/float/str numeric to Decimal without float artifacts."""
    return v if isinstance(v, Decimal) else Decimal(str(v))


def rhup1(v):
    """Round half up to exactly 1 decimal place."""
    return D(v).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def rhup0_int(v):
    """Round half up to an integer."""
    return int(D(v).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# net60_temperature_correction (PRD 3.4/3.5)
# ---------------------------------------------------------------------------

def net60_gallons(observed_gal, temp_coeff_per_degF, observed_temp_F):
    """net60 = round_half_up_1dp(observed * (1 - coeff * (temp - 60)))."""
    return rhup1(D(observed_gal) *
                 (Decimal(1) - D(temp_coeff_per_degF) * (D(observed_temp_F) - REFERENCE_TEMP_F)))


# ---------------------------------------------------------------------------
# billing_totals (PRD 3.6): pinned per-line rounding before summing
# ---------------------------------------------------------------------------

def billing_total_cents(basis_gallons, rate_per_gal_cents, shortage_credit_cents=0):
    charge = rhup0_int(D(basis_gallons) * rate_per_gal_cents)
    surcharge = rhup0_int(FUEL_SURCHARGE_PCT * charge)
    return charge + surcharge + RACK_FEE_CENTS - shortage_credit_cents


def plan_estimate_cents(ordered_gallons, rate_per_gal_cents):
    """Plan-time estimate: the provisional formula on the ordered quantity."""
    return billing_total_cents(ordered_gallons, rate_per_gal_cents, 0)


def shortage_credit_cents(loaded_net60, delivered_net60, allowed_loss, rate_per_gal_cents):
    excess = D(loaded_net60) - D(delivered_net60) - D(allowed_loss)
    if excess <= 0:
        return 0
    return rhup0_int(excess * rate_per_gal_cents)


# ---------------------------------------------------------------------------
# allowed_delivery_loss (PRD 3.5)
# ---------------------------------------------------------------------------

def allowed_loss_gal(route_miles):
    return rhup1(min(LOSS_CAP_GAL, LOSS_BASE_GAL + LOSS_PER_MILE_GAL * route_miles))


def variance_gallons(loaded_net60, delivered_net60):
    return rhup1(D(loaded_net60) - D(delivered_net60))


# ---------------------------------------------------------------------------
# axle_load_compliance (PRD 3.4)
# ---------------------------------------------------------------------------

def product_weight_lb(net60, density_lb_per_gal):
    return rhup0_int(D(net60) * D(density_lb_per_gal))


def expected_gross_lb(trailer, net60, density_lb_per_gal):
    return trailer["tare_weight_lb"] + product_weight_lb(net60, density_lb_per_gal)


# ---------------------------------------------------------------------------
# wash_requirement_resolution (PRD 3.3)
# ---------------------------------------------------------------------------

def find_rule(prior_group, next_group):
    for r in store.compat_rules.values():
        if r["prior_group"] == prior_group and r["next_group"] == next_group:
            return r
    return None


# ---------------------------------------------------------------------------
# customer_credit_exposure (PRD 3.6)
# ---------------------------------------------------------------------------

def customer_exposure_cents(customer_id):
    """Sum provisional totals (plan estimate while no meter ticket has
    closed) over live shipments plus final totals over RECONCILED shipments.
    DRAFT and CANCELLED contribute zero."""
    total = 0
    for s in store.shipments.values():
        if s["customer_id"] != customer_id:
            continue
        st = s["status"]
        if st in EXPOSURE_PROVISIONAL_STATUSES:
            if s["provisional_total_cents"] is not None:
                total += s["provisional_total_cents"]
            else:
                total += plan_estimate_cents(s["ordered_gallons"], s["rate_per_gal_cents"])
        elif st == "RECONCILED":
            total += s["final_total_cents"] or 0
    return total


# ---------------------------------------------------------------------------
# dedicated_shortfall_settlement (PRD 3.8)
# ---------------------------------------------------------------------------

def commitment_floor_loads(committed_loads_per_month):
    return int((COMMITMENT_FLOOR_PCT * committed_loads_per_month)
               .to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# spill_severity_classification (PRD 3.7)
# ---------------------------------------------------------------------------

def severity_for(gallons_spilled):
    g = D(gallons_spilled)
    if g < MAJOR_THRESHOLD_GAL:
        return "MINOR"
    if g < REPORTABLE_THRESHOLD_GAL:
        return "MAJOR"
    return "REPORTABLE"


# ---------------------------------------------------------------------------
# shared lookups
# ---------------------------------------------------------------------------

def open_meter_ticket(shipment_id):
    for t in store.meter_tickets.values():
        if t["shipment_id"] == shipment_id and t["status"] == "OPEN":
            return t
    return None


def closed_meter_ticket(shipment_id):
    for t in store.meter_tickets.values():
        if t["shipment_id"] == shipment_id and t["status"] == "CLOSED":
            return t
    return None


def approved_spill_plan(customer_id, product_id):
    """An APPROVED plan for (customer, product) whose expires_at is later
    than the logical clock (departure gate, PRD 3.4)."""
    for p in store.spill_plans.values():
        if (p["customer_id"] == customer_id and p["product_id"] == product_id
                and p["status"] == "APPROVED" and p["expires_at"] is not None
                and p["expires_at"] > store.clock):
            return p
    return None


def active_agreement_for(customer_id, trailer_id):
    for a in store.agreements.values():
        if (a["customer_id"] == customer_id and a["trailer_id"] == trailer_id
                and a["status"] == "ACTIVE"):
            return a
    return None
