"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import DISCLOSURE_SCORE_MAX, DISCLOSURE_SCORE_MIN


def assert_identity_quartet(data: dict, entity_label: str = "entity") -> None:
    """Every entity but the two append-only ones carries the full quartet."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be ISO-8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_label}.updated_at must be ISO-8601"
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be an int"
    assert data["version"] >= 1, f"{entity_label}.version starts at 1"


def assert_append_only_identity(data: dict, entity_label: str = "entity") -> None:
    """Append-only rows carry id and created_at and nothing else from the quartet."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be ISO-8601"
    assert "updated_at" not in data, f"{entity_label} must not expose updated_at"
    assert "version" not in data, f"{entity_label} must not expose version"


def assert_millisecond_timestamp(value: str, label: str = "timestamp") -> None:
    """created_at renders with exactly three fractional-second digits."""
    assert is_iso8601_timestamp(value), f"{label} must be ISO-8601: {value!r}"
    assert "." in value, f"{label} must carry fractional seconds: {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, f"{label} must carry three fractional digits: {value!r}"


def assert_jurisdiction(data: dict) -> None:
    assert_identity_quartet(data, "Jurisdiction")
    assert isinstance(data["code"], str) and 3 <= len(data["code"]) <= 32
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert 0 <= data["occupancy_tax_rate_bps"] <= 5000
    for flag in (
        "first_quote_total_required",
        "itemization_required_on_folio",
        "mandatory_fee_ban",
        "opt_out_mandate",
    ):
        assert isinstance(data[flag], bool), f"Jurisdiction.{flag} must be a boolean"


def assert_taxability_rule(data: dict) -> None:
    assert_identity_quartet(data, "TaxabilityRule")
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["fee_code"], str) and len(data["fee_code"]) > 0
    assert data["taxability"] in ("TAXABLE", "EXEMPT", "TAXABLE_IF_MANDATORY")
    if data["tax_rate_bps"] is not None:
        assert 0 <= data["tax_rate_bps"] <= 5000


