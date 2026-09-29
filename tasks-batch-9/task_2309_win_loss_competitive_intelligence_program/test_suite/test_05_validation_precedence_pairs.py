"""
Two requests that breach two rules at once, where only one refusal is correct.

Both pairs are chosen so the two candidate errors carry different HTTP statuses,
which makes the ordering observable from the status line alone.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CONSENT_NOT_GRANTED,
    ERR_CONTACT_COOLING_OFF_ACTIVE,
    ERR_INCENTIVE_BUDGET_EXCEEDED,
    ERR_PROGRAM_POSTURE_FROZEN,
)
from test_helpers.assertions import (
    assert_analyst_workload,
    assert_deal_dimensions,
    assert_field,
    assert_ledger,
    assert_not_null,
)
from test_helpers.fixtures import WinLossWorld


def _frozen_program_with_a_no_show_to_rebook(world: WinLossWorld) -> WinLossWorld:
    """A FROZEN program holding one NO_SHOW interview that could be rebooked.

    Rebooking it would also breach the 300.00 budget, so both the posture rule and
    the fiscal ceiling are live at the same moment.
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program(incentive_budget_usd=300.00)
    world.create_competitor()
    world.create_analyst()
    deal_one = world.create_deal(primary_competitor_id=world.competitor["id"])
    deal_two = world.create_deal(
        crm_deal_ref="CRM-1002",
        acr_usd=260000.00,
        close_date="2026-06-20T00:00:00.000Z",
        sales_rep_user_ref="rep-78",
        primary_competitor_id=world.competitor["id"],
    )
    contact_one = world.consented_contact(deal_id=deal_one["id"])
    contact_two = world.consented_contact(
        deal_id=deal_two["id"], email="buyer2@brava.test", full_name="Cal Dos"
    )
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=2)
    world.schedule_interview(deal_id=deal_one["id"], buyer_contact_id=contact_one["id"])
    world.set_clock("2026-08-10T14:16:00.000Z")
    world.no_show()
    second = world.schedule_interview(
        deal_id=deal_two["id"],
        buyer_contact_id=contact_two["id"],
        scheduled_start_at="2026-08-15T14:00:00.000Z",
        scheduled_end_at="2026-08-15T15:00:00.000Z",
    )
    world.cover_guide(interview_id=second["id"], recorded_at="2026-08-15T14:10:00.000Z", rating=3)
    world.set_clock("2026-08-15T15:30:00.000Z")
    world.complete_interview(
        interview_id=second["id"],
        actual_start_at="2026-08-15T14:00:00.000Z",
        actual_end_at="2026-08-15T15:20:00.000Z",
    )
    return world


