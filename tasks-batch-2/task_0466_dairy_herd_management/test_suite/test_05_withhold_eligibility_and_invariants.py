"""Milk-eligibility withhold, cross-entity state gates, compensating invariants.

Difficulty instances:
  cross_entity_state_dependency / calving_requires_breeding_confirmed_pregnant
  cross_entity_state_dependency / milk_check_excludes_ineligible_animal_under_withhold
  compensating_invariant / treatment_void_restores_milk_eligible_invariant
  compensating_invariant / milking_shift_void_restores_parlor_interval_availability
Corner instances:
  state_machines / clear_treatment_before_withhold_elapsed_returns_not_elapsed
  state_machines / clear_treatment_after_withhold_elapsed_succeeds
  cross_cutting_complexity_layers / scheduled_treatment_withhold_sets_milk_eligible_false
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_open_lactation, add_test_day, create_price_sheet,
    setup_active_cow_with_treatment, setup_parlor_with_logged_shift,
    api_client, ApiErrorId, TEST_USERS,
)

HM = TEST_USERS["herd_manager_headers"]
VET = TEST_USERS["veterinarian_headers"]
PT = TEST_USERS["parlor_tech_headers"]
COOP = TEST_USERS["coop_agent_headers"]


def _herd(name):
    return get_success_data(api_client.create_herd(
        {"name": name, "federal_order_number": "30"}, HM))


# ---------------------------------------------------------------------------
# cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_calving_rejected_when_breeding_still_bred():
    """PRD §3.6: "The named breeding event must be `CONFIRMED_PREGNANT`; if it is in any other state the calving is rejected with `ERR_BREEDING_NOT_CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/calving_requires_breeding_confirmed_pregnant
    """
    api_client.set_clock("2026-01-15T00:00:00Z", HM)
    herd = _herd("Calve Dep Dairy")
    animal = get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "CD-001", "birth_date": "2024-01-01"}, HM))
    be = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-01-10", "sire_code": "S-1"}, VET))
    # Not confirmed — still BRED.
    resp = api_client.create_calving_event(
        {"animal_id": animal["id"], "breeding_event_id": be["id"], "calving_date": "2026-10-01"}, HM)
    validate_error(resp, ApiErrorId.ERR_BREEDING_NOT_CONFIRMED.value)


def test_calving_rejected_on_bred_leaves_animal_heifer():
    """PRD §3.6: "The named breeding event must be `CONFIRMED_PREGNANT`; if it is in any other state the calving is rejected with `ERR_BREEDING_NOT_CONFIRMED`."
    PRD §3.2: "A newly registered animal starts with `status` of `HEIFER`, `parity` of 0 (a heifer has not yet calved), and `milk_eligible` of `true`."

    Design: Difficulty/cross_entity_state_dependency/calving_requires_breeding_confirmed_pregnant
    """
    api_client.set_clock("2026-01-15T00:00:00Z", HM)
    herd = _herd("Calve Dep Dairy 2")
    animal = get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "CD-002", "birth_date": "2024-01-01"}, HM))
    be = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-01-10", "sire_code": "S-1"}, VET))
    resp = api_client.create_calving_event(
        {"animal_id": animal["id"], "breeding_event_id": be["id"], "calving_date": "2026-10-01"}, HM)
    validate_error(resp, ApiErrorId.ERR_BREEDING_NOT_CONFIRMED.value)
    # The rejected calving applies no cascade: the heifer stays HEIFER at parity 0.
    a = validate_success(api_client.get_animal(animal["id"], HM))
    assert a["status"] == "HEIFER", a["status"]
    assert a["parity"] == 0, a["parity"]


def test_finalize_empty_pool_when_only_producer_ineligible():
    """PRD §3.8: "The **pool** comprises every test-day record whose `herd_id` is this herd, whose `test_date` falls in the check's `settlement_month`, whose owning animal is `milk_eligible` at the moment of finalization, and whose `included_in_milk_check_id` is still null (not already pooled by an earlier check)."
    PRD §3.8: "there must be at least one eligible, not-yet-pooled test-day record in the settlement month, otherwise the finalize is rejected with `ERR_EMPTY_MILK_POOL`."

    Design: Difficulty/cross_entity_state_dependency/milk_check_excludes_ineligible_animal_under_withhold
    """
    herd, animal, lact, _c = setup_open_lactation(
        herd_name="Withhold Pool Dairy", ear_tag="WP-001",
        service_date="2026-01-10", calving_date="2026-02-01",
        calving_clock="2026-02-01T00:00:00Z",
    )
    add_test_day(lact["id"], "2026-06-08", milk_weight_lbs=1000, fat_pct=3.8,
                 protein_pct=3.1, scc_thousands=180, clock="2026-06-10T00:00:00Z")
    # ACTIVE treatment with a live withhold => animal not milk_eligible at clock 2026-06-10.
    get_success_data(api_client.create_health_treatment(
        {"animal_id": animal["id"], "drug_name": "Mastitis Tx",
         "administered_at": "2026-06-09T08:00:00Z",
         "milk_withhold_hours": 96, "meat_withdrawal_hours": 240}, VET))

    a = validate_success(api_client.get_animal(animal["id"], HM))
    assert a["milk_eligible"] is False, a["milk_eligible"]

    price_sheet = create_price_sheet(herd["id"], settlement_month="2026-06")
    milk_check = get_success_data(api_client.create_milk_check(
        {"herd_id": herd["id"], "price_sheet_id": price_sheet["id"]}, COOP))
    resp = api_client.finalize_milk_check(milk_check["id"], milk_check["version"], COOP)
    validate_error(resp, ApiErrorId.ERR_EMPTY_MILK_POOL.value)


def test_finalize_pool_empty_with_ineligible_animal_leaves_check_provisional():
    """PRD §3.8: "The **pool** comprises every test-day record whose `herd_id` is this herd, whose `test_date` falls in the check's `settlement_month`, whose owning animal is `milk_eligible` at the moment of finalization, and whose `included_in_milk_check_id` is still null (not already pooled by an earlier check)."
    PRD §3.8: "there must be at least one eligible, not-yet-pooled test-day record in the settlement month, otherwise the finalize is rejected with `ERR_EMPTY_MILK_POOL`."

    Design: Difficulty/cross_entity_state_dependency/milk_check_excludes_ineligible_animal_under_withhold
    """
    herd, animal, lact, _c = setup_open_lactation(
        herd_name="Withhold Pool Dairy 2", ear_tag="WP-002",
        service_date="2026-01-10", calving_date="2026-02-01",
        calving_clock="2026-02-01T00:00:00Z",
    )
    add_test_day(lact["id"], "2026-06-08", milk_weight_lbs=1000, fat_pct=3.8,
                 protein_pct=3.1, scc_thousands=180, clock="2026-06-10T00:00:00Z")
    get_success_data(api_client.create_health_treatment(
        {"animal_id": animal["id"], "drug_name": "Mastitis Tx",
         "administered_at": "2026-06-09T08:00:00Z",
         "milk_withhold_hours": 96, "meat_withdrawal_hours": 240}, VET))
    price_sheet = create_price_sheet(herd["id"], settlement_month="2026-06")
    milk_check = get_success_data(api_client.create_milk_check(
        {"herd_id": herd["id"], "price_sheet_id": price_sheet["id"]}, COOP))
    resp = api_client.finalize_milk_check(milk_check["id"], milk_check["version"], COOP)
    validate_error(resp, ApiErrorId.ERR_EMPTY_MILK_POOL.value)
    # The rejected finalize does not transition the check — it stays PROVISIONAL.
    mc = validate_success(api_client.get_milk_check(milk_check["id"], COOP))
    assert mc["status"] == "PROVISIONAL", mc["status"]


# ---------------------------------------------------------------------------
# compensating_invariant
# ---------------------------------------------------------------------------
def test_treatment_void_restores_milk_eligible():
    """PRD §3.9: "A treatment entered in error is instead voided by the `Veterinarian`, moving it `ACTIVE → VOIDED` (again only from `ACTIVE`, otherwise `ERR_TREATMENT_NOT_ACTIVE`); voiding recomputes the animal's `milk_eligible` immediately, since a voided treatment no longer counts toward any withhold."

    Design: Difficulty/compensating_invariant/treatment_void_restores_milk_eligible_invariant
    """
    _herd, animal, treatment = setup_active_cow_with_treatment(
        herd_name="Invariant Eligible Dairy", ear_tag="IE-001",
        administered_at="2026-06-09T08:00:00Z",
        milk_withhold_hours=96, meat_withdrawal_hours=240,
        treatment_clock="2026-06-10T00:00:00Z",
    )
    # Forward administer flipped milk_eligible to false.
    a_before = validate_success(api_client.get_animal(animal["id"], HM))
    assert a_before["milk_eligible"] is False, a_before["milk_eligible"]

    voided = validate_success(api_client.void_health_treatment(treatment["id"], VET))
    assert voided["status"] == "VOIDED", voided["status"]

    a_after = validate_success(api_client.get_animal(animal["id"], HM))
    assert a_after["milk_eligible"] is True, a_after["milk_eligible"]


def test_voided_treatment_status_persists_voided():
    """PRD §3.9: "A treatment entered in error is instead voided by the `Veterinarian`, moving it `ACTIVE → VOIDED` (again only from `ACTIVE`, otherwise `ERR_TREATMENT_NOT_ACTIVE`); voiding recomputes the animal's `milk_eligible` immediately, since a voided treatment no longer counts toward any withhold."

    Design: Difficulty/compensating_invariant/treatment_void_restores_milk_eligible_invariant
    """
    _herd2, _animal, treatment = setup_active_cow_with_treatment(
        herd_name="Invariant Eligible Dairy 2", ear_tag="IE-002",
        administered_at="2026-06-09T08:00:00Z",
        milk_withhold_hours=96, meat_withdrawal_hours=240,
        treatment_clock="2026-06-10T00:00:00Z",
    )
    validate_success(api_client.void_health_treatment(treatment["id"], VET))
    fetched = validate_success(api_client.get_health_treatment(treatment["id"], VET))
    assert fetched["status"] == "VOIDED", fetched["status"]


def test_shift_void_frees_interval_for_overlapping_shift():
    """PRD §3.3: "The check considers only `LOGGED` shifts: voiding a shift (`LOGGED → VOIDED`, permitted only when the shift is `LOGGED`, otherwise `ERR_SHIFT_NOT_LOGGED`) frees its interval so that a later shift that previously would have collided becomes permissible."

    Design: Difficulty/compensating_invariant/milking_shift_void_restores_parlor_interval_availability
    """
    _h, parlor, shift = setup_parlor_with_logged_shift(
        turnaround_minutes=0, herd_name="Invariant Parlor Dairy",
        start_at="2026-06-01T04:00:00Z", end_at="2026-06-01T07:00:00Z",
    )
    voided = validate_success(api_client.void_milking_shift(shift["id"], PT))
    assert voided["status"] == "VOIDED", voided["status"]
    # An overlapping 05:00-08:00 shift now succeeds because the prior interval is freed.
    resp = api_client.create_milking_shift(
        {"parlor_id": parlor["id"], "start_at": "2026-06-01T05:00:00Z",
         "end_at": "2026-06-01T08:00:00Z", "cows_milked": 24}, PT)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "LOGGED", data["status"]


def test_voided_shift_status_persists_voided():
    """PRD §3.3: "voiding a shift (`LOGGED → VOIDED`, permitted only when the shift is `LOGGED`, otherwise `ERR_SHIFT_NOT_LOGGED`) frees its interval so that a later shift that previously would have collided becomes permissible."

    Design: Difficulty/compensating_invariant/milking_shift_void_restores_parlor_interval_availability
    """
    _h, _parlor, shift = setup_parlor_with_logged_shift(
        turnaround_minutes=0, herd_name="Invariant Parlor Dairy 2",
        start_at="2026-06-01T04:00:00Z", end_at="2026-06-01T07:00:00Z",
    )
    validate_success(api_client.void_milking_shift(shift["id"], PT))
    fetched = validate_success(api_client.get_milking_shift(shift["id"], PT))
    assert fetched["status"] == "VOIDED", fetched["status"]


# ---------------------------------------------------------------------------
# Corner: treatment clear gate + scheduled withhold
# ---------------------------------------------------------------------------
def test_clear_treatment_before_withhold_elapsed_rejected():
    """PRD §3.9: "Clearing is permitted only on an `ACTIVE` treatment — otherwise `ERR_TREATMENT_NOT_ACTIVE` — and only when the current clock is at or beyond both `milk_withhold_until` and `meat_withdrawal_until`; if either window is still running the clear is rejected with `ERR_WITHHOLD_NOT_ELAPSED`."

    Design: Corner/state_machines/clear_treatment_before_withhold_elapsed_returns_not_elapsed
    """
    api_client.set_clock("2026-06-10T00:00:00Z", HM)
    herd = _herd("Withhold Clear Dairy")
    animal = get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "WC-001", "birth_date": "2023-01-01"}, HM))
    treatment = get_success_data(api_client.create_health_treatment(
        {"animal_id": animal["id"], "drug_name": "Penicillin",
         "administered_at": "2026-06-09T08:00:00Z",
         "milk_withhold_hours": 96, "meat_withdrawal_hours": 240}, VET))
    # Clock 2026-06-10 is before milk_withhold_until 2026-06-13T08:00Z.
    resp = api_client.clear_health_treatment(treatment["id"], VET)
    validate_error(resp, ApiErrorId.ERR_WITHHOLD_NOT_ELAPSED.value)


def test_clear_treatment_after_windows_elapsed_restores_eligibility():
    """PRD §3.9: "The `Veterinarian` clears a treatment once its windows have elapsed, moving it `ACTIVE → CLEARED`."
    PRD §3.9: "Clearing recomputes the animal's `milk_eligible`, setting it true if no other `ACTIVE` treatment still holds a live milk-withhold."

    Design: Corner/state_machines/clear_treatment_after_withhold_elapsed_succeeds
    """
    api_client.set_clock("2026-06-10T00:00:00Z", HM)
    herd = _herd("Withhold Done Dairy")
    animal = get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "WD-001", "birth_date": "2023-01-01"}, HM))
    treatment = get_success_data(api_client.create_health_treatment(
        {"animal_id": animal["id"], "drug_name": "Penicillin",
         "administered_at": "2026-06-09T08:00:00Z",
         "milk_withhold_hours": 96, "meat_withdrawal_hours": 240}, VET))
    api_client.set_clock("2026-06-20T00:00:00Z", HM)
    cleared = validate_success(api_client.clear_health_treatment(treatment["id"], VET))
    assert cleared["status"] == "CLEARED", cleared["status"]
    a = validate_success(api_client.get_animal(animal["id"], HM))
    assert a["milk_eligible"] is True, a["milk_eligible"]


def test_recording_treatment_sets_milk_eligible_false():
    """PRD §3.9: "While the animal has any `ACTIVE` health treatment whose `milk_withhold_until` is still after the current clock, the animal is not `milk_eligible`. On recording a treatment, the system sets the animal's `milk_eligible` to false if the new treatment's `milk_withhold_until` is after the current clock."

    Design: Corner/cross_cutting_complexity_layers/scheduled_treatment_withhold_sets_milk_eligible_false
    """
    api_client.set_clock("2026-06-10T00:00:00Z", HM)
    herd = _herd("Sched Withhold Dairy")
    animal = get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "SW-001", "birth_date": "2023-01-01"}, HM))
    resp = api_client.create_health_treatment(
        {"animal_id": animal["id"], "drug_name": "Penicillin",
         "administered_at": "2026-06-09T08:00:00Z",
         "milk_withhold_hours": 96, "meat_withdrawal_hours": 240}, VET)
    validate_success(resp, expected_status=201)
    a = validate_success(api_client.get_animal(animal["id"], HM))
    assert a["milk_eligible"] is False, a["milk_eligible"]
