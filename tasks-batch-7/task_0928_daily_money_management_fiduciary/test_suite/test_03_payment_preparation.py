"""Preparing a disbursement: the fee band, the two settlement-date variants,
referential integrity and the duplicate-payment buffer."""

from test_helpers import (
    ApiErrorId,
    account_version,
    api_client,
    assert_payment,
    assert_same_instant,
    payment_request,
    read_account,
    read_bond,
    read_budget_category,
    read_payment,
    release_payment,
    schedule_payment,
    set_clock,
    setup_billpay_world,
    TEST_USERS,
    list_payments,
    validate_error,
    validate_success,
)

SPECIALIST = TEST_USERS["bill_pay_specialist_headers"]

UNUSED_PAYEE_UUID = "11111111-2222-4333-8444-555555555555"


def test_the_projected_settlement_date_is_computed_and_fixed_at_creation():
    """PRD §3.3: "*Stage three, the business-day lead.* Each channel carries a
    lead time counted in business days: `CHECK` takes 5, `ACH` takes 2, and
    `BILLER_DIRECT` takes 0. The **submit date itself is not counted** — it is
    day zero, and the lead advances from it."
    PRD §3.3: "A principal from 50000 cents up to but not including 250000
    cents carries 500 cents."

    Design: Difficulty/dual_variant_calc/payment_settlement_projected_vs_effective_diverge
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")

    payment = schedule_payment(world, amount_cents=80000, channel="ACH")

    assert_payment(payment)
    assert payment["projected_settlement_date"] == "2026-06-03"
    assert payment["effective_settlement_date"] is None
    assert payment["service_fee_cents"] == 500
    assert payment["total_charge_cents"] == 80500
    assert payment["approval_status"] == "APPROVED"
    assert payment["settlement_status"] == "SCHEDULED"


def test_release_writes_a_strictly_later_effective_settlement_date():
    """PRD §3.4: "The effective variant runs the same three stages as the
    projection, but at the release instant and **with `requested_send_date`
    treated as absent**, so the starting date is the release instant's own
    calendar date and the cut-off test always applies."
    PRD §3.4: "`projected_settlement_date` is deliberately left untouched, so
    the two figures can be compared afterwards: a payment released on a later
    day, or on the same day but at or after the 16:00:00 UTC cut-off, carries
    an effective date strictly later than its projection."

    Design: Difficulty/dual_variant_calc/payment_settlement_projected_vs_effective_diverge
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    payment = schedule_payment(world, amount_cents=80000, channel="ACH")

    set_clock("2026-06-03T16:00:00Z")
    released = release_payment(payment["id"])

    assert released["settlement_status"] == "IN_FLIGHT"
    assert released["approval_status"] == "APPROVED"
    assert released["projected_settlement_date"] == "2026-06-03"
    assert released["effective_settlement_date"] == "2026-06-08"
    assert_same_instant(
        released["released_at"], "2026-06-03T16:00:00Z", "Payment.released_at"
    )


def test_the_cutoff_the_weekend_roll_and_the_check_lead_compose():
    """PRD §3.3: "If that starting date is the same calendar date as the
    evaluation instant **and** the evaluation instant's time of day is at or
    after 16:00:00 UTC, advance the date by one calendar day."
    PRD §3.3: "*Stage two, the weekend roll.* While the resulting date falls on
    a Saturday or a Sunday, advance it one calendar day at a time until it
    lands on a Monday through Friday."

    Design: Difficulty/combinatorial_formula/settlement_cutoff_weekend_and_channel_interact_mode_a
    """
    world = setup_billpay_world(clock_iso="2026-06-05T16:00:00Z")

    payment = schedule_payment(world, amount_cents=40000, channel="CHECK")

    # Friday 2026-06-05 at exactly the cut-off rolls to Saturday 06-06, the
    # weekend roll carries it to Monday 06-08, and five business days land on
    # Monday 2026-06-15.
    assert payment["projected_settlement_date"] == "2026-06-15"
    assert payment["service_fee_cents"] == 250
    assert payment["total_charge_cents"] == 40250
    assert payment["approval_status"] == "APPROVED"


