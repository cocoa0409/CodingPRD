"""UiClaim endpoints: notice intake, listing, reverse reachability, withdraw
and close."""
from datetime import timedelta

from flask import Blueprint, request

from db import STORE
from errors import (
    err,
    ERR_APPEAL_IN_FLIGHT,
    ERR_CLAIM_NOT_CLOSABLE,
    ERR_CLAIM_NOT_WITHDRAWABLE,
    ERR_CROSS_PARENT_REFERENCE,
    ERR_DETERMINATION_NOT_FINAL,
    ERR_DUPLICATE_ACTIVE_RECORD,
)
from middleware import require_roles
from response import paginate, success
from routes.state_rules import find_rule_by_code
from services.core import (
    find_or_404,
    new_record,
    now,
    serialize,
    sorted_created,
    touch,
)
from services.deadlines import response_due_at
from services.scoring import recompute_posture
from util import as_dt, as_int, as_str, body_json, req

bp = Blueprint("claims", __name__)

CLAIM_STATUSES = (
    "NOTICE_RECEIVED", "RESPONSE_IN_PROGRESS", "RESPONSE_SUBMITTED",
    "LATE_RESPONSE", "UNDER_ADJUDICATION", "DETERMINED", "HEARING_PENDING",
    "CLOSED", "WITHDRAWN",
)

POSTURE_WINDOW = timedelta(days=2)


def compute_posture(claim):
    """adjudication_posture: EXPEDITED while the claim is in NOTICE_RECEIVED /
    RESPONSE_IN_PROGRESS and no more than 48 hours remain before the response
    deadline; STANDARD otherwise."""
    if claim["status"] in ("NOTICE_RECEIVED", "RESPONSE_IN_PROGRESS"):
        if claim["response_due_at"] - now() <= POSTURE_WINDOW:
            return "EXPEDITED"
    return "STANDARD"


