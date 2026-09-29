"""The read and action surfaces: a computed reconciliation, a two-step close, the
clock, composed list filters and per-facility isolation.

These are the routes whose whole content is what they return rather than what they
refuse, so each one is driven end to end and every declared field of the response is
read back.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_defect_count,
    assert_hours_equal,
    assert_instant_equals,
    assert_mou_unit_ledger,
    assert_posture,
    assert_total_count,
)
from test_helpers.factories import (
    make_transfer_accept_payload,
    make_transfer_complete_payload,
    make_transfer_decline_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    COORDINATOR,
    OFFICER,
    admit_to_observation,
    coverage_summary,
    create_ambulance_mou,
    create_facility,
    create_physician_shift,
    create_transfer_agreement,
    create_transfer_order,
    create_volume_forecast,
    open_facility,
    protected_nsa_contract,
    read_ambulance_mou,
    read_encounter,
    read_facility,
    register_encounter,
    set_clock,
    transfer_ready_encounter,
)

WORKING_INSTANT = "2026-08-01T08:00:00Z"
LATER_INSTANT = "2026-08-01T09:30:00Z"
DEADLINE_AFTER_LATER_INSTANT = "2026-08-01T10:00:00Z"
SIGNAGE_EXPIRY_INSTANT = "2027-08-01T08:00:00Z"
NARROW_FACILITY = {
    "observation_bed_count": 2,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
    "max_concurrent_physicians": 2,
}
SEVEN_DAY_HISTORY = [22, 19, 26, 31, 18, 24, 29]
REQUIRED_PER_DAY_HOURS = "16.25"
REQUIRED_TOTAL_HOURS = "113.75"
REQUIRED_BOARD_CERTIFIED_HOURS = "85.31"
SCHEDULED_HOURS = "24.00"
BOARD_CERTIFIED_HOURS = "12.00"
DEFICIT_HOURS = "89.75"
SECOND_HOSPITAL = "Bluff Creek Medical Center"


def test_the_coverage_summary_reconciles_the_active_forecast_against_the_schedule():
    """One computed read carrying a whole week's requirement and a day's staffing.

    PRD 3.4: "Under the `TRAILING_MEAN` variant, `forecast_daily_volume` is that window mean
    unchanged." and "The forecast volume is then converted to raw hours by dividing by a
    throughput of 1.5 patients per physician hour. Those raw hours are raised to the next
    whole quarter hour — multiply by four, take the ceiling, divide by four — and
    `required_physician_hours_per_day` is the larger of that quarter-hour figure and the
    12-hour statutory floor." with "`required_physician_hours_total` is
    `required_physician_hours_per_day` multiplied by `period_days`, rounded half up to two
    decimals. `required_board_certified_hours_total` is that total multiplied by the
    board-certification minimum share of three quarters, rounded half up to two decimals".
    The read itself is specified in PRD 3.4: "when that parameter is omitted, the forecast
    selected is the facility's `ACTIVE` forecast ordered by `period_start_date` descending,
    ties broken by `created_at` ascending, taking the first" and "The response reports
    `facility_id`, the facility's `compliance_posture`, the `selected_volume_forecast_id`
    actually used, the selected forecast's `forecast_basis` and its `forecast_method` (the
    value of the forecast's `method`), `required_physician_hours_per_day`,
    `required_physician_hours_total`, `required_board_certified_hours_total`,
    `scheduled_physician_hours`, `board_certified_hours`, `coverage_deficit_hours`, the
    `coverage_compliant` boolean, the facility's `coverage_deficit_flag`,
    `observation_bed_count`, `observation_beds_occupied`, and `ambulance_units_available`,
    that last figure being the facility's committed unit total less its reserved unit total."

    Design: Corner/endpoints/coverage_summary_computed_read_reconciles_the_selected_active_forecast
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    facility_id = context["facility_id"]

    forecast = create_volume_forecast(
        facility_id,
        ADMIN,
        period_start_date="2026-09-01",
        period_days=7,
        historical_daily_volumes=SEVEN_DAY_HISTORY,
        method="TRAILING_MEAN",
    )
    create_physician_shift(
        facility_id,
        ADMIN,
        clinician_user_id="doc-a",
        role_type="PHYSICIAN",
        board_certified=True,
        start_utc="2026-09-01T00:00:00Z",
        end_utc="2026-09-01T12:00:00Z",
    )
    create_physician_shift(
        facility_id,
        ADMIN,
        clinician_user_id="doc-b",
        role_type="PHYSICIAN",
        board_certified=False,
        start_utc="2026-09-01T12:00:00Z",
        end_utc="2026-09-02T00:00:00Z",
    )

    summary = coverage_summary(facility_id, OFFICER)

    assert summary["facility_id"] == facility_id
    assert summary["compliance_posture"] == "OPEN"
    assert summary["selected_volume_forecast_id"] == forecast["id"]
    assert summary["forecast_method"] == "TRAILING_MEAN"
    assert summary["forecast_basis"] == "HISTORY"
    assert_hours_equal(
        summary["required_physician_hours_per_day"], REQUIRED_PER_DAY_HOURS, "per day"
    )
    assert_hours_equal(
        summary["required_physician_hours_total"], REQUIRED_TOTAL_HOURS, "required total"
    )
    assert_hours_equal(
        summary["required_board_certified_hours_total"],
        REQUIRED_BOARD_CERTIFIED_HOURS,
        "required board-certified",
    )
    assert_hours_equal(summary["scheduled_physician_hours"], SCHEDULED_HOURS, "scheduled")
    assert_hours_equal(
        summary["board_certified_hours"], BOARD_CERTIFIED_HOURS, "board certified"
    )
    assert_hours_equal(summary["coverage_deficit_hours"], DEFICIT_HOURS, "deficit")
    assert summary["coverage_compliant"] is False
    assert summary["coverage_deficit_flag"] is True
    assert summary["observation_bed_count"] == 2
    assert summary["observation_beds_occupied"] == 0
    assert summary["ambulance_units_available"] == 0


