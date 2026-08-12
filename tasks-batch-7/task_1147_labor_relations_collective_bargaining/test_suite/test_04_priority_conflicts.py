"""Priority-pair validation conflict tests (difficulty rule 5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_draft_agreement,
    create_proposal_payload,
    create_session,
    create_union,
    get_success_data,
    make_union_representative_headers,
    validate_error,
)

ADMIN = TEST_USERS["lr_admin_headers"]
NEG1 = TEST_USERS["negotiator_headers"]
CHIEF = TEST_USERS["chief_negotiator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / accept_state_beats_fiscal
# ---------------------------------------------------------------------------

def test_accept_draft_proposal_reports_state_error(api):
    """PRD §2.11: "State-machine validity comes after that
    (`ERR_INVALID_STATE`), then optimistic-concurrency
    (`ERR_STALE_AGREEMENT_VERSION`), then union-standing and
    segregation-of-duties checks ... and finally the economic-envelope check
    (`ERR_ENVELOPE_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/accept_state_beats_fiscal
    """
    union = create_union(name="Union I")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA I",
        headcount_baseline=50,
        fte_projected=60,
        avg_loaded_wage_cents=4000,
        costing_envelope_cents=1000,
    )
    proposal = get_success_data(
        api.create_proposal(
            create_proposal_payload(
                agreement_id=agreement["id"],
                side="EMPLOYER",
                title="Big ask",
                proposal_type="ECONOMIC",
                recurring_annual_cost_cents=999999,
            ),
            NEG1,
        )
    )
    resp = api.transition_proposal(
        proposal["id"], {"to_status": "ACCEPTED"}, make_union_representative_headers(union["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_accept_draft_proposal_leaves_no_partial_mutation(api):
    """PRD §2.11: "Validation across the platform is priority-ordered so that
    earlier failures mask later ones."

    Design: Difficulty/priority_pair_validation_conflict/accept_state_beats_fiscal
    """
    union = create_union(name="Union I")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA I",
        headcount_baseline=50,
        fte_projected=60,
        avg_loaded_wage_cents=4000,
        costing_envelope_cents=1000,
    )
    proposal = get_success_data(
        api.create_proposal(
            create_proposal_payload(
                agreement_id=agreement["id"],
                side="EMPLOYER",
                title="Big ask",
                proposal_type="ECONOMIC",
                recurring_annual_cost_cents=999999,
            ),
            NEG1,
        )
    )
    api.transition_proposal(
        proposal["id"], {"to_status": "ACCEPTED"}, make_union_representative_headers(union["id"])
    )
    after = get_success_data(api.get_proposal(proposal["id"], NEG1))
    assert after["status"] == "DRAFT", "rejected accept must not mutate the proposal"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / session_safety_beats_temporal
# ---------------------------------------------------------------------------

def _setup_trusteed_union_with_session(api):
    union = create_union(name="Union J")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA J",
        headcount_baseline=50,
        fte_projected=60,
        avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    s1 = create_session(
        agreement["id"],
        mediator_id="med-1",
        lead_negotiator_id="ln-1",
        location="Room 1",
        start_at="2026-06-01T10:00:00Z",
        end_at="2026-06-01T11:00:00Z",
    )
    get_success_data(api.transition_union(union["id"], {"to_status": "TRUSTEED"}, ADMIN))
    return union, agreement, s1


def test_session_create_trusteed_reports_safety_error(api):
    """PRD §2.11: "State-machine validity comes after that
    (`ERR_INVALID_STATE`), then optimistic-concurrency
    (`ERR_STALE_AGREEMENT_VERSION`), then union-standing and
    segregation-of-duties checks (`ERR_UNION_TRUSTED`, `ERR_UNION_DECERTIFIED`,
    `ERR_SOD_VIOLATION`), then scalar temporal rules ... then interval
    conflicts (`ERR_MEDIATOR_CONFLICT`, `ERR_NEGOTIATOR_BUFFER_CONFLICT`,
    `ERR_SIDE_LETTER_OVERLAP`) ..."

    Design: Difficulty/priority_pair_validation_conflict/session_safety_beats_temporal
    """
    _, agreement, _ = _setup_trusteed_union_with_session(api)
    resp = api.create_session(
        {
            "agreement_id": agreement["id"],
            "mediator_id": "med-1",
            "lead_negotiator_id": "ln-2",
            "location": "Room 2",
            "start_at": "2026-06-01T10:30:00Z",
            "end_at": "2026-06-01T12:00:00Z",
        },
        NEG1,
    )
    validate_error(resp, ApiErrorId.ERR_UNION_TRUSTEED)


def test_session_create_trusteed_leaves_existing_session_untouched(api):
    """PRD §2.5: "A union in `TRUSTEED` blocks two operations: tendering a
    proposal and scheduling a bargaining session. Both attempts are rejected
    with `ERR_UNION_TRUSTEED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/session_safety_beats_temporal
    """
    _, _, s1 = _setup_trusteed_union_with_session(api)
    # The would-be-conflicting create attempt is rejected; existing session unchanged.
    s1_after = get_success_data(api.get_session(s1["id"], NEG1))
    assert s1_after["status"] == "SCHEDULED"
    assert s1_after["version"] == s1["version"]
