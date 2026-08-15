"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_primary_common_fields(data: dict):
    """Common fields carried by every primary resource (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_snapshot_common_fields(data: dict):
    """Ledger-style snapshots carry only id and created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "snapshot resources must not carry updated_at"
    assert "version" not in data, "snapshot resources must not carry version"


def assert_publication(data: dict):
    _assert_primary_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["issn"], str) and len(data["issn"]) == 8
    assert data["frequency"] in ("WEEKLY", "MONTHLY", "QUARTERLY")
    assert data["circulation_model"] in ("PAID", "CONTROLLED", "MIXED")
    assert isinstance(data["issues_per_year"], int)
    assert isinstance(data["base_cover_price_cents"], int)
    assert data["deferred_revenue_method"] in ("PRO_RATA_ISSUE", "STRAIGHT_LINE_MONTH")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CEASED")


def assert_issue(data: dict):
    _assert_primary_common_fields(data)
    assert isinstance(data["publication_id"], str)
    assert isinstance(data["issue_number"], int)
    assert isinstance(data["volume_number"], int)
    for field in ("cover_date", "editorial_close_date", "ad_close_date",
                  "ship_to_printer_date", "mail_date"):
        assert is_iso8601_timestamp(data.get(field, "")), f"{field} must be ISO 8601"
    assert isinstance(data["ad_pages_sold"], int)
    assert isinstance(data["newsstand_buffer_copies"], int)
    assert data["status"] in (
        "PLANNING", "EDITORIAL_CLOSED", "AD_CLOSED", "AT_PRINTER", "MAILED", "FINALIZED"
    )


def assert_subscriber(data: dict):
    _assert_primary_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["address_line1"], str) and data["address_line1"]
    assert isinstance(data["city"], str) and data["city"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["postal_code"], str) and data["postal_code"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert isinstance(data["is_deliverable"], bool)
    assert data["circulation_class"] in (
        "PAID_QUALIFIED", "CONTROLLED_QUALIFIED", "NON_QUALIFIED"
    )


def assert_subscription(data: dict):
    _assert_primary_common_fields(data)
    assert isinstance(data["subscriber_id"], str)
    assert isinstance(data["publication_id"], str)
    assert isinstance(data["start_issue_id"], str)
    assert isinstance(data["term_issues"], int) and data["term_issues"] > 0
    assert isinstance(data["price_paid_cents"], int) and data["price_paid_cents"] >= 0
    assert data["qualification_tier"] in ("PAID", "CONTROLLED", "COMPLIMENTARY")
    assert data["payment_method"] in ("CARD", "CHECK", "INVOICE", "NONE")
    assert isinstance(data["issues_served"], int)
    assert isinstance(data["issues_remaining"], int)
    assert isinstance(data["issues_suspended_count"], int)
    assert isinstance(data["renewal_effort_number"], int)
    assert data["status"] in (
        "PENDING_START", "ACTIVE", "SUSPENDED", "GRACE", "EXPIRED", "CANCELLED", "RENEWED"
    )


def assert_subscription_term(data: dict):
    _assert_primary_common_fields(data)
    assert isinstance(data["subscription_id"], str)
    assert isinstance(data["term_index"], int) and data["term_index"] >= 1
    assert isinstance(data["issues_in_term"], int)
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["deferred_balance_cents"], int)
    assert isinstance(data["recognized_balance_cents"], int)
    assert data["recognition_variant"] in ("PRO_RATA_ISSUE", "STRAIGHT_LINE_MONTH")
    assert data["status"] in ("OPEN", "FULLY_RECOGNIZED", "REFUNDED", "PARTIALLY_REFUNDED")


def assert_renewal_series(data: dict):
    _assert_primary_common_fields(data)
    assert isinstance(data["publication_id"], str)
    assert isinstance(data["series_code"], str) and data["series_code"]
    assert isinstance(data["effort_offsets_days"], list)
    assert isinstance(data["effort_pricing_cents"], list)
    assert data["max_efforts"] == len(data["effort_offsets_days"])
    assert isinstance(data["is_default"], bool)


def assert_renewal_event(data: dict):
    _assert_primary_common_fields(data)
    assert isinstance(data["subscription_id"], str)
    assert isinstance(data["series_code"], str)
    assert isinstance(data["effort_number"], int) and data["effort_number"] >= 1
    assert is_iso8601_timestamp(data.get("sent_at", "")), "sent_at must be ISO 8601"
    assert isinstance(data["offered_price_cents"], int)
    assert data["response"] in ("PENDING", "ACCEPTED", "DECLINED", "EXPIRED")


