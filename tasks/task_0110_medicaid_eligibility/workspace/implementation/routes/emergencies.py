"""EmergencyDeclaration routes (PRD §3.5)."""

from flask import Blueprint, request

from core.auth import require_roles
from core.envelope import success_object, success_array
from core.errors import raise_error
from core.store import STORE, gen_id, lock
from core.timeutils import parse_iso
from core.validation import require_body, require_field, require_enum, parse_pagination
from services.cascade import emergency_arrival_cascade
from services.mutations import stamp_create
from services.projections import project_emergency_declaration, emergency_status


bp = Blueprint("emergencies", __name__)


@bp.route("/emergency-declarations", methods=["POST"])
@require_roles("PolicyAdmin")
def create_declaration():
    body = require_body(request)
    scope = require_enum(body, "scope", {"FEDERAL", "STATE"})
    state_code = body.get("state_code")
    if scope == "STATE":
        # PRD §3.1 / §3.5: state_code required (non-empty) iff scope=STATE.
        if not isinstance(state_code, str) or not state_code.strip():
            raise_error("ERR_INVALID_REQUEST", "state_code is required when scope=STATE")
    else:
        if state_code not in (None,):
            raise_error("ERR_INVALID_REQUEST", "state_code must be null when scope=FEDERAL")
    declared_at = require_field(body, "declared_at", kind="string")
    expires_at = require_field(body, "expires_at", kind="string")
    declared_dt = parse_iso(declared_at, "declared_at")
    expires_dt = parse_iso(expires_at, "expires_at")
    if expires_dt <= declared_dt:
        raise_error("ERR_INVALID_REQUEST", "expires_at must be strictly after declared_at")

    with lock():
        did = gen_id()
        row = {
            "id": did,
            "scope": scope,
            "state_code": state_code if scope == "STATE" else None,
            "_declared_at_dt": declared_dt,
            "_expires_at_dt": expires_dt,
        }
        stamp_create(row, append_only=True)
        STORE.emergency_declarations[did] = row
        # Cascade: flip eligible Enrollments to CONTINUOUS_COVERAGE
        emergency_arrival_cascade(row)

    return success_object(project_emergency_declaration(row), status=201)


@bp.route("/emergency-declarations/<declaration_id>", methods=["GET"])
@require_roles("PolicyAdmin", "IntakeWorker", "EligibilityCaseworker", "AppealsOfficer")
def get_declaration(declaration_id):
    row = STORE.emergency_declarations.get(declaration_id)
    if row is None:
        raise_error("ERR_NOT_FOUND", "EmergencyDeclaration not found")
    return success_object(project_emergency_declaration(row))


@bp.route("/emergency-declarations", methods=["GET"])
@require_roles("PolicyAdmin", "IntakeWorker", "EligibilityCaseworker", "AppealsOfficer")
def list_declarations():
    limit, offset = parse_pagination(request)
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in ("ACTIVE", "EXPIRED"):
        raise_error("ERR_INVALID_REQUEST", "status filter must be ACTIVE or EXPIRED")
    rows = list(STORE.emergency_declarations.values())
    if status_filter is not None:
        rows = [r for r in rows if emergency_status(r) == status_filter]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_array([project_emergency_declaration(r) for r in page], limit, offset, total)
