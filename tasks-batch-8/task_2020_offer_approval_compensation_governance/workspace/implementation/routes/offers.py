"""Offer endpoints: construction, revision, submission, letters, extension,
candidate answer, rescission, withdrawal."""

from flask import Blueprint, request

import db
from errors import (
    raise_err, ERR_OFFER_NOT_FOUND, ERR_REQUISITION_NOT_FOUND,
    ERR_CANDIDATE_NOT_FOUND, ERR_NOT_RESOURCE_OWNER, ERR_REQUISITION_NOT_OPEN,
    ERR_CANDIDATE_NOT_HIRABLE, ERR_INVALID_OFFER_STATE, ERR_STALE_OFFER_VERSION,
    ERR_INSUFFICIENT_PEER_DATA, ERR_REQUISITION_BUDGET_EXCEEDED,
    ERR_BASE_EXCEEDS_HARD_CAP, ERR_OFFER_EXPIRED,
    ERR_DECLINATION_REASON_REQUIRED, ERR_CANDIDATE_ACTIVE_OFFER_EXISTS,
    ERR_INVALID_REQUEST,
)
from middleware import (
    get_actor, require_role, get_json_body, validate_fields, req_string,
    req_enum, req_int, req_number, get_pagination, paginate,
)
from response import success
from services import calc
from services import offer_ops

bp = Blueprint("offers", __name__)

READ_ROLES = ["Recruiter", "HiringManager", "CompAnalyst", "DepartmentDirector",
              "VPPeople", "HRAdmin", "Candidate"]
DECLINATION_REASONS = ["COMPETING_OFFER", "COMPENSATION", "ROLE_SCOPE", "LOCATION",
                       "BENEFITS", "PERSONAL", "TIMING", "OTHER"]
RESCIND_REASONS = ["RENEG", "COMPLIANCE_HOLD"]


def get_offer(offer_id):
    offer = db.offers.get(offer_id)
    if offer is None:
        raise_err(ERR_OFFER_NOT_FOUND, "Offer not found")
    return offer


def candidate_owns(offer, uid, role):
    if role == "Candidate" and offer["candidate_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Candidates may only access their own offers")


@bp.route("/api/offers", methods=["POST"])
def create():
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body,
                    ["requisition_id", "candidate_id", "base_cents",
                     "bonus_target_pct", "equity_shares", "equity_fmv_cents"],
                    [])
    req_id = req_string(body, "requisition_id")
    cand_id = req_string(body, "candidate_id")
    base = req_int(body, "base_cents", min_value=1)
    bonus_pct = req_number(body, "bonus_target_pct", min_value=0)
    equity_shares = req_int(body, "equity_shares", allow_zero=True)
    equity_fmv = req_int(body, "equity_fmv_cents", allow_zero=True)
    require_role(role, ["Recruiter", "HiringManager"])
    # Existence (priority 5): body FK references, left to right
    req = db.requisitions.get(req_id)
    if req is None:
        raise_err(ERR_REQUISITION_NOT_FOUND, "Requisition not found")
    cand = db.candidates.get(cand_id)
    if cand is None:
        raise_err(ERR_CANDIDATE_NOT_FOUND, "Candidate not found")
    # State gates (priority 6)
    if req["status"] != "OPEN":
        raise_err(ERR_REQUISITION_NOT_OPEN, "Requisition is not OPEN")
    if cand["status"] == "ARCHIVED":
        raise_err(ERR_CANDIDATE_NOT_HIRABLE, "Candidate is ARCHIVED")
    # Fiscal (priority 12): hard cap
    if calc.exceeds_hard_cap(base, req):
        raise_err(ERR_BASE_EXCEEDS_HARD_CAP, "base_cents exceeds salary_max_cents * 1.25")
    ts = db.now_ms()
    offer = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "requisition_id": req_id,
        "candidate_id": cand_id,
        "created_by_user_id": uid,
        "base_cents": base,
        "bonus_target_pct": bonus_pct,
        "equity_shares": equity_shares,
        "equity_fmv_cents": equity_fmv,
        "status": "DRAFT",
        "clearance_posture": "NOT_STARTED",
        "round_count": 0,
        "original_submitted_base_cents": None,
        "expires_at": None,
        "declination_reason": None,
        "rescind_reason": None,
    }
    db.offers[offer["id"]] = offer
    calc.recompute_offer_analytics(offer, req)
    if cand["status"] == "PROSPECT":
        cand["status"] = "IN_PROCESS"
        calc.touch(cand)
    offer_ops.append_event(offer["id"], "OFFER_CREATED", uid, None)
    return success(offer, status=201)


