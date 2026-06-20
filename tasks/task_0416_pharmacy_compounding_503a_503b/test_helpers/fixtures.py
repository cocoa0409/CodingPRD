"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be in a state that takes 5-15 API
calls to reach (a released batch, a recalled-and-reconciled batch, a ledger at a
window boundary). These helpers encapsulate those chains so tests focus on
assertions. They use get_success_data() (lenient) internally so a setup failure
surfaces as a clear "Setup failed" rather than a confusing assertion error.

Compiler/releaser identity threading: the segregation-of-duties control compares
the X-User-ID recorded at compile against the one recorded at release. Fixtures
therefore compile under a fixed compiler id and release under a *different* QA id
by default, and expose those ids so consumers can override them.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_facility_payload,
    set_clock_payload,
    create_mfr_payload,
    create_ingredient_lot_payload,
    create_prescription_payload,
    create_batch_payload,
    create_batch_ingredient_usage_payload,
    compile_payload,
    release_payload,
    create_qc_test_payload,
    record_qc_payload,
    create_environmental_log_payload,
)
from .test_users import TEST_USERS, make_compounding_headers, make_qa_headers
from .constants import DEFAULT_CLOCK, FAR_FUTURE_EXPIRY

ADMIN = TEST_USERS["admin_headers"]
COMP = TEST_USERS["compounding_headers"]
QA = TEST_USERS["qa_headers"]
DISP = TEST_USERS["dispensing_headers"]

# Default operator fingerprints for the segregation-of-duties wall.
COMPILER_ID = "comp-user-1"
RELEASER_ID = "qa-user-2"


# ─── Tier 0: Primitive creates ───────────────────────────────────────────────

def create_facility(registration_type="503A", clock=DEFAULT_CLOCK, **overrides):
    """Create a facility and set its deterministic clock. Returns the facility."""
    res = api_client.create_facility(
        create_facility_payload(registration_type=registration_type, **overrides), ADMIN
    )
    facility = get_success_data(res)
    if clock is not None:
        clk = api_client.set_clock(facility["id"], set_clock_payload(clock), ADMIN)
        facility = get_success_data(clk)
    return facility


def create_mfr(facility_id, **overrides):
    """Create a master formulation record. Returns the MFR."""
    res = api_client.create_mfr(create_mfr_payload(facility_id, **overrides), COMP)
    return get_success_data(res)


def create_lot(facility_id, **overrides):
    """Receive an ingredient lot. Returns the lot."""
    res = api_client.create_ingredient_lot(
        create_ingredient_lot_payload(facility_id, **overrides), COMP
    )
    return get_success_data(res)


def create_prescription(facility_id, mfr_id, **overrides):
    """Create a 503A patient-specific prescription. Returns the prescription."""
    res = api_client.create_prescription(
        create_prescription_payload(facility_id, mfr_id, **overrides), DISP
    )
    return get_success_data(res)


# ─── Tier 1: Batch state progression ─────────────────────────────────────────

def create_draft_batch(facility_id, mfr_id, purpose="OFFICE_USE", **overrides):
    """Open a DRAFT compounding batch. Returns the batch."""
    res = api_client.create_batch(
        create_batch_payload(facility_id, mfr_id, purpose, **overrides), COMP
    )
    return get_success_data(res)


def charge_usage(batch_id, lot_id, grams_used=10):
    """Charge a lot to a DRAFT batch. Returns the BatchIngredientUsage row."""
    res = api_client.create_batch_ingredient_usage(
        create_batch_ingredient_usage_payload(batch_id, lot_id, grams_used=grams_used), COMP
    )
    return get_success_data(res)


def create_started_batch(facility_id, mfr_id, lot_id, purpose="OFFICE_USE",
                         grams_used=10, batch_overrides=None):
    """facility/mfr/lot already exist → create batch, charge a lot, /start.
    Returns the started (IN_PROCESS) batch.
    """
    batch = create_draft_batch(
        facility_id, mfr_id, purpose, **(batch_overrides or {})
    )
    charge_usage(batch["id"], lot_id, grams_used=grams_used)
    res = api_client.start_batch(batch["id"], COMP)
    return get_success_data(res)


def create_compiled_batch(facility_id, mfr_id, lot_id, actual_yield_units,
                         purpose="OFFICE_USE", grams_used=10, batch_overrides=None,
                         compiler_id=COMPILER_ID):
    """Create → charge → start → compile. Returns the COMPILED batch.

    The compile is performed under `compiler_id` so a later release by a different
    QA operator satisfies segregation of duties.
    """
    batch = create_started_batch(
        facility_id, mfr_id, lot_id, purpose=purpose,
        grams_used=grams_used, batch_overrides=batch_overrides,
    )
    res = api_client.compile_batch(
        batch["id"], compile_payload(actual_yield_units),
        make_compounding_headers(compiler_id),
    )
    return get_success_data(res)


# ─── Tier 2: QC seeding ──────────────────────────────────────────────────────

