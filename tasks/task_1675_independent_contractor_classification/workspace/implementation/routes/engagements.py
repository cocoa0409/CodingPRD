"""Engagement endpoints: intake, questionnaire, determinations, review loop,
approvals, lifecycle actions (activate/suspend/reinstate/terminate)."""

from flask import Blueprint, request

from db import store, new_id, now_iso, parse_date
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_QUESTIONNAIRE_INCOMPLETE, ERR_DETERMINATION_REQUIRED,
    ERR_DETERMINATION_STALE, ERR_STALE_VERSION,
    ERR_ENGAGEMENT_NOT_APPROVAL_PENDING, ERR_APPROVAL_OUT_OF_ORDER,
    ERR_APPROVER_ALREADY_ACTED, ERR_CONTRACT_NOT_EXECUTED,
    ERR_CONTRACTOR_STANDING_SUSPENDED, ERR_RESOURCE_NOT_FOUND,
)
from middleware import require_auth, ALL_ROLES
from response import success, paginate
from services.core import (
    stamp_new, touch, get_engagement_or_404, get_contractor_or_404,
    run_classification, recompute_risk_tier, recompute_scope_creep,
    require_high_tier_exception, lazy_expire_contract, lazy_expire_grant,
    downgrade_standing_on_revoke, FACTOR_KEYS, APPROVAL_SEQUENCE,
)

bp = Blueprint("engagements", __name__)

RATE_UNITS = {"HOURLY", "DAILY", "PROJECT"}
SUPERVISION_LEVELS = {"NONE", "LIGHT", "CLOSE"}
NON_TERMINAL_ENGAGEMENT = {
    "DRAFT", "INTAKE_SUBMITTED", "CLASSIFIED", "UNDER_REVIEW",
    "INFO_REQUESTED", "APPROVAL_PENDING", "APPROVED",
}


def _standing_gate(contractor):
    if contractor["standing_status"] not in ("GOOD_STANDING", "WATCH"):
        raise ApiError(
            ERR_CONTRACTOR_STANDING_SUSPENDED, 422,
            "Contractor standing blocks this operation",
        )


@bp.route("/api/engagements", methods=["POST"])
def create_engagement():
    require_auth(["EngagementManager"])
    body = request.get_json(silent=True) or {}

    # shape
    contractor_id = body.get("contractor_id")
    jurisdiction_id = body.get("jurisdiction_id")
    title = body.get("title")
    scope_description = body.get("scope_description")
    agreed_rate_cents = body.get("agreed_rate_cents")
    rate_unit = body.get("rate_unit")
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    supervision_level = body.get("supervision_level", "NONE")

    if not isinstance(contractor_id, str) or not contractor_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "contractor_id is required")
    if not isinstance(jurisdiction_id, str) or not jurisdiction_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "jurisdiction_id is required")
    if not title or not isinstance(title, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "title is required")
    if scope_description is None or not isinstance(scope_description, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "scope_description is required")
    if (agreed_rate_cents is None or not isinstance(agreed_rate_cents, int)
            or isinstance(agreed_rate_cents, bool) or agreed_rate_cents <= 0):
        raise ApiError(ERR_INVALID_REQUEST, 400, "agreed_rate_cents must be an integer > 0")
    if rate_unit not in RATE_UNITS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid rate_unit")
    sd = parse_date(start_date)
    ed = parse_date(end_date)
    if sd is None or ed is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "start_date/end_date must be ISO dates")
    if ed < sd:
        raise ApiError(ERR_INVALID_REQUEST, 400, "end_date must be >= start_date")
    if supervision_level not in SUPERVISION_LEVELS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid supervision_level")

    # existence (left-to-right: contractor first)
    contractor = get_contractor_or_404(contractor_id)
    jurisdiction = store.jurisdictions.get(jurisdiction_id)
    if jurisdiction is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Jurisdiction not found")

    # business safety: standing gate
    _standing_gate(contractor)

    eng = {
        "id": new_id(),
        "contractor_id": contractor_id,
        "jurisdiction_id": jurisdiction_id,
        "title": title,
        "scope_description": scope_description,
        "agreed_rate_cents": agreed_rate_cents,
        "rate_unit": rate_unit,
        "start_date": start_date,
        "end_date": end_date,
        "supervision_level": supervision_level,
        "status": "DRAFT",
        "risk_tier": None,
        "required_approval_count": None,
        "approvals_recorded": [],
        "current_determination_id": None,
        "scope_creep_index": 0,
        "scope_creep_tier": "LOW",
    }
    stamp_new(eng)
    store.engagements[eng["id"]] = eng
    return success(eng, status=201)


