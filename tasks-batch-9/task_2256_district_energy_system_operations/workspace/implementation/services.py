"""Lookups, cascades and the derived-counter bookkeeping shared by the routes."""

import calc
from calc import D, r2
from db import creation_order, store, touch
from errors import fail

# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
NOT_FOUND = {
    "loops": "ERR_LOOP_NOT_FOUND",
    "segments": "ERR_SEGMENT_NOT_FOUND",
    "fuel_contracts": "ERR_FUEL_CONTRACT_NOT_FOUND",
    "assets": "ERR_ASSET_NOT_FOUND",
    "forecasts": "ERR_FORECAST_NOT_FOUND",
    "plans": "ERR_PLAN_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "rate_schedules": "ERR_RATE_SCHEDULE_NOT_FOUND",
    "agreements": "ERR_AGREEMENT_NOT_FOUND",
    "points": "ERR_METERING_POINT_NOT_FOUND",
    "readings": "ERR_READING_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
    "work_orders": "ERR_WORK_ORDER_NOT_FOUND",
    "projects": "ERR_PROJECT_NOT_FOUND",
}


def collection(name):
    return getattr(store, name)


def path_get(name, key):
    """Admission ladder step 4: resolve a path identifier or raise its 404."""
    record = collection(name).get(key)
    if record is None:
        fail(NOT_FOUND[name], "%s '%s' does not exist" % (name[:-1], key))
    return record


def fk_get(name, key):
    """Admission ladder step 5: resolve a body foreign key or ERR_FK_NOT_FOUND."""
    record = collection(name).get(key)
    if record is None:
        fail("ERR_FK_NOT_FOUND", "referenced %s '%s' does not exist" % (name[:-1], key))
    return record


def rows(name):
    return creation_order(list(collection(name).values()))


def where(name, **filters):
    result = []
    for record in rows(name):
        keep = True
        for field in filters:
            if record.get(field) != filters[field]:
                keep = False
                break
        if keep:
            result.append(record)
    return result


def require_unique_code(name, field, value, **scope):
    for record in collection(name).values():
        if record.get(field) != value:
            continue
        matched = True
        for key in scope:
            if record.get(key) != scope[key]:
                matched = False
                break
        if matched:
            fail("ERR_DUPLICATE_CODE", "%s '%s' is already in use" % (field, value))


# ---------------------------------------------------------------------------
# Loop counters and posture
# ---------------------------------------------------------------------------
def add_committed_reserved(loop, delta):
    loop["committed_reserved_kw"] = float(r2(D(loop["committed_reserved_kw"]) + D(delta)))


def suspect_count(loop_id):
    total = 0
    for segment in store.segments.values():
        if segment["loop_id"] == loop_id and segment["condition"] == "SUSPECT":
            total += 1
    return total


# ---------------------------------------------------------------------------
# Fuel supply contract cascades (PRD 3.2)
# ---------------------------------------------------------------------------
def contract_assets(contract_id):
    return [a for a in rows("assets") if a.get("fuel_contract_id") == contract_id]


def plan_asset_ids(plan_id):
    return set(o["asset_id"] for o in store.orders.values() if o["plan_id"] == plan_id)


def cascade_contract_suspended(contract):
    contract["status"] = "SUSPENDED"
    touch(contract)

    cascaded = set()
    loop_order = []
    for asset in contract_assets(contract["id"]):
        if asset["availability_state"] != "AVAILABLE":
            continue
        asset["availability_state"] = "DERATED"
        touch(asset)
        cascaded.add(asset["id"])
        if asset["loop_id"] not in loop_order:
            loop_order.append(asset["loop_id"])

    for loop_id in loop_order:
        reverted = False
        for plan in where("plans", loop_id=loop_id, plan_state="APPROVED"):
            if not (plan_asset_ids(plan["id"]) & cascaded):
                continue
            plan["plan_state"] = "DRAFT"
            plan["reviewed_by_user_id"] = None
            touch(plan)
            reverted = True
        if not reverted:
            continue
        loop = store.loops.get(loop_id)
        if loop is not None and loop["posture"] == "NORMAL":
            loop["posture"] = "CONSTRAINED"
            touch(loop)


def cascade_contract_reinstated(contract):
    contract["status"] = "ACTIVE"
    touch(contract)
    for asset in contract_assets(contract["id"]):
        if asset["availability_state"] != "DERATED":
            continue
        asset["availability_state"] = "AVAILABLE"
        touch(asset)


def cascade_contract_expired(contract):
    contract["status"] = "EXPIRED"
    touch(contract)
    for asset in contract_assets(contract["id"]):
        if asset["availability_state"] == "OUTAGE":
            continue
        asset["availability_state"] = "OUTAGE"
        touch(asset)


# ---------------------------------------------------------------------------
# Dispatch plan helpers
# ---------------------------------------------------------------------------
NON_TERMINAL_PLAN_STATES = ("DRAFT", "SUBMITTED", "APPROVED")


