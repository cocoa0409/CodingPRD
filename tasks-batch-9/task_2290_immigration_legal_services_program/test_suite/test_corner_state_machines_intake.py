"""State-machine coverage of the IntakeScreening lifecycle and its cycle effects.

The screening is the only door into the system: nothing is computed before the
screen step, every decision branch departs from `SCREENED` alone, and the three
terminal branches differ sharply in what they leave behind. These tests walk the
transition table one edge at a time, including the edges that are absent from it.

Each test translates exactly one instance of section 1.9 `state_machines`.
"""

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_INTAKE_NOT_ACCEPTED,
    ERR_INVALID_STATE_TRANSITION,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_error,
    assert_fields,
    assert_no_rows,
    assert_null_fields,
    assert_slot_conservation,
    created,
    ok,
    only_row,
)
from test_helpers.fixtures import create_client, minimal_world, template_a

_CLOCK_UTC = "2026-08-03T09:00:00.000Z"


def _world(api, **overrides):
    """The minimal cycle-plus-two-attorneys world every recipe here starts from."""
    settings = {
        "clock": _CLOCK_UTC,
        "cycle_label": "FY26-H2",
        "period_start_date": "2026-07-01",
        "period_end_date": "2026-12-31",
        "total_case_slots": 10,
        "reserved_detained_slots": 2,
        "languages": ["en", "es"],
    }
    settings.update(overrides)
    return minimal_world(api, **settings)


def _screening(env, **overrides):
    """Open one screening for a fresh Rosa Mena, as the screener."""
    client = create_client(env, **overrides.pop("client_overrides", {}))
    env["client_id"] = client["id"]
    intake = created(
        env.api.create_intake(
            factories.intake_payload(client["id"], env["cycle_id"], **overrides),
            headers=env.screener,
        )
    )
    env["intake_id"] = intake["id"]
    return intake


def test_a_new_screening_is_a_draft_with_nothing_computed_yet(api):
    """Creation records the request and computes none of the derived verdicts.

    The eligibility verdict and the whole urgency triple stay null until the
    screen step runs, and the cycle has not been touched at all.

    Design: Corner/state_machines/intake_screening_starts_in_draft_with_null_computed_verdict
    """
    env = _world(api)
    intake = _screening(env)
    # PRD 3.3: "A newly created screening carries legal_eligibility_verdict of
    # PENDING, no urgency_score, no urgency_tier and no urgency_variant_applied."
    assert_fields(
        intake,
        status="DRAFT",
        case_type="U_VISA",
        detained=False,
        legal_eligibility_verdict="PENDING",
    )
    assert_null_fields(
        intake,
        "urgency_score",
        "urgency_tier",
        "urgency_variant_applied",
    )
    cycle = env.cycle()
    assert_fields(cycle, available_slot_count=10, total_case_slots=10)
    assert_slot_conservation(cycle)


def test_screening_stamps_the_screener_the_clock_the_verdict_and_the_urgency_triple(api):
    """One transition writes five fields at once.

    A non-detained U_VISA with no statutory deadline scores its 22.00 base with a
    zero horizon and no anchor at all, landing in the routine tier under the
    strict-statutory variant.

    Design: Corner/state_machines/intake_screen_records_screener_and_all_four_urgency_fields
    """
    env = _world(api)
    intake = _screening(env)
    screened = ok(api.screen_intake(intake["id"], headers=env.screener))
    assert_fields(
        screened,
        status="SCREENED",
        screener_representative_id=env["screener_id"],
        screened_at_utc=_CLOCK_UTC,
        legal_eligibility_verdict="ELIGIBLE",
        urgency_variant_applied="STRICT_STATUTORY",
        urgency_tier="ROUTINE",
    )
    assert_null_fields(screened, "urgency_anchor_date")
    assert_decimal_equals(screened["urgency_score"], "22.00", 2)
    # income 2000000 against a household-of-three guideline of 2572000
    assert_decimal_equals(env.client_row()["fpl_percent"], "77.76", 2)


def test_deciding_an_unscreened_row_is_refused_and_mints_no_matter(api):
    """Every decision branch departs from `SCREENED`, so a draft has no edge.

    Design: Corner/state_machines/intake_decide_from_draft_returns_invalid_state_transition
    """
    env = _world(api)
    intake = _screening(env)
    assert_error(
        api.decide_intake(
            intake["id"],
            {"decision": "ACCEPT", "decision_reason_code": "ACCEPTED_ON_MERIT"},
            headers=env.supervisor,
        ),
        # PRD 3.4: "Deciding a screening that is not in SCREENED -- with the single
        # exception of promotion described below -- is rejected with
        # ERR_INTAKE_NOT_ACCEPTED (HTTP 409)."
        ERR_INTAKE_NOT_ACCEPTED,
    )
    assert_fields(env.intake(intake["id"]), status="DRAFT")
    assert_no_rows(
        api.list_matters(params={"intake_id": intake["id"]}, headers=env.director)
    )
    assert_fields(env.cycle(), available_slot_count=10)


