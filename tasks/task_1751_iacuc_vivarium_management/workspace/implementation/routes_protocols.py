"""Protocol lifecycle routes: create, submit, review-decisions, suspend,
reinstate, personnel attachment, reviewer and reverse-reachability listings.
"""
from flask import Blueprint

from db import STORE, mint_protocol_number, new_rec, now
from domain import (
    budget_remaining,
    personnel_cleared,
    plus_years,
    ser_cage,
    ser_protocol,
    ser_protocol_reviewer,
    suspend_protocol_cascade,
    effective_occupancy,
)
from envelope import get_body, list_response, ok_obj
from errors import (
    ApiError,
    ERR_GRANT_EXHAUSTED,
    ERR_INVALID_VOTE_TALLY,
    ERR_NOT_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_TRAINING_INCOMPLETE,
    invalid_request,
    invalid_state,
    not_found,
)
from routes_admin import fetch
from validation import authenticate, require_role, req_enum, req_int, req_str

bp = Blueprint("protocols", __name__)

SPECIES = {"MOUSE", "RAT", "RABBIT", "ZEBRAFISH"}
PAIN_CATEGORIES = {"B", "C", "D", "E"}
REVIEW_PATHS = {"DMR", "FCR"}
DECISIONS = {"APPROVE", "REQUIRE_MODIFICATIONS", "WITHHOLD"}


@bp.post("/iacuc/protocols")
def create_protocol():
    uid, role = authenticate()
    require_role(role, "Investigator")
    body = get_body()
    investigator_id = req_str(body, "investigator_id")
    grant_id = req_str(body, "grant_id")
    title = req_str(body, "title")
    species = req_enum(body, "species", SPECIES)
    max_animals = req_int(body, "max_animals_justified", minimum=1)
    pain_category = req_enum(body, "pain_category", PAIN_CATEGORIES)
    review_path = req_enum(body, "review_path", REVIEW_PATHS)
    fetch("investigators", investigator_id)
    fetch("grants", grant_id)
    r = new_rec(
        "protocols",
        protocol_number=mint_protocol_number(),
        investigator_id=investigator_id,
        grant_id=grant_id,
        title=title,
        species=species,
        max_animals_justified=max_animals,
        pain_category=pain_category,
        review_path=review_path,
        status="DRAFT",
        approved_at=None,
        expires_at=None,
        personnel_ids=[],
    )
    return ok_obj(ser_protocol(r), 201)


@bp.get("/iacuc/protocols/<rid>")
def get_protocol(rid):
    uid, role = authenticate()
    require_role(
        role, "IacucAdministrator", "Investigator", "AttendingVeterinarian",
        "AnimalCareStaff", "BillingCoordinator",
    )
    return ok_obj(ser_protocol(fetch("protocols", rid)))


