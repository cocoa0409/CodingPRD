"""Household routes (PRD §3.1)."""

from flask import Blueprint, request

from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, gen_id, lock
from core.validation import require_body, require_field, require_enum
from services.mutations import stamp_create, bump
from services.projections import project_household, find_policy_by_state


bp = Blueprint("households", __name__)


_FILING_STATUSES = {"SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD"}


def _validate_state_code(s, field="state_code"):
    # PRD §3.1 does not pin a format on state_code; the FK reference to
    # StatePolicy is the only constraint. Just check it is a non-empty
    # string here; the FK lookup below handles "unknown state code".
    if not isinstance(s, str) or not s.strip():
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' must be a non-empty string")
    return s


@bp.route("/households", methods=["POST"])
@require_roles("IntakeWorker")
def create_household():
    body = require_body(request)
    state_code = _validate_state_code(require_field(body, "state_code", kind="string"))
    address_line = require_field(body, "address_line", kind="string")
    filing_status = require_enum(body, "filing_status", _FILING_STATUSES)

    # PRD §3.1: "The household carries a state_code that must reference an
    # existing StatePolicy." PRD §2.5: "body-level foreign key references
    # ... must resolve, and a dangling reference is rejected with
    # ERR_NOT_FOUND."
    if state_code not in STORE.state_policies_by_code:
        raise_error("ERR_NOT_FOUND", f"StatePolicy for state_code '{state_code}' not found")

    with lock():
        hid = gen_id()
        row = {
            "id": hid,
            "state_code": state_code,
            "head_applicant_id": None,
            "address_line": address_line,
            "filing_status": filing_status,
        }
        stamp_create(row)
        STORE.households[hid] = row

    return success_object(project_household(row), status=201)


@bp.route("/households/<household_id>", methods=["GET"])
@require_roles("IntakeWorker", "EligibilityCaseworker", "PolicyAdmin")
def get_household(household_id):
    row = STORE.households.get(household_id)
    if row is None:
        raise_error("ERR_NOT_FOUND", "Household not found")
    return success_object(project_household(row))


@bp.route("/households/<household_id>", methods=["PATCH"])
@require_roles("IntakeWorker")
def patch_household(household_id):
    row = STORE.households.get(household_id)
    if row is None:
        raise_error("ERR_NOT_FOUND", "Household not found")
    body = require_body(request)
    # OCC: if version is supplied, must match
    if "version" in body and body["version"] is not None:
        v = body["version"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise_error("ERR_INVALID_REQUEST", "version must be an integer")
        if v != row["version"]:
            raise_error("ERR_VERSION_CONFLICT", "version does not match")
    # Apply patches
    changed = False
    if "address_line" in body and body["address_line"] is not None:
        addr = body["address_line"]
        if not isinstance(addr, str) or not addr.strip():
            raise_error("ERR_INVALID_REQUEST", "address_line must be a non-empty string")
        row["address_line"] = addr
        changed = True
    if "filing_status" in body and body["filing_status"] is not None:
        fs = body["filing_status"]
        if fs not in _FILING_STATUSES:
            raise_error("ERR_INVALID_REQUEST", "filing_status invalid")
        row["filing_status"] = fs
        changed = True
    if changed:
        bump(row)
    return success_object(project_household(row))
