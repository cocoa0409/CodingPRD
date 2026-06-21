"""Protocol endpoints (PRD §3.1)."""

from flask import Blueprint, request

import errors
from db import LOCK, db
from errors import err
from middleware import authenticate, require_role
from response import object_response
from routes._helpers import get_json_body, paginated, sort_by_created
from services import lookup
from services.common import base_entity, parse_date, touch
from services.serialize import public

bp = Blueprint("protocols", __name__)

READ_ROLES = {"ClinicAdmin", "Clinician", "Collector", "MRO"}
PANEL_CODES = {"PHYSICAL", "DRUG_DOT", "DRUG_NON_DOT", "AUDIOMETRIC", "RESPIRATOR_FIT"}


def _validate_panels(panels):
    if not isinstance(panels, list):
        raise err(errors.ERR_INVALID_REQUEST, "panels must be an array")
    cleaned = []
    for p in panels:
        if not isinstance(p, dict):
            raise err(errors.ERR_INVALID_REQUEST, "each panel must be an object")
        code = p.get("panel_code")
        if code not in PANEL_CODES:
            raise err(errors.ERR_INVALID_REQUEST, "invalid panel_code")
        required_for = p.get("required_for_job_category")
        if not isinstance(required_for, str):
            raise err(errors.ERR_INVALID_REQUEST, "required_for_job_category must be a string")
        price = p.get("price_cents")
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            raise err(errors.ERR_INVALID_REQUEST, "price_cents must be a non-negative integer")
        recheck = p.get("recheck_interval_days")
        if isinstance(recheck, bool) or not isinstance(recheck, int) or recheck < 0:
            raise err(errors.ERR_INVALID_REQUEST, "recheck_interval_days must be a non-negative integer")
        cleaned.append({
            "panel_code": code,
            "required_for_job_category": required_for,
            "price_cents": price,
            "recheck_interval_days": recheck,
        })
    return cleaned


@bp.route("/clinic/protocols", methods=["POST"])
def create_protocol():
    caller = authenticate()
    require_role(caller, {"ClinicAdmin"})
    body = get_json_body()

    with LOCK:
        # Body FK existence/consistency (priority 4): a missing OR not-found body
        # reference is ERR_CROSS_EMPLOYER_REFERENCE per PRD §2.5.
        employer_id = body.get("employer_id")
        if employer_id is None or employer_id not in db.employers:
            raise err(errors.ERR_CROSS_EMPLOYER_REFERENCE,
                      "employer_id missing or not found")

        effective_date = body.get("effective_date")
        if effective_date is None or parse_date(effective_date) is None:
            raise err(errors.ERR_INVALID_REQUEST, "effective_date must be a valid date")

        if "panels" not in body or body["panels"] is None:
            raise err(errors.ERR_INVALID_REQUEST, "panels is required")
        panels = _validate_panels(body["panels"])

        proto = base_entity()
        proto.update({
            "employer_id": employer_id,
            "status": "DRAFT",
            "effective_date": effective_date,
            "panels": panels,
        })
        db.protocols[proto["id"]] = proto
        return object_response(public(proto), 201)


@bp.route("/clinic/protocols", methods=["GET"])
def list_protocols():
    caller = authenticate()
    require_role(caller, READ_ROLES)
    employer_id = request.args.get("employer_id")
    status = request.args.get("status")
    items = list(db.protocols.values())
    if employer_id is not None:
        items = [p for p in items if p["employer_id"] == employer_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginated(sort_by_created(items))


@bp.route("/clinic/protocols/<protocol_id>", methods=["GET"])
def get_protocol(protocol_id):
    caller = authenticate()
    require_role(caller, READ_ROLES)
    proto = lookup.get_protocol(protocol_id)
    return object_response(public(proto), 200)


@bp.route("/clinic/protocols/<protocol_id>/activate", methods=["POST"])
def activate_protocol(protocol_id):
    caller = authenticate()
    require_role(caller, {"ClinicAdmin"})
    body = get_json_body()

    with LOCK:
        proto = lookup.get_protocol(protocol_id)
        employer = lookup.get_employer(proto["employer_id"])

        # Priority 5: body well-formedness for the OCC field.
        if "expected_employer_version" not in body or body["expected_employer_version"] is None:
            raise err(errors.ERR_INVALID_REQUEST, "expected_employer_version is required")
        expected = body["expected_employer_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err(errors.ERR_INVALID_REQUEST, "expected_employer_version must be an integer")

        # Priority 6: OCC check (before state preconditions and business rules).
        if expected != employer["version"]:
            raise err(errors.ERR_STALE_EMPLOYER_VERSION,
                      "expected_employer_version does not match employer version")

        # Priority 7: state precondition.
        if proto["status"] != "DRAFT":
            raise err(errors.ERR_PROTOCOL_NOT_DRAFT, "Protocol must be DRAFT to activate")

        # Business rules (after state).
        panels = proto.get("panels") or []
        if len(panels) == 0:
            raise err(errors.ERR_PROTOCOL_EMPTY_PANELS, "Protocol has no panels")
        codes = [p["panel_code"] for p in panels]
        if len(codes) != len(set(codes)):
            raise err(errors.ERR_DUPLICATE_PANEL_CODE, "A panel_code appears more than once")
        if employer.get("dot_regulated") and "DRUG_DOT" not in codes:
            raise err(errors.ERR_DOT_PANEL_REQUIRED,
                      "DOT-regulated employer protocol must include a DRUG_DOT panel")

        # Side effects.
        proto["status"] = "ACTIVE"
        touch(proto)

        # Cascade: retire any other ACTIVE protocol for this employer.
        for other in db.protocols.values():
            if (other["id"] != proto["id"]
                    and other["employer_id"] == employer["id"]
                    and other["status"] == "ACTIVE"):
                other["status"] = "RETIRED"
                touch(other)

        # Cascade: PROSPECT -> ACTIVE (no-op if already ACTIVE).
        if employer["account_status"] == "PROSPECT":
            employer["account_status"] = "ACTIVE"

        # Employer.version increments by 1 (single bump for the activation).
        touch(employer)

        return object_response(public(proto), 200)
