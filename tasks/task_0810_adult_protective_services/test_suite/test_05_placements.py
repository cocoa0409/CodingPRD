"""Emergency protective placement: eligibility gates, half-open bed-capacity
geometry, the eligibility-before-bed check order, bed conservation across
place/discharge, review-driven expiry, and interval validation."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    create_placement_payload,
)
from test_helpers import fixtures as fx

CASEWORKER = TEST_USERS["caseworker_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def _ready_case_with_court_placement(fac_beds=2):
    """Case UNDER_INVESTIGATION with an ACTIVE court-authorized placement, then
    driven to READY_FOR_CLOSURE (comprehensive assessment, submit, dispose).
    No freezes, so estimated_exposure_cents stays 0."""
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(total_beds=fac_beds)
    base = fx.create_case_under_investigation(allegation_types=["PHYSICAL_ABUSE"], priority="EMERGENCY")
    fx.add_capacity_determination(base["client"]["id"], "IMPAIRED")
    plc = fx.create_placement(base["case_id"], fac["id"],
                              "2026-06-01T00:00:00Z", "2026-06-05T00:00:00Z", court_authorized=True)
    fx.add_comprehensive_assessment(base["client"]["id"], isolation_level=2, cognitive_impairment_level=2,
                                    financial_vulnerability_level=1, caregiver_dependency_level=1,
                                    prior_report_count=0)
    inv_id = base["investigation"]["id"]
    get_success_data(api_client.submit_findings(inv_id, {"finding_summary": "abuse indicators"}, CASEWORKER))
    get_success_data(api_client.dispose_investigation(inv_id, {"disposition": "UNSUBSTANTIATED"}, SUPERVISOR))
    return {"facility": fac, "placement": plc, **base}


# ---------------- close cascade -> placement -> facility ----------------

def test_close_discharges_active_placement(api):
    """PRD §3.8: "Every `ACTIVE` EmergencyPlacement in the case is discharged,
    moving from `ACTIVE` to `DISCHARGED` and releasing its bed back to its
    facility."

    Design: Difficulty/transitive_cascade/close_cascade_placement_bed_release
    """
    ctx = _ready_case_with_court_placement(fac_beds=2)
    resp = api.close_case(ctx["case_id"], {"closure_reason": "client relocated safely"}, SUPERVISOR)
    case = validate_success(resp)
    assert case["status"] == "CLOSED"
    placement = fx.get_placement(ctx["placement"]["id"])
    assert placement["status"] == "DISCHARGED"


def test_close_releases_bed_to_facility(api):
    """PRD §3.8: "Every `ACTIVE` EmergencyPlacement in the case is discharged,
    moving from `ACTIVE` to `DISCHARGED` and releasing its bed back to its
    facility."

    Design: Difficulty/transitive_cascade/close_cascade_placement_bed_release
    """
    ctx = _ready_case_with_court_placement(fac_beds=2)
    api.close_case(ctx["case_id"], {"closure_reason": "client relocated safely"}, SUPERVISOR)
    facility = fx.get_facility(ctx["facility"]["id"])
    assert facility["available_beds"] == 2, f"bed must be released; available_beds={facility['available_beds']}"


# ---------------- eligibility beats bed (priority pair) ----------------

def test_ineligible_client_placement_rejected_when_facility_full(api):
    """PRD §3.4: "the subject client must be eligible for emergency protective
    placement, which means the client's `capacity_status` is `IMPAIRED` or the
    client's `risk_level` is `HIGH`; if neither holds, the placement is refused
    with `ERR_CLIENT_NOT_ELIGIBLE_FOR_PLACEMENT` (422)."

    Design: Difficulty/priority_pair_validation_conflict/placement_safety_beats_temporal
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(total_beds=1)
    # Eligible client A occupies the only bed.
    baseA = fx.create_screened_in_case(allegation_types=["PHYSICAL_ABUSE"], priority="EMERGENCY")
    fx.add_capacity_determination(baseA["client"]["id"], "IMPAIRED")
    fx.create_placement(baseA["case_id"], fac["id"], "2026-06-01T00:00:00Z", "2026-06-20T00:00:00Z", court_authorized=True)
    # Ineligible client B (capacity UNKNOWN, risk null).
    baseB = fx.create_screened_in_case(allegation_types=["NEGLECT"], priority="PRIORITY")
    resp = api.create_placement(
        create_placement_payload(baseB["case_id"], fac["id"], "2026-06-02T00:00:00Z", "2026-06-05T00:00:00Z"),
        CASEWORKER,
    )
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_ELIGIBLE_FOR_PLACEMENT.value)


