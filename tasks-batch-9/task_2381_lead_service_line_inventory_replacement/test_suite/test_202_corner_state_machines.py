"""Queue B - corner section ``state_machines``.

Declared initial states, every rejected transition, and the three declared
cycles: the appointment no-access loop, the sampling resample loop and the
water-system amendment loop.
"""

import pytest

from test_helpers import (
    ApiClient,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CONTRACTOR_HEADERS,
    CSR_HEADERS,
    OFFICER_HEADERS,
    make_field_technician_headers,
)
from test_helpers.types import (
    AppointmentState,
    BarrierReason,
    BatchState,
    CctOptimizationStatus,
    CertaintyBasis,
    Classification,
    ConsentBarrierReason,
    ConsentOutcome,
    ConsentState,
    CrewStatus,
    DeliveryChannel,
    EvidenceOrigin,
    FulfillmentState,
    InventoryState,
    InventoryStatus,
    Material,
    NotificationState,
    OrderScope,
    ProgramPosture,
    PublicationState,
    RejectionReason,
    ReplacementState,
    ReturnReason,
    SampleType,
    Side,
    SourceType,
    SupersedeReason,
    VerificationMethod,
)


def test_every_state_field_starts_in_its_declared_initial_state(api: ApiClient) -> None:
    """One creation call per state-bearing entity, each landing on its declared origin.

    PRD 3.1: "The system's `inventory_status` follows four states — `DRAFT`,
    `VALIDATION_PENDING`, `PUBLISHED` and `AMENDMENT_PENDING` — and none of them is
    terminal."
    PRD 3.2: "The classification axis, `inventory_state`, starts at `UNCLASSIFIED` and
    moves among `CLASSIFIED_PROVISIONAL` and `CLASSIFIED_VERIFIED`. The replacement
    axis, `replacement_state`, starts at `NOT_REQUIRED` and moves among `ELIGIBLE`,
    `IN_PROGRAM`, `REPLACED_PARTIAL` and `REPLACED_FULL`."
    PRD 3.3: "The appointment is created with `state` equal to `SCHEDULED` and
    `attempt_count` equal to 1, and the crew's `scheduled_appointment_count` is
    refreshed."
    PRD 3.4: "The batch opens with `state` equal to `OPEN`, `reopen_count` at 0,
    `rejection_reason` null, `valid_sample_count` at 0, `exceedance_count` at 0,
    `exceedance` false, and both `percentile_90_ppb` and `classification_confidence`
    null."

    Design: Corner/state_machines/every_state_field_starts_in_its_declared_initial_state
    """
    system = fixtures.create_water_system(api, "IL2101001", system_name="Initial Water")
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    crew = fixtures.create_crew(
        api,
        system["id"],
        crew_name="Crew A",
        shift_start_utc_time="08:00",
        shift_end_utc_time="18:00",
        daily_appointment_capacity=2,
        certified_methods=[VerificationMethod.VISUAL_INSPECTION, VerificationMethod.POTHOLE],
    )
    appointment = fixtures.book_appointment(
        api,
        line["id"],
        crew["id"],
        method=VerificationMethod.POTHOLE,
        window_start_utc="2026-08-05T09:00:00Z",
        window_end_utc="2026-08-05T10:00:00Z",
    )
    batch = fixtures.open_batch(api, system["id"], stratum_code="STR-A", stratum_line_count=20)

    assert system["inventory_status"] == InventoryStatus.DRAFT
    assert line["inventory_state"] == InventoryState.UNCLASSIFIED
    assert line["replacement_state"] == ReplacementState.NOT_REQUIRED
    assert crew["status"] == CrewStatus.ACTIVE
    assert fixtures.read_crew(api, crew["id"])["scheduled_appointment_count"] == 1
    assert appointment["state"] == AppointmentState.SCHEDULED
    assert appointment["attempt_count"] == 1
    assert appointment["emitted_evidence_item_id"] is None
    assert batch["state"] == BatchState.OPEN
    assert batch["reopen_count"] == 0
    assert batch["required_sample_count"] == 5
    assert batch["valid_sample_count"] == 0
    assert batch["rejection_reason"] is None
    assert batch["percentile_90_ppb"] is None
    assert batch["classification_confidence"] is None
    assert batch["exceedance"] is False
    assert batch["exceedance_count"] == 0


def test_arriving_twice_on_the_same_appointment_is_rejected(api: ApiClient) -> None:
    """The second arrive is a conflict, not a silent no-op, and burns no attempt.

    PRD 3.3: "A `FieldTechnician` whose `X-User-ID` matches the appointment's
    `crew_id` moves it from `SCHEDULED` to `ON_SITE` on arrival, which additionally
    requires the assigned crew's `status` to be `ACTIVE`; arriving with an inactive
    crew is refused with `ERR_CREW_INACTIVE`."
    PRD 2.10: "**Declared-transition state checks.** The target row is in the `from:`
    state the requested transition declares, else the entity's own conflict code at
    HTTP 409: `ERR_INVENTORY_STATE_INVALID` for a water-system inventory advance,
    `ERR_APPOINTMENT_STATE_INVALID` for appointment arrival, completion, barrier
    reporting and re-booking"

    Design: Corner/state_machines/arriving_twice_on_the_same_appointment_is_rejected
    """
    scenario = fixtures.bare_system_with_crew(
        api,
        "IL2101002",
        crew_name="Crew A",
        certified_methods=[VerificationMethod.VISUAL_INSPECTION, VerificationMethod.POTHOLE],
        daily_appointment_capacity=1,
    )
    appointment = fixtures.book_appointment(
        api, scenario["service_line_id"], scenario["crew_id"], method=VerificationMethod.POTHOLE
    )
    fixtures.arrive(api, appointment["id"], scenario["crew_id"])

    response = api.arrive_appointment(
        appointment["id"], make_field_technician_headers(scenario["crew_id"])
    )

    validate_error(response, "ERR_APPOINTMENT_STATE_INVALID", 409)
    unchanged = fixtures.read_appointment(api, appointment["id"])
    assert unchanged["state"] == AppointmentState.ON_SITE
    assert unchanged["attempt_count"] == 1


