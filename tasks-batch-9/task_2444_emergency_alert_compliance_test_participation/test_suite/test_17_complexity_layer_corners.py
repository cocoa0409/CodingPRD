"""Optimistic-concurrency corners: the two version guards of PRD §2.7.

`POST /monitoring-assignments` guards the station it widens, and `POST /filing-records`
guards the test event it files against, so a client working from a stale read is stopped
before it can either lose a source or blind-reverse a filing it never saw.
"""

import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    OFFICER,
    SOURCE_CALL_SIGNS,
    ApiErrorId,
    api_client,
    assert_score_and_posture,
    assert_version_incremented,
    create_active_plan,
    create_ready_device,
    filing_record_payload,
    monitoring_assignment_payload,
    register_station,
    set_clock,
    setup_logged_test_event,
    station_summary,
    station_version,
    test_event_version as read_test_event_version,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Layer: optimistic concurrency on POST /monitoring-assignments
# ---------------------------------------------------------------------------
def _two_source_station():
    """Plan requiring PEP and SATELLITE, with two READY devices and no assignments."""
    plan = create_active_plan(("PEP", "SATELLITE"))
    station = register_station(plan["id"])
    first_device = create_ready_device(station["id"])
    second_device = create_ready_device(station["id"], model_code="SAGE-3644")
    return {
        "plan_id": plan["id"],
        "station_id": station["id"],
        "first_device_id": first_device["id"],
        "second_device_id": second_device["id"],
    }


def test_stale_station_version_rejects_the_second_assignment_create():
    """PRD §2.7: "If that value does not equal the station's current `version`, the create is rejected with `ERR_STALE_STATION_VERSION` and HTTP 412."
    PRD §2.7: "A successful create increments the station's `version` by one, so a client that reads the station once and then creates two assignments must re-read between them."
    PRD §3.8: "`accessible_source_count` is the number of *distinct* `source_type` values among the station's monitoring assignments whose `status` is `ACTIVE` and whose `source_type` appears in the governing plan's `required_source_types`; two `ACTIVE` assignments covering the same required source type therefore count once, and assignments in `SILENT`, `SUSPENDED` or `DECOMMISSIONED` do not count at all."
    PRD §2.10: "The band mapping is: a score of 90.00 or greater yields `COMPLIANT`; a score of at least 75.00 but below 90.00 yields `WATCH`; anything below 75.00 yields `SUSPENDED_FILINGS`."
    PRD §3.3: "A successful create lands in `ACTIVE` with `last_receipt_at` and `silence_flagged_at` null, and sets `counts_toward_required_sources` to true exactly when the row's `status` is `ACTIVE` and its `source_type` appears in the governing plan's `required_source_types` — a row covering a source the plan does not require is stored and reported but never contributes coverage."

    Design: Corner/cross_cutting_complexity_layers/occ_rule_assignment_create_stale_station_rejects_then_accepts_a_refreshed_version
    """
    ctx = _two_source_station()
    observed_version = station_version(ctx["station_id"], ENGINEER)

    first = validate_success(
        api_client.create_monitoring_assignment(
            monitoring_assignment_payload(
                ctx["station_id"],
                ctx["first_device_id"],
                observed_version,
                source_type="PEP",
            ),
            ENGINEER,
        ),
        201,
    )
    assert first["status"] == "ACTIVE"
    assert first["counts_toward_required_sources"] is True

    summary = station_summary(ctx["station_id"])
    assert summary["accessible_source_count"] == 1
    assert summary["missing_source_count"] == 1
    assert_score_and_posture(summary, 75.00, "WATCH")

    version_after_first = station_version(ctx["station_id"], ENGINEER)
    assert_version_incremented(version_after_first, observed_version)

    # The client still holds its pre-create read of the station.
    stale = api_client.create_monitoring_assignment(
        monitoring_assignment_payload(
            ctx["station_id"],
            ctx["second_device_id"],
            observed_version,
            source_type="SATELLITE",
        ),
        ENGINEER,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_STATION_VERSION)

    assert station_version(ctx["station_id"], ENGINEER) == version_after_first, (
        "the 412 must leave the station's version exactly where the first create left it"
    )
    _, meta = validate_paginated(
        api_client.list_monitoring_assignments(
            ADMIN, params={"station_id": ctx["station_id"]}
        )
    )
    assert meta["total_count"] == 1, "the rejected create stored no assignment row"

    unchanged = station_summary(ctx["station_id"])
    assert unchanged["accessible_source_count"] == 1
    assert unchanged["missing_source_count"] == 1
    assert_score_and_posture(unchanged, 75.00, "WATCH")


