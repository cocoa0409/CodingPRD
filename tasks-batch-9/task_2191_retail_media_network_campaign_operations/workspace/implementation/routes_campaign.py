"""Campaign construction, review and the delivery dimension (PRD 3.3)."""
from flask import Blueprint

from core import F, fail, insert, lookup, new_row, now, ok, rows, touch
import derive as D
import helpers as H
from guard import guard

bp = Blueprint("campaigns", __name__)

WRITE_ROLES = ("NetworkAdmin", "AccountManager", "AdvertiserUser")
READ_ROLES = ("NetworkAdmin", "AccountManager", "MeasurementAnalyst",
              "BillingOps", "AdvertiserUser")
CHANNEL_MIX = ("ONSITE_ONLY", "OFFSITE_ONLY", "OMNI")
PAUSE_REASONS = ("NONE", "OUT_OF_STOCK", "MANUAL", "BUDGET_EXHAUSTED",
                 "CATALOG_RESTRICTED")

DELIVERY_TRANSITIONS = {
    "submit": {"DRAFT": "PENDING_REVIEW"},
    "APPROVE": {"PENDING_REVIEW": "SCHEDULED"},
    "REJECT": {"PENDING_REVIEW": "REJECTED"},
    "activate": {"SCHEDULED": "DELIVERING"},
    "pause": {"DELIVERING": "PAUSED"},
    "resume": {"PAUSED": "DELIVERING"},
    "complete": {"DELIVERING": "COMPLETED", "PAUSED": "COMPLETED"},
    "archive": {"COMPLETED": "ARCHIVED", "SCHEDULED": "ARCHIVED"},
}

LIST_FILTERS = (
    ("advertiser_id", "advertiser_id", "string"),
    ("budget_plan_id", "budget_plan_id", "string"),
    ("delivery_status", "delivery_status", "string"),
    ("billing_status", "billing_status", "string"),
    ("channel_mix", "channel_mix", "string"),
)


# ---------------------------------------------------------------------------
def _channel_of_line_item(li):
    slot = D.slot_of_line_item(li)
    return slot["channel"] if slot else None


def _channel_mix_check(camp, channel_mix, require_coverage):
    """Rejection check 64."""
    channels = set(_channel_of_line_item(l)
                   for l in D.line_items_of_campaign(camp["id"]))
    if channel_mix == "ONSITE_ONLY" and "OFFSITE" in channels:
        fail("ERR_OFFSITE_CHANNEL_MISMATCH",
             "An ONSITE_ONLY campaign may hold no off-site line item.")
    if channel_mix == "OFFSITE_ONLY" and "ONSITE" in channels:
        fail("ERR_OFFSITE_CHANNEL_MISMATCH",
             "An OFFSITE_ONLY campaign may hold no on-site line item.")
    if require_coverage:
        if channel_mix != "ONSITE_ONLY" and "OFFSITE" not in channels:
            fail("ERR_OFFSITE_CHANNEL_MISMATCH",
                 "At least one off-site line item is required.")
        if channel_mix == "OMNI" and "ONSITE" not in channels:
            fail("ERR_OFFSITE_CHANNEL_MISMATCH",
                 "An OMNI campaign needs a line item on each channel.")


def _containment(plan, start, end):
    """Rejection check 47."""
    if start is None or end is None or start >= end:
        fail("ERR_FLIGHT_WINDOW_OUTSIDE_PLAN",
             "flight_start_at must be strictly before flight_end_at.")
    if start < plan["window_start_at"] or end > plan["window_end_at"]:
        fail("ERR_FLIGHT_WINDOW_OUTSIDE_PLAN",
             "The campaign flight must lie inside the plan window.")


def _caps(adv, allocated, daily_cap):
    """Rejection check 71."""
    if daily_cap > allocated:
        fail("ERR_CAP_EXCEEDS_PARENT_LIMIT",
             "daily_cap_cents may not exceed allocated_budget_cents.")
    if adv["service_model"] == "SELF_SERVE" and \
            daily_cap > adv["self_serve_daily_spend_cap_cents"]:
        fail("ERR_CAP_EXCEEDS_PARENT_LIMIT",
             "daily_cap_cents may not exceed the self-serve daily cap.")