def test_completing_a_scheduled_appointment_before_arrival_is_rejected(
    api: ApiClient,
) -> None:
    """Completion is declared only from ON_SITE, so no cascade fires from SCHEDULED.

    PRD 3.3: "From `ON_SITE` the visit resolves one of two ways. **Completion** is
    the productive outcome: the technician records the `observed_side` — `UTILITY` or
    `CUSTOMER` — and the `observed_material` found, and the appointment moves to
    `COMPLETED`."
    PRD 3.3: "the new item's identifier is stored back onto the appointment as
    `emitted_evidence_item_id`, which is null until completion."

    Design: Corner/state_machines/completing_a_scheduled_appointment_before_arrival_is_rejected
    """
    scenario = fixtures.bare_system_with_crew(
        api,
        "IL2101003",
        crew_name="Crew A",
        certified_methods=[VerificationMethod.VISUAL_INSPECTION, VerificationMethod.POTHOLE],
        daily_appointment_capacity=1,
    )
    appointment = fixtures.book_appointment(
        api, scenario["service_line_id"], scenario["crew_id"], method=VerificationMethod.POTHOLE
    )

    response = api.complete_appointment(
        appointment["id"],
        factories.appointment_complete_payload(Side.UTILITY, Material.LEAD),
        make_field_technician_headers(scenario["crew_id"]),
    )

    validate_error(response, "ERR_APPOINTMENT_STATE_INVALID", 409)
    unchanged = fixtures.read_appointment(api, appointment["id"])
    assert unchanged["state"] == AppointmentState.SCHEDULED
    assert unchanged["emitted_evidence_item_id"] is None
    assert (
        fixtures.read_service_line(api, scenario["service_line_id"])["inventory_state"]
        == InventoryState.UNCLASSIFIED
    )


def test_no_access_then_reschedule_cycles_the_appointment_and_increments_attempt_count(
    api: ApiClient,
) -> None:
    """SCHEDULED to ON_SITE to NO_ACCESS to SCHEDULED with attempt_count now 2.

    PRD 3.3: "When the appointment's `attempt_count` is fewer than 3, the appointment
    is parked: it moves from `ON_SITE` to `NO_ACCESS`, the supplied reason is stored
    as `barrier_reason`, the crew's `scheduled_appointment_count` is refreshed, and
    `version` advances by one."
    PRD 3.3: "A `ProgramAdministrator` re-books a `NO_ACCESS` appointment into a new
    `window_start_utc` and `window_end_utc`, which returns it to `SCHEDULED`, writes
    the new window onto the row, increases `attempt_count` by 1, refreshes the crew's
    `scheduled_appointment_count`, and advances `version` by one."

    Design: Corner/state_machines/no_access_then_reschedule_cycles_the_appointment_and_increments_attempt_count
    """
    scenario = fixtures.bare_system_with_crew(
        api,
        "IL2101004",
        crew_name="Crew A",
        certified_methods=[VerificationMethod.VISUAL_INSPECTION, VerificationMethod.POTHOLE],
        daily_appointment_capacity=1,
    )
    appointment = fixtures.book_appointment(
        api, scenario["service_line_id"], scenario["crew_id"], method=VerificationMethod.POTHOLE
    )
    fixtures.arrive(api, appointment["id"], scenario["crew_id"])
    parked = fixtures.report_no_access(
        api, appointment["id"], scenario["crew_id"], BarrierReason.LOCKED_PREMISE
    )
    assert parked["state"] == AppointmentState.NO_ACCESS

    rebooked = fixtures.reschedule_appointment(
        api, appointment["id"], "2026-08-06T09:00:00Z", "2026-08-06T10:00:00Z"
    )

    assert rebooked["state"] == AppointmentState.SCHEDULED
    assert rebooked["attempt_count"] == 2
    assert rebooked["window_start_utc"].startswith("2026-08-06T09:00:00")
    assert rebooked["window_end_utc"].startswith("2026-08-06T10:00:00")
    assert rebooked["barrier_reason"] == BarrierReason.LOCKED_PREMISE
    assert fixtures.read_crew(api, scenario["crew_id"])["scheduled_appointment_count"] == 1


