"""Proposals, gift agreements, and naming opportunities."""

from datetime import timedelta

from flask import Blueprint, request

from core import (
    authenticate, authorize, body_json, check_unknown_fields, req_str, opt_str,
    req_int, opt_int, req_money, req_enum, now, new_entity, touch,
    success_object, success_list, paginate, ALL_ROLES,
)
from db import store
from errors import (
    fail, ERR_PROSPECT_NOT_FOUND, ERR_PROPOSAL_NOT_FOUND, ERR_AGREEMENT_NOT_FOUND,
    ERR_RESOURCE_NOT_FOUND, ERR_STALE_VERSION, ERR_PROSPECT_NOT_RATED,
    ERR_PROSPECT_NOT_SOLICITABLE, ERR_PROPOSAL_STATE_FORBIDS,
    ERR_PROPOSAL_NOT_UNDER_REVIEW, ERR_PROPOSAL_NOT_APPROVED,
    ERR_AGREEMENT_INVALID_STATE, ERR_RESCIND_BLOCKED_BY_PAYMENTS,
    ERR_SEGREGATION_OF_DUTIES, ERR_DUPLICATE_APPROVAL,
    ERR_TIER_APPROVAL_ROLE_VIOLATION, ERR_ASK_EXCEEDS_CAPACITY,
    ERR_OPEN_ASK_LOAD_EXCEEDED, ERR_AGREEMENT_AMOUNT_MISMATCH,
    ERR_BELOW_NAMING_FLOOR, ERR_NAMING_OPPORTUNITY_UNAVAILABLE,
    ERR_RESERVATION_EXPIRED,
)
from services import (
    ser_proposal, ser_agreement, ser_naming_opportunity,
    require_prospect_owner, owner_fundraiser_id, bump_owner_fundraiser,
    approval_tier_determination, fundraiser_current_open_ask_cents,
    recompute_campaign_totals, refresh_prospect_recognition,
    OPEN_PROPOSAL_STATES, MINIMUM_ACTIVATION_CENTS,
)

bp = Blueprint("proposals", __name__)


def _get_proposal(pid):
    proposal = store["proposals"].get(pid)
    if proposal is None:
        fail(ERR_PROPOSAL_NOT_FOUND, "Proposal not found")
    return proposal


def _get_agreement(aid):
    agreement = store["agreements"].get(aid)
    if agreement is None:
        fail(ERR_AGREEMENT_NOT_FOUND, "Agreement not found")
    return agreement


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------

