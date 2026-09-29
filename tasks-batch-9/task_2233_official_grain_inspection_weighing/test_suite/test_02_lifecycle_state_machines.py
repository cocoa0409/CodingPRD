"""Lifecycle contracts: declared initial states, refused transitions, terminal
states and the two dimensions that advance on disjoint triggers."""

from test_helpers import (
    ADMIN,
    BUSINESS_HOURS_CLOCK,
    INSPECTOR,
    STANDARD_HOURS_OPEN_CLOCK,
    SUPERVISOR,
    ApiErrorId,
    api_client,
    activate_licence,
    certificate_payload,
    countersign,
    create_active_inspector,
    create_applicant_account,
    create_certified_scale,
    create_designated_area,
    create_equipment_row,
    create_inspector_row,
    create_request,
    create_active_schedule,
    draft_schedule,
    draw_sample,
    file_training_hours,
    issue_certificate,
    read_applicant,
    read_area,
    read_inspector,
    read_request,
    read_weighing,
    record_grading,
    record_weighing,
    sample_payload,
    schedule_watch,
    set_clock,
    setup_office,
    setup_sampled_request,
    setup_weighed_request,
    supervise_payload,
    suspend_licence,
    suspension_payload,
    validate_error,
    validate_paginated,
    validate_success,
    vessel_watch_payload,
)


GRADING_SCHEDULE = {
    "service_class": "GRADING",
    "base_fee_cents": 8000,
    "per_thousand_bushel_rate_cents": 2000,
    "minimum_fee_cents": 10000,
}

WEIGHING_SCHEDULE = {
    "service_class": "WEIGHING",
    "base_fee_cents": 6000,
    "per_thousand_bushel_rate_cents": 1000,
    "minimum_fee_cents": 8000,
}