def test_refreshed_station_version_admits_the_second_assignment_create():
    """PRD §2.7: "A successful create increments the station's `version` by one, so a client that reads the station once and then creates two assignments must re-read between them."
    PRD §2.7: "If that value does not equal the station's current `version`, the create is rejected with `ERR_STALE_STATION_VERSION` and HTTP 412."
    PRD §3.8: "Scoring starts from a base of 100.00 points and subtracts:"
    PRD §3.8: "25.00 points for every required source type the station is missing, where the missing count is the plan's `required_source_count` less the station's `accessible_source_count`, floored at zero so that over-coverage never earns a credit;"
    PRD §2.10: "The band mapping is: a score of 90.00 or greater yields `COMPLIANT`; a score of at least 75.00 but below 90.00 yields `WATCH`; anything below 75.00 yields `SUSPENDED_FILINGS`."
    PRD §3.3: "If the station already had an `ACTIVE` assignment for the same `source_type`, that older row is pushed `ACTIVE` → `DECOMMISSIONED` and the new row's `superseded_assignment_id` is set to the older row's `id`; when no such row existed, `superseded_assignment_id` stays null."

    Design: Corner/cross_cutting_complexity_layers/occ_rule_assignment_create_stale_station_rejects_then_accepts_a_refreshed_version
    """
    ctx = _two_source_station()
    observed_version = station_version(ctx["station_id"], ENGINEER)

    validate_success(
        api_client.create_monitoring_assignment(
            monitoring_assignment_payload(
                ctx["station_id"],
                ctx["first_device_id"],
                observed_version,
                source_type="PEP",
            ),
            ENGINEER,
        ),
        201,
    )
    validate_error(
        api_client.create_monitoring_assignment(
            monitoring_assignment_payload(
                ctx["station_id"],
                ctx["second_device_id"],
                observed_version,
                source_type="SATELLITE",
            ),
            ENGINEER,
        ),
        ApiErrorId.ERR_STALE_STATION_VERSION,
    )

    refreshed_version = station_version(ctx["station_id"], ENGINEER)
    second = validate_success(
        api_client.create_monitoring_assignment(
            monitoring_assignment_payload(
                ctx["station_id"],
                ctx["second_device_id"],
                refreshed_version,
                source_type="SATELLITE",
            ),
            ENGINEER,
        ),
        201,
    )
    assert second["status"] == "ACTIVE"
    assert second["source_type"] == "SATELLITE"
    assert second["source_call_sign"] == SOURCE_CALL_SIGNS["SATELLITE"]
    assert second["superseded_assignment_id"] is None

    _, meta = validate_paginated(
        api_client.list_monitoring_assignments(
            ADMIN, params={"station_id": ctx["station_id"]}
        )
    )
    assert meta["total_count"] == 2, "the retry with the refreshed version landed"

    summary = station_summary(ctx["station_id"])
    assert summary["accessible_source_count"] == 2
    assert summary["missing_source_count"] == 0
    assert_score_and_posture(summary, 100.00, "COMPLIANT")


# ---------------------------------------------------------------------------
# Layer: optimistic concurrency on POST /filing-records
# ---------------------------------------------------------------------------
def _first_filing():
    """A LOGGED test event filed once on time, ready for an amendment attempt."""
    ctx = setup_logged_test_event()
    set_clock("2026-08-12T00:40:00Z")
    ctx["observed_event_version"] = read_test_event_version(ctx["test_event_id"], OFFICER)
    ctx["first_filing"] = validate_success(
        api_client.create_filing_record(
            filing_record_payload(
                ctx["test_event_id"], ctx["observed_event_version"]
            ),
            OFFICER,
        ),
        201,
    )
    return ctx


