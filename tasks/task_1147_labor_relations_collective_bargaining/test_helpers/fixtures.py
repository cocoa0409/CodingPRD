"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared
endpoints; the harness restarts the server before every test, so no state
carries over between tests.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agreement_payload,
    create_clause_payload,
    create_costing_scenario_payload,
    create_information_request_payload,
    create_past_practice_payload,
    create_proposal_payload,
    create_ratification_vote_payload,
    create_session_payload,
    create_side_letter_payload,
    create_union_payload,
)
from .test_users import (
    TEST_USERS,
    make_chief_negotiator_headers,
    make_legal_counsel_headers,
    make_lr_manager_headers,
    make_negotiator_headers,
    make_union_representative_headers,
)

ADMIN = TEST_USERS["lr_admin_headers"]
MGR = TEST_USERS["lr_manager_headers"]
NEG1 = TEST_USERS["negotiator_headers"]
NEG2 = TEST_USERS["negotiator_2_headers"]
CHIEF = TEST_USERS["chief_negotiator_headers"]
LC = TEST_USERS["legal_counsel_headers"]


# ---------------------------------------------------------------------------
# Tier 1: base entities
# ---------------------------------------------------------------------------

def create_union(name="Union", union_code=None):
    payload = create_union_payload(name=name)
    if union_code is not None:
        payload["union_code"] = union_code
    resp = api_client.create_union(payload, ADMIN)
    return get_success_data(resp)


def create_draft_agreement(union_id, **overrides):
    payload = create_agreement_payload(union_id=union_id, **overrides)
    resp = api_client.create_agreement(payload, ADMIN)
    return get_success_data(resp)


def create_active_agreement(union_id, **overrides):
    agreement = create_draft_agreement(union_id, **overrides)
    resp = api_client.activate_agreement(agreement["id"], ADMIN)
    return get_success_data(resp)


def create_clause(agreement_id, **overrides):
    payload = create_clause_payload(agreement_id=agreement_id, **overrides)
    resp = api_client.create_clause(payload, MGR)
    return get_success_data(resp)


def create_session(agreement_id, **overrides):
    payload = create_session_payload(agreement_id=agreement_id, **overrides)
    resp = api_client.create_session(payload, NEG1)
    return get_success_data(resp)


def get_agreement(agreement_id):
    return get_success_data(api_client.get_agreement(agreement_id, NEG1))


def get_agreement_version(agreement_id) -> int:
    return get_agreement(agreement_id)["version"]


def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: proposals walked to ON_TABLE
# ---------------------------------------------------------------------------

def create_employer_proposal_on_table(agreement_id, union_id, **overrides):
    """EMPLOYER proposal walked DRAFT -> TENDERED -> ON_TABLE."""
    payload = create_proposal_payload(agreement_id=agreement_id, side="EMPLOYER", **overrides)
    proposal = get_success_data(api_client.create_proposal(payload, NEG1))
    get_success_data(api_client.transition_proposal(proposal["id"], {"to_status": "TENDERED"}, CHIEF))
    on_table = get_success_data(
        api_client.transition_proposal(
            proposal["id"], {"to_status": "ON_TABLE"}, make_union_representative_headers(union_id)
        )
    )
    return on_table


def create_union_proposal_on_table(agreement_id, union_id, **overrides):
    """UNION proposal walked DRAFT -> TENDERED -> ON_TABLE."""
    payload = create_proposal_payload(agreement_id=agreement_id, side="UNION", **overrides)
    proposal = get_success_data(
        api_client.create_proposal(payload, make_union_representative_headers(union_id))
    )
    get_success_data(
        api_client.transition_proposal(
            proposal["id"], {"to_status": "TENDERED"}, make_union_representative_headers(union_id)
        )
    )
    on_table = get_success_data(
        api_client.transition_proposal(proposal["id"], {"to_status": "ON_TABLE"}, CHIEF)
    )
    return on_table


# ---------------------------------------------------------------------------
# Tier 3: costing scenario lifecycle
# ---------------------------------------------------------------------------

def create_computed_scenario(agreement_id, proposal_ids, **overrides):
    """Scenario created and moved DRAFT -> COMPUTED (computed by neg-1)."""
    payload = create_costing_scenario_payload(
        agreement_id=agreement_id, proposal_ids=proposal_ids, **overrides
    )
    scenario = get_success_data(api_client.create_costing_scenario(payload, NEG1))
    computed = get_success_data(
        api_client.transition_costing_scenario(scenario["id"], {"to_status": "COMPUTED"}, NEG1)
    )
    return computed


