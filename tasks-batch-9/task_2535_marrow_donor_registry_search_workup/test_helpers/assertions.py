"""Entity assertions and domain invariant checkers for the marrow-donor API."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

from .constants import CLAIM_LINE_ORDER


# ---------------------------------------------------------------------------
# shared shape helpers
# ---------------------------------------------------------------------------

def assert_common_record_properties(data: dict, label: str = "record"):
    """id / created_at / updated_at / version, as every resource but the
    append-only follow-up row carries them."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID with no prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_no_content(response):
    """A 204 response carries no body at all."""
    assert response.status_code == 204, (
        f"Expected HTTP 204 No Content, got {response.status_code}: {response.text}"
    )
    assert response.text in ("", None), (
        f"Expected an empty body on 204, got {response.text!r}"
    )


def assert_hla_typing_object(typing: dict, label: str = "hla_typing"):
    assert isinstance(typing, dict), f"{label} must be an object"
    assert set(typing.keys()) == {"A", "B", "C", "DRB1", "DQB1"}, (
        f"{label} must carry exactly the five loci A, B, C, DRB1, DQB1, got "
        f"{sorted(typing.keys())}"
    )
    for locus, alleles in typing.items():
        assert isinstance(alleles, list) and len(alleles) == 2, (
            f"{label}.{locus} must hold exactly two strings, got {alleles!r}"
        )
        for allele in alleles:
            assert isinstance(allele, str) and allele, (
                f"{label}.{locus} entries must be non-empty strings"
            )


def assert_two_decimal_places(value, label: str):
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    quantised = round(float(value) + 1e-9, 2)
    assert abs(float(value) - quantised) < 1e-9, (
        f"{label} must carry at most two decimal places, got {value!r}"
    )


def assert_three_decimal_places(value, label: str):
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    quantised = round(float(value) + 1e-12, 3)
    assert abs(float(value) - quantised) < 1e-9, (
        f"{label} must carry at most three decimal places, got {value!r}"
    )


# ---------------------------------------------------------------------------
# per-entity assertions
# ---------------------------------------------------------------------------

