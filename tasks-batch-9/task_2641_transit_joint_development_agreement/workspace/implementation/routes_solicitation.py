"""Solicitations, proposals, closing/ranking and the award cascade."""

from flask import Blueprint, g

import authz
import calc
import common
import enums
import envelope
import shape
import store
from errors import fail

bp = Blueprint("solicitation", __name__)


# -------------------------------------------------------------- solicitations ---
@bp.post("/jda/sites/<site_id>/solicitations")
def draft_solicitation(site_id):
    authz.authorize("RealEstateOfficer")
    body = shape.body()
    solicitation_type = shape.as_enum(body, "solicitation_type", enums.SOLICITATION_TYPE)
    response_deadline = shape.as_datetime(body, "response_deadline")
    benchmark = shape.as_int(body, "benchmark_value_cents", minimum=1)
    affordable_min = shape.as_num(body, "affordable_housing_min_pct", minimum=0, maximum=100)
    min_proposals = shape.as_int(body, "min_proposals_required", required=False,
                                 default=1, minimum=1)
    joint_use_required = shape.as_bool(body, "joint_use_required", required=False, default=False)
    store.require("site", site_id)
    solicitation = store.create("solicitation", {
        "site_id": site_id,
        "solicitation_type": solicitation_type,
        "response_deadline": response_deadline,
        "benchmark_value_cents": benchmark,
        "affordable_housing_min_pct": affordable_min,
        "min_proposals_required": min_proposals,
        "joint_use_required": joint_use_required,
        "status": "DRAFT",
        "issued_at": None,
        "responsive_proposal_count": 0,
    })
    return envelope.created(common.public(solicitation))


@bp.post("/jda/solicitations/<solicitation_id>/issue")
def issue_solicitation(solicitation_id):
    authz.authorize("RealEstateOfficer")
    solicitation = store.require("solicitation", solicitation_id)
    site = store.require("site", solicitation["site_id"])
    if site["status"] != "SOLICITATION_READY":
        fail("ERR_INVALID_SITE_STATE",
             "Site must be SOLICITATION_READY for a solicitation to be issued")
    if solicitation["status"] != "DRAFT":
        fail("ERR_SOLICITATION_NOT_ISSUED", "Solicitation is not in DRAFT")
    deadline = store.parse_dt(solicitation["response_deadline"])
    if deadline is None or deadline <= store.now():
        fail("ERR_RESPONSE_DEADLINE_PASSED",
             "response_deadline must be strictly after the current instant")
    solicitation["status"] = "ISSUED"
    solicitation["issued_at"] = store.now_iso()
    store.touch(solicitation)
    return envelope.ok(common.public(solicitation))