def test_third_exhausted_attempt_abandons_the_appointment_and_locks_it_down(
    api: ApiClient,
) -> None:
    """The barrier taken at attempt 3 terminates rather than parks, and closes the row.

    PRD 3.3: "When `attempt_count` has already reached 3, the same request instead
    terminates the appointment: it moves from `ON_SITE` to `ABANDONED`, and the
    supplied reason is stored as `barrier_reason`, the crew's
    `scheduled_appointment_count` is refreshed, and `version` advances by one exactly
    as in the parked case. The third exhausted attempt ends the pursuit rather than
    parking it again."
    PRD 3.3: "An appointment's lifecycle spans five states — `SCHEDULED`, `ON_SITE`,
    `COMPLETED`, `NO_ACCESS` and `ABANDONED` — of which `COMPLETED` and `ABANDONED`
    are terminal."
    PRD 3.3: "The crew also carries a derived `scheduled_appointment_count`, starting
    at 0, counting the appointments booked to it whose `state` is `SCHEDULED` or
    `ON_SITE`."

    Design: Corner/state_machines/third_exhausted_attempt_abandons_the_appointment_and_locks_it_down
    """
    scenario = fixtures.bare_system_with_crew(
        api,
        "IL2101005",
        crew_name="Crew A",
        certified_methods=[VerificationMethod.VISUAL_INSPECTION, VerificationMethod.POTHOLE],
        daily_appointment_capacity=1,
    )
    crew_id = scenario["crew_id"]
    appointment = fixtures.book_appointment(
        api, scenario["service_line_id"], crew_id, method=VerificationMethod.POTHOLE
    )
    appointment_id = appointment["id"]
    fixtures.arrive(api, appointment_id, crew_id)
    fixtures.report_no_access(api, appointment_id, crew_id, BarrierReason.LOCKED_PREMISE)
    fixtures.reschedule_appointment(
        api, appointment_id, "2026-08-06T09:00:00Z", "2026-08-06T10:00:00Z"
    )
    fixtures.arrive(api, appointment_id, crew_id)
    fixtures.report_no_access(api, appointment_id, crew_id, BarrierReason.OCCUPANT_REFUSED)
    third = fixtures.reschedule_appointment(
        api, appointment_id, "2026-08-07T09:00:00Z", "2026-08-07T10:00:00Z"
    )
    assert third["attempt_count"] == 3
    fixtures.arrive(api, appointment_id, crew_id)

    abandoned = fixtures.report_no_access(api, appointment_id, crew_id, BarrierReason.WEATHER)

    assert abandoned["state"] == AppointmentState.ABANDONED
    assert abandoned["attempt_count"] == 3
    assert abandoned["barrier_reason"] == BarrierReason.WEATHER
    assert fixtures.read_crew(api, crew_id)["scheduled_appointment_count"] == 0

    response = api.arrive_appointment(appointment_id, make_field_technician_headers(crew_id))
    validate_error(response, "ERR_APPOINTMENT_STATE_INVALID", 409)
    assert (
        fixtures.read_appointment(api, appointment_id)["state"] == AppointmentState.ABANDONED
    )


def test_rejected_batch_reopen_clears_every_persisted_statistic(api: ApiClient) -> None:
    """A 0.6000 confidence rejects with no corrosion effect, and reopen nulls the stats.

    PRD 3.4: "When `classification_confidence` is below 0.8000, the batch moves from
    `OPEN` to `REJECTED` instead, and `rejection_reason` is set to
    `CONFIDENCE_BELOW_FLOOR`. The rejected branch carries **no** corrosion-control
    side effect whatsoever"
    PRD 3.4: "`exceedance_count` is the number of valid samples whose own `lead_ppb`
    is strictly greater than 15.0. And `classification_confidence` is one minus the
    exceedance count divided by the valid-sample count, rounded half-up to four
    decimal places."
    PRD 3.4: "A `ComplianceOfficer` supplies a `reason`, the batch returns from
    `REJECTED` to `OPEN`, `reopen_count` increases by 1, and `percentile_90_ppb`,
    `classification_confidence` and `rejection_reason` are all cleared back to null
    while `exceedance` returns to false."

    Design: Corner/state_machines/rejected_batch_reopen_clears_every_persisted_statistic
    """
    system = fixtures.create_water_system(api, "IL2101006", system_name="Reject Water")
    line = fixtures.make_lead_line(api, system["id"], address_label="101 Elm St")
    batch = fixtures.open_batch(api, system["id"], stratum_code="STR-A", stratum_line_count=20)
    fixtures.append_samples(api, batch["id"], line["id"], readings=(1.0, 2.0, 3.0, 20.0, 30.0))

    rejected = fixtures.validate_batch(api, batch["id"])

    assert rejected["state"] == BatchState.REJECTED
    assert rejected["percentile_90_ppb"] == pytest.approx(30.0)
    assert rejected["exceedance"] is True
    assert rejected["exceedance_count"] == 2
    assert rejected["classification_confidence"] == pytest.approx(0.6000)
    assert rejected["rejection_reason"] == RejectionReason.CONFIDENCE_BELOW_FLOOR
    assert (
        fixtures.read_water_system(api, system["id"])["cct_optimization_status"]
        == CctOptimizationStatus.NOT_REQUIRED
    )

    reopened = fixtures.reopen_batch(api, batch["id"], "RESAMPLE_ROUND_2")

    assert reopened["state"] == BatchState.OPEN
    assert reopened["reopen_count"] == 1
    assert reopened["percentile_90_ppb"] is None
    assert reopened["classification_confidence"] is None
    assert reopened["rejection_reason"] is None
    assert reopened["exceedance"] is False
    assert reopened["exceedance_count"] == 0
    assert reopened["valid_sample_count"] == 5