@bp.route("/api/engagements", methods=["GET"])
def list_engagements():
    require_auth(ALL_ROLES)
    items = list(store.engagements.values())
    contractor_id = request.args.get("contractor_id")
    jurisdiction_id = request.args.get("jurisdiction_id")
    status = request.args.get("status")
    if contractor_id:
        items = [e for e in items if e["contractor_id"] == contractor_id]
    if jurisdiction_id:
        items = [e for e in items if e["jurisdiction_id"] == jurisdiction_id]
    if status:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: e["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


@bp.route("/api/engagements/<eid>", methods=["GET"])
def get_engagement(eid):
    require_auth(ALL_ROLES)
    return success(get_engagement_or_404(eid))


# ---------------------------------------------------------------------------
# questionnaire
# ---------------------------------------------------------------------------

@bp.route("/api/engagements/<eid>/questionnaire", methods=["POST"])
def submit_questionnaire(eid):
    require_auth(["EngagementManager"])
    body = request.get_json(silent=True) or {}
    answers = body.get("answers")
    if not isinstance(answers, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "answers must be a list")
    seen = set()
    for a in answers:
        if not isinstance(a, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "answer entries must be objects")
        fk = a.get("factor_key")
        ans = a.get("answer")
        if fk not in FACTOR_KEYS:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid factor_key")
        if ans not in ("YES", "NO"):
            raise ApiError(ERR_INVALID_REQUEST, 400, "answer must be YES or NO")
        if fk in seen:
            # duplicate factor key -> shape-level invalid? PRD says duplicates leave
            # questionnaire incomplete rather than 400; keep as incomplete.
            pass
        seen.add(fk)

    eng = get_engagement_or_404(eid)
    if eng["status"] not in ("DRAFT", "INTAKE_SUBMITTED", "CLASSIFIED", "INFO_REQUESTED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Questionnaire not accepted in this status")

    complete = (len(seen) == 8 and len(answers) == 8)
    existing = store.questionnaires.get(eid)
    if existing is None:
        q = {
            "id": new_id(),
            "engagement_id": eid,
            "answers": answers,
            "revision": 1,
            "complete": complete,
            "submitted_at": now_iso(),
        }
        stamp_new(q)
        store.questionnaires[eid] = q
    else:
        q = existing
        q["answers"] = answers
        q["revision"] += 1
        q["complete"] = complete
        q["submitted_at"] = now_iso()
        touch(q)

    if eng["status"] == "DRAFT":
        eng["status"] = "INTAKE_SUBMITTED"
    elif eng["status"] == "INFO_REQUESTED":
        eng["status"] = "UNDER_REVIEW"
    touch(eng)
    return success(q)


@bp.route("/api/engagements/<eid>/questionnaire", methods=["GET"])
def get_questionnaire(eid):
    require_auth(ALL_ROLES)
    get_engagement_or_404(eid)
    q = store.questionnaires.get(eid)
    items = [q] if q else []
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


# ---------------------------------------------------------------------------
# determinations
# ---------------------------------------------------------------------------

@bp.route("/api/engagements/<eid>/determinations", methods=["POST"])
def create_determination(eid):
    require_auth(["ClassificationAnalyst"])
    body = request.get_json(silent=True) or {}
    expected = body.get("expected_engagement_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_engagement_version is required")

    eng = get_engagement_or_404(eid)
    if eng["status"] not in ("INTAKE_SUBMITTED", "CLASSIFIED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Determination not allowed in this status")
    if expected != eng["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Stale engagement version")

    q = store.questionnaires.get(eid)
    if q is None or not q["complete"]:
        raise ApiError(ERR_QUESTIONNAIRE_INCOMPLETE, 422, "Questionnaire incomplete")

    outcome, score, failed_prongs = run_classification(eng, q)
    jur = store.jurisdictions[eng["jurisdiction_id"]]

    # supersede prior
    prior_id = eng.get("current_determination_id")
    if prior_id and prior_id in store.determinations:
        store.determinations[prior_id]["superseded"] = True

    det = {
        "id": new_id(),
        "engagement_id": eid,
        "jurisdiction_test_type": jur["test_type"],
        "questionnaire_revision": q["revision"],
        "outcome": outcome,
        "score": score,
        "failed_prongs": failed_prongs,
        "superseded": False,
        "created_at": now_iso(),
    }
    store.determinations[det["id"]] = det
    eng["current_determination_id"] = det["id"]
    eng["status"] = "CLASSIFIED"
    recompute_risk_tier(eng)
    touch(eng)
    return success(det, status=201)


@bp.route("/api/engagements/<eid>/determinations", methods=["GET"])
def list_determinations(eid):
    require_auth(ALL_ROLES)
    get_engagement_or_404(eid)
    items = [d for d in store.determinations.values() if d["engagement_id"] == eid]
    # newest first (exception to default ordering). created_at is stamped from the
    # logical clock, so ties are common; a stable ascending sort followed by a
    # reverse resolves ties toward the most recently created record.
    items.sort(key=lambda d: d["created_at"])
    items.reverse()
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


# ---------------------------------------------------------------------------
# review pipeline
# ---------------------------------------------------------------------------

@bp.route("/api/engagements/<eid>/submit-review", methods=["POST"])
def submit_review(eid):
    require_auth(["EngagementManager"])
    get_engagement_or_404_body = request.get_json(silent=True) or {}
    eng = get_engagement_or_404(eid)
    if eng["status"] != "CLASSIFIED":
        raise ApiError(ERR_INVALID_STATE, 409, "submit-review requires CLASSIFIED")
    if not eng.get("current_determination_id"):
        raise ApiError(ERR_DETERMINATION_REQUIRED, 409, "A current determination is required")
    q = store.questionnaires.get(eid)
    if q is None or not q["complete"]:
        raise ApiError(ERR_QUESTIONNAIRE_INCOMPLETE, 422, "Questionnaire incomplete")
    eng["status"] = "UNDER_REVIEW"
    touch(eng)
    return success(eng)


@bp.route("/api/engagements/<eid>/request-info", methods=["POST"])
def request_info(eid):
    require_auth(["ClassificationAnalyst"])
    eng = get_engagement_or_404(eid)
    if eng["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "request-info requires UNDER_REVIEW")
    eng["status"] = "INFO_REQUESTED"
    touch(eng)
    return success(eng)


@bp.route("/api/engagements/<eid>/submit-approval", methods=["POST"])
def submit_approval(eid):
    require_auth(["ClassificationAnalyst"])
    eng = get_engagement_or_404(eid)
    if eng["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "submit-approval requires UNDER_REVIEW")
    det_id = eng.get("current_determination_id")
    q = store.questionnaires.get(eid)
    if not det_id or not q or store.determinations[det_id]["questionnaire_revision"] != q["revision"]:
        raise ApiError(ERR_DETERMINATION_STALE, 409, "Determination is stale")
    eng["status"] = "APPROVAL_PENDING"
    eng["approvals_recorded"] = []
    touch(eng)
    return success(eng)


@bp.route("/api/engagements/<eid>/approve", methods=["POST"])
def approve(eid):
    user_id, role = require_auth(["HRApprover", "LegalApprover", "ComplianceBoardMember"])
    eng = get_engagement_or_404(eid)
    if eng["status"] != "APPROVAL_PENDING":
        raise ApiError(ERR_ENGAGEMENT_NOT_APPROVAL_PENDING, 409,
                       "Engagement is not APPROVAL_PENDING")
    required = eng["required_approval_count"] or 1
    sequence = APPROVAL_SEQUENCE[:required]
    idx = len(eng["approvals_recorded"])
    if idx >= len(sequence) or role != sequence[idx]:
        raise ApiError(ERR_APPROVAL_OUT_OF_ORDER, 409, "Acting role is not next in sequence")
    if any(a["user_id"] == user_id for a in eng["approvals_recorded"]):
        raise ApiError(ERR_APPROVER_ALREADY_ACTED, 409, "Approver already acted")
    # final-step exception gate for HIGH
    if idx == required - 1 and eng.get("risk_tier") == "HIGH":
        require_high_tier_exception(eng)
    eng["approvals_recorded"].append({
        "role": role,
        "user_id": user_id,
        "decided_at": now_iso(),
    })
    if len(eng["approvals_recorded"]) == required:
        eng["status"] = "APPROVED"
    touch(eng)
    return success(eng)


@bp.route("/api/engagements/<eid>/reject", methods=["POST"])
def reject(eid):
    require_auth(["ClassificationAnalyst", "HRApprover", "LegalApprover", "ComplianceBoardMember"])
    eng = get_engagement_or_404(eid)
    if eng["status"] not in ("UNDER_REVIEW", "APPROVAL_PENDING"):
        raise ApiError(ERR_INVALID_STATE, 409, "reject requires UNDER_REVIEW or APPROVAL_PENDING")
    eng["status"] = "REJECTED"
    touch(eng)
    return success(eng)


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------

@bp.route("/api/engagements/<eid>/activate", methods=["POST"])
def activate(eid):
    require_auth(["EngagementManager"])
    eng = get_engagement_or_404(eid)
    if eng["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "activate requires APPROVED")
    contract = None
    for c in store.contracts.values():
        if c["engagement_id"] == eid:
            lazy_expire_contract(c)
            if c["status"] == "EXECUTED":
                contract = c
                break
    if contract is None:
        raise ApiError(ERR_CONTRACT_NOT_EXECUTED, 409, "No EXECUTED contract for engagement")
    contractor = get_contractor_or_404(eng["contractor_id"])
    _standing_gate(contractor)
    eng["status"] = "ACTIVE"
    touch(eng)
    return success(eng)


@bp.route("/api/engagements/<eid>/suspend", methods=["POST"])
def suspend(eid):
    require_auth(["ComplianceOfficer"])
    eng = get_engagement_or_404(eid)
    if eng["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "suspend requires ACTIVE")
    eng["status"] = "SUSPENDED"
    touch(eng)

    # cascade link 1: EXECUTED contract -> SUSPENDED
    for c in store.contracts.values():
        if c["engagement_id"] == eid and c["status"] == "EXECUTED":
            c["status"] = "SUSPENDED"
            touch(c)
            # cascade link 2: amendments PROPOSED|APPROVED -> VOIDED
            revoked_grant_ids = []
            for am in store.amendments.values():
                if am["contract_id"] == c["id"] and am["status"] in ("PROPOSED", "APPROVED"):
                    am["status"] = "VOIDED"
                    touch(am)
                    if am.get("exception_grant_id"):
                        revoked_grant_ids.append(am["exception_grant_id"])
            # cascade link 3: linked ACTIVE grants -> REVOKED
            for gid in revoked_grant_ids:
                g = store.exceptions.get(gid)
                if g is not None:
                    lazy_expire_grant(g)
                    if g["status"] == "ACTIVE":
                        g["status"] = "REVOKED"
                        touch(g)
                        # cascade link 4
                        downgrade_standing_on_revoke(eng["contractor_id"])
    recompute_scope_creep(eng)
    return success(eng)


@bp.route("/api/engagements/<eid>/reinstate", methods=["POST"])
def reinstate(eid):
    require_auth(["ComplianceOfficer"])
    eng = get_engagement_or_404(eid)
    if eng["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "reinstate requires SUSPENDED")
    contractor = get_contractor_or_404(eng["contractor_id"])
    _standing_gate(contractor)
    eng["status"] = "ACTIVE"
    touch(eng)
    for c in store.contracts.values():
        if c["engagement_id"] == eid and c["status"] == "SUSPENDED":
            c["status"] = "EXECUTED"
            touch(c)
    recompute_scope_creep(eng)
    return success(eng)


@bp.route("/api/engagements/<eid>/terminate", methods=["POST"])
def terminate(eid):
    require_auth(["ComplianceOfficer"])
    eng = get_engagement_or_404(eid)
    if eng["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409, "terminate requires ACTIVE or SUSPENDED")
    eng["status"] = "TERMINATED"
    touch(eng)
    for c in store.contracts.values():
        if c["engagement_id"] == eid and c["status"] in ("EXECUTED", "SUSPENDED"):
            c["status"] = "TERMINATED"
            touch(c)
    return success(eng)
