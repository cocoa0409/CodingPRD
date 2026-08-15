"""ClaimResponse endpoints: drafting, submission (OCC on the claim), agency
accept/reject with segregation of duties, and amendment/evidence reachability."""
from flask import Blueprint, g

from db import STORE
from errors import (
    err,
    ERR_AUTHORITY_VIOLATION,
    ERR_CLAIM_NOT_RESPONSIVE,
    ERR_CROSS_PARENT_REFERENCE,
    ERR_INVALID_REQUEST,
    ERR_RESPONSE_INCOMPLETE,
    ERR_RESPONSE_NOT_DRAFT,
    ERR_RESPONSE_NOT_SUBMITTED,
    ERR_STALE_VERSION,
    ERR_TPA_NOT_ACTIVE,
    ERR_TPA_SCOPE_VIOLATION,
)
from middleware import require_roles
from response import paginate, success
from routes.claims import compute_posture
from routes.tpa import FILING_STATUSES, scope_covers_response
from services.core import find_or_404, new_record, now, serialize, sorted_created, touch
from services.scoring import assembly_score, recompute_posture, SUBMIT_THRESHOLD
from services.deadlines import timeliness as compute_timeliness
from util import as_int, as_str, body_json, check_enum, opt, req

bp = Blueprint("responses", __name__)

RESPONSE_TYPES = ("PROTEST", "NO_PROTEST", "INFORMATION_ONLY")
SEPARATION_REASONS = (
    "VOLUNTARY_QUIT",
    "DISCHARGE_MISCONDUCT",
    "DISCHARGE_NON_MISCONDUCT",
    "LAYOFF",
    "LEAVE_OF_ABSENCE",
)


def _check_tpa_draft_authority(claim, filed_by_tpa_id):
    """Draft-time TPA authority (§3.1): an ACTIVE-form engagement must cover
    the claim's employer and its scope must authorize response filings."""
    if filed_by_tpa_id is not None:
        eng = find_or_404(STORE.tpa_engagements, filed_by_tpa_id, "tpa engagement")
        if eng["employer_id"] != claim["employer_id"]:
            raise err(
                ERR_CROSS_PARENT_REFERENCE,
                422,
                "engagement belongs to a different employer than the claim",
            )
        # While SUSPENDED (or TERMINATED) every filing under it is rejected
        if eng["oversight_status"] not in FILING_STATUSES:
            raise err(ERR_TPA_NOT_ACTIVE, 403, "engagement is suspended or terminated")
        if not scope_covers_response(eng):
            raise err(
                ERR_TPA_SCOPE_VIOLATION,
                403,
                "engagement authority_scope does not authorize response filings",
            )
        return
    # No engagement named: some ACTIVE-form, in-scope engagement must cover
    # the claim's employer or the draft is a scope violation.
    for eng in STORE.tpa_engagements.values():
        if (
            eng["employer_id"] == claim["employer_id"]
            and eng["oversight_status"] in FILING_STATUSES
            and scope_covers_response(eng)
        ):
            return
    raise err(
        ERR_TPA_SCOPE_VIOLATION,
        403,
        "no ACTIVE engagement with response-filing scope covers this employer",
    )


