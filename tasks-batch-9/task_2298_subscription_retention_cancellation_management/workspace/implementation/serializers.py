"""Read-model projections.  Computed fields are derived at read time against
the logical clock (PRD §2.4)."""
from db import store
from services import calc

_COMMON = ("id", "created_at", "updated_at", "version")


def _pick(rec, fields):
    out = {}
    for f in fields:
        out[f] = rec.get(f)
    return out


PLAN_FIELDS = ("id", "code", "name", "monthly_price_cents", "unit_cogs_cents",
               "shipments_per_cycle", "shipments_per_term", "allowed_frequency_weeks",
               "margin_floor_pct", "is_negative_option", "renewal_reminder_days_before",
               "max_pause_cycles", "addon_catalog", "downgrade_target_plan_id", "status",
               "created_at", "updated_at", "version")


def plan(rec):
    out = _pick(rec, PLAN_FIELDS)
    out["active_subscription_count"] = sum(
        1 for s in store.subscriptions.values()
        if s["plan_id"] == rec["id"] and s["lifecycle_state"] in ("ACTIVE", "PAUSED", "PENDING_CANCEL"))
    return out


TEMPLATE_FIELDS = ("id", "code", "name", "offer_type", "discount_pct", "discount_cycles",
                   "pause_cycles", "skip_count", "min_tenure_days", "eligible_reason_codes",
                   "max_per_subscriber_per_365d", "priority_rank", "expires_after_hours",
                   "status", "created_at", "updated_at", "version")


def template(rec):
    return _pick(rec, TEMPLATE_FIELDS)


SUBSCRIBER_FIELDS = ("id", "email", "acquisition_channel", "do_not_contact",
                     "first_subscribed_at", "lapsed_at", "won_back_at", "churn_type",
                     "winback_suppressed_until", "cohort_month",
                     "created_at", "updated_at", "version")


def subscriber(rec):
    out = _pick(rec, SUBSCRIBER_FIELDS)
    tenure = calc.tenure_days_now(rec)
    out["tenure_days"] = tenure
    out["tenure_bucket"] = calc.bucket_for_days(tenure)
    out["realized_ltv_cents"] = calc.realized_ltv(rec)
    out["projected_ltv_cents"] = calc.projected_ltv(rec)
    out["save_offer_grants_365d_count"] = calc.save_offer_grants_365d_count(rec)
    out["last_contacted_at"] = calc.last_contacted_at(rec)
    return out


PM_FIELDS = ("id", "subscriber_id", "card_last4", "exp_month", "exp_year", "network",
             "status", "updater_status", "updater_requested_at",
             "created_at", "updated_at", "version")


def payment_method(rec):
    return _pick(rec, PM_FIELDS)


SUBSCRIPTION_FIELDS = ("id", "subscriber_id", "plan_id", "payment_method_id",
                       "lifecycle_state", "billing_state", "frequency_weeks", "addons",
                       "active_discount_pct", "discount_remaining_cycles",
                       "baseline_price_cents", "committed_price_cents",
                       "next_renewal_at", "next_ship_at", "paused_until",
                       "pause_cycles_used", "term_shipments_delivered",
                       "term_shipments_skipped", "cancel_effective_at",
                       "first_failed_at", "grace_end_at", "consecutive_failed_attempts",
                       "disclosure_acknowledged", "created_at", "updated_at", "version")


def subscription(rec):
    out = _pick(rec, SUBSCRIPTION_FIELDS)
    plan_rec = store.plans.get(rec["plan_id"])
    per_term = plan_rec["shipments_per_term"] if plan_rec else 0
    out["term_shipments_remaining"] = (per_term - rec["term_shipments_delivered"]
                                       - rec["term_shipments_skipped"])
    return out


INVOICE_FIELDS = ("id", "subscription_id", "payment_method_id", "cycle_index",
                  "amount_cents", "cogs_cents", "line_items", "status", "due_at",
                  "paid_at", "attempt_count", "proration_factor", "is_renewal",
                  "created_at", "updated_at", "version")


def invoice(rec):
    return _pick(rec, INVOICE_FIELDS)


ATTEMPT_FIELDS = ("id", "invoice_id", "previous_attempt_id", "attempt_number",
                  "scheduled_at", "attempted_at", "outcome", "decline_code",
                  "backoff_days_applied", "grace_clamped", "is_final", "created_at")


def dunning_attempt(rec):
    return _pick(rec, ATTEMPT_FIELDS)


SESSION_FIELDS = ("id", "subscription_id", "state", "reason_code", "reason_detail",
                  "step_count", "offers_presented_count", "entry_channel", "started_at",
                  "completed_at", "presented_by_user_id", "created_at", "updated_at",
                  "version")


def session(rec):
    return _pick(rec, SESSION_FIELDS)


GRANT_FIELDS = ("id", "cancellation_session_id", "save_offer_template_id",
                "subscription_id", "state", "per_cycle_margin_pct",
                "blended_term_margin_pct", "margin_exception_required",
                "margin_exception_state", "presented_by_user_id", "decided_by_user_id",
                "expires_at", "accepted_at", "retention_value_cents",
                "created_at", "updated_at", "version")


def grant(rec):
    return _pick(rec, GRANT_FIELDS)


MOD_FIELDS = ("id", "subscription_id", "save_offer_grant_id", "reverses_modification_id",
              "target_plan_id", "mod_type", "state", "frequency_weeks", "addon_code",
              "addon_qty", "skip_ship_at", "pause_start_at", "pause_end_at",
              "effective_at", "delta_price_cents", "prior_snapshot", "applied_at",
              "created_at", "updated_at", "version")


def modification(rec):
    return _pick(rec, MOD_FIELDS)


NOTICE_FIELDS = ("id", "subscription_id", "notice_type", "state", "scheduled_for",
                 "sent_at", "channel", "renewal_cycle_index", "body_ref",
                 "created_at", "updated_at", "version")


def notice(rec):
    return _pick(rec, NOTICE_FIELDS)


CAMPAIGN_FIELDS = ("id", "code", "name", "target_channels", "target_reason_codes",
                   "min_days_since_lapse", "max_days_since_lapse", "offer_discount_pct",
                   "send_window_days", "suppression_days", "state",
                   "created_at", "updated_at", "version")


def campaign(rec):
    out = _pick(rec, CAMPAIGN_FIELDS)
    targets = calc.targets_of_campaign(rec["id"])
    out["targeted_count"] = len(targets)
    out["sent_count"] = sum(1 for t in targets
                            if t["state"] in ("SENT", "EXPIRED", "CONVERTED"))
    out["converted_count"] = sum(1 for t in targets if t["state"] == "CONVERTED")
    return out


TARGET_FIELDS = ("id", "winback_campaign_id", "subscriber_id", "state",
                 "suppression_reason", "priority_score", "projected_ltv_cents",
                 "sent_at", "expires_at", "converted_at", "days_since_lapse_at_target",
                 "created_at", "updated_at", "version")


def target(rec):
    return _pick(rec, TARGET_FIELDS)


SNAPSHOT_FIELDS = ("id", "cohort_month", "acquisition_channel", "plan_code",
                   "tenure_bucket", "ltv_variant", "member_count", "retained_count",
                   "churned_voluntary_count", "churned_involuntary_count",
                   "retention_rate", "mean_ltv_cents", "computed_at", "created_at")


def snapshot(rec):
    return _pick(rec, SNAPSHOT_FIELDS)
