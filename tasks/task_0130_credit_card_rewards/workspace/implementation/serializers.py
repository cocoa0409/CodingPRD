"""Entity-to-JSON serializers.

The PRD §2.4 says four resources are append-only and only expose id+created_at
(no updated_at, no version): QuarterlyActivation, PointsTransfer, StatementCredit,
PointsLedgerEntry. Cardholder, Account, CashbackCategory, Transaction, and
TransferPartner all expose id, created_at, updated_at, version.
"""


def cardholder_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "email": c["email"],
        "display_name": c["display_name"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def account_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "cardholder_id": a["cardholder_id"],
        "opened_at": a["opened_at"],
        "lifecycle_state": a["lifecycle_state"],
        "spending_tier": a["spending_tier"],
        "ytd_qualifying_spend_cents": a["ytd_qualifying_spend_cents"],
        "points_balance": a["points_balance"],
        "signup_bonus_state": a["signup_bonus_state"],
        "signup_bonus_qualifying_spend_cents": a["signup_bonus_qualifying_spend_cents"],
        "signup_bonus_deadline_at": a["signup_bonus_deadline_at"],
        "last_qualifying_activity_at": a["last_qualifying_activity_at"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def cashback_category_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "code": c["code"],
        "category_type": c["category_type"],
        "base_rate_bps": c["base_rate_bps"],
        "requires_activation": c["requires_activation"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def quarterly_activation_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "account_id": a["account_id"],
        "category_id": a["category_id"],
        "quarter_label": a["quarter_label"],
        "activation_window_start": a["activation_window_start"],
        "activation_window_end": a["activation_window_end"],
        "activated_at": a["activated_at"],
        "status": a["status"],
        "created_at": a["created_at"],
    }


def transaction_view(t: dict) -> dict:
    return {
        "id": t["id"],
        "account_id": t["account_id"],
        "category_id": t["category_id"],
        "txn_type": t["txn_type"],
        "amount_cents": t["amount_cents"],
        "posted_at": t["posted_at"],
        "status": t["status"],
        "points_provisional": t["points_provisional"],
        "points_final": t["points_final"],
        "original_transaction_id": t.get("original_transaction_id"),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def transfer_partner_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "code": p["code"],
        "partner_type": p["partner_type"],
        "conversion_ratio_points_per_unit": p["conversion_ratio_points_per_unit"],
        "min_transfer_increment": p["min_transfer_increment"],
        "is_active": p["is_active"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def points_transfer_view(t: dict) -> dict:
    return {
        "id": t["id"],
        "account_id": t["account_id"],
        "partner_id": t["partner_id"],
        "requested_partner_units": t["requested_partner_units"],
        "points_debited": t["points_debited"],
        "status": t["status"],
        "initiated_at": t["initiated_at"],
        "completed_at": t["completed_at"],
        "created_at": t["created_at"],
    }


def statement_credit_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "account_id": c["account_id"],
        "redemption_mode": c["redemption_mode"],
        "requested_points": c["requested_points"],
        "requested_amount_cents": c["requested_amount_cents"],
        "points_debited": c["points_debited"],
        "credit_amount_cents": c["credit_amount_cents"],
        "applied_at": c["applied_at"],
        "status": c["status"],
        "created_at": c["created_at"],
    }


def ledger_entry_view(e: dict) -> dict:
    return {
        "id": e["id"],
        "account_id": e["account_id"],
        "entry_type": e["entry_type"],
        "source_entity_type": e["source_entity_type"],
        "source_entity_id": e["source_entity_id"],
        "delta_points": e["delta_points"],
        "occurred_at": e["occurred_at"],
        "created_at": e["created_at"],
    }
