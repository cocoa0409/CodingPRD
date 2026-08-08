"""Composite setup helpers.

These encapsulate the multi-step preambles that most interesting claims require
(register actors -> configure plan -> create & activate membership -> run a lab
panel through REVIEWED -> draft & activate a treatment plan -> issue a
prescription). Each test starts against an empty database, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.

Setup calls use the lenient get_success_data() validator so that a broken
precondition surfaces as a clear "Setup failed" rather than a confusing
assertion deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_clinic_admin_headers,
    make_clinician_headers,
    make_pharmacist_headers,
    make_patient_headers,
)
from . import factories as f

ADMIN = make_clinic_admin_headers()


# --------------------------------------------------------------------------- atoms
def create_clinician(**overrides) -> dict:
    return get_success_data(api_client.create_clinician(f.create_clinician_payload(**overrides), ADMIN))


def create_pharmacist(**overrides) -> dict:
    return get_success_data(api_client.create_pharmacist(f.create_pharmacist_payload(**overrides), ADMIN))


def create_patient(**overrides) -> dict:
    return get_success_data(api_client.create_patient(f.create_patient_payload(**overrides), ADMIN))


def create_membership_plan(**overrides) -> dict:
    return get_success_data(api_client.create_membership_plan(f.create_membership_plan_payload(**overrides), ADMIN))


def create_draw_station(**overrides) -> dict:
    return get_success_data(api_client.create_draw_station(f.create_draw_station_payload(**overrides), ADMIN))


def create_membership(patient_id, plan_id, activate=True) -> dict:
    data = get_success_data(api_client.create_membership(f.create_membership_payload(patient_id, plan_id), ADMIN))
    if activate:
        data = get_success_data(api_client.activate_membership(data["id"], ADMIN))
    return data


def set_clock(iso8601: str) -> None:
    get_success_data(api_client.set_clock({"to_iso8601": iso8601}, ADMIN))


def create_reviewed_panel(patient_id, clinician_id, panel_type="BASELINE", results=None) -> dict:
    """Order -> draw -> result -> review a lab panel; returns the REVIEWED panel."""
    cln = make_clinician_headers(clinician_id)
    panel = get_success_data(
        api_client.create_lab_panel(
            f.create_lab_panel_payload(patient_id, clinician_id, panel_type=panel_type), cln
        )
    )
    pid = panel["id"]
    get_success_data(api_client.draw_lab_panel(pid, cln))
    get_success_data(api_client.result_lab_panel(pid, f.result_lab_panel_payload(**(results or {})), cln))
    return get_success_data(api_client.review_lab_panel(pid, cln))


def get_plan(plan_id) -> dict:
    return get_success_data(api_client.get_treatment_plan(plan_id, ADMIN))


def get_prescription(prescription_id) -> dict:
    return get_success_data(api_client.get_prescription(prescription_id, ADMIN))


def get_membership(membership_id) -> dict:
    return get_success_data(api_client.get_membership(membership_id, ADMIN))


def get_refill(refill_id) -> dict:
    return get_success_data(api_client.get_refill_order(refill_id, ADMIN))


# --------------------------------------------------------------------------- composites
def setup_active_plan(
    plan_overrides=None,
    baseline_results=None,
    protocol_type="TRT_INJECTION",
    starting_dose_mg=100,
    activate_plan=True,
    activate_membership=True,
) -> dict:
    """Build clinician + patient + plan config + (active) membership + a REVIEWED,
    safe baseline panel + a treatment plan, activated by default.

    Returns a context dict with every id and the plan's current version.
    """
    clinician = create_clinician()
    patient = create_patient()
    plan_cfg = create_membership_plan(**(plan_overrides or {}))
    membership = create_membership(patient["id"], plan_cfg["id"], activate=activate_membership)
    baseline = create_reviewed_panel(
        patient["id"], clinician["id"], panel_type="BASELINE", results=baseline_results
    )
    cln = make_clinician_headers(clinician["id"])
    plan = get_success_data(
        api_client.create_treatment_plan(
            f.create_treatment_plan_payload(
                patient["id"], clinician["id"], baseline["id"],
                protocol_type=protocol_type, starting_dose_mg=starting_dose_mg,
            ),
            cln,
        )
    )
    ctx = {
        "clinician_id": clinician["id"],
        "clinician": clinician,
        "patient_id": patient["id"],
        "patient": patient,
        "plan_cfg_id": plan_cfg["id"],
        "plan_cfg": plan_cfg,
        "membership_id": membership["id"],
        "membership": membership,
        "baseline_panel_id": baseline["id"],
        "plan_id": plan["id"],
        "plan": plan,
        "plan_version": plan["version"],
        "clinician_headers": cln,
    }
    if activate_plan:
        activated = get_success_data(api_client.activate_treatment_plan(plan["id"], cln))
        ctx["plan"] = activated
        ctx["plan_version"] = activated["version"]
    return ctx


def setup_plan_with_prescription(rx_overrides=None, **plan_kwargs) -> dict:
    """setup_active_plan + an ISSUED controlled-substance prescription.

    Adds rx_id, rx (data), rx_version, pharmacist_id to the context.
    """
    ctx = setup_active_plan(**plan_kwargs)
    cln = ctx["clinician_headers"]
    rx = get_success_data(
        api_client.create_prescription(
            f.create_prescription_payload(ctx["plan_id"], ctx["patient_id"], **(rx_overrides or {})),
            cln,
        )
    )
    pharmacist = create_pharmacist()
    ctx.update({
        "rx_id": rx["id"],
        "rx": rx,
        "rx_version": rx["version"],
        "pharmacist_id": pharmacist["id"],
        "pharmacist_headers": make_pharmacist_headers(pharmacist["id"]),
    })
    return ctx


def create_refill(ctx, requested_quantity_units=8, expected_prescription_version=None) -> dict:
    """Create a PENDING_REVIEW refill order against ctx's prescription, using the
    prescription's current version unless one is explicitly supplied."""
    if expected_prescription_version is None:
        expected_prescription_version = get_prescription(ctx["rx_id"])["version"]
    return get_success_data(
        api_client.create_refill_order(
            f.create_refill_order_payload(
                ctx["rx_id"], ctx["membership_id"], ctx["patient_id"],
                expected_prescription_version,
                requested_quantity_units=requested_quantity_units,
            ),
            make_clinic_admin_headers(),
        )
    )


def make_plan_titration_pending(ctx, proposed_dose_mg=120) -> dict:
    """Propose a titration on the active plan, moving it to TITRATION_PENDING.
    Returns the created DoseTitration (PROPOSED). ctx['plan_version'] is refreshed."""
    cln = ctx["clinician_headers"]
    plan_v = get_plan(ctx["plan_id"])["version"]
    titration = get_success_data(
        api_client.create_titration(
            ctx["plan_id"], {"proposed_dose_mg": proposed_dose_mg, "expected_plan_version": plan_v}, cln
        )
    )
    ctx["titration_id"] = titration["id"]
    ctx["plan_version"] = get_plan(ctx["plan_id"])["version"]
    return titration
