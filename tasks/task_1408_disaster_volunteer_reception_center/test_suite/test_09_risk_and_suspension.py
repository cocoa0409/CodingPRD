"""Risk scoring and decay, substantiation cascades, suspension and
reinstatement, withdrawal, demobilization gates, and shift-cancel cascades."""
from test_helpers import (
    validate_success, validate_error,
    create_active_incident, register_volunteer, vet_volunteer,
    create_published_request, create_open_shift, propose_assignment,
    propose_accept_assignment, propose_accept_confirm_assignment, issue_ppe,
    create_trip_payload, create_seat_booking_payload, create_credential_payload,
    create_background_check_payload, file_and_substantiate_report, set_clock,
    make_volunteer_headers, TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
INTAKE = TEST_USERS["intake_headers"]
VET = TEST_USERS["vetting_headers"]
LOGI = TEST_USERS["logistics_headers"]
SITE = TEST_USERS["supervisor_headers"]
RISK = TEST_USERS["risk_headers"]


def _medium_substantiated_volunteer(api):
    """REGISTERED volunteer with one MEDIUM report substantiated at
    2026-08-01T00:00:00Z (15 points). Returns volunteer id."""
    incident = create_active_incident(name="Flood Beta")
    volunteer = register_volunteer(incident["id"], full_name="Bob Baker")
    file_and_substantiate_report(volunteer["id"], "MEDIUM", category="MISCONDUCT",
                                 description="Left staging area without sign-out")
    return volunteer["id"]


def test_current_risk_score_halves_in_the_second_decay_band(api):
    """PRD section 3.6: "The `current_risk_score` decays in steps: a source
    counts in full while its age is under 168 hours (seven days), counts at
    half — computed by floor division of its points by two — from 168 hours up
    to but not including 720 hours (thirty days), and counts as zero at or
    beyond 720 hours, with the total never falling below zero."

    Design: Difficulty/dual_variant_calc/risk_score_current_decays_to_zero_while_lifetime_persists
    """
    volunteer_id = _medium_substantiated_volunteer(api)
    set_clock("2026-08-10T00:00:00Z")  # age 216h: floor(15 / 2)
    mid = validate_success(api.get_volunteer(volunteer_id, MGR))
    assert mid["current_risk_score"] == 7
    assert mid["lifetime_risk_score"] == 15


def test_current_risk_score_zeroes_after_720h_while_lifetime_persists(api):
    """PRD section 3.6: "The `lifetime_risk_score` sums the same sources with
    no decay, forever; identical inputs therefore always leave the lifetime
    score at least the current one, strictly greater once any source passes 168
    hours."

    Design: Difficulty/dual_variant_calc/risk_score_current_decays_to_zero_while_lifetime_persists
    """
    volunteer_id = _medium_substantiated_volunteer(api)
    set_clock("2026-08-31T01:00:00Z")  # age 721h: zeroed for the current variant
    end = validate_success(api.get_volunteer(volunteer_id, MGR))
    assert end["current_risk_score"] == 0
    assert end["lifetime_risk_score"] == 15


def _setup_suspended_with_fresh_check(api):
    """READY volunteer suspended, with a fresh REQUESTED background check
    opened while SUSPENDED. Returns (volunteer, check)."""
    incident = create_active_incident(name="Flood Epsilon")
    volunteer = vet_volunteer(incident["id"], full_name="Eve Egan",
                              credential_overrides={"skill_code": "SHELTER_OPS"})["volunteer"]
    validate_success(api.suspend_volunteer(volunteer["id"], RISK))
    check = validate_success(api.create_background_check(
        create_background_check_payload(volunteer["id"]), VET), 201)
    return volunteer, check


def test_reinstate_returns_suspended_volunteer_to_vetting(api):
    """PRD section 3.6: "Reinstatement returns a `SUSPENDED` volunteer to
    `VETTING` for fresh vetting: it requires a background check already
    standing in `REQUESTED` for the volunteer (otherwise `ERR_INVALID_STATE`)
    and a `lifetime_risk_score` below 100 — at 100 or more the volunteer is
    blacklisted and reinstatement fails with `ERR_VOLUNTEER_BLACKLISTED` (HTTP
    403)."

    Design: Difficulty/non_linear_state_machine/volunteer_suspension_revetting_cycle_returns_to_ready
    """
    volunteer, _ = _setup_suspended_with_fresh_check(api)
    reinstated = validate_success(api.reinstate_volunteer(volunteer["id"], RISK))
    assert reinstated["status"] == "VETTING"


def test_revetting_cycle_completes_back_to_ready(api):
    """PRD section 3.2: "promotion from `VETTING` to `CLEARED` occurs as soon
    as the volunteer holds both a `CLEARED` background check whose `expires_at`
    is still in the future and at least one `VERIFIED` credential"
    PRD section 3.2: "Marking a volunteer ready, an `IntakeCoordinator` action
    from `CLEARED`, requires all four prerequisites to hold at once"

    Design: Difficulty/non_linear_state_machine/volunteer_suspension_revetting_cycle_returns_to_ready
    """
    volunteer, check = _setup_suspended_with_fresh_check(api)
    validate_success(api.reinstate_volunteer(volunteer["id"], RISK))
    validate_success(api.clear_background_check(check["id"], VET))
    cleared = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert cleared["status"] == "CLEARED", (
        "auto-promotion re-fires: the still-VERIFIED credential satisfies it")
    ready = validate_success(api.mark_ready(volunteer["id"], INTAKE))
    assert ready["status"] == "READY"


def _setup_suspension_cascade(api):
    """READY volunteer (current risk 20 from LOW+MEDIUM), CONFIRMED assignment
    (request FILLED headcount 1, shift LOCKED capacity 1), seat BOOKED on a
    trip; a HIGH report filed. Returns ids dict."""
    incident = create_active_incident(name="Flood Eta")
    volunteer = vet_volunteer(incident["id"], full_name="Gail Gow")["volunteer"]
    file_and_substantiate_report(volunteer["id"], "LOW", description="late arrival")
    file_and_substantiate_report(volunteer["id"], "MEDIUM", category="MISCONDUCT",
                                 occurred_at="2026-08-01T01:00:00Z",
                                 description="ignored staging rules")
    request = create_published_request(incident["id"], site_name="East Lot")
    shift = create_open_shift(incident["id"], site_name="East Lot", capacity=1)
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    trip = validate_success(api.create_trip(
        create_trip_payload(incident["id"], shift["id"], vehicle_id="BUS-7"),
        LOGI), 201)
    booking = validate_success(api.create_seat_booking(
        create_seat_booking_payload(trip["id"], assignment["id"]), LOGI), 201)
    from test_helpers import create_risk_report_payload
    high = validate_success(api.create_risk_report(
        create_risk_report_payload(volunteer["id"], severity="HIGH",
                                   category="SAFETY_VIOLATION",
                                   description="removed PPE in hot zone",
                                   occurred_at="2026-08-01T02:00:00Z"), SITE), 201)
    return {"incident": incident, "volunteer": volunteer, "request": request,
            "shift": shift, "assignment": assignment, "trip": trip,
            "booking": booking, "report": high}


def test_substantiation_past_threshold_auto_suspends_and_cancels_work(api):
    """PRD section 3.6: "immediately after a substantiation, if it has reached
    at least 50 while the volunteer is `CLEARED`, `READY`, or `DEPLOYED`, the
    system suspends the volunteer automatically."
    PRD section 3.6: "First, every assignment of the volunteer in `PROPOSED`,
    `ACCEPTED`, or `CONFIRMED` is cancelled, and every `CHECKED_IN` assignment
    is recalled. Second, for each cancelled or recalled assignment the
    volunteer's `committed_hours` are released and the parent request's
    `filled_count` and the shift's `rostered_count` are recomputed with the
    usual regressions"

    Design: Difficulty/transitive_cascade/risk_substantiation_triggers_suspension_cascade_depth5
    """
    ids = _setup_suspension_cascade(api)
    validate_success(api.substantiate_risk_report(ids["report"]["id"], RISK))
    volunteer = validate_success(api.get_volunteer(ids["volunteer"]["id"], MGR))
    assert volunteer["current_risk_score"] == 50  # 5 + 15 + 30, all inside 168h
    assert volunteer["status"] == "SUSPENDED"
    assert volunteer["committed_hours"] == 0.0
    assignment = validate_success(api.get_assignment(ids["assignment"]["id"], MGR))
    assert assignment["status"] == "CANCELLED"


def test_substantiation_cascade_regresses_request_shift_and_seats(api):
    """PRD section 3.6: "`FILLED` to `MATCHING` when fills drop below
    headcount, `MATCHING` to `OPEN` when no fills and no `PROPOSED` or
    `ACCEPTED` assignments remain, and a `LOCKED` shift reopening below
    capacity. Third, every `BOOKED` or `BOARDED` seat booking of the volunteer
    is cancelled and each owning trip's `booked_seats` recomputed."

    Design: Difficulty/transitive_cascade/risk_substantiation_triggers_suspension_cascade_depth5
    """
    ids = _setup_suspension_cascade(api)
    validate_success(api.substantiate_risk_report(ids["report"]["id"], RISK))
    booking = validate_success(api.get_seat_booking(ids["booking"]["id"], MGR))
    assert booking["status"] == "CANCELLED"
    trip = validate_success(api.get_trip(ids["trip"]["id"], MGR))
    assert trip["booked_seats"] == 0
    request = validate_success(api.get_support_request(ids["request"]["id"], MGR))
    assert request["status"] == "OPEN"
    assert request["filled_count"] == 0
    shift = validate_success(api.get_shift(ids["shift"]["id"], MGR))
    assert shift["status"] == "OPEN_FOR_ROSTER"
    assert shift["rostered_count"] == 0


def _setup_shift_cancel_cascade(api):
    """READY volunteer CONFIRMED (request FILLED, headcount 1), SCHEDULED trip
    on the shift with the volunteer's seat BOOKED. Returns ids dict."""
    incident = create_active_incident(name="Fire Theta")
    volunteer = vet_volunteer(incident["id"], full_name="Hank Hale")["volunteer"]
    request = create_published_request(incident["id"], site_name="West Field")
    shift = create_open_shift(incident["id"], site_name="West Field", capacity=2)
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    trip = validate_success(api.create_trip(
        create_trip_payload(incident["id"], shift["id"], vehicle_id="VAN-3",
                            seat_capacity=8), LOGI), 201)
    booking = validate_success(api.create_seat_booking(
        create_seat_booking_payload(trip["id"], assignment["id"]), LOGI), 201)
    return {"incident": incident, "volunteer": volunteer, "request": request,
            "shift": shift, "assignment": assignment, "trip": trip, "booking": booking}


def test_shift_cancel_cancels_assignment_and_regresses_request(api):
    """PRD section 3.3: "first, each of its assignments in `PROPOSED`,
    `ACCEPTED`, or `CONFIRMED` is cancelled and each `CHECKED_IN` assignment is
    recalled, releasing committed hours and recomputing `filled_count` and
    `rostered_count` with the usual regressions"

    Design: Difficulty/transitive_cascade/shift_cancel_triggers_release_cascade_depth4
    """
    ids = _setup_shift_cancel_cascade(api)
    validate_success(api.cancel_shift(ids["shift"]["id"], LOGI))
    assignment = validate_success(api.get_assignment(ids["assignment"]["id"], MGR))
    assert assignment["status"] == "CANCELLED"
    volunteer = validate_success(api.get_volunteer(ids["volunteer"]["id"], MGR))
    assert volunteer["committed_hours"] == 0.0
    request = validate_success(api.get_support_request(ids["request"]["id"], MGR))
    assert request["status"] == "OPEN"


def test_shift_cancel_cascades_to_trips_and_their_bookings(api):
    """PRD section 3.3: "second, every `SCHEDULED` trip ferrying to that shift
    is cancelled, while `DEPARTED` trips run on unaffected; third, every
    `BOOKED` or `BOARDED` seat booking on those trips is cancelled with each
    trip's `booked_seats` recomputed; fourth, the incident's posture is
    re-derived."

    Design: Difficulty/transitive_cascade/shift_cancel_triggers_release_cascade_depth4
    """
    ids = _setup_shift_cancel_cascade(api)
    validate_success(api.cancel_shift(ids["shift"]["id"], LOGI))
    trip = validate_success(api.get_trip(ids["trip"]["id"], MGR))
    assert trip["status"] == "CANCELLED"
    assert trip["booked_seats"] == 0
    booking = validate_success(api.get_seat_booking(ids["booking"]["id"], MGR))
    assert booking["status"] == "CANCELLED"


def test_blacklisted_volunteer_cannot_reinstate(api):
    """PRD section 3.6: "Reinstatement returns a `SUSPENDED` volunteer to
    `VETTING` for fresh vetting: it requires a background check already
    standing in `REQUESTED` for the volunteer (otherwise `ERR_INVALID_STATE`)
    and a `lifetime_risk_score` below 100 — at 100 or more the volunteer is
    blacklisted and reinstatement fails with `ERR_VOLUNTEER_BLACKLISTED` (HTTP
    403)."

    Design: Corner/validations/blacklisted_volunteer_cannot_reinstate
    """
    incident = create_active_incident(name="Flood C3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = vet_volunteer(incident["id"], full_name="Val Voe")["volunteer"]
    # CRITICAL substantiation auto-suspends at current 60 >= 50.
    file_and_substantiate_report(volunteer["id"], "CRITICAL",
                                 category="SAFETY_VIOLATION",
                                 description="entered collapse zone")
    file_and_substantiate_report(volunteer["id"], "HIGH",
                                 category="SAFETY_VIOLATION",
                                 occurred_at="2026-08-01T01:00:00Z",
                                 description="removed barricade")
    file_and_substantiate_report(volunteer["id"], "MEDIUM", category="MISCONDUCT",
                                 occurred_at="2026-08-01T02:00:00Z",
                                 description="verbal altercation")
    validate_success(api.create_background_check(
        create_background_check_payload(volunteer["id"]), VET), 201)
    res = api.reinstate_volunteer(volunteer["id"], RISK)
    validate_error(res, "ERR_VOLUNTEER_BLACKLISTED", expected_status=403)
    after = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert after["lifetime_risk_score"] == 105
    assert after["status"] == "SUSPENDED"


def test_demobilize_with_open_assignment_returns_open_assignments(api):
    """PRD section 3.6: "It requires that no assignment of the volunteer remain
    in `PROPOSED`, `ACCEPTED`, `CONFIRMED`, or `CHECKED_IN`
    (`ERR_OPEN_ASSIGNMENTS`) and that no PPE issuance of the volunteer still be
    `ISSUED` (`ERR_UNRETURNED_PPE`)."

    Design: Corner/validations/demobilize_with_open_assignment_returns_open_assignments
    """
    incident = create_active_incident(name="Fire Z2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = vet_volunteer(incident["id"], full_name="Sid Suh")["volunteer"]
    request = create_published_request(incident["id"])
    shift = create_open_shift(incident["id"])
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    res = api.demobilize_volunteer(volunteer["id"], MGR)
    validate_error(res, "ERR_OPEN_ASSIGNMENTS")
    validate_success(api.cancel_assignment(assignment["id"], INTAKE))
    demobilized = validate_success(api.demobilize_volunteer(volunteer["id"], MGR))
    assert demobilized["status"] == "DEMOBILIZED"


def test_demobilize_with_issued_ppe_returns_unreturned_ppe(api):
    """PRD section 3.6: "It requires that no assignment of the volunteer remain
    in `PROPOSED`, `ACCEPTED`, `CONFIRMED`, or `CHECKED_IN`
    (`ERR_OPEN_ASSIGNMENTS`) and that no PPE issuance of the volunteer still be
    `ISSUED` (`ERR_UNRETURNED_PPE`)."
    PRD section 3.4: "Closing an issuance takes an `outcome` of `RETURNED`,
    `DAMAGED`, or `LOST`: `RETURNED` restores the issued quantity to the
    incident's stock as a compensating credit, while `DAMAGED` and `LOST` do
    not restore it; all three stamp `closed_at` and are terminal."

    Design: Corner/validations/demobilize_with_issued_ppe_returns_unreturned_ppe
    """
    incident = create_active_incident(name="Flood A3",
                                      ppe_stock={"GLOVES": 2, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = vet_volunteer(incident["id"], full_name="Tess To")["volunteer"]
    ppe = issue_ppe(volunteer["id"], quantity=2)
    res = api.demobilize_volunteer(volunteer["id"], MGR)
    validate_error(res, "ERR_UNRETURNED_PPE")
    validate_success(api.close_ppe_issuance(ppe["id"], {"outcome": "LOST"}, LOGI))
    demobilized = validate_success(api.demobilize_volunteer(volunteer["id"], MGR))
    assert demobilized["status"] == "DEMOBILIZED"
    assert demobilized["recognition_tier"] == "NONE"
    incident_after = validate_success(api.get_incident(incident["id"], MGR))
    assert incident_after["ppe_stock"]["GLOVES"] == 0, "LOST does not restore stock"
