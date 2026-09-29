"""Agency registration, financial review and the appointment decision (PRD 3.1)."""

from flask import Blueprint

import calc
import db
import derive
import lookup
import middleware as mw
import response
import shape
import tx
from db import store
from errors import ApiError

bp = Blueprint("agencies", __name__)

APPOINTMENT_TRANSITIONS = {
    "PENDING_REVIEW": ("APPOINTED",),
    "APPOINTED": ("SUSPENDED", "TERMINATED"),
    "SUSPENDED": ("APPOINTED", "TERMINATED"),
}
APPOINTMENT_TERMINALS = ("TERMINATED",)

DECISION_TARGET = {
    "APPOINT": "APPOINTED",
    "SUSPEND": "SUSPENDED",
    "REINSTATE": "APPOINTED",
    "TERMINATE": "TERMINATED",
}
DECISION_ORIGIN = {
    "APPOINT": ("PENDING_REVIEW",),
    "SUSPEND": ("APPOINTED",),
    "REINSTATE": ("SUSPENDED",),
    "TERMINATE": ("APPOINTED", "SUSPENDED"),
}
TERMINATION_REASONS = ("FOR_CAUSE", "VOLUNTARY", "NON_RENEWAL")


def new_agency_fields(legal_name, tax_id, authority_limit):
    return {
        "legal_name": legal_name,
        "tax_id": tax_id,
        "underwriting_authority_limit_cents": authority_limit,
        "appointment_status": "PENDING_REVIEW",
        "financial_review_status": "NOT_SUBMITTED",
        "submitted_eo_policy_limit_cents": 0,
        "submitted_eo_expires_on": None,
        "submitted_net_worth_cents": 0,
        "submitted_fidelity_bond_cents": 0,
        "eo_policy_limit_cents": 0,
        "eo_expires_on": None,
        "net_worth_cents": 0,
        "fidelity_bond_cents": 0,
        "escrow_standing": "COMPLIANT",
        "defalcation_score": 0,
        "oversight_posture": "RESTRICTED",
        "open_critical_finding_count": 0,
        "unreported_policy_count": 0,
        "cpl_outstanding_exposure_cents": 0,
        "unremitted_premium_cents": 0,
        "last_remittance_period_end": None,
        "termination_reason": None,
        "transferee_agency_id": None,
        "pending_transfer_count": 0,
    }


@bp.post("/agencies")
def create_agency():
    mw.require_roles(mw.COMPLIANCE_OFFICER, mw.LICENSING_ANALYST)
    payload = shape.body()
    legal_name = shape.req_str(payload, "legal_name")
    tax_id = shape.req_str(payload, "tax_id")
    authority_limit = shape.req_cents(payload, "underwriting_authority_limit_cents")

    for existing in store.all(db.AGENCY):
        if existing["tax_id"] == tax_id:
            raise ApiError("ERR_DUPLICATE_TAX_ID")

    agency = db.new_row(db.AGENCY, new_agency_fields(legal_name, tax_id, authority_limit))
    derive.recompute_agency(agency)
    return response.created(agency)


@bp.get("/agencies/<agency_id>")
def read_agency(agency_id):
    mw.require_roles(*mw.ALL_ROLES)
    return response.ok(lookup.agency(agency_id))


