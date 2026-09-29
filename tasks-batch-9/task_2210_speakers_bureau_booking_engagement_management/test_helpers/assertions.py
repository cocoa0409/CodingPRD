"""Shape and invariant assertions for the Speakers Bureau Engagements API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    COMMISSION_PCT_MAX,
    COMMISSION_PCT_MIN,
    SURCHARGE_PCT,
    TIER_COMMISSION_PCT,
)

# ---------------------------------------------------------------------------
# Generic building blocks
# ---------------------------------------------------------------------------


def assert_identity_and_audit_fields(record: dict, label: str = "record") -> None:
    """Every resource except Feedback carries id, created_at, updated_at, version."""
    assert is_valid_uuid(record["id"]), f"{label}.id is not a UUID: {record['id']}"
    assert is_iso8601_timestamp(
        record["created_at"]
    ), f"{label}.created_at is not ISO 8601: {record['created_at']}"
    assert is_iso8601_timestamp(
        record["updated_at"]
    ), f"{label}.updated_at is not ISO 8601: {record['updated_at']}"
    assert isinstance(record["version"], int), f"{label}.version must be an integer"
    assert record["version"] >= 1, f"{label}.version must start at 1"


def assert_append_only_fields(record: dict, label: str = "record") -> None:
    """Feedback carries id and created_at but neither updated_at nor version."""
    assert is_valid_uuid(record["id"]), f"{label}.id is not a UUID: {record['id']}"
    assert is_iso8601_timestamp(
        record["created_at"]
    ), f"{label}.created_at is not ISO 8601: {record['created_at']}"
    assert "updated_at" not in record, f"{label} must not expose updated_at"
    assert "version" not in record, f"{label} must not expose version"


def assert_money_cents(value, label: str) -> None:
    assert isinstance(value, int) and not isinstance(
        value, bool
    ), f"{label} must be an integer number of cents, got {value!r}"
    assert value >= 0, f"{label} must not be negative, got {value}"


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------


def assert_speaker(speaker: dict) -> None:
    assert_identity_and_audit_fields(speaker, "speaker")
    assert isinstance(speaker["full_name"], str) and speaker["full_name"]
    assert isinstance(speaker["topics"], list) and speaker["topics"]
    assert_money_cents(speaker["fee_floor_cents"], "speaker.fee_floor_cents")
    assert_money_cents(speaker["fee_ceiling_cents"], "speaker.fee_ceiling_cents")
    assert speaker["fee_floor_cents"] <= speaker["fee_ceiling_cents"]
    assert speaker["travel_class"] in ("ECONOMY", "PREMIUM", "BUSINESS")
    assert 0 <= speaker["travel_buffer_days"] <= 3
    assert speaker["tax_form_status"] in ("MISSING", "ON_FILE")
    assert speaker["roster_status"] in ("ACTIVE", "PROBATION", "PAUSED", "RETIRED")
    assert speaker["roster_tier"] in ("BRONZE", "SILVER", "GOLD")
    assert speaker["engagements_delivered_count"] >= 0
    assert_money_cents(
        speaker["lifetime_gross_fees_cents"], "speaker.lifetime_gross_fees_cents"
    )
    assert speaker["held_days_count"] >= 0
    assert_money_cents(
        speaker["pending_remittance_cents"], "speaker.pending_remittance_cents"
    )
    assert speaker["feedback_count"] >= 0


def assert_client(client: dict) -> None:
    assert_identity_and_audit_fields(client, "client")
    assert isinstance(client["org_name"], str) and client["org_name"]
    assert isinstance(client["industry_code"], str) and client["industry_code"]
    assert "@" in client["primary_contact_email"]
    assert client["credit_status"] in ("GOOD", "WATCH", "HOLD")
    assert_money_cents(
        client["outstanding_balance_cents"], "client.outstanding_balance_cents"
    )
    assert client["circumvention_strikes"] >= 0


def assert_inquiry(inquiry: dict) -> None:
    assert_identity_and_audit_fields(inquiry, "inquiry")
    assert is_valid_uuid(inquiry["client_id"])
    assert isinstance(inquiry["required_topic"], str)
    assert is_iso8601_timestamp(inquiry["event_start_utc"])
    assert is_iso8601_timestamp(inquiry["event_end_utc"])
    assert inquiry["event_start_utc"] < inquiry["event_end_utc"]
    assert isinstance(inquiry["is_virtual"], bool)
    assert inquiry["audience_size"] >= 1
    assert_money_cents(inquiry["budget_cents"], "inquiry.budget_cents")
    assert inquiry["status"] in (
        "RECEIVED",
        "QUALIFIED",
        "BLOCKED",
        "PROPOSED",
        "WON",
        "LOST",
        "DISQUALIFIED",
    )


def assert_proposal(proposal: dict) -> None:
    assert_identity_and_audit_fields(proposal, "proposal")
    assert is_valid_uuid(proposal["inquiry_id"])
    assert proposal["round_no"] >= 1
    assert proposal["revision_count"] >= 0
    assert proposal["options_count"] >= 0
    assert is_iso8601_timestamp(proposal["valid_until_utc"])
    assert proposal["status"] in (
        "DRAFT",
        "PRESENTED",
        "REVISION_REQUESTED",
        "ACCEPTED",
        "DECLINED",
        "SUPERSEDED",
        "CLOSED",
    )


def assert_proposal_option(option: dict) -> None:
    assert_identity_and_audit_fields(option, "proposal_option")
    assert is_valid_uuid(option["proposal_id"])
    assert is_valid_uuid(option["speaker_id"])
    assert_money_cents(option["quoted_fee_cents"], "option.quoted_fee_cents")
    assert_money_cents(
        option["travel_allowance_cents"], "option.travel_allowance_cents"
    )
    assert 1 <= option["rank_no"] <= 4
    assert option["status"] in ("OFFERED", "SELECTED", "REJECTED", "WITHDRAWN")


def assert_engagement(engagement: dict) -> None:
    assert_identity_and_audit_fields(engagement, "engagement")
    assert is_valid_uuid(engagement["inquiry_id"])
    assert is_valid_uuid(engagement["speaker_id"])
    assert is_valid_uuid(engagement["selected_option_id"])
    assert is_iso8601_timestamp(engagement["event_start_utc"])
    assert is_iso8601_timestamp(engagement["event_end_utc"])
    assert_money_cents(engagement["quoted_fee_cents"], "engagement.quoted_fee_cents")
    assert engagement["booking_status"] in (
        "OFFERED",
        "CONFIRMED",
        "CONTRACTED",
        "DELIVERED",
        "DECLINED_BY_SPEAKER",
        "CANCELLED_BY_CLIENT",
        "CANCELLED_BY_SPEAKER",
    )
    assert engagement["settlement_status"] in (
        "UNBILLED",
        "INVOICED",
        "PARTIALLY_COLLECTED",
        "COLLECTED",
        "REMITTED",
        "WAIVED",
        "WRITTEN_OFF",
    )
    assert engagement["commission_adjustment_count"] >= 0
    if engagement["commission_pct_snapshot"] is not None:
        assert_commission_pct_in_band(engagement["commission_pct_snapshot"])


def assert_contract(contract: dict) -> None:
    assert_identity_and_audit_fields(contract, "contract")
    assert is_valid_uuid(contract["engagement_id"])
    assert contract["cancellation_schedule_code"] in ("STANDARD", "STRICT")
    assert contract["travel_policy_code"] in ("POLICY_A", "POLICY_B")
    assert contract["recording_rights"] in ("NONE", "AUDIO_ONLY", "FULL_BUY_OUT")
    assert contract["technical_rider_code"] in (
        "STANDARD_AV",
        "STAGE_PLUS",
        "BROADCAST",
    )
    assert contract["exclusivity_days"] in (0, 30, 90, 180)
    assert contract["status"] in (
        "DRAFT",
        "SENT",
        "PARTIALLY_SIGNED",
        "EXECUTED",
        "VOID",
    )


def assert_speaker_hold(hold: dict) -> None:
    assert_identity_and_audit_fields(hold, "speaker_hold")
    assert is_valid_uuid(hold["speaker_id"])
    assert hold["kind"] in ("ENGAGEMENT", "BLACKOUT")
    assert is_iso8601_timestamp(hold["hold_start_utc"])
    assert is_iso8601_timestamp(hold["hold_end_utc"])
    assert hold["hold_start_utc"] < hold["hold_end_utc"]
    assert hold["day_span"] >= 1
    assert hold["status"] in ("ACTIVE", "RELEASED", "CONSUMED")


def assert_exclusivity_grant(grant: dict) -> None:
    assert_identity_and_audit_fields(grant, "exclusivity_grant")
    assert is_valid_uuid(grant["source_engagement_id"])
    assert is_valid_uuid(grant["speaker_id"])
    assert is_valid_uuid(grant["beneficiary_client_id"])
    assert is_iso8601_timestamp(grant["effective_from_utc"])
    assert is_iso8601_timestamp(grant["effective_to_utc"])
    assert grant["effective_from_utc"] < grant["effective_to_utc"]
    assert grant["status"] in ("ACTIVE", "EXPIRED", "WAIVED")


def assert_travel_expense(expense: dict) -> None:
    assert_identity_and_audit_fields(expense, "travel_expense")
    assert is_valid_uuid(expense["engagement_id"])
    assert_money_cents(expense["receipts_cents"], "travel_expense.receipts_cents")
    assert expense["travel_days"] >= 1
    assert expense["distance_band"] in (
        "LOCAL",
        "REGIONAL",
        "NATIONAL",
        "INTERNATIONAL",
    )
    assert expense["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "REIMBURSED")


def assert_invoice(invoice: dict) -> None:
    assert_identity_and_audit_fields(invoice, "invoice")
    assert is_valid_uuid(invoice["engagement_id"])
    assert is_valid_uuid(invoice["client_id"])
    assert invoice["kind"] in ("ENGAGEMENT_FEE", "CANCELLATION_RETENTION")
    for field in (
        "fee_line_cents",
        "recording_line_cents",
        "travel_line_cents",
        "surcharge_cents",
        "amount_due_cents",
        "amount_paid_cents",
    ):
        assert_money_cents(invoice[field], f"invoice.{field}")
    assert invoice["status"] in ("ISSUED", "PARTIALLY_PAID", "PAID", "VOID")
    assert is_iso8601_timestamp(invoice["issued_at_utc"])


def assert_remittance(remittance: dict) -> None:
    assert_identity_and_audit_fields(remittance, "remittance")
    assert is_valid_uuid(remittance["engagement_id"])
    assert is_valid_uuid(remittance["speaker_id"])
    for field in (
        "gross_fee_cents",
        "commission_cents",
        "travel_passthrough_cents",
        "net_payable_cents",
    ):
        assert_money_cents(remittance[field], f"remittance.{field}")
    assert remittance["status"] in ("PENDING", "APPROVED", "PAID", "VOIDED")


def assert_feedback(feedback: dict) -> None:
    assert_append_only_fields(feedback, "feedback")
    assert is_valid_uuid(feedback["engagement_id"])
    assert 1 <= feedback["content_score"] <= 5
    assert 1 <= feedback["logistics_score"] <= 5
    assert isinstance(feedback["composite_score"], (int, float))


def assert_circumvention_claim(claim: dict) -> None:
    assert_identity_and_audit_fields(claim, "circumvention_claim")
    assert is_valid_uuid(claim["client_id"])
    assert is_valid_uuid(claim["speaker_id"])
    assert is_valid_uuid(claim["source_engagement_id"])
    assert is_iso8601_timestamp(claim["direct_event_date_utc"])
    assert_money_cents(claim["direct_fee_cents"], "claim.direct_fee_cents")
    assert claim["days_after_source"] >= 0
    assert claim["protection_factor"] in (1.00, 0.50, 1.0, 0.5)
    assert_money_cents(claim["commission_due_cents"], "claim.commission_due_cents")
    assert claim["status"] in ("OPEN", "UPHELD", "DISMISSED", "SETTLED")


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------


def assert_commission_pct_in_band(pct: float) -> None:
    """A commission rate never leaves the band the PRD allows."""
    assert (
        COMMISSION_PCT_MIN <= pct <= COMMISSION_PCT_MAX
    ), f"commission pct {pct} is outside [{COMMISSION_PCT_MIN}, {COMMISSION_PCT_MAX}]"


def assert_tier_default_rate(speaker: dict) -> None:
    """A speaker's default commission rate always matches its roster tier."""
    expected = TIER_COMMISSION_PCT[speaker["roster_tier"]]
    assert speaker["default_commission_pct"] == expected, (
        f"tier {speaker['roster_tier']} implies {expected} but the speaker "
        f"reports {speaker['default_commission_pct']}"
    )