def test_stale_test_event_version_blocks_the_blind_amendment():
    """PRD §2.7: "If that value does not equal the test event's current `version`, the filing is rejected with `ERR_STALE_TEST_EVENT_VERSION` and HTTP 412."
    PRD §2.7: "The guard exists because a second filing against an already-`FILED` event is a legitimate amendment that reverses the prior filing (§3.7): an officer working from a stale view of the event would reverse a filing whose penalty points they never saw."
    PRD §3.7: "A successful filing is stored in `SUBMITTED` with `reversal_reason` null, increments the event's `version` by one, and advances the event to `FILED`."

    Design: Corner/cross_cutting_complexity_layers/occ_rule_filing_create_stale_test_event_blocks_the_blind_amendment
    """
    ctx = _first_filing()
    first_filing = ctx["first_filing"]

    assert first_filing["status"] == "SUBMITTED"
    assert first_filing["late_days"] == 0
    assert first_filing["penalty_points"] == pytest.approx(0.00, abs=0.01)
    assert first_filing["superseded_filing_id"] is None
    assert first_filing["reversal_reason"] is None

    event = validate_success(
        api_client.get_test_event(ctx["test_event_id"], OFFICER)
    )
    assert event["status"] == "FILED"
    assert_version_incremented(event["version"], ctx["observed_event_version"])
    version_after_first = event["version"]

    # The amending officer still holds the pre-filing read of the event.
    stale = api_client.create_filing_record(
        filing_record_payload(
            ctx["test_event_id"],
            ctx["observed_event_version"],
            attestation_note="amended results",
        ),
        OFFICER,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_TEST_EVENT_VERSION)

    untouched = validate_success(
        api_client.get_filing_record(first_filing["id"], OFFICER)
    )
    assert untouched["status"] == "SUBMITTED", "the 412 reversed nothing"
    assert untouched["superseded_filing_id"] is None
    assert untouched["reversal_reason"] is None

    assert read_test_event_version(ctx["test_event_id"], OFFICER) == version_after_first, (
        "the 412 must leave the test event's version exactly where the first filing "
        "left it"
    )
    _, meta = validate_paginated(
        api_client.list_filing_records(
            ADMIN, params={"test_event_id": ctx["test_event_id"]}
        )
    )
    assert meta["total_count"] == 1, "the rejected amendment stored no filing row"


def test_refreshed_test_event_version_admits_the_amendment():
    """PRD §3.7: "An amendment reverses whichever earlier filing for the same event is still in `SUBMITTED` or `ACCEPTED`, moving that earlier row to `REVERSED` with its `reversal_reason` set to the literal string `SUPERSEDED_BY_AMENDMENT`, and sets the new filing's `superseded_filing_id` to the reversed row's `id`; a first filing on an event leaves `superseded_filing_id` null."
    PRD §2.7: "If that value does not equal the test event's current `version`, the filing is rejected with `ERR_STALE_TEST_EVENT_VERSION` and HTTP 412."
    PRD §3.7: "Filings can be listed filtered by `test_event_id`, `status` and `superseded_filing_id`."
    PRD §3.7: "Finally the station's ledger is resynchronised: `penalty_points_total` becomes the sum of `penalty_points` across all of that station's filing records whose `status` is `SUBMITTED` or `ACCEPTED`, rounded half-up to two decimal places."
    PRD §3.8: "When the station is not certified-eligible, `compliance_variant_applied` is `PROVISIONAL` and only the first four deductions are applied."

    Design: Corner/cross_cutting_complexity_layers/occ_rule_filing_create_stale_test_event_blocks_the_blind_amendment
    """
    ctx = _first_filing()
    first_filing = ctx["first_filing"]

    validate_error(
        api_client.create_filing_record(
            filing_record_payload(
                ctx["test_event_id"], ctx["observed_event_version"]
            ),
            OFFICER,
        ),
        ApiErrorId.ERR_STALE_TEST_EVENT_VERSION,
    )

    amendment = validate_success(
        api_client.create_filing_record(
            filing_record_payload(
                ctx["test_event_id"],
                read_test_event_version(ctx["test_event_id"], OFFICER),
                attestation_note="amended results",
            ),
            OFFICER,
        ),
        201,
    )
    assert amendment["status"] == "SUBMITTED"
    assert amendment["reversal_reason"] is None
    assert amendment["superseded_filing_id"] == first_filing["id"]
    assert amendment["penalty_points"] == pytest.approx(0.00, abs=0.01)

    reversed_row = validate_success(
        api_client.get_filing_record(first_filing["id"], OFFICER)
    )
    assert reversed_row["status"] == "REVERSED"
    assert reversed_row["reversal_reason"] == "SUPERSEDED_BY_AMENDMENT"

    rows, meta = validate_paginated(
        api_client.list_filing_records(
            ADMIN, params={"superseded_filing_id": first_filing["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [amendment["id"]]

    summary = station_summary(ctx["station_id"])
    assert summary["penalty_points_total"] == pytest.approx(0.00, abs=0.01)
    assert summary["compliance_variant_applied"] == "PROVISIONAL"
    assert_score_and_posture(summary, 100.00, "COMPLIANT")