# ---------------------------------------------------------------------------
@bp.post("/rmn/campaigns")
def create_campaign():
    specs = (
        F("advertiser_id", "string", required=True),
        F("budget_plan_id", "string", required=True),
        F("name", "string", required=True),
        F("channel_mix", "enum", required=True, enum=CHANNEL_MIX),
        F("flight_start_at", "datetime", required=True),
        F("flight_end_at", "datetime", required=True),
        F("allocated_budget_cents", "integer", required=True, minimum=100000),
        F("pacing_mode", "enum", enum=("EVEN", "ACCELERATED"),
          default="EVEN", has_default=True),
        F("daily_cap_cents", "integer", required=True, minimum=1000),
        F("attribution_model", "enum", enum=("LAST_TOUCH", "FRACTIONAL"),
          default="LAST_TOUCH", has_default=True),
        F("attribution_window_days", "integer", minimum=1, maximum=30,
          default=14, has_default=True),
    )
    ctx = guard(WRITE_ROLES, body_specs=specs,
                body_refs=(("advertiser", "advertiser_id"),
                           ("budget_plan", "budget_plan_id")),
                mutating=True)
    data = ctx.data
    adv = ctx.get("advertiser")
    plan = ctx.get("budget_plan")
    _containment(plan, data["flight_start_at"], data["flight_end_at"])
    if plan["advertiser_id"] != data["advertiser_id"]:
        fail("ERR_CROSS_ADVERTISER_REFERENCE",
             "The funding plan belongs to another advertiser.")
    _caps(adv, data["allocated_budget_cents"], data["daily_cap_cents"])

    row = new_row()
    row.update({
        "advertiser_id": data["advertiser_id"],
        "budget_plan_id": data["budget_plan_id"],
        "name": data["name"],
        "channel_mix": data["channel_mix"],
        "delivery_status": "DRAFT",
        "billing_status": "UNBILLED",
        "flight_start_at": data["flight_start_at"],
        "flight_end_at": data["flight_end_at"],
        "pacing_mode": data["pacing_mode"],
        "daily_cap_cents": data["daily_cap_cents"],
        "allocated_budget_cents": data["allocated_budget_cents"],
        "attribution_model": data["attribution_model"],
        "attribution_window_days": data["attribution_window_days"],
        "offsite_reported_spend_cents": 0,
        "pacing_index": 0.0,
        "review_decided_by_user_id": None,
        "submitted_for_review_by_user_id": None,
    })
    insert("campaign", row)
    return ok(D.ser_campaign(row), 201)


@bp.get("/rmn/campaigns")
def list_campaigns():
    ctx = guard(READ_ROLES, paginated=True)
    return H.respond_list(ctx, "campaign", rows("campaign"), LIST_FILTERS,
                          owner_kind="campaign")


@bp.get("/rmn/campaigns/<cid>")
def read_campaign(cid):
    ctx = guard(READ_ROLES, path_refs=(("campaign", cid),))
    return ok(D.ser_campaign(ctx.get("campaign")))


@bp.patch("/rmn/campaigns/<cid>")
def patch_campaign(cid):
    specs = (
        F("name", "string"),
        F("flight_start_at", "datetime"),
        F("flight_end_at", "datetime"),
        F("allocated_budget_cents", "integer", minimum=100000),
        F("pacing_mode", "enum", enum=("EVEN", "ACCELERATED")),
        F("daily_cap_cents", "integer", minimum=1000),
        F("attribution_model", "enum", enum=("LAST_TOUCH", "FRACTIONAL")),
        F("attribution_window_days", "integer", minimum=1, maximum=30),
        F("channel_mix", "enum", enum=CHANNEL_MIX),
    )
    ctx = guard(WRITE_ROLES, path_refs=(("campaign", cid),), body_specs=specs,
                mutating=True)
    camp = ctx.get("campaign")
    adv = ctx.get("advertiser")
    plan = D.plan_of_campaign(camp)
    if camp["delivery_status"] not in ("DRAFT", "PENDING_REVIEW"):
        fail("ERR_INVALID_CAMPAIGN_TRANSITION",
             "A campaign in %s may not be amended." % camp["delivery_status"])
    data = ctx.data
    start = data.get("flight_start_at", camp["flight_start_at"])
    end = data.get("flight_end_at", camp["flight_end_at"])
    allocated = data.get("allocated_budget_cents", camp["allocated_budget_cents"])
    daily_cap = data.get("daily_cap_cents", camp["daily_cap_cents"])
    channel_mix = data.get("channel_mix", camp["channel_mix"])
    _containment(plan, start, end)
    _caps(adv, allocated, daily_cap)
    _channel_mix_check(camp, channel_mix, False)

    camp["name"] = data.get("name", camp["name"])
    camp["flight_start_at"] = start
    camp["flight_end_at"] = end
    camp["allocated_budget_cents"] = allocated
    camp["pacing_mode"] = data.get("pacing_mode", camp["pacing_mode"])
    camp["daily_cap_cents"] = daily_cap
    camp["attribution_model"] = data.get("attribution_model",
                                         camp["attribution_model"])
    camp["attribution_window_days"] = data.get("attribution_window_days",
                                               camp["attribution_window_days"])
    camp["channel_mix"] = channel_mix
    touch(camp)
    return ok(D.ser_campaign(camp))


