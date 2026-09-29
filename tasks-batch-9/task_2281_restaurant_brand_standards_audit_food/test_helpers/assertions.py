"""Entity assertions and domain invariant checkers for the audit API."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

VERSIONED_TIMESTAMP_FIELDS = ("created_at", "updated_at")


def assert_versioned_record(data: dict):
    """Fields carried by every fully versioned resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be an integer, got {data.get('version')!r}"


def assert_light_record(data: dict):
    """Fields carried by the four record types that hold only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "updated_at must be absent from this record type"
    assert "version" not in data, "version must be absent from this record type"


def assert_instant(actual, expected_iso, label="instant"):
    """Compare two ISO 8601 UTC instants to whole-second precision."""
    assert isinstance(actual, str), f"{label} must be a string instant, got {actual!r}"
    assert is_iso8601_timestamp(actual), f"{label} must be ISO 8601, got {actual!r}"
    assert actual[:19] == expected_iso[:19], \
        f"{label} should be {expected_iso}, got {actual}"


def assert_two_decimals(value, label="value"):
    """Decimal figures are carried to exactly two decimal places."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), \
        f"{label} must carry at most two decimal places, got {value!r}"


# --------------------------------------------------------------------------
# Per-resource assertions
# --------------------------------------------------------------------------
def assert_brand(data: dict):
    assert_versioned_record(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["brand_code"], str) and 2 <= len(data["brand_code"]) <= 8
    assert isinstance(data["unannounced_min_ratio_pct"], int)
    assert 0 <= data["unannounced_min_ratio_pct"] <= 100
    assert_two_decimals(data["brand_risk_index"], "brand_risk_index")
    assert data["brand_risk_tier"] in ("BASELINE", "ELEVATED", "SEVERE")
    assert isinstance(data["location_count"], int) and data["location_count"] >= 0
    assert isinstance(data["default_location_count"], int) and data["default_location_count"] >= 0


def assert_franchisee(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["brand_id"])
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 160
    assert "@" in data["contact_email"], "contact_email must contain an at-sign"
    assert isinstance(data["open_default_location_count"], int)
    assert isinstance(data["termination_recommended"], bool)


def assert_auditor(data: dict):
    assert_versioned_record(data)
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert isinstance(data["employee_code"], str) and 3 <= len(data["employee_code"]) <= 12
    assert data["status"] in ("PROVISIONAL", "CERTIFIED", "SUSPENDED")
    assert_two_decimals(data["reliability_score"], "reliability_score")
    assert 0.00 <= data["reliability_score"] <= 100.00
    assert isinstance(data["finalized_visit_count"], int)
    if data.get("suspension_reason") is not None:
        assert data["suspension_reason"] in ("MANUAL_REVIEW", "RELIABILITY_BELOW_FLOOR")


def assert_location(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["brand_id"])
    assert is_valid_uuid(data["franchisee_id"])
    assert isinstance(data["store_number"], str) and 3 <= len(data["store_number"]) <= 16
    assert data["region_code"] in ("NORTHEAST", "SOUTHEAST", "MIDWEST", "WEST")
    assert_two_decimals(data["standing_score"], "standing_score")
    assert data["standing_score"] >= 0.00, "standing_score never goes below 0.00"
    if data.get("latest_grade") is not None:
        assert data["latest_grade"] in ("PASS", "CONDITIONAL", "FAIL")
    assert isinstance(data["open_corrective_action_count"], int)
    assert data["open_corrective_action_count"] >= 0
    assert isinstance(data["repeat_violation_count"], int)
    assert isinstance(data["escalation_level"], int)
    assert data["escalation_level"] >= 0, "escalation_level is never negative"
    assert data["franchise_agreement_status"] in (
        "GOOD_STANDING", "NOTICE_OF_DEFAULT", "CURE_PERIOD", "TERMINATION_RECOMMENDED",
    )


def assert_rubric_version(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["brand_id"])
    assert isinstance(data["version_label"], str) and len(data["version_label"]) > 0
    assert isinstance(data["total_points"], int) and 1 <= data["total_points"] <= 1000
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")
    assert isinstance(data["item_count"], int) and data["item_count"] >= 0
    assert isinstance(data["critical_item_count"], int) and data["critical_item_count"] >= 0


