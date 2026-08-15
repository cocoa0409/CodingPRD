"""Composite setup helpers: canonical journeys through the VBC lifecycle.

Every test boots against an empty database, so each journey below is built
purely from PRD-declared endpoints. The ladders mirror the year lifecycle of
PRD §3.4 and the settlement lifecycle of PRD §3.10-§3.12.

Window-convention note: the PRD names the reconciliation runout, the dispute
window, and the dispute-resolution window without fixing their day counts, so
clock placements use FINALIZE (months past period_end), DISPUTE/RESOLVE (one
day after their anchor), and WINDOW_PAST / RESOLUTION_PAST (a full year after
their anchor) — outcomes are identical for any plausible window length.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CLOCK_DISPUTE, CLOCK_FINALIZE, CLOCK_INTERIM, CLOCK_MAR, CLOCK_RECONCILE,
    CLOCK_RESOLVE, CLOCK_START, CLOCK_WINDOW_PAST,
)
from .factories import (
    SINGLE_MEASURE_CATALOG, clock_payload, create_attribution_record_payload,
    create_attribution_run_payload, create_claim_payload, create_contract_payload,
    create_dispute_payload, create_interim_report_payload, create_member_payload,
    create_practice_group_payload, create_practice_payload, create_program_payload,
    create_quality_result_payload, create_renewal_analysis_payload,
    create_risk_score_payload, create_settlement_payload, create_span_payload,
    create_year_payload, resolve_dispute_payload, suspend_group_payload,
)
from .test_users import (
    TEST_USERS, make_dispute_adjudicator_headers,
    make_practice_group_rep_headers, make_settlement_officer_headers,
)

ADMIN = TEST_USERS["payer_admin_headers"]
MANAGER = TEST_USERS["contract_manager_headers"]
ATTRIBUTION = TEST_USERS["attribution_analyst_headers"]
ACTUARY = TEST_USERS["actuary_analyst_headers"]
QUALITY = TEST_USERS["quality_analyst_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]
OFFICER = TEST_USERS["settlement_officer_headers"]
ADJUDICATOR = TEST_USERS["dispute_adjudicator_headers"]
PAYMENTS = TEST_USERS["payment_ops_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

# Canonical member rosters: (member_ref, birth_year, span_start, span_end).
MEMBER_FULL_YEAR = ("M-001", 1980, "2026-01-01", "2026-12-31")
MEMBER_HALF_YEAR = ("M-002", 1975, "2026-07-01", "2026-12-31")
ONE_MEMBER_SPECS = [MEMBER_FULL_YEAR]
TWO_MEMBER_SPECS = [MEMBER_FULL_YEAR, MEMBER_HALF_YEAR]

# Canonical quality payloads: HBA1C 350/1000 scores 3 decile points; MAMMO
# 50/1000 scores 0 (PRD §3.8 achievement rule).
QUALITY_CANONICAL_DUAL = [("HBA1C", 350, 1000), ("MAMMO", 50, 1000)]
QUALITY_CANONICAL_SINGLE = [("HBA1C", 350, 1000)]


# ---------------------------------------------------------------------------
# Primitive creators (lenient validation; clear setup-failure messages)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


def make_program(activate=True, **overrides):
    program = get_success_data(api_client.create_program(create_program_payload(**overrides), ADMIN))
    if activate:
        program = get_success_data(api_client.activate_program(program["id"], ADMIN))
    return program


def make_group(**overrides):
    return get_success_data(
        api_client.create_practice_group(create_practice_group_payload(**overrides), ADMIN)
    )


def make_practice(group_id, **overrides):
    return get_success_data(
        api_client.create_practice(create_practice_payload(group_id, **overrides), ADMIN)
    )


def make_member(program_id, **overrides):
    return get_success_data(api_client.create_member(create_member_payload(program_id, **overrides), ADMIN))


def make_span(member_id, **overrides):
    return get_success_data(
        api_client.create_eligibility_span(create_span_payload(member_id, **overrides), ADMIN)
    )


def make_contract(program_id, group_id, activate=True, drop_fields=(), **overrides):
    payload = create_contract_payload(program_id, group_id, **overrides)
    for field in drop_fields:
        payload.pop(field, None)
    contract = get_success_data(api_client.create_contract(payload, MANAGER))
    if activate:
        contract = get_success_data(api_client.activate_contract(contract["id"], MANAGER))
    return contract


def make_year(contract_id, **overrides):
    return get_success_data(
        api_client.create_performance_year(create_year_payload(contract_id, **overrides), ADMIN)
    )


def get_year(year_id):
    return get_success_data(api_client.get_performance_year(year_id, ADMIN))


def get_contract(contract_id):
    return get_success_data(api_client.get_contract(contract_id, MANAGER))


def get_settlement(settlement_id):
    return get_success_data(api_client.get_settlement(settlement_id, OFFICER))


def year_version(year_id):
    return get_year(year_id)["version"]


def contract_version(contract_id):
    return get_contract(contract_id)["version"]


def open_year(year_id):
    return get_success_data(api_client.open_attribution(year_id, ADMIN))


def make_draft_run(year_id, run_label="R-1"):
    """Create an attribution run OCC-guarded against the year's live version (PRD §2.7)."""
    payload = create_attribution_run_payload(year_version(year_id), run_label=run_label)
    return get_success_data(api_client.create_attribution_run(year_id, payload, ATTRIBUTION))


