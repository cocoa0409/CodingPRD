"""Entity -> public JSON serializers. Strips internal fields (_seq)."""

_COMMON = ("id", "created_at", "updated_at", "version")


def _base(rec, fields):
    out = {}
    for f in fields:
        out[f] = rec.get(f)
    for f in _COMMON:
        out[f] = rec.get(f)
    return out


def broker(rec):
    return _base(rec, ("firm_name", "license_number", "accrued_commission_cents"))


def seller(rec):
    return _base(rec, ("full_name", "email"))


def buyer(rec):
    out = _base(rec, ("full_name", "email", "proof_of_funds_cents", "net_worth_cents",
                      "committed_capital_cents", "escrowed_cents"))
    out["available_capital_cents"] = (
        int(rec["proof_of_funds_cents"])
        - int(rec["committed_capital_cents"])
        - int(rec["escrowed_cents"])
    )
    return out


def listing(rec):
    return _base(rec, ("broker_id", "seller_id", "business_name", "industry_code",
                       "annual_sde_cents", "annual_revenue_cents", "ffe_value_cents",
                       "inventory_value_cents", "industry_multiple", "asking_price_cents",
                       "exclusive_start_date", "exclusive_end_date", "status"))


def cim(rec):
    return _base(rec, ("listing_id", "valuation_method", "recommended_price_cents", "status"))


def nda(rec):
    return _base(rec, ("listing_id", "buyer_id", "status"))


def document(rec):
    return _base(rec, ("listing_id", "title", "doc_type"))


def meeting(rec):
    return _base(rec, ("listing_id", "buyer_id", "start_at", "end_at", "status"))


def deal(rec):
    return _base(rec, ("listing_id", "buyer_id", "broker_id", "status",
                       "accepted_loi_id", "accepted_price_cents", "earnout_total_cents",
                       "earnout_periods", "earnout_baseline_sde_cents", "earnout_paid_cents",
                       "provisional_commission_cents", "final_commission_cents",
                       "seller_net_proceeds_cents"))


def loi(rec):
    return _base(rec, ("deal_id", "offer_price_cents", "earnest_deposit_cents",
                       "earnout_amount_cents", "earnout_periods", "financing_contingency",
                       "counter_price_cents", "round_number", "status"))


def loan(rec):
    return _base(rec, ("deal_id", "requested_amount_cents", "approved_amount_cents",
                       "decision_reason", "status"))


def escrow(rec):
    return _base(rec, ("deal_id", "closing_price_cents", "required_deposit_cents",
                       "balance_cents", "status"))
