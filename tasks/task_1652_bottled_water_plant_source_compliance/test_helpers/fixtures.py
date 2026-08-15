"""Composite setup helpers.

Multi-step setup sequences translated from the design indices so tests can
focus on assertions. Fixtures use get_success_data() (lenient) so setup
failures surface as clear "Setup failed" errors.

Conventions:
- Every fixture builds from scratch (the server is relaunched per test).
- OCC-guarded writes re-read the parent version immediately before posting
  unless the caller explicitly passes a version (for stale-version tests).
- Segregation of duties (PRD §2.10): parameters recorded by "pl-1" are
  validated by "qa-1"; lots completed by "pl-1" are released by "qa-1".
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import api_client
from .factories import (
    create_plant_payload,
    create_permit_payload,
    create_withdrawal_event_payload,
    create_treatment_run_payload,
    passing_parameters_payload,
    create_bottling_line_payload,
    create_preform_delivery_payload,
    qc_verdict_payload,
    create_production_lot_payload,
    create_recall_payload,
    create_wash_batch_payload,
    complete_wash_batch_payload,
    create_bottle_payload,
    create_lab_test_payload,
    record_result_payload,
)
from .test_users import (
    TEST_USERS,
    make_production_lead_headers,
    make_qa_officer_headers,
    make_sanitation_lead_headers,
)

PLANT_ADMIN = TEST_USERS["plant_admin_headers"]
SOURCE_MONITOR = TEST_USERS["source_monitor_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]

# Operator ids used across the segregation-of-duties boundary.
PL1 = make_production_lead_headers("pl-1")
QA1 = make_qa_officer_headers("qa-1")
QA2 = make_qa_officer_headers("qa-2")
SL1 = make_sanitation_lead_headers("sl-1")


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_plant(name="Test Plant"):
    """Create a plant. Returns the plant dict."""
    resp = api_client.create_plant(create_plant_payload(name=name), PLANT_ADMIN)
    return get_success_data(resp)


def create_permit(plant_id, **overrides):
    """Register a source permit. Returns the permit dict (ACTIVE, aggregates 0)."""
    resp = api_client.create_permit(plant_id, create_permit_payload(**overrides), COMPLIANCE_OFFICER)
    return get_success_data(resp)


def create_bottling_line(plant_id, **overrides):
    """Create a bottling line. Returns the line dict (ledger 0/0, version 1)."""
    resp = api_client.create_bottling_line(plant_id, create_bottling_line_payload(**overrides), PLANT_ADMIN)
    return get_success_data(resp)


def create_treatment_run(plant_id, permit_id, **overrides):
    """Schedule a treatment run. Returns the run dict (SCHEDULED)."""
    payload = create_treatment_run_payload(source_permit_id=permit_id, **overrides)
    resp = api_client.create_treatment_run(plant_id, payload, PL1)
    return get_success_data(resp)


def create_bottle(plant_id, bottle_code):
    """Register a returnable bottle. Returns the bottle dict (SANITIZED)."""
    resp = api_client.create_bottle(plant_id, create_bottle_payload(bottle_code=bottle_code), SL1)
    return get_success_data(resp)


def create_wash_batch(plant_id, **overrides):
    """Schedule a wash batch. Returns the batch dict (SCHEDULED)."""
    resp = api_client.create_wash_batch(plant_id, create_wash_batch_payload(**overrides), SL1)
    return get_success_data(resp)


def create_source_raw_test(plant_id, permit_id, due_date=None):
    """Schedule a SOURCE_RAW lab test on a permit. Returns the test dict."""
    payload = create_lab_test_payload(test_type="SOURCE_RAW", subject_permit_id=permit_id)
    if due_date is not None:
        payload["due_date"] = due_date
    resp = api_client.create_lab_test(plant_id, payload, QA1)
    return get_success_data(resp)


def set_clock(to_iso8601):
    """Move the server logical clock (PRD §2.4)."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, PLANT_ADMIN)
    return get_success_data(resp)


