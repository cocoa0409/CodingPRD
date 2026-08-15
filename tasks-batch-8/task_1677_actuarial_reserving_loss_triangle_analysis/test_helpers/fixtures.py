"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch through PRD-declared
endpoints — the test harness restarts the server before each test, so nothing
is shared between tests. Setup calls use the lenient get_success_data()
validator so a broken precondition surfaces as a clear "Setup failed" error.

Two canonical books are provided:

- "Minimal Book": one claim E-1 with a single 100000-cent payment at dev 0,
  triangle at 2025-Q1 (no fully-developed accident-quarter pair exists, so the
  pattern has no selected factors and the chain-ladder estimate equals the
  diagonal with zero IBNR; approval then needs no chief-actuary override).
- "Main Book": claims C-A (accident 2025-Q1: payments 100000@dev0,
  100000@dev1, 50000@dev2), C-B (accident 2025-Q2: 200000@dev0, 100000@dev1),
  C-D (accident 2025-Q2: 100000@dev0), triangle at 2025-Q3 and a SELECTED
  pattern with window [2025-Q3, 2026-Q2).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    case_reserve_set_payload,
    create_catastrophe_event_payload,
    create_claim_payload,
    create_development_pattern_payload,
    create_opinion_payload,
    create_reserve_run_payload,
    create_segment_payload,
    create_study_payload,
    create_triangle_payload,
    payment_payload,
    payment_reversal_payload,
    review_payload,
    set_clock_payload,
)
from .test_users import (
    make_actuarial_analyst_headers,
    make_appointed_actuary_headers,
    make_claims_examiner_headers,
    make_peer_reviewer_headers,
)

SETUP_ADMIN = "aa-setup"
SETUP_EXAMINER = "examiner-1"
DEFAULT_ANALYST = "analyst-1"
DEFAULT_REVIEWER = "reviewer-1"


# --- Primitive wrappers (one per endpoint) -----------------------------------


def create_segment(**overrides) -> dict:
    payload = create_segment_payload(**overrides)
    return get_success_data(
        api_client.create_segment(payload, make_appointed_actuary_headers(SETUP_ADMIN))
    )


def create_catastrophe_event(segment_id: str, **overrides) -> dict:
    payload = create_catastrophe_event_payload(segment_id, **overrides)
    return get_success_data(
        api_client.create_catastrophe_event(
            payload, make_appointed_actuary_headers(SETUP_ADMIN)
        )
    )


def create_claim(segment_id: str, **overrides) -> dict:
    payload = create_claim_payload(segment_id, **overrides)
    return get_success_data(
        api_client.create_claim(payload, make_claims_examiner_headers(SETUP_EXAMINER))
    )


def post_payment(claim_id: str, transaction_date: str, amount_cents: int) -> dict:
    payload = payment_payload(
        transaction_date=transaction_date, amount_cents=amount_cents
    )
    return get_success_data(
        api_client.post_claim_transaction(
            claim_id, payload, make_claims_examiner_headers(SETUP_EXAMINER)
        )
    )


def post_payment_reversal(
    claim_id: str, transaction_date: str, amount_cents: int
) -> dict:
    payload = payment_reversal_payload(
        transaction_date=transaction_date, amount_cents=amount_cents
    )
    return get_success_data(
        api_client.post_claim_transaction(
            claim_id, payload, make_claims_examiner_headers(SETUP_EXAMINER)
        )
    )


def post_case_reserve(claim_id: str, transaction_date: str, case_value_cents: int) -> dict:
    payload = case_reserve_set_payload(
        transaction_date=transaction_date, case_value_cents=case_value_cents
    )
    return get_success_data(
        api_client.post_claim_transaction(
            claim_id, payload, make_claims_examiner_headers(SETUP_EXAMINER)
        )
    )


