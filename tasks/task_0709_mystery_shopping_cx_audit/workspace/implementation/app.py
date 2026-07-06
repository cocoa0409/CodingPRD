"""Mystery Shopping & CX-Audit Platform API — entry point.

Python + Flask. In-memory storage only (see db.py). Boots empty on every
process start; nothing is seeded. Listens on $PORT (default 10000), 0.0.0.0.
"""
import os

from flask import Flask, request

from db import db, stamp_create, touch, parse_iso, new_id
from errors import ApiError, err
from auth import authenticate, require_roles
from response import object_response, array_response, error_response, success
from serialize import public, public_list
import validate as V
import calc
import services as S
import lookups as L

app = Flask(__name__)
app.url_map.strict_slashes = False

FAMILIES = {"RETAIL", "DINING", "BANKING"}


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #
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
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)


def auth_and_roles(allowed):
    caller = authenticate()
    require_roles(caller, allowed)
    return caller


def list_sorted(records):
    """Sort by creation order ascending (PRD 2.3)."""
    return sorted(records, key=lambda r: r.get("_seq", 0))


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth_and_roles({"PlatformAdmin"})
    body = V.get_body()
    iso = V.require_str(body, "to_iso8601")
    try:
        db.clock = parse_iso(iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 timestamp.")
    return object_response({}, status=200)


# --------------------------------------------------------------------------- #
# ClientAccount
# --------------------------------------------------------------------------- #
@app.route("/clients", methods=["POST"])
def create_client():
    # Public self-registration (Anonymous or PlatformAdmin). Auth optional, but
    # if headers are present they must be well-formed and a permitted role.
    if request.headers.get("X-User-ID") or request.headers.get("X-User-Role"):
        auth_and_roles({"Anonymous", "PlatformAdmin"})
    body = V.get_body()
    company_name = V.require_str(body, "company_name")
    billing_email = V.require_str(body, "billing_email")
    fee = V.require_int(body, "fee_per_completed_shop_cents", minimum=0)
    rec = {
        "company_name": company_name,
        "billing_email": billing_email,
        "fee_per_completed_shop_cents": fee,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.clients[rec["id"]] = rec
    return object_response(public(rec), status=201)


@app.route("/clients/<cid>", methods=["GET"])
def get_client_ep(cid):
    auth_and_roles({"PlatformAdmin", "ClientManager"})
    rec = L.get_client(cid)
    return object_response(public(rec))


@app.route("/clients/<cid>/suspend", methods=["POST"])
def suspend_client(cid):
    auth_and_roles({"PlatformAdmin"})
    rec = L.get_client(cid)
    rec["status"] = "SUSPENDED"
    touch(rec)
    return object_response(public(rec))


# --------------------------------------------------------------------------- #
# Ownership helper for client-scoped resources
# --------------------------------------------------------------------------- #
def check_client_owner(caller, client_id):
    """A ClientManager may only act on resources of its own ClientAccount
    (PRD 2.1 / validation #4)."""
    if caller.role == "ClientManager" and caller.user_id != client_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "ClientManager does not own this client.")


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #
@app.route("/clients/<cid>/locations", methods=["POST"])
def create_location(cid):
    caller = auth_and_roles({"ClientManager", "PlatformAdmin"})
    client = L.get_client(cid)
    check_client_owner(caller, cid)
    body = V.get_body()
    label = V.require_str(body, "label")
    lat = V.require_number(body, "lat")
    lng = V.require_number(body, "lng")
    family = V.require_enum(body, "scenario_family", FAMILIES)
    rec = {
        "client_id": cid,
        "label": label,
        "lat": lat,
        "lng": lng,
        "scenario_family": family,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.locations[rec["id"]] = rec
    return object_response(public(rec), status=201)


@app.route("/clients/<cid>/locations", methods=["GET"])
def list_locations(cid):
    caller = auth_and_roles({"ClientManager", "PlatformAdmin"})
    L.get_client(cid)
    check_client_owner(caller, cid)
    limit, offset = V.pagination()
    items = list_sorted([x for x in db.locations.values() if x["client_id"] == cid])
    page, total = V.paginate(items, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/locations/<lid>/retire", methods=["POST"])
def retire_location(lid):
    caller = auth_and_roles({"ClientManager", "PlatformAdmin"})
    loc = L.get_location(lid)
    check_client_owner(caller, loc["client_id"])
    loc["status"] = "RETIRED"
    touch(loc)
    return object_response(public(loc))


# --------------------------------------------------------------------------- #
# ScenarioScript
# --------------------------------------------------------------------------- #
def _weights_sum_ok(weights_json):
    """Non-negative everywhere and sum to 1.00 (round_half_up, 2dp)."""
    if not isinstance(weights_json, dict) or not weights_json:
        return False
    from decimal import Decimal, ROUND_HALF_UP
    total = Decimal("0")
    for v in weights_json.values():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return False
        if v < 0:
            return False
        total += Decimal(str(v))
    total_2dp = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return total_2dp == Decimal("1.00")


@app.route("/clients/<cid>/scripts", methods=["POST"])
def create_script(cid):
    caller = auth_and_roles({"ClientManager", "PlatformAdmin"})
    client = L.get_client(cid)
    check_client_owner(caller, cid)
    body = V.get_body()
    title = V.require_str(body, "title")
    family = V.require_enum(body, "scenario_family", FAMILIES)
    required_photo_count = V.require_int(body, "required_photo_count", minimum=0)
    receipt_required = V.opt_bool(body, "receipt_required", default=True)
    reimburse_cap_cents = V.require_int(body, "reimburse_cap_cents", minimum=0)
    base_fee_cents = V.require_int(body, "base_fee_cents", minimum=0)
    weights_json = V.require_object(body, "weights_json")
    passing_score = V.require_int(body, "passing_score")
    if passing_score < 0 or passing_score > 100:
        raise err("ERR_INVALID_REQUEST", "passing_score must be between 0 and 100.")
    # weights values must be numeric & non-negative (structural validity at create).
    for v in weights_json.values():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise err("ERR_INVALID_REQUEST", "weights_json values must be non-negative numbers.")
    rec = {
        "client_id": cid,
        "title": title,
        "scenario_family": family,
        "required_photo_count": required_photo_count,
        "receipt_required": receipt_required,
        "reimburse_cap_cents": reimburse_cap_cents,
        "base_fee_cents": base_fee_cents,
        "weights_json": weights_json,
        "passing_score": passing_score,
        "status": "DRAFT",
    }
    stamp_create(rec)
    db.scripts[rec["id"]] = rec
    return object_response(public(rec), status=201)


@app.route("/clients/<cid>/scripts", methods=["GET"])
def list_scripts(cid):
    caller = auth_and_roles({"ClientManager", "PlatformAdmin"})
    L.get_client(cid)
    check_client_owner(caller, cid)
    limit, offset = V.pagination()
    items = list_sorted([x for x in db.scripts.values() if x["client_id"] == cid])
    page, total = V.paginate(items, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/scripts/<sid>/publish", methods=["POST"])
def publish_script(sid):
    caller = auth_and_roles({"ClientManager"})
    script = L.get_script(sid)
    check_client_owner(caller, script["client_id"])
    if script["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Script is not DRAFT.")
    if not _weights_sum_ok(script["weights_json"]):
        raise err("ERR_WEIGHTS_NOT_NORMALIZED",
                  "Script weights must be non-negative and sum to 1.00.")
    client = db.clients[script["client_id"]]
    if client["status"] != "ACTIVE":
        raise err("ERR_FAMILY_MISMATCH", "Owning client is not ACTIVE.")
    script["status"] = "PUBLISHED"
    touch(script)
    return object_response(public(script))


@app.route("/scripts/<sid>/archive", methods=["POST"])
def archive_script(sid):
    caller = auth_and_roles({"ClientManager"})
    script = L.get_script(sid)
    check_client_owner(caller, script["client_id"])
    if script["status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE", "Script is not PUBLISHED.")
    non_terminal = {"ASSIGNED", "IN_FIELD", "SUBMITTED", "REVISION_REQUESTED"}
    for a in db.assignments.values():
        if a["script_id"] == sid and a["status"] in non_terminal:
            raise err("ERR_SCRIPT_IN_USE", "Script is referenced by a non-terminal assignment.")
    script["status"] = "ARCHIVED"
    touch(script)
    return object_response(public(script))


# --------------------------------------------------------------------------- #
# ShopWave
# --------------------------------------------------------------------------- #
@app.route("/clients/<cid>/waves", methods=["POST"])
def create_wave(cid):
    caller = auth_and_roles({"ClientManager", "PlatformAdmin"})
    client = L.get_client(cid)
    check_client_owner(caller, cid)
    body = V.get_body()
    name = V.require_str(body, "name")
    start_raw = V.require_str(body, "field_window_start")
    end_raw = V.require_str(body, "field_window_end")
    try:
        start_dt = parse_iso(start_raw)
        end_dt = parse_iso(end_raw)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "field_window_start/end must be ISO 8601 timestamps.")
    cooldown = V.opt_int(body, "rotation_cooldown_days", default=30, minimum=0)
    # Window validity at creation (PRD 3.3) -> ERR_INVALID_WINDOW.
    if not (end_dt > start_dt):
        raise err("ERR_INVALID_WINDOW", "field_window_end must be strictly after field_window_start.")
    rec = {
        "client_id": cid,
        "name": name,
        "field_window_start": start_raw,
        "field_window_end": end_raw,
        "rotation_cooldown_days": cooldown,
        "status": "DRAFT",
        "validated_shop_count": 0,
        "client_billable_cents": 0,
    }
    stamp_create(rec)
    db.waves[rec["id"]] = rec
    return object_response(public(rec), status=201)


@app.route("/clients/<cid>/waves", methods=["GET"])
def list_waves(cid):
    caller = auth_and_roles({"ClientManager", "PlatformAdmin"})
    L.get_client(cid)
    check_client_owner(caller, cid)
    limit, offset = V.pagination()
    items = list_sorted([x for x in db.waves.values() if x["client_id"] == cid])
    page, total = V.paginate(items, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/waves/<wid>", methods=["GET"])
def get_wave_ep(wid):
    caller = auth_and_roles({"ClientManager", "PlatformAdmin"})
    wave = L.get_wave(wid)
    check_client_owner(caller, wave["client_id"])
    return object_response(public(wave))


@app.route("/waves/<wid>/publish", methods=["POST"])
def publish_wave(wid):
    caller = auth_and_roles({"ClientManager"})
    wave = L.get_wave(wid)
    check_client_owner(caller, wave["client_id"])
    if wave["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Wave is not DRAFT.")
    start_dt = parse_iso(wave["field_window_start"])
    end_dt = parse_iso(wave["field_window_end"])
    if not (end_dt > start_dt):
        raise err("ERR_INVALID_WINDOW", "field_window_end must be strictly after field_window_start.")
    client = db.clients[wave["client_id"]]
    if client["status"] != "ACTIVE":
        raise err("ERR_FAMILY_MISMATCH", "Owning client is not ACTIVE.")
    wave["status"] = "PUBLISHED"
    touch(wave)
    return object_response(public(wave))


@app.route("/waves/<wid>/close", methods=["POST"])
def close_wave(wid):
    caller = auth_and_roles({"ClientManager"})
    wave = L.get_wave(wid)
    check_client_owner(caller, wave["client_id"])
    if wave["status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE", "Wave is not PUBLISHED.")
    live = {"ASSIGNED", "IN_FIELD", "SUBMITTED", "REVISION_REQUESTED"}
    for a in db.assignments.values():
        if a["wave_id"] == wid and a["status"] in live:
            raise err("ERR_WAVE_NOT_DRAINED", "Wave still has non-terminal assignments.")
    wave["status"] = "CLOSED"
    touch(wave)
    return object_response(public(wave))


# --------------------------------------------------------------------------- #
# Shoppers
# --------------------------------------------------------------------------- #
@app.route("/shoppers", methods=["POST"])
def create_shopper():
    if request.headers.get("X-User-ID") or request.headers.get("X-User-Role"):
        auth_and_roles({"Anonymous", "PlatformAdmin"})
    body = V.get_body()
    full_name = V.require_str(body, "full_name")
    email = V.require_str(body, "email")
    home_lat = V.require_number(body, "home_lat")
    home_lng = V.require_number(body, "home_lng")
    tax_id_on_file = V.opt_bool(body, "tax_id_on_file", default=False)
    rec = {
        "full_name": full_name,
        "email": email,
        "home_lat": home_lat,
        "home_lng": home_lng,
        "tax_id_on_file": tax_id_on_file,
        "status": "REGISTERED",
        "certification_score": 0,
        "reliability_score": 100.0,
        "ytd_paid_cents": 0,
        "open_assignment_count": 0,
    }
    stamp_create(rec)
    db.shoppers[rec["id"]] = rec
    return object_response(public(rec), status=201)


@app.route("/shoppers/<sid>", methods=["GET"])
def get_shopper_ep(sid):
    caller = auth_and_roles({"PlatformAdmin", "QaValidator", "FinanceOfficer", "Shopper"})
    rec = L.get_shopper(sid)
    if caller.role == "Shopper" and caller.user_id != sid:
        raise err("ERR_NOT_RESOURCE_OWNER", "Shopper may only read their own record.")
    return object_response(public(rec))


@app.route("/shoppers/<sid>/tax-profile", methods=["PATCH"])
def set_tax_profile(sid):
    caller = auth_and_roles({"PlatformAdmin", "FinanceOfficer", "Shopper"})
    rec = L.get_shopper(sid)
    if caller.role == "Shopper" and caller.user_id != sid:
        raise err("ERR_NOT_RESOURCE_OWNER", "Shopper may only edit their own record.")
    body = V.get_body()
    flag = V.require_bool(body, "tax_id_on_file")
    rec["tax_id_on_file"] = flag
    touch(rec)
    return object_response(public(rec))


@app.route("/shoppers/<sid>/certification-attempts", methods=["POST"])
def create_cert_attempt(sid):
    auth_and_roles({"QaValidator"})
    shopper = L.get_shopper(sid)
    body = V.get_body()
    # Validate raw_score and scenario_family -> ERR_INVALID_REQUEST.
    if "raw_score" not in body:
        raise err("ERR_INVALID_REQUEST", "Missing required field: raw_score.")
    raw_score = body["raw_score"]
    if isinstance(raw_score, bool) or not isinstance(raw_score, int):
        raise err("ERR_INVALID_REQUEST", "raw_score must be an integer.")
    if raw_score < 0 or raw_score > 100:
        raise err("ERR_INVALID_REQUEST", "raw_score must be between 0 and 100.")
    family = V.require_enum(body, "scenario_family", FAMILIES)

    # attempt_index: 1-based ordinal among this shopper's attempts in this family.
    prior = [
        a for a in db.certification_attempts.values()
        if a["shopper_id"] == sid and a["scenario_family"] == family
    ]
    attempt_index = len(prior) + 1

    outcome = "PASSED" if raw_score >= calc.CERT_PASS_THRESHOLD else "FAILED"
    attempt = {
        "id": new_id(),
        "shopper_id": sid,
        "raw_score": raw_score,
        "scenario_family": family,
        "outcome": outcome,
        "attempt_index": attempt_index,
    }
    # CertificationAttempt is immutable: only id + created_at, no updated_at/version.
    from db import now_iso_millis
    attempt["created_at"] = now_iso_millis()
    attempt["_seq"] = db.next_seq()
    db.certification_attempts[attempt["id"]] = attempt

    # Certification side effects (PRD 3.2).
    if outcome == "PASSED":
        if shopper["status"] == "REGISTERED":
            shopper["certification_score"] = raw_score
            shopper["status"] = "CERTIFIED"
            # track which families the shopper is certified in
            _add_cert_family(shopper, family)
            touch(shopper)
        elif shopper["status"] == "CERTIFIED":
            shopper["certification_score"] = max(shopper["certification_score"], raw_score)
            _add_cert_family(shopper, family)
            touch(shopper)
        # SUSPENDED: no status change defined; refresh family record only if certified path.
    return object_response(public(attempt), status=201)


def _add_cert_family(shopper, family):
    fams = shopper.setdefault("_cert_families", [])
    if family not in fams:
        fams.append(family)


@app.route("/shoppers/<sid>/certification-attempts", methods=["GET"])
def list_cert_attempts(sid):
    auth_and_roles({"QaValidator", "PlatformAdmin"})
    L.get_shopper(sid)
    limit, offset = V.pagination()
    items = list_sorted([a for a in db.certification_attempts.values() if a["shopper_id"] == sid])
    page, total = V.paginate(items, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/shoppers/<sid>/suspend", methods=["POST"])
def suspend_shopper(sid):
    auth_and_roles({"PlatformAdmin"})
    shopper = L.get_shopper(sid)
    if shopper["status"] != "CERTIFIED":
        raise err("ERR_INVALID_STATE", "Shopper is not CERTIFIED.")
    if shopper["open_assignment_count"] != 0:
        raise err("ERR_SHOPPER_HAS_OPEN_ASSIGNMENTS", "Shopper has open assignments.")
    shopper["status"] = "SUSPENDED"
    touch(shopper)
    return object_response(public(shopper))


@app.route("/shoppers/<sid>/reinstate", methods=["POST"])
def reinstate_shopper(sid):
    auth_and_roles({"PlatformAdmin"})
    shopper = L.get_shopper(sid)
    if shopper["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Shopper is not SUSPENDED.")
    shopper["status"] = "CERTIFIED"
    touch(shopper)
    return object_response(public(shopper))


# --------------------------------------------------------------------------- #
# Assignments
# --------------------------------------------------------------------------- #
@app.route("/assignments", methods=["POST"])
def create_assignment():
    caller = auth_and_roles({"ClientManager", "PlatformAdmin"})
    body = V.get_body()
    wave_id = V.require_str(body, "wave_id")
    shopper_id = V.require_str(body, "shopper_id")
    location_id = V.require_str(body, "location_id")
    script_id = V.require_str(body, "script_id")
    due_at_raw = V.require_str(body, "due_at")
    try:
        due_at = parse_iso(due_at_raw)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "due_at must be an ISO 8601 timestamp.")

    # Existence (body FKs) -> ERR_NOT_FOUND, resolved in turn (PRD 2.4).
    wave = L.get_wave(wave_id)
    shopper = L.get_shopper(shopper_id)
    location = L.get_location(location_id)
    script = L.get_script(script_id)

    # Ownership: ClientManager must own the wave's client.
    check_client_owner(caller, wave["client_id"])

    client = db.clients[wave["client_id"]]

    # #9 ERR_SHOPPER_NOT_CERTIFIED: shopper CERTIFIED and certified in the
    # location's scenario_family.
    if shopper["status"] != "CERTIFIED":
        raise err("ERR_SHOPPER_NOT_CERTIFIED", "Shopper is not CERTIFIED.")
    if location["scenario_family"] not in shopper.get("_cert_families", []):
        raise err("ERR_SHOPPER_NOT_CERTIFIED",
                  "Shopper is not certified in the location's scenario_family.")

    # #10 ERR_FAMILY_MISMATCH: families identical; script PUBLISHED; wave
    # PUBLISHED; location ACTIVE; client ACTIVE.
    if location["scenario_family"] != script["scenario_family"]:
        raise err("ERR_FAMILY_MISMATCH", "Location and script scenario_family differ.")
    if script["status"] != "PUBLISHED":
        raise err("ERR_FAMILY_MISMATCH", "Script is not PUBLISHED.")
    if wave["status"] != "PUBLISHED":
        raise err("ERR_FAMILY_MISMATCH", "Wave is not PUBLISHED.")
    if location["status"] != "ACTIVE":
        raise err("ERR_FAMILY_MISMATCH", "Location is not ACTIVE.")
    if client["status"] != "ACTIVE":
        raise err("ERR_FAMILY_MISMATCH", "Owning client is not ACTIVE.")

    # #11 ERR_DUE_OUTSIDE_WINDOW: due_at within [start, end] inclusive.
    start_dt = parse_iso(wave["field_window_start"])
    end_dt = parse_iso(wave["field_window_end"])
    if due_at < start_dt or due_at > end_dt:
        raise err("ERR_DUE_OUTSIDE_WINDOW", "due_at is outside the wave field window.")

    # #12 ERR_ROTATION_COOLDOWN: no prior assignment to the SAME location whose
    # due_at falls within rotation_cooldown_days before the new due_at.
    from datetime import timedelta
    cooldown_days = wave["rotation_cooldown_days"]
    window_start = due_at - timedelta(days=cooldown_days)
    for a in db.assignments.values():
        if a["shopper_id"] != shopper_id or a["location_id"] != location_id:
            continue
        prior_due = parse_iso(a["due_at"])
        # within rotation_cooldown_days before the new due_at
        if window_start <= prior_due <= due_at:
            raise err("ERR_ROTATION_COOLDOWN",
                      "Shopper assigned to same location too soon.")

    # Compute & freeze travel_distance_km (PRD 3.4).
    dist = calc.travel_distance_km(
        shopper["home_lat"], shopper["home_lng"], location["lat"], location["lng"]
    )

    rec = {
        "wave_id": wave_id,
        "shopper_id": shopper_id,
        "location_id": location_id,
        "script_id": script_id,
        "due_at": due_at_raw,
        "travel_distance_km": dist,
        "claimed_out_of_pocket_cents": 0,
        "reimbursable_cents": 0,
        "shopper_fee_cents": 0,
        "status": "ASSIGNED",
        "submission_count": 0,
        "validated_by_user_id": None,
    }
    stamp_create(rec)
    db.assignments[rec["id"]] = rec
    return object_response(public(rec), status=201)


@app.route("/assignments/<aid>", methods=["GET"])
def get_assignment_ep(aid):
    caller = auth_and_roles(
        {"ClientManager", "PlatformAdmin", "QaValidator", "FinanceOfficer", "Shopper"})
    a = L.get_assignment(aid)
    if caller.role == "Shopper" and caller.user_id != a["shopper_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Shopper may only read their own assignment.")
    if caller.role == "ClientManager":
        wave = db.waves[a["wave_id"]]
        check_client_owner(caller, wave["client_id"])
    return object_response(public(a))


@app.route("/assignments", methods=["GET"])
def list_assignments():
    caller = auth_and_roles(
        {"ClientManager", "PlatformAdmin", "QaValidator", "FinanceOfficer", "Shopper"})
    limit, offset = V.pagination()
    items = list(db.assignments.values())

    for key in ("wave_id", "shopper_id", "location_id", "script_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a[key] == val]

    # Scope by caller identity where the role binds to ownership.
    if caller.role == "Shopper":
        items = [a for a in items if a["shopper_id"] == caller.user_id]
    elif caller.role == "ClientManager":
        owned_waves = {w["id"] for w in db.waves.values() if w["client_id"] == caller.user_id}
        items = [a for a in items if a["wave_id"] in owned_waves]

    items = list_sorted(items)
    page, total = V.paginate(items, limit, offset)
    return array_response(public_list(page), limit, offset, total)


def _shopper_owns(caller, assignment):
    if caller.user_id != assignment["shopper_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Shopper does not own this assignment.")


def _clock_within_due(assignment):
    return db.clock <= parse_iso(assignment["due_at"])


@app.route("/assignments/<aid>/accept", methods=["POST"])
def accept_assignment(aid):
    caller = auth_and_roles({"Shopper"})
    a = L.get_assignment(aid)
    _shopper_owns(caller, a)
    if a["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "Assignment is not ASSIGNED.")
    if not _clock_within_due(a):
        raise err("ERR_INVALID_STATE", "Past due_at.")
    a["status"] = "IN_FIELD"
    touch(a)
    shopper = db.shoppers[a["shopper_id"]]
    S.adjust_open_assignment_count(shopper, 1)
    return object_response(public(a))


@app.route("/assignments/<aid>/evidence", methods=["POST"])
def upload_evidence(aid):
    caller = auth_and_roles({"Shopper"})
    a = L.get_assignment(aid)
    _shopper_owns(caller, a)
    body = V.get_body()
    kind = V.require_enum(body, "kind", {"PHOTO", "RECEIPT"})
    object_uri = V.require_str(body, "object_uri")
    section_key = V.opt_str(body, "section_key", default=None)
    receipt_amount_cents = V.opt_int(body, "receipt_amount_cents", default=0, minimum=0)
    # section_key, when present, must be a key of the backing script weights_json.
    if section_key is not None:
        script = db.scripts[a["script_id"]]
        if section_key not in script["weights_json"]:
            raise err("ERR_INVALID_REQUEST", "section_key must be a key of the script weights_json.")
    rec = {
        "assignment_id": aid,
        "kind": kind,
        "object_uri": object_uri,
        "section_key": section_key,
        "receipt_amount_cents": receipt_amount_cents if kind == "RECEIPT" else 0,
        "review_status": "PENDING",
    }
    stamp_create(rec)
    db.evidence[rec["id"]] = rec
    return object_response(public(rec), status=201)


@app.route("/assignments/<aid>/evidence", methods=["GET"])
def list_evidence(aid):
    caller = auth_and_roles({"Shopper", "QaValidator", "ClientManager", "PlatformAdmin"})
    a = L.get_assignment(aid)
    if caller.role == "Shopper" and caller.user_id != a["shopper_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Shopper may only read their own evidence.")
    if caller.role == "ClientManager":
        wave = db.waves[a["wave_id"]]
        check_client_owner(caller, wave["client_id"])
    limit, offset = V.pagination()
    items = list_sorted([e for e in db.evidence.values() if e["assignment_id"] == aid])
    page, total = V.paginate(items, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/evidence/<eid>/review", methods=["POST"])
def review_evidence(eid):
    auth_and_roles({"QaValidator"})
    ev = L.get_evidence(eid)
    body = V.get_body()
    decision = V.require_enum(body, "decision", {"APPROVE", "FLAG"})
    if ev["review_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Evidence is not PENDING.")
    ev["review_status"] = "APPROVED" if decision == "APPROVE" else "FLAGGED"
    touch(ev)
    return object_response(public(ev))


@app.route("/assignments/<aid>/scorecard", methods=["POST"])
def create_scorecard(aid):
    caller = auth_and_roles({"Shopper"})
    a = L.get_assignment(aid)
    _shopper_owns(caller, a)
    body = V.get_body()
    section_scores = V.require_object(body, "section_scores_json")
    script = db.scripts[a["script_id"]]
    # keys must be exactly the weights_json keys -> ERR_SECTION_KEYS_MISMATCH.
    if set(section_scores.keys()) != set(script["weights_json"].keys()):
        raise err("ERR_SECTION_KEYS_MISMATCH",
                  "section_scores_json keys must match the script weights_json keys.")
    for v in section_scores.values():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or v > 100:
            raise err("ERR_INVALID_REQUEST", "section scores must be numbers in 0..100.")
    rec = {
        "assignment_id": aid,
        "section_scores_json": section_scores,
        "estimated_score": 0,
        "audited_score": None,
        "audit_status": "DRAFT",
        "fraud_status": "UNCHECKED",
    }
    stamp_create(rec)
    db.scorecards[rec["id"]] = rec
    return object_response(public(rec), status=201)


@app.route("/assignments/<aid>/scorecard", methods=["GET"])
def get_scorecard(aid):
    caller = auth_and_roles({"Shopper", "QaValidator", "ClientManager", "PlatformAdmin"})
    a = L.get_assignment(aid)
    if caller.role == "Shopper" and caller.user_id != a["shopper_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Shopper may only read their own scorecard.")
    if caller.role == "ClientManager":
        wave = db.waves[a["wave_id"]]
        check_client_owner(caller, wave["client_id"])
    limit, offset = V.pagination()
    items = list_sorted([s for s in db.scorecards.values() if s["assignment_id"] == aid])
    page, total = V.paginate(items, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/assignments/<aid>/scorecard/fraud-check", methods=["POST"])
def fraud_check(aid):
    auth_and_roles({"QaValidator"})
    a = L.get_assignment(aid)
    sc = S.get_scorecard_for_assignment(aid)
    if sc is None:
        raise err("ERR_NOT_FOUND", "No scorecard for this assignment.")
    body = V.get_body()
    decision = V.require_enum(body, "decision", {"CLEAR", "HOLD"})
    if decision == "HOLD":
        if sc["fraud_status"] != "UNCHECKED":
            raise err("ERR_INVALID_STATE", "fraud_status must be UNCHECKED to HOLD.")
        sc["fraud_status"] = "FRAUD_HOLD"
    else:  # CLEAR
        if sc["fraud_status"] not in ("UNCHECKED", "FRAUD_HOLD"):
            raise err("ERR_INVALID_STATE", "fraud_status cannot be cleared from its current value.")
        sc["fraud_status"] = "CLEARED"
    touch(sc)
    return object_response(public(sc))


@app.route("/assignments/<aid>/submit", methods=["POST"])
def submit_assignment(aid):
    caller = auth_and_roles({"Shopper"})
    a = L.get_assignment(aid)
    _shopper_owns(caller, a)
    if a["status"] != "IN_FIELD":
        raise err("ERR_INVALID_STATE", "Assignment is not IN_FIELD.")
    if not _clock_within_due(a):
        raise err("ERR_INVALID_STATE", "Past due_at.")
    script = db.scripts[a["script_id"]]
    sc = S.get_scorecard_for_assignment(aid)
    # Evidence completeness -> ERR_EVIDENCE_INCOMPLETE.
    approved_photos = [
        e for e in S.evidence_for_assignment(aid)
        if e["kind"] == "PHOTO" and e["review_status"] == "APPROVED"
    ]
    if len(approved_photos) < script["required_photo_count"]:
        raise err("ERR_EVIDENCE_INCOMPLETE", "Too few APPROVED photos.")
    if script["receipt_required"]:
        approved_receipts = [
            e for e in S.evidence_for_assignment(aid)
            if e["kind"] == "RECEIPT" and e["review_status"] == "APPROVED"
        ]
        if len(approved_receipts) < 1:
            raise err("ERR_EVIDENCE_INCOMPLETE", "Missing required APPROVED receipt.")
    if sc is None:
        raise err("ERR_EVIDENCE_INCOMPLETE", "No scorecard exists.")

    # Side effects.
    a["status"] = "SUBMITTED"
    a["submission_count"] = a["submission_count"] + 1
    a["claimed_out_of_pocket_cents"] = sum(
        e["receipt_amount_cents"] for e in S.evidence_for_assignment(aid)
        if e["kind"] == "RECEIPT" and e["review_status"] == "APPROVED"
    )
    a["reimbursable_cents"] = S.provisional_reimbursable(a, script)
    touch(a)

    sc["estimated_score"] = S.compute_estimated_score(a, script, sc)
    touch(sc)
    return object_response(public(a))


@app.route("/assignments/<aid>/validate", methods=["POST"])
def validate_assignment(aid):
    caller = auth_and_roles({"QaValidator"})
    a = L.get_assignment(aid)
    if a["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Assignment is not SUBMITTED.")
    sc = S.get_scorecard_for_assignment(aid)
    if sc is not None and sc["fraud_status"] == "FRAUD_HOLD":
        raise err("ERR_INVALID_STATE", "ScoreCard is on FRAUD_HOLD.")
    shopper = db.shoppers[a["shopper_id"]]
    if shopper["status"] == "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Shopper is SUSPENDED.")
    script = db.scripts[a["script_id"]]
    wave = db.waves[a["wave_id"]]
    S.settle_validation(a, script, shopper, wave, sc, caller.user_id)
    S.adjust_open_assignment_count(shopper, -1)
    return object_response(public(a))


@app.route("/assignments/<aid>/request-revision", methods=["POST"])
def request_revision(aid):
    auth_and_roles({"QaValidator"})
    a = L.get_assignment(aid)
    if a["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Assignment is not SUBMITTED.")
    if a["submission_count"] > calc.MAX_REVISION_ROUNDS:
        raise err("ERR_REVISION_LIMIT_REACHED", "Revision limit reached.")
    a["status"] = "REVISION_REQUESTED"
    touch(a)
    for e in S.evidence_for_assignment(aid):
        if e["review_status"] == "APPROVED":
            e["review_status"] = "PENDING"
            touch(e)
    return object_response(public(a))


@app.route("/assignments/<aid>/resume", methods=["POST"])
def resume_assignment(aid):
    caller = auth_and_roles({"Shopper"})
    a = L.get_assignment(aid)
    _shopper_owns(caller, a)
    if a["status"] != "REVISION_REQUESTED":
        raise err("ERR_INVALID_STATE", "Assignment is not REVISION_REQUESTED.")
    if not _clock_within_due(a):
        raise err("ERR_INVALID_STATE", "Past due_at.")
    a["status"] = "IN_FIELD"
    touch(a)
    return object_response(public(a))


@app.route("/assignments/<aid>/reject", methods=["POST"])
def reject_assignment(aid):
    caller = auth_and_roles({"QaValidator"})
    a = L.get_assignment(aid)
    if a["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Assignment is not SUBMITTED.")
    a["status"] = "REJECTED"
    a["validated_by_user_id"] = caller.user_id
    a["reimbursable_cents"] = 0
    a["shopper_fee_cents"] = 0
    touch(a)
    shopper = db.shoppers[a["shopper_id"]]
    S.adjust_reliability(shopper, -calc.REJECT_RELIABILITY_PENALTY)
    S.adjust_open_assignment_count(shopper, -1)
    return object_response(public(a))


@app.route("/assignments/<aid>/cancel", methods=["POST"])
def cancel_assignment(aid):
    caller = auth_and_roles({"ClientManager", "PlatformAdmin"})
    a = L.get_assignment(aid)
    if caller.role == "ClientManager":
        wave = db.waves[a["wave_id"]]
        check_client_owner(caller, wave["client_id"])
    if a["status"] not in ("ASSIGNED", "IN_FIELD", "REVISION_REQUESTED"):
        raise err("ERR_INVALID_STATE", "Assignment cannot be cancelled from its current state.")
    # OCC (PRD 2.7): expected_assignment_version is mandatory.
    body = V.get_body()
    if "expected_assignment_version" not in body:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_assignment_version.")
    expected = body["expected_assignment_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_assignment_version must be an integer.")
    if expected != a["version"]:
        raise err("ERR_STALE_ASSIGNMENT_VERSION", "Stale assignment version.")
    prev_status = a["status"]
    a["status"] = "CANCELLED"
    touch(a)
    if prev_status in ("IN_FIELD", "REVISION_REQUESTED"):
        shopper = db.shoppers[a["shopper_id"]]
        S.adjust_open_assignment_count(shopper, -1)
    return object_response(public(a))


@app.route("/assignments/<aid>/sweep-deadline", methods=["POST"])
def sweep_deadline(aid):
    auth_and_roles({"PlatformAdmin"})
    a = L.get_assignment(aid)
    if a["status"] not in ("ASSIGNED", "IN_FIELD", "REVISION_REQUESTED"):
        raise err("ERR_INVALID_STATE", "Assignment is not in a sweepable state.")
    if not (db.clock > parse_iso(a["due_at"])):
        raise err("ERR_INVALID_STATE", "Assignment is not past due_at.")
    prev_status = a["status"]
    a["status"] = "EXPIRED"
    touch(a)
    shopper = db.shoppers[a["shopper_id"]]
    S.adjust_reliability(shopper, -calc.NO_SHOW_RELIABILITY_PENALTY)
    if prev_status in ("IN_FIELD", "REVISION_REQUESTED"):
        S.adjust_open_assignment_count(shopper, -1)
    return object_response(public(a))


# --------------------------------------------------------------------------- #
# Disputes
# --------------------------------------------------------------------------- #
@app.route("/assignments/<aid>/disputes", methods=["POST"])
def open_dispute(aid):
    caller = auth_and_roles({"Shopper", "ClientManager"})
    a = L.get_assignment(aid)
    if caller.role == "Shopper":
        _shopper_owns(caller, a)
    else:  # ClientManager
        wave = db.waves[a["wave_id"]]
        check_client_owner(caller, wave["client_id"])
    body = V.get_body()
    reason = V.require_enum(body, "reason",
                            {"REJECTION_APPEAL", "SCORE_CHALLENGE", "REIMBURSE_SHORTFALL"})
    if a["status"] not in ("VALIDATED", "REJECTED"):
        raise err("ERR_INVALID_STATE", "Assignment must be VALIDATED or REJECTED to dispute.")
    # At most one live dispute per assignment.
    for d in db.disputes.values():
        if d["assignment_id"] == aid and d["status"] in ("UNDER_REVIEW", "COUNTERED"):
            raise err("ERR_DISPUTE_ALREADY_OPEN", "A dispute is already open on this assignment.")
    opened_by_role = "SHOPPER" if caller.role == "Shopper" else "CLIENT"
    rec = {
        "assignment_id": aid,
        "opened_by_role": opened_by_role,
        "reason": reason,
        "round_index": 1,
        "status": "UNDER_REVIEW",
    }
    stamp_create(rec)
    db.disputes[rec["id"]] = rec
    return object_response(public(rec), status=201)


@app.route("/assignments/<aid>/disputes", methods=["GET"])
def list_disputes(aid):
    caller = auth_and_roles(
        {"Shopper", "ClientManager", "QaValidator", "FinanceOfficer", "PlatformAdmin"})
    a = L.get_assignment(aid)
    if caller.role == "Shopper" and caller.user_id != a["shopper_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Shopper may only read their own disputes.")
    if caller.role == "ClientManager":
        wave = db.waves[a["wave_id"]]
        check_client_owner(caller, wave["client_id"])
    limit, offset = V.pagination()
    items = list_sorted([d for d in db.disputes.values() if d["assignment_id"] == aid])
    page, total = V.paginate(items, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/disputes/<did>/counter", methods=["POST"])
def counter_dispute(did):
    auth_and_roles({"QaValidator"})
    d = L.get_dispute(did)
    if d["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Dispute is not UNDER_REVIEW.")
    if d["round_index"] >= calc.MAX_DISPUTE_ROUNDS:
        raise err("ERR_DISPUTE_ROUNDS_EXHAUSTED", "Dispute rounds exhausted.")
    d["status"] = "COUNTERED"
    touch(d)
    return object_response(public(d))


@app.route("/disputes/<did>/respond", methods=["POST"])
def respond_dispute(did):
    caller = auth_and_roles({"Shopper"})
    d = L.get_dispute(did)
    a = db.assignments[d["assignment_id"]]
    if caller.user_id != a["shopper_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Shopper does not own the parent assignment.")
    if d["status"] != "COUNTERED":
        raise err("ERR_INVALID_STATE", "Dispute is not COUNTERED.")
    d["round_index"] = d["round_index"] + 1
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return object_response(public(d))


@app.route("/disputes/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    auth_and_roles({"FinanceOfficer"})
    d = L.get_dispute(did)
    body = V.get_body()
    decision = V.require_enum(body, "decision", {"UPHOLD", "OVERTURN"})
    if d["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Dispute is not UNDER_REVIEW.")
    a = db.assignments[d["assignment_id"]]

    if decision == "UPHOLD":
        d["status"] = "UPHELD"
        touch(d)
        return object_response(public(d))

    # OVERTURN: requires parent assignment in the right state per reason.
    reason = d["reason"]
    if reason == "REJECTION_APPEAL":
        if a["status"] != "REJECTED":
            raise err("ERR_INVALID_STATE", "REJECTION_APPEAL overturn requires a REJECTED assignment.")
    else:  # SCORE_CHALLENGE / REIMBURSE_SHORTFALL
        if a["status"] != "VALIDATED":
            raise err("ERR_INVALID_STATE",
                      "SCORE_CHALLENGE/REIMBURSE_SHORTFALL overturn requires a VALIDATED assignment.")

    d["status"] = "OVERTURNED"
    touch(d)

    script = db.scripts[a["script_id"]]
    wave = db.waves[a["wave_id"]]
    shopper = db.shoppers[a["shopper_id"]]
    sc = S.get_scorecard_for_assignment(a["id"])

    if reason == "REJECTION_APPEAL":
        # Cascade A: re-validate the REJECTED assignment.
        S.settle_validation(a, script, shopper, wave, sc, a.get("validated_by_user_id"))
        S.adjust_reliability(shopper, calc.REJECT_RELIABILITY_PENALTY)  # restore, capped 100
    else:
        # Cascade B: re-price the final reimbursable & update the ACCRUED reimbursement.
        a["reimbursable_cents"] = S.final_reimbursable(a, script)
        touch(a)
        reimb = S.reimbursement_for_assignment(a["id"])
        if reimb is not None:
            reimb["amount_cents"] = a["reimbursable_cents"] + a["shopper_fee_cents"]
            touch(reimb)
            # If already BATCHED, recompute the batch gross.
            if reimb["status"] == "BATCHED" and reimb.get("payout_batch_id"):
                batch = db.payout_batches.get(reimb["payout_batch_id"])
                if batch is not None:
                    batch["gross_amount_cents"] = sum(
                        r["amount_cents"] for r in db.reimbursements.values()
                        if r.get("payout_batch_id") == batch["id"] and r["status"] == "BATCHED"
                    )
                    touch(batch)
    return object_response(public(d))


@app.route("/disputes/<did>/withdraw", methods=["POST"])
def withdraw_dispute(did):
    caller = auth_and_roles({"Shopper"})
    d = L.get_dispute(did)
    a = db.assignments[d["assignment_id"]]
    if d["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Dispute is not UNDER_REVIEW.")
    if d["opened_by_role"] != "SHOPPER":
        raise err("ERR_NOT_RESOURCE_OWNER", "Only the opening shopper may withdraw.")
    if caller.user_id != a["shopper_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Shopper does not own the parent assignment.")
    d["status"] = "WITHDRAWN"
    touch(d)
    return object_response(public(d))


# --------------------------------------------------------------------------- #
# Payouts
# --------------------------------------------------------------------------- #
@app.route("/payout-batches", methods=["POST"])
def create_payout_batch():
    caller = auth_and_roles({"FinanceOfficer"})
    body = V.get_body()
    shopper_id = V.require_str(body, "shopper_id")
    if "reimbursement_ids" not in body or not isinstance(body["reimbursement_ids"], list):
        raise err("ERR_INVALID_REQUEST", "reimbursement_ids must be a list.")
    reimbursement_ids = body["reimbursement_ids"]
    for rid in reimbursement_ids:
        if not isinstance(rid, str):
            raise err("ERR_INVALID_REQUEST", "reimbursement_ids must be strings.")

    shopper = L.get_shopper(shopper_id)
    # Existence of each reimbursement -> ERR_NOT_FOUND.
    reimbs = []
    for rid in reimbursement_ids:
        reimbs.append(L.get_or_404(db.reimbursements, rid))

    # Segregation of duties: officer X-User-ID != validated_by_user_id of any
    # included assignment (PRD 2.8).
    for r in reimbs:
        a = db.assignments[r["assignment_id"]]
        if caller.user_id == a.get("validated_by_user_id"):
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "FinanceOfficer cannot batch a reimbursement they validated.")

    # Each must currently be ACCRUED -> ERR_REIMBURSEMENT_NOT_ACCRUED.
    for r in reimbs:
        if r["status"] != "ACCRUED":
            raise err("ERR_REIMBURSEMENT_NOT_ACCRUED", "Reimbursement is not ACCRUED.")

    gross = sum(r["amount_cents"] for r in reimbs)
    batch = {
        "shopper_id": shopper_id,
        "tax_year": db.clock.year,
        "gross_amount_cents": gross,
        "requires_1099": False,
        "status": "OPEN",
    }
    stamp_create(batch)
    db.payout_batches[batch["id"]] = batch

    for r in reimbs:
        r["status"] = "BATCHED"
        r["payout_batch_id"] = batch["id"]
        touch(r)
    return object_response(public(batch), status=201)


@app.route("/payout-batches/<bid>", methods=["GET"])
def get_payout_batch_ep(bid):
    auth_and_roles({"FinanceOfficer", "PlatformAdmin"})
    batch = L.get_payout_batch(bid)
    return object_response(public(batch))


@app.route("/payout-batches", methods=["GET"])
def list_payout_batches():
    auth_and_roles({"FinanceOfficer", "PlatformAdmin"})
    limit, offset = V.pagination()
    items = list(db.payout_batches.values())
    shopper_id = request.args.get("shopper_id")
    if shopper_id is not None:
        items = [b for b in items if b["shopper_id"] == shopper_id]
    items = list_sorted(items)
    page, total = V.paginate(items, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/payout-batches/<bid>/reimbursements", methods=["GET"])
def list_batch_reimbursements(bid):
    auth_and_roles({"FinanceOfficer", "PlatformAdmin"})
    L.get_payout_batch(bid)
    limit, offset = V.pagination()
    items = list_sorted([r for r in db.reimbursements.values() if r.get("payout_batch_id") == bid])
    page, total = V.paginate(items, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/shoppers/<sid>/reimbursements", methods=["GET"])
def list_shopper_reimbursements(sid):
    caller = auth_and_roles({"FinanceOfficer", "PlatformAdmin", "Shopper"})
    L.get_shopper(sid)
    if caller.role == "Shopper" and caller.user_id != sid:
        raise err("ERR_NOT_RESOURCE_OWNER", "Shopper may only read their own reimbursements.")
    limit, offset = V.pagination()
    items = [r for r in db.reimbursements.values() if r["shopper_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = list_sorted(items)
    page, total = V.paginate(items, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/assignments/<aid>/reimbursement", methods=["GET"])
def list_assignment_reimbursement(aid):
    caller = auth_and_roles({"FinanceOfficer", "PlatformAdmin", "QaValidator", "Shopper"})
    a = L.get_assignment(aid)
    if caller.role == "Shopper" and caller.user_id != a["shopper_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Shopper may only read their own reimbursement.")
    limit, offset = V.pagination()
    items = list_sorted([r for r in db.reimbursements.values() if r["assignment_id"] == aid])
    page, total = V.paginate(items, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/payout-batches/<bid>/pay", methods=["POST"])
def pay_batch(bid):
    caller = auth_and_roles({"FinanceOfficer"})
    batch = L.get_payout_batch(bid)
    if batch["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Batch is not OPEN.")
    members = [r for r in db.reimbursements.values() if r.get("payout_batch_id") == bid]

    # Segregation of duties at pay time (PRD 2.8).
    for r in members:
        a = db.assignments[r["assignment_id"]]
        if caller.user_id == a.get("validated_by_user_id"):
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "FinanceOfficer cannot pay a reimbursement they validated.")

    # Every member reimbursement must still be BATCHED (none reversed).
    for r in members:
        if r["status"] != "BATCHED":
            raise err("ERR_INVALID_STATE", "A member reimbursement is no longer BATCHED.")

    shopper = db.shoppers[batch["shopper_id"]]

    # Recompute requires_1099 at pay time (thousand_99_check).
    prior_ytd = shopper["ytd_paid_cents"]
    requires_1099 = calc.crosses_1099(prior_ytd, batch["gross_amount_cents"])

    # 1099 gate (PRD 2.8): requires_1099 demands tax_id_on_file true.
    if requires_1099 and not shopper["tax_id_on_file"]:
        raise err("ERR_TAX_ID_REQUIRED", "Payee tax_id_on_file is required for a 1099 batch.")

    batch["status"] = "PAID"
    batch["requires_1099"] = requires_1099
    touch(batch)
    for r in members:
        r["status"] = "PAID"
        touch(r)
    shopper["ytd_paid_cents"] = shopper["ytd_paid_cents"] + batch["gross_amount_cents"]
    touch(shopper)
    return object_response(public(batch))


@app.route("/payout-batches/<bid>/void", methods=["POST"])
def void_batch(bid):
    auth_and_roles({"FinanceOfficer"})
    batch = L.get_payout_batch(bid)
    if batch["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Batch is not OPEN.")
    batch["status"] = "VOIDED"
    touch(batch)
    for r in db.reimbursements.values():
        if r.get("payout_batch_id") == bid:
            r["status"] = "ACCRUED"
            r["payout_batch_id"] = None
            touch(r)
    return object_response(public(batch))


# --------------------------------------------------------------------------- #
# Health / entrypoint
# --------------------------------------------------------------------------- #
@app.route("/", methods=["GET"])
def health():
    return object_response({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
