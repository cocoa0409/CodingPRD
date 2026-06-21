import os
from datetime import datetime, timezone
from flask import Flask, request

import errors
from errors import ApiError, err
from store import STORE
import domain
from domain import (parse_date, stamp_new, touch, days_between, date_plus,
                    product_of_lot, antigen_of_immunization, mandated_antigens,
                    compute_dose_validity, reconcile_lot, create_evaluation,
                    latest_evaluation, recompute_latest_evaluation,
                    revoke_certs_if_dropped, has_contraindication)
import serializers as S
import response as R
from auth import get_identity, require_roles

app = Flask(__name__)


# -------------------------------------------------------------------
# Error handling
# -------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(e):
    return R.error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return R.error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return R.error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return R.error_response("ERR_INVALID_REQUEST", str(e), 400)


# -------------------------------------------------------------------
# Request helpers
# -------------------------------------------------------------------

def body():
    if request.data and len(request.data) > 0:
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None
        if data is None:
            raise err(errors.ERR_INVALID_REQUEST, "Invalid JSON body.")
        if not isinstance(data, dict):
            raise err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object.")
        return data
    return {}


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {f}")


def pagination():
    limit = request.args.get("limit", "10")
    offset = request.args.get("offset", "0")
    try:
        limit = int(limit)
        offset = int(offset)
    except (ValueError, TypeError):
        raise err(errors.ERR_INVALID_REQUEST, "Invalid pagination parameter.")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset, serializer):
    total = len(items)
    window = items[offset:offset + limit]
    return R.list_response([serializer(x) for x in window], limit, offset, total)


def sort_created(items):
    return sorted(items, key=lambda x: (x["created_at"], x["_seq"]))


# Existence lookups (raise ERR_NOT_FOUND)

def get_or_404(coll, _id):
    obj = coll.get(_id)
    if obj is None:
        raise err(errors.ERR_NOT_FOUND, "Resource not found.")
    return obj


