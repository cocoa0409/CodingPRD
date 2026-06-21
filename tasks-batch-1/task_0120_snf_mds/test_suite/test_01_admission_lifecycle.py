"""Admission creation, activation gating, and census invariants.

Covers difficulty rules: priority_pair_validation_conflict (PASRR vs qualifying),
cross_entity_state_dependency (PASRR cleared), compensating_invariant
(occupied_bed_count), plus corner validations on the activate path.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    fixtures,
    factories as f,
)

COORD = TEST_USERS["admissions_coordinator_headers"]
ADMIN = TEST_USERS["administrator_headers"]


# =====================================================================
# Difficulty/cross_entity_state_dependency/admission_activate_requires_pasrr_cleared
# =====================================================================

def test_activate_blocked_when_pasrr_pending():
    """PRD §3.3: "In all cases the linked screening must be CLEARED, or activation
    is rejected with ERR_PASRR_NOT_CLEARED".

    Design: Difficulty/cross_entity_state_dependency/admission_activate_requires_pasrr_cleared
    """
    facility, resident, pasrr, admission, qs = fixtures.create_pending_admission(
        payer_source="PRIVATE", pasrr_cleared=False,
    )
    resp = api_client.activate_admission(admission["id"], {}, COORD)
    validate_error(resp, ApiErrorId.ERR_PASRR_NOT_CLEARED.value)


def test_activate_private_succeeds_when_pasrr_cleared():
    """PRD §3.3: "either the payer is not MEDICARE_A, or the payer is MEDICARE_A and
    the linked qualifying stay both exists and qualifies ... the admission becomes
    ACTIVE, the resident moves from PROSPECTIVE to ADMITTED".

    Design: Difficulty/cross_entity_state_dependency/admission_activate_requires_pasrr_cleared
    """
    facility, resident, pasrr, admission, qs = fixtures.create_pending_admission(
        payer_source="PRIVATE", pasrr_cleared=True,
    )
    data = validate_success(api_client.activate_admission(admission["id"], {}, COORD))
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    res = validate_success(api_client.get_resident(resident["id"], COORD))
    assert res["status"] == "ADMITTED", f"expected resident ADMITTED, got {res['status']}"


# =====================================================================
# Difficulty/priority_pair_validation_conflict/pasrr_referential_beats_qualifying_safety_on_activate
# =====================================================================

def test_activate_reports_pasrr_before_qualifying_stay():
    """PRD §2.7: "on admission activation, PASRR clearance is checked before the
    qualifying-stay requirement, which is checked before bed availability".
    PRD §3.3: "In all cases the linked screening must be CLEARED, or activation is
    rejected with ERR_PASRR_NOT_CLEARED".

    Design: Difficulty/priority_pair_validation_conflict/pasrr_referential_beats_qualifying_safety_on_activate
    """
    # MEDICARE_A admission whose PASRR is still PENDING AND which has no qualifying
    # stay: both the PASRR rule and the qualifying-stay rule are violated; the
    # PASRR error must surface because it is checked first.
    facility, resident, pasrr, admission, qs = fixtures.create_pending_admission(
        payer_source="MEDICARE_A", with_qualifying=False, pasrr_cleared=False,
    )
    resp = api_client.activate_admission(admission["id"], {}, COORD)
    assert resp.status_code == 409, f"expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_PASRR_NOT_CLEARED.value)


def test_activate_reports_pasrr_not_qualifying_when_both_violated_isolated():
    """PRD §2.7: "PASRR clearance is checked before the qualifying-stay requirement".
    PRD §3.3: "When the payer is MEDICARE_A and a qualifying stay is not met ... and
    allow_non_covered was not set to true, activation is rejected with
    ERR_QUALIFYING_STAY_NOT_MET".

    Design: Difficulty/priority_pair_validation_conflict/pasrr_referential_beats_qualifying_safety_on_activate
    """
    # Same dual-violation scenario; assert specifically that the lower-priority
    # qualifying-stay error is NOT the one returned.
    facility, resident, pasrr, admission, qs = fixtures.create_pending_admission(
        payer_source="MEDICARE_A", with_qualifying=False, pasrr_cleared=False,
    )
    err = validate_error(
        api_client.activate_admission(admission["id"], {}, COORD),
        ApiErrorId.ERR_PASRR_NOT_CLEARED.value,
    )
    assert err["error_id"] != ApiErrorId.ERR_QUALIFYING_STAY_NOT_MET.value


# =====================================================================
# Difficulty/compensating_invariant/occupied_bed_count_admit_then_discharge_conserved
# =====================================================================

def test_occupied_bed_count_conserved_admit_then_discharge():
    """PRD §2.9: "Bed availability is enforced at admission activation ... The census
    is recomputed (and the facility mutated) whenever a resident is admitted,
    discharged, or converted from leave to discharge".
    PRD §3.8: "On discharge the admission's status becomes DISCHARGED ... the facility
    census is recomputed downward".

    Design: Difficulty/compensating_invariant/occupied_bed_count_admit_then_discharge_conserved
    """
    facility, admission, plan, goal, discharge_assessment = (
        fixtures.setup_discharge_planned_with_active_plan(payer_source="PRIVATE")
    )
    # Bed count is 1 while admitted.
    before = validate_success(api_client.get_facility(facility["id"], ADMIN))
    assert before["occupied_bed_count"] == 1, f"expected 1 occupied, got {before['occupied_bed_count']}"

    get_success_data(
        api_client.discharge_admission(admission["id"], {"discharge_at": "2026-02-11T00:00:00Z"}, COORD)
    )
    after = validate_success(api_client.get_facility(facility["id"], ADMIN))
    assert after["occupied_bed_count"] == 0, (
        f"admit(+1)/discharge(-1) must conserve census back to 0, got {after['occupied_bed_count']}"
    )


def test_occupied_bed_count_one_while_admitted():
    """PRD §2.9: "Its occupied_bed_count is a computed census: the number of residents
    whose status is either ADMITTED or ON_LEAVE and whose active admission is at this
    facility".

    Design: Difficulty/compensating_invariant/occupied_bed_count_admit_then_discharge_conserved
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    fac = validate_success(api_client.get_facility(facility["id"], ADMIN))
    assert fac["occupied_bed_count"] == 1, f"expected 1, got {fac['occupied_bed_count']}"


