"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import CONTROL_DOMAIN_ORDER, DOMAIN_WEIGHTS


def assert_common_fields(data: dict):
    """id / created_at / updated_at / version appear on every persisted resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_millisecond_timestamp(value: str):
    """ISO 8601 UTC rendered with exactly three fractional digits."""
    assert isinstance(value, str) and value, f"expected a timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not ISO 8601: {value!r}"
    frac = value.split(".")[-1]
    digits = "".join(ch for ch in frac if ch.isdigit())
    assert "." in value and len(digits) == 3, (
        f"timestamp must carry exactly three fractional digits, got {value!r}"
    )


def assert_decimals(value, places: int, label: str = "value"):
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    quantized = round(float(value), places)
    assert abs(float(value) - quantized) < 1e-9, (
        f"{label} must carry at most {places} decimals, got {value!r}"
    )


def assert_jurisdiction_profile(data: dict):
    assert_common_fields(data)
    assert isinstance(data["jurisdiction_code"], str) and len(data["jurisdiction_code"]) == 2
    assert data["jurisdiction_code"].isupper() and data["jurisdiction_code"].isalpha()
    assert 1 <= len(data["name"]) <= 120
    assert data["sanctions_status"] in ("PERMITTED", "RESTRICTED", "COMPREHENSIVELY_SANCTIONED")
    assert data["fatf_listing"] in ("NONE", "INCREASED_MONITORING", "CALL_FOR_ACTION")
    assert isinstance(data["secrecy_flag"], bool)
    assert isinstance(data["nested_correspondent_prohibited"], bool)
    assert 0.00 <= data["basel_aml_index"] <= 10.00
    assert 0.50 <= data["corridor_risk_weight"] <= 2.50
    assert data["max_permitted_risk_rating"] in ("LOW", "MEDIUM", "HIGH", "PROHIBITED")
    assert 0.00 <= data["jurisdiction_risk_points"] <= 40.00
    assert_decimals(data["jurisdiction_risk_points"], 2, "jurisdiction_risk_points")


def assert_respondent(data: dict):
    assert_common_fields(data)
    assert 1 <= len(data["legal_name"]) <= 160
    assert len(data["swift_bic"]) in (8, 11)
    assert data["dd_state"] in (
        "PROSPECT", "DD_IN_PROGRESS", "PENDING_COMMITTEE", "APPROVED", "DECLINED",
        "RESTRICTED", "REFRESH_DUE", "UNDER_REFRESH", "REFRESH_OVERDUE", "EXITING", "TERMINATED",
    )
    assert data["payment_posture"] in ("BLOCKED", "SCREEN_ONLY", "OPEN", "WIND_DOWN_ONLY")
    assert data["license_status"] in (
        "UNVERIFIED", "ACTIVE", "CONDITIONAL", "SUSPENDED", "REVOKED"
    )
    assert data["regulator_standing"] in (
        "UNVERIFIED", "GOOD_STANDING", "UNDER_ENFORCEMENT", "DEREGISTERED"
    )
    assert data["risk_rating"] in ("UNRATED", "LOW", "MEDIUM", "HIGH", "PROHIBITED")
    assert data["approved_risk_rating"] in ("UNRATED", "LOW", "MEDIUM", "HIGH", "PROHIBITED")
    assert_respondent_invariants(data)


def assert_respondent_invariants(data: dict):
    """Invariants that must hold on a respondent after any operation."""
    assert 0.00 <= data["verified_ownership_pct"] <= 100.00
    assert_decimals(data["verified_ownership_pct"], 2, "verified_ownership_pct")
    assert isinstance(data["control_chain_complete"], bool)
    assert isinstance(data["ownership_verified"], bool)
    assert data["ownership_verified"] == (
        data["verified_ownership_pct"] >= 75.00 and data["control_chain_complete"]
    ), "ownership_verified must be verified_ownership_pct >= 75.00 and control_chain_complete"
    for counter in (
        "disclosed_nested_count", "undisclosed_nested_count", "max_nested_depth",
        "nested_exposure_units", "unresponsive_strikes", "escalation_units",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer, got {data[counter]!r}"
        )
    assert 0.00 <= data["inherent_risk_score"] <= 100.00
    assert_decimals(data["inherent_risk_score"], 2, "inherent_risk_score")
    assert 0.00 <= data["control_score"] <= 100.00
    assert_decimals(data["control_score"], 2, "control_score")
    assert_decimals(data["control_credit"], 4, "control_credit")
    assert 0.00 <= data["adverse_media_uplift"] <= 20.00
    assert_decimals(data["adverse_media_uplift"], 2, "adverse_media_uplift")
    assert_decimals(data["residual_risk_score"], 2, "residual_risk_score")


def assert_beneficial_owner(data: dict):
    assert_common_fields(data)
    assert 1 <= len(data["owner_name"]) <= 160
    assert data["owner_type"] in ("NATURAL_PERSON", "LEGAL_ENTITY", "STATE")
    assert 0.00 < data["ownership_pct"] <= 100.00
    assert data["verification_status"] in ("PENDING", "VERIFIED", "REJECTED")
    assert 1 <= data["chain_depth"] <= 4
    assert_decimals(data["effective_ownership_pct"], 2, "effective_ownership_pct")
    assert isinstance(data["is_pep"], bool)


def assert_questionnaire(data: dict):
    assert_common_fields(data)
    assert 1 <= len(data["questionnaire_version"]) <= 40
    assert data["state"] in (
        "DRAFT", "SUBMITTED", "UNDER_ASSESSMENT", "RETURNED_FOR_CLARIFICATION",
        "ASSESSED", "SUPERSEDED",
    )
    assert 0 <= data["clarification_rounds"] <= 3
    assert data["control_score_variant"] in ("NONE", "ONBOARDING_PROVISIONAL", "REFRESH_FINAL")
    assert isinstance(data["declared_nested_activity"], bool)
    assert isinstance(data["declared_downstream_count"], int)


def assert_control_assessment(data: dict):
    assert_common_fields(data)
    assert data["control_domain"] in CONTROL_DOMAIN_ORDER
    assert 1 <= data["self_rating"] <= 5
    if data["assessed_rating"] is not None:
        assert 1 <= data["assessed_rating"] <= 5
    assert data["gap_severity"] in ("NONE", "MINOR", "MAJOR", "CRITICAL")
    assert isinstance(data["remediation_required"], bool)
    assert abs(data["domain_weight"] - DOMAIN_WEIGHTS[data["control_domain"]]) < 1e-9, (
        f"domain_weight for {data['control_domain']} must be "
        f"{DOMAIN_WEIGHTS[data['control_domain']]}, got {data['domain_weight']}"
    )


def assert_nested_relationship(data: dict):
    assert_common_fields(data)
    assert 1 <= len(data["downstream_institution_name"]) <= 160
    assert data["relationship_type"] in (
        "DOWNSTREAM_CORRESPONDENT", "PAYABLE_THROUGH", "NESTED_PSP"
    )
    assert data["discovery_source"] in (
        "QUESTIONNAIRE", "TRANSACTION_MONITORING", "RFI", "ADVERSE_MEDIA"
    )
    assert data["state"] in (
        "DISCLOSED", "UNDISCLOSED_DETECTED", "CONFIRMED", "SUSPENDED", "PROHIBITED", "TERMINATED"
    )
    assert isinstance(data["depth"], int) and 1 <= data["depth"] <= 4


def assert_monitoring_profile(data: dict):
    assert_common_fields(data)
    assert data["calibration_state"] in (
        "PROVISIONAL", "CALIBRATED", "RECALIBRATION_REQUIRED", "SUPERSEDED"
    )
    assert 0.00 <= data["tolerance_pct"] <= 0.50
    assert isinstance(data["expected_corridors"], list)
    assert 1 <= len(data["expected_corridors"]) <= 8
    assert isinstance(data["corridor_thresholds"], list)


def assert_calibrated_profile(data: dict):
    """Corridor thresholds and the buffered aggregate after a calibration."""
    assert_monitoring_profile(data)
    assert data["calibration_state"] == "CALIBRATED"
    assert len(data["corridor_thresholds"]) == len(data["expected_corridors"])
    for supplied, computed in zip(data["expected_corridors"], data["corridor_thresholds"]):
        assert computed["jurisdiction_code"] == supplied["jurisdiction_code"], (
            "corridor_thresholds must be in the same order as the corridors were supplied"
        )
        assert 10000.00 <= computed["usd_threshold"] <= 500000000.00
        assert_decimals(computed["usd_threshold"], 2, "usd_threshold")
        assert isinstance(computed["count_threshold"], int) and computed["count_threshold"] >= 5
    total = round(sum(c["usd_threshold"] for c in data["corridor_thresholds"]) * 1.10, 2)
    assert abs(data["aggregate_usd_threshold"] - total) < 0.01, (
        f"aggregate_usd_threshold must be the rounded corridor sum times 1.10 "
        f"({total}), got {data['aggregate_usd_threshold']}"
    )
    assert abs(data["hold_threshold_usd"] - round(data["aggregate_usd_threshold"] / 10.0, 2)) < 0.01


def assert_activity_observation(data: dict):
    assert_common_fields(data)
    assert len(data["period_month"]) == 7 and data["period_month"][4] == "-"
    assert data["aggregate_usd"] >= 0
    assert isinstance(data["txn_count"], int)
    assert isinstance(data["distinct_downstream_count"], int)
    assert isinstance(data["alerts_created_count"], int) and 0 <= data["alerts_created_count"] <= 4
    if data["breach_ratio"] is not None:
        assert_decimals(data["breach_ratio"], 4, "breach_ratio")


def assert_monitoring_alert(data: dict):
    assert_common_fields(data)
    assert data["alert_type"] in (
        "VOLUME_BREACH", "COUNT_BREACH", "CORRIDOR_UNEXPECTED", "NESTED_ACTIVITY_UNDISCLOSED"
    )
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["state"] in (
        "OPEN", "UNDER_INVESTIGATION", "ESCALATED", "CLOSED_FALSE_POSITIVE", "CLOSED_CONFIRMED"
    )
    if data["breach_ratio"] is not None:
        assert_decimals(data["breach_ratio"], 4, "breach_ratio")


def assert_information_request(data: dict):
    assert_common_fields(data)
    assert data["request_topic"] in (
        "OWNERSHIP_EVIDENCE", "LICENSING_EVIDENCE", "NESTED_DISCLOSURE",
        "ACTIVITY_EXPLANATION", "CONTROL_REMEDIATION",
    )
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["state"] in (
        "DRAFT", "SENT", "RESPONDED", "OVERDUE", "ESCALATED", "ACCEPTED", "ABANDONED"
    )
    assert 0 <= data["escalation_level"] <= 3
    assert data["reminder_count"] >= 0
    assert 0 <= data["insufficiency_rounds"] <= 2
    assert isinstance(data["retro_credited"], bool)


def assert_adverse_media_event(data: dict):
    assert_common_fields(data)
    assert 1 <= len(data["headline"]) <= 200
    assert data["category"] in (
        "SANCTIONS_EVASION", "MONEY_LAUNDERING", "FRAUD", "REGULATORY_ACTION",
        "LITIGATION", "OTHER",
    )
    assert data["severity_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert data["source_reliability"] in ("A", "B", "C")
    assert data["adjudication_state"] in ("NEW", "CONFIRMED", "DISMISSED")
    assert_decimals(data["uplift_points"], 2, "uplift_points")


def assert_periodic_refresh(data: dict):
    assert_common_fields(data)
    assert data["trigger_reason"] in (
        "CADENCE", "ADVERSE_MEDIA", "ALERT_ESCALATION", "NESTED_DISCOVERY", "REGULATOR_ACTION"
    )
    assert data["state"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "LAPSED", "CANCELLED")
    assert isinstance(data["cadence_months_applied"], int)


def assert_payment_instruction(data: dict):
    assert_common_fields(data)
    assert data["amount_usd"] > 0
    assert data["purpose_code"] in (
        "TRADE_SETTLEMENT", "REMITTANCE", "INTERBANK_PLACEMENT", "RETURN_OF_FUNDS", "SETTLEMENT"
    )
    assert data["screening_state"] in (
        "RECEIVED", "SCREENED_CLEAR", "HELD_FOR_REVIEW", "BLOCKED_SANCTIONS", "RELEASED", "REJECTED"
    )
    if data["hold_reason"] is not None:
        assert data["hold_reason"] in (
            "SANCTIONS_RESTRICTED_JURISDICTION", "POSTURE_SCREEN_ONLY",
            "UNDISCLOSED_NESTED_PARTY", "AMOUNT_THRESHOLD",
        )
    assert isinstance(data["involves_nested_party"], bool)
    if data["screening_state"] == "BLOCKED_SANCTIONS":
        assert data["hold_reason"] is None, "a blocked instruction is never a hold"


def assert_closure_plan(data: dict):
    assert_common_fields(data)
    assert data["termination_reason"] in (
        "UNRESPONSIVE", "SANCTIONS_EXPOSURE", "PROHIBITED_NESTING", "RISK_APPETITE",
        "COMMERCIAL", "REGULATORY_ACTION",
    )
    assert data["state"] in (
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "NOTICE_SERVED", "WIND_DOWN", "CLOSED", "ABORTED"
    )
    assert data["cap_basis"] in ("NONE", "FORWARD_PROJECTED", "CHRONOLOGICAL_ACTUAL")
    assert isinstance(data["notice_period_days"], int) and data["notice_period_days"] >= 0
    assert_obligation_invariants(data)


def assert_obligation_invariants(data: dict):
    """After every allocation and every reversal, both invariants hold."""
    assert (
        data["outstanding_obligation_cents"] + data["settled_cents"]
        == data["original_obligation_cents"]
    ), (
        "outstanding_obligation_cents plus settled_cents must equal "
        f"original_obligation_cents; got {data['outstanding_obligation_cents']} + "
        f"{data['settled_cents']} != {data['original_obligation_cents']}"
    )
    assert 0 <= data["outstanding_obligation_cents"] <= data["original_obligation_cents"]
    assert isinstance(data["allocation_round"], int) and data["allocation_round"] >= 0
    assert isinstance(data["allocation_lines"], list)


def assert_control_domain_weight_order(rows: list):
    """Control-assessment rows come back in the fixed control-domain weight order."""
    returned = [r["control_domain"] for r in rows]
    expected = [d for d in CONTROL_DOMAIN_ORDER if d in returned]
    assert returned == expected, (
        f"rows must be returned in the fixed control-domain weight order {expected}, got {returned}"
    )


def assert_sorted_ascending(rows: list, field: str):
    values = [r[field] for r in rows]
    assert values == sorted(values), f"rows must be sorted by {field} ascending, got {values}"


def assert_sorted_descending(rows: list, field: str):
    values = [r[field] for r in rows]
    assert values == sorted(values, reverse=True), (
        f"rows must be sorted by {field} descending, got {values}"
    )

def parse_instant(value: str):
    """Parse an ISO 8601 UTC instant however many fractional digits it carries."""
    from datetime import datetime, timezone

    assert isinstance(value, str) and value, f"expected an instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str, label: str = "instant"):
    """Compare two ISO 8601 instants by value, not by rendering."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label} must be {expected}, got {actual}"
    )
