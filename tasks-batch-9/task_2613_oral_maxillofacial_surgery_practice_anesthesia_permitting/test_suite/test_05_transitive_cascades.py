"""Enforcement cascades: the five-hop suspension chain and the narrower three-hop
probation chain."""
import pytest

from test_helpers import (
    assert_instant_equals,
    api_client,
    clear_case,
    confirm_case,
    create_block,
    create_lot,
    draft_case,
    fetch_block,
    fetch_case,
    fetch_evaluation,
    fetch_lot,
    fetch_permit,
    fetch_practice,
    fetch_reservation,
    file_adverse_event,
    hold_case_on_block,
    record_inspection_result,
    reserve_from_lot,
    schedule_inspection,
    set_env_clock,
    setup_permitted_practice,
    SCHEDULER,
    validate_error,
)

CLOCK = "2026-09-11T10:00:00Z"

# --- critical_inspection_five_hop_suspension_cascade ---------------------------


def _confirmed_case_with_consignment_exposure():
    """A CONFIRMED MODERATE_SEDATION implant case holding two consignment fixtures,
    with a second inspection scheduled and due."""
    env = setup_permitted_practice(
        "MODERATE_SEDATION", clock=CLOCK,
        turnover_buffer_minutes=15, consignment_credit_limit_cents=500000,
    )
    block = create_block(
        env["practice_id"], env["surgeon"]["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z", room_code="OR-1",
    )
    case = draft_case(
        env,
        planned_anesthesia_level="MODERATE_SEDATION",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        procedure_category="IMPLANT",
    )
    hold_case_on_block(case["id"], block["id"])
    set_env_clock(env, "2026-09-14T12:00:00Z")
    evaluation = clear_case(env, case["id"])
    confirm_case(case["id"], block["id"])
    lot = create_lot(
        env["practice_id"], unit_cost_cents=30000, quantity_on_hand=5,
        is_consignment=True, expiry_date="2027-06-30T00:00:00Z",
    )
    reservation = reserve_from_lot(case["id"], lot["id"], quantity=2)
    second = schedule_inspection(env["permit"]["id"], "2026-09-15T10:00:00Z")
    set_env_clock(env, "2026-09-15T10:00:00Z")
    return env, case, block, lot, reservation, evaluation, second


def test_one_critical_deficiency_suspends_the_permit_and_reverts_the_case(api):
    """PRD 3.2: "If `critical_deficiency_count` is one or more, the inspection ends
    `FAILED_CRITICAL` regardless of the score — a single immediate-jeopardy finding
    dominates, so an otherwise pristine facility with one critical deficiency and a
    score of 75 still fails critically."
    PRD 2.10: "Hop two, because the privilege no longer permits sedation, reverts
    every surgical case of that practice whose `scheduling_status` is `CONFIRMED` and
    whose `planned_anesthesia_level` is anything other than `LOCAL_ONLY` back to
    `BLOCK_HELD` and sets its `clearance_status` to `DEFERRED`."
    PRD 3.4: "the block's `committed_minutes` is left alone, because a `BLOCK_HELD`
    case still counts as committed"

    Design: Difficulty/transitive_cascade/critical_inspection_five_hop_suspension_cascade
    """
    env, case, block, lot, reservation, evaluation, second = (
        _confirmed_case_with_consignment_exposure()
    )
    assert reservation["consignment_liability_cents"] == 48000
    assert fetch_practice(env["practice_id"])["consignment_committed_cents"] == 48000

    result = record_inspection_result(second["id"], 0, 0, 1)

    assert result["inspection_score"] == 75
    assert result["status"] == "FAILED_CRITICAL"

    permit = fetch_permit(env["permit"]["id"])
    assert permit["status"] == "SUSPENDED"
    assert permit["last_enforcement_reason"] == "CRITICAL_DEFICIENCY"
    assert fetch_practice(env["practice_id"])["sedation_privilege_state"] == "SUSPENDED"

    reverted = fetch_case(case["id"])
    assert reverted["scheduling_status"] == "BLOCK_HELD", (
        f"the confirmed sedated case reverts one step, got {reverted['scheduling_status']}"
    )
    assert reverted["clearance_status"] == "DEFERRED"

    ledger = fetch_block(block["id"])
    assert ledger["committed_minutes"] == 60, (
        "a BLOCK_HELD case still counts as committed, so the minutes do not move"
    )
    assert float(ledger["utilization_pct"]) == pytest.approx(25.00, abs=0.001)
    assert fetch_evaluation(evaluation["id"])["status"] == "VERIFIED", (
        "the cascade moves the case's clearance, never the evaluation's own status"
    )
    assert fetch_evaluation(evaluation["id"])["final_risk_score"] == pytest.approx(
        20.0, abs=0.01
    )


def test_the_reverted_case_releases_its_fixtures_and_clears_the_exposure(api):
    """PRD 2.10: "Hop three, because those cases left the confirmed roster, moves
    each of their implant reservations still in `HELD` to `RELEASED`, applying the
    tiered restocking fee and dropping the consignment credit to zero."
    PRD 2.10: "Hop four, because those reservations left `HELD`, decrements each
    parent lot's `quantity_reserved` by the released quantity, recomputes that lot's
    `available_quantity`, and increments the lot's `version`."
    PRD 2.10: "Hop five, because reservation liabilities changed, recomputes the
    practice's `consignment_committed_cents`."
    PRD 3.6: "The system-driven releases described in §2.10 and §3.6 — a cancelled
    case, a privilege-driven reversion — apply exactly the same field arithmetic as
    the operator-driven `RELEASED` disposition, restocking fee included; only the
    recall quarantine waives the fee."

    Design: Difficulty/transitive_cascade/critical_inspection_five_hop_suspension_cascade
    """
    env, case, block, lot, reservation, evaluation, second = (
        _confirmed_case_with_consignment_exposure()
    )
    before = fetch_lot(lot["id"])
    assert before["quantity_reserved"] == 2
    assert before["available_quantity"] == 3

    record_inspection_result(second["id"], 0, 0, 1)

    released = fetch_reservation(reservation["id"])
    assert released["status"] == "RELEASED"
    assert released["restocking_fee_cents"] == 6000
    assert released["consignment_credit_cents"] == 0
    assert released["consignment_liability_cents"] == 6000

    after = fetch_lot(lot["id"])
    assert after["quantity_reserved"] == 0
    assert after["quantity_on_hand"] == 5, "a release returns the units to the shelf"
    assert after["available_quantity"] == 5
    assert after["version"] == before["version"] + 1

    assert fetch_practice(env["practice_id"])["consignment_committed_cents"] == 0


# --- sentinel_event_three_hop_probation_cascade --------------------------------

def _cleared_deep_sedation_case():
    """A CLEARED DEEP_SEDATION_GENERAL case under an ACTIVE deep permit, on the
    morning of surgery."""
    env = setup_permitted_practice("DEEP_SEDATION_GENERAL", clock=CLOCK)
    block = create_block(
        env["practice_id"], env["surgeon"]["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z", room_code="OR-1",
    )
    case = draft_case(
        env,
        planned_anesthesia_level="DEEP_SEDATION_GENERAL",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T15:00:00Z",
        procedure_category="ORTHOGNATHIC",
    )
    hold_case_on_block(case["id"], block["id"])
    set_env_clock(env, "2026-09-14T12:00:00Z")
    evaluation = clear_case(env, case["id"])
    return env, case, block, evaluation


def test_a_sentinel_report_puts_the_permit_on_probation_and_restricts_the_office(api):
    """PRD 3.9: "When the practice's permit is `ACTIVE`, the event drives it to
    `PROBATION` with `last_enforcement_reason` `SENTINEL_EVENT`, increases
    `probation_count` by 1, sets `remediation_deadline_at` to the logical clock plus
    30 days, and increments the permit's `version`."
    PRD 3.9: "The cascade then runs in two visible hops: the practice's
    `sedation_privilege_state` becomes `RESTRICTED`, and because the practice is
    restricted, every case of that practice whose `planned_anesthesia_level` is
    `DEEP_SEDATION_GENERAL` and whose `clearance_status` is `CLEARED` moves to
    `clearance_status` `DEFERRED`."

    Design: Difficulty/transitive_cascade/sentinel_event_three_hop_probation_cascade
    """
    env, case, block, evaluation = _cleared_deep_sedation_case()
    assert fetch_case(case["id"])["clearance_status"] == "CLEARED"
    assert evaluation["final_risk_score"] == pytest.approx(26.0, abs=0.01), (
        "20 base points scaled by the DEEP_SEDATION_GENERAL multiplier of 1.3"
    )
    assert evaluation["risk_band"] == "ELEVATED"

    event = file_adverse_event(
        env, case["id"], severity="SENTINEL", event_type="DEATH",
        occurred_at="2026-09-14T11:00:00Z",
    )

    assert event["status"] == "REPORTED"
    assert_instant_equals(
        event["reporting_deadline_at"], "2026-09-15T11:00:00Z",
        f"a SENTINEL deadline is occurred_at plus 24 hours, got {event['reporting_deadline_at']}",
    )
    assert event["late_report"] is False

    permit = fetch_permit(env["permit"]["id"])
    assert permit["status"] == "PROBATION"
    assert permit["last_enforcement_reason"] == "SENTINEL_EVENT"
    assert permit["probation_count"] == 1
    assert_instant_equals(permit["remediation_deadline_at"], "2026-10-14T12:00:00Z")

    practice = fetch_practice(env["practice_id"])
    assert practice["sedation_privilege_state"] == "RESTRICTED", (
        "probation restricts rather than suspends, which is a narrower scope"
    )
    assert practice["open_adverse_event_count"] == 1


def test_the_deferred_deep_case_now_fails_confirmation_on_the_clearance_gate(api):
    """PRD 3.9: "Those cases' `VERIFIED` evaluations keep their own `status` of
    `VERIFIED` — the clinical work stands — but the cases can no longer be confirmed,
    and the confirmation attempt now fails on the clearance gate with
    `ERR_CASE_NOT_CLEARED` rather than on any privilege check."
    PRD 3.4: "Third, the case's `clearance_status` must read exactly `CLEARED`;
    `NOT_EVALUATED`, `EVALUATED`, and `DEFERRED` are all refused with
    `ERR_CASE_NOT_CLEARED` (HTTP 409), which is what a case pushed to `DEFERRED` by a
    privilege cascade will see even though it was confirmable an hour earlier."

    Design: Difficulty/transitive_cascade/sentinel_event_three_hop_probation_cascade
    """
    env, case, block, evaluation = _cleared_deep_sedation_case()
    file_adverse_event(
        env, case["id"], severity="SENTINEL", event_type="DEATH",
        occurred_at="2026-09-14T11:00:00Z",
    )

    deferred = fetch_case(case["id"])
    assert deferred["clearance_status"] == "DEFERRED"
    assert deferred["scheduling_status"] == "BLOCK_HELD", (
        "the probation cascade touches clearance only"
    )
    assert fetch_evaluation(evaluation["id"])["status"] == "VERIFIED"

    response = api_client.confirm_case(
        case["id"], {"expected_block_version": fetch_block(block["id"])["version"]},
        SCHEDULER,
    )
    validate_error(response, "ERR_CASE_NOT_CLEARED", 409)
    assert fetch_case(case["id"])["scheduling_status"] == "BLOCK_HELD"
