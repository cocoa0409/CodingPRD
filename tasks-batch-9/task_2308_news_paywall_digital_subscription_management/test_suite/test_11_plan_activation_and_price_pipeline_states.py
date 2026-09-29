"""The one-way activation door and the three-step regulated increase pipeline."""

from test_helpers import (
    OFFICER_ONE_HEADERS,
    OFFICER_TWO_HEADERS,
    REVENUE_MANAGER_HEADERS,
    api_client,
    create_active_plan,
    dispatch_notices,
    read_plan,
    schedule_price_change,
    set_clock_date,
    validate_error,
    validate_success,
)
from test_helpers import factories as f


def test_a_fresh_plan_sits_in_draft_with_an_untouched_price_pipeline():
    """Both plan dimensions start at their declared initial states, with no pending price.

    PRD: "A newly authored plan is born in `status` `DRAFT`, with `active_subscription_count` at 0 and its `price_change_state` at `NONE`."
    PRD: "Raising a standard price is a three-step regulated pipeline across two different desks, and the plan's `price_change_state` is the pipeline's memory."

    Design: Corner/state_machines/offer_plan_starts_in_draft_status
    """
    set_clock_date("2026-09-01")

    created = validate_success(
        api_client.create_offer_plan(
            f.create_offer_plan_payload(name="Digital Initial"), REVENUE_MANAGER_HEADERS
        ),
        201,
    )

    plan = read_plan(created["id"])
    assert plan["status"] == "DRAFT"
    assert plan["price_change_state"] == "NONE"
    assert plan["pending_price_cents"] is None
    assert plan["notice_sent_on"] is None


