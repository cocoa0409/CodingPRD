"""Loan applications: underwriting, referral and the committee fork
(PRD sections 3.5 and 3.6)."""

from flask import Blueprint, request

import auth
import calc
import envelope
import resolve
import serializers
import shapes
import store
from auth import (COMMITTEE_MEMBER, CREDIT_ANALYST, INSTITUTION_REP,
                  PLATFORM_ADMIN, READ_ALL)
from errors import ApiError
from routes.collateral import release_occupation

bp = Blueprint("applications", __name__)

PURPOSES = ("SANCTUARY_CONSTRUCTION", "SCHOOL_CONSTRUCTION", "REFINANCE",
            "PLEDGE_ADVANCE")
TERMS = (120, 180, 240)
DECISIONS = ("APPROVE", "DECLINE", "REQUEST_REVISION")
SUMMARY_ROLES = (PLATFORM_ADMIN, CREDIT_ANALYST, COMMITTEE_MEMBER,
                 INSTITUTION_REP)


@bp.route("/loan-applications", methods=["POST"])
def create_application():
    ctx = auth.authenticate((CREDIT_ANALYST, INSTITUTION_REP))
    b = shapes.body()
    auth.scope(ctx, b.get("institution_id"))
    institution = resolve.institution(b.get("institution_id"))
    if institution is None:
        shapes.req_id_field(b, "institution_id")
    packet = resolve.governance_authorization(b.get("governance_authorization_id"))
    if packet is None:
        shapes.req_id_field(b, "governance_authorization_id")
    campaign = None
    if b.get("pledge_campaign_id") is not None:
        campaign = resolve.pledge_campaign(b.get("pledge_campaign_id"))
        if campaign is None:
            shapes.opt_id_field(b, "pledge_campaign_id")

    purpose = shapes.req_enum(b, "purpose", PURPOSES)
    amount = shapes.req_int(b, "requested_amount_cents", exclusive_minimum=0)
    term = shapes.req_int(b, "term_months")
    if term not in TERMS:
        shapes.bad("term_months", "must be one of 120, 180, 240")
    rate = shapes.req_int(b, "interest_rate_bps", exclusive_minimum=0)

    # ladder 39
    if packet["institution_id"] != institution["id"]:
        raise ApiError("ERR_INSTITUTION_MISMATCH")
    if campaign is not None and campaign["institution_id"] != institution["id"]:
        raise ApiError("ERR_INSTITUTION_MISMATCH")

    row = store.base_record()
    row.update({
        "institution_id": institution["id"],
        "governance_authorization_id": packet["id"],
        "pledge_campaign_id": campaign["id"] if campaign else None,
        "purpose": purpose,
        "requested_amount_cents": amount,
        "term_months": term,
        "interest_rate_bps": rate,
        "status": "DRAFT",
        "giving_basis": None,
        "giving_base_cents": None,
        "net_available_dollars": None,
        "collateral_lending_value_cents": None,
        "max_supportable_principal_cents": None,
        "prepared_by_user_id": None,
        "decided_by_user_id": None,
        "revision_reason": None,
        "revision_count": 0,
    })
    store.loan_applications[row["id"]] = row
    store.mark_created(row)
    return envelope.created(serializers.loan_application(row))


@bp.route("/loan-applications/<loan_application_id>", methods=["GET"])
def get_application(loan_application_id):
    ctx = auth.authenticate(READ_ALL)
    row = resolve.loan_application(loan_application_id)
    auth.scope(ctx, auth.owner_of_application(row))
    return envelope.ok(serializers.loan_application(row))


@bp.route("/loan-applications", methods=["GET"])
def list_applications():
    auth.authenticate(READ_ALL)
    rows = envelope.filter_rows(
        list(store.loan_applications.values()),
        {"institution_id": "institution_id",
         "governance_authorization_id": "governance_authorization_id",
         "pledge_campaign_id": "pledge_campaign_id",
         "status": "status",
         "purpose": "purpose"})
    return envelope.listing(envelope.sort_created_desc(rows),
                            serializers.loan_application)


@bp.route("/loan-applications/<loan_application_id>/submit-underwriting",
          methods=["POST"])
def submit_underwriting(loan_application_id):
    ctx = auth.authenticate((CREDIT_ANALYST,))
    row = resolve.loan_application(loan_application_id)
    b = shapes.body()
    shapes.opt_str(b, "analyst_note")
    if row["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_APPLICATION_INVALID_STATE")
    institution = store.institutions[row["institution_id"]]
    # ladder 29
    if row["requested_amount_cents"] > institution["bylaws_borrowing_cap_cents"]:
        raise ApiError("ERR_BYLAWS_CAP_EXCEEDED")
    # ladder 42
    total, _audited = calc.period_counts(institution["id"])
    if total < calc.MIN_GIVING_PERIODS:
        raise ApiError("ERR_INSUFFICIENT_GIVING_HISTORY")
    # ladder 46
    if row["purpose"] == "PLEDGE_ADVANCE" and not row.get("pledge_campaign_id"):
        raise ApiError("ERR_PLEDGE_CAMPAIGN_REQUIRED")

    basis = calc.mandated_basis(institution["id"])
    as_of = store.clock_now()
    row["giving_basis"] = basis
    row["giving_base_cents"] = calc.giving_base_cents(institution["id"], as_of,
                                                      basis)
    row["net_available_dollars"] = calc.net_available_dollars(
        institution["id"], as_of, basis)
    row["prepared_by_user_id"] = ctx.user_id
    row["revision_reason"] = None
    row["status"] = "UNDERWRITING"
    store.touch(row)
    return envelope.ok(serializers.loan_application(row))