def add_record(run_id, member_id, practice_id):
    return get_success_data(
        api_client.create_attribution_record(
            run_id, create_attribution_record_payload(member_id, practice_id), ATTRIBUTION
        )
    )


def compute_run(run_id):
    return get_success_data(api_client.compute_attribution_run(run_id, ATTRIBUTION))


def lock_run(run_id):
    return get_success_data(api_client.lock_attribution_run(run_id, ATTRIBUTION))


def make_locked_run(year_id, pairs, run_label="R-1"):
    """Draft run + one record per (member_id, practice_id) pair + compute + lock.
    Returns (run, records)."""
    run = make_draft_run(year_id, run_label=run_label)
    records = [add_record(run["id"], member_id, practice_id) for member_id, practice_id in pairs]
    run = compute_run(run["id"])
    run = lock_run(run["id"])
    return run, records


def lock_year_attribution(year_id):
    return get_success_data(api_client.lock_attribution(year_id, ADMIN))


def begin_measurement(year_id):
    return get_success_data(api_client.begin_measurement(year_id, ADMIN))


def begin_reconciliation(year_id, clock=CLOCK_RECONCILE):
    set_clock(clock)
    return get_success_data(api_client.begin_reconciliation(year_id, ADMIN))


def report_quality(year_id, measure_code, numerator, denominator, validate=True, lock=False):
    result = get_success_data(
        api_client.create_quality_result(
            create_quality_result_payload(
                year_id, measure_code=measure_code,
                numerator_count=numerator, denominator_count=denominator,
            ),
            QUALITY,
        )
    )
    if validate:
        result = get_success_data(api_client.validate_quality_result(result["id"], QUALITY))
    if lock:
        result = get_success_data(api_client.lock_quality_result(result["id"], QUALITY))
    return result


def make_claim(year_id, member_id, ref, service_date, amount, pay=False, pay_clock=None):
    """Create a claim; optionally mark it paid (stamping paid_on from the clock)."""
    claim = get_success_data(
        api_client.create_claim(
            create_claim_payload(
                year_id, member_id, claim_ref=ref,
                service_date=service_date, paid_amount_cents=amount,
            ),
            CLAIMS,
        )
    )
    if pay:
        if pay_clock:
            set_clock(pay_clock)
        claim = get_success_data(api_client.mark_claim_paid(claim["id"], CLAIMS))
    return claim


