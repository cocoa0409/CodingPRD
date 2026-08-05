"""Entity assertions, instant comparison helpers and conservation checkers.

Timestamps are ALWAYS compared semantically. PRD 2.4 renders stored instants with
exactly three fractional digits and a trailing Z, but callers supply plain
`...T08:00:00Z` values, so a raw string comparison would fail an otherwise correct
implementation. `parse_instant()` / `assert_same_instant()` exist so no test ever
compares two instants as strings.
"""

from datetime import date, datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# ------------------------------------------------------------ instants ----


def parse_instant(value):
    """Parse an ISO 8601 UTC instant into an aware datetime.

    Accepts a trailing 'Z' and any number of fractional-second digits.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected, message=""):
    """Compare two ISO 8601 instants by value, never by rendering."""
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, (
        f"{message} expected instant {expected} ({want.isoformat()}), "
        f"got {actual} ({got.isoformat()})"
    )


def parse_iso_date(value):
    assert isinstance(value, str) and value, f"expected an ISO date, got {value!r}"
    return date.fromisoformat(value[:10])


def assert_same_date(actual, expected, message=""):
    got = parse_iso_date(actual)
    want = parse_iso_date(expected)
    assert got == want, f"{message} expected date {expected}, got {actual}"


def assert_common_fields(data, expect_version=None):
    """Every persisted resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )
    if expect_version is not None:
        assert data["version"] == expect_version, (
            f"expected version {expect_version}, got {data['version']}"
        )


# ------------------------------------------------------ entity shapes ----


def assert_employer(data):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["employer_code"], str) and 2 <= len(data["employer_code"]) <= 16
    assert isinstance(data["annual_total_cost_of_coverage_cents"], int)
    assert isinstance(data["wellness_budget_cents"], int)
    assert isinstance(data["wellness_budget_committed_cents"], int)
    assert isinstance(data["wellness_budget_remaining_cents"], int)
    assert isinstance(data["program_cost_to_date_cents"], int)
    assert isinstance(data["tobacco_program_enabled"], bool)
    assert data["status"] == "ACTIVE"
    assert (
        data["wellness_budget_remaining_cents"]
        == data["wellness_budget_cents"] - data["wellness_budget_committed_cents"]
    ), "wellness_budget_remaining_cents must equal budget less committed"


def assert_site(data):
    assert_common_fields(data)
    assert data["site_type"] in ("ON_SITE", "NEAR_SITE")
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert isinstance(data["operating_weekdays"], list)
    assert isinstance(data["closure_dates"], list)
    assert isinstance(data["daily_slot_capacity"], int) and data["daily_slot_capacity"] >= 1
    for counter in (
        "slots_held_count",
        "slots_consumed_count",
        "slots_no_show_count",
        "slots_released_count",
        "slots_requested_total",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer"
        )
    assert_site_slot_conservation(data)