@bp.get("/iacuc/investigators/<rid>/protocols")
def list_investigator_protocols(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator", "Investigator")
    fetch("investigators", rid)
    rows = [p for p in STORE["protocols"].values() if p.investigator_id == rid]
    return list_response(rows, ser_protocol)


@bp.get("/iacuc/grants/<rid>/protocols")
def list_grant_protocols(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator", "BillingCoordinator")
    fetch("grants", rid)
    rows = [p for p in STORE["protocols"].values() if p.grant_id == rid]
    return list_response(rows, ser_protocol)


@bp.get("/iacuc/protocols/<rid>/cages")
def list_protocol_cages(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "IacucAdministrator", "BillingCoordinator")
    fetch("protocols", rid)
    rows = [c for c in STORE["cages"].values() if c.protocol_id == rid]
    return list_response(rows, ser_cage)


def _create_reviewers(protocol):
    """Auto-route on submit: mint reviewer assignments if none exist yet."""
    existing = [
        r for r in STORE["protocol_reviewers"].values()
        if r.protocol_id == protocol.id
    ]
    if existing:
        return
    if protocol.review_path == "DMR":
        new_rec(
            "protocol_reviewers",
            protocol_id=protocol.id,
            reviewer_name="Designated Member",
            reviewer_kind="DESIGNATED_MEMBER",
            decision="PENDING",
        )
    else:
        for i in range(1, 4):
            new_rec(
                "protocol_reviewers",
                protocol_id=protocol.id,
                reviewer_name=f"Committee Member {i}",
                reviewer_kind="COMMITTEE_MEMBER",
                decision="PENDING",
            )


@bp.post("/iacuc/protocols/<rid>/submit")
def submit_protocol(rid):
    uid, role = authenticate()
    require_role(role, "Investigator")
    p = fetch("protocols", rid)
    if p.investigator_id != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "Only the owning investigator may submit")
    if p.status != "DRAFT":
        raise invalid_state("Protocol is not DRAFT")
    grant = fetch("grants", p.grant_id)
    if budget_remaining(grant) <= 0 or grant.expires_on <= now():
        raise ApiError(
            ERR_GRANT_EXHAUSTED, 402,
            "Grant has no remaining budget or has expired",
        )
    p.status = "DMR_REVIEW" if p.review_path == "DMR" else "FCR_REVIEW"
    p.touch()
    _create_reviewers(p)
    return ok_obj(ser_protocol(p))


@bp.post("/iacuc/protocols/<rid>/review-decisions")
def review_decisions(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator")
    body = get_body()
    raw = body.get("decisions")
    if not isinstance(raw, list):
        raise invalid_request("'decisions' must be a list")
    parsed = []
    for item in raw:
        if not isinstance(item, dict):
            raise invalid_request("Each decision must be an object")
        reviewer_id = item.get("reviewer_id", item.get("id"))
        if not isinstance(reviewer_id, str):
            raise invalid_request("Each decision requires a 'reviewer_id'")
        decision = item.get("decision")
        if not isinstance(decision, str) or decision not in DECISIONS:
            raise invalid_request(
                "Each decision requires a 'decision' in APPROVE | "
                "REQUIRE_MODIFICATIONS | WITHHOLD"
            )
        parsed.append((reviewer_id, decision))

    p = fetch("protocols", rid)
    reviewers = [
        r for r in STORE["protocol_reviewers"].values() if r.protocol_id == p.id
    ]
    by_id = {r.id: r for r in reviewers}
    for reviewer_id, _ in parsed:
        if reviewer_id not in STORE["protocol_reviewers"]:
            raise not_found(f"ProtocolReviewer {reviewer_id} not found")

    if p.status not in ("DMR_REVIEW", "FCR_REVIEW"):
        raise invalid_state("Protocol is not under review")

    # Segregation of duties: the owning investigator may not record decisions.
    if uid == p.investigator_id:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES, 403,
            "An investigator may not record review decisions on their own protocol",
        )

    # Vote-tally validity for the protocol's review path.
    if p.review_path == "DMR":
        expected = {r.id for r in reviewers if r.reviewer_kind == "DESIGNATED_MEMBER"}
        given = [rid_ for rid_, _ in parsed]
        if len(given) != 1 or set(given) != expected:
            raise ApiError(
                ERR_INVALID_VOTE_TALLY, 422,
                "DMR tally requires exactly one DESIGNATED_MEMBER decision",
            )
    else:
        expected = {r.id for r in reviewers if r.reviewer_kind == "COMMITTEE_MEMBER"}
        given = [rid_ for rid_, _ in parsed]
        if len(given) != len(expected) or set(given) != expected:
            raise ApiError(
                ERR_INVALID_VOTE_TALLY, 422,
                "FCR tally requires decisions for all COMMITTEE_MEMBER reviewers",
            )

    for reviewer_id, decision in parsed:
        reviewer = by_id[reviewer_id]
        reviewer.decision = decision
        reviewer.touch()

    votes = [d for _, d in parsed]
    if p.review_path == "DMR":
        vote = votes[0]
        if vote == "APPROVE":
            outcome = "APPROVED"
        elif vote == "REQUIRE_MODIFICATIONS":
            outcome = "DRAFT"
        else:
            outcome = "WITHDRAWN"
    else:
        if "WITHHOLD" in votes:
            outcome = "WITHDRAWN"
        elif sum(1 for v in votes if v == "APPROVE") >= 2:
            outcome = "APPROVED"
        else:
            outcome = "DRAFT"

    if outcome == "APPROVED":
        p.approved_at = now()
        p.expires_at = plus_years(p.approved_at, 3)
        p.status = "APPROVED"
    elif outcome == "DRAFT":
        p.status = "DRAFT"
        for r in reviewers:
            if r.decision != "PENDING":
                r.decision = "PENDING"
                r.touch()
    else:
        p.status = "WITHDRAWN"
    p.touch()
    return ok_obj(ser_protocol(p))


@bp.get("/iacuc/protocols/<rid>/reviewers")
def list_reviewers(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator")
    fetch("protocols", rid)
    rows = [r for r in STORE["protocol_reviewers"].values() if r.protocol_id == rid]
    return list_response(rows, ser_protocol_reviewer)


@bp.post("/iacuc/protocols/<rid>/suspend")
def suspend_protocol(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator")
    body = get_body()
    expected = req_int(body, "expected_protocol_version")
    p = fetch("protocols", rid)
    if p.status != "APPROVED":
        raise invalid_state("Protocol is not APPROVED")
    has_imposed = any(
        d.protocol_id == p.id and d.state == "SUSPENSION_IMPOSED"
        for d in STORE["deviations"].values()
    )
    if not has_imposed:
        raise invalid_state(
            "No ProtocolDeviation in SUSPENSION_IMPOSED state on this protocol"
        )
    if expected != p.version:
        raise ApiError(
            ERR_STALE_VERSION, 412,
            "expected_protocol_version does not match the current version",
        )
    suspend_protocol_cascade(p)
    return ok_obj(ser_protocol(p))


@bp.post("/iacuc/protocols/<rid>/reinstate")
def reinstate_protocol(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator")
    p = fetch("protocols", rid)
    if p.status != "SUSPENDED":
        raise invalid_state("Protocol is not SUSPENDED")
    unresolved = any(
        d.protocol_id == p.id and d.state not in ("CLOSED", "SUSPENSION_IMPOSED")
        for d in STORE["deviations"].values()
    )
    if unresolved:
        raise invalid_state(
            "All deviations on the protocol must be CLOSED or SUSPENSION_IMPOSED"
        )
    p.status = "APPROVED"
    p.touch()
    for cage in STORE["cages"].values():
        if cage.protocol_id == p.id and cage.status == "OVER_CAPACITY":
            eff = effective_occupancy(cage.id)
            if eff <= cage.capacity_adults:
                if eff == 0:
                    cage.status = "EMPTY"
                    cage.occupied_since = None
                else:
                    cage.status = "OCCUPIED"
                cage.touch()
    return ok_obj(ser_protocol(p))


@bp.post("/iacuc/protocols/<rid>/personnel")
def attach_personnel(rid):
    uid, role = authenticate()
    require_role(role, "Investigator")
    body = get_body()
    personnel_id = req_str(body, "personnel_id")
    p = fetch("protocols", rid)
    fetch("personnel", personnel_id)
    if not personnel_cleared(personnel_id):
        raise ApiError(
            ERR_TRAINING_INCOMPLETE, 422,
            "Personnel lacks completed training or occ-health clearance",
        )
    if personnel_id not in p.personnel_ids:
        p.personnel_ids.append(personnel_id)
    p.touch()
    return ok_obj({"protocol_id": p.id, "personnel_id": personnel_id}, 201)
