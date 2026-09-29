"""Read-your-write on the money ledger: the confirmation response already
carries the encumbrance every later reader will see."""
from test_helpers import (
    FISCAL_OFFICER_USER_ID,
    api_client,
    confirm_session_as_liaison,
    make_fiscal_officer_headers,
    make_teaching_artist_headers,
    schedule_session,
    set_clock_to_default,
    setup_active_residency,
    validate_success,
)


def _planned_session_awaiting_confirmation() -> dict:
    """An ACTIVE ten-session residency on a 200000-cent budget with one PLANNED
    session and nothing yet encumbered."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["session"] = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-15",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    return scenario


def test_the_confirmation_response_already_carries_the_encumbrance(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §2.7: "Reconciliation is immediate and transitive."
    PRD §3.6: "Confirmation persists both supplied fields and then **encumbers**
    the money it expects to owe."
    PRD §3.6: "The server evaluates the session fee rules of §3.7 as though the
    artist had taught the full `session_length_minutes`, writes that amount into
    the session's own `encumbered_cents`, adds it to the residency's
    `encumbered_cents`, and recomputes `available_cents`."

    Design: Corner/Consistency Model/confirmation_response_already_reflects_the_new_money_ledger
    """
    scenario = _planned_session_awaiting_confirmation()
    assert scenario["session"]["status"] == "PLANNED"
    assert scenario["session"]["encumbered_cents"] == 0, (
        "a PLANNED session holds nothing yet, got "
        f"{scenario['session']['encumbered_cents']}"
    )

    confirmed = confirm_session_as_liaison(
        scenario["session"]["id"], scenario["school"]["id"]
    )
    assert confirmed["status"] == "CONFIRMED", (
        f"the school locked the date in, got {confirmed['status']}"
    )
    assert confirmed["classroom_teacher_name"] == "Ms. Delgado"
    assert confirmed["co_planning_completed"] is True
    assert confirmed["encumbered_cents"] == 13974, (
        "the confirmation response itself must already show the full-length "
        "hold of 13974 for the lead artist on a bilingual DANCE G3_5 "
        f"residency, got {confirmed['encumbered_cents']}"
    )


def test_the_next_reader_of_either_row_sees_the_same_ledger_figures(api):
    """PRD §2.7: "Reconciliation is immediate and transitive."
    PRD §2.12: "The **money ledger** partitions the budget across three accounts:
    `encumbered_cents`, the sum of the amounts currently held by this residency's
    sessions; `disbursed_cents`, the sum of `total_cents` over this residency's
    `APPROVED` vouchers; and `available_cents`, which is `budget_cents` less
    encumbered less disbursed."
    PRD §3.4: "`projected_cost_cents` is the forward-looking figure the program
    director watches against `budget_cents`: it starts from
    `earned_to_date_cents`, adds a full-length fee projection for every session of
    the residency whose status is `PLANNED`, `CONFIRMED`, or `VACATED`, and then
    adds one lead projection for each remaining unscheduled allotment unit and
    each outstanding make-up credit — that is, `sessions_unscheduled_count` plus
    `makeup_credits_outstanding` lead projections."
    PRD §3.4: "A **lead projection** evaluates the same fee rules for a
    hypothetical regular, non-substitute, full-length session of this residency
    taught by the residency's lead artist with the lead premium applied; when
    `lead_artist_id` is null, the lead projection is instead evaluated at the
    `TEACHING_ARTIST` tier multiplier with no lead premium and no language
    premium."

    Design: Corner/Consistency Model/confirmation_response_already_reflects_the_new_money_ledger
    """
    scenario = _planned_session_awaiting_confirmation()
    residency_id = scenario["residency"]["id"]
    session_id = scenario["session"]["id"]

    confirmed = confirm_session_as_liaison(session_id, scenario["school"]["id"])
    held = confirmed["encumbered_cents"]
    assert held == 13974, (
        "the confirm response reports the full-length hold for the lead "
        f"artist, got {held}"
    )

    # The fiscal officer reads the residency straight after the school liaison's
    # write; there is no window in which the parent still shows the old figures.
    residency = validate_success(
        api_client.get_residency(
            residency_id, make_fiscal_officer_headers(FISCAL_OFFICER_USER_ID)
        )
    )
    assert residency["encumbered_cents"] == held, (
        "the residency's hold must already equal the amount the confirmation "
        f"response reported, got {residency['encumbered_cents']} against {held}"
    )
    assert residency["available_cents"] == 186026, (
        "200000 budget less the single 13974 hold and nothing disbursed, got "
        f"{residency['available_cents']}"
    )
    assert residency["disbursed_cents"] == 0
    assert residency["earned_to_date_cents"] == 0, (
        "nothing has been delivered, so the backward-looking figure is untouched"
    )
    assert residency["projected_cost_cents"] == 139740, (
        "the one CONFIRMED session projects 13974 and the nine remaining "
        f"unscheduled units project 13974 each, got "
        f"{residency['projected_cost_cents']}"
    )

    session = validate_success(
        api_client.get_session(
            session_id, make_teaching_artist_headers(scenario["artist"]["id"])
        )
    )
    assert session["status"] == "CONFIRMED"
    assert session["encumbered_cents"] == held, (
        "the session row carries the same hold as the confirmation response, "
        f"got {session['encumbered_cents']} against {held}"
    )
