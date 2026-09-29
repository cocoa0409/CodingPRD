"""Reusable assertions: entity shapes, the mutation apparatus, and the two
conservation invariants the PRD states in prose.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# Resources that carry the full mutation apparatus.
VERSIONED_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")

# The two append-only record types carry only these.
APPEND_ONLY_COMMON_FIELDS = ("id", "created_at")


# --------------------------------------------------------------------------
# Common-field apparatus
# --------------------------------------------------------------------------

def assert_common_fields(entity: dict) -> None:
    """Every mutable resource exposes id, created_at, updated_at and version."""
    for field in VERSIONED_COMMON_FIELDS:
        assert field in entity, f"missing common field {field!r}: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int), entity["version"]
    assert entity["version"] >= 1, entity["version"]


def assert_append_only_common_fields(entity: dict) -> None:
    """Append-only records expose id and created_at, and neither updated_at nor
    version."""
    for field in APPEND_ONLY_COMMON_FIELDS:
        assert field in entity, f"missing common field {field!r}: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert "updated_at" not in entity, "append-only record must not carry updated_at"
    assert "version" not in entity, "append-only record must not carry version"


def assert_fields_present(entity: dict, *fields: str) -> None:
    for field in fields:
        assert field in entity, f"missing field {field!r}: {sorted(entity)}"


def assert_field_values(entity: dict, **expected) -> None:
    for field, value in expected.items():
        assert field in entity, f"missing field {field!r}: {sorted(entity)}"
        assert entity[field] == value, (
            f"{field}: expected {value!r}, got {entity[field]!r}"
        )


def assert_created_version_is_one(entity: dict) -> None:
    """A newly created resource starts at version 1."""
    assert entity["version"] == 1, f"expected version 1, got {entity['version']}"


# --------------------------------------------------------------------------
# Per-resource shape assertions
# --------------------------------------------------------------------------

def assert_port(port: dict) -> None:
    assert_common_fields(port)
    assert_fields_present(
        port, "port_code", "name", "country_code", "docking_mode",
        "risk_buffer_minutes", "tender_egress_minutes",
    )


def assert_meeting_point(meeting_point: dict) -> None:
    assert_common_fields(meeting_point)
    assert_fields_present(
        meeting_point, "port_id", "name", "zone", "max_concurrent_groups",
        "slot_buffer_minutes",
    )


def assert_port_call(port_call: dict) -> None:
    assert_common_fields(port_call)
    assert_fields_present(
        port_call, "port_id", "voyage_code", "ship_code", "arrival_utc",
        "all_aboard_utc", "departure_utc", "delay_minutes",
        "effective_arrival_utc", "status",
    )


def assert_tender_wave(wave: dict) -> None:
    assert_common_fields(wave)
    assert_fields_present(
        wave, "port_call_id", "wave_index", "window_start_utc", "window_end_utc",
        "guest_capacity", "priority_class", "assigned_guest_count",
        "assigned_departure_count",
    )


def assert_operator(operator: dict) -> None:
    assert_common_fields(operator)
    assert_fields_present(
        operator, "port_id", "legal_name", "contact_email", "insurance_expiry_date",
        "insurance_liability_limit_cents", "commission_rate_bps", "vetting_status",
        "vetting_cycle_count", "safety_score", "reliability_strikes",
        "liability_reserve_cents",
    )


def assert_safety_audit(audit: dict) -> None:
    assert_append_only_common_fields(audit)
    assert_fields_present(
        audit, "operator_id", "audit_type", "conducted_on", "raw_score",
        "critical_finding_count", "auditor_user_id",
    )


def assert_excursion(excursion: dict) -> None:
    assert_common_fields(excursion)
    assert_fields_present(
        excursion, "port_id", "operator_id", "title", "duration_minutes", "min_age",
        "mobility_level", "medical_warning_codes", "languages", "base_price_cents",
        "price_tier", "is_line_operated", "return_guarantee", "catalog_status",
    )


def assert_departure(departure: dict) -> None:
    assert_common_fields(departure)
    assert_fields_present(
        departure, "excursion_id", "port_call_id", "meeting_point_id",
        "meeting_time_utc", "dispatch_dwell_minutes", "total_capacity",
        "precruise_allocation", "onboard_allocation", "precruise_sold_seats",
        "onboard_sold_seats", "seats_available_total",
        "effective_precruise_available", "effective_onboard_available", "status",
        "projected_return_scheduled_utc", "projected_return_actual_utc",
        "slack_minutes_scheduled", "slack_minutes_actual",
        "timing_risk_band_scheduled", "timing_risk_band_actual",
        "return_guarantee_eligible",
    )


def assert_guest(guest: dict) -> None:
    assert_common_fields(guest)
    assert_fields_present(
        guest, "full_name", "birth_date", "voyage_code", "mobility_level",
        "language_pref", "medical_flags", "loyalty_tier",
    )


def assert_booking(booking: dict) -> None:
    assert_common_fields(booking)
    assert_fields_present(
        booking, "departure_id", "guest_id", "party_size", "channel",
        "language_choice", "medical_warning_acknowledged", "age_at_meeting",
        "per_guest_price_cents", "quoted_total_cents", "service_fee_cents",
        "charge_total_cents", "refunded_cents", "retained_cents",
        "goodwill_credit_cents", "commission_accrued_cents", "fulfillment_status",
        "financial_status", "alternative_offer_status", "return_guarantee_honored",
    )


def assert_ledger_entry(entry: dict) -> None:
    assert_append_only_common_fields(entry)
    assert_fields_present(
        entry, "booking_id", "entry_kind", "amount_cents", "refund_pct_bps",
        "basis", "reason_code",
    )


def assert_incident(incident: dict) -> None:
    assert_common_fields(incident)
    assert_fields_present(
        incident, "booking_id", "category", "severity", "occurred_utc", "narrative",
        "filed_by_user_id", "status",
    )


def assert_claim(claim: dict) -> None:
    assert_common_fields(claim)
    assert_fields_present(
        claim, "incident_id", "operator_id", "port_call_id", "claimed_amount_cents",
        "basis_code", "status", "dispute_round_count", "liability_share_bps",
        "settlement_amount_cents", "operator_charge_cents", "submitted_by_user_id",
    )


def assert_statement(statement: dict) -> None:
    assert_common_fields(statement)
    assert_fields_present(
        statement, "operator_id", "port_call_id", "basis", "status",
        "gross_ticket_cents", "refunds_cents", "port_fee_cents",
        "line_commission_cents", "claim_offset_cents", "operational_penalty_cents",
        "payable_pre_rebate_cents", "rebate_bps", "rebate_cents",
        "adjustment_cents", "operator_payable_cents", "booking_line_count",
    )


# --------------------------------------------------------------------------
# Domain invariants stated in the PRD
# --------------------------------------------------------------------------

def assert_seat_conservation(departure: dict, precruise_released: bool = False) -> None:
    """Sold seats never exceed their bucket allocation, the two allocations sum
    to total capacity, and seats_available_total is total capacity less both sold
    counts.

    The two effective-availability figures are checked against the effective
    allocations, which differ before and after the pre-cruise release: once the
    minutes to the meeting time have fallen to 2880 or below, the effective
    pre-cruise allocation collapses to precruise_sold_seats and the effective
    onboard allocation becomes total_capacity less precruise_sold_seats.  Pass
    ``precruise_released=True`` when the clock is at or past that point.  Both
    figures are floored at 0.
    """
    assert (
        departure["precruise_allocation"] + departure["onboard_allocation"]
        == departure["total_capacity"]
    ), (
        f"allocations {departure['precruise_allocation']}+"
        f"{departure['onboard_allocation']} != total "
        f"{departure['total_capacity']}"
    )
    assert departure["precruise_sold_seats"] <= departure["precruise_allocation"], (
        f"pre-cruise sold {departure['precruise_sold_seats']} exceeds allocation "
        f"{departure['precruise_allocation']}"
    )
    assert departure["onboard_sold_seats"] <= departure["onboard_allocation"], (
        f"onboard sold {departure['onboard_sold_seats']} exceeds allocation "
        f"{departure['onboard_allocation']}"
    )
    if precruise_released:
        effective_precruise_allocation = departure["precruise_sold_seats"]
        effective_onboard_allocation = (
            departure["total_capacity"] - departure["precruise_sold_seats"]
        )
    else:
        effective_precruise_allocation = departure["precruise_allocation"]
        effective_onboard_allocation = departure["onboard_allocation"]
    assert departure["effective_precruise_available"] == max(
        0, effective_precruise_allocation - departure["precruise_sold_seats"]
    ), departure
    assert departure["effective_onboard_available"] == max(
        0, effective_onboard_allocation - departure["onboard_sold_seats"]
    ), departure
    assert (
        departure["seats_available_total"]
        == departure["total_capacity"]
        - departure["precruise_sold_seats"]
        - departure["onboard_sold_seats"]
    ), departure


def assert_money_conservation(booking: dict) -> None:
    """Every charged cent that has actually been settled is either refunded or
    retained.

    The PRD pins ``retained_cents`` at two points only: it is 0 while
    ``financial_status`` is ``AUTHORIZED``, and it is ``charge_total_cents`` less
    ``refunded_cents`` once ``financial_status`` is terminal.  While the money is
    merely captured (``CHARGED``) nothing has yet been retained or refunded, and
    a voided authorisation captured nothing at all — so in those two states only
    the refunded side is checked and the conservation identity is not asserted.
    """
    status = booking["financial_status"]
    if status == "AUTHORIZED":
        assert booking["retained_cents"] == 0, booking
        assert booking["refunded_cents"] == 0, booking
        return
    if status in ("CHARGED", "VOIDED"):
        assert booking["refunded_cents"] == 0, booking
        return
    assert booking["refunded_cents"] + booking["retained_cents"] == booking[
        "charge_total_cents"
    ], (
        f"refunded {booking['refunded_cents']} + retained "
        f"{booking['retained_cents']} != charged "
        f"{booking['charge_total_cents']}"
    )


def assert_charge_total_is_quote_plus_fee(booking: dict) -> None:
    """The amount charged is the quoted ticket total plus the service fee."""
    assert (
        booking["charge_total_cents"]
        == booking["quoted_total_cents"] + booking["service_fee_cents"]
    ), booking


def assert_quote_is_per_guest_times_party(booking: dict) -> None:
    """The ticket total is the rounded per-guest price multiplied by party size."""
    assert (
        booking["quoted_total_cents"]
        == booking["per_guest_price_cents"] * booking["party_size"]
    ), booking


def assert_statement_waterfall(statement: dict) -> None:
    """The payable figures follow the stated waterfall.

    Payable before rebate is gross less the port fee, less the line commission,
    less the claim offset, less the operational penalty, floored at zero — there
    is no refunds term at this step, because refunds are already netted out of
    the gross on a FINAL statement.  The final payable then *adds* the rebate,
    which is stored as a negative amount, and adds any adjustment.
    """
    assert statement["payable_pre_rebate_cents"] == max(
        0,
        statement["gross_ticket_cents"]
        - statement["port_fee_cents"]
        - statement["line_commission_cents"]
        - statement["claim_offset_cents"]
        - statement["operational_penalty_cents"],
    ), statement
    assert statement["operator_payable_cents"] == (
        statement["payable_pre_rebate_cents"]
        + statement["rebate_cents"]
        + statement["adjustment_cents"]
    ), statement


def assert_no_version_drift(before: dict, after: dict) -> None:
    """A rejected write leaves the resource's version untouched."""
    assert before["version"] == after["version"], (
        f"version moved from {before['version']} to {after['version']} on a "
        f"rejected write"
    )