@bp.post("/rmn/campaigns/<cid>/submit-for-review")
def submit_for_review(cid):
    specs = (F("submission_note", "string"),)
    ctx = guard(WRITE_ROLES, path_refs=(("campaign", cid),), body_specs=specs,
                mutating=True)
    camp = ctx.get("campaign")
    plan = D.plan_of_campaign(camp)
    if plan["plan_status"] not in ("APPROVED", "ACTIVE"):
        fail("ERR_PLAN_NOT_FUNDABLE",
             "The funding plan is %s." % plan["plan_status"])
    target = H.require_transition(camp["delivery_status"],
                                  DELIVERY_TRANSITIONS["submit"],
                                  "ERR_INVALID_CAMPAIGN_TRANSITION",
                                  "delivery_status")
    ready = [l for l in D.line_items_of_campaign(camp["id"])
             if l["line_item_status"] in ("PENDING_ELIGIBILITY", "ELIGIBLE")]
    if not ready:
        fail("ERR_LINE_ITEM_INVALID_STATE",
             "At least one line item must be pending eligibility or eligible.")
    _channel_mix_check(camp, camp["channel_mix"], True)
    if camp["allocated_budget_cents"] > D.plan_available(plan):
        fail("ERR_PLAN_BUDGET_INSUFFICIENT",
             "allocated_budget_cents exceeds the plan's available_cents.")
    camp["submitted_for_review_by_user_id"] = ctx.user_id
    camp["delivery_status"] = target
    touch(camp)
    return ok(D.ser_campaign(camp))


@bp.post("/rmn/campaigns/<cid>/review-decision")
def review_decision(cid):
    specs = (
        F("decision", "enum", required=True, enum=("APPROVE", "REJECT")),
        F("decision_note", "string"),
    )
    ctx = guard(("NetworkAdmin", "AccountManager"),
                path_refs=(("campaign", cid),), body_specs=specs,
                mutating=True)
    camp = ctx.get("campaign")
    adv = ctx.get("advertiser")
    plan = D.plan_of_campaign(camp)
    decision = ctx.data["decision"]
    if adv["onboarding_status"] != "ACTIVE":
        fail("ERR_ADVERTISER_NOT_ACTIVE",
             "The advertiser is %s." % adv["onboarding_status"])
    target = H.require_transition(camp["delivery_status"],
                                  DELIVERY_TRANSITIONS[decision],
                                  "ERR_INVALID_CAMPAIGN_TRANSITION",
                                  "delivery_status")
    if ctx.user_id == camp["submitted_for_review_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The operator that submitted the campaign may not decide it.")
    if decision == "APPROVE" and now() >= camp["flight_end_at"]:
        fail("ERR_INVALID_CAMPAIGN_TRANSITION",
             "The campaign flight has already ended.")

    camp["review_decided_by_user_id"] = ctx.user_id
    camp["delivery_status"] = target
    touch(camp)
    if decision == "REJECT":
        for li in D.line_items_of_campaign(camp["id"]):
            if li["line_item_status"] in ("DRAFT", "PENDING_ELIGIBILITY",
                                          "ELIGIBLE"):
                li["line_item_status"] = "REJECTED"
                touch(li)
    else:
        touch(plan)
        touch(adv)
    return ok(D.ser_campaign(camp))


def activate_eligible_line_items(camp):
    """A campaign reaching DELIVERING activates its eligible line items."""
    plan = D.plan_of_campaign(camp)
    for li in D.line_items_of_campaign(camp["id"]):
        if li["line_item_status"] != "ELIGIBLE":
            continue
        if D.eligible_product_count(li) < 1:
            continue
        if D.plan_available(plan) < li["daily_budget_cents"]:
            continue
        if not (li["flight_start_at"] <= now() < li["flight_end_at"]):
            continue
        li["line_item_status"] = "SERVING"
        li["pause_reason"] = "NONE"
        li["priority_tier"] = D.priority_tier(li)
        touch(li)


