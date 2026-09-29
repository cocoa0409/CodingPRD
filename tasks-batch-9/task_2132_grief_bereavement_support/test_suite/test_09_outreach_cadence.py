"""The anniversary outreach cadence: the four-touchpoint plan, ripening,
silence and re-engagement."""

import pytest

from test_helpers import (
    IC,
    PD,
    ApiErrorId,
    UNUSED_UUIDS,
    api_client,
    assert_anniversary_outreach,
    create_assessment_payload,
    create_participant,
    read_assessments,
    read_outreach_plan,
    read_participant,
    record_assessment,
    run_cadence_sweep,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_participant,
)


def test_acceptance_lays_down_four_touchpoints_at_the_pinned_offsets():
    """PRD 3.8: "The cadence plan is laid down once, at the moment a referral is
    accepted, and it always consists of exactly four touchpoints created in a fixed
    order: `ONE_MONTH`, `THREE_MONTH`, `SIX_MONTH`, then `FIRST_ANNIVERSARY`. Each
    row records the `participant_id` it belongs to, the `occasion` it marks, and a
    `due_on` date computed as the participant's `date_of_death` advanced by that
    occasion's offset — thirty days for `ONE_MONTH`, ninety for `THREE_MONTH`, one
    hundred and eighty for `SIX_MONTH`, and a full year of three hundred and
    sixty-five days for `FIRST_ANNIVERSARY`. All four are created in status
    `SCHEDULED` with `escalated` false, `sent_at` and `acknowledged_at` null, and a
    `channel` of `PHONE` when the participant's `risk_tier` is `HIGH` and `EMAIL`
    otherwise."
    PRD 3.8: "A participant's touchpoints can be listed in occasion order and
    filtered by `status`."

    Design: Corner/calculations/outreach_cadence_plan_creates_four_touchpoints_at_pinned_offsets
    """
    set_clock()
    participant = create_participant(
        source_type="HOSPICE", source_org_name="Riverside Hospice",
        decedent_name="Ann Vance", date_of_death="2026-06-01",
        relationship_to_deceased="SPOUSE", loss_type="ANTICIPATED_ILLNESS",
        contact_name="Ben Vance", contact_email="ben.vance@example.org")
    assert participant["anniversary_month_day"] == "06-01"

    resp = api_client.list_anniversary_outreaches(participant["id"], IC)
    rows, meta = validate_paginated(resp)
    assert meta["total_count"] == 4, f"Expected 4 touchpoints, got {meta['total_count']}"
    assert len(rows) == 4

    expected = [("ONE_MONTH", "2026-07-01"), ("THREE_MONTH", "2026-08-30"),
                ("SIX_MONTH", "2026-11-28"), ("FIRST_ANNIVERSARY", "2027-06-01")]
    for row, (occasion, due_on) in zip(rows, expected):
        assert_anniversary_outreach(row)
        assert row["occasion"] == occasion
        assert row["due_on"] == due_on, (
            f"Expected {occasion} due on {due_on}, got {row['due_on']}")
        assert row["status"] == "SCHEDULED"
        assert row["channel"] == "EMAIL"
        assert row["escalated"] is False
        assert row["sent_at"] is None
        assert row["acknowledged_at"] is None


def test_sending_a_touchpoint_that_is_still_scheduled_is_refused():
    """PRD 3.8: "Sending a touchpoint is done by an `IntakeCoordinator` or by a
    `VolunteerCompanion` accompanying that participant, and it is permitted only
    from `DUE` — a send against a touchpoint in any other status is refused with
    `ERR_OUTREACH_NOT_DUE`."
    PRD 3.8: "A touchpoint in `SCHEDULED` whose `due_on` has been reached — that
    is, the logical clock date is on or after `due_on` — moves `SCHEDULED → DUE`,
    provided the participant's `outreach_status` is itself `SCHEDULED`."

    Design: Corner/state_machines/anniversary_outreach_send_before_it_is_due_returns_outreach_not_due
    """
    set_clock()
    participant = create_participant(
        source_type="HOSPICE", source_org_name="Riverside Hospice",
        decedent_name="Ann Vance", date_of_death="2026-06-01",
        relationship_to_deceased="SPOUSE", loss_type="ANTICIPATED_ILLNESS",
        contact_name="Ben Vance", contact_email="ben.vance@example.org")

    scheduled = read_outreach_plan(participant["id"], status="SCHEDULED")
    assert len(scheduled) == 4
    assert [row["occasion"] for row in scheduled] == [
        "ONE_MONTH", "THREE_MONTH", "SIX_MONTH", "FIRST_ANNIVERSARY"]
    first = scheduled[0]
    assert first["due_on"] == "2026-07-01"

    validate_error(api_client.send_outreach(first["id"], IC),
                   ApiErrorId.ERR_OUTREACH_NOT_DUE.value, 409)

    refreshed = read_outreach_plan(participant["id"])[0]
    assert refreshed["status"] == "SCHEDULED"
    assert refreshed["channel"] == "EMAIL"