@bp.post("/ui/claims/<cid>/responses")
def draft_response(cid):
    require_roles("ClaimsAnalyst", "TpaAgent")
    # body well-formedness runs before path existence (validation tier 2.5)
    body = body_json()
    response_type = check_enum(
        as_str(req(body, "response_type"), "response_type"), RESPONSE_TYPES, "response_type"
    )
    separation_reason_code = check_enum(
        as_str(req(body, "separation_reason_code"), "separation_reason_code"),
        SEPARATION_REASONS, "separation_reason_code",
    )
    narrative = req(body, "narrative")
    if not isinstance(narrative, str):
        raise err(ERR_INVALID_REQUEST, 400, "field must be a string: narrative")
    filed_by_tpa_id = opt(body, "filed_by_tpa_id")
    if filed_by_tpa_id is not None:
        filed_by_tpa_id = as_str(filed_by_tpa_id, "filed_by_tpa_id")
    amendment_of = opt(body, "amendment_of")
    if amendment_of is not None:
        amendment_of = as_str(amendment_of, "amendment_of")

    claim = find_or_404(STORE.claims, cid, "claim")

    # body FK resolution + cross-parent integrity
    amended = None
    if amendment_of is not None:
        amended = find_or_404(STORE.responses, amendment_of, "response")
        if amended["claim_id"] != cid:
            raise err(
                ERR_CROSS_PARENT_REFERENCE,
                422,
                "amended response belongs to a different claim",
            )

    # state precondition: drafting is possible from NOTICE_RECEIVED /
    # RESPONSE_IN_PROGRESS, and from RESPONSE_SUBMITTED only for amendments
    if claim["status"] not in ("NOTICE_RECEIVED", "RESPONSE_IN_PROGRESS", "RESPONSE_SUBMITTED"):
        raise err(ERR_CLAIM_NOT_RESPONSIVE, 409, "claim does not accept response drafts")
    if claim["status"] == "RESPONSE_SUBMITTED" and amendment_of is None:
        raise err(ERR_CLAIM_NOT_RESPONSIVE, 409, "only an amendment may be drafted from RESPONSE_SUBMITTED")

    # the asserted reason code must equal the separation's recorded reason
    sep = STORE.separations.get(claim["separation_id"])
    if sep is not None and separation_reason_code != sep["separation_reason"]:
        raise err(
            ERR_INVALID_REQUEST,
            400,
            "separation_reason_code must equal the separation's recorded reason",
        )

    # TPA authority at filing time
    if g.user_role == "TpaAgent":
        _check_tpa_draft_authority(claim, filed_by_tpa_id)

    rec = new_record({
        "claim_id": cid,
        "filed_by_tpa_id": filed_by_tpa_id,
        "response_type": response_type,
        "separation_reason_code": separation_reason_code,
        "narrative": narrative,
        "filed_at": None,
        "timeliness": None,
        "completeness_score": assembly_score(claim),
        "status": "DRAFT",
        "amendment_of": amendment_of,
        "_created_by": g.user_id,
    })
    STORE.responses[rec["id"]] = rec

    # an amendment filing supersedes the DRAFT it amends
    if amended is not None and amended["status"] == "DRAFT":
        amended["status"] = "SUPERSEDED"
        touch(amended)

    # claim side effects: first draft advances NOTICE_RECEIVED ->
    # RESPONSE_IN_PROGRESS; posture recomputed; version bumps in all cases
    if claim["status"] == "NOTICE_RECEIVED":
        claim["status"] = "RESPONSE_IN_PROGRESS"
    claim["adjudication_posture"] = compute_posture(claim)
    touch(claim)
    return success(serialize(rec), 201)


@bp.get("/ui/responses/<rid>")
def get_response(rid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "TpaAgent", "AgencyLiaison")
    rec = find_or_404(STORE.responses, rid, "response")
    return success(serialize(rec))


@bp.get("/ui/responses/<rid>/amendments")
def response_amendments(rid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "TpaAgent", "AgencyLiaison")
    find_or_404(STORE.responses, rid, "response")
    items = [
        serialize(r) for r in sorted_created(STORE.responses.values())
        if r["amendment_of"] == rid
    ]
    return paginate(items)


@bp.get("/ui/responses/<rid>/evidence")
def response_evidence(rid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "TpaAgent", "AgencyLiaison")
    find_or_404(STORE.responses, rid, "response")
    items = [
        serialize(d) for d in sorted_created(STORE.evidence.values())
        if d["response_id"] == rid
    ]
    return paginate(items)


def _resolve_response_under_claim(cid, rid):
    """Path ids left-to-right, then the nested parent-scope check."""
    claim = find_or_404(STORE.claims, cid, "claim")
    resp = find_or_404(STORE.responses, rid, "response")
    if resp["claim_id"] != cid:
        raise err(
            ERR_CROSS_PARENT_REFERENCE,
            422,
            "response belongs to a different claim than the path scope",
        )
    return claim, resp


def _late_cascades(claim, resp):
    """Lateness cascade (§3.4): employer strike + posture recompute; TPA
    breach attribution with automatic suspension at three breaches."""
    emp = STORE.employers.get(claim["employer_id"])
    if emp is not None:
        emp["late_response_strikes"] += 1
        recompute_posture(emp)
        touch(emp)
    if resp["filed_by_tpa_id"] is not None:
        eng = STORE.tpa_engagements.get(resp["filed_by_tpa_id"])
        if eng is not None:
            eng["breach_count"] += 1
            if eng["breach_count"] >= 3 and eng["oversight_status"] in ("ACTIVE", "REINSTATED"):
                eng["oversight_status"] = "SUSPENDED"
            touch(eng)