def make_risk_score(member_id, year_id, model, score_milli, finalize=False):
    score = get_success_data(
        api_client.create_risk_score(
            create_risk_score_payload(
                member_id, year_id, model_used=model, score_milli=score_milli
            ),
            ACTUARY,
        )
    )
    if finalize:
        score = get_success_data(api_client.finalize_risk_score(score["id"], ACTUARY))
    return score


def make_settlement(year_id):
    return get_success_data(api_client.create_settlement(create_settlement_payload(year_id), OFFICER))


def finalize_settlement(settlement_id, officer_user_id="so-1", clock=CLOCK_FINALIZE):
    set_clock(clock)
    return get_success_data(
        api_client.finalize_settlement(
            settlement_id, make_settlement_officer_headers(officer_user_id)
        )
    )


def recalculate_settlement(settlement_id):
    return get_success_data(api_client.recalculate_settlement(settlement_id, OFFICER))


def file_dispute(settlement_id, group_id, clock=CLOCK_DISPUTE, **overrides):
    """The owning PracticeGroupRep files a dispute (entity-backed identity)."""
    set_clock(clock)
    return get_success_data(
        api_client.create_dispute(
            settlement_id, create_dispute_payload(**overrides),
            make_practice_group_rep_headers(group_id),
        )
    )


def begin_review(dispute_id):
    return get_success_data(api_client.begin_dispute_review(dispute_id, ADJUDICATOR))


def resolve_dispute(dispute_id, outcome, adjudicator_user_id="adj-9", clock=CLOCK_RESOLVE):
    set_clock(clock)
    return get_success_data(
        api_client.resolve_dispute(
            dispute_id, resolve_dispute_payload(outcome),
            make_dispute_adjudicator_headers(adjudicator_user_id),
        )
    )


def make_interim_report(year_id, months_elapsed=6, clock=CLOCK_INTERIM):
    """Create a DRAFT interim report (OCC-guarded against the live year version).

    Creation computes both estimate variants, the estimated net payable, and
    the reserve accrual (PRD §3.9). Does not publish.
    """
    set_clock(clock)
    payload = create_interim_report_payload(
        year_id, year_version(year_id), months_elapsed=months_elapsed
    )
    return get_success_data(api_client.create_interim_report(payload, ACTUARY))


def publish_interim_report(year_id, months_elapsed=6, clock=CLOCK_INTERIM):
    """Create + publish an interim report (OCC-guarded create, then publish)."""
    set_clock(clock)
    payload = create_interim_report_payload(
        year_id, year_version(year_id), months_elapsed=months_elapsed
    )
    report = get_success_data(api_client.create_interim_report(payload, ACTUARY))
    return get_success_data(api_client.publish_interim_report(report["id"], ACTUARY))


def list_all_remittances():
    data, _meta = validate_paginated(api_client.list_remittances(PAYMENTS))
    return data


def remittance_for_practice(practice_id):
    matches = [r for r in list_all_remittances() if r["practice_id"] == practice_id]
    assert len(matches) == 1, f"expected exactly one remittance for practice {practice_id}"
    return matches[0]


def authorize_settlement(settlement_id, clock=CLOCK_WINDOW_PAST):
    """Authorize distribution past the dispute window; returns (settlement, remittances)."""
    set_clock(clock)
    settlement = get_success_data(api_client.authorize_distribution(settlement_id, OFFICER))
    return settlement, list_all_remittances()


def approve_remittance(remittance_id):
    return get_success_data(api_client.approve_remittance(remittance_id, PAYMENTS))


def pay_remittance(remittance_id):
    return get_success_data(api_client.mark_remittance_paid(remittance_id, PAYMENTS))


def pay_all_remittances(remittances):
    paid = []
    for rem in remittances:
        approve_remittance(rem["id"])
        paid.append(pay_remittance(rem["id"]))
    return paid


def mark_year_settled(year_id, clock=CLOCK_WINDOW_PAST):
    set_clock(clock)
    return get_success_data(api_client.mark_year_settled(year_id, OFFICER))


def close_year(year_id):
    return get_success_data(api_client.close_year(year_id, AUDITOR))