def test_every_freshly_created_entity_reports_its_declared_initial_state():
    """A new watch is `SCHEDULED` with `stowage_certified` false, a null
    `started_at`, a null `closed_at` and a null `supervision_minutes`, and the
    owning area's `open_watch_count` increases by one.

    Every new licence begins `PROBATIONARY` with `performance_score` 100,
    `training_hours_completed` 0, `appeal_reversal_count` 0,
    `check_sample_deviation_count` 0, `late_certificate_count` 0 and a null
    `suspension_reason`.

    Registration leaves the row in `PENDING_APPROVAL` with a null
    `certified_until`, a null `last_certification_error_lbs`, an empty
    `recent_deviations_pct`, a null `rolling_bias_pct`, a null
    `last_comparison_deviation_pct`, a `comparison_check_count` of 0 and a
    `consecutive_out_of_tolerance_checks` of 0. A new schedule is born `DRAFT`.

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    set_clock(STANDARD_HOURS_OPEN_CLOCK)
    area = create_designated_area()
    applicant = create_applicant_account()

    fresh_licence = create_inspector_row(area["id"], "L-2101")
    assert fresh_licence["license_status"] == "PROBATIONARY"
    assert fresh_licence["performance_score"] == 100
    assert fresh_licence["training_hours_completed"] == 0
    assert fresh_licence["appeal_reversal_count"] == 0
    assert fresh_licence["check_sample_deviation_count"] == 0
    assert fresh_licence["late_certificate_count"] == 0
    assert fresh_licence["suspension_reason"] is None

    fresh_device = create_equipment_row(area["id"], "SAMPLING_DEVICE")
    assert fresh_device["approval_status"] == "PENDING_APPROVAL"
    assert fresh_device["certified_until"] is None

    fresh_schedule = draft_schedule(area["id"], "GRADING")
    assert fresh_schedule["status"] == "DRAFT"

    supervisor = create_active_inspector(area["id"], "L-2102")
    request = create_request(
        applicant["id"],
        area["id"],
        lot_identifier="LOT-INIT",
        requested_services=["GRADING", "EXPORT_SUPERVISION"],
    )
    assert request["grading_status"] == "OPEN"
    assert request["weighing_status"] == "NOT_REQUIRED"

    response = api_client.create_vessel_watch(
        vessel_watch_payload(
            request["id"],
            supervisor["id"],
            "2026-08-03T08:00:00Z",
            "2026-08-03T12:00:00Z",
            holds_declared=2,
        ),
        SUPERVISOR,
    )
    watch = validate_success(response, 201)

    assert watch["status"] == "SCHEDULED"
    assert watch["started_at"] is None
    assert watch["closed_at"] is None
    assert watch["supervision_minutes"] is None
    assert watch["stowage_certified"] is False
    assert read_area(area["id"])["open_watch_count"] == 1


def test_a_grade_certificate_is_refused_while_the_request_is_only_sampled():
    """A `GRADE`, `COMBINED`, `EXPORT_CARGO` or `APPEAL_GRADE` certificate
    requires a `FINAL` grading determination on the request, else
    `ERR_GRADING_RESULT_MISSING`.

    The assessed fee is charged before the certificate is returned: it is added
    to the applicant's `charges_total_cents`, `open_balance_cents` is recomputed,
    and the certificate begins with `fee_paid_cents` 0 and
    `fee_settlement_status` `UNPAID`.

    Design: Corner/state_machines/certificate_cannot_be_issued_before_a_final_grading_result_exists
    """
    office = setup_office("DELEGATED", fee_schedules=(GRADING_SCHEDULE,))
    staged = setup_sampled_request(
        office, declared_quantity_bushels=500, portions_count=2, lot_identifier="LOT-SM"
    )

    premature = api_client.create_certificate(
        certificate_payload(
            staged["request"]["id"], office["inspector"]["id"], "GRADE"
        ),
        INSPECTOR,
    )
    validate_error(premature, ApiErrorId.ERR_GRADING_RESULT_MISSING.value, 409)

    assert read_request(staged["request"]["id"])["grading_status"] == "SAMPLED"

    listed = api_client.list_request_certificates(staged["request"]["id"], ADMIN)
    rows, meta = validate_paginated(listed)
    assert meta["total_count"] == 0
    assert rows == []
    assert read_applicant(office["applicant"]["id"])["charges_total_cents"] == 0


def test_a_revoked_licence_is_terminal_while_a_suspended_one_recovers():
    """Revocation moves `SUSPENDED → REVOKED` with a `suspension_reason`;
    `REVOKED` is terminal and every later operation naming that inspector is
    refused.

    Reinstatement moves `SUSPENDED → ACTIVE`, requires a `performance_score` of
    at least 80 (`ERR_INSPECTOR_NOT_QUALIFIED` otherwise) and a
    `license_expires_at` still in the future, and clears `suspension_reason`.

    A violation is reported as `ERR_INSPECTOR_LICENSE_INVALID` (HTTP 409).

    Design: Corner/state_machines/revoked_license_is_terminal_and_rejects_reinstatement
    """
    office = setup_office("DESIGNATED")
    doomed = create_active_inspector(office["area"]["id"], "L-2201")
    suspend_licence(doomed["id"])
    revoked = validate_success(
        api_client.revoke_inspector(
            doomed["id"], suspension_payload("Falsified certificate"), ADMIN
        ),
        200,
    )
    assert revoked["license_status"] == "REVOKED"

    reinstatement = api_client.reinstate_inspector(doomed["id"], ADMIN)
    validate_error(reinstatement, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    stored = read_inspector(doomed["id"])
    assert stored["license_status"] == "REVOKED"
    assert stored["suspension_reason"] == "Falsified certificate"

    validate_error(
        api_client.activate_inspector(doomed["id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )
    validate_error(
        api_client.suspend_inspector(doomed["id"], suspension_payload(), ADMIN),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    request = create_request(
        office["applicant"]["id"], office["area"]["id"], lot_identifier="LOT-REV"
    )
    naming_a_revoked_inspector = api_client.create_sample(
        sample_payload(
            request["id"],
            office["probe"]["id"],
            doomed["id"],
            seal_number="SEAL-REV",
            portions_count=2,
        ),
        INSPECTOR,
    )
    validate_error(
        naming_a_revoked_inspector,
        ApiErrorId.ERR_INSPECTOR_LICENSE_INVALID.value,
        409,
    )

    # Only REVOKED is terminal: a merely suspended licence still recovers.
    suspend_licence(office["supervisor"]["id"])
    recovered = validate_success(
        api_client.reinstate_inspector(office["supervisor"]["id"], ADMIN), 200
    )
    assert recovered["license_status"] == "ACTIVE"
    assert recovered["suspension_reason"] is None


def test_a_countersigned_weighing_cannot_be_countersigned_a_second_time():
    """The record must be in `WEIGHED`, the supplied `supervisor_inspector_id`
    must differ from the record's `weigher_inspector_id`
    (`ERR_SELF_SUPERVISION_FORBIDDEN`), and the supervisor must hold the
    `SUPERVISION` endorsement with an `ACTIVE` licence.

    On success the record moves `WEIGHED → SUPERVISED`,
    `supervisor_inspector_id` is recorded where it had been null, and the
    request's weighing dimension advances `WEIGHED → SUPERVISED`.

    **State** — the entity must be in a state the requested action is declared
    from.

    Design: Corner/state_machines/second_supervise_call_on_the_same_weighing_is_rejected
    """
    office = setup_office(
        "DESIGNATED",
        area_overrides={"supervision_required": True},
        second_supervisor=True,
    )
    staged = setup_weighed_request(office)
    supervised = countersign(staged["weighing"]["id"], office["supervisor"]["id"])
    assert supervised["status"] == "SUPERVISED"
    version_after_first = supervised["version"]

    repeat = api_client.supervise_weighing_record(
        staged["weighing"]["id"],
        supervise_payload(office["supervisor_2"]["id"]),
        SUPERVISOR,
    )
    validate_error(repeat, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    stored = read_weighing(staged["weighing"]["id"])
    assert stored["status"] == "SUPERVISED"
    assert stored["supervisor_inspector_id"] == office["supervisor"]["id"]
    assert stored["version"] == version_after_first
    assert read_request(staged["request"]["id"])["weighing_status"] == "SUPERVISED"


def test_weighing_and_grading_advance_without_disturbing_each_other():
    """Each request carries **two independent status dimensions** that advance on
    disjoint triggers. Neither dimension constrains the other.

    Creating the record advances the request `PENDING → WEIGHED` and sets
    `certified_quantity_bushels` to `net_bushels`.

    A `GRADE`, `COMBINED` or `EXPORT_CARGO` certificate moves the grading
    dimension `GRADED → GRADE_CERTIFIED`. A `WEIGHT`, `COMBINED` or
    `EXPORT_CARGO` certificate moves the weighing dimension
    `SUPERVISED → WEIGHT_CERTIFIED`; where the area's `supervision_required` is
    false, a `WEIGHT` or `COMBINED` certificate may instead move it
    `WEIGHED → WEIGHT_CERTIFIED` directly, and an `EXPORT_CARGO` certificate
    always requires the countersigned path.

    Design: Corner/state_machines/grading_and_weighing_dimensions_advance_independently
    """
    office = setup_office(
        "DELEGATED",
        area_overrides={"supervision_required": False},
        fee_schedules=(GRADING_SCHEDULE, WEIGHING_SCHEDULE),
    )
    request = create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        declared_quantity_bushels=3500,
        requested_services=["GRADING", "WEIGHING"],
        lot_identifier="LOT-PAR",
    )
    assert request["grading_status"] == "OPEN"
    assert request["weighing_status"] == "PENDING"

    record_weighing(
        request["id"],
        office["scale"]["id"],
        office["inspector"]["id"],
        dockage_pct=1.5,
    )
    weighed = read_request(request["id"])
    assert weighed["grading_status"] == "OPEN"
    assert weighed["weighing_status"] == "WEIGHED"
    assert weighed["certified_quantity_bushels"] == 3609.27

    sample = draw_sample(
        request["id"],
        office["probe"]["id"],
        office["inspector"]["id"],
        portions_count=2,
        seal_number="SEAL-PAR",
    )
    sampled = read_request(request["id"])
    assert sampled["grading_status"] == "SAMPLED"
    assert sampled["weighing_status"] == "WEIGHED"

    record_grading(request["id"], sample["id"], office["inspector"]["id"])
    graded = read_request(request["id"])
    assert graded["grading_status"] == "GRADED"
    assert graded["weighing_status"] == "WEIGHED"
    assert graded["certified_quantity_bushels"] == 3609.27

    issue_certificate(request["id"], office["inspector"]["id"], "COMBINED")
    certified = read_request(request["id"])
    assert certified["grading_status"] == "GRADE_CERTIFIED"
    assert certified["weighing_status"] == "WEIGHT_CERTIFIED"


def test_suspending_a_supervisor_aborts_the_watches_they_were_holding():
    """A `ServiceAdmin` may suspend a `PROBATIONARY` or `ACTIVE` licence at will,
    supplying a `suspension_reason` that is stored verbatim; the inspector's
    `SCHEDULED` and `IN_PROGRESS` vessel watches are aborted and the owning
    area's `open_watch_count` is decremented once for each.

    A `SCHEDULED` watch is also aborted without anyone asking when its
    supervising inspector is suspended, expires or is revoked, as described in
    §3.2. `CLOSED` and `ABORTED` are both terminal.

    Design: Corner/state_machines/inspector_suspension_aborts_their_scheduled_watches
    """
    office = setup_office(
        "DESIGNATED",
        clock=STANDARD_HOURS_OPEN_CLOCK,
        area_overrides={"concurrent_watch_capacity": 1},
        second_supervisor=True,
    )
    first_request = create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        lot_identifier="LOT-SUS-1",
        requested_services=["GRADING", "EXPORT_SUPERVISION"],
    )
    second_request = create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        lot_identifier="LOT-SUS-2",
        requested_services=["GRADING", "EXPORT_SUPERVISION"],
    )
    watch = schedule_watch(
        first_request["id"],
        office["supervisor"]["id"],
        "2026-08-03T08:00:00Z",
        "2026-08-03T12:00:00Z",
    )
    assert read_area(office["area"]["id"])["open_watch_count"] == 1

    suspended = validate_success(
        api_client.suspend_inspector(
            office["supervisor"]["id"], suspension_payload("Under investigation"), ADMIN
        ),
        200,
    )
    assert suspended["license_status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "Under investigation"

    aborted = validate_success(api_client.get_vessel_watch(watch["id"], ADMIN), 200)
    assert aborted["status"] == "ABORTED"
    assert read_area(office["area"]["id"])["open_watch_count"] == 0

    replacement = api_client.create_vessel_watch(
        vessel_watch_payload(
            second_request["id"],
            office["supervisor_2"]["id"],
            "2026-08-03T08:00:00Z",
            "2026-08-03T12:00:00Z",
        ),
        ADMIN,
    )
    validate_success(replacement, 201)

    restart = api_client.start_vessel_watch(watch["id"], SUPERVISOR)
    validate_error(restart, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    validate_success(
        api_client.reinstate_inspector(office["supervisor"]["id"], ADMIN), 200
    )
    still_aborted = validate_success(
        api_client.get_vessel_watch(watch["id"], ADMIN), 200
    )
    assert still_aborted["status"] == "ABORTED"


def test_countersignature_waits_for_activation_although_weighing_did_not():
    """An inspector whose `license_status` is `PROBATIONARY` or `ACTIVE` may
    sample, grade, analyse and weigh. Only an inspector whose `license_status` is
    `ACTIVE` may countersign a weighing, hold a vessel watch, perform an appeal
    regrade or cast a panel vote.

    Activation moves the licence `PROBATIONARY → ACTIVE`, and it is the gate
    through which supervision authority is granted. It requires at least 24
    completed training hours and a `performance_score` of at least 80; falling
    short of either yields `ERR_INSPECTOR_NOT_QUALIFIED`.

    A `WEIGHT`, `COMBINED` or `EXPORT_CARGO` certificate requires an operative
    weighing record, and how operative is defined depends on the area: where
    `supervision_required` is true the record must be `SUPERVISED`, and where it
    is false a record in either `WEIGHED` or `SUPERVISED` will do; falling short
    is `ERR_WEIGHING_SUPERVISION_REQUIRED`.

    Design: Corner/state_machines/weighing_countersignature_requires_an_active_supervisor_licence
    """
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_designated_area(supervision_required=True)
    create_active_schedule(
        area["id"],
        "WEIGHING",
        base_fee_cents=6000,
        per_thousand_bushel_rate_cents=1000,
        minimum_fee_cents=8000,
    )
    applicant = create_applicant_account()
    scale = create_certified_scale(area["id"], "SCALE-P1")
    weigher = create_inspector_row(area["id"], "L-3001", endorsements=["WEIGHING"])
    candidate = create_inspector_row(
        area["id"], "L-3002", endorsements=["WEIGHING", "SUPERVISION"]
    )
    issuer = create_active_inspector(
        area["id"], "L-3003", endorsements=["GRADING", "WEIGHING", "SUPERVISION"]
    )
    request = create_request(
        applicant["id"],
        area["id"],
        declared_quantity_bushels=3500,
        requested_services=["GRADING", "WEIGHING"],
        lot_identifier="LOT-ACT",
    )

    # A probationary weigher may record the weighing itself.
    assert read_inspector(weigher["id"])["license_status"] == "PROBATIONARY"
    weighing = record_weighing(
        request["id"], scale["id"], weigher["id"], dockage_pct=1.5
    )
    assert weighing["status"] == "WEIGHED"

    too_soon = api_client.supervise_weighing_record(
        weighing["id"], supervise_payload(candidate["id"]), SUPERVISOR
    )
    validate_error(too_soon, ApiErrorId.ERR_INSPECTOR_LICENSE_INVALID.value, 409)

    stalled = read_weighing(weighing["id"])
    assert stalled["status"] == "WEIGHED"
    assert stalled["supervisor_inspector_id"] is None
    assert read_request(request["id"])["weighing_status"] == "WEIGHED"

    uncountersigned = api_client.create_certificate(
        certificate_payload(request["id"], issuer["id"], "WEIGHT"), INSPECTOR
    )
    validate_error(
        uncountersigned, ApiErrorId.ERR_WEIGHING_SUPERVISION_REQUIRED.value, 409
    )

    file_training_hours(candidate["id"], 24)
    activated = activate_licence(candidate["id"])
    assert activated["license_status"] == "ACTIVE"

    accepted = api_client.supervise_weighing_record(
        weighing["id"], supervise_payload(candidate["id"]), SUPERVISOR
    )
    countersigned = validate_success(accepted, 200)
    assert countersigned["status"] == "SUPERVISED"
    assert countersigned["supervisor_inspector_id"] == candidate["id"]
    assert read_request(request["id"])["weighing_status"] == "SUPERVISED"
