"""Public serialization of each entity (SCAFFOLD §1.1).

Each serializer emits exactly the fields the entity declares, in a predictable
order, stripping internal bookkeeping (keys prefixed with '_').
"""

COMMON = ["id", "created_at", "updated_at", "version"]
AUDIT = ["id", "created_at"]


def _pick(rec, fields):
    return {f: rec.get(f) for f in fields}


def creator(rec):
    fields = COMMON + [
        "display_name", "email", "platform_plan", "payout_account_ref",
        "billing_mode", "charge_timing", "pending_payout_cents", "status",
    ]
    return _pick(rec, fields)


def tier(rec):
    fields = COMMON + [
        "creator_id", "name", "monthly_fee_cents", "per_creation_fee_cents",
        "per_creation_monthly_cap_cents", "billing_model", "rank",
        "benefit_labels", "active_pledge_count", "status",
    ]
    return _pick(rec, fields)


def patron(rec):
    fields = COMMON + ["display_name", "email", "wallet_credit_cents", "status"]
    return _pick(rec, fields)


def pledge(rec):
    fields = COMMON + [
        "patron_id", "creator_id", "tier_id", "scheduled_tier_id",
        "billing_model", "cycle_anchor_date", "current_cycle_charged_cents",
        "lifecycle_status", "billing_status", "grace_deadline", "lapsed_at",
        "win_back_applied",
    ]
    return _pick(rec, fields)


def charge(rec):
    fields = COMMON + [
        "pledge_id", "creator_id", "charge_kind", "cycle_anchor_date",
        "gross_amount_cents", "wallet_applied_cents", "net_amount_cents",
        "processing_fee_cents", "status", "swept_into_payout_id",
    ]
    return _pick(rec, fields)


def post(rec):
    fields = COMMON + [
        "creator_id", "title", "body", "min_tier_rank", "is_paid_creation",
        "status",
    ]
    return _pick(rec, fields)


def post_access(rec):
    fields = AUDIT + ["post_id", "patron_id", "pledge_id", "granted_tier_rank"]
    return _pick(rec, fields)


def conversation(rec):
    fields = COMMON + ["creator_id", "patron_id", "status", "message_count"]
    return _pick(rec, fields)


def message(rec):
    fields = AUDIT + ["conversation_id", "sender_role", "sender_id", "body"]
    return _pick(rec, fields)


def payout(rec):
    fields = COMMON + [
        "creator_id", "cycle_anchor_date", "gross_cents", "platform_fee_cents",
        "processing_fee_cents", "payout_amount_cents", "swept_charge_count",
        "status",
    ]
    return _pick(rec, fields)


def win_back_offer(rec):
    fields = COMMON + ["pledge_id", "discount_pct", "expires_at", "status"]
    return _pick(rec, fields)
