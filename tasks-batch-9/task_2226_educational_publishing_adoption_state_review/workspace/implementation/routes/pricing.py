"""PricingProposal endpoints (PRD 3.6)."""

import calc
import domain
import serializers as S
import validation as V
from db import apply_changes, base_record, db, touch
from errors import fail
from middleware import authorize, check_state_scope
from response import respond, respond_list

from flask import Blueprint

bp = Blueprint("pricing", __name__)

READ_ROLES = ("PlatformAdmin", "PricingManager", "StateAdoptionOfficer", "SalesRep")

DECISION_VERDICTS = ("APPROVE", "REJECT")

FILEABLE_REVIEW_STATUSES = ("FILED", "SCHEDULED", "PRESENTED")
FILEABLE_CYCLE_STATUSES = ("OPEN", "CLOSED_FOR_SUBMISSION", "IN_REVIEW")

# PRD 2.11: accessibility is a ranked comparison; NONE satisfies no state at all.
ACCESSIBILITY_RANK = {"NONE": 0, "WCAG_2_1_AA": 1, "WCAG_2_2_AA": 2}


@bp.post("/pricing-proposals")
def file_proposal():
    authorize(("PricingManager",))
    payload = V.body()

    submission_id = V.get_str(payload, "submission_id")
    bundle_id = V.get_str(payload, "bundle_id", required=False, default=None)
    base_price_cents = V.get_int(payload, "base_price_cents", minimum=1)
    term_years = V.get_int(payload, "term_years", minimum=1, maximum=10)
    annual_escalator_bps = V.get_int(
        payload, "annual_escalator_bps", minimum=0, maximum=500
    )
    projected_adoption_units = V.get_int(
        payload, "projected_adoption_units", minimum=0
    )
    digital_seat_price_cents = V.get_int(
        payload, "digital_seat_price_cents", minimum=1
    )
    expected_submission_version = V.get_int(
        payload, "expected_submission_version", minimum=0
    )

    submission = domain.find_submission(
        submission_id, "ERR_REFERENCED_RESOURCE_NOT_FOUND"
    )
    bundle = None
    if bundle_id is not None:
        bundle = domain.find_bundle(bundle_id, "ERR_REFERENCED_RESOURCE_NOT_FOUND")

    cycle, title, state = domain.submission_context(submission)

    if expected_submission_version != submission["version"]:
        fail(
            "ERR_STALE_SUBMISSION_VERSION",
            "expected_submission_version does not match the submission's version.",
        )
    if cycle["status"] not in FILEABLE_CYCLE_STATUSES:
        fail(
            "ERR_ADOPTION_CYCLE_STATE_INVALID",
            "The adoption cycle no longer admits price filings.",
        )
    if submission["review_status"] not in FILEABLE_REVIEW_STATUSES:
        fail(
            "ERR_SUBMISSION_STATE_INVALID",
            "Price may only be filed on a FILED, SCHEDULED or PRESENTED submission.",
        )

    if bundle is not None:
        bundle_rank = ACCESSIBILITY_RANK[bundle["accessibility_conformance"]]
        state_rank = ACCESSIBILITY_RANK[state["accessibility_standard"]]
        if bundle_rank == 0 or bundle_rank < state_rank:
            fail(
                "ERR_ACCESSIBILITY_COMMITMENT_MISSING",
                "The bundle does not meet the state's accessibility standard.",
            )
        if state["data_privacy_addendum_required"] and not bundle[
            "privacy_addendum_signed"
        ]:
            fail(
                "ERR_PRIVACY_ADDENDUM_MISSING",
                "This state requires a signed data privacy addendum.",
            )
        if bundle["rostering_standard"] != state["rostering_standard"]:
            fail(
                "ERR_ROSTERING_STANDARD_UNSUPPORTED",
                "The bundle's rostering standard is not the one this state uses.",
            )
        if bundle["title_id"] != submission["title_id"]:
            fail(
                "ERR_BUNDLE_TITLE_MISMATCH",
                "The bundle belongs to a different edition.",
            )

    max_term = min(state["multi_year_max_years"], cycle["contract_term_years"])
    if term_years > max_term:
        fail(
            "ERR_TERM_YEARS_EXCEED_STATE_MAX",
            "term_years may not exceed %d for this state and cycle." % max_term,
        )

    prior = domain.proposals_of_submission(submission_id)
    supersedable = []
    for proposal in prior:
        if proposal["status"] not in ("FILED", "APPROVED"):
            continue
        if proposal["contract_locked"]:
            fail(
                "ERR_CONTRACT_LOCKED",
                "A contract-locked price filing can never be superseded.",
            )
        supersedable.append(proposal)

    priced = calc.state_net_price(
        base_price_cents,
        term_years,
        annual_escalator_bps,
        projected_adoption_units,
        bundle,
    )
    if (
        state["price_cap_cents"] is not None
        and priced["net_state_price_cents"] > state["price_cap_cents"]
    ):
        fail(
            "ERR_PRICE_CAP_EXCEEDED",
            "The computed net state price exceeds this state's cap.",
        )

    for proposal in supersedable:
        apply_changes(proposal, {"status": "SUPERSEDED"})

    record = base_record()
    record.update(
        {
            "submission_id": submission_id,
            "bundle_id": bundle_id,
            "base_price_cents": base_price_cents,
            "term_years": term_years,
            "annual_escalator_bps": annual_escalator_bps,
            "projected_adoption_units": projected_adoption_units,
            "digital_seat_price_cents": digital_seat_price_cents,
            "status": "FILED",
            "contract_locked": False,
            "decision_officer_ref": None,
        }
    )
    record.update(priced)
    db.pricing_proposals[record["id"]] = record

    # An accepted filing always advances the submission's version by exactly 1.
    submission["pricing_status"] = "PRICE_FILED"
    touch(submission)

    return respond(S.serialize(record, S.PRICING_PROPOSAL_FIELDS), 201)