def assert_rubric_item(data: dict):
    assert_light_record(data)
    assert is_valid_uuid(data["rubric_version_id"])
    assert isinstance(data["item_code"], str) and len(data["item_code"]) > 0
    assert data["section"] in ("FOOD_SAFETY", "BRAND_STANDARDS", "FACILITY")
    assert isinstance(data["max_points"], int) and 1 <= data["max_points"] <= 100
    assert isinstance(data["is_critical"], bool)
    assert isinstance(data["display_order"], int) and 1 <= data["display_order"] <= 999


def assert_audit_visit(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["location_id"])
    assert is_valid_uuid(data["auditor_id"])
    assert is_valid_uuid(data["rubric_version_id"])
    assert data["visit_type"] in ("ANNOUNCED", "UNANNOUNCED", "SHADOW")
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "SUBMITTED", "FINALIZED", "VOIDED",
    )
    assert isinstance(data["critical_violation_count"], int)
    assert_two_decimals(data["critical_penalty_points"], "critical_penalty_points")
    assert isinstance(data["rescore_count"], int) and 0 <= data["rescore_count"] <= 2
    if data.get("composite_variant") is not None:
        assert data["composite_variant"] in ("PROVISIONAL", "FINAL")
    if data.get("grade") is not None:
        assert data["grade"] in ("PASS", "CONDITIONAL", "FAIL")
    if data.get("void_reason") is not None:
        assert data["void_reason"] in (
            "AUDITOR_SUSPENDED", "RUBRIC_DEFECT", "SCHEDULING_ERROR",
        )
    for field in ("food_safety_percent", "brand_standards_percent",
                  "facility_percent", "health_component_percent", "composite_score"):
        if data.get(field) is not None:
            assert_two_decimals(data[field], field)


def assert_scheduled_visit_is_blank(data: dict):
    """A newly scheduled visit's derived fields are all null or zero."""
    for field in ("started_at", "submitted_at", "finalized_at", "food_safety_percent",
                  "brand_standards_percent", "facility_percent", "health_component_percent",
                  "composite_score", "composite_variant", "grade",
                  "linked_health_inspection_id", "void_reason"):
        assert data.get(field) is None, f"{field} must be null on a newly scheduled visit"
    assert data["critical_violation_count"] == 0
    assert data["critical_penalty_points"] == 0.00
    assert data["rescore_count"] == 0


def assert_scored_item(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["visit_id"])
    assert is_valid_uuid(data["rubric_item_id"])
    assert isinstance(data["points_awarded"], int)
    assert isinstance(data["original_points_awarded"], int)
    assert isinstance(data["effective_points_awarded"], int)
    assert isinstance(data["is_violation"], bool)
    assert data["severity"] in ("NONE", "STANDARD", "CRITICAL")
    assert data["status"] in ("SCORED", "UNDER_DISPUTE", "AMENDED", "UPHELD")