def _same_person_on_a_second_deal_without_consent(world: WinLossWorld) -> WinLossWorld:
    """One buyer person on two deals: consented on the first, REQUESTED on the second."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    deal_one = world.create_deal(primary_competitor_id=world.competitor["id"])
    deal_two = world.create_deal(
        crm_deal_ref="CRM-1002",
        acr_usd=260000.00,
        close_date="2026-06-20T00:00:00.000Z",
        sales_rep_user_ref="rep-78",
        primary_competitor_id=world.competitor["id"],
    )
    contact_one = world.consented_contact(deal_id=deal_one["id"])
    contact_two = world.create_contact(deal_id=deal_two["id"])
    world.record_consent(
        "REQUESTED", deal_id=deal_two["id"], contact_id=contact_two["id"]
    )
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=2)
    world.schedule_interview(deal_id=deal_one["id"], buyer_contact_id=contact_one["id"])
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=4)
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z", actual_end_at="2026-08-10T15:00:00.000Z"
    )
    world.first_deal = deal_one
    world.second_deal = deal_two
    world.first_contact = contact_one
    world.second_contact = contact_two
    return world


# ---------------------------------------------------------------------------
# Frozen posture versus the incentive budget
# ---------------------------------------------------------------------------


def test_the_frozen_posture_precondition_holds_before_the_rebooking_attempt(world):
    """The overrun completion left the program frozen and its frame suspended.

    "When a program's `posture` is recomputed to `FROZEN`, every `SEALED` frame of
    that program transitions `SEALED → SUSPENDED` and has its `version`
    incremented"

    Design: Difficulty/priority_pair_validation_conflict/posture_frozen_outranks_incentive_budget_exceeded_on_reschedule
    """
    _frozen_program_with_a_no_show_to_rebook(world)

    assert_ledger(world.refresh_program(), 0.00, 312.50, "FROZEN")
    assert_field(world.get_frame(), "status", "SUSPENDED")


def test_a_frozen_posture_is_reported_instead_of_the_breached_budget(world):
    """Both rules are breached; the state rule is the one that answers.

    "the program's `posture` must not be `FROZEN`, and the new interval must clear
    the full scheduling battery again: independence, certification, consent, the
    buyer cooling-off window, the buffered analyst slot check, the open-workload cap
    and the incentive budget ceiling all re-run exactly as at first scheduling."

    Design: Difficulty/priority_pair_validation_conflict/posture_frozen_outranks_incentive_budget_exceeded_on_reschedule
    """
    _frozen_program_with_a_no_show_to_rebook(world)

    body = validate_error(
        world.api.reschedule_interview(
            world.interview["id"],
            f.reschedule_payload("2026-08-25T09:00:00.000Z", "2026-08-25T10:00:00.000Z"),
            world.analyst_headers,
        ),
        ERR_PROGRAM_POSTURE_FROZEN,
        409,
    )

    assert body["error_id"] != ERR_INCENTIVE_BUDGET_EXCEEDED, (
        "the fiscal ceiling must not be evaluated ahead of the posture gate"
    )


def test_the_refused_rebooking_leaves_the_no_show_and_the_ledger_untouched(world):
    """A refusal writes nothing: no re-commitment and no loop counter increment.

    "A no-show can be rebooked, moving the interview `NO_SHOW → SCHEDULED` on a
    fresh `scheduled_start_at` and `scheduled_end_at`."

    Design: Difficulty/priority_pair_validation_conflict/posture_frozen_outranks_incentive_budget_exceeded_on_reschedule
    """
    _frozen_program_with_a_no_show_to_rebook(world)
    interview_id = world.interview["id"]

    validate_error(
        world.api.reschedule_interview(
            interview_id,
            f.reschedule_payload("2026-08-25T09:00:00.000Z", "2026-08-25T10:00:00.000Z"),
            world.analyst_headers,
        ),
        ERR_PROGRAM_POSTURE_FROZEN,
        409,
    )

    interview = world.get_interview(interview_id)
    assert_field(interview, "status", "NO_SHOW")
    assert_field(interview, "reschedule_count", 0)
    assert_field(interview, "incentive_status", "FORFEITED")
    assert_ledger(world.refresh_program(), 0.00, 312.50)


# ---------------------------------------------------------------------------
# Consent versus the cooling-off window
# ---------------------------------------------------------------------------


def test_both_the_consent_and_the_cooling_off_conditions_are_live(world):
    """The same person was interviewed nine days ago and has not consented again.

    "The lower-cased `email` is the **person key**: the same human appearing on two
    different deals is one person for the purposes of the cooling-off rule in §3.4"

    Design: Difficulty/priority_pair_validation_conflict/consent_gate_outranks_contact_cooling_off_window_on_scheduling
    """
    _same_person_on_a_second_deal_without_consent(world)

    first = world.get_contact(world.first_contact["id"])
    second = world.get_contact(world.second_contact["id"])
    assert first["last_completed_interview_end_at"] == "2026-08-10T15:00:00.000Z", (
        f"anchor instant not recorded: {first['last_completed_interview_end_at']}"
    )
    assert_field(second, "consent_status", "REQUESTED")
    assert_field(second, "email", "buyer1@acme.test")
    assert_deal_dimensions(
        world.get_deal(world.second_deal["id"]), research_status="SELECTED"
    )


def test_missing_consent_is_reported_instead_of_the_active_cooling_off_window(world):
    """Consent is the safety gate and therefore answers first.

    "Consent is a safety precondition to contacting a buyer at all and therefore
    outranks the two temporal rules that follow it."

    Design: Difficulty/priority_pair_validation_conflict/consent_gate_outranks_contact_cooling_off_window_on_scheduling
    """
    _same_person_on_a_second_deal_without_consent(world)

    body = validate_error(
        world.api.create_interview(
            f.interview_payload(
                world.second_deal["id"],
                world.second_contact["id"],
                world.analyst["id"],
                scheduled_start_at="2026-08-20T14:00:00.000Z",
                scheduled_end_at="2026-08-20T15:00:00.000Z",
            ),
            world.analyst_headers,
        ),
        ERR_CONSENT_NOT_GRANTED,
        422,
    )

    assert body["error_id"] != ERR_CONTACT_COOLING_OFF_ACTIVE, (
        "the temporal rule must not be evaluated ahead of the consent gate"
    )


def test_the_refused_scheduling_creates_no_interview_and_commits_no_money(world):
    """Nothing is booked and nothing is charged when consent is missing.

    "the program's `incentive_committed_usd` plus its `incentive_paid_usd` plus the
    provisional amount this new interview would commit must not exceed
    `incentive_budget_usd`"

    Design: Difficulty/priority_pair_validation_conflict/consent_gate_outranks_contact_cooling_off_window_on_scheduling
    """
    _same_person_on_a_second_deal_without_consent(world)

    validate_error(
        world.api.create_interview(
            f.interview_payload(
                world.second_deal["id"],
                world.second_contact["id"],
                world.analyst["id"],
                scheduled_start_at="2026-08-20T14:00:00.000Z",
                scheduled_end_at="2026-08-20T15:00:00.000Z",
            ),
            world.analyst_headers,
        ),
        ERR_CONSENT_NOT_GRANTED,
        422,
    )

    items, _ = validate_paginated(world.api.list_interviews(world.admin))
    assert all(item["deal_id"] != world.second_deal["id"] for item in items), (
        "the refused request must not have left an interview row behind"
    )
    assert_ledger(world.refresh_program(), 0.00, 250.00)
    assert_analyst_workload(world.get_analyst(), 0, 0)


def test_the_completed_first_interview_remains_the_only_booking(world):
    """The one legitimate interview is untouched by the refusal.

    "`COMPLETED` is terminal for the interview."

    Design: Difficulty/priority_pair_validation_conflict/consent_gate_outranks_contact_cooling_off_window_on_scheduling
    """
    _same_person_on_a_second_deal_without_consent(world)
    validate_error(
        world.api.create_interview(
            f.interview_payload(
                world.second_deal["id"],
                world.second_contact["id"],
                world.analyst["id"],
                scheduled_start_at="2026-08-20T14:00:00.000Z",
                scheduled_end_at="2026-08-20T15:00:00.000Z",
            ),
            world.analyst_headers,
        ),
        ERR_CONSENT_NOT_GRANTED,
        422,
    )

    body = validate_success(
        world.api.get_interview(world.interview["id"], world.admin), 200
    )
    assert_field(body, "status", "COMPLETED")
    assert_not_null(body["actual_end_at"], "actual_end_at")
