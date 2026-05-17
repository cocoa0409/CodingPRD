"""Authorization endpoints — PRD §3.4."""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..clock import diff_seconds, parse_iso
from ..errors import APIError
from ..helpers import (
    get_json_body,
    get_pagination_params,
    optional_field,
    paginate,
    require_field,
)
from ..responses import list_response, success_response
from ..services.calculations import (
    compute_supervision_ratio,
    recompute_authorization_consumption,
)
from ..services.lookups import (
    get_authorization,
    get_patient,
    get_treatment_plan,
)
from ..services.serialize import serialize_authorization, serialize_ledger_entry
from ..store import get_lock, get_store, stamp_create, stamp_update


bp = Blueprint("authorizations", __name__)


VALID_CPT_CODES = {"97151", "97153", "97155", "97156"}
MIN_WINDOW_DAYS = 90
MAX_WINDOW_DAYS = 366
MIN_APPROVED_UNITS = 1
MAX_APPROVED_UNITS = 4000


def _validate_window(effective_start: str, effective_end: str) -> None:
    start_dt = parse_iso(effective_start)
    end_dt = parse_iso(effective_end)
    if end_dt <= start_dt:
        raise APIError("ERR_VALIDATION", "effective_end must be strictly after effective_start")
    span_days = (end_dt - start_dt).total_seconds() / 86400.0
    if span_days < MIN_WINDOW_DAYS or span_days > MAX_WINDOW_DAYS:
        raise APIError("ERR_VALIDATION",
                       f"effective window must be in [{MIN_WINDOW_DAYS}, {MAX_WINDOW_DAYS}] days")


@bp.post("/patients/<patient_id>/authorizations")
@require_auth("ClinicAdmin")
def create_authorization(patient_id):
    body = get_json_body()
    with get_lock():
        patient = get_patient(patient_id)
        clinic = get_store().clinics[patient["clinic_id"]]
        store = get_store()

        treatment_plan_id = require_field(body, "treatment_plan_id")
        payer_name = require_field(body, "payer_name")
        cpt_code = require_field(body, "cpt_code")
        approved_units = require_field(body, "approved_units")
        effective_start = require_field(body, "effective_start")
        effective_end = require_field(body, "effective_end")
        renewed_from_id = optional_field(body, "renewed_from_id")

        if cpt_code not in VALID_CPT_CODES:
            raise APIError("ERR_VALIDATION",
                           f"cpt_code must be one of {sorted(VALID_CPT_CODES)}")
        if not isinstance(payer_name, str) or not payer_name.strip():
            raise APIError("ERR_VALIDATION", "payer_name must be a non-empty string")
        if not isinstance(approved_units, int) or isinstance(approved_units, bool):
            raise APIError("ERR_VALIDATION", "approved_units must be an integer")
        if approved_units < MIN_APPROVED_UNITS or approved_units > MAX_APPROVED_UNITS:
            raise APIError("ERR_VALIDATION",
                           f"approved_units must be in [{MIN_APPROVED_UNITS}, {MAX_APPROVED_UNITS}]")
        _validate_window(effective_start, effective_end)

        plan = get_treatment_plan(treatment_plan_id)
        if plan["patient_id"] != patient_id:
            raise APIError("ERR_VALIDATION",
                           "treatment_plan must belong to the same patient")
        if plan["status"] != "ACTIVE":
            raise APIError("ERR_INVALID_STATE",
                           "treatment_plan must be ACTIVE at authorization submission")

        if renewed_from_id is not None:
            parent = store.authorizations.get(renewed_from_id)
            if parent is None:
                raise APIError("ERR_NOT_FOUND",
                               f"renewed_from_id {renewed_from_id} not found")
            if parent["cpt_code"] != cpt_code:
                raise APIError("ERR_RENEWAL_CPT_MISMATCH",
                               "renewal cpt_code must equal parent cpt_code")

        record = stamp_create(
            {
                "patient_id": patient_id,
                "treatment_plan_id": treatment_plan_id,
                "payer_name": payer_name,
                "cpt_code": cpt_code,
                "approved_units": approved_units,
                "effective_start": effective_start,
                "effective_end": effective_end,
                "provisional_units_consumed": 0,
                "adjudicated_units_consumed": 0,
                "renewed_from_id": renewed_from_id,
                "renewed_to_id": None,
                "status": "PENDING",
            },
            now=clinic["now_ts"],
        )
        store.authorizations[record["id"]] = record

    body_out, status = success_response(serialize_authorization(record), status=201)
    return jsonify(body_out), status


