"""Serializers: project internal records to public API output.

Internal records carry private bookkeeping keys (prefixed with '_'). Public
output exposes exactly the entity fields plus the system fields. Common-fields
entities expose id/created_at/updated_at/version; LedgerEntry exposes only
id/created_at.
"""

COMMON = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "merchant": ("legal_name", "ein", "state_code", "status", "monthly_revenue_cents"),
    "bank_feed": ("merchant_id", "plaid_item_id", "pulled_at", "avg_daily_balance_cents",
                  "nsf_count_90d", "deposit_volume_cents", "status"),
    "application": ("merchant_id", "bank_feed_id", "requested_limit_cents",
                    "submitted_by_user_id", "status", "risk_score",
                    "approved_limit_cents", "pricing_tier", "decline_reason"),
    "credit_line": ("application_id", "merchant_id", "credit_limit_cents", "pricing_tier",
                    "fee_factor_bps", "remittance_cadence", "outstanding_principal_cents",
                    "outstanding_fee_cents", "available_credit_cents", "nsf_strike_count",
                    "status", "defaulted_by_user_id"),
    "draw": ("credit_line_id", "principal_cents", "fee_cents", "principal_repaid_cents",
             "fee_repaid_cents", "drawn_at", "status"),
    "remittance": ("credit_line_id", "scheduled_for", "amount_cents", "principal_applied_cents",
                   "fee_applied_cents", "attempt_count", "status", "failure_reason",
                   "next_retry_remittance_id"),
    "line_increase_request": ("credit_line_id", "latest_bank_feed_id", "requested_limit_cents",
                              "approved_limit_cents", "status", "denial_reason"),
    "renewal_offer": ("credit_line_id", "new_fee_factor_bps", "term_days", "total_fee_cents",
                      "equivalent_apr_bps", "status"),
    "statement": ("credit_line_id", "period_start", "period_end", "opening_principal_cents",
                  "draws_total_cents", "fees_assessed_cents", "remittances_total_cents",
                  "closing_principal_cents", "status"),
}

LEDGER_FIELDS = ("credit_line_id", "draw_id", "remittance_id", "entry_type",
                 "amount_cents", "balance_after_cents")


def _project(record, fields, common=True):
    out = {}
    if common:
        for k in COMMON:
            out[k] = record.get(k)
    else:
        out["id"] = record.get("id")
        out["created_at"] = record.get("created_at")
    for f in fields:
        out[f] = record.get(f)
    return out


def merchant(r):
    return _project(r, FIELDS["merchant"])


def bank_feed(r):
    return _project(r, FIELDS["bank_feed"])


def application(r):
    return _project(r, FIELDS["application"])


def credit_line(r):
    return _project(r, FIELDS["credit_line"])


def draw(r):
    return _project(r, FIELDS["draw"])


def remittance(r):
    return _project(r, FIELDS["remittance"])


def line_increase_request(r):
    return _project(r, FIELDS["line_increase_request"])


def renewal_offer(r):
    return _project(r, FIELDS["renewal_offer"])


def statement(r):
    return _project(r, FIELDS["statement"])


def ledger_entry(r):
    return _project(r, LEDGER_FIELDS, common=False)