def assert_corrective_action(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["scored_item_id"])
    assert is_valid_uuid(data["location_id"])
    assert is_valid_uuid(data["assigned_franchisee_id"])
    assert data["severity"] in ("STANDARD", "CRITICAL")
    assert data["status"] in (
        "ASSIGNED", "SUBMITTED", "REJECTED", "VERIFIED", "OVERDUE", "ESCALATED", "VOIDED",
    )
    assert is_iso8601_timestamp(data["due_at"]), "due_at must be ISO 8601 UTC"
    for counter in ("submission_count", "rejection_count", "evidence_photo_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_dispute(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["scored_item_id"])
    assert is_valid_uuid(data["filed_by_franchisee_id"])
    assert isinstance(data["requested_points"], int)
    assert isinstance(data["reason"], str) and 10 <= len(data["reason"]) <= 1000
    assert data["status"] in (
        "FILED", "INFO_REQUESTED", "EVIDENCE_REVIEW", "UPHELD", "AMENDED", "WITHDRAWN",
    )
    assert isinstance(data["info_request_count"], int) and 0 <= data["info_request_count"] <= 2


def assert_health_inspection(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["location_id"])
    assert isinstance(data["authority_name"], str) and 1 <= len(data["authority_name"]) <= 120
    assert isinstance(data["points_possible"], int) and 1 <= data["points_possible"] <= 1000
    assert isinstance(data["points_scored"], int)
    assert 0 <= data["points_scored"] <= data["points_possible"]
    assert data["letter_grade"] in ("A", "B", "C", "FAIL")
    assert data["status"] in ("RECORDED", "DISREGARDED")
    if data.get("disregard_reason") is not None:
        assert data["disregard_reason"] in (
            "SUPERSEDED_BY_REINSPECTION", "WRONG_LOCATION", "DATA_ERROR",
        )


def assert_evidence_photo(data: dict):
    assert_light_record(data)
    assert data["file_uri"].startswith("s3://"), "file_uri must begin with s3://"
    assert is_iso8601_timestamp(data["captured_at"]), "captured_at must be ISO 8601"
    assert data["uploaded_by_role"] in ("Franchisee", "Auditor")
    named = [data.get("corrective_action_id"), data.get("dispute_id")]
    assert sum(1 for value in named if value is not None) == 1, \
        "a photo names exactly one of corrective_action_id and dispute_id"


def assert_calibration_record(data: dict):
    assert_light_record(data)
    assert is_valid_uuid(data["shadow_visit_id"])
    assert is_valid_uuid(data["primary_visit_id"])
    assert is_valid_uuid(data["auditor_id"])
    assert is_valid_uuid(data["reviewer_auditor_id"])
    assert_two_decimals(data["variance_points"], "variance_points")
    assert data["variance_points"] >= 0.00, "variance_points is an absolute difference"
    assert data["band"] in ("EXCELLENT", "ACCEPTABLE", "MARGINAL", "UNACCEPTABLE")
    assert_two_decimals(data["reliability_delta"], "reliability_delta")
    assert is_iso8601_timestamp(data["recorded_at"])


def assert_escalation_event(data: dict):
    assert_light_record(data)
    assert is_valid_uuid(data["location_id"])
    assert data["event_type"] in (
        "REPEAT_CRITICAL", "OVERDUE_CRITICAL", "CURE_ACCEPTED", "VOID_REVERSAL",
    )
    assert data["level_delta"] in (1, -1)
    assert isinstance(data["resulting_escalation_level"], int)
    assert data["resulting_escalation_level"] >= 0
    assert data["resulting_agreement_status"] in (
        "GOOD_STANDING", "NOTICE_OF_DEFAULT", "CURE_PERIOD", "TERMINATION_RECOMMENDED",
    )
    assert is_iso8601_timestamp(data["occurred_at"])


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_grade_matches_composite(data: dict):
    """The grade derivation, critical-violation override included."""
    if data.get("composite_score") is None:
        assert data.get("grade") is None, "grade must be null when no composite exists"
        return
    if data["critical_violation_count"] >= 2:
        assert data["grade"] == "FAIL", \
            "two or more critical violations grade FAIL regardless of the score"
        return
    score = data["composite_score"]
    expected = "PASS" if score >= 90.00 else "CONDITIONAL" if score >= 80.00 else "FAIL"
    assert data["grade"] == expected, \
        f"composite {score} should grade {expected}, got {data['grade']}"


def assert_agreement_status_matches_level(data: dict):
    """The agreement status follows directly from the escalation level."""
    level = data["escalation_level"]
    if level == 0:
        expected = "GOOD_STANDING"
    elif level == 1:
        expected = "NOTICE_OF_DEFAULT"
    elif level == 2:
        expected = "CURE_PERIOD"
    else:
        expected = "TERMINATION_RECOMMENDED"
    assert data["franchise_agreement_status"] == expected, \
        f"escalation_level {level} should give {expected}, got {data['franchise_agreement_status']}"


def assert_risk_tier_matches_index(data: dict):
    index = data["brand_risk_index"]
    expected = "SEVERE" if index >= 60.00 else "ELEVATED" if index >= 35.00 else "BASELINE"
    assert data["brand_risk_tier"] == expected, \
        f"index {index} should give tier {expected}, got {data['brand_risk_tier']}"


def assert_calibration_band_matches_variance(data: dict):
    variance = data["variance_points"]
    if variance <= 2.00:
        band, delta = "EXCELLENT", 4.00
    elif variance <= 5.00:
        band, delta = "ACCEPTABLE", 1.00
    elif variance <= 10.00:
        band, delta = "MARGINAL", -3.00
    else:
        band, delta = "UNACCEPTABLE", -8.00
    assert data["band"] == band, f"variance {variance} lands in {band}, got {data['band']}"
    assert data["reliability_delta"] == delta, \
        f"band {band} credits {delta}, got {data['reliability_delta']}"