# -------------------------------------------------------------------
# Clock (test-driving)
# -------------------------------------------------------------------

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar"])
    data = body()
    require_fields(data, ["to_iso8601"])
    raw = data["to_iso8601"]
    if not isinstance(raw, str):
        raise err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be a string.")
    s = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(errors.ERR_INVALID_REQUEST, "Invalid ISO8601 instant.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    STORE.clock.set_utc(dt.astimezone(timezone.utc))
    return R.ok({})


# -------------------------------------------------------------------
# Patients
# -------------------------------------------------------------------

@app.route("/patients", methods=["POST"])
def create_patient():
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk"])
    data = body()
    require_fields(data, ["full_name", "date_of_birth", "state_code"])
    full_name = data["full_name"]
    dob_raw = data["date_of_birth"]
    state_code = data["state_code"]
    if not isinstance(full_name, str) or not isinstance(dob_raw, str) or not isinstance(state_code, str):
        raise err(errors.ERR_INVALID_REQUEST, "Invalid field type.")
    dob = parse_date(dob_raw)
    if dob is None:
        raise err(errors.ERR_INVALID_REQUEST, "date_of_birth must be a valid ISO date.")
    if dob > STORE.clock.today_date():
        raise err(errors.ERR_INVALID_REQUEST, "date_of_birth cannot be after the current clock date.")
    if not (len(state_code) == 2 and state_code.isalpha() and state_code.isupper()):
        raise err(errors.ERR_INVALID_REQUEST, "state_code must be two uppercase letters.")

    pid = STORE.new_id()
    p = stamp_new({
        "id": pid,
        "full_name": full_name,
        "date_of_birth": dob_raw,
        "state_code": state_code,
        "schedule_status": "UP_TO_DATE",
        "active_certificate_id": None,
    })
    STORE.patients[pid] = p
    return R.created(S.ser_patient(p))


@app.route("/patients/<pid>", methods=["GET"])
def get_patient(pid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk", "Provider"])
    p = get_or_404(STORE.patients, pid)
    return R.ok(S.ser_patient(p))


@app.route("/patients", methods=["GET"])
def list_patients():
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk"])
    limit, offset = pagination()
    items = list(STORE.patients.values())
    state = request.args.get("state_code")
    if state is not None:
        items = [p for p in items if p["state_code"] == state]
    return paginate(sort_created(items), limit, offset, S.ser_patient)


@app.route("/patients/<pid>/immunizations", methods=["GET"])
def list_patient_immunizations(pid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk", "Provider"])
    get_or_404(STORE.patients, pid)
    limit, offset = pagination()
    items = [i for i in STORE.immunizations.values() if i["patient_id"] == pid]
    return paginate(sort_created(items), limit, offset, S.ser_immunization)


@app.route("/patients/<pid>/allergy-records", methods=["GET"])
def list_patient_allergies(pid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk", "Provider"])
    get_or_404(STORE.patients, pid)
    limit, offset = pagination()
    items = [a for a in STORE.allergy_records.values() if a["patient_id"] == pid]
    return paginate(sort_created(items), limit, offset, S.ser_allergy)


@app.route("/patients/<pid>/evaluations", methods=["GET"])
def list_patient_evaluations(pid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk"])
    get_or_404(STORE.patients, pid)
    limit, offset = pagination()
    items = [e for e in STORE.evaluations.values() if e["patient_id"] == pid]
    return paginate(sort_created(items), limit, offset, S.ser_evaluation)


@app.route("/patients/<pid>/certificates", methods=["GET"])
def list_patient_certificates(pid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk"])
    get_or_404(STORE.patients, pid)
    limit, offset = pagination()
    items = [c for c in STORE.certificates.values() if c["patient_id"] == pid]
    return paginate(sort_created(items), limit, offset, S.ser_certificate)


# -------------------------------------------------------------------
# Providers
# -------------------------------------------------------------------

@app.route("/providers", methods=["POST"])
def create_provider():
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar"])
    data = body()
    require_fields(data, ["name", "vfc_pin"])
    name = data["name"]
    vfc_pin = data["vfc_pin"]
    if not isinstance(name, str) or not isinstance(vfc_pin, str) or vfc_pin == "":
        raise err(errors.ERR_INVALID_REQUEST, "Invalid name or vfc_pin.")
    apc = data.get("authorized_product_codes", [])
    if apc is None:
        apc = []
    if not isinstance(apc, list):
        raise err(errors.ERR_INVALID_REQUEST, "authorized_product_codes must be an array.")
    status = data.get("status", "ENROLLED")
    if status not in ("ENROLLED", "SUSPENDED"):
        raise err(errors.ERR_INVALID_REQUEST, "Invalid status.")

    for p in STORE.providers.values():
        if p["vfc_pin"] == vfc_pin:
            raise err(errors.ERR_DUPLICATE, "Duplicate vfc_pin.")

    pid = STORE.new_id()
    p = stamp_new({
        "id": pid,
        "name": name,
        "vfc_pin": vfc_pin,
        "authorized_product_codes": list(apc),
        "status": status,
    })
    STORE.providers[pid] = p
    return R.created(S.ser_provider(p))


@app.route("/providers/<pid>", methods=["GET"])
def get_provider(pid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "Provider"])
    p = get_or_404(STORE.providers, pid)
    return R.ok(S.ser_provider(p))


# -------------------------------------------------------------------
# Vaccine products
# -------------------------------------------------------------------

@app.route("/products", methods=["POST"])
def create_product():
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar"])
    data = body()
    require_fields(data, ["product_code", "antigen", "doses_in_series",
                          "min_age_days", "recommended_age_days", "min_interval_days"])
    product_code = data["product_code"]
    antigen = data["antigen"]
    if not isinstance(product_code, str) or product_code == "" or not isinstance(antigen, str):
        raise err(errors.ERR_INVALID_REQUEST, "Invalid product_code or antigen.")

    def _int(name, field):
        v = data[field]
        if isinstance(v, bool) or not isinstance(v, int):
            raise err(errors.ERR_INVALID_REQUEST, f"{field} must be an integer.")
        return v

    doses_in_series = _int("doses_in_series", "doses_in_series")
    min_age_days = _int("min_age_days", "min_age_days")
    recommended_age_days = _int("recommended_age_days", "recommended_age_days")
    min_interval_days = _int("min_interval_days", "min_interval_days")
    grace = data.get("grace_period_days", 4)
    if grace is None:
        grace = 4
    if isinstance(grace, bool) or not isinstance(grace, int):
        raise err(errors.ERR_INVALID_REQUEST, "grace_period_days must be an integer.")
    status = data.get("status", "ACTIVE")
    if status not in ("ACTIVE", "RETIRED"):
        raise err(errors.ERR_INVALID_REQUEST, "Invalid status.")

    if doses_in_series < 1:
        raise err(errors.ERR_INVALID_REQUEST, "doses_in_series must be >= 1.")
    if min_age_days < 0 or min_interval_days < 0 or grace < 0:
        raise err(errors.ERR_INVALID_REQUEST, "Day fields must be >= 0.")
    # cross-field constraints -> ERR_VALIDATION
    if recommended_age_days < min_age_days:
        raise err(errors.ERR_VALIDATION, "recommended_age_days must be >= min_age_days.")

    for p in STORE.products.values():
        if p["product_code"] == product_code:
            raise err(errors.ERR_DUPLICATE, "Duplicate product_code.")

    pid = STORE.new_id()
    p = stamp_new({
        "id": pid,
        "product_code": product_code,
        "antigen": antigen,
        "doses_in_series": doses_in_series,
        "min_age_days": min_age_days,
        "recommended_age_days": recommended_age_days,
        "min_interval_days": min_interval_days,
        "grace_period_days": grace,
        "status": status,
    })
    STORE.products[pid] = p
    return R.created(S.ser_product(p))


@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "Provider", "RecordsClerk"])
    p = get_or_404(STORE.products, pid)
    return R.ok(S.ser_product(p))


# -------------------------------------------------------------------
# Vaccine lots
# -------------------------------------------------------------------

@app.route("/lots", methods=["POST"])
def create_lot():
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar"])
    data = body()
    require_fields(data, ["product_id", "lot_number", "received_date",
                          "expiration_date", "doses_total"])
    product_id = data["product_id"]
    lot_number = data["lot_number"]
    received_date = data["received_date"]
    expiration_date = data["expiration_date"]
    doses_total = data["doses_total"]

    if not isinstance(lot_number, str) or lot_number == "":
        raise err(errors.ERR_INVALID_REQUEST, "Invalid lot_number.")
    if isinstance(doses_total, bool) or not isinstance(doses_total, int):
        raise err(errors.ERR_INVALID_REQUEST, "doses_total must be an integer.")
    rd = parse_date(received_date) if isinstance(received_date, str) else None
    ed = parse_date(expiration_date) if isinstance(expiration_date, str) else None
    if rd is None or ed is None:
        raise err(errors.ERR_INVALID_REQUEST, "Invalid date.")
    if doses_total < 1:
        raise err(errors.ERR_INVALID_REQUEST, "doses_total must be >= 1.")

    # existence of product (existence priority)
    get_or_404(STORE.products, product_id)

    # cross-field constraint -> ERR_VALIDATION
    if not (ed > rd):
        raise err(errors.ERR_VALIDATION, "expiration_date must be strictly after received_date.")

    for l in STORE.lots.values():
        if l["product_id"] == product_id and l["lot_number"] == lot_number:
            raise err(errors.ERR_DUPLICATE, "Duplicate lot_number within product.")

    lid = STORE.new_id()
    l = stamp_new({
        "id": lid,
        "product_id": product_id,
        "lot_number": lot_number,
        "received_date": received_date,
        "expiration_date": expiration_date,
        "doses_total": doses_total,
        "administered_count": 0,
        "status": "AVAILABLE",
    })
    STORE.lots[lid] = l
    return R.created(S.ser_lot(l))


@app.route("/lots/<lid>", methods=["GET"])
def get_lot(lid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "Provider"])
    l = get_or_404(STORE.lots, lid)
    return R.ok(S.ser_lot(l))


@app.route("/lots", methods=["GET"])
def list_lots():
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "Provider"])
    limit, offset = pagination()
    items = list(STORE.lots.values())
    product_id = request.args.get("product_id")
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    return paginate(sort_created(items), limit, offset, S.ser_lot)


