"""Corner state-machine tests: terminal lockdowns, invalid transitions, and
workflow cycles."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_agreement,
    create_draft_agreement,
    create_information_request_payload,
    create_past_practice_payload,
    create_proposal_payload,
    create_session,
    create_union,
    create_verified_practice,
    get_success_data,
    make_union_representative_headers,
    validate_error,
)

ADMIN = TEST_USERS["lr_admin_headers"]
MGR = TEST_USERS["lr_manager_headers"]
NEG1 = TEST_USERS["negotiator_headers"]
CHIEF = TEST_USERS["chief_negotiator_headers"]
LC = TEST_USERS["legal_counsel_headers"]


# ---------------------------------------------------------------------------
# Corner: state_machines / rejected_proposal_terminal_lockdown
# ---------------------------------------------------------------------------

def test_rejected_proposal_terminal_lockdown(api):
    """PRD §3.3: "The receiving side may accept (`ON_TABLE → ACCEPTED`), reject
    (`ON_TABLE → REJECTED`, requiring a `reason` which is stored as
    `rejection_reason`), or counter (per §3.4's round mechanics)."
    PRD §2.11: "State-machine validity comes after that (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/rejected_proposal_terminal_lockdown
    """
    union = create_union(name="Union CG")
    agreement = create_draft_agreement(union["id"], title="CBA CG")
    rep = make_union_representative_headers(union["id"])
    proposal = get_success_data(
        api.create_proposal(
            create_proposal_payload(
                agreement_id=agreement["id"],
                side="UNION",
                title="Union ask",
                proposal_type="NON_ECONOMIC",
            ),
            rep,
        )
    )
    get_success_data(api.transition_proposal(proposal["id"], {"to_status": "TENDERED"}, rep))
    get_success_data(api.transition_proposal(proposal["id"], {"to_status": "ON_TABLE"}, CHIEF))
    rejected = get_success_data(
        api.transition_proposal(
            proposal["id"], {"to_status": "REJECTED", "reason": "Out of scope"}, CHIEF
        )
    )
    assert rejected["rejection_reason"] == "Out of scope"
    resp = api.transition_proposal(proposal["id"], {"to_status": "WITHDRAWN"}, rep)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_proposal(proposal["id"], NEG1))
    assert after["status"] == "REJECTED"
    assert after["rejection_reason"] == "Out of scope"


# ---------------------------------------------------------------------------
# Corner: state_machines / archived_agreement_terminal_lockdown
# ---------------------------------------------------------------------------

def test_archived_agreement_extend_rejected(api):
    """PRD §3.12: "Finally, an `LRAdmin` may archive an agreement in `EXPIRED`
    or `REPLACED`, moving it to `ARCHIVED` with posture `CLOSED` and
    incrementing its `version`." and "The agreement must be in `ACTIVE`,
    `EXPIRED`, or `EXTENDED`; the new expiration must be strictly later than
    the current one (otherwise `ERR_EXTENSION_NOT_FORWARD`)"

    Design: Corner/state_machines/archived_agreement_terminal_lockdown
    """
    union = create_union(name="Union CH")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA CH",
        effective_date="2026-01-01T00:00:00Z",
        expiration_date="2026-06-30T00:00:00Z",
        headcount_baseline=50,
        fte_projected=60,
        avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    get_success_data(api.activate_agreement(agreement["id"], ADMIN))
    get_success_data(api.set_clock("2026-07-01T00:00:00Z", ADMIN))
    archived = get_success_data(api.archive_agreement(agreement["id"], ADMIN))
    resp = api.extend_agreement(
        agreement["id"],
        {"new_expiration_date": "2027-06-30T00:00:00Z",
         "expected_agreement_version": archived["version"]},
        CHIEF,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_agreement(agreement["id"], ADMIN))
    assert after["status"] == "ARCHIVED"
    assert after["posture"] == "CLOSED"


# ---------------------------------------------------------------------------
# Corner: state_machines / completed_session_cannot_reopen
# ---------------------------------------------------------------------------

def test_completed_session_cannot_reopen(api):
    """PRD §3.3: "From `IN_SESSION`, a `ChiefNegotiator` completes the session
    by supplying a `summary_note` — omitting it is `ERR_INVALID_REQUEST` — and
    the note is stored."
    PRD §2.11: "State-machine validity comes after that (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/completed_session_cannot_reopen
    """
    union = create_union(name="Union CI")
    agreement = create_draft_agreement(union["id"], title="CBA CI")
    session = create_session(
        agreement["id"], mediator_id="med-c", lead_negotiator_id="ln-c",
        location="Room 1", start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z",
    )
    get_success_data(api.set_clock("2026-06-01T10:30:00Z", ADMIN))
    get_success_data(api.transition_session(session["id"], {"to_status": "IN_SESSION"}, CHIEF))
    completed = get_success_data(
        api.transition_session(
            session["id"], {"to_status": "COMPLETED", "summary_note": "Exchanged economics"}, CHIEF
        )
    )
    assert completed["summary_note"] == "Exchanged economics"
    resp = api.transition_session(session["id"], {"to_status": "IN_SESSION"}, CHIEF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_session(session["id"], NEG1))
    assert after["status"] == "COMPLETED"
    assert after["summary_note"] == "Exchanged economics"


# ---------------------------------------------------------------------------
# Corner: state_machines / decertified_union_no_return
# ---------------------------------------------------------------------------

def test_decertified_union_no_return(api):
    """PRD §2.5: "A union begins in `ACTIVE` status; an `LRAdmin` may move it
    to `TRUSTEED` or `DECERTIFIED`, and a `TRUSTEED` union may be restored to
    `ACTIVE`."
    PRD §2.11: "State-machine validity comes after that (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/decertified_union_no_return
    """
    union = create_union(name="Union CJ")
    get_success_data(api.transition_union(union["id"], {"to_status": "DECERTIFIED"}, ADMIN))
    resp = api.transition_union(union["id"], {"to_status": "TRUSTEED"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_union(union["id"], ADMIN))
    assert after["status"] == "DECERTIFIED"


# ---------------------------------------------------------------------------
# Corner: state_machines / info_request_objection_cycle
# ---------------------------------------------------------------------------

def test_info_request_objection_cycle(api):
    """PRD §3.11: "A `LegalCounsel` may object (`IN_PROGRESS → OBJECTED`),
    supplying `objection_basis`, which is stored; if the objection is later
    withdrawn, a `LegalCounsel` moves the request back (`OBJECTED →
    IN_PROGRESS`) with the `objection_basis` retained for audit." and "Each
    terminal or partial fulfillment — that is, every transition into
    `FULFILLED` or `PARTIALLY_FULFILLED` — decrements the union's
    `open_information_request_count` and bumps the union's `version`."

    Design: Corner/state_machines/info_request_objection_cycle
    """
    union = create_union(name="Union CK")
    agreement = create_draft_agreement(
        union["id"], title="CBA CK", deadline_mode="BUSINESS",
        headcount_baseline=50, fte_projected=60, avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    request = get_success_data(
        api.create_information_request(
            create_information_request_payload(
                union_id=union["id"], agreement_id=agreement["id"],
                subject="Seniority list", received_at="2026-05-01T09:00:00Z",
            ),
            make_union_representative_headers(union["id"]),
        )
    )
    get_success_data(api.transition_information_request(request["id"], {"to_status": "ACKNOWLEDGED"}, MGR))
    get_success_data(api.transition_information_request(request["id"], {"to_status": "IN_PROGRESS"}, MGR))
    objected = get_success_data(
        api.transition_information_request(
            request["id"],
            {"to_status": "OBJECTED", "objection_basis": "Confidential trade secret"},
            LC,
        )
    )
    assert objected["objection_basis"] == "Confidential trade secret"
    back = get_success_data(
        api.transition_information_request(request["id"], {"to_status": "IN_PROGRESS"}, LC)
    )
    assert back["objection_basis"] == "Confidential trade secret", (
        "objection_basis retained for audit after the withdrawal cycle"
    )
    fulfilled = get_success_data(
        api.transition_information_request(
            request["id"], {"to_status": "FULFILLED", "response_note": "Records shipped"}, MGR
        )
    )
    assert fulfilled["status"] == "FULFILLED"
    union_after = get_success_data(api.get_union(union["id"], MGR))
    assert union_after["open_information_request_count"] == 0


# ---------------------------------------------------------------------------
# Corner: state_machines / practice_abandon_notice_sweep
# ---------------------------------------------------------------------------

def test_practice_abandon_notice_and_sweep(api):
    """PRD §3.10: "An `LRManager` moves a `VERIFIED` practice to
    `NOTICE_GIVEN`, which sets `abandon_effective_date` to the current clock
    plus 30 days." and "When the clock reaches `abandon_effective_date`, the
    sweep moves the practice to `ABANDONED`"
    PRD §2.12: "Step 4: past practices in `NOTICE_GIVEN` whose
    `abandon_effective_date` has been reached or passed become `ABANDONED`"

    Design: Corner/state_machines/practice_abandon_notice_sweep
    """
    union = create_union(name="Union CL")
    practice = create_verified_practice(
        union["id"],
        title="Premium",
        description="December premium",
        first_observed_date="2023-05-01T00:00:00Z",
        last_observed_date="2025-05-01T00:00:00Z",
        occurrence_count=8,
    )
    noticed = get_success_data(
        api.transition_past_practice(practice["id"], {"to_status": "NOTICE_GIVEN"}, MGR)
    )
    # Default clock is 2026-05-01T00:00:00Z; +30 days = 2026-05-31T00:00:00Z.
    assert noticed["abandon_effective_date"] == "2026-05-31T00:00:00Z", (
        f"abandon_effective_date mismatch: {noticed['abandon_effective_date']}"
    )
    get_success_data(api.set_clock("2026-05-31T00:00:00Z", ADMIN))
    after = get_success_data(api.get_past_practice(practice["id"], MGR))
    assert after["status"] == "ABANDONED", "sweep flips at abandon_effective_date (inclusive)"


# ---------------------------------------------------------------------------
# Corner: state_machines / session_no_show_sweep_boundary
# ---------------------------------------------------------------------------

def test_session_no_show_sweep_boundary(api):
    """PRD §2.12: "Step 2: sessions still `SCHEDULED` whose `end_at` is
    strictly earlier than the new clock become `NO_SHOW`, with the mediator's
    scheduled-minutes released exactly as on cancellation."

    Design: Corner/state_machines/session_no_show_sweep_boundary
    """
    union = create_union(name="Union CM")
    agreement = create_draft_agreement(union["id"], title="CBA CM")
    session = create_session(
        agreement["id"], mediator_id="med-d", lead_negotiator_id="ln-d",
        location="Room 1", start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z",
    )
    get_success_data(api.set_clock("2026-06-01T11:00:00Z", ADMIN))
    at_end = get_success_data(api.get_session(session["id"], NEG1))
    assert at_end["status"] == "SCHEDULED", "clock == end_at is not strictly past"
    get_success_data(api.set_clock("2026-06-01T11:00:01Z", ADMIN))
    after = get_success_data(api.get_session(session["id"], NEG1))
    assert after["status"] == "NO_SHOW"


# ---------------------------------------------------------------------------
# Corner: state_machines / task_missed_then_completed_late
# ---------------------------------------------------------------------------

def test_task_missed_then_completed_late(api):
    """PRD §3.12: "The `completed_late` flag is set to true when `DONE` is
    reached either after `due_date` per the current clock, or from a prior
    status of `MISSED`; in the `MISSED → DONE` case the flag is forced true
    regardless of the clock. Independently, the clock sweep moves any `PENDING`
    or `IN_PROGRESS` task whose `due_date` is strictly past to `MISSED`."

    Design: Corner/state_machines/task_missed_then_completed_late
    """
    union = create_union(name="Union CN")
    agreement = create_active_agreement(
        union["id"], title="CBA CN",
        effective_date="2026-01-01T00:00:00Z", expiration_date="2026-06-30T00:00:00Z",
        headcount_baseline=50, fte_projected=60, avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    task = get_success_data(
        api.create_expiration_task(
            {
                "agreement_id": agreement["id"],
                "title": "60-day notice",
                "task_type": "NOTICE_DEADLINE",
                "due_offset_days": -60,
                "assignee_user_id": "mgr-1",
            },
            MGR,
        )
    )
    assert task["due_date"] == "2026-05-01T00:00:00Z", (
        f"due_date must be expiration - 60 days; got {task['due_date']}"
    )
    get_success_data(api.set_clock("2026-05-10T00:00:00Z", ADMIN))
    swept = get_success_data(api.get_expiration_task(task["id"], MGR))
    assert swept["status"] == "MISSED"
    done = get_success_data(
        api.transition_expiration_task(task["id"], {"to_status": "DONE"}, MGR)
    )
    assert done["status"] == "DONE"
    assert done["completed_late"] is True