@bp.get("/agencies")
def list_agencies():
    mw.require_roles(*mw.ALL_ROLES)
    limit, offset = shape.pagination()
    filters = {
        "appointment_status": shape.query_value("appointment_status"),
        "financial_review_status": shape.query_value("financial_review_status"),
        "oversight_posture": shape.query_value("oversight_posture"),
        "escrow_standing": shape.query_value("escrow_standing"),
        "transferee_agency_id": shape.query_value("transferee_agency_id"),
    }
    rows = []
    for row in store.all(db.AGENCY):
        if all(v is None or row.get(k) == v for k, v in filters.items()):
            rows.append(row)
    return response.ok_list(shape.page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/agencies/<agency_id>/financial-review")
def submit_financial_review(agency_id):
    user_id, role = mw.require_roles(mw.AGENCY_PRINCIPAL)
    payload = shape.body()
    eo_limit = shape.req_cents(payload, "submitted_eo_policy_limit_cents")
    eo_expires = shape.req_date(payload, "submitted_eo_expires_on")
    net_worth = shape.req_cents(payload, "submitted_net_worth_cents")
    fidelity_bond = shape.req_cents(payload, "submitted_fidelity_bond_cents")

    agency = lookup.agency(agency_id)
    mw.require_ownership(user_id, role, agency["id"])

    # Tier 10 - a terminated agency may not submit at all.
    if agency["appointment_status"] == "TERMINATED":
        raise ApiError("ERR_INVALID_STATE")

    agency["submitted_eo_policy_limit_cents"] = eo_limit
    agency["submitted_eo_expires_on"] = db.date_str(eo_expires)
    agency["submitted_net_worth_cents"] = net_worth
    agency["submitted_fidelity_bond_cents"] = fidelity_bond
    agency["financial_review_status"] = "SUBMITTED"
    derive.recompute_agency(agency)
    tx.force_agency_version_bump(agency)
    return response.ok(agency)


@bp.post("/agencies/<agency_id>/financial-review-decision")
def decide_financial_review(agency_id):
    mw.require_roles(mw.LICENSING_ANALYST)
    payload = shape.body()
    decision = shape.req_enum(payload, "decision", ("ACCEPT", "DEFICIENT"))
    shape.opt_str(payload, "note")

    agency = lookup.agency(agency_id)

    # Tier 10
    if agency["financial_review_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")

    if decision == "ACCEPT":
        # Tier 11 - both minimums read the staged values.
        if agency["submitted_eo_policy_limit_cents"] < calc.MIN_EO_LIMIT_CENTS:
            raise ApiError("ERR_EO_LIMIT_BELOW_MINIMUM")
        if agency["submitted_net_worth_cents"] < calc.MIN_NET_WORTH_CENTS:
            raise ApiError("ERR_NET_WORTH_BELOW_MINIMUM")
        agency["financial_review_status"] = "ACCEPTED"
        agency["eo_policy_limit_cents"] = agency["submitted_eo_policy_limit_cents"]
        agency["eo_expires_on"] = agency["submitted_eo_expires_on"]
        agency["net_worth_cents"] = agency["submitted_net_worth_cents"]
        agency["fidelity_bond_cents"] = agency["submitted_fidelity_bond_cents"]
    else:
        agency["financial_review_status"] = "DEFICIENT"

    derive.recompute_agency(agency)
    tx.force_agency_version_bump(agency)
    return response.ok(agency)


@bp.post("/agencies/<agency_id>/appointment-decision")
def appointment_decision(agency_id):
    user_id, role = mw.require_roles(mw.LICENSING_ANALYST, mw.COMPLIANCE_OFFICER)
    payload = shape.body()
    decision = shape.req_enum(
        payload, "decision", ("APPOINT", "SUSPEND", "REINSTATE", "TERMINATE")
    )
    shape.opt_str(payload, "reason")
    termination_reason = None
    if decision == "TERMINATE":
        if "termination_reason" not in payload or payload["termination_reason"] is None:
            raise ApiError("ERR_TERMINATION_REASON_REQUIRED")
        termination_reason = shape.req_enum(
            payload, "termination_reason", TERMINATION_REASONS
        )
    transferee_id = shape.opt_id(payload, "transferee_agency_id")

    # Tier 4
    agency = lookup.agency(agency_id)
    # Tier 5 - body reference resolution
    transferee = None
    if transferee_id is not None:
        transferee = lookup.agency(transferee_id)

    # Tier 7
    if decision == "TERMINATE":
        mw.require_transition_role(role, (mw.COMPLIANCE_OFFICER,))
    else:
        mw.require_transition_role(role, (mw.LICENSING_ANALYST,))

    # Tier 10
    current = agency["appointment_status"]
    if current in APPOINTMENT_TERMINALS:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if current not in DECISION_ORIGIN[decision]:
        raise ApiError("ERR_INVALID_STATE")
    if decision == "REINSTATE":
        if (
            agency["escrow_standing"] == "DEFALCATION_RISK"
            or agency["open_critical_finding_count"] != 0
        ):
            raise ApiError("ERR_REINSTATEMENT_BLOCKED_BY_ESCROW_STANDING")

    if decision == "APPOINT":
        # Tier 11
        if agency["financial_review_status"] != "ACCEPTED":
            raise ApiError("ERR_FINANCIAL_REVIEW_NOT_ACCEPTED")
        # Tier 12
        has_active = any(
            appt["status"] == "ACTIVE"
            for appt in store.where(db.APPOINTMENT, agency_id=agency["id"])
        )
        if not has_active:
            raise ApiError("ERR_NO_ACTIVE_APPOINTMENT_IN_STATE")

    if decision == "TERMINATE" and transferee is not None:
        # Tier 12
        if not derive.transferee_eligible(transferee, agency["id"]):
            raise ApiError("ERR_TRANSFEREE_NOT_ELIGIBLE")

    if decision == "APPOINT":
        agency["appointment_status"] = "APPOINTED"
        derive.recompute_agency(agency)
    elif decision == "SUSPEND":
        agency["appointment_status"] = "SUSPENDED"
        previous = derive.recompute_agency(agency)
        derive.apply_freeze_to_accounts(agency, previous)
    elif decision == "REINSTATE":
        agency["appointment_status"] = "APPOINTED"
        previous = derive.recompute_agency(agency)
        if previous == "FROZEN" and agency["oversight_posture"] != "FROZEN":
            derive.release_restricted_accounts(agency)
    else:
        derive.cascade_b(agency, termination_reason, transferee_id)

    tx.force_agency_version_bump(agency)
    return response.ok(agency)
