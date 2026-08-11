"""Transitive cascade tests: depth-5 ratification cascade and depth-2
decertify cascade (difficulty rule 4)."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_clause_payload,
    create_draft_agreement,
    create_employer_proposal_on_table,
    create_executed_side_letter,
    create_interpreted_clause,
    create_locked_scenario,
    create_ratification_vote_payload,
    create_session,
    create_union,
    get_success_data,
    make_union_representative_headers,
)

ADMIN = TEST_USERS["lr_admin_headers"]
NEG1 = TEST_USERS["negotiator_headers"]
CHIEF = TEST_USERS["chief_negotiator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / ratification_depth5_cascade
# ---------------------------------------------------------------------------

def _setup_ratification_cascade(api):
    """Incumbent ACTIVE agreement with INTERPRETED clause + EXECUTED letter;
    successor DRAFT agreement with an ACCEPTED proposal referencing that clause
    under a LOCKED scenario; OPEN vote; clock past ballot_close."""
    union = create_union(name="Union G")
    a1 = create_draft_agreement(
        union["id"],
        title="CBA G incumbent",
        effective_date="2026-01-01T00:00:00Z",
        expiration_date="2026-12-31T00:00:00Z",
        headcount_baseline=100,
        fte_projected=120,
        avg_loaded_wage_cents=5000,
        costing_envelope_cents=1_000_000_000_000,
    )
    a1 = get_success_data(api.activate_agreement(a1["id"], ADMIN))
    clause = create_interpreted_clause(
        a1["id"], article_ref="12.1", title="Overtime", body_text="Overtime terms", is_economic=True
    )
    letter = create_executed_side_letter(
        a1["id"],
        clause["id"],
        letter_type="SIDE_LETTER",
        title="OT moderation letter",
        effective_start="2026-01-01T00:00:00Z",
        effective_end="2027-12-31T00:00:00Z",
    )
    a2 = create_draft_agreement(
        union["id"],
        title="CBA G successor",
        effective_date="2026-06-01T00:00:00Z",
        expiration_date="2029-05-31T00:00:00Z",
        headcount_baseline=100,
        fte_projected=120,
        avg_loaded_wage_cents=5000,
        costing_envelope_cents=1_000_000,
    )
    proposal = get_success_data(
        api.create_proposal(
            {
                "agreement_id": a2["id"],
                "clause_id": clause["id"],
                "side": "EMPLOYER",
                "title": "OT allowance",
                "proposal_type": "ECONOMIC",
                "recurring_annual_cost_cents": 100,
            },
            NEG1,
        )
    )
    get_success_data(api.transition_proposal(proposal["id"], {"to_status": "TENDERED"}, CHIEF))
    proposal = get_success_data(
        api.transition_proposal(
            proposal["id"], {"to_status": "ON_TABLE"}, make_union_representative_headers(union["id"])
        )
    )
    create_locked_scenario(a2["id"], [proposal["id"]], scenario_mode="FINAL", term_years=3)
    get_success_data(
        api.transition_proposal(
            proposal["id"], {"to_status": "ACCEPTED"}, make_union_representative_headers(union["id"])
        )
    )
    vote = get_success_data(
        api.create_ratification_vote(
            create_ratification_vote_payload(
                agreement_id=a2["id"], eligible_voter_count=10, ballot_close_at="2026-06-01T00:00:00Z"
            ),
            CHIEF,
        )
    )
    get_success_data(api.transition_ratification_vote(vote["id"], {"to_status": "OPEN"}, CHIEF))
    get_success_data(api.set_clock("2026-06-02T00:00:00Z", ADMIN))
    return union, a1, a2, clause, letter, proposal, vote


def test_ratification_depth5_cascade_states(api):
    """PRD §3.6: "Link 1: the agreement moves `DRAFT → ACTIVE` and posture is
    recomputed. Link 2: the incumbent agreement of the same union in `ACTIVE`
    or `EXTENDED` becomes `REPLACED` (posture `CLOSED`) — this is the
    incumbent-supersession rule, applied here by cascade rather than by direct
    activation. Link 3: every `ACCEPTED` proposal of the ratified agreement
    becomes `IMPLEMENTED`, and the agreement's `envelope_committed_cents` is
    recomputed (the implemented proposals remain in the committed envelope).
    Link 4: every `EXECUTED` side letter whose `clause_id` equals an
    implemented proposal's `clause_id` and whose `[effective_start,
    effective_end]` closed interval overlaps the agreement's `[effective_date,
    expiration_date]` closed interval becomes `SUPERSEDED`. Link 5: each such
    supersession re-triggers the clause cascade — the affected clause moves
    from `INTERPRETED`, `DISPUTED`, or `RESOLVED` back to `UNDER_REVIEW`."

    Design: Difficulty/transitive_cascade/ratification_depth5_cascade
    """
    union, a1, a2, clause, letter, proposal, vote = _setup_ratification_cascade(api)
    result = get_success_data(
        api.tally_vote(
            vote["id"], {"votes_for": 4, "votes_against": 1},
            make_union_representative_headers(union["id"]),
        )
    )
    assert result["status"] == "RATIFIED"
    assert result["retro_payout_cents"] == 0, (
        "effective_date 2026-06-01 is only 1 day before tally 2026-06-02 -> 0 whole periods"
    )

    a1_after = get_success_data(api.get_agreement(a1["id"], NEG1))
    a2_after = get_success_data(api.get_agreement(a2["id"], NEG1))
    proposal_after = get_success_data(api.get_proposal(proposal["id"], NEG1))
    letter_after = get_success_data(api.get_side_letter(letter["id"], NEG1))
    clause_after = get_success_data(api.get_clause(clause["id"], NEG1))

    assert a2_after["status"] == "ACTIVE", "cascade link 1: successor activates"
    assert a1_after["status"] == "REPLACED", "cascade link 2: incumbent superseded"
    assert proposal_after["status"] == "IMPLEMENTED", "cascade link 3: package implemented"
    assert letter_after["status"] == "SUPERSEDED", "cascade link 4: overlapping letter superseded"
    assert clause_after["interpretation_status"] == "UNDER_REVIEW", (
        "cascade link 5: clause returns to UNDER_REVIEW"
    )


def test_ratification_depth5_cascade_envelope(api):
    """PRD §3.6: "Link 3: every `ACCEPTED` proposal of the ratified agreement
    becomes `IMPLEMENTED`, and the agreement's `envelope_committed_cents` is
    recomputed (the implemented proposals remain in the committed envelope)."

    Design: Difficulty/transitive_cascade/ratification_depth5_cascade
    """
    union, a1, a2, clause, letter, proposal, vote = _setup_ratification_cascade(api)
    get_success_data(
        api.tally_vote(
            vote["id"], {"votes_for": 4, "votes_against": 1},
            make_union_representative_headers(union["id"]),
        )
    )
    a2_after = get_success_data(api.get_agreement(a2["id"], NEG1))
    # FINAL mode, basis 100: wage 0 (pct null), recurring 100, one_time 0
    # -> estimated_year1_cost_cents == 100
    assert a2_after["envelope_committed_cents"] == 100


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / union_decertify_depth2_cascade
# ---------------------------------------------------------------------------

def _setup_decertify(api):
    union = create_union(name="Union H")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA H",
        headcount_baseline=50,
        fte_projected=60,
        avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    session = create_session(
        agreement["id"],
        mediator_id="med-9",
        lead_negotiator_id="ln-9",
        location="Room 1",
        start_at="2026-06-01T10:00:00Z",
        end_at="2026-06-01T11:00:00Z",
    )
    return union, agreement, session


def test_decertify_cascade_agreements_and_sessions(api):
    """PRD §2.5: "When a union transitions to `DECERTIFIED`, the system walks
    its agreements: every `CollectiveAgreement` of that union still in `DRAFT`
    becomes `ARCHIVED`, and every `BargainingSession` tied to one of those
    just-archived agreements — or belonging to this union — that is still
    `SCHEDULED` becomes `CANCELLED` with `cancel_reason` set to
    `UNION_DECERTIFIED`."

    Design: Difficulty/transitive_cascade/union_decertify_depth2_cascade
    """
    union, agreement, session = _setup_decertify(api)
    result = get_success_data(
        api.transition_union(union["id"], {"to_status": "DECERTIFIED"}, ADMIN)
    )
    assert result["status"] == "DECERTIFIED"
    agreement_after = get_success_data(api.get_agreement(agreement["id"], NEG1))
    session_after = get_success_data(api.get_session(session["id"], NEG1))
    assert agreement_after["status"] == "ARCHIVED", "cascade link 1: DRAFT agreement archived"
    assert session_after["status"] == "CANCELLED", "cascade link 2: SCHEDULED session cancelled"
    assert session_after["cancel_reason"] == "UNION_DECERTIFIED"


def test_decertify_cascade_version_increments(api):
    """PRD §2.5: "The union's `version` increments, and each cascaded entity's
    `version` increments as well."

    Design: Difficulty/transitive_cascade/union_decertify_depth2_cascade
    """
    union, agreement, session = _setup_decertify(api)
    get_success_data(api.transition_union(union["id"], {"to_status": "DECERTIFIED"}, ADMIN))
    union_after = get_success_data(api.get_union(union["id"], NEG1))
    agreement_after = get_success_data(api.get_agreement(agreement["id"], NEG1))
    session_after = get_success_data(api.get_session(session["id"], NEG1))
    assert union_after["version"] == union["version"] + 1
    assert agreement_after["version"] == agreement["version"] + 1
    assert session_after["version"] == session["version"] + 1