@app.route("/lots/<lid>/immunizations", methods=["GET"])
def list_lot_immunizations(lid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "Provider"])
    get_or_404(STORE.lots, lid)
    limit, offset = pagination()
    items = [i for i in STORE.immunizations.values() if i["lot_id"] == lid]
    return paginate(sort_created(items), limit, offset, S.ser_immunization)


# -------------------------------------------------------------------
# Lot recalls
# -------------------------------------------------------------------

@app.route("/lots/<lid>/recalls", methods=["POST"])
def create_recall(lid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar"])
    lot = get_or_404(STORE.lots, lid)
    data = body()
    require_fields(data, ["reason"])
    reason = data["reason"]
    if not isinstance(reason, str):
        raise err(errors.ERR_INVALID_REQUEST, "reason must be a string.")

    # Set lot RECALLED
    lot["status"] = "RECALLED"
    touch(lot)

    rid = STORE.new_id()
    recall = stamp_new({
        "id": rid,
        "lot_id": lid,
        "reason": reason,
        "invalidated_count": 0,
        "status": "ISSUED",
        "_struck_ids": [],
    })
    STORE.recalls[rid] = recall

    # Cascade hop 1: invalidate RECORDED/AMENDED immunizations on this lot
    affected_patients = set()
    struck = []
    for imm in STORE.immunizations.values():
        if imm["lot_id"] == lid and imm["status"] in ("RECORDED", "AMENDED"):
            imm["status"] = "INVALIDATED"
            imm["validity"] = "INVALID_RECALL"
            touch(imm)
            struck.append(imm["id"])
            affected_patients.add(imm["patient_id"])
    recall["_struck_ids"] = struck
    recall["invalidated_count"] = len(struck)

    # reconcile lot inventory (decrement for each struck dose)
    reconcile_lot(lid)

    # recompute validity/dose_number for affected patients' same-antigen series
    for pid in affected_patients:
        for ag in mandated_antigens():
            compute_dose_validity(pid, ag)
        # also recompute antigens that may not be "mandated" but have doses
        _recompute_all_patient_antigens(pid)

    # Cascade hop 2 & 3: recompute evaluations, revoke certs
    for pid in affected_patients:
        overall = recompute_latest_evaluation(pid)
        if overall is not None:
            revoke_certs_if_dropped(pid, overall)

    return R.created(S.ser_recall(recall))


def _recompute_all_patient_antigens(pid):
    """Recompute validity for every antigen the patient has doses in."""
    antigens = set()
    for imm in STORE.immunizations.values():
        if imm["patient_id"] == pid and imm["status"] != "DELETED":
            ag = antigen_of_immunization(imm)
            if ag:
                antigens.add(ag)
    for ag in antigens:
        compute_dose_validity(pid, ag)


@app.route("/lots/<lid>/recalls", methods=["GET"])
def list_recalls(lid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "Provider"])
    get_or_404(STORE.lots, lid)
    limit, offset = pagination()
    items = [r for r in STORE.recalls.values() if r["lot_id"] == lid]
    return paginate(sort_created(items), limit, offset, S.ser_recall)


