"""Housing assignment guards, bed occupancy, and the release cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, fixtures,
)
from test_helpers import factories as f

INTAKE = TEST_USERS["intake_headers"]
CLASSIFICATION = TEST_USERS["classification_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / housing_requires_booking_classified
# ---------------------------------------------------------------------------
def test_housing_unclassified_booking_rejected(api):
    """PRD §3.3: "The booking must already be `CLASSIFIED`; a booking that has never been
    classified is rejected with `ERR_BOOKING_NOT_CLASSIFIED`."

    Design: Difficulty/cross_entity_state_dependency/housing_requires_booking_classified
    """
    inmate = fixtures.create_inmate(api, sex="MALE")
    booking = fixtures.create_booking(api, inmate["id"], sentence_days=40)  # left BOOKED
    _unit, beds = fixtures.create_unit_with_beds(api, "MIN", "MALE", 4, ("B1",))
    resp = api.create_housing_assignment(
        f.create_housing_assignment_payload(booking["id"], beds[0]["id"], "2026-05-02T10:00:00Z"),
        CLASSIFICATION,
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_CLASSIFIED.value)


def test_housing_classified_booking_succeeds(api):
    """PRD §3.3: "A new `HousingAssignment` begins in `assignment_status` `ACTIVE`, sets its bed
    to `OCCUPIED` (incrementing the bed's `version`), and drives the booking from `CLASSIFIED`
    to `HOUSED`."

    Design: Difficulty/cross_entity_state_dependency/housing_requires_booking_classified
    """
    _inmate, booking = fixtures.create_classified_booking(api, sex="MALE",
                                                          charge_severity="MISDEMEANOR", sentence_days=40)
    _unit, beds = fixtures.create_unit_with_beds(api, "MIN", "MALE", 4, ("B1",))
    resp = api.create_housing_assignment(
        f.create_housing_assignment_payload(booking["id"], beds[0]["id"], "2026-05-02T10:00:00Z"),
        CLASSIFICATION,
    )
    data = validate_success(resp, expected_status=201)
    assert data["assignment_status"] == "ACTIVE", f"got {data['assignment_status']}"
    booking_now = get_success_data(api.get_booking(booking["id"], SUPERVISOR))
    assert booking_now["booking_status"] == "HOUSED", f"got {booking_now['booking_status']}"


# ---------------------------------------------------------------------------
# validations / housing_gender_mismatch_returns_error
# ---------------------------------------------------------------------------
def test_housing_gender_mismatch_rejected(api):
    """PRD §3.3: "The unit's `gender` must accept the inmate's `sex`, where a `COED` unit
    accepts both a `MALE` and a `FEMALE` inmate, otherwise `ERR_GENDER_MISMATCH`."

    Design: Corner/validations/housing_gender_mismatch_returns_error
    """
    _inmate, booking = fixtures.create_classified_booking(api, sex="MALE",
                                                          charge_severity="MISDEMEANOR", sentence_days=40)
    _unit, beds = fixtures.create_unit_with_beds(api, "MIN", "FEMALE", 4, ("F1",))
    resp = api.create_housing_assignment(
        f.create_housing_assignment_payload(booking["id"], beds[0]["id"], "2026-05-02T10:00:00Z"),
        CLASSIFICATION,
    )
    validate_error(resp, ApiErrorId.ERR_GENDER_MISMATCH.value)


# ---------------------------------------------------------------------------
# validations / housing_unit_full_returns_error
# ---------------------------------------------------------------------------
def test_housing_unit_full_rejected(api):
    """PRD §3.3: "counting the beds in the unit whose `status` is `OCCUPIED`, if that count is
    already at or above the unit's `capacity` the assignment is rejected with
    `ERR_HOUSING_UNIT_FULL`."

    Design: Corner/validations/housing_unit_full_returns_error
    """
    _i1, bk1 = fixtures.create_classified_booking(api, sex="MALE", charge_severity="MISDEMEANOR", sentence_days=40)
    _i2, bk2 = fixtures.create_classified_booking(api, sex="MALE", charge_severity="MISDEMEANOR", sentence_days=40)
    _unit, beds = fixtures.create_unit_with_beds(api, "MIN", "MALE", 1, ("U1", "U2"))
    fixtures.house_booking(api, bk1["id"], beds[0]["id"], "2026-05-02T10:00:00Z")
    resp = api.create_housing_assignment(
        f.create_housing_assignment_payload(bk2["id"], beds[1]["id"], "2026-05-02T10:00:00Z"),
        CLASSIFICATION,
    )
    validate_error(resp, ApiErrorId.ERR_HOUSING_UNIT_FULL.value)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / housing_security_beats_double_booked
# ---------------------------------------------------------------------------
def _setup_security_vs_double_booked(api):
    """MED/COED unit one bed; bk1 (MED) housed [10:00,12:00); bk2 (MIN) classified un-housed."""
    _i1, bk1 = fixtures.create_classified_booking(api, sex="MALE", charge_severity="FELONY",
                                                  prior_bookings_count=0, sentence_days=300)  # MED
    _i2, bk2 = fixtures.create_classified_booking(api, sex="MALE", charge_severity="MISDEMEANOR",
                                                  prior_bookings_count=0, sentence_days=50)  # MIN
    unit, beds = fixtures.create_unit_with_beds(api, "MED", "COED", 4, ("M1",))
    fixtures.house_booking(api, bk1["id"], beds[0]["id"], "2026-05-02T10:00:00Z", "2026-05-02T12:00:00Z")
    return bk1, bk2, beds[0]


def test_security_mismatch_returns_security_error(api):
    """PRD §3.3: "The bed's unit `security_level` must equal the booking's
    `classification_level`, otherwise `ERR_SECURITY_LEVEL_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/housing_security_beats_double_booked
    """
    _bk1, bk2, bed = _setup_security_vs_double_booked(api)
    resp = api.create_housing_assignment(
        f.create_housing_assignment_payload(bk2["id"], bed["id"], "2026-05-02T11:00:00Z",
                                            "2026-05-02T13:00:00Z"),
        CLASSIFICATION,
    )
    validate_error(resp, ApiErrorId.ERR_SECURITY_LEVEL_MISMATCH.value)


def test_security_check_precedes_double_booked(api):
    """PRD §2.6: precedence lists "... security-level match, gender match, bed double-booking ...",
    so a security-level mismatch is reported ahead of a bed double-booking on the same request.

    Design: Difficulty/priority_pair_validation_conflict/housing_security_beats_double_booked
    """
    _bk1, bk2, bed = _setup_security_vs_double_booked(api)
    resp = api.create_housing_assignment(
        f.create_housing_assignment_payload(bk2["id"], bed["id"], "2026-05-02T11:00:00Z",
                                            "2026-05-02T13:00:00Z"),
        CLASSIFICATION,
    )
    err = validate_error(resp, ApiErrorId.ERR_SECURITY_LEVEL_MISMATCH.value)
    assert err["error_id"] != ApiErrorId.ERR_BED_DOUBLE_BOOKED.value, (
        "security-level check must pre-empt the bed double-booking check"
    )


# ---------------------------------------------------------------------------
# resource_temporal_overlap / bed_half_open_adjacency
# ---------------------------------------------------------------------------
def test_adjacent_bed_assignment_allowed(api):
    """PRD §3.3: "overlap is judged on the half-open interval running from the inclusive
    `start_datetime` up to but not including the `end_datetime`".

    Design: Difficulty/resource_temporal_overlap/bed_half_open_adjacency
    """
    _i1, bk1 = fixtures.create_classified_booking(api, sex="MALE", charge_severity="MISDEMEANOR", sentence_days=60)
    _i2, bk2 = fixtures.create_classified_booking(api, sex="MALE", charge_severity="MISDEMEANOR", sentence_days=60)
    _unit, beds = fixtures.create_unit_with_beds(api, "MIN", "MALE", 4, ("C1",))
    fixtures.house_booking(api, bk1["id"], beds[0]["id"], "2026-05-02T10:00:00Z", "2026-05-02T12:00:00Z")
    resp = api.create_housing_assignment(
        f.create_housing_assignment_payload(bk2["id"], beds[0]["id"], "2026-05-02T12:00:00Z",
                                            "2026-05-02T14:00:00Z"),
        CLASSIFICATION,
    )
    data = validate_success(resp, expected_status=201)
    assert data["assignment_status"] == "ACTIVE", (
        "an assignment starting exactly at the prior assignment's end is allowed (half-open)"
    )


def test_overlapping_bed_assignment_rejected(api):
    """PRD §3.3: "The requested interval must not overlap any existing `ACTIVE` assignment on
    that same bed ... a clash is rejected with `ERR_BED_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/bed_half_open_adjacency
    """
    _i1, bk1 = fixtures.create_classified_booking(api, sex="MALE", charge_severity="MISDEMEANOR", sentence_days=60)
    _i2, bk2 = fixtures.create_classified_booking(api, sex="MALE", charge_severity="MISDEMEANOR", sentence_days=60)
    _unit, beds = fixtures.create_unit_with_beds(api, "MIN", "MALE", 4, ("C1",))
    fixtures.house_booking(api, bk1["id"], beds[0]["id"], "2026-05-02T10:00:00Z", "2026-05-02T12:00:00Z")
    resp = api.create_housing_assignment(
        f.create_housing_assignment_payload(bk2["id"], beds[0]["id"], "2026-05-02T11:00:00Z",
                                            "2026-05-02T13:00:00Z"),
        CLASSIFICATION,
    )
    validate_error(resp, ApiErrorId.ERR_BED_DOUBLE_BOOKED.value)


# ---------------------------------------------------------------------------
# transitive_cascade / release_cascade_assignment_bed_unit
# ---------------------------------------------------------------------------
def _setup_housed_booking(api):
    _inmate, booking = fixtures.create_classified_booking(api, sex="MALE",
                                                          charge_severity="MISDEMEANOR", sentence_days=100)
    _unit, beds = fixtures.create_unit_with_beds(api, "MIN", "MALE", 4, ("A1",))
    assignment = fixtures.house_booking(api, booking["id"], beds[0]["id"], "2026-05-02T10:00:00Z")
    return booking, beds[0], assignment, _inmate


def test_release_cascade_ends_assignment_and_frees_bed(api):
    """PRD §3.8: "When the booking was `HOUSED`, release additionally cascades: it ends the
    `ACTIVE` housing assignment (moving it to `ENDED`), which frees the bed to `AVAILABLE` and
    increments the bed's `version`, and the freed bed reduces its unit's occupied-bed count."

    Design: Difficulty/transitive_cascade/release_cascade_assignment_bed_unit
    """
    booking, bed, assignment, _inmate = _setup_housed_booking(api)
    validate_success(api.release_booking(booking["id"], f.release_payload("COURT_ORDER"), SUPERVISOR))
    ha = get_success_data(api.get_housing_assignment(assignment["id"], SUPERVISOR))
    assert ha["assignment_status"] == "ENDED", f"got {ha['assignment_status']}"
    beds = get_success_data(api.list_beds(bed["housing_unit_id"], SUPERVISOR))
    freed = next(b for b in beds if b["id"] == bed["id"])
    assert freed["status"] == "AVAILABLE", f"got {freed['status']}"


def test_release_cascade_releases_booking_and_inmate(api):
    """PRD §3.8: "Release drives the booking to the terminal `RELEASED`, sets the person's
    `Inmate.status` to `RELEASED`, and returns every `STORED` property item on the booking to
    `RETURNED`."

    Design: Difficulty/transitive_cascade/release_cascade_assignment_bed_unit
    """
    booking, _bed, _assignment, inmate = _setup_housed_booking(api)
    released = validate_success(api.release_booking(booking["id"], f.release_payload("COURT_ORDER"), SUPERVISOR))
    assert released["booking_status"] == "RELEASED", f"got {released['booking_status']}"
    inmate_now = get_success_data(api.get_inmate(inmate["id"], SUPERVISOR))
    assert inmate_now["status"] == "RELEASED", f"got {inmate_now['status']}"


# ---------------------------------------------------------------------------
# compensating_invariant / bed_capacity_conservation
# ---------------------------------------------------------------------------
def test_bed_occupied_after_assignment(api):
    """PRD §3.3: "A new `HousingAssignment` begins in `assignment_status` `ACTIVE`, sets its bed
    to `OCCUPIED` (incrementing the bed's `version`), and drives the booking from `CLASSIFIED`
    to `HOUSED`."

    Design: Difficulty/compensating_invariant/bed_capacity_conservation
    """
    _inmate, booking = fixtures.create_classified_booking(api, sex="MALE",
                                                          charge_severity="MISDEMEANOR", sentence_days=60)
    _unit, beds = fixtures.create_unit_with_beds(api, "MIN", "MALE", 4, ("A1", "A2"))
    fixtures.house_booking(api, booking["id"], beds[0]["id"], "2026-05-02T10:00:00Z")
    unit_beds = get_success_data(api.list_beds(beds[0]["housing_unit_id"], SUPERVISOR))
    bed1 = next(b for b in unit_beds if b["id"] == beds[0]["id"])
    assert bed1["status"] == "OCCUPIED", f"got {bed1['status']}"


def test_bed_available_after_ending_assignment(api):
    """PRD §3.3: "ending moves the `assignment_status` from `ACTIVE` to `ENDED`, frees the bed
    back to `AVAILABLE` (incrementing the bed's `version`), and returns the booking from
    `HOUSED` to `CLASSIFIED`."

    Design: Difficulty/compensating_invariant/bed_capacity_conservation
    """
    _inmate, booking = fixtures.create_classified_booking(api, sex="MALE",
                                                          charge_severity="MISDEMEANOR", sentence_days=60)
    _unit, beds = fixtures.create_unit_with_beds(api, "MIN", "MALE", 4, ("A1", "A2"))
    assignment = fixtures.house_booking(api, booking["id"], beds[0]["id"], "2026-05-02T10:00:00Z")
    ended = validate_success(api.end_housing_assignment(assignment["id"], CLASSIFICATION))
    assert ended["assignment_status"] == "ENDED", f"got {ended['assignment_status']}"
    unit_beds = get_success_data(api.list_beds(beds[0]["housing_unit_id"], SUPERVISOR))
    bed1 = next(b for b in unit_beds if b["id"] == beds[0]["id"])
    assert bed1["status"] == "AVAILABLE", f"got {bed1['status']}"
