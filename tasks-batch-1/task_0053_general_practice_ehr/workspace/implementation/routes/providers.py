"""Provider endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

import db
from db import stamp_create, touch
from errors import (
    APIError,
    ERR_DUPLICATE_NPI,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PANEL_AT_CAPACITY,
    ERR_REFERENCE_NOT_FOUND,
    ERR_STALE_VERSION,
)
from middleware import require
from response import ok_array, ok_object
from routes.common import lookup_or_404, paginate, parse_pagination, sort_by_created
from services import derive
from validation import (
    get_body,
    optional_bool,
    optional_enum,
    optional_int,
    optional_str,
    require_int,
    require_str,
)

bp = Blueprint("providers", __name__)

SPECIALTIES = {"FAMILY_MEDICINE", "INTERNAL_MEDICINE", "PEDIATRICS"}


def _validate_npi(npi: str) -> None:
    if len(npi) != 10 or not npi.isdigit():
        raise APIError(ERR_INVALID_REQUEST, 422, "npi must be exactly 10 digits")


def _validate_dea(dea) -> None:
    if dea is None:
        return
    if len(dea) != 9 or not dea[:2].isalpha() or not dea[2:].isdigit():
        raise APIError(
            ERR_INVALID_REQUEST, 422,
            "dea_number must be 9 chars: 2 letters followed by 7 digits",
        )


@bp.route("/providers", methods=["POST"])
def create_provider():
    require(["FrontDesk"])
    body = get_body()
    npi = require_str(body, "npi")
    full_name = require_str(body, "full_name")
    specialty = optional_enum(body, "specialty", SPECIALTIES, default="FAMILY_MEDICINE")
    dea_number = optional_str(body, "dea_number", default=None)
    epcs_enrolled = optional_bool(body, "epcs_enrolled", default=False)
    panel_capacity = optional_int(body, "panel_capacity", default=2000, minimum=0)

    _validate_npi(npi)
    _validate_dea(dea_number)

    # Uniqueness (priority 16) — ERR_DUPLICATE_NPI.
    for p in db.providers.values():
        if p["npi"] == npi:
            raise APIError(ERR_DUPLICATE_NPI, 409, "npi already registered")

    rec = stamp_create({
        "npi": npi,
        "full_name": full_name,
        "specialty": specialty,
        "dea_number": dea_number,
        "epcs_enrolled": epcs_enrolled,
        "panel_capacity": panel_capacity,
        "status": "ACTIVE",
        "panel_size": 0,
        "controlled_rx_count": 0,
    })
    db.providers[rec["id"]] = rec
    return ok_object(derive.serialize_provider(rec), 201)


@bp.route("/providers/<pid>", methods=["GET"])
def get_provider(pid):
    require(["FrontDesk", "Provider", "Biller", "QualityAnalyst"])
    rec = lookup_or_404(db.providers, pid, "Provider")
    return ok_object(derive.serialize_provider(rec), 200)


@bp.route("/providers", methods=["GET"])
def list_providers():
    require(["FrontDesk", "Provider", "Biller", "QualityAnalyst"])
    from flask import request

    limit, offset = parse_pagination()
    items = list(db.providers.values())
    specialty = request.args.get("specialty")
    status = request.args.get("status")
    if specialty is not None:
        items = [p for p in items if p["specialty"] == specialty]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return ok_array([derive.serialize_provider(p) for p in window], limit, offset, total)


@bp.route("/providers/<pid>/deactivate", methods=["POST"])
def deactivate_provider(pid):
    require(["FrontDesk"])
    rec = lookup_or_404(db.providers, pid, "Provider")
    if rec["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Provider is not ACTIVE")

    # Cascade: unbind every patient on this provider's panel.
    for patient in db.patients.values():
        if patient.get("pcp_id") == pid:
            patient["pcp_id"] = None
            touch(patient)

    rec["status"] = "INACTIVE"
    rec["panel_size"] = derive.compute_provider_panel_size(pid)  # -> 0
    touch(rec)
    return ok_object(derive.serialize_provider(rec), 200)


@bp.route("/providers/<pid>/panel", methods=["POST"])
def bind_panel(pid):
    require(["FrontDesk"])
    # Priority 3: path resource exists.
    rec = lookup_or_404(db.providers, pid, "Provider")
    body = get_body()

    # Priority 4: body FK existence (patient_id) BEFORE field validation.
    # Only resolvable when present and a string; absent/ill-typed falls through
    # to priority-5 field validation (ERR_INVALID_REQUEST) below.
    patient_id_raw = body.get("patient_id")
    if isinstance(patient_id_raw, str) and patient_id_raw not in db.patients:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "patient_id does not resolve")

    # Priority 5: required fields present and well-typed.
    patient_id = require_str(body, "patient_id")
    expected_version = require_int(body, "expected_provider_version")
    if patient_id not in db.patients:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "patient_id does not resolve")
    patient = db.patients[patient_id]

    # Business priority 12: at-capacity ceiling. Binding makes panel_size reach
    # or exceed panel_capacity -> reject. panel_size counts ACTIVE bound patients;
    # if this patient is not already counted (and is ACTIVE), the bind adds one.
    current_size = derive.compute_provider_panel_size(pid)
    already_counted = (patient.get("pcp_id") == pid and patient.get("status") == "ACTIVE")
    prospective = current_size if already_counted else current_size + (
        1 if patient.get("status") == "ACTIVE" else 0
    )
    if prospective >= rec["panel_capacity"]:
        raise APIError(ERR_PANEL_AT_CAPACITY, 409, "Provider panel is at capacity")

    # Business priority 13: optimistic concurrency — final guard on this endpoint.
    if expected_version != rec["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "expected_provider_version is stale")

    patient["pcp_id"] = pid
    touch(patient)
    rec["panel_size"] = derive.compute_provider_panel_size(pid)
    touch(rec)
    return ok_object(derive.serialize_provider(rec), 200)


@bp.route("/providers/<pid>/patients", methods=["GET"])
def list_panel_patients(pid):
    require(["FrontDesk", "Provider", "QualityAnalyst"])
    lookup_or_404(db.providers, pid, "Provider")
    limit, offset = parse_pagination()
    items = [p for p in db.patients.values() if p.get("pcp_id") == pid]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return ok_array([derive.serialize_patient(p) for p in window], limit, offset, total)


@bp.route("/providers/<pid>/referrals", methods=["GET"])
def list_provider_referrals(pid):
    require(["FrontDesk", "Provider"])
    lookup_or_404(db.providers, pid, "Provider")
    limit, offset = parse_pagination()
    items = [r for r in db.referrals.values() if r.get("referring_provider_id") == pid]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return ok_array([derive.serialize_referral(r) for r in window], limit, offset, total)
