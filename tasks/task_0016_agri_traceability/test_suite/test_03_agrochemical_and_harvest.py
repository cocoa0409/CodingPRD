"""Agrochemical applications, withdrawal-period calc, and harvest records (PRD §3.3, §3.4)."""
import pytest

from test_helpers import (
    api_client as api,
    validate_success,
    validate_error,
    create_agrochemical_application_payload,
    create_harvest_record_payload,
    create_planting_batch,
    setup_batch_growing,
    setup_batch_harvested,
    declare_growing,
    record_application,
    record_harvest,
    create_pesticide_registry_entry,
    create_storage_bin,
    make_grower_headers,
    DEFAULT_GROWER_ID,
)


# --------------------------------------------------------------------------
# PRD §3.3 — registration_no must exist
# --------------------------------------------------------------------------

def test_application_with_unknown_registration_no_rejected():
    """PRD §3.3: "the registry must contain a matching registration_no (else
    ERR_REGISTRATION_NOT_FOUND)."

    Claim: posting an application referencing a non-existent registration_no →
    ERR_REGISTRATION_NOT_FOUND.
    """
    batch = setup_batch_growing()
    payload = create_agrochemical_application_payload(registration_no="PD-999999")
    res = api.create_agrochemical_application(
        batch["id"], payload, make_grower_headers(batch["grower_id"])
    )
    validate_error(res, "ERR_REGISTRATION_NOT_FOUND")


def test_application_with_prohibited_substance_rejected():
    """PRD §3.3: "the registry record must not be prohibited at the application
    date — meaning either prohibited is false, or prohibited is true but the
    application's application_date is strictly before prohibited_since — else
    ERR_PROHIBITED_SUBSTANCE."

    Claim: applying a substance whose registry has prohibited=true (and
    prohibited_since on or before application_date) → ERR_PROHIBITED_SUBSTANCE.
    """
    batch = setup_batch_growing()
    reg = create_pesticide_registry_entry(
        prohibited=True,
        prohibited_since="2026-01-01T00:00:00.000Z",
        max_dosage_per_hectare_g=200.0,
        withdrawal_period_days=14,
    )
    payload = create_agrochemical_application_payload(
        registration_no=reg["registration_no"],
        application_date="2026-02-15T00:00:00.000Z",
        dosage_g_per_hectare=50.0,
    )
    res = api.create_agrochemical_application(
        batch["id"], payload, make_grower_headers(batch["grower_id"])
    )
    validate_error(res, "ERR_PROHIBITED_SUBSTANCE")


def test_application_dosage_exceeded_rejected():
    """PRD §3.3: "the supplied dosage_g_per_hectare must be less than or equal
    to the registry's max_dosage_per_hectare_g, else ERR_DOSAGE_EXCEEDED."

    Claim: dosage > max_dosage_per_hectare_g → ERR_DOSAGE_EXCEEDED.
    """
    batch = setup_batch_growing()
    reg = create_pesticide_registry_entry(max_dosage_per_hectare_g=100.0)
    payload = create_agrochemical_application_payload(
        registration_no=reg["registration_no"],
        dosage_g_per_hectare=150.0,
    )
    res = api.create_agrochemical_application(
        batch["id"], payload, make_grower_headers(batch["grower_id"])
    )
    validate_error(res, "ERR_DOSAGE_EXCEEDED")


def test_application_dosage_at_threshold_accepted():
    """PRD §3.3: "the supplied dosage_g_per_hectare must be less than or equal
    to the registry's max_dosage_per_hectare_g."

    Claim: dosage == max_dosage_per_hectare_g succeeds (boundary inclusive).
    """
    batch = setup_batch_growing()
    reg = create_pesticide_registry_entry(max_dosage_per_hectare_g=200.0)
    payload = create_agrochemical_application_payload(
        registration_no=reg["registration_no"],
        dosage_g_per_hectare=200.0,
    )
    res = api.create_agrochemical_application(
        batch["id"], payload, make_grower_headers(batch["grower_id"])
    )
    validate_success(res, 201)


# --------------------------------------------------------------------------
# PRD §3.3 — first application implicitly transitions REGISTERED → GROWING
# --------------------------------------------------------------------------

def test_first_application_transitions_batch_to_growing():
    """PRD §3.3: "Inserting the first application on a batch in REGISTERED
    simultaneously transitions the batch to GROWING."

    Claim: posting first application on REGISTERED batch leaves batch in GROWING.
    """
    batch = create_planting_batch()
    reg = create_pesticide_registry_entry()
    record_application(batch, registration_no=reg["registration_no"])
    refreshed = validate_success(
        api.get_planting_batch(batch["id"], make_grower_headers(batch["grower_id"])), 200
    )
    assert refreshed["status"] == "GROWING"


# --------------------------------------------------------------------------
# PRD §3.3 — earliest_legal_harvest_date computation
# --------------------------------------------------------------------------

def test_earliest_legal_harvest_date_is_max_of_application_plus_withdrawal():
    """PRD §3.3: "for each application the candidate earliest legal harvest is
    the application's application_date advanced by withdrawal_period_days
    whole days; the batch's earliest_legal_harvest_date is the latest of those
    candidates, stored at UTC midnight of the resulting date."

    Claim: with two applications {(2026-02-01, 14d), (2026-03-01, 7d)} the
    batch's earliest_legal_harvest_date is 2026-03-08T00:00:00Z (max).
    """
    batch = create_planting_batch()
    reg_a = create_pesticide_registry_entry(withdrawal_period_days=14)
    reg_b = create_pesticide_registry_entry(withdrawal_period_days=7)
    record_application(
        batch, registration_no=reg_a["registration_no"],
        application_date="2026-02-01T00:00:00.000Z",
    )
    record_application(
        batch, registration_no=reg_b["registration_no"],
        application_date="2026-03-01T00:00:00.000Z",
    )
    refreshed = validate_success(
        api.get_planting_batch(batch["id"], make_grower_headers(batch["grower_id"])), 200
    )
    elhd = refreshed["earliest_legal_harvest_date"]
    assert elhd is not None
    # 2026-02-01 + 14d = 2026-02-15; 2026-03-01 + 7d = 2026-03-08; max is 2026-03-08.
    assert elhd.startswith("2026-03-08"), \
        f"expected earliest_legal_harvest_date 2026-03-08T00:00:00Z, got {elhd!r}"