def test_appending_a_sample_to_a_validated_batch_is_rejected(api: ApiClient) -> None:
    """The append endpoint is declared only from OPEN, so a validated batch refuses it.

    PRD 3.4: "Samples are appended one at a time, by either a `FieldTechnician` or a
    `ComplianceOfficer`, to a batch that is still `OPEN`."
    PRD 3.4: "Appending or invalidating a sample is only legal while the batch is
    `OPEN`, validation only from `OPEN`, and reopening only from `REJECTED`; anything
    else is `ERR_BATCH_STATE_INVALID`."

    Design: Corner/state_machines/appending_a_sample_to_a_validated_batch_is_rejected
    """
    system = fixtures.create_water_system(api, "IL2101007", system_name="Closed Batch Water")
    line = fixtures.make_lead_line(api, system["id"], address_label="101 Elm St")
    validated = fixtures.open_and_validate_batch(api, system["id"], line["id"])
    assert validated["state"] == BatchState.VALIDATED

    response = api.append_sample(
        validated["id"],
        factories.sample_payload(
            line["id"], 6.0, "2026-07-16T09:00:00Z", sample_type=SampleType.FIRST_DRAW
        ),
        OFFICER_HEADERS,
    )

    validate_error(response, "ERR_BATCH_STATE_INVALID", 409)
    unchanged = fixtures.read_batch(api, validated["id"])
    assert unchanged["state"] == BatchState.VALIDATED
    assert unchanged["valid_sample_count"] == 5


def test_notification_deliver_return_deliver_cycle_restores_the_outstanding_counter(
    api: ApiClient,
) -> None:
    """The counter walks 1 to 0 to 1 to 0 and the posture follows it exactly.

    PRD 3.5: "A `CustomerRepresentative` records a successful delivery by supplying a
    `delivery_channel` — `MAIL`, `EMAIL` or `DOOR_HANGER` — and a `delivered_at`
    instant; the notification moves to `DELIVERED`, `delivery_attempt_count`
    increases by 1, `return_reason` is cleared back to null, the water system's
    `outstanding_notification_count` is refreshed and its `program_posture`
    recomputed"
    PRD 3.5: "A return takes a `return_reason` drawn from `ADDRESS_INVALID`, `REFUSED`
    and `VACANT`, moves the row from `DELIVERED` to `RETURNED`, stores that reason,
    clears `delivered_at` back to null, refreshes the water system's
    `outstanding_notification_count` — the row re-enters the outstanding set — and
    recomputes `program_posture`, which lands back on `RESTRICTED`"
    PRD 3.5: "A returned notification can be delivered again, which closes the
    redelivery cycle `PENDING → DELIVERED → RETURNED → DELIVERED`, increases
    `delivery_attempt_count` again, and clears `return_reason` back to null."

    Design: Corner/state_machines/notification_deliver_return_deliver_cycle_restores_the_outstanding_counter
    """
    scenario = fixtures.published_system_with_lead_line(api, "IL2101008", system_name="Redeliver Water")
    notification = fixtures.notification_for_line(api, scenario["service_line_id"])

    assert notification["state"] == NotificationState.PENDING
    assert notification["notified_classification"] == Classification.LEAD
    assert notification["due_at"].startswith("2026-08-31T00:00:00")
    before = fixtures.read_water_system(api, scenario["water_system_id"])
    assert before["outstanding_notification_count"] == 1
    assert before["program_posture"] == ProgramPosture.RESTRICTED

    first = fixtures.deliver_notification(
        api,
        notification["id"],
        delivered_at="2026-08-02T10:00:00Z",
        delivery_channel=DeliveryChannel.MAIL,
    )
    assert first["state"] == NotificationState.DELIVERED
    assert first["delivery_attempt_count"] == 1
    assert first["delivered_at"].startswith("2026-08-02T10:00:00")
    after_first = fixtures.read_water_system(api, scenario["water_system_id"])
    assert after_first["outstanding_notification_count"] == 0
    assert after_first["program_posture"] == ProgramPosture.OPEN

    returned = fixtures.return_notification(
        api, notification["id"], ReturnReason.ADDRESS_INVALID
    )
    assert returned["state"] == NotificationState.RETURNED
    assert returned["return_reason"] == ReturnReason.ADDRESS_INVALID
    assert returned["delivered_at"] is None
    after_return = fixtures.read_water_system(api, scenario["water_system_id"])
    assert after_return["outstanding_notification_count"] == 1
    assert after_return["program_posture"] == ProgramPosture.RESTRICTED

    second = fixtures.deliver_notification(
        api,
        notification["id"],
        delivered_at="2026-08-03T10:00:00Z",
        delivery_channel=DeliveryChannel.MAIL,
    )
    assert second["state"] == NotificationState.DELIVERED
    assert second["delivery_attempt_count"] == 2
    assert second["delivered_at"].startswith("2026-08-03T10:00:00")
    assert second["return_reason"] is None
    after_second = fixtures.read_water_system(api, scenario["water_system_id"])
    assert after_second["outstanding_notification_count"] == 0
    assert after_second["program_posture"] == ProgramPosture.OPEN


