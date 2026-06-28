"""Composite setup helpers for multi-step test prerequisites.

The test harness restarts the server (empty DB) before every test, so each helper
builds its preconditions from scratch using only PRD-declared endpoints. Helpers use
get_success_data() (lenient validator) so setup failures surface as clear errors.

Identity threading: a Practitioner is entity_backed, so any ownership-gated call
(intake create/finalize, plan lifecycle, appointment complete) uses
make_practitioner_headers(practitioner_id) — never the shared constant.

Plan-version threading: booking an appointment and creating a dispense both advance
the parent plan's version, and these writes carry expected_treatment_plan_version. Each
helper re-reads the live plan version before such writes so OCC does not falsely reject.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_practitioner_payload, create_room_payload, create_herb_item_payload,
    create_formula_payload, create_patient_payload, create_intake_payload,
    create_treatment_plan_payload, create_package_series_payload,
    create_appointment_payload, create_addon_payload, create_dispense_payload,
)
from .test_users import TEST_USERS, make_practitioner_headers

ADMIN = TEST_USERS["clinic_admin_headers"]
PHARM = TEST_USERS["pharmacist_headers"]

# Monotonically-increasing license suffix so unique license_number is never reused
# within a single test process (the DB is empty each test, but a test may create many).
_lic_counter = [0]


def _next_license() -> str:
    _lic_counter[0] += 1
    return f"LIC-{_lic_counter[0]:05d}"


# ─── Primitive creators ───────────────────────────────────────────────────
def create_practitioner(**overrides):
    """Create a practitioner (ClinicAdmin). Returns the practitioner dict."""
    payload = create_practitioner_payload(license_number=_next_license(), **overrides)
    return get_success_data(api_client.create_practitioner(payload, ADMIN))


def create_room(**overrides):
    """Create a treatment room. Returns the room dict."""
    return get_success_data(api_client.create_room(create_room_payload(**overrides), ADMIN))


def create_patient(**overrides):
    """Register a patient. Returns the patient dict."""
    return get_success_data(api_client.create_patient(create_patient_payload(**overrides), ADMIN))


def create_herb_item(**overrides):
    """Create a herb inventory item (Pharmacist). Returns the herb dict."""
    return get_success_data(api_client.create_herb_item(create_herb_item_payload(**overrides), PHARM))


def create_formula(herb_item_id, grams_per_dose=10, **overrides):
    """Create a herbal formula referencing herb_item_id. Returns the formula dict."""
    payload = create_formula_payload(herb_item_id=herb_item_id,
                                     grams_per_dose=grams_per_dose, **overrides)
    return get_success_data(api_client.create_formula(payload, PHARM))


def get_plan_version(plan_id) -> int:
    """Re-read the live treatment-plan version."""
    return get_success_data(api_client.get_treatment_plan(plan_id, ADMIN))["version"]


# ─── Tier 1/2: patient with finalized intake + ACTIVE plan ─────────────────
def setup_finalized_intake(patient_id, practitioner_id, **intake_overrides):
    """Create a DRAFT intake for the patient and finalize it. Returns the
    finalized intake dict (the patient's intake_status becomes INTAKE_COMPLETE)."""
    prac_headers = make_practitioner_headers(practitioner_id)
    intake = get_success_data(api_client.create_intake(
        create_intake_payload(patient_id, **intake_overrides), prac_headers))
    finalized = get_success_data(api_client.finalize_intake(intake["id"], prac_headers))
    return finalized


def setup_active_plan(patient_id, practitioner_id, intake_id, **plan_overrides):
    """Create an ACTIVE treatment plan from a finalized intake. Returns the plan dict."""
    prac_headers = make_practitioner_headers(practitioner_id)
    payload = create_treatment_plan_payload(patient_id, practitioner_id, intake_id,
                                            **plan_overrides)
    return get_success_data(api_client.create_treatment_plan(payload, prac_headers))


def setup_patient_with_active_plan(payer_mode="CASH", patient_overrides=None,
                                   plan_overrides=None, intake_overrides=None):
    """Full clinical preamble: practitioner + patient + finalized intake + ACTIVE plan.

    Returns dict with keys: practitioner, patient, intake, plan.
    """
    patient_overrides = dict(patient_overrides or {})
    patient_overrides.setdefault("payer_mode", payer_mode)
    practitioner = create_practitioner()
    patient = create_patient(**patient_overrides)
    intake = setup_finalized_intake(patient["id"], practitioner["id"],
                                    **(intake_overrides or {}))
    plan = setup_active_plan(patient["id"], practitioner["id"], intake["id"],
                             **(plan_overrides or {}))
    return {
        "practitioner": practitioner,
        "patient": patient,
        "intake": intake,
        "plan": plan,
    }


def setup_clinic_scenario(payer_mode="CASH", patient_overrides=None,
                          plan_overrides=None, intake_overrides=None):
    """Clinical preamble plus a treatment room. Adds key 'room' to the dict
    returned by setup_patient_with_active_plan."""
    ctx = setup_patient_with_active_plan(
        payer_mode=payer_mode, patient_overrides=patient_overrides,
        plan_overrides=plan_overrides, intake_overrides=intake_overrides)
    ctx["room"] = create_room()
    return ctx


# ─── Tier 3: appointment lifecycle shortcuts ───────────────────────────────
def book_appointment(ctx, room_id=None, practitioner_id=None, **appt_overrides):
    """Book a PER_VISIT appointment against ctx's plan, re-reading the live plan
    version for the OCC check. Returns the appointment dict.

    ctx is the dict from setup_clinic_scenario (or compatible). appt_overrides can
    set charge_source, package_series_id, scheduled_start/end, base_fee_cents, etc.
    """
    plan = ctx["plan"]
    pid = ctx["patient"]["id"]
    prac = practitioner_id or ctx["practitioner"]["id"]
    rid = room_id or ctx["room"]["id"]
    plv = get_plan_version(plan["id"])
    payload = create_appointment_payload(pid, plan["id"], prac, rid, plv, **appt_overrides)
    return get_success_data(api_client.create_appointment(payload, ADMIN))


def add_addon(appt_id, modality, fee_cents):
    """Attach an add-on to an appointment (ClinicAdmin). Returns the add-on dict."""
    return get_success_data(api_client.add_addon(
        appt_id, create_addon_payload(modality=modality, fee_cents=fee_cents), ADMIN))


def check_in_and_complete(ctx, appt_id, clock_iso=None):
    """Advance the clock (optional), check the appointment in (ClinicAdmin), then
    complete it (Practitioner owner). Returns the completed appointment dict."""
    if clock_iso is not None:
        get_success_data(api_client.set_clock(clock_iso, ADMIN))
    get_success_data(api_client.check_in(appt_id, ADMIN))
    prac_headers = make_practitioner_headers(ctx["practitioner"]["id"])
    return get_success_data(api_client.complete_appointment(appt_id, prac_headers))


def book_check_in_complete(ctx, base_fee_cents=12000, addons=None,
                           scheduled_start="2026-06-01T10:00:00Z",
                           scheduled_end="2026-06-01T10:45:00Z",
                           clock_iso="2026-06-01T10:00:00Z"):
    """Book a PER_VISIT visit, optionally attach add-ons, check in on time, complete.

    addons: list of (modality, fee_cents) tuples, attached in order before check-in.
    Returns dict with keys: appointment, addons (list).
    """
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=base_fee_cents,
                            scheduled_start=scheduled_start, scheduled_end=scheduled_end)
    created_addons = []
    for modality, fee_cents in (addons or []):
        created_addons.append(add_addon(appt["id"], modality, fee_cents))
    completed = check_in_and_complete(ctx, appt["id"], clock_iso=clock_iso)
    return {"appointment": completed, "addons": created_addons}


