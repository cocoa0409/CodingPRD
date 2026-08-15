"""Application studies: feasibility tiers, segregation of duties, supersede
target validity, OCC, and reject-revise loop (PRD §3.2, §2.7)."""
from test_helpers import (
    ApiErrorId,
    assert_application_study,
    create_and_submit_study,
    create_application_study_payload,
    create_org,
    create_project,
    create_site,
    create_user,
    get_project,
    make_finance_admin_headers,
    make_project_engineer_headers,
    make_safety_lead_headers,
    move_project_to_study,
    setup_full_project,
    validate_error,
    validate_success,
)


def test_cycle_time_simulated_vs_measured_diverge(api):
    """PRD §3.2: "The `adjusted_cycle_time_s` is the simulated cycle time
    divided by one-hundredth of the confidence percentage, rounded half-up to
    three decimal places; the `feasibility` verdict is `FEASIBLE` when the
    adjusted time does not exceed the project's `contracted_cycle_time_s`".
    PRD §3.2: "the acceptance workflow of §3.6 uses the measured cycle time
    directly with no confidence derating, so the same cell legitimately
    produces two different cycle-time numbers across the two variants."

    Design: Difficulty/dual_variant_calc/cycle_time_simulated_vs_measured_diverge
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-100"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    proj = move_project_to_study(ctx["project"], eng["id"])

    study = create_and_submit_study(
        proj, eng["id"], sim_cycle_time_s=8.0, sim_confidence_pct=80.0
    )
    assert_application_study(study)
    # 8.0 / 0.80 = 10.000 (derated). Contract is 10.0 -> FEASIBLE at exactly contract.
    assert study["adjusted_cycle_time_s"] == 10.000
    assert study["feasibility"] == "FEASIBLE"
    # Provisional derated value is stored on the study; the raw simulated
    # input remains on the study as well.
    assert study["sim_cycle_time_s"] == 8.0


def test_adjusted_cycle_time_feasibility_tiers(api):
    """PRD §3.2: "the `feasibility` verdict is `FEASIBLE` when the adjusted
    time does not exceed the project's `contracted_cycle_time_s`, `MARGINAL`
    when it exceeds the contract but stays at or under one hundred and ten
    percent of it, and `INFEASIBLE` beyond that."

    Design: Corner/calculations/adjusted_cycle_time_feasibility_tiers
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-T1"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    proj = move_project_to_study(ctx["project"], eng["id"])

    # 8.4 / 0.80 = 10.500 -> MARGINAL (10.0 < 10.500 <= 11.000).
    study = create_and_submit_study(
        proj, eng["id"], sim_cycle_time_s=8.4, sim_confidence_pct=80.0
    )
    assert study["adjusted_cycle_time_s"] == 10.5
    assert study["feasibility"] == "MARGINAL"


def test_segregation_of_duties_study_approve(api):
    """PRD §3.2: "The approver's `X-User-ID` must differ from the study's
    creating user id — a creator may never approve their own study, and a
    violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/segregation_of_duties_study_approve
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-SOD"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    proj = move_project_to_study(ctx["project"], eng["id"])
    study = create_and_submit_study(proj, eng["id"])

    # Creator attempts to approve their own study, even wearing SafetyLead.
    resp = api.approve_application_study(
        study["id"], make_safety_lead_headers(eng["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_supersede_target_must_be_approved_same_project(api):
    """PRD §3.2: "When `supersedes_study_id` is present it must reference an
    application study of the same project whose status is `APPROVED`, or the
    create is rejected with `ERR_SUPERSEDE_TARGET_INVALID`."

    Design: Corner/validations/supersede_target_must_be_approved_same_project
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-SUP"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    proj = move_project_to_study(ctx["project"], eng["id"])

    # First study stays in DRAFT (never approved).
    eng_hdrs = make_project_engineer_headers(eng["id"])
    fresh = get_project(proj["id"], eng_hdrs)
    s1 = validate_success(
        api.create_application_study(
            proj["id"],
            create_application_study_payload(
                fresh["version"], sim_cycle_time_s=9.0, sim_confidence_pct=100.0
            ),
            eng_hdrs,
        ),
        201,
    )
    assert s1["status"] == "DRAFT"

    fresh2 = get_project(proj["id"], eng_hdrs)
    resp = api.create_application_study(
        proj["id"],
        create_application_study_payload(
            fresh2["version"],
            sim_cycle_time_s=8.5,
            sim_confidence_pct=95.0,
            supersedes_study_id=s1["id"],
        ),
        eng_hdrs,
    )
    validate_error(resp, ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID)


