import os
from flask import Flask, request

import errors
from errors import ApiError, err
from response import success, error_response, now_dt
from db import db, new_common, new_record, touch
from middleware import authenticate, require_role
from pagination import parse_pagination, paginate
import util
from util import parse_iso, parse_date
import serialize
import services
import calculations as calc

app = Flask(__name__)

ALL_ROLES = {"ParkManager", "Resident", "HousingAuthority"}


# ===========================================================================
# Error handling
# ===========================================================================

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}", 400)


def get_json():
    """Parse the request JSON body, defaulting to {} for empty bodies on action
    endpoints. Malformed JSON -> ERR_INVALID_REQUEST (PRD §2.6)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err(errors.ERR_INVALID_REQUEST, "Malformed JSON body.")
    if body is None:
        return {}
    return body


# ===========================================================================
# Existence helpers, clock
# ===========================================================================

def fetch_or_404(collection, rid, label="Resource"):
    rec = collection.get(rid)
    if rec is None:
        raise err(errors.ERR_NOT_FOUND, f"{label} not found.")
    return rec


def server_now():
    """The server's current instant for time-gated checks (PRD §2.9)."""
    if db.current_clock is not None:
        return parse_iso(db.current_clock)
    return now_dt()


def do_list(collection, serializer, filters=None):
    limit, offset = parse_pagination()
    items = list(collection.values())
    if filters:
        for field, value in filters.items():
            if value is not None:
                items = [r for r in items if r.get(field) == value]
    page, meta = paginate(items, limit, offset)
    return success([serializer(r) for r in page], status=200, pagination=meta)


# ===========================================================================
# Test clock
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = util.require_body(get_json())
    to_iso = util.req_datetime(body, "to_iso8601")
    db.current_clock = to_iso
    return success({}, status=200)


# ===========================================================================
# Community
# ===========================================================================

@app.route("/communities", methods=["POST"])
def create_community():
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = util.require_body(get_json())
    name = util.req_str(body, "name", 1, 1000)
    state_code = util.req_enum(body, "state_code", {"CA", "OR", "FL", "TX"})
    method = util.opt_enum(body, "utility_apportionment_method",
                           {"PER_CAPITA", "SUB_METER"}, "PER_CAPITA")

    rec = new_common()
    rec.update({
        "name": name,
        "state_code": state_code,
        "ownership_model": "PARK_OWNED",
        "utility_apportionment_method": method,
        "total_metered_units": 0,
    })
    db.communities[rec["id"]] = rec
    return success(serialize.community_out(rec), status=201)


