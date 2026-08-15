"""Hour accounting, federal cost-share rollups, and recognition tiers."""
from test_helpers import (
    validate_success, validate_error,
    create_active_incident, vet_volunteer, create_published_request,
    create_open_shift, propose_accept_confirm_assignment, issue_ppe,
    refresh_briefing, set_clock, check_in_and_complete,
    create_completed_assignment_with_entry, create_verified_entry,
    create_hour_entry_payload, create_shift_payload,
    file_and_substantiate_report, make_volunteer_headers,
    assert_incident_share_invariants, TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
INTAKE = TEST_USERS["intake_headers"]
LOGI = TEST_USERS["logistics_headers"]
SITE = TEST_USERS["supervisor_headers"]


def _setup_one_verified_one_submitted(api):
    """Incident with a VERIFIED 8.00h STANDARD entry (22400 cents) and a
    SUBMITTED 3.75h STANDARD entry (10500 cents). Returns incident id."""
    incident = create_active_incident(name="Flood Alpha",
                                      ppe_stock={"GLOVES": 10, "MASK": 10, "HARD_HAT": 5,
                                                 "VEST": 5, "GOGGLES": 5})
    volunteer = vet_volunteer(incident["id"], full_name="Ann Able")["volunteer"]
    request1 = create_published_request(incident["id"])
    shift1 = create_open_shift(incident["id"], capacity=3)
    create_verified_entry(volunteer, request1, shift1, work_date="2026-08-10",
                          hours=8.0, checkin_at="2026-08-10T08:00:00Z")
    request2 = create_published_request(
        incident["id"], window_start="2026-08-11T06:00:00Z",
        window_end="2026-08-11T20:00:00Z")
    shift2 = create_open_shift(incident["id"], start_at="2026-08-11T08:00:00Z",
                               end_at="2026-08-11T11:45:00Z", capacity=3)
    create_completed_assignment_with_entry(
        volunteer, request2, shift2, work_date="2026-08-11", hours=3.75,
        checkin_at="2026-08-11T08:00:00Z")
    return incident["id"]


def test_provisional_cost_share_includes_unverified_entry(api):
    """PRD section 3.5: "The provisional view, `provisional_cost_share_cents`,
    sums `entry_value_cents` over every hour entry of the incident's
    assignments in `SUBMITTED`, `DISPUTED`, or `VERIFIED` — the
    documentation-in-progress view used during the incident."

    Design: Difficulty/dual_variant_calc/cost_share_provisional_includes_unverified_but_verified_excludes_it
    """
    incident_id = _setup_one_verified_one_submitted(api)
    incident = validate_success(api.get_incident(incident_id, MGR))
    assert incident["provisional_cost_share_cents"] == 32900
    assert_incident_share_invariants(incident)


def test_verified_cost_share_excludes_unverified_and_splits_shares(api):
    """PRD section 3.5: "The audited view, `verified_cost_share_cents`, sums
    only `VERIFIED` entries and underpins federal documentation and close-out"
    PRD section 3.5: "`federal_share_cents` is the verified total multiplied by
    0.75 and rounded half-up to whole cents; `state_share_cents` is the
    verified total multiplied by 0.125 and rounded half-up; and
    `local_share_cents` is whatever remains — the verified total minus the
    federal share minus the state share — absorbing the rounding remainder
    rather than being independently rounded."

    Design: Difficulty/dual_variant_calc/cost_share_provisional_includes_unverified_but_verified_excludes_it
    """
    incident_id = _setup_one_verified_one_submitted(api)
    incident = validate_success(api.get_incident(incident_id, MGR))
    assert incident["verified_cost_share_cents"] == 22400
    assert incident["provisional_cost_share_cents"] != incident["verified_cost_share_cents"]
    assert incident["federal_share_cents"] == 16800
    assert incident["state_share_cents"] == 2800
    assert incident["local_share_cents"] == 2800


def _setup_overtime_advanced_entry(api):
    """10.50h shift on AMBER with an ADVANCED CHAINSAW credential; entry 10.5h.
    Returns (incident_id, entry)."""
    incident = create_active_incident(name="Wind Gamma")
    volunteer = vet_volunteer(
        incident["id"], full_name="Cara Cruz",
        credential_overrides={"skill_code": "CHAINSAW",
                              "credential_class": "ADVANCED"})["volunteer"]
    # The rate follows the CREDENTIAL class, not the request minimum.
    request = create_published_request(
        incident["id"], requesting_agency="County OES", site_name="Ridge Road",
        required_skill="CHAINSAW", min_credential_class="STANDARD",
        window_end="2026-08-10T22:00:00Z")
    shift = create_open_shift(incident["id"], site_name="Ridge Road",
                              hazard_level="AMBER", end_at="2026-08-10T18:30:00Z")
    assignment, entry = create_completed_assignment_with_entry(
        volunteer, request, shift, work_date="2026-08-10", hours=10.5,
        checkin_at="2026-08-10T08:00:00Z", ppe_item="HARD_HAT")
    return incident["id"], entry


def test_entry_value_overtime_split_with_class_rate(api):
    """PRD section 3.5: "Its `credential_class` fixes the hourly rate: 2800
    cents per hour for `STANDARD`, 4600 cents for `ADVANCED`. Hours up to a
    threshold of 8.0 are normal hours and any remainder is overtime. The value
    is the normal hours times the rate, plus the overtime hours times the rate
    times one and a half, rounded half-up to a whole cent"

    Design: Difficulty/combinatorial_formula/entry_value_overtime_split_with_class_rate (mode a)
    """
    _, entry = _setup_overtime_advanced_entry(api)
    # 8 * 4600 + 2.5 * 4600 * 1.5 = 36800 + 17250
    assert entry["entry_value_cents"] == 54050
    assert entry["entry_value_cents"] != 48300, "flat-rate misread"
    assert entry["entry_value_cents"] != 72450, "all-overtime misread"


def test_entry_value_rolls_into_verified_total(api):
    """PRD section 3.5: "Verifying a `SUBMITTED` entry — a `SiteSupervisor`
    action — stamps `verified_by_user_id`, adds the entry's `hours` to the
    volunteer's `verified_hours_total`, and recomputes the incident rollups as
    the entry joins the verified-only input set it was already provisionally
    inside."

    Design: Difficulty/combinatorial_formula/entry_value_overtime_split_with_class_rate (mode a)
    """
    incident_id, entry = _setup_overtime_advanced_entry(api)
    validate_success(api.verify_hour_entry(entry["id"], SITE))
    incident = validate_success(api.get_incident(incident_id, MGR))
    assert incident["verified_cost_share_cents"] == 54050
    assert incident["provisional_cost_share_cents"] == 54050


def _setup_single_verified_3_75h(api):
    """One VERIFIED 3.75h STANDARD entry: verified total exactly 10500 cents."""
    incident = create_active_incident(name="Fire Delta")
    volunteer = vet_volunteer(incident["id"], full_name="Dan Doyle")["volunteer"]
    request = create_published_request(incident["id"], site_name="South Yard")
    shift = create_open_shift(incident["id"], site_name="South Yard",
                              end_at="2026-08-10T11:45:00Z")
    create_verified_entry(volunteer, request, shift, work_date="2026-08-10",
                          hours=3.75, checkin_at="2026-08-10T08:00:00Z",
                          ppe_item="VEST")
    return incident["id"]


def test_share_split_federal_and_state_rounded_half_up(api):
    """PRD section 3.5: "`federal_share_cents` is the verified total multiplied
    by 0.75 and rounded half-up to whole cents; `state_share_cents` is the
    verified total multiplied by 0.125 and rounded half-up"

    Design: Difficulty/combinatorial_formula/share_split_rounding_local_absorbs_remainder (mode b)
    """
    incident = validate_success(api.get_incident(_setup_single_verified_3_75h(api), MGR))
    assert incident["verified_cost_share_cents"] == 10500
    assert incident["federal_share_cents"] == 7875
    assert incident["state_share_cents"] == 1313  # round_half_up(1312.5)


def test_local_share_absorbs_rounding_remainder(api):
    """PRD section 3.5: "and `local_share_cents` is whatever remains — the
    verified total minus the federal share minus the state share — absorbing
    the rounding remainder rather than being independently rounded."

    Design: Difficulty/combinatorial_formula/share_split_rounding_local_absorbs_remainder (mode b)
    """
    incident = validate_success(api.get_incident(_setup_single_verified_3_75h(api), MGR))
    assert incident["local_share_cents"] == 1312  # 10500 - 7875 - 1313, not 1313
    assert (incident["federal_share_cents"] + incident["state_share_cents"]
            + incident["local_share_cents"]) == incident["verified_cost_share_cents"]


def test_hour_entry_with_non_quarter_increment_returns_invalid_request(api):
    """PRD section 2.11: "Request-body shape: required fields present, types
    correct, enum members valid, `quantity` and `headcount_needed` at least 1,
    hours positive, at most 16, and a multiple of 0.25, end instants strictly
    after start instants, the PPE stock object carrying exactly its five keys —
    any violation is `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/validations/hour_entry_with_non_quarter_increment_returns_invalid_request
    """
    incident = create_active_incident(name="Fire U2",
                                      ppe_stock={"GLOVES": 2, "MASK": 2, "HARD_HAT": 2,
                                                 "VEST": 2, "GOGGLES": 2})
    volunteer = vet_volunteer(incident["id"], full_name="Mia Moy")["volunteer"]
    request = create_published_request(incident["id"])
    shift = create_open_shift(incident["id"])
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    issue_ppe(volunteer["id"])
    assignment = check_in_and_complete(assignment, volunteer["id"], "2026-08-10T08:00:00Z")
    res = api.create_hour_entry(
        create_hour_entry_payload(assignment["id"], work_date="2026-08-10", hours=1.3),
        make_volunteer_headers(volunteer["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_duplicate_hour_entry_same_work_date_rejected(api):
    """PRD section 3.5: "At most one entry not in `REJECTED_FINAL` may exist
    for the same assignment and work date, with a duplicate refused as
    `ERR_DUPLICATE_HOUR_ENTRY`."

    Design: Corner/validations/duplicate_hour_entry_same_work_date_rejected
    """
    incident = create_active_incident(name="Flood T2",
                                      ppe_stock={"GLOVES": 2, "MASK": 2, "HARD_HAT": 2,
                                                 "VEST": 2, "GOGGLES": 2})
    volunteer = vet_volunteer(incident["id"], full_name="Leo Lai")["volunteer"]
    request = create_published_request(incident["id"])
    shift = create_open_shift(incident["id"])
    assignment, _ = create_completed_assignment_with_entry(
        volunteer, request, shift, work_date="2026-08-10", hours=8.0,
        checkin_at="2026-08-10T08:00:00Z")
    res = api.create_hour_entry(
        create_hour_entry_payload(assignment["id"], work_date="2026-08-10", hours=2.0),
        make_volunteer_headers(volunteer["id"]))
    validate_error(res, "ERR_DUPLICATE_HOUR_ENTRY")


def test_hour_entry_dispute_resubmit_second_dispute_locks_rejected_final(api):
    """PRD section 3.5: "A second dispute — possible only on a resubmitted
    entry, one whose `dispute_count` already stands at 1 — settles the matter:
    the entry flips to terminal `REJECTED_FINAL`, `dispute_count` becomes 2,
    the latest `reason` is kept, and the entry's value leaves the provisional
    total, `REJECTED_FINAL` being the only status excluded from it."

    Design: Corner/state_machines/hour_entry_dispute_resubmit_second_dispute_locks_rejected_final
    """
    incident = create_active_incident(name="Fire G2",
                                      ppe_stock={"GLOVES": 3, "MASK": 3, "HARD_HAT": 3,
                                                 "VEST": 3, "GOGGLES": 3})
    volunteer = vet_volunteer(incident["id"], full_name="Zoe Zahn")["volunteer"]
    request = create_published_request(incident["id"])
    shift = create_open_shift(incident["id"])
    _, entry = create_completed_assignment_with_entry(
        volunteer, request, shift, work_date="2026-08-10", hours=8.0,
        checkin_at="2026-08-10T08:00:00Z")
    disputed = validate_success(api.dispute_hour_entry(
        entry["id"], {"reason": "hours look high"}, SITE))
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_count"] == 1
    resubmitted = validate_success(api.resubmit_hour_entry(
        entry["id"], {"hours": 7.75}, make_volunteer_headers(volunteer["id"])))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["entry_value_cents"] == 21700  # 7.75 * 2800, recomputed
    final = validate_success(api.dispute_hour_entry(
        entry["id"], {"reason": "still unverified by site log"}, SITE))
    assert final["status"] == "REJECTED_FINAL"
    assert final["dispute_count"] == 2
    incident_after = validate_success(api.get_incident(incident["id"], MGR))
    assert incident_after["provisional_cost_share_cents"] == 0


def test_complete_request_with_submitted_hours_returns_hours_unresolved(api):
    """PRD section 3.3: "Completing a request — from `MATCHING` or `FILLED` —
    demands that none of its assignments remain in `PROPOSED`, `ACCEPTED`,
    `CONFIRMED`, or `CHECKED_IN` (`ERR_OPEN_ASSIGNMENTS`) and that no hour
    entry on those assignments sit in `SUBMITTED` or `DISPUTED`
    (`ERR_HOURS_UNRESOLVED`); completion stamps the request `COMPLETED` and
    re-derives posture."

    Design: Corner/validations/complete_request_with_submitted_hours_returns_hours_unresolved
    """
    incident = create_active_incident(name="Fire B3",
                                      ppe_stock={"GLOVES": 2, "MASK": 2, "HARD_HAT": 2,
                                                 "VEST": 2, "GOGGLES": 2})
    volunteer = vet_volunteer(incident["id"], full_name="Uli Ung")["volunteer"]
    request = create_published_request(incident["id"])
    shift = create_open_shift(incident["id"])
    _, entry = create_completed_assignment_with_entry(
        volunteer, request, shift, work_date="2026-08-10", hours=8.0,
        checkin_at="2026-08-10T08:00:00Z")
    res = api.complete_support_request(request["id"], TEST_USERS["agency_headers"])
    validate_error(res, "ERR_HOURS_UNRESOLVED")
    validate_success(api.verify_hour_entry(entry["id"], SITE))
    completed = validate_success(api.complete_support_request(
        request["id"], TEST_USERS["agency_headers"]))
    assert completed["status"] == "COMPLETED"


def test_recognition_tier_silver_at_exactly_24_verified_hours(api):
    """PRD section 3.6: "a base tier of `GOLD` for at least 60.00 verified
    hours, `SILVER` for at least 24.00, and `BRONZE` for at least 8.00, with
    `NONE` below that and inclusive boundaries throughout — exactly 24.00 hours
    earns `SILVER`"

    Design: Corner/calculations/recognition_tier_silver_at_exactly_24_verified_hours
    """
    incident = create_active_incident(name="Flood J2",
                                      ppe_stock={"GLOVES": 2, "MASK": 2, "HARD_HAT": 2,
                                                 "VEST": 2, "GOGGLES": 2})
    volunteer = vet_volunteer(incident["id"], full_name="Cid Chan")["volunteer"]
    request = create_published_request(incident["id"], site_name="Levee East",
                                       headcount_needed=3,
                                       window_end="2026-08-12T20:00:00Z")
    ppe = issue_ppe(volunteer["id"])
    for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
        shift = create_open_shift(incident["id"], site_name="Levee East",
                                  start_at=f"{day}T08:00:00Z",
                                  end_at=f"{day}T16:00:00Z", capacity=3)
        create_verified_entry(volunteer, request, shift, work_date=day, hours=8.0,
                              checkin_at=f"{day}T08:00:00Z")
    validate_success(api.close_ppe_issuance(ppe["id"], {"outcome": "RETURNED"}, LOGI))
    demobilized = validate_success(api.demobilize_volunteer(volunteer["id"], MGR))
    assert demobilized["verified_hours_total"] == 24.0
    assert demobilized["recognition_tier"] == "SILVER"
    assert demobilized["status"] == "DEMOBILIZED"


def test_recognition_tier_gold_capped_to_silver_by_lifetime_risk(api):
    """PRD section 3.6: "a base tier of `GOLD` for at least 60.00 verified
    hours, `SILVER` for at least 24.00, and `BRONZE` for at least 8.00, with
    `NONE` below that and inclusive boundaries throughout — exactly 24.00 hours
    earns `SILVER` — except that a base tier of `GOLD` is capped down to
    `SILVER` whenever the `lifetime_risk_score` is 20 or more."

    Design: Corner/calculations/recognition_tier_gold_capped_to_silver_by_lifetime_risk
    """
    incident = create_active_incident(name="Fire K2",
                                      ppe_stock={"GLOVES": 2, "MASK": 2, "HARD_HAT": 2,
                                                 "VEST": 2, "GOGGLES": 2})
    volunteer = vet_volunteer(incident["id"], full_name="Dee Dorn")["volunteer"]
    file_and_substantiate_report(volunteer["id"], "LOW",
                                 occurred_at="2026-08-01T00:00:00Z", description="late")
    file_and_substantiate_report(volunteer["id"], "MEDIUM", category="MISCONDUCT",
                                 occurred_at="2026-08-01T01:00:00Z",
                                 description="left post")
    request = create_published_request(incident["id"], site_name="Debris Field",
                                       headcount_needed=4,
                                       window_start="2026-08-10T05:00:00Z",
                                       window_end="2026-08-13T23:00:00Z")
    ppe = issue_ppe(volunteer["id"], item_type="VEST")
    for day in ("2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"):
        shift = create_open_shift(incident["id"], site_name="Debris Field",
                                  start_at=f"{day}T06:00:00Z",
                                  end_at=f"{day}T21:00:00Z", capacity=4)
        create_verified_entry(volunteer, request, shift, work_date=day, hours=15.0,
                              checkin_at=f"{day}T06:00:00Z")
    validate_success(api.close_ppe_issuance(ppe["id"], {"outcome": "RETURNED"}, LOGI))
    demobilized = validate_success(api.demobilize_volunteer(volunteer["id"], MGR))
    assert demobilized["verified_hours_total"] == 60.0
    assert demobilized["lifetime_risk_score"] == 20
    assert demobilized["recognition_tier"] == "SILVER"