@bp.route("/loan-applications/<loan_application_id>/committee-referral",
          methods=["POST"])
def committee_referral(loan_application_id):
    auth.authenticate((CREDIT_ANALYST,))
    row = resolve.loan_application(loan_application_id)
    b = shapes.body()
    shapes.opt_str(b, "referral_note")
    if row["status"] != "UNDERWRITING":
        raise ApiError("ERR_APPLICATION_INVALID_STATE")
    packet = store.governance_authorizations[row["governance_authorization_id"]]
    # ladder 30
    if packet["status"] != "AUTHORIZED":
        raise ApiError("ERR_GOVERNANCE_NOT_AUTHORIZED")
    # ladder 31
    if packet["_expires_on_dt"] < store.clock_now():
        raise ApiError("ERR_GOVERNANCE_AUTHORIZATION_EXPIRED")
    # ladder 38
    first_lien = [a for a in calc.assigned_assets(row["id"])
                  if a.get("lien_position") == 1]
    if not first_lien:
        raise ApiError("ERR_COLLATERAL_LINK_BROKEN")
    # ladder 47
    maximum, _binding = calc.max_supportable(row, row.get("net_available_dollars"))
    if row["requested_amount_cents"] > maximum:
        raise ApiError("ERR_LTV_COVERAGE_INSUFFICIENT")

    row["collateral_lending_value_cents"] = calc.first_lien_value_cents(row["id"])
    row["max_supportable_principal_cents"] = maximum
    row["status"] = "COMMITTEE_REVIEW"
    store.touch(row)
    return envelope.ok(serializers.loan_application(row))


@bp.route("/loan-applications/<loan_application_id>/committee-decision",
          methods=["POST"])
def committee_decision(loan_application_id):
    ctx = auth.authenticate((COMMITTEE_MEMBER,))
    row = resolve.loan_application(loan_application_id)
    b = shapes.body()
    decision = shapes.req_enum(b, "decision", DECISIONS)
    note = shapes.opt_str(b, "note")
    if row["status"] != "COMMITTEE_REVIEW":
        raise ApiError("ERR_APPLICATION_INVALID_STATE")
    packet = store.governance_authorizations[row["governance_authorization_id"]]
    # ladder 31
    if packet["_expires_on_dt"] < store.clock_now():
        raise ApiError("ERR_GOVERNANCE_AUTHORIZATION_EXPIRED")
    # ladder 33
    if row.get("prepared_by_user_id") is not None and \
            ctx.user_id == row["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if decision == "APPROVE":
        # ladder 48 — the resolution binds every application in aggregate
        aggregate = row["requested_amount_cents"]
        for other in store.loan_applications.values():
            if other["id"] == row["id"]:
                continue
            if other.get("governance_authorization_id") != packet["id"]:
                continue
            if other.get("status") in ("APPROVED", "FUNDED"):
                aggregate += other["requested_amount_cents"]
        if aggregate > packet["authorized_amount_cents"]:
            raise ApiError("ERR_AUTHORIZED_AMOUNT_EXCEEDED")
        row["status"] = "APPROVED"
    elif decision == "DECLINE":
        row["status"] = "DECLINED"
        row["revision_reason"] = note
        for asset in calc.assigned_assets(row["id"]):
            release_occupation(asset)
    else:
        row["status"] = "REVISION_REQUESTED"
        row["revision_reason"] = note
        row["revision_count"] = row.get("revision_count", 0) + 1
    row["decided_by_user_id"] = ctx.user_id
    store.touch(row)
    return envelope.ok(serializers.loan_application(row))


@bp.route("/loan-applications/<loan_application_id>/underwriting-summary",
          methods=["GET"])
def underwriting_summary(loan_application_id):
    ctx = auth.authenticate(SUMMARY_ROLES)
    row = resolve.loan_application(loan_application_id)
    auth.scope(ctx, auth.owner_of_application(row))
    institution = store.institutions[row["institution_id"]]
    basis = request.args.get("giving_basis")
    if basis is None or basis == "":
        basis = row.get("giving_basis") or calc.mandated_basis(institution["id"])
    if basis not in calc.GIVING_BASES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter 'giving_basis' is invalid.")
    as_of = store.clock_now()
    window = calc.window_periods(institution["id"], as_of, basis)
    total, audited = calc.period_counts(institution["id"])
    net = calc.net_available_dollars(institution["id"], as_of, basis)
    maximum, binding = calc.max_supportable(row, net)
    return envelope.ok({
        "giving_basis": basis,
        "period_count": total,
        "audited_period_count": audited,
        "window_period_labels": [p["period_label"] for p in window],
        "giving_base_cents": calc.giving_base_cents(institution["id"], as_of,
                                                    basis),
        "net_available_dollars": net,
        "membership_trend_pct": calc.num(
            calc.membership_trend_pct(institution["id"], as_of, basis)),
        "collateral_lending_value_cents": calc.first_lien_value_cents(row["id"]),
        "max_supportable_principal_cents": maximum,
        "requested_amount_cents": row["requested_amount_cents"],
        "binding_cap": binding,
    })