def test_occ_stale_version_on_study_create(api):
    """PRD §2.7: "If the project's version has advanced since the client last
    read it, the create is rejected with `ERR_STALE_PROJECT_VERSION`
    (HTTP 412), because a prior supersede may already have replaced the very
    study the client intended to supersede."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_study_create
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-OCC2"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sl = ctx["users"]["SAFETY_LEAD"]
    proj = move_project_to_study(ctx["project"], eng["id"])
    eng_hdrs = make_project_engineer_headers(eng["id"])

    # Create + submit + approve S1.
    study1 = create_and_submit_study(proj, eng["id"])
    validate_success(
        api.approve_application_study(study1["id"], make_safety_lead_headers(sl["id"]))
    )

    # Capture current version, run a first supersede (bumps version).
    v_obs = get_project(proj["id"], eng_hdrs)["version"]
    s2 = validate_success(
        api.create_application_study(
            proj["id"],
            create_application_study_payload(
                v_obs,
                sim_cycle_time_s=8.8,
                sim_confidence_pct=98.0,
                supersedes_study_id=study1["id"],
            ),
            eng_hdrs,
        ),
        201,
    )
    assert s2["revision"] == 2

    study1_after = validate_success(api.get_application_study(study1["id"], eng_hdrs))
    assert study1_after["status"] == "SUPERSEDED"

    # Second create with the same (now stale) version must be rejected.
    resp = api.create_application_study(
        proj["id"],
        create_application_study_payload(
            v_obs,
            sim_cycle_time_s=8.7,
            sim_confidence_pct=97.0,
            supersedes_study_id=study1["id"],
        ),
        eng_hdrs,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION)


def test_business_referential_vs_state_on_study_create(api):
    """PRD §2.6: "The ladder, from first to last, is: ... 4. Whether the
    target entity stands in a state from which the requested transition is
    defined — `ERR_INVALID_STATE` (HTTP 409). ... 13. Supersede-target
    validity on study creation — `ERR_SUPERSEDE_TARGET_INVALID` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_state_on_study_create
    """
    ctx = setup_full_project(project_overrides={"project_code": "P-PC2"})
    eng = ctx["users"]["PROJECT_ENGINEER"]
    sl = ctx["users"]["SAFETY_LEAD"]
    proj = move_project_to_study(ctx["project"], eng["id"])
    eng_hdrs = make_project_engineer_headers(eng["id"])

    # First study: create, submit, reject (leaves it REJECTED).
    study1 = create_and_submit_study(proj, eng["id"])
    validate_success(
        api.reject_application_study(study1["id"], make_safety_lead_headers(sl["id"]))
    )

    # Place the project ON_HOLD; on hold, child creates are state-blocked.
    validate_success(
        api.hold_cell_project(
            proj["id"], {"hold_reason": "customer request"}, eng_hdrs
        )
    )
    v_hold = get_project(proj["id"], eng_hdrs)["version"]

    # Supersede target is REJECTED (would be referential error) but the
    # state error must fire first.
    resp = api.create_application_study(
        proj["id"],
        create_application_study_payload(
            v_hold,
            sim_cycle_time_s=9.5,
            sim_confidence_pct=95.0,
            supersedes_study_id=study1["id"],
        ),
        eng_hdrs,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
