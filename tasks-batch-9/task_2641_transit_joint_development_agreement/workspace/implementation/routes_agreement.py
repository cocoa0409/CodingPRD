"""Joint development agreements: drafting, revision, review, board and execution."""

from flask import Blueprint, g

import authz
import calc
import common
import enums
import envelope
import shape
import store
from errors import fail

bp = Blueprint("agreement", __name__)


def _governing_solicitation(proposal):
    return store.get("solicitation", proposal["solicitation_id"])


def _require_live_period(agreement):
    """The period holding this agreement's proposal must be ACTIVE or EXTENDED with
    the logical clock's date on or before its end_date."""
    period = common.period_holding(agreement["proposal_id"])
    if period is None:
        fail("ERR_NEGOTIATION_PERIOD_EXPIRED",
             "No live exclusive negotiation period holds this agreement's proposal")
    end = store.parse_date(period["end_date"])
    if end is None or store.today() > end:
        fail("ERR_NEGOTIATION_PERIOD_EXPIRED",
             "The exclusive negotiation period has lapsed")
    return period


@bp.post("/jda/agreements")
def draft_agreement():
    authz.authorize("RealEstateOfficer")
    body = shape.body()
    site_id = shape.as_str(body, "site_id")
    developer_id = shape.as_str(body, "developer_id")
    proposal_id = shape.as_str(body, "proposal_id")
    valuation_id = shape.as_str(body, "valuation_id")
    structure = shape.as_enum(body, "structure", enums.PROPOSED_STRUCTURE)
    term_years = shape.as_int(body, "term_years", minimum=1)
    base_rent = shape.as_int(body, "base_rent_cents", required=False, default=0, minimum=0)
    purchase_price = shape.as_int(body, "purchase_price_cents", required=False,
                                 default=0, minimum=0)
    revenue_share_pct = shape.as_num(body, "revenue_share_pct", minimum=0, maximum=1)
    projected_gross = shape.as_int(body, "projected_gross_revenue_cents", minimum=0)
    affordable_committed = shape.as_int(body, "affordable_units_committed", minimum=0)
    total_units = shape.as_int(body, "total_units", minimum=1)
    site_area_share_pct = shape.as_num(body, "site_area_share_pct", exclusive_min=0, maximum=100)
    joint_use_committed = shape.as_bool(body, "joint_use_committed", required=False, default=False)
    if structure == "GROUND_LEASE" and base_rent < 1:
        fail("ERR_INVALID_REQUEST",
             "base_rent_cents must be at least 1 for a GROUND_LEASE agreement")
    if structure == "FEE_DISPOSITION" and purchase_price < 1:
        fail("ERR_INVALID_REQUEST",
             "purchase_price_cents must be at least 1 for a FEE_DISPOSITION agreement")
    # Body foreign keys resolve in declaration order.
    site = store.require("site", site_id)
    developer = store.require("developer", developer_id)
    proposal = store.require("proposal", proposal_id)
    valuation = store.require("valuation", valuation_id)
    if site["status"] != "UNDER_AGREEMENT":
        fail("ERR_SITE_NOT_UNDER_AGREEMENT", "Site is not UNDER_AGREEMENT")
    if developer["debarment_status"] != "CLEAR":
        fail("ERR_DEVELOPER_DEBARRED", "Developer is %s" % developer["debarment_status"])
    solicitation = _governing_solicitation(proposal)
    committed_pct = calc.affordable_pct(affordable_committed, total_units)
    if solicitation is not None:
        if calc.dec(committed_pct) < calc.dec(solicitation["affordable_housing_min_pct"]):
            fail("ERR_AFFORDABLE_MINIMUM_NOT_MET",
                 "Committed affordable share %s is below the solicitation minimum %s"
                 % (committed_pct, solicitation["affordable_housing_min_pct"]))
        if solicitation["joint_use_required"] and not joint_use_committed:
            fail("ERR_JOINT_USE_NOT_COMMITTED",
                 "The governing solicitation requires a joint-use commitment")
    if valuation["site_id"] != site_id or (solicitation is not None
                                           and solicitation["site_id"] != site_id):
        fail("ERR_VALUATION_SITE_MISMATCH",
             "The valuation or the proposal does not belong to this site")
    period = common.period_holding(proposal_id)
    period_end = store.parse_date(period["end_date"]) if period is not None else None
    if period is None or period_end is None or store.today() > period_end:
        fail("ERR_NEGOTIATION_PERIOD_EXPIRED",
             "No live exclusive negotiation period holds the referenced proposal")
    agreement = store.create("agreement", {
        "site_id": site_id,
        "developer_id": developer_id,
        "proposal_id": proposal_id,
        "valuation_id": valuation_id,
        "structure": structure,
        "term_years": term_years,
        "base_rent_cents": base_rent,
        "purchase_price_cents": purchase_price,
        "revenue_share_pct": revenue_share_pct,
        "projected_gross_revenue_cents": projected_gross,
        "affordable_units_committed": affordable_committed,
        "total_units": total_units,
        "site_area_share_pct": site_area_share_pct,
        "joint_use_committed": joint_use_committed,
        "capital_credit_cents": 0,
        "annual_revenue_to_agency_cents": 0,
        "consideration_value_cents": 0,
        "negotiation_status": "DRAFTING",
        "federal_approval_status": ("NOT_REQUIRED"
                                   if calc.dec(site["federal_interest_pct"]) == calc.D("0")
                                   else "NOT_SUBMITTED"),
        "submitted_by_user_id": None,
        "board_resolution_number": None,
        "execution_date": None,
        "revision_notes": None,
    })
    calc.apply_agreement_money(agreement)
    return envelope.created(common.public(agreement))


