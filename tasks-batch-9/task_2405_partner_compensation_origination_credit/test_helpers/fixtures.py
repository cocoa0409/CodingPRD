"""Composite setup helpers.

Every helper builds its preconditions from scratch through published endpoints
only — each test runs against an empty database. Setup calls use the lenient
`get_success_data()` validator so a broken precondition reports as a setup
failure rather than as a confusing assertion error.

Identity threading: any ownership-gated or actor-resolved call uses
`make_partner_headers(...)` / `make_committee_member_headers(...)` /
`make_credit_arbiter_headers(...)` with the real partner id.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from . import factories as f
from .test_users import (
    make_committee_member_headers,
    make_credit_arbiter_headers,
    make_cycle_admin_headers,
    make_partner_headers,
)

ADMIN = make_cycle_admin_headers()


# ─── Primitive builders ───────────────────────────────


def set_clock(api=None, to_iso8601: str = DEFAULT_CLOCK_ISO) -> None:
    """Move the logical clock. Every fixture below assumes the startup value
    2026-08-01T00:00:00Z unless a caller moves it."""
    api = api or api_client
    get_success_data(api.set_clock(f.clock_payload(to_iso8601), ADMIN))


def create_cycle(api=None, **overrides) -> dict:
    api = api or api_client
    return get_success_data(api.create_cycle(f.create_cycle_payload(**overrides), ADMIN))


def create_partner(api=None, **overrides) -> dict:
    api = api or api_client
    return get_success_data(api.create_partner(f.create_partner_payload(**overrides), ADMIN))


def create_committee_member(api=None, full_name="Cass Committee", **overrides) -> dict:
    """A committee member who votes but is not scored this year."""
    defaults = {
        "full_name": full_name,
        "compensation_model": "FORMULA",
        "is_committee_member": True,
        "evaluation_required": False,
    }
    defaults.update(overrides)
    return create_partner(api, **defaults)


def create_credit_arbiter(api=None, full_name="Arya Arbiter", **overrides) -> dict:
    defaults = {
        "full_name": full_name,
        "compensation_model": "FORMULA",
        "is_credit_arbiter": True,
        "evaluation_required": False,
    }
    defaults.update(overrides)
    return create_partner(api, **defaults)


def create_matter(api=None, billing_attorney_id=None, responsible_attorney_id=None, **overrides) -> dict:
    api = api or api_client
    payload = f.create_matter_payload(
        billing_attorney_id=billing_attorney_id,
        responsible_attorney_id=responsible_attorney_id or billing_attorney_id,
        **overrides,
    )
    return get_success_data(api.create_matter(payload, ADMIN))


# ─── Fresh reads (also the OCC version source) ────────


def read_cycle(api=None, cycle_id=None) -> dict:
    api = api or api_client
    return get_success_data(api.get_cycle(cycle_id, ADMIN))


def read_partner(api=None, partner_id=None) -> dict:
    api = api or api_client
    return get_success_data(api.get_partner(partner_id, ADMIN))


def read_matter(api=None, matter_id=None) -> dict:
    api = api or api_client
    return get_success_data(api.get_matter(matter_id, ADMIN))


def read_award(api=None, award_id=None) -> dict:
    api = api or api_client
    return get_success_data(api.get_award(award_id, ADMIN))


def read_claim(api=None, claim_id=None) -> dict:
    api = api or api_client
    return get_success_data(api.get_credit_claim(claim_id, ADMIN))


def read_assessment(api=None, assessment_id=None) -> dict:
    api = api or api_client
    return get_success_data(api.get_self_assessment(assessment_id, ADMIN))


def read_transition(api=None, transition_id=None) -> dict:
    api = api or api_client
    return get_success_data(api.get_credit_transition(transition_id, ADMIN))


def matter_version(api=None, matter_id=None) -> int:
    return read_matter(api, matter_id)["version"]


def cycle_version(api=None, cycle_id=None) -> int:
    return read_cycle(api, cycle_id)["version"]


def partner_version(api=None, partner_id=None) -> int:
    return read_partner(api, partner_id)["version"]


# ─── Matter economics ─────────────────────────────────


def post_financials(
    api=None,
    matter_id=None,
    billed_delta_cents=0,
    collected_delta_cents=0,
    direct_cost_delta_cents=0,
    expected_matter_version=None,
) -> dict:
    """Apply signed billing, collection and direct-cost deltas. Reads the
    matter's current version when the caller does not pin one."""
    api = api or api_client
    if expected_matter_version is None:
        expected_matter_version = matter_version(api, matter_id)
    payload = f.matter_financials_payload(
        expected_matter_version,
        billed_delta_cents=billed_delta_cents,
        collected_delta_cents=collected_delta_cents,
        direct_cost_delta_cents=direct_cost_delta_cents,
    )
    return get_success_data(api.post_matter_financials(matter_id, payload, ADMIN))


