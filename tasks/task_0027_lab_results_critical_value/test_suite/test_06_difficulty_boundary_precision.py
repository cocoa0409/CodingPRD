"""Difficulty Rule 6 — boundary_precision_check.

Numeric boundary on criticality_high (>= is inclusive). Empty-collection boundary
on GET /critical-notifications/{id}/acknowledgements when no receipts exist yet.
"""
from test_helpers import (
    api_client,
    bootstrap_actors,
    get_success_data,
    register_patient,
    setup_released_result,
    setup_sent_critical_notification,
    validate_paginated,
    validate_success,
)


class TestCriticalHighBoundaryIsInclusive:
    """PRD §2.4: "a reading equal to `critical_high` is classified as
    `CRITICAL_HIGH`."
    """

    def test_numeric_value_equal_to_critical_high_classifies_critical_high(self, api):
        """PRD §2.4: "a reading equal to `critical_high` is classified as
        `CRITICAL_HIGH`."

        Design: Difficulty/boundary_precision_check/criticality_high_threshold_inclusive_ge_on_release
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-B1B000", date_of_birth="1980-01-01",
        )
        # K=6.00 exactly == critical_high. Adult — no NEONATE override applies.
        bundle = setup_released_result(
            actors, patient,
            analyte_code="K", numeric_value=6.00, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        assert bundle["result"]["criticality"] == "CRITICAL_HIGH", (
            f"K=6.00 == critical_high MUST classify as CRITICAL_HIGH "
            f"(PRD §2.4 inclusive boundary); got {bundle['result']['criticality']!r}"
        )

    def test_numeric_value_strictly_above_critical_high_classifies_critical_high(self, api):
        """PRD §3.5: "a `numeric_value` at or above `critical_high` yields
        `CRITICAL_HIGH`"

        Design: Difficulty/boundary_precision_check/criticality_high_threshold_inclusive_ge_on_release
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-B1C000", date_of_birth="1980-01-01",
        )
        # K=6.01 strictly > critical_high.
        bundle = setup_released_result(
            actors, patient,
            analyte_code="K", numeric_value=6.01, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        assert bundle["result"]["criticality"] == "CRITICAL_HIGH", (
            f"K=6.01 > critical_high MUST classify as CRITICAL_HIGH; "
            f"got {bundle['result']['criticality']!r}"
        )

    def test_numeric_value_strictly_below_critical_high_is_abnormal_when_outside_reference(self, api):
        """PRD §3.5: "a `numeric_value` strictly below `reference_low` or strictly above
        `reference_high` (but still inside the critical band) yields `ABNORMAL`"

        Design: Difficulty/boundary_precision_check/criticality_high_threshold_inclusive_ge_on_release
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-B1A000", date_of_birth="1980-01-01",
        )
        # K=5.99 strictly < critical_high (6.00) and strictly > reference_high (5.10) → ABNORMAL.
        bundle = setup_released_result(
            actors, patient,
            analyte_code="K", numeric_value=5.99, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        assert bundle["result"]["criticality"] == "ABNORMAL", (
            f"K=5.99 (above reference_high but below critical_high) MUST classify as "
            f"ABNORMAL; got {bundle['result']['criticality']!r}"
        )


class TestAcknowledgementListingEmptyOnSentNotification:
    """PRD §4 + §2.3: list endpoints return a possibly-empty array of receipts.
    """

    def test_get_acknowledgements_for_sent_notification_returns_empty_array(self, api):
        """PRD §2.3: "Every list endpoint accepts two query parameters: `limit` and `offset`."
        PRD §2.3: "List responses always return items sorted by `created_at` ascending."
        PRD §2.3: "The `meta` block on list responses includes `limit`, `offset`, `total_count`, and `has_more` alongside the standard request metadata."

        Design: Difficulty/boundary_precision_check/ack_receipt_listing_empty_when_no_receipts_yet
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["TROP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-B20000", date_of_birth="1970-01-01",
        )
        bundle = setup_sent_critical_notification(actors, patient)
        notif = bundle["notification"]

        # No acknowledgement created yet. List should be empty.
        res = api_client.list_acknowledgements_for_notification(
            notif["id"], actors.lt_headers
        )
        data, meta = validate_paginated(res)
        assert data == [], (
            f"acknowledgement list MUST be an empty array when no receipts exist; "
            f"got {data!r}"
        )
        assert meta["total_count"] == 0, (
            f"total_count must be 0 when no receipts exist; got {meta['total_count']!r}"
        )

    def test_notification_state_unaffected_by_listing_acknowledgements(self, api):
        """PRD §4: GET endpoints are read-only and do not transition resources.
        PRD §2.4: Each entity carries a `version` that is "incremented by exactly 1
        on every successful mutation." A GET is not a mutation.

        Design: Difficulty/boundary_precision_check/ack_receipt_listing_empty_when_no_receipts_yet
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["TROP"])
        patient = register_patient(
            actors.lt_id, mrn="MRN-B2B000", date_of_birth="1970-01-01",
        )
        bundle = setup_sent_critical_notification(actors, patient)
        notif = bundle["notification"]

        # GET twice — neither should mutate the notification.
        api_client.list_acknowledgements_for_notification(notif["id"], actors.lt_headers)
        after = get_success_data(
            api_client.get_critical_notification(notif["id"], actors.lt_headers)
        )
        assert after["status"] == "SENT", (
            f"notification status must remain SENT after read-only listing; "
            f"got {after['status']!r}"
        )
        assert after["version"] == notif["version"], (
            f"version must not increment on a GET; "
            f"got {after['version']!r} expected {notif['version']!r}"
        )