def assert_property(data: dict) -> None:
    assert_identity_quartet(data, "Property")
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["brand_code"], str) and 1 <= len(data["brand_code"]) <= 16
    assert data["base_room_rate_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["disclosure_posture"] in ("COMPLIANT", "AT_RISK", "NON_COMPLIANT")
    if data["min_channel_disclosure_score"] is not None:
        assert (
            DISCLOSURE_SCORE_MIN
            <= data["min_channel_disclosure_score"]
            <= DISCLOSURE_SCORE_MAX
        )
    assert data["open_disclosure_obligation_count"] >= 0
    assert data["published_fee_program_count"] >= 0
    assert data["aggregate_disclosure_gap_cents"] >= 0


def assert_channel(data: dict) -> None:
    assert_identity_quartet(data, "Channel")
    assert data["channel_type"] in (
        "OWNED_WEB",
        "OWNED_APP",
        "OTA",
        "GDS",
        "METASEARCH",
        "VOICE",
    )
    assert isinstance(data["supports_total_price_display"], bool)
    assert isinstance(data["supports_itemization"], bool)


def assert_fee_program(data: dict) -> None:
    assert_identity_quartet(data, "FeeProgram")
    assert is_valid_uuid(data["property_id"])
    assert data["status"] in ("DRAFT", "UNDER_REVIEW", "PUBLISHED", "SUPERSEDED")
    assert isinstance(data["version_label"], str) and len(data["version_label"]) > 0
    assert data["effective_to"] > data["effective_from"]
    assert data["fee_count"] >= 0
    assert data["mandatory_fee_count"] >= 0
    assert data["total_mandatory_fee_cents_per_night"] >= 0
    assert float(data["inclusion_coverage_ratio"]) >= 0.0


def assert_fee(data: dict) -> None:
    assert_identity_quartet(data, "Fee")
    assert is_valid_uuid(data["fee_program_id"])
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["classification"] in ("MANDATORY", "OPTIONAL", "CONDITIONAL")
    assert data["basis"] in (
        "PER_NIGHT",
        "PER_STAY",
        "PER_PERSON_PER_NIGHT",
        "PERCENT_OF_ROOM",
    )
    assert 8 <= len(data["disclosure_text"]) <= 500
    assert isinstance(data["avoidable"], bool)
    if data["basis"] == "PERCENT_OF_ROOM":
        assert data["amount_cents"] is None, "a percent-of-room fee carries no amount"
        assert 1 <= data["percent_bps"] <= 10000
    else:
        assert data["amount_cents"] is not None and data["amount_cents"] >= 0
        assert data["percent_bps"] is None
    if data["avoidable"]:
        assert 0 <= data["opt_out_window_hours"] <= 720
    else:
        assert data["opt_out_window_hours"] is None
    assert data["inclusion_count"] >= 0
    assert data["inclusion_value_cents"] >= 0


def assert_fee_inclusion(data: dict) -> None:
    assert_identity_quartet(data, "FeeInclusion")
    assert is_valid_uuid(data["fee_id"])
    assert data["retail_value_cents"] >= 0
    assert 1 <= data["units"] <= 100
    assert data["included_value_cents"] == data["retail_value_cents"] * data["units"]


def assert_channel_disclosure_profile(data: dict) -> None:
    assert_identity_quartet(data, "ChannelDisclosureProfile")
    assert is_valid_uuid(data["property_id"])
    assert is_valid_uuid(data["channel_id"])
    assert is_valid_uuid(data["fee_program_id"])
    assert isinstance(data["first_quote_shows_total"], bool)
    assert isinstance(data["itemized_at_first_quote"], bool)
    assert data["disclosure_placement"] in (
        "FIRST_QUOTE",
        "RATE_DETAILS",
        "CHECKOUT",
        "CONFIRMATION_ONLY",
        "ABSENT",
    )
    assert data["status"] in ("DRAFT", "DEPLOYED", "FLAGGED", "REMEDIATED", "RETIRED")
    assert DISCLOSURE_SCORE_MIN <= data["disclosure_score"] <= DISCLOSURE_SCORE_MAX
    assert data["confirmed_undisclosed_count"] >= 0
    assert data["remediation_round"] >= 0
    assert data["deployed_to"] > data["deployed_from"]


def assert_booking(data: dict) -> None:
    assert_identity_quartet(data, "Booking")
    assert is_valid_uuid(data["property_id"])
    assert is_valid_uuid(data["channel_id"])
    assert is_valid_uuid(data["channel_disclosure_profile_id"])
    assert is_valid_uuid(data["fee_program_id"])
    assert 1 <= data["nights"] <= 30
    assert 1 <= data["guests"] <= 8
    assert data["room_rate_cents"] >= 0
    assert isinstance(data["disclosed_fee_amounts"], dict)
    assert data["stay_status"] in ("QUOTED", "CONFIRMED", "IN_HOUSE", "CHECKED_OUT")
    assert data["disclosure_status"] in (
        "PENDING_AUDIT",
        "DISCLOSED",
        "DISPUTED",
        "UNDISCLOSED_CONFIRMED",
        "CURED",
    )
    assert data["quote_disclosure_gap_cents"] >= 0


def assert_folio(data: dict) -> None:
    assert_identity_quartet(data, "Folio")
    assert is_valid_uuid(data["booking_id"])
    assert data["status"] in ("OPEN", "ITEMIZED", "POSTED", "ADJUSTED", "CLOSED")
    assert data["line_count"] >= 0
    assert data["charges_subtotal_cents"] >= 0
    assert data["credits_total_cents"] >= 0
    assert data["tax_total_cents"] >= 0
    assert isinstance(data["itemization_complete"], bool)


def assert_folio_line(data: dict) -> None:
    assert_append_only_identity(data, "FolioLine")
    assert is_valid_uuid(data["folio_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert data["line_type"] in (
        "ROOM",
        "MANDATORY_FEE",
        "OPTIONAL_FEE",
        "FEE_CREDIT",
        "FEE_REBILL",
        "COMPLAINT_REFUND",
    )
    assert data["taxability_determination"] in (
        "TAXABLE",
        "EXEMPT",
        "TAXABLE_IF_MANDATORY_APPLIED",
        "TAXABLE_IF_MANDATORY_WAIVED",
    )
    assert data["amount_cents"] > 0, "every folio line carries a positive amount"
    assert data["tax_rate_bps"] >= 0
    assert data["sequence_no"] >= 1


def assert_opt_out_request(data: dict) -> None:
    assert_identity_quartet(data, "OptOutRequest")
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["fee_id"])
    assert data["status"] in ("REQUESTED", "GRANTED", "DENIED", "EXPIRED", "REVOKED")
    assert data["requested_hours_before_arrival"] >= 0
    assert data["credit_cents"] >= 0
    assert data["tax_credit_cents"] >= 0
    if data["denial_reason_code"] is not None:
        assert data["denial_reason_code"] in (
            "NOT_AVOIDABLE",
            "SERVICE_ALREADY_CONSUMED",
            "POLICY_EXCEPTION_DENIED",
        )


def assert_guest_complaint(data: dict) -> None:
    assert_identity_quartet(data, "GuestComplaint")
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["folio_line_id"])
    assert data["complaint_reason"] in (
        "NOT_DISCLOSED",
        "MISSTATED_AMOUNT",
        "MANDATORY_NOT_AVOIDABLE",
        "TOTAL_NOT_SHOWN",
    )
    assert 8 <= len(data["narrative"]) <= 1000
    assert data["status"] in (
        "SUBMITTED",
        "UNDER_INVESTIGATION",
        "SUBSTANTIATED",
        "UNSUBSTANTIATED",
        "REFUNDED",
    )
    if data["refund_variant"] is not None:
        assert data["refund_variant"] in (
            "FULL_FEE_REFUND",
            "DISCLOSURE_GAP_DIFFERENTIAL",
        )
    if data["dismissal_reason_code"] is not None:
        assert data["dismissal_reason_code"] in (
            "DISCLOSURE_EVIDENCED",
            "GUEST_ACKNOWLEDGED_AT_CHECK_IN",
            "DUPLICATE_COMPLAINT",
        )
    assert data["refund_entitlement_cents"] >= 0
    assert data["refunded_amount_cents"] >= 0