def set_matter_status(api=None, matter_id=None, target_state=None, **overrides) -> dict:
    api = api or api_client
    payload = f.matter_status_payload(target_state, **overrides)
    return get_success_data(api.set_matter_status(matter_id, payload, ADMIN))


# ─── Contribution records ─────────────────────────────


def create_billable_record(
    api=None,
    partner_id=None,
    cycle_id=None,
    matter_id=None,
    hours=10.00,
    standard_rate_cents=50000,
    service_period_start="2026-01-15",
    service_period_end="2026-06-30",
    headers=None,
) -> dict:
    api = api or api_client
    payload = f.create_contribution_record_payload(
        partner_id=partner_id,
        cycle_id=cycle_id,
        matter_id=matter_id,
        kind="BILLABLE",
        category="CLIENT_WORK",
        hours=hours,
        standard_rate_cents=standard_rate_cents,
        service_period_start=service_period_start,
        service_period_end=service_period_end,
    )
    return get_success_data(api.create_contribution_record(payload, headers or ADMIN))


def create_non_billable_record(
    api=None,
    partner_id=None,
    cycle_id=None,
    category="FIRM_MANAGEMENT",
    hours=40.00,
    service_period_start="2026-02-01",
    service_period_end="2026-02-28",
    headers=None,
) -> dict:
    api = api or api_client
    payload = f.create_contribution_record_payload(
        partner_id=partner_id,
        cycle_id=cycle_id,
        kind="NON_BILLABLE",
        category=category,
        hours=hours,
        standard_rate_cents=0,
        service_period_start=service_period_start,
        service_period_end=service_period_end,
    )
    payload.pop("matter_id", None)
    return get_success_data(api.create_contribution_record(payload, headers or ADMIN))


def verify_record(api=None, record_id=None) -> dict:
    api = api or api_client
    return get_success_data(api.verify_contribution_record(record_id, {}, ADMIN))


def create_verified_billable_hours(api=None, partner_id=None, cycle_id=None, matter_id=None, **overrides) -> dict:
    """Book billable hours against a matter and verify them, which admits them
    to the scoring input sets and derives the WORKING allocation."""
    record = create_billable_record(
        api, partner_id=partner_id, cycle_id=cycle_id, matter_id=matter_id, **overrides
    )
    verify_record(api, record["id"])
    return record


def create_verified_non_billable_hours(api=None, partner_id=None, cycle_id=None, **overrides) -> dict:
    record = create_non_billable_record(api, partner_id=partner_id, cycle_id=cycle_id, **overrides)
    verify_record(api, record["id"])
    return record


# ─── Cycle staging ────────────────────────────────────


def advance_cycle(api=None, cycle_id=None, target_state=None) -> dict:
    api = api or api_client
    return get_success_data(
        api.advance_cycle(cycle_id, f.advance_cycle_payload(target_state), ADMIN)
    )


STAGE_ORDER = [
    "OPEN_INTAKE",
    "SELF_ASSESSMENT",
    "PEER_REVIEW",
    "DELIBERATION",
    "AWARDS_PUBLISHED",
    "TRUE_UP_OPEN",
    "CLOSED",
]


def advance_cycle_to(api=None, cycle_id=None, target_state=None) -> dict:
    """Walk the cycle stage machine forward one adjacent edge at a time."""
    cycle = read_cycle(api, cycle_id)
    start = STAGE_ORDER.index(cycle["state"])
    stop = STAGE_ORDER.index(target_state)
    for stage in STAGE_ORDER[start + 1 : stop + 1]:
        cycle = advance_cycle(api, cycle_id, stage)
    return cycle


# ─── Origination credit ───────────────────────────────