def test_silence_for_twenty_one_days_lapses_the_participant_until_acknowledgement():
    """PRD 3.8: "When the logical clock reaches or passes twenty-one days after
    `sent_at`, the sweep moves the touchpoint `SENT → NO_RESPONSE` and, at the
    participant level, moves `outreach_status` `SCHEDULED → LAPSED` — the
    programme's signal that a family has gone quiet."
    PRD 3.8: "An `IntakeCoordinator` or an accompanying `VolunteerCompanion`
    records that the family responded, moving the touchpoint to `ACKNOWLEDGED` and
    stamping `acknowledged_at`. Acknowledgement is available from `SENT` and also
    from `NO_RESPONSE` — this second path is explicitly declared, so a lapsed family
    that resurfaces can be re-engaged rather than written off. Where the
    participant's `outreach_status` was `LAPSED`, acknowledgement moves it back
    `LAPSED → SCHEDULED`, closing the outreach cycle."

    Design: Corner/state_machines/ops_run_marks_sent_outreach_no_response_and_lapses_participant_outreach_status
    """
    set_clock("2026-08-15T00:00:00Z")
    participant = create_participant(
        source_type="HOSPICE", source_org_name="Riverside Hospice",
        decedent_name="Ann Vance", date_of_death="2026-06-01",
        relationship_to_deceased="SPOUSE", loss_type="ANTICIPATED_ILLNESS",
        contact_name="Ben Vance", contact_email="ben.vance@example.org")
    ripened = run_cadence_sweep()
    assert ripened["outreaches_due"] == 1

    set_clock("2026-09-01T00:00:00Z")
    due_rows = read_outreach_plan(participant["id"], status="DUE")
    assert len(due_rows) == 1
    sent = validate_success(api_client.send_outreach(due_rows[0]["id"], IC))
    assert sent["sent_at"] == "2026-09-01T00:00:00.000Z"

    set_clock("2026-09-21T00:00:00Z")
    early = run_cadence_sweep()
    assert early["outreaches_no_response"] == 0, "twenty days is not yet silence"

    set_clock("2026-09-22T00:00:00Z")
    late = run_cadence_sweep()
    assert late["outreaches_no_response"] == 1
    assert read_participant(participant["id"])["outreach_status"] == "LAPSED"

    acknowledged = validate_success(
        api_client.acknowledge_outreach(due_rows[0]["id"], IC))
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_at"] == "2026-09-22T00:00:00.000Z"

    refreshed = read_participant(participant["id"])
    assert refreshed["outreach_status"] == "SCHEDULED"
    assert refreshed["service_status"] == "INTAKE", (
        "acknowledgement must not move the clinical dimension")


def test_sending_an_unknown_touchpoint_is_not_found():
    """PRD 2.8: "Each entity has its own dedicated code — `ERR_REFERRAL_NOT_FOUND`,
    `ERR_PARTICIPANT_NOT_FOUND`, `ERR_SPACE_NOT_FOUND`, `ERR_COHORT_NOT_FOUND`,
    `ERR_ENROLLMENT_NOT_FOUND`, `ERR_COUNSELOR_NOT_FOUND`,
    `ERR_COUNSELING_REFERRAL_NOT_FOUND`, `ERR_COMPANION_NOT_FOUND`,
    `ERR_MATCH_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_INVITATION_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_REPORT_NOT_FOUND` and
    `ERR_OUTREACH_NOT_FOUND` — all reported at HTTP 404."

    Design: Corner/errors/anniversary_outreach_send_with_unknown_id_returns_outreach_not_found
    """
    set_clock()
    error = validate_error(
        api_client.send_outreach(UNUSED_UUIDS["outreach"], IC),
        ApiErrorId.ERR_OUTREACH_NOT_FOUND.value, 404)
    assert error["error_id"] != ApiErrorId.ERR_OUTREACH_NOT_DUE.value


def test_a_participant_scoped_write_after_withdrawal_is_refused():
    """PRD 3.8: "`WITHDRAWN` is terminal on the service dimension; any
    participant-scoped write attempted afterwards is refused with
    `ERR_PARTICIPANT_WITHDRAWN`."
    PRD 3.8: "And every anniversary touchpoint of theirs in `SCHEDULED`, `DUE` or
    `SENT` moves to `CANCELLED`."

    Design: Corner/errors/participant_scoped_write_after_withdrawal_returns_participant_withdrawn
    """
    set_clock()
    participant = create_participant(
        source_type="SELF", decedent_name="Elin Roos", date_of_death="2026-05-20",
        relationship_to_deceased="SPOUSE", loss_type="SUDDEN_DEATH",
        contact_name="Finn Roos", contact_email="finn.roos@example.org")
    record_assessment(participant["id"], kind="NEEDS", grief_severity=20,
                      isolation_index=8, functional_impairment=8)
    withdraw_participant(participant["id"])

    validate_error(
        api_client.create_assessment(
            participant["id"],
            create_assessment_payload(kind="BASELINE", grief_severity=20,
                                      isolation_index=8, functional_impairment=8),
            IC),
        ApiErrorId.ERR_PARTICIPANT_WITHDRAWN.value, 409)

    refreshed = read_participant(participant["id"])
    assert refreshed["service_status"] == "WITHDRAWN"
    assert refreshed["outreach_status"] == "CLOSED"
    assert refreshed["baseline_score"] is None
    assert len(read_assessments(participant["id"])) == 1
    plan = read_outreach_plan(participant["id"])
    assert len(plan) == 4
    for row in plan:
        assert row["status"] == "CANCELLED"