def round_half_up(value: float) -> int:
    """Round to the nearest whole cent, ties away from zero."""
    from decimal import ROUND_HALF_UP, Decimal

    return int(
        Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def expected_surcharge_cents(*line_amounts_cents: int) -> int:
    """Surcharge is computed and rounded per line, then summed."""
    return sum(round_half_up(line * SURCHARGE_PCT) for line in line_amounts_cents)


def assert_invoice_totals_consistent(invoice: dict) -> None:
    """An invoice's amount due is its three lines plus the per-line surcharge."""
    lines = (
        invoice["fee_line_cents"],
        invoice["recording_line_cents"],
        invoice["travel_line_cents"],
    )
    expected_surcharge = expected_surcharge_cents(*lines)
    assert invoice["surcharge_cents"] == expected_surcharge, (
        f"surcharge should be {expected_surcharge} for lines {lines} but the "
        f"invoice reports {invoice['surcharge_cents']}"
    )
    assert invoice["amount_due_cents"] == sum(lines) + expected_surcharge


def assert_remittance_nets_out(remittance: dict) -> None:
    """Net payable is gross fee minus commission plus travel passthrough."""
    expected = (
        remittance["gross_fee_cents"]
        - remittance["commission_cents"]
        + remittance["travel_passthrough_cents"]
    )
    assert remittance["net_payable_cents"] == expected, (
        f"net payable should be {expected} but the remittance reports "
        f"{remittance['net_payable_cents']}"
    )


def assert_client_balance(client: dict, expected_cents: int) -> None:
    assert client["outstanding_balance_cents"] == expected_cents, (
        f"client outstanding balance should be {expected_cents} but is "
        f"{client['outstanding_balance_cents']}"
    )


def assert_speaker_payable(speaker: dict, expected_cents: int) -> None:
    assert speaker["pending_remittance_cents"] == expected_cents, (
        f"speaker pending remittance should be {expected_cents} but is "
        f"{speaker['pending_remittance_cents']}"
    )


def assert_held_days(speaker: dict, expected_days: int) -> None:
    assert speaker["held_days_count"] == expected_days, (
        f"speaker held days should be {expected_days} but is "
        f"{speaker['held_days_count']}"
    )


def assert_booking_and_settlement(
    engagement: dict, booking_status: str, settlement_status: str
) -> None:
    """The booking dimension and the settlement dimension are read separately."""
    assert engagement["booking_status"] == booking_status, (
        f"booking status should be {booking_status} but is "
        f"{engagement['booking_status']}"
    )
    assert engagement["settlement_status"] == settlement_status, (
        f"settlement status should be {settlement_status} but is "
        f"{engagement['settlement_status']}"
    )


def assert_composite_score(feedback: dict, expected: float) -> None:
    assert abs(feedback["composite_score"] - expected) < 0.005, (
        f"composite score should be {expected} but is {feedback['composite_score']}"
    )
