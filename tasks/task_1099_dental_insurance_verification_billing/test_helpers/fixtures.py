"""Composite setup helpers.

Every helper takes the ApiClient `api` as its first argument, builds state from
scratch through PRD-declared endpoints, and uses the lenient get_success_data
validator so setup failures surface as clear "Setup failed" errors.

The logical clock starts at 2026-05-01T00:00:00Z before any set.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    make_frontoffice_headers, make_biller_headers, make_manager_headers,
    make_patient_headers,
)
from . import factories as f

FRONT = make_frontoffice_headers()
BILLER = make_biller_headers()
MANAGER = make_manager_headers()


# --------------------------------------------------------------------------
# Low-level single-entity helpers
# --------------------------------------------------------------------------
def set_clock(api, iso):
    return get_success_data(api.set_clock(iso, MANAGER))


def run_billing(api):
    return get_success_data(api.run_billing(MANAGER))


def new_patient(api, **overrides):
    return get_success_data(api.create_patient(f.create_patient_payload(**overrides), FRONT))


def new_plan(api, **overrides):
    return get_success_data(api.create_insurance_plan(f.create_insurance_plan_payload(**overrides), MANAGER))


def new_procedure(api, **overrides):
    return get_success_data(api.create_procedure(f.create_procedure_payload(**overrides), MANAGER))


def new_membership_plan(api, **overrides):
    return get_success_data(api.create_membership_plan(f.create_membership_plan_payload(**overrides), MANAGER))


def new_coverage(api, patient_id, plan_id, **overrides):
    return get_success_data(api.create_coverage(
        f.create_coverage_payload(patient_id, plan_id, **overrides), FRONT))


def new_verification(api, coverage, **overrides):
    """Create a verification against `coverage` (a coverage dict), threading its
    current version into expected_coverage_version."""
    ver = f.create_verification_payload(coverage["version"], **overrides)
    return get_success_data(api.create_verification(coverage["id"], ver, FRONT))


def new_membership(api, patient_id, mp_id, **overrides):
    return get_success_data(api.create_membership(
        f.create_membership_payload(patient_id, mp_id, **overrides), FRONT))


# --------------------------------------------------------------------------
# Tier 2/3: crown-claim scenarios (the dominant recurring preamble)
# --------------------------------------------------------------------------
def crown_scenario(api, *, clock=None, plan_overrides=None, proc_overrides=None,
                   cov_overrides=None, ver_overrides=None, verify=True):
    """Patient + InsurancePlan + a crown Procedure(D2740 MAJOR ucr 120000) +
    Coverage + (optionally) one Verification. Returns a dict of created entities.

    Defaults mirror the canonical P1/Delta plan (annual max 150000, deductible
    5000, major 50). Pass overrides to control any layer.
    """
    if clock is not None:
        set_clock(api, clock)
    patient = new_patient(api)
    plan = new_plan(api, **(plan_overrides or {"annual_maximum_cents": 150000,
                                              "deductible_cents": 5000,
                                              "major_coinsurance_pct": 50}))
    procedure = new_procedure(api, **(proc_overrides or {}))
    coverage = new_coverage(api, patient["id"], plan["id"], **(cov_overrides or {}))
    verification = None
    if verify:
        verification = new_verification(api, coverage, **(ver_overrides or {
            "verified_annual_maximum_cents": 150000,
            "verified_deductible_cents": 5000,
            "verified_preventive_pct": 100,
            "verified_basic_pct": 80,
            "verified_major_pct": 50,
        }))
    return {
        "patient": patient,
        "plan": plan,
        "procedure": procedure,
        "coverage": coverage,
        "verification": verification,
    }


def new_claim(api, patient_id, coverage_id, procedures, service_date="2026-05-01", **overrides):
    return get_success_data(api.create_claim(
        f.create_claim_payload(patient_id, coverage_id, procedures, service_date, **overrides),
        BILLER))


def submit_claim(api, claim_id, submit_user="biller_alice"):
    return get_success_data(api.submit_claim(claim_id, make_biller_headers(submit_user)))


def submitted_crown_claim(api, *, billed_fee_cents=130000, service_date="2026-05-01",
                          submit_user="biller_alice", clock=None,
                          plan_overrides=None, ver_overrides=None):
    """crown_scenario + a crown claim created and submitted. Returns
    (scenario_dict, submitted_claim_dict)."""
    sc = crown_scenario(api, clock=clock, plan_overrides=plan_overrides,
                        ver_overrides=ver_overrides)
    claim = new_claim(api, sc["patient"]["id"], sc["coverage"]["id"],
                     [{"cdt_code": "D2740", "billed_fee_cents": billed_fee_cents}],
                     service_date=service_date)
    submitted = submit_claim(api, claim["id"], submit_user=submit_user)
    return sc, submitted


def post_insurance_eob(api, patient_id, claim_id, *, amount_cents=57500,
                       allowed_cents=120000, paid_cents=57500,
                       deductible_applied_cents=5000, cdt_code="D2740",
                       post_user="mgr_bob"):
    """Post a non-denial INSURANCE EOB payment for a single crown line."""
    payload = f.create_payment_payload(
        patient_id, "INSURANCE", amount_cents, claim_id=claim_id, is_denial=False,
        eob_lines=[{"cdt_code": cdt_code, "allowed_cents": allowed_cents,
                    "paid_cents": paid_cents,
                    "deductible_applied_cents": deductible_applied_cents}])
    return get_success_data(api.create_payment(payload, make_manager_headers(post_user)))


def post_insurance_denial(api, patient_id, claim_id, *, post_user="mgr_bob"):
    payload = f.create_payment_payload(
        patient_id, "INSURANCE", 0, claim_id=claim_id, is_denial=True)
    return get_success_data(api.create_payment(payload, make_manager_headers(post_user)))


def adjudicated_crown_claim(api, *, billed_fee_cents=130000, paid_cents=57500,
                            allowed_cents=120000, deductible_applied_cents=5000,
                            submit_user="biller_alice", post_user="mgr_bob",
                            clock=None):
    """crown_scenario -> claim submitted -> single INSURANCE EOB posted.
    Returns (scenario_dict, claim_dict, payment_dict)."""
    sc, submitted = submitted_crown_claim(
        api, billed_fee_cents=billed_fee_cents, submit_user=submit_user, clock=clock)
    payment = post_insurance_eob(
        api, sc["patient"]["id"], submitted["id"], amount_cents=paid_cents,
        allowed_cents=allowed_cents, paid_cents=paid_cents,
        deductible_applied_cents=deductible_applied_cents, post_user=post_user)
    claim = get_success_data(api.get_claim(submitted["id"], BILLER))
    return sc, claim, payment


# --------------------------------------------------------------------------
# Tier 1/5: membership scenarios
# --------------------------------------------------------------------------
def enrolled_membership(api, *, clock="2026-05-01T00:00:00Z", annual_fee_cents=30000,
                        billing_period="MONTHLY", period_start="2026-05-01",
                        period_end="2027-05-01"):
    """Patient + MembershipPlan + an ACTIVE Membership. Returns
    (patient_dict, membership_plan_dict, membership_dict)."""
    if clock is not None:
        set_clock(api, clock)
    patient = new_patient(api)
    mp = new_membership_plan(api, annual_fee_cents=annual_fee_cents, billing_period=billing_period)
    membership = new_membership(api, patient["id"], mp["id"],
                               period_start=period_start, period_end=period_end)
    return patient, mp, membership


def pay_membership(api, membership_id, amount_cents, patient_id):
    return get_success_data(api.pay_membership(
        membership_id, amount_cents, make_patient_headers(patient_id)))