def transition_claim(claim_id: str, target_status: str) -> dict:
    return get_success_data(
        api_client.set_claim_status(
            claim_id,
            {"target_status": target_status},
            make_claims_examiner_headers(SETUP_EXAMINER),
        )
    )


def aggregate_triangle(segment_id: str, basis: str, valuation_quarter: str) -> dict:
    payload = create_triangle_payload(
        segment_id, basis=basis, valuation_quarter=valuation_quarter
    )
    return get_success_data(
        api_client.create_triangle(
            payload, make_actuarial_analyst_headers(DEFAULT_ANALYST)
        )
    )


def create_pattern(
    segment_id: str,
    basis: str,
    valuation_quarter: str,
    effective_from_quarter: str,
    effective_to_quarter: str,
) -> dict:
    payload = create_development_pattern_payload(
        segment_id,
        basis=basis,
        valuation_quarter=valuation_quarter,
        effective_from_quarter=effective_from_quarter,
        effective_to_quarter=effective_to_quarter,
    )
    return get_success_data(
        api_client.create_development_pattern(
            payload, make_actuarial_analyst_headers(DEFAULT_ANALYST)
        )
    )


def select_pattern(pattern_id: str) -> dict:
    return get_success_data(
        api_client.select_development_pattern(
            pattern_id, make_actuarial_analyst_headers(DEFAULT_ANALYST)
        )
    )


def create_reserve_run(
    segment_id: str,
    valuation_quarter: str,
    method: str,
    basis: str,
    earned_exposure_cents=None,
    a_priori_loss_ratio=None,
) -> dict:
    payload = create_reserve_run_payload(
        segment_id, valuation_quarter=valuation_quarter, method=method, basis=basis
    )
    if earned_exposure_cents is not None:
        payload["earned_exposure_cents"] = earned_exposure_cents
    if a_priori_loss_ratio is not None:
        payload["a_priori_loss_ratio"] = a_priori_loss_ratio
    return get_success_data(
        api_client.create_reserve_run(
            payload, make_actuarial_analyst_headers(DEFAULT_ANALYST)
        )
    )


def create_study(
    segment_id: str,
    valuation_quarter: str,
    selected_method: str = "CHAIN_LADDER",
    selected_basis: str = "PAID",
    analyst_user_id: str = DEFAULT_ANALYST,
) -> dict:
    payload = create_study_payload(
        segment_id,
        valuation_quarter=valuation_quarter,
        selected_method=selected_method,
        selected_basis=selected_basis,
    )
    return get_success_data(
        api_client.create_study(
            payload, make_actuarial_analyst_headers(analyst_user_id)
        )
    )


def submit_study(study_id: str, analyst_user_id: str = DEFAULT_ANALYST) -> dict:
    return get_success_data(
        api_client.submit_study(
            study_id, make_actuarial_analyst_headers(analyst_user_id)
        )
    )


def review_study_decision(
    study_id: str,
    decision: str,
    reviewer_user_id: str = DEFAULT_REVIEWER,
    chief_actuary_override=None,
) -> dict:
    payload = review_payload(decision)
    if chief_actuary_override is not None:
        payload["chief_actuary_override"] = chief_actuary_override
    return get_success_data(
        api_client.review_study(
            study_id, payload, make_peer_reviewer_headers(reviewer_user_id)
        )
    )


def withdraw_study_by(study_id: str, analyst_user_id: str = DEFAULT_ANALYST) -> dict:
    return get_success_data(
        api_client.withdraw_study(
            study_id, make_actuarial_analyst_headers(analyst_user_id)
        )
    )


def create_opinion(
    statement_date: str = "2025-09-30",
    opinion_scope: str = "REASONABLE",
    actuary_user_id: str = "aa-1",
) -> dict:
    payload = create_opinion_payload(
        statement_date=statement_date, opinion_scope=opinion_scope
    )
    return get_success_data(
        api_client.create_opinion(
            payload, make_appointed_actuary_headers(actuary_user_id)
        )
    )