def assert_vendor_contract(data):
    assert_common_fields(data)
    assert data["fee_model"] in ("PER_VISIT", "FTE_HOUR")
    assert data["status"] in ("ACTIVE", "TRUED_UP")
    for field in (
        "per_visit_fee_cents",
        "fte_hourly_rate_cents",
        "minimum_guarantee_cents",
        "quota_visits_total",
        "quota_visits_consumed",
        "quota_visits_released",
        "quota_visits_requested_total",
        "quota_visits_remaining",
        "billable_visit_count",
        "gross_fee_cents",
        "true_up_amount_cents",
        "contract_cost_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer, got {data[field]!r}"
    assert isinstance(data["staffed_hours"], (int, float))
    assert_contract_quota_conservation(data)


def assert_provider(data):
    assert_common_fields(data)
    assert data["provider_function"] in ("CLINICIAN", "NAVIGATOR")
    assert data["credential_status"] in ("CREDENTIALED", "LAPSED", "DEACTIVATED")
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0
    parse_iso_date(data["license_expiry_date"])


def assert_staffing_shift(data):
    assert_common_fields(data)
    assert data["coverage_role"] in ("PRIMARY_CARE", "OCC_HEALTH", "WELLNESS", "NAVIGATION")
    assert parse_instant(data["shift_end"]) > parse_instant(data["shift_start"])
    assert isinstance(data["staffed_hours"], (int, float))


def assert_eligibility_record(data):
    assert_common_fields(data)
    assert data["tier"] in ("EMPLOYEE", "SPOUSE", "DEPENDENT", "RETIREE")
    assert data["coverage_status"] in ("FUTURE", "EFFECTIVE", "EXPIRED")
    assert isinstance(data["retro_terminated"], bool)
    parse_iso_date(data["effective_date"])


def assert_participant(data):
    assert_common_fields(data)
    assert data["enrollment_status"] in ("ACTIVE", "TERMINATED", "CLOSED")
    assert data["authorization_status"] in (
        "NOT_REQUESTED",
        "GRANTED",
        "REVOKED",
        "WITHDRAWN",
    )
    assert data["tier"] in ("EMPLOYEE", "SPOUSE", "DEPENDENT", "RETIREE")
    parse_iso_date(data["enrolled_on"])
    assert isinstance(data["completed_visit_count"], int)
    assert isinstance(data["incentive_awarded_cents"], int)


def assert_appointment(data):
    assert_common_fields(data)
    assert data["status"] in ("BOOKED", "CANCELLED", "NO_SHOW", "CONSUMED")
    assert data["visit_type"] in ("PRIMARY_CARE", "OCC_HEALTH", "WELLNESS")
    assert isinstance(data["reschedule_count"], int)
    assert_slot_is_thirty_minutes(data)
    assert_same_date(data["service_date"], data["scheduled_start"][:10])


def assert_visit(data):
    assert_common_fields(data)
    assert data["encounter_status"] in (
        "CHECKED_IN",
        "IN_PROGRESS",
        "COMPLETED",
        "AMENDED",
        "LOCKED",
    )
    assert data["disclosure_status"] in (
        "WALLED",
        "RELEASE_PENDING",
        "FITNESS_RELEASED",
        "PARTICIPATION_RELEASED",
        "NOT_DISCLOSABLE",
        "SUPPRESSED",
    )
    assert data["visit_type"] in ("PRIMARY_CARE", "OCC_HEALTH", "WELLNESS")
    assert isinstance(data["amendment_count"], int)


def assert_health_assessment(data):
    assert_common_fields(data)
    assert data["source_type"] in ("CLINIC_MEASURED", "SELF_ATTESTED")
    assert data["risk_band"] in ("LOW", "MODERATE", "HIGH")
    assert data["outcome_credit_status"] in (
        "MET_DIRECT",
        "PENDING_ALTERNATIVE",
        "CREDITED_VIA_RAS",
    )
    assert isinstance(data["risk_points_raw"], int)
    assert isinstance(data["risk_points_total"], int)
    assert isinstance(data["outcome_standard_met"], bool)


def assert_referral(data):
    assert_common_fields(data)
    assert data["status"] in (
        "SUBMITTED",
        "AUTHORIZED",
        "DECLINED",
        "REDIRECTED",
        "ESCALATED",
        "CLOSED_LOOP",
    )
    assert data["steerage_tier"] in (
        "CENTER_OF_EXCELLENCE",
        "PREFERRED",
        "STANDARD",
        "OUT_OF_NETWORK",
    )
    assert data["urgency"] in ("EMERGENT", "URGENT", "ROUTINE")
    parse_instant(data["sla_due_at"])


def assert_alternative_standard(data):
    assert_common_fields(data)
    assert data["status"] in ("REQUESTED", "ASSIGNED", "COMPLETED", "DENIED")
    assert isinstance(data["credit_granted"], bool)
    assert isinstance(data["reassignment_count"], int)


def assert_incentive_award(data):
    assert_common_fields(data)
    assert data["award_type"] in ("OUTCOME_BASED", "PARTICIPATORY", "TOBACCO_CESSATION")
    assert data["status"] in (
        "PENDING",
        "APPROVED",
        "EXPORTED",
        "PAID",
        "REVERSED",
        "FORFEITED",
    )
    assert isinstance(data["award_amount_cents"], int)
    assert isinstance(data["retroactive"], bool)


def assert_reporting_period(data):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "FINALIZED", "RESTATING", "CLOSED")
    assert isinstance(data["restatement_count"], int)
    for bucket in (
        "incentive_awarded_cents",
        "incentive_pending_cents",
        "incentive_paid_cents",
        "incentive_reversed_cents",
        "incentive_forfeited_cents",
    ):
        assert isinstance(data[bucket], int), f"{bucket} must be an integer"
    assert_period_money_conservation(data)