def test_acknowledging_a_pending_notification_is_rejected(api: ApiClient) -> None:
    """Acknowledgement is declared only from DELIVERED, never from the fanned-out row.

    PRD 3.5: "Acknowledgement takes an `acknowledged_at` instant, moves the row to
    the terminal `ACKNOWLEDGED`, stores that instant, and advances `version` by one."
    PRD 2.10: "`ERR_NOTIFICATION_STATE_INVALID` for delivering, acknowledging and
    returning a notification"

    Design: Corner/state_machines/acknowledging_a_pending_notification_is_rejected
    """
    scenario = fixtures.published_system_with_lead_line(api, "IL2101009", system_name="Ack Water")
    notification = fixtures.notification_for_line(api, scenario["service_line_id"])
    assert notification["state"] == NotificationState.PENDING

    response = api.acknowledge_notification(
        notification["id"],
        factories.acknowledge_notification_payload("2026-08-02T10:00:00Z"),
        CSR_HEADERS,
    )

    validate_error(response, "ERR_NOTIFICATION_STATE_INVALID", 409)
    unchanged = fixtures.read_notification(api, notification["id"])
    assert unchanged["state"] == NotificationState.PENDING
    assert unchanged["acknowledged_at"] is None
    assert (
        fixtures.read_water_system(api, scenario["water_system_id"])[
            "outstanding_notification_count"
        ]
        == 1
    )


def test_publishing_a_draft_publication_before_certification_is_rejected(
    api: ApiClient,
) -> None:
    """Publish is declared only from CERTIFIED, so the fan-out never runs on a DRAFT.

    PRD 3.5: "A publication's `state` walks `DRAFT`, `CERTIFIED`, `PUBLISHED` and the
    terminal `SUPERSEDED`; a request against a publication that is not in the
    declared origin state yields `ERR_PUBLICATION_STATE_INVALID`."
    PRD 3.5: "Publishing is the officer's second act, and it re-validates the pin
    before it fans anything out. The publication must be `CERTIFIED`, and its
    `notifiable_line_count` must still equal the current number of service lines of
    that water system whose `classification` is `LEAD`, `GRR` or `UNKNOWN`"

    Design: Corner/state_machines/publishing_a_draft_publication_before_certification_is_rejected
    """
    system = fixtures.create_water_system(api, "IL2101010", system_name="Draft Publish Water")
    line = fixtures.make_lead_line(api, system["id"], address_label="101 Elm St")
    fixtures.open_and_validate_batch(api, system["id"], line["id"])
    advanced = fixtures.advance_to_validation_pending(api, system["id"])
    publication = fixtures.draft_publication(api, system["id"], advanced["version"])
    assert publication["state"] == PublicationState.DRAFT

    response = api.publish_publication(publication["id"], OFFICER_HEADERS)

    validate_error(response, "ERR_PUBLICATION_STATE_INVALID", 409)
    unchanged = fixtures.read_publication(api, publication["id"])
    assert unchanged["state"] == PublicationState.DRAFT
    assert unchanged["published_at"] is None
    assert unchanged["notifiable_line_count"] is None
    system_after = fixtures.read_water_system(api, system["id"])
    assert system_after["inventory_status"] == InventoryStatus.VALIDATION_PENDING
    assert system_after["outstanding_notification_count"] == 0


def test_amendment_then_second_publication_supersedes_the_first(api: ApiClient) -> None:
    """The retraction drives the amendment edge and pub2 supersedes pub1 without cancelling it.

    PRD 3.2: "If the retraction removes the last non-retracted `VISUAL_INSPECTION` or
    `POTHOLE` item on either side, so that the both-sides condition no longer holds,
    the server immediately moves the line from `CLASSIFIED_VERIFIED` back to
    `CLASSIFIED_PROVISIONAL`"
    PRD 3.1: "That last pair forms the amendment cycle — a published inventory drops
    back to `AMENDMENT_PENDING` when a classification changes underneath it, and
    returns to `PUBLISHED` only when a newer publication publishes."
    PRD 3.5: "When a publication of a water system reaches `PUBLISHED`, any other
    publication of the same water system that was in `PUBLISHED` moves to
    `SUPERSEDED` with `supersede_reason` set to `AMENDED_BY_NEWER_PUBLICATION`, and
    that superseded row's `version` advances by one."
    PRD 3.5: "Superseding is deliberately not destructive downstream: the customer
    notifications created by the superseded publication keep their own `state` and
    are **not** cancelled."

    Design: Corner/state_machines/amendment_then_second_publication_supersedes_the_first
    """
    system = fixtures.create_water_system(api, "IL2101011", system_name="Amend Water")
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    record = fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.HISTORIC_RECORD,
        side=Side.UTILITY,
        observed_material=Material.LEAD,
        observed_at="2026-06-01T00:00:00Z",
    )
    first_publication = fixtures.publish_inventory(api, system["id"], line["id"])
    assert first_publication["state"] == PublicationState.PUBLISHED

    fixtures.retract_evidence(api, record["id"], "RECORD_SUPERSEDED_BY_AUDIT")

    amended_line = fixtures.read_service_line(api, line["id"])
    assert amended_line["classification"] == Classification.UNKNOWN
    assert amended_line["certainty_score"] == pytest.approx(0.00)
    amended_system = fixtures.read_water_system(api, system["id"])
    assert amended_system["lead_count"] == 0
    assert amended_system["unknown_count"] == 1
    assert amended_system["inventory_status"] == InventoryStatus.AMENDMENT_PENDING
    assert amended_system["program_posture"] == ProgramPosture.RESTRICTED

    second = fixtures.draft_publication(
        api,
        system["id"],
        amended_system["version"],
        reporting_period_label="2026-H2-AMD",
    )
    fixtures.certify_publication(api, second["id"])
    published_second = fixtures.publish_publication(api, second["id"])

    assert published_second["state"] == PublicationState.PUBLISHED
    assert published_second["notifiable_line_count"] == 1
    superseded = fixtures.read_publication(api, first_publication["id"])
    assert superseded["state"] == PublicationState.SUPERSEDED
    assert superseded["supersede_reason"] == SupersedeReason.AMENDED_BY_NEWER_PUBLICATION
    final_system = fixtures.read_water_system(api, system["id"])
    assert final_system["inventory_status"] == InventoryStatus.PUBLISHED
    assert final_system["outstanding_notification_count"] == 2
    assert final_system["program_posture"] == ProgramPosture.RESTRICTED