# ─── Tier 4: package / credit targeting ────────────────────────────────────
def create_package(patient_id, total_credits=10, price_paid_cents=90000):
    """Purchase a package series for a patient. Returns the series dict."""
    return get_success_data(api_client.create_package_series(
        create_package_series_payload(patient_id, total_credits, price_paid_cents), ADMIN))


def book_package_appointment(ctx, package_series_id, room_id=None,
                             scheduled_start="2026-06-02T09:00:00Z",
                             scheduled_end="2026-06-02T09:45:00Z", **overrides):
    """Book a PACKAGE-funded appointment drawing a credit from the series.
    Returns the appointment dict."""
    return book_appointment(ctx, room_id=room_id, charge_source="PACKAGE",
                            package_series_id=package_series_id, base_fee_cents=0,
                            scheduled_start=scheduled_start, scheduled_end=scheduled_end,
                            **overrides)


def setup_package_scenario(total_credits=10, price_paid_cents=90000, payer_mode="CASH"):
    """Clinic scenario plus a package series. Adds key 'package' to the ctx dict."""
    ctx = setup_clinic_scenario(payer_mode=payer_mode)
    ctx["package"] = create_package(ctx["patient"]["id"], total_credits, price_paid_cents)
    return ctx


# ─── Tier: strike accumulation (penalty boundary targeting) ────────────────
def accumulate_no_show_strikes(ctx, count, base_fee_cents=12000,
                               start_hour=9, day="2026-06-03"):
    """Book and immediately mark NO_SHOW `count` disposable PER_VISIT appointments so
    the patient's strike_count rises to `count`. Each no-show is a separate appointment.
    Returns the list of no-showed appointment dicts."""
    results = []
    for i in range(count):
        start = f"{day}T{start_hour + i:02d}:00:00Z"
        end = f"{day}T{start_hour + i:02d}:45:00Z"
        appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=base_fee_cents,
                                scheduled_start=start, scheduled_end=end)
        results.append(get_success_data(api_client.no_show(appt["id"], ADMIN)))
    return results


# ─── Tier: herbal dispense lifecycle ───────────────────────────────────────
def setup_dispense_scenario(initial_grams=500, reorder_threshold_grams=400,
                            grams_per_dose=120, doses=1, payer_mode="CASH"):
    """Herb item + formula + clinical preamble + a REQUESTED dispense.

    Returns dict with keys: herb, formula, practitioner, patient, intake, plan, dispense.
    """
    herb = create_herb_item(initial_grams=initial_grams,
                            reorder_threshold_grams=reorder_threshold_grams)
    formula = create_formula(herb["id"], grams_per_dose=grams_per_dose)
    ctx = setup_patient_with_active_plan(payer_mode=payer_mode)
    plv = get_plan_version(ctx["plan"]["id"])
    dispense = get_success_data(api_client.create_dispense(
        create_dispense_payload(ctx["patient"]["id"], ctx["plan"]["id"], formula["id"],
                                plv, doses=doses), PHARM))
    ctx.update({"herb": herb, "formula": formula, "dispense": dispense})
    return ctx