def test_a_declined_screening_is_terminal_and_cannot_be_withdrawn(api):
    """Withdrawal reaches four states, and `DECLINED` is not one of them.

    The refusal must leave the decline's own reason code in place rather than
    overwriting it with the withdrawal's.

    Design: Corner/state_machines/declined_intake_is_terminal_and_rejects_withdraw
    """
    env = _world(api)
    intake = _screening(env)
    ok(api.screen_intake(intake["id"], headers=env.screener))
    ok(
        api.decide_intake(
            intake["id"],
            {"decision": "DECLINE", "decision_reason_code": "NO_LEGAL_RELIEF"},
            headers=env.supervisor,
        )
    )
    assert_error(
        api.withdraw_intake(intake["id"], headers=env.screener),
        ERR_INVALID_STATE_TRANSITION,
    )
    assert_fields(
        env.intake(intake["id"]),
        status="DECLINED",
        decision_reason_code="NO_LEGAL_RELIEF",
    )


def test_the_decline_branch_mints_no_matter_and_consumes_no_slot(api):
    """Declining writes only the decision fields.

    Design: Corner/state_machines/intake_decline_branch_creates_no_matter_and_consumes_no_slot
    """
    env = _world(api)
    intake = _screening(env)
    ok(api.screen_intake(intake["id"], headers=env.screener))
    declined = ok(
        api.decide_intake(
            intake["id"],
            {"decision": "DECLINE", "decision_reason_code": "CONFLICT_OF_INTEREST"},
            headers=env.supervisor,
        )
    )
    assert_fields(
        declined,
        status="DECLINED",
        decided_by_representative_id=env["atty_b_id"],
        decided_at_utc=_CLOCK_UTC,
        decision_reason_code="CONFLICT_OF_INTEREST",
    )
    assert_no_rows(
        api.list_matters(params={"intake_id": intake["id"]}, headers=env.director)
    )
    cycle = env.cycle()
    assert_fields(cycle, available_slot_count=10, general_slots_consumed=0)
    assert_decimal_equals(cycle["utilization_ratio"], "0.0000", 4)
    assert_fields(env.client_row(), open_matter_count=0)


def test_referring_out_without_a_partner_code_is_a_shape_failure(api):
    """Only the referral branch demands a partner code, and it demands it strictly.

    Design: Corner/state_machines/intake_refer_out_without_partner_code_returns_validation
    """
    env = _world(api)
    intake = _screening(env)
    ok(api.screen_intake(intake["id"], headers=env.screener))
    assert_error(
        api.decide_intake(
            intake["id"],
            {"decision": "REFER_OUT", "decision_reason_code": "OUTSIDE_SERVICE_AREA"},
            headers=env.supervisor,
        ),
        ERR_VALIDATION,
    )
    unchanged = env.intake(intake["id"])
    assert_fields(unchanged, status="SCREENED")
    assert_null_fields(unchanged, "referral_partner_code")


def test_accepting_mints_the_matter_copies_its_fields_and_moves_the_cycle(api):
    """One acceptance writes across the screening, a new matter, the cycle and the client.

    Design: Corner/state_machines/intake_accept_mints_matter_with_copied_fields_and_recomputes_cycle
    """
    env = _world(api)
    intake = _screening(env)
    ok(api.screen_intake(intake["id"], headers=env.screener))
    accepted = ok(
        api.decide_intake(
            intake["id"],
            {"decision": "ACCEPT", "decision_reason_code": "ACCEPTED_ON_MERIT"},
            headers=env.supervisor,
        )
    )
    assert_fields(accepted, status="ACCEPTED")

    matter = only_row(
        api.list_matters(params={"intake_id": intake["id"]}, headers=env.director)
    )
    assert_fields(
        matter,
        client_id=env["client_id"],
        intake_id=intake["id"],
        cycle_id=env["cycle_id"],
        case_type="U_VISA",
        detained=False,
        representation_status="UNSTAFFED",
        filing_status="PRE_FILING",
        slot_pool_consumed="GENERAL",
        forum="USCIS",
    )
    assert_null_fields(matter, "principal_matter_id")
    cycle = env.cycle()
    assert_fields(
        cycle,
        general_slots_consumed=1,
        detained_slots_consumed=0,
        available_slot_count=9,
        capacity_posture="OPEN",
    )
    assert_decimal_equals(cycle["utilization_ratio"], "0.1000", 4)
    assert_slot_conservation(cycle)
    assert_fields(env.client_row(), open_matter_count=1)


def test_waitlisting_takes_a_rank_and_a_thirty_day_window_but_no_slot(api):
    """The waitlist branch is the one decision that leaves capacity alone.

    Design: Corner/state_machines/intake_waitlist_sets_rank_one_and_thirty_day_ttl
    """
    env = _world(api)
    intake = _screening(env)
    ok(api.screen_intake(intake["id"], headers=env.screener))
    waitlisted = ok(
        api.decide_intake(
            intake["id"],
            {"decision": "WAITLIST", "decision_reason_code": "CAPACITY_FULL"},
            headers=env.supervisor,
        )
    )
    assert_fields(
        waitlisted,
        status="WAITLISTED",
        waitlist_rank=1,
        # the logical clock plus exactly 30 days
        waitlist_expires_at_utc="2026-09-02T09:00:00.000Z",
    )
    cycle = env.cycle()
    assert_fields(cycle, waitlisted_count=1, available_slot_count=10)
    assert_decimal_equals(cycle["utilization_ratio"], "0.0000", 4)
    assert_no_rows(
        api.list_matters(params={"intake_id": intake["id"]}, headers=env.director)
    )