@bp.route("/api/offers", methods=["GET"])
def list_all():
    uid, role = get_actor()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    items = sorted(db.offers.values(), key=lambda o: o["created_at"])
    if role == "Candidate":
        items = [o for o in items if o["candidate_id"] == uid]
    req_f = request.args.get("requisition_id")
    cand_f = request.args.get("candidate_id")
    status_f = request.args.get("status")
    if req_f is not None:
        items = [o for o in items if o["requisition_id"] == req_f]
    if cand_f is not None:
        items = [o for o in items if o["candidate_id"] == cand_f]
    if status_f is not None:
        items = [o for o in items if o["status"] == status_f]
    page, pg = paginate(items, limit, offset)
    return success(list(page), response_type="array", pagination=pg)


@bp.route("/api/offers/<offer_id>", methods=["GET"])
def get_one(offer_id):
    uid, role = get_actor()
    require_role(role, READ_ROLES)
    offer = get_offer(offer_id)
    candidate_owns(offer, uid, role)
    # lazy expiry may persist EXPIRED on read
    offer_ops.check_lazy_expiry(offer)
    return success(offer)


@bp.route("/api/offers/<offer_id>", methods=["PATCH"])
def patch(offer_id):
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body,
                    ["expected_offer_version"],
                    ["base_cents", "bonus_target_pct", "equity_shares",
                     "equity_fmv_cents"])
    expected = req_int(body, "expected_offer_version")
    require_role(role, ["Recruiter", "HiringManager"])
    offer = get_offer(offer_id)
    if offer["status"] not in ("DRAFT", "RETURNED"):
        raise_err(ERR_INVALID_OFFER_STATE, "Offer terms may only be revised in DRAFT or RETURNED")
    if expected != offer["version"]:
        raise_err(ERR_STALE_OFFER_VERSION, "Stale offer version")
    if "base_cents" in body:
        offer["base_cents"] = req_int(body, "base_cents", min_value=1)
    if "bonus_target_pct" in body:
        offer["bonus_target_pct"] = req_number(body, "bonus_target_pct", min_value=0)
    if "equity_shares" in body:
        offer["equity_shares"] = req_int(body, "equity_shares", allow_zero=True)
    if "equity_fmv_cents" in body:
        offer["equity_fmv_cents"] = req_int(body, "equity_fmv_cents", allow_zero=True)
    req = db.requisitions[offer["requisition_id"]]
    calc.recompute_offer_analytics(offer, req)
    calc.touch(offer)
    offer_ops.append_event(offer["id"], "TERMS_REVISED", uid, None)
    return success(offer)


def _create_steps(offer, chain, actor):
    for seq, role_name in enumerate(chain):
        ts = db.now_ms()
        step = {
            "id": db.new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "offer_id": offer["id"],
            "sequence": seq,
            "required_role": role_name,
            "status": "ACTIONABLE" if seq == 0 else "WAITING",
            "decided_by_user_id": None,
            "decided_via_delegation": False,
            "delegation_grant_id": None,
            "decision_note": None,
        }
        db.approval_steps[step["id"]] = step