@bp.patch("/jda/agreements/<agreement_id>")
def revise_agreement(agreement_id):
    authz.authorize("RealEstateOfficer")
    body = shape.body()
    term_years = shape.as_int(body, "term_years", required=False, default=None, minimum=1)
    base_rent = shape.as_int(body, "base_rent_cents", required=False, default=None, minimum=0)
    purchase_price = shape.as_int(body, "purchase_price_cents", required=False,
                                 default=None, minimum=0)
    revenue_share_pct = shape.as_num(body, "revenue_share_pct", required=False,
                                     default=None, minimum=0, maximum=1)
    projected_gross = shape.as_int(body, "projected_gross_revenue_cents", required=False,
                                   default=None, minimum=0)
    affordable_committed = shape.as_int(body, "affordable_units_committed", required=False,
                                        default=None, minimum=0)
    site_area_share_pct = shape.as_num(body, "site_area_share_pct", required=False,
                                       default=None, exclusive_min=0, maximum=100)
    agreement = store.require("agreement", agreement_id)
    effective_base = base_rent if base_rent is not None else agreement["base_rent_cents"]
    effective_price = (purchase_price if purchase_price is not None
                       else agreement["purchase_price_cents"])
    if agreement["structure"] == "GROUND_LEASE" and effective_base < 1:
        fail("ERR_INVALID_REQUEST",
             "base_rent_cents must be at least 1 for a GROUND_LEASE agreement")
    if agreement["structure"] == "FEE_DISPOSITION" and effective_price < 1:
        fail("ERR_INVALID_REQUEST",
             "purchase_price_cents must be at least 1 for a FEE_DISPOSITION agreement")
    if agreement["negotiation_status"] not in ("DRAFTING", "REVISION_REQUESTED"):
        fail("ERR_AGREEMENT_NOT_DRAFTING",
             "Agreement is neither DRAFTING nor REVISION_REQUESTED")
    if term_years is not None:
        agreement["term_years"] = term_years
    if base_rent is not None:
        agreement["base_rent_cents"] = base_rent
    if purchase_price is not None:
        agreement["purchase_price_cents"] = purchase_price
    if revenue_share_pct is not None:
        agreement["revenue_share_pct"] = revenue_share_pct
    if projected_gross is not None:
        agreement["projected_gross_revenue_cents"] = projected_gross
    if affordable_committed is not None:
        agreement["affordable_units_committed"] = affordable_committed
    if site_area_share_pct is not None:
        agreement["site_area_share_pct"] = site_area_share_pct
    calc.apply_agreement_money(agreement)
    # Any amendment clears the segregation-of-duties comparand.
    agreement["submitted_by_user_id"] = None
    if agreement["negotiation_status"] == "REVISION_REQUESTED":
        agreement["negotiation_status"] = "DRAFTING"
    if agreement["federal_approval_status"] == "FTA_REJECTED":
        agreement["federal_approval_status"] = "NOT_SUBMITTED"
    store.touch(agreement)
    return envelope.ok(common.public(agreement))


