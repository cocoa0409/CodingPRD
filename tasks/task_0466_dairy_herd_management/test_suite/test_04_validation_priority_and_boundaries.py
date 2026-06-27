"""Validation-priority conflicts, numeric/temporal boundaries, interval overlap.

Difficulty instances:
  priority_pair_validation_conflict / testday_closed_lactation_beats_test_date_temporal
  priority_pair_validation_conflict / cull_cross_herd_replacement_beats_meat_withdrawal
  boundary_precision_check / scc_quality_band_boundary_inclusive_200
  boundary_precision_check / parlor_shift_adjacency_at_turnaround_boundary_allowed
  resource_temporal_overlap / parlor_shift_extent_overlap_within_buffer_rejected
  resource_temporal_overlap / breeding_service_within_vwp_minimum_gap_rejected
Corner instances:
  validations / test_date_not_after_prior_on_open_lactation_returns_temporal_error
  validations / milkingshift_end_not_after_start_returns_invalid_request
  validations / open_service_exists_blocks_new_breeding
  validations / calving_cross_herd_breeding_reference_returns_referential_error
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_provisional_milk_check_single_record,
    setup_parlor_with_logged_shift, setup_active_cow_with_treatment,
    setup_open_lactation, add_test_day,
    api_client, ApiErrorId, TEST_USERS,
)

HM = TEST_USERS["herd_manager_headers"]
VET = TEST_USERS["veterinarian_headers"]
PT = TEST_USERS["parlor_tech_headers"]
COOP = TEST_USERS["coop_agent_headers"]


def _herd(name):
    return get_success_data(api_client.create_herd(
        {"name": name, "federal_order_number": "30"}, HM))


def _animal(herd_id, ear_tag, birth_date="2022-01-01"):
    return get_success_data(api_client.create_animal(
        {"herd_id": herd_id, "ear_tag": ear_tag, "birth_date": birth_date}, HM))


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict
# ---------------------------------------------------------------------------
def test_testday_on_closed_lactation_returns_state_error_not_temporal():
    """PRD §3.4: "A test day cannot be added to a lactation that has already reached `CLOSED`; such an attempt is rejected with `ERR_LACTATION_CLOSED`."
    PRD §2.10: "The order is: first the authentication headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT`), then role authorization (`ERR_INSUFFICIENT_PERMISSIONS`), then existence of all referenced resources path-first then body left-to-right (the not-found errors), then — on the two OCC-guarded milk-check mutations — the stale-version check (`ERR_STALE_MILK_CHECK_VERSION`) ahead of any business precondition, then the target resource's state precondition (the various `ERR_*_NOT_*` state errors at HTTP 409), then field shape and numeric-range validation (`ERR_INVALID_REQUEST` at HTTP 422), then within-herd uniqueness (`ERR_DUPLICATE_KEY` at HTTP 409), then same-herd referential integrity (`ERR_CROSS_HERD_REFERENCE`), then the temporal and safety rules described in §3."

    Design: Difficulty/priority_pair_validation_conflict/testday_closed_lactation_beats_test_date_temporal
    """
    api_client.set_clock("2026-02-01T00:00:00Z", HM)
    herd = _herd("Conflict Dairy A")
    animal = _animal(herd["id"], "CA-001")
    be1 = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-01-10", "sire_code": "S-1"}, VET))
    get_success_data(api_client.confirm_breeding_event(be1["id"], VET))
    ce1 = get_success_data(api_client.create_calving_event(
        {"animal_id": animal["id"], "breeding_event_id": be1["id"], "calving_date": "2026-02-01"}, HM))
    lact1_id = ce1["opened_lactation_id"]
    add_test_day(lact1_id, "2026-03-13", milk_weight_lbs=85.0, fat_pct=3.8,
                 protein_pct=3.1, scc_thousands=150, clock="2026-03-13T00:00:00Z")
    get_success_data(api_client.dry_off_animal(animal["id"], HM))
    be2 = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-04-20", "sire_code": "S-2"}, VET))
    get_success_data(api_client.confirm_breeding_event(be2["id"], VET))
    api_client.set_clock("2026-12-01T00:00:00Z", HM)
    # Subsequent calving CLOSES lact1.
    get_success_data(api_client.create_calving_event(
        {"animal_id": animal["id"], "breeding_event_id": be2["id"], "calving_date": "2026-12-01"}, HM))

    # test_date 2026-03-01 is also NOT after the prior test (dim 40) — state error must win.
    resp = api_client.create_test_day_record(
        {"lactation_id": lact1_id, "test_date": "2026-03-01", "milk_weight_lbs": 70.0,
         "fat_pct": 3.8, "protein_pct": 3.1, "scc_thousands": 150}, PT)
    validate_error(resp, ApiErrorId.ERR_LACTATION_CLOSED.value)


def test_testday_closed_lactation_state_error_carries_409():
    """PRD §3.4: "A test day cannot be added to a lactation that has already reached `CLOSED`; such an attempt is rejected with `ERR_LACTATION_CLOSED`."
    PRD §2.10: "The order is: first the authentication headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT`), then role authorization (`ERR_INSUFFICIENT_PERMISSIONS`), then existence of all referenced resources path-first then body left-to-right (the not-found errors), then — on the two OCC-guarded milk-check mutations — the stale-version check (`ERR_STALE_MILK_CHECK_VERSION`) ahead of any business precondition, then the target resource's state precondition (the various `ERR_*_NOT_*` state errors at HTTP 409), then field shape and numeric-range validation (`ERR_INVALID_REQUEST` at HTTP 422), then within-herd uniqueness (`ERR_DUPLICATE_KEY` at HTTP 409), then same-herd referential integrity (`ERR_CROSS_HERD_REFERENCE`), then the temporal and safety rules described in §3."

    Design: Difficulty/priority_pair_validation_conflict/testday_closed_lactation_beats_test_date_temporal
    """
    api_client.set_clock("2026-02-01T00:00:00Z", HM)
    herd = _herd("Conflict Dairy A2")
    animal = _animal(herd["id"], "CA-002")
    be1 = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-01-10", "sire_code": "S-1"}, VET))
    get_success_data(api_client.confirm_breeding_event(be1["id"], VET))
    ce1 = get_success_data(api_client.create_calving_event(
        {"animal_id": animal["id"], "breeding_event_id": be1["id"], "calving_date": "2026-02-01"}, HM))
    lact1_id = ce1["opened_lactation_id"]
    add_test_day(lact1_id, "2026-03-13", milk_weight_lbs=85.0, fat_pct=3.8,
                 protein_pct=3.1, scc_thousands=150, clock="2026-03-13T00:00:00Z")
    get_success_data(api_client.dry_off_animal(animal["id"], HM))
    be2 = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-04-20", "sire_code": "S-2"}, VET))
    get_success_data(api_client.confirm_breeding_event(be2["id"], VET))
    api_client.set_clock("2026-12-01T00:00:00Z", HM)
    get_success_data(api_client.create_calving_event(
        {"animal_id": animal["id"], "breeding_event_id": be2["id"], "calving_date": "2026-12-01"}, HM))

    resp = api_client.create_test_day_record(
        {"lactation_id": lact1_id, "test_date": "2026-03-01", "milk_weight_lbs": 70.0,
         "fat_pct": 3.8, "protein_pct": 3.1, "scc_thousands": 150}, PT)
    # The status-map registration makes validate_error assert HTTP 409 for ERR_LACTATION_CLOSED.
    validate_error(resp, ApiErrorId.ERR_LACTATION_CLOSED.value, expected_status=409)


def test_cull_cross_herd_replacement_returns_referential_not_safety():
    """PRD §3.10: "The replacement, when supplied, must be a `HEIFER` in the same herd; a replacement from another herd is rejected with `ERR_CROSS_HERD_REFERENCE`."
    PRD §2.10: "then same-herd referential integrity (`ERR_CROSS_HERD_REFERENCE`), then the temporal and safety rules described in §3."

    Design: Difficulty/priority_pair_validation_conflict/cull_cross_herd_replacement_beats_meat_withdrawal
    """
    api_client.set_clock("2026-01-15T00:00:00Z", HM)
    herd_a = _herd("Cull Herd A")
    herd_b = _herd("Cull Herd B")
    a_a = _animal(herd_a["id"], "A-001")
    a_b = get_success_data(api_client.create_animal(
        {"herd_id": herd_b["id"], "ear_tag": "B-HEIFER", "birth_date": "2024-01-01"}, HM))
    be = get_success_data(api_client.create_breeding_event(
        {"animal_id": a_a["id"], "service_date": "2025-12-20", "sire_code": "S-1"}, VET))
    get_success_data(api_client.confirm_breeding_event(be["id"], VET))
    get_success_data(api_client.create_calving_event(
        {"animal_id": a_a["id"], "breeding_event_id": be["id"], "calving_date": "2026-01-15"}, HM))
    api_client.set_clock("2026-03-01T00:00:00Z", HM)
    # Active meat withdrawal in force.
    get_success_data(api_client.create_health_treatment(
        {"animal_id": a_a["id"], "drug_name": "Penicillin",
         "administered_at": "2026-03-01T08:00:00Z",
         "milk_withhold_hours": 96, "meat_withdrawal_hours": 240}, VET))
    api_client.set_clock("2026-03-05T00:00:00Z", HM)

    # SLAUGHTER cull with cross-herd replacement AND active meat withdrawal:
    # referential (cross-herd) error must win over the safety meat-withdrawal error.
    resp = api_client.create_cull_decision(
        {"animal_id": a_a["id"], "reason": "INJURY", "disposition": "SLAUGHTER",
         "decided_at": "2026-03-05T10:00:00Z", "replacement_animal_id": a_b["id"]}, HM)
    validate_error(resp, ApiErrorId.ERR_CROSS_HERD_REFERENCE.value)


def test_cull_cross_herd_replacement_leaves_animal_active():
    """PRD §3.10: "The replacement, when supplied, must be a `HEIFER` in the same herd; a replacement from another herd is rejected with `ERR_CROSS_HERD_REFERENCE`."
    PRD §2.8: "the system applies the full ripple atomically."

    Design: Difficulty/priority_pair_validation_conflict/cull_cross_herd_replacement_beats_meat_withdrawal
    """
    api_client.set_clock("2026-01-15T00:00:00Z", HM)
    herd_a = _herd("Cull Herd A2")
    herd_b = _herd("Cull Herd B2")
    a_a = _animal(herd_a["id"], "A-002")
    a_b = get_success_data(api_client.create_animal(
        {"herd_id": herd_b["id"], "ear_tag": "B-HEIFER2", "birth_date": "2024-01-01"}, HM))
    be = get_success_data(api_client.create_breeding_event(
        {"animal_id": a_a["id"], "service_date": "2025-12-20", "sire_code": "S-1"}, VET))
    get_success_data(api_client.confirm_breeding_event(be["id"], VET))
    get_success_data(api_client.create_calving_event(
        {"animal_id": a_a["id"], "breeding_event_id": be["id"], "calving_date": "2026-01-15"}, HM))
    api_client.set_clock("2026-03-01T00:00:00Z", HM)
    get_success_data(api_client.create_health_treatment(
        {"animal_id": a_a["id"], "drug_name": "Penicillin",
         "administered_at": "2026-03-01T08:00:00Z",
         "milk_withhold_hours": 96, "meat_withdrawal_hours": 240}, VET))
    api_client.set_clock("2026-03-05T00:00:00Z", HM)
    resp = api_client.create_cull_decision(
        {"animal_id": a_a["id"], "reason": "INJURY", "disposition": "SLAUGHTER",
         "decided_at": "2026-03-05T10:00:00Z", "replacement_animal_id": a_b["id"]}, HM)
    validate_error(resp, ApiErrorId.ERR_CROSS_HERD_REFERENCE.value)
    # Rejected cull leaves the animal in its prior ACTIVE state — no terminal transition applied.
    a = validate_success(api_client.get_animal(a_a["id"], HM))
    assert a["status"] == "ACTIVE", a["status"]


# ---------------------------------------------------------------------------
# boundary_precision_check
# ---------------------------------------------------------------------------
def test_scc_exactly_200_yields_good_quality():
    """PRD §3.8: "If that weighted SCC is at or below 200 (thousands), the herd's `milk_quality_status` becomes `GOOD`; if it is above 200 but at or below 400, it becomes `WARNING`; if it is above 400, it becomes `PENALIZED`."
    PRD §3.8: "The upper bound of each band is inclusive."

    Design: Difficulty/boundary_precision_check/scc_quality_band_boundary_inclusive_200
    """
    herd, _a, _l, milk_check, _ps, _tdr = setup_provisional_milk_check_single_record(
        scc_thousands=200, milk_weight_lbs=1000, fat_pct=3.8, protein_pct=3.1,
        herd_name="Boundary SCC Dairy",
    )
    data = validate_success(
        api_client.finalize_milk_check(milk_check["id"], milk_check["version"], COOP))
    assert data["weighted_scc_thousands"] == 200.00, data["weighted_scc_thousands"]
    h = validate_success(api_client.get_herd(herd["id"], HM))
    assert h["milk_quality_status"] == "GOOD", h["milk_quality_status"]


def test_scc_one_above_band_boundary_yields_warning():
    """PRD §3.8: "If that weighted SCC is at or below 200 (thousands), the herd's `milk_quality_status` becomes `GOOD`; if it is above 200 but at or below 400, it becomes `WARNING`; if it is above 400, it becomes `PENALIZED`."
    PRD §3.8: "The upper bound of each band is inclusive."

    Design: Difficulty/boundary_precision_check/scc_quality_band_boundary_inclusive_200
    """
    # weighted_scc = 201 (one above the inclusive GOOD upper bound) => WARNING.
    herd, _a, _l, milk_check, _ps, _tdr = setup_provisional_milk_check_single_record(
        scc_thousands=201, milk_weight_lbs=1000, fat_pct=3.8, protein_pct=3.1,
        herd_name="Boundary SCC Dairy 2",
    )
    data = validate_success(
        api_client.finalize_milk_check(milk_check["id"], milk_check["version"], COOP))
    assert data["weighted_scc_thousands"] == 201.00, data["weighted_scc_thousands"]
    h = validate_success(api_client.get_herd(herd["id"], HM))
    assert h["milk_quality_status"] == "WARNING", h["milk_quality_status"]


def test_shift_starting_exactly_at_turnaround_boundary_allowed():
    """PRD §3.3: "a new shift's `start_at` must be at or after the prior shift's `end_at` plus the parlor's `turnaround_minutes`; a new shift that starts exactly at that buffer boundary is allowed."

    Design: Difficulty/boundary_precision_check/parlor_shift_adjacency_at_turnaround_boundary_allowed
    """
    _h, parlor, _shift = setup_parlor_with_logged_shift(
        turnaround_minutes=30, herd_name="Parlor Boundary Dairy",
        start_at="2026-06-01T04:00:00Z", end_at="2026-06-01T07:00:00Z",
    )
    # prior end 07:00 + 30min buffer = 07:30 exactly => allowed.
    resp = api_client.create_milking_shift(
        {"parlor_id": parlor["id"], "start_at": "2026-06-01T07:30:00Z",
         "end_at": "2026-06-01T10:00:00Z", "cows_milked": 24}, PT)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "LOGGED", data["status"]


def test_shift_at_boundary_persists_and_is_retrievable():
    """PRD §3.3: "a new shift's `start_at` must be at or after the prior shift's `end_at` plus the parlor's `turnaround_minutes`; a new shift that starts exactly at that buffer boundary is allowed."
    PRD §3.3: "On creation the system copies the `herd_id` from the parlor, records the acting user's identifier as `operator_user_id`, and sets `status` to `LOGGED`."

    Design: Difficulty/boundary_precision_check/parlor_shift_adjacency_at_turnaround_boundary_allowed
    """
    herd, parlor, _shift = setup_parlor_with_logged_shift(
        turnaround_minutes=30, herd_name="Parlor Boundary Dairy 2",
        start_at="2026-06-01T04:00:00Z", end_at="2026-06-01T07:00:00Z",
    )
    created = validate_success(api_client.create_milking_shift(
        {"parlor_id": parlor["id"], "start_at": "2026-06-01T07:30:00Z",
         "end_at": "2026-06-01T10:00:00Z", "cows_milked": 24}, PT), expected_status=201)
    fetched = validate_success(api_client.get_milking_shift(created["id"], PT))
    assert fetched["status"] == "LOGGED", fetched["status"]
    assert fetched["herd_id"] == herd["id"], fetched["herd_id"]


# ---------------------------------------------------------------------------
# resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_shift_one_minute_inside_buffer_rejected():
    """PRD §3.3: "Treating each shift as the half-open interval from its `start_at` up to but not including its `end_at`, a new shift is rejected with `ERR_PARLOR_SHIFT_OVERLAP` if it would overlap any existing `LOGGED` shift on the same parlor once the parlor's turnaround buffer is applied."

    Design: Difficulty/resource_temporal_overlap/parlor_shift_extent_overlap_within_buffer_rejected
    """
    _h, parlor, _shift = setup_parlor_with_logged_shift(
        turnaround_minutes=30, herd_name="Overlap Parlor Dairy",
        start_at="2026-06-01T04:00:00Z", end_at="2026-06-01T07:00:00Z",
    )
    # 07:29 is one minute inside the 07:30 boundary => overlap.
    resp = api_client.create_milking_shift(
        {"parlor_id": parlor["id"], "start_at": "2026-06-01T07:29:00Z",
         "end_at": "2026-06-01T09:00:00Z", "cows_milked": 24}, PT)
    validate_error(resp, ApiErrorId.ERR_PARLOR_SHIFT_OVERLAP.value)


def test_shift_overlapping_existing_extent_rejected():
    """PRD §3.3: "Treating each shift as the half-open interval from its `start_at` up to but not including its `end_at`, a new shift is rejected with `ERR_PARLOR_SHIFT_OVERLAP` if it would overlap any existing `LOGGED` shift on the same parlor once the parlor's turnaround buffer is applied."

    Design: Difficulty/resource_temporal_overlap/parlor_shift_extent_overlap_within_buffer_rejected
    """
    # A zero-turnaround parlor; a second shift whose extent overlaps the first's
    # 04:00-07:00 window (starting 06:00) is rejected purely on extent overlap.
    _h, parlor, _shift = setup_parlor_with_logged_shift(
        turnaround_minutes=0, herd_name="Overlap Parlor Dairy 2",
        start_at="2026-06-01T04:00:00Z", end_at="2026-06-01T07:00:00Z",
    )
    resp = api_client.create_milking_shift(
        {"parlor_id": parlor["id"], "start_at": "2026-06-01T06:00:00Z",
         "end_at": "2026-06-01T09:00:00Z", "cows_milked": 24}, PT)
    validate_error(resp, ApiErrorId.ERR_PARLOR_SHIFT_OVERLAP.value)


def test_breeding_service_within_vwp_rejected():
    """PRD §3.5: "the new `service_date` must be at or after each such prior service's `service_date` plus 30 days; a `service_date` falling within the half-open 30-day interval starting at any prior service date (on or after that date but before that date plus 30 days) is rejected with `ERR_SERVICE_WITHIN_VWP`."

    Design: Difficulty/resource_temporal_overlap/breeding_service_within_vwp_minimum_gap_rejected
    """
    api_client.set_clock("2026-02-01T00:00:00Z", HM)
    herd = _herd("VWP Dairy")
    animal = _animal(herd["id"], "VW-001")
    be1 = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-02-01", "sire_code": "S-1"}, VET))
    # Mark OPEN so it counts as a prior non-voided service but does not block by status.
    get_success_data(api_client.mark_open_breeding_event(be1["id"], VET))
    api_client.set_clock("2026-02-21T00:00:00Z", HM)
    # 2026-02-21 is 20 days after 2026-02-01 => inside [02-01, 03-03) VWP window.
    resp = api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-02-21", "sire_code": "S-2"}, VET)
    validate_error(resp, ApiErrorId.ERR_SERVICE_WITHIN_VWP.value)


def test_breeding_service_within_vwp_returns_409():
    """PRD §3.5: "a `service_date` falling within the half-open 30-day interval starting at any prior service date (on or after that date but before that date plus 30 days) is rejected with `ERR_SERVICE_WITHIN_VWP`. This is a minimum-gap rule along the animal's own timeline, distinct from the parlor's interval-overlap-with-buffer geometry."

    Design: Difficulty/resource_temporal_overlap/breeding_service_within_vwp_minimum_gap_rejected
    """
    api_client.set_clock("2026-02-01T00:00:00Z", HM)
    herd = _herd("VWP Dairy 2")
    animal = _animal(herd["id"], "VW-002")
    be1 = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-02-01", "sire_code": "S-1"}, VET))
    get_success_data(api_client.mark_open_breeding_event(be1["id"], VET))
    api_client.set_clock("2026-02-15T00:00:00Z", HM)
    # 2026-02-15 is 14 days after the prior service => inside the half-open VWP window.
    resp = api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-02-15", "sire_code": "S-2"}, VET)
    # Status-map registration makes validate_error assert HTTP 409 for ERR_SERVICE_WITHIN_VWP.
    validate_error(resp, ApiErrorId.ERR_SERVICE_WITHIN_VWP.value, expected_status=409)


# ---------------------------------------------------------------------------
# Corner validations (isolated single-failure scenarios)
# ---------------------------------------------------------------------------
def test_test_date_not_after_prior_on_open_lactation():
    """PRD §3.4: "the new `day_in_milk` must be strictly greater than the highest `day_in_milk` already recorded on that lactation, and the `test_date` must be on or after the lactation's `start_date`; a violation of either is rejected with `ERR_TEST_DATE_NOT_AFTER_PRIOR`."

    Design: Corner/validations/test_date_not_after_prior_on_open_lactation_returns_temporal_error
    """
    _h, _a, lact, _c = setup_open_lactation(
        herd_name="Temporal Dairy", ear_tag="TP-001",
        service_date="2026-01-10", calving_date="2026-02-01",
        calving_clock="2026-02-01T00:00:00Z",
    )
    add_test_day(lact["id"], "2026-03-13", milk_weight_lbs=85.0, fat_pct=3.8,
                 protein_pct=3.1, scc_thousands=150, clock="2026-03-13T00:00:00Z")
    # Same test_date (same dim 40) — not strictly greater.
    resp = api_client.create_test_day_record(
        {"lactation_id": lact["id"], "test_date": "2026-03-13", "milk_weight_lbs": 80.0,
         "fat_pct": 3.8, "protein_pct": 3.1, "scc_thousands": 150}, PT)
    validate_error(resp, ApiErrorId.ERR_TEST_DATE_NOT_AFTER_PRIOR.value)


def test_milking_shift_end_not_after_start_rejected():
    """PRD §3.3: "Recording Milking Shifts in the Parlor A `ParlorTech` (or a `HerdManager`) logs a **MilkingShift** against a parlor by supplying the `parlor_id`, a `start_at` instant (inclusive), an `end_at` instant (exclusive, and which must be strictly after `start_at` — otherwise the request is an invalid one rejected with `ERR_INVALID_REQUEST`), and the `cows_milked` head count for the shift, which must be at least 0."

    Design: Corner/validations/milkingshift_end_not_after_start_returns_invalid_request
    """
    herd = _herd("Shift Range Dairy")
    parlor = get_success_data(api_client.create_parlor(
        {"herd_id": herd["id"], "name": "P1", "stall_capacity": 12}, HM))
    resp = api_client.create_milking_shift(
        {"parlor_id": parlor["id"], "start_at": "2026-06-01T07:00:00Z",
         "end_at": "2026-06-01T07:00:00Z", "cows_milked": 10}, PT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_open_service_blocks_new_breeding():
    """PRD §3.5: "a new breeding event may not be logged while the animal already has a breeding event in `BRED` or `CONFIRMED_PREGNANT` status — a cow with an open or confirmed service cannot be re-bred — and such an attempt is rejected with `ERR_OPEN_SERVICE_EXISTS`."

    Design: Corner/validations/open_service_exists_blocks_new_breeding
    """
    api_client.set_clock("2026-02-01T00:00:00Z", HM)
    herd = _herd("Open Service Dairy")
    animal = _animal(herd["id"], "OS-001")
    get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-02-01", "sire_code": "S-1"}, VET))
    api_client.set_clock("2026-03-20T00:00:00Z", HM)
    # >30d later (isolates from VWP) but the first service is still BRED.
    resp = api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-03-20", "sire_code": "S-2"}, VET)
    validate_error(resp, ApiErrorId.ERR_OPEN_SERVICE_EXISTS.value)


def test_calving_cross_herd_breeding_reference_rejected():
    """PRD §3.6: "The breeding event must also belong to the same animal — a breeding event from another animal or herd is an `ERR_CROSS_HERD_REFERENCE`."

    Design: Corner/validations/calving_cross_herd_breeding_reference_returns_referential_error
    """
    api_client.set_clock("2026-01-10T00:00:00Z", HM)
    herd = _herd("XRef Dairy")
    a_x = _animal(herd["id"], "X-001")
    a_y = _animal(herd["id"], "Y-001")
    be_x = get_success_data(api_client.create_breeding_event(
        {"animal_id": a_x["id"], "service_date": "2026-01-10", "sire_code": "S-1"}, VET))
    get_success_data(api_client.confirm_breeding_event(be_x["id"], VET))
    # Calving on Y references X's breeding event => cross-reference.
    resp = api_client.create_calving_event(
        {"animal_id": a_y["id"], "breeding_event_id": be_x["id"], "calving_date": "2026-10-01"}, HM)
    validate_error(resp, ApiErrorId.ERR_CROSS_HERD_REFERENCE.value)
