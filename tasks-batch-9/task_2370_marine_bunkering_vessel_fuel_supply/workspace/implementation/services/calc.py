"""Every pinned calculation of the PRD (sections 2.12, 3.2, 3.4, 3.6, 3.8, 3.9)."""

import math
from datetime import timedelta
from decimal import Decimal

import db
from db import store
from errors import ApiError
from validation import rnd

# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #

MIN_WINDOW_HOURS = 6
MEASUREMENT_TOLERANCE_MT = Decimal("1.000")

WATCH_UTILISATION = Decimal("0.8000")
HOLD_UTILISATION = Decimal("1.0000")

ECA_SURCHARGE_USD_PER_MT = Decimal("4.25")

BASE_BAF = Decimal("0.020")
VOL_MID_THRESHOLD = Decimal("0.05")
VOL_HIGH_THRESHOLD = Decimal("0.10")
VOL_STEP_LOW = Decimal("0.000")
VOL_STEP_MID = Decimal("0.010")
VOL_STEP_HIGH = Decimal("0.020")
MODE_PREMIUM_BARGE = Decimal("0.005")
MODE_PREMIUM_TRUCK = Decimal("0.015")
ECA_PREMIUM = Decimal("0.010")
TIER_DISCOUNT = Decimal("0.010")
TIER_QTY_THRESHOLD = Decimal("1000.000")
BAF_FLOOR = Decimal("0.010")
BAF_CEILING = Decimal("0.045")

OFFSPEC_ALLOWANCE_PCT = Decimal("0.15")
DEBUNKER_HANDLING_USD_PER_MT = Decimal("12.00")
SEVERE_EXCEEDANCE_PCT = Decimal("0.050")
SEVERE_EXCEEDANCE_MULTIPLIER = Decimal("1.25")
CREDIT_CAP_PCT = Decimal("0.60")

MAJOR_PENALTY = Decimal("45.00")
MINOR_PENALTY = Decimal("15.00")
MAJOR_VOLUME_LITERS = Decimal("100.00")
FRESH_DAYS = 30
RECENT_DAYS = 90
STALE_DAYS = 180
DECAY_FRESH = Decimal("1.00")
DECAY_RECENT = Decimal("0.50")
DECAY_STALE = Decimal("0.25")
CLEAN_DELIVERY_BONUS = Decimal("1.00")
CLEAN_BONUS_CAP = Decimal("10.00")

PUMP_RATE_MT_PER_HOUR = Decimal("250")
FIXED_HOSE_MINUTES = 60

SAMPLE_RETENTION_DAYS = 90
CLAIM_WINDOW_DAYS = 30
MAX_ANALYSIS_ROUNDS = 2

ACTIVE_ORDER_STATES = ("SCHEDULED", "CLEARED", "PUMPING")
BILLED_INVOICE_STATES = ("ISSUED", "CREDIT_APPLIED")
NON_VOID_INVOICE_STATES = ("PROVISIONAL", "ISSUED", "CREDIT_APPLIED")
OPEN_COMMITMENT_STATES = ("CONFIRMED", "SCHEDULED", "AWAITING_SCHEDULE", "DELIVERED")


# --------------------------------------------------------------------------- #
# index quote selection (PRD 2.12)
# --------------------------------------------------------------------------- #


def _quote_sort_key(quote):
    return (quote["quote_date"], quote["created_at"], quote["_seq"])


def governing_quote(grade_id, instant):
    """Quote with the greatest quote_date <= instant; ties -> later created_at."""
    candidates = [
        q
        for q in store.index_quotes.values()
        if q["grade_id"] == grade_id and q["quote_date"] <= instant
    ]
    if not candidates:
        return None
    return max(candidates, key=_quote_sort_key)


def prior_quote(grade_id, governing):
    candidates = [
        q
        for q in store.index_quotes.values()
        if q["grade_id"] == grade_id and q["quote_date"] < governing["quote_date"]
    ]
    if not candidates:
        return None
    return max(candidates, key=_quote_sort_key)


def index_price(grade_id, instant, strict=True):
    quote = governing_quote(grade_id, instant)
    if quote is None:
        if strict:
            raise ApiError("ERR_INDEX_QUOTE_UNAVAILABLE")
        return None
    return quote["price_usd_per_mt"]


# --------------------------------------------------------------------------- #
# relationship helpers
# --------------------------------------------------------------------------- #


