"""Shared business logic: serializers, calculations, events, time sweep."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g

import db
from response import ts

# --- package formats ---------------------------------------------------------
UNIT_LITERS = {
    "CAN_12OZ": Decimal("0.355"),
    "CAN_16OZ": Decimal("0.473"),
    "BOTTLE_500ML": Decimal("0.500"),
    "BOTTLE_750ML": Decimal("0.750"),
    "KEG_5GAL": Decimal("18.927"),
    "KEG_15_5GAL": Decimal("58.674"),
}

PACKAGE_FORMATS = set(UNIT_LITERS.keys())
EXCISE_RATE_CENTS_PER_LITER = Decimal("22.6")

MARKETS = {"FEDERAL_TTB", "NY_SLA", "VT_DLL", "MA_ABCC"}
# destination state -> regulator market for order label gates
STATE_TO_MARKET = {"NY": "NY_SLA", "VT": "VT_DLL", "MA": "MA_ABCC"}

TANK_MATERIALS = {"STAINLESS", "OAK", "CONCRETE", "PLASTIC"}
YEAST_KINDS = {"CULTURED", "WILD", "MIXED"}
PRODUCT_STYLES = {"DRY", "SEMI_DRY", "SWEET", "HOPPED", "FRUIT_INFUSED"}
LICENSE_KINDS = {
    "TTB_BREWERS_NOTICE",
    "NY_FARM_CIDERY",
    "VT_MANUFACTURER",
    "MA_FARMER_WINERY",
    "INTERSTATE_SHIPPER",
}
ORDER_CHANNELS = {"TASTING_ROOM", "CLUB_SUBSCRIPTION", "WHOLESALE_DISTRIBUTION"}
INTERSTATE_CHANNELS = {"CLUB_SUBSCRIPTION", "WHOLESALE_DISTRIBUTION"}
REGULATORS = {"TTB", "NY_SLA", "VT_DLL", "MA_ABCC"}


# --- decimal helpers ----------------------------------------------------------
def _d(x):
    return Decimal(str(x))


def q2(x):
    return _d(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q3(x):
    return _d(x).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def q1(x):
    return _d(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def q0(x):
    return int(_d(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fnum(dec):
    """Serialize a Decimal as a JSON number."""
    return float(dec)


# --- compliance events ---------------------------------------------------------
def emit_event(entity_type, entity_id, action, before, after):
    ev = {}
    db.stamp_new(ev, common=False)
    ev.update(
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_role": getattr(g, "role", None),
            "actor_id": getattr(g, "user_id", None),
            "action": action,
            "before_snapshot": before or {},
            "after_snapshot": after or {},
            "event_at": db.now(),
        }
    )
    db.store["compliance_events"][ev["id"]] = ev
    return ev


# --- shared computed state ------------------------------------------------------
def recompute_contract_received(contract):
    """received_weight_lbs = sum of weight over lots in RECEIVED /
    PARTIALLY_PRESSED / PRESSED (SPOILED excluded). Bumps only on change."""
    total = sum(
        lot["weight_lbs"]
        for lot in db.store["harvest_lots"].values()
        if lot["contract_id"] == contract["id"]
        and lot["status"] in ("RECEIVED", "PARTIALLY_PRESSED", "PRESSED")
    )
    if contract["received_weight_lbs"] != total:
        contract["received_weight_lbs"] = total
        db.bump(contract)


def lot_status_from_pressed(lot):
    if lot["pressed_weight_lbs"] <= 0:
        return "RECEIVED"
    if lot["pressed_weight_lbs"] >= lot["weight_lbs"]:
        return "PRESSED"
    return "PARTIALLY_PRESSED"


def expired(record):
    """An expiry is in force once the logical clock has passed expires_at."""
    exp = record.get("expires_at")
    return exp is not None and exp < db.now()


def time_sweep():
    """Runs when the logical clock is advanced: auto-expiry of licenses and
    non-federal label approvals (cancelling SCHEDULED runs that reference
    them), and REINSTATED -> ACTIVE licenses at the next ops run."""
    now = db.now()
    for lic in db.store["licenses"].values():
        if lic["status"] == "ACTIVE" and expired(lic):
            lic["status"] = "EXPIRED"
            db.bump(lic)
        elif lic["status"] == "REINSTATED":
            lic["status"] = "ACTIVE"
            db.bump(lic)
        # Calendar-year scoping of the volume tally (PRD 3.4): when the logical
        # clock stands in a different calendar year than the tally's, the new
        # year's accumulation starts from zero.
        vol_year = lic.get("_volume_year")
        if vol_year is not None and vol_year != now.year:
            lic["volume_used_liters"] = 0
            lic["_volume_year"] = now.year
            db.bump(lic)
    for la in db.store["label_approvals"].values():
        if (
            la["status"] == "APPROVED"
            and la["market"] != "FEDERAL_TTB"
            and expired(la)
        ):
            la["status"] = "EXPIRED"
            db.bump(la)
            for run in db.store["packaging_runs"].values():
                if run["label_approval_id"] == la["id"] and run["status"] == "SCHEDULED":
                    run["status"] = "CANCELLED"
                    db.bump(run)


# --- calculations ---------------------------------------------------------------
def compute_shortfall_penalty(contract, received_lbs):
    committed = contract["committed_weight_lbs"]
    rate = contract.get("shortfall_penalty_cents_per_lb", 0)
    shortfall = max(0, committed - received_lbs)
    free_allowance = (committed * 10) // 100  # floor(committed * 0.10)
    tier1 = (committed * 20) // 100           # floor(committed * 0.20)
    if shortfall <= free_allowance:
        return 0
    remaining = shortfall - free_allowance
    t1 = min(remaining, tier1)
    t2 = remaining - t1
    return t1 * rate + t2 * (2 * rate)


def compute_abv(original_gravity_brix, current_gravity_brix):
    return fnum(q1((_d(original_gravity_brix) - _d(current_gravity_brix)) * Decimal("0.55")))


def period_bounds(year, month):
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def recompute_excise_report(report):
    """Chronological replay of orders shipped in [period_start, period_end)
    with status SHIPPED / DELIVERED / RETURNED; returns subtract."""
    start, end = period_bounds(report["period_year"], report["period_month"])
    orders = [
        o
        for o in db.store["orders"].values()
        if o.get("shipped_at") is not None
        and start <= o["shipped_at"] < end
        and o["status"] in ("SHIPPED", "DELIVERED", "RETURNED")
    ]
    orders.sort(key=lambda o: (o["shipped_at"], o["created_at"], o["_seq"]))
    cents = 0
    liters = Decimal("0")
    for o in orders:
        sign = -1 if o["status"] == "RETURNED" else 1
        cents += sign * int(o.get("excise_tax_cents") or 0)
        run = db.store["packaging_runs"].get(o["packaging_run_id"])
        if run is not None:
            liters += sign * _d(o["units"]) * UNIT_LITERS[run["package_format"]]
    changed = False
    if report["taxable_cents"] != cents:
        report["taxable_cents"] = cents
        changed = True
    liters_int = q0(liters)
    if report["taxable_liters"] != liters_int:
        report["taxable_liters"] = liters_int
        changed = True
    if changed:
        db.bump(report)


def reports_covering(shipped_at):
    out = []
    for rep in db.store["excise_reports"].values():
        start, end = period_bounds(rep["period_year"], rep["period_month"])
        if start <= shipped_at < end:
            out.append(rep)
    return out


# --- serializers ------------------------------------------------------------------
def ser_variety(r):
    return {
        "id": r["id"],
        "code": r["code"],
        "tannin_g_per_l": r["tannin_g_per_l"],
        "brix_at_harvest": r["brix_at_harvest"],
        "acidity_g_per_l": r["acidity_g_per_l"],
        "is_bittersweet": r["is_bittersweet"],
        "created_at": ts(r["created_at"]),
    }


def ser_yeast(r):
    return {
        "id": r["id"],
        "code": r["code"],
        "kind": r["kind"],
        "attenuation_pct": r["attenuation_pct"],
        "temp_min_f": r["temp_min_f"],
        "temp_max_f": r["temp_max_f"],
        "nutrient_required": r["nutrient_required"],
        "created_at": ts(r["created_at"]),
    }


def ser_contract(r):
    return {
        "id": r["id"],
        "grower_name": r["grower_name"],
        "region_code": r["region_code"],
        "season_year": r["season_year"],
        "committed_weight_lbs": r["committed_weight_lbs"],
        "received_weight_lbs": r["received_weight_lbs"],
        "price_per_lb_cents": r["price_per_lb_cents"],
        "shortfall_penalty_cents_per_lb": r["shortfall_penalty_cents_per_lb"],
        "settlement_penalty_cents": r.get("settlement_penalty_cents"),
        "status": r["status"],
        "created_at": ts(r["created_at"]),
        "updated_at": ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_lot(r):
    return {
        "id": r["id"],
        "contract_id": r["contract_id"],
        "variety_id": r["variety_id"],
        "received_at": ts(r["received_at"]),
        "weight_lbs": r["weight_lbs"],
        "measured_brix": r["measured_brix"],
        "measured_tannin_g_per_l": r["measured_tannin_g_per_l"],
        "pressed_weight_lbs": r["pressed_weight_lbs"],
        "unpressed_weight_lbs": r["weight_lbs"] - r["pressed_weight_lbs"],
        "status": r["status"],
        "created_at": ts(r["created_at"]),
        "updated_at": ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_press_batch(r):
    return {
        "id": r["id"],
        "scheduled_press_date": ts(r["scheduled_press_date"]),
        "press_window_minutes": r["press_window_minutes"],
        "target_juice_liters": r["target_juice_liters"],
        "actual_juice_liters": r["actual_juice_liters"],
        "press_yield_ratio": r["press_yield_ratio"],
        "blend_brix": r["blend_brix"],
        "blend_tannin": r["blend_tannin"],
        "status": r["status"],
        "created_at": ts(r["created_at"]),
        "updated_at": ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_blend_line(r):
    return {
        "id": r["id"],
        "press_batch_id": r["press_batch_id"],
        "harvest_lot_id": r["harvest_lot_id"],
        "weight_lbs": r["weight_lbs"],
        "position": r["position"],
        "created_at": ts(r["created_at"]),
    }


def ser_tank(r):
    return {
        "id": r["id"],
        "code": r["code"],
        "capacity_liters": r["capacity_liters"],
        "material": r["material"],
        "temperature_controlled": r["temperature_controlled"],
        "status": r["status"],
        "current_batch_id": r["current_batch_id"],
        "created_at": ts(r["created_at"]),
        "updated_at": ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_fermentation_batch(r):
    return {
        "id": r["id"],
        "press_batch_id": r["press_batch_id"],
        "tank_id": r["tank_id"],
        "yeast_program_id": r["yeast_program_id"],
        "started_at": ts(r["started_at"]),
        "original_gravity_brix": r["original_gravity_brix"],
        "current_gravity_brix": r["current_gravity_brix"],
        "volume_liters": r["volume_liters"],
        "abv_pct": r["abv_pct"],
        "back_blend_source_batch_id": r["back_blend_source_batch_id"],
        "back_blend_pct": r["back_blend_pct"],
        "status": r["status"],
        "created_at": ts(r["created_at"]),
        "updated_at": ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_product(r):
    return {
        "id": r["id"],
        "sku": r["sku"],
        "name": r["name"],
        "style": r["style"],
        "target_abv_pct": r["target_abv_pct"],
        "abv_tolerance_pct": r["abv_tolerance_pct"],
        "vintage_year": r["vintage_year"],
        "status": r["status"],
        "created_at": ts(r["created_at"]),
        "updated_at": ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_label_approval(r):
    return {
        "id": r["id"],
        "product_id": r["product_id"],
        "market": r["market"],
        "application_number": r["application_number"],
        "submitted_at": ts(r["submitted_at"]),
        "approved_at": ts(r["approved_at"]),
        "expires_at": ts(r["expires_at"]),
        "status": r["status"],
        "created_at": ts(r["created_at"]),
        "updated_at": ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_license(r):
    return {
        "id": r["id"],
        "kind": r["kind"],
        "license_number": r["license_number"],
        "issued_at": ts(r["issued_at"]),
        "expires_at": ts(r["expires_at"]),
        "scope_states": r["scope_states"],
        "annual_volume_cap_liters": r["annual_volume_cap_liters"],
        "volume_used_liters": r["volume_used_liters"],
        "status": r["status"],
        "created_at": ts(r["created_at"]),
        "updated_at": ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_packaging_run(r):
    return {
        "id": r["id"],
        "product_id": r["product_id"],
        "fermentation_batch_id": r["fermentation_batch_id"],
        "package_format": r["package_format"],
        "units_produced": r["units_produced"],
        "volume_liters": r["volume_liters"],
        "label_approval_id": r["label_approval_id"],
        "license_id": r["license_id"],
        "packaged_at": ts(r["packaged_at"]),
        "status": r["status"],
        "created_at": ts(r["created_at"]),
        "updated_at": ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_order(r):
    return {
        "id": r["id"],
        "channel": r["channel"],
        "destination_state": r["destination_state"],
        "product_id": r["product_id"],
        "packaging_run_id": r["packaging_run_id"],
        "units": r["units"],
        "unit_price_cents": r["unit_price_cents"],
        "subtotal_cents": r["subtotal_cents"],
        "excise_tax_cents": r["excise_tax_cents"],
        "total_cents": r["total_cents"],
        "shipped_at": ts(r["shipped_at"]),
        "status": r["status"],
        "created_at": ts(r["created_at"]),
        "updated_at": ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_excise_report(r):
    return {
        "id": r["id"],
        "period_year": r["period_year"],
        "period_month": r["period_month"],
        "regulator": r["regulator"],
        "taxable_liters": r["taxable_liters"],
        "taxable_cents": r["taxable_cents"],
        "filed_at": ts(r["filed_at"]),
        "status": r["status"],
        "created_at": ts(r["created_at"]),
        "updated_at": ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_compliance_event(r):
    return {
        "id": r["id"],
        "entity_type": r["entity_type"],
        "entity_id": r["entity_id"],
        "actor_role": r["actor_role"],
        "actor_id": r["actor_id"],
        "action": r["action"],
        "before_snapshot": r["before_snapshot"],
        "after_snapshot": r["after_snapshot"],
        "event_at": ts(r["event_at"]),
        "created_at": ts(r["created_at"]),
    }