@bp.get("/advancement/prospects/<pid>/proposals")
def list_prospect_proposals(pid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    if pid not in store["prospects"]:
        fail(ERR_PROSPECT_NOT_FOUND, "Prospect not found")
    items = [p for p in store["proposals"].values() if p["prospect_id"] == pid]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([ser_proposal(p) for p in page], limit, offset, total)


@bp.post("/advancement/proposals")
def create_proposal():
    user_id, role = authenticate()
    authorize(role, ["GiftOfficer"])
    body = body_json()
    check_unknown_fields(body, {"prospect_id", "proposal_type", "ask_amount_cents",
                                "designation_purpose", "expected_prospect_version"})
    prospect_id = req_str(body, "prospect_id")
    proposal_type = req_enum(body, "proposal_type", {"OUTRIGHT", "PLEDGE", "PLANNED"})
    ask_amount_cents = req_money(body, "ask_amount_cents")
    designation_purpose = req_str(body, "designation_purpose")
    expected_version = req_int(body, "expected_prospect_version")
    # existence (priority 4)
    prospect = store["prospects"].get(prospect_id)
    if prospect is None:
        fail(ERR_PROSPECT_NOT_FOUND, "Prospect not found")
    # portfolio ownership (priority 5)
    require_prospect_owner(user_id, prospect_id)
    # OCC on the prospect version (priority 7)
    if expected_version != prospect["version"]:
        fail(ERR_STALE_VERSION, "expected_prospect_version does not match the prospect's current version")
    # readiness gates (priority 8)
    if prospect["research_status"] != "RATED":
        fail(ERR_PROSPECT_NOT_RATED, "Prospect must be RATED before a proposal is created")
    if prospect["moves_stage"] not in ("CULTIVATION", "SOLICITATION", "NEGOTIATION"):
        fail(ERR_PROSPECT_NOT_SOLICITABLE,
             "Prospect moves_stage must be CULTIVATION, SOLICITATION, or NEGOTIATION")
    entity = new_entity()
    entity.update({
        "prospect_id": prospect_id,
        "proposal_type": proposal_type,
        "ask_amount_cents": ask_amount_cents,
        "designation_purpose": designation_purpose,
        "approval_tier": None,
        "effective_ask_cents": None,
        "pinned_capacity_band": None,
        "submitted_by": None,
        "approvals_received": 0,
        "approver_ids": [],
        "decided_by": None,
        "decision_rationale": None,
        "approved_at": None,
        "status": "DRAFT",
    })
    store["proposals"][entity["id"]] = entity
    touch(prospect)
    return success_object(ser_proposal(entity), 201)


@bp.get("/advancement/proposals/<pid>")
def get_proposal(pid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    return success_object(ser_proposal(_get_proposal(pid)))


@bp.patch("/advancement/proposals/<pid>")
def patch_proposal(pid):
    user_id, role = authenticate()
    authorize(role, ["GiftOfficer"])
    body = body_json()
    check_unknown_fields(body, {"ask_amount_cents", "designation_purpose"})
    ask_amount_cents = opt_int(body, "ask_amount_cents", minimum=1)
    designation_purpose = opt_str(body, "designation_purpose")
    proposal = _get_proposal(pid)
    require_prospect_owner(user_id, proposal["prospect_id"])
    if proposal["status"] not in ("DRAFT", "NEGOTIATING", "RETURNED", "REJECTED"):
        fail(ERR_PROPOSAL_STATE_FORBIDS, f"Proposal in {proposal['status']} cannot be edited")
    was_open = proposal["status"] in OPEN_PROPOSAL_STATES
    if ask_amount_cents is not None:
        proposal["ask_amount_cents"] = ask_amount_cents
    if designation_purpose is not None:
        proposal["designation_purpose"] = designation_purpose
    # reset to DRAFT and clear the review machinery
    proposal["status"] = "DRAFT"
    proposal["approval_tier"] = None
    proposal["effective_ask_cents"] = None
    proposal["pinned_capacity_band"] = None
    proposal["approvals_received"] = 0
    proposal["approver_ids"] = []
    touch(proposal)
    if was_open:
        bump_owner_fundraiser(proposal["prospect_id"])
    return success_object(ser_proposal(proposal))


@bp.post("/advancement/proposals/<pid>/submit")
def submit_proposal(pid):
    user_id, role = authenticate()
    authorize(role, ["GiftOfficer"])
    body_json()  # no documented inputs
    proposal = _get_proposal(pid)
    require_prospect_owner(user_id, proposal["prospect_id"])
    if proposal["status"] not in ("DRAFT", "RETURNED", "REJECTED", "NEGOTIATING"):
        fail(ERR_PROPOSAL_STATE_FORBIDS, f"Proposal in {proposal['status']} cannot be submitted")
    prospect = store["prospects"][proposal["prospect_id"]]
    # capacity ceiling: ask may not exceed the rated adjusted capacity
    rated_capacity = prospect["rated_adjusted_capacity_cents"]
    if rated_capacity is None or proposal["ask_amount_cents"] > rated_capacity:
        fail(ERR_ASK_EXCEEDS_CAPACITY, "ask_amount_cents exceeds the prospect's rated adjusted capacity")
    # open-ask ceiling: current + this ask must be <= max (equality allowed)
    fid = owner_fundraiser_id(proposal["prospect_id"])
    fundraiser = store["fundraisers"].get(fid) if fid else None
    if fundraiser is not None:
        if fundraiser_current_open_ask_cents(fid) + proposal["ask_amount_cents"] > fundraiser["max_open_ask_cents"]:
            fail(ERR_OPEN_ASK_LOAD_EXCEEDED, "Submission would exceed the fundraiser's open-ask ceiling")
    tier, effective = approval_tier_determination(proposal, prospect)
    proposal["approval_tier"] = tier
    proposal["effective_ask_cents"] = effective
    proposal["pinned_capacity_band"] = prospect["capacity_band"]
    proposal["submitted_by"] = user_id
    proposal["approvals_received"] = 0
    proposal["approver_ids"] = []
    proposal["decided_by"] = None
    proposal["status"] = "UNDER_REVIEW"
    touch(proposal)
    if fundraiser is not None:
        touch(fundraiser)
    return success_object(ser_proposal(proposal))


@bp.post("/advancement/proposals/<pid>/review")
def review_proposal(pid):
    user_id, role = authenticate()
    authorize(role, ["AdvancementDirector", "VPAdvancement"])
    body = body_json()
    check_unknown_fields(body, {"decision", "decision_rationale"})
    decision = req_enum(body, "decision", {"APPROVE", "NEGOTIATE", "RETURN", "REJECT"})
    rationale = opt_str(body, "decision_rationale")
    proposal = _get_proposal(pid)
    # segregation of duties / duplicate approval (priority 6)
    if user_id == proposal["submitted_by"]:
        fail(ERR_SEGREGATION_OF_DUTIES, "Reviewer must differ from the proposal's submitter")
    if decision == "APPROVE" and user_id in proposal["approver_ids"]:
        fail(ERR_DUPLICATE_APPROVAL, "This approver has already approved the current review round")
    # state precondition (priority 8)
    if proposal["status"] != "UNDER_REVIEW":
        fail(ERR_PROPOSAL_NOT_UNDER_REVIEW, "Proposal is not UNDER_REVIEW")
    # tier-role mapping (priority 11)
    tier = proposal["approval_tier"]
    if tier == "STANDARD":
        if role != "AdvancementDirector":
            fail(ERR_TIER_APPROVAL_ROLE_VIOLATION, "STANDARD proposals require an AdvancementDirector review")
    else:  # MAJOR or PRINCIPAL
        if role != "VPAdvancement":
            fail(ERR_TIER_APPROVAL_ROLE_VIOLATION, f"{tier} proposals require a VPAdvancement review")
    if rationale is not None:
        proposal["decision_rationale"] = rationale
    if decision == "NEGOTIATE":
        proposal["status"] = "NEGOTIATING"
        touch(proposal)
        return success_object(ser_proposal(proposal))
    if decision == "RETURN":
        proposal["status"] = "RETURNED"
        touch(proposal)
        return success_object(ser_proposal(proposal))
    if decision == "REJECT":
        proposal["status"] = "REJECTED"
        proposal["decided_by"] = user_id
        touch(proposal)
        # leaves the open proposal states: recompute the owner's open-ask load
        bump_owner_fundraiser(proposal["prospect_id"])
        return success_object(ser_proposal(proposal))
    # APPROVE
    proposal["approvals_received"] += 1
    proposal["approver_ids"].append(user_id)
    quorum = 2 if tier == "PRINCIPAL" else 1
    if proposal["approvals_received"] < quorum:
        # first PRINCIPAL approval leaves the proposal UNDER_REVIEW
        touch(proposal)
        return success_object(ser_proposal(proposal))
    proposal["status"] = "APPROVED"
    proposal["decided_by"] = user_id
    proposal["approved_at"] = now()
    touch(proposal)
    # approval is exclusive per prospect: supersede any other APPROVED proposal
    superseded_prospects = set()
    for other in store["proposals"].values():
        if (other["prospect_id"] == proposal["prospect_id"] and other["id"] != proposal["id"]
                and other["status"] == "APPROVED"):
            other["status"] = "SUPERSEDED"
            touch(other)
            superseded_prospects.add(other["prospect_id"])
    for spid in superseded_prospects:
        bump_owner_fundraiser(spid)
    return success_object(ser_proposal(proposal))


# ---------------------------------------------------------------------------
# Gift agreements
# ---------------------------------------------------------------------------

@bp.post("/advancement/proposals/<pid>/agreements")
def create_agreement(pid):
    user_id, role = authenticate()
    authorize(role, ["GiftOfficer"])
    body = body_json()
    check_unknown_fields(body, {"restriction_type", "agreement_amount_cents",
                                "purpose_code", "naming_opportunity_id"})
    restriction_type = req_enum(body, "restriction_type",
                                {"UNRESTRICTED", "RESTRICTED_CURRENT_USE", "ENDOWED"})
    agreement_amount_cents = req_money(body, "agreement_amount_cents")
    purpose_code = opt_str(body, "purpose_code")
    naming_opportunity_id = opt_str(body, "naming_opportunity_id")
    if restriction_type != "UNRESTRICTED" and purpose_code is None:
        from errors import ERR_INVALID_REQUEST
        fail(ERR_INVALID_REQUEST, "purpose_code is required for restricted agreements")
    # existence: proposal path segment, then naming body reference
    proposal = _get_proposal(pid)
    opportunity = None
    if naming_opportunity_id is not None:
        opportunity = store["naming_opportunities"].get(naming_opportunity_id)
        if opportunity is None:
            fail(ERR_RESOURCE_NOT_FOUND, "Naming opportunity not found")
    # ownership (priority 5)
    require_prospect_owner(user_id, proposal["prospect_id"])
    # state (priority 8)
    if proposal["status"] != "APPROVED":
        fail(ERR_PROPOSAL_NOT_APPROVED, "Agreement requires an APPROVED proposal")
    # amount equality, then naming floor (priority 11)
    if agreement_amount_cents != proposal["ask_amount_cents"]:
        fail(ERR_AGREEMENT_AMOUNT_MISMATCH, "agreement_amount_cents must equal the approved ask_amount_cents")
    if opportunity is not None and agreement_amount_cents < opportunity["price_floor_cents"]:
        fail(ERR_BELOW_NAMING_FLOOR, "agreement_amount_cents is below the naming opportunity's price floor")
    entity = new_entity()
    entity.update({
        "proposal_id": pid,
        "prospect_id": proposal["prospect_id"],
        "restriction_type": restriction_type,
        "purpose_code": purpose_code,
        "naming_opportunity_id": naming_opportunity_id,
        "agreement_amount_cents": agreement_amount_cents,
        "reservation_expires_at": None,
        "signature_status": "DRAFT",
        "compliance_status": "COMPLIANT",
    })
    store["agreements"][entity["id"]] = entity
    return success_object(ser_agreement(entity), 201)


@bp.get("/advancement/agreements/<aid>")
def get_agreement(aid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    return success_object(ser_agreement(_get_agreement(aid)))


@bp.get("/advancement/agreements")
def list_agreements():
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(store["agreements"].values())
    for param in ("proposal_id", "prospect_id", "naming_opportunity_id", "signature_status"):
        value = request.args.get(param)
        if value is not None:
            items = [a for a in items if a.get(param) == value]
    page, limit, offset, total = paginate(items)
    return success_list([ser_agreement(a) for a in page], limit, offset, total)


@bp.post("/advancement/agreements/<aid>/present")
def present_agreement(aid):
    user_id, role = authenticate()
    authorize(role, ["GiftOfficer"])
    body_json()  # no documented inputs
    agreement = _get_agreement(aid)
    require_prospect_owner(user_id, agreement["prospect_id"])
    if agreement["signature_status"] != "DRAFT":
        fail(ERR_AGREEMENT_INVALID_STATE, "Only a DRAFT agreement can be presented")
    opportunity = None
    if agreement["naming_opportunity_id"] is not None:
        opportunity = store["naming_opportunities"].get(agreement["naming_opportunity_id"])
        if opportunity is None or opportunity["status"] != "AVAILABLE":
            fail(ERR_NAMING_OPPORTUNITY_UNAVAILABLE, "Naming opportunity is not AVAILABLE")
    agreement["signature_status"] = "PENDING_SIGNATURE"
    touch(agreement)
    if opportunity is not None:
        reserved_until = now() + timedelta(days=14)
        opportunity["status"] = "RESERVED"
        opportunity["reserved_by_agreement_id"] = agreement["id"]
        opportunity["reserved_until"] = reserved_until
        touch(opportunity)
        agreement["reservation_expires_at"] = reserved_until
    return success_object(ser_agreement(agreement))


@bp.post("/advancement/agreements/<aid>/execute")
def execute_agreement(aid):
    user_id, role = authenticate()
    authorize(role, ["VPAdvancement"])
    body_json()  # no documented inputs
    agreement = _get_agreement(aid)
    if agreement["signature_status"] != "PENDING_SIGNATURE":
        fail(ERR_AGREEMENT_INVALID_STATE, "Only a PENDING_SIGNATURE agreement can be executed")
    opportunity = None
    if agreement["naming_opportunity_id"] is not None:
        opportunity = store["naming_opportunities"].get(agreement["naming_opportunity_id"])
        held_by_this = (
            opportunity is not None
            and opportunity["status"] == "RESERVED"
            and opportunity["reserved_by_agreement_id"] == agreement["id"]
        )
        if not held_by_this:
            # OCCUPIED / RETIRED / RESERVED by another / missing -> unavailable;
            # an AVAILABLE opportunity here means the reservation lapsed and the
            # sweep already released it.
            if opportunity is not None and opportunity["status"] == "AVAILABLE":
                fail(ERR_RESERVATION_EXPIRED, "The naming reservation window has lapsed")
            fail(ERR_NAMING_OPPORTUNITY_UNAVAILABLE, "Naming opportunity is not held for this agreement")
        expires = agreement["reservation_expires_at"]
        if expires is not None and now() >= expires:
            fail(ERR_RESERVATION_EXPIRED, "The naming reservation window has lapsed")
    agreement["signature_status"] = "EXECUTED"
    touch(agreement)
    if opportunity is not None:
        opportunity["status"] = "OCCUPIED"
        touch(opportunity)  # reserved_until kept for audit
    # establish the restricted fund for restricted agreement types
    if agreement["restriction_type"] in ("RESTRICTED_CURRENT_USE", "ENDOWED"):
        fund = new_entity()
        fund.update({
            "agreement_id": agreement["id"],
            "purpose_code": agreement["purpose_code"],
            "is_endowed": agreement["restriction_type"] == "ENDOWED",
            "balance_cents": 0,
            "minimum_activation_cents": MINIMUM_ACTIVATION_CENTS,
            "trailing_market_values": [],
            "disbursements": [],
            "status": "PENDING_MINIMUM",
        })
        store["funds"][fund["id"]] = fund
    # the only path into STEWARDSHIP
    prospect = store["prospects"].get(agreement["prospect_id"])
    if prospect is not None and prospect["moves_stage"] in ("CULTIVATION", "SOLICITATION", "NEGOTIATION"):
        prospect["moves_stage"] = "STEWARDSHIP"
        touch(prospect)
    return success_object(ser_agreement(agreement))


@bp.post("/advancement/agreements/<aid>/rescind")
def rescind_agreement(aid):
    user_id, role = authenticate()
    authorize(role, ["VPAdvancement"])
    body_json()  # no documented inputs
    agreement = _get_agreement(aid)
    if agreement["signature_status"] == "RESCINDED":
        fail(ERR_AGREEMENT_INVALID_STATE, "Agreement is already RESCINDED")
    pledge = next((p for p in store["pledges"].values() if p["agreement_id"] == aid), None)
    fund = next((f for f in store["funds"].values() if f["agreement_id"] == aid), None)
    # guard: no non-reversed payment referencing the agreement's pledge or fund
    for g in store["payments"].values():
        if g["reversed"]:
            continue
        if pledge is not None and g["pledge_id"] == pledge["id"]:
            fail(ERR_RESCIND_BLOCKED_BY_PAYMENTS, "A non-reversed payment references the agreement's pledge")
        if fund is not None and g["fund_id"] == fund["id"]:
            fail(ERR_RESCIND_BLOCKED_BY_PAYMENTS, "A non-reversed payment references the agreement's fund")
    agreement["signature_status"] = "RESCINDED"
    touch(agreement)
    # release a naming opportunity held by this agreement
    for opp in store["naming_opportunities"].values():
        if opp["reserved_by_agreement_id"] == aid and opp["status"] in ("RESERVED", "OCCUPIED"):
            opp["status"] = "AVAILABLE"
            opp["reserved_by_agreement_id"] = None
            opp["reserved_until"] = None
            touch(opp)
    # cancel the pledge, if any
    if pledge is not None and pledge["status"] != "CANCELLED":
        pledge["status"] = "CANCELLED"
        touch(pledge)
        if pledge["campaign_id"] is not None:
            campaign = store["campaigns"].get(pledge["campaign_id"])
            if campaign is not None:
                recompute_campaign_totals(campaign)
        prospect = store["prospects"].get(pledge["prospect_id"])
        if prospect is not None:
            refresh_prospect_recognition(prospect)
            touch(prospect)
    # close the established fund (balance must be zero)
    if fund is not None and fund["status"] != "CLOSED":
        fund["status"] = "CLOSED"
        touch(fund)
    return success_object(ser_agreement(agreement))


@bp.get("/advancement/agreements/<aid>/naming-reservations")
def list_agreement_naming_reservations(aid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    _get_agreement(aid)
    items = [
        o for o in store["naming_opportunities"].values()
        if o["reserved_by_agreement_id"] == aid and o["status"] in ("RESERVED", "OCCUPIED")
    ]
    page, limit, offset, total = paginate(items)
    return success_list([ser_naming_opportunity(o) for o in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Naming opportunities
# ---------------------------------------------------------------------------

@bp.post("/advancement/naming-opportunities")
def create_naming_opportunity():
    user_id, role = authenticate()
    authorize(role, ["VPAdvancement"])
    body = body_json()
    check_unknown_fields(body, {"name", "category", "price_floor_cents"})
    name = req_str(body, "name")
    category = req_enum(body, "category", {"BUILDING", "ENDOWED_CHAIR", "SCHOLARSHIP", "PROGRAM"})
    price_floor_cents = req_money(body, "price_floor_cents")
    entity = new_entity()
    entity.update({
        "name": name,
        "category": category,
        "price_floor_cents": price_floor_cents,
        "status": "AVAILABLE",
        "reserved_by_agreement_id": None,
        "reserved_until": None,
    })
    store["naming_opportunities"][entity["id"]] = entity
    return success_object(ser_naming_opportunity(entity), 201)


@bp.get("/advancement/naming-opportunities/<oid>")
def get_naming_opportunity(oid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    opportunity = store["naming_opportunities"].get(oid)
    if opportunity is None:
        fail(ERR_RESOURCE_NOT_FOUND, "Naming opportunity not found")
    return success_object(ser_naming_opportunity(opportunity))


@bp.post("/advancement/naming-opportunities/<oid>/retire")
def retire_naming_opportunity(oid):
    user_id, role = authenticate()
    authorize(role, ["VPAdvancement"])
    body_json()  # no documented inputs
    opportunity = store["naming_opportunities"].get(oid)
    if opportunity is None:
        fail(ERR_RESOURCE_NOT_FOUND, "Naming opportunity not found")
    if opportunity["status"] not in ("AVAILABLE", "RESERVED"):
        fail(ERR_NAMING_OPPORTUNITY_UNAVAILABLE,
             "Only an AVAILABLE or RESERVED opportunity can be retired")
    # a RESERVED opportunity's holding agreement keeps its signature_status but
    # loses its claim (execute later fails ERR_NAMING_OPPORTUNITY_UNAVAILABLE)
    opportunity["status"] = "RETIRED"
    touch(opportunity)
    return success_object(ser_naming_opportunity(opportunity))
