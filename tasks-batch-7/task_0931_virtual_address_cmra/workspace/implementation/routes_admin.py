"""Registered-agent add-on, compliance reviews, billing cycles and cancellation."""

import re

from flask import Blueprint, g, request

import calc
import domain
import ladder as L
import serializers as S
import store
from errors import ApiError
from response import created, listing, ok, touch
from store import DB, insert
from util import (
    ABANDONMENT_RTS_DAYS, CLOCK, FINAL_FORWARD_WINDOW_DAYS, NOTICE_PERIOD_DAYS,
    RA_DEFAULT_RETENTION_DAYS, RETENTION_FLOOR_DAYS, STATUS_ENUMS, add_days,
)

bp = Blueprint("admin", __name__)

_JURISDICTION = re.compile(r"^[A-Z]{2}$")


# ------------------------------------------------------------------ registered agent
@bp.post("/boxes/<ident>/registered-agent")
@L.endpoint(roles=["PlatformAdmin"], primary="box")
def attach_ra(box):
    b = L.body()
    code = L.req_str(b, "jurisdiction_code")
    if not _JURISDICTION.match(code):
        L._bad("jurisdiction_code", "must be exactly two uppercase letters")
    days = L.opt_int(b, "retention_days", RA_DEFAULT_RETENTION_DAYS, 1)
    L.gate_b("ra_attach", box)
    # Adjudication of friction 5 (reading B): nothing constrains a mailbox to a
    # single add-on -- the collection is listed per mailbox with an `active`
    # filter that presupposes several rows -- and reading A would need an
    # undeclared error for the second attach.  The governing add-on is the most
    # recently created active one (see store.active_ra).
    row = insert(DB.registered_agents, {
        "box_id": box["id"], "jurisdiction_code": code, "retention_days": days,
        "active": True, "deactivated_at": None,
    })
    return created(S.registered_agent(row))


@bp.get("/boxes/<ident>/registered-agent")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer", "BoxHolder"],
            primary="box", scope=True)
def list_ra(box):
    active = request.args.get("active")
    data = store.ra_services_of_box(box["id"])
    if active is not None:
        if active.lower() not in ("true", "false"):
            L._bad("active", "must be true or false")
        data = [r for r in data if r["active"] == (active.lower() == "true")]
    items, total, limit, offset = L.paginate(data, S.registered_agent)
    return listing(items, total, limit, offset)


@bp.post("/boxes/<ident>/registered-agent/deactivate")
@L.endpoint(roles=["PlatformAdmin"], primary="box")
def deactivate_ra(box):
    ra = store.active_ra(box["id"])                                 # rung 4
    if ra is None:
        raise ApiError("ERR_INVALID_STATE", "The mailbox carries no active add-on.")
    L.gate_b("ra_deactivate", box)
    ra["active"] = False
    ra["deactivated_at"] = CLOCK.now
    touch(ra)
    return ok(S.registered_agent(ra))


# ------------------------------------------------------------------ compliance
@bp.post("/boxes/<ident>/compliance-reviews")
@L.endpoint(roles=["ComplianceOfficer"], primary="box")
def open_review(box):
    b = L.body()
    L.req_present(b, "reason")
    reason = L.enum_body(b, "reason", "reason")
    L.gate_b("review_open", box)
    status = box["compliance_status"]                               # rung 14
    if status == "COMPLIANT":
        if box["service_status"] not in ("ACTIVE", "SUSPENDED", "CLOSING"):
            raise ApiError("ERR_INVALID_STATE")
    elif status == "NON_COMPLIANT":
        if any(r["status"] in ("OPEN", "SUSPENDED") for r in store.reviews_of_box(box["id"])):
            raise ApiError("ERR_INVALID_STATE")
    else:
        raise ApiError("ERR_INVALID_STATE")
    row = insert(DB.compliance_reviews, {
        "box_id": box["id"], "reason": reason, "status": "OPEN",
        "opened_by_user_id": g.user_id, "resolved_by_user_id": None,
        "resolution": "NONE", "resolved_at": None,
    })
    box["compliance_status"] = "UNDER_REVIEW"
    touch(box)
    return created(S.compliance_review(row))


@bp.get("/boxes/<ident>/compliance-reviews")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer"], primary="box")
def list_reviews(box):
    status = L.enum_query("status", members=STATUS_ENUMS["compliance_review"])
    data = [r for r in store.reviews_of_box(box["id"])
            if status is None or r["status"] == status]
    items, total, limit, offset = L.paginate(data, S.compliance_review)
    return listing(items, total, limit, offset)


