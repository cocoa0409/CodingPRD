"""Deal endpoints: list, get, propose-terms (OCC), creator-respond,
brand-respond (activation), terminate (full cascade), disputes (raise),
deliverables (plan/list), performance reports (submit/list)."""

import datetime as _dt

from flask import Blueprint, request

import db
import errors as err
import response as resp
from middleware import require_roles, require_owner
from services import calc, helpers as H, lifecycle

bp = Blueprint("deals", __name__)

DEAL_TERMINAL = {"COMPLETED", "TERMINATED"}


@bp.route("/deals", methods=["GET"])
@require_roles("BrandManager", "TalentManager", "FinanceAdmin", "Creator",
               "Brand")
def list_deals(actor):
    items = list(db.deals.values())
    # Entity-backed callers see only their own deals.
    if actor.role == "Creator":
        items = [d for d in items if d["creator_id"] == actor.user_id]
    elif actor.role == "Brand":
        items = [d for d in items if d["brand_id"] == actor.user_id]

    pitch_id = request.args.get("pitch_id")
    brief_id = request.args.get("brief_id")
    creator_id = request.args.get("creator_id")
    brand_id = request.args.get("brand_id")
    status = request.args.get("status")
    if pitch_id is not None:
        items = [d for d in items if d["pitch_id"] == pitch_id]
    if brief_id is not None:
        items = [d for d in items if d["brief_id"] == brief_id]
    if creator_id is not None:
        items = [d for d in items if d["creator_id"] == creator_id]
    if brand_id is not None:
        items = [d for d in items if d["brand_id"] == brand_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return resp.paginate(items, request.args)


@bp.route("/deals/<did>", methods=["GET"])
@require_roles("BrandManager", "TalentManager", "FinanceAdmin", "Creator",
               "Brand", "ComplianceOfficer")
def get_deal(actor, did):
    deal = H.get_or_404(db.deals, did, "deal")
    if actor.role == "Creator":
        require_owner(actor, deal["creator_id"], "deal")
    elif actor.role == "Brand":
        require_owner(actor, deal["brand_id"], "deal")
    return resp.ok(deal)


@bp.route("/deals/<did>/propose-terms", methods=["POST"])
@require_roles("BrandManager")
def propose_terms(actor, did):
    deal = H.get_or_404(db.deals, did, "deal")
    payload = H.body()
    H.req_fields(payload, ["fee_base_cents", "expected_deal_version"])
    fee_base = H.require_int(payload, "fee_base_cents", minimum=1)

    expected = payload.get("expected_deal_version")
    if not H.is_int(expected):
        raise err.validation("expected_deal_version must be an integer")
    if expected != deal["version"]:
        raise err.stale_version(
            "expected_deal_version does not match the deal's current version")

    if deal["status"] in DEAL_TERMINAL:
        raise err.already_terminal(f"Deal is {deal['status']}")
    if deal["status"] != "DRAFT":
        raise err.invalid_state("Terms can be proposed only from DRAFT")

    deal["fee_base_cents"] = fee_base
    deal["terms_version"] += 1
    deal["status"] = "PENDING_CREATOR"
    H.touch(deal)
    return resp.ok(deal)


@bp.route("/deals/<did>/creator-respond", methods=["POST"])
@require_roles("Creator")
def creator_respond(actor, did):
    deal = H.get_or_404(db.deals, did, "deal")
    require_owner(actor, deal["creator_id"], "deal")
    payload = H.body()
    H.req_fields(payload, ["action"])
    action = H.require_enum(payload, "action", {"ACCEPT", "COUNTER", "DECLINE"})

    if deal["status"] in DEAL_TERMINAL:
        raise err.already_terminal(f"Deal is {deal['status']}")
    if deal["status"] != "PENDING_CREATOR":
        raise err.invalid_state(
            "Creator response requires deal PENDING_CREATOR")

    if action == "ACCEPT":
        deal["status"] = "PENDING_BRAND"
        H.touch(deal)
        return resp.ok(deal)
    if action == "COUNTER":
        if deal["negotiation_rounds"] >= H.MAX_DEAL_NEGOTIATION_ROUNDS:
            raise err.ApiError(err.ERR_NEGOTIATION_LIMIT_EXCEEDED,
                               "Deal negotiation round cap reached", 422)
        deal["negotiation_rounds"] += 1
        deal["status"] = "DRAFT"
        H.touch(deal)
        return resp.ok(deal)
    # DECLINE
    deal["status"] = "TERMINATED"
    H.touch(deal)
    H.recompute_slots_committed(deal["brief_id"])
    return resp.ok(deal)


def _exclusivity_conflict(deal, candidate_start, candidate_end):
    """True when another ACTIVE deal of the same creator in the same non-NONE
    category has a half-open window overlapping [candidate_start,
    candidate_end). Adjacency (end == start) is NOT a conflict."""
    if deal["exclusivity_category"] == "NONE":
        return False
    for other in db.deals.values():
        if other["id"] == deal["id"]:
            continue
        if other["creator_id"] != deal["creator_id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if other["exclusivity_category"] != deal["exclusivity_category"]:
            continue
        o_start = db.parse_iso(other.get("exclusive_window_start") or "")
        o_end = db.parse_iso(other.get("exclusive_window_end") or "")
        if o_start is None or o_end is None:
            continue
        # Half-open overlap: start1 < end2 and start2 < end1.
        if candidate_start < o_end and o_start < candidate_end:
            return True
    return False


@bp.route("/deals/<did>/brand-respond", methods=["POST"])
@require_roles("Brand")
def brand_respond(actor, did):
    deal = H.get_or_404(db.deals, did, "deal")
    require_owner(actor, deal["brand_id"], "deal")
    payload = H.body()
    H.req_fields(payload, ["action"])
    action = H.require_enum(payload, "action", {"ACCEPT", "COUNTER", "DECLINE"})

    if deal["status"] in DEAL_TERMINAL:
        raise err.already_terminal(f"Deal is {deal['status']}")
    if deal["status"] != "PENDING_BRAND":
        raise err.invalid_state("Brand response requires deal PENDING_BRAND")

    if action == "COUNTER":
        if deal["negotiation_rounds"] >= H.MAX_DEAL_NEGOTIATION_ROUNDS:
            raise err.ApiError(err.ERR_NEGOTIATION_LIMIT_EXCEEDED,
                               "Deal negotiation round cap reached", 422)
        deal["negotiation_rounds"] += 1
        deal["status"] = "DRAFT"
        H.touch(deal)
        return resp.ok(deal)

    if action == "DECLINE":
        deal["status"] = "TERMINATED"
        H.touch(deal)
        H.recompute_slots_committed(deal["brief_id"])
        return resp.ok(deal)

    # action == "ACCEPT" — activation. Business order per PRD §3.4:
    # exclusivity scan, then credit hold.
    now = db.get_clock()
    candidate_start = now
    candidate_end = now + _dt.timedelta(days=int(deal["exclusivity_days"]))
    if _exclusivity_conflict(deal, candidate_start, candidate_end):
        raise err.ApiError(err.ERR_EXCLUSIVITY_CONFLICT,
                           "Activation overlaps an existing exclusivity window",
                           409)

    brand = db.brands.get(deal["brand_id"])
    if brand is not None and brand["credit_hold"]:
        raise err.ApiError(err.ERR_BRAND_CREDIT_HOLD,
                           "Brand is on credit hold", 402)

    creator = db.creators.get(deal["creator_id"])
    brief = db.briefs.get(deal["brief_id"])
    rate_flat = int(creator.get("rate_card_flat_cents") or 0)
    fee_total = calc.deal_fee(rate_flat,
                              int(brief["deliverables_per_slot"]),
                              int(deal["usage_rights_days"]),
                              bool(deal["whitelisting"]),
                              deal["exclusivity_category"])

    deal["fee_total_cents"] = fee_total
    deal["activated_at"] = db.iso_format(now)
    if deal["exclusivity_category"] == "NONE":
        deal["exclusive_window_start"] = None
        deal["exclusive_window_end"] = None
    else:
        deal["exclusive_window_start"] = db.iso_format(candidate_start)
        deal["exclusive_window_end"] = db.iso_format(candidate_end)
    deal["status"] = "ACTIVE"
    H.touch(deal)
    return resp.ok(deal)


@bp.route("/deals/<did>/terminate", methods=["POST"])
@require_roles("BrandManager")
def terminate_deal(actor, did):
    deal = H.get_or_404(db.deals, did, "deal")
    payload = H.body()
    H.req_fields(payload, ["reason"])
    H.require_str(payload, "reason")

    if deal["status"] in DEAL_TERMINAL:
        raise err.already_terminal(f"Deal is {deal['status']}")
    if deal["status"] != "ACTIVE":
        raise err.invalid_state("Only an ACTIVE deal can be terminated")

    deal["status"] = "TERMINATED"
    H.touch(deal)
    lifecycle.terminate_deal_cascade(deal)
    return resp.ok(deal)


@bp.route("/deals/<did>/disputes", methods=["POST"])
@require_roles("Creator", "Brand")
def raise_dispute(actor, did):
    deal = H.get_or_404(db.deals, did, "deal")

    # Priority 3: entity-backed caller must own the deal.
    if actor.role == "Creator":
        require_owner(actor, deal["creator_id"], "deal")
        raised_by_role = "CREATOR"
    else:
        require_owner(actor, deal["brand_id"], "deal")
        raised_by_role = "BRAND"

    payload = H.body()
    H.req_fields(payload, ["reason", "note"])
    reason = H.require_enum(payload, "reason", H.DISPUTE_REASON_ENUM)
    note = H.require_str(payload, "note")
    deliverable_id = H.opt_str(payload, "deliverable_id", default=None)
    if reason == "RESHOOT_REQUEST" and deliverable_id is None:
        raise err.validation(
            "deliverable_id is required when reason is RESHOOT_REQUEST")

    if deal["status"] in DEAL_TERMINAL and deal["status"] != "COMPLETED":
        raise err.already_terminal(f"Deal is {deal['status']}")
    if deal["status"] not in ("ACTIVE", "COMPLETED"):
        raise err.invalid_state(
            "Disputes may be raised only on ACTIVE or COMPLETED deals")

    if deliverable_id is not None:
        d = H.get_or_404(db.deliverables, deliverable_id, "deliverable")
        if d["deal_id"] != deal["id"]:
            raise err.validation(
                "deliverable_id does not belong to this deal")

    dispute = H.new_entity()
    dispute.update({
        "deal_id": deal["id"],
        "deliverable_id": deliverable_id,
        "raised_by_role": raised_by_role,
        "reason": reason,
        "note": note,
        "status": "OPEN",
        "remedy": None,
        "reduction_pct": None,
        "resolution_note": None,
    })
    db.disputes[dispute["id"]] = dispute

    # Deal ACTIVE -> IN_DISPUTE; COMPLETED stays COMPLETED. Either way the
    # deal observes the mutation (PRD §2.4/§3.9) and payouts are held.
    if deal["status"] == "ACTIVE":
        deal["status"] = "IN_DISPUTE"
    H.touch(deal)
    lifecycle.hold_payouts_of_deal(deal["id"])

    return resp.created(dispute)


@bp.route("/deals/<did>/deliverables", methods=["POST"])
@require_roles("BrandManager")
def plan_deliverable(actor, did):
    deal = H.get_or_404(db.deals, did, "deal")
    payload = H.body()
    H.req_fields(payload, ["platform", "due_date", "scheduled_publish_date"])
    platform = H.require_enum(payload, "platform", H.PLATFORM_ENUM)
    due_date = H.require_dt(payload, "due_date")
    scheduled = H.require_dt(payload, "scheduled_publish_date")

    if deal["status"] in DEAL_TERMINAL:
        raise err.already_terminal(f"Deal is {deal['status']}")
    if deal["status"] != "ACTIVE":
        raise err.invalid_state(
            "Deliverables can be planned only on an ACTIVE deal")

    # Priority 13: publish gap vs siblings.
    gap = _dt.timedelta(hours=H.MIN_PUBLISH_GAP_HOURS)
    for sib in db.deliverables.values():
        if sib["deal_id"] != deal["id"] or sib["status"] == "CANCELLED":
            continue
        sib_sched = db.parse_iso(sib["scheduled_publish_date"])
        if sib_sched is None:
            continue
        if abs(scheduled - sib_sched) < gap:
            raise err.ApiError(err.ERR_PUBLISH_GAP_VIOLATION,
                               "scheduled_publish_date within "
                               f"{H.MIN_PUBLISH_GAP_HOURS}h of a sibling", 409)

    # Priority 14: deliverable count.
    brief = db.briefs.get(deal["brief_id"])
    per_slot = int(brief["deliverables_per_slot"]) if brief else 0
    existing = [d for d in db.deliverables.values()
                if d["deal_id"] == deal["id"] and d["status"] != "CANCELLED"]
    if len(existing) >= per_slot:
        raise err.ApiError(err.ERR_DELIVERABLE_COUNT_EXCEEDED,
                           "Deal already has deliverables_per_slot "
                           "non-CANCELLED deliverables", 422)

    deliverable = H.new_entity()
    deliverable.update({
        "deal_id": deal["id"],
        "platform": platform,
        "due_date": db.iso_format(due_date),
        "scheduled_publish_date": db.iso_format(scheduled),
        "content_url": None,
        "published_at": None,
        "status": "PENDING_SUBMISSION",
        "revision_rounds_used": 0,
        "reshoot_count": 0,
        "reviewed_by_user_id": None,
        "verified_at": None,
    })
    db.deliverables[deliverable["id"]] = deliverable
    return resp.created(deliverable)


@bp.route("/deals/<did>/deliverables", methods=["GET"])
@require_roles("BrandManager", "TalentManager", "Creator", "Brand",
               "ComplianceOfficer", "FinanceAdmin")
def list_deal_deliverables(actor, did):
    deal = H.get_or_404(db.deals, did, "deal")
    if actor.role == "Creator":
        require_owner(actor, deal["creator_id"], "deal")
    elif actor.role == "Brand":
        require_owner(actor, deal["brand_id"], "deal")
    items = [d for d in db.deliverables.values() if d["deal_id"] == did]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return resp.paginate(items, request.args)


def _periods_overlap(a_start, a_end, b_start, b_end):
    """Any intersection at all (periods are start-inclusive, end-exclusive)."""
    return a_start < b_end and b_start < a_end


@bp.route("/deals/<did>/performance-reports", methods=["POST"])
@require_roles("BrandManager")
def submit_report(actor, did):
    deal = H.get_or_404(db.deals, did, "deal")
    payload = H.body()
    H.req_fields(payload, ["period_start", "period_end", "views", "likes",
                           "comments", "shares", "expected_deal_version"])
    period_start = H.require_dt(payload, "period_start")
    period_end = H.require_dt(payload, "period_end")
    views = H.require_int(payload, "views", minimum=0)
    likes = H.require_int(payload, "likes", minimum=0)
    comments = H.require_int(payload, "comments", minimum=0)
    shares = H.require_int(payload, "shares", minimum=0)

    if period_end <= period_start:
        raise err.validation("period_end must be later than period_start")

    expected = payload.get("expected_deal_version")
    if not H.is_int(expected):
        raise err.validation("expected_deal_version must be an integer")
    if expected != deal["version"]:
        raise err.stale_version(
            "expected_deal_version does not match the deal's current version")

    if deal["status"] in ("TERMINATED",):
        raise err.already_terminal(f"Deal is {deal['status']}")
    if deal["status"] not in ("ACTIVE", "COMPLETED"):
        raise err.invalid_state(
            "Performance reports require an ACTIVE or COMPLETED deal")

    # Priority 20: overlapping FINAL report of the same deal.
    for r in db.performance_reports.values():
        if r["deal_id"] != deal["id"] or r["status"] != "FINAL":
            continue
        r_start = db.parse_iso(r["period_start"])
        r_end = db.parse_iso(r["period_end"])
        if r_start and r_end and _periods_overlap(period_start, period_end,
                                                  r_start, r_end):
            raise err.ApiError(err.ERR_DUPLICATE_REPORT_PERIOD,
                               "Report period overlaps a FINAL report of the "
                               "same deal", 422)

    report = H.new_entity()
    report.update({
        "deal_id": deal["id"],
        "period_start": db.iso_format(period_start),
        "period_end": db.iso_format(period_end),
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "audited_views": None,
        "audited_engagements": None,
        "status": "REPORTED",
        "provisional_bonus_cents": calc.performance_bonus(
            views, likes + comments + shares),
        "final_bonus_cents": None,
    })
    db.performance_reports[report["id"]] = report

    # Supersede overlapping REPORTED reports of the same deal.
    for r in db.performance_reports.values():
        if r["id"] == report["id"]:
            continue
        if r["deal_id"] != deal["id"] or r["status"] != "REPORTED":
            continue
        r_start = db.parse_iso(r["period_start"])
        r_end = db.parse_iso(r["period_end"])
        if r_start and r_end and _periods_overlap(period_start, period_end,
                                                  r_start, r_end):
            r["status"] = "SUPERSEDED"
            H.touch(r)

    # Submission increments the deal's version.
    H.touch(deal)

    return resp.created(report)


@bp.route("/deals/<did>/performance-reports", methods=["GET"])
@require_roles("BrandManager", "TalentManager", "Creator", "Brand",
               "FinanceAdmin")
def list_reports(actor, did):
    deal = H.get_or_404(db.deals, did, "deal")
    if actor.role == "Creator":
        require_owner(actor, deal["creator_id"], "deal")
    elif actor.role == "Brand":
        require_owner(actor, deal["brand_id"], "deal")
    items = [r for r in db.performance_reports.values() if r["deal_id"] == did]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return resp.paginate(items, request.args)


@bp.route("/deals/<did>/invoices", methods=["POST"])
@require_roles("FinanceAdmin")
def create_invoice(actor, did):
    deal = H.get_or_404(db.deals, did, "deal")
    H.body()  # payload must be a JSON object when present

    if deal["status"] == "TERMINATED":
        raise err.already_terminal("Deal is TERMINATED")
    if deal["status"] not in ("ACTIVE", "COMPLETED"):
        raise err.invalid_state(
            "Invoice creation requires an ACTIVE or COMPLETED deal")
    has_verified = any(
        d["deal_id"] == deal["id"] and d["status"] == "VERIFIED"
        for d in db.deliverables.values())
    if not has_verified:
        raise err.invalid_state(
            "Invoice creation requires at least one VERIFIED deliverable")

    # Priority 21: one non-VOID invoice per deal.
    for inv in db.invoices.values():
        if inv["deal_id"] == deal["id"] and inv["status"] != "VOID":
            raise err.ApiError(err.ERR_INVOICE_ALREADY_EXISTS,
                               "Deal already has a non-VOID invoice", 409)

    H.recompute_bonus_accrued(deal["id"])
    deal = db.deals[deal["id"]]
    fee_line, service_line, bonus_line, total = calc.invoice_lines(
        int(deal["fee_total_cents"]), deal.get("reduction_pct", 0),
        int(deal.get("bonus_accrued_cents") or 0))

    billed_report_ids = [
        r["id"] for r in db.performance_reports.values()
        if r["deal_id"] == deal["id"] and r["status"] == "FINAL"
    ]

    invoice = H.new_entity()
    invoice.update({
        "deal_id": deal["id"],
        "brand_id": deal["brand_id"],
        "status": "DRAFT",
        "fee_line_cents": fee_line,
        "service_line_cents": service_line,
        "bonus_line_cents": bonus_line,
        "total_cents": total,
        "late_fee_cents": 0,
        "issued_at": None,
        "due_date": None,
        "paid_at": None,
        "issued_by_user_id": None,
        "void_reason": None,
        "billed_report_ids": billed_report_ids,
    })
    db.invoices[invoice["id"]] = invoice
    return resp.created(invoice)