def assert_registry(data: dict):
    assert_common_record_properties(data, "registry")
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 16
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert isinstance(data["currency_code"], str) and len(data["currency_code"]) == 3
    assert float(data["fx_rate_to_usd"]) > 0, "fx_rate_to_usd must be strictly positive"
    assert isinstance(data["is_domestic"], bool)
    assert data["cooperation_status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert 1 <= data["cooperation_tier"] <= 3
    assert 1 <= data["ct_response_deadline_hours"] <= 720
    assert isinstance(data["donor_count"], int) and data["donor_count"] >= 0


def assert_collection_center(data: dict):
    assert_common_record_properties(data, "collection_center")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert len(data["country_code"]) == 2
    assert 1 <= data["concurrent_collection_capacity"] <= 5
    assert isinstance(data["committed_slot_minutes"], int)
    assert data["committed_slot_minutes"] >= 0, (
        "committed_slot_minutes is a re-derivation over live bookings and can never go negative"
    )


def assert_patient(data: dict):
    assert_common_record_properties(data, "patient")
    assert isinstance(data["mrn"], str) and 1 <= len(data["mrn"]) <= 32
    assert isinstance(data["transplant_center_code"], str)
    assert len(data["country_code"]) == 2
    assert data["urgency_tier"] in ("STANDARD", "HIGH", "CRITICAL")
    assert float(data["weight_kg"]) > 0
    assert data["cmv_status"] in ("NEGATIVE", "POSITIVE")
    assert_hla_typing_object(data["hla_typing"], "patient.hla_typing")
    assert isinstance(data["case_budget_cents"], int) and data["case_budget_cents"] >= 0
    assert isinstance(data["coordinating_user_id"], str) and data["coordinating_user_id"]
    assert data["conditioning_status"] in (
        "NOT_SCHEDULED", "SCHEDULED", "STARTED", "INFUSED", "ABORTED",
    )
    assert isinstance(data["committed_cost_cents"], int)
    assert data["committed_cost_cents"] >= 0, (
        "committed_cost_cents re-derives over live claims and can never go negative"
    )


def assert_search_request(data: dict):
    assert_common_record_properties(data, "search_request")
    assert isinstance(data["patient_id"], str)
    assert data["search_scope"] in ("DOMESTIC_ONLY", "DOMESTIC_AND_INTERNATIONAL")
    assert 0.0 <= float(data["min_preliminary_score"]) <= 100.0
    assert data["status"] in (
        "SEARCHING", "NO_MATCH_FOUND", "PRIMARY_ENGAGED", "WORKUP_ACTIVE",
        "BACKUP_REQUIRED", "STALLED", "FULFILLED",
    )
    assert isinstance(data["match_pool_size"], int) and 0 <= data["match_pool_size"] <= 5
    assert isinstance(data["backup_candidate_count"], int)
    assert 0 <= data["backup_candidate_count"] <= 2, (
        "a search's backup bench only ever shrinks from its two slots"
    )


def assert_donor_profile(data: dict):
    assert_common_record_properties(data, "donor")
    assert isinstance(data["registry_id"], str)
    assert isinstance(data["donor_code"], str) and 1 <= len(data["donor_code"]) <= 24
    assert 17 <= data["age_years"] <= 75
    assert data["sex"] in ("M", "F")
    assert float(data["weight_kg"]) > 0
    assert data["cmv_status"] in ("NEGATIVE", "POSITIVE")
    assert_hla_typing_object(data["hla_typing_registry"], "donor.hla_typing_registry")
    assert isinstance(data["ambiguous_loci"], list)
    assert set(data["ambiguous_loci"]) <= {"A", "B", "C", "DRB1", "DQB1"}
    assert len(set(data["ambiguous_loci"])) == len(data["ambiguous_loci"])
    assert isinstance(data["consented_methods"], list) and data["consented_methods"]
    assert set(data["consented_methods"]) <= {"PBSC", "MARROW"}
    assert 0 <= data["prior_donation_count"] <= 5
    assert data["availability_status"] in (
        "AVAILABLE", "TEMPORARILY_DEFERRED", "PERMANENTLY_DEFERRED", "WITHDRAWN",
    )
    assert isinstance(data["blocked_day_count"], int) and data["blocked_day_count"] >= 0
    assert isinstance(data["adverse_event_count"], int) and data["adverse_event_count"] >= 0


def assert_match_candidate(data: dict):
    assert_common_record_properties(data, "match_candidate")
    assert isinstance(data["search_request_id"], str)
    assert isinstance(data["donor_id"], str)
    assert 0.00 <= float(data["preliminary_score"]) <= 100.00
    assert_two_decimal_places(data["preliminary_score"], "preliminary_score")
    assert 0.000 <= float(data["rank_score"]) <= 100.000
    assert_three_decimal_places(data["rank_score"], "rank_score")
    assert isinstance(data["rank_position"], int) and 1 <= data["rank_position"] <= 5
    assert data["candidate_role"] in ("PRIMARY", "BACKUP", "ARCHIVED_POOL")
    assert data["status"] in (
        "IDENTIFIED", "TYPING_REQUESTED", "TYPING_RESPONDED", "TYPING_EXPIRED",
        "SCREENING_PASSED", "DEFERRED", "EXCLUDED", "WORKUP_OPEN", "COLLECTED", "CLOSED",
    )
    assert 0 <= data["ct_attempt_count"] <= 2
    if data.get("confirmed_score") is not None:
        assert 0.00 <= float(data["confirmed_score"]) <= 100.00
        assert_two_decimal_places(data["confirmed_score"], "confirmed_score")


def assert_typing_request(data: dict):
    assert_common_record_properties(data, "typing_request")
    assert isinstance(data["match_candidate_id"], str)
    assert data["attempt_number"] in (1, 2)
    assert isinstance(data["priority_flag"], bool)
    assert is_iso8601_timestamp(data["requested_at"]), "requested_at must be ISO 8601"
    assert is_iso8601_timestamp(data["deadline_at"]), "deadline_at must be ISO 8601"
    assert data["status"] in ("REQUESTED", "RESPONDED", "EXPIRED", "CANCELLED")


def assert_workup_case(data: dict):
    assert_common_record_properties(data, "workup_case")
    assert isinstance(data["match_candidate_id"], str)
    assert data["case_status"] in ("OPEN", "ABORTED", "COMPLETED")
    assert data["clearance_status"] in ("PENDING", "IN_PROGRESS", "CLEARED", "FAILED")
    assert data["logistics_status"] in (
        "UNSCHEDULED", "METHOD_SET", "BOOKED", "COLLECTED", "IN_TRANSIT",
        "DELIVERED", "PRODUCT_LOST",
    )
    if data.get("collection_method") is not None:
        assert data["collection_method"] in ("PBSC", "MARROW")
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    assert data["planned_window_days"] in (6, 8)


def assert_clearance_item(data: dict):
    assert_common_record_properties(data, "clearance_item")
    assert isinstance(data["workup_case_id"], str)
    assert data["item_type"] in ("PHYSICAL_EXAM", "IDM_PANEL", "CONSENT")
    assert data["result"] in ("PENDING", "PASS", "FAIL")
    if data["result"] == "PENDING":
        assert data.get("resulted_at") is None, "resulted_at stays null while PENDING"
        assert data.get("resulted_by_user_id") is None
    else:
        assert is_iso8601_timestamp(data["resulted_at"])
        assert isinstance(data["resulted_by_user_id"], str)


def assert_collection_booking(data: dict):
    assert_common_record_properties(data, "collection_booking")
    assert isinstance(data["workup_case_id"], str)
    assert isinstance(data["collection_center_id"], str)
    assert data["method"] in ("PBSC", "MARROW")
    assert data["duration_minutes"] in (300, 240)
    assert isinstance(data["collection_date"], str) and len(data["collection_date"]) == 10
    assert data["status"] in ("HELD", "CONFIRMED", "COMPLETED", "CANCELLED", "SUPERSEDED")
    assert isinstance(data["cancelled_after_confirmation"], bool)


def assert_unavailability_window(data: dict):
    assert_common_record_properties(data, "unavailability_window")
    assert isinstance(data["donor_id"], str)
    assert len(data["date_from"]) == 10 and len(data["date_to"]) == 10
    assert data["date_from"] <= data["date_to"], "date_to must not precede date_from"
    assert data["reason"] in ("PERSONAL", "MEDICAL_HOLD", "DEFERRAL", "COLLECTION_WINDOW")
    assert isinstance(data["day_count"], int) and data["day_count"] >= 1
    assert data["status"] in ("ACTIVE", "RELEASED")
    if data["status"] == "ACTIVE":
        assert data.get("released_at") is None, "released_at stays null while ACTIVE"


def assert_product_shipment(data: dict):
    assert_common_record_properties(data, "product_shipment")
    assert isinstance(data["collection_booking_id"], str)
    assert is_iso8601_timestamp(data["collected_at"])
    assert float(data["collected_cd34_e6_per_kg"]) > 0
    assert float(data["collected_volume_ml"]) > 0
    assert isinstance(data["courier_reference"], str)
    assert 1 <= len(data["courier_reference"]) <= 40
    assert is_iso8601_timestamp(data["must_infuse_by"])
    assert data["dose_adequacy"] in ("ADEQUATE", "INADEQUATE")
    assert data["status"] in (
        "SCHEDULED", "IN_TRANSIT", "DELIVERED", "DISCARDED", "CANCELLED",
    )
    assert isinstance(data["transit_event_count"], int)
    assert data["transit_event_count"] >= 0


def assert_donor_follow_up(data: dict):
    """A follow-up row is an immutable audit record: id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), "follow_up.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "follow_up.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, (
        "a follow-up row has no updated_at field and it must not appear in the payload"
    )
    assert "version" not in data, (
        "a follow-up row has no version field and it must not appear in the payload"
    )
    assert data["event_type"] in (
        "DAY_7_CONTACT", "DAY_30_CONTACT", "ONE_YEAR_CONTACT", "ADVERSE_EVENT",
    )
    assert 0 <= data["severity_grade"] <= 5
    assert isinstance(data["triggered_permanent_deferral"], bool)
    assert is_iso8601_timestamp(data["reported_at"])


def assert_reimbursement_claim(data: dict):
    assert_common_record_properties(data, "reimbursement_claim")
    assert isinstance(data["workup_case_id"], str)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["billing_registry_id"], str)
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "VOID")
    assert data["variant_applied"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["currency_code"], str) and len(data["currency_code"]) == 3
    assert float(data["fx_rate_snapshot"]) > 0
    assert_claim_line_items(data)
    assert isinstance(data["subtotal_usd_cents"], int)
    assert data["volume_discount_pct"] in (0, 0.0, 0.05, 0.09)
    assert isinstance(data["discount_usd_cents"], int)
    assert isinstance(data["intl_coordination_fee_usd_cents"], int)
    assert isinstance(data["total_usd_cents"], int)
    assert isinstance(data["billed_amount_local_cents"], int)
    assert isinstance(data["cancellation_fee_applied"], bool)


def assert_claim_line_items(data: dict):
    """The seven claim lines appear in one pinned order, zero lines included."""
    lines = data["line_items"]
    assert isinstance(lines, list), "line_items must be an array"
    assert [line["line_type"] for line in lines] == CLAIM_LINE_ORDER, (
        f"line_items must carry all seven line types in the pinned order "
        f"{CLAIM_LINE_ORDER}, got {[line.get('line_type') for line in lines]}"
    )
    for line in lines:
        assert isinstance(line["amount_usd_cents"], int), (
            f"{line['line_type']}.amount_usd_cents must be a whole number of cents"
        )


def claim_line(data: dict, line_type: str) -> int:
    """The `amount_usd_cents` of one named claim line."""
    for line in data["line_items"]:
        if line["line_type"] == line_type:
            return line["amount_usd_cents"]
    raise AssertionError(f"claim carries no {line_type} line: {data['line_items']!r}")


def assert_claim_arithmetic(data: dict):
    """The claim's own internal arithmetic, as the PRD pins it."""
    subtotal = sum(line["amount_usd_cents"] for line in data["line_items"])
    assert data["subtotal_usd_cents"] == subtotal, (
        f"subtotal_usd_cents must be the exact integer sum of the seven lines "
        f"({subtotal}), got {data['subtotal_usd_cents']}"
    )
    expected_total = (
        data["subtotal_usd_cents"]
        - data["discount_usd_cents"]
        + data["intl_coordination_fee_usd_cents"]
    )
    assert data["total_usd_cents"] == expected_total, (
        f"total_usd_cents must be subtotal - discount + coordination fee "
        f"({expected_total}), got {data['total_usd_cents']}"
    )


def assert_same_instant(actual, expected: str, label: str):
    """Compare two instant-valued fields as instants, not as strings.

    PRD §2.4: "Instant-valued fields (`requested_at`, `deadline_at`,
    `responded_at`, `expired_by_sweep_at`, `resulted_at`, `expires_at`,
    `start_at`, `end_at`, `confirmed_at`, `collected_at`, `must_infuse_by`,
    `departed_at`, `delivered_at`, `released_at`, `reported_at`, `finalized_at`
    and `last_sweep_at`) are compared exactly, to the second."  The PRD pins
    the comparison semantics of these fields but never pins their rendering, so
    the assertion is made on the parsed instant.
    """
    from datetime import datetime

    def parse(value):
        assert isinstance(value, str), f"{label} must be an ISO 8601 instant, got {value!r}"
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    assert parse(actual) == parse(expected), (
        f"{label}: expected the instant {expected}, got {actual!r}"
    )


def assert_half_open_interval_minutes(start_at: str, end_at: str, duration_minutes: int):
    """`end_at` is `start_at` advanced by the method's duration."""
    from datetime import datetime, timedelta

    def parse(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    assert parse(end_at) - parse(start_at) == timedelta(minutes=duration_minutes), (
        f"end_at must be start_at advanced by {duration_minutes} minutes "
        f"({start_at} -> {end_at})"
    )
