"""Domain assertion helpers for the Wildfire Mitigation PSPS contract."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import TOLERANCE_1DP, TOLERANCE_2DP, TOLERANCE_4DP


# --------------------------------------------------------------------------
# Common fields (PRD §2.4)
# --------------------------------------------------------------------------
def assert_versioned_entity(entity, expected_version=None):
    """A versioned resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_record(record):
    """An append-only record carries only id and created_at from the common set."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert "updated_at" not in record, "append-only records carry no updated_at"
    assert "version" not in record, "append-only records carry no version"


def assert_envelope_meta(response):
    meta = response.json()["meta"]
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta[
        "api_request_timestamp"
    ]
    return meta


def assert_instant(actual, expected):
    """Compare two UTC instants without insisting on how many fractional digits the
    server chose to print."""
    if expected is None:
        assert actual is None, f"expected null, got {actual!r}"
        return
    assert isinstance(actual, str), f"expected an ISO 8601 instant, got {actual!r}"
    assert is_iso8601_timestamp(actual), f"not an ISO 8601 UTC instant: {actual!r}"
    assert _normalise_instant(actual) == _normalise_instant(expected), (
        f"expected instant {expected}, got {actual}"
    )


def _normalise_instant(value):
    body = value[:-1] if value.endswith("Z") else value
    if "." in body:
        head, fraction = body.split(".", 1)
        return f"{head}.{fraction.ljust(3, '0')[:3]}"
    return f"{body}.000"


def assert_list_meta_absent(response):
    """Single-resource reads and action endpoints omit the four pagination fields."""
    meta = response.json()["meta"]
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, f"meta must omit {field} on a non-list response"


# --------------------------------------------------------------------------
# Numeric scales (PRD §2.6)
# --------------------------------------------------------------------------
def assert_4dp(actual, expected):
    """`hardened_fraction` and `net_benefit_ratio` carry four decimal places."""
    assert abs(float(actual) - float(expected)) < TOLERANCE_4DP, (
        f"expected {expected} at 4 dp, got {actual}"
    )


def assert_2dp(actual, expected):
    """Score fields carry two decimal places."""
    assert abs(float(actual) - float(expected)) < TOLERANCE_2DP, (
        f"expected {expected} at 2 dp, got {actual}"
    )


def assert_1dp(actual, expected):
    """Mileage fields carry one decimal place."""
    assert abs(float(actual) - float(expected)) < TOLERANCE_1DP, (
        f"expected {expected} at 1 dp, got {actual}"
    )


def assert_integer(actual, expected):
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"expected an integer, got {actual!r}"
    )
    assert actual == expected, f"expected {expected}, got {actual}"


# --------------------------------------------------------------------------
# Circuits
# --------------------------------------------------------------------------
def assert_circuit_state(circuit, energization_state=None, risk_posture=None):
    if energization_state is not None:
        assert circuit["energization_state"] == energization_state, (
            f"expected energization_state {energization_state}, "
            f"got {circuit['energization_state']}"
        )
    if risk_posture is not None:
        assert circuit["risk_posture"] == risk_posture, (
            f"expected risk_posture {risk_posture}, got {circuit['risk_posture']}"
        )


def assert_hardening_ledger(
    circuit, covered_conductor_miles, underground_miles, hardened_fraction
):
    """The per-circuit hardened-mileage ledger of PRD §2.11."""
    assert_1dp(circuit["covered_conductor_miles"], covered_conductor_miles)
    assert_1dp(circuit["underground_miles"], underground_miles)
    assert_4dp(circuit["hardened_fraction"], hardened_fraction)


def assert_population_counters(
    circuit, customer_count, medical_baseline_count, critical_facility_count
):
    assert_integer(circuit["customer_count"], customer_count)
    assert_integer(circuit["medical_baseline_count"], medical_baseline_count)
    assert_integer(circuit["critical_facility_count"], critical_facility_count)


def energized_customer_total(circuits):
    """The conserved quantity of PRD §2.11: customer_count over ENERGIZED circuits."""
    return sum(
        c["customer_count"] for c in circuits if c["energization_state"] == "ENERGIZED"
    )


# --------------------------------------------------------------------------
# Fire potential indices
# --------------------------------------------------------------------------
def assert_fpi(index, score, tier):
    assert_2dp(index["fpi_score"], score)
    assert index["fpi_tier"] == tier, (
        f"expected fpi_tier {tier}, got {index['fpi_tier']} at score {index['fpi_score']}"
    )


def assert_fpi_components(index, wind=None, dryness=None, terrain=None, equipment=None):
    if wind is not None:
        assert_2dp(index["wind_component"], wind)
    if dryness is not None:
        assert_2dp(index["dryness_component"], dryness)
    if terrain is not None:
        assert_2dp(index["terrain_component"], terrain)
    if equipment is not None:
        assert_2dp(index["equipment_component"], equipment)


def assert_effective_inputs(index, gust, humidity, fuel_moisture):
    assert_1dp(index["effective_wind_gust_mph"], gust)
    assert_1dp(index["effective_relative_humidity_pct"], humidity)
    assert_1dp(index["effective_dead_fuel_moisture_pct"], fuel_moisture)


# --------------------------------------------------------------------------
# Events, scope rows and net benefit
# --------------------------------------------------------------------------
def assert_event_dimensions(event, scope_status=None, notification_status=None):
    """The two independent state dimensions of PRD §3.4."""
    if scope_status is not None:
        assert event["scope_status"] == scope_status, (
            f"expected scope_status {scope_status}, got {event['scope_status']}"
        )
    if notification_status is not None:
        assert event["notification_status"] == notification_status, (
            f"expected notification_status {notification_status}, "
            f"got {event['notification_status']}"
        )


def assert_scope_counts(event, confirmed, excluded):
    assert_integer(event["confirmed_scope_count"], confirmed)
    assert_integer(event["excluded_scope_count"], excluded)


def assert_impact_counts(event, impacted, medical_baseline, critical_facility):
    assert_integer(event["impacted_customer_count"], impacted)
    assert_integer(event["medical_baseline_customer_count"], medical_baseline)
    assert_integer(event["critical_facility_count"], critical_facility)


def assert_net_benefit(
    event,
    variant=None,
    duration_hours=None,
    customer_impact_score=None,
    crc_mitigation_credit=None,
    adjusted_customer_impact_score=None,
    ignition_risk_avoided_score=None,
    net_benefit_ratio=None,
):
    """The five-step accounting of PRD §3.8."""
    if variant is not None:
        assert event["benefit_variant"] == variant, (
            f"expected benefit_variant {variant}, got {event['benefit_variant']}"
        )
    if duration_hours is not None:
        assert_integer(event["duration_hours"], duration_hours)
    if customer_impact_score is not None:
        assert_2dp(event["customer_impact_score"], customer_impact_score)
    if crc_mitigation_credit is not None:
        assert_2dp(event["crc_mitigation_credit"], crc_mitigation_credit)
    if adjusted_customer_impact_score is not None:
        assert_2dp(
            event["adjusted_customer_impact_score"], adjusted_customer_impact_score
        )
    if ignition_risk_avoided_score is not None:
        assert_2dp(event["ignition_risk_avoided_score"], ignition_risk_avoided_score)
    if net_benefit_ratio is not None:
        assert_4dp(event["net_benefit_ratio"], net_benefit_ratio)


def scope_row_for(rows, circuit_id):
    """The single scope row naming a circuit, or None."""
    matches = [row for row in rows if row["circuit_id"] == circuit_id]
    assert len(matches) <= 1, f"expected at most one scope row per circuit, got {matches}"
    return matches[0] if matches else None


def assert_scope_row(
    rows,
    circuit_id,
    scope_status=None,
    inclusion_basis=None,
    fpi_score_applied=None,
    ignition_risk_term=None,
    customer_count_snapshot=None,
    exclusion_justification=...,
    restored_at=...,
):
    row = scope_row_for(rows, circuit_id)
    assert row is not None, f"no scope row names circuit {circuit_id}"
    if scope_status is not None:
        assert row["scope_status"] == scope_status, (
            f"expected scope_status {scope_status}, got {row['scope_status']}"
        )
    if inclusion_basis is not None:
        assert row["inclusion_basis"] == inclusion_basis, (
            f"expected inclusion_basis {inclusion_basis}, got {row['inclusion_basis']}"
        )
    if fpi_score_applied is not None:
        assert_2dp(row["fpi_score_applied"], fpi_score_applied)
    if ignition_risk_term is not None:
        assert_2dp(row["ignition_risk_term"], ignition_risk_term)
    if customer_count_snapshot is not None:
        assert_integer(row["customer_count_snapshot"], customer_count_snapshot)
    if exclusion_justification is not ...:
        assert row["exclusion_justification"] == exclusion_justification, (
            f"expected exclusion_justification {exclusion_justification!r}, "
            f"got {row['exclusion_justification']!r}"
        )
    if restored_at is not ...:
        assert_instant(row["restored_at"], restored_at)
    return row


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------
def assert_batch_outcome(batch, status, target_count, delivered_count, unreachable_count):
    assert batch["status"] == status, (
        f"expected batch status {status}, got {batch['status']}"
    )
    assert_integer(batch["target_count"], target_count)
    assert_integer(batch["delivered_count"], delivered_count)
    assert_integer(batch["unreachable_count"], unreachable_count)


def record_for(records, customer_id):
    matches = [r for r in records if r["customer_id"] == customer_id]
    assert len(matches) == 1, (
        f"expected exactly one record for customer {customer_id}, got {len(matches)}"
    )
    return matches[0]


def assert_record(
    record,
    attempt_order=None,
    language_used=None,
    channel_used=...,
    delivery_status=None,
    accessibility_format=None,
):
    if attempt_order is not None:
        assert_integer(record["attempt_order"], attempt_order)
    if language_used is not None:
        assert record["language_used"] == language_used, (
            f"expected language_used {language_used}, got {record['language_used']}"
        )
    if channel_used is not ...:
        assert record["channel_used"] == channel_used, (
            f"expected channel_used {channel_used!r}, got {record['channel_used']!r}"
        )
    if delivery_status is not None:
        assert record["delivery_status"] == delivery_status, (
            f"expected delivery_status {delivery_status}, got {record['delivery_status']}"
        )
    if accessibility_format is not None:
        assert record["accessibility_format"] == accessibility_format, (
            f"expected accessibility_format {accessibility_format}, "
            f"got {record['accessibility_format']}"
        )


# --------------------------------------------------------------------------
# Resource centers
# --------------------------------------------------------------------------
def assert_center_state(
    center, status, activation_order=None, psps_event_id=..., last_served_all_clear_at=...
):
    assert center["status"] == status, (
        f"expected resource center status {status}, got {center['status']}"
    )
    if activation_order is not None:
        assert_integer(center["activation_order"], activation_order)
    if psps_event_id is not ...:
        assert center["psps_event_id"] == psps_event_id
    if last_served_all_clear_at is not ...:
        assert_instant(center["last_served_all_clear_at"], last_served_all_clear_at)


def assert_activation_summary(
    summary, activated_count, activated_capacity, unmet_capacity, activated_ids=None
):
    """The four-field summary object of PRD §3.6."""
    assert_integer(summary["activated_count"], activated_count)
    assert_integer(summary["activated_capacity"], activated_capacity)
    assert_integer(summary["unmet_capacity"], unmet_capacity)
    if activated_ids is not None:
        assert summary["activated_resource_center_ids"] == activated_ids, (
            f"expected activated_resource_center_ids {activated_ids}, "
            f"got {summary['activated_resource_center_ids']}"
        )


# --------------------------------------------------------------------------
# Plan filings
# --------------------------------------------------------------------------
def assert_filing_tracks(
    filing,
    status=None,
    safety_review_state=None,
    fiscal_review_state=None,
    safety_reviewer_user_id=...,
    fiscal_reviewer_user_id=...,
    deficiency_round_count=None,
):
    if status is not None:
        assert filing["status"] == status, (
            f"expected filing status {status}, got {filing['status']}"
        )
    if safety_review_state is not None:
        assert filing["safety_review_state"] == safety_review_state
    if fiscal_review_state is not None:
        assert filing["fiscal_review_state"] == fiscal_review_state
    if safety_reviewer_user_id is not ...:
        assert filing["safety_reviewer_user_id"] == safety_reviewer_user_id
    if fiscal_reviewer_user_id is not ...:
        assert filing["fiscal_reviewer_user_id"] == fiscal_reviewer_user_id
    if deficiency_round_count is not None:
        assert_integer(filing["deficiency_round_count"], deficiency_round_count)


def assert_filing_metrics(
    filing,
    qualifying_project_count=None,
    covered_conductor_miles_reported=None,
    underground_miles_reported=None,
    psps_event_count=None,
    customer_minutes_interrupted=None,
    avg_notification_lead_minutes=None,
    compliance_score=None,
):
    if qualifying_project_count is not None:
        assert_integer(filing["qualifying_project_count"], qualifying_project_count)
    if covered_conductor_miles_reported is not None:
        assert_1dp(
            filing["covered_conductor_miles_reported"], covered_conductor_miles_reported
        )
    if underground_miles_reported is not None:
        assert_1dp(filing["underground_miles_reported"], underground_miles_reported)
    if psps_event_count is not None:
        assert_integer(filing["psps_event_count"], psps_event_count)
    if customer_minutes_interrupted is not None:
        assert_integer(
            filing["customer_minutes_interrupted"], customer_minutes_interrupted
        )
    if avg_notification_lead_minutes is not None:
        assert_2dp(
            filing["avg_notification_lead_minutes"], avg_notification_lead_minutes
        )
    if compliance_score is not None:
        assert_2dp(filing["compliance_score"], compliance_score)
