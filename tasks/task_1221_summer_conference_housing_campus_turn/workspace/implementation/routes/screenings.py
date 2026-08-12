"""Background screenings: submit, begin-review, decide, appeal,
resolve-appeal (PRD 3.3)."""
from flask import Blueprint, request

from authz import ADMIN, SCREENING, COORDINATOR, require_roles, check_group_ownership
from db import store
from errors import ApiError, invalid_state
from respond import success
from serialize import ser_screening
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate, req_enum,
    req_str, sorted_by_creation, touch,
)

bp = Blueprint("screenings", __name__)


def _screening_group_id(s):
    participant = store.participants.get(s["participant_id"])
    return participant["group_id"] if participant else None


@bp.route("/participants/<pid>/background-screenings", methods=["POST"])
def submit_screening(pid):
    uid, role = require_roles([COORDINATOR, ADMIN])
    p = get_or_404(store.participants, pid)
    check_group_ownership(uid, role, p["group_id"])
    data = json_body()
    consent_reference = req_str(data, "consent_reference")
    if p["role_in_group"] not in ("CHAPERONE", "STAFF"):
        raise ApiError("ERR_SCREENING_NOT_REQUIRED", 422,
                       "Screenings are accepted only for CHAPERONE and STAFF participants")
    s = {
        "id": new_id(),
        "_seq": next(store.seq),
        "participant_id": pid,
        "consent_reference": consent_reference,
        "status": "SUBMITTED",
        "decided_at": None,
        "cleared_on": None,
        "appeal_reason": None,
    }
    s.update(new_common_fields())
    store.screenings[s["id"]] = s
    return success(ser_screening(s), status=201)


@bp.route("/participants/<pid>/background-screenings", methods=["GET"])
def list_screenings(pid):
    require_roles([ADMIN, SCREENING, COORDINATOR])
    get_or_404(store.participants, pid)
    status = request.args.get("status")
    items = [s for s in store.screenings.values()
             if s["participant_id"] == pid and (status is None or s["status"] == status)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_screening(s) for s in page], response_type="array", pagination=pagination)


@bp.route("/background-screenings/<sid>", methods=["GET"])
def get_screening(sid):
    require_roles([ADMIN, SCREENING, COORDINATOR])
    return success(ser_screening(get_or_404(store.screenings, sid)))


@bp.route("/background-screenings/<sid>/begin-review", methods=["POST"])
def begin_review(sid):
    require_roles([SCREENING, ADMIN])
    s = get_or_404(store.screenings, sid)
    if s["status"] != "SUBMITTED":
        raise invalid_state("Screening must be SUBMITTED to begin review")
    s["status"] = "IN_REVIEW"
    touch(s)
    return success(ser_screening(s))


@bp.route("/background-screenings/<sid>/decide", methods=["POST"])
def decide_screening(sid):
    require_roles([SCREENING, ADMIN])
    s = get_or_404(store.screenings, sid)
    data = json_body()
    outcome = req_enum(data, "outcome", ("CLEAR", "FLAG"))
    if s["status"] != "IN_REVIEW":
        raise invalid_state("Screening must be IN_REVIEW to decide")
    s["decided_at"] = store.clock
    if outcome == "CLEAR":
        s["status"] = "CLEARED"
        s["cleared_on"] = store.clock.date()
    else:
        s["status"] = "FLAGGED"
    touch(s)
    return success(ser_screening(s))


@bp.route("/background-screenings/<sid>/appeal", methods=["POST"])
def appeal_screening(sid):
    uid, role = require_roles([COORDINATOR, ADMIN])
    s = get_or_404(store.screenings, sid)
    check_group_ownership(uid, role, _screening_group_id(s))
    data = json_body()
    appeal_reason = req_str(data, "appeal_reason")
    if s["status"] != "FLAGGED":
        raise invalid_state("Screening must be FLAGGED to appeal")
    s["status"] = "APPEALED"
    s["appeal_reason"] = appeal_reason
    touch(s)
    return success(ser_screening(s))


@bp.route("/background-screenings/<sid>/resolve-appeal", methods=["POST"])
def resolve_appeal(sid):
    require_roles([SCREENING, ADMIN])
    s = get_or_404(store.screenings, sid)
    data = json_body()
    outcome = req_enum(data, "outcome", ("CLEAR", "DENY"))
    if s["status"] != "APPEALED":
        raise invalid_state("Screening must be APPEALED to resolve the appeal")
    s["decided_at"] = store.clock
    if outcome == "CLEAR":
        s["status"] = "CLEARED"
        s["cleared_on"] = store.clock.date()
    else:
        s["status"] = "DENIED"
    touch(s)
    return success(ser_screening(s))