@bp.post("/ui/claims/<cid>/responses/<rid>/submit")
def submit_response(cid, rid):
    require_roles("ClaimsAnalyst", "TpaAgent")
    body = body_json()
    expected_claim_version = as_int(
        req(body, "expected_claim_version"), "expected_claim_version"
    )
    claim, resp = _resolve_response_under_claim(cid, rid)
    # state precondition
    if resp["status"] != "DRAFT":
        raise err(ERR_RESPONSE_NOT_DRAFT, 409, "response is not DRAFT")
    # TPA authority: the engagement must be ACTIVE-form and inside its
    # effective window at the moment of filing
    if resp["filed_by_tpa_id"] is not None:
        eng = STORE.tpa_engagements.get(resp["filed_by_tpa_id"])
        filing_moment = now()
        if (
            eng is None
            or eng["oversight_status"] not in FILING_STATUSES
            or not (eng["effective_from"] <= filing_moment <= eng["effective_to"])
        ):
            raise err(ERR_TPA_NOT_ACTIVE, 403, "engagement is not active and in-window at filing time")
    # evidence sufficiency: submit re-checks the assembly score over the
    # claim's current evidence pool
    resp["completeness_score"] = assembly_score(claim)
    if resp["completeness_score"] < SUBMIT_THRESHOLD:
        raise err(ERR_RESPONSE_INCOMPLETE, 422, "completeness_score below 40 at submit")
    # optimistic concurrency runs last so business errors surface first
    if expected_claim_version != claim["version"]:
        raise err(ERR_STALE_VERSION, 412, "expected_claim_version does not match the claim's current version")

    filed_at = now()
    resp["filed_at"] = filed_at
    resp["timeliness"] = compute_timeliness(filed_at, claim["response_due_at"])
    resp["status"] = "SUBMITTED"
    touch(resp)

    claim["response_channel"] = "TPA" if resp["filed_by_tpa_id"] else "SELF"
    if resp["timeliness"] == "LATE":
        claim["status"] = "LATE_RESPONSE"
    else:
        claim["status"] = "RESPONSE_SUBMITTED"
    claim["adjudication_posture"] = compute_posture(claim)
    touch(claim)

    if resp["timeliness"] == "LATE":
        _late_cascades(claim, resp)
    return success(serialize(resp))


def _segregation_of_duties(resp):
    """The operator who drafted a response cannot accept or reject it."""
    if g.user_id == resp["_created_by"]:
        raise err(
            ERR_AUTHORITY_VIOLATION,
            403,
            "the drafting operator may not accept or reject this response",
        )


@bp.post("/ui/claims/<cid>/responses/<rid>/accept")
def accept_response(cid, rid):
    require_roles("AgencyLiaison")
    claim, resp = _resolve_response_under_claim(cid, rid)
    if resp["status"] != "SUBMITTED":
        raise err(ERR_RESPONSE_NOT_SUBMITTED, 409, "response is not SUBMITTED")
    _segregation_of_duties(resp)
    resp["status"] = "ACCEPTED"
    touch(resp)
    # every other SUBMITTED/DRAFT response on the claim is superseded —
    # including the earlier response an accepted amendment named
    for other in STORE.responses.values():
        if other["id"] != rid and other["claim_id"] == cid and other["status"] in ("SUBMITTED", "DRAFT"):
            other["status"] = "SUPERSEDED"
            touch(other)
    return success(serialize(resp))


@bp.post("/ui/claims/<cid>/responses/<rid>/reject")
def reject_response(cid, rid):
    require_roles("AgencyLiaison")
    claim, resp = _resolve_response_under_claim(cid, rid)
    if resp["status"] != "SUBMITTED":
        raise err(ERR_RESPONSE_NOT_SUBMITTED, 409, "response is not SUBMITTED")
    _segregation_of_duties(resp)
    resp["status"] = "REJECTED_INSUFFICIENT"
    touch(resp)
    # rejection challenges the employer's reason coding
    sep = STORE.separations.get(claim["separation_id"])
    if sep is not None:
        sep["reason_coding_confidence"] = "DISPUTED"
        touch(sep)
    return success(serialize(resp))
