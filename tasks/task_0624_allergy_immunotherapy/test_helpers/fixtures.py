"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors rather than confusing assertion failures.

All roles are opaque, so each helper uses the shared role-header constant for
the actor that owns the operation per the PRD's RBAC matrix.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_patient_payload,
    create_panel_payload,
    create_skin_test_payload,
    create_blood_test_payload,
    create_plan_payload,
    create_lot_payload,
    mix_vial_payload,
    administer_shot_payload,
    release_payload,
    record_reaction_payload,
    resume_payload,
)
from .test_users import TEST_USERS

ALLERGIST = TEST_USERS["allergist_headers"]
PHARMACIST = TEST_USERS["pharmacist_headers"]
NURSE = TEST_USERS["nurse_headers"]
BILLER = TEST_USERS["biller_headers"]
FRONTDESK = TEST_USERS["frontdesk_headers"]

# Monotonic lot-number generator so concurrently-built fixtures across tests
# never collide on the unique lot_number constraint (each test runs against a
# fresh server, but a single test may mint several lots).
_lot_counter = itertools.count(1)


def unique_lot_number(prefix="LOT"):
    return f"{prefix}-{next(_lot_counter):06d}"


# ─── Clock ────────────────────────────────────────────────────────────────
def set_clock(to_iso8601, headers=NURSE):
    """Set the logical clock; returns the response data (incl. expired_vial_ids)."""
    return get_success_data(api_client.set_clock(to_iso8601, headers))


# ─── Tier 0: atomic builders ────────────────────────────────────────────────
def create_patient(epinephrine_on_file=None, **overrides):
    payload = create_patient_payload(**overrides)
    if epinephrine_on_file is not None:
        payload["epinephrine_on_file"] = epinephrine_on_file
    return get_success_data(api_client.create_patient(payload, FRONTDESK))


def create_open_panel(patient_id, control_wheal_mm=3, panel_name="Panel"):
    return get_success_data(
        api_client.create_panel(
            patient_id,
            create_panel_payload(panel_name=panel_name, control_wheal_mm=control_wheal_mm),
            ALLERGIST,
        )
    )


def add_skin_test(patient_id, panel_id, wheal_mm, clinically_relevant=False,
                  allergen_code="DUST"):
    return get_success_data(
        api_client.add_test(
            patient_id,
            panel_id,
            create_skin_test_payload(
                wheal_mm=wheal_mm,
                clinically_relevant=clinically_relevant,
                allergen_code=allergen_code,
            ),
            ALLERGIST,
        )
    )


def add_blood_test(patient_id, panel_id, specific_ige_ku, clinically_relevant=False,
                   allergen_code="DUST"):
    return get_success_data(
        api_client.add_test(
            patient_id,
            panel_id,
            create_blood_test_payload(
                specific_ige_ku=specific_ige_ku,
                clinically_relevant=clinically_relevant,
                allergen_code=allergen_code,
            ),
            ALLERGIST,
        )
    )


def finalize_panel(patient_id, panel_id):
    return get_success_data(api_client.finalize_panel(patient_id, panel_id, ALLERGIST))


def create_lot(vial_color, lot_number=None, potency=10000,
               received_at_iso="2026-01-01T00:00:00Z"):
    if lot_number is None:
        lot_number = unique_lot_number(vial_color)
    return get_success_data(
        api_client.create_lot(
            create_lot_payload(
                vial_color=vial_color,
                lot_number=lot_number,
                concentrate_potency_pnu_per_ml=potency,
                received_at_iso=received_at_iso,
            ),
            PHARMACIST,
        )
    )


def mix_vial(plan_id, lot_id, expected_plan_version, prepared_volume_ml=5.0):
    return get_success_data(
        api_client.mix_vial(
            plan_id,
            mix_vial_payload(
                lot_id=lot_id,
                expected_plan_version=expected_plan_version,
                prepared_volume_ml=prepared_volume_ml,
            ),
            PHARMACIST,
        )
    )


def administer_shot(plan_id, vial_id, expected_plan_version, injection_count=None):
    return get_success_data(
        api_client.administer_shot(
            plan_id,
            administer_shot_payload(
                vial_id=vial_id,
                expected_plan_version=expected_plan_version,
                injection_count=injection_count,
            ),
            NURSE,
        )
    )


def release_visit(visit_id, released_at_iso, reaction_grade="NONE"):
    return get_success_data(
        api_client.release_visit(
            visit_id,
            release_payload(released_at_iso=released_at_iso, reaction_grade=reaction_grade),
            NURSE,
        )
    )


def record_reaction(visit_id, reaction_grade, epinephrine_administered=None):
    return get_success_data(
        api_client.record_reaction(
            visit_id,
            record_reaction_payload(
                reaction_grade=reaction_grade,
                epinephrine_administered=epinephrine_administered,
            ),
            NURSE,
        )
    )


def get_plan(plan_id):
    return get_success_data(api_client.get_plan(plan_id, ALLERGIST))


# ─── Tier 1: panel-to-plan composites ───────────────────────────────────────
def create_finalized_panel(epinephrine_on_file=True, wheal_mm=6, control_wheal_mm=3,
                           clinically_relevant=True, panel_name="Panel"):
    """Patient + OPEN panel + one positive SKIN test + finalize.

    A SKIN wheal of `wheal_mm` over control `control_wheal_mm` yields
    sensitization_index = wheal_mm - control. With the defaults (6 over 3 -> 3)
    the clinical_composite is 3 -> recommended_tier MODERATE -> starting YELLOW.
    Returns (patient, panel).
    """
    patient = create_patient(epinephrine_on_file=epinephrine_on_file)
    panel = create_open_panel(
        patient["id"], control_wheal_mm=control_wheal_mm, panel_name=panel_name
    )
    add_skin_test(
        patient["id"], panel["id"], wheal_mm=wheal_mm,
        clinically_relevant=clinically_relevant,
    )
    panel = finalize_panel(patient["id"], panel["id"])
    return patient, panel


