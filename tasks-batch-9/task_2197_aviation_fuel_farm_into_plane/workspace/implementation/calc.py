"""All derived figures, calculations and recompute passes."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from core import D, q2, q4, q5, cents, f2, f4, db, now, now_iso, fmt_dt, parse_dt

REF_TEMP = D("15.0")
ALPHA_HEAVY = D("0.000850")
ALPHA_MID = D("0.000900")
ALPHA_LIGHT = D("0.000950")
WATER_CAP_FRACTION = D("0.005")

ELEMENT_LITERS_LIFE = D("4000000.0")
ELEMENT_DAYS_LIFE = D("365")
ELEMENT_MAX_DP_KPA = D("103.0")

ORDER_OPEN_STATES = ("AUTHORIZED", "ASSIGNED", "FUELING")


def alpha_for(density):
    d = D(density)
    if d >= D("800.0"):
        return ALPHA_HEAVY
    if d >= D("780.0"):
        return ALPHA_MID
    return ALPHA_LIGHT


def vcf_for(density, temperature_c):
    """Volume correction factor, rounded to 5 decimals BEFORE use as a multiplier."""
    alpha = alpha_for(density)
    return q5(D(1) - alpha * (D(temperature_c) - REF_TEMP))


# ------------------------------------------------------------- receipt volumes
def receipt_volumes(delivery_mode, meter_gross, open_gauge, close_gauge,
                    temperature_c, cert_density, measured_water):
    vcf = vcf_for(cert_density, temperature_c)
    gauge_delta = q2(D(close_gauge) - D(open_gauge))
    meter = D(meter_gross)
    if delivery_mode == "TRUCK":
        governing, advisory = meter, gauge_delta
    else:
        governing, advisory = gauge_delta, meter
    water = D(measured_water)

    corrected = q2(governing * vcf)
    cap = q2(governing * WATER_CAP_FRACTION)
    net = q2(corrected - min(water, cap))

    adv_corrected = q2(advisory * vcf)
    adv_cap = q2(advisory * WATER_CAP_FRACTION)
    adv_net = q2(adv_corrected - min(water, adv_cap))
    return {
        "governing_gross_liters": f2(governing),
        "advisory_gross_liters": f2(advisory),
        "net_volume_liters": f2(net),
        "advisory_net_volume_liters": f2(adv_net),
    }


# ------------------------------------------------------------- sample verdict
METRIC_ORDER = [
    "water_reaction_rating", "particulate_mg_per_l", "conductivity_ps_per_m",
    "observed_density_kg_per_m3", "flash_point_c",
]


def sample_verdict(sample, comparison_density):
    failed = []
    v = sample.get("water_reaction_rating")
    if v is not None and D(v) > D(1):
        failed.append("water_reaction_rating")
    v = sample.get("particulate_mg_per_l")
    if v is not None and D(v) > D("1.0"):
        failed.append("particulate_mg_per_l")
    v = sample.get("conductivity_ps_per_m")
    if v is not None and not (D("50.0") <= D(v) <= D("600.0")):
        failed.append("conductivity_ps_per_m")
    v = sample.get("observed_density_kg_per_m3")
    if v is not None and comparison_density is not None and \
            abs(D(v) - D(comparison_density)) > D("3.0"):
        failed.append("observed_density_kg_per_m3")
    v = sample.get("flash_point_c")
    if v is not None and D(v) < D("38.0"):
        failed.append("flash_point_c")
    ordered = [m for m in METRIC_ORDER if m in failed]
    return ("PASS" if not ordered else "FAIL"), ordered


# ------------------------------------------------------------- collection scans
def farm_tanks(farm_id):
    return [t for t in db.tanks.values() if t["fuel_farm_id"] == farm_id]


def farm_assets(farm_id):
    return [a for a in db.assets.values() if a["fuel_farm_id"] == farm_id]


def farm_spills(farm_id):
    return [s for s in db.spills.values() if s["fuel_farm_id"] == farm_id]


def farm_permits(farm_id):
    return [p for p in db.permits.values() if p["fuel_farm_id"] == farm_id]


def tank_receipts(tank_id):
    return [r for r in db.receipts.values() if r["storage_tank_id"] == tank_id]


def tank_uplifts(tank_id):
    return [u for u in db.uplifts.values() if u["storage_tank_id"] == tank_id]


def tank_orders(tank_id):
    return [o for o in db.orders.values() if o["storage_tank_id"] == tank_id]


def order_uplifts(order_id):
    return [u for u in db.uplifts.values() if u["fueling_order_id"] == order_id]


def order_account_id(order):
    flight = db.flights.get(order.get("flight_id"))
    return flight["airline_account_id"] if flight else None


def account_uplifts(account_id):
    out = []
    for u in db.uplifts.values():
        o = db.orders.get(u["fueling_order_id"])
        if o and order_account_id(o) == account_id:
            out.append(u)
    return out


def account_orders(account_id):
    return [o for o in db.orders.values() if order_account_id(o) == account_id]


def account_invoices(account_id):
    return [i for i in db.invoices.values() if i["airline_account_id"] == account_id]


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ------------------------------------------------------------- governing permit
def governing_permit(farm_id):
    perms = farm_permits(farm_id)
    if not perms:
        return None
    def key(p):
        vf = parse_dt(p["valid_from_utc"])
        return (vf, p["created_at"], p["_seq"])
    perms.sort(key=key)
    best = perms[-1]
    latest_vf = parse_dt(best["valid_from_utc"])
    tied = [p for p in perms if parse_dt(p["valid_from_utc"]) == latest_vf]
    tied.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return tied[0]


def expire_permits(farm_id):
    """Lazy ACTIVE -> EXPIRED for the farm's permits against the logical clock."""
    clock = now()
    for p in farm_permits(farm_id):
        if p["status"] == "ACTIVE" and clock >= parse_dt(p["valid_until_utc"]):
            p["status"] = "EXPIRED"
            p["version"] = p["version"] + 1
            p["updated_at"] = now_iso()


