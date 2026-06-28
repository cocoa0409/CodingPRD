"""Cyclic state machines and multi-entity cascades.

Difficulty instances:
  non_linear_state_machine / breeding_event_bred_open_retry_cycle
  non_linear_state_machine / animal_active_dry_active_cycle
  transitive_cascade / calving_cascade_close_open_lactation_status_count_depth3
  transitive_cascade / milk_check_finalize_cascade_stamp_then_quality_depth2
Corner instances:
  cross_cutting_complexity_layers / cascade_calving_first_parity_opens_single_lactation
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_provisional_milk_check_single_record,
    api_client, TEST_USERS,
)

HM = TEST_USERS["herd_manager_headers"]
VET = TEST_USERS["veterinarian_headers"]
COOP = TEST_USERS["coop_agent_headers"]


def _herd(name):
    return get_success_data(api_client.create_herd(
        {"name": name, "federal_order_number": "30"}, HM))


def _animal(herd_id, ear_tag, birth_date="2022-01-01"):
    return get_success_data(api_client.create_animal(
        {"herd_id": herd_id, "ear_tag": ear_tag, "birth_date": birth_date}, HM))


def test_breeding_bred_open_then_new_service_confirmed():
    """PRD §3.5: "When a service fails, the `Veterinarian` marks it open, moving the event `BRED → OPEN` (again permitted only from `BRED`, otherwise `ERR_BREEDING_NOT_PENDING`); this returns the animal to a breedable state so a fresh service can be logged, completing the retry cycle."
    PRD §3.5: "The `Veterinarian` confirms a pregnancy, moving the event `BRED → CONFIRMED_PREGNANT`."

    Design: Difficulty/non_linear_state_machine/breeding_event_bred_open_retry_cycle
    """
    api_client.set_clock("2026-02-01T00:00:00Z", HM)
    herd = _herd("Repro Dairy")
    animal = _animal(herd["id"], "RP-001")
    be1 = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-02-01", "sire_code": "S-1"}, VET))
    get_success_data(api_client.mark_open_breeding_event(be1["id"], VET))
    api_client.set_clock("2026-03-05T00:00:00Z", HM)
    be2 = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-03-05", "sire_code": "S-2"}, VET))

    confirmed = validate_success(api_client.confirm_breeding_event(be2["id"], VET))
    assert confirmed["status"] == "CONFIRMED_PREGNANT", confirmed["status"]

    first = validate_success(api_client.get_breeding_event(be1["id"], VET))
    assert first["status"] == "OPEN", first["status"]


def test_breeding_first_event_stays_open_after_retry_cycle():
    """PRD §3.5: "this returns the animal to a breedable state so a fresh service can be logged, completing the retry cycle. The `BRED → OPEN` branch carries no calculation; it exists purely to release the animal for re-service."

    Design: Difficulty/non_linear_state_machine/breeding_event_bred_open_retry_cycle
    """
    api_client.set_clock("2026-02-01T00:00:00Z", HM)
    herd = _herd("Repro Dairy 2")
    animal = _animal(herd["id"], "RP-002")
    be1 = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-02-01", "sire_code": "S-1"}, VET))
    opened = validate_success(api_client.mark_open_breeding_event(be1["id"], VET))
    assert opened["status"] == "OPEN", opened["status"]
    # The release lets a new service be logged at a later date.
    api_client.set_clock("2026-03-05T00:00:00Z", HM)
    be2 = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-03-05", "sire_code": "S-2"}, VET))
    assert be2["status"] == "BRED", be2["status"]


def _bring_to_active_parity1(herd_id, animal_id, service_date, calving_date):
    be = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal_id, "service_date": service_date, "sire_code": "S-1"}, VET))
    get_success_data(api_client.confirm_breeding_event(be["id"], VET))
    return get_success_data(api_client.create_calving_event(
        {"animal_id": animal_id, "breeding_event_id": be["id"], "calving_date": calving_date}, HM))


def test_animal_active_dry_active_increments_parity_to_two():
    """PRD §3.2: "Recording a calving (see §3.6) advances a `HEIFER` to `ACTIVE` and increments `parity` to 1; thereafter each subsequent calving moves the cow from `DRY` back to `ACTIVE` and increments `parity` again."

    Design: Difficulty/non_linear_state_machine/animal_active_dry_active_cycle
    """
    api_client.set_clock("2026-01-15T00:00:00Z", HM)
    herd = _herd("Cycle Dairy")
    animal = _animal(herd["id"], "CY-001")
    _bring_to_active_parity1(herd["id"], animal["id"], "2025-12-20", "2026-01-15")
    get_success_data(api_client.dry_off_animal(animal["id"], HM))
    be2 = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-02-20", "sire_code": "S-2"}, VET))
    get_success_data(api_client.confirm_breeding_event(be2["id"], VET))

    get_success_data(api_client.create_calving_event(
        {"animal_id": animal["id"], "breeding_event_id": be2["id"], "calving_date": "2026-12-01"}, HM))

    final = validate_success(api_client.get_animal(animal["id"], HM))
    assert final["status"] == "ACTIVE", final["status"]
    assert final["parity"] == 2, final["parity"]


def test_animal_dry_off_returns_dry_status():
    """PRD §3.2: "Drying off moves the animal `ACTIVE → DRY` and, as a cross-entity side effect, transitions her `OPEN` lactation to `DRY` and stamps that lactation's `dry_off_date`."

    Design: Difficulty/non_linear_state_machine/animal_active_dry_active_cycle
    """
    api_client.set_clock("2026-01-15T00:00:00Z", HM)
    herd = _herd("Cycle Dairy 2")
    animal = _animal(herd["id"], "CY-002")
    _bring_to_active_parity1(herd["id"], animal["id"], "2025-12-20", "2026-01-15")
    dried = validate_success(api_client.dry_off_animal(animal["id"], HM))
    assert dried["status"] == "DRY", dried["status"]
    assert dried["parity"] == 1, dried["parity"]


def test_calving_cascade_closes_prior_opens_new_keeps_count():
    """PRD §3.6: "If the animal has a prior `OPEN` or `DRY` lactation, that lactation is transitioned to `CLOSED` and its `id` is recorded on the calving as `closed_lactation_id`; if there is no prior lactation (the heifer's first calving), `closed_lactation_id` is null."
    PRD §3.6: "A new lactation is then opened in `OPEN` status with its `start_date` equal to the `calving_date`, and its `id` is recorded on the calving as `opened_lactation_id`."

    Design: Difficulty/transitive_cascade/calving_cascade_close_open_lactation_status_count_depth3
    """
    api_client.set_clock("2026-01-15T00:00:00Z", HM)
    herd = _herd("Cascade Dairy")
    animal = _animal(herd["id"], "CS-001")
    ce1 = _bring_to_active_parity1(herd["id"], animal["id"], "2025-12-20", "2026-01-15")
    lact1_id = ce1["opened_lactation_id"]
    get_success_data(api_client.dry_off_animal(animal["id"], HM))
    be2 = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-02-20", "sire_code": "S-2"}, VET))
    get_success_data(api_client.confirm_breeding_event(be2["id"], VET))

    ce2 = get_success_data(api_client.create_calving_event(
        {"animal_id": animal["id"], "breeding_event_id": be2["id"], "calving_date": "2026-12-01"}, HM))
    lact2_id = ce2["opened_lactation_id"]

    l1 = validate_success(api_client.get_lactation(lact1_id, HM))
    assert l1["status"] == "CLOSED", l1["status"]
    l2 = validate_success(api_client.get_lactation(lact2_id, HM))
    assert l2["status"] == "OPEN", l2["status"]


def test_calving_cascade_animal_active_and_herd_count_recomputed():
    """PRD §3.6: "Finally the herd's `active_animal_count` is recomputed to reflect that the animal is now `ACTIVE`."
    PRD §2.8: "The herd's `active_animal_count` is always the count of that herd's animals whose status is `ACTIVE` or `DRY` — heifers, sold, culled, and dead animals do not count."

    Design: Difficulty/transitive_cascade/calving_cascade_close_open_lactation_status_count_depth3
    """
    api_client.set_clock("2026-01-15T00:00:00Z", HM)
    herd = _herd("Cascade Dairy 2")
    animal = _animal(herd["id"], "CS-002")
    _bring_to_active_parity1(herd["id"], animal["id"], "2025-12-20", "2026-01-15")
    get_success_data(api_client.dry_off_animal(animal["id"], HM))
    be2 = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-02-20", "sire_code": "S-2"}, VET))
    get_success_data(api_client.confirm_breeding_event(be2["id"], VET))
    get_success_data(api_client.create_calving_event(
        {"animal_id": animal["id"], "breeding_event_id": be2["id"], "calving_date": "2026-12-01"}, HM))

    a = validate_success(api_client.get_animal(animal["id"], HM))
    assert a["status"] == "ACTIVE", a["status"]
    h = validate_success(api_client.get_herd(herd["id"], HM))
    assert h["active_animal_count"] == 1, h["active_animal_count"]


def test_finalize_stamps_pooled_record_with_check_id():
    """PRD §3.8: "As the records are pooled, each one's `included_in_milk_check_id` is stamped with this check's `id`."

    Design: Difficulty/transitive_cascade/milk_check_finalize_cascade_stamp_then_quality_depth2
    """
    _h, _a, _l, milk_check, _ps, tdr = setup_provisional_milk_check_single_record(
        scc_thousands=180, milk_weight_lbs=1000, fat_pct=3.8, protein_pct=3.1,
        herd_name="Quality Dairy",
    )
    validate_success(
        api_client.finalize_milk_check(milk_check["id"], milk_check["version"], COOP)
    )
    record = validate_success(api_client.get_test_day_record(tdr["id"], HM))
    assert record["included_in_milk_check_id"] == milk_check["id"], (
        record["included_in_milk_check_id"]
    )


def test_finalize_recomputes_herd_milk_quality_to_good():
    """PRD §3.8: "Finalizing also refreshes the herd's **milk-quality status** from the just-finalized check's `weighted_scc_thousands`."

    Design: Difficulty/transitive_cascade/milk_check_finalize_cascade_stamp_then_quality_depth2
    """
    herd, _a, _l, milk_check, _ps, _tdr = setup_provisional_milk_check_single_record(
        scc_thousands=180, milk_weight_lbs=1000, fat_pct=3.8, protein_pct=3.1,
        herd_name="Quality Dairy 2",
    )
    validate_success(
        api_client.finalize_milk_check(milk_check["id"], milk_check["version"], COOP)
    )
    h = validate_success(api_client.get_herd(herd["id"], HM))
    assert h["milk_quality_status"] == "GOOD", h["milk_quality_status"]


def test_first_calving_opens_single_lactation_no_close():
    """PRD §3.6: "if there is no prior lactation (the heifer's first calving), `closed_lactation_id` is null."
    PRD §3.6: "The animal's `parity` is incremented by one and her `status` is set to `ACTIVE` (a first calving moves `HEIFER → ACTIVE`; a later one moves `DRY → ACTIVE`)."

    Design: Corner/cross_cutting_complexity_layers/cascade_calving_first_parity_opens_single_lactation
    """
    api_client.set_clock("2026-01-10T00:00:00Z", HM)
    herd = _herd("First Calf Dairy")
    animal = _animal(herd["id"], "FC-001", birth_date="2023-06-01")
    be = get_success_data(api_client.create_breeding_event(
        {"animal_id": animal["id"], "service_date": "2026-01-10", "sire_code": "S-1"}, VET))
    get_success_data(api_client.confirm_breeding_event(be["id"], VET))

    ce = get_success_data(api_client.create_calving_event(
        {"animal_id": animal["id"], "breeding_event_id": be["id"], "calving_date": "2026-10-01"}, HM))
    assert ce["closed_lactation_id"] is None, ce["closed_lactation_id"]

    a = validate_success(api_client.get_animal(animal["id"], HM))
    assert a["status"] == "ACTIVE", a["status"]
    assert a["parity"] == 1, a["parity"]
    h = validate_success(api_client.get_herd(herd["id"], HM))
    assert h["active_animal_count"] == 1, h["active_animal_count"]