@bp.post("/ui/claims")
def create_claim():
    require_roles("ClaimsAnalyst", "AgencyLiaison")
    body = body_json()
    employer_id = as_str(req(body, "employer_id"), "employer_id")
    separation_id = as_str(req(body, "separation_id"), "separation_id")
    state_code = as_str(req(body, "state_code"), "state_code")
    state_claim_number = as_str(req(body, "state_claim_number"), "state_claim_number")
    notice_received_at = as_dt(req(body, "notice_received_at"), "notice_received_at")
    benefit_year_begin = as_dt(req(body, "benefit_year_begin"), "benefit_year_begin")
    weekly_benefit_amount_cents = as_int(
        req(body, "weekly_benefit_amount_cents"), "weekly_benefit_amount_cents"
    )
    max_benefit_cents = as_int(req(body, "max_benefit_cents"), "max_benefit_cents")
    # body FK resolution
    find_or_404(STORE.employers, employer_id, "employer")
    sep = find_or_404(STORE.separations, separation_id, "separation")
    rule = find_rule_by_code(state_code)
    if rule is None:
        from errors import not_found
        raise not_found("state rule")
    # cross-parent: the separation must belong to the claim's employer
    if sep["employer_id"] != employer_id:
        raise err(
            ERR_CROSS_PARENT_REFERENCE,
            422,
            "separation belongs to a different employer than the claim",
        )
    # uniqueness: state_claim_number unique within its state
    for c in STORE.claims.values():
        if c["state_code"] == state_code and c["state_claim_number"] == state_claim_number:
            raise err(
                ERR_DUPLICATE_ACTIVE_RECORD,
                409,
                "state_claim_number already exists within this state",
            )
    due = response_due_at(notice_received_at, rule)
    rec = new_record({
        "employer_id": employer_id,
        "separation_id": separation_id,
        "state_code": state_code,
        "state_claim_number": state_claim_number,
        "notice_received_at": notice_received_at,
        "response_due_at": due,
        "benefit_year_begin": benefit_year_begin,
        "weekly_benefit_amount_cents": weekly_benefit_amount_cents,
        "max_benefit_cents": max_benefit_cents,
        "charged_amount_cents": 0,
        "status": "NOTICE_RECEIVED",
        "response_channel": None,
        "adjudication_posture": "STANDARD",
    })
    rec["adjudication_posture"] = compute_posture(rec)
    STORE.claims[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/ui/claims")
def list_claims():
    require_roles("PlatformAdmin", "ClaimsAnalyst", "TpaAgent", "ChargeAuditor", "AgencyLiaison")
    employer_id = request.args.get("employer_id")
    state_code = request.args.get("state_code")
    status = request.args.get("status")
    separation_id = request.args.get("separation_id")
    items = []
    for c in sorted_created(STORE.claims.values()):
        if employer_id is not None and c["employer_id"] != employer_id:
            continue
        if state_code is not None and c["state_code"] != state_code:
            continue
        if status is not None and c["status"] != status:
            continue
        if separation_id is not None and c["separation_id"] != separation_id:
            continue
        items.append(serialize(c))
    return paginate(items)


@bp.get("/ui/claims/<cid>")
def get_claim(cid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "TpaAgent", "ChargeAuditor", "AgencyLiaison")
    rec = find_or_404(STORE.claims, cid, "claim")
    return success(serialize(rec))


@bp.get("/ui/claims/<cid>/responses")
def claim_responses(cid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "TpaAgent", "AgencyLiaison")
    find_or_404(STORE.claims, cid, "claim")
    items = [serialize(r) for r in sorted_created(STORE.responses.values()) if r["claim_id"] == cid]
    return paginate(items)


@bp.get("/ui/claims/<cid>/evidence")
def claim_evidence(cid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "TpaAgent", "AgencyLiaison")
    find_or_404(STORE.claims, cid, "claim")
    items = [serialize(d) for d in sorted_created(STORE.evidence.values()) if d["claim_id"] == cid]
    return paginate(items)


@bp.get("/ui/claims/<cid>/determinations")
def claim_determinations(cid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "AgencyLiaison")
    find_or_404(STORE.claims, cid, "claim")
    items = [serialize(d) for d in sorted_created(STORE.determinations.values()) if d["claim_id"] == cid]
    return paginate(items)


@bp.get("/ui/claims/<cid>/hearings")
def claim_hearings(cid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "AgencyLiaison")
    find_or_404(STORE.claims, cid, "claim")
    items = [serialize(h) for h in sorted_created(STORE.hearings.values()) if h["claim_id"] == cid]
    return paginate(items)


@bp.get("/ui/claims/<cid>/charge-line-items")
def claim_charge_lines(cid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "ChargeAuditor", "AgencyLiaison")
    find_or_404(STORE.claims, cid, "claim")
    items = [serialize(l) for l in sorted_created(STORE.charge_lines.values()) if l["claim_id"] == cid]
    return paginate(items)


@bp.post("/ui/claims/<cid>/withdraw")
def withdraw_claim(cid):
    require_roles("AgencyLiaison")
    claim = find_or_404(STORE.claims, cid, "claim")
    if claim["status"] not in ("NOTICE_RECEIVED", "RESPONSE_IN_PROGRESS"):
        raise err(ERR_CLAIM_NOT_WITHDRAWABLE, 409, "claim is beyond the withdrawable window")
    claim["status"] = "WITHDRAWN"
    claim["adjudication_posture"] = compute_posture(claim)
    touch(claim)
    for resp in STORE.responses.values():
        if resp["claim_id"] == cid and resp["status"] == "DRAFT":
            resp["status"] = "SUPERSEDED"
            touch(resp)
    return success(serialize(claim))


@bp.post("/ui/claims/<cid>/close")
def close_claim(cid):
    require_roles("ClaimsAnalyst")
    claim = find_or_404(STORE.claims, cid, "claim")
    if claim["status"] != "DETERMINED":
        raise err(ERR_CLAIM_NOT_CLOSABLE, 409, "only a DETERMINED claim can close")
    dets = [d for d in sorted_created(STORE.determinations.values()) if d["claim_id"] == cid]
    latest_det = dets[-1] if dets else None
    if latest_det is None or latest_det["status"] != "FINAL":
        raise err(ERR_DETERMINATION_NOT_FINAL, 409, "claim's determination is not FINAL")
    det_ids = {d["id"] for d in dets}
    for ap in STORE.appeals.values():
        if ap["determination_id"] in det_ids and ap["status"] in ("FILED", "DOCKETED", "HEARD"):
            raise err(ERR_APPEAL_IN_FLIGHT, 409, "an appeal is still in flight for this claim")
    claim["status"] = "CLOSED"
    claim["adjudication_posture"] = compute_posture(claim)
    touch(claim)
    emp = STORE.employers.get(claim["employer_id"])
    if emp is not None:
        recompute_posture(emp)
        touch(emp)
    return success(serialize(claim))
