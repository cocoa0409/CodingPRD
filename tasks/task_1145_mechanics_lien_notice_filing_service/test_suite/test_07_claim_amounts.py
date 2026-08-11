"""Lien claim amount computation: dual variants, caps, waterfall, lock gates
(PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    apply_waiver,
    create_company,
    create_draft_claim,
    create_payment,
    create_project,
    create_verified_project,
    create_waiver,
    get_lien_claim,
    lock_claim,
    make_customer_admin_headers,
    order_notice,
    publish_rule,
    record_proof,
    record_span,
    serve_notice,
    setup_project_with_proofed_notice,
    setup_tx_public_project,
    setup_verified_ca_project,
    validate_error,
    verify_payment,
)
from test_helpers import api_client as api
from test_helpers.factories import create_lien_claim_payload
from test_helpers.test_users import TEST_USERS

_PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
_OPS_AGENT = TEST_USERS["ops_agent_headers"]


# ─── Dual-variant amounts (queue A: dual_variant_calc) ───────────────

def _setup_dual_variant_scenario():
    """Verified CA project (contract 1000000, extras 200000, retainage 100000),
    proof-confirmed prelim notice, W1 UNCONDITIONAL 40000 APPLIED, W2
    CONDITIONAL 60000 APPLIED with its condition unmet, P1 VERIFIED 300000,
    P2 PENDING 50000."""
    ctx = setup_project_with_proofed_notice(
        notice_role="LENDER", name="CA Tower", county="Los Angeles",
        contract_value_cents=1000000, approved_extras_cents=200000,
        retainage_held_cents=100000,
    )
    project_id = ctx["project"]["id"]
    company_id = ctx["company"]["id"]

    w1 = create_waiver(project_id, company_id,
                       waiver_type="UNCONDITIONAL_PROGRESS", amount_cents=40000,
                       period_start="2026-05-01", period_end="2026-05-31")
    apply_waiver(w1["id"])
    w2 = create_waiver(project_id, company_id,
                       waiver_type="CONDITIONAL_PROGRESS", amount_cents=60000,
                       period_start="2026-06-01", period_end="2026-06-30")
    apply_waiver(w2["id"])

    p1 = create_payment(project_id, company_id,
                        amount_cents=300000, received_at="2026-06-15")
    verify_payment(p1["id"])
    create_payment(project_id, company_id,
                   amount_cents=50000, received_at="2026-06-20")  # stays PENDING
    return ctx


def test_provisional_amount_counts_pending_payments_and_all_waivers():
    """PRD §3.5: "The provisional variant is deliberately simple: the project's
    `contract_value_cents` plus its `approved_extras_cents`, minus the sum of
    all recorded payments on the project whether `PENDING` or `VERIFIED`, minus
    the sum of all waivers that are not `VOIDED`, floored at zero."
    (1000000 + 200000 - 350000 - 100000 = 750000.)

    Design: Difficulty/dual_variant_calc/provisional_vs_final_claim_amount
    """
    ctx = _setup_dual_variant_scenario()

    claim = create_draft_claim(ctx["project"]["id"], ctx["company"]["id"])
    assert claim["status"] == "DRAFT"
    assert claim["provisional_amount_cents"] == 750000


def test_final_amount_at_lock_uses_verified_payments_and_gates_conditional():
    """PRD §3.5: "From gross, subtract verified payments — the sum of
    `amount_cents` over the project's payments in `VERIFIED` status, regardless
    of which claim they are allocated to — and then subtract effective waivers."
    and "a `CONDITIONAL_PROGRESS` or `CONDITIONAL_FINAL` waiver counts only when
    a `VERIFIED` payment exists on the project whose `received_at` falls on or
    after the waiver's `period_end`."
    (gross 1100000 - verified 300000 - effective 40000 = 760000; the provisional
    750000 legitimately diverges.)

    Design: Difficulty/dual_variant_calc/provisional_vs_final_claim_amount
    """
    ctx = _setup_dual_variant_scenario()
    claim = create_draft_claim(ctx["project"]["id"], ctx["company"]["id"])

    locked = lock_claim(claim["id"], ctx["company"]["id"])
    assert locked["status"] == "AMOUNT_LOCKED"
    assert locked["gross_snapshot_cents"] == 1100000
    assert locked["verified_paid_cents"] == 300000
    assert locked["effective_waiver_cents"] == 40000
    assert locked["final_amount_cents"] == 760000
    assert locked["outstanding_cents"] == 760000
    assert locked["final_amount_cents"] != locked["provisional_amount_cents"]


# ─── Cap and waterfall at lock (queue A: combinatorial_formula) ──────

def _cap_scenario_with_claim():
    """WA project (contract 1000000, extras 200000, retainage 0) under a
    CONTRACT_BALANCE / retainage-claimable rule; proofed notice; W1
    UNCONDITIONAL 50000 APPLIED; P1 VERIFIED 800000; DRAFT claim created."""
    company = create_company(name="Cap Co", seed_balance_cents=10000000)
    rule = publish_rule(state_code="WA", retainage_claimable=True,
                        cap_mode="CONTRACT_BALANCE")
    project, parties = create_verified_project(
        company["id"], name="WA Job", state_code="WA", county="King",
        contract_value_cents=1000000, approved_extras_cents=200000,
        retainage_held_cents=0,
    )
    record_span(project["id"], company["id"])
    notice = order_notice(project["id"], company["id"], parties["OWNER"]["id"])
    serve_notice(notice["id"], "2026-05-20")
    record_proof(notice["id"])

    w1 = create_waiver(project["id"], company["id"],
                       waiver_type="UNCONDITIONAL_PROGRESS", amount_cents=50000,
                       period_start="2026-05-01", period_end="2026-05-31")
    apply_waiver(w1["id"])
    p1 = create_payment(project["id"], company["id"],
                        amount_cents=800000, received_at="2026-06-05")
    verify_payment(p1["id"])

    claim = create_draft_claim(project["id"], company["id"])
    return company, rule, project, claim


def test_final_amount_capped_by_contract_balance():
    """PRD §3.5: "When the rule's `cap_mode` is `UNCAPPED`, no cap applies;
    under `CONTRACT_BALANCE` the cap is the contract value minus verified
    payments, floored at zero. The `final_amount_cents` is the smaller of the
    cap and the remainder of gross minus verified payments minus effective
    waivers, floored at zero."
    (cap 200000 binds below the uncapped remainder 350000.)

    Design: Difficulty/combinatorial_formula/final_amount_cap_min_max_branch
    """
    _company, _rule, _project, claim = _cap_scenario_with_claim()

    locked = lock_claim(claim["id"], _company["id"])
    # retainage claimable -> nothing subtracted: gross = 1000000 + 200000
    assert locked["gross_snapshot_cents"] == 1200000
    assert locked["final_amount_cents"] == 200000


def test_waterfall_consumes_extras_pool_before_contract():
    """PRD §3.5: "An extras pool starts at `approved_extras_cents` and a
    contract pool at `contract_value_cents`; each waiver consumes the smaller of
    its `amount_cents` and the remaining extras pool, then consumes the smaller
    of its own remainder and the remaining contract pool."
    (single 50000 waiver lands entirely in the 200000 extras pool.)

    Design: Difficulty/combinatorial_formula/final_amount_cap_min_max_branch
    """
    _company, _rule, _project, claim = _cap_scenario_with_claim()

    locked = lock_claim(claim["id"], _company["id"])
    assert locked["waived_to_extras_cents"] == 50000
    assert locked["waived_to_contract_cents"] == 0


# ─── Zero/one-cent lock boundary (queue A: boundary_precision_check) ─

def _setup_boundary_project(name, contract_value_cents, paid_cents):
    """Verified CA project with proofed notice and one VERIFIED payment;
    returns (ctx, claim)."""
    ctx = setup_project_with_proofed_notice(
        name=name, county="Kern", contract_value_cents=contract_value_cents,
    )
    p = create_payment(ctx["project"]["id"], ctx["company"]["id"],
                       amount_cents=paid_cents, received_at="2026-06-01")
    verify_payment(p["id"])
    claim = create_draft_claim(ctx["project"]["id"], ctx["company"]["id"])
    return ctx, claim


def test_lock_with_zero_final_amount_rejected():
    """PRD §3.5: "the computed `final_amount_cents` must exceed zero
    (`ERR_ZERO_CLAIM_AMOUNT`, HTTP 422)."
    (contract 100000 - verified 100000 = 0.)

    Design: Difficulty/boundary_precision_check/zero_amount_lock_rejected_one_cent_locks
    """
    ctx, claim = _setup_boundary_project("Zero A", 100000, 100000)

    res = api.lock_lien_claim(
        claim["id"], make_customer_admin_headers(ctx["company"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_ZERO_CLAIM_AMOUNT)
    assert get_lien_claim(claim["id"])["status"] == "DRAFT"


def test_lock_with_one_cent_final_amount_succeeds():
    """PRD §3.5: "the computed `final_amount_cents` must exceed zero
    (`ERR_ZERO_CLAIM_AMOUNT`, HTTP 422)."
    (contract 100001 - verified 100000 = 1 cent above the boundary.)

    Design: Difficulty/boundary_precision_check/zero_amount_lock_rejected_one_cent_locks
    """
    ctx, claim = _setup_boundary_project("Zero B", 100001, 100000)

    locked = lock_claim(claim["id"], ctx["company"]["id"])
    assert locked["status"] == "AMOUNT_LOCKED"
    assert locked["final_amount_cents"] == 1


# ─── Prelim-notice gate on lock (queue A: cross_entity_state_dependency) ──

def _setup_served_notice_scenario():
    """Verified CA project (contract 50000) with a notice SERVED but not yet
    proofed, and a DRAFT claim."""
    ctx = setup_verified_ca_project(
        name="Gate Job", county="Shasta", contract_value_cents=50000,
    )
    notice = order_notice(ctx["project"]["id"], ctx["company"]["id"],
                          ctx["parties"]["OWNER"]["id"])
    serve_notice(notice["id"], "2026-05-20")
    claim = create_draft_claim(ctx["project"]["id"], ctx["company"]["id"])
    return ctx, notice, claim


def test_lock_rejected_while_prelim_notice_only_served():
    """PRD §3.5: "when the effective rule's `prelim_notice_required` is true, a
    notice order on the same project must already be `PROOF_CONFIRMED`
    (`ERR_PRELIM_NOTICE_REQUIRED`, HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/claim_lock_requires_proofed_prelim_notice
    """
    ctx, notice, claim = _setup_served_notice_scenario()
    res = api.lock_lien_claim(
        claim["id"], make_customer_admin_headers(ctx["company"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_PRELIM_NOTICE_REQUIRED)
    assert get_lien_claim(claim["id"])["status"] == "DRAFT"


def test_lock_succeeds_after_prelim_proof_confirmed():
    """PRD §3.5: "when the effective rule's `prelim_notice_required` is true, a
    notice order on the same project must already be `PROOF_CONFIRMED`
    (`ERR_PRELIM_NOTICE_REQUIRED`, HTTP 409)" and "A `result` of `DELIVERED`
    moves the notice to `PROOF_CONFIRMED`" (§3.4).

    Design: Difficulty/cross_entity_state_dependency/claim_lock_requires_proofed_prelim_notice
    """
    ctx, notice, claim = _setup_served_notice_scenario()

    confirmed = record_proof(notice["id"], result="DELIVERED")
    assert confirmed["status"] == "PROOF_CONFIRMED"

    locked = lock_claim(claim["id"], ctx["company"]["id"])
    assert locked["status"] == "AMOUNT_LOCKED"
    assert locked["final_amount_cents"] == 50000


# ─── Waterfall split across pools (queue B) ──────────────────────────

def test_waiver_waterfall_extras_before_contract():
    """PRD §3.5: "Effective waivers are processed in ascending `period_end`
    order, ties broken by ascending `created_at`." and "each waiver consumes the
    smaller of its `amount_cents` and the remaining extras pool, then consumes
    the smaller of its own remainder and the remaining contract pool."
    (W1 150000 fills 150000 of the 200000 extras pool; W2 100000 takes the last
    50000 of extras and spills 50000 to contract.)

    Design: Corner/calculations/waiver_waterfall_extras_before_contract
    """
    ctx = setup_project_with_proofed_notice(
        name="WW Job", contract_value_cents=1000000, approved_extras_cents=200000,
        retainage_held_cents=0,
    )
    project_id = ctx["project"]["id"]
    company_id = ctx["company"]["id"]

    w1 = create_waiver(project_id, company_id, amount_cents=150000,
                       period_start="2026-05-01", period_end="2026-05-31")
    apply_waiver(w1["id"])
    w2 = create_waiver(project_id, company_id, amount_cents=100000,
                       period_start="2026-06-01", period_end="2026-06-30")
    apply_waiver(w2["id"])

    claim = create_draft_claim(project_id, company_id)
    locked = lock_claim(claim["id"], company_id)
    assert locked["waived_to_extras_cents"] == 200000
    assert locked["waived_to_contract_cents"] == 50000
    assert locked["effective_waiver_cents"] == 250000
    assert locked["final_amount_cents"] == 950000


# ─── Claim creation gates (queue B) ──────────────────────────────────

def test_second_open_claim_rejected():
    """PRD §3.5: "when the project already has an open claim — one in `DRAFT`,
    `AMOUNT_LOCKED`, or `FILED` — it is rejected with `ERR_OPEN_CLAIM_EXISTS`
    (HTTP 409)."

    Design: Corner/validations/second_open_claim_rejected
    """
    company = create_company(name="OC Co", seed_balance_cents=1000000)
    publish_rule()
    project = create_project(company["id"], name="OC Job")
    create_draft_claim(project["id"], company["id"])

    res = api.create_lien_claim(
        create_lien_claim_payload(project["id"]),
        make_customer_admin_headers(company["id"]),
    )
    validate_error(res, ApiErrorId.ERR_OPEN_CLAIM_EXISTS)


def test_public_project_lien_claim_rejected():
    """PRD §3.5: "Liens exist only on private work." and "on a `STATE_PUBLIC`
    or `FEDERAL_PUBLIC` project the create is rejected with
    `ERR_LIEN_NOT_PERMITTED_PUBLIC` (HTTP 422)"

    Design: Corner/validations/public_project_lien_claim_rejected
    """
    ctx = setup_tx_public_project()

    res = api.create_lien_claim(
        create_lien_claim_payload(ctx["project"]["id"]),
        make_customer_admin_headers(ctx["company"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LIEN_NOT_PERMITTED_PUBLIC)
