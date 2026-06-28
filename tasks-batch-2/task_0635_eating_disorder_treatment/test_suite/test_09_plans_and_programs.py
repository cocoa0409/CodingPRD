"""Treatment-plan fork-join activation, family-program auto-completion, and
discharge-plan finalization gating.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    CLINICIAN,
    fixtures as fx,
)


def test_treatment_plan_activate_before_all_disciplines_rejected(api):
    """PRD §3.7: "From `DRAFT`, activation is legal only when the plan is `DRAFT`,
    else `ERR_INVALID_STATE`, and only when all three flags are true — the join —
    else `ERR_DISCIPLINES_INCOMPLETE`".

    Design: Corner/state_machines/treatment_plan_activate_before_all_disciplines_signed_rejected
    """
    ctx = fx.setup_admitted_admission()
    tp = validate_success(
        api.create_treatment_plan(
            {"admission_id": ctx["admission"]["id"],
             "facility_id": ctx["facility"]["id"], "goals_total": 5},
            CLINICIAN,
        ),
        expected_status=201,
    )
    validate_success(
        api.sign_treatment_plan(tp["id"], {"discipline": "THERAPY"}, CLINICIAN)
    )
    validate_success(
        api.sign_treatment_plan(tp["id"], {"discipline": "MEDICAL"}, CLINICIAN)
    )
    # DIETITIAN unsigned: the join blocks.
    resp = api.activate_treatment_plan(tp["id"], CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_DISCIPLINES_INCOMPLETE.value)
    data = validate_success(api.get_treatment_plan(tp["id"], CLINICIAN))
    assert data["therapy_signed"] is True
    assert data["dietitian_signed"] is False


def test_family_program_auto_completes_at_required(api):
    """PRD §3.10: "A `Clinician` records a completed family session, which
    increments `sessions_completed` by one; once the completed count reaches or
    exceeds `sessions_required`, the status automatically advances to
    `COMPLETED`."

    Design: Corner/endpoints/family_program_complete_session_auto_completes_at_required
    """
    facility, program, cohort = fx.create_substrate()
    patient = fx.create_patient(facility["id"])
    admission = fx.create_admission(
        patient["id"], facility["id"], program["id"], cohort["id"]
    )
    fp = validate_success(
        api.create_family_program(
            {"admission_id": admission["id"], "facility_id": facility["id"],
             "family_contact_name": "Kin", "sessions_required": 2},
            CLINICIAN,
        ),
        expected_status=201,
    )
    validate_success(api.complete_family_session(fp["id"], CLINICIAN))
    final = validate_success(api.complete_family_session(fp["id"], CLINICIAN))
    assert final["sessions_completed"] == 2, (
        f"expected 2, got {final['sessions_completed']}"
    )
    assert final["status"] == "COMPLETED", (
        f"expected COMPLETED, got {final['status']}"
    )


def test_discharge_plan_finalize_without_relapse_complete_rejected(api):
    """PRD §3.10: "A `Clinician` finalizes the plan, moving it from `DRAFT` to
    `FINALIZED` (legal only from `DRAFT`, else `ERR_INVALID_STATE`); finalize
    requires `relapse_plan_complete` to be true, else
    `ERR_RELAPSE_PLAN_INCOMPLETE`."

    Design: Corner/state_machines/discharge_plan_finalize_without_relapse_plan_complete_rejected
    """
    facility, program, cohort = fx.create_substrate()
    patient = fx.create_patient(facility["id"])
    admission = fx.create_admission(
        patient["id"], facility["id"], program["id"], cohort["id"]
    )
    dp = validate_success(
        api.create_discharge_plan(
            {"admission_id": admission["id"], "facility_id": facility["id"],
             "aftercare_level_of_care": "OP", "relapse_warning_signs": "isolation",
             "relapse_plan_complete": False},
            CLINICIAN,
        ),
        expected_status=201,
    )
    resp = api.finalize_discharge_plan(dp["id"], CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_RELAPSE_PLAN_INCOMPLETE.value)
    data = validate_success(api.get_discharge_plan(dp["id"], CLINICIAN))
    assert data["status"] == "DRAFT", f"plan must stay DRAFT, got {data['status']}"