def test_one_second_before_the_cutoff_settles_three_calendar_days_earlier():
    """PRD §3.3: "The cut-off boundary is inclusive on the late side: an
    instant of exactly 16:00:00 rolls to the next day, while 15:59:59 does
    not."

    Design: Difficulty/combinatorial_formula/settlement_cutoff_weekend_and_channel_interact_mode_a
    """
    world = setup_billpay_world(clock_iso="2026-06-05T15:59:59Z")

    payment = schedule_payment(world, amount_cents=40000, channel="CHECK")

    # No cut-off roll, so the submit date stays Friday 2026-06-05 and five
    # business days land on Friday 2026-06-12.
    assert payment["projected_settlement_date"] == "2026-06-12"
    assert payment["service_fee_cents"] == 250
    assert payment["total_charge_cents"] == 40250


def test_the_fee_band_is_selected_from_the_pre_fee_principal_alone():
    """PRD §3.3: "The definition looks circular — the total charge is what the
    account is charged, and the fee is the fee on that charge — so the
    evaluation order is pinned: select the band from `amount_cents`, read that
    band's flat fee, add the two, and **never re-select the band from
    `total_charge_cents`**."
    PRD §3.3: "A principal below 50000 cents carries a fee of 250 cents."

    Design: Difficulty/combinatorial_formula/service_fee_tier_selected_from_pre_fee_amount_mode_c
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")

    payment = schedule_payment(world, amount_cents=49900, channel="ACH")

    # 49900 sits in the first band even though the resulting total of 50150
    # would fall in the second.
    assert payment["service_fee_cents"] == 250
    assert payment["total_charge_cents"] == 50150


def test_the_three_commitment_bases_are_not_interchangeable():
    """PRD §3.3: "The account's `committed_disbursements_cents` accumulates
    `total_charge_cents` — principal plus fee, because the fee leaves the
    account too. The budget line's `committed_cents` accumulates `amount_cents`
    only, because the practice's fee is not the client's grocery money. The
    bond's `exposure_committed_cents` also accumulates `amount_cents` only."
    PRD §3.3: "`headroom_committed_cents` is `coverage_cents` minus
    `exposure_committed_cents`, and it may go negative if coverage was lowered
    after exposure had already accrued."

    Design: Difficulty/combinatorial_formula/service_fee_tier_selected_from_pre_fee_amount_mode_c
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")

    schedule_payment(world, amount_cents=49900, channel="ACH")

    account = read_account(world["account"]["id"])
    assert account["committed_disbursements_cents"] == 50150
    assert account["available_balance_cents"] == 4949850

    line = read_budget_category(world["budget_category"]["id"])
    assert line["committed_cents"] == 49900

    bond = read_bond(world["bond"]["id"])
    assert bond["exposure_committed_cents"] == 49900
    assert bond["headroom_committed_cents"] == 99950100


def test_a_principal_of_exactly_two_hundred_fifty_thousand_takes_the_third_band():
    """PRD §3.3: "A principal from 50000 cents up to but not including 250000
    cents carries 500 cents. A principal of 250000 cents or more carries 900
    cents."

    Design: Corner/calculations/corner_service_fee_reaches_tier_three_at_exactly_two_hundred_fifty_thousand
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z", allocation_cents=300000)

    payment = schedule_payment(world, amount_cents=250000, channel="ACH")

    assert payment["service_fee_cents"] == 900
    assert payment["total_charge_cents"] == 250900
    assert payment["approval_status"] == "PENDING_SECOND_APPROVAL"

    account = read_account(world["account"]["id"])
    assert account["committed_disbursements_cents"] == 250900
    assert account["available_balance_cents"] == 4749100

    line = read_budget_category(world["budget_category"]["id"])
    assert line["committed_cents"] == 250000
    assert line["remaining_cents"] == 50000


def test_scheduling_without_amount_cents_is_refused_at_the_request_shape_rung():
    """PRD §2.9 rung 4: "**Request shape.** The body carries every required
    field of the endpoint's input list, each of the declared JSON type. Unknown
    extra fields are ignored rather than rejected. Otherwise `ERR_VALIDATION`
    (422)."

    Design: Corner/entities/corner_payment_missing_required_amount_cents_returns_invalid_request
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")

    payload = {
        "account_id": world["account"]["id"],
        "payee_id": world["payee"]["id"],
        "authorization_id": world["authorization"]["id"],
        "budget_category_id": world["budget_category"]["id"],
        "channel": "ACH",
        "expected_account_version": account_version(world["account"]["id"]),
    }
    response = api_client.create_payment(payload, SPECIALIST)

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)
    assert list_payments(account_id=world["account"]["id"]) == []