@bp.post("/authorizations/<authorization_id>/approve")
@require_auth("PayerAdmin")
def approve_authorization(authorization_id):
    with get_lock():
        auth = get_authorization(authorization_id)
        if auth["status"] != "PENDING":
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot approve authorization in status {auth['status']}")
        store = get_store()
        plan = store.treatment_plans.get(auth["treatment_plan_id"])
        if plan is None or plan["status"] != "ACTIVE":
            raise APIError("ERR_INVALID_STATE",
                           "treatment_plan must still be ACTIVE at approval time")

        patient = get_patient(auth["patient_id"])
        clinic = store.clinics[patient["clinic_id"]]
        now_ts = clinic["now_ts"]

        # Renewal cascade: if this authorization references a parent via renewed_from_id,
        # the parent must be ACTIVE, and we flip it ACTIVE → RENEWED atomically.
        parent_id = auth.get("renewed_from_id")
        if parent_id:
            parent = store.authorizations.get(parent_id)
            if parent is None:
                raise APIError("ERR_NOT_FOUND",
                               f"renewed_from parent {parent_id} not found")
            # Concurrency: another renewal already claimed this parent.
            if parent.get("renewed_to_id"):
                raise APIError("ERR_RENEWAL_CONFLICT",
                               "Parent authorization already has a renewal")
            if parent["status"] != "ACTIVE":
                raise APIError("ERR_INVALID_STATE",
                               "Parent authorization must be ACTIVE to be renewed")
            parent["renewed_to_id"] = auth["id"]
            parent["status"] = "RENEWED"
            stamp_update(parent, now=now_ts)

        auth["status"] = "APPROVED"
        stamp_update(auth, now=now_ts)

    body_out, status = success_response(serialize_authorization(auth))
    return jsonify(body_out), status


@bp.post("/authorizations/<authorization_id>/deny")
@require_auth("PayerAdmin")
def deny_authorization(authorization_id):
    with get_lock():
        auth = get_authorization(authorization_id)
        if auth["status"] != "PENDING":
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot deny authorization in status {auth['status']}")
        patient = get_patient(auth["patient_id"])
        clinic = get_store().clinics[patient["clinic_id"]]
        auth["status"] = "DENIED"
        stamp_update(auth, now=clinic["now_ts"])

    body_out, status = success_response(serialize_authorization(auth))
    return jsonify(body_out), status


@bp.get("/authorizations/<authorization_id>")
@require_auth("ClinicAdmin", "BCBA", "RBT", "PayerAdmin")
def read_authorization(authorization_id):
    with get_lock():
        auth = get_authorization(authorization_id)
        recompute_authorization_consumption(auth)
    body_out, status = success_response(serialize_authorization(auth))
    return jsonify(body_out), status


@bp.get("/authorizations/<authorization_id>/supervision-ratio")
@require_auth("ClinicAdmin", "BCBA", "PayerAdmin")
def authorization_supervision_ratio(authorization_id):
    with get_lock():
        auth = get_authorization(authorization_id)
        patient = get_patient(auth["patient_id"])
        clinic = get_store().clinics[patient["clinic_id"]]
        snapshot = compute_supervision_ratio(auth["patient_id"], clinic["now_ts"])

    body_out, status = success_response(snapshot)
    return jsonify(body_out), status


@bp.get("/authorizations/<authorization_id>/ledger")
@require_auth("ClinicAdmin", "BCBA", "PayerAdmin")
def authorization_ledger(authorization_id):
    limit, offset = get_pagination_params()
    with get_lock():
        get_authorization(authorization_id)
        items = [
            e for e in get_store().ledger_entries.values()
            if e["authorization_id"] == authorization_id
        ]
        items.sort(key=lambda e: e["created_at"])
        page, total = paginate(items, limit, offset)
        body_out, status = list_response(
            [serialize_ledger_entry(e) for e in page], total, limit, offset
        )
    return jsonify(body_out), status
