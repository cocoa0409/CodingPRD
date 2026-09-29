"""State profiles (PRD 2.7) and the logical clock (PRD 2.4)."""
from flask import Blueprint

import clock
import response
import validate
from auth import ALL_ROLES, endpoint
from dates import fmt
from db import db, public, stamp_new
from errors import ApiError
from validate import CANONICAL_CLAUSE_ORDER

bp = Blueprint("config", __name__)

RENEWAL_DUE_RULES = ("FYE_PLUS_4M_15D", "FYE_PLUS_6M", "CALENDAR_MAY_15")
ASSURANCE_BASES = ("CONTRIBUTIONS_ONLY", "GROSS_REVENUE")


@bp.post("/state-profiles")
@endpoint(["SystemAdmin"])
def create_state_profile():
    """Only six fields are required; every other field falls back to its default."""
    body = validate.json_body()

    state_code = validate.req_state_code(body, "state_code")
    registration_required = validate.req_bool(body, "registration_required")
    renewal_due_rule = validate.req_enum(body, "renewal_due_rule", RENEWAL_DUE_RULES)
    assurance_basis = validate.req_enum(body, "assurance_basis", ASSURANCE_BASES)
    review_threshold_cents = validate.req_int(body, "review_threshold_cents", minimum=0)
    audit_threshold_cents = validate.req_int(body, "audit_threshold_cents", minimum=0)
    if audit_threshold_cents < review_threshold_cents:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "audit_threshold_cents may not be lower than review_threshold_cents.",
        )

    profile = {
        "state_code": state_code,
        "registration_required": registration_required,
        "renewal_due_rule": renewal_due_rule,
        "assurance_basis": assurance_basis,
        "review_threshold_cents": review_threshold_cents,
        "audit_threshold_cents": audit_threshold_cents,
        "donor_count_trigger": validate.opt_int(body, "donor_count_trigger", 25, minimum=0),
        "contribution_trigger_cents": validate.opt_int(
            body, "contribution_trigger_cents", 2500000, minimum=0),
        "online_presence_counts": validate.opt_bool(body, "online_presence_counts", False),
        "extension_allowed": validate.opt_bool(body, "extension_allowed", False),
        "extension_max_days": validate.opt_int(body, "extension_max_days", 0, minimum=0),
        "disclosure_required_clauses": validate.opt_array(
            body, "disclosure_required_clauses", allowed=CANONICAL_CLAUSE_ORDER, default=[]),
        "fundraiser_contract_filing_days": validate.opt_int(
            body, "fundraiser_contract_filing_days", 10, minimum=0),
        "fundraiser_bond_minimum_cents": validate.opt_int(
            body, "fundraiser_bond_minimum_cents", 0, minimum=0),
        "coventure_filing_required": validate.opt_bool(body, "coventure_filing_required", False),
        "coventure_buffer_days": validate.opt_int(body, "coventure_buffer_days", 0, minimum=0),
        "base_filing_fee_cents": validate.opt_int(body, "base_filing_fee_cents", 2500, minimum=0),
        "online_surcharge_cents": validate.opt_int(body, "online_surcharge_cents", 0, minimum=0),
        "per_contract_fee_cents": validate.opt_int(body, "per_contract_fee_cents", 0, minimum=0),
        "filing_fee_cap_cents": validate.opt_int(body, "filing_fee_cap_cents", 30000, minimum=0),
        "late_fee_base_cents": validate.opt_int(body, "late_fee_base_cents", 2000, minimum=0),
        "late_fee_escalation_pct": validate.opt_number(
            body, "late_fee_escalation_pct", 0.1, minimum=0),
        "late_fee_cap_cents": validate.opt_int(body, "late_fee_cap_cents", 50000, minimum=0),
        "cure_period_days": validate.opt_int(body, "cure_period_days", 30, minimum=0),
        "reinstatement_fee_cents": validate.opt_int(
            body, "reinstatement_fee_cents", 12500, minimum=0),
    }

    # Ladder rung 28 -- state_code unused by another profile.
    if state_code in db.state_profiles:
        raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                       "A state profile already exists for %s." % state_code)

    # Ordered so that the canonical clause order is preserved on the way out.
    profile["disclosure_required_clauses"] = [
        c for c in CANONICAL_CLAUSE_ORDER if c in set(profile["disclosure_required_clauses"])
    ]

    stamp_new(profile)
    db.state_profiles[state_code] = profile
    return response.created(public(profile))


@bp.get("/state-profiles/<state_code>")
@endpoint(ALL_ROLES)
def read_state_profile(state_code):
    return response.ok(public(validate.find_state_profile(state_code)))


@bp.post("/_clock/set_current_utc")
@endpoint(["SystemAdmin"])
def set_clock():
    """Move the logical clock and echo the new instant as current_utc."""
    body = validate.json_body()
    instant = validate.req_datetime(body, "to_iso8601")
    clock.set_now(instant)
    return response.ok({"current_utc": fmt(clock.now())})
