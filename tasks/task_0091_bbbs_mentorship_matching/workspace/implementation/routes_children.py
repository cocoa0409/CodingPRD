"""Guardian, Child, and MatchProposal endpoints (PRD §3.3, §3.4)."""
from flask import Blueprint, request

import calc
import clock
import db
import domain
import serialize
from errors import err
from middleware import require
from response import array_response, object_response
from store import create, get_or_404, paginate, sort_key, touch
import validate as V

bp = Blueprint("children", __name__)

GENDERS = {"MALE", "FEMALE", "NONBINARY"}
DECLINE_REASONS = {"VOLUNTEER_UNAVAILABLE", "GUARDIAN_DECLINED", "POOR_FIT"}


# --- Guardian ---
@bp.route("/guardians", methods=["POST"])
@require("Coordinator", "MatchSpecialist")
def create_guardian():
    body = V.get_body()
    full_name = V.require_str(body, "full_name")
    email = V.require_str(body, "email")
    consent = V.optional_bool(body, "consent_on_file", default=False)
    rec = create(
        {"full_name": full_name, "email": email, "consent_on_file": consent},
        db.guardians,
        "Guardian",
    )
    return object_response(serialize.guardian(rec), 201)


@bp.route("/guardians/<gid>", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def get_guardian(gid):
    rec = get_or_404(db.guardians, gid, "Guardian")
    return object_response(serialize.guardian(rec))


@bp.route("/guardians/<gid>", methods=["PATCH"])
@require("Coordinator", "MatchSpecialist")
def update_guardian(gid):
    rec = get_or_404(db.guardians, gid, "Guardian")
    body = V.get_body()
    # expected_guardian_version is part of the mutation contract (PRD §2.5). It
    # must be present and well-typed; a mismatch is ERR_STALE_VERSION.
    expected = body.get("expected_guardian_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        err("ERR_INVALID_REQUEST", "expected_guardian_version must be an integer")
    if expected != rec["version"]:
        err("ERR_STALE_VERSION", "Guardian version mismatch")
    if "consent_on_file" in body and body.get("consent_on_file") is not None:
        rec["consent_on_file"] = V.require_bool(body, "consent_on_file")
    touch(rec)
    return object_response(serialize.guardian(rec))


@bp.route("/guardians/<gid>/children", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def list_guardian_children(gid):
    get_or_404(db.guardians, gid, "Guardian")
    items = [c for c in db.children.values() if c["guardian_id"] == gid]
    ordered = sorted(items, key=sort_key)
    return array_response([serialize.child(r) for r in ordered], 10, 0, len(ordered))


# --- Child ---
@bp.route("/children", methods=["POST"])
@require("Coordinator", "MatchSpecialist")
def create_child():
    body = V.get_body()
    guardian_id = V.require_str(body, "guardian_id")
    first_name = V.require_str(body, "first_name")
    age = V.require_int(body, "age", minimum=6, maximum=16)
    gender = V.require_enum(body, "gender", GENDERS)
    home_zip = V.require_zip(body, "home_zip")
    interest_tags = V.require_string_array(body, "interest_tags")
    requires_same_gender = V.optional_bool(body, "requires_same_gender", default=False)
    # Body FK existence (priority 3, after field validation cannot fail before
    # existence per §2.6; existence is checked here for the body FK).
    if guardian_id not in db.guardians:
        err("ERR_NOT_FOUND", "Guardian %s not found" % guardian_id)
    rec = create(
        {
            "guardian_id": guardian_id,
            "first_name": first_name,
            "age": age,
            "gender": gender,
            "home_zip": home_zip,
            "interest_tags": interest_tags,
            "requires_same_gender": requires_same_gender,
            "status": "WAITLISTED",
            "open_proposal_id": None,
        },
        db.children,
        "Child",
    )
    return object_response(serialize.child(rec), 201)


@bp.route("/children/<cid>", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def get_child(cid):
    rec = get_or_404(db.children, cid, "Child")
    return object_response(serialize.child(rec))


@bp.route("/children", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def list_children():
    limit, offset = V.parse_pagination(request.args)
    status = request.args.get("status")
    guardian_id = request.args.get("guardian_id")
    items = list(db.children.values())
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if guardian_id is not None:
        items = [r for r in items if r["guardian_id"] == guardian_id]
    window, total = paginate(items, limit, offset)
    return array_response([serialize.child(r) for r in window], limit, offset, total)


def _eligible_pool(child):
    """Candidate pool: ELIGIBLE volunteers with active_match_count==0, a non-null
    cleared_check_id, and a satisfied gender preference (PRD §3.3)."""
    pool = []
    for v in db.volunteers.values():
        if v["status"] != "ELIGIBLE":
            continue
        domain.recompute_volunteer_active_match_count(v)
        if v["active_match_count"] != 0:
            continue
        # cleared_check_id reflects joint validity of the three checks at "now".
        domain.recompute_volunteer_cleared(v)
        if v["cleared_check_id"] is None:
            continue
        if child["requires_same_gender"] and v["gender"] != child["gender"]:
            continue
        pool.append(v)
    return pool


@bp.route("/children/<cid>/propose-match", methods=["POST"])
@require("MatchSpecialist")
def propose_match(cid):
    rec = get_or_404(db.children, cid, "Child")
    body = V.get_body()
    expected = body.get("expected_child_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        err("ERR_INVALID_REQUEST", "expected_child_version must be an integer")
    # OCC (priority 5) before state precondition (priority 6).
    if expected != rec["version"]:
        err("ERR_STALE_VERSION", "Child version mismatch")
    # State precondition (PRD §3.3): proposing is permitted while the child is
    # WAITLISTED. The same call also handles re-proposal: if the child already
    # holds an OFFERED proposal (status PROPOSED), that prior offer is superseded
    # and the child momentarily reverts toward the waitlist before being
    # re-attached to the fresh proposal. A child that is MATCHED or INACTIVE
    # cannot be proposed.
    has_open_offer = domain.child_open_proposal(rec) is not None
    if not (rec["status"] == "WAITLISTED" or (rec["status"] == "PROPOSED" and has_open_offer)):
        err("ERR_INVALID_STATE", "Child must be WAITLISTED (or have an open offer to supersede) to propose a match")
    # Business: guardian consent on file.
    guardian = db.guardians.get(rec["guardian_id"])
    if guardian is None or not guardian["consent_on_file"]:
        err("ERR_CONSENT_NOT_ON_FILE", "Guardian consent is not on file")
    # Business: candidate pool non-empty.
    pool = _eligible_pool(rec)
    if not pool:
        err("ERR_NO_ELIGIBLE_VOLUNTEER", "No eligible volunteer for this child")

    # Score and select: highest rounded score, ties broken by earliest created_at.
    scored = []
    for v in pool:
        scored.append((calc.compatibility_score(v, rec), v))
    best_score = max(s for s, _ in scored)
    candidates = [v for s, v in scored if s == best_score]
    # Tie-break: earliest created_at; never by id (PRD §3.3). _seq breaks exact
    # created_at ties by true insertion order (the test clock can freeze
    # created_at across many records), keeping selection deterministic without
    # ever consulting the random id.
    selected = min(candidates, key=lambda v: (v["created_at"], v["_seq"]))

    # Supersede any prior OFFERED proposal for this child.
    prior = domain.child_open_proposal(rec)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    proposal = create(
        {
            "child_id": rec["id"],
            "volunteer_id": selected["id"],
            "compatibility_score": best_score,
            "candidate_pool_size": len(pool),
            "status": "OFFERED",
            "decline_reason": None,
        },
        db.match_proposals,
        "MatchProposal",
    )
    # Child WAITLISTED -> PROPOSED; open_proposal_id set; version increments.
    rec["status"] = "PROPOSED"
    rec["open_proposal_id"] = proposal["id"]
    touch(rec)
    return object_response(serialize.match_proposal(proposal), 201)


@bp.route("/children/<cid>/proposals", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def list_child_proposals(cid):
    get_or_404(db.children, cid, "Child")
    items = [p for p in db.match_proposals.values() if p["child_id"] == cid]
    ordered = sorted(items, key=sort_key)
    return array_response([serialize.match_proposal(r) for r in ordered], 10, 0, len(ordered))


@bp.route("/children/<cid>/match", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def list_child_match(cid):
    get_or_404(db.children, cid, "Child")
    items = domain.matches_for_child(cid)
    ordered = sorted(items, key=sort_key)
    return array_response([serialize.match(r) for r in ordered], 10, 0, len(ordered))


# --- MatchProposal ---
@bp.route("/match-proposals/<pid>", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def get_proposal(pid):
    rec = get_or_404(db.match_proposals, pid, "MatchProposal")
    return object_response(serialize.match_proposal(rec))


@bp.route("/match-proposals", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def list_proposals():
    limit, offset = V.parse_pagination(request.args)
    child_id = request.args.get("child_id")
    volunteer_id = request.args.get("volunteer_id")
    status = request.args.get("status")
    items = list(db.match_proposals.values())
    if child_id is not None:
        items = [r for r in items if r["child_id"] == child_id]
    if volunteer_id is not None:
        items = [r for r in items if r["volunteer_id"] == volunteer_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    window, total = paginate(items, limit, offset)
    return array_response([serialize.match_proposal(r) for r in window], limit, offset, total)


@bp.route("/match-proposals/<pid>/accept", methods=["POST"])
@require("MatchSpecialist")
def accept_proposal(pid):
    from flask import request as flask_request

    rec = get_or_404(db.match_proposals, pid, "MatchProposal")
    body = V.get_body()
    expected = body.get("expected_volunteer_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        err("ERR_INVALID_REQUEST", "expected_volunteer_version must be an integer")
    volunteer = db.volunteers.get(rec["volunteer_id"])
    # OCC (priority 5) before state precondition (priority 6).
    if volunteer is None or expected != volunteer["version"]:
        err("ERR_STALE_VERSION", "Volunteer version mismatch")
    # State precondition: proposal must be OFFERED.
    if rec["status"] != "OFFERED":
        err("ERR_INVALID_STATE", "Only an OFFERED proposal may be accepted")
    # Business: volunteer must be ELIGIBLE.
    if volunteer["status"] != "ELIGIBLE":
        err("ERR_VOLUNTEER_NOT_ELIGIBLE", "Selected volunteer is not ELIGIBLE")
    # Business: one-on-one exclusivity (active_match_count == 0).
    domain.recompute_volunteer_active_match_count(volunteer)
    if volunteer["active_match_count"] != 0:
        err("ERR_VOLUNTEER_AT_CAPACITY", "Selected volunteer already has an active match")

    now = clock.now()
    confirming_user = flask_request.headers.get("X-User-ID")
    rec["status"] = "ACCEPTED"
    touch(rec)

    match_rec = create(
        {
            "child_id": rec["child_id"],
            "volunteer_id": volunteer["id"],
            "proposal_id": rec["id"],
            "relationship_status": "CONFIRMED",
            "confirmed_at": now,
            "activated_at": None,
            "last_activity_at": None,
            "last_contact_at": None,
            "total_mentoring_minutes": 0,
            "closure_reason": None,
            "_confirmed_by": confirming_user,  # operator identity for SoD (PRD §2.1)
        },
        db.matches,
        "Match",
    )

    # Bubble child PROPOSED -> MATCHED (clears open_proposal_id).
    child = db.children.get(rec["child_id"])
    if child is not None and child["status"] == "PROPOSED":
        child["status"] = "MATCHED"
        child["open_proposal_id"] = None
        touch(child)

    # Bubble volunteer ELIGIBLE -> MATCHED, active_match_count -> 1, version++.
    volunteer["status"] = "MATCHED"
    domain.recompute_volunteer_active_match_count(volunteer)
    touch(volunteer)

    return object_response(serialize.match(match_rec), 201)


@bp.route("/match-proposals/<pid>/decline", methods=["POST"])
@require("MatchSpecialist")
def decline_proposal(pid):
    rec = get_or_404(db.match_proposals, pid, "MatchProposal")
    body = V.get_body()
    decline_reason = V.require_enum(body, "decline_reason", DECLINE_REASONS)
    if rec["status"] != "OFFERED":
        err("ERR_INVALID_STATE", "Only an OFFERED proposal may be declined")
    rec["status"] = "DECLINED"
    rec["decline_reason"] = decline_reason
    touch(rec)
    child = db.children.get(rec["child_id"])
    if child is not None:
        domain.revert_child_after_offer_gone(child)
    return object_response(serialize.match_proposal(rec))


@bp.route("/match-proposals/<pid>/match", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def list_proposal_match(pid):
    get_or_404(db.match_proposals, pid, "MatchProposal")
    items = [m for m in db.matches.values() if m["proposal_id"] == pid]
    ordered = sorted(items, key=sort_key)
    return array_response([serialize.match(r) for r in ordered], 10, 0, len(ordered))
