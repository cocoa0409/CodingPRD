"""Assignment proposal safety gates, overlap rules, and the auto-match selector."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_active_incident, register_volunteer, vet_volunteer,
    create_published_request, create_open_shift, propose_assignment,
    propose_accept_confirm_assignment, set_clock, make_volunteer_headers,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
INTAKE = TEST_USERS["intake_headers"]
VET = TEST_USERS["vetting_headers"]
AGENCY = TEST_USERS["agency_headers"]
LOGI = TEST_USERS["logistics_headers"]


def test_propose_volunteer_not_ready_returns_volunteer_not_ready(api):
    """PRD section 3.3: "The volunteer must be `READY`
    (`ERR_VOLUNTEER_NOT_READY`); must hold a `VERIFIED` credential whose
    `skill_code` equals the request's `required_skill` (`ERR_SKILL_MISMATCH`)
    at a class meeting the `min_credential_class`, where `ADVANCED` satisfies a
    `STANDARD` minimum (`ERR_CREDENTIAL_CLASS_INSUFFICIENT`)"

    Design: Corner/validations/propose_volunteer_not_ready_returns_volunteer_not_ready
    """
    incident = create_active_incident(name="Flood Y2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    # CLEARED (vetted) but never marked ready: clearances missing.
    bundle = vet_volunteer(incident["id"], with_clearances=False, mark_ready=False,
                           full_name="Rae Ru")
    volunteer = bundle["volunteer"]
    assert volunteer["status"] == "CLEARED"
    request = create_published_request(incident["id"])
    shift = create_open_shift(incident["id"])
    res = api.create_assignment(
        {"volunteer_id": volunteer["id"], "support_request_id": request["id"],
         "site_shift_id": shift["id"]}, INTAKE)
    validate_error(res, "ERR_VOLUNTEER_NOT_READY")


def test_red_hazard_shift_rejects_standard_credential(api):
    """PRD section 3.3: "a `RED` shift demands an `ADVANCED` qualifying
    credential (`ERR_HAZARD_CREDENTIAL_REQUIRED`)"

    Design: Corner/validations/red_hazard_shift_rejects_standard_credential
    """
    incident = create_active_incident(name="Fire V2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = vet_volunteer(incident["id"], full_name="Ned Noy")["volunteer"]
    request = create_published_request(incident["id"], requesting_agency="County FD",
                                       site_name="Burn Zone")
    shift = create_open_shift(incident["id"], site_name="Burn Zone", hazard_level="RED")
    res = api.create_assignment(
        {"volunteer_id": volunteer["id"], "support_request_id": request["id"],
         "site_shift_id": shift["id"]}, INTAKE)
    validate_error(res, "ERR_HAZARD_CREDENTIAL_REQUIRED")
    # The open RED shift independently drives posture_derivation.
    posture = validate_success(api.get_incident(incident["id"], MGR))
    assert posture["operational_posture"] == "RESTRICTED"


def test_standard_credential_below_advanced_minimum_returns_insufficient(api):
    """PRD section 3.3: "must hold a `VERIFIED` credential whose `skill_code`
    equals the request's `required_skill` (`ERR_SKILL_MISMATCH`) at a class
    meeting the `min_credential_class`, where `ADVANCED` satisfies a `STANDARD`
    minimum (`ERR_CREDENTIAL_CLASS_INSUFFICIENT`)"

    Design: Corner/validations/standard_credential_below_advanced_minimum_returns_insufficient
    """
    incident = create_active_incident(name="Flood W2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = vet_volunteer(incident["id"], full_name="Ora Ong",
                              credential_overrides={"skill_code": "MEDICAL"})["volunteer"]
    request = create_published_request(incident["id"], requesting_agency="County Health",
                                       site_name="Triage Tent", required_skill="MEDICAL",
                                       min_credential_class="ADVANCED")
    shift = create_open_shift(incident["id"], site_name="Triage Tent")
    res = api.create_assignment(
        {"volunteer_id": volunteer["id"], "support_request_id": request["id"],
         "site_shift_id": shift["id"]}, INTAKE)
    validate_error(res, "ERR_CREDENTIAL_CLASS_INSUFFICIENT")


def test_shift_outside_request_site_window_rejected(api):
    """PRD section 3.3: "The shift's `site_name` must equal the request's
    exactly, and the shift window must sit entirely inside the request window —
    starting no earlier than `window_start` and ending no later than
    `window_end` — or the proposal fails with `ERR_SITE_WINDOW_MISMATCH`."

    Design: Corner/validations/shift_outside_request_site_window_rejected
    """
    incident = create_active_incident(name="Fire X2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = vet_volunteer(incident["id"], full_name="Pat Pye")["volunteer"]
    request = create_published_request(incident["id"], site_name="West Field")
    shift = create_open_shift(incident["id"], site_name="East Lot")
    res = api.create_assignment(
        {"volunteer_id": volunteer["id"], "support_request_id": request["id"],
         "site_shift_id": shift["id"]}, INTAKE)
    validate_error(res, "ERR_SITE_WINDOW_MISMATCH")


def test_propose_with_lapsed_background_check_returns_background_check_lapsed(api):
    """PRD section 3.3: "and a `CLEARED` background check whose `expires_at`
    remains in the future must exist (`ERR_BACKGROUND_CHECK_LAPSED`)."

    Design: Corner/errors/propose_with_lapsed_background_check_returns_background_check_lapsed
    """
    incident = create_active_incident(name="Flood N3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    # Credential outlives the 720h background-check validity window.
    volunteer = vet_volunteer(incident["id"], full_name="Fox Fyn",
                              credential_overrides={"expires_at": "2026-10-01T00:00:00Z"}
                              )["volunteer"]
    # The 2026-08-01 clearance ages past 720h at 2026-08-31T00:00:00Z.
    set_clock("2026-09-01T00:00:00Z")
    request = create_published_request(
        incident["id"], window_start="2026-09-05T06:00:00Z",
        window_end="2026-09-05T20:00:00Z")
    shift = create_open_shift(incident["id"], start_at="2026-09-05T08:00:00Z",
                              end_at="2026-09-05T16:00:00Z")
    res = api.create_assignment(
        {"volunteer_id": volunteer["id"], "support_request_id": request["id"],
         "site_shift_id": shift["id"]}, INTAKE)
    validate_error(res, "ERR_BACKGROUND_CHECK_LAPSED")


def _setup_volunteer_occupied_08_to_16(api, incident):
    """READY volunteer CONFIRMED on shift S1 2026-08-10 08:00-16:00.
    Returns (volunteer, request, [shift_ids keyed by window])."""
    volunteer = vet_volunteer(incident["id"])["volunteer"]
    request = create_published_request(incident["id"], headcount_needed=3,
                                       window_end="2026-08-10T23:00:00Z")
    shift1 = create_open_shift(incident["id"], capacity=3)
    propose_accept_confirm_assignment(volunteer, request, shift1)
    return volunteer, request, shift1


def test_adjacent_shift_proposal_is_legal_under_half_open_rule(api):
    """PRD section 3.3: "A shift starting exactly at another's end is merely
    adjacent, and adjacency is legal."

    Design: Difficulty/resource_temporal_overlap/volunteer_shift_overlap_half_open_adjacency_legal
    """
    incident = create_active_incident(name="Flood Omicron")
    volunteer, request, _ = _setup_volunteer_occupied_08_to_16(api, incident)
    adjacent = create_open_shift(incident["id"], capacity=3,
                                 start_at="2026-08-10T16:00:00Z",
                                 end_at="2026-08-10T20:00:00Z")
    res = api.create_assignment(
        {"volunteer_id": volunteer["id"], "support_request_id": request["id"],
         "site_shift_id": adjacent["id"]}, INTAKE)
    created = validate_success(res, 201)
    assert created["status"] == "PROPOSED"


def test_overlapping_shift_proposal_returns_double_booked_shift(api):
    """PRD section 3.3: "a candidate conflicts — `ERR_DOUBLE_BOOKED_SHIFT` —
    whenever its start falls strictly before an occupied interval's end while
    that interval's start falls strictly before the candidate's end."

    Design: Difficulty/resource_temporal_overlap/volunteer_shift_overlap_half_open_adjacency_legal
    """
    incident = create_active_incident(name="Flood Omicron")
    volunteer, request, _ = _setup_volunteer_occupied_08_to_16(api, incident)
    overlapping = create_open_shift(incident["id"], capacity=3,
                                    start_at="2026-08-10T15:00:00Z",
                                    end_at="2026-08-10T17:00:00Z")
    res = api.create_assignment(
        {"volunteer_id": volunteer["id"], "support_request_id": request["id"],
         "site_shift_id": overlapping["id"]}, INTAKE)
    validate_error(res, "ERR_DOUBLE_BOOKED_SHIFT")


def _setup_skill_mismatch_and_overlap(api):
    """Volunteer READY with VERIFIED CHAINSAW/STANDARD, CONFIRMED on a CHAINSAW
    shift 08:00-16:00; second request requires MEDICAL with a 10:00-18:00 shift
    overlapping the first. Returns (volunteer, request2)."""
    incident = create_active_incident(name="Fire Kappa")
    volunteer = vet_volunteer(incident["id"], full_name="Jack Judd",
                              credential_overrides={"skill_code": "CHAINSAW"})["volunteer"]
    request1 = create_published_request(incident["id"], site_name="Ridge Road",
                                        required_skill="CHAINSAW")
    shift1 = create_open_shift(incident["id"], site_name="Ridge Road")
    propose_accept_confirm_assignment(volunteer, request1, shift1)
    request2 = create_published_request(incident["id"], requesting_agency="County Health",
                                        site_name="Ridge Road", required_skill="MEDICAL",
                                        window_end="2026-08-10T23:00:00Z")
    return incident, volunteer, request2


def test_skill_mismatch_wins_over_shift_overlap(api):
    """PRD section 2.11: "Every request is validated against an ordered
    pipeline, and a request that would fail several checks reports the earliest
    failing stage."
    PRD section 2.11: "9. Assignment safety checks: readiness, skill match,
    credential class, hazard gating, and background-check freshness (§3.3)."
    PRD section 2.11: "12. Temporal interval rules: double-booking, vehicle
    turnaround, the check-in window, no-show timing, and roster-opening timing
    (§3.3 and §3.4)."

    Design: Difficulty/priority_pair_validation_conflict/propose_with_skill_mismatch_and_shift_overlap_safety_wins
    """
    incident, volunteer, request2 = _setup_skill_mismatch_and_overlap(api)
    overlapping = create_open_shift(incident["id"], site_name="Ridge Road",
                                    start_at="2026-08-10T10:00:00Z",
                                    end_at="2026-08-10T18:00:00Z")
    res = api.create_assignment(
        {"volunteer_id": volunteer["id"], "support_request_id": request2["id"],
         "site_shift_id": overlapping["id"]}, INTAKE)
    validate_error(res, "ERR_SKILL_MISMATCH")
    # The failed proposal leaves no assignment behind on the second request.
    data, _ = validate_paginated(
        api.list_assignments(MGR, params={"support_request_id": request2["id"]}))
    assert data == []


def test_skill_mismatch_also_fires_without_any_overlap(api):
    """PRD section 3.3: "must hold a `VERIFIED` credential whose `skill_code`
    equals the request's `required_skill` (`ERR_SKILL_MISMATCH`)"

    Design: Difficulty/priority_pair_validation_conflict/propose_with_skill_mismatch_and_shift_overlap_safety_wins
    """
    incident, volunteer, request2 = _setup_skill_mismatch_and_overlap(api)
    # Same-day adjacent shift (16:00-18:00 touches the confirmed shift's end):
    # no temporal conflict, so only the skill rule can fail.
    far = create_open_shift(incident["id"], site_name="Ridge Road",
                            start_at="2026-08-10T16:00:00Z",
                            end_at="2026-08-10T18:00:00Z")
    res = api.create_assignment(
        {"volunteer_id": volunteer["id"], "support_request_id": request2["id"],
         "site_shift_id": far["id"]}, INTAKE)
    error = validate_error(res, "ERR_SKILL_MISMATCH")
    assert error["error_id"] == "ERR_SKILL_MISMATCH"


def test_auto_match_empty_pool_returns_no_eligible_placements(api):
    """PRD section 3.3: "If not a single placement can be made, the whole call
    is rejected with `ERR_NO_ELIGIBLE_PLACEMENTS` (HTTP 422) and the request is
    left untouched."

    Design: Corner/endpoints/auto_match_empty_pool_returns_no_eligible_placements
    """
    incident = create_active_incident(name="Fire G3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    request = create_published_request(incident["id"], headcount_needed=2)
    create_open_shift(incident["id"])
    res = api.auto_match(request["id"], INTAKE)
    validate_error(res, "ERR_NO_ELIGIBLE_PLACEMENTS", expected_status=422)
    after = validate_success(api.get_support_request(request["id"], MGR))
    assert after["status"] == "OPEN"


def test_auto_match_ranks_fewest_verified_hours_then_earliest_created(api):
    """PRD section 3.3: "Candidates are ranked by `verified_hours_total`
    ascending, then `created_at` ascending, then last name and first name in
    ascending lexicographic order; an `id` is never consulted."

    Design: Corner/cross_cutting_layers/auto_match_ranks_fewest_verified_hours_then_earliest_created
    """
    from test_helpers import (create_verified_entry, issue_ppe,
                              check_in_and_complete, propose_accept_confirm_assignment,
                              create_hour_entry_payload)
    incident = create_active_incident(name="Fire Z3",
                                      ppe_stock={"GLOVES": 4, "MASK": 4, "HARD_HAT": 4,
                                                 "VEST": 4, "GOGGLES": 4})
    # V1: created first, earns 8.00 verified hours on 2026-08-09.
    v1 = vet_volunteer(incident["id"], full_name="Ryu Rho")["volunteer"]
    request0 = create_published_request(incident["id"], site_name="Old Mill",
                                        window_start="2026-08-09T06:00:00Z",
                                        window_end="2026-08-09T20:00:00Z")
    shift0 = create_open_shift(incident["id"], site_name="Old Mill",
                               start_at="2026-08-09T08:00:00Z",
                               end_at="2026-08-09T16:00:00Z")
    assignment0 = propose_accept_confirm_assignment(v1, request0, shift0)
    issue_ppe(v1["id"])
    assignment0 = check_in_and_complete(assignment0, v1["id"], "2026-08-09T08:00:00Z")
    entry0 = validate_success(api.create_hour_entry(
        create_hour_entry_payload(assignment0["id"], work_date="2026-08-09", hours=8.0),
        make_volunteer_headers(v1["id"])), 201)
    validate_success(api.verify_hour_entry(entry0["id"], TEST_USERS["supervisor_headers"]))
    # V2: created second, zero verified hours.
    v2 = vet_volunteer(incident["id"], full_name="Sio Sao")["volunteer"]
    # Fresh request: one headcount on 2026-08-12.
    request = create_published_request(incident["id"], headcount_needed=1,
                                       window_start="2026-08-12T06:00:00Z",
                                       window_end="2026-08-12T20:00:00Z")
    create_open_shift(incident["id"], start_at="2026-08-12T08:00:00Z",
                      end_at="2026-08-12T16:00:00Z", capacity=5)
    result = validate_success(api.auto_match(request["id"], INTAKE), 201)
    assert result["proposed_count"] == 1
    assert result["remaining_need"] == 0
    assert result["request_status"] == "MATCHING"
    data, _ = validate_paginated(
        api.list_assignments(MGR, params={"support_request_id": request["id"]}))
    assert len(data) == 1
    assert data[0]["volunteer_id"] == v2["id"], (
        "verified_hours_total 0.0 outranks 8.0 despite V1's earlier created_at")
    assert data[0]["origin"] == "AUTO_MATCH"
