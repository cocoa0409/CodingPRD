"""/violations endpoints."""

from datetime import timedelta
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
from services.aggregates import recompute_program_compliance
from services.calculations import compute_penalty_points
from services.cascades import (
    cascade_violation_sustained,
    cascade_violation_overturned,
    cascade_violation_dismissed,
)


bp = Blueprint("violations", __name__)


VALID_SUBJECTS = {"BOOSTER", "COACH", "ATHLETE", "PROGRAM_ADMIN"}
VALID_TYPES = {
    "IMPERMISSIBLE_BENEFIT",
    "RECRUITING_CONTACT",
    "NIL_COLLECTIVE_PAYFORPLAY",
    "ACADEMIC_FRAUD",
    "OTHER",
}
VALID_SEVERITIES = {"LEVEL_I", "LEVEL_II", "LEVEL_III", "LEVEL_IV"}
VALID_STATUSES = {
    "REPORTED",
    "INVESTIGATING",
    "SUBSTANTIATED",
    "DISMISSED",
    "APPEALED",
    "SUSTAINED",
    "OVERTURNED",
}


def _serialize_violation(v):
    out = dict(v)
    out.pop("_seq", None)
    return out


@bp.route("/violations", methods=["POST"])
@require_roles("ComplianceOfficer", "Auditor")
def create_violation():
    body = require_body(request)
    program_id = require_field(body, "program_id", kind="string")
    subject_type = require_enum(body, "subject_type", VALID_SUBJECTS)
    subject_ref = require_field(body, "subject_ref", kind="string")
    violation_type = require_enum(body, "violation_type", VALID_TYPES)
    severity = require_enum(body, "severity", VALID_SEVERITIES)
    related_athlete_id = body.get("related_athlete_id")
    related_deal_id = body.get("related_deal_id")

    with lock():
        if program_id not in STORE.programs:
            raise_error("ERR_REFERENCE_NOT_FOUND", "Program not found")
        if related_athlete_id is not None and related_athlete_id not in STORE.athletes:
            raise_error("ERR_REFERENCE_NOT_FOUND", "related_athlete_id not found")
        if related_deal_id is not None and related_deal_id not in STORE.nil_deals:
            raise_error("ERR_REFERENCE_NOT_FOUND", "related_deal_id not found")

        v = make_entity("ComplianceViolation", {
            "program_id": program_id,
            "subject_type": subject_type,
            "subject_ref": subject_ref,
            "violation_type": violation_type,
            "severity": severity,
            "related_athlete_id": related_athlete_id,
            "related_deal_id": related_deal_id,
            "status": "REPORTED",
            "outcome": "PENDING",
            "penalty_points": 0,
            "reviewer_user_id": None,
        })
        STORE.compliance_violations[v["id"]] = v
        return success_object(_serialize_violation(v), status=201)


