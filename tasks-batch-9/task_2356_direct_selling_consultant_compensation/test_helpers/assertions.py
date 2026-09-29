"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import DISTRIBUTION_BUCKET_BOUNDS


def assert_common_fields(data: dict, expect_version_and_updated_at: bool = True):
    """PRD §2.4 — every resource carries a UUID id and an ISO 8601 created_at.

    Almost every resource also carries updated_at and a version starting at 1;
    a tax jurisdiction carries neither.
    """
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if expect_version_and_updated_at:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be an integer starting at 1, got {data.get('version')!r}"
        )


def same_instant(actual, expected) -> bool:
    """Compare two ISO 8601 UTC values for the same instant.

    PRD §2.4 documents `created_at` with three fractional digits while PRD §2.5 writes the
    logical clock's own value without them, so `2026-08-01T00:00:00Z` and
    `2026-08-01T00:00:00.000Z` name the same instant and must compare equal.
    """
    if actual is None or expected is None:
        return actual is expected

    def normalise(value: str) -> str:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1]
        if "." in text:
            head, frac = text.split(".", 1)
            frac = frac.rstrip("0")
            text = f"{head}.{frac}" if frac else head
        return text

    return normalise(actual) == normalise(expected)


def assert_instant(actual, expected, label="timestamp"):
    """Assert that a stamped timestamp names the expected instant."""
    assert same_instant(actual, expected), f"{label}: expected {expected!r}, got {actual!r}"


def assert_compensation_plan(data: dict):
    assert_common_fields(data)
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["compression_mode"] in ("DYNAMIC", "STATIC")
    assert isinstance(data["consultant_count"], int) and data["consultant_count"] >= 0
    assert isinstance(data["rank_ladder"], list) and len(data["rank_ladder"]) >= 1
    orders = [rung["rank_order"] for rung in data["rank_ladder"]]
    assert sorted(orders) == list(range(1, len(orders) + 1)), (
        f"rank_order values must be the contiguous integers from 1, got {orders}"
    )
    codes = [rung["rank_code"] for rung in data["rank_ladder"]]
    assert len(set(codes)) == len(codes), f"rank_code must be unique within the ladder: {codes}"
    for rung in data["rank_ladder"]:
        assert len(rung["override_bp_by_level"]) == rung["override_levels"], (
            "override_bp_by_level length must equal override_levels for "
            f"{rung['rank_code']}"
        )
    bands = data["pv_bonus_bands"]
    assert isinstance(bands, list) and len(bands) >= 1
    assert bands[-1]["upper_points"] is None, "the final bonus band must carry a null upper_points"


def assert_tax_jurisdiction(data: dict):
    """PRD §2.4 — a jurisdiction row carries only id and created_at."""
    assert_common_fields(data, expect_version_and_updated_at=False)
    assert "version" not in data, "a tax jurisdiction has no version"
    assert "updated_at" not in data, "a tax jurisdiction has no updated_at"
    assert len(data["state_code"]) == 2 and data["state_code"].isupper()
    assert 0 <= data["tax_rate_bp"] <= 2_000
    assert isinstance(data["facilitator_agreement_active"], bool)
    if data["facilitator_agreement_active"]:
        assert data["tax_basis_mode"] == "SRP"
        assert data["remitter"] == "COMPANY"
    else:
        assert data["tax_basis_mode"] == "NET_PRICE"
        assert data["remitter"] == "CONSULTANT"