def test_accepting_a_transfer_holds_the_unit_and_only_completing_it_releases_everything():
    """The two coordinator actions do different things to the same reservation.

    PRD 3.8: "Acceptance moves it `REQUESTED → ACCEPTED`, accepts an optional
    `accepting_clinician_note`, and re-checks that the agreement's `status` is still `ACTIVE`
    at that moment — a window that expired between ordering and acceptance yields
    `ERR_AGREEMENT_NOT_ACTIVE`. Acceptance holds the ambulance unit: `units_reserved` is
    unchanged, because the unit is still committed to this patient. The encounter stays in
    `TRANSFER_PENDING`."  Completion is where everything unwinds: "It moves the order
    `ACCEPTED → COMPLETED`, accepts an optional `arrival_confirmation_note`, and sets
    `reserved_unit_count` to 0. The memorandum's unit is released with the same recomputation
    chain as a decline — `units_reserved`, `units_available`, `saturation_state`, the
    facility's `ambulance_units_reserved_total` and `transfer_capacity_state`. The encounter
    moves `TRANSFER_PENDING → TRANSFERRED`; if `observation_bed_held` was true it becomes
    false and the facility's `observation_beds_occupied` is recomputed downward by one".

    Design: Corner/endpoints/accept_then_complete_a_transfer_closes_the_encounter_and_releases_the_unit
    """
    context = transfer_ready_encounter(
        clock=WORKING_INSTANT,
        acuity_level=4,
        service_line="CARDIAC",
        facility_overrides=NARROW_FACILITY,
    )
    in_observation = admit_to_observation(context["encounter_id"])
    assert in_observation["clinical_state"] == "OBSERVATION"

    order = create_transfer_order(
        context["encounter_id"],
        context["agreement_id"],
        context["mou_id"],
        in_observation["version"],
    )

    accepted = validate_success(
        api_client.accept_transfer_order(
            order["id"],
            make_transfer_accept_payload(accepting_clinician_note="bed assigned"),
            COORDINATOR,
        )
    )

    assert accepted["status"] == "ACCEPTED"
    assert accepted["reserved_unit_count"] == 1
    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=1, available=1)

    still_pending = read_encounter(context["encounter_id"])
    assert still_pending["clinical_state"] == "TRANSFER_PENDING"
    assert still_pending["observation_bed_held"] is True
    assert read_facility(context["facility_id"])["observation_beds_occupied"] == 1

    completed = validate_success(
        api_client.complete_transfer_order(
            order["id"],
            make_transfer_complete_payload(
                arrival_confirmation_note="patient arrived 09:10"
            ),
            COORDINATOR,
        )
    )

    assert completed["status"] == "COMPLETED"
    assert completed["reserved_unit_count"] == 0

    closed = read_encounter(context["encounter_id"])
    assert closed["clinical_state"] == "TRANSFERRED"
    assert closed["observation_bed_held"] is False
    assert closed["disclosure_state"] == "DISCLOSURE_ACKNOWLEDGED"

    facility = read_facility(context["facility_id"])
    assert facility["observation_beds_occupied"] == 0
    assert_defect_count(facility, 0)
    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=0, available=2)