def create_draft_plan(epinephrine_on_file=True, wheal_mm=6, control_wheal_mm=3):
    """Patient + finalized panel + a DRAFT plan. Returns (patient, panel, plan)."""
    patient, panel = create_finalized_panel(
        epinephrine_on_file=epinephrine_on_file,
        wheal_mm=wheal_mm,
        control_wheal_mm=control_wheal_mm,
    )
    plan = get_success_data(
        api_client.create_plan(
            create_plan_payload(patient["id"], panel["id"]), ALLERGIST
        )
    )
    return patient, panel, plan


def create_active_plan_with_vial(
    epinephrine_on_file=True,
    wheal_mm=6,
    control_wheal_mm=3,
    vial_color="YELLOW",
    prepared_volume_ml=5.0,
    potency=10000,
    lot_received_at="2026-01-01T00:00:00Z",
):
    """Patient + finalized panel + DRAFT plan + matching starting vial + activate.

    By default a SKIN wheal of 6 (index 3) -> MODERATE -> starting YELLOW, and a
    YELLOW vial is mixed so activation can succeed. Override `wheal_mm`/`vial_color`
    together to target a different starting tier/color.

    Returns dict with keys: patient, panel, plan, lot, vial, version
    (the plan's current version after activation).
    """
    patient, panel, plan = create_draft_plan(
        epinephrine_on_file=epinephrine_on_file,
        wheal_mm=wheal_mm,
        control_wheal_mm=control_wheal_mm,
    )
    lot = create_lot(vial_color, potency=potency, received_at_iso=lot_received_at)
    vial = mix_vial(
        plan["id"], lot["id"], plan["version"], prepared_volume_ml=prepared_volume_ml
    )
    activated = get_success_data(api_client.activate_plan(plan["id"], ALLERGIST))
    return {
        "patient": patient,
        "panel": panel,
        "plan": activated,
        "lot": lot,
        "vial": vial,
        "version": activated["version"],
    }


def create_red_active_plan(prepared_volume_ml=5.0, epinephrine_on_file=True,
                           potency=10000, lot_received_at="2026-01-01T00:00:00Z"):
    """An ACTIVE RED-start plan with a single RED starting vial.

    A SKIN wheal of 7 over control 3 -> index 4 -> clinical_composite 4 ->
    MODERATE? No: composite 4 is in [4,7) -> MODERATE -> YELLOW. To force RED we
    need LOW (composite < 4). A SKIN wheal of 6 over control 3 -> index 3 ->
    composite 3 -> LOW -> RED. Returns the create_active_plan_with_vial dict.
    """
    return create_active_plan_with_vial(
        epinephrine_on_file=epinephrine_on_file,
        wheal_mm=6,
        control_wheal_mm=3,
        vial_color="RED",
        prepared_volume_ml=prepared_volume_ml,
        potency=potency,
        lot_received_at=lot_received_at,
    )


def create_green_active_plan(prepared_volume_ml=5.0, epinephrine_on_file=True):
    """An ACTIVE GREEN-start plan (HIGH tier, wheal 10 -> index 7 -> composite 7)."""
    return create_active_plan_with_vial(
        epinephrine_on_file=epinephrine_on_file,
        wheal_mm=10,
        control_wheal_mm=3,
        vial_color="GREEN",
        prepared_volume_ml=prepared_volume_ml,
    )


def create_yellow_active_plan(prepared_volume_ml=5.0, epinephrine_on_file=True):
    """An ACTIVE YELLOW-start plan (MODERATE tier).

    A SKIN wheal of 7 over control 3 -> index 4 -> clinical_composite 4.0 which
    is in [4,7) -> MODERATE -> starting YELLOW, so a YELLOW vial satisfies
    activation.
    """
    return create_active_plan_with_vial(
        epinephrine_on_file=epinephrine_on_file,
        wheal_mm=7,
        control_wheal_mm=3,
        vial_color="YELLOW",
        prepared_volume_ml=prepared_volume_ml,
    )


# ─── Tier 3: lifecycle shortcuts ────────────────────────────────────────────
def administer_and_release(plan_id, vial_id, expected_plan_version,
                           admin_clock=None, release_clock="2026-01-01T01:00:00Z"):
    """Administer one shot then release it after the observation window.

    Caller supplies a release clock at least the visit's observation window
    after administration. The fixture advances the clock then releases with
    reaction_grade NONE. The release endpoint returns the (RELEASED) visit per
    the PRD, so the refreshed plan is re-fetched via GET. Returns
    (visit, refreshed_plan).
    """
    if admin_clock is not None:
        set_clock(admin_clock)
    visit = administer_shot(plan_id, vial_id, expected_plan_version)
    set_clock(release_clock)
    release_visit(visit["id"], release_clock, reaction_grade="NONE")
    plan = get_plan(plan_id)
    return visit, plan


def create_held_plan_via_systemic(prepared_volume_ml=5.0):
    """An ACTIVE RED-start plan put into HELD via a systemic reaction on its first shot.

    Patient has epinephrine_on_file=true. Returns dict with patient, panel, plan
    (HELD), lot, vial, visit, and held_version (the plan version while HELD,
    read back via GET so it is never stale).
    """
    ctx = create_red_active_plan(prepared_volume_ml=prepared_volume_ml)
    visit = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    record_reaction(visit["id"], "SYSTEMIC", epinephrine_administered=True)
    held_plan = get_plan(ctx["plan"]["id"])
    ctx["visit"] = visit
    ctx["plan"] = held_plan
    ctx["held_version"] = held_plan["version"]
    return ctx