def test_placement_eligibility_checked_before_bed_availability(api):
    """PRD §3.4: "Next the subject client must be eligible for emergency
    protective placement ... Finally the facility must have a free bed for the
    requested window". The eligibility gate fires before the bed gate, so a full
    facility does not turn the ineligibility into ERR_NO_BED_AVAILABLE.

    Design: Difficulty/priority_pair_validation_conflict/placement_safety_beats_temporal
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(total_beds=1)
    baseA = fx.create_screened_in_case(allegation_types=["PHYSICAL_ABUSE"], priority="EMERGENCY")
    fx.add_capacity_determination(baseA["client"]["id"], "IMPAIRED")
    fx.create_placement(baseA["case_id"], fac["id"], "2026-06-01T00:00:00Z", "2026-06-20T00:00:00Z", court_authorized=True)
    baseB = fx.create_screened_in_case(allegation_types=["NEGLECT"], priority="PRIORITY")
    resp = api.create_placement(
        create_placement_payload(baseB["case_id"], fac["id"], "2026-06-02T00:00:00Z", "2026-06-05T00:00:00Z"),
        CASEWORKER,
    )
    error_id = resp.json()["data"]["error_id"]
    assert error_id != ApiErrorId.ERR_NO_BED_AVAILABLE.value, (
        f"eligibility must be checked before bed availability; got {error_id}"
    )
    assert error_id == ApiErrorId.ERR_CLIENT_NOT_ELIGIBLE_FOR_PLACEMENT.value


# ---------------- placement enabled by HIGH risk_level ----------------

def test_placement_succeeds_for_high_risk_client(api):
    """PRD §3.4: "the subject client must be eligible for emergency protective
    placement, which means the client's `capacity_status` is `IMPAIRED` or the
    client's `risk_level` is `HIGH`".

    Design: Difficulty/cross_entity_state_dependency/placement_enabled_by_client_high_risk
    """
    ctx = fx.create_eligible_placement_case(total_beds=1, make_eligible="HIGH")
    assert ctx["client"]["risk_level"] == "HIGH"
    assert ctx["client"]["capacity_status"] == "UNKNOWN"
    resp = api.create_placement(
        create_placement_payload(ctx["case_id"], ctx["facility"]["id"],
                                 "2026-06-01T00:00:00Z", "2026-06-03T00:00:00Z", court_authorized=True),
        CASEWORKER,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"


def test_placement_by_high_risk_client_occupies_bed(api):
    """PRD §3.4: "On success the placement is created in `ACTIVE` status, the
    facility's `available_beds` is decremented (its `occupied_beds` rises by
    one)".

    Design: Difficulty/cross_entity_state_dependency/placement_enabled_by_client_high_risk
    """
    ctx = fx.create_eligible_placement_case(total_beds=1, make_eligible="HIGH")
    fx.create_placement(ctx["case_id"], ctx["facility"]["id"],
                        "2026-06-01T00:00:00Z", "2026-06-03T00:00:00Z", court_authorized=True)
    facility = fx.get_facility(ctx["facility"]["id"])
    assert facility["available_beds"] == 0, f"the only bed should be occupied; got {facility['available_beds']}"


# ---------------- half-open bed capacity geometry ----------------

def test_overlapping_placement_rejected_no_bed(api):
    """PRD §3.4: "the number of existing `ACTIVE` placements at that facility
    whose window overlaps the requested `[start_at, end_at)` window must be
    strictly fewer than the facility's `total_beds` ... If no bed is free, the
    placement is refused with `ERR_NO_BED_AVAILABLE` (409)."

    Design: Difficulty/resource_temporal_overlap/placement_bed_halfopen_capacity_overlap
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(total_beds=1)
    baseA = fx.create_screened_in_case(allegation_types=["PHYSICAL_ABUSE"], priority="EMERGENCY")
    fx.add_capacity_determination(baseA["client"]["id"], "IMPAIRED")
    fx.create_placement(baseA["case_id"], fac["id"], "2026-06-01T00:00:00Z", "2026-06-03T00:00:00Z", court_authorized=True)
    baseB = fx.create_screened_in_case(allegation_types=["NEGLECT"], priority="PRIORITY")
    fx.add_capacity_determination(baseB["client"]["id"], "IMPAIRED")
    resp = api.create_placement(
        create_placement_payload(baseB["case_id"], fac["id"], "2026-06-02T00:00:00Z", "2026-06-04T00:00:00Z",
                                 court_authorized=True),
        CASEWORKER,
    )
    validate_error(resp, ApiErrorId.ERR_NO_BED_AVAILABLE.value)


