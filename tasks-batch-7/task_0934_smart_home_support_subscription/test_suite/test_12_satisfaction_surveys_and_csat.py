"""Satisfaction surveys, the 72-hour window and the two CSAT credit variants."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_same_instant,
    assert_service_credit,
    assert_survey,
    fetch_subscription,
    fetch_ticket,
    find_one,
    first_response,
    list_credits,
    list_surveys,
    new_ticket,
    open_session,
    set_clock,
    setup_account,
    setup_resolved_ticket,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["support_agent_headers"]


def test_a_low_score_on_a_met_ticket_pays_the_pro_goodwill_credit(api):
    """PRD 3.12: "Otherwise, if the household's in-force plan `tier` is `PRO`,
    `credit_variant` is `GOODWILL` and the uncapped amount is `monthly_fee_cents`
    multiplied by 0.05, rounded half up to whole cents."
    PRD 3.12: "A score of 2 or lower is **low**; a score of 3, 4 or 5 is not."
    PRD 3.12: "The created row records its `ticket_id`, the `score`, the `comment`, a
    `submitted_at` stamped with the logical-clock instant, and a `window_closes_at`
    equal to the ticket's `survey_solicited_at` plus 72 hours."
    PRD 3.6: "`applied_to_cycle_index`, which is always the issuing `cycle_index` plus
    one because credits land on the **next** invoice and never on the current one."

    round_half_up(9999 * 0.05) == 500 cents.

    Design: Corner/calculations/csat_goodwill_credit_pays_five_percent_for_a_pro_household_without_a_breach
    """
    world = setup_account(
        plan_kind="PRO", allow_overage=False, name="Csat House", email_prefix="csat"
    )
    ticket = setup_resolved_ticket(world, severity="P2", summary="Scene automation flaky")
    set_clock("2026-05-01T01:00:00Z")

    data = validate_success(
        api.submit_survey(
            ticket["id"],
            {"score": 1, "comment": "Took too many steps."},
            world["owner_headers"],
        ),
        201,
    )

    assert_survey(data)
    assert fetch_ticket(ticket["id"])["sla_status"] == "MET"
    assert data["credit_variant"] == "GOODWILL"
    assert data["credit_cents"] == 500
    assert_same_instant(
        data["window_closes_at"],
        "2026-05-04T00:20:00Z",
        "SatisfactionSurvey.window_closes_at",
    )

    credits = list_credits(ticket_id=ticket["id"])
    assert len(credits) == 1
    assert_service_credit(credits[0])
    assert credits[0]["reason"] == "CSAT_GOODWILL"
    assert credits[0]["amount_cents"] == 500
    assert credits[0]["applied_to_cycle_index"] == 2
    assert (
        fetch_subscription(world["subscription"]["id"])["credits_issued_cents_this_cycle"] == 500
    )


def test_a_low_score_on_a_credited_ticket_stacks_the_compounded_credit(api):
    """PRD 3.12: "Otherwise, if the ticket's SLA axis is breached, `credit_variant` is
    `BREACH_COMPOUNDED` and the uncapped amount is the subscription's
    `monthly_fee_cents` multiplied by 0.10, rounded half up to whole cents. This pays
    ten per cent of the monthly fee **on top of** any SLA breach credit already
    issued this cycle, so the per-cycle cap is what limits the stack."
    PRD 3.12: "The ticket's SLA axis is read at *submission* time, not at resolution
    time, and counts as **breached** when `sla_status` is `BREACHED_FIRST_RESPONSE`,
    `BREACHED_ONSITE` or `CREDITED`."
    PRD 3.6: "a ratio above 0.25 and up to and including 1.00 is a `MAJOR` breach
    carrying fifteen per cent"

    240 counted minutes against the 120-minute P2 target is a ratio of exactly 1.00 —
    MAJOR — paying round_half_up(9999 * 0.15) == 1500; the survey then adds
    round_half_up(9999 * 0.10) == 1000 against a 4999-cent cycle cap.

    Design: Corner/calculations/csat_breach_compounded_credit_stacks_on_top_of_the_sla_credit
    """
    world = setup_account(
        plan_kind="PRO", allow_overage=False, name="Stack House", email_prefix="stk"
    )
    ticket = new_ticket(
        world["household"]["id"],
        world["owner_headers"],
        severity="P2",
        summary="Lock jammed",
        opened_by_member_id=world["owner"]["id"],
    )
    set_clock("2026-05-01T04:00:00Z")
    first_response(ticket["id"], "Late triage.")
    session = open_session(ticket["id"])
    set_clock("2026-05-01T05:00:00Z")
    validate_success(
        api.complete_remote_session(
            session["id"],
            {"outcome": "RESOLVED", "diagnostic_notes": "Motor recalibrated."},
            AGENT,
        ),
        200,
    )
    set_clock("2026-05-01T06:00:00Z")

    survey = validate_success(
        api.submit_survey(ticket["id"], {"score": 2}, world["owner_headers"]), 201
    )

    credits = list_credits(ticket_id=ticket["id"])
    assert len(credits) == 2
    breach_credit = find_one(credits, reason="SLA_FIRST_RESPONSE_BREACH")
    assert breach_credit["breach_tier"] == "MAJOR"
    assert breach_credit["amount_cents"] == 1500

    assert survey["credit_variant"] == "BREACH_COMPOUNDED"
    assert survey["credit_cents"] == 1000

    subscription = fetch_subscription(world["subscription"]["id"])
    assert subscription["credits_issued_cents_this_cycle"] == 2500
    assert subscription["next_invoice_credit_cents"] == 2500


def test_a_second_survey_for_the_same_ticket_is_refused(api):
    """PRD 3.12: "Two rungs guard it: a second submission for the same ticket is
    refused with `ERR_SURVEY_ALREADY_SUBMITTED`"
    PRD 3.12: "If the score is not low, `credit_variant` is `NONE` and the uncapped
    amount is 0."

    Design: Corner/validations/survey_submitted_twice_returns_already_submitted
    """
    world = setup_account(
        plan_kind="PRO", allow_overage=False, name="Twice House", email_prefix="twi"
    )
    ticket = setup_resolved_ticket(world, severity="P2", summary="Quick fix")
    set_clock("2026-05-01T01:00:00Z")
    validate_success(
        api.submit_survey(
            ticket["id"], {"score": 5, "comment": "Great."}, world["owner_headers"]
        ),
        201,
    )

    response = api.submit_survey(ticket["id"], {"score": 1}, world["owner_headers"])
    validate_error(response, ApiErrorId.ERR_SURVEY_ALREADY_SUBMITTED.value, 409)

    surveys = list_surveys(ticket_id=ticket["id"])
    assert len(surveys) == 1
    assert surveys[0]["score"] == 5
    assert surveys[0]["credit_variant"] == "NONE"
    assert (
        fetch_subscription(world["subscription"]["id"])["credits_issued_cents_this_cycle"] == 0
    )


def test_a_survey_at_exactly_seventy_two_hours_finds_the_window_closed(api):
    """PRD 3.12: "and a submission whose ticket has a null `survey_solicited_at`, or
    that arrives at or after `survey_solicited_at` plus 72 hours, is refused with
    `ERR_SURVEY_WINDOW_CLOSED`."
    PRD 3.7: "`survey_solicited_at` is stamped with the same instant **on the first
    resolution only** and is never overwritten by a later re-resolution"

    survey_solicited_at is 2026-05-01T00:20:00Z, so 72 hours later is exactly
    2026-05-04T00:20:00Z — the first instant no longer inside the window.

    Design: Corner/validations/survey_at_exactly_seventy_two_hours_returns_window_closed
    """
    world = setup_account(
        plan_kind="PRO", allow_overage=False, name="Window2 House", email_prefix="win2"
    )
    ticket = setup_resolved_ticket(world, severity="P2", summary="Quick fix")
    set_clock("2026-05-04T00:20:00Z")

    response = api.submit_survey(ticket["id"], {"score": 4}, world["owner_headers"])
    validate_error(response, ApiErrorId.ERR_SURVEY_WINDOW_CLOSED.value, 409)

    assert list_surveys(ticket_id=ticket["id"]) == []
    assert_same_instant(
        fetch_ticket(ticket["id"])["survey_solicited_at"],
        "2026-05-01T00:20:00Z",
        "Ticket.survey_solicited_at",
    )