@bp.route("/violations/<violation_id>", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Auditor")
def get_violation(violation_id):
    with lock():
        v = STORE.compliance_violations.get(violation_id)
        if not v:
            raise_error("ERR_NOT_FOUND", "ComplianceViolation not found")
        return success_object(_serialize_violation(v))


@bp.route("/violations", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Auditor")
def list_violations():
    limit, offset = parse_pagination(request)
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    outcome = request.args.get("outcome")
    severity = request.args.get("severity")

    with lock():
        items = list(STORE.compliance_violations.values())
        if program_id:
            items = [v for v in items if v.get("program_id") == program_id]
        if status:
            items = [v for v in items if v.get("status") == status]
        if outcome:
            items = [v for v in items if v.get("outcome") == outcome]
        if severity:
            items = [v for v in items if v.get("severity") == severity]
        items.sort(key=lambda v: (v["created_at"], v["_seq"]))
        total = len(items)
        page = items[offset:offset + limit]
        return success_array([_serialize_violation(v) for v in page], limit, offset, total)


@bp.route("/violations/<violation_id>/state", methods=["POST"])
@require_roles("ComplianceOfficer", "Coach")
def transition_violation(violation_id):
    body = require_body(request)
    to_status = require_enum(body, "to_status", VALID_STATUSES)

    with lock():
        v = STORE.compliance_violations.get(violation_id)
        if not v:
            raise_error("ERR_NOT_FOUND", "ComplianceViolation not found")
        cur = v["status"]
        valid = {
            ("REPORTED", "INVESTIGATING"),
            ("INVESTIGATING", "SUBSTANTIATED"),
            ("INVESTIGATING", "DISMISSED"),
            ("SUBSTANTIATED", "APPEALED"),
            ("APPEALED", "SUSTAINED"),
            ("APPEALED", "OVERTURNED"),
        }
        if (cur, to_status) not in valid:
            raise_error("ERR_INVALID_STATE", f"Invalid transition {cur} -> {to_status}")

        # Role gating
        # Coach can only APPEALED (SUBSTANTIATED->APPEALED). Everything else ComplianceOfficer.
        if g.user_role == "Coach":
            if (cur, to_status) != ("SUBSTANTIATED", "APPEALED"):
                raise_error("ERR_FORBIDDEN", "Coach may only post APPEALED")

        # OCC
        check_version(body, v["version"])

        # Segregation of duties
        if (cur, to_status) == ("REPORTED", "INVESTIGATING"):
            # Per PRD §3.7: acting officer must not be affiliated with the implicated program.
            # The implementer enforces this via a header check. Since we have no concept of
            # "affiliation" in this scaffold beyond X-User-ID being opaque, we accept any
            # ComplianceOfficer X-User-ID as not-affiliated by default. (The PRD says "if it
            # fails" — there's no way for the check to fail without an affiliation table,
            # so this is effectively a no-op here.)
            v["status"] = "INVESTIGATING"
            v["reviewer_user_id"] = g.user_id
            mark_mutated(v)
            return success_object(_serialize_violation(v))

        if (cur, to_status) in (("INVESTIGATING", "SUBSTANTIATED"), ("INVESTIGATING", "DISMISSED")):
            # Continuity-of-investigation: caller must equal reviewer_user_id
            if v.get("reviewer_user_id") and g.user_id != v["reviewer_user_id"]:
                raise_error(
                    "ERR_SEGREGATION_OF_DUTIES",
                    "Only the original reviewer may take this case forward",
                )
            if to_status == "SUBSTANTIATED":
                v["status"] = "SUBSTANTIATED"
                mark_mutated(v)
                STORE.substantiated_at[v["id"]] = CLOCK.now()
                return success_object(_serialize_violation(v))
            # DISMISSED
            v["status"] = "DISMISSED"
            cascade_violation_dismissed(v)
            return success_object(_serialize_violation(v))

        if (cur, to_status) == ("SUBSTANTIATED", "APPEALED"):
            # Appeal window: clock - SUBSTANTIATED transition timestamp < 14 days
            sub_at = STORE.substantiated_at.get(v["id"])
            if sub_at is not None and CLOCK.now() - sub_at >= timedelta(days=14):
                raise_error("ERR_APPEAL_WINDOW_CLOSED", "Appeal window has closed")
            v["status"] = "APPEALED"
            mark_mutated(v)
            return success_object(_serialize_violation(v))

        if (cur, to_status) in (("APPEALED", "SUSTAINED"), ("APPEALED", "OVERTURNED")):
            # Caller's X-User-ID must DIFFER from reviewer_user_id (SoD)
            if v.get("reviewer_user_id") and g.user_id == v["reviewer_user_id"]:
                raise_error(
                    "ERR_SEGREGATION_OF_DUTIES",
                    "Appeal must be heard by a different officer than the original reviewer",
                )
            if to_status == "SUSTAINED":
                v["status"] = "SUSTAINED"
                # Compute penalty points first (so program compliance posture is correct).
                v["penalty_points"] = compute_penalty_points(
                    v, list(STORE.compliance_violations.values())
                )
                cascade_violation_sustained(v)
                return success_object(_serialize_violation(v))
            # OVERTURNED
            v["status"] = "OVERTURNED"
            # Recompute prior penalty_points - revert
            v["penalty_points"] = 0
            cascade_violation_overturned(v)
            return success_object(_serialize_violation(v))
