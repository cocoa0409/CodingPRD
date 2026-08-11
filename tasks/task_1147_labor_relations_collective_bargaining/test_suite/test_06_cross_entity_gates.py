"""Cross-entity state dependency tests (difficulty rule 7): agreement
bargainable gate on proposal tender and the vote-open scenario/package gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_draft_agreement,
    create_employer_proposal_on_table,
    create_locked_scenario,
    create_proposal_payload,
    create_ratification_vote_payload,
    create_union,
    get_success_data,
    make_union_representative_headers,
    validate_error,
)

ADMIN = TEST_USERS["lr_admin_headers"]
NEG1 = TEST_USERS["negotiator_headers"]
NEG2 = TEST_USERS["negotiator_2_headers"]
CHIEF = TEST_USERS["chief_negotiator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / proposal_tender_agreement_gate
# ---------------------------------------------------------------------------

def _setup_active_and_expired_agreements(api):
    union_a = create_union(name="Union MA")
    aa = create_draft_agreement(
        union_a["id"],
        title="CBA MA",
        effective_date="2026-01-01T00:00:00Z",
        expiration_date="2029-05-31T00:00:00Z",
        headcount_baseline=50,
        fte_projected=60,
        avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    get_success_data(api.activate_agreement(aa["id"], ADMIN))
    pa = get_success_data(
        api.create_proposal(
            create_proposal_payload(
                agreement_id=aa["id"],
                side="EMPLOYER",
                title="Midterm ask",
                proposal_type="NON_ECONOMIC",
            ),
            NEG1,
        )
    )
    union_b = create_union(name="Union MB")
    ab = create_draft_agreement(
        union_b["id"],
        title="CBA MB",
        effective_date="2026-01-01T00:00:00Z",
        expiration_date="2026-06-30T00:00:00Z",
        headcount_baseline=50,
        fte_projected=60,
        avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    get_success_data(api.activate_agreement(ab["id"], ADMIN))
    # Sweep AB to EXPIRED.
    get_success_data(api.set_clock("2026-07-01T00:00:00Z", ADMIN))
    pb = get_success_data(
        api.create_proposal(
            create_proposal_payload(
                agreement_id=ab["id"],
                side="EMPLOYER",
                title="Post-expiry ask",
                proposal_type="NON_ECONOMIC",
            ),
            NEG1,
        )
    )
    return union_a, aa, pa, union_b, ab, pb


def test_tender_rejected_when_agreement_active_open_posture(api):
    """PRD §2.6: "An agreement is **bargainable** when its `status` is `DRAFT`,
    `EXPIRED`, or `EXTENDED`, or when its `posture` is `SUNSET` or `CRITICAL`.
    Tendering a proposal or scheduling a session against a non-bargainable
    agreement is rejected with `ERR_AGREEMENT_NOT_BARGAINABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/proposal_tender_agreement_gate
    """
    _, aa, pa, _, _, _ = _setup_active_and_expired_agreements(api)
    resp = api.transition_proposal(pa["id"], {"to_status": "TENDERED"}, CHIEF)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_BARGAINABLE)


def test_tender_accepted_when_agreement_expired(api):
    """PRD §2.6: "An agreement is **bargainable** when its `status` is `DRAFT`,
    `EXPIRED`, or `EXTENDED`, or when its `posture` is `SUNSET` or `CRITICAL`."

    Design: Difficulty/cross_entity_state_dependency/proposal_tender_agreement_gate
    """
    _, _, _, _, ab, pb = _setup_active_and_expired_agreements(api)
    ab_after = get_success_data(api.get_agreement(ab["id"], NEG1))
    assert ab_after["status"] == "EXPIRED", "sweep must have expired AB"
    tendered = get_success_data(api.transition_proposal(pb["id"], {"to_status": "TENDERED"}, CHIEF))
    assert tendered["status"] == "TENDERED"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / vote_open_scenario_package_gates
# ---------------------------------------------------------------------------

def test_vote_open_gates_fire_in_order(api):
    """PRD §3.6: "a `LOCKED` costing scenario must exist for the vote's
    agreement (otherwise `ERR_NO_LOCKED_SCENARIO`); at least one proposal of
    that agreement must be `ACCEPTED` (otherwise `ERR_NO_ACCEPTED_PACKAGE`,
    which is checked only after the locked-scenario gate passes)"

    Design: Difficulty/cross_entity_state_dependency/vote_open_scenario_package_gates
    """
    union = create_union(name="Union N")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA N",
        headcount_baseline=100,
        fte_projected=120,
        avg_loaded_wage_cents=5000,
        costing_envelope_cents=1_000_000_000_000,
    )
    vote = get_success_data(
        api.create_ratification_vote(
            create_ratification_vote_payload(
                agreement_id=agreement["id"],
                eligible_voter_count=10,
                ballot_close_at="2026-06-01T00:00:00Z",
            ),
            CHIEF,
        )
    )
    # Gate 1: no LOCKED scenario exists.
    resp1 = api.transition_ratification_vote(vote["id"], {"to_status": "OPEN"}, CHIEF)
    validate_error(resp1, ApiErrorId.ERR_NO_LOCKED_SCENARIO)

    # Build a LOCKED scenario over an ON_TABLE (never ACCEPTED) proposal.
    proposal = create_employer_proposal_on_table(
        agreement["id"], union["id"], title="Allowance",
        proposal_type="ECONOMIC", recurring_annual_cost_cents=100,
    )
    create_locked_scenario(agreement["id"], [proposal["id"]], scenario_mode="FINAL", term_years=3)

    # Gate 2: locked scenario exists but no ACCEPTED package.
    resp2 = api.transition_ratification_vote(vote["id"], {"to_status": "OPEN"}, CHIEF)
    validate_error(resp2, ApiErrorId.ERR_NO_ACCEPTED_PACKAGE)


def test_vote_open_failed_attempts_leave_vote_scheduled(api):
    """PRD §3.6: "Opening the vote is a gated transition. The vote must be
    `SCHEDULED`; a `LOCKED` costing scenario must exist for the vote's
    agreement (otherwise `ERR_NO_LOCKED_SCENARIO`); at least one proposal of
    that agreement must be `ACCEPTED` (otherwise `ERR_NO_ACCEPTED_PACKAGE`,
    which is checked only after the locked-scenario gate passes)"

    Design: Difficulty/cross_entity_state_dependency/vote_open_scenario_package_gates
    """
    union = create_union(name="Union N")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA N",
        headcount_baseline=100,
        fte_projected=120,
        avg_loaded_wage_cents=5000,
        costing_envelope_cents=1_000_000_000_000,
    )
    vote = get_success_data(
        api.create_ratification_vote(
            create_ratification_vote_payload(
                agreement_id=agreement["id"],
                eligible_voter_count=10,
                ballot_close_at="2026-06-01T00:00:00Z",
            ),
            CHIEF,
        )
    )
    api.transition_ratification_vote(vote["id"], {"to_status": "OPEN"}, CHIEF)
    proposal = create_employer_proposal_on_table(
        agreement["id"], union["id"], title="Allowance",
        proposal_type="ECONOMIC", recurring_annual_cost_cents=100,
    )
    create_locked_scenario(agreement["id"], [proposal["id"]], scenario_mode="FINAL", term_years=3)
    api.transition_ratification_vote(vote["id"], {"to_status": "OPEN"}, CHIEF)
    vote_after = get_success_data(api.get_ratification_vote(vote["id"], NEG1))
    assert vote_after["status"] == "SCHEDULED", "both failed opens leave the vote SCHEDULED"
