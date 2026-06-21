"""Patient and Payer registration + reads."""
from flask import Blueprint, request

import db
from errors import err, ERR_DUPLICATE_RESOURCE, ERR_NOT_FOUND
from middleware import require_auth, require_role
from response import success_object
from services import store, serializers, lookup, validate
from .common import list_response

bp = Blueprint("patients", __name__)


# ---------------- Patients ----------------

@bp.route("/patients", methods=["POST"])
def create_patient():
    # Public (Anonymous).
    body = validate.get_body()
    full_name = validate.require_str(body, "full_name")
    email = validate.require_str(body, "email")
    residence_state_code = validate.require_state(body, "residence_state_code")
    insurance_payer_id = validate.optional_str(body, "insurance_payer_id", None)

    with db.lock:
        # Body FK validation (priority 3) after body well-formedness.
        if insurance_payer_id is not None:
            if insurance_payer_id not in db.payers:
                raise err(ERR_NOT_FOUND, "insurance_payer_id does not resolve to a payer.")
        # Uniqueness: email unique (priority 5).
        for p in db.patients.values():
            if p["email"] == email:
                raise err(ERR_DUPLICATE_RESOURCE, "email already registered.")
        record = store.create_full({
            "full_name": full_name,
            "email": email,
            "residence_state_code": residence_state_code,
            "insurance_payer_id": insurance_payer_id,
        })
        db.patients[record["id"]] = record
        return success_object(serializers.patient(record), status=201)


@bp.route("/patients/<pid>", methods=["GET"])
def get_patient(pid):
    with db.lock:
        p = lookup.patient(pid)
        return success_object(serializers.patient(p))


@bp.route("/patients", methods=["GET"])
def list_patients():
    with db.lock:
        records = list(db.patients.values())
        payer_filter = request.args.get("insurance_payer_id")
        if payer_filter is not None:
            records = [p for p in records if p.get("insurance_payer_id") == payer_filter]
        return list_response(records, serializers.patient)


# ---------------- Payers ----------------

@bp.route("/payers", methods=["POST"])
def create_payer():
    # Anonymous or ComplianceOfficer. Public registration is allowed; if auth
    # headers are present they must carry a permitted role.
    _user_id, role = db_identity_or_anonymous()
    if role not in (None, "Anonymous", "ComplianceOfficer"):
        from errors import ERR_FORBIDDEN
        raise err(ERR_FORBIDDEN, "Role %s may not register a payer." % role)

    body = validate.get_body()
    name = validate.require_str(body, "name")
    telehealth_parity = validate.optional_bool(body, "telehealth_parity", False)
    copay_cents = validate.require_int_min(body, "copay_cents", 0)
    covered_state_codes = validate.require_str_list(body, "covered_state_codes")
    allowed_amount_cents = validate.require_int_min(body, "allowed_amount_cents", 0)

    with db.lock:
        record = store.create_lean({
            "name": name,
            "telehealth_parity": telehealth_parity,
            "copay_cents": copay_cents,
            "covered_state_codes": covered_state_codes,
            "allowed_amount_cents": allowed_amount_cents,
        })
        db.payers[record["id"]] = record
        return success_object(serializers.payer(record), status=201)


@bp.route("/payers/<pid>", methods=["GET"])
def get_payer(pid):
    with db.lock:
        p = lookup.payer(pid)
        return success_object(serializers.payer(p))


def db_identity_or_anonymous():
    """For endpoints open to Anonymous: if X-User-Role header present, validate it
    against declared roles; if absent, treat as anonymous (role None)."""
    from middleware import DECLARED_ROLES
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if role is None and user_id is None:
        return None, None
    # If either header is present, require a valid declared role + id (auth gate).
    from errors import ERR_UNAUTHENTICATED
    if not user_id or not role or role not in DECLARED_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers.")
    return user_id, role