def test_the_logical_clock_is_readable_and_every_later_stamp_follows_it():
    """Moving the clock moves the next arrival, and leaves the stamps already written.

    PRD 2.4: "All domain time in this system comes from a **logical clock**, not from
    wall-clock time. Before the clock has ever been set, it reads `2026-08-01T00:00:00Z`. A
    test-driving capability lets any of the seven roles set the clock to a supplied
    `current_utc` instant, and a companion read returns the clock's `current_utc` value.
    Setting the clock stamps no rows and increments no entity's `version`; it simply changes
    the instant that subsequent reads and writes observe."  The encounter registered
    afterwards takes its stamps from the moved clock, since PRD 3.6 says "`arrival_at` is
    stamped with the logical clock and `registered_by_user_id` with the acting clerk.
    `mse_start_deadline_at` is computed as `arrival_at` plus half an hour (30 minutes)".

    Design: Corner/endpoints/clock_endpoints_expose_and_advance_the_logical_clock
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)

    before = validate_success(api_client.get_clock(ADMIN))
    assert_instant_equals(before["current_utc"], WORKING_INSTANT, "clock before")

    set_clock(LATER_INSTANT)

    after = validate_success(api_client.get_clock(OFFICER))
    assert_instant_equals(after["current_utc"], LATER_INSTANT, "clock after")

    encounter = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-3201",
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )

    assert_instant_equals(encounter["arrival_at"], LATER_INSTANT, "arrival_at")
    assert_instant_equals(
        encounter["mse_start_deadline_at"],
        DEADLINE_AFTER_LATER_INSTANT,
        "mse_start_deadline_at",
    )
    assert_instant_equals(
        read_facility(context["facility_id"])["signage_expires_at"],
        SIGNAGE_EXPIRY_INSTANT,
        "signage_expires_at",
    )


def test_the_transfer_order_list_honours_each_declared_filter_and_their_combination():
    """Two orders on one encounter, then four different windows onto them.

    PRD 3.8: "Orders are readable individually and as a list filtered by `encounter_id`,
    `transfer_agreement_id`, `ambulance_mou_id` or `status`."  The two orders arise from the
    supersede path: "When a new order is created on an encounter already in
    `TRANSFER_PENDING`, the previous `REQUESTED` or `ACCEPTED` order on that encounter
    transitions to `CANCELLED` and releases its reserved ambulance unit".  The second is then
    declined, which PRD 3.8 says drops "`reserved_unit_count`" to 0 and increments "The
    encounter's `declined_transfer_count`" by 1.  PRD 2.3 pins the window arithmetic:
    "`total_count` as the number of rows matching the filters before the window was applied,
    and `has_more` as a boolean that is true when rows remain beyond the current window."

    Design: Corner/endpoints/transfer_order_list_filters_compose_across_encounter_agreement_and_status
    """
    context = transfer_ready_encounter(
        clock=WORKING_INSTANT,
        acuity_level=4,
        service_line="CARDIAC",
        facility_overrides=NARROW_FACILITY,
    )
    second_agreement = create_transfer_agreement(
        context["facility_id"],
        ADMIN,
        destination_hospital_name=SECOND_HOSPITAL,
        service_line="CARDIAC",
        capability_tier=3,
    )

    first_order = create_transfer_order(
        context["encounter_id"],
        context["agreement_id"],
        context["mou_id"],
        context["encounter_version"],
    )
    second_order = create_transfer_order(
        context["encounter_id"],
        second_agreement["id"],
        context["mou_id"],
        read_encounter(context["encounter_id"])["version"],
    )
    declined = validate_success(
        api_client.decline_transfer_order(
            second_order["id"], make_transfer_decline_payload("CAPACITY"), COORDINATOR
        )
    )
    assert declined["status"] == "DECLINED"

    by_encounter, encounter_meta = validate_paginated(
        api_client.list_transfer_orders(
            OFFICER, params={"encounter_id": context["encounter_id"]}
        )
    )
    assert_total_count(encounter_meta, 2)
    assert {row["id"] for row in by_encounter} == {first_order["id"], second_order["id"]}
    statuses = {row["id"]: row["status"] for row in by_encounter}
    assert statuses[first_order["id"]] == "CANCELLED"
    assert statuses[second_order["id"]] == "DECLINED"

    only_declined, declined_meta = validate_paginated(
        api_client.list_transfer_orders(
            OFFICER,
            params={"encounter_id": context["encounter_id"], "status": "DECLINED"},
        )
    )
    assert_total_count(declined_meta, 1)
    assert only_declined[0]["id"] == second_order["id"]

    by_agreement, agreement_meta = validate_paginated(
        api_client.list_transfer_orders(
            OFFICER, params={"transfer_agreement_id": context["agreement_id"]}
        )
    )
    assert_total_count(agreement_meta, 1)
    assert by_agreement[0]["id"] == first_order["id"]

    windowed, window_meta = validate_paginated(
        api_client.list_transfer_orders(
            OFFICER,
            params={"ambulance_mou_id": context["mou_id"], "limit": 1, "offset": 0},
        )
    )
    assert len(windowed) == 1
    assert_total_count(window_meta, 2)
    assert window_meta["has_more"] is True

    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=0, available=2)


def test_a_facility_scoped_collection_read_never_shows_another_facility_s_rows():
    """Three child collections on one facility, and three empty ones on its neighbour.

    PRD 3.3: "Contracts can be listed per facility, filtered by `status` or by
    `network_status`, and read individually".  PRD 3.5: "Agreements can be listed per facility
    filtered by `status` or `service_line`, and read individually, by administrators,
    compliance officers, physicians and transfer coordinators." and "Memoranda can be listed
    per facility filtered by `status` or `saturation_state`, and read individually."  The bare
    neighbour is exactly what PRD 3.1 describes: "A newly created facility is deliberately not
    yet open for business."

    Design: Corner/endpoints/facility_scoped_child_collection_reads_are_isolated_per_facility
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    facility_id = context["facility_id"]

    contract = protected_nsa_contract(facility_id, OFFICER)
    agreement = create_transfer_agreement(facility_id, ADMIN)
    mou = create_ambulance_mou(facility_id, ADMIN)

    neighbour = create_facility(ADMIN, name="Bluff Creek Freestanding ED")

    contracts, contract_meta = validate_paginated(
        api_client.list_payer_contracts(facility_id, OFFICER)
    )
    assert_total_count(contract_meta, 1)
    assert contracts[0]["id"] == contract["id"]
    assert contracts[0]["status"] == "ACTIVE"
    assert contracts[0]["idr_eligible"] is True

    agreements, agreement_meta = validate_paginated(
        api_client.list_transfer_agreements(facility_id, ADMIN)
    )
    assert_total_count(agreement_meta, 1)
    assert agreements[0]["id"] == agreement["id"]
    assert agreements[0]["status"] == "ACTIVE"

    mous, mou_meta = validate_paginated(
        api_client.list_ambulance_mous(facility_id, ADMIN)
    )
    assert_total_count(mou_meta, 1)
    assert mous[0]["id"] == mou["id"]
    assert mous[0]["units_available"] == 2

    for response in (
        api_client.list_payer_contracts(neighbour["id"], OFFICER),
        api_client.list_transfer_agreements(neighbour["id"], ADMIN),
        api_client.list_ambulance_mous(neighbour["id"], ADMIN),
    ):
        assert response.json()["response_type"] == "array"
        rows, meta = validate_paginated(response)
        assert rows == []
        assert_total_count(meta, 0)
        assert meta["has_more"] is False

    bare = read_facility(neighbour["id"])
    assert bare["ambulance_units_committed_total"] == 0
    assert bare["current_published_template_id"] is None
    assert_posture(bare, "RESTRICTED")
