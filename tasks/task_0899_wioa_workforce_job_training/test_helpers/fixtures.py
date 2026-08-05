"""Composite setup helpers for the WIOA Workforce API.

Every test runs against a freshly-restarted, empty server, so each helper builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls use
get_success_data() (lenient) so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS
from . import factories as f

ADMIN = TEST_USERS["state_admin_headers"]
CM = TEST_USERS["case_manager_headers"]
FO = TEST_USERS["fiscal_officer_headers"]
BSR = TEST_USERS["business_rep_headers"]
ANY = TEST_USERS["any_headers"]


# --- Atomic builders -------------------------------------------------------
def create_area(api, **overrides) -> dict:
    """Create a LocalArea. Returns its data (includes version)."""
    return get_success_data(api.create_local_area(f.create_local_area_payload(**overrides), ADMIN))


def intake_participant(api, la_id, **overrides) -> dict:
    return get_success_data(
        api.create_participant(la_id, f.create_participant_payload(**overrides), CM))


def make_eligible(api, p_id) -> dict:
    return get_success_data(
        api.determine_eligibility(p_id, {"decision": "ELIGIBLE"}, CM))


def enroll(api, p_id) -> dict:
    return get_success_data(api.enroll_participant(p_id, CM))


def exit_participant(api, p_id, **payload) -> dict:
    return get_success_data(api.exit_participant(p_id, CM, payload or {}))


def create_plan(api, p_id, **overrides) -> dict:
    return get_success_data(
        api.create_career_plan(p_id, f.create_career_plan_payload(**overrides), CM))


def activate_plan(api, cp_id) -> dict:
    return get_success_data(api.activate_career_plan(cp_id, CM))


def create_provider(api, la_id, **overrides) -> dict:
    return get_success_data(
        api.create_training_provider(la_id, f.create_training_provider_payload(**overrides), ADMIN))


def approve_provider(api, prov_id) -> dict:
    return get_success_data(api.approve_provider(prov_id, ADMIN))


def create_program(api, prov_id, **overrides) -> dict:
    return get_success_data(
        api.create_program(prov_id, f.create_program_payload(**overrides), ADMIN))


def create_voucher(api, p_id, program_id, career_plan_id, **overrides) -> dict:
    return get_success_data(
        api.create_voucher(p_id, f.create_voucher_payload(program_id, career_plan_id, **overrides), CM))


def obligate_voucher(api, v_id, expected_version) -> dict:
    return get_success_data(
        api.obligate_voucher(v_id, {"expected_local_area_version": expected_version}, CM))


def area_version(api, la_id) -> int:
    """Fetch the LocalArea's current version (the OCC anchor)."""
    return get_success_data(api.get_local_area(la_id, ANY))["version"]


def create_employer(api, la_id, **overrides) -> dict:
    return get_success_data(
        api.create_employer(la_id, f.create_employer_payload(**overrides), BSR))


def create_ojt(api, emp_id, participant_id, **overrides) -> dict:
    return get_success_data(
        api.create_ojt(emp_id, f.create_ojt_payload(participant_id, **overrides), BSR))


def activate_ojt(api, c_id) -> dict:
    return get_success_data(api.activate_ojt(c_id, BSR))


# --- Composite scenarios ---------------------------------------------------
def setup_eligible_enrolled_participant(api, area_overrides=None, participant_overrides=None) -> dict:
    """Area + participant advanced to ELIGIBLE + ENROLLED.

    Returns {la_id, la_version, p_id, area, participant}.
    """
    area = create_area(api, **(area_overrides or {}))
    p = intake_participant(api, area["id"], **(participant_overrides or {}))
    make_eligible(api, p["id"])
    enroll(api, p["id"])
    return {"la_id": area["id"], "la_version": area["version"], "p_id": p["id"],
            "area": area}


def setup_etpl_program(api, la_id, program_overrides=None) -> dict:
    """Approved provider with one ACTIVE program. Returns {prov_id, prog_id}."""
    prov = create_provider(api, la_id)
    approve_provider(api, prov["id"])
    prog = create_program(api, prov["id"], **(program_overrides or {}))
    return {"prov_id": prov["id"], "prog_id": prog["id"]}