@bp.get("/pricing-proposals/<proposal_id>")
def get_proposal(proposal_id):
    authorize(READ_ROLES)
    record = domain.find_proposal(proposal_id)
    return respond(S.serialize(record, S.PRICING_PROPOSAL_FIELDS))


@bp.get("/pricing-proposals")
def list_proposals():
    authorize(READ_ROLES)
    limit, offset = V.pagination()
    submission_id = V.query_str("submission_id")
    bundle_id = V.query_str("bundle_id")
    status = V.query_enum("status", V.PROPOSAL_STATUSES)
    contract_locked = V.query_bool("contract_locked")

    items = domain.ordered(list(db.pricing_proposals.values()))
    if submission_id is not None:
        items = [i for i in items if i["submission_id"] == submission_id]
    if bundle_id is not None:
        items = [i for i in items if i["bundle_id"] == bundle_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if contract_locked is not None:
        items = [i for i in items if i["contract_locked"] == contract_locked]

    total = len(items)
    page = items[offset:offset + limit]
    return respond_list(
        S.serialize_many(page, S.PRICING_PROPOSAL_FIELDS), total, limit, offset
    )


@bp.post("/pricing-proposals/<proposal_id>/decision")
def decide_proposal(proposal_id):
    user_id, role = authorize(("StateAdoptionOfficer",))
    payload = V.body()

    verdict = V.get_enum(payload, "verdict", DECISION_VERDICTS)
    V.get_str(payload, "reason", min_len=1, max_len=500, required=False, default=None)

    proposal = domain.find_proposal(proposal_id)
    submission = db.submissions[proposal["submission_id"]]
    cycle = db.adoption_cycles[submission["cycle_id"]]
    check_state_scope(role, user_id, cycle["state_id"])

    if proposal["status"] != "FILED":
        fail(
            "ERR_PRICING_PROPOSAL_STATE_INVALID",
            "Only a FILED price proposal may be decided.",
        )

    if verdict == "APPROVE":
        apply_changes(
            proposal, {"status": "APPROVED", "decision_officer_ref": user_id}
        )
        apply_changes(submission, {"pricing_status": "PRICE_APPROVED"})
    else:
        apply_changes(
            proposal, {"status": "REJECTED", "decision_officer_ref": user_id}
        )
        apply_changes(submission, {"pricing_status": "PRICE_REJECTED"})

    return respond(S.serialize(proposal, S.PRICING_PROPOSAL_FIELDS))
