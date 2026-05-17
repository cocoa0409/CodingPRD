"""VeteranReferral endpoints."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_CLINIC_ADMIN, ROLE_THERAPIST, require_roles
from ..errors import err_validation
from ..helpers import (
    assert_integer,
    assert_string,
    parse_iso8601,
    require_json_object,
)
from ..responses import created, ok
from ..services.lookups import get_patient_ref, get_veteran_referral_or_404
from ..services.mutations import create_veteran_referral
from ..services.serialize import veteran_referral_to_dict
from ..store import store

bp = Blueprint("veteran_referrals", __name__)


@bp.route("/veteran-referrals", methods=["POST"])
@require_roles(ROLE_CLINIC_ADMIN)
def create_referral_route(**_kwargs):
    body = require_json_object()
    patient_id = assert_string(body.get("patient_id"), "patient_id")
    facility = assert_string(body.get("referring_va_facility_code"), "referring_va_facility_code")
    authorized_units = assert_integer(body.get("authorized_units"), "authorized_units", minimum=1)
    valid_from_raw = body.get("valid_from")
    valid_through_raw = body.get("valid_through")
    parse_iso8601(valid_from_raw, "valid_from")
    parse_iso8601(valid_through_raw, "valid_through")

    s = store()
    with s.lock:
        patient = get_patient_ref(patient_id)
        if patient.get("insurance_type") != "VA":
            raise err_validation("Patient.insurance_type must be VA for a VeteranReferral")
        row = create_veteran_referral(
            patient_id=patient_id,
            referring_va_facility_code=facility,
            authorized_units=authorized_units,
            valid_from=valid_from_raw,
            valid_through=valid_through_raw,
        )
    return created(veteran_referral_to_dict(row))


@bp.route("/veteran-referrals/<rid>", methods=["GET"])
@require_roles(ROLE_CLINIC_ADMIN, ROLE_THERAPIST)
def get_referral_route(rid: str, **_kwargs):
    s = store()
    with s.lock:
        row = get_veteran_referral_or_404(rid)
    return ok(veteran_referral_to_dict(row))
