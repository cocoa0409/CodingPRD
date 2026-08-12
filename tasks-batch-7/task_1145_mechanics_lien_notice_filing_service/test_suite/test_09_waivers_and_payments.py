"""Waiver period overlap (half-open), apply/void compensation, payment
verification idempotency, and the verify-to-auto-release cascade
(PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    apply_waiver,
    assert_claim_amounts_conserve_gross,
    create_company,
    create_draft_claim,
    create_payment,
    create_project,
    create_waiver,
    file_claim,
    get_lien_claim,
    get_project,
    lock_claim,
    make_customer_admin_headers,
    setup_project_with_proofed_notice,
    validate_error,
    validate_success,
    verify_payment,
)
from test_helpers import api_client as api
from test_helpers.factories import create_payment_payload, create_waiver_payload
from test_helpers.test_users import TEST_USERS

_PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
_OPS_AGENT = TEST_USERS["ops_agent_headers"]


# ─── Half-open waiver periods (queue A: resource_temporal_overlap) ───

def _setup_project_with_first_waiver():
    """CA project holding one non-VOIDED waiver over [2026-05-01, 2026-05-31)."""
    company = create_company(name="Ov Co")
    project = create_project(company["id"], name="Ov Job", county="Tehama",
                             approved_extras_cents=100000)
    waiver = create_waiver(project["id"], company["id"],
                           waiver_type="UNCONDITIONAL_PROGRESS",
                           amount_cents=10000,
                           period_start="2026-05-01", period_end="2026-05-31")
    return company, project, waiver


def test_adjacent_waiver_periods_allowed():
    """PRD §3.5: "Periods are half-open — each period includes its
    `period_start` and excludes its `period_end` — and a new waiver whose period
    overlaps a non-`VOIDED` waiver on the same project is rejected with
    `ERR_WAIVER_PERIOD_OVERLAP` (HTTP 409), while mere adjacency, where one
    waiver's `period_start` equals another's `period_end`, is allowed."

    Design: Difficulty/resource_temporal_overlap/waiver_period_half_open_overlap
    """
    company, project, _w1 = _setup_project_with_first_waiver()

    adjacent = create_waiver(project["id"], company["id"],
                             waiver_type="UNCONDITIONAL_PROGRESS",
                             amount_cents=20000,
                             period_start="2026-05-31", period_end="2026-06-30")
    assert adjacent["status"] == "RECEIVED"


def test_overlapping_waiver_period_rejected():
    """PRD §3.5: "a new waiver whose period overlaps a non-`VOIDED` waiver on
    the same project is rejected with `ERR_WAIVER_PERIOD_OVERLAP` (HTTP 409)"
    ([2026-05-15, 2026-06-15) shares interior days with the existing
    [2026-05-01, 2026-05-31).)

    Design: Difficulty/resource_temporal_overlap/waiver_period_half_open_overlap
    """
    company, project, _w1 = _setup_project_with_first_waiver()

    res = api.create_waiver(
        create_waiver_payload(
            project["id"], waiver_type="CONDITIONAL_FINAL", amount_cents=5000,
            period_start="2026-05-15", period_end="2026-06-15",
        ),
        make_customer_admin_headers(company["id"]),
    )
    validate_error(res, ApiErrorId.ERR_WAIVER_PERIOD_OVERLAP)


# ─── Apply/void compensation on a locked claim (queue A: compensating_invariant) ──

def _setup_locked_claim_with_waiver():
    """Locked claim: contract 1000000, extras 200000, retainage 100000
    (gross 1100000); P1 VERIFIED 300000; W1 UNCONDITIONAL 40000 APPLIED;
    final 760000."""
    ctx = setup_project_with_proofed_notice(
        name="Inv Job", county="Placer", contract_value_cents=1000000,
        approved_extras_cents=200000, retainage_held_cents=100000,
    )
    project_id = ctx["project"]["id"]
    company_id = ctx["company"]["id"]
    p1 = create_payment(project_id, company_id,
                        amount_cents=300000, received_at="2026-06-15")
    verify_payment(p1["id"])
    w1 = create_waiver(project_id, company_id,
                       waiver_type="UNCONDITIONAL_PROGRESS", amount_cents=40000,
                       period_start="2026-05-01", period_end="2026-05-31")
    apply_waiver(w1["id"])
    ctx["claim"] = create_draft_claim(project_id, company_id)
    ctx["claim"] = lock_claim(ctx["claim"]["id"], company_id)
    return ctx


def test_apply_waiver_recomputes_locked_amounts_conserving_gross():
    """PRD §3.5: "the project's open claim (whether `DRAFT` or `AMOUNT_LOCKED`)
    recomputes its waiver fields and amounts" — after applying a further 10000
    waiver, final drops to 750000 while verified 300000 + effective 50000 +
    final 750000 still equals the gross snapshot 1100000.

    Design: Difficulty/compensating_invariant/waiver_apply_void_conserves_gross_value
    """
    ctx = _setup_locked_claim_with_waiver()
    claim = ctx["claim"]
    assert claim["gross_snapshot_cents"] == 1100000
    assert claim["final_amount_cents"] == 760000
    assert_claim_amounts_conserve_gross(claim)

    w3 = create_waiver(ctx["project"]["id"], ctx["company"]["id"],
                       waiver_type="UNCONDITIONAL_FINAL", amount_cents=10000,
                       period_start="2026-07-01", period_end="2026-07-31")
    apply_waiver(w3["id"])

    after = get_lien_claim(claim["id"])
    assert after["final_amount_cents"] == 750000
    assert after["effective_waiver_cents"] == 50000
    assert_claim_amounts_conserve_gross(after)


def test_void_applied_waiver_restores_locked_amounts():
    """PRD §3.5: "voiding an applied waiver triggers a compensating recompute
    that restores the open claim's figures as if the waiver had never applied."

    Design: Difficulty/compensating_invariant/waiver_apply_void_conserves_gross_value
    """
    ctx = _setup_locked_claim_with_waiver()
    claim = ctx["claim"]

    w3 = create_waiver(ctx["project"]["id"], ctx["company"]["id"],
                       waiver_type="UNCONDITIONAL_FINAL", amount_cents=10000,
                       period_start="2026-07-01", period_end="2026-07-31")
    apply_waiver(w3["id"])

    voided = validate_success(
        api.void_waiver(w3["id"], make_customer_admin_headers(ctx["company"]["id"])),
        200,
    )
    assert voided["status"] == "VOIDED"

    after = get_lien_claim(claim["id"])
    assert after["final_amount_cents"] == 760000
    assert after["effective_waiver_cents"] == 40000
    assert_claim_amounts_conserve_gross(after)


# ─── Waiver state machine edges (queue B) ────────────────────────────

def test_waiver_apply_on_voided_rejected():
    """PRD §3.5: "an `OpsAgent` applies it, moving it `RECEIVED` → `APPLIED` —
    applying a waiver in any other state fails with `ERR_WAIVER_NOT_RECEIVED`
    (HTTP 409)" and "A `CustomerAdmin` may void a waiver from either `RECEIVED`
    or `APPLIED`"

    Design: Corner/state_machines/waiver_apply_on_voided_rejected
    """
    company = create_company(name="WV Co")
    project = create_project(company["id"], name="WV Job")
    waiver = create_waiver(project["id"], company["id"], amount_cents=5000)

    voided = validate_success(
        api.void_waiver(waiver["id"], make_customer_admin_headers(company["id"])),
        200,
    )
    assert voided["status"] == "VOIDED"

    res = api.apply_waiver(waiver["id"], _OPS_AGENT)
    validate_error(res, ApiErrorId.ERR_WAIVER_NOT_RECEIVED)


# ─── Payment verification (queue B) ──────────────────────────────────

def test_payment_verify_twice_rejected():
    """PRD §3.5: "The payment starts `PENDING`, and verification is valid only
    while the payment is `PENDING`."
    PRD §2.10: "when no specific state error applies, the generic
    `ERR_INVALID_STATE` is used."

    Design: Corner/state_machines/payment_verify_twice_rejected
    """
    company = create_company(name="PV Co")
    project = create_project(company["id"], name="PV Job")
    payment = create_payment(project["id"], company["id"], amount_cents=10000)

    verified = verify_payment(payment["id"])
    assert verified["status"] == "VERIFIED"

    res = api.verify_payment(payment["id"], _OPS_AGENT)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    # the amount is counted exactly once in a fresh claim's verified total
    claim = create_draft_claim(project["id"], company["id"])
    assert claim["verified_paid_cents"] == 10000


def test_payment_zero_amount_rejected():
    """PRD §3.5: "A `CustomerAdmin` records a payment with its `project_id`, an
    optional `lien_claim_id` allocation link used for outstanding-balance
    tracking, the `amount_cents` (which must exceed zero, else
    `ERR_AMOUNT_MUST_BE_POSITIVE`), and the `received_at` date"

    Design: Corner/validations/payment_zero_amount_rejected
    """
    company = create_company(name="ZA Co")
    project = create_project(company["id"], name="ZA Job")

    res = api.create_payment(
        create_payment_payload(project["id"], amount_cents=0,
                               received_at="2026-06-01"),
        make_customer_admin_headers(company["id"]),
    )
    validate_error(res, ApiErrorId.ERR_AMOUNT_MUST_BE_POSITIVE)


# ─── Verify-to-auto-release cascade (queue A: transitive_cascade) ────

def _setup_filed_claim_with_pending_payment():
    """FILED claim (final 100000 after a project-level VERIFIED 100000) plus a
    PENDING 100000 payment allocated to the claim."""
    ctx = setup_project_with_proofed_notice(
        name="Pay Job", county="Napa", contract_value_cents=200000,
    )
    project_id = ctx["project"]["id"]
    company_id = ctx["company"]["id"]
    p1 = create_payment(project_id, company_id,
                        amount_cents=100000, received_at="2026-06-01")
    verify_payment(p1["id"])
    claim = create_draft_claim(project_id, company_id)
    claim = lock_claim(claim["id"], company_id)
    assert claim["final_amount_cents"] == 100000
    claim = file_claim(claim["id"], "2026-07-01")
    p2 = create_payment(project_id, company_id, lien_claim_id=claim["id"],
                        amount_cents=100000, received_at="2026-08-01")
    return ctx, claim, p2


def test_payment_verify_drives_outstanding_to_zero():
    """PRD §3.5: "While `FILED`, the claim tracks `outstanding_cents`: the
    frozen `final_amount_cents` minus the sum of `VERIFIED` payments whose
    `lien_claim_id` names this claim."
    (100000 frozen - 100000 linked and verified = 0.)

    Design: Difficulty/transitive_cascade/payment_verify_auto_release_chain
    """
    _ctx, claim, p2 = _setup_filed_claim_with_pending_payment()

    verified = verify_payment(p2["id"])
    assert verified["status"] == "VERIFIED"

    claim_after = get_lien_claim(claim["id"])
    assert claim_after["outstanding_cents"] == 0


def test_zero_outstanding_auto_releases_filed_claim():
    """PRD §3.5: "When a payment verification drives the outstanding balance to
    zero, the claim auto-releases, moving `FILED` → `RELEASED`." and "Either
    way, release decrements the project's `open_lien_count` by one, recomputes
    the posture"

    Design: Difficulty/transitive_cascade/payment_verify_auto_release_chain
    """
    ctx, claim, p2 = _setup_filed_claim_with_pending_payment()
    assert get_project(ctx["project"]["id"])["open_lien_count"] == 1
    assert get_project(ctx["project"]["id"])["lien_posture"] == "ENCUMBERED"

    verify_payment(p2["id"])

    claim_after = get_lien_claim(claim["id"])
    assert claim_after["status"] == "RELEASED"
    project_after = get_project(ctx["project"]["id"])
    assert project_after["open_lien_count"] == 0
    # PRD §2.3: with no claim FILED, the still-PROOF_CONFIRMED prelim notice
    # makes the posture NOTICED ("failing that, `NOTICED` when any notice
    # order is `SERVED` or `PROOF_CONFIRMED`").
    assert project_after["lien_posture"] == "NOTICED"
