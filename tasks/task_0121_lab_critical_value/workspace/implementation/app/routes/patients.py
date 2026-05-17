"""Patient endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import ROLE_LAB_DIRECTOR, ROLE_LAB_TECH, ROLE_ORDERING_PROVIDER, require_roles
from ..errors import err_validation
from ..helpers import (
    assert_enum,
    assert_string,
    new_uuid,
    paginate,
    parse_iso_date,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.lookups import get_patient
from ..services.serialize import patient_view
from ..services.workflows import create_common_fields
from ..store import store

bp = Blueprint("patients", __name__)

MRN_PATTERN = r"^[A-Z]{2}[0-9]{8}$"
PHONE_PATTERN = r"^\+[1-9][0-9]{6,14}$"
CONSENT_VALUES = ["SMS_AND_VOICE", "VOICE_ONLY", "NONE"]


@bp.route("/patients", methods=["POST"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_DIRECTOR)
def create_patient(**_):
    body = require_json_object()
    mrn = assert_string(body.get("mrn"), "mrn", pattern=MRN_PATTERN)
    full_name = assert_string(body.get("full_name"), "full_name")
    dob = parse_iso_date(body.get("date_of_birth"), "date_of_birth")
    primary = assert_string(body.get("primary_phone_e164"), "primary_phone_e164", pattern=PHONE_PATTERN)
    backup_raw = body.get("backup_phone_e164")
    backup = None
    if backup_raw is not None:
        backup = assert_string(backup_raw, "backup_phone_e164", pattern=PHONE_PATTERN)
    consent = assert_enum(body.get("notification_consent"), "notification_consent", CONSENT_VALUES, required=False) or "SMS_AND_VOICE"

    with store().lock:
        # unique mrn
        for p in store().patients.values():
            if p["mrn"] == mrn:
                raise err_validation(f"mrn {mrn} already exists")
        row = {
            **create_common_fields(),
            "mrn": mrn,
            "full_name": full_name,
            "date_of_birth": dob,
            "primary_phone_e164": primary,
            "backup_phone_e164": backup,
            "notification_consent": consent,
        }
        store().patients[row["id"]] = row
    return created(patient_view(row))


@bp.route("/patients/<pid>", methods=["GET"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_TECH, ROLE_LAB_DIRECTOR)
def fetch_patient(pid, **_):
    row = get_patient(pid)
    return ok(patient_view(row))


@bp.route("/patients", methods=["GET"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_TECH, ROLE_LAB_DIRECTOR)
def list_patients(**_):
    limit, offset = parse_pagination()
    mrn_filter = request.args.get("mrn")
    items = list(store().patients.values())
    if mrn_filter:
        items = [p for p in items if mrn_filter in p["mrn"]]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return listing([patient_view(r) for r in page], total, limit, offset)