def permit_satisfactory(permit):
    if permit is None or permit["status"] != "ACTIVE":
        return False
    clock = now()
    return parse_dt(permit["valid_from_utc"]) <= clock < parse_dt(permit["valid_until_utc"])


# ------------------------------------------------------------- permit throughput
def permit_day_throughput(farm_id):
    clock = now()
    day_start = clock.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(hours=24)
    total = D(0)
    for r in db.receipts.values():
        tank = db.tanks.get(r["storage_tank_id"])
        if not tank or tank["fuel_farm_id"] != farm_id:
            continue
        if r["status"] != "RELEASED" or not r.get("released_at_utc"):
            continue
        rel = parse_dt(r["released_at_utc"])
        if day_start <= rel < day_end:
            total += D(r["net_volume_liters"])
    for u in db.uplifts.values():
        tank = db.tanks.get(u["storage_tank_id"])
        if not tank or tank["fuel_farm_id"] != farm_id:
            continue
        if u["status"] not in ("POSTED", "BILLED"):
            continue
        cr = parse_dt(u["created_at"])
        if day_start <= cr < day_end:
            total += D(u["net_liters"])
    return q2(total)


# ------------------------------------------------------------- tank ledger
def tank_adjustment_total(tank_id):
    total = D(0)
    for run in db.runs.values():
        if run["status"] != "POSTED":
            continue
        for m in run.get("tank_measurements") or []:
            if m.get("storage_tank_id") == tank_id and m.get("adjustment_liters") is not None:
                total += D(m["adjustment_liters"])
    return total


def recompute_tank(tank):
    farm = db.farms.get(tank["fuel_farm_id"])
    unpumpable = D(farm["unpumpable_bottom_liters"]) if farm else D(0)
    book = D(tank["opening_volume_liters"])
    for r in tank_receipts(tank["id"]):
        if r["status"] == "RELEASED":
            book += D(r["net_volume_liters"])
    for u in tank_uplifts(tank["id"]):
        if u["status"] in ("POSTED", "BILLED"):
            book -= D(u["net_liters"])
    book += tank_adjustment_total(tank["id"])
    book = q2(book)
    reserved = D(0)
    for o in tank_orders(tank["id"]):
        if o["status"] in ORDER_OPEN_STATES:
            reserved += D(o["requested_uplift_liters"])
    reserved = q2(reserved)
    available = q2(book - reserved - unpumpable)
    if available < 0:
        available = D("0.00")
    if tank["service_status"] == "ISOLATED":
        available = D("0.00")
    tank["book_volume_liters"] = f2(book)
    tank["reserved_volume_liters"] = f2(reserved)
    tank["available_volume_liters"] = f2(available)
    return tank


# ------------------------------------------------------------- asset figures
def recompute_onboard(asset):
    if asset["asset_type"] == "HYDRANT_CART":
        asset["onboard_volume_liters"] = 0.0
        return asset
    total = D(0)
    for u in db.uplifts.values():
        if u["status"] != "POSTED":
            continue
        o = db.orders.get(u["fueling_order_id"])
        if not o or o["status"] != "FUELING":
            continue
        if o["delivery_mode"] != "TRUCK" or o.get("fueling_asset_id") != asset["id"]:
            continue
        total += D(u["net_liters"])
    asset["onboard_volume_liters"] = f2(total)
    return asset