def supersede_loop_plans(loop_id, exclude_id=None):
    for plan in rows("plans"):
        if plan["loop_id"] != loop_id or plan["id"] == exclude_id:
            continue
        if plan["plan_state"] not in NON_TERMINAL_PLAN_STATES:
            continue
        plan["plan_state"] = "SUPERSEDED"
        touch(plan)


def plan_orders(plan_id):
    return creation_order([o for o in store.orders.values() if o["plan_id"] == plan_id])


def eligible_assets(loop_id):
    result = []
    for asset in rows("assets"):
        if asset["loop_id"] != loop_id:
            continue
        if asset["availability_state"] not in ("AVAILABLE", "DERATED"):
            continue
        contract_id = asset.get("fuel_contract_id")
        if contract_id is not None:
            contract = store.fuel_contracts.get(contract_id)
            if contract is None or contract["status"] not in ("ACTIVE", "SUSPENDED"):
                continue
        result.append(asset)
    return result


def fuel_key(asset):
    contract_id = asset.get("fuel_contract_id")
    if contract_id is None:
        return "STORAGE"
    contract = store.fuel_contracts.get(contract_id)
    if contract is None:
        return "STORAGE"
    return contract["fuel_type"]


# ---------------------------------------------------------------------------
# Connection agreement cascades (PRD 3.5)
# ---------------------------------------------------------------------------
def cascade_agreement_terminated(agreement):
    """Everything the TERMINATED edge does besides setting contract_state."""
    for point in rows("points"):
        if point["agreement_id"] != agreement["id"]:
            continue
        if point["meter_state"] not in ("INSTALLED", "COMMISSIONED"):
            continue
        point["meter_state"] = "REMOVED"
        touch(point)
    if agreement["billing_state"] == "IN_ARREARS":
        agreement["billing_state"] = "WRITTEN_OFF"
        touch(agreement)


# ---------------------------------------------------------------------------
# Invoice ledger (PRD 3.7)
# ---------------------------------------------------------------------------
def agreement_invoices(agreement_id, states):
    return [i for i in rows("invoices")
            if i["agreement_id"] == agreement_id and i["invoice_state"] in states]


def recompute_balance(agreement):
    ledger = agreement_invoices(agreement["id"], ("ISSUED", "ADJUSTED"))
    agreement["balance_due"] = calc.agreement_balance(ledger)
    return D(agreement["balance_due"])


def enter_arrears_if_needed(agreement, balance):
    if agreement["billing_state"] == "CURRENT" and balance > calc.ARREARS_THRESHOLD_AMOUNT:
        agreement["billing_state"] = "IN_ARREARS"


def exit_arrears_if_needed(agreement, balance):
    if agreement["billing_state"] == "IN_ARREARS" and balance <= calc.ARREARS_THRESHOLD_AMOUNT:
        agreement["billing_state"] = "CURRENT"


def agreement_points(agreement_id, states):
    return [p for p in rows("points")
            if p["agreement_id"] == agreement_id and p["meter_state"] in states]


def determinant_readings(agreement, period_start, period_end, variant):
    """The admitted register-read set, ordered read_at ASC then created_at ASC."""
    points = agreement_points(agreement["id"], ("COMMISSIONED", "REMOVED"))
    point_ids = dict((p["id"], p) for p in points)
    admitted = []
    for reading in store.readings.values():
        if reading["point_id"] not in point_ids:
            continue
        if variant == "ACTUAL_TRUE_UP" and reading["read_type"] != "ACTUAL":
            continue
        moment = reading["_read_at"]
        if moment < period_start or moment >= period_end:
            continue
        admitted.append(reading)
    admitted.sort(key=lambda r: (r["_read_at"], r["created_at"], r["_seq"]))
    return admitted, point_ids


def period_hours(period_start, period_end):
    return int((period_end - period_start).total_seconds() // 3600)


def run_determinants(agreement, invoice_period_start, invoice_period_end, variant):
    readings, points = determinant_readings(
        agreement, invoice_period_start, invoice_period_end, variant)
    if len(readings) < 2:
        fail("ERR_INSUFFICIENT_METER_DATA",
             "the billing period admits fewer than two register reads")
    return calc.invoice_billing_determinants(
        agreement, store.rate_schedules[agreement["rate_schedule_id"]], variant,
        readings, points, period_hours(invoice_period_start, invoice_period_end))


# ---------------------------------------------------------------------------
# Segment condition banding (PRD 3.8)
# ---------------------------------------------------------------------------
def apply_band(segment, score, loop):
    """Store a recomputed score and move the segment into the implied band."""
    band = calc.band_for_score(score)
    previous = segment["condition"]
    segment["leak_risk_score"] = float(score)
    segment["condition"] = band
    touch(segment)
    was_suspect = previous == "SUSPECT"
    is_suspect = band == "SUSPECT"
    if was_suspect == is_suspect or loop is None:
        return
    delta = 1 if is_suspect else -1
    loop["suspect_segment_count"] = loop["suspect_segment_count"] + delta
    touch(loop)