def file_claim(
    api=None,
    cycle_id=None,
    matter_id=None,
    claimant_id=None,
    claim_basis="NEW_CLIENT",
    requested_pct=100.00,
    narrative="I introduced this client to the firm and led the pitch.",
) -> dict:
    api = api or api_client
    payload = f.create_credit_claim_payload(
        cycle_id=cycle_id,
        matter_id=matter_id,
        claim_basis=claim_basis,
        requested_pct=requested_pct,
        narrative=narrative,
    )
    return get_success_data(
        api.create_credit_claim(payload, make_partner_headers(claimant_id))
    )


def submit_claim(api=None, claim_id=None, claimant_id=None) -> dict:
    api = api or api_client
    return get_success_data(
        api.submit_credit_claim(claim_id, {}, make_partner_headers(claimant_id))
    )


def dispute_claim(api=None, claim_id=None, disputer_id=None, **overrides) -> dict:
    api = api or api_client
    payload = f.dispute_claim_payload(**overrides)
    return get_success_data(
        api.dispute_credit_claim(claim_id, payload, make_partner_headers(disputer_id))
    )


def adjudicate_claim(
    api=None,
    claim_id=None,
    arbiter_id=None,
    decision="ALLOCATE",
    matter_id=None,
    expected_matter_version=None,
    **overrides,
) -> dict:
    api = api or api_client
    if expected_matter_version is None:
        expected_matter_version = matter_version(api, matter_id)
    payload = f.adjudicate_claim_payload(decision, expected_matter_version, **overrides)
    return get_success_data(
        api.adjudicate_credit_claim(claim_id, payload, make_credit_arbiter_headers(arbiter_id))
    )


def allocate_origination_credit(
    api=None,
    cycle_id=None,
    matter_id=None,
    claimant_id=None,
    arbiter_id=None,
    approved_pct=100.00,
    claim_basis="NEW_CLIENT",
    requested_pct=None,
) -> dict:
    """File, submit and allocate one origination claim. Returns the adjudicated
    claim. With a NEW_CLIENT basis the claimant keeps the whole approved_pct."""
    claim = file_claim(
        api,
        cycle_id=cycle_id,
        matter_id=matter_id,
        claimant_id=claimant_id,
        claim_basis=claim_basis,
        requested_pct=requested_pct if requested_pct is not None else approved_pct,
    )
    submit_claim(api, claim["id"], claimant_id)
    return adjudicate_claim(
        api,
        claim_id=claim["id"],
        arbiter_id=arbiter_id,
        decision="ALLOCATE",
        matter_id=matter_id,
        approved_pct=approved_pct,
    )


def matter_allocations(api=None, matter_id=None, **params) -> list:
    api = api or api_client
    body = get_success_data(api.list_matter_credit_allocations(matter_id, ADMIN, params or None))
    return body


def partner_allocations(api=None, partner_id=None, **params) -> list:
    api = api or api_client
    return get_success_data(api.list_partner_credit_allocations(partner_id, ADMIN, params or None))


# ─── Self-assessment and peer review ──────────────────


def create_assessment(api=None, cycle_id=None, partner_id=None, **overrides) -> dict:
    api = api or api_client
    payload = f.create_self_assessment_payload(cycle_id=cycle_id, **overrides)
    return get_success_data(
        api.create_self_assessment(payload, make_partner_headers(partner_id))
    )


def submit_assessment(api=None, assessment_id=None, partner_id=None) -> dict:
    api = api or api_client
    return get_success_data(
        api.submit_self_assessment(assessment_id, {}, make_partner_headers(partner_id))
    )


def assign_peer_review(api=None, assessment_id=None, reviewer_id=None) -> dict:
    api = api or api_client
    return get_success_data(
        api.create_peer_review(f.create_peer_review_payload(assessment_id, reviewer_id), ADMIN)
    )


def score_peer_review(api=None, review_id=None, reviewer_id=None, technical=4, collaboration=4, client_service=4, **overrides) -> dict:
    api = api or api_client
    payload = f.peer_review_score_payload(technical, collaboration, client_service, **overrides)
    return get_success_data(
        api.decide_peer_review(review_id, payload, make_partner_headers(reviewer_id))
    )


def accept_assessment(api=None, assessment_id=None, committee_member_id=None) -> dict:
    api = api or api_client
    return get_success_data(
        api.review_decision_self_assessment(
            assessment_id,
            f.review_decision_payload("ACCEPT"),
            make_committee_member_headers(committee_member_id),
        )
    )


