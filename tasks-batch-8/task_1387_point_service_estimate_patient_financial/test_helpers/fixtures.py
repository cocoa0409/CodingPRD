"""Composite setup helpers for the patient financial clearance workflows.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, and threads the OCC parent-version fields
(`expected_patient_version`, `expected_case_version`, PRD §2.6) by re-reading
the parent immediately before each guarded create. Setup calls use the lenient
get_success_data() validator so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, INS_A
from .factories import (
    create_case_payload,
    create_charge_item_payload,
    create_contract_rate_payload,
    create_deposit_payload,
    create_eligibility_snapshot_payload,
    create_estimate_payload,
    create_patient_payload,
    create_payer_contract_payload,
    create_payment_plan_payload,
)
from .test_users import TEST_USERS, make_reviewer_headers, make_supervisor_headers

ADMIN = TEST_USERS["admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
COUNSELOR = TEST_USERS["counselor_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


# ─── Tier 0: Clock and configuration primitives ─────────────────────────────

def set_clock(to_iso8601: str = CLOCK_START) -> dict:
    """Advance the logical clock (runs the time-driven sweep, PRD §2.4)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_charge_item(cpt_code: str = INS_A["CPT_CODE"],
                       list_price_cents: int = INS_A["LIST_PRICE_CENTS"],
                       requires_auth_prior: bool = False,
                       description: str = "Total knee arthroplasty") -> dict:
    return get_success_data(api_client.create_charge_item(
        create_charge_item_payload(cpt_code=cpt_code,
                                   list_price_cents=list_price_cents,
                                   requires_auth_prior=requires_auth_prior,
                                   description=description),
        ADMIN))


def create_contract_with_rates(payer_code: str = INS_A["PAYER_CODE"],
                               bundling_rule: str = "NONE",
                               reduction_pct=None,
                               rates=()) -> dict:
    """Create a payer contract and attach rate windows.

    rates: iterable of dicts with keys cpt_code, rate_cents, effective_from
    and optional effective_to.
    """
    payload = create_payer_contract_payload(payer_code=payer_code,
                                            bundling_rule=bundling_rule)
    if reduction_pct is not None:
        payload["reduction_pct"] = reduction_pct
    contract = get_success_data(api_client.create_payer_contract(payload, ADMIN))
    for rate in rates:
        get_success_data(api_client.add_contract_rate(
            contract["id"], create_contract_rate_payload(**rate), ADMIN))
    return contract


def create_patient(mrn: str = "MRN-1000", full_name: str = "Test Patient",
                   date_of_birth: str = "1980-01-01") -> dict:
    return get_success_data(api_client.create_patient(
        create_patient_payload(mrn=mrn, full_name=full_name,
                               date_of_birth=date_of_birth),
        REGISTRAR))


def create_snapshot(patient_id: str, payer_code: str = INS_A["PAYER_CODE"],
                    member_id: str = "M-1000",
                    deductible_total_cents: int = INS_A["DEDUCTIBLE_TOTAL_CENTS"],
                    deductible_met_cents: int = INS_A["DEDUCTIBLE_MET_CENTS"],
                    oop_max_cents: int = INS_A["OOP_MAX_CENTS"],
                    oop_met_cents: int = INS_A["OOP_MET_CENTS"],
                    coinsurance_pct: int = INS_A["COINSURANCE_PCT"]) -> dict:
    """Capture an eligibility snapshot, threading the OCC patient version."""
    patient = get_success_data(api_client.get_patient(patient_id, REGISTRAR))
    return get_success_data(api_client.create_eligibility_snapshot(
        patient_id,
        create_eligibility_snapshot_payload(
            patient["version"], payer_code=payer_code, member_id=member_id,
            deductible_total_cents=deductible_total_cents,
            deductible_met_cents=deductible_met_cents,
            oop_max_cents=oop_max_cents, oop_met_cents=oop_met_cents,
            coinsurance_pct=coinsurance_pct),
        REGISTRAR))


def create_case(patient_id: str, service_date: str = INS_A["SERVICE_DATE"],
                service_description: str = "Scheduled service") -> dict:
    return get_success_data(api_client.create_case(
        patient_id,
        create_case_payload(service_date=service_date,
                            service_description=service_description),
        REGISTRAR))


