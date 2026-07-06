"""Entity -> API JSON serializers. Each returns the exact field set per the PRD."""


def plan_out(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "tier": p["tier"],
        "annual_fee_cents": p["annual_fee_cents"],
        "reward_rate_bps": p["reward_rate_bps"],
        "reward_cap_cents": p["reward_cap_cents"],
        "max_household_cards": p["max_household_cards"],
        "addon_fee_cents": p["addon_fee_cents"],
    }


def membership_out(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "plan_id": m["plan_id"],
        "primary_member_name": m["primary_member_name"],
        "status": m["status"],
        "auto_renew": m["auto_renew"],
        "term_start_utc": m["term_start_utc"],
        "term_end_utc": m["term_end_utc"],
        "reward_accrued_cents": m["reward_accrued_cents"],
        "reward_redeemed_cents": m["reward_redeemed_cents"],
        "fees_paid_cents": m["fees_paid_cents"],
        "household_card_count": m["household_card_count"],
    }


def card_out(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "membership_id": c["membership_id"],
        "cardholder_name": c["cardholder_name"],
        "card_kind": c["card_kind"],
        "status": c["status"],
        "fee_charged_cents": c["fee_charged_cents"],
    }


def product_out(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "sku": p["sku"],
        "list_price_cents": p["list_price_cents"],
        "member_price_cents": p["member_price_cents"],
        "member_only": p["member_only"],
        "per_member_limit": p["per_member_limit"],
        "department": p["department"],
        "reward_eligible": p["reward_eligible"],
    }


def instant_saving_out(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "product_id": s["product_id"],
        "kind": s["kind"],
        "amount_cents": s["amount_cents"],
        "window_start_utc": s["window_start_utc"],
        "window_end_utc": s["window_end_utc"],
        "max_units": s["max_units"],
    }


def transaction_out(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "membership_id": t["membership_id"],
        "status": t["status"],
        "gross_cents": t["gross_cents"],
        "instant_savings_cents": t["instant_savings_cents"],
        "rebate_cents": t["rebate_cents"],
        "net_cents": t["net_cents"],
        "reward_accrued_cents": t["reward_accrued_cents"],
        "finalized_at_utc": t["finalized_at_utc"],
    }


def line_out(line):
    return {
        "id": line["id"],
        "created_at": line["created_at"],
        "updated_at": line["updated_at"],
        "version": line["version"],
        "transaction_id": line["transaction_id"],
        "product_id": line["product_id"],
        "qty": line["qty"],
        "unit_price_cents": line["unit_price_cents"],
        "line_instant_savings_cents": line["line_instant_savings_cents"],
        "line_rebate_cents": line["line_rebate_cents"],
        "returned_qty": line["returned_qty"],
    }


def ledger_out(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "membership_id": e["membership_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "source_transaction_id": e["source_transaction_id"],
        "term_start_utc": e["term_start_utc"],
    }


def return_out(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "membership_id": r["membership_id"],
        "transaction_id": r["transaction_id"],
        "product_id": r["product_id"],
        "qty": r["qty"],
        "lookup_mode": r["lookup_mode"],
        "status": r["status"],
        "refund_cents": r["refund_cents"],
        "reward_reversal_cents": r["reward_reversal_cents"],
    }


def fee_event_out(fe):
    return {
        "id": fe["id"],
        "created_at": fe["created_at"],
        "membership_id": fe["membership_id"],
        "kind": fe["kind"],
        "amount_cents": fe["amount_cents"],
        "term_start_utc": fe["term_start_utc"],
    }


def payment_out(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "membership_id": p["membership_id"],
        "purpose": p["purpose"],
        "outcome": p["outcome"],
        "amount_cents": p["amount_cents"],
    }