def expire_contract(contract_id):
    return get_success_data(api_client.expire_contract(contract_id, MANAGER))


def make_renewal_analysis(contract_id):
    """OCC-guarded renewal-analysis create against the contract's live version."""
    payload = create_renewal_analysis_payload(contract_version(contract_id))
    return get_success_data(api_client.create_renewal_analysis(contract_id, payload, MANAGER))


# ---------------------------------------------------------------------------
# Journey builder (Tier 2-5 composite)
# ---------------------------------------------------------------------------

def setup_org(member_specs=None, practice_count=2, group_overrides=None):
    """Program (ACTIVE) + one group + practices + members + eligibility spans."""
    set_clock(CLOCK_START)
    specs = member_specs if member_specs is not None else TWO_MEMBER_SPECS
    program = make_program()
    group = make_group(**(group_overrides or {}))
    practices = [
        make_practice(group["id"], practice_name=f"PR{i + 1}", npi=f"200000000{i + 1}")
        for i in range(practice_count)
    ]
    members, spans = [], []
    for ref, birth_year, span_start, span_end in specs:
        member = make_member(program["id"], member_ref=ref, birth_year=birth_year)
        members.append(member)
        spans.append(make_span(member["id"], start_date=span_start, end_date=span_end))
    return {
        "program": program, "group": group, "practices": practices,
        "members": members, "spans": spans,
    }


def build_pipeline(org, *, contract_overrides=None, contract_drop_fields=(),
                   attributions=None,
                   claim_specs=(), quality_specs=(), quality_lock=True,
                   risk_scores=(), stage="RECONCILING", contract_ref="C-1",
                   year_label=2026, period_start="2026-01-01", period_end="2027-01-01",
                   interim_months=None, finalize_officer="so-1"):
    """Build a contract + performance year and walk it to `stage`.

    stage ladder: SETUP -> OPEN -> RUN_LOCKED -> ATTRIBUTION_LOCKED ->
    MEASURING -> RECONCILING -> SETTLEMENT -> FINALIZED -> AUTHORIZED ->
    DISTRIBUTED -> SETTLED -> CLOSED -> EXPIRED.

    claim_specs: dicts {member (index), ref, service_date, amount,
                        pay (default True), pay_clock (optional)}.
    quality_specs: (measure_code, numerator, denominator) tuples.
    risk_scores: dicts {member (index), model, score, finalize (default True)}.
    attributions: (member_index, practice_index) pairs; defaults to diagonal.
    """
    ladder = ["SETUP", "OPEN", "RUN_LOCKED", "ATTRIBUTION_LOCKED", "MEASURING",
              "RECONCILING", "SETTLEMENT", "FINALIZED", "AUTHORIZED",
              "DISTRIBUTED", "SETTLED", "CLOSED", "EXPIRED"]
    target = ladder.index(stage)

    out = dict(org)
    out["claims"] = []
    out["quality"] = []
    out["risk_scores"] = []
    out["remittances"] = []

    # contract_ref is the default; an explicit contract_ref inside
    # contract_overrides wins (two contracts on one program need distinct refs).
    contract_kwargs = {"contract_ref": contract_ref}
    contract_kwargs.update(contract_overrides or {})
    contract = make_contract(
        org["program"]["id"], org["group"]["id"],
        activate=True, drop_fields=contract_drop_fields, **contract_kwargs,
    )
    year = make_year(
        contract["id"], year_label=year_label,
        period_start=period_start, period_end=period_end,
    )
    out.update(contract=contract, year=year, run=None, records=[],
               settlement=None, report=None)
    if target == 0:
        return out

    out["year"] = open_year(year["id"])
    if target == 1:
        return out

    # Claims ingest (paid at their own clocks, defaulting to CLOCK_MAR).
    for spec in claim_specs:
        out["claims"].append(make_claim(
            year["id"], org["members"][spec["member"]]["id"],
            ref=spec["ref"], service_date=spec["service_date"],
            amount=spec["amount"], pay=spec.get("pay", True),
            pay_clock=spec.get("pay_clock", CLOCK_MAR),
        ))

    # Risk scores (FINAL before attribution lock drive the rollup, PRD §3.6).
    for spec in risk_scores:
        out["risk_scores"].append(make_risk_score(
            org["members"][spec["member"]]["id"], year["id"],
            model=spec["model"], score_milli=spec["score"],
            finalize=spec.get("finalize", True),
        ))

    pairs = attributions
    if pairs is None:
        pairs = [(i, min(i, len(org["practices"]) - 1)) for i in range(len(org["members"]))]
    id_pairs = [(org["members"][mi]["id"], org["practices"][pi]["id"]) for mi, pi in pairs]
    run, records = make_locked_run(year["id"], id_pairs)
    out["run"] = run
    out["records"] = records
    if target == 2:
        return out

    out["year"] = lock_year_attribution(year["id"])
    if target == 3:
        return out

    out["year"] = begin_measurement(year["id"])
    for code, num, den in quality_specs:
        out["quality"].append(
            report_quality(year["id"], code, num, den, validate=True, lock=quality_lock)
        )
    if interim_months is not None:
        out["report"] = publish_interim_report(year["id"], months_elapsed=interim_months)
    if target == 4:
        return out

    out["year"] = begin_reconciliation(year["id"])
    if target == 5:
        return out

    out["settlement"] = make_settlement(year["id"])
    if target == 6:
        return out

    out["settlement"] = finalize_settlement(
        out["settlement"]["id"], officer_user_id=finalize_officer
    )
    if target == 7:
        return out

    out["settlement"], out["remittances"] = authorize_settlement(out["settlement"]["id"])
    if target == 8:
        return out

    pay_all_remittances(out["remittances"])
    out["settlement"] = get_settlement(out["settlement"]["id"])
    if target == 9:
        return out

    out["year"] = mark_year_settled(year["id"])
    if target == 10:
        return out

    out["year"] = close_year(year["id"])
    if target == 11:
        return out

    out["contract"] = expire_contract(contract["id"])
    return out


