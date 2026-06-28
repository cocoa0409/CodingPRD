"""Entity serializers — control the exact field set returned per resource.

Each serializer returns a plain dict with the fields the PRD/scaffold declares
for that entity, including the common id/created_at/updated_at/version fields.
Internal-only bookkeeping keys (prefixed with '_') are never exposed.
"""

COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(entity, fields):
    return {f: entity.get(f) for f in fields}


def patient(p):
    return _pick(p, COMMON + [
        "full_name",
        "date_of_birth",
        "epinephrine_on_file",
        "prior_systemic_reaction",
        "status",
    ])


def panel(p):
    return _pick(p, COMMON + [
        "patient_id",
        "panel_name",
        "control_wheal_mm",
        "screening_composite",
        "clinical_composite",
        "recommended_tier",
        "status",
    ])


def allergen_test(t):
    return _pick(t, COMMON + [
        "panel_id",
        "allergen_code",
        "method",
        "wheal_mm",
        "specific_ige_ku",
        "clinically_relevant",
        "sensitization_index",
        "is_positive",
    ])


def plan(p):
    return _pick(p, COMMON + [
        "patient_id",
        "panel_id",
        "starting_vial_color",
        "current_vial_color",
        "current_step_index",
        "phase",
        "last_dose_volume_ml",
        "status",
    ])


def lot(l):
    return _pick(l, COMMON + [
        "vial_color",
        "lot_number",
        "concentrate_potency_pnu_per_ml",
        "received_at_iso",
        "status",
    ])


def vial(v):
    return _pick(v, COMMON + [
        "plan_id",
        "lot_id",
        "vial_color",
        "dilution_factor",
        "prepared_volume_ml",
        "remaining_volume_ml",
        "shelf_life_days",
        "beyond_use_date_iso",
        "mixed_at_iso",
        "needs_refill",
        "status",
    ])


def visit(v):
    return _pick(v, COMMON + [
        "plan_id",
        "vial_id",
        "scheduled_dose_volume_ml",
        "administered_volume_ml",
        "antigen_units_delivered",
        "injection_count",
        "administered_at_iso",
        "observation_window_min",
        "released_at_iso",
        "reaction_grade",
        "epinephrine_administered",
        "status",
    ])


def billing_entry(b):
    return _pick(b, COMMON + [
        "visit_id",
        "vial_id",
        "patient_id",
        "cpt_code",
        "billed_dose_units",
        "charge_cents",
        "variant",
        "status",
    ])