def test_advancing_a_published_system_back_to_validation_pending_is_rejected(
    api: ApiClient,
) -> None:
    """The only declared advance edge leaves DRAFT, so a PUBLISHED system cannot rewind.

    PRD 3.1: "A `ComplianceOfficer` walks it out of `DRAFT` by supplying a
    `target_status` of `VALIDATION_PENDING`. That advance is permitted only when the
    system is currently in `DRAFT`, when it has at least one service line, and when
    no service line of the system is still sitting at `UNCLASSIFIED` on its
    classification axis; a request that does not describe a declared transition out
    of the current status is refused with `ERR_INVENTORY_STATE_INVALID`."

    Design: Corner/state_machines/advancing_a_published_system_back_to_validation_pending_is_rejected
    """
    scenario = fixtures.published_system_with_lead_line(api, "IL2101012", system_name="Rewind Water")

    response = api.advance_inventory_status(
        scenario["water_system_id"],
        factories.advance_inventory_status_payload(InventoryStatus.VALIDATION_PENDING),
        OFFICER_HEADERS,
    )

    validate_error(response, "ERR_INVENTORY_STATE_INVALID", 409)
    assert (
        fixtures.read_water_system(api, scenario["water_system_id"])["inventory_status"]
        == InventoryStatus.PUBLISHED
    )


def test_advance_inventory_status_requires_at_least_one_fully_classified_line(
    api: ApiClient,
) -> None:
    """An empty system and an unclassified system are each refused independently.

    PRD 3.1: "That advance is permitted only when the system is currently in `DRAFT`,
    when it has at least one service line, and when no service line of the system is
    still sitting at `UNCLASSIFIED` on its classification axis"
    PRD 3.1: "A freshly registered system starts with `inventory_status` at `DRAFT`,
    and because clause 1 of the posture rule fires on `DRAFT`, its `program_posture`
    is `FROZEN` from the very first moment."

    Design: Corner/state_machines/advance_inventory_status_requires_at_least_one_fully_classified_line
    """
    empty = fixtures.create_water_system(api, "IL2101013", system_name="Empty Water")
    raw = fixtures.create_water_system(api, "IL2101014", system_name="Raw Water")
    line = fixtures.create_service_line(api, raw["id"], address_label="101 Elm St")

    empty_response = api.advance_inventory_status(
        empty["id"],
        factories.advance_inventory_status_payload(InventoryStatus.VALIDATION_PENDING),
        OFFICER_HEADERS,
    )
    raw_response = api.advance_inventory_status(
        raw["id"],
        factories.advance_inventory_status_payload(InventoryStatus.VALIDATION_PENDING),
        OFFICER_HEADERS,
    )

    validate_error(empty_response, "ERR_INVENTORY_STATE_INVALID", 409)
    validate_error(raw_response, "ERR_INVENTORY_STATE_INVALID", 409)

    empty_after = fixtures.read_water_system(api, empty["id"])
    assert empty_after["inventory_status"] == InventoryStatus.DRAFT
    assert empty_after["program_posture"] == ProgramPosture.FROZEN
    raw_after = fixtures.read_water_system(api, raw["id"])
    assert raw_after["inventory_status"] == InventoryStatus.DRAFT
    assert raw_after["program_posture"] == ProgramPosture.FROZEN
    assert (
        fixtures.read_service_line(api, line["id"])["inventory_state"]
        == InventoryState.UNCLASSIFIED
    )