def add_passing_required_qc(batch_id, is_sterile=False, endotoxin_measured_value=0.5):
    """Add and PASS every required QC test for a batch.

    Required: POTENCY_ASSAY + VISUAL_INSPECTION always; plus STERILITY + ENDOTOXIN
    when the formula is sterile.
    """
    # POTENCY_ASSAY (numeric, in-band)
    pot = get_success_data(api_client.create_qc_test(
        create_qc_test_payload(batch_id, "POTENCY_ASSAY",
                               measured_value=100, lower_limit=90, upper_limit=110), QA))
    api_client.begin_qc_test(pot["id"], QA)
    api_client.record_qc_test(pot["id"], record_qc_payload(measured_value=100), QA)

    # VISUAL_INSPECTION (pass/fail)
    vis = get_success_data(api_client.create_qc_test(
        create_qc_test_payload(batch_id, "VISUAL_INSPECTION"), QA))
    api_client.begin_qc_test(vis["id"], QA)
    api_client.record_qc_test(vis["id"], record_qc_payload(pass_flag=True), QA)

    if is_sterile:
        ster = get_success_data(api_client.create_qc_test(
            create_qc_test_payload(batch_id, "STERILITY"), QA))
        api_client.begin_qc_test(ster["id"], QA)
        api_client.record_qc_test(ster["id"], record_qc_payload(pass_flag=True), QA)

        endo = get_success_data(api_client.create_qc_test(
            create_qc_test_payload(batch_id, "ENDOTOXIN"), QA))
        api_client.begin_qc_test(endo["id"], QA)
        api_client.record_qc_test(
            endo["id"], record_qc_payload(measured_value=endotoxin_measured_value), QA)


# ─── Tier 3: Full lifecycle shortcuts ────────────────────────────────────────

def quarantine_batch(batch_id):
    """Move a COMPILED batch to QUARANTINED. Returns the batch."""
    return get_success_data(api_client.quarantine_batch(batch_id, COMP))


def release_batch(batch_id, releaser_id=RELEASER_ID, expected_version=None):
    """Release a QUARANTINED batch under a QA operator distinct from the compiler.

    If expected_version is None, the current batch.version is read first.
    Returns the RELEASED batch.
    """
    if expected_version is None:
        cur = get_success_data(api_client.get_batch(batch_id, QA))
        expected_version = cur["version"]
    res = api_client.release_batch(
        batch_id, release_payload(expected_version), make_qa_headers(releaser_id))
    return get_success_data(res)


def create_released_batch(facility_id, mfr_id, lot_id, actual_yield_units,
                         purpose="OFFICE_USE", is_sterile=False, grams_used=10,
                         batch_overrides=None, compiler_id=COMPILER_ID,
                         releaser_id=RELEASER_ID):
    """Full chain: compile → add+pass required QC → quarantine → release.
    Returns the RELEASED batch.
    """
    batch = create_compiled_batch(
        facility_id, mfr_id, lot_id, actual_yield_units, purpose=purpose,
        grams_used=grams_used, batch_overrides=batch_overrides, compiler_id=compiler_id,
    )
    add_passing_required_qc(batch["id"], is_sterile=is_sterile)
    quarantine_batch(batch["id"])
    return release_batch(batch["id"], releaser_id=releaser_id)


def list_finished_preparations(batch_id):
    """Return the list of FinishedPreparation rows for a batch (creation order)."""
    res = api_client.list_finished_preparations(
        DISP, params={"compounding_batch_id": batch_id, "limit": 100})
    return get_success_data(res)


def dispense_prescription_unit(facility_id, prep_id, prescription_id):
    """Dispense a 503A unit against a prescription. Returns the Dispense record."""
    from .factories import create_dispense_payload
    res = api_client.create_dispense(
        create_dispense_payload(facility_id, prep_id, prescription_id=prescription_id), DISP)
    return get_success_data(res)


# ─── Tier 4: Whole-scenario builders for the recurring difficulty/corner chains ─

def setup_503a_released_prescription_batch(yield_units=5, units_prescribed=None,
                                          default_bud_days_nonsterile=90,
                                          dosage_form="ORAL_SOLID", clock=DEFAULT_CLOCK,
                                          lot_overrides=None, mfr_overrides=None):
    """Build a 503A facility whose PRESCRIPTION batch is RELEASED.

    Returns dict with facility, mfr, lot, prescription, batch, and the list of
    minted finished preparations.
    """
    if units_prescribed is None:
        units_prescribed = yield_units
    facility = create_facility("503A", clock=clock)
    mfr = create_mfr(
        facility["id"],
        dosage_form=dosage_form,
        default_bud_days_nonsterile=default_bud_days_nonsterile,
        theoretical_yield_units=yield_units,
        **(mfr_overrides or {}),
    )
    lot = create_lot(facility["id"], **(lot_overrides or {}))
    rx = create_prescription(
        facility["id"], mfr["id"], units_prescribed=units_prescribed)
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], yield_units,
        purpose="PRESCRIPTION", is_sterile=False,
        batch_overrides={"prescription_id": rx["id"]},
    )
    preps = list_finished_preparations(batch["id"])
    return {
        "facility": facility, "mfr": mfr, "lot": lot,
        "prescription": rx, "batch": batch, "preps": preps,
    }


def setup_503b_released_office_use_batch(yield_units=120, is_sterile=False,
                                        dosage_form="ORAL_LIQUID",
                                        default_bud_days_nonsterile=90,
                                        anticipatory_max_units=200,
                                        anticipatory_window_days=30,
                                        clock=DEFAULT_CLOCK, lot_overrides=None):
    """Build a 503B facility whose OFFICE_USE batch is RELEASED.

    Returns dict with facility, mfr, lot, batch, and the minted preparations.
    """
    facility = create_facility("503B", clock=clock)
    mfr = create_mfr(
        facility["id"],
        dosage_form=dosage_form,
        default_bud_days_nonsterile=default_bud_days_nonsterile,
        theoretical_yield_units=yield_units,
        anticipatory_max_units=anticipatory_max_units,
        anticipatory_window_days=anticipatory_window_days,
    )
    lot = create_lot(facility["id"], **(lot_overrides or {}))
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], yield_units,
        purpose="OFFICE_USE", is_sterile=is_sterile,
    )
    preps = list_finished_preparations(batch["id"])
    return {
        "facility": facility, "mfr": mfr, "lot": lot,
        "batch": batch, "preps": preps,
    }
