from flask import Blueprint, request

import auth
import calcs
import services
import store
import validators as v
from auth import ALL_ROLES
from envelope import ok, ok_page
from errors import ApiError
from store import DB

bp = Blueprint("evidence_requests", __name__)

REVIEW_ACTIONS = ("ACCEPT", "REJECT", "WAIVE")
REVIEW_ACTION_ROLES = {
    "ACCEPT": {"EvidenceReviewer"},
    "REJECT": {"EvidenceReviewer"},
    "WAIVE": {"ComplianceLead"},
}


@bp.post("/soc/evidence-requests")
def create_evidence_request():
    auth.authenticate({"ComplianceLead"})
    body = auth.body()
    control = v.fk(body, "control_id", "controls")
    v.req_id(body, "control_id")
    period_index = v.req_int(body, "period_index", minv=0)
    start = v.req_dt(body, "period_start")
    end = v.req_dt(body, "period_end")
    if end <= start:
        raise ApiError("ERR_VALIDATION")

    for existing in services.evidence_of_control(control["id"]):
        if existing["status"] == "MISSED":
            continue
        e_start = store.parse_iso(existing["period_start"])
        e_end = store.parse_iso(existing["period_end"])
        if start < e_end and e_start < end:
            raise ApiError("ERR_EVIDENCE_PERIOD_OVERLAP")

    for existing in services.evidence_of_control(control["id"]):
        if existing["period_index"] == period_index:
            raise ApiError("ERR_DUPLICATE_RESOURCE")

    row = store.new_row(
        "evidence_requests",
        {
            "control_id": control["id"],
            "period_index": period_index,
            "period_start": store.fmt_iso(start),
            "period_end": store.fmt_iso(end),
            "due_date": store.fmt_iso(store.add_days(end, calcs.GRACE_DAYS)),
            "status": "SCHEDULED",
            "submitted_by_user_id": None,
            "submitted_at": None,
            "reviewed_by_user_id": None,
            "reviewed_at": None,
            "rejection_round": 0,
            "artifact_ref": None,
            "late": False,
        },
    )
    control["evidence_scheduled_count"] = control["evidence_scheduled_count"] + 1
    store.touch(control)
    return ok(store.public(row), 201)


@bp.get("/soc/evidence-requests/<evidence_request_id>")
def read_evidence_request(evidence_request_id):
    auth.authenticate(ALL_ROLES)
    row = store.get_or_404("evidence_requests", evidence_request_id)
    return ok(store.public(row))


@bp.get("/soc/evidence-requests")
def list_evidence_requests():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("evidence_requests")
    for key in ("control_id", "status"):
        value = request.args.get(key)
        if value is not None:
            items = [r for r in items if r[key] == value]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([store.public(r) for r in page], limit, offset, total)


@bp.post("/soc/evidence-requests/<evidence_request_id>/submit")
def submit_evidence(evidence_request_id):
    user_id, role = auth.authenticate({"ControlOwner", "SubserviceContact"})
    row = store.get_or_404("evidence_requests", evidence_request_id)
    body = auth.body()
    artifact_ref = v.req_str(body, "artifact_ref", 1, 500)

    control = DB["controls"][row["control_id"]]
    engagement = DB["engagements"][control["engagement_id"]]
    services.require_phase(engagement, {"OBSERVATION"})
    services.require_not_frozen(engagement)

    if row["status"] not in ("SCHEDULED", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE")

    if role == "SubserviceContact":
        if control["subservice_organization_id"] != user_id:
            raise ApiError("ERR_NOT_CONTROL_OWNER")
    else:
        if control["owner_user_id"] is None or control["owner_user_id"] != user_id:
            raise ApiError("ERR_NOT_CONTROL_OWNER")

    clock = store.now_dt()
    due = store.parse_iso(row["due_date"])
    if due is not None and clock > due:
        raise ApiError("ERR_EVIDENCE_WINDOW_CLOSED")

    previous = row["status"]
    row["status"] = "SUBMITTED"
    row["artifact_ref"] = artifact_ref
    row["submitted_at"] = store.now_iso()
    row["submitted_by_user_id"] = user_id
    row["late"] = due is not None and clock > due
    store.touch(row)
    if previous == "SCHEDULED":
        control["evidence_scheduled_count"] = max(0, control["evidence_scheduled_count"] - 1)
        store.touch(control)
    return ok(store.public(row))


@bp.post("/soc/evidence-requests/<evidence_request_id>/review")
def review_evidence(evidence_request_id):
    user_id, role = auth.authenticate({"EvidenceReviewer", "ComplianceLead"})
    body = auth.body()
    auth.check_action_role(role, body.get("action"), REVIEW_ACTION_ROLES)
    row = store.get_or_404("evidence_requests", evidence_request_id)
    action = v.req_enum(body, "action", REVIEW_ACTIONS)
    v.opt_str(body, "review_note", 0, 2000)

    control = DB["controls"][row["control_id"]]
    engagement = DB["engagements"][control["engagement_id"]]
    services.require_not_frozen(engagement)

    if row["status"] != "SUBMITTED":
        raise ApiError("ERR_TRANSITION_NOT_ALLOWED")

    if action in ("ACCEPT", "REJECT"):
        if control["owner_user_id"] is not None and user_id == control["owner_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        if row["submitted_by_user_id"] is not None and user_id == row["submitted_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    row["reviewed_at"] = store.now_iso()
    row["reviewed_by_user_id"] = user_id
    if action == "ACCEPT":
        row["status"] = "ACCEPTED"
        control["evidence_accepted_count"] = control["evidence_accepted_count"] + 1
        store.touch(control)
    elif action == "REJECT":
        row["status"] = "REJECTED"
        row["rejection_round"] = row["rejection_round"] + 1
        control["evidence_scheduled_count"] = control["evidence_scheduled_count"] + 1
        store.touch(control)
    else:
        row["status"] = "WAIVED"
    store.touch(row)
    return ok(store.public(row))
