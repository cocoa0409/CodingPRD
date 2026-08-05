"""Taking a complaint, triaging it, closing it, and the zone counters it moves."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_complaint,
    bootstrap_registry,
    file_complaint,
    install_station,
    make_supervisor_headers,
    record_reading,
    set_clock,
    setup_issued_order,
    TEST_USERS,
    triage,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]


def test_complaint_intake_without_a_description_is_rejected(api):
    """PRD §3.2: "Intake names the `property_id` the complaint concerns and a
    `complaint_type` from `RODENT_SIGHTING`, `HARBORAGE`,
    `GARBAGE_ACCUMULATION`, `DEAD_ANIMAL` or `MOSQUITO_BREEDING`, records who is
    filing via `reporter_type` — `RESIDENT`, `OWNER`, `AGENCY` or `ANONYMOUS` —
    and captures a free-text `description` of 1 to 1000 characters."
    PRD §2.5: "Required fields present, enum members recognised, integers inside
    their declared ranges, and the structural window rules honoured, else
    `ERR_VALIDATION` (400)."

    Design: Corner/entities/corner_complaint_missing_description_rejected
    """
    env = bootstrap_registry(inspectors=0, with_supervisor=False)
    resp = api.create_complaint(
        {
            "property_id": env["prop_id"],
            "complaint_type": "HARBORAGE",
            "reporter_type": "RESIDENT",
        },
        CLERK,
    )
    assert resp.status_code == 400
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    rows, meta = validate_paginated(
        api.list_complaints(CLERK, params={"property_id": env["prop_id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_complaint_intake_with_an_unknown_type_is_rejected(api):
    """PRD §3.2: "Intake names the `property_id` the complaint concerns and a
    `complaint_type` from `RODENT_SIGHTING`, `HARBORAGE`,
    `GARBAGE_ACCUMULATION`, `DEAD_ANIMAL` or `MOSQUITO_BREEDING`, records who is
    filing via `reporter_type` — `RESIDENT`, `OWNER`, `AGENCY` or `ANONYMOUS` —
    and captures a free-text `description` of 1 to 1000 characters."
    PRD §3.2: "It then computes `priority_score` and `response_due_at`,
    increments the zone's `open_complaint_count`, and recomputes that zone's
    `rodent_index` and `posture`."

    Design: Corner/entities/corner_complaint_invalid_enum_rejected
    """
    env = bootstrap_registry(inspectors=0, with_supervisor=False)
    resp = api.create_complaint(
        {
            "property_id": env["prop_id"],
            "complaint_type": "BIRD_NUISANCE",
            "reporter_type": "RESIDENT",
            "description": "Pigeons on the roof",
        },
        CLERK,
    )
    assert resp.status_code == 400
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["open_complaint_count"] == 0


def test_complaint_list_reports_window_and_total_count(api):
    """PRD §2.3: "Every list endpoint accepts two optional query parameters,
    `limit` and `offset`."
    PRD §2.3: "Every list response populates `limit`, `offset`, `total_count`
    and `has_more` inside `meta`: `total_count` is the number of rows matching
    the filters before the page window is applied, and `has_more` is true exactly
    when rows remain beyond the current window."
    PRD §3.8: "The **complaint component** counts the zone's complaints that are
    simultaneously open — status `RECEIVED`, `TRIAGED`, `INSPECTION_SCHEDULED`,
    `INSPECTED` or `ABATEMENT_ORDERED` — and were created inside the same closed
    30-day window. That count is multiplied by 20.0, capped at 100.0, and
    rounded half-up to two decimal places."

    Design: Corner/entities/corner_complaints_list_pagination_envelope
    """
    env = bootstrap_registry(inspectors=0, with_supervisor=False)
    file_complaint(env["prop_id"], complaint_type="HARBORAGE")
    file_complaint(
        env["prop_id"], complaint_type="GARBAGE_ACCUMULATION",
        reporter_type="AGENCY", description="Refuse piled behind the building",
    )
    file_complaint(
        env["prop_id"], complaint_type="DEAD_ANIMAL",
        reporter_type="ANONYMOUS", description="Dead rat by the gate",
    )

    rows, meta = validate_paginated(
        api.list_complaints(
            CLERK,
            params={"property_id": env["prop_id"], "limit": 2, "offset": 2},
        )
    )
    assert meta["limit"] == 2
    assert meta["offset"] == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(rows) == 1

    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["open_complaint_count"] == 3
    assert zone["rodent_index"] == pytest.approx(12.00, abs=0.001)


def test_triaging_an_already_triaged_complaint_is_rejected(api):
    """PRD §3.2: "Triaging anything other than a `RECEIVED` complaint is
    `ERR_INVALID_STATE`."
    PRD §3.2: "The severity base contributes 20 for `ROUTINE`, 40 for `HIGH` and
    60 for `CRITICAL`, reading the complaint's operative `severity` and not the
    reported one."
    PRD §3.2: "The `response_due_at` is the complaint's `created_at` plus a
    service-level window that depends on the operative `severity`: 168 hours for
    `ROUTINE`, 72 hours for `HIGH`, and 24 hours for `CRITICAL`."

    Design: Corner/state_machines/corner_triage_of_already_triaged_complaint_rejected
    """
    env = bootstrap_registry(inspectors=0)
    complaint = file_complaint(
        env["prop_id"], complaint_type="HARBORAGE", reported_severity="ROUTINE"
    )
    triage(complaint["id"], env["sup_id"], "HIGH")

    resp = api.triage_complaint(
        complaint["id"], {"severity": "CRITICAL"},
        make_supervisor_headers(env["sup_id"]),
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_complaint(complaint["id"], CLERK))
    assert_complaint(after)
    assert after["severity"] == "HIGH"
    assert after["priority_score"] == pytest.approx(55.00, abs=0.001)
    assert after["response_due_at"] == "2026-05-07T09:00:00.000Z"


def test_hotspot_zone_escalates_routine_at_triage_and_adds_the_posture_bonus(api):
    """PRD §3.2: "The submitted severity is written first, and then one automatic
    adjustment applies: if the containing zone's `posture` is `HOTSPOT` at triage
    time and the resulting severity would be `ROUTINE`, it is escalated to
    `HIGH`."
    PRD §3.2: "A posture bonus is added according to the containing zone's
    `posture` read at that same moment: 0 when `NORMAL`, 5 when `ELEVATED`, and
    12 when `HOTSPOT`."
    PRD §3.2: "The offset is *always* measured from `created_at` and never from
    `triaged_at`, so when triage changes the severity the deadline moves relative
    to the original intake instant rather than relative to the triage instant."

    Design: Corner/calculations/corner_hotspot_posture_escalates_routine_and_adds_priority_bonus
    """
    env = bootstrap_registry(inspectors=1)
    file_complaint(
        env["prop_id"], complaint_type="RODENT_SIGHTING",
        reported_severity="ROUTINE", description="Rats crossing the sidewalk",
    )
    station = install_station(env["prop_id"], env["insp_id"])
    record_reading(
        station["id"], env["insp_id"], take_pct=87, activity_sign_count=6,
        station_condition="INTACT", rebaited=True,
    )

    intake = validate_success(
        api.create_complaint(
            {
                "property_id": env["prop_id"],
                "complaint_type": "MOSQUITO_BREEDING",
                "reporter_type": "AGENCY",
                "description": "Standing water in the rear lot",
                "reported_severity": "ROUTINE",
            },
            CLERK,
        ),
        201,
    )
    assert intake["severity"] == "ROUTINE"
    assert intake["priority_score"] == pytest.approx(50.00, abs=0.001)
    assert intake["response_due_at"] == "2026-05-11T09:00:00.000Z"

    triaged = validate_success(
        api.triage_complaint(
            intake["id"],
            {"severity": "ROUTINE", "triage_notes": "Standing water plus active rodent index"},
            make_supervisor_headers(env["sup_id"]),
        )
    )
    assert triaged["severity"] == "HIGH"
    assert triaged["priority_score"] == pytest.approx(70.00, abs=0.001)
    assert triaged["response_due_at"] == "2026-05-07T09:00:00.000Z"

    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["posture"] == "HOTSPOT"
    assert zone["open_complaint_count"] == 2


def test_same_nuisance_within_forty_eight_hours_is_a_duplicate(api):
    """PRD §3.2: "If an open complaint of the same `complaint_type` already exists
    on the same parcel and was created within the last 48 hours of logical-clock
    time, intake is rejected with `ERR_DUPLICATE_COMPLAINT`."
    PRD §3.8: "That count is multiplied by 20.0, capped at 100.0, and rounded
    half-up to two decimal places."

    Design: Corner/validations/corner_duplicate_complaint_window_rejects_then_releases
    """
    env = bootstrap_registry(inspectors=0, with_supervisor=False)
    file_complaint(env["prop_id"], complaint_type="HARBORAGE")

    set_clock("2026-05-06T08:00:00Z")
    too_soon = api.create_complaint(
        {
            "property_id": env["prop_id"],
            "complaint_type": "HARBORAGE",
            "reporter_type": "ANONYMOUS",
            "description": "Same burrows reported again",
        },
        CLERK,
    )
    assert too_soon.status_code == 409
    validate_error(too_soon, ApiErrorId.ERR_DUPLICATE_COMPLAINT.value)
    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["open_complaint_count"] == 1

    set_clock("2026-05-06T10:00:00Z")
    accepted = api.create_complaint(
        {
            "property_id": env["prop_id"],
            "complaint_type": "HARBORAGE",
            "reporter_type": "ANONYMOUS",
            "description": "Same burrows reported again",
        },
        CLERK,
    )
    second = validate_success(accepted, 201)
    assert second["status"] == "RECEIVED"

    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["open_complaint_count"] == 2
    assert zone["rodent_index"] == pytest.approx(8.00, abs=0.001)


def test_complaint_close_is_refused_while_the_parcel_carries_a_live_order(api):
    """PRD §3.2: "If any abatement order on the same parcel is still in a
    non-terminal status — that is, in `ISSUED`, `SERVED`,
    `REINSPECTION_SCHEDULED`, `ESCALATED` or `CITY_ABATED` — the closure is
    refused with `ERR_OPEN_ORDER_EXISTS`."
    PRD §3.6: "Issuance also moves the linked complaint `INSPECTED →
    ABATEMENT_ORDERED`, raises the parcel's `open_order_count` by one and
    increments the parcel's `version` by one."

    Design: Corner/validations/corner_complaint_close_blocked_while_parcel_under_order
    """
    env = setup_issued_order()
    second = file_complaint(
        env["prop_id"], complaint_type="RODENT_SIGHTING",
        reporter_type="ANONYMOUS", description="Rat run behind the bins",
    )

    resp = api.close_complaint(
        second["id"],
        {"closure_reason": "WITHDRAWN", "note": "Caller no longer wishes to pursue"},
        make_supervisor_headers(env["sup_id"]),
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_OPEN_ORDER_EXISTS.value)

    after = validate_success(api.get_complaint(second["id"], CLERK))
    assert after["status"] == "RECEIVED"
    assert after["closure_reason"] is None

    order = validate_success(
        api.get_abatement_order(env["order_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert order["status"] == "ISSUED"
    prop = validate_success(
        api.get_property(env["prop_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert prop["open_order_count"] == 1
    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["open_complaint_count"] == 2


def test_each_withdrawal_gives_the_zone_open_case_count_back(api):
    """PRD §3.2: "Whichever leg fires, the chosen `closure_reason` is stamped
    along with `closed_at` at the current logical clock, the zone's
    `open_complaint_count` drops by one, and the zone's `rodent_index` and
    `posture` are recomputed."
    PRD §3.8: "`open_complaint_count` is the number of complaints in the zone
    whose status is none of `CLOSED_NO_VIOLATION`, `CLOSED_RESOLVED`,
    `CLOSED_WITHDRAWN` or `CLOSED_DUPLICATE`."

    Design: Difficulty/compensating_invariant/zone_open_case_count_conserved_on_withdrawal
    """
    env = bootstrap_registry(inspectors=0, parcels=2)
    first = file_complaint(
        env["prop1_id"], complaint_type="RODENT_SIGHTING",
        reported_severity="ROUTINE", description="Rats near the bins",
    )
    second = file_complaint(
        env["prop2_id"], complaint_type="HARBORAGE",
        reported_severity="ROUTINE", description="Woodpile against the fence",
    )

    before = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert before["open_complaint_count"] == 2

    sup = make_supervisor_headers(env["sup_id"])
    closed_one = validate_success(
        api.close_complaint(
            first["id"],
            {"closure_reason": "WITHDRAWN",
             "note": "Reporter withdrew after private extermination"},
            sup,
        )
    )
    assert closed_one["status"] == "CLOSED_WITHDRAWN"
    assert closed_one["closure_reason"] == "WITHDRAWN"
    assert closed_one["closed_at"] == "2026-05-04T09:00:00.000Z"
    mid = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert mid["open_complaint_count"] == 1

    closed_two = validate_success(
        api.close_complaint(
            second["id"],
            {"closure_reason": "WITHDRAWN",
             "note": "Duplicate of a neighbour report, withdrawn"},
            sup,
        )
    )
    assert closed_two["status"] == "CLOSED_WITHDRAWN"
    after = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert after["open_complaint_count"] == 0


def test_zone_rodent_index_falls_back_as_each_case_is_withdrawn(api):
    """PRD §3.8: "The **complaint component** counts the zone's complaints that
    are simultaneously open — status `RECEIVED`, `TRIAGED`,
    `INSPECTION_SCHEDULED`, `INSPECTED` or `ABATEMENT_ORDERED` — and were created
    inside the same closed 30-day window. That count is multiplied by 20.0,
    capped at 100.0, and rounded half-up to two decimal places."
    PRD §3.8: "The `posture` follows directly from the resulting index:
    `HOTSPOT` when the index is at least 70.00, otherwise `ELEVATED` when the
    index is at least 40.00, otherwise `NORMAL`."

    Design: Difficulty/compensating_invariant/zone_open_case_count_conserved_on_withdrawal
    """
    env = bootstrap_registry(inspectors=0, parcels=2)
    first = file_complaint(
        env["prop1_id"], complaint_type="RODENT_SIGHTING",
        reported_severity="ROUTINE", description="Rats near the bins",
    )
    second = file_complaint(
        env["prop2_id"], complaint_type="HARBORAGE",
        reported_severity="ROUTINE", description="Woodpile against the fence",
    )

    before = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert before["rodent_index"] == pytest.approx(8.00, abs=0.001)
    assert before["posture"] == "NORMAL"

    sup = make_supervisor_headers(env["sup_id"])
    api.close_complaint(first["id"], {"closure_reason": "WITHDRAWN"}, sup)
    mid = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert mid["rodent_index"] == pytest.approx(4.00, abs=0.001)
    assert mid["posture"] == "NORMAL"

    api.close_complaint(second["id"], {"closure_reason": "WITHDRAWN"}, sup)
    after = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert after["rodent_index"] == pytest.approx(0.00, abs=0.001)
    assert after["posture"] == "NORMAL"
