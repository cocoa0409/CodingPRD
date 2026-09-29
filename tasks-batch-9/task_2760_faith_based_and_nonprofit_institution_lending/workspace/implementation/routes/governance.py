"""Governance authorizations (PRD section 3.2)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import envelope
import resolve
import serializers
import shapes
import store
from auth import (COMMITTEE_MEMBER, CREDIT_ANALYST, GOVERNANCE_OFFICER,
                  INSTITUTION_REP, PLATFORM_ADMIN)
from errors import ApiError

bp = Blueprint("governance", __name__)

READ_ROLES = (PLATFORM_ADMIN, GOVERNANCE_OFFICER, CREDIT_ANALYST,
              COMMITTEE_MEMBER, INSTITUTION_REP)
DECISIONS = ("APPROVE", "REJECT")


@bp.route("/governance-authorizations", methods=["POST"])
def create_authorization():
    ctx = auth.authenticate((INSTITUTION_REP,))
    b = shapes.body()
    auth.scope(ctx, b.get("institution_id"))
    institution = resolve.institution(b.get("institution_id"))
    if institution is None:
        shapes.req_id_field(b, "institution_id")

    resolution_raw, _resolution_dt = shapes.req_dt(b, "resolution_date")
    citation = shapes.req_str(b, "bylaws_citation")
    votes_for = shapes.req_int(b, "board_votes_for", minimum=0)
    votes_total = shapes.req_int(b, "board_votes_total", exclusive_minimum=0)
    amount = shapes.req_int(b, "authorized_amount_cents", exclusive_minimum=0)
    expires_raw, expires_dt = shapes.req_dt(b, "expires_on")
    body_name = shapes.opt_str(b, "denominational_body")

    row = store.base_record()
    row.update({
        "institution_id": institution["id"],
        "status": "DRAFT",
        "resolution_date": resolution_raw,
        "bylaws_citation": citation,
        "board_votes_for": votes_for,
        "board_votes_total": votes_total,
        "authorized_amount_cents": amount,
        "denominational_body": body_name,
        "denominational_decision_note": None,
        "expires_on": expires_raw,
        "board_quorum_pct": None,
        "verified_by_user_id": None,
        "revision_round": 0,
        "minutes_reference": None,
        "rework_note": None,
        "_expires_on_dt": expires_dt,
    })
    store.governance_authorizations[row["id"]] = row
    store.mark_created(row)
    return envelope.created(serializers.governance_authorization(row))


@bp.route("/governance-authorizations/<governance_authorization_id>",
          methods=["GET"])
def get_authorization(governance_authorization_id):
    ctx = auth.authenticate(READ_ROLES)
    row = resolve.governance_authorization(governance_authorization_id)
    auth.scope(ctx, row.get("institution_id"))
    return envelope.ok(serializers.governance_authorization(row))


@bp.route("/governance-authorizations", methods=["GET"])
def list_authorizations():
    auth.authenticate(READ_ROLES)
    rows = envelope.filter_rows(
        list(store.governance_authorizations.values()),
        {"institution_id": "institution_id", "status": "status"})
    return envelope.listing(envelope.sort_created_desc(rows),
                            serializers.governance_authorization)


@bp.route("/governance-authorizations/<governance_authorization_id>/submit",
          methods=["POST"])
def submit_authorization(governance_authorization_id):
    ctx = auth.authenticate((INSTITUTION_REP,))
    row = resolve.governance_authorization(governance_authorization_id)
    auth.scope(ctx, row.get("institution_id"))
    if row["status"] != "DRAFT":
        raise ApiError("ERR_AUTHORIZATION_INVALID_STATE")
    institution = store.institutions.get(row["institution_id"])
    if institution is not None and \
            row["authorized_amount_cents"] > institution["bylaws_borrowing_cap_cents"]:
        raise ApiError("ERR_BYLAWS_CAP_EXCEEDED")
    row["status"] = "SUBMITTED"
    store.touch(row)
    return envelope.ok(serializers.governance_authorization(row))


@bp.route("/governance-authorizations/<governance_authorization_id>"
          "/board-verification", methods=["POST"])
def verify_authorization(governance_authorization_id):
    ctx = auth.authenticate((GOVERNANCE_OFFICER,))
    row = resolve.governance_authorization(governance_authorization_id)
    b = shapes.body()
    minutes = shapes.req_str(b, "minutes_reference")
    if row["status"] != "SUBMITTED":
        raise ApiError("ERR_AUTHORIZATION_INVALID_STATE")
    institution = store.institutions.get(row["institution_id"])
    quorum = calc.rhu(
        Decimal(row["board_votes_for"]) / Decimal(row["board_votes_total"]), 4)
    if institution is not None and quorum < institution["bylaws_quorum_pct"]:
        raise ApiError("ERR_BOARD_QUORUM_NOT_MET")
    row["board_quorum_pct"] = quorum
    row["verified_by_user_id"] = ctx.user_id
    row["minutes_reference"] = minutes
    requires = bool(institution and
                    institution.get("requires_denominational_approval"))
    row["status"] = "BOARD_VERIFIED" if requires else "AUTHORIZED"
    store.touch(row)
    return envelope.ok(serializers.governance_authorization(row))


@bp.route("/governance-authorizations/<governance_authorization_id>"
          "/denominational-decision", methods=["POST"])
def denominational_decision(governance_authorization_id):
    auth.authenticate((GOVERNANCE_OFFICER,))
    row = resolve.governance_authorization(governance_authorization_id)
    b = shapes.body()
    decision = shapes.req_enum(b, "decision", DECISIONS)
    note = shapes.opt_str(b, "note")
    if row["status"] != "BOARD_VERIFIED":
        raise ApiError("ERR_AUTHORIZATION_INVALID_STATE")
    if not row.get("denominational_body"):
        raise ApiError("ERR_DENOMINATIONAL_APPROVAL_REQUIRED")
    row["denominational_decision_note"] = note
    row["status"] = "AUTHORIZED" if decision == "APPROVE" else "DENOM_REJECTED"
    store.touch(row)
    return envelope.ok(serializers.governance_authorization(row))


@bp.route("/governance-authorizations/<governance_authorization_id>"
          "/return-to-draft", methods=["POST"])
def return_to_draft(governance_authorization_id):
    ctx = auth.authenticate((INSTITUTION_REP,))
    row = resolve.governance_authorization(governance_authorization_id)
    auth.scope(ctx, row.get("institution_id"))
    b = shapes.body()
    note = shapes.req_str(b, "rework_note")
    if row["status"] != "DENOM_REJECTED":
        raise ApiError("ERR_AUTHORIZATION_INVALID_STATE")
    row["status"] = "DRAFT"
    row["revision_round"] = row.get("revision_round", 0) + 1
    row["denominational_decision_note"] = None
    row["verified_by_user_id"] = None
    row["rework_note"] = note
    store.touch(row)
    return envelope.ok(serializers.governance_authorization(row))
