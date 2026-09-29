"""Entity assertions and domain invariant checkers."""
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import TIER_RANK


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def round_half_up(value, places: int) -> float:
    """Round half up to `places` decimals, the PRD's rounding discipline."""
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def assert_common_fields(data: dict, entity: str = "resource"):
    """id + created_at + updated_at + version, per PRD 2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601 UTC: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601 UTC: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1, got {data['version']}"


def assert_append_only_fields(data: dict, entity: str = "resource"):
    """id + created_at only - no updated_at, no version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, f"{entity} is append-only and must not carry updated_at"
    assert "version" not in data, f"{entity} is append-only and must not carry version"


# ---------------------------------------------------------------------------
# per-entity assertions
# ---------------------------------------------------------------------------
def assert_advertiser(data: dict):
    assert_common_fields(data, "Advertiser")
    assert isinstance(data["name"], str) and data["name"].strip()
    assert isinstance(data["credit_cap_cents"], int) and data["credit_cap_cents"] >= 0
    assert isinstance(data["credit_received_cents_total"], int)
    assert data["credit_received_cents_total"] >= 0
    assert isinstance(data["settled_claim_count"], int) and data["settled_claim_count"] >= 0


def assert_publisher(data: dict):
    assert_common_fields(data, "Publisher")
    assert isinstance(data["name"], str) and data["name"].strip()
    assert isinstance(data["primary_domain"], str) and data["primary_domain"]
    assert 0.0 <= float(data["sourced_traffic_pct"]) <= 1.0
    assert data["publisher_status"] in ("ACTIVE", "RESTRICTED", "DELISTED")
    for counter in (
        "mfa_page_count", "quarantined_batch_count", "certified_batch_count",
        "decided_appeal_count", "overturned_appeal_count", "credit_issued_cents_total",
    ):
        assert isinstance(data[counter], int), f"Publisher.{counter} must be an integer"
        assert data[counter] >= 0, f"Publisher.{counter} must never go negative"


def assert_methodology_version(data: dict):
    assert_common_fields(data, "MethodologyVersion")
    assert data["standard_family"] in ("VIEWABILITY", "IVT", "SUITABILITY")
    assert isinstance(data["version_code"], str) and 1 <= len(data["version_code"]) <= 40
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["effective_from"] < data["effective_to"]
    assert data["accreditation_status"] in (
        "PROVISIONAL", "ACCREDITED", "SUSPENDED", "LAPSED"
    )
    assert float(data["display_in_view_seconds"]) > 0
    assert float(data["video_in_view_seconds"]) > 0
    for pixel_field in ("display_pixel_pct", "large_display_pixel_pct", "video_pixel_pct"):
        assert 0 < float(data[pixel_field]) <= 1
    assert 0 < float(data["coverage_rate_floor"]) <= 1
    assert 0 <= float(data["ivt_rate_ceiling"]) < 1
    assert isinstance(data["decertified_batch_count"], int)


def assert_campaign(data: dict):
    assert_common_fields(data, "Campaign")
    assert isinstance(data["cpm_cents"], int) and data["cpm_cents"] > 0
    assert data["min_suitability_tier"] in TIER_RANK
    assert 0 < float(data["target_coverage_rate"]) <= 1
    assert data["format"] in ("DISPLAY", "LARGE_DISPLAY", "VIDEO")
    assert data["status"] in ("ACTIVE", "UNDER_REMEDIATION")
    assert data["coverage_status"] in ("UNKNOWN", "ON_TARGET", "BELOW_TARGET")
    assert isinstance(data["certified_measured_impressions"], int)
    assert isinstance(data["certified_measurable_impressions"], int)
    assert isinstance(data["open_claim_count"], int) and data["open_claim_count"] >= 0


def assert_inventory_list(data: dict):
    assert_common_fields(data, "InventoryList")
    assert data["list_type"] in ("INCLUSION", "EXCLUSION")
    assert data["status"] in ("DRAFT", "PUBLISHED", "STALE")
    assert isinstance(data["entry_count"], int) and data["entry_count"] >= 0


def assert_list_entry(data: dict):
    assert_append_only_fields(data, "ListEntry")
    assert data["entry_type"] in ("PAGE_URL", "DOMAIN", "PUBLISHER", "CATEGORY")
    assert isinstance(data["entry_value"], str) and 1 <= len(data["entry_value"]) <= 300
    assert data["action"] in ("ALLOW", "BLOCK")
    assert data["specificity_rank"] in (1, 2, 3, 4)