def test_starting_a_draft_replacement_order_is_rejected(api: ApiClient) -> None:
    """Breaking ground is declared only from SCHEDULED, so a DRAFT order refuses it.

    PRD 3.7: "Breaking ground moves the order from `SCHEDULED` to `IN_PROGRESS`,
    refreshes `active_excavation_order_count` again, and advances `version` by one."
    PRD 2.10: "`ERR_ORDER_STATE_INVALID` for consent request, consent response,
    funding plan, schedule, start, complete and cancel — the last of which checks the
    relevant axis's declared `from:` state on each of the order's two independent
    axes."

    Design: Corner/state_machines/starting_a_draft_replacement_order_is_rejected
    """
    scenario = fixtures.published_system_with_lead_line(api, "IL2101015", system_name="Start Water")
    order = fixtures.open_order(
        api,
        scenario["service_line_id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-11",
    )

    response = api.start_order(order["id"], CONTRACTOR_HEADERS)

    validate_error(response, "ERR_ORDER_STATE_INVALID", 409)
    unchanged = fixtures.read_order(api, order["id"])
    assert unchanged["fulfillment_state"] == FulfillmentState.DRAFT
    assert unchanged["consent_state"] == ConsentState.NOT_REQUESTED
    assert unchanged["scope"] is None
    assert (
        fixtures.read_service_line(api, scenario["service_line_id"])["replacement_state"]
        == ReplacementState.IN_PROGRAM
    )


def test_opening_a_replacement_order_against_a_non_lead_line_is_rejected(
    api: ApiClient,
) -> None:
    """A copper-verified line sits at NOT_REQUIRED, and eligibility outranks publication.

    PRD 3.2: "Symmetrically, a recompute that lands the classification at `NON_LEAD`
    moves a line sitting at `ELIGIBLE` back to `NOT_REQUIRED`, sets its
    `replacement_priority_score` to exactly 0.00, and advances its `version` by one."
    PRD 3.7: "Three gates guard the opening: the line's `replacement_state` must be
    `ELIGIBLE` or `REPLACED_PARTIAL`, else `ERR_LINE_NOT_ELIGIBLE`; the water
    system's `inventory_status` must be `PUBLISHED` or `AMENDMENT_PENDING`, because
    replacement may not precede publication, else `ERR_INVENTORY_NOT_PUBLISHED`; and
    the `program_posture` must not be `FROZEN`."
    PRD 3.2: "A line verified by potholing on both sides therefore reaches 100.00"

    Design: Corner/state_machines/opening_a_replacement_order_against_a_non_lead_line_is_rejected
    """
    system = fixtures.create_water_system(api, "IL2101016", system_name="Copper Water")
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.POTHOLE,
        side=Side.UTILITY,
        observed_material=Material.COPPER,
        observed_at="2026-06-01T00:00:00Z",
    )
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.POTHOLE,
        side=Side.CUSTOMER,
        observed_material=Material.COPPER,
        observed_at="2026-06-02T00:00:00Z",
    )

    verified = fixtures.read_service_line(api, line["id"])
    assert verified["inventory_state"] == InventoryState.CLASSIFIED_VERIFIED
    assert verified["certainty_basis"] == CertaintyBasis.FIELD_BASIS
    assert verified["classification"] == Classification.NON_LEAD
    assert verified["certainty_score"] == pytest.approx(100.00)
    assert verified["replacement_state"] == ReplacementState.NOT_REQUIRED
    assert verified["replacement_priority_score"] == pytest.approx(0.00)

    response = api.create_replacement_order(
        factories.replacement_order_payload(
            line["id"],
            estimated_cost_cents=100000,
            excavation_start_date="2026-08-10",
            excavation_end_date="2026-08-11",
        ),
        ADMIN_HEADERS,
    )

    error = validate_error(response, "ERR_LINE_NOT_ELIGIBLE", 409)
    assert error["error_id"] != "ERR_INVENTORY_NOT_PUBLISHED"


