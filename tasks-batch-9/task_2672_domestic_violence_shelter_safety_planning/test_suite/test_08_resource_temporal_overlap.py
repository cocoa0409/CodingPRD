"""Two resources booked on a calendar rather than on a counter: an advocate's buffered
hearing calendar, and a unit's stay windows, where only overlapping windows compete.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    MODERATE_FACTORS,
    api_client,
    approve_screening,
    assert_bed_ledger_invariant,
    assert_protective_order_case,
    assert_same_instant,
    assert_unit_status_derived,
    create_client_payload,
    file_case,
    get_success_data,
    read_unit,
    reserve_bed,
    seed_client_with_assessed_call,
    seed_legal_advocate,
    seed_screening_request,
    seed_shelter_scene,
    unit_version,
    validate_error,
    validate_paginated,
    validate_success,
)

FIRST_HEARING_START = "2026-08-20T09:00:00Z"
FIRST_HEARING_END = "2026-08-20T10:00:00Z"


def _one_filed_hearing():
    """One FILED case holding 09:00-10:00 for Iris Vale, and a second petition still drafted.

    The first hearing's buffered window runs 08:00 to 11:00.
    """
    legal = seed_legal_advocate("Iris Vale", max_caseload=12)
    client = get_success_data(
        api_client.create_client(
            create_client_payload(
                client_code="C-9501",
                legal_name="Priya Nair",
                household_size=1,
                minor_children_count=0,
                hmis_disclosure_consent="DENIED",
            ),
            ADMIN_HEADERS,
        )
    )
    first = get_success_data(
        api_client.create_protective_order_case(
            {"client_id": client["id"], "order_type": "EMERGENCY_EX_PARTE"}, legal.headers
        )
    )
    first = get_success_data(
        file_case(legal, first["id"], legal.id, FIRST_HEARING_START, FIRST_HEARING_END)
    )
    second = get_success_data(
        api_client.create_protective_order_case(
            {"client_id": client["id"], "order_type": "FULL_ORDER"}, legal.headers
        )
    )
    return legal, first, second


def test_a_hearing_whose_buffer_only_touches_the_booked_one_is_a_double_booking():
    """A 12:00 hearing buffers back to 11:00, exactly where the booked buffer ends.

    PRD: "Touching endpoints conflict: two hearings whose buffered windows share a single
    boundary instant are a double booking, refused with `ERR_ADVOCATE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/advocate_hearing_buffer_rejects_touching_windows
    """
    legal, first, second = _one_filed_hearing()

    response = file_case(
        legal, second["id"], legal.id, "2026-08-20T12:00:00Z", "2026-08-20T13:00:00Z"
    )

    validate_error(response, ApiErrorId.ERR_ADVOCATE_DOUBLE_BOOKED.value, 409)
    unfiled = get_success_data(
        api_client.get_protective_order_case(second["id"], legal.headers)
    )
    assert unfiled["status"] == "PETITION_DRAFTED"
    assert unfiled["hearing_start_utc"] is None
    assert unfiled["hearing_end_utc"] is None
    assert unfiled["accompanying_advocate_id"] is None
    assert unfiled["filed_court"] is None
    assert unfiled["version"] == 1
    booked = get_success_data(
        api_client.get_protective_order_case(first["id"], legal.headers)
    )
    assert booked["status"] == "FILED"
    assert_same_instant(booked["hearing_start_utc"], FIRST_HEARING_START)
    assert_same_instant(booked["hearing_end_utc"], FIRST_HEARING_END)


def test_one_minute_of_daylight_between_the_buffers_lets_the_second_hearing_file():
    """Pushed to 12:01 the buffered windows finally clear each other and filing succeeds.

    PRD: "In practice this means two hearings for the same advocate must be separated by
    strictly more than two hours of clear time."

    Design: Difficulty/resource_temporal_overlap/advocate_hearing_buffer_rejects_touching_windows
    """
    legal, first, second = _one_filed_hearing()

    response = file_case(
        legal, second["id"], legal.id, "2026-08-20T12:01:00Z", "2026-08-20T13:01:00Z"
    )

    filed = validate_success(response, 200)
    assert filed["status"] == "FILED"
    assert_same_instant(filed["hearing_start_utc"], "2026-08-20T12:01:00Z")
    assert_same_instant(filed["hearing_end_utc"], "2026-08-20T13:01:00Z")
    assert filed["accompanying_advocate_id"] == legal.id
    assert filed["refile_count"] == 0
    assert_protective_order_case(filed)
    booked = get_success_data(
        api_client.get_protective_order_case(first["id"], legal.headers)
    )
    assert_same_instant(booked["hearing_start_utc"], FIRST_HEARING_START)
    assert booked["status"] == "FILED"


TWO_ADULTS = {"household_size": 2, "minor_children_count": 0, "hmis_disclosure_consent": "DENIED"}


def _two_touching_reservations():
    """A four-bed STANDARD room booked twice back to back, plus a third approved request.

    Both existing windows are reserved before the trigger, and all three screenings were
    decided while the facility was still empty.
    """
    scene = seed_shelter_scene(
        shelter_overrides={
            "name": "Elm House",
            "nightly_rate_cents": 8000,
            "weekend_surcharge_cents": 2000,
            "child_supplement_cents": 1000,
        },
        unit_overrides={"unit_label": "B1", "unit_type": "STANDARD", "bed_capacity": 4},
    )
    requests = []
    for code, name, household, entry in (
        ("C-9601", "Alina Ford", 2, "2026-08-07"),
        ("C-9602", "Mira Osei", 2, "2026-08-12"),
        ("C-9603", "Tess Baird", 1, "2026-08-10"),
    ):
        client, call, _ra = seed_client_with_assessed_call(
            scene.advocate,
            client_overrides=dict(
                TWO_ADULTS, client_code=code, legal_name=name, household_size=household
            ),
            assessment_overrides=dict(MODERATE_FACTORS),
        )
        request = seed_screening_request(
            scene.advocate,
            client["id"],
            call["id"],
            scene.shelter["id"],
            requested_entry_date=entry,
        )
        requests.append(approve_screening(scene.manager, request["id"], scene.advocate.id))
    early, late, spare = requests
    first = get_success_data(
        reserve_bed(scene, early["id"], entry_date="2026-08-07", planned_exit_date="2026-08-12")
    )
    second = get_success_data(
        reserve_bed(scene, late["id"], entry_date="2026-08-12", planned_exit_date="2026-08-17")
    )
    return scene, spare, first, second


def test_two_stays_that_only_touch_share_the_same_four_bed_room():
    """Four adults fit because the second window opens on the day the first one closes.

    PRD: "Two windows that merely touch — one ending on the very day the other starts — do
    not overlap, so a household leaving on the 10th and a household arriving on the 10th can
    share a four-bed room even if together they are six people."

    Design: Difficulty/resource_temporal_overlap/unit_stay_window_capacity_aggregates_only_overlapping_windows
    """
    scene, _spare, first, second = _two_touching_reservations()

    assert first["occupancy_status"] == "RESERVED"
    assert second["occupancy_status"] == "RESERVED"
    assert second["entry_date"] == "2026-08-12"
    assert second["planned_exit_date"] == "2026-08-17"
    assert first["planned_exit_date"] == second["entry_date"]
    unit = read_unit(scene.manager, scene.unit["id"])
    assert unit["reserved_beds"] == 4
    assert unit["occupied_beds"] == 0
    assert unit["available_beds"] == 0
    assert unit["status"] == "HOLD"
    assert_bed_ledger_invariant(unit)
    assert_unit_status_derived(unit)


def test_a_window_straddling_both_stays_is_refused_on_the_aggregate_sum():
    """Two plus two plus one is five, and five will not fit in four beds.

    PRD: "Over the half-open day window running from `entry_date` up to but excluding
    `planned_exit_date`, the server sums the `household_size` of every admission already on
    that unit whose `occupancy_status` is `RESERVED` or `CHECKED_IN` and whose own half-open
    window overlaps the requested one, adds the requesting `household_size`, and refuses the
    placement with `ERR_UNIT_CAPACITY_EXCEEDED` if the total exceeds the unit's
    `bed_capacity`."

    Design: Difficulty/resource_temporal_overlap/unit_stay_window_capacity_aggregates_only_overlapping_windows
    """
    scene, spare, first, second = _two_touching_reservations()
    version_before = unit_version(scene.manager, scene.unit["id"])

    response = reserve_bed(
        scene,
        spare["id"],
        entry_date="2026-08-10",
        planned_exit_date="2026-08-13",
        expected_shelter_unit_version=version_before,
    )

    validate_error(response, ApiErrorId.ERR_UNIT_CAPACITY_EXCEEDED.value, 409)
    assert (
        get_success_data(api_client.get_screening_request(spare["id"], scene.manager.headers))[
            "status"
        ]
        == "APPROVED"
    )
    unit = read_unit(scene.manager, scene.unit["id"])
    assert unit["reserved_beds"] == 4
    assert unit["occupied_beds"] == 0
    assert unit["available_beds"] == 0
    assert unit["status"] == "HOLD"
    assert unit["version"] == version_before
    assert_bed_ledger_invariant(unit)
    rows, _meta = validate_paginated(
        api_client.list_shelter_admissions(scene.manager.headers, params={"limit": 100, "offset": 0})
    )
    assert sorted(row["id"] for row in rows) == sorted([first["id"], second["id"]])