def assert_pre_bid_segment(data: dict):
    assert_common_fields(data, "PreBidSegment")
    assert data["suitability_floor_tier"] in TIER_RANK
    assert data["sync_status"] in ("PENDING", "SYNCED", "STALE")
    assert data["inclusion_list_id"] is not None or data["exclusion_list_id"] is not None


def assert_page(data: dict):
    assert_common_fields(data, "Page")
    assert isinstance(data["url"], str) and data["url"].startswith("https://")
    assert isinstance(data["domain"], str) and data["domain"] == data["domain"].lower()
    assert data["classification_state"] in (
        "UNCLASSIFIED", "MODEL_CLASSIFIED", "HUMAN_CONFIRMED", "APPEALED", "RECLASSIFIED"
    )
    if data["current_tier"] is not None:
        assert data["current_tier"] in TIER_RANK
    assert isinstance(data["latest_category_codes"], list)
    assert isinstance(data["mfa_flag"], bool)
    assert isinstance(data["appeal_count"], int) and data["appeal_count"] >= 0


def assert_page_classification(data: dict):
    assert_common_fields(data, "PageClassification")
    assert data["classifier_kind"] in ("MODEL", "HUMAN", "APPEAL_REMEDY")
    assert isinstance(data["category_codes"], list) and len(data["category_codes"]) <= 6
    assert 0.0 <= float(data["ad_density_ratio"]) <= 1.0
    assert isinstance(data["refresh_seconds"], int) and data["refresh_seconds"] >= 0
    assert 0.0 <= float(data["originality_score"]) <= 100.0
    assert data["assigned_tier"] in TIER_RANK
    assert isinstance(data["mfa_flag"], bool)
    assert data["review_state"] in (
        "PENDING_REVIEW", "CONFIRMED", "OVERRIDDEN", "SUPERSEDED", "VACATED"
    )
    assert float(data["base_risk_points"]) >= 0
    assert float(data["adjusted_risk_points"]) >= 0


def assert_appeal(data: dict):
    assert_common_fields(data, "Appeal")
    assert data["appeal_state"] in (
        "FILED", "MORE_EVIDENCE_REQUIRED", "UPHELD", "OVERTURNED"
    )
    assert data["reason_code"] in (
        "CATEGORY_MISREAD", "CONTEXT_IGNORED", "STALE_CRAWL", "MFA_SIGNAL_WRONG"
    )
    assert isinstance(data["round_no"], int) and 1 <= data["round_no"] <= 3
    if data["revised_tier"] is not None:
        assert data["revised_tier"] in TIER_RANK


def assert_measurement_batch(data: dict):
    assert_common_fields(data, "MeasurementBatch")
    assert data["format"] in ("DISPLAY", "LARGE_DISPLAY", "VIDEO")
    assert data["scoring_status"] in (
        "INGESTED", "SCORED", "CERTIFIED", "QUARANTINED", "DECERTIFIED"
    )
    assert data["settlement_status"] in (
        "UNBILLED", "CLAIMED", "CREDITED", "CLOSED_NO_CREDIT"
    )
    assert data["measured_impressions"] > 0
    assert 0 <= data["measurable_impressions"] <= data["measured_impressions"]
    assert 0 <= data["in_view_impressions"] <= data["measurable_impressions"]
    if data["assessed_tier"] is not None:
        assert data["assessed_tier"] in list(TIER_RANK) + ["UNRATED"]
    assert isinstance(data["sophistication_flag"], bool)
    assert isinstance(data["suitability_breach_flag"], bool)


def assert_ivt_finding(data: dict):
    assert_common_fields(data, "IvtFinding")
    assert data["ivt_class"] in (
        "GENERAL_BOT", "DATACENTER", "SIVT_HIJACKED_DEVICE", "SIVT_AD_FARM",
        "SIVT_INCENTIVIZED",
    )
    assert data["ivt_family"] in ("GIVT", "SIVT")
    assert data["flagged_impressions"] > 0
    assert 0.0 <= float(data["confidence"]) <= 1.0
    assert data["status"] in ("PROPOSED", "CONFIRMED", "RETRACTED")


def assert_refund_claim(data: dict):
    assert_common_fields(data, "RefundClaim")
    assert data["claim_state"] in (
        "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "REVERSED"
    )
    assert isinstance(data["batch_ids"], list) and 1 <= len(data["batch_ids"]) <= 20
    assert len(set(data["batch_ids"])) == len(data["batch_ids"]), "batch_ids must be distinct"