def assert_regulator_inquiry(data: dict) -> None:
    assert_identity_quartet(data, "RegulatorInquiry")
    assert is_valid_uuid(data["jurisdiction_id"])
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["docket_number"], str) and len(data["docket_number"]) > 0
    assert isinstance(data["channel_scope"], list) and len(data["channel_scope"]) > 0
    assert len(set(data["channel_scope"])) == len(data["channel_scope"])
    assert data["status"] in (
        "RECEIVED",
        "RESPONSE_DRAFTED",
        "RESPONSE_SUBMITTED",
        "REMEDIATION_REQUIRED",
        "REMEDIATION_SUBMITTED",
        "ACCEPTED",
        "WITHDRAWN",
    )
    assert isinstance(data["flagged_profile_ids"], list)
    assert data["remediation_round"] >= 0
    assert data["exposure_cents"] >= 0


def assert_revenue_impact_model(data: dict) -> None:
    assert_append_only_identity(data, "RevenueImpactModel")
    assert is_valid_uuid(data["property_id"])
    assert is_valid_uuid(data["fee_program_id"])
    assert data["scenario"] in ("STATUS_QUO", "PARTIAL_ROLL_IN", "FULL_ROLL_IN")
    assert data["variant"] in ("RATE_PARITY", "TAX_ABSORBED")
    assert isinstance(data["roll_in_fee_codes"], list)
    assert data["applied_commission_bps"] in (1500, 1800, 2100)


CHARGE_LINE_TYPES = ("ROOM", "MANDATORY_FEE", "OPTIONAL_FEE", "FEE_REBILL")
CREDIT_LINE_TYPES = ("FEE_CREDIT", "COMPLAINT_REFUND")


def assert_folio_ledger_conservation(folio: dict, lines: list) -> None:
    """The folio subtotals must reconcile against its own line ledger."""
    charge_side = sum(
        line["amount_cents"] + line["tax_cents"]
        for line in lines
        if line["line_type"] in CHARGE_LINE_TYPES
    )
    credit_side = sum(
        line["amount_cents"] - line["tax_cents"]
        for line in lines
        if line["line_type"] in CREDIT_LINE_TYPES
    )
    charges = sum(
        line["amount_cents"] for line in lines if line["line_type"] in CHARGE_LINE_TYPES
    )
    credits = sum(
        line["amount_cents"] for line in lines if line["line_type"] in CREDIT_LINE_TYPES
    )
    # PRD 3.5: "tax_total_cents is the sum of tax_cents over **every** line,
    # credits contributing their negative values."  A credit line already stores
    # a negative tax, so the sum is plain and nothing is re-signed here.
    taxes = sum(line["tax_cents"] for line in lines)
    assert folio["charges_subtotal_cents"] == charges, (
        f"charges_subtotal_cents {folio['charges_subtotal_cents']} != "
        f"sum of charge lines {charges}"
    )
    assert folio["credits_total_cents"] == credits, (
        f"credits_total_cents {folio['credits_total_cents']} != "
        f"sum of credit lines {credits}"
    )
    assert folio["tax_total_cents"] == taxes, (
        f"tax_total_cents {folio['tax_total_cents']} != net line tax {taxes}"
    )
    assert folio["folio_total_cents"] == charges - credits + taxes, (
        f"folio_total_cents {folio['folio_total_cents']} != "
        f"{charges} - {credits} + {taxes}"
    )
    assert charge_side - credit_side == folio["folio_total_cents"], (
        "the guest's out-of-pocket sum must equal the folio total"
    )