def create_estimate(case_id: str, pricing_mode: str = "INSURED",
                    eligibility_snapshot_id=None, lines=None,
                    extra_fields=None) -> dict:
    """Create an estimate revision, threading the OCC case version."""
    case = get_success_data(api_client.get_case(case_id, COUNSELOR))
    payload = create_estimate_payload(
        case["version"], pricing_mode,
        lines if lines is not None else [{"cpt_code": INS_A["CPT_CODE"], "quantity": 1}],
        eligibility_snapshot_id=eligibility_snapshot_id)
    if extra_fields:
        payload.update(extra_fields)
    return get_success_data(api_client.create_estimate(case_id, payload, COUNSELOR))


# ─── Tier 1: Estimate state progression ─────────────────────────────────────

def price_estimate(estimate_id: str) -> dict:
    return get_success_data(api_client.price_estimate(estimate_id, COUNSELOR))


def present_estimate(estimate_id: str) -> dict:
    return get_success_data(api_client.present_estimate(estimate_id, COUNSELOR))


def accept_estimate(estimate_id: str) -> dict:
    return get_success_data(api_client.accept_estimate(estimate_id, COUNSELOR))


def finalize_estimate(estimate_id: str, actual_billed_cents: int) -> dict:
    return get_success_data(api_client.finalize_estimate(
        estimate_id, {"actual_billed_cents": actual_billed_cents}, COUNSELOR))


def price_present_estimate(estimate_id: str) -> dict:
    present_estimate(price_estimate(estimate_id)["id"])
    return get_success_data(api_client.get_estimate(estimate_id, COUNSELOR))


def price_present_accept_estimate(estimate_id: str) -> dict:
    accept_estimate(price_present_estimate(estimate_id)["id"])
    return get_success_data(api_client.get_estimate(estimate_id, COUNSELOR))


# ─── Tier 2: Insured scenario hierarchy ──────────────────────────────────────

def setup_insured_scenario(mrn: str = "MRN-1000",
                           cpt_code: str = INS_A["CPT_CODE"],
                           list_price_cents: int = INS_A["LIST_PRICE_CENTS"],
                           requires_auth_prior: bool = False,
                           bundling_rule: str = INS_A["BUNDLING_RULE"],
                           reduction_pct=INS_A["REDUCTION_PCT"],
                           rate_cents: int = INS_A["RATE_CENTS"],
                           service_date: str = INS_A["SERVICE_DATE"],
                           deductible_total_cents: int = INS_A["DEDUCTIBLE_TOTAL_CENTS"],
                           deductible_met_cents: int = INS_A["DEDUCTIBLE_MET_CENTS"],
                           oop_max_cents: int = INS_A["OOP_MAX_CENTS"],
                           oop_met_cents: int = INS_A["OOP_MET_CENTS"],
                           coinsurance_pct: int = INS_A["COINSURANCE_PCT"],
                           lines=None,
                           effective_from: str = INS_A["EFFECTIVE_FROM"],
                           effective_to=None,
                           with_contract: bool = True,
                           with_charge_item: bool = True,
                           clock: str = CLOCK_START) -> dict:
    """Charge item + contract/rate + patient + ACTIVE snapshot + case + DRAFT
    INSURED estimate. Returns a context dict with every entity. Pass
    with_charge_item=False when the charge item already exists."""
    set_clock(clock)
    if with_charge_item:
        create_charge_item(cpt_code=cpt_code, list_price_cents=list_price_cents,
                           requires_auth_prior=requires_auth_prior)
    contract = None
    if with_contract:
        rate = {"cpt_code": cpt_code, "rate_cents": rate_cents,
                "effective_from": effective_from}
        if effective_to is not None:
            rate["effective_to"] = effective_to
        contract = create_contract_with_rates(
            bundling_rule=bundling_rule, reduction_pct=reduction_pct, rates=[rate])
    patient = create_patient(mrn=mrn)
    snapshot = create_snapshot(
        patient["id"], payer_code=INS_A["PAYER_CODE"],
        deductible_total_cents=deductible_total_cents,
        deductible_met_cents=deductible_met_cents,
        oop_max_cents=oop_max_cents, oop_met_cents=oop_met_cents,
        coinsurance_pct=coinsurance_pct)
    case = create_case(patient["id"], service_date=service_date)
    estimate = create_estimate(
        case["id"], pricing_mode="INSURED",
        eligibility_snapshot_id=snapshot["id"],
        lines=lines or [{"cpt_code": cpt_code, "quantity": 1}])
    return {"patient": patient, "snapshot": snapshot, "case": case,
            "estimate": estimate, "contract": contract}


def setup_priced_insured_estimate(**kwargs) -> dict:
    """setup_insured_scenario + price. Context estimate is PRICED."""
    ctx = setup_insured_scenario(**kwargs)
    ctx["estimate"] = price_estimate(ctx["estimate"]["id"])
    return ctx


