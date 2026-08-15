"""Determination endpoints: agency decision recorded on an
UNDER_ADJUDICATION claim; appeal window anchored on the mailing date."""
from flask import Blueprint

from db import STORE
from errors import err, ERR_CLAIM_NOT_UNDER_ADJUDICATION
from middleware import require_roles
from response import paginate, success
from routes.state_rules import find_rule_by_code
from services.core import find_or_404, new_record, serialize, sorted_created, touch
from services.deadlines import calendar_window_due
from util import as_dt, as_int, as_str, body_json, check_enum, opt, req

bp = Blueprint("determinations", __name__)

OUTCOMES = ("ALLOWED", "DENIED", "ALLOWED_NO_CHARGE")


@bp.post("/ui/claims/<cid>/determinations")
def create_determination(cid):
    require_roles("AgencyLiaison")
    body = body_json()
    outcome = check_enum(as_str(req(body, "outcome"), "outcome"), OUTCOMES, "outcome")
    mailed_at = as_dt(req(body, "mailed_at"), "mailed_at")
    disqualification_weeks = as_int(opt(body, "disqualification_weeks", 0), "disqualification_weeks")

    claim = find_or_404(STORE.claims, cid, "claim")
    if claim["status"] != "UNDER_ADJUDICATION":
        raise err(ERR_CLAIM_NOT_UNDER_ADJUDICATION, 409, "claim is not UNDER_ADJUDICATION")

    rule = find_rule_by_code(claim["state_code"])
    if rule is None:
        from errors import not_found
        raise not_found("state rule")
    appeal_due = calendar_window_due(mailed_at, rule["appeal_window_days"], rule)

    rec = new_record({
        "claim_id": cid,
        "outcome": outcome,
        "mailed_at": mailed_at,
        "appeal_due_at": appeal_due,
        "disqualification_weeks": disqualification_weeks,
        "status": "ISSUED",
    })
    STORE.determinations[rec["id"]] = rec

    claim["status"] = "DETERMINED"
    claim["adjudication_posture"] = "STANDARD"
    touch(claim)

    # a DENIED outcome vindicates a DISPUTED employer coding
    if outcome == "DENIED":
        sep = STORE.separations.get(claim["separation_id"])
        if sep is not None and sep["reason_coding_confidence"] == "DISPUTED":
            sep["reason_coding_confidence"] = "CONFIRMED"
            touch(sep)
    return success(serialize(rec), 201)


@bp.get("/ui/determinations/<rid>")
def get_determination(rid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "AgencyLiaison", "RatingAnalyst")
    rec = find_or_404(STORE.determinations, rid, "determination")
    return success(serialize(rec))


@bp.get("/ui/determinations/<rid>/appeals")
def determination_appeals(rid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "AgencyLiaison")
    find_or_404(STORE.determinations, rid, "determination")
    items = [serialize(a) for a in sorted_created(STORE.appeals.values()) if a["determination_id"] == rid]
    return paginate(items)