@app.route("/lots/<lid>/recalls/<recall_id>/reverse", methods=["POST"])
def reverse_recall(lid, recall_id):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar"])
    lot = get_or_404(STORE.lots, lid)
    recall = get_or_404(STORE.recalls, recall_id)
    if recall["lot_id"] != lid:
        raise err(errors.ERR_NOT_FOUND, "Recall does not belong to this lot.")

    # state: recall must be ISSUED and lot still recalled by it
    if recall["status"] != "ISSUED" or lot["status"] != "RECALLED":
        raise err(errors.ERR_INVALID_STATE, "Recall is not in a reversible state.")

    # lot back to AVAILABLE
    lot["status"] = "AVAILABLE"
    touch(lot)

    affected_patients = set()
    for imm_id in recall["_struck_ids"]:
        imm = STORE.immunizations.get(imm_id)
        if imm and imm["status"] == "INVALIDATED" and imm["validity"] == "INVALID_RECALL":
            imm["status"] = "RECORDED"
            touch(imm)
            affected_patients.add(imm["patient_id"])

    # reconcile lot inventory (re-add restored doses)
    reconcile_lot(lid)

    # recompute validity & dose_number for affected patients
    for pid in affected_patients:
        _recompute_all_patient_antigens(pid)

    recall["status"] = "REVERSED"
    touch(recall)

    # recompute evaluations after restoration (per PRD recall reverse compensates)
    for pid in affected_patients:
        overall = recompute_latest_evaluation(pid)

    return R.ok(S.ser_recall(recall))


# -------------------------------------------------------------------
# Recording guardrails (shared by direct record & adjudication)
# -------------------------------------------------------------------

def _check_line_guardrails(patient, lot, provider, administered_date, strict_interval=False):
    """Run §3.3 ordered checks. Raises ApiError on the first failure.
    administered_date is a date object."""
    prod = product_of_lot(lot)
    # provider authorization
    if prod["product_code"] not in provider["authorized_product_codes"]:
        raise err(errors.ERR_PRODUCT_NOT_AUTHORIZED, "Provider not authorized for product.")
    # recall
    if lot["status"] == "RECALLED":
        raise err(errors.ERR_LOT_RECALLED, "Lot is recalled.")
    # expiry / window
    rd = parse_date(lot["received_date"])
    ed = parse_date(lot["expiration_date"])
    if administered_date < rd or administered_date > ed:
        raise err(errors.ERR_LOT_EXPIRED, "administered_date outside lot window.")
    # contraindication
    if has_contraindication(patient["id"], prod["antigen"]):
        raise err(errors.ERR_CONTRAINDICATED, "Patient contraindicated for antigen.")
    # strict interval guard (direct recordings only)
    if strict_interval:
        grace = prod["grace_period_days"]
        last_valid = _last_valid_date(patient["id"], prod["antigen"])
        if last_valid is not None and days_between(last_valid, administered_date) < (prod["min_interval_days"] - grace):
            raise err(errors.ERR_INTERVAL_TOO_SHORT, "Dose violates minimum interval.")
    # capacity
    if not (lot["administered_count"] < lot["doses_total"]):
        raise err(errors.ERR_LOT_DEPLETED, "Lot has no remaining capacity.")


def _last_valid_date(patient_id, antigen):
    valids = []
    for imm in STORE.immunizations.values():
        if (imm["patient_id"] == patient_id and imm["status"] != "DELETED"
                and imm["validity"] == "VALID" and antigen_of_immunization(imm) == antigen):
            valids.append(imm)
    if not valids:
        return None
    valids.sort(key=lambda d: (parse_date(d["administered_date"]), d["_seq"]))
    return parse_date(valids[-1]["administered_date"])


def _line_passes(patient, lot, provider, administered_date):
    """Like _check_line_guardrails but returns True/False (no strict interval) for adjudication."""
    try:
        _check_line_guardrails(patient, lot, provider, administered_date, strict_interval=False)
        return True
    except ApiError:
        return False


# -------------------------------------------------------------------
# Immunizations
# -------------------------------------------------------------------