def attach_study_to_opinion(
    opinion_id: str, study_id: str, actuary_user_id: str = "aa-1"
) -> dict:
    return get_success_data(
        api_client.attach_study(
            opinion_id,
            {"study_id": study_id},
            make_appointed_actuary_headers(actuary_user_id),
        )
    )


def sign_opinion_as(opinion_id: str, actuary_user_id: str) -> dict:
    return get_success_data(
        api_client.sign_opinion(
            opinion_id, make_appointed_actuary_headers(actuary_user_id)
        )
    )


def set_logical_clock(to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_clock(
            set_clock_payload(to_iso8601),
            make_appointed_actuary_headers(SETUP_ADMIN),
        )
    )


def create_roll_forward(
    segment_id: str, valuation_quarter: str, analyst_user_id: str = DEFAULT_ANALYST
) -> dict:
    return get_success_data(
        api_client.create_roll_forward(
            {"segment_id": segment_id, "valuation_quarter": valuation_quarter},
            make_actuarial_analyst_headers(analyst_user_id),
        )
    )


# --- Tier 1: Minimal Book ----------------------------------------------------


def setup_minimal_book() -> dict:
    """Segment plus claim E-1 carrying a single 100000-cent dev-0 payment."""
    segment = create_segment(
        name="Minimal Book", line_of_business="WORKERS_COMP"
    )
    claim = create_claim(
        segment["id"],
        claim_number="E-1",
        accident_date="2025-01-15",
        report_date="2025-01-18",
    )
    post_payment(claim["id"], "2025-02-01T00:00:00Z", 100000)
    return {"segment": segment, "claim": claim}


def setup_minimal_book_with_triangle() -> dict:
    """Minimal Book plus a fresh PAID triangle at 2025-Q1."""
    ctx = setup_minimal_book()
    ctx["triangle"] = aggregate_triangle(ctx["segment"]["id"], "PAID", "2025-Q1")
    return ctx


def setup_minimal_book_with_pattern() -> dict:
    """Minimal Book plus a SELECTED pattern with window [2025-Q1, 2025-Q3)."""
    ctx = setup_minimal_book_with_triangle()
    pattern = create_pattern(
        ctx["segment"]["id"], "PAID", "2025-Q1", "2025-Q1", "2025-Q3"
    )
    ctx["pattern"] = select_pattern(pattern["id"])
    return ctx


def setup_minimal_book_with_run() -> dict:
    """Minimal Book plus a fresh CHAIN_LADDER run at 2025-Q1."""
    ctx = setup_minimal_book_with_pattern()
    ctx["run"] = create_reserve_run(
        ctx["segment"]["id"], "2025-Q1", "CHAIN_LADDER", "PAID"
    )
    return ctx


def setup_minimal_book_study(status: str = "DRAFT") -> dict:
    """Minimal Book plus a study (creator analyst-1) walked to `status`.

    status: DRAFT | IN_REVIEW | APPROVED. The run's IBNR is zero, so the
    range-width gate passes without a chief-actuary override.
    """
    ctx = setup_minimal_book_with_run()
    ctx["study"] = create_study(
        ctx["segment"]["id"], "2025-Q1", "CHAIN_LADDER", "PAID"
    )
    if status in ("IN_REVIEW", "APPROVED"):
        ctx["study"] = submit_study(ctx["study"]["id"])
    if status == "APPROVED":
        ctx["study"] = review_study_decision(ctx["study"]["id"], "APPROVE")
    return ctx


# --- Tier 2: Main Book -------------------------------------------------------