def assert_mailing_batch(data: dict):
    _assert_primary_common_fields(data)
    assert isinstance(data["issue_id"], str)
    assert isinstance(data["batch_label"], str) and data["batch_label"]
    assert data["postal_class"] in ("PERIODICAL", "STANDARD", "FIRST_CLASS")
    assert data["entry_point"] in ("ORIGIN", "DDU", "DSCF", "SCF")
    assert isinstance(data["permit_number"], str) and data["permit_number"]
    assert data["status"] in (
        "DRAFT", "LABELS_GENERATED", "POSTAL_VERIFIED", "TENDERED", "CONFIRMED"
    )


def assert_mailing_label(data: dict):
    _assert_snapshot_common_fields(data)
    assert isinstance(data["batch_id"], str)
    assert isinstance(data["subscription_id"], str)
    assert isinstance(data["subscriber_id"], str)
    assert isinstance(data["address_block"], str)
    assert isinstance(data["postal_code"], str)
    assert isinstance(data["is_controlled_copy"], bool)
    assert isinstance(data["postage_cents"], int)


def assert_postal_statement(data: dict):
    _assert_snapshot_common_fields(data)
    assert isinstance(data["batch_id"], str)
    assert data["form_number"] in ("PS_3541", "PS_3541_A", "PS_3602_R")
    assert isinstance(data["paid_piece_count"], int)
    assert isinstance(data["controlled_piece_count"], int)
    assert isinstance(data["paid_percentage_bps"], int)
    assert isinstance(data["total_postage_cents"], int)


def assert_back_issue_order(data: dict):
    _assert_primary_common_fields(data)
    assert isinstance(data["subscriber_id"], str)
    assert isinstance(data["issue_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["shipping_cents"], int)
    assert isinstance(data["total_charged_cents"], int)
    assert isinstance(data["is_recognized_revenue"], bool)
    assert data["status"] in (
        "PENDING", "FULFILLED", "SHIPPED", "DELIVERED", "CANCELLED", "REFUNDED"
    )


def assert_digital_entitlement(data: dict):
    _assert_primary_common_fields(data)
    assert isinstance(data["subscription_id"], str)
    assert isinstance(data["issue_id"], str)
    assert data["access_level"] in ("FULL", "PREVIEW", "NONE")
    assert is_iso8601_timestamp(data.get("granted_at", "")), "granted_at must be ISO 8601"


def assert_deferred_revenue_entry(data: dict):
    _assert_snapshot_common_fields(data)
    assert isinstance(data["subscription_term_id"], str)
    assert isinstance(data["issue_id"], str)
    assert is_iso8601_timestamp(data.get("recognized_at", "")), "recognized_at must be ISO 8601"
    assert isinstance(data["amount_cents"], int)
    assert data["variant"] in ("PRO_RATA_ISSUE", "STRAIGHT_LINE_MONTH")
    assert data["entry_type"] in ("RECOGNITION", "REVERSAL", "REFUND_LIQUIDATION")


def assert_circulation_audit_record(data: dict):
    _assert_primary_common_fields(data)
    assert isinstance(data["publication_id"], str)
    assert is_iso8601_timestamp(data.get("audit_period_start", ""))
    assert is_iso8601_timestamp(data.get("audit_period_end", ""))
    assert data["status"] in ("DRAFT", "FILED", "AUDIT_PASSED", "AUDIT_FAILED")


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_term_balance_invariant(term: dict):
    """While a term stands OPEN, recognized + deferred always sum to gross (PRD §2.10)."""
    total = term["recognized_balance_cents"] + term["deferred_balance_cents"]
    assert total == term["gross_amount_cents"], (
        f"recognized ({term['recognized_balance_cents']}) + deferred "
        f"({term['deferred_balance_cents']}) must equal gross ({term['gross_amount_cents']})"
    )


def assert_print_run_invariant(issue: dict):
    """With no override, print_run == qualified_subscriber_count + newsstand_buffer_copies (PRD §3.3)."""
    assert issue.get("print_run_override") is None, "invariant applies only without an override"
    assert issue["print_run"] == issue["qualified_subscriber_count"] + issue["newsstand_buffer_copies"], (
        f"print_run ({issue['print_run']}) must equal qualified_subscriber_count "
        f"({issue['qualified_subscriber_count']}) + newsstand_buffer_copies "
        f"({issue['newsstand_buffer_copies']})"
    )