def test_adjacent_placement_accepted_half_open(api):
    """PRD §3.4: "adjacency, where one placement's `end_at` equals the next
    placement's `start_at`, does not count as an overlap."

    Design: Difficulty/resource_temporal_overlap/placement_bed_halfopen_capacity_overlap
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(total_beds=1)
    baseA = fx.create_screened_in_case(allegation_types=["PHYSICAL_ABUSE"], priority="EMERGENCY")
    fx.add_capacity_determination(baseA["client"]["id"], "IMPAIRED")
    fx.create_placement(baseA["case_id"], fac["id"], "2026-06-01T00:00:00Z", "2026-06-03T00:00:00Z", court_authorized=True)
    baseB = fx.create_screened_in_case(allegation_types=["NEGLECT"], priority="PRIORITY")
    fx.add_capacity_determination(baseB["client"]["id"], "IMPAIRED")
    resp = api.create_placement(
        create_placement_payload(baseB["case_id"], fac["id"], "2026-06-03T00:00:00Z", "2026-06-05T00:00:00Z",
                                 court_authorized=True),
        CASEWORKER,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE", "a placement starting exactly at the prior end_at must be accepted"


# ---------------- bed conservation across place/discharge ----------------

def test_discharge_restores_available_beds(api):
    """PRD §3.4: "discharge requires the placement to be `ACTIVE` ... moves it
    from `ACTIVE` to `DISCHARGED`, stamps `discharged_at` with the logical
    clock, increments the facility's `available_beds` by one".

    Design: Difficulty/compensating_invariant/bed_conservation_place_then_discharge
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(total_beds=3)
    base = fx.create_screened_in_case(allegation_types=["PHYSICAL_ABUSE"], priority="EMERGENCY")
    fx.add_capacity_determination(base["client"]["id"], "IMPAIRED")
    plc = fx.create_placement(base["case_id"], fac["id"], "2026-06-01T00:00:00Z", "2026-06-04T00:00:00Z", court_authorized=True)
    resp = api.discharge_placement(plc["id"], CASEWORKER)
    data = validate_success(resp)
    assert data["status"] == "DISCHARGED"
    facility = fx.get_facility(fac["id"])
    assert facility["available_beds"] == 3, f"all beds restored; got {facility['available_beds']}"


def test_discharge_conserves_bed_total(api):
    """PRD §3.4: "the invariant is that available and occupied beds always sum to
    the licensed total." After a place-then-discharge cycle at a 3-bed facility,
    occupied returns to 0 and the total is conserved.

    Design: Difficulty/compensating_invariant/bed_conservation_place_then_discharge
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(total_beds=3)
    base = fx.create_screened_in_case(allegation_types=["PHYSICAL_ABUSE"], priority="EMERGENCY")
    fx.add_capacity_determination(base["client"]["id"], "IMPAIRED")
    plc = fx.create_placement(base["case_id"], fac["id"], "2026-06-01T00:00:00Z", "2026-06-04T00:00:00Z", court_authorized=True)
    api.discharge_placement(plc["id"], CASEWORKER)
    facility = fx.get_facility(fac["id"])
    assert facility["occupied_beds"] == 0
    assert facility["available_beds"] + facility["occupied_beds"] == facility["total_beds"] == 3


# ---------------- review-driven expiry (queue B) ----------------

def test_placement_review_expires_past_72h_releases_bed(api):
    """PRD §3.4: "when the placement is not court-authorized and the logical
    clock has reached or passed the placement's `expires_at`, the review expires
    it — moving it from `ACTIVE` to `EXPIRED`, stamping `discharged_at`,
    incrementing the facility's `available_beds`".

    Design: Corner/state_machines/placement_review_expires_past_72h_releases_bed
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(total_beds=1)
    base = fx.create_screened_in_case(allegation_types=["PHYSICAL_ABUSE"], priority="EMERGENCY")
    fx.add_capacity_determination(base["client"]["id"], "IMPAIRED")
    plc = fx.create_placement(base["case_id"], fac["id"], "2026-06-01T00:00:00Z", "2026-06-20T00:00:00Z", court_authorized=False)
    fx.set_clock("2026-06-04T00:00:00Z")  # == start_at + 72h == expires_at
    resp = api.review_placement(plc["id"], SUPERVISOR)
    data = validate_success(resp)
    assert data["status"] == "EXPIRED"
    facility = fx.get_facility(fac["id"])
    assert facility["available_beds"] == 1


# ---------------- interval validation (queue B) ----------------

def test_placement_invalid_date_range_returns_422(api):
    """PRD §3.4: "Interval ordering is checked first among the business rules:
    `end_at` must be strictly after `start_at`, or the request fails with
    `ERR_INVALID_DATE_RANGE` (422)."

    Design: Corner/validations/placement_invalid_date_range_returns_422
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(total_beds=2)
    base = fx.create_screened_in_case(allegation_types=["PHYSICAL_ABUSE"], priority="EMERGENCY")
    fx.add_capacity_determination(base["client"]["id"], "IMPAIRED")
    resp = api.create_placement(
        create_placement_payload(base["case_id"], fac["id"],
                                 "2026-06-05T00:00:00Z", "2026-06-05T00:00:00Z", court_authorized=True),
        CASEWORKER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value)
