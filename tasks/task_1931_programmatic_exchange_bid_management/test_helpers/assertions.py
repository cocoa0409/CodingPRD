"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_COMMON_DOC = "PRD common resource properties: id is a server-minted UUID; " \
    "created_at/updated_at are ISO 8601 UTC timestamps; version is an integer."


def _assert_common(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_ledger_common(data, entity_name):
    """Ledger-style resources carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_name}.created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, \
        f"{entity_name} is append-only: updated_at must be absent"
    assert "version" not in data, \
        f"{entity_name} is append-only: version must be absent"


def assert_publisher(data):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["domain"], str) and data["domain"]
    assert data["payment_terms"] in ("SEQUENTIAL_LIABILITY", "GUARANTEED")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    for field in ("lifetime_net_micros", "accrued_open_micros",
                  "paid_out_micros", "written_off_micros",
                  "active_package_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_demand_partner(data):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["seat_id"], str) and data["seat_id"]
    assert isinstance(data["max_qps"], int) and data["max_qps"] >= 1
    assert isinstance(data["daily_cap_micros"], int) and data["daily_cap_micros"] >= 1
    assert data["status"] in ("ACTIVE", "THROTTLED", "SUSPENDED")
    for field in ("spend_today_micros", "current_second_auction_count",
                  "lifetime_spend_micros"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_package(data):
    _assert_common(data)
    assert isinstance(data["publisher_id"], str) and data["publisher_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["ad_format"] in ("DISPLAY", "VIDEO", "NATIVE", "AUDIO")
    assert isinstance(data["category_tags"], list) and data["category_tags"]
    assert isinstance(data["base_floor_cpm_micros"], int)
    assert data["status"] in ("ACTIVE", "PAUSED")
    assert isinstance(data["active_deal_count"], int)
    assert isinstance(data["current_seasonal_multiplier_bps"], int)
    assert isinstance(data["effective_floor_cpm_micros"], int)


def assert_seasonal_window(data):
    _assert_common(data)
    assert isinstance(data["package_id"], str) and data["package_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["start_date"], str) and data["start_date"]
    assert isinstance(data["end_date"], str) and data["end_date"]
    assert isinstance(data["multiplier_bps"], int)
    assert isinstance(data["is_currently_applied"], bool)


def assert_deal(data):
    _assert_common(data)
    assert isinstance(data["package_id"], str) and data["package_id"]
    assert isinstance(data["publisher_id"], str) and data["publisher_id"]
    assert isinstance(data["demand_partner_id"], str) and data["demand_partner_id"]
    assert data["deal_type"] in (
        "PMP_STANDARD", "PMP_EXCLUSIVE", "PREFERRED", "PROGRAMMATIC_GUARANTEED")
    assert isinstance(data["is_exclusive"], bool)
    assert data["auction_type"] in ("FIRST_PRICE", "SECOND_PRICE")
    assert isinstance(data["floor_cpm_micros"], int)
    assert isinstance(data["delivered_impressions"], int)
    assert isinstance(data["renegotiation_count"], int)
    assert data["status"] in (
        "DRAFT", "PENDING_REVIEW", "ACTIVE", "RENEGOTIATING", "PAUSED", "EXPIRED")


def assert_supply_chain_node(data):
    _assert_ledger_common(data, "SupplyChainNode")
    assert isinstance(data["package_id"], str) and data["package_id"]
    assert isinstance(data["seller_domain"], str) and data["seller_domain"]
    assert isinstance(data["fee_bps"], int)
    assert isinstance(data["hop_index"], int)
    assert isinstance(data["is_tail"], bool)


def assert_blocklist_entry(data):
    _assert_common(data)
    assert data["scope"] in ("EXCHANGE", "PUBLISHER", "DEAL")
    assert data["rule_type"] in ("ADVERTISER_DOMAIN", "CATEGORY")
    assert isinstance(data["value"], str) and data["value"]
    assert data["status"] in ("ACTIVE", "LIFTED")


def assert_auction_record(data):
    _assert_ledger_common(data, "AuctionRecord")
    assert isinstance(data["deal_id"], str) and data["deal_id"]
    assert isinstance(data["publisher_id"], str) and data["publisher_id"]
    assert isinstance(data["demand_partner_id"], str) and data["demand_partner_id"]
    assert data["auction_type"] in ("FIRST_PRICE", "SECOND_PRICE")
    for field in ("winning_bid_cpm_micros", "clearing_cpm_micros", "impressions",
                  "gross_micros", "exchange_fee_micros", "supply_fee_micros",
                  "publisher_net_micros", "dsp_fee_micros", "dsp_billed_micros"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["creative_domain"], str) and data["creative_domain"]
    assert isinstance(data["voided"], bool)
    assert data["dsp_confirmed_at"] is None or isinstance(data["dsp_confirmed_at"], str)
    assert data["voided_at"] is None or isinstance(data["voided_at"], str)


def assert_reconciliation_report(data):
    _assert_common(data)
    assert isinstance(data["deal_id"], str) and data["deal_id"]
    for field in ("ssp_impressions", "ssp_spend_micros", "dsp_impressions",
                  "dsp_billed_micros"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["discrepancy_pct"], (int, float))
    assert isinstance(data["auto_flagged"], bool)
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "DISPUTED", "RESOLVED")


def assert_payout_batch(data):
    _assert_common(data)
    assert isinstance(data["period_start"], str) and data["period_start"]
    assert isinstance(data["period_end"], str) and data["period_end"]
    assert data["status"] in (
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "RELEASED", "SETTLED")
    assert isinstance(data["created_by_user_id"], str)
    for field in ("line_count", "total_gross_micros", "total_payable_micros"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_payout_line(data):
    _assert_common(data)
    assert isinstance(data["batch_id"], str) and data["batch_id"]
    assert isinstance(data["publisher_id"], str) and data["publisher_id"]
    assert data["status"] in ("PENDING", "HELD", "ELIGIBLE", "PAID", "WRITTEN_OFF")
    for field in ("gross_micros", "confirmed_micros", "unconfirmed_micros",
                  "adjustment_micros", "payable_micros"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def normalize_outcome(value):
    """Normalize the auction outcome token for comparison.

    The PRD names the auction outcomes "fill" and "no-fill" in prose; this
    folds case and separator variants ("fill", "FILL", "no_fill",
    "no-fill") into the canonical FILL / NO_FILL tokens before comparison.
    """
    return str(value).strip().upper().replace("-", "_").replace(" ", "_")


def assert_outcome(data, expected):
    actual = normalize_outcome(data.get("outcome"))
    assert actual == expected, (
        f"Expected auction outcome {expected}, got {data.get('outcome')!r}")


def assert_money_identity(record):
    """publisher_net_micros == gross - exchange_fee - supply_fee."""
    assert record["publisher_net_micros"] == (
        record["gross_micros"]
        - record["exchange_fee_micros"]
        - record["supply_fee_micros"]
    ), "publisher_net_micros must equal gross minus both fee layers"


def assert_dsp_billing_identity(record):
    """dsp_billed_micros == gross_micros + dsp_fee_micros."""
    assert record["dsp_billed_micros"] == (
        record["gross_micros"] + record["dsp_fee_micros"]
    ), "dsp_billed_micros must equal gross plus the DSP fee"


def assert_publisher_accrual_conserved(publisher, adjustments_micros=0):
    """Conservation invariant: lifetime_net + adjustments == paid + written + open."""
    lhs = publisher["lifetime_net_micros"] + adjustments_micros
    rhs = (publisher["paid_out_micros"] + publisher["written_off_micros"]
           + publisher["accrued_open_micros"])
    assert lhs == rhs, (
        f"Accrual conservation violated: {lhs} != {rhs} for publisher "
        f"{publisher['id']}")
