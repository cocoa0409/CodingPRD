"""Composite setup helpers.

These encapsulate the multi-step preambles that the design instances share, so
tests can focus on the trigger + assertions. Every helper uses get_success_data()
(lenient 2xx validator) so a setup failure surfaces as a clear "Setup failed".

The test harness restarts the server (empty DB) before every test, so every
helper builds its preconditions from scratch using only PRD-declared endpoints.

Identity threading: the Patient role is entity_backed; any consent signature uses
make_patient_headers(patient_id) so X-User-ID equals the acting patient's id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_patient_headers
from . import factories as f

ADMIN = TEST_USERS["clinic_admin_headers"]
NURSE = TEST_USERS["nurse_headers"]
EMBRYO = TEST_USERS["embryologist_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]


# --------------------------------------------------------------------------
# Tier 0: primitives
# --------------------------------------------------------------------------
def create_clinic(**overrides) -> dict:
    return get_success_data(api_client.create_clinic(f.create_clinic_payload(**overrides), ADMIN))


def set_clock(clinic_id: str, to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(f.set_clock_payload(clinic_id, to_iso8601), ADMIN))


def create_package(clinic_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_package(clinic_id, f.create_package_payload(**overrides), ADMIN))


def create_patient(clinic_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_patient(clinic_id, f.create_patient_payload(**overrides), ADMIN))


def create_donor(clinic_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_donor(clinic_id, f.create_donor_payload(**overrides), ADMIN))


def create_surrogate(clinic_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_surrogate(clinic_id, f.create_surrogate_payload(**overrides), ADMIN))


def create_tank(clinic_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_tank(clinic_id, f.create_tank_payload(**overrides), EMBRYO))


# --------------------------------------------------------------------------
# Tier 1: consent setup (publish a form, sign it as the patient)
# --------------------------------------------------------------------------
def publish_consent_form(clinic_id: str, **overrides) -> dict:
    """Create a DRAFT consent form then publish it. Returns the published form."""
    form = get_success_data(
        api_client.create_consent_form(clinic_id, f.create_consent_form_payload(**overrides), ADMIN)
    )
    return get_success_data(api_client.publish_consent_form(clinic_id, form["id"], ADMIN))


def sign_consent(clinic_id: str, patient_id: str, consent_form_id: str) -> dict:
    """Patient signs a published form (identity threaded via make_patient_headers)."""
    payload = f.create_patient_consent_payload(patient_id, consent_form_id)
    return get_success_data(
        api_client.create_patient_consent(clinic_id, payload, make_patient_headers(patient_id))
    )


def setup_patient_with_consent(clinic_id: str, patient_id: str, required_for=None) -> dict:
    """Publish + sign a consent form gating the given protocol gates. Returns consent."""
    if required_for is None:
        required_for = ["CYCLE_START", "RETRIEVAL", "TRANSFER", "CRYO_STORE"]
    form = publish_consent_form(clinic_id, required_for=required_for)
    return sign_consent(clinic_id, patient_id, form["id"])


# --------------------------------------------------------------------------
# Tier 2: cycle state progression
# --------------------------------------------------------------------------
def create_cycle(clinic_id: str, patient_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_cycle(clinic_id, f.create_cycle_payload(patient_id, **overrides), NURSE)
    )


def setup_cycle_in_stim(clinic_id=None, patient_overrides=None, package_overrides=None,
                        required_for=None, **clinic_overrides):
    """Active patient with consent, cycle started -> STIM.

    Returns dict with clinic, patient, cycle (and package if package_overrides given).
    """
    clinic = create_clinic(**clinic_overrides) if clinic_id is None else {"id": clinic_id}
    cid = clinic["id"]
    pkg = None
    pat_kwargs = dict(patient_overrides or {})
    if package_overrides is not None:
        pkg = create_package(cid, **package_overrides)
        pat_kwargs["insurance_package_id"] = pkg["id"]
    patient = create_patient(cid, **pat_kwargs)
    setup_patient_with_consent(cid, patient["id"], required_for=required_for)
    cycle = create_cycle(cid, patient["id"])
    cycle = get_success_data(api_client.start_stim(cid, cycle["id"], NURSE))
    return {"clinic": clinic, "package": pkg, "patient": patient, "cycle": cycle}


def setup_cycle_in_retrieval(oocytes_retrieved=6, required_for=None, **kwargs):
    """Cycle driven to RETRIEVAL with the given oocyte count."""
    if required_for is None:
        required_for = ["CYCLE_START", "RETRIEVAL", "TRANSFER", "CRYO_STORE"]
    ctx = setup_cycle_in_stim(required_for=required_for, **kwargs)
    cid, cyc_id = ctx["clinic"]["id"], ctx["cycle"]["id"]
    ctx["cycle"] = get_success_data(
        api_client.retrieve(cid, cyc_id, {"oocytes_retrieved": oocytes_retrieved}, NURSE)
    )
    return ctx


def setup_cycle_in_fertilization(oocytes_retrieved=6, embryos_fertilized=3,
                                 required_for=None, **kwargs):
    """Cycle driven to FERTILIZATION (stores now allowed)."""
    ctx = setup_cycle_in_retrieval(oocytes_retrieved=oocytes_retrieved,
                                   required_for=required_for, **kwargs)
    cid, cyc_id = ctx["clinic"]["id"], ctx["cycle"]["id"]
    ctx["cycle"] = get_success_data(
        api_client.fertilize(cid, cyc_id, {"embryos_fertilized": embryos_fertilized}, EMBRYO)
    )
    return ctx


# --------------------------------------------------------------------------
# Tier 3: cryo specimen lifecycle shortcuts
# --------------------------------------------------------------------------
def create_specimen(clinic_id: str, cycle_id: str, tank_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_specimen(clinic_id, f.create_specimen_payload(cycle_id, tank_id, **overrides), EMBRYO)
    )


def store_specimen(clinic_id: str, specimen_id: str, expected_tank_version: int) -> dict:
    return get_success_data(
        api_client.store_specimen(clinic_id, specimen_id, {"expected_tank_version": expected_tank_version}, EMBRYO)
    )


def setup_fertilization_with_stored_specimen(tank_capacity=5, **kwargs):
    """FERTILIZATION cycle + a tank + one STORED specimen (reserved_slots == 1).

    Returns dict adding tank, specimen, and the tank's post-store version.
    """
    ctx = setup_cycle_in_fertilization(**kwargs)
    cid = ctx["clinic"]["id"]
    tank = create_tank(cid, label="Tank-Stored", capacity_slots=tank_capacity)
    specimen = create_specimen(cid, ctx["cycle"]["id"], tank["id"])
    stored = store_specimen(cid, specimen["id"], tank["version"])
    tank = get_success_data(api_client.get_tank(cid, tank["id"], EMBRYO))
    ctx.update({"tank": tank, "specimen": stored})
    return ctx


# --------------------------------------------------------------------------
# Tier 4: full lifecycle to a billable, finalized cycle (settle path)
# --------------------------------------------------------------------------
def get_cycle_version(clinic_id: str, cycle_id: str) -> int:
    return get_success_data(api_client.get_cycle(clinic_id, cycle_id, NURSE))["version"]


def record_outcome(clinic_id: str, cycle_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_outcome(clinic_id, f.create_outcome_payload(cycle_id, **overrides), NURSE)
    )


def complete_cycle(clinic_id: str, cycle_id: str) -> dict:
    return get_success_data(api_client.complete_cycle(clinic_id, cycle_id, NURSE))


def drive_fresh_transfer_to_completed(clinic_id: str, cycle_id: str, outcome_overrides=None) -> dict:
    """From FERTILIZATION: transfer -> outcome -> complete. Returns completed cycle."""
    get_success_data(api_client.transfer(clinic_id, cycle_id, EMBRYO))
    record_outcome(clinic_id, cycle_id, **(outcome_overrides or {}))
    return complete_cycle(clinic_id, cycle_id)