def _waitlist_one(env):
    """Screen and waitlist a single intake, returning it."""
    intake = _screening(env)
    ok(env.api.screen_intake(intake["id"], headers=env.screener))
    row = ok(
        env.api.decide_intake(
            intake["id"],
            {"decision": "WAITLIST", "decision_reason_code": "CAPACITY_FULL"},
            headers=env.supervisor,
        )
    )
    assert_fields(row, status="WAITLISTED", waitlist_expires_at_utc="2026-09-02T09:00:00.000Z")
    return row


def test_the_sweep_expires_a_window_that_closes_on_the_same_instant_it_runs(api):
    """Expiry runs strictly before promotion, so a free slot cannot save the row.

    Design: Corner/state_machines/checkpoint_expires_waitlist_before_promotion_even_with_free_slots
    """
    env = _world(api)
    intake = _waitlist_one(env)
    ok(api.set_clock("2026-09-02T09:00:00.000Z", headers=env.director))

    ok(api.checkpoint_cycle(env["cycle_id"], headers=env.director))
    expired = env.intake(intake["id"])
    assert_fields(expired, status="WAITLIST_EXPIRED")
    assert_null_fields(expired, "waitlist_rank")
    assert_no_rows(
        api.list_matters(params={"intake_id": intake["id"]}, headers=env.director)
    )
    cycle = env.cycle()
    assert_fields(
        cycle,
        waitlisted_count=0,
        available_slot_count=10,
        # the cycle was created at epoch 1; one sweep advances it
        checkpoint_epoch=2,
        last_checkpoint_utc="2026-09-02T09:00:00.000Z",
    )


def test_the_sweep_promotes_the_same_row_a_day_before_its_window_closes(api):
    """One day earlier the identical sweep promotes instead of expiring.

    Promotion is the system actor's own act: it clears both waitlist fields and
    overwrites the capacity reason code with an acceptance on merit.

    Design: Corner/state_machines/checkpoint_promotes_unexpired_waitlisted_row_and_mints_matter
    """
    env = _world(api)
    intake = _waitlist_one(env)
    ok(api.set_clock("2026-09-01T09:00:00.000Z", headers=env.director))

    ok(api.checkpoint_cycle(env["cycle_id"], headers=env.director))
    promoted = env.intake(intake["id"])
    assert_fields(
        promoted,
        status="ACCEPTED",
        decision_reason_code="ACCEPTED_ON_MERIT",
        decided_at_utc="2026-09-01T09:00:00.000Z",
    )
    assert_null_fields(promoted, "waitlist_rank", "waitlist_expires_at_utc")
    matter = only_row(
        api.list_matters(params={"intake_id": intake["id"]}, headers=env.director)
    )
    assert_fields(matter, slot_pool_consumed="GENERAL")
    cycle = env.cycle()
    assert_fields(
        cycle, general_slots_consumed=1, available_slot_count=9, waitlisted_count=0
    )
    assert_fields(env.client_row(), open_matter_count=1)


def test_withdrawing_an_accepted_screening_reverses_every_acceptance_effect(api):
    """The compensating withdrawal unwinds four entities in one request.

    The matter closes with no filing, the active lead is released with the
    client's own reason code, the representative's caseload returns to zero, and
    the cycle's five capacity values land exactly where they stood before the
    acceptance, because no waitlisted row exists to absorb the freed slot.

    Design: Corner/state_machines/withdraw_accepted_intake_restores_slot_partition_and_releases_assignments
    """
    env = template_a(api, clock=_CLOCK_UTC)
    assert_fields(env.cycle(), general_slots_consumed=1, available_slot_count=9)

    withdrawn = ok(api.withdraw_intake(env["intake_id"], headers=env.screener))
    assert_fields(
        withdrawn, status="WITHDRAWN", decision_reason_code="CLIENT_WITHDREW"
    )
    assert_fields(
        env.matter(),
        representation_status="WITHDRAWN_FROM",
        filing_status="CLOSED_NO_FILING",
        outcome="WITHDRAWN",
        closed_at_utc=_CLOCK_UTC,
    )
    assert_fields(
        env.assignment(env["lead_id"]),
        status="RELEASED",
        release_reason_code="CLIENT_WITHDREW",
    )
    assert_fields(env.representative(env["atty_a_id"]), active_case_load=0)
    cycle = env.cycle()
    assert_fields(
        cycle,
        general_slots_consumed=0,
        detained_slots_consumed=0,
        available_slot_count=10,
        capacity_posture="OPEN",
    )
    assert_decimal_equals(cycle["utilization_ratio"], "0.0000", 4)
    assert_slot_conservation(cycle)
    assert_fields(env.client_row(), open_matter_count=0, status="CLOSED")