# =====================================================================
# Corner/validations/error_no_beds_available_on_activate
# =====================================================================

def test_no_beds_available_at_full_facility():
    """PRD §2.9: "a pending admission may only activate while occupied_bed_count is
    strictly less than certified_bed_count; otherwise activation is rejected with
    ERR_NO_BEDS_AVAILABLE".

    Design: Corner/validations/error_no_beds_available_on_activate
    """
    facility = fixtures.create_facility(certified_bed_count=1)
    # First resident admitted -> occupied 1 of 1.
    res1 = fixtures.create_resident(facility["id"])
    p1 = fixtures.create_cleared_pasrr(res1["id"])
    adm1 = get_success_data(api_client.create_admission(
        f.create_admission_payload(res1["id"], facility["id"], p1["id"], payer_source="PRIVATE"), COORD))
    get_success_data(api_client.activate_admission(adm1["id"], {}, COORD))

    # Second resident: cleared and pending, but no bed.
    res2 = fixtures.create_resident(facility["id"])
    p2 = fixtures.create_cleared_pasrr(res2["id"])
    adm2 = get_success_data(api_client.create_admission(
        f.create_admission_payload(res2["id"], facility["id"], p2["id"],
                                   payer_source="PRIVATE", admit_at="2026-02-02T00:00:00Z"), COORD))
    validate_error(api_client.activate_admission(adm2["id"], {}, COORD),
                   ApiErrorId.ERR_NO_BEDS_AVAILABLE.value)


# =====================================================================
# Corner/validations/error_qualifying_stay_not_met_on_medicare_activate
# =====================================================================

def test_qualifying_stay_not_met_on_medicare_activate():
    """PRD §3.3: "When the payer is MEDICARE_A and a qualifying stay is not met — that
    is, qualifying_stay_id is null or the linked stay's qualifies is false — and
    allow_non_covered was not set to true, activation is rejected with
    ERR_QUALIFYING_STAY_NOT_MET".

    Design: Corner/validations/error_qualifying_stay_not_met_on_medicare_activate
    """
    # PASRR cleared (so the higher-priority rule passes); qualifying stay only 2 midnights.
    facility, resident, pasrr, admission, qs = fixtures.create_pending_admission(
        payer_source="MEDICARE_A", with_qualifying=True, pasrr_cleared=True,
        qualifying_overrides={"hospital_admit_at": "2026-01-27T10:00:00Z",
                              "hospital_discharge_at": "2026-01-29T10:00:00Z"},
    )
    validate_error(api_client.activate_admission(admission["id"], {}, COORD),
                   ApiErrorId.ERR_QUALIFYING_STAY_NOT_MET.value)