def setup_presented_insured_estimate(**kwargs) -> dict:
    ctx = setup_priced_insured_estimate(**kwargs)
    ctx["estimate"] = present_estimate(ctx["estimate"]["id"])
    return ctx


def setup_accepted_insured_estimate(**kwargs) -> dict:
    """Full walk through ACCEPTED (resp 500000 under default INS-A inputs)."""
    ctx = setup_presented_insured_estimate(**kwargs)
    ctx["estimate"] = accept_estimate(ctx["estimate"]["id"])
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], COUNSELOR))
    return ctx


# ─── Tier 2b: GFE scenario hierarchy ─────────────────────────────────────────

def setup_gfe_scenario(mrn: str = "MRN-2000", cpt_code: str = "27447",
                       list_price_cents: int = 5000000,
                       requires_auth_prior: bool = False,
                       service_date: str = INS_A["SERVICE_DATE"],
                       lines=None, with_charge_item: bool = True,
                       clock: str = CLOCK_START) -> dict:
    """Charge item + patient + case + DRAFT UNINSURED_GFE estimate. Pass
    with_charge_item=False when the charge item already exists."""
    set_clock(clock)
    if with_charge_item:
        create_charge_item(cpt_code=cpt_code, list_price_cents=list_price_cents,
                           requires_auth_prior=requires_auth_prior)
    patient = create_patient(mrn=mrn)
    case = create_case(patient["id"], service_date=service_date)
    estimate = create_estimate(
        case["id"], pricing_mode="UNINSURED_GFE",
        lines=lines or [{"cpt_code": cpt_code, "quantity": 1}])
    return {"patient": patient, "case": case, "estimate": estimate}


def setup_accepted_gfe_estimate(**kwargs) -> dict:
    """GFE estimate walked through price/present/accept. The context carries
    the priced gfe_total_cents and the post-acceptance case."""
    ctx = setup_gfe_scenario(**kwargs)
    ctx["estimate"] = price_estimate(ctx["estimate"]["id"])
    ctx["gfe_total_cents"] = ctx["estimate"]["gfe_total_cents"]
    ctx["estimate"] = present_estimate(ctx["estimate"]["id"])
    ctx["estimate"] = accept_estimate(ctx["estimate"]["id"])
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], COUNSELOR))
    return ctx


# ─── Tier 3: Authorization / escalation / deposit lifecycle shortcuts ───────

def request_authorization(case_id: str, cpt_codes=("27447",),
                          payer_code: str = INS_A["PAYER_CODE"],
                          requester_id: str = "ur-1") -> dict:
    return get_success_data(api_client.create_authorization(
        case_id, {"cpt_codes": list(cpt_codes), "payer_code": payer_code},
        make_reviewer_headers(requester_id)))


def approve_authorization(authorization_id: str,
                          valid_from: str = "2026-08-10",
                          valid_to: str = "2026-08-31",
                          decider_id: str = "ur-2") -> dict:
    return get_success_data(api_client.decide_authorization(
        authorization_id,
        {"decision": "APPROVED", "medical_necessity_met": True,
         "valid_from": valid_from, "valid_to": valid_to},
        make_reviewer_headers(decider_id)))


def request_and_approve_authorization(case_id: str, cpt_codes=("27447",),
                                      payer_code: str = INS_A["PAYER_CODE"],
                                      valid_from: str = "2026-08-10",
                                      valid_to: str = "2026-08-31",
                                      requester_id: str = "ur-1",
                                      decider_id: str = "ur-2") -> dict:
    auth = request_authorization(case_id, cpt_codes, payer_code, requester_id)
    return approve_authorization(auth["id"], valid_from, valid_to, decider_id)


def pledge_and_post_deposit(case_id: str, amount_cents: int,
                            method: str = "CARD") -> dict:
    deposit = get_success_data(api_client.create_deposit(
        case_id, create_deposit_payload(amount_cents=amount_cents, method=method),
        COUNSELOR))
    return get_success_data(api_client.post_deposit(deposit["id"], COUNSELOR))


def approve_open_escalations(case_id: str, decider_id: str = "sup-1") -> list:
    """Approve every OPEN escalation on the case (system-opened escalations may
    be decided by any supervisor, PRD §2.9). Returns the approved records."""
    approved = []
    data, _meta = _list_case_escalations(case_id)
    for esc in data:
        if esc["status"] == "OPEN":
            approved.append(get_success_data(api_client.approve_escalation(
                esc["id"], {"decision_note": "reviewed"},
                make_supervisor_headers(decider_id))))
    return approved


