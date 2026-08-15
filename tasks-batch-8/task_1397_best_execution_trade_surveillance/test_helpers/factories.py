"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "EMPLOYEE_NAME": "Test Employee",
    "DEPARTMENT": "TRADING",
    "ATTESTATION_DUE_AT": "2027-01-01T00:00:00Z",
    "VENUE_CODE": "NYSE",
    "VENUE_NAME": "New York Stock Exchange",
    "VENUE_TYPE": "EXCHANGE",
    "ARR_FROM": "2026-08-01T00:00:00Z",
    "ARR_TO": "2026-09-01T00:00:00Z",
    "ROUTING_FEE_BPS": 2,
    "SYMBOL": "ACME",
    "BID": 9990,
    "ASK": 10010,
    "PERIOD_MONTH": "2026-08",
    "QUARTER": "2026-Q3",
    "POLICY_CODE": "PAT",
    "POLICY_TITLE": "Personal Account Trading",
}


def create_employee_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["EMPLOYEE_NAME"],
        "employee_ref": "EMP-001",
        "department": DEFAULTS["DEPARTMENT"],
        "attestation_due_at": DEFAULTS["ATTESTATION_DUE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "venue_code": DEFAULTS["VENUE_CODE"],
        "name": DEFAULTS["VENUE_NAME"],
        "venue_type": DEFAULTS["VENUE_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def flat_tier(rate=0.10):
    return [{"min_monthly_shares": 0, "rate_cents_per_share": rate}]


def create_arrangement_payload(venue_id, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "effective_from": DEFAULTS["ARR_FROM"],
        "effective_to": DEFAULTS["ARR_TO"],
        "pfof_tiers": flat_tier(),
        "routing_fee_bps": DEFAULTS["ROUTING_FEE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "client_ref": "ORD-1",
        "symbol": DEFAULTS["SYMBOL"],
        "side": "BUY",
        "quantity": 100,
        "order_type": "MARKET",
        "arrival_nbbo_bid_cents": DEFAULTS["BID"],
        "arrival_nbbo_ask_cents": DEFAULTS["ASK"],
    }
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(venue_id, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "order_type": "MARKET",
        "period_month": DEFAULTS["PERIOD_MONTH"],
        "variant": "FAR_TOUCH",
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_payload(**overrides) -> dict:
    defaults = {
        "quarter": DEFAULTS["QUARTER"],
        "pricing_variant": "MARGINAL",
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(snapshot_ids, venue_decisions, **overrides) -> dict:
    defaults = {
        "quarter": DEFAULTS["QUARTER"],
        "snapshot_ids": snapshot_ids,
        "venue_decisions": venue_decisions,
    }
    defaults.update(overrides)
    return defaults


def create_personal_trade_payload(**overrides) -> dict:
    defaults = {
        "symbol": DEFAULTS["SYMBOL"],
        "side": "BUY",
        "quantity": 50,
    }
    defaults.update(overrides)
    return defaults


def create_restricted_entry_payload(**overrides) -> dict:
    defaults = {
        "symbol": DEFAULTS["SYMBOL"],
        "restriction_kind": "ALL",
        "effective_from": "2026-09-10T00:00:00Z",
        "effective_to": "2026-09-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_comm_item_payload(author_employee_id, **overrides) -> dict:
    defaults = {
        "channel": "EMAIL",
        "author_employee_id": author_employee_id,
        "body_text": "hello",
    }
    defaults.update(overrides)
    return defaults


def create_lexicon_policy_payload(**overrides) -> dict:
    defaults = {
        "name": "LX",
        "terms": [{"term": "guarantee", "weight": 60}],
    }
    defaults.update(overrides)
    return defaults


def create_compliance_policy_payload(**overrides) -> dict:
    defaults = {
        "policy_code": DEFAULTS["POLICY_CODE"],
        "title": DEFAULTS["POLICY_TITLE"],
        "version_label": "v2026.1",
    }
    defaults.update(overrides)
    return defaults