def order_nomination(order):
    return store.nominations.get(order["nomination_id"])


def order_context(order):
    """(nomination, port, grade, customer, asset) behind a delivery order."""
    nomination = order_nomination(order)
    port = store.ports.get(nomination["port_id"]) if nomination else None
    grade = store.fuel_grades.get(nomination["grade_id"]) if nomination else None
    customer = store.customers.get(nomination["customer_id"]) if nomination else None
    asset = store.delivery_assets.get(order["asset_id"])
    return nomination, port, grade, customer, asset


def orders_of_nomination(nomination_id):
    return [
        o for o in store.delivery_orders.values() if o["nomination_id"] == nomination_id
    ]


def notes_of_order(order_id):
    return [
        n
        for n in store.bunker_delivery_notes.values()
        if n["delivery_order_id"] == order_id
    ]


def issued_note_of_order(order_id):
    for note in notes_of_order(order_id):
        if note["status"] == "ISSUED":
            return note
    return None


def invoices_of_order(order_id):
    return [i for i in store.invoices.values() if i["delivery_order_id"] == order_id]


def non_void_invoice_of_order(order_id):
    rows = [i for i in invoices_of_order(order_id) if i["status"] != "VOID"]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows[-1] if rows else None


def claim_order(claim):
    note = store.bunker_delivery_notes.get(claim["bdn_id"])
    if note is None:
        return None
    return store.delivery_orders.get(note["delivery_order_id"])


def analyses_of_claim(claim_id):
    return [a for a in store.lab_analyses.values() if a["claim_id"] == claim_id]


def governing_analysis(claim_id):
    rows = analyses_of_claim(claim_id)
    if not rows:
        return None
    return max(rows, key=lambda a: (a["round_index"], a["created_at"], a["_seq"]))


def open_spill_incidents(asset_id):
    return [
        s
        for s in store.spill_incidents.values()
        if s["asset_id"] == asset_id and s["status"] == "OPEN"
    ]


def grade_compatible(asset, grade):
    """PRD 3.4/3.5 cross-contamination rule."""
    last_grade_id = asset.get("last_grade_id")
    if last_grade_id is None:
        return True
    last_grade = store.fuel_grades.get(last_grade_id)
    if last_grade is not None and (
        last_grade["cross_contamination_group"] == grade["cross_contamination_group"]
    ):
        return True
    return bool(asset.get("segregated_tanks"))


# --------------------------------------------------------------------------- #
# sample custody (PRD 3.7)
# --------------------------------------------------------------------------- #


def sample_custody_status(note):
    if note.get("sample_released_at") is not None:
        return "RELEASED_TO_LAB"
    if db.now() > note["sample_retention_until"]:
        return "EXPIRED"
    return "RETAINED"


# --------------------------------------------------------------------------- #
# customer credit exposure (PRD 3.2)
# --------------------------------------------------------------------------- #


def settled_receivables(customer_id):
    total = Decimal("0")
    for invoice in store.invoices.values():
        if invoice["customer_id"] == customer_id and invoice["status"] in BILLED_INVOICE_STATES:
            total += invoice["final_amount_usd"]
    return rnd(total, 2)


def open_commitments(customer_id, strict=False):
    """Index-valued unbilled commitments; returns (amount, count)."""
    total = Decimal("0")
    count = 0
    for nomination in db.sorted_rows(store.nominations):
        if nomination["customer_id"] != customer_id:
            continue
        if nomination["fulfillment_status"] not in OPEN_COMMITMENT_STATES:
            continue
        billed = False
        for order in orders_of_nomination(nomination["id"]):
            for invoice in invoices_of_order(order["id"]):
                if invoice["status"] in BILLED_INVOICE_STATES:
                    billed = True
                    break
            if billed:
                break
        if billed:
            continue
        price = index_price(nomination["grade_id"], db.now(), strict=strict)
        if price is None:
            continue
        count += 1
        total += nomination["nominated_quantity_mt"] * price
    return rnd(total, 2), count


def credit_status_for(settled, credit_limit):
    if credit_limit == 0:
        return "HOLD" if settled > 0 else "OK"
    utilisation = rnd(settled / credit_limit, 4)
    if utilisation >= HOLD_UTILISATION:
        return "HOLD"
    if utilisation >= WATCH_UTILISATION:
        return "WATCH"
    return "OK"


def conservative_exposure(customer, strict=False):
    settled = settled_receivables(customer["id"])
    commitments, _count = open_commitments(customer["id"], strict=strict)
    return rnd(settled + commitments, 2)