def assert_publisher_scorecard(data: dict):
    assert isinstance(data["adjudicated_batch_count"], int)
    for rate in ("ivt_rate_avg", "viewability_rate_avg", "overturn_rate"):
        assert 0.0 <= float(data[rate]) <= 1.0, f"{rate} out of range: {data[rate]}"
    assert 0.00 <= float(data["quality_index"]) <= 100.00
    assert data["tier_band"] in ("PREFERRED", "STANDARD", "WATCHLIST", "SUSPENDED_QUALITY")


def assert_pre_bid_decision(data: dict):
    assert data["decision"] in ("ALLOW", "ALLOW_OVERRIDE", "BLOCK")
    assert data["reason_code"] in (
        "PUBLISHER_RESTRICTED", "LIST_EXCLUSION", "LIST_INCLUSION",
        "UNRATED_INVENTORY", "BELOW_SUITABILITY_FLOOR", "MEETS_FLOOR",
    )
    assert data["effective_tier"] in list(TIER_RANK) + ["UNRATED"]
    assert data["floor_tier"] in TIER_RANK


# ---------------------------------------------------------------------------
# domain invariants
# ---------------------------------------------------------------------------
def assert_impression_conservation(batch: dict):
    """PRD 2.11: "For every scored batch, `measured_impressions` equals the sum of
    `qualified_in_view_impressions`, `non_viewable_impressions` and
    `unmeasurable_impressions`." The viewability-side identity is therefore
    scoped to batches that have actually been scored - a freshly ingested batch
    still carries "every computed figure at its default and `scored_at` null"
    (PRD 3.7), so the three components are 0 and the identity does not apply.

    The invalid-traffic identity is unconditional: PRD 2.11 requires
    net_billable + ivt == measured "before a confirmation, after a confirmation,
    and again after the matching retraction".
    """
    if batch.get("scored_at") is not None:
        assert (
            batch["measured_impressions"]
            == batch["qualified_in_view_impressions"]
            + batch["non_viewable_impressions"]
            + batch["unmeasurable_impressions"]
        ), (
            "measured_impressions must equal qualified + non_viewable + unmeasurable, got "
            f"{batch['measured_impressions']} vs "
            f"{batch['qualified_in_view_impressions']}+{batch['non_viewable_impressions']}"
            f"+{batch['unmeasurable_impressions']}"
        )
    assert (
        batch["net_billable_impressions"] + batch["ivt_impressions"]
        == batch["measured_impressions"]
    ), "net_billable_impressions + ivt_impressions must equal measured_impressions"


def assert_credit_double_entry(advertiser: dict, publisher: dict, expected_cents: int):
    """PRD 2.11: every cent credited to the advertiser is charged to the publisher."""
    assert advertiser["credit_received_cents_total"] == expected_cents, (
        f"advertiser credit_received_cents_total expected {expected_cents}, "
        f"got {advertiser['credit_received_cents_total']}"
    )
    assert publisher["credit_issued_cents_total"] == expected_cents, (
        f"publisher credit_issued_cents_total expected {expected_cents}, "
        f"got {publisher['credit_issued_cents_total']}"
    )


def assert_money_triple(claim: dict, gross: int, rate: float, fee: int, net: int):
    """The frozen money figures of an approved claim (PRD 3.9)."""
    assert claim["gross_credit_cents"] == gross, (
        f"gross_credit_cents expected {gross}, got {claim['gross_credit_cents']}"
    )
    assert float(claim["admin_fee_rate"]) == rate, (
        f"admin_fee_rate expected {rate}, got {claim['admin_fee_rate']}"
    )
    assert claim["admin_fee_cents"] == fee, (
        f"admin_fee_cents expected {fee}, got {claim['admin_fee_cents']}"
    )
    assert claim["net_credit_cents"] == net, (
        f"net_credit_cents expected {net}, got {claim['net_credit_cents']}"
    )
    assert claim["net_credit_cents"] == claim["gross_credit_cents"] - claim["admin_fee_cents"]


def assert_rate_precision(value, field: str = "rate"):
    """Rates are carried to 4 decimal places (PRD 2.6)."""
    assert value is not None, f"{field} must be present"
    quantised = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    assert Decimal(str(value)) == quantised, (
        f"{field} must carry at most 4 decimal places, got {value}"
    )


def assert_score_precision(value, field: str = "score"):
    """Scores are carried to 2 decimal places (PRD 2.6)."""
    assert value is not None, f"{field} must be present"
    quantised = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert Decimal(str(value)) == quantised, (
        f"{field} must carry at most 2 decimal places, got {value}"
    )