def test_partial_replacement_permits_a_follow_up_customer_side_order(
    api: ApiClient,
) -> None:
    """A PARTIAL close-out lands REPLACED_PARTIAL, 46 flushing minutes and stays orderable.

    PRD 3.7: "Completion also settles the service line. A `FULL` order moves the
    line's `replacement_state` from `IN_PROGRAM` to `REPLACED_FULL`; a `PARTIAL`
    order moves it to `REPLACED_PARTIAL`."
    PRD 3.7: "a partial replacement lands it on the utility side only, so the
    customer side keeps whatever previously governed it, the line stays
    `CLASSIFIED_PROVISIONAL` on `RECORDS_BASIS`, and its `classification` does not
    move off `LEAD`, `GRR` or `UNKNOWN`."
    PRD 3.7: "Sixth and last, the stored value is a base half-hour of 30 minutes plus
    the volume minutes plus the partial penalty, that whole sum multiplied by the
    corrosion-control multiplier, and the product rounded up to a whole minute."
    PRD 3.7: "or, on a follow-up order covering the customer side of an already
    partially replaced line whose `classification` is still `LEAD`, `GRR` or
    `UNKNOWN`, from `REPLACED_PARTIAL` back to `IN_PROGRAM`, closing that axis's
    cycle `IN_PROGRAM → REPLACED_PARTIAL → IN_PROGRAM`."

    Design: Corner/state_machines/partial_replacement_permits_a_follow_up_customer_side_order
    """
    scenario = fixtures.in_progress_order_on_published_system(
        api,
        "IL2101017",
        system_name="Partial Water",
        consent_outcome=ConsentOutcome.NO_RESPONSE,
        barrier_reason=ConsentBarrierReason.NO_CONTACT,
    )
    fixtures.set_clock(api, "2026-08-11T16:00:00Z")

    completed = fixtures.complete_order(
        api, scenario["order_id"], "2026-08-11T16:00:00Z", [Side.UTILITY]
    )

    assert completed["fulfillment_state"] == FulfillmentState.COMPLETED
    assert completed["scope"] == OrderScope.PARTIAL
    assert completed["flushing_duration_minutes"] == 46

    settled = fixtures.read_service_line(api, scenario["service_line_id"])
    assert settled["replacement_state"] == ReplacementState.REPLACED_PARTIAL
    assert settled["certainty_basis"] == CertaintyBasis.RECORDS_BASIS
    assert settled["classification"] == Classification.LEAD
    assert settled["certainty_score"] == pytest.approx(16.00)
    assert settled["replacement_priority_score"] == pytest.approx(42.00)

    rows, _meta = validate_paginated(
        api.list_evidence_items(
            ADMIN_HEADERS,
            service_line_id=scenario["service_line_id"],
            origin=EvidenceOrigin.REPLACEMENT_CASCADE,
        )
    )
    assert len(rows) == 1
    assert rows[0]["source_type"] == SourceType.POTHOLE
    assert rows[0]["side"] == Side.UTILITY
    assert rows[0]["observed_material"] == Material.COPPER
    assert rows[0]["observed_at"].startswith("2026-08-11T16:00:00")

    follow_up = get_success_data(
        api.create_replacement_order(
            factories.replacement_order_payload(
                scenario["service_line_id"],
                estimated_cost_cents=100000,
                excavation_start_date="2026-08-10",
                excavation_end_date="2026-08-11",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )

    assert follow_up["fulfillment_state"] == FulfillmentState.DRAFT
    assert follow_up["consent_state"] == ConsentState.NOT_REQUESTED
    assert (
        fixtures.read_service_line(api, scenario["service_line_id"])["replacement_state"]
        == ReplacementState.IN_PROGRAM
    )


def test_retracting_the_last_field_evidence_reverts_the_line_to_provisional(
    api: ApiClient,
) -> None:
    """The basis flip runs backwards: 91.00 on FIELD_BASIS becomes exactly 46.00 on records.

    PRD 3.2: "If the retraction removes the last non-retracted `VISUAL_INSPECTION` or
    `POTHOLE` item on either side, so that the both-sides condition no longer holds,
    the server immediately moves the line from `CLASSIFIED_VERIFIED` back to
    `CLASSIFIED_PROVISIONAL`: `certainty_basis` returns to `RECORDS_BASIS`,
    `classification` and `certainty_score` are re-derived under the records variant
    so the records-basis value returns"
    PRD 3.2: "The score then weights the two contributions unevenly, deliberately
    favouring the weaker side: one hundred multiplied by the sum of six tenths of the
    lower of the two side figures and four tenths of the higher of the two, rounded
    half-up to two decimal places."
    PRD 3.6: "The second step adds a certainty bonus of 15.00 points when the line's
    `inventory_state` is `CLASSIFIED_VERIFIED`, and nothing otherwise."

    Design: Corner/state_machines/retracting_the_last_field_evidence_reverts_the_line_to_provisional
    """
    system = fixtures.create_water_system(api, "IL2101018", system_name="Revert Water")
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.HISTORIC_RECORD,
        side=Side.UTILITY,
        observed_material=Material.LEAD,
        observed_at="2026-06-01T00:00:00Z",
    )
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.PREDICTIVE_MODEL,
        side=Side.CUSTOMER,
        observed_material=Material.COPPER,
        observed_at="2026-06-02T00:00:00Z",
    )
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.POTHOLE,
        side=Side.UTILITY,
        observed_material=Material.LEAD,
        observed_at="2026-07-01T00:00:00Z",
    )
    field_item = fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.VISUAL_INSPECTION,
        side=Side.CUSTOMER,
        observed_material=Material.COPPER,
        observed_at="2026-07-02T00:00:00Z",
    )

    before = fixtures.read_service_line(api, line["id"])
    assert before["inventory_state"] == InventoryState.CLASSIFIED_VERIFIED
    assert before["certainty_basis"] == CertaintyBasis.FIELD_BASIS
    assert before["certainty_score"] == pytest.approx(91.00)
    assert before["replacement_priority_score"] == pytest.approx(65.00)

    retracted = fixtures.retract_evidence(api, field_item["id"], "FIELD_SHEET_VOIDED")

    assert retracted["retracted"] is True
    assert retracted["retraction_reason"] == "FIELD_SHEET_VOIDED"
    after = fixtures.read_service_line(api, line["id"])
    assert after["inventory_state"] == InventoryState.CLASSIFIED_PROVISIONAL
    assert after["certainty_basis"] == CertaintyBasis.RECORDS_BASIS
    assert after["utility_side_material"] == Material.LEAD
    assert after["customer_side_material"] == Material.COPPER
    assert after["classification"] == Classification.LEAD
    assert after["certainty_score"] == pytest.approx(46.00)
    assert after["replacement_priority_score"] == pytest.approx(50.00)
    parent = fixtures.read_water_system(api, system["id"])
    assert parent["lead_count"] == 1
    assert parent["non_lead_count"] == 0