def recompute_settled(customer):
    """calculations.customer_credit_exposure variant settled_receivables."""
    settled = settled_receivables(customer["id"])
    customer["outstanding_balance_usd"] = settled
    customer["credit_status"] = credit_status_for(settled, customer["credit_limit_usd"])
    customer["available_credit_usd"] = rnd(
        customer["credit_limit_usd"] - customer["conservative_exposure_usd"], 2
    )
    return customer


def recompute_exposure(customer, strict=False):
    """Both variants: rewrites all five computed exposure fields."""
    settled = settled_receivables(customer["id"])
    commitments, count = open_commitments(customer["id"], strict=strict)
    conservative = rnd(settled + commitments, 2)
    customer["outstanding_balance_usd"] = settled
    customer["conservative_exposure_usd"] = conservative
    customer["available_credit_usd"] = rnd(customer["credit_limit_usd"] - conservative, 2)
    customer["open_commitment_count"] = count
    customer["credit_status"] = credit_status_for(settled, customer["credit_limit_usd"])
    return customer


def credit_availability_passes(nomination, customer):
    """PRD 3.4 conservative credit check."""
    price = index_price(nomination["grade_id"], db.now(), strict=True)
    prospective_commitment = rnd(nomination["nominated_quantity_mt"] * price, 2)
    conservative = conservative_exposure(customer, strict=False)
    addition = (
        prospective_commitment
        if nomination["fulfillment_status"] == "DRAFT"
        else Decimal("0.00")
    )
    prospective = rnd(conservative + addition, 2)
    return prospective <= customer["credit_limit_usd"]


# --------------------------------------------------------------------------- #
# asset aggregates (PRD 3.1, 3.6)
# --------------------------------------------------------------------------- #


def recompute_committed_quantity(asset):
    total = Decimal("0")
    for order in store.delivery_orders.values():
        if order["asset_id"] == asset["id"] and order["logistics_status"] in ACTIVE_ORDER_STATES:
            total += order["planned_quantity_mt"]
    asset["committed_quantity_mt"] = rnd(total, 3)
    return asset


def recompute_compliance_score(asset):
    incidents = [s for s in store.spill_incidents.values() if s["asset_id"] == asset["id"]]
    incidents.sort(key=lambda s: (s["reported_at"], s["created_at"], s["_seq"]))
    penalty = Decimal("0.00")
    clock = db.now()
    for incident in incidents:
        elapsed = (clock - incident["reported_at"]).total_seconds()
        age_days = math.floor(elapsed / 86400.0)
        if age_days <= FRESH_DAYS:
            decay = DECAY_FRESH
        elif age_days <= RECENT_DAYS:
            decay = DECAY_RECENT
        elif age_days <= STALE_DAYS:
            decay = DECAY_STALE
        else:
            decay = Decimal("0.00")
        penalty = penalty + rnd(incident["penalty_points"] * decay, 2)

    spilled_order_ids = {s["delivery_order_id"] for s in store.spill_incidents.values()}
    clean_count = 0
    for order in store.delivery_orders.values():
        if (
            order["asset_id"] == asset["id"]
            and order["logistics_status"] == "DELIVERED"
            and order["id"] not in spilled_order_ids
        ):
            clean_count += 1
    bonus = min(CLEAN_BONUS_CAP, rnd(Decimal(clean_count) * CLEAN_DELIVERY_BONUS, 2))
    score = rnd(Decimal("100.00") - penalty + bonus, 2)
    score = min(Decimal("100.00"), max(Decimal("0.00"), score))
    asset["compliance_score"] = rnd(score, 2)
    return asset


# --------------------------------------------------------------------------- #
# slot admissibility (PRD 3.4)
# --------------------------------------------------------------------------- #


def asset_slot_conflict(asset, slot_start, slot_end, exclude_order_id=None):
    """Closed-interval rule with a strictly-greater-than turnaround buffer."""
    buffer_minutes = asset["turnaround_buffer_minutes"]
    for order in store.delivery_orders.values():
        if order["asset_id"] != asset["id"]:
            continue
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        if order["logistics_status"] not in ACTIVE_ORDER_STATES:
            continue
        other_start = order["slot_start"]
        other_end = order["slot_end"]
        # closed intervals intersect
        if slot_start <= other_end and other_start <= slot_end:
            return True
        if slot_end < other_start:
            gap_minutes = (other_start - slot_end).total_seconds() / 60.0
        else:
            gap_minutes = (slot_start - other_end).total_seconds() / 60.0
        if not gap_minutes > buffer_minutes:
            return True
    return False