def element_life_pct(asset):
    throughput_pct = q4(D(asset["liters_since_filter_change"]) / ELEMENT_LITERS_LIFE * D(100))
    last = parse_dt(asset["last_filter_change_at_utc"]) if asset.get("last_filter_change_at_utc") else None
    if last is None:
        days = 0
    else:
        delta = now() - last
        days = delta.days if delta.total_seconds() >= 0 else 0
        if days < 0:
            days = 0
    days_pct = q4(D(days) / ELEMENT_DAYS_LIFE * D(100))
    dp_pct = q4(D(asset["differential_pressure_kpa"]) / ELEMENT_MAX_DP_KPA * D(100))
    return max(throughput_pct, days_pct, dp_pct)


def reliability_score(asset):
    # PRD: "only incidents that have actually reached `CONTAINED` are applied — an incident
    # still in `REPORTED` or `ESCALATED` has had no effect on the score yet." `REMEDIATED` and
    # `CLOSED` sit downstream of containment, so those incidents have reached it and keep their
    # penalty: closing the file is paperwork, not repair.
    reached_containment = ("CONTAINED", "REMEDIATED", "CLOSED")
    incidents = [s for s in db.spills.values()
                 if s.get("fueling_asset_id") == asset["id"]
                 and s["status"] in reached_containment]
    incidents.sort(key=lambda s: (s["reported_at_utc"], s["created_at"], s["_seq"]))
    score = 100
    for s in incidents:
        steps = int(D(s["spilled_volume_liters"]).__truediv__(D("10.0")).to_integral_value(rounding=ROUND_CEILING))
        severity = min(40, steps * 5)
        mult = 2 if s["surface"] in ("STORM_DRAIN", "UNSEALED_GROUND") else 1
        penalty = min(40, severity * mult)
        score = max(0, score - penalty)
    return score


def recompute_asset(asset, auto_status=True):
    recompute_onboard(asset)
    asset["element_life_pct"] = f4(element_life_pct(asset))
    asset["reliability_score"] = reliability_score(asset)
    if auto_status:
        apply_asset_auto_status(asset)
    return asset


def apply_asset_auto_status(asset):
    life = D(str(asset["element_life_pct"]))
    dp = D(asset["differential_pressure_kpa"])
    if dp >= ELEMENT_MAX_DP_KPA and asset["status"] in ("IN_SERVICE", "FILTER_DUE"):
        asset["status"] = "DOWN_FOR_FILTER"
        return
    if asset["reliability_score"] < 60 and asset["status"] == "IN_SERVICE":
        asset["status"] = "DOWN_MAINTENANCE"
        return
    if life >= D("100.0") and asset["status"] == "IN_SERVICE":
        asset["status"] = "FILTER_DUE"


# ------------------------------------------------------------- farm posture
def recompute_farm(farm):
    farm_id = farm["id"]
    expire_permits(farm_id)
    permit = governing_permit(farm_id)
    ok_permit = permit_satisfactory(permit)

    farm["active_permit_throughput_used_liters"] = f2(permit_day_throughput(farm_id))
    assets = farm_assets(farm_id)
    farm["in_service_asset_count"] = sum(1 for a in assets if a["status"] == "IN_SERVICE")
    spills = farm_spills(farm_id)
    farm["open_spill_count"] = sum(1 for s in spills if s["status"] in ("REPORTED", "ESCALATED"))

    frozen = (not ok_permit) or any(s["status"] == "ESCALATED" for s in spills)
    restricted = False
    if any(t["quality_status"] == "QUARANTINED" for t in farm_tanks(farm_id)):
        restricted = True
    if any(s["status"] == "REPORTED" for s in spills):
        restricted = True
    if permit is not None:
        used = D(str(farm["active_permit_throughput_used_liters"]))
        if used >= D("0.90") * D(permit["max_daily_throughput_liters"]):
            restricted = True
    if farm["in_service_asset_count"] == 0:
        restricted = True

    farm["posture"] = "FROZEN" if frozen else ("RESTRICTED" if restricted else "OPEN")
    return farm