def setup_accepted_assessment(
    api=None,
    cycle_id=None,
    subject_id=None,
    reviewer_ids=None,
    decider_id=None,
    scores=((4, 4, 4), (4, 4, 4)),
) -> dict:
    """Assessment created, submitted, scored by two reviewers and accepted.
    Returns {"assessment": ..., "reviews": [...]}. The cycle must be in
    SELF_ASSESSMENT."""
    assessment = create_assessment(api, cycle_id=cycle_id, partner_id=subject_id)
    submit_assessment(api, assessment["id"], subject_id)
    reviews = []
    for reviewer_id, score in zip(reviewer_ids, scores):
        review = assign_peer_review(api, assessment["id"], reviewer_id)
        reviews.append(score_peer_review(api, review["id"], reviewer_id, *score))
    accepted = accept_assessment(
        api, assessment["id"], decider_id or reviewer_ids[0]
    )
    return {"assessment": accepted, "reviews": reviews}


# ─── Committee deliberation ───────────────────────────


def find_ballot(api=None, cycle_id=None, subject_partner_id=None, committee_member_id=None) -> dict:
    api = api or api_client
    params = {
        "cycle_id": cycle_id,
        "subject_partner_id": subject_partner_id,
        "committee_member_id": committee_member_id,
    }
    rows = get_success_data(api.list_ballots(ADMIN, params))
    assert len(rows) == 1, (
        f"Expected exactly one ballot for subject {subject_partner_id} and member "
        f"{committee_member_id}, found {len(rows)}"
    )
    return rows[0]


def cast_ballot(api=None, ballot_id=None, committee_member_id=None, points_proposed=800.00, cycle_id=None, expected_cycle_version=None, **overrides) -> dict:
    """Cast one ballot. Every accepted decision advances the cycle's version, so
    the current version is re-read unless the caller pins one."""
    api = api or api_client
    if expected_cycle_version is None:
        expected_cycle_version = cycle_version(api, cycle_id)
    payload = f.cast_ballot_payload(points_proposed, expected_cycle_version, **overrides)
    return get_success_data(
        api.cast_ballot(ballot_id, payload, make_committee_member_headers(committee_member_id))
    )


def setup_deliberation_cycle(
    api=None,
    cycle_overrides=None,
    subject_overrides=None,
    committee_count=2,
) -> dict:
    """Cycle in DELIBERATION with one DISCRETIONARY subject partner whose
    assessment is ACCEPTED and `committee_count` committee members, so the
    subject's PENDING ballots already exist.

    Returns {"cycle", "subject", "committee", "assessment", "ballots"}.
    """
    api = api or api_client
    cycle = create_cycle(api, **(cycle_overrides or {}))
    subject_defaults = {
        "full_name": "Dana Discretion",
        "compensation_model": "DISCRETIONARY",
        "practice_group": "LITIGATION",
    }
    subject_defaults.update(subject_overrides or {})
    subject = create_partner(api, **subject_defaults)
    committee = [
        create_committee_member(api, full_name=f"Cass Committee {n + 1}")
        for n in range(committee_count)
    ]
    advance_cycle(api, cycle["id"], "SELF_ASSESSMENT")
    bundle = setup_accepted_assessment(
        api,
        cycle_id=cycle["id"],
        subject_id=subject["id"],
        reviewer_ids=[member["id"] for member in committee[:2]],
    )
    advance_cycle(api, cycle["id"], "PEER_REVIEW")
    cycle = advance_cycle(api, cycle["id"], "DELIBERATION")
    ballots = [
        find_ballot(api, cycle["id"], subject["id"], member["id"]) for member in committee
    ]
    return {
        "cycle": cycle,
        "subject": subject,
        "committee": committee,
        "assessment": bundle["assessment"],
        "reviews": bundle["reviews"],
        "ballots": ballots,
    }


