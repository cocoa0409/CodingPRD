"""Appeal endpoints: filing (timeliness branch), withdrawal, and the
three-way decision (AFFIRM / REVERSE / REMAND) with charge compensation."""
from flask import Blueprint

from db import STORE
from errors import (
    err,
    ERR_APPEAL_NOT_HEARD,
    ERR_APPEAL_NOT_WITHDRAWABLE,
    ERR_DETERMINATION_NOT_APPEALABLE,
)
from middleware import require_roles
from response import paginate, success
from services.core import find_or_404, new_record, now, serialize, sorted_created, touch
from services.deadlines import timeliness as compute_timeliness
from services.rating import supersede_models
from util import as_str, body_json, check_enum, req

bp = Blueprint("appeals", __name__)

APPELLANTS = ("EMPLOYER", "CLAIMANT")
DECISIONS = ("AFFIRM", "REVERSE", "REMAND")


def _claim_for(det):
    return STORE.claims.get(det["claim_id"])


def _next_round_number(claim_id):
    """A re-appeal after remand carries one more than the remanded appeal's
    round number."""
    det_ids = {
        d["id"] for d in STORE.determinations.values() if d["claim_id"] == claim_id
    }
    remanded_rounds = [
        a["round_number"]
        for a in STORE.appeals.values()
        if a["determination_id"] in det_ids and a["status"] == "REMANDED"
    ]
    return max(remanded_rounds) + 1 if remanded_rounds else 1


@bp.post("/ui/determinations/<did>/appeals")
def file_appeal(did):
    require_roles("ClaimsAnalyst", "AgencyLiaison")
    body = body_json()
    appellant = check_enum(as_str(req(body, "appellant"), "appellant"), APPELLANTS, "appellant")
    grounds = req(body, "grounds")
    from errors import ERR_INVALID_REQUEST
    if not isinstance(grounds, str):
        raise err(ERR_INVALID_REQUEST, 400, "field must be a string: grounds")

    det = find_or_404(STORE.determinations, did, "determination")
    if det["status"] != "ISSUED":
        raise err(ERR_DETERMINATION_NOT_APPEALABLE, 409, "determination is not ISSUED")

    claim = _claim_for(det)
    filed_at = now()
    tl = compute_timeliness(filed_at, det["appeal_due_at"])

    rec = new_record({
        "determination_id": did,
        "appellant": appellant,
        "filed_at": filed_at,
        "timeliness": tl,
        "grounds": grounds,
        "round_number": _next_round_number(det["claim_id"]),
        "status": "FILED",
    })

    if tl == "LATE":
        # detected at filing: dismissed outright, determination finalizes,
        # claim stays DETERMINED
        rec["status"] = "DISMISSED_UNTIMELY"
        STORE.appeals[rec["id"]] = rec
        det["status"] = "FINAL"
        touch(det)
        return success(serialize(rec), 201)

    STORE.appeals[rec["id"]] = rec
    det["status"] = "APPEALED_BY_EMPLOYER" if appellant == "EMPLOYER" else "APPEALED_BY_CLAIMANT"
    touch(det)
    if claim is not None:
        claim["status"] = "HEARING_PENDING"
        touch(claim)
    return success(serialize(rec), 201)


@bp.get("/ui/appeals/<rid>")
def get_appeal(rid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "AgencyLiaison")
    rec = find_or_404(STORE.appeals, rid, "appeal")
    return success(serialize(rec))


@bp.get("/ui/appeals/<rid>/hearings")
def appeal_hearings(rid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "AgencyLiaison")
    find_or_404(STORE.appeals, rid, "appeal")
    items = [serialize(h) for h in sorted_created(STORE.hearings.values()) if h["appeal_id"] == rid]
    return paginate(items)


@bp.post("/ui/appeals/<rid>/withdraw")
def withdraw_appeal(rid):
    require_roles("ClaimsAnalyst")
    ap = find_or_404(STORE.appeals, rid, "appeal")
    if ap["status"] not in ("FILED", "DOCKETED"):
        raise err(ERR_APPEAL_NOT_WITHDRAWABLE, 409, "appeal is not withdrawable")
    ap["status"] = "WITHDRAWN"
    touch(ap)
    det = STORE.determinations.get(ap["determination_id"])
    if det is not None:
        det["status"] = "FINAL"
        touch(det)
        claim = _claim_for(det)
        if claim is not None and claim["status"] == "HEARING_PENDING":
            claim["status"] = "DETERMINED"
            touch(claim)
    # any hearing still in preparation is closed; witness rows remain frozen
    for h in STORE.hearings.values():
        if h["appeal_id"] == rid and h["status"] in ("SCHEDULED", "PREP_IN_PROGRESS", "READY"):
            h["status"] = "CLOSED"
            touch(h)
    return success(serialize(ap))


def _reverse_allowed_charges(claim):
    """Every PENDING/SUSTAINED line on the reversed claim auto-reverses; each
    reversal decrements statement total and claim charged amount, and the
    employer reserve is credited exactly once per reversed line."""
    emp = STORE.employers.get(claim["employer_id"])
    credited = 0
    for line in STORE.charge_lines.values():
        if line["claim_id"] != claim["id"] or line["status"] not in ("PENDING", "SUSTAINED"):
            continue
        line["status"] = "REVERSED"
        touch(line)
        stmt = STORE.charge_statements.get(line["statement_id"])
        if stmt is not None:
            stmt["total_charged_cents"] -= line["amount_cents"]
            touch(stmt)
        claim["charged_amount_cents"] -= line["amount_cents"]
        credited += line["amount_cents"]
    if credited:
        touch(claim)
    if emp is not None and credited:
        emp["reserve_balance_cents"] += credited
        touch(emp)


@bp.post("/ui/appeals/<rid>/decide")
def decide_appeal(rid):
    require_roles("AgencyLiaison")
    body = body_json()
    decision = check_enum(as_str(req(body, "decision"), "decision"), DECISIONS, "decision")
    ap = find_or_404(STORE.appeals, rid, "appeal")
    if ap["status"] != "HEARD":
        raise err(ERR_APPEAL_NOT_HEARD, 409, "appeal has not been HEARD")
    det = STORE.determinations.get(ap["determination_id"])
    claim = _claim_for(det) if det is not None else None

    if decision == "AFFIRM":
        ap["status"] = "DECIDED_AFFIRMED"
        touch(ap)
        if det is not None:
            det["status"] = "FINAL"
            touch(det)
        if claim is not None:
            claim["status"] = "DETERMINED"
            touch(claim)
    elif decision == "REVERSE":
        ap["status"] = "DECIDED_REVERSED"
        touch(ap)
        was_allowed = det is not None and det["outcome"] == "ALLOWED"
        if det is not None:
            det["status"] = "REVERSED"
            touch(det)
        if was_allowed and claim is not None:
            _reverse_allowed_charges(claim)
        # rating inputs invalidated — all of the employer's models supersede
        if claim is not None:
            supersede_models(claim["employer_id"], include_finalized=True)
    else:  # REMAND
        ap["status"] = "REMANDED"
        touch(ap)
        if det is not None:
            det["status"] = "REVERSED"
            touch(det)
        if claim is not None:
            claim["status"] = "UNDER_ADJUDICATION"
            touch(claim)
    return success(serialize(ap))