@app.route("/immunizations", methods=["POST"])
def create_immunization():
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk"])
    data = body()
    require_fields(data, ["patient_id", "lot_id", "provider_id", "administered_date"])
    administered_date = data["administered_date"]
    if not isinstance(administered_date, str):
        raise err(errors.ERR_INVALID_REQUEST, "administered_date must be a string.")
    adm = parse_date(administered_date)
    if adm is None:
        raise err(errors.ERR_INVALID_REQUEST, "Invalid administered_date.")

    # existence (left to right per body order: patient, lot, provider)
    patient = get_or_404(STORE.patients, data["patient_id"])
    lot = get_or_404(STORE.lots, data["lot_id"])
    provider = get_or_404(STORE.providers, data["provider_id"])

    # guardrails (strict interval for direct recordings)
    _check_line_guardrails(patient, lot, provider, adm, strict_interval=True)

    prod = product_of_lot(lot)
    iid = STORE.new_id()
    imm = stamp_new({
        "id": iid,
        "patient_id": patient["id"],
        "lot_id": lot["id"],
        "provider_id": provider["id"],
        "report_id": None,
        "administered_date": administered_date,
        "dose_number": 1,
        "validity": "VALID",
        "status": "RECORDED",
    })
    STORE.immunizations[iid] = imm

    # compute validity & dose_number across same-antigen series
    compute_dose_validity(patient["id"], prod["antigen"])
    # increment lot inventory
    reconcile_lot(lot["id"])

    return R.created(S.ser_immunization(imm))