def setup_published_discretionary_award(
    api=None,
    points=(800.00, 600.00),
    cycle_overrides=None,
    subject_overrides=None,
) -> dict:
    """The deliberation cycle above, with every ballot cast and the cycle
    advanced to AWARDS_PUBLISHED. Returns the deliberation bundle plus
    {"award": ...}.

    With the default parameters the subject's committee_points are the plain
    mean 700.00, the discretionary pool is 20,000,000 cents, target_award_cents
    is 20,000,000 and draw_schedule_monthly_cents is 1,333,333.
    """
    api = api or api_client
    bundle = setup_deliberation_cycle(
        api, cycle_overrides=cycle_overrides, subject_overrides=subject_overrides
    )
    for ballot, member, proposal in zip(bundle["ballots"], bundle["committee"], points):
        cast_ballot(
            api,
            ballot_id=ballot["id"],
            committee_member_id=member["id"],
            points_proposed=proposal,
            cycle_id=bundle["cycle"]["id"],
        )
    bundle["cycle"] = advance_cycle(api, bundle["cycle"]["id"], "AWARDS_PUBLISHED")
    bundle["award"] = find_award(api, bundle["cycle"]["id"], bundle["subject"]["id"])
    return bundle


def find_award(api=None, cycle_id=None, partner_id=None) -> dict:
    api = api or api_client
    rows = get_success_data(
        api.list_awards(ADMIN, {"cycle_id": cycle_id, "partner_id": partner_id})
    )
    assert len(rows) == 1, (
        f"Expected exactly one award for partner {partner_id} in cycle {cycle_id}, "
        f"found {len(rows)}"
    )
    return rows[0]


# ─── Draws, true-up and closure ───────────────────────


def pay_draw(api=None, award_id=None, period_year=2026, period_month=1) -> dict:
    api = api or api_client
    return get_success_data(
        api.draw_run(award_id, f.draw_run_payload(period_year, period_month), ADMIN)
    )


def true_up_award(api=None, award_id=None) -> dict:
    api = api or api_client
    return get_success_data(api.true_up(award_id, {}, ADMIN))


def draw_ledger(api=None, award_id=None, **params) -> list:
    api = api or api_client
    return get_success_data(api.list_draw_payments(award_id, ADMIN, params or None))


def contribute_capital(api=None, partner_id=None, amount_cents=0, expected_partner_version=None) -> dict:
    api = api or api_client
    if expected_partner_version is None:
        expected_partner_version = partner_version(api, partner_id)
    return get_success_data(
        api.capital_contribution(
            partner_id, f.capital_contribution_payload(amount_cents, expected_partner_version), ADMIN
        )
    )


def setup_drawn_award(
    api=None,
    periods=((2026, 1), (2026, 2)),
    points=(800.00, 600.00),
    cycle_overrides=None,
    subject_overrides=None,
) -> dict:
    """A published discretionary award with one scheduled draw per period paid,
    leaving the award in payment state DRAWING."""
    api = api or api_client
    bundle = setup_published_discretionary_award(
        api, points=points, cycle_overrides=cycle_overrides, subject_overrides=subject_overrides
    )
    for period_year, period_month in periods:
        bundle["award"] = pay_draw(
            api, bundle["award"]["id"], period_year=period_year, period_month=period_month
        )
    return bundle


def setup_trued_up_award(
    api=None,
    periods=((2026, 1), (2026, 2)),
    points=(800.00, 600.00),
    cycle_overrides=None,
    subject_overrides=None,
) -> dict:
    """A drawn award, with the cycle moved to TRUE_UP_OPEN and the award
    trued up."""
    api = api or api_client
    bundle = setup_drawn_award(
        api,
        periods=periods,
        points=points,
        cycle_overrides=cycle_overrides,
        subject_overrides=subject_overrides,
    )
    bundle["cycle"] = advance_cycle(api, bundle["cycle"]["id"], "TRUE_UP_OPEN")
    bundle["award"] = true_up_award(api, bundle["award"]["id"])
    return bundle


# ─── Formula-model scoring scenarios ──────────────────