@bp.post("/rmn/campaigns/<cid>/activate")
def activate_campaign(cid):
    ctx = guard(WRITE_ROLES, path_refs=(("campaign", cid),), mutating=True)
    camp = ctx.get("campaign")
    adv = ctx.get("advertiser")
    plan = D.plan_of_campaign(camp)
    if adv["onboarding_status"] != "ACTIVE":
        fail("ERR_ADVERTISER_NOT_ACTIVE",
             "The advertiser is %s." % adv["onboarding_status"])
    if plan["plan_status"] not in ("APPROVED", "ACTIVE"):
        fail("ERR_PLAN_NOT_FUNDABLE",
             "The funding plan is %s." % plan["plan_status"])
    target = H.require_transition(camp["delivery_status"],
                                  DELIVERY_TRANSITIONS["activate"],
                                  "ERR_INVALID_CAMPAIGN_TRANSITION",
                                  "delivery_status")
    if now() < camp["flight_start_at"]:
        fail("ERR_INVALID_CAMPAIGN_TRANSITION",
             "The campaign flight has not started yet.")
    if now() >= camp["flight_end_at"]:
        fail("ERR_INVALID_CAMPAIGN_TRANSITION",
             "The campaign flight has already ended.")
    camp["delivery_status"] = target
    H.promote_plan_active(plan)
    activate_eligible_line_items(camp)
    D.recompute_pacing(camp)
    touch(camp)
    H.fire_billing(camp, "ACCRUING")
    return ok(D.ser_campaign(camp))


@bp.post("/rmn/campaigns/<cid>/pause")
def pause_campaign(cid):
    specs = (F("pause_reason", "enum", required=True, enum=PAUSE_REASONS),)
    ctx = guard(WRITE_ROLES, path_refs=(("campaign", cid),), body_specs=specs,
                mutating=True)
    camp = ctx.get("campaign")
    target = H.require_transition(camp["delivery_status"],
                                  DELIVERY_TRANSITIONS["pause"],
                                  "ERR_INVALID_CAMPAIGN_TRANSITION",
                                  "delivery_status")
    camp["delivery_status"] = target
    touch(camp)
    for li in D.line_items_of_campaign(camp["id"]):
        if li["line_item_status"] == "SERVING":
            H.pause_line_item(li, ctx.data["pause_reason"])
    return ok(D.ser_campaign(camp))


@bp.post("/rmn/campaigns/<cid>/resume")
def resume_campaign(cid):
    ctx = guard(WRITE_ROLES, path_refs=(("campaign", cid),), mutating=True)
    camp = ctx.get("campaign")
    adv = ctx.get("advertiser")
    plan = D.plan_of_campaign(camp)
    if adv["onboarding_status"] != "ACTIVE":
        fail("ERR_ADVERTISER_NOT_ACTIVE",
             "The advertiser is %s." % adv["onboarding_status"])
    if plan["plan_status"] != "ACTIVE":
        fail("ERR_PLAN_NOT_FUNDABLE",
             "The funding plan is %s." % plan["plan_status"])
    target = H.require_transition(camp["delivery_status"],
                                  DELIVERY_TRANSITIONS["resume"],
                                  "ERR_INVALID_CAMPAIGN_TRANSITION",
                                  "delivery_status")
    if now() >= camp["flight_end_at"]:
        fail("ERR_INVALID_CAMPAIGN_TRANSITION",
             "The campaign flight has already ended.")
    resumable = [l for l in D.line_items_of_campaign(camp["id"])
                 if l["line_item_status"] in ("ELIGIBLE", "MANUAL_PAUSED")]
    if not resumable:
        fail("ERR_LINE_ITEM_INVALID_STATE",
             "No line item is eligible or manually paused.")
    if D.plan_available(plan) <= 0:
        fail("ERR_PLAN_BUDGET_INSUFFICIENT",
             "The funding plan has no remaining headroom.")
    camp["delivery_status"] = target
    for li in resumable:
        if li["line_item_status"] == "MANUAL_PAUSED" and \
                li["pause_reason"] in ("MANUAL", "BUDGET_EXHAUSTED"):
            li["line_item_status"] = "SERVING"
            li["pause_reason"] = "NONE"
            li["priority_tier"] = D.priority_tier(li)
            touch(li)
    D.recompute_pacing(camp)
    touch(camp)
    return ok(D.ser_campaign(camp))