def port_capacity_exceeded(port, slot_start, slot_end, exclude_order_id=None):
    """Half-open aggregate rule at the port."""
    count = 0
    for order in store.delivery_orders.values():
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        if order["logistics_status"] not in ACTIVE_ORDER_STATES:
            continue
        nomination = order_nomination(order)
        if nomination is None or nomination["port_id"] != port["id"]:
            continue
        if slot_start < order["slot_end"] and order["slot_start"] < slot_end:
            count += 1
    return count >= port["concurrent_ops_capacity"]


def derive_auto_slot(nomination, requested_slot_start):
    pump_minutes = int(
        math.ceil(nomination["nominated_quantity_mt"] / PUMP_RATE_MT_PER_HOUR * Decimal(60))
    )
    slot_end = requested_slot_start + timedelta(minutes=pump_minutes + FIXED_HOSE_MINUTES)
    return requested_slot_start, slot_end


def auto_select_asset(nomination, port, grade, slot_start, slot_end):
    """calculations.auto_schedule_asset_selection: eligibility, ranking, tie-break."""
    candidates = []
    for asset in store.delivery_assets.values():
        if asset["home_port_id"] != nomination["port_id"]:
            continue
        if asset["asset_type"] != nomination["delivery_mode"]:
            continue
        if asset["status"] != "AVAILABLE":
            continue
        if asset["capacity_mt"] < nomination["nominated_quantity_mt"]:
            continue
        if not asset["boom_certified"]:
            continue
        if not grade_compatible(asset, grade):
            continue
        if open_spill_incidents(asset["id"]):
            continue
        if asset_slot_conflict(asset, slot_start, slot_end):
            continue
        if port_capacity_exceeded(port, slot_start, slot_end):
            continue
        candidates.append(asset)
    if not candidates:
        return None
    candidates.sort(
        key=lambda a: (
            -a["compliance_score"],
            a["capacity_mt"] - nomination["nominated_quantity_mt"],
            a["created_at"],
            a["_seq"],
        )
    )
    return candidates[0]


# --------------------------------------------------------------------------- #
# measurement resolution (PRD 3.5)
# --------------------------------------------------------------------------- #


def apply_supplier_figures(order):
    order["agreed_quantity_mt"] = rnd(order["barge_sounding_mt"], 3)
    order["measurement_basis"] = "SUPPLIER_FIGURES"
    order["shortfall_mt"] = rnd(
        order["barge_sounding_mt"] - order["agreed_quantity_mt"], 3
    )
    order["measurement_status"] = "AGREED"


def apply_joint_survey(order):
    order["agreed_quantity_mt"] = rnd(order["surveyed_mt"], 3)
    order["measurement_basis"] = "JOINT_SURVEY"
    order["shortfall_mt"] = rnd(
        order["barge_sounding_mt"] - order["agreed_quantity_mt"], 3
    )
    order["measurement_status"] = "AGREED"


# --------------------------------------------------------------------------- #
# off-spec verdict (PRD 3.8)
# --------------------------------------------------------------------------- #


def offspec_verdict(measured_sulfur_pct, port, nomination, grade):
    if port["eca_zone"] and not nomination["scrubber_fitted"]:
        regulatory_limit = port["eca_sulfur_limit_pct"]
    else:
        regulatory_limit = grade["max_sulfur_pct"]
    effective_limit = min(regulatory_limit, grade["max_sulfur_pct"])
    trip_point = effective_limit + grade["test_tolerance_pct"]
    verdict = "OFF_SPEC" if measured_sulfur_pct > trip_point else "ON_SPEC"
    exceedance = rnd(measured_sulfur_pct - trip_point, 3)
    if exceedance < Decimal("0.000"):
        exceedance = Decimal("0.000")
    return verdict, rnd(exceedance, 3)


# --------------------------------------------------------------------------- #
# remediation credit (PRD 3.8) — eight pinned steps
# --------------------------------------------------------------------------- #