@bp.route("/api/offers/<offer_id>/submit", methods=["POST"])
def submit(offer_id):
    uid, role = get_actor()
    if db.request_has_body():
        get_json_body()
    require_role(role, ["Recruiter", "HiringManager"])
    offer = get_offer(offer_id)
    if offer["status"] not in ("DRAFT", "RETURNED"):
        raise_err(ERR_INVALID_OFFER_STATE, "Submit only from DRAFT or RETURNED")
    req = db.requisitions[offer["requisition_id"]]
    if req["status"] != "OPEN":
        raise_err(ERR_REQUISITION_NOT_OPEN, "Requisition is not OPEN")
    # Peer-data sufficiency (priority 9)
    if calc.matching_peer_count(req) < calc.MIN_PEER_SNAPSHOTS:
        raise_err(ERR_INSUFFICIENT_PEER_DATA, "Fewer than 3 matching peer snapshots")
    # recompute equity metrics at submission once the gate passes
    calc.compute_equity_metrics(offer, req)
    # Fiscal gates (priority 12): budget then hard cap
    if offer["fully_loaded_annual_cost_cents"] > req["annual_budget_cents"] - req["committed_budget_cents"]:
        raise_err(ERR_REQUISITION_BUDGET_EXCEEDED, "Offer exceeds remaining requisition budget")
    if calc.exceeds_hard_cap(offer["base_cents"], req):
        raise_err(ERR_BASE_EXCEEDS_HARD_CAP, "base_cents exceeds salary_max_cents * 1.25")
    # Resubmission from RETURNED: supersede pre-existing chain
    if offer["status"] == "RETURNED":
        offer_ops.supersede_steps(offer["id"], ("WAITING", "ACTIONABLE", "APPROVED"), uid)
    if offer["original_submitted_base_cents"] is None:
        offer["original_submitted_base_cents"] = offer["base_cents"]
    offer["status"] = "PENDING_APPROVAL"
    calc.touch_no_version(offer)
    chain = calc.build_approval_chain(offer)
    _create_steps(offer, chain, uid)
    # perks DRAFT -> LOCKED
    for p in db.perks.values():
        if p["offer_id"] == offer["id"] and p["status"] == "DRAFT":
            p["status"] = "LOCKED"
            calc.touch(p)
    calc.recompute_committed_budget(req)
    offer_ops.append_event(offer["id"], "SUBMITTED", uid, None)
    return success(offer)


@bp.route("/api/offers/<offer_id>/withdraw", methods=["POST"])
def withdraw(offer_id):
    uid, role = get_actor()
    body = get_json_body() if db.request_has_body() else {}
    if body:
        validate_fields(body, [], ["reason"])
    require_role(role, ["Recruiter", "HiringManager"])
    offer = get_offer(offer_id)
    if offer["status"] not in ("DRAFT", "RETURNED", "PENDING_APPROVAL"):
        raise_err(ERR_INVALID_OFFER_STATE, "Withdraw only from DRAFT, RETURNED, or PENDING_APPROVAL")
    req = db.requisitions[offer["requisition_id"]]
    prior = offer["status"]
    if prior == "PENDING_APPROVAL":
        offer_ops.supersede_steps(offer["id"], ("WAITING", "ACTIONABLE"), uid)
        offer_ops.void_perks(offer["id"], ("LOCKED",), uid)
    else:
        offer_ops.void_perks(offer["id"], ("DRAFT",), uid)
    offer["status"] = "WITHDRAWN"
    calc.touch_no_version(offer)
    if prior == "PENDING_APPROVAL":
        calc.recompute_committed_budget(req)
    offer_ops.append_event(offer["id"], "WITHDRAWN", uid, None)
    return success(offer)