@app.route("/communities/<cid>", methods=["GET"])
def get_community(cid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch_or_404(db.communities, cid, "Community")
    return success(serialize.community_out(rec), status=200)


# ===========================================================================
# Lot
# ===========================================================================

@app.route("/lots", methods=["POST"])
def create_lot():
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = util.require_body(get_json())
    # existence (priority 3) on community_id before further field validation.
    community = _existence_fk(body, "community_id", db.communities, "Community")
    lot_number = util.req_str(body, "lot_number", 1, 1000)
    base_rent = util.req_int(body, "base_rent_cents", 0)
    # duplicate lot_number within community (priority 6).
    for lot in db.lots.values():
        if lot["community_id"] == community["id"] and lot["lot_number"] == lot_number:
            raise err(errors.ERR_DUPLICATE_LOT_NUMBER,
                      "lot_number already used within the community.")

    rec = new_common()
    rec.update({
        "community_id": community["id"],
        "lot_number": lot_number,
        "base_rent_cents": base_rent,
        "status": "VACANT",
        "current_lease_id": None,
    })
    db.lots[rec["id"]] = rec
    return success(serialize.lot_out(rec), status=201)


@app.route("/lots/<lid>", methods=["GET"])
def get_lot(lid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch_or_404(db.lots, lid, "Lot")
    return success(serialize.lot_out(rec), status=200)


@app.route("/lots", methods=["GET"])
def list_lots():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return do_list(db.lots, serialize.lot_out, {
        "community_id": request.args.get("community_id"),
        "current_lease_id": request.args.get("current_lease_id"),
    })


# ===========================================================================
# Resident
# ===========================================================================

@app.route("/residents", methods=["POST"])
def create_resident():
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = util.require_body(get_json())
    community = _existence_fk(body, "community_id", db.communities, "Community")
    full_name = util.req_str(body, "full_name", 1, 1000)
    household_size = util.req_int(body, "household_size", 1)

    rec = new_common()
    rec.update({
        "community_id": community["id"],
        "full_name": full_name,
        "household_size": household_size,
        "standing": "GOOD",
    })
    db.residents[rec["id"]] = rec
    return success(serialize.resident_out(rec), status=201)


@app.route("/residents/<rid>", methods=["GET"])
def get_resident(rid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch_or_404(db.residents, rid, "Resident")
    return success(serialize.resident_out(rec), status=200)


@app.route("/residents", methods=["GET"])
def list_residents():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return do_list(db.residents, serialize.resident_out, {
        "community_id": request.args.get("community_id"),
    })


# ===========================================================================
# LotLease
# ===========================================================================

def _existence_fk(body, field, collection, label):
    """Resolve a required FK: if the field is present and a string, check its
    existence (priority 3, ERR_NOT_FOUND) BEFORE general body validation. If the
    field is absent / non-string, it's a body-validation problem deferred to the
    caller's own req_* validation — but since existence must precede
    invalid_request, we treat a present-but-unresolvable id as 404 and a
    missing/ill-typed id as 400 here."""
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a non-empty string.")
    rec = collection.get(v)
    if rec is None:
        raise err(errors.ERR_NOT_FOUND, f"{label} not found.")
    return rec


@app.route("/lot-leases", methods=["POST"])
def create_lease():
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = util.require_body(get_json())
    # existence left-to-right (priority 3): lot_id then resident_id, then the
    # optional supersedes_lease_id.
    lot = _existence_fk(body, "lot_id", db.lots, "Lot")
    resident = _existence_fk(body, "resident_id", db.residents, "Resident")
    supersedes_lease = None
    if body.get("supersedes_lease_id") is not None:
        supersedes_lease = _existence_fk(body, "supersedes_lease_id",
                                         db.lot_leases, "LotLease")
    # body validation (priority 4).
    start_date = util.req_iso_date(body, "start_date")
    expected_lot_version = util.opt_int(body, "expected_lot_version")
    # cross-community reference (priority 5): lot, resident (and superseded
    # lease's lot) must share a community.
    if lot["community_id"] != resident["community_id"]:
        raise err(errors.ERR_CROSS_COMMUNITY_REFERENCE,
                  "Lot and resident belong to different communities.")
    if supersedes_lease is not None:
        prior_lot = db.lots.get(supersedes_lease["lot_id"])
        if prior_lot is not None and prior_lot["community_id"] != lot["community_id"]:
            raise err(errors.ERR_CROSS_COMMUNITY_REFERENCE,
                      "Superseded lease is in a different community.")

    rec = new_common()
    rec.update({
        "lot_id": lot["id"],
        "resident_id": resident["id"],
        "supersedes_lease_id": supersedes_lease["id"] if supersedes_lease else None,
        "start_date": start_date,
        "rent_cents_at_signing": None,
        "status": "PENDING",
        "expected_lot_version": expected_lot_version,
    })
    db.lot_leases[rec["id"]] = rec
    return success(serialize.lease_out(rec), status=201)


@app.route("/lot-leases/<lid>", methods=["GET"])
def get_lease(lid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch_or_404(db.lot_leases, lid, "LotLease")
    return success(serialize.lease_out(rec), status=200)


@app.route("/lot-leases", methods=["GET"])
def list_leases():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return do_list(db.lot_leases, serialize.lease_out, {
        "lot_id": request.args.get("lot_id"),
        "resident_id": request.args.get("resident_id"),
        "supersedes_lease_id": request.args.get("supersedes_lease_id"),
    })


@app.route("/lot-leases/<lid>/activate", methods=["POST"])
def activate_lease(lid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = util.require_body(get_json())
    lease = fetch_or_404(db.lot_leases, lid, "LotLease")
    # body validation (priority 4): optional expected_lot_version override.
    body_expected_version = util.opt_int(body, "expected_lot_version")

    lot = db.lots.get(lease["lot_id"])
    if lot is None:
        raise err(errors.ERR_NOT_FOUND, "Lot not found.")

    # state (priority 7): the lease must be PENDING.
    if lease["status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Lease is not PENDING.")

    is_supersede = lease["supersedes_lease_id"] is not None

    if not is_supersede:
        # ---- first-occupancy activation ----
        # lot must be VACANT (priority 8).
        if lot["status"] != "VACANT":
            if lot["status"] == "FROZEN":
                raise err(errors.ERR_LOT_FROZEN,
                          "Lot is FROZEN by an open conversion vote.")
            raise err(errors.ERR_LOT_NOT_VACANT,
                      "First-occupancy activation requires a VACANT lot.")
        # lot must not be FROZEN (priority 9) — covered above for completeness.
        if lot["status"] == "FROZEN":
            raise err(errors.ERR_LOT_FROZEN,
                      "Lot is FROZEN by an open conversion vote.")

        rent_at_signing = services.current_rent_cents(lot)
        lease["status"] = "ACTIVE"
        lease["rent_cents_at_signing"] = rent_at_signing
        touch(lease)
        lot["status"] = "OCCUPIED"
        lot["current_lease_id"] = lease["id"]
        touch(lot)  # increments Lot.version
        # opening RENT_CHARGE ledger entry = rent_cents_at_signing.
        services.post_ledger_entry(lease, "RENT_CHARGE", rent_at_signing)
        return success(serialize.lease_out(lease), status=200)

    # ---- home-sale supersede activation ----
    # supersede requires the lot OCCUPIED and supersedes_lease_id ==
    # current_lease_id (priority 7, ERR_INVALID_STATE).
    if lot["status"] != "OCCUPIED" or lease["supersedes_lease_id"] != lot["current_lease_id"]:
        raise err(errors.ERR_INVALID_STATE,
                  "Supersede requires an OCCUPIED lot whose current lease matches "
                  "supersedes_lease_id.")
    prior_lease = db.lot_leases.get(lease["supersedes_lease_id"])
    if prior_lease is None or prior_lease["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Prior lease is not the lot's ACTIVE lease.")

    # blocked by an open eviction case on the prior lease (priority 10).
    for ec in db.eviction_cases.values():
        if ec["lease_id"] == prior_lease["id"] and ec["status"] == "NOTICE_SERVED":
            raise err(errors.ERR_EVICTION_IN_PROGRESS,
                      "An open eviction case blocks the home-sale supersede.")

    # OCC stale-version check (priority 18, ERR_STALE_LOT_VERSION / 412).
    expected = body_expected_version
    if expected is None:
        expected = lease.get("expected_lot_version")
    if expected != lot["version"]:
        raise err(errors.ERR_STALE_LOT_VERSION,
                  "expected_lot_version does not match the lot's current version.")

    rent_at_signing = services.current_rent_cents(lot)
    prior_lease["status"] = "TRANSFERRED"
    touch(prior_lease)
    lease["status"] = "ACTIVE"
    lease["rent_cents_at_signing"] = rent_at_signing
    touch(lease)
    lot["current_lease_id"] = lease["id"]
    touch(lot)  # increments Lot.version; lot stays OCCUPIED
    services.post_ledger_entry(lease, "RENT_CHARGE", rent_at_signing)
    return success(serialize.lease_out(lease), status=200)


@app.route("/lot-leases/<lid>/payments", methods=["POST"])
def post_payment(lid):
    user_id, role = authenticate()
    require_role(role, {"ParkManager", "Resident"})
    body = util.require_body(get_json())
    lease = fetch_or_404(db.lot_leases, lid, "LotLease")
    amount = util.req_int(body, "amount_cents", 1)
    # Resident ownership (PRD §2.1): a Resident may act only on its own lease.
    if role == "Resident" and lease["resident_id"] != user_id:
        raise err(errors.ERR_FORBIDDEN, "Resident may only pay on its own lease.")

    entry = services.post_ledger_entry(lease, "PAYMENT", -amount)

    # standing may revert to GOOD when arrears fall below threshold (PRD §3.6/§3.7).
    resident = db.residents.get(lease["resident_id"])
    if resident is not None and resident["standing"] == "DELINQUENT":
        if services.resident_arrears(resident["id"]) < calc.ARREARS_THRESHOLD_CENTS:
            resident["standing"] = "GOOD"
            touch(resident)
    return success(serialize.ledger_entry_out(entry), status=201)


# ===========================================================================
# RentSchedule
# ===========================================================================

@app.route("/rent-schedules", methods=["POST"])
def create_rent_schedule():
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = util.require_body(get_json())
    lot = _existence_fk(body, "lot_id", db.lots, "Lot")
    proposed = util.req_int(body, "proposed_rent_cents", 0)
    effective_date = util.req_iso_date(body, "effective_date")

    community = db.communities.get(lot["community_id"])
    prior = services.current_rent_cents(lot)
    new_rent, cap_applied = calc.capped_rent(prior, proposed, community["state_code"])

    rec = new_common()
    rec.update({
        "lot_id": lot["id"],
        "prior_rent_cents": prior,
        "proposed_rent_cents": proposed,
        "new_rent_cents": new_rent,
        "effective_date": effective_date,
        "cap_applied": cap_applied,
        "status": "PROPOSED",
    })
    db.rent_schedules[rec["id"]] = rec
    return success(serialize.rent_schedule_out(rec), status=201)


@app.route("/rent-schedules/<sid>", methods=["GET"])
def get_rent_schedule(sid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch_or_404(db.rent_schedules, sid, "RentSchedule")
    return success(serialize.rent_schedule_out(rec), status=200)


@app.route("/rent-schedules", methods=["GET"])
def list_rent_schedules():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return do_list(db.rent_schedules, serialize.rent_schedule_out, {
        "lot_id": request.args.get("lot_id"),
    })


@app.route("/rent-schedules/<sid>/accept", methods=["POST"])
def accept_rent_schedule(sid):
    _, role = authenticate()
    require_role(role, {"Resident"})
    rec = fetch_or_404(db.rent_schedules, sid, "RentSchedule")
    if rec["status"] != "PROPOSED":
        raise err(errors.ERR_INVALID_STATE, "RentSchedule is not PROPOSED.")
    rec["status"] = "ACCEPTED"
    touch(rec)
    return success(serialize.rent_schedule_out(rec), status=200)


@app.route("/rent-schedules/<sid>/contest", methods=["POST"])
def contest_rent_schedule(sid):
    _, role = authenticate()
    require_role(role, {"Resident"})
    rec = fetch_or_404(db.rent_schedules, sid, "RentSchedule")
    if rec["status"] != "PROPOSED":
        raise err(errors.ERR_INVALID_STATE, "RentSchedule is not PROPOSED.")
    rec["status"] = "CONTESTED"
    touch(rec)
    return success(serialize.rent_schedule_out(rec), status=200)


@app.route("/rent-schedules/<sid>/revise", methods=["POST"])
def revise_rent_schedule(sid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = util.require_body(get_json())
    rec = fetch_or_404(db.rent_schedules, sid, "RentSchedule")
    proposed = util.req_int(body, "proposed_rent_cents", 0)
    if rec["status"] != "CONTESTED":
        raise err(errors.ERR_INVALID_STATE, "RentSchedule is not CONTESTED.")
    # recompute against the SAME prior_rent_cents / effective_date baseline.
    lot = db.lots.get(rec["lot_id"])
    community = db.communities.get(lot["community_id"]) if lot else None
    new_rent, cap_applied = calc.capped_rent(
        rec["prior_rent_cents"], proposed, community["state_code"])
    rec["proposed_rent_cents"] = proposed
    rec["new_rent_cents"] = new_rent
    rec["cap_applied"] = cap_applied
    rec["status"] = "PROPOSED"
    touch(rec)
    return success(serialize.rent_schedule_out(rec), status=200)


@app.route("/rent-schedules/<sid>/apply", methods=["POST"])
def apply_rent_schedule(sid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    rec = fetch_or_404(db.rent_schedules, sid, "RentSchedule")
    if rec["status"] != "ACCEPTED":
        raise err(errors.ERR_INVALID_STATE, "RentSchedule is not ACCEPTED.")
    # business temporal (priority 11): effective_date >= 12 months after the
    # lot's most recent EFFECTIVE schedule's effective_date.
    lot = db.lots.get(rec["lot_id"])
    prior_effective = [
        s for s in db.rent_schedules.values()
        if s["lot_id"] == rec["lot_id"] and s["status"] == "EFFECTIVE"
    ]
    if prior_effective:
        prior_effective.sort(key=lambda s: (s["effective_date"], s["_seq"]))
        last_date = parse_date(prior_effective[-1]["effective_date"])
        this_date = parse_date(rec["effective_date"])
        if not _at_least_12_months_after(last_date, this_date):
            raise err(errors.ERR_INCREASE_TOO_SOON,
                      "Effective date is less than 12 months after the last "
                      "effective schedule.")
    rec["status"] = "EFFECTIVE"
    touch(rec)
    # Lot.current_rent_cents recomputes to new_rent_cents (derived); bump version.
    touch(lot)
    return success(serialize.rent_schedule_out(rec), status=200)


def _at_least_12_months_after(base_date, target_date):
    """True when target_date is on or after (base_date + 12 months)."""
    from datetime import date
    year = base_date.year + 1
    month = base_date.month
    day = base_date.day
    try:
        threshold = date(year, month, day)
    except ValueError:
        # e.g. Feb 29 -> use Mar 1.
        from datetime import timedelta
        threshold = date(year, month, 28) + timedelta(days=1)
    return target_date >= threshold


@app.route("/rent-schedules/<sid>/withdraw", methods=["POST"])
def withdraw_rent_schedule(sid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    rec = fetch_or_404(db.rent_schedules, sid, "RentSchedule")
    if rec["status"] != "PROPOSED":
        raise err(errors.ERR_INVALID_STATE, "RentSchedule is not PROPOSED.")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return success(serialize.rent_schedule_out(rec), status=200)


# ===========================================================================
# UtilityBill / readings / charges
# ===========================================================================

@app.route("/utility-bills", methods=["POST"])
def create_utility_bill():
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = util.require_body(get_json())
    community = _existence_fk(body, "community_id", db.communities, "Community")
    utility_type = util.req_enum(body, "utility_type", {"WATER", "ELECTRIC", "SEWER"})
    period_start = util.req_iso_date(body, "period_start")
    period_end = util.req_iso_date(body, "period_end")
    master_charge = util.req_int(body, "master_charge_cents", 0)

    rec = new_common()
    rec.update({
        "community_id": community["id"],
        "utility_type": utility_type,
        "period_start": period_start,
        "period_end": period_end,
        "master_charge_cents": master_charge,
        "apportioned_total_cents": 0,
        "status": "DRAFT",
    })
    db.utility_bills[rec["id"]] = rec
    return success(serialize.utility_bill_out(rec), status=201)


@app.route("/utility-bills/<bid>", methods=["GET"])
def get_utility_bill(bid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch_or_404(db.utility_bills, bid, "UtilityBill")
    return success(serialize.utility_bill_out(rec), status=200)


@app.route("/utility-bills", methods=["GET"])
def list_utility_bills():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return do_list(db.utility_bills, serialize.utility_bill_out, {
        "community_id": request.args.get("community_id"),
    })


@app.route("/utility-bills/<bid>/readings", methods=["POST"])
def create_reading(bid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = util.require_body(get_json())
    bill = fetch_or_404(db.utility_bills, bid, "UtilityBill")
    lot = _existence_fk(body, "lot_id", db.lots, "Lot")
    metered_units = util.req_number(body, "metered_units", 0)

    rec = new_record()
    rec.update({
        "utility_bill_id": bill["id"],
        "lot_id": lot["id"],
        "metered_units": metered_units,
    })
    db.utility_readings[rec["id"]] = rec
    return success(serialize.utility_reading_out(rec), status=201)


@app.route("/utility-readings/<rid>", methods=["GET"])
def get_reading(rid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch_or_404(db.utility_readings, rid, "UtilityReading")
    return success(serialize.utility_reading_out(rec), status=200)


@app.route("/utility-readings", methods=["GET"])
def list_readings():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return do_list(db.utility_readings, serialize.utility_reading_out, {
        "utility_bill_id": request.args.get("utility_bill_id"),
        "lot_id": request.args.get("lot_id"),
    })


@app.route("/utility-bills/<bid>/apportion", methods=["POST"])
def apportion_bill(bid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    bill = fetch_or_404(db.utility_bills, bid, "UtilityBill")
    # state (priority 7).
    if bill["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "UtilityBill is not DRAFT.")
    community = db.communities.get(bill["community_id"])
    method = community["utility_apportionment_method"]

    # occupied set: lots in this community with status OCCUPIED, each with an
    # ACTIVE lease, ordered created_at ASC then lot_number ASC.
    occupied = [
        lot for lot in db.lots.values()
        if lot["community_id"] == bill["community_id"] and lot["status"] == "OCCUPIED"
    ]
    # priority 16: requires >= 1 occupied lot.
    if len(occupied) < 1:
        raise err(errors.ERR_NO_OCCUPIED_LOTS, "Apportionment requires at least one OCCUPIED lot.")

    occupied.sort(key=lambda lot: (lot["created_at"], lot["lot_number"], lot["_seq"]))

    # readings for this bill, summed per lot.
    readings_by_lot = {}
    total_metered = 0
    for r in db.utility_readings.values():
        if r["utility_bill_id"] == bill["id"]:
            readings_by_lot[r["lot_id"]] = readings_by_lot.get(r["lot_id"], 0) + r["metered_units"]
            total_metered += r["metered_units"]

    if method == "SUB_METER":
        # priority 16: SUB_METER additionally requires total_metered_units > 0.
        if total_metered <= 0:
            raise err(errors.ERR_NO_METER_READINGS,
                      "SUB_METER apportionment requires total metered units > 0.")

    # Build weighted lots and resolve each lot's active-lease resident.
    weighted = []
    lot_resident = {}
    for lot in occupied:
        active_lease = None
        if lot["current_lease_id"]:
            cl = db.lot_leases.get(lot["current_lease_id"])
            if cl is not None and cl["status"] == "ACTIVE":
                active_lease = cl
        lot_resident[lot["id"]] = active_lease["resident_id"] if active_lease else None
        if method == "PER_CAPITA":
            resident = db.residents.get(active_lease["resident_id"]) if active_lease else None
            weight = resident["household_size"] if resident else 0
        else:  # SUB_METER
            weight = readings_by_lot.get(lot["id"], 0)
        weighted.append((lot["id"], weight))

    shares = calc.apportion(bill["master_charge_cents"], weighted)

    apportioned_total = 0
    for lot in occupied:
        amount = shares[lot["id"]]
        apportioned_total += amount
        charge = new_record()
        charge.update({
            "utility_bill_id": bill["id"],
            "lot_id": lot["id"],
            "resident_id": lot_resident[lot["id"]],
            "amount_cents": amount,
        })
        db.utility_charges[charge["id"]] = charge
        # UTILITY_CHARGE ledger entry against the lot's active resident.
        if lot["current_lease_id"]:
            cl = db.lot_leases.get(lot["current_lease_id"])
            if cl is not None and cl["status"] == "ACTIVE":
                services.post_ledger_entry(cl, "UTILITY_CHARGE", amount)

    bill["apportioned_total_cents"] = apportioned_total
    community["total_metered_units"] = total_metered
    bill["status"] = "APPORTIONED"
    touch(bill)
    return success(serialize.utility_bill_out(bill), status=200)


@app.route("/utility-charges/<cid>", methods=["GET"])
def get_charge(cid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch_or_404(db.utility_charges, cid, "UtilityCharge")
    return success(serialize.utility_charge_out(rec), status=200)


@app.route("/utility-charges", methods=["GET"])
def list_charges():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return do_list(db.utility_charges, serialize.utility_charge_out, {
        "utility_bill_id": request.args.get("utility_bill_id"),
        "lot_id": request.args.get("lot_id"),
        "resident_id": request.args.get("resident_id"),
    })


# ===========================================================================
# Ledger
# ===========================================================================

@app.route("/lot-ledger-entries/<eid>", methods=["GET"])
def get_ledger_entry(eid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch_or_404(db.lot_ledger_entries, eid, "LotLedgerEntry")
    return success(serialize.ledger_entry_out(rec), status=200)


@app.route("/lot-ledger-entries", methods=["GET"])
def list_ledger_entries():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return do_list(db.lot_ledger_entries, serialize.ledger_entry_out, {
        "lease_id": request.args.get("lease_id"),
        "resident_id": request.args.get("resident_id"),
    })


# ===========================================================================
# EvictionCase
# ===========================================================================

@app.route("/eviction-cases", methods=["POST"])
def create_eviction_case():
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = util.require_body(get_json())
    lease = _existence_fk(body, "lease_id", db.lot_leases, "LotLease")
    reason = util.req_enum(body, "reason", {"NONPAYMENT", "LEASE_VIOLATION"})

    lot = db.lots.get(lease["lot_id"])
    # state (priority 7): serving a notice requires the lot OCCUPIED.
    if lot is None or lot["status"] != "OCCUPIED":
        raise err(errors.ERR_INVALID_STATE, "Lot is not OCCUPIED.")

    resident = db.residents.get(lease["resident_id"])
    # NONPAYMENT requires arrears >= threshold (priority 14).
    if reason == "NONPAYMENT":
        if services.resident_arrears(resident["id"]) < calc.ARREARS_THRESHOLD_CENTS:
            raise err(errors.ERR_ARREARS_BELOW_THRESHOLD,
                      "NONPAYMENT eviction requires arrears at or above the threshold.")

    community = db.communities.get(lot["community_id"])
    rec = new_common()
    # The notice is served at the server's current logical instant (PRD §2.9):
    # cure/adjudication windows are time-gated by that instant, and the
    # cure_deadline is derived from the date portion of the case's created_at
    # (PRD §3.7), so created_at must reflect the logical clock, not wall time.
    from response import iso_ms
    rec["created_at"] = iso_ms(server_now())
    rec["updated_at"] = rec["created_at"]
    rec["lease_id"] = lease["id"]
    rec["reason"] = reason
    rec["status"] = "NOTICE_SERVED"
    # cure_deadline derived from created_at + state cure days (PRD §3.7).
    deadline_dt = calc.cure_deadline(parse_iso(rec["created_at"]), community["state_code"])
    rec["cure_deadline"] = iso_ms(deadline_dt)
    db.eviction_cases[rec["id"]] = rec

    # cascade: lot OCCUPIED -> EVICTING; bump version; NONPAYMENT -> DELINQUENT.
    lot["status"] = "EVICTING"
    touch(lot)
    if reason == "NONPAYMENT" and resident is not None:
        resident["standing"] = "DELINQUENT"
        touch(resident)
    return success(serialize.eviction_case_out(rec), status=201)


@app.route("/eviction-cases/<eid>", methods=["GET"])
def get_eviction_case(eid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch_or_404(db.eviction_cases, eid, "EvictionCase")
    return success(serialize.eviction_case_out(rec), status=200)


@app.route("/eviction-cases", methods=["GET"])
def list_eviction_cases():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return do_list(db.eviction_cases, serialize.eviction_case_out, {
        "lease_id": request.args.get("lease_id"),
    })


@app.route("/eviction-cases/<eid>/cure", methods=["POST"])
def cure_eviction(eid):
    user_id, role = authenticate()
    require_role(role, {"Resident"})
    rec = fetch_or_404(db.eviction_cases, eid, "EvictionCase")
    lease = db.lot_leases.get(rec["lease_id"])
    # Resident ownership (PRD §2.1).
    if lease is not None and lease["resident_id"] != user_id:
        raise err(errors.ERR_FORBIDDEN, "Resident may only cure its own eviction.")
    # state (priority 7).
    if rec["status"] != "NOTICE_SERVED":
        raise err(errors.ERR_INVALID_STATE, "EvictionCase is not NOTICE_SERVED.")
    # cure permitted only while now <= cure_deadline (priority 12).
    if server_now() > parse_iso(rec["cure_deadline"]):
        raise err(errors.ERR_CURE_PERIOD_EXPIRED, "Cure attempted after the cure deadline.")
    resident = db.residents.get(lease["resident_id"]) if lease else None
    # NONPAYMENT cure requires arrears cleared below threshold (priority 15).
    if rec["reason"] == "NONPAYMENT":
        if resident is None or services.resident_arrears(resident["id"]) >= calc.ARREARS_THRESHOLD_CENTS:
            raise err(errors.ERR_ARREARS_NOT_CLEARED,
                      "NONPAYMENT cure requires arrears cleared below the threshold.")

    rec["status"] = "CURED"
    touch(rec)
    lot = db.lots.get(lease["lot_id"]) if lease else None
    if lot is not None:
        lot["status"] = "OCCUPIED"
        touch(lot)
    if resident is not None and resident["standing"] == "DELINQUENT":
        resident["standing"] = "GOOD"
        touch(resident)
    return success(serialize.eviction_case_out(rec), status=200)


@app.route("/eviction-cases/<eid>/adjudicate", methods=["POST"])
def adjudicate_eviction(eid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    rec = fetch_or_404(db.eviction_cases, eid, "EvictionCase")
    # state (priority 7).
    if rec["status"] != "NOTICE_SERVED":
        raise err(errors.ERR_INVALID_STATE, "EvictionCase is not NOTICE_SERVED.")
    # adjudication permitted only while now > cure_deadline (priority 13).
    if not (server_now() > parse_iso(rec["cure_deadline"])):
        raise err(errors.ERR_CURE_PERIOD_ACTIVE,
                  "Adjudication attempted on or before the cure deadline.")

    rec["status"] = "ADJUDICATED"
    touch(rec)
    lease = db.lot_leases.get(rec["lease_id"])
    lot = db.lots.get(lease["lot_id"]) if lease else None
    resident = db.residents.get(lease["resident_id"]) if lease else None
    if lease is not None:
        lease["status"] = "TERMINATED"
        touch(lease)
    if lot is not None:
        lot["status"] = "VACANT"
        lot["current_lease_id"] = None
        touch(lot)  # occupied_lot_count is derived from lot status
    if resident is not None:
        resident["standing"] = "EVICTED"
        touch(resident)
    return success(serialize.eviction_case_out(rec), status=200)


@app.route("/eviction-cases/<eid>/dismiss", methods=["POST"])
def dismiss_eviction(eid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    rec = fetch_or_404(db.eviction_cases, eid, "EvictionCase")
    if rec["status"] != "NOTICE_SERVED":
        raise err(errors.ERR_INVALID_STATE, "EvictionCase is not NOTICE_SERVED.")
    rec["status"] = "DISMISSED"
    touch(rec)
    lease = db.lot_leases.get(rec["lease_id"])
    lot = db.lots.get(lease["lot_id"]) if lease else None
    if lot is not None:
        lot["status"] = "OCCUPIED"
        touch(lot)
    return success(serialize.eviction_case_out(rec), status=200)


# ===========================================================================
# ConversionVote / ballots
# ===========================================================================

@app.route("/conversion-votes", methods=["POST"])
def create_conversion_vote():
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = util.require_body(get_json())
    community = _existence_fk(body, "community_id", db.communities, "Community")
    quorum = util.req_number(body, "quorum_threshold_pct", 0, 1, strict_min=True)

    rec = new_common()
    rec.update({
        "community_id": community["id"],
        "quorum_threshold_pct": quorum,
        "eligible_lot_count": 0,
        "status": "OPEN",
    })
    db.conversion_votes[rec["id"]] = rec
    return success(serialize.conversion_vote_out(rec), status=201)


@app.route("/conversion-votes/<vid>", methods=["GET"])
def get_conversion_vote(vid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch_or_404(db.conversion_votes, vid, "ConversionVote")
    return success(serialize.conversion_vote_out(rec), status=200)


@app.route("/conversion-votes", methods=["GET"])
def list_conversion_votes():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return do_list(db.conversion_votes, serialize.conversion_vote_out, {
        "community_id": request.args.get("community_id"),
    })


@app.route("/conversion-votes/<vid>/open", methods=["POST"])
def open_conversion_vote(vid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    rec = fetch_or_404(db.conversion_votes, vid, "ConversionVote")
    if rec["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "ConversionVote is not OPEN.")
    # snapshot eligible_lot_count = community.occupied_lot_count.
    rec["eligible_lot_count"] = services.occupied_lot_count(rec["community_id"])
    touch(rec)
    # freeze cascade: every OCCUPIED community lot -> FROZEN; bump each version.
    for lot in db.lots.values():
        if lot["community_id"] == rec["community_id"] and lot["status"] == "OCCUPIED":
            lot["status"] = "FROZEN"
            touch(lot)
    return success(serialize.conversion_vote_out(rec), status=200)


@app.route("/conversion-votes/<vid>/ballots", methods=["POST"])
def cast_ballot(vid):
    _, role = authenticate()
    require_role(role, {"ParkManager", "Resident"})
    body = util.require_body(get_json())
    vote = fetch_or_404(db.conversion_votes, vid, "ConversionVote")
    lot = _existence_fk(body, "lot_id", db.lots, "Lot")
    choice = util.req_enum(body, "choice", {"YES", "NO"})

    # cross-community reference (priority 5): lot must belong to the vote's
    # community.
    if lot["community_id"] != vote["community_id"]:
        raise err(errors.ERR_CROSS_COMMUNITY_REFERENCE,
                  "Ballot lot belongs to a different community.")

    # one ballot per lot per vote; lot must be eligible (OCCUPIED or FROZEN by
    # this vote) (priority 17). A frozen lot was occupied at open time.
    for b in db.conversion_ballots.values():
        if b["conversion_vote_id"] == vote["id"] and b["lot_id"] == lot["id"]:
            raise err(errors.ERR_DUPLICATE_BALLOT, "A ballot already exists for this lot.")
    if lot["status"] not in ("OCCUPIED", "FROZEN"):
        raise err(errors.ERR_DUPLICATE_BALLOT, "Lot is not eligible (not occupied).")

    rec = new_record()
    rec.update({
        "conversion_vote_id": vote["id"],
        "lot_id": lot["id"],
        "choice": choice,
    })
    db.conversion_ballots[rec["id"]] = rec
    # yes_count is derived; no need to store. Bump the vote's version as it
    # changed (a derived recompute is a modification).
    touch(vote)
    return success(serialize.conversion_ballot_out(rec), status=201)


@app.route("/conversion-votes/<vid>/ballots", methods=["GET"])
def list_vote_ballots(vid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    fetch_or_404(db.conversion_votes, vid, "ConversionVote")
    return do_list(db.conversion_ballots, serialize.conversion_ballot_out, {
        "conversion_vote_id": vid,
    })


@app.route("/conversion-ballots/<bid>", methods=["GET"])
def get_ballot(bid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = fetch_or_404(db.conversion_ballots, bid, "ConversionBallot")
    return success(serialize.conversion_ballot_out(rec), status=200)


@app.route("/conversion-ballots", methods=["GET"])
def list_ballots():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return do_list(db.conversion_ballots, serialize.conversion_ballot_out, {
        "conversion_vote_id": request.args.get("conversion_vote_id"),
        "lot_id": request.args.get("lot_id"),
    })


@app.route("/conversion-votes/<vid>/tally", methods=["POST"])
def tally_conversion_vote(vid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    vote = fetch_or_404(db.conversion_votes, vid, "ConversionVote")
    if vote["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "ConversionVote is not OPEN.")

    yes = services.yes_count(vote["id"])
    eligible = vote["eligible_lot_count"]
    # quorum: pass when yes/eligible >= threshold (PRD §3.8). Guard divide-by-0.
    passed = eligible > 0 and (yes / eligible) >= vote["quorum_threshold_pct"]

    vote["status"] = "PASSED" if passed else "FAILED"
    touch(vote)
    community = db.communities.get(vote["community_id"])
    if passed and community is not None:
        community["ownership_model"] = "RESIDENT_OWNED"
        touch(community)
    # unfreeze cascade: every FROZEN community lot -> OCCUPIED; bump version.
    for lot in db.lots.values():
        if lot["community_id"] == vote["community_id"] and lot["status"] == "FROZEN":
            lot["status"] = "OCCUPIED"
            touch(lot)
    return success(serialize.conversion_vote_out(vote), status=200)


# ===========================================================================
# Entrypoint
# ===========================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    # Avoid a startup-blocking DNS timeout when binding 0.0.0.0 (socket.getfqdn
    # can stall ~5s resolving the host's .local name). It only populates a
    # cosmetic server_name, so short-circuit it.
    import socket as _socket
    _socket.getfqdn = lambda name="": (name or "localhost")

    from werkzeug.serving import make_server
    httpd = make_server("0.0.0.0", port, app, threaded=True)
    httpd.serve_forever()