def single_member_journey(stage="RECONCILING", claim_amounts=None, **kwargs):
    """The single-member canonical journey: M1 (12 member-months) attributed to
    PR1 under a single-measure contract, PAID claims, HBA1C 350/1000 locked."""
    org = setup_org(member_specs=ONE_MEMBER_SPECS, practice_count=1)
    if claim_amounts is None:
        claim_amounts = [("2026-03-10", 400000)]
    claims = [
        {"member": 0, "ref": f"CL-{i + 1}", "service_date": service, "amount": amount}
        for i, (service, amount) in enumerate(claim_amounts)
    ]
    overrides = {"quality_measures": kwargs.pop("quality_measures", SINGLE_MEASURE_CATALOG)}
    overrides.update(kwargs.pop("contract_overrides", {}))
    return build_pipeline(
        org, stage=stage, claim_specs=claims,
        quality_specs=QUALITY_CANONICAL_SINGLE if kwargs.pop("quality", True) else (),
        contract_overrides=overrides, **kwargs,
    )


def canonical_two_member_journey(stage="RECONCILING", claim_amounts=None, **kwargs):
    """The two-member canonical journey: M1 (12 mm) -> PR1, M2 (6 mm) -> PR2,
    dual-measure catalog, both results locked (composite 30, multiplier 5000)."""
    org = setup_org(member_specs=TWO_MEMBER_SPECS, practice_count=2)
    if claim_amounts is None:
        claim_amounts = [("2026-03-10", 400000, 0), ("2026-09-05", 700000, 1)]
    claims = [
        {"member": member, "ref": f"CL-{i + 1}", "service_date": service, "amount": amount}
        for i, (service, amount, member) in enumerate(claim_amounts)
    ]
    return build_pipeline(
        org, stage=stage, claim_specs=claims,
        quality_specs=QUALITY_CANONICAL_DUAL, **kwargs,
    )