def assert_product(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["wholesale_price_cents"] >= 0
    assert data["srp_cents"] >= data["wholesale_price_cents"], (
        "srp_cents must be at least the wholesale price"
    )
    assert data["volume_points_per_unit"] >= 0
    assert isinstance(data["commissionable"], bool)
    assert isinstance(data["buyback_eligible"], bool)
    assert isinstance(data["is_starter_kit"], bool)


def assert_enrollment_application(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "READY_FOR_APPROVAL", "APPROVED", "REJECTED", "WITHDRAWN")
    assert data["agreement_status"] in ("NOT_ACCEPTED", "ACCEPTED")
    assert data["identity_status"] in ("UNVERIFIED", "PENDING_REVIEW", "VERIFIED", "FAILED")
    assert data["kit_status"] in ("UNPAID", "PAID")
    assert data["kit_total_cents"] == data["kit_charge_cents"] + data["kit_tax_cents"], (
        "kit_total_cents is kit_charge_cents plus kit_tax_cents"
    )
    assert data["identity_attempt_count"] >= 0


def assert_consultant(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "PROBATION", "SUSPENDED", "INACTIVE", "TERMINATED")
    assert data["rank_source"] in (
        "ENROLLMENT",
        "EARNED",
        "ADMIN_ADJUSTED",
        "MAINTENANCE_DEMOTION",
        "REINSTATEMENT",
    )
    assert isinstance(data["upline_path"], list)
    assert data["genealogy_depth"] == len(data["upline_path"]), (
        "genealogy_depth is the number of entries in upline_path"
    )
    assert data["clawback_balance_cents"] >= 0
    assert isinstance(data["payout_hold"], bool)
    assert data["direct_downline_count"] >= 0


def assert_product_order(data: dict):
    assert_common_fields(data)
    assert data["payment_status"] in ("PENDING", "PAID", "REFUNDED_PARTIAL", "REFUNDED_FULL")
    assert data["fulfillment_status"] in (
        "NEW",
        "SHIPPED",
        "DELIVERED",
        "RETURNED_PARTIAL",
        "RETURNED_FULL",
    )
    assert data["order_type"] in ("PERSONAL_INVENTORY", "RETAIL_CUSTOMER", "BUSINESS_SUPPLY")
    assert 1 <= len(data["lines"]) <= 20
    assert data["merchandise_subtotal_cents"] == sum(
        line["line_wholesale_subtotal_cents"] for line in data["lines"]
    ), "merchandise_subtotal_cents is the sum of the lines' wholesale subtotals"
    assert data["srp_basis_cents"] == sum(
        line["line_srp_subtotal_cents"] for line in data["lines"]
    ), "srp_basis_cents is the sum of the lines' suggested-retail subtotals"
    assert data["tax_total_cents"] == sum(line["line_tax_cents"] for line in data["lines"]), (
        "tax_total_cents is the sum of the already-rounded line_tax_cents values"
    )
    assert (
        data["total_due_cents"]
        == data["merchandise_subtotal_cents"] + data["tax_total_cents"] + data["shipping_cents"]
    ), "total_due_cents is merchandise plus tax plus shipping"
    assert data["total_volume_points"] == sum(
        line["line_volume_points"] for line in data["lines"]
    ), "total_volume_points is the sum of every line's line_volume_points"
    assert data["commissionable_volume_points"] == sum(
        line["line_volume_points"] for line in data["lines"] if line["commissionable"]
    ), "commissionable_volume_points sums only the commissionable lines"
    assert not (data["payment_status"] == "PENDING" and data["fulfillment_status"] == "SHIPPED"), (
        "PENDING payment with SHIPPED fulfillment is unreachable"
    )


def assert_qualification_period(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "LOCKED", "CLOSED", "REOPENED")
    assert data["period_end"] > data["period_start"], "period_end must be strictly after period_start"
    assert data["reopen_count"] >= 0
    assert isinstance(data["correction_pending"], bool)


def assert_period_qualification(data: dict):
    assert_common_fields(data)
    assert (
        data["net_personal_volume_points"]
        == data["personal_volume_points"] - data["returned_volume_points"]
    ), "net_personal_volume_points is the personal points minus the returned points"
    assert 0 <= data["sell_through_bp"] <= 10_000
    assert data["active_leg_count"] >= 0
    if data["qualified_rank_code"] is None:
        assert data["qualified_rank_order"] == 0
        assert data["paid_as_rank_code"] is None


def assert_commission_run(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "CALCULATED", "APPROVED", "PAID", "REVERSED")
    assert data["distributable_pool_cents"] == (
        data["gross_total_cents"] + data["forfeited_to_company_cents"]
    ), "distributable_pool_cents is gross_total_cents plus forfeited_to_company_cents"
    assert data["calculation_sequence"] >= 0
    assert isinstance(data["correction_flagged"], bool)


def assert_commission_statement(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "VOIDED")
    assert data["payout_status"] in ("PENDING", "PAYABLE", "CARRIED_FORWARD", "PAID", "VOIDED")
    assert data["gross_commission_cents"] == (
        data["retail_profit_cents"] + data["pv_bonus_cents"] + data["override_total_cents"]
    ), "gross_commission_cents is retail profit plus the personal volume bonus plus overrides"
    assert data["net_payable_cents"] == (
        data["gross_commission_cents"] - data["withholding_cents"]
    ), "net_payable_cents is gross_commission_cents minus withholding_cents"
    assert data["override_total_cents"] == sum(
        element["amount_cents"] for element in data["override_breakdown"]
    ), "override_total_cents is the sum of the breakdown's amount_cents values"


def assert_buyback_request(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "REFUNDED")
    assert data["net_refund_cents"] >= 0, "a refund is never negative"
    assert data["unrecovered_clawback_cents"] >= 0
    assert data["net_refund_cents"] == max(
        0,
        data["gross_refund_cents"]
        - data["restocking_fee_cents"]
        - data["commission_clawback_cents"],
    ), "net_refund_cents is the greater of 0 and gross minus fee minus clawback"


def assert_compliance_case(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "SANCTIONED", "DISMISSED", "APPEALED")
    assert data["claim_type"] in (
        "INCOME_CLAIM",
        "PRODUCT_CLAIM",
        "PRICING_VIOLATION",
        "CROSS_RECRUITING",
    )
    assert data["appeal_count"] in (0, 1)
    assert data["sanction_order"] in (0, 1, 2, 3, 4)


def assert_income_disclosure_statement(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "LEGAL_REVIEW", "PUBLISHED", "SUPERSEDED")
    assert data["population_basis"] in ("ALL_ENROLLED", "PAID_ONLY")
    assert data["population_count"] >= 1
    buckets = data["distribution_buckets"]
    assert len(buckets) == 4, "distribution_buckets is always four bands"
    for bucket, bounds in zip(buckets, DISTRIBUTION_BUCKET_BOUNDS):
        assert bucket["lower_cents"] == bounds["lower_cents"]
        assert bucket["upper_cents"] == bounds["upper_cents"]
    assert sum(b["consultant_count"] for b in buckets) == data["population_count"], (
        "every population member falls into exactly one band"
    )
    if data["supersede_reason"] != "NEWER_PUBLICATION":
        assert data.get("superseded_by_id") is None, (
            "superseded_by_id is set only in the NEWER_PUBLICATION case"
        )


def assert_bucket_counts_and_shares(data: dict, counts: list, shares: list):
    """Compare a disclosure's four bands against expected counts and share_bp values."""
    actual_counts = [b["consultant_count"] for b in data["distribution_buckets"]]
    actual_shares = [b["share_bp"] for b in data["distribution_buckets"]]
    assert actual_counts == counts, f"expected bucket counts {counts}, got {actual_counts}"
    assert actual_shares == shares, f"expected bucket shares {shares}, got {actual_shares}"


def find_line(order: dict, product_id: str) -> dict:
    """Return the order line naming a given product."""
    for line in order["lines"]:
        if line["product_id"] == product_id:
            return line
    raise AssertionError(f"order {order['id']} has no line for product {product_id}")