# ------------------------------------------------------------- pricing
def month_start(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_to_date_liters(account_id, upto_created_at, upto_seq):
    """Sum net_liters of POSTED/BILLED tickets of the account in the calendar UTC month
    of upto_created_at, up to and including (created_at, seq)."""
    ms = month_start(parse_dt(upto_created_at))
    total = D(0)
    for u in account_uplifts(account_id):
        if u["status"] not in ("POSTED", "BILLED"):
            continue
        cr = parse_dt(u["created_at"])
        if cr < ms:
            continue
        if (u["created_at"], u["_seq"]) > (upto_created_at, upto_seq):
            continue
        total += D(u["net_liters"])
    return total


def tier_diff(cumulative):
    c = D(cumulative)
    if c >= D("500000.0"):
        return D("1.60")
    if c >= D("100000.0"):
        return D("2.40")
    return D("3.20")


def price_uplift(uplift, account):
    """Price a POSTED uplift ticket; writes the pricing fields onto the row."""
    net = D(uplift["net_liters"])
    cumulative = month_to_date_liters(account["id"], uplift["created_at"], uplift["_seq"])
    diff = tier_diff(cumulative)
    base = D(account["base_price_cents_per_liter"])

    fuel_component = cents(net * (base + diff))
    into_plane = max(2500, cents(net * D("0.45")))
    flowage = cents(net * D("0.12"))
    if account.get("tax_exempt"):
        excise = 0
        sales_tax = 0
    else:
        excise = cents(net * D("1.14"))
        sales_tax = cents(D(fuel_component + into_plane) * D("0.0725"))
    billed = fuel_component + into_plane + flowage + excise + sales_tax
    if account["contract_type"] == "INTO_PLANE_ONLY":
        fuel_component = 0
        billed = into_plane + flowage

    uplift["volume_tier_diff_cents_per_liter"] = float(diff)
    uplift["fuel_component_cents"] = fuel_component
    uplift["billed_line_cents"] = billed
    return uplift


def reservation_amount(account, requested_liters):
    req = D(requested_liters)
    mtd = D(0)
    clock_iso = now_iso()
    ms = month_start(now())
    for u in account_uplifts(account["id"]):
        if u["status"] not in ("POSTED", "BILLED"):
            continue
        cr = parse_dt(u["created_at"])
        if ms <= cr <= now():
            mtd += D(u["net_liters"])
    diff = tier_diff(mtd + req)
    base = D(account["base_price_cents_per_liter"])
    return cents(req * (base + diff)) + max(2500, cents(req * D("0.45")))


# ------------------------------------------------------------- exposures
def recompute_exposure(account):
    invoiced = 0
    for inv in account_invoices(account["id"]):
        if inv["status"] in ("ISSUED", "DISPUTED"):
            invoiced += int(inv["total_cents"]) - int(inv["amount_paid_cents"])
    uncollected = 0
    for u in account_uplifts(account["id"]):
        if u["status"] == "POSTED" and u.get("billed_line_cents") is not None:
            uncollected += int(u["billed_line_cents"])
    reservation = 0
    for o in account_orders(account["id"]):
        if o["status"] in ORDER_OPEN_STATES:
            reservation += int(o["reserved_amount_cents"])
    account["invoiced_exposure_cents"] = invoiced
    account["accrual_exposure_cents"] = invoiced + uncollected + reservation
    return account


# ------------------------------------------------------------- invoice totals
def recompute_invoice_totals(invoice, tickets):
    swept_net = q2(sum((D(t["net_liters"]) for t in tickets), D(0)))
    fuel_component = sum(int(t["fuel_component_cents"] or 0) for t in tickets)
    subtotal = sum(int(t["billed_line_cents"] or 0) for t in tickets)
    if swept_net >= D("250000.0"):
        rate = D("0.015")
    elif swept_net >= D("100000.0"):
        rate = D("0.0075")
    else:
        rate = D(0)
    rebate = cents(D(fuel_component) * rate)
    admin = min(50000, cents(D(subtotal - rebate) * D("0.004")))
    invoice["swept_net_liters"] = f2(swept_net)
    invoice["fuel_component_cents"] = fuel_component
    invoice["subtotal_cents"] = subtotal
    invoice["volume_rebate_cents"] = rebate
    invoice["admin_fee_cents"] = admin
    invoice["total_cents"] = subtotal - rebate + admin
    return invoice


def invoice_tickets(invoice_id):
    return by_created([u for u in db.uplifts.values() if u.get("invoice_id") == invoice_id])


# ------------------------------------------------------------- authorization code
def mint_authorization(account, flight):
    dep = parse_dt(flight["scheduled_departure_utc"])
    prefix = account["airline_iata_code"]
    date_part = dep.strftime("%y%m%d")
    dep_day = dep.date()
    count = 0
    for a in db.authorizations.values():
        if a["airline_account_id"] != account["id"]:
            continue
        f = db.flights.get(a["flight_id"])
        if not f:
            continue
        if parse_dt(f["scheduled_departure_utc"]).date() == dep_day:
            count += 1
    day_sequence = count + 1
    body = prefix + date_part + ("%04d" % day_sequence)
    check = "%02d" % (sum(ord(c) for c in body) % 97)
    return body + check, day_sequence, fmt_dt(dep + timedelta(hours=2))