# --------------------------------------------------------------------------
# PRD §3.4 — withdrawal-period guard on harvest
# --------------------------------------------------------------------------

def test_harvest_before_earliest_legal_date_rejected():
    """PRD §3.4: "The withdrawal-period guard rejects the insert with
    ERR_WITHDRAWAL_NOT_ELAPSED whenever earliest_legal_harvest_date is not null
    and harvest_date is strictly before it."

    Claim: harvest_date strictly before earliest_legal_harvest_date →
    ERR_WITHDRAWAL_NOT_ELAPSED.
    """
    batch = create_planting_batch()
    reg = create_pesticide_registry_entry(withdrawal_period_days=30)
    record_application(
        batch, registration_no=reg["registration_no"],
        application_date="2026-04-01T00:00:00.000Z",
    )
    bin_obj = create_storage_bin(capacity_kg=500.0)
    payload = create_harvest_record_payload(
        bin_obj["id"],
        harvest_date="2026-04-15T00:00:00.000Z",  # earliest is 2026-05-01
        quantity_kg=50.0,
    )
    res = api.create_harvest_record(
        batch["id"], payload, make_grower_headers(batch["grower_id"])
    )
    validate_error(res, "ERR_WITHDRAWAL_NOT_ELAPSED")


def test_harvest_at_earliest_legal_date_accepted():
    """PRD §3.4: "equality with earliest_legal_harvest_date is permitted."

    Claim: harvest_date == earliest_legal_harvest_date succeeds.
    """
    batch = create_planting_batch()
    reg = create_pesticide_registry_entry(withdrawal_period_days=30)
    record_application(
        batch, registration_no=reg["registration_no"],
        application_date="2026-04-01T00:00:00.000Z",
    )
    bin_obj = create_storage_bin(capacity_kg=500.0)
    payload = create_harvest_record_payload(
        bin_obj["id"],
        harvest_date="2026-05-01T00:00:00.000Z",
        quantity_kg=10.0,
    )
    res = api.create_harvest_record(
        batch["id"], payload, make_grower_headers(batch["grower_id"])
    )
    validate_success(res, 201)


# --------------------------------------------------------------------------
# PRD §3.4 — capacity & first harvest cascade
# --------------------------------------------------------------------------

def test_first_harvest_transitions_growing_to_harvested():
    """PRD §3.4: "A successful harvest insert ... when this is the first harvest
    on the batch — transitions the batch from GROWING to HARVESTED."

    Claim: first harvest on a GROWING batch leaves it in HARVESTED.
    """
    batch, _bin, _harvest = setup_batch_harvested()
    assert batch["status"] == "HARVESTED"


def test_harvest_into_full_bin_rejected_with_capacity_exceeded():
    """PRD §3.4: "A harvest insert is rejected with ERR_BIN_CAPACITY_EXCEEDED
    when the destination bin's current occupied_kg plus the new quantity_kg
    would exceed the bin's capacity_kg."

    Claim: combined weight > capacity_kg → ERR_BIN_CAPACITY_EXCEEDED.
    """
    batch = setup_batch_growing()
    bin_obj = create_storage_bin(capacity_kg=20.0)
    # First harvest: 15 kg → occupied = 15
    record_harvest(batch, bin_obj["id"], quantity_kg=15.0)
    # Second harvest: 10 kg → 25 > 20 capacity
    payload = create_harvest_record_payload(bin_obj["id"], quantity_kg=10.0)
    res = api.create_harvest_record(
        batch["id"], payload, make_grower_headers(batch["grower_id"])
    )
    validate_error(res, "ERR_BIN_CAPACITY_EXCEEDED")


def test_harvest_total_quantity_kg_accumulates_on_batch():
    """PRD §3.4: "A successful harvest insert appends to the batch's
    total_quantity_kg."

    Claim: batch.total_quantity_kg increases by quantity_kg per harvest.
    """
    batch = setup_batch_growing()
    bin_obj = create_storage_bin(capacity_kg=200.0)
    record_harvest(batch, bin_obj["id"], quantity_kg=30.0)
    record_harvest(batch, bin_obj["id"], quantity_kg=20.0)
    refreshed = validate_success(
        api.get_planting_batch(batch["id"], make_grower_headers(batch["grower_id"])), 200
    )
    assert refreshed["total_quantity_kg"] == pytest.approx(50.0, abs=0.01)


def test_harvest_updates_storage_bin_occupied_kg():
    """PRD §3.4: "A successful harvest insert ... refreshes the destination
    bin's occupied_kg and status."

    Claim: bin.occupied_kg reflects sum of harvest quantities.
    """
    batch = setup_batch_growing()
    bin_obj = create_storage_bin(capacity_kg=200.0)
    record_harvest(batch, bin_obj["id"], quantity_kg=42.0)
    res = api.get_storage_bin(bin_obj["id"], make_grower_headers(batch["grower_id"]))
    bin_after = validate_success(res, 200)
    assert bin_after["occupied_kg"] == pytest.approx(42.0, abs=0.01)