@bp.route("/api/offers/<offer_id>/letters", methods=["POST"])
def generate_letter(offer_id):
    uid, role = get_actor()
    if db.request_has_body():
        get_json_body()
    require_role(role, ["Recruiter"])
    offer = get_offer(offer_id)
    if offer["status"] not in ("APPROVED", "LETTER_GENERATED"):
        raise_err(ERR_INVALID_OFFER_STATE, "Letters may be generated only from APPROVED or LETTER_GENERATED")
    req = db.requisitions[offer["requisition_id"]]
    if req["status"] != "OPEN":
        raise_err(ERR_REQUISITION_NOT_OPEN, "Requisition is not OPEN")
    # supersede current GENERATED letter
    letters = [l for l in db.offer_letters.values() if l["offer_id"] == offer["id"]]
    max_seq = 0
    for l in letters:
        max_seq = max(max_seq, l["sequence"])
        if l["status"] == "GENERATED":
            l["status"] = "SUPERSEDED"
            calc.touch(l)
            offer_ops.append_event(offer["id"], "LETTER_SUPERSEDED", uid, f"sequence={l['sequence']}")
    body_text = (
        f"Offer letter for candidate {offer['candidate_id']} on requisition "
        f"{offer['requisition_id']}: base_cents={offer['base_cents']}, "
        f"bonus_target_pct={offer['bonus_target_pct']}, "
        f"equity_shares={offer['equity_shares']}, "
        f"equity_fmv_cents={offer['equity_fmv_cents']}, "
        f"pinned_offer_version={offer['version']}."
    )
    ts = db.now_ms()
    letter = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "offer_id": offer["id"],
        "sequence": max_seq + 1,
        "pinned_offer_version": offer["version"],
        "body_text": body_text,
        "status": "GENERATED",
    }
    db.offer_letters[letter["id"]] = letter
    if offer["status"] == "APPROVED":
        offer["status"] = "LETTER_GENERATED"
        calc.touch_no_version(offer)
    offer_ops.append_event(offer["id"], "LETTER_GENERATED", uid, f"sequence={letter['sequence']}")
    return success(letter, status=201)


@bp.route("/api/offers/<offer_id>/extend", methods=["POST"])
def extend(offer_id):
    uid, role = get_actor()
    if db.request_has_body():
        get_json_body()
    require_role(role, ["Recruiter"])
    offer = get_offer(offer_id)
    if offer["status"] != "LETTER_GENERATED":
        raise_err(ERR_INVALID_OFFER_STATE, "Extend only from LETTER_GENERATED")
    letters = [l for l in db.offer_letters.values() if l["offer_id"] == offer["id"]]
    latest = max(letters, key=lambda l: l["sequence"]) if letters else None
    if latest is None or latest["status"] != "GENERATED" or latest["pinned_offer_version"] != offer["version"]:
        raise_err(ERR_INVALID_OFFER_STATE,
                  "Latest letter must be GENERATED and pinned to the current offer version")
    for other in db.offers.values():
        if (other["candidate_id"] == offer["candidate_id"] and other["id"] != offer["id"]
                and other["status"] in ("EXTENDED", "COUNTERED", "ACCEPTED")):
            raise_err(ERR_CANDIDATE_ACTIVE_OFFER_EXISTS,
                      "Candidate already has an active extended offer")
    offer_ops.set_expires_at(offer)
    offer["status"] = "EXTENDED"
    calc.touch_no_version(offer)
    offer_ops.append_event(offer["id"], "EXTENDED", uid, None)
    return success(offer)


@bp.route("/api/offers/<offer_id>/accept", methods=["POST"])
def accept(offer_id):
    uid, role = get_actor()
    if db.request_has_body():
        get_json_body()
    require_role(role, ["Candidate"])
    offer = get_offer(offer_id)
    candidate_owns(offer, uid, role)
    if offer["status"] not in ("EXTENDED", "COUNTERED"):
        raise_err(ERR_INVALID_OFFER_STATE, "Accept only from EXTENDED or COUNTERED")
    # lazy expiry first
    if offer_ops.check_lazy_expiry(offer):
        raise_err(ERR_OFFER_EXPIRED, "Offer has expired")
    if offer["status"] == "COUNTERED":
        offer_ops.withdraw_proposed_round(offer["id"], uid)
    offer["status"] = "ACCEPTED"
    calc.touch_no_version(offer)
    offer_ops.append_event(offer["id"], "ACCEPTED", uid, None)
    return success(offer)


