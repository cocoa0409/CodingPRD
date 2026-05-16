"""/scholarship-slots endpoints."""

from flask import Blueprint, request, g

from core.auth import require_roles
from core.clock import CLOCK
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
from services.aggregates import recompute_program_aggregates
from services.money import is_two_decimal_places


bp = Blueprint("scholarship_slots", __name__)


VALID_STATUSES = {"OFFERED", "SIGNED", "ACTIVE", "WITHDRAWN", "RELEASED", "REVOKED"}


@bp.route("/scholarship-slots", methods=["POST"])
@require_roles("Coach")
def create_slot():
    body = require_body(request)
    program_id = require_field(body, "program_id", kind="string")
    athlete_id = require_field(body, "athlete_id", kind="string")
    fe = require_field(body, "fractional_equivalency", kind="number")
    annual_value = require_field(body, "annual_value_cents", kind="int")

    with lock():
        # Existence priority 5
        if program_id not in STORE.programs:
            raise_error("ERR_REFERENCE_NOT_FOUND", "Program not found")
        if athlete_id not in STORE.athletes:
            raise_error("ERR_REFERENCE_NOT_FOUND", "Athlete not found")

        # Body shape priority 18
        if isinstance(fe, bool):
            raise_error("ERR_VALIDATION_FAILED", "fractional_equivalency must be number")
        fe_f = float(fe)
        if not (0.01 <= fe_f <= 1.00):
            raise_error("ERR_VALIDATION_FAILED", "fractional_equivalency must be in [0.01, 1.00]")
        if not is_two_decimal_places(fe_f):
            raise_error("ERR_VALIDATION_FAILED", "fractional_equivalency must have at most 2 decimal places")
        if isinstance(annual_value, bool) or int(annual_value) <= 0:
            raise_error("ERR_VALIDATION_FAILED", "annual_value_cents must be > 0")

        from services.money import round_two_dp
        slot = make_entity("ScholarshipSlot", {
            "program_id": program_id,
            "athlete_id": athlete_id,
            "fractional_equivalency": round_two_dp(fe_f),
            "annual_value_cents": int(annual_value),
            "status": "OFFERED",
            "signed_at": None,
            "activated_at": None,
        })
        STORE.scholarship_slots[slot["id"]] = slot
        return success_object(serialize(slot), status=201)


@bp.route("/scholarship-slots/<slot_id>", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Auditor")
def get_slot(slot_id):
    with lock():
        s = STORE.scholarship_slots.get(slot_id)
        if not s:
            raise_error("ERR_NOT_FOUND", "ScholarshipSlot not found")
        return success_object(serialize(s))


@bp.route("/scholarship-slots", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Auditor")
def list_slots():
    limit, offset = parse_pagination(request)
    program_id = request.args.get("program_id")
    athlete_id = request.args.get("athlete_id")
    status = request.args.get("status")
    with lock():
        items = list(STORE.scholarship_slots.values())
        if program_id:
            items = [s for s in items if s.get("program_id") == program_id]
        if athlete_id:
            items = [s for s in items if s.get("athlete_id") == athlete_id]
        if status:
            items = [s for s in items if s.get("status") == status]
        items.sort(key=lambda s: (s["created_at"], s["_seq"]))
        total = len(items)
        page = items[offset:offset + limit]
        return success_array(serialize_list(page), limit, offset, total)


@bp.route("/scholarship-slots/<slot_id>/state", methods=["POST"])
@require_roles("Coach", "ComplianceOfficer")
def transition_slot(slot_id):
    body = require_body(request)
    to_status = require_enum(body, "to_status", VALID_STATUSES)

    with lock():
        s = STORE.scholarship_slots.get(slot_id)
        if not s:
            raise_error("ERR_NOT_FOUND", "ScholarshipSlot not found")

        cur = s["status"]
        # Coach handles OFFERED transitions; ComplianceOfficer handles ACTIVE->REVOKED.
        # SIGNED->ACTIVE and ACTIVE->RELEASED are cascade-only (not via this endpoint).
        valid_pairs_by_role = {
            "Coach": {("OFFERED", "SIGNED"), ("OFFERED", "WITHDRAWN")},
            "ComplianceOfficer": {("ACTIVE", "REVOKED")},
        }
        allowed = valid_pairs_by_role.get(g.user_role, set())
        if (cur, to_status) not in allowed:
            # If the transition is structurally invalid for any role -> ERR_INVALID_STATE.
            # If it's a valid transition for some other role -> ERR_FORBIDDEN.
            all_valid = set().union(*valid_pairs_by_role.values())
            if (cur, to_status) in all_valid:
                raise_error("ERR_FORBIDDEN", f"Role {g.user_role} cannot perform {cur} -> {to_status}")
            raise_error("ERR_INVALID_STATE", f"Invalid transition {cur} -> {to_status}")

        # OCC priority 7
        check_version(body, s["version"])

        if (cur, to_status) == ("OFFERED", "SIGNED"):
            # Priority 9: eligibility cleared
            athlete = STORE.athletes.get(s["athlete_id"])
            if athlete is None:
                raise_error("ERR_REFERENCE_NOT_FOUND", "Athlete not found")
            elig_id = athlete.get("eligibility_record_id")
            if not elig_id:
                raise_error("ERR_ELIGIBILITY_NOT_CLEARED", "Athlete has no EligibilityRecord")
            elig = STORE.eligibility_records.get(elig_id)
            if not elig or elig.get("decision") not in ("QUALIFIER", "PARTIAL_QUALIFIER"):
                raise_error("ERR_ELIGIBILITY_NOT_CLEARED", "EligibilityRecord decision not cleared")
            # Priority 13: athlete not in TRANSFER_PORTAL or INELIGIBLE
            if athlete.get("status") in ("TRANSFER_PORTAL", "INELIGIBLE"):
                raise_error("ERR_ATHLETE_NOT_AVAILABLE", "Athlete is not available for signing")
            # Priority 16: scholarship cap
            prog = STORE.programs.get(s["program_id"])
            if prog is None:
                raise_error("ERR_REFERENCE_NOT_FOUND", "Program not found")
            from services.money import round_two_dp
            projected = round_two_dp(
                float(prog.get("total_equivalencies_used", 0)) + float(s["fractional_equivalency"])
            )
            if projected > float(prog["scholarship_cap_equivalencies"]):
                raise_error("ERR_SCHOLARSHIP_CAP_EXCEEDED", "Scholarship cap would be exceeded")
            # OK to sign
            s["status"] = "SIGNED"
            s["signed_at"] = CLOCK.now_iso()
            mark_mutated(s)
            recompute_program_aggregates(s["program_id"])
            return success_object(serialize(s))

        if (cur, to_status) == ("OFFERED", "WITHDRAWN"):
            s["status"] = "WITHDRAWN"
            mark_mutated(s)
            return success_object(serialize(s))

        if (cur, to_status) == ("ACTIVE", "REVOKED"):
            # Need a SUSTAINED LEVEL_I or LEVEL_II violation against this athlete.
            aid = s["athlete_id"]
            has_sustained = any(
                v.get("related_athlete_id") == aid
                and v.get("outcome") == "SUSTAINED"
                and v.get("severity") in ("LEVEL_I", "LEVEL_II")
                for v in STORE.compliance_violations.values()
            )
            if not has_sustained:
                raise_error("ERR_NO_SUSTAINED_VIOLATION", "No qualifying SUSTAINED violation against athlete")
            s["status"] = "REVOKED"
            mark_mutated(s)
            recompute_program_aggregates(s["program_id"])
            return success_object(serialize(s))
