"""Settlement instruments: drafting, lodging, entry and the compliance cycle."""

from flask import Blueprint

import calc
import constants as K
import derive
import logical_clock
import serialize
import shape
import store
import txn
from authz import require
from errors import ApiError
from routes import common

bp = Blueprint("decrees", __name__)


@bp.post("/sites/<site_id>/consent-decrees")
def create_decree(site_id):
    require(K.ROLE_COUNSEL)
    body = shape.get_body()
    scope_type = shape.enum_field(body, "scope_type", K.SCOPE_TYPES)
    scope_summary = shape.str_field(body, "scope_summary")
    party_ids = shape.id_list_field(body, "party_prp_ids", 1, 20)
    cap = shape.money_field(body, "oversight_cost_cap_cents", strictly_positive=True)
    per_day = shape.money_field(
        body, "stipulated_penalty_per_day_cents", strictly_positive=True
    )
    deadline = shape.date_field(body, "performance_deadline")
    site = common.get_site(site_id)
    # Priority 5: every element must be a party named for this very site.
    for prp_id in party_ids:
        prp = common.get_prp(prp_id)
        if prp["site_id"] != site["id"]:
            raise ApiError("ERR_PRP_NOT_FOUND")
    common.deny_deleted(site)

    decree = common.new_record(
        {
            "site_id": site["id"],
            "scope_type": scope_type,
            "scope_summary": scope_summary,
            "party_prp_ids": list(party_ids),
            "oversight_cost_cap_cents": cap,
            "stipulated_penalty_per_day_cents": per_day,
            "performance_deadline": deadline,
            "legal_status": "NEGOTIATING",
            "compliance_status": "COMPLIANT",
            "violation_type": None,
            "first_noncompliance_date": None,
            "days_in_violation": 0,
            "penalty_cap_cents": calc.penalty_cap_cents(cap),
            "accrued_penalty_cents": 0,
            "court_docket_number": None,
            "entered_at": None,
            "lodged_at": None,
            "public_comment_close_at": None,
            "paid_penalty_cents": 0,
            "penalty_capped": False,
            "last_assessment_at": None,
            "open_violation_count": 0,
            "terminated_at": None,
        }
    )
    store.consent_decrees[decree["id"]] = decree
    return common.respond(decree, serialize.consent_decree, 201)


@bp.post("/consent-decrees/<decree_id>/lodging")
def lodge_decree(decree_id):
    require(K.ROLE_COUNSEL)
    shape.get_body()
    decree = common.get_decree(decree_id)
    site = store.sites[decree["site_id"]]
    common.state(decree["legal_status"] == "NEGOTIATING")
    common.deny_deleted(site)
    if not site["adopted_round_id"]:
        raise ApiError("ERR_NO_ADOPTED_ALLOCATION")
    for prp_id in decree["party_prp_ids"]:
        prp = store.prps.get(prp_id)
        if prp is None or prp["status"] != "PARTICIPATING":
            raise ApiError("ERR_PARTY_NOT_PARTICIPATING")

    lodged = logical_clock.now()
    txn.watch(decree)
    decree["legal_status"] = "LODGED"
    decree["lodged_at"] = lodged
    decree["public_comment_close_at"] = logical_clock.plus_days(
        lodged, K.DECREE_COMMENT_DAYS
    )
    return common.respond(decree, serialize.consent_decree)


@bp.post("/consent-decrees/<decree_id>/entry")
def enter_decree(decree_id):
    require(K.ROLE_COUNSEL)
    body = shape.get_body()
    docket = shape.str_field(body, "court_docket_number")
    decree = common.get_decree(decree_id)
    site = store.sites[decree["site_id"]]
    common.state(decree["legal_status"] == "LODGED")
    common.deny_deleted(site)
    # The closing instant itself qualifies.
    if logical_clock.now() < decree["public_comment_close_at"]:
        raise ApiError("ERR_DECREE_COMMENT_PERIOD_OPEN")

    txn.watch(decree)
    decree["legal_status"] = "ENTERED"
    decree["entered_at"] = logical_clock.now()
    decree["court_docket_number"] = docket
    decree["compliance_status"] = "COMPLIANT"
    decree["first_noncompliance_date"] = None
    decree["penalty_cap_cents"] = calc.penalty_cap_cents(
        decree["oversight_cost_cap_cents"]
    )
    # The entered instrument becomes the site's governing oversight cap.
    derive.recompute_site_derived(site)
    return common.respond(decree, serialize.consent_decree)


@bp.post("/consent-decrees/<decree_id>/compliance-events")
def compliance_event(decree_id):
    require(K.ROLE_COUNSEL)
    body = shape.get_body()
    event_type = shape.enum_field(body, "event_type", K.EVENT_TYPES)
    # PRD 3.7: `effective_at` is an ISO 8601 UTC instant like every other `_at`
    # field; `first_noncompliance_date` is stamped *from* it (its date part),
    # while `last_assessment_at` is stamped *with* it.
    effective_at = shape.datetime_field(body, "effective_at")
    effective_day = effective_at.date()
    violation_type = shape.str_field(body, "violation_type", required=False)
    paid = shape.money_field(body, "paid_penalty_cents", required=False, minimum=0)
    decree = common.get_decree(decree_id)
    site = store.sites[decree["site_id"]]
    common.deny_deleted(site)
    # Priority 15 sits ahead of the compliance-dimension transition check.
    if decree["legal_status"] != "ENTERED":
        raise ApiError("ERR_DECREE_NOT_ENTERED")

    status = decree["compliance_status"]
    if event_type == "VIOLATION":
        common.state(status == "COMPLIANT")
        txn.watch(decree)
        decree["compliance_status"] = "IN_VIOLATION"
        decree["first_noncompliance_date"] = effective_day
        decree["violation_type"] = violation_type
        decree["open_violation_count"] += 1
    elif event_type == "PENALTY_ASSESSMENT":
        if status == "IN_VIOLATION":
            common.state(effective_day >= decree["first_noncompliance_date"])
        elif status == "PENALTY_ACCRUING":
            common.state(
                decree["last_assessment_at"] is None
                or effective_at > decree["last_assessment_at"]
            )
        else:
            common.state(False)
        days, accrued, capped = calc.penalty_accrual(
            decree["first_noncompliance_date"],
            effective_day,
            decree["stipulated_penalty_per_day_cents"],
            decree["penalty_cap_cents"],
        )
        txn.watch(decree)
        # Recomputed from first_noncompliance_date, never added to the previous
        # figure, so repeated assessment is idempotent in aggregate.
        decree["days_in_violation"] = days
        decree["accrued_penalty_cents"] = accrued
        decree["penalty_capped"] = capped
        decree["last_assessment_at"] = effective_at
        decree["compliance_status"] = "PENALTY_ACCRUING"
    else:
        common.state(status in ("IN_VIOLATION", "PENALTY_ACCRUING"))
        outstanding = decree["accrued_penalty_cents"] - decree["paid_penalty_cents"]
        if (paid or 0) != outstanding:
            raise ApiError("ERR_PENALTY_BALANCE_MISMATCH")
        txn.watch(decree)
        decree["paid_penalty_cents"] = decree["accrued_penalty_cents"]
        decree["compliance_status"] = "COMPLIANT"
        decree["first_noncompliance_date"] = None
        decree["last_assessment_at"] = None
        decree["days_in_violation"] = 0
        decree["open_violation_count"] = max(0, decree["open_violation_count"] - 1)

    derive.recompute_site_derived(site)
    return common.respond(decree, serialize.consent_decree)
