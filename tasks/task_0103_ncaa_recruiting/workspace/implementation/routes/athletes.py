"""/athletes endpoints (incl. state transitions PROSPECTIVE->COMMITTED, COMMITTED->ENROLLED)."""

from flask import Blueprint, request, g

from core.auth import require_roles
from core.envelope import success_object, success_array
from core.errors import raise_error
from core.models import make_entity, mark_mutated, serialize, serialize_list
from core.store import STORE, lock
from core.validation import (
    require_body,
    require_field,
    require_enum,
    parse_pagination,
    check_version,
)
from services.cascades import cascade_enroll


bp = Blueprint("athletes", __name__)


VALID_STATUSES = {"PROSPECTIVE", "COMMITTED", "ENROLLED", "TRANSFER_PORTAL", "INELIGIBLE"}
VALID_AMATEUR_STATUSES = {"AMATEUR", "AT_RISK", "FORFEITED"}


@bp.route("/athletes", methods=["POST"])
@require_roles("ComplianceOfficer", "Coach")
def create_athlete():
    body = require_body(request)
    full_name = require_field(body, "full_name", kind="string")
    high_school = require_field(body, "high_school", kind="string")
    grad_year = require_field(body, "graduation_year", kind="int")

    with lock():
        a = make_entity("Athlete", {
            "full_name": full_name,
            "high_school": high_school,
            "graduation_year": int(grad_year),
            "status": "PROSPECTIVE",
            "current_program_id": None,
            "eligibility_record_id": None,
            "amateur_status": "AMATEUR",
            "years_of_eligibility_remaining": 4,
            "nil_deal_lifetime_value_cents": 0,
        })
        STORE.athletes[a["id"]] = a
        return success_object(serialize(a), status=201)


@bp.route("/athletes/<athlete_id>", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Athlete", "Auditor")
def get_athlete(athlete_id):
    with lock():
        a = STORE.athletes.get(athlete_id)
        if not a:
            raise_error("ERR_NOT_FOUND", "Athlete not found")
        # Athlete role can only read own record
        if g.user_role == "Athlete" and g.user_id != athlete_id:
            raise_error("ERR_FORBIDDEN", "Athlete may only read own record")
        return success_object(serialize(a))


@bp.route("/athletes", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Auditor")
def list_athletes():
    limit, offset = parse_pagination(request)
    status = request.args.get("status")
    current_program_id = request.args.get("current_program_id")
    amateur_status = request.args.get("amateur_status")

    with lock():
        items = list(STORE.athletes.values())
        if status:
            items = [a for a in items if a.get("status") == status]
        if current_program_id:
            items = [a for a in items if a.get("current_program_id") == current_program_id]
        if amateur_status:
            items = [a for a in items if a.get("amateur_status") == amateur_status]
        items.sort(key=lambda a: (a["created_at"], a["_seq"]))
        total = len(items)
        page = items[offset:offset + limit]
        return success_array(serialize_list(page), limit, offset, total)


@bp.route("/athletes/<athlete_id>/state", methods=["POST"])
@require_roles("ComplianceOfficer")
def transition_athlete(athlete_id):
    body = require_body(request)
    to_status = require_enum(body, "to_status", VALID_STATUSES)

    with lock():
        a = STORE.athletes.get(athlete_id)
        if not a:
            raise_error("ERR_NOT_FOUND", "Athlete not found")

        cur = a["status"]
        # State validity priority 6
        valid_transitions = {
            ("PROSPECTIVE", "COMMITTED"),
            ("COMMITTED", "ENROLLED"),
        }
        if (cur, to_status) not in valid_transitions:
            raise_error("ERR_INVALID_STATE", f"Invalid transition {cur} -> {to_status}")

        # OCC priority 7
        check_version(body, a["version"])

        if to_status == "COMMITTED":
            # Required program_id
            program_id = require_field(body, "program_id", kind="string")
            prog = STORE.programs.get(program_id)
            if prog is None:
                raise_error("ERR_REFERENCE_NOT_FOUND", "Program not found")
            # Eligibility clearance priority 9
            elig_id = a.get("eligibility_record_id")
            if not elig_id:
                raise_error("ERR_ELIGIBILITY_NOT_CLEARED", "Athlete has no EligibilityRecord")
            elig = STORE.eligibility_records.get(elig_id)
            if not elig or elig.get("decision") not in ("QUALIFIER", "PARTIAL_QUALIFIER"):
                raise_error("ERR_ELIGIBILITY_NOT_CLEARED", "EligibilityRecord decision not cleared")
            # Must have at least one SIGNED slot for this athlete + program
            has_signed = any(
                s.get("athlete_id") == athlete_id
                and s.get("program_id") == program_id
                and s.get("status") == "SIGNED"
                for s in STORE.scholarship_slots.values()
            )
            if not has_signed:
                raise_error("ERR_NO_SIGNED_SLOT", "Athlete has no SIGNED slot at this program")
            a["status"] = "COMMITTED"
            a["current_program_id"] = program_id
            mark_mutated(a)
            return success_object(serialize(a))

        if to_status == "ENROLLED":
            if not a.get("current_program_id"):
                raise_error("ERR_INVALID_STATE", "Athlete has no current_program_id")
            pid = a["current_program_id"]
            # Need SIGNED slot
            has_signed = any(
                s.get("athlete_id") == athlete_id
                and s.get("program_id") == pid
                and s.get("status") == "SIGNED"
                for s in STORE.scholarship_slots.values()
            )
            if not has_signed:
                raise_error("ERR_NO_SIGNED_SLOT", "Athlete has no SIGNED slot to activate")
            cascade_enroll(a)
            return success_object(serialize(a))
