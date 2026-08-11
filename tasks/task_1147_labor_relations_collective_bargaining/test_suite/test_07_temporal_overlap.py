"""Resource temporal-overlap tests (difficulty rule 8): mediator half-open
intervals vs side-letter closed intervals."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_agreement,
    create_clause,
    create_draft_agreement,
    create_session,
    create_side_letter_payload,
    create_union,
    get_success_data,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["lr_admin_headers"]
MGR = TEST_USERS["lr_manager_headers"]
NEG1 = TEST_USERS["negotiator_headers"]
LC = TEST_USERS["legal_counsel_headers"]


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / session_mediator_half_open
# ---------------------------------------------------------------------------

def _setup_mediator_session(api):
    union = create_union(name="Union O")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA O",
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
    return agreement, s1


def test_mediator_adjacency_allowed(api):
    """PRD §2.4: "The mediator is governed by a half-open overlap rule: a new
    session conflicts with an existing one whenever they share `mediator_id`,
    both are in `SCHEDULED` or `IN_SESSION` status, and their `[start_at,
    end_at)` windows intersect. Adjacency is permitted — one session ending at
    exactly the moment another begins is not a conflict"

    Design: Difficulty/resource_temporal_overlap/session_mediator_half_open
    """
    agreement, _ = _setup_mediator_session(api)
    s2 = get_success_data(
        api.create_session(
            {
                "agreement_id": agreement["id"],
                "mediator_id": "med-1",
                "lead_negotiator_id": "ln-2",
                "location": "Room 1",
                "start_at": "2026-06-01T11:00:00Z",
                "end_at": "2026-06-01T12:00:00Z",
            },
            NEG1,
        )
    )
    assert s2["status"] == "SCHEDULED"


def test_mediator_one_minute_overlap_rejected(api):
    """PRD §2.4: "The mediator is governed by a half-open overlap rule: a new
    session conflicts with an existing one whenever they share `mediator_id`,
    both are in `SCHEDULED` or `IN_SESSION` status, and their `[start_at,
    end_at)` windows intersect. ... and any such overlap is rejected with
    `ERR_MEDIATOR_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/session_mediator_half_open
    """
    agreement, _ = _setup_mediator_session(api)
    resp = api.create_session(
        {
            "agreement_id": agreement["id"],
            "mediator_id": "med-1",
            "lead_negotiator_id": "ln-3",
            "location": "Room 2",
            "start_at": "2026-06-01T10:59:00Z",
            "end_at": "2026-06-01T11:30:00Z",
        },
        NEG1,
    )
    validate_error(resp, ApiErrorId.ERR_MEDIATOR_CONFLICT)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / side_letter_closed_interval_overlap
# ---------------------------------------------------------------------------

def _setup_executed_letter(api):
    union = create_union(name="Union P")
    agreement = create_active_agreement(
        union["id"],
        title="CBA P",
        effective_date="2026-01-01T00:00:00Z",
        expiration_date="2029-05-31T00:00:00Z",
        headcount_baseline=50,
        fte_projected=60,
        avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    clause = create_clause(agreement["id"], article_ref="8.2", title="Scheduling", body_text="Scheduling terms")
    sl1 = get_success_data(
        api.create_side_letter(
            create_side_letter_payload(
                agreement_id=agreement["id"],
                clause_id=clause["id"],
                letter_type="MOA",
                title="Letter 1",
                effective_start="2026-01-01T00:00:00Z",
                effective_end="2026-12-31T00:00:00Z",
            ),
            MGR,
        )
    )
    get_success_data(api.transition_side_letter(sl1["id"], {"to_status": "PENDING_LEGAL"}, MGR))
    get_success_data(api.transition_side_letter(sl1["id"], {"to_status": "EXECUTED"}, LC))
    return agreement, clause


def _draft_pending_letter(api, agreement_id, clause_id, title, start, end):
    letter = get_success_data(
        api.create_side_letter(
            create_side_letter_payload(
                agreement_id=agreement_id,
                clause_id=clause_id,
                letter_type="MOA",
                title=title,
                effective_start=start,
                effective_end=end,
            ),
            MGR,
        )
    )
    get_success_data(api.transition_side_letter(letter["id"], {"to_status": "PENDING_LEGAL"}, MGR))
    return letter


def test_side_letter_touching_boundaries_conflict(api):
    """PRD §3.9: "the closed-interval overlap rule — no other `EXECUTED` letter
    on the same `clause_id` may have an effective window where the candidate's
    `effective_start` is on or before the other's `effective_end` and the
    other's `effective_start` is on or before the candidate's `effective_end`,
    with touching boundaries counted as a conflict — otherwise
    `ERR_SIDE_LETTER_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/side_letter_closed_interval_overlap
    """
    agreement, clause = _setup_executed_letter(api)
    sl2 = _draft_pending_letter(
        api, agreement["id"], clause["id"], "Letter 2",
        "2026-12-31T00:00:00Z", "2027-06-30T00:00:00Z",
    )
    resp = api.transition_side_letter(sl2["id"], {"to_status": "EXECUTED"}, LC)
    validate_error(resp, ApiErrorId.ERR_SIDE_LETTER_OVERLAP)
    after = get_success_data(api.get_side_letter(sl2["id"], MGR))
    assert after["status"] == "PENDING_LEGAL", "failed execute leaves state unchanged"


def test_side_letter_clear_window_executes(api):
    """PRD §3.9: "the closed-interval overlap rule — no other `EXECUTED` letter
    on the same `clause_id` may have an effective window where the candidate's
    `effective_start` is on or before the other's `effective_end` and the
    other's `effective_start` is on or before the candidate's `effective_end`,
    with touching boundaries counted as a conflict — otherwise
    `ERR_SIDE_LETTER_OVERLAP`." (A window starting 2027-01-01 clears the
    incumbent's inclusive 2026-12-31 end.)

    Design: Difficulty/resource_temporal_overlap/side_letter_closed_interval_overlap
    """
    agreement, clause = _setup_executed_letter(api)
    sl3 = _draft_pending_letter(
        api, agreement["id"], clause["id"], "Letter 3",
        "2027-01-01T00:00:00Z", "2027-12-31T00:00:00Z",
    )
    executed = get_success_data(api.transition_side_letter(sl3["id"], {"to_status": "EXECUTED"}, LC))
    assert executed["status"] == "EXECUTED"