# =====================================================================
# Corner/validations/non_covered_admit_allowed_with_flag
# =====================================================================

def test_non_covered_admit_allowed_with_flag():
    """PRD §3.3: "When the payer is MEDICARE_A but the qualifying stay is not met, and
    the coordinator opts in by setting allow_non_covered to true ... the admission
    moves from PENDING to NON_COVERED: medicare_covered is set false, the admission
    status becomes NON_COVERED".

    Design: Corner/validations/non_covered_admit_allowed_with_flag
    """
    facility, resident, pasrr, admission, qs = fixtures.create_pending_admission(
        payer_source="MEDICARE_A", with_qualifying=False, pasrr_cleared=True,
    )
    data = validate_success(
        api_client.activate_admission(admission["id"], {"allow_non_covered": True}, COORD)
    )
    assert data["status"] == "NON_COVERED", f"expected NON_COVERED, got {data['status']}"
    assert data["medicare_covered"] is False, "medicare_covered must be false on the non-covered branch"


# =====================================================================
# Corner/entities/admission_medicare_covered_computed_true
# =====================================================================

def test_medicare_covered_computed_true_on_activate():
    """PRD §3.3: "medicare_covered is computed true exactly when the payer is
    MEDICARE_A and the linked qualifying stay's qualifies is true; the admission
    becomes ACTIVE".

    Design: Corner/entities/admission_medicare_covered_computed_true
    """
    facility, resident, pasrr, admission, qs = fixtures.create_pending_admission(
        payer_source="MEDICARE_A", with_qualifying=True, pasrr_cleared=True,
    )
    data = validate_success(api_client.activate_admission(admission["id"], {}, COORD))
    assert data["medicare_covered"] is True, "medicare_covered must be true for qualifying Medicare admit"
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"


# =====================================================================
# Corner/cross_cutting_complexity_layers/derived_occupied_bed_count_recompute_on_admit
# =====================================================================

def test_derived_occupied_bed_count_recomputed_on_admit():
    """PRD §2.9: "The census is recomputed (and the facility mutated) whenever a
    resident is admitted, discharged, or converted from leave to discharge".

    Design: Corner/cross_cutting_complexity_layers/derived_occupied_bed_count_recompute_on_admit
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    fac = validate_success(api_client.get_facility(facility["id"], ADMIN))
    assert fac["occupied_bed_count"] == 1, (
        f"occupied_bed_count must recompute to 1 after admit, got {fac['occupied_bed_count']}"
    )


# =====================================================================
# Corner/entities/admission_create_invalid_payer_enum_returns_invalid_request
# =====================================================================

def test_create_admission_invalid_payer_enum():
    """PRD §3.3: "The payer_source is one of MEDICARE_A, MEDICAID, PRIVATE, or
    MANAGED_CARE".
    PRD §2.7: "the body must contain all required fields with valid types, enums, and
    ranges, else ERR_INVALID_REQUEST".

    Design: Corner/entities/admission_create_invalid_payer_enum_returns_invalid_request
    """
    facility = fixtures.create_facility()
    resident = fixtures.create_resident(facility["id"])
    pasrr = fixtures.create_pasrr(resident["id"])
    payload = f.create_admission_payload(
        resident["id"], facility["id"], pasrr["id"], payer_source="SELF_PAY",
    )
    validate_error(api_client.create_admission(payload, COORD),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


# =====================================================================
# Corner/endpoints/list_admissions_filtered_by_pasrr_screening_id
# =====================================================================

def test_list_admissions_filtered_by_pasrr_screening_id():
    """PRD §3.3: "supplying the resident_id, the facility_id, the pasrr_screening_id
    of the screening that gates this episode".
    PRD §2.3: "The total_count reflects the total number of matching resources before
    pagination is applied".

    Design: Corner/endpoints/list_admissions_filtered_by_pasrr_screening_id
    """
    facility, resident, pasrr, admission, qs = fixtures.create_pending_admission(
        payer_source="PRIVATE", pasrr_cleared=True,
    )
    resp = api_client.list_admissions(COORD, params={"pasrr_screening_id": pasrr["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert data[0]["id"] == admission["id"], "filtered admission must be the one referencing the PASRR"