def remediation_credit(claim, analysis, invoice, remediation_type):
    affected = claim["affected_quantity_mt"]
    reference_price = invoice["index_price_usd_per_mt"]
    if remediation_type == "PRICE_ALLOWANCE":
        rate = rnd(reference_price * OFFSPEC_ALLOWANCE_PCT, 2)
    else:
        rate = max(
            DEBUNKER_HANDLING_USD_PER_MT,
            rnd(
                (claim["replacement_price_usd_per_mt"] - reference_price)
                + DEBUNKER_HANDLING_USD_PER_MT,
                2,
            ),
        )
    raw_credit = rnd(affected * rate, 2)
    if analysis is not None and analysis["exceedance_pct"] > SEVERE_EXCEEDANCE_PCT:
        raw_credit = rnd(raw_credit * SEVERE_EXCEEDANCE_MULTIPLIER, 2)
    cap = rnd(invoice["provisional_amount_usd"] * CREDIT_CAP_PCT, 2)
    return min(raw_credit, cap)


# --------------------------------------------------------------------------- #
# invoice amount and BAF (PRD 3.9)
# --------------------------------------------------------------------------- #


def bunker_adjustment_factor(nomination, port, quote, grade_id, quantity_basis_mt):
    prior = prior_quote(grade_id, quote)
    if prior is not None and prior["price_usd_per_mt"] != 0:
        volatility = abs(quote["price_usd_per_mt"] - prior["price_usd_per_mt"]) / prior[
            "price_usd_per_mt"
        ]
    else:
        volatility = Decimal("0")

    if volatility < VOL_MID_THRESHOLD:
        volatility_step = VOL_STEP_LOW
    elif volatility < VOL_HIGH_THRESHOLD:
        volatility_step = VOL_STEP_MID
    else:
        volatility_step = VOL_STEP_HIGH

    mode_premium = (
        MODE_PREMIUM_TRUCK if nomination["delivery_mode"] == "TRUCK" else MODE_PREMIUM_BARGE
    )
    eca_premium = ECA_PREMIUM if port["eca_zone"] else Decimal("0")
    tier_discount = (
        TIER_DISCOUNT if quantity_basis_mt >= TIER_QTY_THRESHOLD else Decimal("0")
    )
    raw = BASE_BAF + volatility_step + mode_premium + eca_premium - tier_discount
    clamped = min(BAF_CEILING, max(BAF_FLOOR, raw))
    return rnd(clamped, 4)


def claim_credit_for_order(order_id):
    note_ids = {n["id"] for n in notes_of_order(order_id)}
    total = Decimal("0")
    for claim in store.quality_claims.values():
        if claim["bdn_id"] in note_ids and claim["status"] == "REMEDIATION_ACCEPTED":
            total += claim["credit_usd"]
    return rnd(total, 2)


def compute_invoice_amounts(invoice, order, nomination, port, grade):
    quote = governing_quote(nomination["grade_id"], invoice["pricing_date"])
    if quote is None:
        raise ApiError("ERR_INDEX_QUOTE_UNAVAILABLE")

    quantity_basis = rnd(order["agreed_quantity_mt"], 3)
    index_price_value = quote["price_usd_per_mt"]
    baf_pct = bunker_adjustment_factor(
        nomination, port, quote, nomination["grade_id"], quantity_basis
    )

    fuel_cost = rnd(quantity_basis * index_price_value, 2)
    baf_usd = rnd(fuel_cost * baf_pct, 2)
    barging_fee = max(
        rnd(quantity_basis * grade["base_barging_rate_usd_per_mt"], 2),
        grade["min_barging_fee_usd"],
    )
    eca_surcharge = (
        rnd(quantity_basis * ECA_SURCHARGE_USD_PER_MT, 2)
        if port["eca_zone"]
        else Decimal("0.00")
    )
    provisional = fuel_cost + baf_usd + barging_fee + eca_surcharge
    claim_credit = claim_credit_for_order(order["id"])

    invoice["index_price_usd_per_mt"] = rnd(index_price_value, 2)
    invoice["quantity_basis_mt"] = quantity_basis
    invoice["baf_pct"] = baf_pct
    invoice["fuel_cost_usd"] = fuel_cost
    invoice["baf_usd"] = baf_usd
    invoice["barging_fee_usd"] = rnd(barging_fee, 2)
    invoice["eca_surcharge_usd"] = rnd(eca_surcharge, 2)
    invoice["provisional_amount_usd"] = rnd(provisional, 2)
    invoice["claim_credit_usd"] = claim_credit
    invoice["final_amount_usd"] = rnd(provisional - claim_credit, 2)
    return invoice