@bp.post("/jda/agreements/<agreement_id>/submit-for-review")
def submit_for_review(agreement_id):
    user_id, _role = authz.authorize("RealEstateOfficer")
    agreement = store.require("agreement", agreement_id)
    # Recompute the money fields before the fiscal tests run.
    calc.apply_agreement_money(agreement)
    if agreement["negotiation_status"] != "DRAFTING":
        fail("ERR_AGREEMENT_NOT_DRAFTING", "Agreement is not in DRAFTING")
    valuation = store.get("valuation", agreement["valuation_id"])
    if valuation is None or valuation["status"] != "CERTIFIED":
        fail("ERR_VALUATION_NOT_CERTIFIED", "The referenced valuation is not CERTIFIED")
    _require_live_period(agreement)
    proposal = store.get("proposal", agreement["proposal_id"])
    if proposal is not None and agreement["affordable_units_committed"] < proposal["affordable_units"]:
        fail("ERR_AFFORDABLE_COMMITMENT_SHORTFALL",
             "The agreement commits fewer affordable units than the proposal offered")
    if agreement["consideration_value_cents"] < valuation["permissible_floor_cents"]:
        fail("ERR_BELOW_PERMISSIBLE_FLOOR",
             "consideration_value_cents %d is below the permissible floor %d"
             % (agreement["consideration_value_cents"], valuation["permissible_floor_cents"]))
    agreement["negotiation_status"] = "AGENCY_REVIEW"
    agreement["submitted_by_user_id"] = user_id
    agreement["revision_notes"] = None
    store.touch(agreement)
    return envelope.ok(common.public(agreement))


@bp.post("/jda/agreements/<agreement_id>/request-revision")
def request_revision(agreement_id):
    authz.authorize("BoardSecretary")
    body = shape.body()
    revision_notes = shape.as_str(body, "revision_notes")
    agreement = store.require("agreement", agreement_id)
    if agreement["negotiation_status"] != "AGENCY_REVIEW":
        fail("ERR_AGREEMENT_NOT_IN_REVIEW", "Agreement is not in AGENCY_REVIEW")
    agreement["negotiation_status"] = "REVISION_REQUESTED"
    agreement["revision_notes"] = revision_notes
    store.touch(agreement)
    return envelope.ok(common.public(agreement))


@bp.post("/jda/agreements/<agreement_id>/board-approve")
def board_approve(agreement_id):
    user_id, _role = authz.authorize("BoardSecretary")
    body = shape.body()
    resolution_number = shape.as_str(body, "resolution_number")
    agreement = store.require("agreement", agreement_id)
    # Segregation of duties runs before any lifecycle-state consideration.
    if agreement["submitted_by_user_id"] is not None and agreement["submitted_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "Operator %s submitted this agreement and may not also board-approve it" % user_id)
    if agreement["negotiation_status"] != "AGENCY_REVIEW":
        fail("ERR_AGREEMENT_NOT_IN_REVIEW", "Agreement is not in AGENCY_REVIEW")
    agreement["negotiation_status"] = "BOARD_APPROVED"
    agreement["board_resolution_number"] = resolution_number
    store.touch(agreement)
    return envelope.ok(common.public(agreement))


@bp.post("/jda/agreements/<agreement_id>/execute")
def execute_agreement(agreement_id):
    authz.authorize("RealEstateOfficer")
    body = shape.body()
    execution_date = shape.as_str(body, "execution_date", non_empty=True)
    agreement = store.require("agreement", agreement_id)
    if agreement["negotiation_status"] != "BOARD_APPROVED":
        fail("ERR_AGREEMENT_NOT_BOARD_APPROVED", "Agreement is not BOARD_APPROVED")
    if agreement["federal_approval_status"] not in ("NOT_REQUIRED", "FTA_APPROVED"):
        fail("ERR_FEDERAL_APPROVAL_PENDING",
             "Federal approval is %s" % agreement["federal_approval_status"])
    site = store.get("site", agreement["site_id"])
    replacements = common.replacements_of(agreement_id)
    if site is not None and site["transit_facility_present"]:
        if not any(r["status"] in ("INTERIM_IN_PLACE", "COMPLETE") for r in replacements):
            fail("ERR_FACILITY_REPLACEMENT_INCOMPLETE",
                 "No transit facility replacement has reached INTERIM_IN_PLACE or COMPLETE")
    if any(r["status"] == "DEFICIENT" for r in replacements):
        fail("ERR_FACILITY_REPLACEMENT_DEFICIENT",
             "A transit facility replacement of this agreement is DEFICIENT")
    agreement["negotiation_status"] = "EXECUTED"
    agreement["execution_date"] = execution_date
    store.touch(agreement)
    period = common.period_holding(agreement["proposal_id"])
    if period is not None:
        period["status"] = "CONVERTED"
        store.touch(period)
    if agreement["structure"] == "FEE_DISPOSITION" and site is not None:
        site["status"] = "CONVEYED"
        store.touch(site)
    return envelope.ok(common.public(agreement))