# ------------------------------------------------ conservation invariants ----


def assert_site_slot_conservation(site):
    """PRD 2.12: requested total equals held + consumed + no-show + released."""
    partition = (
        site["slots_held_count"]
        + site["slots_consumed_count"]
        + site["slots_no_show_count"]
        + site["slots_released_count"]
    )
    assert partition == site["slots_requested_total"], (
        "site slot partition broken: held "
        f"{site['slots_held_count']} + consumed {site['slots_consumed_count']} + "
        f"no_show {site['slots_no_show_count']} + released {site['slots_released_count']} "
        f"!= requested_total {site['slots_requested_total']}"
    )


def assert_contract_quota_conservation(contract):
    """PRD 2.12: requested total equals consumed + released; remaining is derived."""
    assert (
        contract["quota_visits_consumed"] + contract["quota_visits_released"]
        == contract["quota_visits_requested_total"]
    ), (
        "contract quota partition broken: consumed "
        f"{contract['quota_visits_consumed']} + released "
        f"{contract['quota_visits_released']} != requested_total "
        f"{contract['quota_visits_requested_total']}"
    )
    assert (
        contract["quota_visits_remaining"]
        == contract["quota_visits_total"] - contract["quota_visits_consumed"]
    ), "quota_visits_remaining must equal quota_visits_total less quota_visits_consumed"


def assert_period_money_conservation(period):
    """PRD 2.12: awarded equals pending + paid + reversed + forfeited."""
    partition = (
        period["incentive_pending_cents"]
        + period["incentive_paid_cents"]
        + period["incentive_reversed_cents"]
        + period["incentive_forfeited_cents"]
    )
    assert partition == period["incentive_awarded_cents"], (
        "period incentive partition broken: pending "
        f"{period['incentive_pending_cents']} + paid {period['incentive_paid_cents']} + "
        f"reversed {period['incentive_reversed_cents']} + forfeited "
        f"{period['incentive_forfeited_cents']} != awarded "
        f"{period['incentive_awarded_cents']}"
    )


# ----------------------------------------------------- domain helpers ----


def assert_slot_is_thirty_minutes(appointment):
    """PRD 3.4: appointments are a fixed half hour."""
    start = parse_instant(appointment["scheduled_start"])
    end = parse_instant(appointment["scheduled_end"])
    assert (end - start).total_seconds() == 30 * 60, (
        f"appointment must span exactly 30 minutes, got {appointment['scheduled_start']} "
        f"to {appointment['scheduled_end']}"
    )


def assert_employer_disclosure_payload(payload, expected_status, expected_conclusion):
    """PRD 3.5: the employer-visible projection carries exactly seven keys and
    never the clinical note."""
    for key in (
        "visit_id",
        "visit_type",
        "service_date",
        "disclosure_status",
        "fitness_conclusion",
        "participation_recorded",
        "clinical_detail_included",
    ):
        assert key in payload, f"employer disclosure payload is missing {key}"
    assert "clinical_note" not in payload, (
        "clinical_note must never appear in an employer-facing payload"
    )
    assert payload["disclosure_status"] == expected_status
    assert payload["fitness_conclusion"] == expected_conclusion
    assert payload["participation_recorded"] is True
    assert payload["clinical_detail_included"] is False
