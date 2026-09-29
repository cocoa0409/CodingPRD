"""Entity representations. Derived fields are recomputed here so a read never
returns a stale projection (PRD 2.5)."""
import config
from db import db
from services import derive, engagement
from services.entitlement import entitlement_source


def _common(entity, data):
    data["id"] = entity["id"]
    data["created_at"] = entity["created_at"]
    if "updated_at" in entity:
        data["updated_at"] = entity["updated_at"]
    if "version" in entity:
        data["version"] = entity["version"]
    return data


def offer_plan(plan):
    return _common(
        plan,
        {
            "name": plan["name"],
            "bundle_type": plan["bundle_type"],
            "status": plan["status"],
            "intro_price_cents": plan["intro_price_cents"],
            "intro_cycles": plan["intro_cycles"],
            "step_up_schedule": [dict(s) for s in plan["step_up_schedule"]],
            "standard_from_cycle": plan["standard_from_cycle"],
            "standard_price_cents": plan["standard_price_cents"],
            "cycle_days": plan["cycle_days"],
            "print_component_cents": plan["print_component_cents"],
            "print_delivery_days": list(plan["print_delivery_days"]),
            "print_deliveries_per_cycle": plan["print_deliveries_per_cycle"],
            "per_seat_price_cents": plan["per_seat_price_cents"],
            "price_change_state": plan["price_change_state"],
            "pending_price_cents": plan["pending_price_cents"],
            "pending_effective_on": plan["pending_effective_on"],
            "notice_sent_on": plan["notice_sent_on"],
            "notice_sent_by_user_id": plan["notice_sent_by_user_id"],
            "grandfather_policy": plan["grandfather_policy"],
            "active_subscription_count": derive.plan_active_subscription_count(plan["id"]),
        },
    )


def paywall_rule(rule):
    return _common(
        rule,
        {
            "name": rule["name"],
            "status": rule["status"],
            "content_type_match": rule["content_type_match"],
            "section_match": rule["section_match"],
            "propensity_band_match": rule["propensity_band_match"],
            "action": rule["action"],
            "meter_allowance_override": rule["meter_allowance_override"],
            "priority": rule["priority"],
            "specificity_score": rule["specificity_score"],
        },
    )


def article(row):
    return _common(
        row,
        {
            "headline": row["headline"],
            "content_type": row["content_type"],
            "section": row["section"],
            "access_class": row["access_class"],
            "published_at": row["published_at"],
        },
    )


def reader(row):
    return _common(
        row,
        {
            "email": row["email"],
            "is_registered": row["is_registered"],
            "propensity_band": row["propensity_band"],
            "engagement_score": row["engagement_score"],
            "churn_risk_band": row["churn_risk_band"],
            "metered_article_ids": list(row["metered_article_ids"]),
            "metered_distinct_article_count": row["metered_distinct_article_count"],
            "meter_period_started_on": row["meter_period_started_on"],
            "entitlement_source": entitlement_source(row),
            "tenure_days": engagement.tenure_days(row),
            "intervention_count_in_period": engagement.intervention_count_in_period(row),
            "card_last4": row["card_last4"],
            "card_exp_month": row["card_exp_month"],
            "card_exp_year": row["card_exp_year"],
            "card_status": engagement.card_status(row),
            "card_updater_registered": row["card_updater_registered"],
            "card_updater_status": row["card_updater_status"],
        },
    )


def subscription(sub):
    return _common(
        sub,
        {
            "reader_id": sub["reader_id"],
            "offer_plan_id": sub["offer_plan_id"],
            "group_account_id": sub["group_account_id"],
            "lifecycle_status": sub["lifecycle_status"],
            "dunning_status": sub["dunning_status"],
            "print_fulfillment_status": sub["print_fulfillment_status"],
            "cycle_index": sub["cycle_index"],
            "cycle_start_on": sub["cycle_start_on"],
            "paid_through_on": sub["paid_through_on"],
            "access_until": sub["access_until"],
            "next_cycle_price_cents": sub["next_cycle_price_cents"],
            "locked_price_cents": sub["locked_price_cents"],
            "grandfathered_until_cycle": sub["grandfathered_until_cycle"],
            "retention_discount_pct": sub["retention_discount_pct"],
            "retention_discount_cycles_remaining": sub["retention_discount_cycles_remaining"],
            "pending_credit_cents": derive.pending_credit_cents(sub),
            "lifetime_credit_cents": derive.lifetime_credit_cents(sub),
            "dunning_first_failed_on": sub["dunning_first_failed_on"],
            "next_retry_on": sub["next_retry_on"],
            "payment_attempt_count": derive.payment_attempt_count(sub),
            "max_payment_attempts": derive.max_payment_attempts(sub),
            "vacation_days_used_365": derive.vacation_days_used_365(sub),
            "tenure_cycles": derive.tenure_cycles(sub),
            "cancel_effective_on": sub["cancel_effective_on"],
        },
    )


