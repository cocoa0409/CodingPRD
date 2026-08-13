"""Composite setup helpers for multi-step test prerequisites.

The settlement pipeline (period -> participants -> beneficiaries -> claims ->
adjudication -> alignment run -> lock -> benchmark -> quality -> settlement ->
finalize -> distribution) is 10-20 API calls deep; these helpers encapsulate it
so tests can focus on assertions. All setup calls use get_success_data() so
failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import PERFORMANCE_END, PERFORMANCE_START, RETRO_WINDOW_END, RETRO_WINDOW_START
from .factories import (
    create_adjustment_payload,
    create_agreement_period_payload,
    create_alignment_run_payload,
    create_appeal_payload,
    create_beneficiary_payload,
    create_benchmark_payload,
    create_claim_payload,
    create_election_payload,
    create_participant_payload,
    create_quality_score_payload,
    create_settlement_payload,
    decide_payload,
    determine_review_payload,
    rebuttal_payload,
    resubmit_score_payload,
    review_score_payload,
    set_clock_payload,
)
from .test_users import (
    APPEALS_OFFICER_1,
    CLAIMS_USER,
    DISTRIBUTION_APPROVER_1,
    MEDICAL_REVIEW_OFFICER_1,
    QUALITY_AUDITOR_1,
    QUALITY_REPORTER_1,
    SETTLEMENT_ACTUARY_1,
    make_actuary_headers,
    make_admin_headers,
    make_appeals_officer_headers,
    make_approver_headers,
    make_claims_processor_headers,
    make_participant_representative_headers,
    make_platform_admin_headers,
    make_quality_auditor_headers,
    make_quality_reporter_headers,
    make_review_officer_headers,
)

ADMIN = make_admin_headers()
CLAIMS = make_claims_processor_headers()
ACTUARY = make_actuary_headers()


# ─── Tier 0: single-step primitives ─────────────────────────────────────────

def create_period(tax_id=None, track="ONE_SIDED", start=PERFORMANCE_START,
                  end=PERFORMANCE_END, name="ACO") -> dict:
    payload = create_agreement_period_payload(
        aco_name=name, track=track,
        performance_start_date=start, performance_end_date=end,
    )
    if tax_id is not None:
        payload["aco_tax_id"] = tax_id
    return get_success_data(api_client.create_agreement_period(payload, ADMIN))


def get_period(period_id) -> dict:
    return get_success_data(api_client.get_agreement_period(period_id, ADMIN))


def current_period_version(period_id) -> int:
    return get_period(period_id)["version"]


def open_period(period_id) -> dict:
    return get_success_data(api_client.open_agreement_period(period_id, ADMIN))


def lock_period(period_id) -> dict:
    return get_success_data(api_client.lock_assignment(period_id, ADMIN))


def add_participant(period_id, tin, legal_name, share_weight_bp) -> dict:
    return get_success_data(api_client.create_participant(
        create_participant_payload(
            period_id, tin=tin, legal_name=legal_name, share_weight_bp=share_weight_bp,
        ),
        ADMIN,
    ))


def add_beneficiary(medicare_id, birth_year, **flags) -> dict:
    return get_success_data(api_client.create_beneficiary(
        create_beneficiary_payload(medicare_id=medicare_id, birth_year=birth_year, **flags),
        ADMIN,
    ))


def add_election(beneficiary_id, direction, effective_date) -> dict:
    return get_success_data(api_client.create_data_sharing_election(
        beneficiary_id,
        create_election_payload(direction=direction, effective_date=effective_date),
        ADMIN,
    ))


def ingest_claim(period_id, beneficiary_id, service_date, amount, claim_type,
                 participant_id=None) -> dict:
    overrides = {}
    if participant_id is not None:
        overrides["participant_id"] = participant_id
    return get_success_data(api_client.create_claim(
        create_claim_payload(
            period_id, beneficiary_id, service_date=service_date,
            allowed_amount_cents=amount, claim_type=claim_type, **overrides,
        ),
        CLAIMS,
    ))


def adjudicate(claim_id) -> dict:
    return get_success_data(api_client.adjudicate_claim(claim_id, CLAIMS))


def void_claim(claim_id, reason="duplicate") -> dict:
    return get_success_data(api_client.void_claim(claim_id, {"reason": reason}, CLAIMS))


def run_alignment(period_id, methodology="RETROSPECTIVE",
                  window_start=RETRO_WINDOW_START, window_end=RETRO_WINDOW_END) -> dict:
    """Create an alignment run, auto-capturing the current period version (PRD §2.6)."""
    version = current_period_version(period_id)
    return get_success_data(api_client.create_alignment_run(
        period_id,
        create_alignment_run_payload(
            version, methodology=methodology,
            window_start_date=window_start, window_end_date=window_end,
        ),
        ADMIN,
    ))


def compute_benchmark(period_id, variant="FINAL") -> dict:
    """Compute a benchmark, auto-capturing the current period version (PRD §2.6)."""
    version = current_period_version(period_id)
    return get_success_data(api_client.create_benchmark(
        period_id, create_benchmark_payload(version, variant=variant), ADMIN,
    ))


def report_score(period_id, measure_code="M1", numerator=3, denominator=4,
                 max_points=10, reporter=QUALITY_REPORTER_1) -> dict:
    return get_success_data(api_client.create_quality_score(
        create_quality_score_payload(
            period_id, measure_code=measure_code, numerator=numerator,
            denominator=denominator, max_points=max_points,
        ),
        make_quality_reporter_headers(reporter),
    ))


def review_score(score_id, outcome="VALIDATED", auditor=QUALITY_AUDITOR_1) -> dict:
    return get_success_data(api_client.review_quality_score(
        score_id, review_score_payload(outcome), make_quality_auditor_headers(auditor),
    ))


def report_and_validate_score(period_id, measure_code="M1", numerator=3, denominator=4,
                              max_points=10, reporter=QUALITY_REPORTER_1,
                              auditor=QUALITY_AUDITOR_1) -> dict:
    score = report_score(period_id, measure_code, numerator, denominator, max_points, reporter)
    return review_score(score["id"], "VALIDATED", auditor)


def propose_settlement(period_id, actuary=SETTLEMENT_ACTUARY_1) -> dict:
    """Create a settlement, auto-capturing the current period version (PRD §2.6)."""
    version = current_period_version(period_id)
    return get_success_data(api_client.create_settlement(
        period_id, create_settlement_payload(version), make_actuary_headers(actuary),
    ))


def finalize_settlement(settlement_id, actuary=SETTLEMENT_ACTUARY_1) -> dict:
    return get_success_data(api_client.finalize_settlement(
        settlement_id, make_actuary_headers(actuary),
    ))


def reopen_settlement(settlement_id, reason="recount", actuary=SETTLEMENT_ACTUARY_1) -> dict:
    return get_success_data(api_client.reopen_settlement(
        settlement_id, {"reason": reason}, make_actuary_headers(actuary),
    ))


def run_distribution(settlement_id, actuary=SETTLEMENT_ACTUARY_1) -> dict:
    return get_success_data(api_client.create_distribution_run(
        settlement_id, make_actuary_headers(actuary),
    ))


def list_distribution_lines(settlement_id, status=None) -> list:
    params = {"settlement_id": settlement_id}
    if status is not None:
        params["status"] = status
    return get_success_data(api_client.list_distribution_lines(ACTUARY, params=params))


def approve_line(line_id, approver=DISTRIBUTION_APPROVER_1) -> dict:
    return get_success_data(api_client.approve_distribution_line(
        line_id, make_approver_headers(approver),
    ))


def pay_line(line_id, approver=DISTRIBUTION_APPROVER_1) -> dict:
    return get_success_data(api_client.pay_distribution_line(
        line_id, make_approver_headers(approver),
    ))


def list_reviews(beneficiary_id=None, period_id=None, status=None) -> list:
    params = {}
    if beneficiary_id is not None:
        params["beneficiary_id"] = beneficiary_id
    if period_id is not None:
        params["agreement_period_id"] = period_id
    if status is not None:
        params["status"] = status
    return get_success_data(api_client.list_high_cost_reviews(ADMIN, params=params))


def determine_review(review_id, outcome, rationale=None, officer=MEDICAL_REVIEW_OFFICER_1) -> dict:
    payload = determine_review_payload(outcome)
    if rationale is not None:
        payload["rationale"] = rationale
    return get_success_data(api_client.determine_high_cost_review(
        review_id, payload, make_review_officer_headers(officer),
    ))


def list_records(**filters) -> list:
    return get_success_data(api_client.list_attribution_records(ADMIN, params=filters))


def file_appeal(period_id, subject_type, subject_id, filer_participant_id,
                grounds="dispute") -> dict:
    return get_success_data(api_client.create_appeal(
        create_appeal_payload(period_id, subject_type, subject_id, grounds=grounds),
        make_participant_representative_headers(filer_participant_id),
    ))


def rebut_appeal(appeal_id, filer_participant_id, memo="round") -> dict:
    return get_success_data(api_client.create_rebuttal(
        appeal_id, rebuttal_payload(memo),
        make_participant_representative_headers(filer_participant_id),
    ))


def resume_appeal_review(appeal_id, officer=APPEALS_OFFICER_1) -> dict:
    return get_success_data(api_client.resume_review(
        appeal_id, make_appeals_officer_headers(officer),
    ))


def decide_appeal(appeal_id, outcome, rationale=None, officer=APPEALS_OFFICER_1) -> dict:
    payload = decide_payload(outcome)
    if rationale is not None:
        payload["rationale"] = rationale
    return get_success_data(api_client.decide_appeal(
        appeal_id, payload, make_appeals_officer_headers(officer),
    ))


def post_adjustment(settlement_id, direction, amount_cents, reason_code,
                    appeal_id=None, actuary=SETTLEMENT_ACTUARY_1) -> dict:
    payload = create_adjustment_payload(
        direction=direction, amount_cents=amount_cents, reason_code=reason_code,
    )
    if appeal_id is not None:
        payload["appeal_id"] = appeal_id
    return get_success_data(api_client.create_reconciliation_adjustment(
        settlement_id, payload, make_actuary_headers(actuary),
    ))


def reverse_adjustment(adjustment_id, actuary=SETTLEMENT_ACTUARY_1) -> dict:
    return get_success_data(api_client.reverse_reconciliation_adjustment(
        adjustment_id, make_actuary_headers(actuary),
    ))


def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_current_utc(
        set_clock_payload(to_iso8601), make_platform_admin_headers(),
    ))


# ─── Tier 1: general scenario pipeline ──────────────────────────────────────

def build_period_scenario(
    tax_id=None,
    track="ONE_SIDED",
    participants=(("100000001", "PA", 10000),),
    beneficiaries=({"medicare_id": "MBI-1", "birth_year": 1960,
                    "dual_eligible": True, "disabled": True},),
    claims=({"beneficiary": 0, "participant": 0, "service_date": "2026-02-01",
             "amount": 20000, "claim_type": "PART_B"},),
    adjudicate_claims=True,
    methodology="RETROSPECTIVE",
    window=(RETRO_WINDOW_START, RETRO_WINDOW_END),
    run=True,
    lock=True,
    benchmark_variant="FINAL",
    quality_scores=(("M1", 3, 4, 10),),
    validate_quality=True,
    settlement=False,
    finalize=False,
    distribution=False,
) -> dict:
    """Walk the settlement pipeline end to end.

    participants: sequence of (tin, legal_name, share_weight_bp).
    beneficiaries: sequence of create kwargs (medicare_id, birth_year, flags...).
    claims: sequence of {beneficiary, participant, service_date, amount, claim_type}
            where beneficiary/participant are indexes into the created lists
            (participant may be None to omit the rendering participant).
    quality_scores: sequence of (measure_code, numerator, denominator, max_points);
            validated in turn when validate_quality is true.
    Returns a dict with every created artifact.
    """
    ctx = {
        "participants": [], "beneficiaries": [], "claims": [], "scores": [],
        "run": None, "benchmark": None, "settlement": None, "distribution": None,
    }
    period = create_period(tax_id=tax_id, track=track)
    ctx["period"] = period
    for tin, legal_name, weight in participants:
        ctx["participants"].append(add_participant(period["id"], tin, legal_name, weight))
    for spec in beneficiaries:
        ctx["beneficiaries"].append(add_beneficiary(**spec))

    if claims or run:
        open_period(period["id"])
    for spec in claims:
        participant_id = (
            ctx["participants"][spec["participant"]]["id"]
            if spec.get("participant") is not None else None
        )
        claim = ingest_claim(
            period["id"], ctx["beneficiaries"][spec["beneficiary"]]["id"],
            spec["service_date"], spec["amount"], spec["claim_type"],
            participant_id=participant_id,
        )
        ctx["claims"].append(claim)
    if adjudicate_claims:
        ctx["claims"] = [adjudicate(c["id"]) for c in ctx["claims"]]

    if run:
        ctx["run"] = run_alignment(
            period["id"], methodology=methodology,
            window_start=window[0], window_end=window[1],
        )
    if lock:
        ctx["period"] = lock_period(period["id"])
    if benchmark_variant is not None:
        ctx["benchmark"] = compute_benchmark(period["id"], variant=benchmark_variant)
    if quality_scores:
        for code, num, den, pts in quality_scores:
            score = report_score(period["id"], code, num, den, pts)
            if validate_quality:
                score = review_score(score["id"], "VALIDATED")
            ctx["scores"].append(score)
    if settlement:
        ctx["settlement"] = propose_settlement(period["id"])
    if finalize:
        ctx["settlement"] = finalize_settlement(ctx["settlement"]["id"])
    if distribution:
        ctx["distribution"] = run_distribution(ctx["settlement"]["id"])
    return ctx


# ─── Tier 2: named canonical scenarios ──────────────────────────────────────

# The two-beneficiary canonical population: BR (1960, dual+disabled -> risk 1.40)
# and BP (1990, no flags -> risk 1.00); PART_B visits plus large PART_A costs.
CANONICAL_BENEFICIARIES = (
    {"medicare_id": "MBI-C-R", "birth_year": 1960, "dual_eligible": True, "disabled": True},
    {"medicare_id": "MBI-C-P", "birth_year": 1990},
)


def canonical_claims(bp_big_amount=1341670):
    """Canonical claim set: 20000+20000 PART_B visits and 1500000+big PART_A costs."""
    return (
        {"beneficiary": 0, "participant": 0, "service_date": "2026-02-01",
         "amount": 20000, "claim_type": "PART_B"},
        {"beneficiary": 1, "participant": 0, "service_date": "2026-02-05",
         "amount": 20000, "claim_type": "PART_B"},
        {"beneficiary": 0, "participant": 0, "service_date": "2026-03-01",
         "amount": 1500000, "claim_type": "PART_A"},
        {"beneficiary": 1, "participant": 0, "service_date": "2026-03-02",
         "amount": bp_big_amount, "claim_type": "PART_A"},
    )


def setup_canonical_proposed_settlement(tax_id=None, participant_weights=(10000,),
                                        bp_big_amount=1341670,
                                        quality_scores=(("M1", 3, 4, 10),),
                                        validate_quality=True) -> dict:
    """Canonical period through a PROPOSED settlement: open -> claims -> adjudicate
    -> retrospective run -> lock -> FINAL benchmark -> quality -> settlement."""
    participants = tuple(
        (f"1000000{i + 1:02d}", f"P{chr(65 + i)}", w)
        for i, w in enumerate(participant_weights)
    )
    return build_period_scenario(
        tax_id=tax_id,
        participants=participants,
        beneficiaries=CANONICAL_BENEFICIARIES,
        claims=canonical_claims(bp_big_amount),
        quality_scores=quality_scores,
        validate_quality=validate_quality,
        settlement=True,
    )


def setup_lite_proposed_settlement(tax_id=None, quality_scores=(("M1", 3, 4, 10),),
                                   validate_quality=True) -> dict:
    """LITE period through a PROPOSED settlement: one participant (weight 10000),
    one beneficiary (1960, dual+disabled), one adjudicated 20000-cent PART_B visit."""
    return build_period_scenario(
        tax_id=tax_id, quality_scores=quality_scores,
        validate_quality=validate_quality, settlement=True,
    )


def setup_lite_final_settlement(tax_id=None) -> dict:
    """LITE period through a FINAL settlement."""
    return build_period_scenario(tax_id=tax_id, settlement=True, finalize=True)


def setup_lite_distributed(tax_id=None) -> dict:
    """LITE period through a FINAL settlement with its distribution run executed."""
    return build_period_scenario(
        tax_id=tax_id, settlement=True, finalize=True, distribution=True,
    )


def setup_locked_period_with_final_record(tax_id=None, beneficiary=None,
                                          claim_amount=20000) -> dict:
    """Locked period whose single beneficiary holds a FINAL attribution record."""
    beneficiaries = (beneficiary,) if beneficiary else (
        {"medicare_id": "MBI-L1", "birth_year": 1980},
    )
    return build_period_scenario(
        tax_id=tax_id, beneficiaries=beneficiaries,
        claims=({"beneficiary": 0, "participant": 0, "service_date": "2026-02-01",
                 "amount": claim_amount, "claim_type": "PART_B"},),
        benchmark_variant=None, quality_scores=None,
    )


def setup_attribution_appeal(tax_id=None, through="filed") -> dict:
    """Locked period with one FINAL record plus an appeal filed against it by the
    participant's representative. Returns ctx with `record` and `appeal` keys."""
    ctx = setup_locked_period_with_final_record(tax_id=tax_id)
    record = list_records(beneficiary_id=ctx["beneficiaries"][0]["id"])[0]
    ctx["record"] = record
    filer = ctx["participants"][0]["id"]
    ctx["appeal"] = file_appeal(
        ctx["period"]["id"], "ATTRIBUTION", record["id"], filer,
    )
    return ctx
