"""Entity assertions and domain invariant checkers."""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating any number of fractional digits.

    The PRD pins domain timestamps (`filed_at_utc`, `triggered_at_utc`,
    `certified_at_utc`, `recommended_at_utc`, `responded_at_utc` and the derived
    `proof_of_claim_deadline_utc`) to a specific *instant* of the logical clock; it
    does not state how many fractional digits those fields render with. Comparisons
    are therefore made on the instant, not on the byte string.
    """
    assert isinstance(value, str), f"expected an ISO 8601 instant string, got {value!r}"
    assert is_iso8601_timestamp(value), f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual, expected: str, message: str = "") -> None:
    """Assert that `actual` names exactly the same UTC instant as `expected`."""
    detail = message or f"expected the instant {expected}, got {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected), detail


def _assert_identity(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be an ISO 8601 timestamp, got {data.get('created_at')!r}"


def _assert_versioned(data: dict) -> None:
    _assert_identity(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be an ISO 8601 timestamp, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


def assert_insolvency(data: dict) -> None:
    _assert_versioned(data)
    assert isinstance(data["insurer_name"], str) and data["insurer_name"]
    assert isinstance(data["naic_code"], str) and data["naic_code"]
    assert data["domiciliary_state_code"].isupper() and len(data["domiciliary_state_code"]) == 2
    assert data["status"] in ("DECLARED", "TRIGGERED", "CLOSED"), data["status"]
    for field in (
        "estate_remitted_cents",
        "estate_distributed_cents",
        "estate_undistributed_cents",
        "estate_returned_cents",
        "administrative_expense_cents",
        "administrative_paid_cents",
        "reserved_claim_cents",
        "pending_up_liability_cents",
        "referral_pending_count",
        "assessment_shortfall_cents",
        "distribution_sequence",
        "policy_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must never go negative, got {data[field]}"


def assert_estate_ledger_identity(insolvency: dict) -> None:
    """The closed estate ledger identity the PRD requires after every write."""
    remitted = insolvency["estate_remitted_cents"]
    total = (
        insolvency["estate_distributed_cents"]
        + insolvency["estate_undistributed_cents"]
        + insolvency["estate_returned_cents"]
    )
    assert remitted == total, (
        "estate_remitted_cents must equal distributed + undistributed + returned; "
        f"got {remitted} vs {total}"
    )


def assert_coverage_profile(data: dict) -> None:
    """The coverage configuration row carries only id and created_at."""
    _assert_identity(data)
    assert "updated_at" not in data, "the coverage configuration row has no updated_at field"
    assert "version" not in data, "the coverage configuration row has no version field"
    assert data["line_of_business"] in (
        "PERSONAL_AUTO",
        "HOMEOWNERS",
        "COMMERCIAL_GENERAL_LIABILITY",
        "WORKERS_COMPENSATION",
    )
    assert data["per_claim_cap_cents"] > 0
    assert data["per_policy_aggregate_cap_cents"] >= data["per_claim_cap_cents"]
    assert data["unearned_premium_cap_cents"] > 0
    assert data["refund_priority_class"] in (1, 2, 3)
    assert data["cap_order_mode"] in ("OFFSET_THEN_CAP", "CAP_THEN_OFFSET")
    assert isinstance(data["covers_punitive_damages"], bool)


def assert_member_insurer(data: dict) -> None:
    _assert_versioned(data)
    assert data["account_status"] in ("ACTIVE", "IMPAIRED", "WITHDRAWN")
    assert 0 <= data["annual_cap_rate_bps"] <= 200
    assert data["direct_written_premium_cents"] >= 0
    assert 2000 <= data["base_year"] <= 2100


def assert_assessment(data: dict) -> None:
    _assert_versioned(data)
    assert data["status"] in ("DRAFT", "CERTIFIED", "SETTLED")
    assert data["needed_amount_cents"] > 0
    assert data["levied_amount_cents"] >= 0
    assert data["shortfall_cents"] >= 0
    assert data["member_count"] >= 0
    assert data["collected_amount_cents"] >= 0
    assert (
        data["levied_amount_cents"] + data["shortfall_cents"] == data["needed_amount_cents"]
    ), "levied plus shortfall must reconcile to the needed amount"


def assert_member_assessment(data: dict) -> None:
    _assert_versioned(data)
    assert data["billing_status"] in ("INVOICED", "PARTIALLY_PAID", "PAID", "DELINQUENT")
    assert data["recoupment_status"] in (
        "NOT_STARTED",
        "SURCHARGE_FILED",
        "RECOUPING",
        "RECOUPED",
    )
    assert data["levied_amount_cents"] >= 0
    assert data["cap_amount_cents"] >= 0
    assert data["paid_amount_cents"] <= data["levied_amount_cents"]
    assert data["recouped_amount_cents"] <= data["levied_amount_cents"]
    assert isinstance(data["capped"], bool)


def assert_poc_transfer(data: dict) -> None:
    _assert_versioned(data)
    assert data["status"] in ("RECEIVED", "CONVERTED", "PARTIALLY_CONVERTED", "REJECTED")
    assert data["record_count"] >= 1
    assert data["converted_count"] + data["rejected_count"] <= data["record_count"]
    assert isinstance(data["rejection_reasons"], list)


def assert_transferred_policy(data: dict) -> None:
    _assert_versioned(data)
    assert data["status"] in ("IMPORTED", "CANCELLED_BY_ORDER", "EXPIRED_BEFORE_ORDER")
    assert data["annual_premium_cents"] > 0
    assert data["expiration_date"] > data["effective_date"]
    assert data["unexpired_days"] >= 0
    assert data["aggregate_paid_cents"] >= 0
    assert isinstance(data["up_refund_filed"], bool)


def assert_covered_claim(data: dict) -> None:
    _assert_versioned(data)
    assert data["status"] in (
        "RECEIVED",
        "SCREENED_ELIGIBLE",
        "DENIED_NOT_COVERED",
        "ADJUSTING",
        "RECOMMENDED",
        "REFERRAL_PENDING",
        "REFERRED_OUT",
        "APPROVED",
        "PARTIALLY_PAID",
        "PAID",
    )
    assert data["gross_loss_cents"] > 0
    assert data["cap_binding"] in ("NONE", "PER_CLAIM", "PER_POLICY_AGGREGATE")
    assert data["net_payable_cents"] >= 0
    assert data["alt_net_payable_cents"] >= 0
    assert data["paid_amount_cents"] >= 0
    assert data["remand_count"] >= 0
    assert is_iso8601_timestamp(data["filed_at_utc"]), "filed_at_utc must be ISO 8601"


def assert_claim_reserve_identity(claim: dict) -> None:
    """Reserve plus payments always reconcile to the statutory net payable."""
    outstanding = claim["net_payable_cents"] - claim["paid_amount_cents"]
    assert outstanding >= 0, (
        f"paid_amount_cents {claim['paid_amount_cents']} must never exceed "
        f"net_payable_cents {claim['net_payable_cents']}"
    )
    assert outstanding + claim["paid_amount_cents"] == claim["net_payable_cents"]


def assert_other_insurance(data: dict) -> None:
    _assert_versioned(data)
    assert data["status"] in ("UNEXHAUSTED", "PURSUING", "EXHAUSTED", "CARRIER_DENIED")
    assert data["coverage_type"] in ("PRIMARY", "EXCESS", "UMBRELLA")
    assert data["stated_limit_cents"] > 0
    assert 0 <= data["recovered_cents"] <= data["stated_limit_cents"]


def assert_vendor_assignment(data: dict) -> None:
    _assert_versioned(data)
    assert data["vendor_type"] in ("ADJUSTER", "DEFENSE_COUNSEL")
    assert data["status"] in ("ASSIGNED", "SUPERSEDED", "CLOSED")
    assert data["hourly_rate_cents"] > 0
    assert data["settlement_authority_cents"] >= 0
    assert data["engagement_end"] >= data["engagement_start"]
    assert data["hours_logged"] >= 0
    assert data["fees_accrued_cents"] >= 0


def assert_unearned_premium_refund(data: dict) -> None:
    _assert_versioned(data)
    assert data["refund_method"] in ("PRO_RATA", "SHORT_RATE")
    assert data["status"] in ("PENDING", "PARTIALLY_PAID", "PAID")
    assert data["computed_refund_cents"] >= 0
    assert data["alt_refund_cents"] >= 0
    assert data["priority_class"] in (1, 2, 3)
    assert 0 <= data["paid_amount_cents"] <= data["computed_refund_cents"]
    assert isinstance(data["capped"], bool)


def assert_referral(data: dict) -> None:
    _assert_versioned(data)
    assert data["status"] in ("OPEN", "ACCEPTED", "DECLINED")
    assert data["basis"] in (
        "POLICYHOLDER_RESIDENCE",
        "CLAIMANT_RESIDENCE",
        "PROPERTY_LOCATION",
    )
    assert len(data["target_state_code"]) == 2 and data["target_state_code"].isupper()


def assert_settlement_worksheet(data: dict) -> None:
    for field in (
        "claim_id",
        "cap_order_mode",
        "covered_basis_cents",
        "attachment_point_cents",
        "covered_layer_cents",
        "other_insurance_recoverable_cents",
        "statutory_deductible_cents",
        "per_claim_cap_cents",
        "remaining_aggregate_cents",
        "net_payable_cents",
        "alt_net_payable_cents",
        "variant_delta_cents",
        "cap_binding",
    ):
        assert field in data, f"settlement worksheet must expose {field}"
    # The PRD defines the delta as the difference between the two payable
    # variants without fixing a sign convention, so only the magnitude is pinned.
    assert abs(data["variant_delta_cents"]) == abs(
        data["net_payable_cents"] - data["alt_net_payable_cents"]
    ), "variant_delta_cents must be the difference between the two payable variants"