def invoice(row):
    return _common(
        row,
        {
            "subscription_id": row["subscription_id"],
            "cycle_index": row["cycle_index"],
            "status": row["status"],
            "price_source": row["price_source"],
            "base_line_cents": row["base_line_cents"],
            "seat_line_cents": row["seat_line_cents"],
            "discount_line_cents": row["discount_line_cents"],
            "credit_line_cents": row["credit_line_cents"],
            "total_cents": row["total_cents"],
            "due_on": row["due_on"],
            "paid_on": row["paid_on"],
        },
    )


def payment_attempt(row):
    return _common(
        row,
        {
            "invoice_id": row["invoice_id"],
            "attempt_no": row["attempt_no"],
            "outcome": row["outcome"],
            "amount_cents": row["amount_cents"],
            "decline_code": row["decline_code"],
            "is_final": row["is_final"],
            "attempted_on": row["attempted_on"],
            "card_last4_snapshot": row["card_last4_snapshot"],
        },
    )


def reader_event(row):
    return _common(
        row,
        {
            "reader_id": row["reader_id"],
            "article_id": row["article_id"],
            "applied_rule_id": row["applied_rule_id"],
            "event_type": row["event_type"],
            "decision": row["decision"],
            "meter_index": row["meter_index"],
            "effective_allowance": row["effective_allowance"],
            "weight": row["weight"],
            "occurred_at": row["occurred_at"],
        },
    )


def cancellation_request(row):
    return _common(
        row,
        {
            "subscription_id": row["subscription_id"],
            "status": row["status"],
            "reason_code": row["reason_code"],
            "save_offer_count": sum(
                1
                for o in db.save_offers.values()
                if o.get("cancellation_request_id") == row["id"]
            ),
            "projected_engagement_score": row["projected_engagement_score"],
            "eligible_save_offer_tier": row["eligible_save_offer_tier"],
            "confirmed_on": row["confirmed_on"],
            "effective_on": row["effective_on"],
            "retained": row["retained"],
        },
    )


def save_offer(row):
    return _common(
        row,
        {
            "cancellation_request_id": row["cancellation_request_id"],
            "offer_type": row["offer_type"],
            "discount_pct": row["discount_pct"],
            "duration_cycles": row["duration_cycles"],
            "pause_days": row["pause_days"],
            "status": row["status"],
            "presented_on": row["presented_on"],
            "decided_on": row["decided_on"],
        },
    )


def hold(row):
    return _common(
        row,
        {
            "subscription_id": row["subscription_id"],
            "hold_type": row["hold_type"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "status": row["status"],
            "delivery_days_credited": row["delivery_days_credited"],
            "credit_cents": row["credit_cents"],
            "credit_applied": row["credit_applied"],
            "credit_applied_cycle_index": row["credit_applied_cycle_index"],
        },
    )


def group_account(row):
    assigned = derive.seats_assigned_count(row)
    return _common(
        row,
        {
            "name": row["name"],
            "admin_email": row["admin_email"],
            "allowed_email_domain": row["allowed_email_domain"],
            "seat_capacity": row["seat_capacity"],
            "offer_plan_id": row["offer_plan_id"],
            "status": row["status"],
            "seats_assigned_count": assigned,
            "seats_available_count": max(0, row["seat_capacity"] - assigned),
        },
    )


def seat(row):
    return _common(
        row,
        {
            "group_account_id": row["group_account_id"],
            "reader_id": row["reader_id"],
            "status": row["status"],
            "starts_on": row["starts_on"],
            "ends_on": row["ends_on"],
            "invited_on": row["invited_on"],
            "invite_expires_on": row["invite_expires_on"],
            "claimed_on": row["claimed_on"],
        },
    )


SERIALIZERS = {
    "offer_plans": offer_plan,
    "paywall_rules": paywall_rule,
    "articles": article,
    "readers": reader,
    "subscriptions": subscription,
    "invoices": invoice,
    "payment_attempts": payment_attempt,
    "reader_events": reader_event,
    "cancellation_requests": cancellation_request,
    "save_offers": save_offer,
    "holds": hold,
    "group_accounts": group_account,
    "seats": seat,
}

assert set(SERIALIZERS) == set(db.COLLECTIONS)
assert config.API_PREFIX == "/paywall"