def setup_formula_matter(
    api=None,
    billed_delta_cents=10_000_000,
    collected_delta_cents=8_500_000,
    direct_cost_delta_cents=1_000_000,
    verified_hours=None,
    partner_overrides=None,
    matter_overrides=None,
    cycle_overrides=None,
) -> dict:
    """One cycle, one FORMULA partner who is both billing and responsible
    attorney of one OPEN matter, that matter's financial deltas posted, and
    optionally `verified_hours` of verified billable time on it.

    Returns {"cycle", "partner", "matter", "record"}.
    """
    api = api or api_client
    cycle = create_cycle(api, **(cycle_overrides or {}))
    partner_defaults = {"full_name": "Ada Origin", "compensation_model": "FORMULA"}
    partner_defaults.update(partner_overrides or {})
    partner = create_partner(api, **partner_defaults)
    matter = create_matter(
        api,
        billing_attorney_id=partner["id"],
        responsible_attorney_id=partner["id"],
        **(matter_overrides or {}),
    )
    post_financials(
        api,
        matter["id"],
        billed_delta_cents=billed_delta_cents,
        collected_delta_cents=collected_delta_cents,
        direct_cost_delta_cents=direct_cost_delta_cents,
    )
    record = None
    if verified_hours:
        record = create_verified_billable_hours(
            api,
            partner_id=partner["id"],
            cycle_id=cycle["id"],
            matter_id=matter["id"],
            hours=verified_hours,
        )
    return {
        "cycle": cycle,
        "partner": partner,
        "matter": read_matter(api, matter["id"]),
        "record": record,
    }


def setup_split_adjudicated_matter(
    api=None,
    billed_delta_cents=200_020,
    collected_delta_cents=100_010,
    direct_cost_delta_cents=0,
    verified_hours=5.00,
    approved_pct=50.00,
    counterparty_pct=50.00,
    client_key="CLI-R1",
    client_display_name="Rounding Industries",
    cycle_overrides=None,
) -> dict:
    """One matter whose origination credit was split between a claimant and a
    disputer, with the claimant also holding BILLING, RESPONSIBLE and a
    WORKING allocation derived from verified billable hours.

    Returns {"cycle", "claimant", "disputer", "arbiter", "matter", "claim"}.
    """
    api = api or api_client
    cycle = create_cycle(api, **(cycle_overrides or {}))
    claimant = create_partner(api, full_name="Ada Origin", compensation_model="FORMULA")
    disputer = create_partner(
        api, full_name="Ben Counter", compensation_model="FORMULA", admission_year=2011
    )
    arbiter = create_credit_arbiter(api, full_name="Rex Arbiter", practice_group="REGULATORY")
    matter = create_matter(
        api,
        billing_attorney_id=claimant["id"],
        responsible_attorney_id=claimant["id"],
        client_key=client_key,
        client_display_name=client_display_name,
    )
    post_financials(
        api,
        matter["id"],
        billed_delta_cents=billed_delta_cents,
        collected_delta_cents=collected_delta_cents,
        direct_cost_delta_cents=direct_cost_delta_cents,
    )
    if verified_hours:
        create_verified_billable_hours(
            api,
            partner_id=claimant["id"],
            cycle_id=cycle["id"],
            matter_id=matter["id"],
            hours=verified_hours,
            service_period_start="2026-02-01",
            service_period_end="2026-02-28",
        )
    claim = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=claimant["id"],
        claim_basis="NEW_CLIENT",
        requested_pct=100.00,
    )
    submit_claim(api, claim["id"], claimant["id"])
    dispute_claim(
        api,
        claim["id"],
        disputer["id"],
        contested_pct=counterparty_pct,
        dispute_grounds="Introduction came from my existing relationship.",
    )
    claim = adjudicate_claim(
        api,
        claim_id=claim["id"],
        arbiter_id=arbiter["id"],
        decision="SPLIT",
        matter_id=matter["id"],
        approved_pct=approved_pct,
        counterparty_pct=counterparty_pct,
    )
    return {
        "cycle": cycle,
        "claimant": claimant,
        "disputer": disputer,
        "arbiter": arbiter,
        "matter": read_matter(api, matter["id"]),
        "claim": claim,
    }


