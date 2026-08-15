"""Invoice service: generation, finalization, payment, write-off, void, and all charge calculations."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from errors import ApiError
import db
from db import store, new_common, touch
from services.rate_schedule import find_published_schedule


def create_invoice(body):
    required = ["service_location_id", "billing_period_start", "billing_period_end"]
    for field in required:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    loc = store.service_locations.get(body["service_location_id"])
    if not loc:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceLocation not found")

    inv = new_common({
        "service_location_id": body["service_location_id"],
        "billing_period_start": body["billing_period_start"],
        "billing_period_end": body["billing_period_end"],
        "status": "PROVISIONAL",
        "variant": "PROVISIONAL",
        "kwh_billed": 0,
        "demand_kw_billed": 0,
        "energy_charge_cents": 0,
        "demand_charge_cents": 0,
        "load_management_credit_cents": 0,
        "total_due_cents": 0,
    })
    store.invoices[inv["id"]] = inv
    compute_invoice_fields(inv, provisional=True)
    return inv


def get_invoice(inv_id):
    inv = store.invoices.get(inv_id)
    if not inv:
        raise ApiError("ERR_NOT_FOUND", 404, "Invoice not found")
    return inv


def list_invoices(service_location_id=None, status=None):
    rows = list(store.invoices.values())
    if service_location_id is not None:
        rows = [r for r in rows if r.get("service_location_id") == service_location_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return rows


def compute_invoice_fields(inv, provisional=True):
    """Compute all derived fields on an invoice."""
    loc = store.service_locations[inv["service_location_id"]]
    bp_start = db.parse_iso(inv["billing_period_start"])
    bp_end = db.parse_iso(inv["billing_period_end"])

    if provisional:
        kwh, demand = _provisional_estimate(inv, loc, bp_start, bp_end)
    else:
        kwh, demand = _final_register(inv, loc, bp_start, bp_end)

    inv["kwh_billed"] = kwh
    inv["demand_kw_billed"] = demand

    schedule = find_published_schedule(loc["rate_class"], bp_start)
    if schedule is None:
        # No published schedule; leave charges at 0
        inv["energy_charge_cents"] = 0
        inv["demand_charge_cents"] = 0
        inv["load_management_credit_cents"] = 0
        inv["total_due_cents"] = 0
        return

    # Energy charge: tiered pricing
    inv["energy_charge_cents"] = _compute_energy_charge(
        schedule, kwh, loc, bp_start, bp_end
    )

    # Demand charge
    inv["demand_charge_cents"] = _compute_demand_charge(
        schedule, demand, loc, inv
    )

    # Load management credits
    inv["load_management_credit_cents"] = _compute_lm_credits(
        loc, bp_start, bp_end
    )

    total = (schedule["customer_charge_cents"]
             + inv["energy_charge_cents"]
             + inv["demand_charge_cents"]
             - inv["load_management_credit_cents"])
    inv["total_due_cents"] = max(0, total)


def _provisional_estimate(inv, loc, bp_start, bp_end):
    """Estimate kwh from average daily kwh of prior 3 FINALIZED invoices."""
    prior_finalized = [
        i for i in store.invoices.values()
        if i.get("service_location_id") == loc["id"]
        and i.get("status") in ("FINALIZED", "PAID", "WRITTEN_OFF")
        and i["id"] != inv["id"]
    ]
    prior_finalized.sort(key=lambda i: db.parse_iso(i["billing_period_end"]))
    prior_3 = prior_finalized[-3:]

    if not prior_3:
        return 0, 0

    total_kwh = 0
    total_days = 0
    max_demand = 0
    for p in prior_3:
        p_start = db.parse_iso(p["billing_period_start"])
        p_end = db.parse_iso(p["billing_period_end"])
        days = max(1, (p_end - p_start).days)
        total_kwh += p.get("kwh_billed", 0)
        total_days += days
        max_demand = max(max_demand, p.get("demand_kw_billed", 0))

    avg_daily = total_kwh / total_days if total_days > 0 else 0
    period_days = max(1, (bp_end - bp_start).days)
    est_kwh = int(avg_daily * period_days)
    return est_kwh, max_demand


def _final_register(inv, loc, bp_start, bp_end):
    """Compute kwh from register delta and demand from period max."""
    readings = [
        r for r in store.meter_readings.values()
        if r.get("service_location_id") == loc["id"]
    ]
    if not readings:
        return 0, 0

    readings.sort(key=lambda r: db.parse_iso(r["reading_at"]))

    # Find readings at or after bp_end (for the "current" register)
    after_end = [r for r in readings if db.parse_iso(r["reading_at"]) >= bp_end]
    # Find readings at or before bp_start (for the "prior" register): the
    # reading taken at the period boundary opens the period's consumption.
    before_start = [r for r in readings if db.parse_iso(r["reading_at"]) <= bp_start]

    if after_end:
        current_register = after_end[0]["kwh_register"]
    else:
        # Use latest available
        current_register = readings[-1]["kwh_register"]

    if before_start:
        prior_register = before_start[-1]["kwh_register"]
    else:
        prior_register = 0

    kwh = max(0, current_register - prior_register)

    # Demand: max demand_kw from readings in [bp_start, bp_end)
    in_period = [r for r in readings
                 if bp_start <= db.parse_iso(r["reading_at"]) < bp_end]
    if in_period:
        demand = max(r.get("demand_kw", 0) for r in in_period)
    elif readings:
        demand = max(r.get("demand_kw", 0) for r in readings)
    else:
        demand = 0

    # Apply rate-class floors
    if loc["rate_class"] == "IRRIGATION":
        demand = max(demand, 5.0)
    elif loc["rate_class"] == "COMMERCIAL_DEMAND":
        # Ratchet: max(period peak, 0.85 * max billed demand over prior 11 months)
        prior_finalized = [
            i for i in store.invoices.values()
            if i.get("service_location_id") == loc["id"]
            and i.get("status") in ("FINALIZED", "PAID", "WRITTEN_OFF")
            and i["id"] != inv["id"]
        ]
        if prior_finalized:
            max_prior_demand = max(p.get("demand_kw_billed", 0) for p in prior_finalized)
            ratchet = 0.85 * max_prior_demand
            demand = max(demand, ratchet)

    # Round demand to 0.01 kW precision
    demand = round(demand, 2)
    return kwh, demand


def _compute_energy_charge(schedule, kwh, loc, bp_start, bp_end):
    """Tiered energy charge per scaffold calculation rules."""
    if kwh <= 0:
        return 0

    tiers = schedule.get("tiers", [])
    remaining = kwh
    prev_bound = 0
    total_cents = 0

    for tier in tiers:
        if remaining <= 0:
            break
        up_to = tier.get("up_to_kwh")
        rate = tier.get("cents_per_kwh", 0)

        if up_to is None:
            take = remaining
        else:
            take = min(remaining, up_to - prev_bound)

        if take > 0:
            line = Decimal(str(take)) * Decimal(str(rate))
            line = line.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            total_cents += int(line)
            remaining -= take

        if up_to is not None:
            prev_bound = up_to

    # Irrigation offseason discount
    if loc["rate_class"] == "IRRIGATION":
        coop = _find_cooperative()
        if coop:
            month = bp_start.month
            start_m = coop.get("irrigation_season_start_month", 1)
            end_m = coop.get("irrigation_season_end_month", 12)
            in_season = _month_in_range(month, start_m, end_m)
            if not in_season:
                discount_pct = Decimal(str(schedule.get("irrigation_offseason_discount_pct", 0)))
                discount_factor = Decimal("1") - discount_pct
                total_cents = int(
                    (Decimal(str(total_cents)) * discount_factor).quantize(
                        Decimal("1"), rounding=ROUND_HALF_UP
                    )
                )

    return total_cents


def _month_in_range(month, start, end):
    """Check if month is in the inclusive [start, end] range, handling wrap-around."""
    if start <= end:
        return start <= month <= end
    else:
        return month >= start or month <= end


def _compute_demand_charge(schedule, demand_kw, loc, inv):
    """Compute demand charge in cents."""
    rate = schedule.get("demand_charge_cents_per_kw", 0)
    if rate == 0 or demand_kw <= 0:
        return 0
    charge = Decimal(str(demand_kw)) * Decimal(str(rate))
    return int(charge.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _compute_lm_credits(loc, bp_start, bp_end):
    """Compute load management credits for a billing period."""
    devices = [
        d for d in store.load_management_devices.values()
        if d.get("service_location_id") == loc["id"]
    ]
    if not devices:
        return 0

    period_days = max(1, (bp_end - bp_start).days)
    total_credit = 0

    for dev in devices:
        if dev["status"] != "ACTIVE":
            # Check for prorated credit (devices that were ACTIVE part of the period)
            if dev["status"] == "SUSPENDED" and dev.get("_active_since"):
                # Device was suspended mid-period; prorate
                active_since = db.parse_iso(dev["_active_since"])
                active_end = db.parse_iso(dev.get("_suspended_at", db.iso_logical(bp_end)))
                overlap_start = max(active_since, bp_start)
                overlap_end = min(active_end, bp_end)
                if overlap_start < overlap_end:
                    active_days = (overlap_end - overlap_start).days
                    monthly = dev.get("monthly_credit_cents", 0)
                    credit = int(monthly * active_days / period_days)
                    total_credit += credit
            continue

        # Full-period credit
        monthly = dev.get("monthly_credit_cents", 0)
        total_credit += monthly

    return total_credit


def finalize_invoice(inv_id):
    inv = get_invoice(inv_id)
    if inv["status"] != "PROVISIONAL":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice must be PROVISIONAL to finalize")

    loc = store.service_locations[inv["service_location_id"]]
    bp_end = db.parse_iso(inv["billing_period_end"])

    # Check: MeterReading with reading_at >= billing_period_end
    readings = [
        r for r in store.meter_readings.values()
        if r.get("service_location_id") == loc["id"]
        and db.parse_iso(r["reading_at"]) >= bp_end
    ]
    if not readings:
        raise ApiError("ERR_READING_MISSING", 409,
                       "No MeterReading at or after billing_period_end")

    # Recompute with FINAL variant
    inv["variant"] = "FINAL"
    compute_invoice_fields(inv, provisional=False)
    inv["status"] = "FINALIZED"
    touch(inv)

    # Feed patronage ledgers
    member = store.members.get(loc["member_id"])
    if member:
        kwh = inv.get("kwh_billed", 0)
        if loc["rate_class"] == "IRRIGATION":
            member["patronage_base_irrigation_kwh"] = member.get("patronage_base_irrigation_kwh", 0) + kwh
        else:
            member["patronage_base_kwh"] = member.get("patronage_base_kwh", 0) + kwh
        touch(member)

    return inv


def pay_invoice(inv_id):
    inv = get_invoice(inv_id)
    if inv["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice must be FINALIZED to pay")
    inv["status"] = "PAID"
    touch(inv)
    return inv


def write_off_invoice(inv_id):
    inv = get_invoice(inv_id)
    if inv["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice must be FINALIZED to write off")

    # Check: billing_period_end more than 180 days in the past
    bp_end = db.parse_iso(inv["billing_period_end"])
    now = db.logical_now()
    days_old = (now - bp_end).days
    if days_old <= 180:
        raise ApiError("ERR_WRITE_OFF_TOO_EARLY", 409,
                       "billing_period_end not yet 180 days in the past")

    inv["status"] = "WRITTEN_OFF"
    touch(inv)

    # Back out patronage
    loc = store.service_locations.get(inv["service_location_id"])
    if loc:
        member = store.members.get(loc["member_id"])
        if member:
            kwh = inv.get("kwh_billed", 0)
            if loc["rate_class"] == "IRRIGATION":
                member["patronage_base_irrigation_kwh"] = max(
                    0, member.get("patronage_base_irrigation_kwh", 0) - kwh
                )
            else:
                member["patronage_base_kwh"] = max(
                    0, member.get("patronage_base_kwh", 0) - kwh
                )
            touch(member)

    return inv


def void_invoice(inv_id):
    inv = get_invoice(inv_id)
    if inv["status"] != "PROVISIONAL":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice must be PROVISIONAL to void")
    inv["status"] = "VOID"
    touch(inv)
    return inv


def _find_cooperative():
    """Find the first cooperative (single-coop model for this API)."""
    for coop in store.cooperatives.values():
        return coop
    return None