# ------------------------------------------------------------------ proposals ---
@bp.post("/jda/solicitations/<solicitation_id>/proposals")
def submit_proposal(solicitation_id):
    user_id, _role = authz.authorize("Developer")
    body = shape.body()
    developer_id = shape.as_str(body, "developer_id")
    structure = shape.as_enum(body, "proposed_structure", enums.PROPOSED_STRUCTURE)
    annual_rent = shape.as_int(body, "proposed_annual_rent_cents", required=False,
                               default=0, minimum=0)
    purchase_price = shape.as_int(body, "proposed_purchase_price_cents", required=False,
                                  default=0, minimum=0)
    affordable_units = shape.as_int(body, "affordable_units", minimum=0)
    total_units = shape.as_int(body, "total_units", minimum=1)
    ridership = shape.as_int(body, "transit_ridership_uplift", minimum=0)
    design_score = shape.as_int(body, "design_compliance_score", minimum=0, maximum=100)
    joint_use_committed = shape.as_bool(body, "joint_use_committed", required=False,
                                        default=False)
    # Structure-conditional money fields (priority 3).
    if structure == "GROUND_LEASE" and annual_rent < 1:
        fail("ERR_INVALID_REQUEST",
             "proposed_annual_rent_cents must be at least 1 for a GROUND_LEASE proposal")
    if structure == "FEE_DISPOSITION" and purchase_price < 1:
        fail("ERR_INVALID_REQUEST",
             "proposed_purchase_price_cents must be at least 1 for a FEE_DISPOSITION proposal")
    solicitation = store.require("solicitation", solicitation_id)
    developer = store.require("developer", developer_id)
    if developer_id != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "developer_id must equal the acting developer")
    if solicitation["status"] != "ISSUED":
        fail("ERR_SOLICITATION_NOT_ISSUED", "Solicitation is not ISSUED")
    if developer["debarment_status"] != "CLEAR":
        fail("ERR_DEVELOPER_DEBARRED", "Developer is %s" % developer["debarment_status"])
    affordable_pct = calc.affordable_pct(affordable_units, total_units)
    if calc.dec(affordable_pct) < calc.dec(solicitation["affordable_housing_min_pct"]):
        fail("ERR_AFFORDABLE_MINIMUM_NOT_MET",
             "affordable share %s is below the solicitation minimum %s"
             % (affordable_pct, solicitation["affordable_housing_min_pct"]))
    if solicitation["joint_use_required"] and not joint_use_committed:
        fail("ERR_JOINT_USE_NOT_COMMITTED",
             "This solicitation requires a joint-use commitment")
    deadline = store.parse_dt(solicitation["response_deadline"])
    if deadline is not None and store.now() >= deadline:
        fail("ERR_RESPONSE_DEADLINE_PASSED", "The response deadline has passed")
    proposal = store.create("proposal", {
        "solicitation_id": solicitation_id,
        "developer_id": developer_id,
        "proposed_structure": structure,
        "proposed_annual_rent_cents": annual_rent,
        "proposed_purchase_price_cents": purchase_price,
        "affordable_units": affordable_units,
        "total_units": total_units,
        "transit_ridership_uplift": ridership,
        "design_compliance_score": design_score,
        "joint_use_committed": joint_use_committed,
        "affordable_pct": affordable_pct,
        "evaluation_score": 0.0,
        "rank": None,
        "status": "SUBMITTED",
    })
    # The evaluation score is computed once, at submission, and frozen thereafter.
    proposal["evaluation_score"] = calc.evaluation_score(proposal, solicitation, developer)
    common.refresh_responsive_count(solicitation, bump=True)
    return envelope.created(common.public(proposal))


@bp.post("/jda/proposals/<proposal_id>/shortlist")
def shortlist_proposal(proposal_id):
    authz.authorize("RealEstateOfficer")
    proposal = store.require("proposal", proposal_id)
    solicitation = store.require("solicitation", proposal["solicitation_id"])
    if solicitation["status"] not in ("ISSUED", "CLOSED"):
        fail("ERR_SOLICITATION_NOT_ISSUED", "Solicitation is neither ISSUED nor CLOSED")
    if proposal["status"] != "SUBMITTED":
        fail("ERR_PROPOSAL_NOT_ELIGIBLE", "Proposal is not in SUBMITTED")
    proposal["status"] = "SHORTLISTED"
    store.touch(proposal)
    # A SHORTLISTED proposal is still responsive, so the count is unchanged.
    common.refresh_responsive_count(solicitation, bump=True)
    return envelope.ok(common.public(proposal))


