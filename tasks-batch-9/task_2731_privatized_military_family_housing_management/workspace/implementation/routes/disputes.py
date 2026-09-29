"""Resident dispute resolution: a bounded rebuttal loop with escalation (PRD 3.9)."""

from flask import Blueprint

import middleware as mw
import response as resp
from db import (base_row, bump, db, iso, now, now_iso, period_of, sort_rows,
                timedelta, today)
from errors import ApiError
from services import core, lookup

bp = Blueprint("disputes", __name__)

DISPUTE_READ_ROLES = (mw.PLATFORM_ADMIN, mw.PROPERTY_MANAGER, mw.SERVICE_MEMBER,
                      mw.INSTALLATION_HOUSING_OFFICE)
DISPUTE_ROUND_CAP = 3
DISPUTE_RESOLUTION_DAYS = 30
CREDIT_OPEN_STATUSES = ("ACTIVE", "SUSPENDED")
OCCUPIED_STATUSES = ("OCCUPIED", "NOTICE_GIVEN")


def _guard(dispute, allowed_from):
    if dispute["status"] == "CLOSED_RESOLVED":
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")
    if dispute["status"] not in allowed_from:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")


def _owner_guard(role, user_id, dispute_id):
    existing = lookup.maybe("disputes", dispute_id)
    if existing is not None:
        mw.require_owner(role, user_id, existing["service_member_id"])


def _post_award(dispute, award_cents):
    """Post the REFUND row for a positive award and recompute the ledger."""
    lease = lookup.lease(dispute["lease_id"])
    if award_cents <= 0:
        return
    core.post_transaction(lease, "REFUND", period_of(today()), -int(award_cents),
                          "DISPUTE_AWARD:" + dispute["id"])
    bump(lease)


def _credit_gate(dispute, award_cents):
    if award_cents <= 0:
        return
    lease = lookup.lease(dispute["lease_id"])
    if lease["allotment_status"] not in CREDIT_OPEN_STATUSES:
        raise ApiError("ERR_ALLOTMENT_NOT_ACTIVE")


@bp.post("/dispute-cases")
def open_dispute():
    user_id, role = mw.authenticate((mw.SERVICE_MEMBER,))
    body = mw.json_body()
    raw_member = mw.raw_ref(body, "service_member_id")
    if raw_member is not None:
        mw.require_owner(role, user_id, raw_member)
    raw_lease = mw.raw_ref(body, "lease_id")
    if raw_lease is not None:
        mw.require_owner(role, user_id, mw.lease_sponsor(raw_lease))

    lease_id = mw.v_id(body, "lease_id")
    member_id = mw.v_id(body, "service_member_id")
    category = mw.v_enum(body, "category", mw.DISPUTE_CATEGORIES)
    description = mw.v_str(body, "description")

    lookup.service_member(member_id)
    lease = lookup.lease(lease_id)
    if lease["occupancy_status"] not in OCCUPIED_STATUSES:
        raise ApiError("ERR_LEASE_NOT_OCCUPIED")

    opened_at = now()
    row = base_row()
    row["lease_id"] = lease["id"]
    row["service_member_id"] = lease["service_member_id"]
    row["category"] = category
    row["description"] = description
    row["status"] = "UNDER_REVIEW"
    row["round_count"] = 0
    row["proposed_remedy"] = None
    row["credit_offer_cents"] = 0
    row["proposed_by_user_id"] = None
    row["decided_by_user_id"] = None
    row["credit_award_cents"] = 0
    row["opened_at"] = iso(opened_at)
    row["resolution_due_at"] = iso(opened_at + timedelta(days=DISPUTE_RESOLUTION_DAYS))
    row["escalated_at"] = None
    db.disputes[row["id"]] = row
    return resp.created(row)


@bp.get("/dispute-cases/<dispute_id>")
def get_dispute(dispute_id):
    user_id, role = mw.authenticate(DISPUTE_READ_ROLES)
    _owner_guard(role, user_id, dispute_id)
    return resp.ok(lookup.dispute(dispute_id))


@bp.get("/dispute-cases")
def list_disputes():
    mw.authenticate(DISPUTE_READ_ROLES)
    limit, offset = mw.pagination()
    lease_id = mw.q_str("lease_id")
    member_id = mw.q_str("service_member_id")
    category = mw.q_enum("category", mw.DISPUTE_CATEGORIES)
    status = mw.q_enum("status", mw.DISPUTE_STATUSES)
    rows = sort_rows(list(db.disputes.values()))
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    if member_id is not None:
        rows = [r for r in rows if r["service_member_id"] == member_id]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return resp.page(rows, limit, offset)


@bp.post("/dispute-cases/<dispute_id>/propose-resolution")
def propose_resolution(dispute_id):
    user_id, _role = mw.authenticate((mw.PROPERTY_MANAGER,))
    body = mw.json_body()
    remedy = mw.v_str(body, "proposed_remedy")
    offer = mw.v_int(body, "credit_offer_cents", minimum=0)
    dispute = lookup.dispute(dispute_id)
    _guard(dispute, ("UNDER_REVIEW",))
    if int(dispute["round_count"]) >= DISPUTE_ROUND_CAP:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The dispute has exhausted its negotiation rounds.")

    dispute["round_count"] = int(dispute["round_count"]) + 1
    dispute["proposed_remedy"] = remedy
    dispute["credit_offer_cents"] = offer
    dispute["proposed_by_user_id"] = user_id
    dispute["status"] = "PROPOSED_RESOLUTION"
    bump(dispute)
    return resp.ok(dispute)


@bp.post("/dispute-cases/<dispute_id>/respond")
def respond(dispute_id):
    user_id, role = mw.authenticate((mw.SERVICE_MEMBER,))
    _owner_guard(role, user_id, dispute_id)
    body = mw.json_body()
    accepted = mw.v_bool(body, "accepted")
    dispute = lookup.dispute(dispute_id)
    _guard(dispute, ("PROPOSED_RESOLUTION",))

    if accepted:
        award = int(dispute["credit_offer_cents"])
        _credit_gate(dispute, award)
        dispute["credit_award_cents"] = award
        dispute["status"] = "CLOSED_RESOLVED"
        bump(dispute)
        _post_award(dispute, award)
        return resp.ok(dispute)

    dispute["status"] = "RESIDENT_REJECTED"
    if int(dispute["round_count"]) < DISPUTE_ROUND_CAP:
        dispute["status"] = "UNDER_REVIEW"
    else:
        dispute["status"] = "ESCALATED_INSTALLATION"
        dispute["escalated_at"] = now_iso()
    bump(dispute)
    return resp.ok(dispute)


@bp.post("/dispute-cases/<dispute_id>/installation-decision")
def installation_decision(dispute_id):
    user_id, _role = mw.authenticate((mw.INSTALLATION_HOUSING_OFFICE,))
    body = mw.json_body()
    award = mw.v_int(body, "credit_award_cents", minimum=0)
    mw.v_str(body, "decision_note", required=False, default=None)
    dispute = lookup.dispute(dispute_id)
    _guard(dispute, ("ESCALATED_INSTALLATION",))
    _credit_gate(dispute, award)
    if dispute.get("proposed_by_user_id") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    dispute["credit_award_cents"] = award
    dispute["decided_by_user_id"] = user_id
    dispute["status"] = "CLOSED_RESOLVED"
    bump(dispute)
    _post_award(dispute, award)
    return resp.ok(dispute)