def test_activation_flips_the_plan_to_active_and_bumps_only_its_own_version():
    """The activation call is a mutation, so version goes 1 to 2 and the pipeline waits.

    PRD: "Activation is the one-way door: a `RevenueManager` moves the plan `DRAFT → ACTIVE`, which re-runs the ladder monotonicity check and increments the plan's `version`."
    PRD: "Draft plans are fully authored but not sellable; only a plan whose `status` is `ACTIVE` may take a new subscription, fund a group account, or receive a scheduled price change, and an attempt to do any of those against a `DRAFT` plan answers `ERR_PLAN_NOT_ACTIVE`."

    Design: Corner/state_machines/offer_plan_activate_moves_draft_to_active
    """
    set_clock_date("2026-09-01")
    created = validate_success(
        api_client.create_offer_plan(
            f.create_offer_plan_payload(name="Digital Activate"),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )
    assert created["version"] == 1

    activated = validate_success(
        api_client.activate_offer_plan(created["id"], REVENUE_MANAGER_HEADERS), 200
    )

    assert activated["status"] == "ACTIVE"
    assert activated["version"] == 2
    assert activated["price_change_state"] == "NONE"


def test_activating_an_already_active_plan_is_refused_and_costs_no_version():
    """ACTIVE absorbs, so the second call is a conflict rather than a silent no-op.

    PRD: "`ACTIVE` is absorbing on that dimension — plans are never closed and never reopened — so activating a plan whose `status` is already `ACTIVE` answers `ERR_PLAN_ALREADY_ACTIVE`."

    Design: Corner/state_machines/offer_plan_activate_twice_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Twice")
    assert plan["version"] == 2

    response = api_client.activate_offer_plan(plan["id"], REVENUE_MANAGER_HEADERS)

    validate_error(response, "ERR_PLAN_ALREADY_ACTIVE", 409)
    after = read_plan(plan["id"])
    assert after["status"] == "ACTIVE"
    assert after["version"] == 2


def test_notices_cannot_be_dispatched_when_no_increase_has_been_scheduled():
    """There is no edge from NONE to NOTICE_SENT, so the officer's call is refused.

    PRD: "Each step requires the pipeline to be in the state that step expects — `NONE` to schedule, `SCHEDULED` to dispatch notices, and either `SCHEDULED` or `NOTICE_SENT` to apply — and a step attempted out of turn answers `ERR_PRICE_CHANGE_STATE_INVALID`."
    PRD: "Only a `ComplianceOfficer` may dispatch the regulated advance notices, moving the pipeline `SCHEDULED → NOTICE_SENT`."

    Design: Corner/state_machines/price_change_notices_without_scheduled_change_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital NoChange")

    response = api_client.dispatch_price_change_notices(plan["id"], OFFICER_ONE_HEADERS)

    validate_error(response, "ERR_PRICE_CHANGE_STATE_INVALID", 409)
    after = read_plan(plan["id"])
    assert after["price_change_state"] == "NONE"
    assert after["notice_sent_on"] is None


def test_apply_on_a_merely_scheduled_change_is_stopped_by_the_notice_requirement():
    """SCHEDULED passes the pipeline-state gate and is then caught by the regulation.

    PRD: "Notices must actually have been dispatched — a non-null `notice_sent_on` — otherwise `ERR_PRICE_NOTICE_NOT_SENT`."
    PRD: "Second, the pipeline-state check on the apply step admits a plan whose price-change pipeline is either `SCHEDULED` or `NOTICE_SENT`; a plan still merely `SCHEDULED` therefore passes that check and is refused by the notices-not-sent rule instead, which is the only way `ERR_PRICE_NOTICE_NOT_SENT` is ever reachable."

    Design: Corner/state_machines/price_change_apply_without_notices_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital NoNotice")
    schedule_price_change(plan["id"], 1799, "2026-10-01", "NONE")

    response = api_client.apply_price_change(plan["id"], OFFICER_TWO_HEADERS)

    validate_error(response, "ERR_PRICE_NOTICE_NOT_SENT", 409)
    after = read_plan(plan["id"])
    assert after["price_change_state"] == "SCHEDULED"
    assert after["standard_price_cents"] == 1499
    assert after["pending_price_cents"] == 1799


def test_a_noticed_increase_cannot_be_applied_a_day_before_it_becomes_effective():
    """Every other guard is satisfied on 2026-09-30; only the calendar refuses.

    PRD: "The clock date must be on or after `pending_effective_on`, otherwise `ERR_PRICE_CHANGE_NOT_EFFECTIVE_YET`."
    PRD: "Dispatch sets `notice_sent_on` to the clock date, records the acting `X-User-ID` in `notice_sent_by_user_id`, and creates one reader event of type `PRICE_INCREASE_NOTICE` — carrying a `weight` of 0, so notices never move an engagement score — for each reader holding a subscription on this plan whose `lifecycle_status` is `PENDING_ACTIVATION`, `ACTIVE`, `PAUSED` or `CANCEL_SCHEDULED`."

    Design: Corner/state_machines/price_change_apply_before_effective_date_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Early")
    schedule_price_change(plan["id"], 1799, "2026-10-01", "NONE")
    dispatch_notices(plan["id"], OFFICER_ONE_HEADERS)
    set_clock_date("2026-09-30")

    response = api_client.apply_price_change(plan["id"], OFFICER_TWO_HEADERS)

    validate_error(response, "ERR_PRICE_CHANGE_NOT_EFFECTIVE_YET", 409)
    after = read_plan(plan["id"])
    assert after["price_change_state"] == "NOTICE_SENT"
    assert after["standard_price_cents"] == 1499
    assert after["notice_sent_on"] == "2026-09-01"


def test_applying_on_the_effective_date_overwrites_the_standard_price_and_clears_pending():
    """A second officer closes the pipeline: 1799 becomes the standard price for good.

    PRD: "In the first hop, `standard_price_cents` is overwritten with `pending_price_cents` and `price_change_state` becomes `APPLIED`."
    PRD: "And the officer applying the increase must not be the officer who noticed it: the acting `X-User-ID` must differ from `notice_sent_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/state_machines/price_change_apply_updates_standard_price_and_clears_pending
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Apply")
    schedule_price_change(plan["id"], 1799, "2026-10-01", "NONE")
    dispatch_notices(plan["id"], OFFICER_ONE_HEADERS)
    set_clock_date("2026-10-01")

    applied = validate_success(
        api_client.apply_price_change(plan["id"], OFFICER_TWO_HEADERS), 200
    )

    assert applied["price_change_state"] == "APPLIED"
    after = read_plan(plan["id"])
    assert after["standard_price_cents"] == 1799
    assert after["price_change_state"] == "APPLIED"
    assert after["notice_sent_on"] == "2026-09-01"
