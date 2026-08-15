"""Reconciliations, return authorizations, profit-share payouts, media blasts."""

from flask import Blueprint, g

import db
from errors import fail
from middleware import ALL_ROLES, require_roles, require_scope
from response import success, success_list
from routes_core import get_or_404
from services import (
    PAYOUT_NON_TERMINAL,
    SHRINK_TOLERANCE_UNITS,
    accepted_agreements,
    compute_payout,
    compute_remittance,
    compute_provisional_lines,
    compute_return_credit,
    latest_reconciliation,
    new_entity,
    recompute_availability,
    recompute_variance,
    touch,
)
from util import (
    get_body,
    list_filtered,
    page,
    pagination_params,
    parse_dt_loose,
    v_datetime,
    v_enum,
    v_int,
    v_str,
    validate_body,
)

bp = Blueprint("finance", __name__)


# ---------------------------------------------------------------------------
# Reconciliations
# ---------------------------------------------------------------------------

@bp.get("/reconciliations")
@require_roles(*ALL_ROLES)
def list_reconciliations():
    limit, offset = pagination_params()
    items = list_filtered(
        db.reconciliations, [("fair_id", "fair_id"), ("status", "status")]
    )
    items, total = page(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/reconciliations/<rid>")
@require_roles(*ALL_ROLES)
def get_reconciliation(rid):
    return success(get_or_404(db.reconciliations, rid, "Reconciliation"))


def _parse_count_lines(raw):
    if not isinstance(raw, list):
        fail("ERR_VALIDATION", "lines must be an array")
    parsed = []
    for item in raw:
        if not isinstance(item, dict):
            fail("ERR_VALIDATION", "each counts line must be an object")
        unknown = sorted(set(item.keys()) - {"stock_line_id", "qty_on_hand"})
        if unknown:
            fail("ERR_VALIDATION", "Unknown line field(s): %s" % ", ".join(unknown))
        if "stock_line_id" not in item or not isinstance(item["stock_line_id"], str):
            fail("ERR_VALIDATION", "line stock_line_id must be a string")
        qty = item.get("qty_on_hand")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 0:
            fail("ERR_VALIDATION", "line qty_on_hand must be a non-negative integer")
        parsed.append({"stock_line_id": item["stock_line_id"], "qty_on_hand": qty})
    return parsed


@bp.post("/reconciliations/<rid>/counts")
@require_roles("Organizer")
def post_counts(rid):
    recon = get_or_404(db.reconciliations, rid, "Reconciliation")
    data = get_body()
    raw_lines = data.get("lines")
    if isinstance(raw_lines, list):
        for item in raw_lines:
            if isinstance(item, dict):
                sid = item.get("stock_line_id")
                if isinstance(sid, str) and sid not in db.stock_lines:
                    fail("ERR_NOT_FOUND", "line stock_line_id references no existing StockLine")
    vals = validate_body(
        data,
        [
            ("lines", True, lambda n, v: _parse_count_lines(v)),
            ("expected_reconciliation_version", True, v_int()),
        ],
    )
    if recon["status"] not in ("OPEN", "VARIANCE_REVIEW", "DISPUTED"):
        fail("ERR_INVALID_STATE", "Counts cannot be entered in the reconciliation's current state")
    # OCC (9): recount legitimately supersedes the prior count set.
    if vals["expected_reconciliation_version"] != recon["version"]:
        fail("ERR_STALE_VERSION", "Reconciliation version has advanced since last read")
    recon["counted_lines"] = vals["lines"]
    for counted in vals["lines"]:
        line = db.stock_lines.get(counted["stock_line_id"])
        if line is not None:
            line["qty_on_hand_counted"] = counted["qty_on_hand"]
            touch(line)
    # Provisional expectations are recomputed from CURRENT counters on every
    # counts call — damage recorded during RECONCILING absorbs shrink.
    recon["provisional_lines"] = compute_provisional_lines(recon["fair_id"])
    recompute_variance(recon)
    if recon["status"] == "DISPUTED":
        recon["dispute_reason"] = None
    if recon["status"] in ("VARIANCE_REVIEW", "DISPUTED"):
        recon["status"] = "OPEN"
    touch(recon)
    return success(recon)


@bp.post("/reconciliations/<rid>/submit-review")
@require_roles("Organizer")
def submit_review(rid):
    recon = get_or_404(db.reconciliations, rid, "Reconciliation")
    validate_body(get_body(), [])
    if recon["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Reconciliation is not in OPEN")
    delivered = {
        l["id"]
        for l in db.stock_lines.values()
        if l["fair_id"] == recon["fair_id"] and l["status"] == "DELIVERED"
    }
    counted = {c["stock_line_id"] for c in recon["counted_lines"]}
    if not delivered <= counted:
        fail("ERR_COUNTS_INCOMPLETE", "Counts must cover every DELIVERED stock line of the fair")
    recon["provisional_lines"] = compute_provisional_lines(recon["fair_id"])
    recompute_variance(recon)
    recon["status"] = "VARIANCE_REVIEW"
    touch(recon)
    return success(recon)


@bp.post("/reconciliations/<rid>/approve")
@require_roles("Organizer")
def approve_reconciliation(rid):
    recon = get_or_404(db.reconciliations, rid, "Reconciliation")
    validate_body(get_body(), [])
    if recon["status"] != "VARIANCE_REVIEW":
        fail("ERR_INVALID_STATE", "Reconciliation is not in VARIANCE_REVIEW")
    # Segregation of duties runs before the variance gate (pinned order).
    if g.user_id == recon["created_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The reconciliation approver must differ from its creator",
        )
    if recon["total_abs_variance"] > SHRINK_TOLERANCE_UNITS:
        fail("ERR_VARIANCE_BEYOND_TOLERANCE", "total_abs_variance exceeds the shrink tolerance")
    remittance = compute_remittance(recon["fair_id"])
    recon["remittance_cents"] = remittance
    recon["status"] = "APPROVED"
    touch(recon)
    fair = db.fairs[recon["fair_id"]]
    fair["publisher_remittance_cents"] = remittance
    touch(fair)
    for line in db.stock_lines.values():
        if line["fair_id"] == recon["fair_id"] and line["status"] == "DELIVERED":
            line["status"] = "RECONCILED"
            touch(line)
    return success(recon)


@bp.post("/reconciliations/<rid>/submit")
@require_roles("Organizer")
def submit_reconciliation(rid):
    recon = get_or_404(db.reconciliations, rid, "Reconciliation")
    validate_body(get_body(), [])
    if recon["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Reconciliation is not in APPROVED")
    recon["status"] = "SUBMITTED"
    touch(recon)
    return success(recon)


def _publisher_scope_for_fair(fair_id):
    publishers = {a["publisher_party_id"] for a in accepted_agreements(fair_id)}
    if g.party["id"] not in publishers:
        fail(
            "ERR_PARTY_SCOPE_MISMATCH",
            "Acting party is not the publisher of the fair's accepted agreement",
        )


@bp.post("/reconciliations/<rid>/accept")
@require_roles("PublisherRep")
def accept_reconciliation(rid):
    recon = get_or_404(db.reconciliations, rid, "Reconciliation")
    _publisher_scope_for_fair(recon["fair_id"])
    validate_body(get_body(), [])
    if recon["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Reconciliation is not in SUBMITTED")
    recon["status"] = "ACCEPTED"
    touch(recon)
    return success(recon)


@bp.post("/reconciliations/<rid>/dispute")
@require_roles("PublisherRep")
def dispute_reconciliation(rid):
    recon = get_or_404(db.reconciliations, rid, "Reconciliation")
    _publisher_scope_for_fair(recon["fair_id"])
    vals = validate_body(get_body(), [("reason", True, v_str)])
    if recon["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Reconciliation is not in SUBMITTED")
    recon["status"] = "DISPUTED"
    recon["dispute_reason"] = vals["reason"]
    touch(recon)
    return success(recon)


# ---------------------------------------------------------------------------
# Return authorizations
# ---------------------------------------------------------------------------

def _parse_ra_lines(raw):
    if not isinstance(raw, list) or len(raw) == 0:
        fail("ERR_VALIDATION", "lines must be a non-empty array")
    parsed = []
    for item in raw:
        if not isinstance(item, dict):
            fail("ERR_VALIDATION", "each return line must be an object")
        unknown = sorted(set(item.keys()) - {"stock_line_id", "qty"})
        if unknown:
            fail("ERR_VALIDATION", "Unknown line field(s): %s" % ", ".join(unknown))
        if "stock_line_id" not in item or not isinstance(item["stock_line_id"], str):
            fail("ERR_VALIDATION", "line stock_line_id must be a string")
        qty = item.get("qty")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            fail("ERR_VALIDATION", "line qty must be a positive integer")
        parsed.append({"stock_line_id": item["stock_line_id"], "qty": qty})
    return parsed


@bp.post("/return-authorizations")
@require_roles("Organizer")
def create_return_authorization():
    data = get_body()
    fair_id = data.get("fair_id")
    if isinstance(fair_id, str) and fair_id not in db.fairs:
        fail("ERR_NOT_FOUND", "fair_id references no existing Fair")
    agreement_id = data.get("agreement_id")
    if isinstance(agreement_id, str) and agreement_id not in db.agreements:
        fail("ERR_NOT_FOUND", "agreement_id references no existing ConsignmentAgreement")
    raw_lines = data.get("lines")
    if isinstance(raw_lines, list):
        for item in raw_lines:
            if isinstance(item, dict):
                sid = item.get("stock_line_id")
                if isinstance(sid, str) and sid not in db.stock_lines:
                    fail("ERR_NOT_FOUND", "line stock_line_id references no existing StockLine")
    vals = validate_body(
        data,
        [
            ("fair_id", True, v_str),
            ("agreement_id", True, v_str),
            ("lines", True, lambda n, v: _parse_ra_lines(v)),
        ],
    )
    agreement = db.agreements[vals["agreement_id"]]
    # Cross-entity state gates (8) run before physical (19) and referential (20).
    if agreement["status"] != "ACCEPTED":
        fail("ERR_AGREEMENT_NOT_ACCEPTED", "The referenced agreement is not ACCEPTED")
    recon = latest_reconciliation(vals["fair_id"])
    if recon is None or recon["status"] not in ("APPROVED", "SUBMITTED", "ACCEPTED"):
        fail(
            "ERR_RECONCILIATION_NOT_APPROVED",
            "The fair's latest reconciliation must be APPROVED, SUBMITTED, or ACCEPTED",
        )
    for ra_line in vals["lines"]:
        line = db.stock_lines[ra_line["stock_line_id"]]
        if line["line_type"] != "FRONTLIST":
            fail("ERR_FIRM_SALE_NOT_RETURNABLE", "BACKLIST lines are firm purchases and cannot be returned")
    if agreement["fair_id"] != vals["fair_id"]:
        fail("ERR_LINE_FAIR_MISMATCH", "Agreement belongs to a different fair")
    ra = new_entity(
        fair_id=vals["fair_id"],
        agreement_id=vals["agreement_id"],
        lines=vals["lines"],
        credit_cents=None,
        status="REQUESTED",
    )
    db.return_authorizations[ra["id"]] = ra
    return success(ra, 201)


@bp.get("/return-authorizations")
@require_roles(*ALL_ROLES)
def list_return_authorizations():
    limit, offset = pagination_params()
    items = list_filtered(
        db.return_authorizations,
        [("fair_id", "fair_id"), ("agreement_id", "agreement_id"), ("status", "status")],
    )
    items, total = page(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/return-authorizations/<rid>")
@require_roles(*ALL_ROLES)
def get_return_authorization(rid):
    return success(get_or_404(db.return_authorizations, rid, "ReturnAuthorization"))


@bp.post("/return-authorizations/<rid>/approve")
@require_roles("PublisherRep")
def approve_return(rid):
    ra = get_or_404(db.return_authorizations, rid, "ReturnAuthorization")
    agreement = db.agreements[ra["agreement_id"]]
    require_scope(agreement["publisher_party_id"])
    validate_body(get_body(), [])
    if ra["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "ReturnAuthorization is not in REQUESTED")
    for ra_line in ra["lines"]:
        line = db.stock_lines[ra_line["stock_line_id"]]
        cumulative = ra_line["qty"]
        for other in db.return_authorizations.values():
            if other["fair_id"] != ra["fair_id"] or other["id"] == ra["id"]:
                continue
            if other["status"] not in ("APPROVED", "SHIPPED", "CREDITED"):
                continue
            for other_line in other["lines"]:
                if other_line["stock_line_id"] == line["id"]:
                    cumulative += other_line["qty"]
        on_hand = line["qty_delivered"] - line["qty_sold"] - line["qty_damaged"]
        if cumulative > on_hand:
            fail(
                "ERR_RETURN_QUANTITY_EXCEEDS_ON_HAND",
                "Cumulative approved return quantity exceeds physical on-hand",
            )
    ra["status"] = "APPROVED"
    touch(ra)
    return success(ra)


@bp.post("/return-authorizations/<rid>/reject")
@require_roles("PublisherRep")
def reject_return(rid):
    ra = get_or_404(db.return_authorizations, rid, "ReturnAuthorization")
    agreement = db.agreements[ra["agreement_id"]]
    require_scope(agreement["publisher_party_id"])
    validate_body(get_body(), [])
    if ra["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "ReturnAuthorization is not in REQUESTED")
    ra["status"] = "REJECTED"
    touch(ra)
    return success(ra)


@bp.post("/return-authorizations/<rid>/ship")
@require_roles("Organizer")
def ship_return(rid):
    ra = get_or_404(db.return_authorizations, rid, "ReturnAuthorization")
    validate_body(get_body(), [])
    if ra["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "ReturnAuthorization is not in APPROVED")
    for ra_line in ra["lines"]:
        line = db.stock_lines[ra_line["stock_line_id"]]
        line["qty_returned_shipped"] += ra_line["qty"]
        recompute_availability(line)
        touch(line)
    ra["status"] = "SHIPPED"
    touch(ra)
    return success(ra)


@bp.post("/return-authorizations/<rid>/confirm-credit")
@require_roles("Organizer")
def confirm_credit(rid):
    ra = get_or_404(db.return_authorizations, rid, "ReturnAuthorization")
    validate_body(get_body(), [])
    if ra["status"] != "SHIPPED":
        fail("ERR_INVALID_STATE", "ReturnAuthorization is not in SHIPPED")
    credit = compute_return_credit(ra)
    ra["credit_cents"] = credit
    for ra_line in ra["lines"]:
        line = db.stock_lines[ra_line["stock_line_id"]]
        line["qty_returned_credited"] += ra_line["qty"]
        touch(line)
    ra["status"] = "CREDITED"
    touch(ra)
    fair = db.fairs[ra["fair_id"]]
    fair["return_credits_cents"] += credit
    touch(fair)
    return success(ra)


# ---------------------------------------------------------------------------
# Profit-share payouts
# ---------------------------------------------------------------------------

@bp.post("/profit-share-payouts")
@require_roles("Organizer")
def create_payout():
    data = get_body()
    fair_id = data.get("fair_id")
    if isinstance(fair_id, str) and fair_id not in db.fairs:
        fail("ERR_NOT_FOUND", "fair_id references no existing Fair")
    vals = validate_body(data, [("fair_id", True, v_str)])
    fair = db.fairs[vals["fair_id"]]
    if fair["status"] != "RECONCILING":
        fail("ERR_INVALID_STATE", "Payout creation requires the fair to be RECONCILING")
    for other in db.payouts.values():
        if other["fair_id"] == fair["id"] and other["status"] in PAYOUT_NON_TERMINAL:
            fail("ERR_DUPLICATE_RESOURCE", "A non-terminal payout already exists for this fair")
    payout = new_entity(
        fair_id=fair["id"],
        school_party_id=fair["school_party_id"],
        net_revenue_cents=None,
        share_cents=None,
        cash_amount_cents=None,
        scrip_amount_cents=None,
        mode=None,
        final_amount_cents=None,
        status="DRAFT",
    )
    db.payouts[payout["id"]] = payout
    return success(payout, 201)


@bp.get("/profit-share-payouts")
@require_roles(*ALL_ROLES)
def list_payouts():
    limit, offset = pagination_params()
    items = list_filtered(
        db.payouts,
        [("fair_id", "fair_id"), ("school_party_id", "school_party_id"), ("status", "status")],
    )
    items, total = page(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/profit-share-payouts/<pid>")
@require_roles(*ALL_ROLES)
def get_payout(pid):
    return success(get_or_404(db.payouts, pid, "ProfitSharePayout"))


@bp.post("/profit-share-payouts/<pid>/calculate")
@require_roles("Organizer")
def calculate_payout(pid):
    payout = get_or_404(db.payouts, pid, "ProfitSharePayout")
    validate_body(get_body(), [])
    if payout["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Payout is not in DRAFT")
    recon = latest_reconciliation(payout["fair_id"])
    if recon is None or recon["status"] != "ACCEPTED":
        fail("ERR_RECONCILIATION_NOT_APPROVED", "The fair's latest reconciliation must be ACCEPTED")
    booking_open = any(
        b["fair_id"] == payout["fair_id"]
        and b["status"] not in ("SETTLED", "CANCELLED", "DECLINED")
        for b in db.bookings.values()
    )
    if booking_open:
        fail("ERR_INVALID_STATE", "Every author booking must be SETTLED, CANCELLED, or DECLINED")
    fair = db.fairs[payout["fair_id"]]
    net, share, cash, scrip = compute_payout(fair)
    payout["net_revenue_cents"] = net
    payout["share_cents"] = share
    payout["cash_amount_cents"] = cash
    payout["scrip_amount_cents"] = scrip
    payout["status"] = "CALCULATED"
    touch(payout)
    return success(payout)


@bp.post("/profit-share-payouts/<pid>/recalculate")
@require_roles("Organizer")
def recalculate_payout(pid):
    payout = get_or_404(db.payouts, pid, "ProfitSharePayout")
    validate_body(get_body(), [])
    if payout["status"] != "CALCULATED":
        fail("ERR_INVALID_STATE", "Payout is not in CALCULATED")
    payout["net_revenue_cents"] = None
    payout["share_cents"] = None
    payout["cash_amount_cents"] = None
    payout["scrip_amount_cents"] = None
    payout["status"] = "DRAFT"
    touch(payout)
    return success(payout)


@bp.post("/profit-share-payouts/<pid>/approve")
@require_roles("SchoolCoordinator")
def approve_payout(pid):
    payout = get_or_404(db.payouts, pid, "ProfitSharePayout")
    require_scope(payout["school_party_id"])
    vals = validate_body(get_body(), [("mode", True, v_enum("CASH", "SCRIP"))])
    if payout["status"] != "CALCULATED":
        fail("ERR_INVALID_STATE", "Payout is not in CALCULATED")
    payout["mode"] = vals["mode"]
    payout["final_amount_cents"] = (
        payout["cash_amount_cents"] if vals["mode"] == "CASH" else payout["scrip_amount_cents"]
    )
    payout["status"] = "APPROVED"
    touch(payout)
    return success(payout)


@bp.post("/profit-share-payouts/<pid>/pay")
@require_roles("Organizer")
def pay_payout(pid):
    payout = get_or_404(db.payouts, pid, "ProfitSharePayout")
    validate_body(get_body(), [])
    if payout["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Payout is not in APPROVED")
    payout["status"] = "PAID"
    touch(payout)
    return success(payout)


# ---------------------------------------------------------------------------
# Media blasts
# ---------------------------------------------------------------------------

@bp.post("/media-blasts")
@require_roles("Organizer")
def create_blast():
    data = get_body()
    fair_id = data.get("fair_id")
    if isinstance(fair_id, str) and fair_id not in db.fairs:
        fail("ERR_NOT_FOUND", "fair_id references no existing Fair")
    vals = validate_body(
        data,
        [
            ("fair_id", True, v_str),
            ("channel", True, v_enum("LOCAL_PAPER", "RADIO", "SOCIAL", "SCHOOL_NEWSLETTER")),
            ("spend_cents", True, v_int(0)),
            ("embargo_until", True, v_datetime),
            ("content_summary", True, v_str),
        ],
    )
    from db import fmt_dt

    blast = new_entity(
        fair_id=vals["fair_id"],
        channel=vals["channel"],
        spend_cents=vals["spend_cents"],
        embargo_until=fmt_dt(vals["embargo_until"]),
        content_summary=vals["content_summary"],
        status="DRAFT",
    )
    db.media_blasts[blast["id"]] = blast
    return success(blast, 201)


@bp.get("/media-blasts")
@require_roles(*ALL_ROLES)
def list_blasts():
    limit, offset = pagination_params()
    items = list_filtered(
        db.media_blasts,
        [("fair_id", "fair_id"), ("status", "status"), ("channel", "channel")],
    )
    items, total = page(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/media-blasts/<bid>")
@require_roles(*ALL_ROLES)
def get_blast(bid):
    return success(get_or_404(db.media_blasts, bid, "MediaBlast"))


@bp.post("/media-blasts/<bid>/submit")
@require_roles("Organizer")
def submit_blast(bid):
    blast = get_or_404(db.media_blasts, bid, "MediaBlast")
    validate_body(get_body(), [])
    if blast["status"] not in ("DRAFT", "REJECTED"):
        fail("ERR_INVALID_STATE", "Blast cannot be submitted from its current state")
    fair = db.fairs[blast["fair_id"]]
    if fair["status"] not in ("DRAFT", "SCHEDULED", "STOCKING", "OPEN"):
        fail("ERR_INVALID_STATE", "Blast's fair must be in DRAFT, SCHEDULED, STOCKING, or OPEN")
    blast["status"] = "PENDING_APPROVAL"
    touch(blast)
    return success(blast)


@bp.post("/media-blasts/<bid>/approve")
@require_roles("SchoolCoordinator")
def approve_blast(bid):
    blast = get_or_404(db.media_blasts, bid, "MediaBlast")
    fair = db.fairs[blast["fair_id"]]
    require_scope(fair["school_party_id"])
    validate_body(get_body(), [])
    if blast["status"] != "PENDING_APPROVAL":
        fail("ERR_INVALID_STATE", "Blast is not in PENDING_APPROVAL")
    committed = sum(
        b["spend_cents"]
        for b in db.media_blasts.values()
        if b["fair_id"] == fair["id"] and b["status"] in ("APPROVED", "PUBLISHED")
    )
    if committed + blast["spend_cents"] > fair["promo_budget_cents"]:
        fail("ERR_PROMO_BUDGET_EXCEEDED", "Approving this blast would exceed the promo budget")
    blast["status"] = "APPROVED"
    touch(blast)
    return success(blast)


@bp.post("/media-blasts/<bid>/reject")
@require_roles("SchoolCoordinator")
def reject_blast(bid):
    blast = get_or_404(db.media_blasts, bid, "MediaBlast")
    fair = db.fairs[blast["fair_id"]]
    require_scope(fair["school_party_id"])
    validate_body(get_body(), [])
    if blast["status"] != "PENDING_APPROVAL":
        fail("ERR_INVALID_STATE", "Blast is not in PENDING_APPROVAL")
    blast["status"] = "REJECTED"
    touch(blast)
    return success(blast)


@bp.post("/media-blasts/<bid>/publish")
@require_roles("Organizer")
def publish_blast(bid):
    blast = get_or_404(db.media_blasts, bid, "MediaBlast")
    validate_body(get_body(), [])
    if blast["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Blast is not in APPROVED")
    if db.logical_clock < parse_dt_loose(blast["embargo_until"]):
        fail("ERR_EMBARGO_ACTIVE", "The embargo has not yet lifted")
    blast["status"] = "PUBLISHED"
    touch(blast)
    return success(blast)
