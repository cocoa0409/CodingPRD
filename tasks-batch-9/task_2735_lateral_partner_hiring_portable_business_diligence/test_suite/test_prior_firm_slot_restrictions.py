"""The two prior-firm guards on a cross-selling slot: the non-solicitation embargo and
the confidential-approach restriction."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    create_introduction_payload,
    read_candidate,
    read_client_book_entry,
    read_integration_plan,
    setup_active_plan,
    validate_error,
    validate_success,
)


def test_the_embargo_bars_an_early_slot_and_admits_the_one_that_lands_on_the_boundary():
    """First, non-solicitation: `slot_start_at` must fall at or after the candidate's
    `resignation_date` advanced by `non_solicit_days` days, since until that moment the
    partner is contractually barred from soliciting prior-firm clients; an earlier slot is
    refused with `ERR_NON_SOLICIT_RESTRICTION`.
    A scheduled slot lands with `status` `PROPOSED` and `completed_at` null, and increments
    the plan's `introduction_count` by 1 along with the plan's `version`.

    Design: Corner/validations/non_solicit_window_blocks_an_early_slot_and_admits_the_boundary_slot
    """
    ctx = setup_active_plan(
        "SLIM",
        plan_overrides={
            "onboarding_start_date": "2026-08-31T00:00:00.000Z",
            "onboarding_end_date": "2027-06-30T00:00:00.000Z",
        },
        cand_overrides={"notice_period_days": 30, "non_solicit_days": 120},
    )
    plan_id = ctx["plan"]["id"]
    assert ctx["plan"]["introduction_count"] == 0

    candidate = read_candidate(ctx["candidate"]["id"])
    assert_instant_equals(
        candidate["resignation_date"], "2026-08-01T00:00:00.000Z", "resignation_date"
    )
    assert_instant_equals(
        candidate["earliest_start_date"], "2026-08-31T00:00:00.000Z", "earliest_start_date"
    )
    assert candidate["non_solicit_days"] == 120

    early = api_client.create_introduction(
        plan_id,
        create_introduction_payload(
            slot_start_at="2026-09-15T09:00:00.000Z",
            slot_end_at="2026-09-15T10:00:00.000Z",
        ),
        ctx["leader_headers"],
    )
    validate_error(early, ApiErrorId.ERR_NON_SOLICIT_RESTRICTION.value)

    boundary = validate_success(
        api_client.create_introduction(
            plan_id,
            create_introduction_payload(
                slot_start_at="2026-11-29T09:00:00.000Z",
                slot_end_at="2026-11-29T10:00:00.000Z",
            ),
            ctx["leader_headers"],
        ),
        expected_status=201,
    )
    assert boundary["status"] == "PROPOSED"
    assert boundary["completed_at"] is None
    assert_instant_equals(
        boundary["slot_start_at"], "2026-11-29T09:00:00.000Z", "slot_start_at"
    )

    plan = read_integration_plan(plan_id)
    assert plan["introduction_count"] == 1
    assert plan["completed_introduction_count"] == 0


def test_a_consent_pending_client_is_off_limits_while_a_confirmed_one_takes_the_same_slot():
    """Second, the confidential approach: when the candidate's `approach_confidential` is
    true, the `target_client_name` must not equal the `client_name` of any `ACTIVE` client
    book entry on that candidate's questionnaire whose `client_consent_status` is
    `CONSENT_PENDING`.
    A client whose `client_consent_status` is `CONSENT_CONFIRMED` is fair game, and so is
    any client not on the disclosed book at all.

    Design: Corner/validations/consent_pending_prior_firm_client_is_off_limits_while_the_approach_is_confidential
    """
    ctx = setup_active_plan("AB")
    plan_id = ctx["plan"]["id"]

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["approach_confidential"] is True
    assert candidate["pipeline_status"] == "HIRED"

    entry_b = read_client_book_entry(ctx["entries"]["Calder Manufacturing"]["id"])
    assert entry_b["client_consent_status"] == "CONSENT_PENDING"
    assert entry_b["status"] == "ACTIVE"

    pending = api_client.create_introduction(
        plan_id,
        create_introduction_payload(target_client_name="Calder Manufacturing"),
        ctx["leader_headers"],
    )
    validate_error(pending, ApiErrorId.ERR_CONFIDENTIAL_APPROACH_RESTRICTION.value)

    confirmed = validate_success(
        api_client.create_introduction(
            plan_id,
            create_introduction_payload(target_client_name="Northwind Holdings"),
            ctx["leader_headers"],
        ),
        expected_status=201,
    )
    assert confirmed["target_client_name"] == "Northwind Holdings"
    assert confirmed["status"] == "PROPOSED"

    assert read_integration_plan(plan_id)["introduction_count"] == 1