@bp.post("/compliance-reviews/<ident>/suspend")
@L.endpoint(roles=["ComplianceOfficer"], primary="compliance_review")
def suspend_review(review):
    box = DB.boxes[review["box_id"]]
    L.gate_b("review_suspend", box)
    if review["status"] != "OPEN" or box["service_status"] != "ACTIVE":   # rung 14
        raise ApiError("ERR_INVALID_STATE")

    # HOP 1 -- the review suspends.
    review["status"] = "SUSPENDED"
    touch(review)
    # HOP 2 -- because the review suspended, the mailbox suspends.
    box["service_status"] = "SUSPENDED"
    box["suspended_reason"] = "COMPLIANCE_REVIEW"
    box["compliance_status"] = "NON_COMPLIANT"
    touch(box)
    # HOP 3 -- because the mailbox is suspended, pending dispositions cancel.
    affected = []
    for item in store.mail_items_of_box(box["id"]):
        for d in store.pending_dispositions(item["id"]):
            d["status"] = "CANCELLED"
            d["resolution_reason"] = "GATE_SUSPENSION"
            touch(d)
            if item not in affected:
                affected.append(item)
    # HOP 4 -- because no pending request remains, those pieces return to HELD.
    returned = []
    for item in affected:
        if item["handling_status"] == "PENDING_DISPOSITION" and not store.pending_dispositions(item["id"]):
            item["handling_status"] = "HELD"
            touch(item)
            returned.append(item)
    # HOP 5 -- because those pieces re-entered HELD, storage is re-evaluated.
    for item in returned:
        domain.evaluate_storage_axis(item)
    # HOP 6 -- because the mailbox is suspended, AUTHORIZED members suspend.
    suspended = []
    for r in store.recipients_of_box(box["id"]):
        if r["roster_status"] == "AUTHORIZED":
            r["roster_status"] = "SUSPENDED"
            touch(r)
            suspended.append(r)
    # HOP 7 -- because those members left AUTHORIZED, eligibility re-derives.
    # All roster statuses are written before any re-derivation so that a MINOR
    # whose guarantor is also being suspended reports GUARANTOR_BLOCKED rather
    # than ROSTER_NOT_AUTHORIZED.
    for r in suspended:
        domain.rederive_eligibility(r)
    return ok(S.compliance_review(review))


@bp.post("/compliance-reviews/<ident>/resolve")
@L.endpoint(roles=["ComplianceOfficer"], primary="compliance_review")
def resolve_review(review):
    b = L.body()
    L.req_present(b, "resolution")                                  # rung 9
    resolution = L.enum_body(b, "resolution", "resolution")         # rung 10
    box = DB.boxes[review["box_id"]]
    L.gate_b("review_resolve", box)                                 # rung 12
    if review["status"] not in ("OPEN", "SUSPENDED"):               # rung 14
        raise ApiError("ERR_INVALID_STATE")
    if review["status"] == "OPEN" and resolution != "CLEARED":
        raise ApiError("ERR_INVALID_STATE",
                       "A review still in OPEN may be resolved only as CLEARED.")
    if review["status"] == "SUSPENDED" and resolution == "ESCALATED_CLOSURE":
        if store.live_cancellation(box["id"]) is not None:
            raise ApiError("ERR_INVALID_STATE",
                           "A cancellation request is already pending on this mailbox.")
    if g.user_id == review["opened_by_user_id"]:                    # rung 15
        raise ApiError("ERR_UNAUTHORIZED", "The resolver must differ from the opener.")

    was_suspended = review["status"] == "SUSPENDED"
    review["status"] = "RESOLVED"
    review["resolution"] = resolution
    review["resolved_by_user_id"] = g.user_id
    review["resolved_at"] = CLOCK.now
    touch(review)

    if not was_suspended:
        box["compliance_status"] = "COMPLIANT"
        touch(box)
    elif resolution == "CLEARED":
        box["service_status"] = "ACTIVE"
        box["suspended_reason"] = "NONE"
        box["compliance_status"] = "COMPLIANT"
        touch(box)
        restored = []
        for r in store.recipients_of_box(box["id"]):
            if r["roster_status"] == "SUSPENDED":
                r["roster_status"] = "AUTHORIZED"
                touch(r)
                restored.append(r)
        for r in restored:
            domain.rederive_eligibility(r)
    else:
        box["service_status"] = "CLOSING"
        box["suspended_reason"] = "USPS_ORDER"
        touch(box)
        _create_cancellation(box, "ADDRESS_ON_FILE", escalated=True)
    return ok(S.compliance_review(review))


