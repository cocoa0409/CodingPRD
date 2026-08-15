"""Routes: exhibition agreements."""

from flask import Blueprint, request

import domain as D
from errors import (err409, err_invalid_state, err_not_found,
                    err_stale_version)
from store import DB
from util import (auth, check_ownership, created_key, get_body, get_or_404,
                  ok, paginate, require_role, v_dt, v_enum, v_int, v_num)

bp = Blueprint("agreements", __name__)

AGR_READ = ["FESTIVAL_ADMIN", "FESTIVAL_DIRECTOR", "SCHEDULING_OPS",
            "FILMMAKER"]
DIRECTOR = ["FESTIVAL_DIRECTOR"]


def _own_check(uid, role, agreement):
    if role == "FILMMAKER":
        sub = DB.submissions.get(agreement["submission_id"])
        check_ownership(sub is not None and sub["submitter_id"] == uid)


@bp.get("/festival/exhibition-agreements/<aid>")
def get_agreement(aid):
    uid, role = auth()
    require_role(role, AGR_READ)
    rec = get_or_404(DB.agreements, aid)
    _own_check(uid, role, rec)
    return ok(D.ser_agreement(rec))


@bp.get("/festival/exhibition-agreements")
def list_agreements():
    uid, role = auth()
    require_role(role, AGR_READ)
    items = list(DB.agreements.values())
    if role == "FILMMAKER":
        own = {s["id"] for s in DB.submissions.values()
               if s["submitter_id"] == uid}
        items = [a for a in items if a["submission_id"] in own]
    submission_id = request.args.get("submission_id")
    slate_entry_id = request.args.get("slate_entry_id")
    status = request.args.get("status")
    if submission_id is not None:
        items = [a for a in items if a["submission_id"] == submission_id]
    if slate_entry_id is not None:
        items = [a for a in items if a["slate_entry_id"] == slate_entry_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_agreement(a) for a in page], pagination=meta)


@bp.post("/festival/exhibition-agreements/<aid>/issue")
def issue_agreement(aid):
    body = get_body()
    rights_scope = v_enum(body, "rights_scope", D.RIGHTS_SCOPES)
    licensed = v_int(body, "licensed_screening_count", min_v=0)
    exclusivity_until = v_dt(body, "exclusivity_until")
    revenue_share_pct = v_num(body, "revenue_share_pct")
    uid, role = auth()
    require_role(role, DIRECTOR)
    rec = get_or_404(DB.agreements, aid)
    if rec["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT agreement may be issued")
    rec["rights_scope"] = rights_scope
    rec["licensed_screening_count"] = licensed
    rec["exclusivity_until"] = exclusivity_until
    rec["revenue_share_pct"] = revenue_share_pct
    rec["status"] = "ISSUED"
    D.touch(rec)
    return ok(D.ser_agreement(rec))


@bp.post("/festival/exhibition-agreements/<aid>/sign")
def sign_agreement(aid):
    get_body()
    uid, role = auth()
    require_role(role, ["FILMMAKER"])
    rec = get_or_404(DB.agreements, aid)
    _own_check(uid, role, rec)
    if rec["status"] != "ISSUED":
        raise err_invalid_state("Only an ISSUED agreement may be signed")
    sub = DB.submissions.get(rec["submission_id"])
    # Version-pinning on approval: pin the submission's current version.
    rec["submission_version_at_signing"] = sub["version"] if sub else None
    rec["status"] = "SIGNED"
    D.touch(rec)
    return ok(D.ser_agreement(rec))


@bp.post("/festival/exhibition-agreements/<aid>/amend")
def amend_agreement(aid):
    body = get_body()
    expected_version = v_int(body, "expected_agreement_version")
    rights_scope = v_enum(body, "rights_scope", D.RIGHTS_SCOPES,
                          required=False)
    licensed = v_int(body, "licensed_screening_count", required=False,
                     min_v=0)
    exclusivity_until = v_dt(body, "exclusivity_until", required=False)
    revenue_share_pct = v_num(body, "revenue_share_pct", required=False)
    uid, role = auth()
    require_role(role, DIRECTOR)
    rec = get_or_404(DB.agreements, aid)
    if rec["status"] not in ("SIGNED", "ACTIVE"):
        raise err_invalid_state(
            "Only a SIGNED or ACTIVE agreement may be amended")
    if licensed is not None and licensed < rec["used_screening_count"]:
        raise err409("ERR_LICENSED_BELOW_USED",
                     "Licensed count may not drop below used count")
    if expected_version != rec["version"]:
        raise err_stale_version()
    if rights_scope is not None:
        rec["rights_scope"] = rights_scope
    if licensed is not None:
        rec["licensed_screening_count"] = licensed
    if exclusivity_until is not None:
        rec["exclusivity_until"] = exclusivity_until
    if revenue_share_pct is not None:
        rec["revenue_share_pct"] = revenue_share_pct
    sub = DB.submissions.get(rec["submission_id"])
    rec["submission_version_at_signing"] = sub["version"] if sub else None
    rec["status"] = "ACTIVE"
    D.touch(rec)
    return ok(D.ser_agreement(rec))


@bp.post("/festival/exhibition-agreements/<aid>/terminate")
def terminate_agreement(aid):
    get_body()
    uid, role = auth()
    require_role(role, DIRECTOR)
    rec = get_or_404(DB.agreements, aid)
    if rec["status"] not in ("SIGNED", "ACTIVE"):
        raise err_invalid_state(
            "Only a SIGNED or ACTIVE agreement may be terminated")
    if any(s["slate_entry_id"] == rec["slate_entry_id"]
           and s["status"] in ("HELD", "CONFIRMED")
           for s in DB.slots.values()):
        raise err409("ERR_ACTIVE_SLOTS_EXIST",
                     "Held or confirmed slots still reference this entry")
    rec["status"] = "TERMINATED"
    D.touch(rec)
    return ok(D.ser_agreement(rec))