def setup_disputed_claim(
    api=None,
    remands=0,
    cycle_overrides=None,
    client_key="CLI-L1",
    client_display_name="Loop Logistics",
) -> dict:
    """A claim sitting in DISPUTED, having been remanded `remands` times first
    (each remand is followed by a re-submit and a re-dispute).

    Returns {"cycle", "claimant", "disputer", "arbiter", "matter", "claim"}.
    """
    api = api or api_client
    cycle = create_cycle(api, **(cycle_overrides or {}))
    claimant = create_partner(api, full_name="Ada Origin", compensation_model="FORMULA")
    disputer = create_partner(
        api, full_name="Ben Counter", compensation_model="FORMULA", admission_year=2011
    )
    arbiter = create_credit_arbiter(api, full_name="Rex Arbiter", practice_group="REGULATORY")
    matter = create_matter(
        api,
        billing_attorney_id=claimant["id"],
        responsible_attorney_id=claimant["id"],
        client_key=client_key,
        client_display_name=client_display_name,
    )
    claim = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=claimant["id"],
        claim_basis="NEW_CLIENT",
        requested_pct=100.00,
        narrative="First contact and pitch were mine.",
    )
    submit_claim(api, claim["id"], claimant["id"])
    dispute_claim(
        api,
        claim["id"],
        disputer["id"],
        contested_pct=50.00,
        dispute_grounds="The client was already mine.",
    )
    for round_number in range(remands):
        adjudicate_claim(
            api,
            claim_id=claim["id"],
            arbiter_id=arbiter["id"],
            decision="REMAND",
            matter_id=matter["id"],
            remand_reason=f"Provide more detail, round {round_number + 1}.",
        )
        submit_claim(api, claim["id"], claimant["id"])
        dispute_claim(
            api,
            claim["id"],
            disputer["id"],
            contested_pct=50.00,
            dispute_grounds="Unchanged position.",
        )
    return {
        "cycle": cycle,
        "claimant": claimant,
        "disputer": disputer,
        "arbiter": arbiter,
        "matter": read_matter(api, matter["id"]),
        "claim": read_claim(api, claim["id"]),
    }


# ─── Departure and credit transitions ─────────────────


def setup_proposed_transition(
    api=None,
    departure_effective_on="2026-12-31",
    cycle_overrides=None,
    matter_overrides=None,
) -> dict:
    """A departing partner holding 100.00 percent ORIGINATING credit on one
    OPEN matter, with notice recorded so exactly one credit transition sits in
    PROPOSED, plus an eligible ACTIVE successor.

    Returns {"cycle", "departing", "successor", "arbiter", "matter",
    "claim", "transition"}.
    """
    api = api or api_client
    cycle = create_cycle(api, **(cycle_overrides or {}))
    departing = create_partner(
        api, full_name="Dev Departing", compensation_model="FORMULA", evaluation_required=False
    )
    successor = create_partner(
        api,
        full_name="Sam Successor",
        compensation_model="FORMULA",
        practice_group="TAX",
        evaluation_required=False,
    )
    arbiter = create_credit_arbiter(api)
    matter = create_matter(
        api,
        billing_attorney_id=departing["id"],
        responsible_attorney_id=departing["id"],
        **(matter_overrides or {}),
    )
    claim = allocate_origination_credit(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=departing["id"],
        arbiter_id=arbiter["id"],
        approved_pct=100.00,
    )
    get_success_data(
        api.notice_of_departure(
            departing["id"], f.notice_of_departure_payload(departure_effective_on), ADMIN
        )
    )
    transitions = get_success_data(
        api.list_credit_transitions(ADMIN, {"departing_partner_id": departing["id"]})
    )
    assert len(transitions) == 1, (
        f"Expected exactly one staged credit transition, found {len(transitions)}"
    )
    return {
        "cycle": cycle,
        "departing": departing,
        "successor": successor,
        "arbiter": arbiter,
        "matter": read_matter(api, matter["id"]),
        "claim": claim,
        "transition": transitions[0],
    }


def effectuate_transition(
    api=None,
    transition_id=None,
    successor_partner_id=None,
    effective_on="2026-12-31",
    matter_id=None,
    expected_matter_version=None,
) -> dict:
    api = api or api_client
    if expected_matter_version is None:
        expected_matter_version = matter_version(api, matter_id)
    return get_success_data(
        api.effectuate_credit_transition(
            transition_id,
            f.effectuate_transition_payload(
                successor_partner_id, effective_on, expected_matter_version
            ),
            ADMIN,
        )
    )


def void_transition(
    api=None,
    transition_id=None,
    void_reason="The successor declined the relationship.",
    matter_id=None,
    expected_matter_version=None,
) -> dict:
    api = api or api_client
    if expected_matter_version is None:
        expected_matter_version = matter_version(api, matter_id)
    return get_success_data(
        api.void_credit_transition(
            transition_id,
            f.void_transition_payload(void_reason, expected_matter_version),
            ADMIN,
        )
    )