# ------------------------------------------------------------------ billing cycles
@bp.get("/boxes/<ident>/billing-cycles")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "BoxHolder"], primary="box", scope=True)
def list_cycles(box):
    status = L.enum_query("status", members=STATUS_ENUMS["billing_cycle"])
    data = [c for c in store.cycles_of_box(box["id"])
            if status is None or c["status"] == status]
    items, total, limit, offset = L.paginate(data, S.billing_cycle)
    return listing(items, total, limit, offset)


@bp.get("/billing-cycles/<ident>")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "BoxHolder"],
            primary="billing_cycle", scope=True)
def read_cycle(cycle):
    return ok(S.billing_cycle(cycle))


@bp.get("/billing-cycles/<ident>/usage-entries")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "BoxHolder"],
            primary="billing_cycle", scope=True)
def list_cycle_usage(cycle):
    unit = L.enum_query("unit_type", "unit_type")
    tranche = L.enum_query("tranche", "tranche")
    data = store.entries_of_cycle(cycle["id"])
    if unit is not None:
        data = [e for e in data if e["unit_type"] == unit]
    if tranche is not None:
        data = [e for e in data if e["tranche"] == tranche]
    items, total, limit, offset = L.paginate(data, S.usage_entry)
    return listing(items, total, limit, offset)


@bp.post("/boxes/<ident>/billing-cycles/close")
@L.endpoint(roles=["PlatformAdmin"], primary="box")
def close_billing_cycle(box):
    cycle = store.open_cycle(box["id"])                             # rung 4
    if cycle is None:
        raise ApiError("ERR_INVALID_STATE", "The mailbox has no OPEN billing cycle.")
    L.gate_b("billing_cycle_close", box)                            # rung 12
    if CLOCK.date() < cycle["period_end"]:                          # rung 14
        raise ApiError("ERR_INVALID_STATE",
                       "The clock date has not reached the cycle's period_end.")
    domain.close_cycle(box, cycle)
    return ok(S.billing_cycle(cycle))


# ------------------------------------------------------------------ cancellation
def _create_cancellation(box, forwarding_address, escalated=False):
    requested_on = CLOCK.date()
    notice_end = add_days(requested_on, NOTICE_PERIOD_DAYS)
    final_forward = add_days(notice_end, FINAL_FORWARD_WINDOW_DAYS)
    abandonment = add_days(final_forward, ABANDONMENT_RTS_DAYS)
    return insert(DB.cancellations, {
        "box_id": box["id"], "forwarding_address": forwarding_address,
        "requested_on": requested_on, "notice_end_date": notice_end,
        "final_forward_deadline": final_forward, "abandonment_date": abandonment,
        "destruction_eligible_on": add_days(abandonment, RETENTION_FLOOR_DAYS),
        "status": "REQUESTED",
        "prepaid_at_request_cents": box["prepaid_balance_cents"],
        "deposit_held_cents": box["security_deposit_cents"],
        "applied_to_overage_cents": 0, "refund_total_cents": 0, "forfeited_cents": 0,
        "_escalated": escalated,
    })


@bp.post("/boxes/<ident>/cancellation")
@L.endpoint(roles=["BoxHolder"], primary="box", scope=True)
def create_cancellation(box):
    b = L.body()
    address = L.req_str(b, "forwarding_address")                    # rung 9
    L.gate_b("cancellation_create", box)                            # rung 12
    # Rung 33 is evaluated ahead of rung 14 here, and only here.  A cancellation
    # in REQUESTED or FINAL_FORWARD always implies the mailbox is CLOSING (lodging
    # drives ACTIVE -> CLOSING; only a withdrawal returns it to ACTIVE, and that
    # same withdrawal retires the request), so behind rung 14 the rung-33 branch
    # is unreachable and ERR_CANCELLATION_ALREADY_PENDING can never be produced.
    # PRD 3.13 attaches the identifier to the pending-cancellation clause
    # explicitly, so that clause is checked first; rung 14 still fires for every
    # other non-ACTIVE service_status (SUSPENDED, and CLOSING with no live request).
    if store.live_cancellation(box["id"]) is not None:              # rung 33
        raise ApiError("ERR_CANCELLATION_ALREADY_PENDING")
    if box["service_status"] != "ACTIVE":                           # rung 14
        raise ApiError("ERR_INVALID_STATE")
    row = _create_cancellation(box, address)
    box["service_status"] = "CLOSING"
    touch(box)
    return created(S.cancellation(row))