# ------------------------------------------------------------- close and rank ---
@bp.post("/jda/solicitations/<solicitation_id>/close")
def close_solicitation(solicitation_id):
    authz.authorize("RealEstateOfficer")
    solicitation = store.require("solicitation", solicitation_id)
    if solicitation["status"] != "ISSUED":
        fail("ERR_SOLICITATION_NOT_ISSUED", "Solicitation is not ISSUED")
    count = common.refresh_responsive_count(solicitation)
    if count < solicitation["min_proposals_required"]:
        fail("ERR_NO_RESPONSIVE_PROPOSALS",
             "Only %d responsive proposals against a minimum of %d"
             % (count, solicitation["min_proposals_required"]))
    solicitation["status"] = "CLOSED"
    store.touch(solicitation)
    candidates = [p for p in common.proposals_of(solicitation_id)
                  if p["status"] in common.RESPONSIVE_STATUSES]
    for index, proposal in enumerate(calc.rank_candidates(candidates), start=1):
        proposal["rank"] = index
        store.touch(proposal)
    return envelope.ok(common.public(solicitation))


# ------------------------------------------------------------ award cascade ---
@bp.post("/jda/solicitations/<solicitation_id>/award")
def award_solicitation(solicitation_id):
    authz.authorize("RealEstateOfficer")
    body = shape.body()
    proposal_id = shape.as_str(body, "proposal_id")
    start_date = shape.as_date(body, "negotiation_start_date")
    end_date = shape.as_date(body, "negotiation_end_date")
    justification = shape.as_str(body, "deviation_justification", required=False, default=None)
    solicitation = store.require("solicitation", solicitation_id)
    proposal = store.require("proposal", proposal_id)
    site = store.require("site", solicitation["site_id"])
    if solicitation["status"] != "CLOSED":
        fail("ERR_SOLICITATION_NOT_CLOSED", "Solicitation is not CLOSED")
    if (proposal["solicitation_id"] != solicitation_id
            or proposal["status"] not in common.RESPONSIVE_STATUSES):
        fail("ERR_PROPOSAL_NOT_ELIGIBLE",
             "The proposal does not belong to this solicitation or is not eligible")
    developer = store.require("developer", proposal["developer_id"])
    if developer["debarment_status"] != "CLEAR":
        fail("ERR_DEVELOPER_DEBARRED", "Developer is %s" % developer["debarment_status"])
    start = store.parse_date(start_date)
    end = store.parse_date(end_date)
    if end <= start:
        fail("ERR_INVALID_INTERVAL",
             "negotiation_end_date must be strictly later than negotiation_start_date")
    if common.period_collides(site["id"], start, end):
        fail("ERR_NEGOTIATION_PERIOD_OVERLAP",
             "The interval collides with a live exclusive negotiation period on the site")
    # The rank-deviation record sits in the remaining-business-constraint group,
    # so it is tested after debarment, interval and overlap (PRD 2.11).
    if proposal["rank"] != 1 and not (justification or "").strip():
        fail("ERR_RANK_DEVIATION_UNJUSTIFIED",
             "Awarding a proposal that is not ranked 1 requires a deviation_justification")

    solicitation["status"] = "AWARDED"
    store.touch(solicitation)
    # hop 1 — the awarded proposal becomes SELECTED
    proposal["status"] = "SELECTED"
    store.touch(proposal)
    # hop 2 — because that proposal became SELECTED, a period is created
    period = store.create("negotiation_period", {
        "site_id": site["id"],
        "proposal_id": proposal["id"],
        "start_date": start_date,
        "end_date": end_date,
        "extension_count": 0,
        "status": "ACTIVE",
        "termination_reason": None,
    })
    # hop 3 — because that period became ACTIVE, the site moves under agreement
    moved = common.move_site_under_agreement(site)
    if moved:
        # hop 4/5 — cancel the site's other DRAFT or ISSUED solicitations and
        # reject their live proposals
        common.cancel_site_solicitations(site["id"], ("DRAFT", "ISSUED"), {solicitation_id})
    # every non-awarded proposal of THIS solicitation is rejected
    for other in store.by_seq(common.proposals_of(solicitation_id)):
        if other["id"] != proposal["id"] and other["status"] in common.RESPONSIVE_STATUSES:
            other["status"] = "REJECTED"
            store.touch(other)
    common.refresh_responsive_count(solicitation)
    _ = period
    return envelope.ok(common.public(solicitation))
