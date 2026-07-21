"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC with three fractional digits, got {data.get('created_at')!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be an integer starting at 1, got {data.get('version')!r}"
        )


def assert_subscription_plan(data: dict):
    _common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str)
    assert isinstance(data["annual_fee_cents"], int) and data["annual_fee_cents"] >= 0
    assert isinstance(data["included_release_slots"], int) and data["included_release_slots"] >= 1
    assert 0 <= data["commission_bps"] <= 10000
    assert isinstance(data["allows_content_id"], bool)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_store(data: dict):
    _common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["delivery_lead_days"], int) and data["delivery_lead_days"] >= 0
    assert isinstance(data["supports_pre_save"], bool)
    assert isinstance(data["requires_isrc"], bool)
    assert isinstance(data["requires_explicit_flag"], bool)
    assert 0 <= data["surcharge_bps"] <= 2000
    assert isinstance(data["max_concurrent_deliveries"], int) and data["max_concurrent_deliveries"] >= 1
    assert data["status"] in ("ACTIVE", "PAUSED")


def assert_artist(data: dict):
    _common(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["legal_name"], str)
    assert len(data["country_code"]) == 2 and data["country_code"].isupper()
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["lifetime_gross_cents"], int) and data["lifetime_gross_cents"] >= 0
    assert isinstance(data["live_track_count"], int) and data["live_track_count"] >= 0


def assert_subscription(data: dict):
    _common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "PAST_DUE", "EXPIRED", "CANCELLED")
    assert isinstance(data["releases_used"], int) and data["releases_used"] >= 0
    assert isinstance(data["auto_renew"], bool)


def assert_release(data: dict):
    _common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "IN_REVIEW", "APPROVED", "REJECTED", "LIVE", "TAKEN_DOWN"
    )
    assert data["delivery_status"] in (
        "NONE", "QUEUED", "PARTIAL", "DELIVERED", "TAKEDOWN_PENDING", "TAKEN_DOWN"
    )
    assert isinstance(data["pre_save_count"], int) and data["pre_save_count"] >= 0
    assert isinstance(data["pre_save_enabled"], bool)
    if data.get("upc") is not None:
        assert len(data["upc"]) == 12 and data["upc"].isdigit(), "upc must be exactly 12 digits"


def assert_track(data: dict):
    _common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "INACTIVE")
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] >= 1
    assert isinstance(data["track_number"], int) and data["track_number"] >= 1
    assert isinstance(data["content_id_enabled"], bool)
    if data.get("isrc") is not None:
        assert len(data["isrc"]) == 12 and data["isrc"].isalnum(), (
            "isrc must be exactly 12 alphanumeric characters"
        )


def assert_collaborator(data: dict):
    _common(data)
    assert data["tax_form_status"] in ("MISSING", "SUBMITTED", "VERIFIED", "EXPIRED")
    assert data["payout_method"] in ("PAYPAL", "BANK_TRANSFER")
    assert data["status"] in ("ACTIVE", "ARCHIVED")
    assert len(data["country_code"]) == 2 and data["country_code"].isupper()
    assert_collaborator_balance_invariants(data)


def assert_collaborator_balance_invariants(data: dict):
    """Every running total on a payee is a non-negative whole number of cents."""
    for field in ("pending_payout_cents", "lifetime_paid_cents", "reversed_payout_cents"):
        assert isinstance(data[field], int), f"{field} must be whole cents, got {data[field]!r}"
        assert data[field] >= 0, f"{field} must never go negative, got {data[field]}"


def assert_settled_total(data: dict, expected_total: int):
    """pending + lifetime_paid + reversed is conserved across pay and reverse."""
    total = (
        data["pending_payout_cents"] + data["lifetime_paid_cents"] + data["reversed_payout_cents"]
    )
    assert total == expected_total, (
        f"Expected settled total {expected_total}, got {total} "
        f"(pending={data['pending_payout_cents']}, paid={data['lifetime_paid_cents']}, "
        f"reversed={data['reversed_payout_cents']})"
    )


def assert_split_sheet(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "PENDING_ACCEPTANCE", "LOCKED", "SUPERSEDED")
    assert isinstance(data["total_share_bps"], int) and data["total_share_bps"] >= 0
    assert isinstance(data["accepted_share_count"], int) and data["accepted_share_count"] >= 0


def assert_split_share(data: dict):
    _common(data)
    assert 1 <= data["share_bps"] <= 10000
    assert isinstance(data["accepted"], bool)


def assert_delivery(data: dict):
    _common(data)
    assert data["status"] in (
        "QUEUED", "SENT", "ACCEPTED", "REJECTED", "TAKEDOWN_REQUESTED", "TAKEN_DOWN"
    )
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_royalty_statement(data: dict):
    _common(data)
    assert data["status"] in ("OPEN", "INGESTING", "RECONCILED", "CLOSED")
    for field in (
        "line_count", "gross_cents", "content_id_gross_cents", "commission_cents",
        "content_id_bonus_cents", "provisional_net_cents", "net_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be a whole integer, got {data[field]!r}"


def assert_royalty_line(data: dict):
    """A royalty line is an append-only ledger entry: id and created_at only."""
    _common(data, versioned=False)
    assert "updated_at" not in data, "a royalty line must not carry updated_at"
    assert "version" not in data, "a royalty line must not carry a version field"
    assert data["source"] in ("STREAMING", "DOWNLOAD", "CONTENT_ID")
    assert isinstance(data["units"], int) and data["units"] >= 0
    assert isinstance(data["gross_cents"], int) and data["gross_cents"] >= 0


def assert_payout(data: dict):
    _common(data)
    assert data["status"] in ("PENDING", "APPROVED", "PAID", "REVERSED")
    assert isinstance(data["auto_approved"], bool)
    for field in ("gross_cents", "withholding_bps", "withholding_cents", "net_cents"):
        assert isinstance(data[field], int), f"{field} must be a whole integer, got {data[field]!r}"
    assert data["net_cents"] == data["gross_cents"] - data["withholding_cents"], (
        "net_cents must equal gross_cents less withholding_cents"
    )


def assert_tax_form(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "VOIDED")
    assert isinstance(data["total_paid_cents"], int) and data["total_paid_cents"] >= 0
    assert 2020 <= data["tax_year"] <= 2100


def assert_statement_summary(data: dict):
    for field in (
        "statement_id", "gross_cents", "content_id_gross_cents", "commission_cents",
        "content_id_bonus_cents", "provisional_net_cents", "net_cents",
        "variant_delta_cents", "payout_count", "payout_gross_total_cents",
    ):
        assert field in data, f"statement summary must report {field}"
    assert data["variant_delta_cents"] == data["net_cents"] - data["provisional_net_cents"], (
        "variant_delta_cents must be the final net_cents less provisional_net_cents"
    )


def assert_payout_totals_match_statement_net(payouts: list, statement_net_cents: int):
    """The sum of gross_cents over the payouts a close created equals the statement net exactly."""
    total = sum(p["gross_cents"] for p in payouts)
    assert total == statement_net_cents, (
        f"Payout gross total {total} must equal statement net_cents {statement_net_cents} "
        f"with nothing lost and nothing invented"
    )