@bp.get("/boxes/<ident>/cancellation")
@L.endpoint(roles=["PlatformAdmin", "CmraOperator", "ComplianceOfficer", "BoxHolder"],
            primary="box", scope=True)
def list_cancellations(box):
    status = L.enum_query("status", members=STATUS_ENUMS["cancellation"])
    data = [c for c in store.cancellations_of_box(box["id"])
            if status is None or c["status"] == status]
    items, total, limit, offset = L.paginate(data, S.cancellation)
    return listing(items, total, limit, offset)


def _target_cancellation(box):
    live = store.live_cancellation(box["id"])
    if live is not None:
        return live
    rows = store.cancellations_of_box(box["id"])
    return rows[-1] if rows else None


@bp.post("/boxes/<ident>/cancellation/withdraw")
@L.endpoint(roles=["BoxHolder"], primary="box")
def withdraw_cancellation(box):
    request_row = _target_cancellation(box)                         # rung 4
    if request_row is None:
        raise ApiError("ERR_INVALID_STATE", "The mailbox has no cancellation request.")
    L.scope_check("box", box)                                       # rung 8
    L.gate_b("cancellation_withdraw", box)                          # rung 12
    if request_row["status"] not in ("REQUESTED", "FINAL_FORWARD"):  # rung 14
        raise ApiError("ERR_INVALID_STATE")
    if box["service_status"] != "CLOSING":
        raise ApiError("ERR_INVALID_STATE")
    if (request_row["status"] == "FINAL_FORWARD"
            and CLOCK.date() > request_row["final_forward_deadline"]):
        raise ApiError("ERR_INVALID_STATE",
                       "The final forward deadline has passed.")
    request_row["status"] = "WITHDRAWN"
    touch(request_row)
    box["service_status"] = "ACTIVE"
    touch(box)
    return ok(S.cancellation(request_row))


@bp.post("/boxes/<ident>/cancellation/finalize")
@L.endpoint(roles=["CmraOperator"], primary="box")
def finalize_cancellation(box):
    request_row = _target_cancellation(box)                         # rung 4
    if request_row is None:
        raise ApiError("ERR_INVALID_STATE", "The mailbox has no cancellation request.")
    L.gate_b("cancellation_finalize", box)                          # rung 12
    if box["service_status"] != "CLOSING" or request_row["status"] != "FINAL_FORWARD":
        raise ApiError("ERR_INVALID_STATE")                         # rung 14
    for item in store.mail_items_of_box(box["id"]):                 # rung 34
        if item["item_class"] != "SOP":
            continue
        if item["storage_status"] not in ("FREE_WINDOW", "ACCRUING"):
            continue
        if domain.sop_retention_blocks(item, request_row):
            raise ApiError("ERR_RA_RETENTION_ACTIVE")
    if CLOCK.date() < request_row["destruction_eligible_on"]:       # rung 35
        raise ApiError("ERR_RETENTION_FLOOR_NOT_REACHED")

    for item in store.mail_items_of_box(box["id"]):
        if item["item_class"] == "SOP":
            continue
        if item["storage_status"] not in ("FREE_WINDOW", "ACCRUING"):
            continue
        item["handling_status"] = "SHREDDED"
        domain.end_custody(item, destroyed=True)
        touch(item)

    if request_row["_escalated"]:
        for item in store.mail_items_of_box(box["id"]):
            if item["billing_status"] == "METERED":
                item["billing_status"] = "WRITTEN_OFF"
                touch(item)

    pool = request_row["prepaid_at_request_cents"] + request_row["deposit_held_cents"]
    applied = min(pool, calc.outstanding_overage(box["id"]))
    remainder = pool - applied
    escalated = any(r["resolution"] == "ESCALATED_CLOSURE"
                    for r in store.reviews_of_box(box["id"]))
    forfeited = remainder if escalated else 0
    request_row["applied_to_overage_cents"] = applied
    request_row["forfeited_cents"] = forfeited
    request_row["refund_total_cents"] = remainder - forfeited
    request_row["status"] = "FINALIZED"
    touch(request_row)

    cycle = store.open_cycle(box["id"])
    if cycle is not None:
        domain.close_cycle(box, cycle)
    box["service_status"] = "CLOSED"
    touch(box)
    return ok(S.cancellation(request_row))
