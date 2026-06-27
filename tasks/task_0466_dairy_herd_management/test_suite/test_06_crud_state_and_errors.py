"""CRUD defaults, invalid/valid transitions, not-found and shape errors, listing, RBAC.

Corner instances:
  entities / herd_create_returns_all_fields_and_defaults
  entities / animal_create_applies_heifer_defaults
  entities / animal_get_nonexistent_returns_not_found
  entities / testday_missing_required_milk_weight_returns_invalid_request
  entities / testday_fat_pct_out_of_range_returns_invalid_request
  entities / animal_duplicate_ear_tag_returns_duplicate_key
  entities / coop_price_sheet_duplicate_month_returns_duplicate_key
  entities / parlor_create_requires_existing_herd
  entities / testday_nonexistent_lactation_returns_not_found
  entities / finalize_nonexistent_milkcheck_returns_not_found
  entities / iofc_nonexistent_ration_returns_not_found
  state_machines / dry_off_heifer_returns_animal_not_milking
  state_machines / confirm_already_confirmed_breeding_returns_not_pending
  state_machines / confirm_after_preg_window_returns_window_elapsed
  state_machines / void_already_voided_shift_returns_not_logged
  state_machines / cull_terminal_animal_returns_not_cullable
  state_machines / cancel_provisional_milkcheck_succeeds
  endpoints / list_animals_pagination_envelope
  endpoints / list_test_day_records_filtered_by_lactation
  rbac / parlortech_cannot_create_herd
  rbac / coopagent_cannot_register_animal
  rbac / herdmanager_cannot_confirm_breeding
  rbac / auditor_cannot_finalize_milkcheck
  errors / confirm_nonexistent_breeding_returns_not_found
  errors / clear_nonexistent_treatment_returns_not_found
  errors / void_nonexistent_shift_returns_not_found
  errors / shift_create_nonexistent_parlor_returns_not_found
  errors / milkcheck_create_nonexistent_price_sheet_returns_not_found
  cross_cutting_complexity_layers / occ_finalize_with_stale_version_after_cancel_returns_412
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    setup_open_lactation, add_test_day,
    api_client, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
)

HM = TEST_USERS["herd_manager_headers"]
VET = TEST_USERS["veterinarian_headers"]
PT = TEST_USERS["parlor_tech_headers"]
COOP = TEST_USERS["coop_agent_headers"]
AUD = TEST_USERS["auditor_headers"]

GHOST = "00000000-0000-0000-0000-000000000000"


def _herd(name="CRUD Dairy"):
    return get_success_data(api_client.create_herd(
        {"name": name, "federal_order_number": "30"}, HM))


# ---------------------------------------------------------------------------
# entities — creation / defaults
# ---------------------------------------------------------------------------
def test_herd_create_returns_defaults():
    """PRD §3.1: "A new herd opens with its `milk_quality_status` at `GOOD` and its `active_animal_count` at 0; both are computed fields the herd never sets directly."
    PRD §2.5: "The `version` field is an integer that begins at 1 and increments by one on every mutation of the resource; it is the basis for the optimistic concurrency mechanism described in §2.7."

    Design: Corner/entities/herd_create_returns_all_fields_and_defaults
    """
    data = validate_success(api_client.create_herd(
        {"name": "Fresh Dairy", "federal_order_number": "30"}, HM), expected_status=201)
    assert data["milk_quality_status"] == "GOOD", data["milk_quality_status"]
    assert data["active_animal_count"] == 0, data["active_animal_count"]
    assert data["version"] == 1, data["version"]


def test_animal_create_applies_heifer_defaults():
    """PRD §3.2: "A newly registered animal starts with `status` of `HEIFER`, `parity` of 0 (a heifer has not yet calved), and `milk_eligible` of `true`."

    Design: Corner/entities/animal_create_applies_heifer_defaults
    """
    herd = _herd("Animal Default Dairy")
    data = validate_success(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "AD-001", "birth_date": "2024-01-01"}, HM),
        expected_status=201)
    assert data["status"] == "HEIFER", data["status"]
    assert data["parity"] == 0, data["parity"]
    assert data["milk_eligible"] is True, data["milk_eligible"]


# ---------------------------------------------------------------------------
# entities — not found / required / type / duplicate / parent
# ---------------------------------------------------------------------------
def test_get_nonexistent_animal_returns_not_found():
    """PRD §2.9: "Nested Resource Retrieval and Reference Validation When a request carries a resource identifier in its path, that identifier is validated first; if it does not correspond to an existing resource the request fails immediately with the resource-specific not-found error (for example `ERR_HERD_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_LACTATION_NOT_FOUND`, `ERR_BREEDING_NOT_FOUND`, `ERR_TREATMENT_NOT_FOUND`, `ERR_MILK_CHECK_NOT_FOUND`, `ERR_PARLOR_NOT_FOUND`, `ERR_RATION_NOT_FOUND`, `ERR_PRICE_SHEET_NOT_FOUND`, or `ERR_SHIFT_NOT_FOUND`)."

    Design: Corner/entities/animal_get_nonexistent_returns_not_found
    """
    _herd("NF Dairy")
    resp = api_client.get_animal(GHOST, HM)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_FOUND.value)


def test_testday_missing_milk_weight_rejected():
    """PRD §3.4: "The payload names the `lactation_id`, the `test_date` the sample was drawn, the `milk_weight_lbs` produced that day (at least 0), the butterfat `fat_pct` (between 0 and 15 inclusive), the true-protein `protein_pct` (between 0 and 10 inclusive), and the somatic-cell count `scc_thousands` in thousands per millilitre (at least 0). Values outside these ranges are rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/testday_missing_required_milk_weight_returns_invalid_request
    """
    _h, _a, lact, _c = setup_open_lactation(
        herd_name="Req Field Dairy", ear_tag="RF-001",
        service_date="2026-01-10", calving_date="2026-02-01",
        calving_clock="2026-02-01T00:00:00Z",
    )
    api_client.set_clock("2026-03-10T00:00:00Z", HM)
    resp = api_client.create_test_day_record(
        {"lactation_id": lact["id"], "test_date": "2026-03-10",
         "fat_pct": 3.8, "protein_pct": 3.1, "scc_thousands": 150}, PT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_testday_fat_pct_out_of_range_rejected():
    """PRD §3.4: "The payload names the `lactation_id`, the `test_date` the sample was drawn, the `milk_weight_lbs` produced that day (at least 0), the butterfat `fat_pct` (between 0 and 15 inclusive), the true-protein `protein_pct` (between 0 and 10 inclusive), and the somatic-cell count `scc_thousands` in thousands per millilitre (at least 0)."

    Design: Corner/entities/testday_fat_pct_out_of_range_returns_invalid_request
    """
    _h, _a, lact, _c = setup_open_lactation(
        herd_name="Range Dairy", ear_tag="RG-001",
        service_date="2026-01-10", calving_date="2026-02-01",
        calving_clock="2026-02-01T00:00:00Z",
    )
    api_client.set_clock("2026-03-10T00:00:00Z", HM)
    resp = api_client.create_test_day_record(
        {"lactation_id": lact["id"], "test_date": "2026-03-10", "milk_weight_lbs": 85.0,
         "fat_pct": 20.0, "protein_pct": 3.1, "scc_thousands": 150}, PT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_animal_duplicate_ear_tag_rejected():
    """PRD §3.2: "The payload supplies the `herd_id`, an `ear_tag` that must be unique within the herd (a collision is rejected with `ERR_DUPLICATE_KEY`), a `birth_date`, and optionally a `dam_id` naming the animal's genetic dam."

    Design: Corner/entities/animal_duplicate_ear_tag_returns_duplicate_key
    """
    herd = _herd("Dup Tag Dairy")
    get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "DUP-1", "birth_date": "2023-01-01"}, HM))
    resp = api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "DUP-1", "birth_date": "2023-02-01"}, HM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)


def test_price_sheet_duplicate_month_rejected():
    """PRD §3.1: "It carries the `herd_id`, the `settlement_month` it applies to (a `YYYY-MM` string that must be unique within the herd — a duplicate is rejected with `ERR_DUPLICATE_KEY`), and the announced rates: `fat_price_per_lb`, `protein_price_per_lb`, and `other_solids_price_per_lb` (butterfat, true-protein, and other-solids dollars per pound), `ppd_per_cwt` (the Producer Price Differential in dollars per hundredweight), `advance_rate_per_cwt` (the provisional rate paid before final settlement), and an optional `hauling_rate_per_cwt` deduction that defaults to 0."

    Design: Corner/entities/coop_price_sheet_duplicate_month_returns_duplicate_key
    """
    herd = _herd("Dup Month Dairy")
    get_success_data(api_client.create_price_sheet(
        {"herd_id": herd["id"], "settlement_month": "2026-06",
         "fat_price_per_lb": 2.805, "protein_price_per_lb": 3.515,
         "other_solids_price_per_lb": 0.405, "ppd_per_cwt": 1.205,
         "advance_rate_per_cwt": 16.00}, COOP))
    resp = api_client.create_price_sheet(
        {"herd_id": herd["id"], "settlement_month": "2026-06",
         "fat_price_per_lb": 2.900, "protein_price_per_lb": 3.600,
         "other_solids_price_per_lb": 0.410, "ppd_per_cwt": 1.300,
         "advance_rate_per_cwt": 16.50}, COOP)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)


def test_parlor_create_nonexistent_herd_rejected():
    """PRD §2.9: "Nested Resource Retrieval and Reference Validation When a request carries a resource identifier in its path, that identifier is validated first; if it does not correspond to an existing resource the request fails immediately with the resource-specific not-found error (for example `ERR_HERD_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_LACTATION_NOT_FOUND`, `ERR_BREEDING_NOT_FOUND`, `ERR_TREATMENT_NOT_FOUND`, `ERR_MILK_CHECK_NOT_FOUND`, `ERR_PARLOR_NOT_FOUND`, `ERR_RATION_NOT_FOUND`, `ERR_PRICE_SHEET_NOT_FOUND`, or `ERR_SHIFT_NOT_FOUND`)."

    Design: Corner/entities/parlor_create_requires_existing_herd
    """
    resp = api_client.create_parlor(
        {"herd_id": GHOST, "name": "Ghost Parlor", "stall_capacity": 12}, HM)
    validate_error(resp, ApiErrorId.ERR_HERD_NOT_FOUND.value)


def test_testday_nonexistent_lactation_rejected():
    """PRD §2.9: "Nested Resource Retrieval and Reference Validation When a request carries a resource identifier in its path, that identifier is validated first; if it does not correspond to an existing resource the request fails immediately with the resource-specific not-found error (for example `ERR_HERD_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_LACTATION_NOT_FOUND`, `ERR_BREEDING_NOT_FOUND`, `ERR_TREATMENT_NOT_FOUND`, `ERR_MILK_CHECK_NOT_FOUND`, `ERR_PARLOR_NOT_FOUND`, `ERR_RATION_NOT_FOUND`, `ERR_PRICE_SHEET_NOT_FOUND`, or `ERR_SHIFT_NOT_FOUND`)."

    Design: Corner/entities/testday_nonexistent_lactation_returns_not_found
    """
    _herd("Lact NF Dairy")
    resp = api_client.create_test_day_record(
        {"lactation_id": GHOST, "test_date": "2026-03-10", "milk_weight_lbs": 80.0,
         "fat_pct": 3.8, "protein_pct": 3.1, "scc_thousands": 150}, PT)
    validate_error(resp, ApiErrorId.ERR_LACTATION_NOT_FOUND.value)


def test_finalize_nonexistent_milkcheck_rejected():
    """PRD §2.9: "Nested Resource Retrieval and Reference Validation When a request carries a resource identifier in its path, that identifier is validated first; if it does not correspond to an existing resource the request fails immediately with the resource-specific not-found error (for example `ERR_HERD_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_LACTATION_NOT_FOUND`, `ERR_BREEDING_NOT_FOUND`, `ERR_TREATMENT_NOT_FOUND`, `ERR_MILK_CHECK_NOT_FOUND`, `ERR_PARLOR_NOT_FOUND`, `ERR_RATION_NOT_FOUND`, `ERR_PRICE_SHEET_NOT_FOUND`, or `ERR_SHIFT_NOT_FOUND`)."

    Design: Corner/entities/finalize_nonexistent_milkcheck_returns_not_found
    """
    herd = _herd("MC NF Dairy")
    ps = get_success_data(api_client.create_price_sheet(
        {"herd_id": herd["id"], "settlement_month": "2026-06",
         "fat_price_per_lb": 2.805, "protein_price_per_lb": 3.515,
         "other_solids_price_per_lb": 0.405, "ppd_per_cwt": 1.205,
         "advance_rate_per_cwt": 16.00}, COOP))
    mc = get_success_data(api_client.create_milk_check(
        {"herd_id": herd["id"], "price_sheet_id": ps["id"]}, COOP))
    resp = api_client.finalize_milk_check(GHOST, mc["version"], COOP)
    validate_error(resp, ApiErrorId.ERR_MILK_CHECK_NOT_FOUND.value)


def test_iofc_nonexistent_ration_rejected():
    """PRD §2.9: "Nested Resource Retrieval and Reference Validation When a request carries a resource identifier in its path, that identifier is validated first; if it does not correspond to an existing resource the request fails immediately with the resource-specific not-found error (for example `ERR_HERD_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_LACTATION_NOT_FOUND`, `ERR_BREEDING_NOT_FOUND`, `ERR_TREATMENT_NOT_FOUND`, `ERR_MILK_CHECK_NOT_FOUND`, `ERR_PARLOR_NOT_FOUND`, `ERR_RATION_NOT_FOUND`, `ERR_PRICE_SHEET_NOT_FOUND`, or `ERR_SHIFT_NOT_FOUND`)."

    Design: Corner/entities/iofc_nonexistent_ration_returns_not_found
    """
    herd = _herd("Ration NF Dairy")
    animal = get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "RN-001", "birth_date": "2023-01-01"}, HM))
    resp = api_client.get_iofc(
        animal["id"], HM, params={"ration_id": GHOST, "blend_price_per_cwt": 22.000})
    validate_error(resp, ApiErrorId.ERR_RATION_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# state_machines — invalid / idempotent / precondition / valid
# ---------------------------------------------------------------------------
def test_dry_off_heifer_rejected():
    """PRD §3.2: "Between calvings, when a cow is to stop being milked, the `HerdManager` dries her off: this transition is permitted only when the animal is `ACTIVE` — otherwise `ERR_ANIMAL_NOT_MILKING` — and only when she has an `OPEN` lactation — otherwise `ERR_NO_OPEN_LACTATION`."

    Design: Corner/state_machines/dry_off_heifer_returns_animal_not_milking
    """
    herd = _herd("DryOff Dairy")
    animal = get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "DO-001", "birth_date": "2024-01-01"}, HM))
    resp = api_client.dry_off_animal(animal["id"], HM)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_MILKING.value)


def test_confirm_already_confirmed_breeding_rejected():
    """PRD §3.5: "Confirmation is permitted only on an event still in `BRED` — otherwise `ERR_BREEDING_NOT_PENDING` — and only at or before `confirm_due_at`; if the current clock has passed `confirm_due_at` the confirmation is rejected with `ERR_PREG_CHECK_WINDOW_ELAPSED`."

    Design: Corner/state_machines/confirm_already_confirmed_breeding_returns_not_pending
    """
    api_client.set_clock("2026-01-10T00:00:00Z", HM)
    herd = _herd("Confirm Dairy")
    animal = get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "CF-001", "birth_date": "2023-01-01"}, HM))
    be = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-01-10", "sire_code": "S-1"}, VET))
    get_success_data(api_client.confirm_breeding_event(be["id"], VET))
    resp = api_client.confirm_breeding_event(be["id"], VET)
    validate_error(resp, ApiErrorId.ERR_BREEDING_NOT_PENDING.value)


def test_confirm_after_preg_window_rejected():
    """PRD §3.5: "only at or before `confirm_due_at`; if the current clock has passed `confirm_due_at` the confirmation is rejected with `ERR_PREG_CHECK_WINDOW_ELAPSED`."

    Design: Corner/state_machines/confirm_after_preg_window_returns_window_elapsed
    """
    api_client.set_clock("2026-01-10T00:00:00Z", HM)
    herd = _herd("Window Dairy")
    animal = get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "WN-001", "birth_date": "2023-01-01"}, HM))
    be = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-01-10", "sire_code": "S-1"}, VET))
    # service 2026-01-10 + 45d = 2026-02-24; clock 2026-03-01 is past the window.
    api_client.set_clock("2026-03-01T00:00:00Z", HM)
    resp = api_client.confirm_breeding_event(be["id"], VET)
    validate_error(resp, ApiErrorId.ERR_PREG_CHECK_WINDOW_ELAPSED.value)


def test_void_already_voided_shift_rejected():
    """PRD §3.3: "The check considers only `LOGGED` shifts: voiding a shift (`LOGGED → VOIDED`, permitted only when the shift is `LOGGED`, otherwise `ERR_SHIFT_NOT_LOGGED`) frees its interval so that a later shift that previously would have collided becomes permissible."

    Design: Corner/state_machines/void_already_voided_shift_returns_not_logged
    """
    herd = _herd("Void Shift Dairy")
    parlor = get_success_data(api_client.create_parlor(
        {"herd_id": herd["id"], "name": "P1", "stall_capacity": 12}, HM))
    shift = get_success_data(api_client.create_milking_shift(
        {"parlor_id": parlor["id"], "start_at": "2026-06-01T04:00:00Z",
         "end_at": "2026-06-01T07:00:00Z", "cows_milked": 12}, PT))
    get_success_data(api_client.void_milking_shift(shift["id"], PT))
    resp = api_client.void_milking_shift(shift["id"], PT)
    validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_LOGGED.value)


def test_cull_already_culled_animal_rejected():
    """PRD §3.10: "A cull may only be executed on an animal currently in `ACTIVE` or `DRY` status; an animal that is already terminal or still a `HEIFER` is rejected with `ERR_ANIMAL_NOT_CULLABLE`."

    Design: Corner/state_machines/cull_terminal_animal_returns_not_cullable
    """
    api_client.set_clock("2026-01-15T00:00:00Z", HM)
    herd = _herd("Cull Terminal Dairy")
    animal = get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "CT-001", "birth_date": "2022-01-01"}, HM))
    be = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2025-12-20", "sire_code": "S-1"}, VET))
    get_success_data(api_client.confirm_breeding_event(be["id"], VET))
    get_success_data(api_client.create_calving_event(
        {"animal_id": animal["id"], "breeding_event_id": be["id"], "calving_date": "2026-01-15"}, HM))
    get_success_data(api_client.create_cull_decision(
        {"animal_id": animal["id"], "reason": "LOW_PRODUCTION", "disposition": "DAIRY_SALE",
         "decided_at": "2026-01-20T10:00:00Z"}, HM))
    resp = api_client.create_cull_decision(
        {"animal_id": animal["id"], "reason": "AGE", "disposition": "DAIRY_SALE",
         "decided_at": "2026-01-21T10:00:00Z"}, HM)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_CULLABLE.value)


def test_cancel_provisional_milkcheck_succeeds():
    """PRD §3.8: "Cancelling a check instead (`PROVISIONAL → CANCELLED`, likewise OCC-guarded and likewise requiring a `PROVISIONAL` check) stamps no test-day records and pools nothing; the `advance_paid` is retained on the record purely as informational history."
    PRD §3.8: "Finalizing increments the milk check's `version` by one, as does cancelling."

    Design: Corner/state_machines/cancel_provisional_milkcheck_succeeds
    """
    herd = _herd("Cancel Check Dairy")
    ps = get_success_data(api_client.create_price_sheet(
        {"herd_id": herd["id"], "settlement_month": "2026-06",
         "fat_price_per_lb": 2.805, "protein_price_per_lb": 3.515,
         "other_solids_price_per_lb": 0.405, "ppd_per_cwt": 1.205,
         "advance_rate_per_cwt": 16.00}, COOP))
    mc = get_success_data(api_client.create_milk_check(
        {"herd_id": herd["id"], "price_sheet_id": ps["id"]}, COOP))
    data = validate_success(api_client.cancel_milk_check(mc["id"], mc["version"], COOP))
    assert data["status"] == "CANCELLED", data["status"]
    assert data["version"] == 2, data["version"]


# ---------------------------------------------------------------------------
# endpoints — listing
# ---------------------------------------------------------------------------
def test_list_animals_pagination_envelope():
    """PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_animals_pagination_envelope
    """
    herd = _herd("List Dairy")
    get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "L-001", "birth_date": "2023-01-01"}, HM))
    get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "L-002", "birth_date": "2023-01-01"}, HM))
    data, meta = validate_paginated(api_client.list_animals(AUD, params={"herd_id": herd["id"]}))
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is False, meta["has_more"]


def test_list_test_day_records_filtered_by_lactation_has_day_in_milk():
    """PRD §3.4: "The record's `day_in_milk` is computed, not supplied: it is the whole number of days from the lactation's `start_date` to the `test_date`, taking the floor."

    Design: Corner/endpoints/list_test_day_records_filtered_by_lactation
    """
    _h, _a, lact, _c = setup_open_lactation(
        herd_name="TDR List Dairy", ear_tag="TL-001",
        service_date="2026-01-10", calving_date="2026-02-01",
        calving_clock="2026-02-01T00:00:00Z",
    )
    add_test_day(lact["id"], "2026-03-13", milk_weight_lbs=85.0, fat_pct=3.8,
                 protein_pct=3.1, scc_thousands=150, clock="2026-03-13T00:00:00Z")
    data, _meta = validate_paginated(
        api_client.list_test_day_records(AUD, params={"lactation_id": lact["id"]}))
    assert len(data) >= 1
    assert data[0]["day_in_milk"] == 40, data[0]["day_in_milk"]


# ---------------------------------------------------------------------------
# rbac
# ---------------------------------------------------------------------------
def test_parlortech_cannot_create_herd():
    """PRD §2.1: "When a well-authenticated user attempts an operation their role is not permitted to perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.1: "The `HerdManager` owns herd setup, animal registration, lactation lifecycle, calving, dry-off, culling, rations, and parlors, and shares some recording duties with other roles."

    Design: Corner/rbac/parlortech_cannot_create_herd
    """
    resp = api_client.create_herd({"name": "Forbidden Dairy", "federal_order_number": "30"}, PT)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_coopagent_cannot_register_animal():
    """PRD §2.1: "The HerdManager owns herd setup, animal registration..."
    PRD §2.1: "When a well-authenticated user attempts an operation their role is not permitted to perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/coopagent_cannot_register_animal
    """
    herd = _herd("RBAC Animal Dairy")
    resp = api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "RB-001", "birth_date": "2023-01-01"}, COOP)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_herdmanager_cannot_confirm_breeding():
    """PRD §2.1: "The `Veterinarian` owns breeding confirmation, health treatments, and withhold clearance, and shares AI logging and treatment recording with the `HerdManager`."
    PRD §2.1: "When a well-authenticated user attempts an operation their role is not permitted to perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/herdmanager_cannot_confirm_breeding
    """
    api_client.set_clock("2026-01-10T00:00:00Z", HM)
    herd = _herd("RBAC Vet Dairy")
    animal = get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "RV-001", "birth_date": "2023-01-01"}, HM))
    be = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-01-10", "sire_code": "S-1"}, VET))
    resp = api_client.confirm_breeding_event(be["id"], HM)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_auditor_cannot_finalize_milkcheck():
    """PRD §2.1: "The `CoopSettlementAgent` owns FMMO price sheets and the entire milk-check settlement lifecycle. The `Auditor` has read-only oversight across all herd data and may call any list or detail endpoint but may not mutate anything."

    Design: Corner/rbac/auditor_cannot_finalize_milkcheck
    """
    herd = _herd("RBAC Audit Dairy")
    ps = get_success_data(api_client.create_price_sheet(
        {"herd_id": herd["id"], "settlement_month": "2026-06",
         "fat_price_per_lb": 2.805, "protein_price_per_lb": 3.515,
         "other_solids_price_per_lb": 0.405, "ppd_per_cwt": 1.205,
         "advance_rate_per_cwt": 16.00}, COOP))
    mc = get_success_data(api_client.create_milk_check(
        {"herd_id": herd["id"], "price_sheet_id": ps["id"]}, COOP))
    resp = api_client.finalize_milk_check(mc["id"], mc["version"], AUD)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ---------------------------------------------------------------------------
# errors — not-found on action / reference endpoints
# ---------------------------------------------------------------------------
def test_confirm_nonexistent_breeding_rejected():
    """PRD §2.9: "Nested Resource Retrieval and Reference Validation When a request carries a resource identifier in its path, that identifier is validated first; if it does not correspond to an existing resource the request fails immediately with the resource-specific not-found error (for example `ERR_HERD_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_LACTATION_NOT_FOUND`, `ERR_BREEDING_NOT_FOUND`, `ERR_TREATMENT_NOT_FOUND`, `ERR_MILK_CHECK_NOT_FOUND`, `ERR_PARLOR_NOT_FOUND`, `ERR_RATION_NOT_FOUND`, `ERR_PRICE_SHEET_NOT_FOUND`, or `ERR_SHIFT_NOT_FOUND`)."

    Design: Corner/errors/confirm_nonexistent_breeding_returns_not_found
    """
    _herd("BE NF Dairy")
    resp = api_client.confirm_breeding_event(GHOST, VET)
    validate_error(resp, ApiErrorId.ERR_BREEDING_NOT_FOUND.value)


def test_clear_nonexistent_treatment_rejected():
    """PRD §2.9: "Nested Resource Retrieval and Reference Validation When a request carries a resource identifier in its path, that identifier is validated first; if it does not correspond to an existing resource the request fails immediately with the resource-specific not-found error (for example `ERR_HERD_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_LACTATION_NOT_FOUND`, `ERR_BREEDING_NOT_FOUND`, `ERR_TREATMENT_NOT_FOUND`, `ERR_MILK_CHECK_NOT_FOUND`, `ERR_PARLOR_NOT_FOUND`, `ERR_RATION_NOT_FOUND`, `ERR_PRICE_SHEET_NOT_FOUND`, or `ERR_SHIFT_NOT_FOUND`)."

    Design: Corner/errors/clear_nonexistent_treatment_returns_not_found
    """
    _herd("Tx NF Dairy")
    resp = api_client.clear_health_treatment(GHOST, VET)
    validate_error(resp, ApiErrorId.ERR_TREATMENT_NOT_FOUND.value)


def test_void_nonexistent_shift_rejected():
    """PRD §2.9: "Nested Resource Retrieval and Reference Validation When a request carries a resource identifier in its path, that identifier is validated first; if it does not correspond to an existing resource the request fails immediately with the resource-specific not-found error (for example `ERR_HERD_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_LACTATION_NOT_FOUND`, `ERR_BREEDING_NOT_FOUND`, `ERR_TREATMENT_NOT_FOUND`, `ERR_MILK_CHECK_NOT_FOUND`, `ERR_PARLOR_NOT_FOUND`, `ERR_RATION_NOT_FOUND`, `ERR_PRICE_SHEET_NOT_FOUND`, or `ERR_SHIFT_NOT_FOUND`)."

    Design: Corner/errors/void_nonexistent_shift_returns_not_found
    """
    _herd("Shift NF Dairy")
    resp = api_client.void_milking_shift(GHOST, PT)
    validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_FOUND.value)


def test_shift_create_nonexistent_parlor_rejected():
    """PRD §2.9: "Nested Resource Retrieval and Reference Validation When a request carries a resource identifier in its path, that identifier is validated first; if it does not correspond to an existing resource the request fails immediately with the resource-specific not-found error (for example `ERR_HERD_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_LACTATION_NOT_FOUND`, `ERR_BREEDING_NOT_FOUND`, `ERR_TREATMENT_NOT_FOUND`, `ERR_MILK_CHECK_NOT_FOUND`, `ERR_PARLOR_NOT_FOUND`, `ERR_RATION_NOT_FOUND`, `ERR_PRICE_SHEET_NOT_FOUND`, or `ERR_SHIFT_NOT_FOUND`)."

    Design: Corner/errors/shift_create_nonexistent_parlor_returns_not_found
    """
    _herd("Parlor NF Dairy")
    resp = api_client.create_milking_shift(
        {"parlor_id": GHOST, "start_at": "2026-06-01T04:00:00Z",
         "end_at": "2026-06-01T07:00:00Z", "cows_milked": 10}, PT)
    validate_error(resp, ApiErrorId.ERR_PARLOR_NOT_FOUND.value)


def test_milkcheck_create_nonexistent_price_sheet_rejected():
    """PRD §2.9: "Nested Resource Retrieval and Reference Validation When a request carries a resource identifier in its path, that identifier is validated first; if it does not correspond to an existing resource the request fails immediately with the resource-specific not-found error (for example `ERR_HERD_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_LACTATION_NOT_FOUND`, `ERR_BREEDING_NOT_FOUND`, `ERR_TREATMENT_NOT_FOUND`, `ERR_MILK_CHECK_NOT_FOUND`, `ERR_PARLOR_NOT_FOUND`, `ERR_RATION_NOT_FOUND`, `ERR_PRICE_SHEET_NOT_FOUND`, or `ERR_SHIFT_NOT_FOUND`)."

    Design: Corner/errors/milkcheck_create_nonexistent_price_sheet_returns_not_found
    """
    herd = _herd("PS NF Dairy")
    resp = api_client.create_milk_check(
        {"herd_id": herd["id"], "price_sheet_id": GHOST}, COOP)
    validate_error(resp, ApiErrorId.ERR_PRICE_SHEET_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# auth missing context
# ---------------------------------------------------------------------------
def test_missing_user_context_rejected():
    """PRD §2.1: "Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401)."

    Design: Corner/validations/auth_missing_user_context_returns_401
    """
    resp = api_client.create_herd({"name": "No Auth Dairy", "federal_order_number": "30"}, {})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT.value)


# ---------------------------------------------------------------------------
# OCC stale version
# ---------------------------------------------------------------------------
def test_occ_finalize_with_stale_version_after_cancel_rejected():
    """PRD §2.7: "Before any business precondition is evaluated, the server compares this value to the milk check's current `version`. If they do not match — because another settlement writer has already cancelled or re-issued that provisional check since the client last read it, advancing its version — the request is rejected with `ERR_STALE_MILK_CHECK_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_finalize_with_stale_version_after_cancel_returns_412
    """
    herd = _herd("OCC Dairy")
    ps = get_success_data(api_client.create_price_sheet(
        {"herd_id": herd["id"], "settlement_month": "2026-06",
         "fat_price_per_lb": 2.805, "protein_price_per_lb": 3.515,
         "other_solids_price_per_lb": 0.405, "ppd_per_cwt": 1.205,
         "advance_rate_per_cwt": 16.00}, COOP))
    mc = get_success_data(api_client.create_milk_check(
        {"herd_id": herd["id"], "price_sheet_id": ps["id"]}, COOP))
    v0 = mc["version"]
    # Cancel with the matching version advances version to 2.
    get_success_data(api_client.cancel_milk_check(mc["id"], v0, COOP))
    # Finalize replays the now-stale v0.
    resp = api_client.finalize_milk_check(mc["id"], v0, COOP)
    validate_error(resp, ApiErrorId.ERR_STALE_MILK_CHECK_VERSION.value)