@bp.route("/api/offers/<offer_id>/decline", methods=["POST"])
def decline(offer_id):
    uid, role = get_actor()
    body = get_json_body()
    # `reason` is NOT a shape-tier required field: PRD 3.6 rejects a *missing*
    # reason with ERR_DECLINATION_REASON_REQUIRED (a tier-10 business
    # constraint), not ERR_INVALID_REQUEST.
    validate_fields(body, [], ["reason", "detail"])
    require_role(role, ["Candidate"])
    reason = body.get("reason")
    offer = get_offer(offer_id)
    candidate_owns(offer, uid, role)
    if offer["status"] not in ("EXTENDED", "COUNTERED"):
        raise_err(ERR_INVALID_OFFER_STATE, "Decline only from EXTENDED or COUNTERED")
    if not isinstance(reason, str) or reason not in DECLINATION_REASONS:
        raise_err(ERR_DECLINATION_REASON_REQUIRED, "A declination reason from the declared enum is required")
    if offer_ops.check_lazy_expiry(offer):
        raise_err(ERR_OFFER_EXPIRED, "Offer has expired")
    req = db.requisitions[offer["requisition_id"]]
    if offer["status"] == "COUNTERED":
        offer_ops.withdraw_proposed_round(offer["id"], uid)
    offer["declination_reason"] = reason
    offer["status"] = "DECLINED"
    calc.touch_no_version(offer)
    offer_ops.void_perks(offer["id"], ("APPROVED",), uid)
    calc.recompute_committed_budget(req)
    offer_ops.append_event(offer["id"], "DECLINED", uid, reason)
    return success(offer)


@bp.route("/api/offers/<offer_id>/rescind", methods=["POST"])
def rescind(offer_id):
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body, ["reason"], [])
    reason = req_enum(body, "reason", RESCIND_REASONS)
    require_role(role, ["HRAdmin", "HiringManager"])
    offer = get_offer(offer_id)
    req = db.requisitions[offer["requisition_id"]]
    if role == "HiringManager" and req["hiring_manager_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER,
                  "HiringManager may only rescind offers on requisitions they own")
    if offer["status"] not in ("LETTER_GENERATED", "EXTENDED", "COUNTERED", "ACCEPTED", "HIRED"):
        raise_err(ERR_INVALID_OFFER_STATE,
                  "Rescind only from LETTER_GENERATED, EXTENDED, COUNTERED, ACCEPTED, or HIRED")
    if offer["status"] in ("EXTENDED", "COUNTERED") and offer_ops.check_lazy_expiry(offer):
        raise_err(ERR_OFFER_EXPIRED, "Offer has expired")
    prior = offer["status"]
    offer["status"] = "RESCINDED"
    offer["rescind_reason"] = reason
    calc.touch_no_version(offer)
    if prior == "COUNTERED":
        offer_ops.withdraw_proposed_round(offer["id"], uid)
    if prior == "ACCEPTED":
        offer_ops.cancel_inflight_checks(offer["id"], uid)
        offer_ops.void_perks(offer["id"], ("APPROVED",), uid)
        calc.recompute_committed_budget(req)
    elif prior == "HIRED":
        offer_ops.cancel_inflight_checks(offer["id"], uid)
        offer_ops.void_perks(offer["id"], ("ACTIVE",), uid)
        # headcount recompute downward; reopen if closed FILLED
        req["headcount_filled"] = sum(
            1 for o in db.offers.values()
            if o["requisition_id"] == req["id"] and o["status"] == "HIRED"
        )
        if req["status"] == "CLOSED" and req["close_reason"] == "FILLED":
            req["status"] = "OPEN"
            req["close_reason"] = None
        calc.touch(req)
        cand = db.candidates.get(offer["candidate_id"])
        if cand and cand["status"] == "HIRED":
            cand["status"] = "IN_PROCESS"
            calc.touch(cand)
        calc.recompute_committed_budget(req)
    else:  # LETTER_GENERATED / EXTENDED / COUNTERED
        offer_ops.void_perks(offer["id"], ("APPROVED",), uid)
        calc.recompute_committed_budget(req)
    offer_ops.append_event(offer["id"], "RESCINDED", uid, reason)
    return success(offer)