def setup_main_book(include_claim_d: bool = True) -> dict:
    """Segment with claims C-A, C-B (and C-D unless excluded) fully posted."""
    segment = create_segment(name="Main Book", line_of_business="COMMERCIAL_AUTO")
    claims = {}
    claim_a = create_claim(
        segment["id"],
        claim_number="C-A",
        accident_date="2025-01-15",
        report_date="2025-01-20",
    )
    post_payment(claim_a["id"], "2025-02-01T00:00:00Z", 100000)
    post_payment(claim_a["id"], "2025-05-01T00:00:00Z", 100000)
    post_payment(claim_a["id"], "2025-09-01T00:00:00Z", 50000)
    claims["C-A"] = claim_a
    claim_b = create_claim(
        segment["id"],
        claim_number="C-B",
        accident_date="2025-04-10",
        report_date="2025-04-12",
    )
    post_payment(claim_b["id"], "2025-05-15T00:00:00Z", 200000)
    post_payment(claim_b["id"], "2025-08-10T00:00:00Z", 100000)
    claims["C-B"] = claim_b
    if include_claim_d:
        claim_d = create_claim(
            segment["id"],
            claim_number="C-D",
            accident_date="2025-04-10",
            report_date="2025-04-15",
        )
        post_payment(claim_d["id"], "2025-05-01T00:00:00Z", 100000)
        claims["C-D"] = claim_d
    return {"segment": segment, "claims": claims}


def setup_main_book_with_pattern(include_claim_d: bool = True) -> dict:
    """Main Book plus a fresh PAID triangle at 2025-Q3 and a SELECTED pattern
    with window [2025-Q3, 2026-Q2)."""
    ctx = setup_main_book(include_claim_d=include_claim_d)
    ctx["triangle"] = aggregate_triangle(ctx["segment"]["id"], "PAID", "2025-Q3")
    pattern = create_pattern(
        ctx["segment"]["id"], "PAID", "2025-Q3", "2025-Q3", "2026-Q2"
    )
    ctx["pattern"] = select_pattern(pattern["id"])
    return ctx


def setup_main_book_with_run(include_claim_d: bool = True) -> dict:
    """Main Book plus a fresh CHAIN_LADDER / PAID run at 2025-Q3."""
    ctx = setup_main_book_with_pattern(include_claim_d=include_claim_d)
    ctx["run"] = create_reserve_run(
        ctx["segment"]["id"], "2025-Q3", "CHAIN_LADDER", "PAID"
    )
    return ctx


def setup_main_book_study(status: str = "DRAFT") -> dict:
    """Main Book (claims C-A/C-B only, matching the targeting index's review
    scenarios) plus a study by analyst-1 walked to `status`.

    status: DRAFT | IN_REVIEW | APPROVED. Approval passes
    chief_actuary_override=true because the indicated range width ratio is
    three-quarters of IBNR over IBNR (0.75), above the segment cap of 0.5.
    """
    ctx = setup_main_book_with_run(include_claim_d=False)
    ctx["study"] = create_study(
        ctx["segment"]["id"], "2025-Q3", "CHAIN_LADDER", "PAID"
    )
    if status in ("IN_REVIEW", "APPROVED"):
        ctx["study"] = submit_study(ctx["study"]["id"])
    if status == "APPROVED":
        ctx["study"] = review_study_decision(
            ctx["study"]["id"], "APPROVE", chief_actuary_override=True
        )
    return ctx


# --- Tier 3: Opinion chains ---------------------------------------------------


def setup_approved_study_with_attached_opinion(
    book: str = "minimal",
    statement_date: str = "2025-09-30",
    actuary_user_id: str = "aa-1",
) -> dict:
    """Full governance chain: approved study + DRAFT opinion + attachment.

    Returns the book context plus "opinion". The opinion is left DRAFT so the
    caller controls the signing step (signer id, logical clock).
    """
    if book == "minimal":
        ctx = setup_minimal_book_study(status="APPROVED")
    else:
        ctx = setup_main_book_study(status="APPROVED")
    ctx["opinion"] = create_opinion(
        statement_date=statement_date, actuary_user_id=actuary_user_id
    )
    attach_study_to_opinion(
        ctx["opinion"]["id"], ctx["study"]["id"], actuary_user_id=actuary_user_id
    )
    return ctx
