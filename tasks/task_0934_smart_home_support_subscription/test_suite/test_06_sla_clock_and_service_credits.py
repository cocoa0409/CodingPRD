"""The SLA clock partition, breach tiers, the credit base and the per-cycle cap."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_service_credit,
    assert_ticket_minute_conservation,
    claim,
    fetch_subscription,
    fetch_ticket,
    find_one,
    first_response,
    list_credits,
    new_ticket,
    open_session,
    set_clock,
    setup_account,
    setup_account_with_catalog,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["support_agent_headers"]


def test_sla_projection_reports_the_partition_and_writes_nothing(api):
    """PRD 3.6: "The read-only projection returns six fields and writes nothing:
    `sla_counted_minutes`, `sla_paused_minutes`, `sla_uncovered_minutes`,
    `total_elapsed_minutes`, `active_target_minutes` and `sla_status`."
    PRD 3.5: "While `first_response_at` is null the active target is
    `first_response_target_minutes`; once `first_response_at` is set the active
    target is `onsite_resolution_target_minutes`."
    PRD 2.4: "Read-only endpoints never bump a version and never refresh
    `updated_at`."

    Design: Corner/endpoints/sla_projection_endpoint_reports_the_partition_without_mutating_the_ticket
    """
    world = setup_account(
        plan_kind="PRO", allow_overage=False, name="Proj House", email_prefix="prj"
    )
    ticket = new_ticket(
        world["household"]["id"],
        world["owner_headers"],
        severity="P2",
        summary="Waiting on triage",
        opened_by_member_id=world["owner"]["id"],
    )
    set_clock("2026-05-01T01:00:00Z")

    data = validate_success(api.get_ticket_sla(ticket["id"], AGENT), 200)

    assert data["sla_counted_minutes"] == 60
    assert data["sla_paused_minutes"] == 0
    assert data["sla_uncovered_minutes"] == 0
    assert data["total_elapsed_minutes"] == 60
    assert data["active_target_minutes"] == 120
    assert data["sla_status"] == "WITHIN"

    current = fetch_ticket(ticket["id"])
    assert current["version"] == 1
    assert current["workflow_status"] == "NEW"


def test_credit_cap_truncates_the_second_credit_and_refuses_the_third(api):
    """PRD 3.6: "The cycle cap is the floor of the subscription's `monthly_fee_cents`
    multiplied by 0.50 — half the monthly fee, rounded down."
    PRD 3.6: "Cap room is the cycle cap less the issued cents, clamped below at 0.
    The credit actually granted, `amount_cents`, is the smaller of the uncapped
    amount and the cap room."
    PRD 3.6: "Unlike the first-response settlement, this endpoint **does** enforce the
    cap rung: when a breach is detected and a credit would be due but the cycle's cap
    room is zero, the request is refused with `ERR_CREDIT_CAP_REACHED` and nothing is
    written."
    PRD 3.6: "a ratio strictly above 1.00 is a `SEVERE` breach carrying thirty per
    cent"

    monthly_fee_cents 1999 gives a cap of floor(999.5) == 999. A first SEVERE breach
    pays round_half_up(1999 * 0.30) == 600; the second's uncapped 600 is truncated to
    the remaining 399; the third finds no room at all.

    Design: Corner/calculations/credit_cap_truncates_the_second_credit_and_rejects_the_third
    """
    world = setup_account(
        plan_kind="BASIC",
        plan_overrides={
            "included_device_count": 2,
            "coverage_mode": "TWENTY_FOUR_SEVEN",
        },
        allow_overage=False,
        name="Cap3 House",
        email_prefix="cap3",
    )
    ticket = new_ticket(
        world["household"]["id"],
        world["owner_headers"],
        severity="P1",
        summary="Whole system down",
        opened_by_member_id=world["owner"]["id"],
    )

    # 540 counted minutes against a 240-minute P1 target: ratio 1.25 -> SEVERE.
    set_clock("2026-05-01T09:00:00Z")
    first_response(ticket["id"], "Very late triage.")

    # 8650 counted minutes against the 4320-minute P1 onsite target -> SEVERE again.
    set_clock("2026-05-07T00:10:00Z")
    validate_success(api.evaluate_sla(ticket["id"], {}, AGENT), 200)

    set_clock("2026-05-08T00:00:00Z")
    response = api.evaluate_sla(ticket["id"], {}, AGENT)
    validate_error(response, ApiErrorId.ERR_CREDIT_CAP_REACHED.value, 409)

    credits = list_credits(subscription_id=world["subscription"]["id"])
    assert len(credits) == 2
    first = find_one(credits, reason="SLA_FIRST_RESPONSE_BREACH")
    second = find_one(credits, reason="SLA_ONSITE_BREACH")
    assert_service_credit(first)
    assert_service_credit(second)
    assert first["breach_tier"] == "SEVERE"
    assert first["uncapped_amount_cents"] == 600
    assert first["amount_cents"] == 600
    assert second["breach_tier"] == "SEVERE"
    assert second["uncapped_amount_cents"] == 600
    assert second["amount_cents"] == 399
    assert (
        fetch_subscription(world["subscription"]["id"])["credits_issued_cents_this_cycle"]
        == 999
    )


# ==========================================================================
# Difficulty: the credit BASE widens on the onsite variant
# ==========================================================================
def _dual_breach_world(api):
    """One P2 ticket that breaches first-response and then the onsite target."""
    world = setup_account_with_catalog(
        "HUB",
        plan_kind="PRO",
        plan_overrides={"included_device_count": 1},
        allow_overage=True,
        name="Alder House",
        email_prefix="alder",
    )
    first_device = claim(
        world["household"]["id"], world["catalog"]["id"], "HBX000001", world["owner_headers"]
    )
    # 30 of 30 cycle days remain, so this overage unit books 299 * 30 / 30 == 299.
    claim(
        world["household"]["id"], world["catalog"]["id"], "HBX000002", world["owner_headers"]
    )
    ticket = new_ticket(
        world["household"]["id"],
        world["owner_headers"],
        severity="P2",
        summary="Hub keeps dropping offline",
        device_id=first_device["id"],
        opened_by_member_id=world["owner"]["id"],
    )

    set_clock("2026-05-01T02:30:00Z")
    validate_success(
        api.first_response(ticket["id"], {"note": "Agent picked up the case."}, AGENT), 200
    )
    set_clock("2026-05-03T02:00:00Z")
    validate_success(api.evaluate_sla(ticket["id"], {}, AGENT), 200)

    world["ticket"] = ticket
    return world


def test_first_response_breach_credit_is_based_on_the_monthly_fee_alone(api):
    """PRD 3.6: "**The credit base is where the two breach kinds diverge.** For a
    first-response breach the base is the subscription's `monthly_fee_cents` alone."
    PRD 3.6: "A ratio of 0.25 or less is a `MINOR` breach carrying a credit of five
    per cent"
    PRD 3.3: "If at least 5 days remain, the charge is the plan's
    `overage_fee_cents_per_device` multiplied by the days remaining, divided by 30,
    rounded half up to whole cents; that amount is added both to
    `overage_charges_cents_this_cycle` and to `next_invoice_adjustment_cents`."

    150 counted minutes against a 120-minute target is a ratio of exactly 0.25 —
    MINOR — so the credit is round_half_up(9999 * 0.05) == 500 cents.

    Design: Difficulty/dual_variant_calc/sla_breach_credit_base_widens_on_onsite_variant
    """
    world = _dual_breach_world(api)

    subscription = fetch_subscription(world["subscription"]["id"])
    assert subscription["overage_charges_cents_this_cycle"] == 299

    credits = list_credits(ticket_id=world["ticket"]["id"])
    first_response_credit = find_one(credits, reason="SLA_FIRST_RESPONSE_BREACH")
    assert_service_credit(first_response_credit)
    assert first_response_credit["breach_tier"] == "MINOR"
    assert first_response_credit["uncapped_amount_cents"] == 500
    assert first_response_credit["amount_cents"] == 500


def test_onsite_breach_credit_adds_the_cycle_overage_to_the_same_tier(api):
    """PRD 3.6: "For an onsite-resolution breach the base is `monthly_fee_cents`
    **plus** `overage_charges_cents_this_cycle`, so the identical breach tier on the
    identical plan yields a strictly larger credit whenever the household has booked
    overage in the current cycle."
    PRD 3.6: "Whenever a credit row is created, its `amount_cents` is added to the
    subscription's `credits_issued_cents_this_cycle` and to its
    `next_invoice_credit_cents`."

    3000 counted minutes against the 2880-minute onsite target is a MINOR ratio, so
    the credit is round_half_up((9999 + 299) * 0.05) == 515 cents — 15 cents more
    than the first-response credit at the identical tier and rate.

    Design: Difficulty/dual_variant_calc/sla_breach_credit_base_widens_on_onsite_variant
    """
    world = _dual_breach_world(api)

    credits = list_credits(ticket_id=world["ticket"]["id"])
    onsite_credit = find_one(credits, reason="SLA_ONSITE_BREACH")
    assert_service_credit(onsite_credit)
    assert onsite_credit["breach_tier"] == "MINOR"
    assert onsite_credit["uncapped_amount_cents"] == 515
    assert onsite_credit["amount_cents"] == 515

    subscription = fetch_subscription(world["subscription"]["id"])
    assert subscription["credits_issued_cents_this_cycle"] == 1015
    assert subscription["next_invoice_credit_cents"] == 1015
    assert fetch_ticket(world["ticket"]["id"])["sla_status"] == "CREDITED"


# ==========================================================================
# Difficulty: the minute partition is conserved across a pause and a resume
# ==========================================================================
def _business_hours_pause_world(api):
    world = setup_account(
        plan_kind="PLUS",
        allow_overage=False,
        name="Clock House",
        email_prefix="clk",
        clock="2026-05-01T08:00:00Z",
    )
    ticket = new_ticket(
        world["household"]["id"],
        world["owner_headers"],
        severity="P2",
        summary="Lock will not pair",
        opened_by_member_id=world["owner"]["id"],
    )
    set_clock("2026-05-01T09:30:00Z")
    first_response(ticket["id"], "Triaged.")
    open_session(ticket["id"])
    set_clock("2026-05-01T10:00:00Z")
    validate_success(
        api.await_customer(
            ticket["id"], {"note": "Waiting on the customer's router details."}, AGENT
        ),
        200,
    )
    set_clock("2026-05-01T18:00:00Z")
    validate_success(
        api.customer_reply(
            ticket["id"], {"message": "Router details attached."}, world["owner_headers"]
        ),
        200,
    )
    world["ticket"] = ticket
    return world


def test_business_hours_partition_after_a_resume_splits_600_minutes_exactly(api):
    """PRD 3.6: "When the `coverage_mode` is `BUSINESS_HOURS`, a minute counts only
    when its UTC minute-of-day is at or after minute 540 of the day — 09:00 UTC —
    and strictly before minute 1020 — 17:00 UTC."
    PRD 3.6: "A minute is classified **paused** when it lies inside one of the
    ticket's customer-wait segments. Segments are half-open, running from a
    `pause_started_at` instant up to but not including the resuming reply instant"
    PRD 3.6: "Failing that, a minute is classified **uncovered** when the plan's
    coverage window does not contain it. Everything else is classified **counted**."

    08:00 to 09:00 is uncovered (60), 09:00 to 10:00 is counted (60) and 10:00 to
    18:00 is one pause segment (480).

    Design: Difficulty/compensating_invariant/sla_minute_partition_conserved_across_pause_and_resume
    """
    world = _business_hours_pause_world(api)

    ticket = fetch_ticket(world["ticket"]["id"])
    assert ticket["sla_paused_minutes"] == 480
    assert ticket["sla_uncovered_minutes"] == 60
    assert ticket["sla_counted_minutes"] == 60
    assert ticket["sla_status"] == "WITHIN"
    assert ticket.get("pause_started_at") is None


def test_pause_and_resume_neither_create_nor_destroy_ticket_minutes(api):
    """PRD 2.10: "For any evaluation instant, `sla_counted_minutes` plus
    `sla_paused_minutes` plus `sla_uncovered_minutes` equals the whole minutes
    elapsed from the ticket's `created_at` to that instant, obtained by floor
    division."
    PRD 2.10: "Parking a ticket on the customer and then receiving the customer's
    reply moves minutes from the counted bucket to the paused bucket; it must never
    create or destroy minutes."

    Design: Difficulty/compensating_invariant/sla_minute_partition_conserved_across_pause_and_resume
    """
    world = _business_hours_pause_world(api)

    projection = validate_success(api.get_ticket_sla(world["ticket"]["id"], AGENT), 200)
    assert projection["total_elapsed_minutes"] == 600

    ticket = fetch_ticket(world["ticket"]["id"])
    assert_ticket_minute_conservation(ticket, 600)