def run_compliance(plant_id):
    """Run the daily compliance checkpoint. Returns the summary object."""
    resp = api_client.run_compliance(plant_id, PLANT_ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: permit + withdrawal events (OCC-threaded)
# ---------------------------------------------------------------------------

def post_withdrawal_event(permit_id, gallons, withdrawal_date=C.STARTUP_DATE,
                          meter_start=0, meter_end=None, supersedes_event_id=None):
    """Post a withdrawal event, reading the permit version fresh for OCC.

    Returns (event_dict, permit_dict_after) where permit_dict_after is the
    re-read permit following the write.
    """
    if meter_end is None:
        meter_end = meter_start + gallons
    permit = get_success_data(api_client.get_permit(permit_id, SOURCE_MONITOR))
    payload = create_withdrawal_event_payload(
        withdrawal_date=withdrawal_date,
        gallons=gallons,
        meter_reading_start_gallons=meter_start,
        meter_reading_end_gallons=meter_end,
        expected_permit_version=permit["version"],
    )
    if supersedes_event_id is not None:
        payload["supersedes_event_id"] = supersedes_event_id
    resp = api_client.create_withdrawal_event(permit_id, payload, SOURCE_MONITOR)
    event = get_success_data(resp)
    permit_after = get_success_data(api_client.get_permit(permit_id, SOURCE_MONITOR))
    return event, permit_after


# ---------------------------------------------------------------------------
# Tier 3: treatment-run lifecycle
# ---------------------------------------------------------------------------

def create_validated_run(plant_id, permit_id, parameters=None, **overrides):
    """Create a run, start it, record parameters (pl-1), validate (qa-1).

    Returns the VALIDATED run dict.
    """
    run = create_treatment_run(plant_id, permit_id, **overrides)
    get_success_data(api_client.start_treatment_run(run["id"], PL1))
    params = parameters if parameters is not None else passing_parameters_payload()
    get_success_data(api_client.record_run_parameters(run["id"], params, PL1))
    resp = api_client.validate_treatment_run(run["id"], QA1)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: line ledger + lot lifecycle
# ---------------------------------------------------------------------------

def setup_line_with_preforms(plant_id, accepted_units=5000, **line_overrides):
    """Create a line and book accepted_units of preform stock via a QC-accepted
    delivery. Returns (line_dict_after_acceptance, delivery_dict)."""
    line = create_bottling_line(plant_id, **line_overrides)
    del_payload = create_preform_delivery_payload(delivered_units=accepted_units)
    del_payload["expected_line_version"] = line["version"]
    delivery = get_success_data(
        api_client.create_preform_delivery(line["id"], del_payload, PL1)
    )
    verdict = qc_verdict_payload(verdict="ACCEPTED", accepted_units=accepted_units)
    get_success_data(api_client.qc_verdict_preform_delivery(delivery["id"], verdict, QA1))
    line_after = get_success_data(api_client.get_bottling_line(line["id"], PL1))
    return line_after, delivery


def create_lot_on_line(line_id, run_id, planned_units=100, **overrides):
    """Create a PLANNED lot on a line, reading the line version fresh for OCC.

    Returns the lot dict (PLANNED).
    """
    line = get_success_data(api_client.get_bottling_line(line_id, PL1))
    payload = create_production_lot_payload(
        treatment_run_id=run_id,
        planned_units=planned_units,
        expected_line_version=line["version"],
        **overrides,
    )
    resp = api_client.create_production_lot(line_id, payload, PL1)
    return get_success_data(resp)


def find_finished_product_test(lot_id):
    """Locate the AUTO FINISHED_PRODUCT test for a completed lot via the
    subject_lot_id reverse lookup. Returns the test dict."""
    data, _meta = _paginated(api_client.list_lab_tests(
        QA1, params={"subject_lot_id": lot_id, "test_type": "FINISHED_PRODUCT"}
    ))
    assert len(data) >= 1, f"Setup failed: no FINISHED_PRODUCT test found for lot {lot_id}"
    return data[0]


def _paginated(resp):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(resp)


def create_lot_in_qa_hold(plant_id, permit_id, line_id, run_id,
                          planned_units=100, produced_units=None, **lot_overrides):
    """Create a lot and drive it PLANNED -> IN_PRODUCTION -> QA_HOLD.

    The caller supplies a run in any state (the release gate, not completion,
    checks run validation). Auto-creates the FINISHED_PRODUCT test.
    Returns (lot_dict_at_qa_hold, finished_product_test_dict).
    """
    lot = create_lot_on_line(line_id, run_id, planned_units=planned_units, **lot_overrides)
    get_success_data(api_client.start_production_lot(lot["id"], PL1))
    produced = produced_units if produced_units is not None else planned_units
    lot_qa = get_success_data(
        api_client.complete_production_lot(lot["id"], {"produced_units": produced}, PL1)
    )
    fptest = find_finished_product_test(lot["id"])
    return lot_qa, fptest


def create_released_lot(plant_id, permit_id, line_id, run_id,
                        planned_units=100, produced_units=None, **lot_overrides):
    """Full lot lifecycle through RELEASED: requires the run be VALIDATED.

    Completed by pl-1, released by qa-1 (segregation of duties), with the AUTO
    finished-product test recorded PASS by qa-1.
    Returns (lot_dict_at_released, finished_product_test_dict).
    """
    lot_qa, fptest = create_lot_in_qa_hold(
        plant_id, permit_id, line_id, run_id,
        planned_units=planned_units, produced_units=produced_units, **lot_overrides,
    )
    get_success_data(api_client.record_lab_result(
        fptest["id"], record_result_payload(result="PASS"), QA1
    ))
    lot_rel = get_success_data(api_client.release_production_lot(lot_qa["id"], QA1))
    return lot_rel, fptest


def setup_released_lot_scenario(plant_name="Test Plant", planned_units=100,
                                preform_units=5000, produced_units=None,
                                permit_overrides=None, line_overrides=None,
                                lot_overrides=None, run_parameters=None):
    """The standard production fixture: plant + SPRING permit + line stocked
    with preforms + VALIDATED treatment run + RELEASED lot.

    Returns a dict with keys: plant, permit, line, run, lot, fptest.
    """
    plant = create_plant(plant_name)
    permit = create_permit(plant["id"], **(permit_overrides or {}))
    line, _delivery = setup_line_with_preforms(
        plant["id"], accepted_units=preform_units, **(line_overrides or {})
    )
    run = create_validated_run(plant["id"], permit["id"], parameters=run_parameters)
    lot, fptest = create_released_lot(
        plant["id"], permit["id"], line["id"], run["id"],
        planned_units=planned_units, produced_units=produced_units,
        **(lot_overrides or {}),
    )
    return {
        "plant": plant, "permit": permit, "line": line,
        "run": run, "lot": lot, "fptest": fptest,
    }


# ---------------------------------------------------------------------------
# Tier 5: bottle loop + wash batches
# ---------------------------------------------------------------------------

def loop_bottle_to_dirty(plant_id, bottle_id, lot_id):
    """Fill (from a RELEASED lot of the same plant) -> deliver -> return.

    Returns the RETURNED_DIRTY bottle dict.
    """
    get_success_data(api_client.fill_bottle(bottle_id, {"lot_id": lot_id}, PL1))
    get_success_data(api_client.deliver_bottle(bottle_id, SL1))
    resp = api_client.return_bottle(bottle_id, SL1)
    return get_success_data(resp)


def create_running_wash_with_bottles(plant_id, bottle_ids, **batch_overrides):
    """Create a SCHEDULED batch, assign the given RETURNED_DIRTY bottles
    (bottles -> IN_WASH), and start the batch (RUNNING).

    Returns (batch_dict_running,).
    """
    batch = create_wash_batch(plant_id, **batch_overrides)
    get_success_data(api_client.assign_bottles(batch["id"], {"bottle_ids": bottle_ids}, SL1))
    running = get_success_data(api_client.start_wash_batch(batch["id"], SL1))
    return running


def wash_bottle_once(plant_id, bottle_id, lot_id,
                     rinse_temp_c=C.RINSE_TEMP_MIN_C, sanitizer_ppm=C.SANITIZER_MIN_PPM,
                     **batch_overrides):
    """Drive a SANITIZED bottle through one full loop:
    fill -> deliver -> return -> assign -> start -> complete.

    With passing parameters the bottle ends SANITIZED with wash_cycle_count 1
    and an AUTO BOTTLE_SANITATION test is created (left SCHEDULED).
    Returns (bottle_dict_after, batch_dict_after).
    """
    loop_bottle_to_dirty(plant_id, bottle_id, lot_id)
    batch = create_running_wash_with_bottles(plant_id, [bottle_id], **batch_overrides)
    batch_after = get_success_data(api_client.complete_wash_batch(
        batch["id"], complete_wash_batch_payload(
            rinse_temp_c=rinse_temp_c, sanitizer_ppm=sanitizer_ppm
        ), SL1
    ))
    bottle_after = get_success_data(api_client.get_bottle(bottle_id, SL1))
    return bottle_after, batch_after


# ---------------------------------------------------------------------------
# Tier 6: recalls
# ---------------------------------------------------------------------------

def create_recall_for_lots(plant_id, lot_ids, reason="quality defect"):
    """Initiate a recall over RELEASED lots. Returns the INITIATED recall."""
    resp = api_client.create_recall(
        plant_id, create_recall_payload(reason=reason, lot_ids=lot_ids), COMPLIANCE_OFFICER
    )
    return get_success_data(resp)