def assert_folio_sequence_integrity(folio: dict, lines: list) -> None:
    """line_count lines numbered 1..line_count, each sequence number once."""
    sequences = sorted(line["sequence_no"] for line in lines)
    assert folio["line_count"] == len(lines), (
        f"line_count {folio['line_count']} != {len(lines)} lines returned"
    )
    assert sequences == list(range(1, folio["line_count"] + 1)), (
        f"sequence numbers must be 1..{folio['line_count']} exactly once, got {sequences}"
    )


def assert_booking_mirrors_folio(booking: dict, folio: dict) -> None:
    """The booking's folio-side figures mirror the folio ledger."""
    assert booking["folio_total_cents"] == folio["folio_total_cents"], (
        f"booking.folio_total_cents {booking['folio_total_cents']} != "
        f"folio.folio_total_cents {folio['folio_total_cents']}"
    )
    assert booking["guest_out_of_pocket_cents"] == folio["folio_total_cents"], (
        f"guest_out_of_pocket_cents {booking['guest_out_of_pocket_cents']} != "
        f"folio total {folio['folio_total_cents']}"
    )


def assert_quote_folio_variance(booking: dict) -> None:
    """quote_folio_variance_cents is the folio total minus the quoted total."""
    expected = booking["folio_total_cents"] - booking["quoted_total_cents"]
    assert booking["quote_folio_variance_cents"] == expected, (
        f"quote_folio_variance_cents {booking['quote_folio_variance_cents']} != "
        f"{booking['folio_total_cents']} - {booking['quoted_total_cents']}"
    )


def assert_disclosure_summary_matches_property(summary: dict, prop: dict) -> None:
    """Every summary field the Property also carries must agree with it."""
    assert summary["property_id"] == prop["id"]
    for field in (
        "disclosure_posture",
        "min_channel_disclosure_score",
        "open_disclosure_obligation_count",
        "published_fee_program_count",
        "aggregate_disclosure_gap_cents",
    ):
        assert summary[field] == prop[field], (
            f"disclosure-summary {field} {summary[field]!r} != property {prop[field]!r}"
        )


def find_line_by_sequence(lines: list, sequence_no: int) -> dict:
    matches = [line for line in lines if line["sequence_no"] == sequence_no]
    assert len(matches) == 1, f"expected exactly one line at sequence {sequence_no}"
    return matches[0]


def find_line_by_fee_code(lines: list, fee_code: str) -> dict:
    matches = [line for line in lines if line.get("fee_code") == fee_code]
    assert len(matches) == 1, (
        f"expected exactly one line for fee code {fee_code}, got {len(matches)}"
    )
    return matches[0]


def assert_stamped_at_clock(value, instant: str, label: str = "timestamp") -> None:
    """A system stamp must record the given logical-clock instant.

    The clock reports its reading without fractional seconds while stored
    stamps render three fractional digits, so both spellings of the same
    instant are accepted and any other instant fails.
    """
    assert isinstance(value, str) and value, f"{label} must be a stamped instant"
    normalised = value.replace("Z", "").replace("+00:00", "")
    expected = instant.replace("Z", "").replace("+00:00", "")
    if "." in normalised:
        seconds, fraction = normalised.split(".", 1)
        assert int(fraction.rstrip("0") or "0") == 0, (
            f"{label} {value!r} is not the instant {instant!r}"
        )
        normalised = seconds
    if "." in expected:
        expected = expected.split(".", 1)[0]
    assert normalised == expected, f"{label} {value!r} is not the instant {instant!r}"
