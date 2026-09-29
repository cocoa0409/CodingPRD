"""Project requests, scope revisions, deliverables and matching (PRD 3.3, 3.4)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request as flask_request

import calc
import config as C
import domain
import guards as G
import response as R
import serialize as Z
import store as S
from calc import dec, rnd
from errors import ApiError
from guards import route

bp = Blueprint("requests", __name__)

READ_ROLES = [
    C.ROLE_PROGRAM_MANAGER,
    C.ROLE_SCOPING_SPECIALIST,
    C.ROLE_PARTNER_CONTACT,
]
SCOPE_READ_ROLES = [
    C.ROLE_PROGRAM_MANAGER,
    C.ROLE_SCOPING_SPECIALIST,
    C.ROLE_VOLUNTEER,
    C.ROLE_PARTNER_CONTACT,
    C.ROLE_QUALITY_REVIEWER,
]


# --------------------------------------------------------------------------- #
# project requests
# --------------------------------------------------------------------------- #
@route(bp, "/project-requests", ["POST"], [C.ROLE_PARTNER_CONTACT])
def create_project_request():
    payload = G.body()
    # priority 14: body foreign keys resolve before the schema is judged
    raw_partner = payload.get("partner_org_id")
    partner = None
    if isinstance(raw_partner, str) and raw_partner.strip():
        partner = G.g14_body_partner(raw_partner)
    raw_cycle = payload.get("cycle_id")
    cycle = None
    if isinstance(raw_cycle, str) and raw_cycle.strip():
        cycle = G.g14_body_cycle(raw_cycle)

    partner_org_id = G.v_id(payload, "partner_org_id")
    cycle_id = G.v_id(payload, "cycle_id")
    title = G.v_str(payload, "title", min_len=1, max_len=160)
    discipline = G.v_enum(payload, "discipline", C.DISCIPLINES)
    required_skill_code = G.v_str(payload, "required_skill_code", min_len=2, max_len=32)
    min_proficiency = G.v_int(payload, "min_proficiency", minimum=1, maximum=5)
    requested_hours = G.v_num(payload, "requested_hours", exclusive_min=0, places=2)
    urgency = G.v_enum(payload, "urgency", C.URGENCIES, required=False, default="ROUTINE")

    G.g31_partner_not_suspended(partner)

    row = S.insert(
        "project_requests",
        {
            "partner_org_id": partner_org_id,
            "cycle_id": cycle_id,
            "title": title,
            "discipline": discipline,
            "required_skill_code": required_skill_code,
            "min_proficiency": min_proficiency,
            "requested_hours": requested_hours,
            "urgency": urgency,
            "status": "DRAFT",
            "rescope_count": 0,
            "failed_match_rounds": 0,
            "closed_at": None,
        },
    )
    return R.created(Z.project_request(row))


@route(bp, "/project-requests/<request_id>", ["GET"], READ_ROLES)
def get_project_request(request_id):
    req = G.g05_request(request_id)
    return R.ok(Z.project_request(req))


@route(bp, "/project-requests", ["GET"], READ_ROLES)
def list_project_requests():
    rows = S.all_rows("project_requests")
    partner_org_id = flask_request.args.get("partner_org_id")
    cycle_id = flask_request.args.get("cycle_id")
    status = flask_request.args.get("status")
    if partner_org_id:
        rows = [r for r in rows if r["partner_org_id"] == partner_org_id]
    if cycle_id:
        rows = [r for r in rows if r["cycle_id"] == cycle_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return R.paginate(rows, Z.project_request)


@route(
    bp,
    "/project-requests/<request_id>/submit-for-scoping",
    ["POST"],
    [C.ROLE_PARTNER_CONTACT],
)
def submit_for_scoping(request_id):
    req = G.g05_request(request_id)
    G.g15_owns_partner(req["partner_org_id"])
    G.g20_request_state(req, ("DRAFT",))
    partner = S.get("partner_orgs", req["partner_org_id"])
    G.g31_partner_active(partner)
    cycle = S.get("program_cycles", req["cycle_id"])
    if cycle is not None and S.now() >= cycle["ends_at"]:
        raise ApiError("ERR_INVALID_REQUEST_STATE", "cycle has already ended")
    req["status"] = "SCOPING"
    S.touch(req)
    return R.ok(Z.project_request(req))


# --------------------------------------------------------------------------- #
# scope revisions
# --------------------------------------------------------------------------- #
@route(
    bp,
    "/project-requests/<request_id>/scope-definitions",
    ["POST"],
    [C.ROLE_SCOPING_SPECIALIST],
)
def create_scope_definition(request_id):
    req = G.g05_request(request_id)
    payload = G.body()

    raw_supersedes = payload.get("supersedes_scope_id")
    if isinstance(raw_supersedes, str) and raw_supersedes.strip():
        G.g14_body_scope(raw_supersedes)

    expected_version = G.v_int(payload, "expected_project_request_version", minimum=0)
    estimated_hours = G.v_num(
        payload, "estimated_hours", minimum=0, maximum=400, places=2
    )
    complexity_factor = G.v_num(
        payload, "complexity_factor", minimum="1.00", maximum="2.50", places=2
    )
    confidentiality_tier = G.v_enum(
        payload, "confidentiality_tier", C.CONFIDENTIALITY_TIERS
    )
    ip_disposition = G.v_enum(payload, "ip_disposition", C.IP_DISPOSITIONS)
    supersedes_scope_id = G.v_id(payload, "supersedes_scope_id", required=False)

    G.g19_positive(estimated_hours, "estimated_hours")
    G.g20_request_state(req, ("SCOPING",))
    G.g29_request_version(req, expected_version)

    revision_no = 1
    for sibling in S.where("scope_definitions", project_request_id=req["id"]):
        revision_no = max(revision_no, int(sibling["revision_no"]) + 1)

    row = S.insert(
        "scope_definitions",
        {
            "project_request_id": req["id"],
            "supersedes_scope_id": supersedes_scope_id,
            "revision_no": revision_no,
            "authored_by_user_id": G.user_id(),
            "estimated_hours": estimated_hours,
            "complexity_factor": complexity_factor,
            "confidentiality_tier": confidentiality_tier,
            "ip_disposition": ip_disposition,
            "status": "DRAFT",
            "approved_at": None,
            "approved_by_user_id": None,
        },
    )
    domain.withdraw_draft_revisions(req, keep_id=row["id"])
    # a forced re-scope eventually produces a revision: the voided escalated
    # change request records its revision_no (PRD 3.7)
    domain.stamp_forced_rescope_result(req, revision_no)
    S.touch(req)
    return R.created(Z.scope_definition(row))


@route(bp, "/scope-definitions/<scope_id>", ["GET"], SCOPE_READ_ROLES)
def get_scope_definition(scope_id):
    scope = G.g06_scope(scope_id)
    return R.ok(Z.scope_definition(scope))


@route(bp, "/scope-definitions", ["GET"], SCOPE_READ_ROLES)
def list_scope_definitions():
    rows = S.all_rows("scope_definitions")
    project_request_id = flask_request.args.get("project_request_id")
    supersedes_scope_id = flask_request.args.get("supersedes_scope_id")
    status = flask_request.args.get("status")
    if project_request_id:
        rows = [r for r in rows if r["project_request_id"] == project_request_id]
    if supersedes_scope_id:
        rows = [r for r in rows if r["supersedes_scope_id"] == supersedes_scope_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return R.paginate(rows, Z.scope_definition)


@route(
    bp,
    "/scope-definitions/<scope_id>/deliverables",
    ["POST"],
    [C.ROLE_SCOPING_SPECIALIST],
)
def create_deliverable(scope_id):
    scope = G.g06_scope(scope_id)
    payload = G.body()
    title = G.v_str(payload, "title", min_len=1, max_len=120)
    sequence_no = G.v_int(payload, "sequence_no", minimum=1)
    weight_pct = G.v_num(payload, "weight_pct", minimum=0, maximum=100, places=2)
    hours_estimate = G.v_num(payload, "hours_estimate", minimum=0, places=2)
    acceptance_criteria = G.v_str(
        payload, "acceptance_criteria", min_len=1, max_len=500
    )

    G.g19_positive(weight_pct, "weight_pct")
    G.g19_positive(hours_estimate, "hours_estimate")
    G.g21_scope_draft(scope)
    G.g47_unique_sequence(scope["id"], sequence_no)
    G.g47_weight_ceiling(scope["id"], weight_pct)

    row = S.insert(
        "deliverables",
        {
            "scope_definition_id": scope["id"],
            "title": title,
            "sequence_no": sequence_no,
            "weight_pct": weight_pct,
            "hours_estimate": hours_estimate,
            "acceptance_criteria": acceptance_criteria,
            "review_status": "PENDING",
            "review_score": None,
            "waived_reason": None,
        },
        versioned=False,
    )
    S.touch(scope)
    return R.created(Z.deliverable(row))


@route(bp, "/scope-definitions/<scope_id>/deliverables", ["GET"], SCOPE_READ_ROLES)
def list_deliverables(scope_id):
    scope = G.g06_scope(scope_id)
    rows = S.where("deliverables", scope_definition_id=scope["id"])
    rows.sort(key=lambda d: (int(d["sequence_no"]), d["created_at"], d["_seq"]))
    return R.paginate(rows, Z.deliverable)


@route(
    bp, "/scope-definitions/<scope_id>/approve", ["POST"], [C.ROLE_PARTNER_CONTACT]
)
def approve_scope_definition(scope_id):
    scope = G.g06_scope(scope_id)
    req = S.get("project_requests", scope["project_request_id"])
    G.g15_owns_partner(req["partner_org_id"])
    G.g20_request_state(req, ("SCOPING",))
    G.g21_scope_draft(scope)
    partner = S.get("partner_orgs", req["partner_org_id"])
    G.g31_partner_not_suspended(partner)
    G.g47_weight_exact(scope["id"])

    domain.supersede_approved_revision(req)
    scope["status"] = "APPROVED"
    scope["approved_at"] = S.now()
    scope["approved_by_user_id"] = G.user_id()
    S.touch(scope)
    req["status"] = "SCOPED"
    S.touch(req)
    return R.ok(Z.scope_definition(scope))


# --------------------------------------------------------------------------- #
# matching
# --------------------------------------------------------------------------- #
@route(
    bp, "/project-requests/<request_id>/match", ["POST"], [C.ROLE_SCOPING_SPECIALIST]
)
def match_project_request(request_id):
    req = G.g05_request(request_id)
    G.g20_request_state(req, ("SCOPED",))
    partner = S.get("partner_orgs", req["partner_org_id"])
    G.g31_partner_active(partner)

    scope = None
    for candidate in S.where("scope_definitions", project_request_id=req["id"]):
        if candidate["status"] == "APPROVED":
            scope = candidate
    G.g49_scope_approved(scope)

    cycle = S.get("program_cycles", req["cycle_id"])
    G.g51_cycle_not_frozen(cycle)
    G.g52_restricted_urgency(cycle, req)
    G.g53_partner_engagement_limit(partner)

    candidates = calc.match_candidates(req, scope)
    if not candidates:
        # the round is charged even though no offer exists
        req["failed_match_rounds"] = int(req["failed_match_rounds"]) + 1
        S.touch(req)
        raise ApiError("ERR_NO_ELIGIBLE_VOLUNTEER")

    winner = candidates[0]
    reserved_hours = calc.required_hours(scope)
    G.g55_window_hours(winner["window"], reserved_hours)

    offered_at = S.now()
    ttl = C.OFFER_TTL_HOURS[req["urgency"]]
    offer = S.insert(
        "match_offers",
        {
            "project_request_id": req["id"],
            "volunteer_id": winner["volunteer"]["id"],
            "scope_definition_id": scope["id"],
            "availability_window_id": winner["window"]["id"],
            "round_no": int(req["failed_match_rounds"]) + 1,
            "match_score": winner["score"],
            "reserved_hours": reserved_hours,
            "offered_at": offered_at,
            "expires_at": offered_at + timedelta(hours=ttl),
            "status": "OFFERED",
            "decline_reason": None,
            "withdraw_reason": None,
            "responded_at": None,
        },
    )
    req["status"] = "MATCHING"
    S.touch(req)
    return R.created(Z.match_offer(offer))


@route(
    bp, "/project-requests/<request_id>/rescope", ["POST"], [C.ROLE_SCOPING_SPECIALIST]
)
def rescope_project_request(request_id):
    req = G.g05_request(request_id)
    G.g20_request_state(req, ("RESCOPING",))
    G.g50_rescope_limit(req)
    req["status"] = "SCOPING"
    S.touch(req)
    domain.waive_milestones_of_request(req, "RESCOPED")
    return R.ok(Z.project_request(req))


@route(
    bp, "/project-requests/<request_id>/abandon", ["POST"], [C.ROLE_PROGRAM_MANAGER]
)
def abandon_project_request(request_id):
    req = G.g05_request(request_id)
    payload = G.body()
    G.v_str(payload, "reason", required=False, min_len=0, max_len=500)
    previous = req["status"]
    G.g20_request_state(
        req, ("DRAFT", "SCOPING", "SCOPED", "MATCHING", "RESCOPING")
    )
    req["status"] = "ABANDONED"
    req["closed_at"] = S.now()
    S.touch(req)
    if previous in ("DRAFT", "MATCHING"):
        domain.withdraw_open_offers_of_request(req, "ADMIN", bump_failed=False)
    if previous == "MATCHING":
        # PRD 3.3: "A revision moves `APPROVED -> SUPERSEDED` ... when the request is
        # abandoned out of `MATCHING`."  active_scope_revision_no is derived from the
        # APPROVED revision, so it falls back to 0 on its own.
        domain.supersede_approved_revision(req)
    if previous in ("SCOPING", "SCOPED"):
        for scope in S.where("scope_definitions", project_request_id=req["id"]):
            if scope["status"] in ("DRAFT", "APPROVED"):
                scope["status"] = "WITHDRAWN"
                S.touch(scope)
    return R.ok(Z.project_request(req))