def _list_case_escalations(case_id: str):
    res = api_client.list_case_escalations(case_id, SUPERVISOR)
    body = res.json()
    return body["data"], body.get("meta", {})


def clear_case(case_id: str) -> dict:
    return get_success_data(api_client.clear_case(case_id, SUPERVISOR))


# ─── Tier 5: Cleared-case setups ─────────────────────────────────────────────

def setup_cleared_insured_case(mrn: str = "MRN-3000",
                               requires_auth_prior: bool = True,
                               deposit_amount_cents: int = None,
                               auth_valid_from: str = "2026-08-10",
                               auth_valid_to: str = "2026-08-31",
                               **scenario_kwargs) -> dict:
    """INS-A style case walked to CLEARED: accepted estimate, approved
    authorization (when requires_auth_prior), posted deposit covering the
    required amount, then clear. Returns the full context."""
    ctx = setup_accepted_insured_estimate(
        mrn=mrn, requires_auth_prior=requires_auth_prior, **scenario_kwargs)
    case_id = ctx["case"]["id"]
    if requires_auth_prior:
        ctx["authorization"] = request_and_approve_authorization(
            case_id, cpt_codes=(scenario_kwargs.get("cpt_code", INS_A["CPT_CODE"]),),
            valid_from=auth_valid_from, valid_to=auth_valid_to)
    case = get_success_data(api_client.get_case(case_id, COUNSELOR))
    amount = deposit_amount_cents
    if amount is None:
        amount = case["required_deposit_cents"]
    ctx["deposit"] = pledge_and_post_deposit(case_id, amount)
    ctx["case"] = clear_case(case_id)
    return ctx


def setup_cleared_gfe_case(mrn: str = "MRN-4000", **kwargs) -> dict:
    """GFE case walked to CLEARED: price (reads gfe_total_cents), any
    auto-opened high-dollar escalations approved, present/accept, deposit
    covering the required amount, then clear."""
    ctx = setup_gfe_scenario(mrn=mrn, **kwargs)
    case_id = ctx["case"]["id"]
    ctx["estimate"] = price_estimate(ctx["estimate"]["id"])
    ctx["gfe_total_cents"] = ctx["estimate"]["gfe_total_cents"]
    approve_open_escalations(case_id)
    ctx["estimate"] = present_estimate(ctx["estimate"]["id"])
    ctx["estimate"] = accept_estimate(ctx["estimate"]["id"])
    case = get_success_data(api_client.get_case(case_id, COUNSELOR))
    ctx["deposit"] = pledge_and_post_deposit(case_id, case["required_deposit_cents"])
    ctx["case"] = clear_case(case_id)
    return ctx


# ─── Tier 3b: Payment plan shortcuts ─────────────────────────────────────────

def create_draft_plan(case_id: str, principal_cents: int = 100001,
                      num_installments: int = 3) -> dict:
    return get_success_data(api_client.create_payment_plan(
        case_id, create_payment_plan_payload(principal_cents=principal_cents,
                                             num_installments=num_installments),
        COUNSELOR))


def create_active_plan(case_id: str, principal_cents: int = 100001,
                       num_installments: int = 3) -> dict:
    plan = create_draft_plan(case_id, principal_cents, num_installments)
    return get_success_data(api_client.activate_payment_plan(plan["id"], COUNSELOR))


def setup_defaulted_plan(mrn: str = "MRN-5000", principal_cents: int = 100001,
                         num_installments: int = 3,
                         default_sweep_to: str = "2026-09-17T00:00:00Z",
                         **scenario_kwargs) -> dict:
    """Accepted INS-A estimate + ACTIVE plan, then the clock sweeps past the
    first due date's 14-day grace so the plan is DEFAULTED (PRD §3.8)."""
    scenario_kwargs.setdefault("requires_auth_prior", False)
    ctx = setup_accepted_insured_estimate(mrn=mrn, **scenario_kwargs)
    ctx["plan"] = create_active_plan(ctx["case"]["id"], principal_cents,
                                     num_installments)
    ctx["sweep"] = set_clock(default_sweep_to)
    # Re-read the plan after the sweep.
    plans, _meta = _list_case_plans(ctx["case"]["id"])
    ctx["plan"] = plans[0]
    return ctx


def _list_case_plans(case_id: str):
    res = api_client.list_case_payment_plans(case_id, COUNSELOR)
    body = res.json()
    return body["data"], body.get("meta", {})