@app.route("/immunizations/<iid>", methods=["GET"])
def get_immunization(iid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk", "Provider"])
    imm = get_or_404(STORE.immunizations, iid)
    return R.ok(S.ser_immunization(imm))


@app.route("/immunizations/<iid>", methods=["PATCH"])
def patch_immunization(iid):
    _, role = get_identity()
    require_roles(role, ["RecordsClerk"])
    imm = get_or_404(STORE.immunizations, iid)
    data = body()
    require_fields(data, ["administered_date"])
    administered_date = data["administered_date"]
    if not isinstance(administered_date, str):
        raise err(errors.ERR_INVALID_REQUEST, "administered_date must be a string.")
    adm = parse_date(administered_date)
    if adm is None:
        raise err(errors.ERR_INVALID_REQUEST, "Invalid administered_date.")

    # state precondition
    if imm["status"] not in ("RECORDED", "AMENDED"):
        raise err(errors.ERR_INVALID_STATE, "Dose not in a correctable state.")

    lot = STORE.lots.get(imm["lot_id"])
    rd = parse_date(lot["received_date"])
    ed = parse_date(lot["expiration_date"])
    if adm < rd or adm > ed:
        raise err(errors.ERR_LOT_EXPIRED, "Corrected administered_date outside lot window.")

    imm["administered_date"] = administered_date
    imm["status"] = "AMENDED"
    touch(imm)

    prod = product_of_lot(lot)
    compute_dose_validity(imm["patient_id"], prod["antigen"])
    reconcile_lot(imm["lot_id"])

    return R.ok(S.ser_immunization(imm))


@app.route("/immunizations/<iid>", methods=["DELETE"])
def delete_immunization(iid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar"])
    imm = get_or_404(STORE.immunizations, iid)

    if imm["status"] not in ("RECORDED", "AMENDED"):
        raise err(errors.ERR_INVALID_STATE, "Dose not in a retractable state.")

    # adverse event block
    for ae in STORE.adverse_events.values():
        if ae["immunization_id"] == iid and ae["status"] in ("REPORTED", "UNDER_REVIEW", "CONFIRMED"):
            raise err(errors.ERR_ADVERSE_EVENT_BLOCKS_DELETE,
                      "Dose referenced by a non-dismissed adverse event.")

    lot = STORE.lots.get(imm["lot_id"])
    prod = product_of_lot(lot)
    imm["status"] = "DELETED"
    touch(imm)

    compute_dose_validity(imm["patient_id"], prod["antigen"])
    reconcile_lot(imm["lot_id"])

    return R.ok(S.ser_immunization(imm))


@app.route("/immunizations", methods=["GET"])
def list_immunizations():
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk", "Provider"])
    limit, offset = pagination()
    items = list(STORE.immunizations.values())
    for key in ("patient_id", "lot_id", "provider_id", "report_id"):
        v = request.args.get(key)
        if v is not None:
            items = [i for i in items if i[key] == v]
    return paginate(sort_created(items), limit, offset, S.ser_immunization)


# -------------------------------------------------------------------
# Allergy records
# -------------------------------------------------------------------

@app.route("/allergy-records", methods=["POST"])
def create_allergy():
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk"])
    data = body()
    require_fields(data, ["patient_id", "antigen"])
    antigen = data["antigen"]
    if not isinstance(antigen, str):
        raise err(errors.ERR_INVALID_REQUEST, "antigen must be a string.")
    severity = data.get("severity", "CONTRAINDICATED")
    if severity is None:
        severity = "CONTRAINDICATED"
    if severity not in ("CONTRAINDICATED", "PRECAUTION"):
        raise err(errors.ERR_INVALID_REQUEST, "Invalid severity.")

    patient = get_or_404(STORE.patients, data["patient_id"])

    aid = STORE.new_id()
    a = stamp_new({
        "id": aid,
        "patient_id": patient["id"],
        "antigen": antigen,
        "severity": severity,
        "origin": "MANUAL",
        "source_event_id": None,
    })
    STORE.allergy_records[aid] = a
    return R.created(S.ser_allergy(a))


@app.route("/allergy-records/<aid>", methods=["GET"])
def get_allergy(aid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk", "Provider"])
    a = get_or_404(STORE.allergy_records, aid)
    return R.ok(S.ser_allergy(a))


@app.route("/allergy-records", methods=["GET"])
def list_allergies():
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk", "Provider"])
    limit, offset = pagination()
    items = list(STORE.allergy_records.values())
    for key in ("patient_id", "source_event_id"):
        v = request.args.get(key)
        if v is not None:
            items = [a for a in items if a[key] == v]
    return paginate(sort_created(items), limit, offset, S.ser_allergy)


# -------------------------------------------------------------------
# Provider reports
# -------------------------------------------------------------------

@app.route("/provider-reports", methods=["POST"])
def create_report():
    _, role = get_identity()
    require_roles(role, ["Provider", "ImmunizationRegistrar"])
    data = body()
    require_fields(data, ["provider_id", "line_count"])
    line_count = data["line_count"]
    if isinstance(line_count, bool) or not isinstance(line_count, int):
        raise err(errors.ERR_INVALID_REQUEST, "line_count must be an integer.")
    if line_count < 1:
        raise err(errors.ERR_INVALID_REQUEST, "line_count must be >= 1.")

    provider = get_or_404(STORE.providers, data["provider_id"])

    rid = STORE.new_id()
    r = stamp_new({
        "id": rid,
        "provider_id": provider["id"],
        "line_count": line_count,
        "accepted_count": 0,
        "rejected_count": 0,
        "status": "DRAFT",
        "_lines": [],
    })
    STORE.provider_reports[rid] = r
    return R.created(S.ser_report(r))


@app.route("/provider-reports/<rid>/lines", methods=["POST"])
def add_report_line(rid):
    _, role = get_identity()
    require_roles(role, ["Provider", "ImmunizationRegistrar"])
    report = get_or_404(STORE.provider_reports, rid)
    data = body()
    require_fields(data, ["patient_id", "lot_id", "administered_date"])
    administered_date = data["administered_date"]
    if not isinstance(administered_date, str) or parse_date(administered_date) is None:
        raise err(errors.ERR_INVALID_REQUEST, "Invalid administered_date.")
    patient = get_or_404(STORE.patients, data["patient_id"])
    lot = get_or_404(STORE.lots, data["lot_id"])

    line = {
        "patient_id": patient["id"],
        "lot_id": lot["id"],
        "administered_date": administered_date,
    }
    report["_lines"].append(line)
    touch(report)
    return R.created(S.ser_report(report))


@app.route("/provider-reports/<rid>", methods=["GET"])
def get_report(rid):
    _, role = get_identity()
    require_roles(role, ["Provider", "ImmunizationRegistrar"])
    r = get_or_404(STORE.provider_reports, rid)
    return R.ok(S.ser_report(r))


@app.route("/provider-reports", methods=["GET"])
def list_reports():
    _, role = get_identity()
    require_roles(role, ["Provider", "ImmunizationRegistrar"])
    limit, offset = pagination()
    items = list(STORE.provider_reports.values())
    v = request.args.get("provider_id")
    if v is not None:
        items = [r for r in items if r["provider_id"] == v]
    return paginate(sort_created(items), limit, offset, S.ser_report)


@app.route("/provider-reports/<rid>/immunizations", methods=["GET"])
def list_report_immunizations(rid):
    _, role = get_identity()
    require_roles(role, ["Provider", "ImmunizationRegistrar"])
    get_or_404(STORE.provider_reports, rid)
    limit, offset = pagination()
    items = [i for i in STORE.immunizations.values() if i["report_id"] == rid]
    return paginate(sort_created(items), limit, offset, S.ser_immunization)


@app.route("/provider-reports/<rid>/submit", methods=["POST"])
def submit_report(rid):
    user_id, role = get_identity()
    require_roles(role, ["Provider"])
    report = get_or_404(STORE.provider_reports, rid)

    # state precondition
    if report["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "Report not in DRAFT.")

    provider = STORE.providers.get(report["provider_id"])
    # ownership: acting provider must be the report's provider
    if report["provider_id"] != user_id:
        raise err(errors.ERR_FORBIDDEN, "Provider may submit only its own reports.")

    # line count match
    if len(report["_lines"]) != report["line_count"]:
        raise err(errors.ERR_LINE_COUNT_MISMATCH, "Attached line count does not match line_count.")

    # provider enrolled
    if provider["status"] != "ENROLLED":
        raise err(errors.ERR_PROVIDER_SUSPENDED, "Provider is suspended.")

    report["status"] = "SUBMITTED"
    touch(report)
    return R.ok(S.ser_report(report))


@app.route("/provider-reports/<rid>/adjudicate", methods=["POST"])
def adjudicate_report(rid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar"])
    report = get_or_404(STORE.provider_reports, rid)

    if report["status"] != "SUBMITTED":
        raise err(errors.ERR_INVALID_STATE, "Report not in SUBMITTED.")

    provider = STORE.providers.get(report["provider_id"])

    # Determine per-line accept/reject. Capacity must account for accepted lines
    # earlier in the batch consuming lot inventory.
    consumed = {}  # lot_id -> provisional administered_count delta
    results = []  # (line, accepted)
    for line in report["_lines"]:
        patient = STORE.patients.get(line["patient_id"])
        lot = STORE.lots.get(line["lot_id"])
        adm = parse_date(line["administered_date"])
        accepted = False
        if patient and lot:
            # build a shallow view of the lot with provisional consumption
            view = dict(lot)
            view["administered_count"] = lot["administered_count"] + consumed.get(lot["id"], 0)
            accepted = _line_passes(patient, view, provider, adm)
        if accepted:
            consumed[lot["id"]] = consumed.get(lot["id"], 0) + 1
        results.append((line, accepted))

    accepted_lines = [ln for ln, ok in results if ok]
    rejected_lines = [ln for ln, ok in results if not ok]

    # materialize accepted lines
    affected_antigens = set()
    for line in accepted_lines:
        lot = STORE.lots.get(line["lot_id"])
        prod = product_of_lot(lot)
        iid = STORE.new_id()
        imm = stamp_new({
            "id": iid,
            "patient_id": line["patient_id"],
            "lot_id": line["lot_id"],
            "provider_id": report["provider_id"],
            "report_id": rid,
            "administered_date": line["administered_date"],
            "dose_number": 1,
            "validity": "VALID",
            "status": "RECORDED",
        })
        STORE.immunizations[iid] = imm
        affected_antigens.add((line["patient_id"], prod["antigen"]))

    # reconcile inventory and recompute validity for affected (patient, antigen)
    for lid in {ln["lot_id"] for ln in accepted_lines}:
        reconcile_lot(lid)
    for pid, ag in affected_antigens:
        compute_dose_validity(pid, ag)

    report["accepted_count"] = len(accepted_lines)
    report["rejected_count"] = len(rejected_lines)
    if not rejected_lines:
        report["status"] = "ACCEPTED"
    elif not accepted_lines:
        report["status"] = "REJECTED"
    else:
        report["status"] = "PARTIALLY_REJECTED"
    touch(report)
    return R.ok(S.ser_report(report))


# -------------------------------------------------------------------
# Adverse events (VAERS)
# -------------------------------------------------------------------

@app.route("/adverse-events", methods=["POST"])
def create_adverse():
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk", "Provider"])
    data = body()
    require_fields(data, ["immunization_id", "seriousness", "symptoms"])
    seriousness = data["seriousness"]
    symptoms = data["symptoms"]
    if seriousness not in ("SERIOUS", "NON_SERIOUS"):
        raise err(errors.ERR_INVALID_REQUEST, "Invalid seriousness.")
    if not isinstance(symptoms, str):
        raise err(errors.ERR_INVALID_REQUEST, "symptoms must be a string.")

    imm = get_or_404(STORE.immunizations, data["immunization_id"])

    aeid = STORE.new_id()
    ae = stamp_new({
        "id": aeid,
        "immunization_id": imm["id"],
        "patient_id": imm["patient_id"],
        "seriousness": seriousness,
        "symptoms": symptoms,
        "status": "REPORTED",
    })
    STORE.adverse_events[aeid] = ae
    return R.created(S.ser_adverse(ae))


@app.route("/adverse-events/<aeid>", methods=["GET"])
def get_adverse(aeid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk", "Provider"])
    ae = get_or_404(STORE.adverse_events, aeid)
    return R.ok(S.ser_adverse(ae))


@app.route("/adverse-events", methods=["GET"])
def list_adverse():
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk", "Provider"])
    limit, offset = pagination()
    items = list(STORE.adverse_events.values())
    for key in ("immunization_id", "patient_id"):
        v = request.args.get(key)
        if v is not None:
            items = [a for a in items if a[key] == v]
    return paginate(sort_created(items), limit, offset, S.ser_adverse)


@app.route("/adverse-events/<aeid>/review", methods=["POST"])
def review_adverse(aeid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar"])
    ae = get_or_404(STORE.adverse_events, aeid)
    if ae["status"] != "REPORTED":
        raise err(errors.ERR_INVALID_STATE, "Event not in REPORTED.")
    ae["status"] = "UNDER_REVIEW"
    touch(ae)
    return R.ok(S.ser_adverse(ae))


@app.route("/adverse-events/<aeid>/confirm", methods=["POST"])
def confirm_adverse(aeid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar"])
    ae = get_or_404(STORE.adverse_events, aeid)
    if ae["status"] != "UNDER_REVIEW":
        raise err(errors.ERR_INVALID_STATE, "Event not in UNDER_REVIEW.")

    ae["status"] = "CONFIRMED"
    touch(ae)

    if ae["seriousness"] == "SERIOUS":
        imm = STORE.immunizations.get(ae["immunization_id"])
        antigen = antigen_of_immunization(imm) if imm else None
        patient_id = ae["patient_id"]
        if antigen is not None:
            # only if no allergy record exists for that antigen
            exists = any(a["patient_id"] == patient_id and a["antigen"] == antigen
                         for a in STORE.allergy_records.values())
            if not exists:
                aid = STORE.new_id()
                a = stamp_new({
                    "id": aid,
                    "patient_id": patient_id,
                    "antigen": antigen,
                    "severity": "CONTRAINDICATED",
                    "origin": "ADVERSE_EVENT",
                    "source_event_id": ae["id"],
                })
                STORE.allergy_records[aid] = a
            # cascade hop 2 & 3: recompute evaluation, revoke certs
            overall = recompute_latest_evaluation(patient_id)
            if overall is not None:
                revoke_certs_if_dropped(patient_id, overall)

    return R.ok(S.ser_adverse(ae))


@app.route("/adverse-events/<aeid>/dismiss", methods=["POST"])
def dismiss_adverse(aeid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar"])
    ae = get_or_404(STORE.adverse_events, aeid)
    if ae["status"] not in ("REPORTED", "UNDER_REVIEW"):
        raise err(errors.ERR_INVALID_STATE, "Event not dismissable from current state.")
    ae["status"] = "DISMISSED"
    touch(ae)
    return R.ok(S.ser_adverse(ae))


# -------------------------------------------------------------------
# Schedule evaluations & certificates
# -------------------------------------------------------------------

@app.route("/patients/<pid>/evaluations", methods=["POST"])
def run_evaluation(pid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk"])
    patient = get_or_404(STORE.patients, pid)
    data = body()
    as_of_raw = data.get("as_of_date")
    if as_of_raw is None:
        as_of = STORE.clock.today_date()
    else:
        if not isinstance(as_of_raw, str):
            raise err(errors.ERR_INVALID_REQUEST, "as_of_date must be a string.")
        as_of = parse_date(as_of_raw)
        if as_of is None:
            raise err(errors.ERR_INVALID_REQUEST, "Invalid as_of_date.")

    ev = create_evaluation(pid, as_of)
    return R.created(S.ser_evaluation(ev))


@app.route("/evaluations/<eid>", methods=["GET"])
def get_evaluation(eid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk"])
    ev = get_or_404(STORE.evaluations, eid)
    return R.ok(S.ser_evaluation(ev))


@app.route("/patients/<pid>/certificates", methods=["POST"])
def issue_certificate(pid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar"])
    patient = get_or_404(STORE.patients, pid)
    data = body()
    require_fields(data, ["evaluation_id", "expected_patient_version"])
    epv = data["expected_patient_version"]
    if isinstance(epv, bool) or not isinstance(epv, int):
        raise err(errors.ERR_INVALID_REQUEST, "expected_patient_version must be an integer.")

    ev = get_or_404(STORE.evaluations, data["evaluation_id"])
    if ev["patient_id"] != pid:
        raise err(errors.ERR_NOT_FOUND, "Evaluation does not belong to patient.")

    # compliance check (priority 12) before OCC (priority 13)
    overall = ev["overall_status"]
    if overall not in ("UP_TO_DATE", "CONDITIONAL"):
        raise err(errors.ERR_NOT_COMPLIANT, "Evaluation is not compliant for issuance.")

    # OCC
    if epv != patient["version"]:
        raise err(errors.ERR_STALE_PATIENT_VERSION, "Stale patient version.")

    cert_type = "COMPLETE" if overall == "UP_TO_DATE" else "CONDITIONAL"

    # supersede prior ACTIVE certificate
    for c in STORE.certificates.values():
        if c["patient_id"] == pid and c["status"] == "ACTIVE":
            c["status"] = "SUPERSEDED"
            touch(c)

    cid = STORE.new_id()
    cert = stamp_new({
        "id": cid,
        "patient_id": pid,
        "evaluation_id": ev["id"],
        "certificate_type": cert_type,
        "status": "ACTIVE",
    })
    STORE.certificates[cid] = cert

    patient["active_certificate_id"] = cid
    touch(patient)

    return R.created(S.ser_certificate(cert))


@app.route("/certificates/<cid>", methods=["GET"])
def get_certificate(cid):
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk", "Provider"])
    c = get_or_404(STORE.certificates, cid)
    return R.ok(S.ser_certificate(c))


@app.route("/certificates", methods=["GET"])
def list_certificates():
    _, role = get_identity()
    require_roles(role, ["ImmunizationRegistrar", "RecordsClerk", "Provider"])
    limit, offset = pagination()
    items = list(STORE.certificates.values())
    for key in ("patient_id", "evaluation_id"):
        v = request.args.get(key)
        if v is not None:
            items = [c for c in items if c[key] == v]
    return paginate(sort_created(items), limit, offset, S.ser_certificate)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