def setup_training_ready(api, area_overrides=None, program_overrides=None,
                         plan_overrides=None) -> dict:
    """Full training-ready context: area + ELIGIBLE+ENROLLED participant +
    ACTIVE career plan + approved provider + ACTIVE program.

    Returns {la_id, la_version, p_id, cp_id, prov_id, prog_id, area}.
    """
    base = setup_eligible_enrolled_participant(api, area_overrides=area_overrides)
    cp = create_plan(api, base["p_id"], **(plan_overrides or {}))
    activate_plan(api, cp["id"])
    etpl = setup_etpl_program(api, base["la_id"], program_overrides=program_overrides)
    return {
        "la_id": base["la_id"],
        "la_version": base["la_version"],
        "p_id": base["p_id"],
        "cp_id": cp["id"],
        "prov_id": etpl["prov_id"],
        "prog_id": etpl["prog_id"],
        "area": base["area"],
    }


def setup_obligated_voucher(api, authorized_cost_cents=800_000,
                            planned_start_date="2026-06-01T00:00:00Z",
                            planned_end_date="2026-09-01T00:00:00Z",
                            area_overrides=None) -> dict:
    """Training-ready context plus one OBLIGATED voucher.

    Returns the setup_training_ready dict extended with {v_id, la_version_after}.
    """
    ctx = setup_training_ready(api, area_overrides=area_overrides)
    v = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                       authorized_cost_cents=authorized_cost_cents,
                       planned_start_date=planned_start_date,
                       planned_end_date=planned_end_date)
    obligate_voucher(api, v["id"], ctx["la_version"])
    ctx["v_id"] = v["id"]
    ctx["la_version_after"] = area_version(api, ctx["la_id"])
    return ctx


def setup_active_ojt_contract(api, obligated_amount_cents=100_000,
                              reimbursement_rate=0.5, wage_cents_per_hour=2000,
                              employer_overrides=None) -> dict:
    """ELIGIBLE+ENROLLED participant + SMALL employer + ACTIVE OJT contract.

    Returns {la_id, p_id, emp_id, c_id}.
    """
    base = setup_eligible_enrolled_participant(api)
    emp = create_employer(api, base["la_id"], **(employer_overrides or {}))
    c = create_ojt(api, emp["id"], base["p_id"],
                   reimbursement_rate=reimbursement_rate,
                   wage_cents_per_hour=wage_cents_per_hour,
                   obligated_amount_cents=obligated_amount_cents)
    activate_ojt(api, c["id"])
    return {"la_id": base["la_id"], "p_id": base["p_id"], "emp_id": emp["id"], "c_id": c["id"]}


def setup_approved_supportive_payment(api, amount_cents=50_000) -> dict:
    """Participant with ACTIVE plan documenting supportive need + APPROVED CHILDCARE payment.

    Returns {la_id, p_id, cp_id, ss_id}.
    """
    base = setup_eligible_enrolled_participant(api)
    cp = create_plan(api, base["p_id"], supportive_need_documented=True)
    activate_plan(api, cp["id"])
    ss = get_success_data(api.create_supportive(
        base["p_id"], f.create_supportive_payload(service_type="CHILDCARE", amount_cents=amount_cents), CM))
    get_success_data(api.approve_supportive(ss["id"], FO))
    return {"la_id": base["la_id"], "p_id": base["p_id"], "cp_id": cp["id"], "ss_id": ss["id"]}


def setup_requested_supportive_payment(api, amount_cents=50_000, activate_plan_flag=True,
                                       supportive_need_documented=True) -> dict:
    """Participant with a REQUESTED CHILDCARE payment; plan optionally activated.

    Returns {la_id, p_id, cp_id, ss_id}.
    """
    base = setup_eligible_enrolled_participant(api)
    cp = create_plan(api, base["p_id"], supportive_need_documented=supportive_need_documented)
    if activate_plan_flag:
        activate_plan(api, cp["id"])
    ss = get_success_data(api.create_supportive(
        base["p_id"], f.create_supportive_payload(service_type="CHILDCARE", amount_cents=amount_cents), CM))
    return {"la_id": base["la_id"], "p_id": base["p_id"], "cp_id": cp["id"], "ss_id": ss["id"]}