def create_reviewed_scenario(agreement_id, proposal_ids, **overrides):
    """Scenario moved DRAFT -> COMPUTED (neg-1) -> REVIEWED (neg-2)."""
    computed = create_computed_scenario(agreement_id, proposal_ids, **overrides)
    reviewed = get_success_data(
        api_client.transition_costing_scenario(computed["id"], {"to_status": "REVIEWED"}, NEG2)
    )
    return reviewed


def create_locked_scenario(agreement_id, proposal_ids, **overrides):
    """Scenario walked to LOCKED by chief-1 against the agreement's live version."""
    reviewed = create_reviewed_scenario(agreement_id, proposal_ids, **overrides)
    version = get_agreement_version(agreement_id)
    locked = get_success_data(
        api_client.lock_costing_scenario(
            reviewed["id"], {"expected_agreement_version": version}, CHIEF
        )
    )
    return locked


# ---------------------------------------------------------------------------
# Tier 4: accepted package / open vote
# ---------------------------------------------------------------------------

def setup_accepted_economic_package(
    union_name="Union",
    agreement_overrides=None,
    proposal_overrides=None,
    scenario_overrides=None,
):
    """Union + DRAFT agreement + ECONOMIC proposal ACCEPTED under a LOCKED scenario.

    Returns (union, agreement, proposal, scenario). After this call the
    proposal is ACCEPTED and the agreement envelope has been charged.
    """
    union = create_union(name=union_name)
    agreement = create_draft_agreement(union["id"], **(agreement_overrides or {}))
    proposal = create_employer_proposal_on_table(
        agreement["id"], union["id"], proposal_type="ECONOMIC", **(proposal_overrides or {})
    )
    scenario = create_locked_scenario(
        agreement["id"], [proposal["id"]], **(scenario_overrides or {})
    )
    accepted = get_success_data(
        api_client.transition_proposal(
            proposal["id"], {"to_status": "ACCEPTED"}, make_union_representative_headers(union["id"])
        )
    )
    return union, agreement, accepted, scenario


def setup_open_vote(union, agreement, ballot_close_at="2026-06-01T00:00:00Z", eligible_voter_count=10):
    """Create + OPEN a ratification vote (agreement must already have a LOCKED
    scenario and at least one ACCEPTED proposal)."""
    vote = get_success_data(
        api_client.create_ratification_vote(
            create_ratification_vote_payload(
                agreement_id=agreement["id"],
                eligible_voter_count=eligible_voter_count,
                ballot_close_at=ballot_close_at,
            ),
            CHIEF,
        )
    )
    opened = get_success_data(
        api_client.transition_ratification_vote(vote["id"], {"to_status": "OPEN"}, CHIEF)
    )
    return opened


# ---------------------------------------------------------------------------
# Tier 5: interpretation workflow helpers
# ---------------------------------------------------------------------------

def create_interpreted_clause(agreement_id, **overrides):
    """Clause walked UNINTERPRETED -> UNDER_REVIEW -> INTERPRETED."""
    clause = create_clause(agreement_id, **overrides)
    get_success_data(api_client.interpret_clause(clause["id"], {"action": "OPEN_REVIEW"}, MGR))
    interpreted = get_success_data(
        api_client.interpret_clause(
            clause["id"], {"action": "RECORD", "interpretation_text": "Ruling text"}, LC
        )
    )
    return interpreted


def create_executed_side_letter(agreement_id, clause_id, **overrides):
    """Side letter drafted by mgr-1, moved to PENDING_LEGAL, EXECUTED by lc-1."""
    letter = get_success_data(
        api_client.create_side_letter(
            create_side_letter_payload(agreement_id=agreement_id, clause_id=clause_id, **overrides),
            MGR,
        )
    )
    get_success_data(api_client.transition_side_letter(letter["id"], {"to_status": "PENDING_LEGAL"}, MGR))
    executed = get_success_data(
        api_client.transition_side_letter(letter["id"], {"to_status": "EXECUTED"}, LC)
    )
    return executed


def create_verified_practice(union_id, **overrides):
    """Past practice walked ASSERTED -> DOCUMENTED -> VERIFIED."""
    practice = get_success_data(
        api_client.create_past_practice(create_past_practice_payload(union_id=union_id, **overrides), MGR)
    )
    get_success_data(api_client.transition_past_practice(practice["id"], {"to_status": "DOCUMENTED"}, MGR))
    verified = get_success_data(
        api_client.transition_past_practice(practice["id"], {"to_status": "VERIFIED"}, LC)
    )
    return verified
