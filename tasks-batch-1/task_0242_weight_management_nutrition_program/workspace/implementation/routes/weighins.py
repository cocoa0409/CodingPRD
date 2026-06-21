"""WeighIn endpoints (PRD 3.6). Append-only, OCC-guarded on enrollment."""
from flask import Blueprint, request

from common import (as_bool, as_int, as_number, as_str, get_body, init_event,
                    parse_pagination, require, sort_by_creation, touch)
from db import db
from errors import (ERR_INVALID_REQUEST, ERR_STALE_ENROLLMENT_VERSION,
                    raise_error)
from lookups import get_enrollment, get_member, get_program
from middleware import require_roles
from response import paginated, success
from serializers import serialize
import calculations as calc
import services

bp = Blueprint("weighins", __name__)


@bp.route("/wm/weigh-ins", methods=["POST"])
@require_roles("ProgramAdmin", "Coach", "Member")
def create_weighin():
    body = get_body()
    enrollment_id = as_str(require(body, "enrollment_id"), "enrollment_id")
    # OCC field is mandatory (PRD 2.7)
    expected_version = require(body, "expected_enrollment_version")
    expected_version = as_int(expected_version, "expected_enrollment_version")

    weight_kg = as_number(require(body, "weight_kg"), "weight_kg")
    if weight_kg <= 0:
        raise_error(ERR_INVALID_REQUEST, "weight_kg must be > 0")

    body_fat_pct = None
    if body.get("body_fat_pct") is not None:
        body_fat_pct = as_number(body["body_fat_pct"], "body_fat_pct")
        if body_fat_pct < 0 or body_fat_pct > 70:
            raise_error(ERR_INVALID_REQUEST, "body_fat_pct must be in 0..70")

    counts = True
    if body.get("counts") is not None:
        counts = as_bool(body["counts"], "counts")

    # existence (priority 3/5) before OCC (priority 7)
    enrollment = get_enrollment(enrollment_id)

    # OCC check: after existence, before business logic
    if expected_version != enrollment["version"]:
        raise_error(ERR_STALE_ENROLLMENT_VERSION,
                    "expected_enrollment_version does not match enrollment.version")

    program = get_program(enrollment["program_id"])
    member = get_member(enrollment["member_id"])

    lean_mass = None
    if body_fat_pct is not None:
        lean_mass = calc.compute_lean_mass(weight_kg, body_fat_pct)

    weighin = {
        "enrollment_id": enrollment_id,
        "member_id": enrollment["member_id"],
        "weight_kg": weight_kg,
        "body_fat_pct": body_fat_pct,
        "lean_mass_kg": lean_mass,
        "recorded_utc": program["current_utc"],
        "counts": counts,
    }
    init_event(weighin)
    db.weigh_ins[weighin["id"]] = weighin

    if counts:
        # recompute member derived figures, goal progress, milestones, grad
        services.recompute_member_progress(member)
        touch(member)
        services.recompute_goal_progress_and_achieve(member, enrollment, program)
        services.recompute_graduation_eligibility(enrollment)
        # a counted weigh-in advances the enrollment version (PRD 2.7)
        touch(enrollment)

    return success(serialize(weighin), 201)


@bp.route("/wm/weigh-ins", methods=["GET"])
@require_roles("ProgramAdmin", "Clinician", "Coach", "Member")
def list_weighins():
    limit, offset = parse_pagination()
    items = list(db.weigh_ins.values())
    enrollment_id = request.args.get("enrollment_id")
    member_id = request.args.get("member_id")
    counts = request.args.get("counts")
    if enrollment_id is not None:
        items = [w for w in items if w["enrollment_id"] == enrollment_id]
    if member_id is not None:
        items = [w for w in items if w["member_id"] == member_id]
    if counts is not None:
        want = counts.lower() == "true"
        items = [w for w in items if w["counts"] is want]
    items = sort_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return paginated([serialize(w) for w in page], limit, offset, total)


@bp.route("/wm/weigh-ins/<weighin_id>", methods=["GET"])
@require_roles("ProgramAdmin", "Clinician", "Coach", "Member")
def get_one_weighin(weighin_id):
    if weighin_id not in db.weigh_ins:
        # PRD catalogue has no weigh-in not-found code; surface a generic 404.
        raise_error(("ERR_WEIGHIN_NOT_FOUND", 404), "WeighIn not found")
    return success(serialize(db.weigh_ins[weighin_id]), 200)