@bp.post("/rmn/campaigns/<cid>/complete")
def complete_campaign(cid):
    ctx = guard(("NetworkAdmin", "AccountManager", "BillingOps"),
                path_refs=(("campaign", cid),), mutating=True)
    camp = ctx.get("campaign")
    target = H.require_transition(camp["delivery_status"],
                                  DELIVERY_TRANSITIONS["complete"],
                                  "ERR_INVALID_CAMPAIGN_TRANSITION",
                                  "delivery_status")
    camp["delivery_status"] = target
    touch(camp)
    for li in D.line_items_of_campaign(camp["id"]):
        if li["line_item_status"] in ("ELIGIBLE", "SERVING", "OOS_PAUSED",
                                      "MANUAL_PAUSED"):
            H.end_line_item(li)
    H.fire_billing(camp, "PENDING_INVOICE")
    return ok(D.ser_campaign(camp))


@bp.post("/rmn/campaigns/<cid>/archive")
def archive_campaign(cid):
    specs = (F("archive_reason", "string"),)
    ctx = guard(("NetworkAdmin", "AccountManager"),
                path_refs=(("campaign", cid),), body_specs=specs,
                mutating=True)
    camp = ctx.get("campaign")
    adv = ctx.get("advertiser")
    plan = D.plan_of_campaign(camp)
    source = camp["delivery_status"]
    target = H.require_transition(source, DELIVERY_TRANSITIONS["archive"],
                                  "ERR_INVALID_CAMPAIGN_TRANSITION",
                                  "delivery_status")
    if source == "COMPLETED":
        if camp["billing_status"] not in ("RECONCILED", "UNBILLED"):
            fail("ERR_INVALID_CAMPAIGN_TRANSITION",
                 "billing_status is %s." % camp["billing_status"])
        li_ids = set(l["id"] for l in D.line_items_of_campaign(camp["id"]))
        for dispute in rows("dispute"):
            if dispute.get("line_item_id") in li_ids and \
                    dispute["dispute_status"] in H.ACTIVE_DISPUTE_STATES:
                fail("ERR_DISPUTE_INVALID_STATE",
                     "A measurement dispute on this campaign is still open.")
    else:
        if D.campaign_delivered_spend(camp) != 0:
            fail("ERR_INVALID_CAMPAIGN_TRANSITION",
                 "A scheduled campaign that already delivered cannot be "
                 "archived.")
    camp["delivery_status"] = target
    touch(camp)
    if source == "SCHEDULED":
        for li in D.line_items_of_campaign(camp["id"]):
            if li["line_item_status"] in ("ELIGIBLE", "PENDING_ELIGIBILITY",
                                          "DRAFT"):
                H.end_line_item(li)
    touch(plan)
    touch(adv)
    return ok(D.ser_campaign(camp))


@bp.post("/rmn/campaigns/<cid>/offsite-reconciliation")
def offsite_reconciliation(cid):
    specs = (
        F("offsite_reported_spend_cents", "integer", required=True, minimum=0),
        F("reporting_partner_code", "string", required=True),
    )
    ctx = guard(("NetworkAdmin", "BillingOps", "MeasurementAnalyst"),
                path_refs=(("campaign", cid),), body_specs=specs,
                mutating=True)
    camp = ctx.get("campaign")
    camp["offsite_reported_spend_cents"] = ctx.data["offsite_reported_spend_cents"]
    touch(camp)
    plan = D.plan_of_campaign(camp)
    if plan is not None:
        H.exhaust_plan_if_drained(plan)
    return ok(D.ser_campaign(camp))


@bp.get("/rmn/campaigns/<cid>/performance-summary")
def performance_summary(cid):
    ctx = guard(READ_ROLES, path_refs=(("campaign", cid),))
    camp = ctx.get("campaign")
    figures = D.pacing_figures(camp)
    return ok({
        "campaign_id": camp["id"],
        "delivery_status": camp["delivery_status"],
        "billing_status": camp["billing_status"],
        "allocated_budget_cents": camp["allocated_budget_cents"],
        "delivered_spend_cents": D.campaign_delivered_spend(camp),
        "offsite_reported_spend_cents": camp["offsite_reported_spend_cents"],
        "offsite_logged_spend_cents": D.logged_offsite(camp),
        "offsite_variance_pct": D.offsite_variance_pct(camp),
        "attributed_revenue_cents": D.campaign_attributed_revenue(camp),
        "incremental_revenue_cents": D.campaign_incremental_revenue(camp),
        "roas": D.campaign_roas(camp),
        "iroas": D.campaign_iroas(camp),
        "pacing_index": camp["pacing_index"],
        "ideal_spend_cents": figures["ideal_spend_cents"],
        "daily_allowance_cents": figures["daily_allowance_cents"],
        "elapsed_days": figures["elapsed_days"],
        "total_days": figures["total_days"],
        "oos_paused_line_item_count": D.campaign_oos_count(camp),
    })
