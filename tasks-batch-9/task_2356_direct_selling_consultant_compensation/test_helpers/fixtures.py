"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its
preconditions from scratch through the endpoints the PRD declares. Setup calls
use the lenient `get_success_data` validator so a broken precondition surfaces as
a setup failure rather than as a confusing assertion failure inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    ANALYST_USER_ID,
    JURISDICTION_NV,
    JURISDICTION_TX,
    PERIOD_2026_07,
    PERIOD_2026_08,
    PRODUCT_CATALOG,
    PRODUCT_KIT,
    PRODUCT_SACHET,
    PRODUCT_SAMPLE,
    PRODUCT_SERUM,
)
from .test_users import TEST_USERS, make_applicant_headers, make_consultant_headers

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["commission_analyst_headers"]
CONTROLLER = TEST_USERS["finance_controller_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
LEGAL = TEST_USERS["legal_reviewer_headers"]

DEFAULT_PRODUCTS = (PRODUCT_KIT, PRODUCT_SERUM, PRODUCT_SAMPLE, PRODUCT_CATALOG)
ALL_PRODUCTS = DEFAULT_PRODUCTS + (PRODUCT_SACHET,)


# --- Tier 1: single-resource creation ---------------------------------------


def set_clock(api, current_utc: str) -> dict:
    return get_success_data(api.set_clock(f.clock_payload(current_utc), ADMIN))


def read_clock(api, headers=None) -> dict:
    return get_success_data(api.get_clock(headers or ADMIN))


def create_plan(api, plan_code="PLAN-A", name="Consultant Plan A", **overrides) -> dict:
    payload = f.compensation_plan_payload(plan_code, name, **overrides)
    return get_success_data(api.create_compensation_plan(payload, ADMIN))


def create_jurisdiction(api, spec=None, **overrides) -> dict:
    spec = dict(spec or JURISDICTION_TX)
    spec.update(overrides)
    return get_success_data(api.create_tax_jurisdiction(spec, ADMIN))


def create_product(api, spec, **overrides) -> dict:
    payload = {
        "sku": spec["sku"],
        "name": spec["name"],
        "wholesale_price_cents": spec["wholesale_price_cents"],
        "srp_cents": spec["srp_cents"],
    }
    for optional in ("volume_points_per_unit", "commissionable", "buyback_eligible", "is_starter_kit"):
        if optional in spec:
            payload[optional] = spec[optional]
    payload.update(overrides)
    return get_success_data(api.create_product(payload, ADMIN))


def create_period(api, plan_id, spec=None, **overrides) -> dict:
    spec = spec or PERIOD_2026_08
    payload = f.qualification_period_payload(
        plan_id,
        period_code=spec["period_code"],
        period_start=spec["period_start"],
        period_end=spec["period_end"],
        **overrides,
    )
    return get_success_data(api.create_qualification_period(payload, ANALYST))


# --- Tier 2: the shared configuration environment ---------------------------


def setup_environment(
    api,
    plan_overrides=None,
    plan_code="PLAN-A",
    products=DEFAULT_PRODUCTS,
    jurisdictions=(JURISDICTION_TX,),
    periods=(PERIOD_2026_08,),
) -> dict:
    """Plan + tax jurisdictions + catalogue + qualification periods.

    Returns {"plan", "jurisdictions" (by state_code), "products" (by sku),
    "periods" (by period_code)}.
    """
    plan = create_plan(api, plan_code=plan_code, **(plan_overrides or {}))
    jurs = {spec["state_code"]: create_jurisdiction(api, spec) for spec in jurisdictions}
    prods = {spec["sku"]: create_product(api, spec) for spec in products}
    pers = {spec["period_code"]: create_period(api, plan["id"], spec) for spec in periods}
    return {"plan": plan, "jurisdictions": jurs, "products": prods, "periods": pers}


def setup_environment_both_states(api, **kwargs) -> dict:
    """Environment carrying both a facilitator-agreement state and a net-price state."""
    return setup_environment(api, jurisdictions=(JURISDICTION_TX, JURISDICTION_NV), **kwargs)


def setup_two_period_environment(api, **kwargs) -> dict:
    """Environment with consecutive periods 2026-07 and 2026-08."""
    return setup_environment(api, periods=(PERIOD_2026_07, PERIOD_2026_08), **kwargs)


# --- Tier 3: enrollment lifecycle shortcuts ---------------------------------


def create_application(
    api,
    env,
    email,
    full_name="Test Applicant",
    sponsor_consultant_id=None,
    state_code="TX",
    kit_sku="KIT-STD",
    identity_document_reference="DOC-1",
    headers=None,
    **overrides,
) -> dict:
    payload = f.enrollment_application_payload(
        env["plan"]["id"],
        env["products"][kit_sku]["id"],
        applicant_email=email,
        applicant_full_name=full_name,
        applicant_state_code=state_code,
        sponsor_consultant_id=sponsor_consultant_id,
        **overrides,
    )
    if identity_document_reference is not None:
        payload.setdefault("identity_document_reference", identity_document_reference)
    return get_success_data(api.create_enrollment_application(payload, headers or ADMIN))


def advance_application_to_ready(api, application) -> dict:
    """Accept the agreement, verify identity and pay the kit — the three gates."""
    email = application["applicant_email"]
    get_success_data(
        api.accept_agreement(
            application["id"], f.accept_agreement_payload(), make_applicant_headers(email)
        )
    )
    get_success_data(
        api.decide_identity(application["id"], f.identity_decision_payload("VERIFY"), COMPLIANCE)
    )
    return get_success_data(
        api.pay_starter_kit(
            application["id"],
            f.pay_starter_kit_payload(application["kit_total_cents"], f"KIT-{email}"),
            ADMIN,
        )
    )


def enroll_consultant(
    api,
    env,
    email,
    full_name="Test Consultant",
    sponsor_consultant_id=None,
    state_code="TX",
    kit_sku="KIT-STD",
) -> dict:
    """Create an application, clear all three gates and approve it. Returns the consultant."""
    application = create_application(
        api,
        env,
        email,
        full_name=full_name,
        sponsor_consultant_id=sponsor_consultant_id,
        state_code=state_code,
        kit_sku=kit_sku,
    )
    advance_application_to_ready(api, application)
    return get_success_data(api.approve_enrollment_application(application["id"], None, COMPLIANCE))


def enroll_root(api, env, email="alice@example.com", full_name="Alice Root", **kwargs) -> dict:
    return enroll_consultant(api, env, email, full_name=full_name, **kwargs)


def setup_single_root(api, env=None, **env_kwargs) -> dict:
    """Environment plus one root consultant. Returns {"env", "a"}."""
    env = env or setup_environment(api, **env_kwargs)
    return {"env": env, "a": enroll_root(api, env)}


def setup_genealogy_abc(api, env=None, **env_kwargs) -> dict:
    """Root A sponsors B, B sponsors C. Returns {"env", "a", "b", "c"}."""
    env = env or setup_environment(api, **env_kwargs)
    a = enroll_root(api, env)
    b = enroll_consultant(
        api, env, "bob@example.com", "Bob Mid", sponsor_consultant_id=a["id"]
    )
    c = enroll_consultant(
        api, env, "carol@example.com", "Carol Leaf", sponsor_consultant_id=b["id"]
    )
    return {"env": env, "a": a, "b": b, "c": c}


# --- Tier 3: ordering shortcuts ---------------------------------------------


def lines_for(env, *pairs):
    """Build order lines from (sku, quantity) pairs."""
    return [f.order_line(env["products"][sku]["id"], quantity) for sku, quantity in pairs]


def place_order(
    api,
    env,
    consultant,
    pairs,
    order_type="PERSONAL_INVENTORY",
    period_code=PERIOD_2026_08["period_code"],
    state_code="TX",
    headers=None,
) -> dict:
    payload = f.product_order_payload(
        consultant["id"],
        lines_for(env, *pairs),
        order_type=order_type,
        posted_period_code=period_code,
        ship_to_state_code=state_code,
    )
    return get_success_data(
        api.create_product_order(payload, headers or make_consultant_headers(consultant["id"]))
    )


def pay_order(api, consultant, order, amount_cents=None, reference="PAY-OK", headers=None) -> dict:
    payload = f.pay_order_payload(
        order["total_due_cents"] if amount_cents is None else amount_cents, reference
    )
    return get_success_data(
        api.pay_product_order(
            order["id"], payload, headers or make_consultant_headers(consultant["id"])
        )
    )


def place_and_pay_order(api, env, consultant, pairs, **kwargs) -> dict:
    """Place an order and pay it in full. Returns the paid order."""
    reference = kwargs.pop("reference", "PAY-OK")
    order = place_order(api, env, consultant, pairs, **kwargs)
    return pay_order(api, consultant, order, reference=reference)


# --- Tier 3: qualification and run lifecycle shortcuts ----------------------


def lock_period(api, period, headers=None) -> dict:
    return get_success_data(api.lock_qualification_period(period["id"], None, headers or ANALYST))


def close_period(api, period, headers=None) -> dict:
    return get_success_data(api.close_qualification_period(period["id"], None, headers or ANALYST))


def reopen_period(api, period, reason="apply the returned volume to group totals") -> dict:
    return get_success_data(
        api.reopen_qualification_period(period["id"], f.reopen_payload(reason), ADMIN)
    )


def read_period(api, period_id, headers=None) -> dict:
    return get_success_data(api.get_qualification_period(period_id, headers or ANALYST))


def read_consultant(api, consultant_id, headers=None) -> dict:
    return get_success_data(api.get_consultant(consultant_id, headers or ADMIN))


def qualification_of(api, consultant_id, period_id, headers=None) -> dict:
    """The single qualification row addressed by a consultant together with a period."""
    response = api.list_period_qualifications(
        headers or ANALYST,
        params={"consultant_id": consultant_id, "qualification_period_id": period_id},
    )
    rows = get_success_data(response)
    assert len(rows) == 1, f"expected exactly one qualification row, got {len(rows)}"
    return rows[0]


def create_run(api, period, expected_version=None, headers=None) -> dict:
    """Open a commission run, quoting the period's current version."""
    version = expected_version
    if version is None:
        version = read_period(api, period["id"])["version"]
    payload = f.commission_run_payload(period["id"], version)
    return get_success_data(api.create_commission_run(payload, headers or ANALYST))


def calculate_run(api, run, headers=None) -> dict:
    return get_success_data(api.calculate_commission_run(run["id"], None, headers or ANALYST))


def approve_run(api, run, headers=None, decision_note=None) -> dict:
    return get_success_data(
        api.decide_commission_run_approval(
            run["id"], f.approval_decision_payload("APPROVE", decision_note), headers or CONTROLLER
        )
    )


def pay_run(api, run, headers=None) -> dict:
    return get_success_data(api.pay_commission_run(run["id"], None, headers or CONTROLLER))


def reverse_run(api, run, reason="duplicate volume posting discovered", headers=None) -> dict:
    return get_success_data(
        api.reverse_commission_run(run["id"], f.reversal_payload(reason), headers or CONTROLLER)
    )


def statements_of(api, run_id, headers=None, **filters) -> list:
    params = {"commission_run_id": run_id}
    params.update(filters)
    return get_success_data(api.list_commission_statements(headers or ANALYST, params=params))


def statement_of(api, run_id, consultant_id, headers=None, status="ACTIVE") -> dict:
    rows = statements_of(api, run_id, headers=headers, consultant_id=consultant_id, status=status)
    assert len(rows) == 1, f"expected one {status} statement, got {len(rows)}"
    return rows[0]


# --- Tier 3: disclosure lifecycle shortcuts ---------------------------------


def draft_disclosure(api, run, population_basis="ALL_ENROLLED", expected_version=None, headers=None):
    version = expected_version
    if version is None:
        version = get_success_data(api.get_commission_run(run["id"], ANALYST))["version"]
    payload = f.income_disclosure_payload(run["id"], version, population_basis)
    return get_success_data(api.create_income_disclosure_statement(payload, headers or ANALYST))


def submit_disclosure(api, disclosure, headers=None) -> dict:
    return get_success_data(
        api.submit_disclosure_for_legal_review(disclosure["id"], None, headers or ANALYST)
    )


def publish_disclosure(api, disclosure, headers=None) -> dict:
    return get_success_data(
        api.decide_disclosure_legal_review(
            disclosure["id"], f.legal_decision_payload("PUBLISH"), headers or LEGAL
        )
    )


def draft_and_publish_disclosure(api, run, population_basis="ALL_ENROLLED") -> dict:
    disclosure = draft_disclosure(api, run, population_basis)
    submit_disclosure(api, disclosure)
    return publish_disclosure(api, disclosure)


# --- Tier 3: buyback, compliance and genealogy shortcuts --------------------


def request_buyback(api, env, consultant, lines, headers=None) -> dict:
    payload = f.buyback_request_payload(consultant["id"], lines)
    return get_success_data(
        api.create_buyback_request(payload, headers or make_consultant_headers(consultant["id"]))
    )


def buyback_lines_from_order(env, order, sku, quantity, condition="RESALABLE"):
    return [f.buyback_line(order["id"], env["products"][sku]["id"], quantity, condition)]


def approve_buyback(api, buyback, headers=None, decision_reason=None) -> dict:
    return get_success_data(
        api.decide_buyback_request(
            buyback["id"],
            f.buyback_decision_payload("APPROVE", decision_reason),
            headers or CONTROLLER,
        )
    )


def refund_buyback(api, buyback, headers=None) -> dict:
    return get_success_data(api.refund_buyback_request(buyback["id"], None, headers or CONTROLLER))


def open_case(api, consultant, claim_type="INCOME_CLAIM", evidence_reference="EV-1", headers=None):
    payload = f.compliance_case_payload(consultant["id"], claim_type, evidence_reference)
    return get_success_data(api.create_compliance_case(payload, headers or COMPLIANCE))


def review_case(api, case, headers=None) -> dict:
    return get_success_data(api.review_compliance_case(case["id"], None, headers or COMPLIANCE))


def sanction_case(
    api,
    case,
    sanction_level,
    effective_from,
    effective_until,
    decision_reason="sanction imposed",
    headers=None,
) -> dict:
    payload = f.compliance_decision_payload(
        "SANCTION",
        sanction_level=sanction_level,
        effective_from=effective_from,
        effective_until=effective_until,
        decision_reason=decision_reason,
    )
    return get_success_data(api.decide_compliance_case(case["id"], payload, headers or COMPLIANCE))


def dismiss_case(api, case, decision_reason="claim not substantiated", headers=None) -> dict:
    payload = f.compliance_decision_payload("DISMISS", decision_reason=decision_reason)
    return get_success_data(api.decide_compliance_case(case["id"], payload, headers or COMPLIANCE))


def sanction_consultant(
    api,
    consultant,
    sanction_level="SUSPENSION",
    effective_from="2026-08-01T00:00:00Z",
    effective_until="2026-08-15T00:00:00Z",
    claim_type="INCOME_CLAIM",
) -> dict:
    """Open a case, move it into review and impose a sanction. Returns the case."""
    case = open_case(api, consultant, claim_type=claim_type)
    review_case(api, case)
    return sanction_case(api, case, sanction_level, effective_from, effective_until)


def appeal_case(api, consultant, case, appeal_statement="the claim was misread") -> dict:
    return get_success_data(
        api.appeal_compliance_case(
            case["id"], f.appeal_payload(appeal_statement), make_consultant_headers(consultant["id"])
        )
    )


def terminate_consultant(api, consultant, termination_reason="VOLUNTARY", headers=None) -> dict:
    return get_success_data(
        api.terminate_consultant(
            consultant["id"], f.termination_payload(termination_reason), headers or COMPLIANCE
        )
    )


def reinstate_consultant(api, consultant, note="returned within the window", headers=None) -> dict:
    return get_success_data(
        api.reinstate_consultant(
            consultant["id"], f.reinstatement_payload(note), headers or COMPLIANCE
        )
    )


def adjust_rank(api, consultant, rank_code, adjustment_reason=None, headers=None) -> dict:
    return get_success_data(
        api.adjust_consultant_rank(
            consultant["id"],
            f.rank_adjustment_payload(rank_code, adjustment_reason),
            headers or ADMIN,
        )
    )


def attest_personal_use(api, consultant, qualification, points, headers=None) -> dict:
    return get_success_data(
        api.attest_personal_use(
            qualification["id"],
            f.personal_use_attestation_payload(points),
            headers or make_consultant_headers(consultant["id"]),
        )
    )


# --- Tier 4: the three-generation volume scenario ---------------------------
#
# A (root) posts 600 net personal volume points, B (A's downline) posts 100 and
# C (B's downline) posts 2,400. A is administratively adjusted to DIRECTOR so
# that its rung pays three override levels. Every order is paid in full, so all
# volume has entered the compensation system before the period is locked.


def setup_three_generation_volume(api, env=None, adjust_a_to="DIRECTOR", **env_kwargs) -> dict:
    env = env or setup_environment(api, **env_kwargs)
    people = setup_genealogy_abc(api, env)
    a, b, c = people["a"], people["b"], people["c"]
    order_a = place_and_pay_order(
        api, env, a, [("SERUM", 30)], order_type="BUSINESS_SUPPLY", reference="PAY-A"
    )
    order_b = place_and_pay_order(
        api, env, b, [("SERUM", 5)], order_type="BUSINESS_SUPPLY", reference="PAY-B"
    )
    order_c = place_and_pay_order(
        api, env, c, [("SERUM", 120)], order_type="PERSONAL_INVENTORY", reference="PAY-C"
    )
    if adjust_a_to:
        a = adjust_rank(api, a, adjust_a_to)
    return {
        "env": env,
        "period": env["periods"][PERIOD_2026_08["period_code"]],
        "a": a,
        "b": b,
        "c": c,
        "order_a": order_a,
        "order_b": order_b,
        "order_c": order_c,
    }


def setup_locked_three_generation(api, **kwargs) -> dict:
    state = kwargs.pop("state", None) or setup_three_generation_volume(api, **kwargs)
    state["period"] = lock_period(api, state["period"])
    return state


def setup_closed_three_generation(api, **kwargs) -> dict:
    state = setup_locked_three_generation(api, **kwargs)
    state["period"] = close_period(api, state["period"])
    return state


def setup_calculated_run(api, **kwargs) -> dict:
    """Closed three-generation period with a CALCULATED commission run."""
    state = setup_closed_three_generation(api, **kwargs)
    state["run"] = create_run(api, state["period"])
    state["run"] = calculate_run(api, state["run"])
    return state


def setup_approved_run(api, **kwargs) -> dict:
    state = setup_calculated_run(api, **kwargs)
    state["run"] = approve_run(api, state["run"])
    return state


def setup_paid_run(api, **kwargs) -> dict:
    """The full arc: volume in, period locked and closed, run calculated, approved and paid."""
    state = setup_approved_run(api, **kwargs)
    state["run"] = pay_run(api, state["run"])
    return state


def setup_single_earner_paid_run(api, env=None, pairs=(("SERUM", 30),), order_type="BUSINESS_SUPPLY"):
    """One root consultant, one paid order, period locked and closed, run paid.

    Returns {"env", "period", "a", "order", "run"}.
    """
    env = env or setup_environment(api)
    a = enroll_root(api, env)
    order = place_and_pay_order(api, env, a, list(pairs), order_type=order_type)
    period = lock_period(api, env["periods"][PERIOD_2026_08["period_code"]])
    period = close_period(api, period)
    run = create_run(api, period)
    run = calculate_run(api, run)
    run = approve_run(api, run)
    run = pay_run(api, run)
    return {"env": env, "period": period, "a": a, "order": order, "run": run}


def setup_single_earner_closed_period(api, env=None, pairs=(("SERUM", 30),), order_type="BUSINESS_SUPPLY"):
    """One root consultant with paid volume and a CLOSED period, no run yet."""
    env = env or setup_environment(api)
    a = enroll_root(api, env)
    order = place_and_pay_order(api, env, a, list(pairs), order_type=order_type)
    period = lock_period(api, env["periods"][PERIOD_2026_08["period_code"]])
    period = close_period(api, period)
    return {"env": env, "period": period, "a": a, "order": order}


# --- Tier 5: two-period tenure scenarios ------------------------------------


def setup_two_period_tenure(
    api,
    plan_overrides=None,
    a_pairs=(("SERUM", 15),),
    b_pairs=(("SERUM", 45),),
    first_clock="2026-07-05T00:00:00Z",
    second_clock="2026-08-05T00:00:00Z",
    adjust_a_to=None,
) -> dict:
    """A sponsors B; both post volume in 2026-07 and again in 2026-08.

    The clock is moved into each period before its orders are placed, so the
    half-open interval test of PRD §3.3 is satisfied in both. Returns
    {"env", "a", "b", "july", "august"} with both periods still OPEN.
    """
    set_clock(api, first_clock)
    env = setup_two_period_environment(api, plan_overrides=plan_overrides)
    a = enroll_root(api, env)
    b = enroll_consultant(api, env, "bob@example.com", "Bob Mid", sponsor_consultant_id=a["id"])
    if adjust_a_to:
        a = adjust_rank(api, a, adjust_a_to)
    july = env["periods"][PERIOD_2026_07["period_code"]]
    august = env["periods"][PERIOD_2026_08["period_code"]]
    if a_pairs:
        place_and_pay_order(
            api, env, a, list(a_pairs), order_type="BUSINESS_SUPPLY",
            period_code=july["period_code"], reference="PAY-A-JUL",
        )
    if b_pairs:
        place_and_pay_order(
            api, env, b, list(b_pairs), order_type="BUSINESS_SUPPLY",
            period_code=july["period_code"], reference="PAY-B-JUL",
        )
    set_clock(api, second_clock)
    if a_pairs:
        place_and_pay_order(
            api, env, a, list(a_pairs), order_type="BUSINESS_SUPPLY",
            period_code=august["period_code"], reference="PAY-A-AUG",
        )
    if b_pairs:
        place_and_pay_order(
            api, env, b, list(b_pairs), order_type="BUSINESS_SUPPLY",
            period_code=august["period_code"], reference="PAY-B-AUG",
        )
    return {"env": env, "a": a, "b": b, "july": july, "august": august}


def lock_and_close(api, period) -> dict:
    return close_period(api, lock_period(api, period))