def test_a_requested_send_date_before_the_current_logical_date_is_refused():
    """PRD §2.9 rung 20: "**Send date not in the past.** A supplied
    `requested_send_date` is not earlier than the current logical date; the
    current logical date itself is acceptable. Otherwise
    `ERR_SEND_DATE_IN_PAST` (422). Applies to scheduling a payment."

    Design: Corner/validations/corner_requested_send_date_in_the_past_is_rejected
    """
    world = setup_billpay_world(clock_iso="2026-06-10T09:00:00Z")

    response = payment_request(
        world, amount_cents=80000, channel="ACH", requested_send_date="2026-06-05"
    )

    validate_error(response, ApiErrorId.ERR_SEND_DATE_IN_PAST.value, 422)
    assert read_account(world["account"]["id"])["committed_disbursements_cents"] == 0


def test_naming_a_payee_that_does_not_exist_returns_the_generic_not_found_code():
    """PRD §2.7: "Requests that name resources do so in a fixed resolution
    order: every identifier in the URL path first, left to right, and then
    every identifier carried in the request body, in the order the endpoint's
    input list declares them."
    PRD §2.7: "Existence resolution sits above every business gate. A caller
    who names a client that does not exist learns only that; they learn nothing
    about the organization's bond status, about any client's freeze state, or
    about whether a period is closed."

    Design: Corner/validations/corner_unknown_payee_id_returns_resource_not_found
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")

    payload = {
        "account_id": world["account"]["id"],
        "payee_id": UNUSED_PAYEE_UUID,
        "authorization_id": world["authorization"]["id"],
        "budget_category_id": world["budget_category"]["id"],
        "amount_cents": 80000,
        "channel": "ACH",
        "expected_account_version": account_version(world["account"]["id"]),
    }
    response = api_client.create_payment(payload, SPECIALIST)

    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)


def test_a_projected_gap_of_exactly_three_days_collides():
    """PRD §3.3: "A collision exists when some other payment shares this
    request's account, shares its payee, carries exactly the same
    `amount_cents`, is still in `settlement_status` `SCHEDULED` or `IN_FLIGHT`,
    and whose `projected_settlement_date` is within three whole calendar days
    of the new payment's own `projected_settlement_date`."
    PRD §3.3: "The buffer is symmetric around the projected date — three days
    earlier collides just as three days later does — and it is inclusive at the
    boundary: a gap of exactly 3 days collides, a gap of 4 days does not."

    Design: Difficulty/resource_temporal_overlap/duplicate_payment_buffer_is_symmetric_and_inclusive_at_three_days
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    first = schedule_payment(world, amount_cents=40000, channel="BILLER_DIRECT")
    assert first["projected_settlement_date"] == "2026-06-01"

    response = payment_request(
        world,
        amount_cents=40000,
        channel="BILLER_DIRECT",
        requested_send_date="2026-06-04",
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_PAYMENT_WINDOW.value, 409)
    account = read_account(world["account"]["id"])
    assert account["committed_disbursements_cents"] == 40250
    assert read_budget_category(world["budget_category"]["id"])["committed_cents"] == 40000
    assert len(list_payments(account_id=world["account"]["id"])) == 1


def test_a_projected_gap_of_four_days_does_not_collide():
    """PRD §3.3: "The buffer is symmetric around the projected date — three
    days earlier collides just as three days later does — and it is inclusive
    at the boundary: a gap of exactly 3 days collides, a gap of 4 days does
    not."

    Design: Difficulty/resource_temporal_overlap/duplicate_payment_buffer_is_symmetric_and_inclusive_at_three_days
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    first = schedule_payment(world, amount_cents=40000, channel="BILLER_DIRECT")
    assert first["projected_settlement_date"] == "2026-06-01"

    response = payment_request(
        world,
        amount_cents=40000,
        channel="BILLER_DIRECT",
        requested_send_date="2026-06-05",
    )

    second = validate_success(response, 201)
    assert second["projected_settlement_date"] == "2026-06-05"
    assert len(list_payments(account_id=world["account"]["id"])) == 2
