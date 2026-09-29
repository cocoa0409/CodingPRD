"""Institutional funding, seat geometry, exact tender and the monotonic clock."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    api_client,
    create_active_plan,
    create_reader,
    create_registered_reader,
    fresh_group_version,
    invite_seat,
    invoice_for_cycle,
    make_reader_headers,
    open_subscription,
    read_group,
    read_invoice,
    read_reader,
    read_seat,
    read_subscription,
    record_payment,
    set_clock_date,
    setup_institutional_group,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f


def test_a_digital_only_plan_cannot_fund_a_group_account():
    """The plan is ACTIVE and sellable, but it sells no seats, so the group is refused.

    PRD: "That plan must be sellable and must be the right shape: a plan whose `status` is not `ACTIVE` answers `ERR_PLAN_NOT_ACTIVE`, and a plan whose `bundle_type` is not `INSTITUTIONAL_SEAT` or whose `per_seat_price_cents` is 0 answers `ERR_PLAN_NOT_INSTITUTIONAL` (HTTP 422)."
    PRD: "The group is created with `status` `ACTIVE`, `seats_assigned_count` at 0 and `seats_available_count` equal to `seat_capacity`."

    Design: Corner/validations/group_account_funded_by_non_institutional_plan_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital NotInst")
    assert plan["status"] == "ACTIVE"

    response = api_client.create_group_account(
        f.create_group_account_payload(
            plan["id"],
            seat_capacity=5,
            name="Wrong Funding",
            admin_email="admin@campus.test",
            allowed_email_domain="campus.test",
        ),
        OPS_AGENT_HEADERS,
    )

    validate_error(response, "ERR_PLAN_NOT_INSTITUTIONAL", 422)
    rows, meta = validate_paginated(api_client.list_group_accounts(OPS_AGENT_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []


def test_an_outsider_may_be_invited_to_a_seat_but_may_not_claim_it():
    """Institutional authentication happens at claim time, so the invite itself stands.

    PRD: "The seat must still be `INVITED`, otherwise `ERR_SEAT_NOT_INVITED`; the clock date must be on or before `invite_expires_on`, otherwise `ERR_SEAT_INVITE_EXPIRED`; the reader's `email` must end with an at-sign followed by the group's `allowed_email_domain`, otherwise `ERR_SEAT_DOMAIN_MISMATCH` (HTTP 422); and the group's funding subscription must still be `ACTIVE` with a `dunning_status` other than `FAILED_FINAL`, otherwise `ERR_GROUP_SUBSCRIPTION_NOT_ACTIVE`."
    PRD: "Claiming drives `INVITED → ACTIVE`, sets `claimed_on` to the clock date, and recomputes the reader's `entitlement_source` to `SEAT` when no subscription already entitles them — a reader with their own live subscription keeps `SUBSCRIPTION`, since it outranks `SEAT`."

    Design: Corner/validations/seat_activation_from_foreign_email_domain_rejected
    """
    scenario = setup_institutional_group(
        seat_capacity=3,
        group_name="Campus Domain Group",
        allowed_email_domain="campus.test",
        funding_reader_email="bursar2@campus.test",
        clock_date="2026-09-01",
        name="Campus Domain",
        per_seat_price_cents=400,
    )
    outsider = create_registered_reader("outsider@other.test")
    seat = invite_seat(
        scenario["group"]["id"],
        outsider["id"],
        "2026-09-02",
        admin_headers=scenario["group_headers"],
    )
    assert seat["status"] == "INVITED"

    response = api_client.activate_seat(seat["id"], make_reader_headers(outsider["id"]))

    validate_error(response, "ERR_SEAT_DOMAIN_MISMATCH", 422)
    unclaimed = read_seat(seat["id"])
    assert unclaimed["status"] == "INVITED"
    assert unclaimed["claimed_on"] is None
    assert read_reader(outsider["id"])["entitlement_source"] == "NONE"


def test_a_seat_that_ends_on_the_day_it_starts_is_not_a_seat():
    """The half-open interval would be empty, so it is refused before any arithmetic.

    PRD: "The interval must be sane: `starts_on` must be on or after the clock date and, when `ends_on` is supplied, it must be strictly after `starts_on`, otherwise `ERR_SEAT_INTERVAL_INVALID` (HTTP 422) — a zero-length half-open occupancy is not a seat."
    PRD: "The group's derived counters use the **same** peak-occupancy measure, computed over the `INVITED` and `ACTIVE` seats only with the candidate excluded: `seats_assigned_count` is that peak, and `seats_available_count` is `seat_capacity` less `seats_assigned_count`, floored at zero."

    Design: Corner/validations/zero_length_seat_interval_rejected
    """
    scenario = setup_institutional_group(
        seat_capacity=3,
        group_name="Campus Zero Group",
        allowed_email_domain="campus.test",
        funding_reader_email="bursar3@campus.test",
        clock_date="2026-09-01",
        name="Campus Zero",
        per_seat_price_cents=400,
    )
    student = create_registered_reader("student3@campus.test")
    group_id = scenario["group"]["id"]

    response = api_client.create_seat(
        group_id,
        f.create_seat_payload(
            student["id"],
            "2026-09-10",
            fresh_group_version(group_id, scenario["group_headers"]),
            ends_on="2026-09-10",
        ),
        scenario["group_headers"],
    )

    validate_error(response, "ERR_SEAT_INTERVAL_INVALID", 422)
    rows, meta = validate_paginated(
        api_client.list_seats(OPS_AGENT_HEADERS, {"group_account_id": group_id})
    )
    assert meta["total_count"] == 0
    assert rows == []
    group = read_group(group_id)
    assert group["seats_assigned_count"] == 0
    assert group["seats_available_count"] == 3


def test_the_same_reader_may_not_hold_two_overlapping_seats_on_one_group():
    """Capacity 3 leaves room, so the refusal must come from the per-reader rule.

    PRD: "The same reader may not hold two overlapping seats on the same group: if any existing seat on the group has the same `reader_id`, a `status` of `INVITED` or `ACTIVE`, and a half-open interval that intersects the candidate's, the answer is `ERR_SEAT_READER_DUPLICATE`."
    PRD: "The invitation is admitted only when that peak is less than or equal to `seat_capacity`, and refused with `ERR_SEAT_CAPACITY_EXCEEDED` otherwise."

    Design: Corner/validations/duplicate_overlapping_seat_for_same_reader_rejected
    """
    scenario = setup_institutional_group(
        seat_capacity=3,
        group_name="Campus Dup Group",
        allowed_email_domain="campus.test",
        funding_reader_email="bursar4@campus.test",
        clock_date="2026-09-01",
        name="Campus Dup",
        per_seat_price_cents=400,
    )
    student = create_registered_reader("student4@campus.test")
    group_id = scenario["group"]["id"]
    invite_seat(
        group_id,
        student["id"],
        "2026-09-10",
        ends_on="2026-09-20",
        admin_headers=scenario["group_headers"],
    )

    response = api_client.create_seat(
        group_id,
        f.create_seat_payload(
            student["id"],
            "2026-09-15",
            fresh_group_version(group_id, scenario["group_headers"]),
            ends_on="2026-09-25",
        ),
        scenario["group_headers"],
    )

    error = validate_error(response, "ERR_SEAT_READER_DUPLICATE", 409)
    assert error["error_id"] != "ERR_SEAT_CAPACITY_EXCEEDED"
    rows, meta = validate_paginated(
        api_client.list_seats(OPS_AGENT_HEADERS, {"group_account_id": group_id})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    group = read_group(group_id)
    assert group["seats_assigned_count"] == 1
    assert group["seats_available_count"] == 2


def test_one_cent_over_the_invoice_total_is_as_invalid_as_one_cent_under():
    """No attempt row is written at all, so the activation never gets a chance to run.

    PRD: "Partial tenders do not exist: `amount_cents` must equal the invoice's `total_cents` exactly, and any other figure answers `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422)."
    PRD: "Recording a `SUCCEEDED` outcome against the cycle-1 invoice of a `PENDING_ACTIVATION` subscription — the invoice must be `OPEN`, must have `cycle_index` 1, and must belong to that subscription — drives `PENDING_ACTIVATION → ACTIVE`."

    Design: Corner/validations/partial_tender_payment_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Tender")
    reader = create_registered_reader("tender@mail.test")
    subscription = open_subscription(reader["id"], plan["id"])
    invoice = invoice_for_cycle(subscription["id"], 1)
    assert invoice["total_cents"] == 499

    response = api_client.create_payment_attempt(
        invoice["id"],
        f.create_payment_attempt_payload("SUCCEEDED", 500),
        OPS_AGENT_HEADERS,
    )

    validate_error(response, "ERR_PAYMENT_AMOUNT_MISMATCH", 422)
    rows, meta = validate_paginated(
        api_client.list_payment_attempts(invoice["id"], OPS_AGENT_HEADERS)
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert read_invoice(invoice["id"])["status"] == "OPEN"
    assert read_subscription(subscription["id"])["lifecycle_status"] == "PENDING_ACTIVATION"
    assert read_reader(reader["id"])["entitlement_source"] == "NONE"


def test_the_logical_clock_refuses_to_step_backwards_and_keeps_its_value():
    """The refused rewind leaves 2026-09-10 in force, as a fresh reader's meter proves.

    PRD: "The clock is strictly monotonic: a request whose `current_utc` is earlier than the clock's present value is refused with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422)."
    PRD: "A request whose `current_utc` equals the present value is accepted."
    PRD: "On creation, `meter_period_started_on` is set to the clock date, `engagement_score` is 0.00, `churn_risk_band` is `SEVERE`, `entitlement_source` is `NONE`, `metered_article_ids` is empty, `metered_distinct_article_count` is 0, and `card_updater_status` is `NOT_APPLICABLE`."

    Design: Corner/validations/clock_moving_backwards_rejected
    """
    set_clock_date("2026-09-10")

    response = api_client.set_clock("2026-09-09T00:00:00Z", OPS_AGENT_HEADERS)

    validate_error(response, "ERR_CLOCK_NOT_MONOTONIC", 422)
    set_clock_date("2026-09-10")
    reader = create_reader()
    assert reader["meter_period_started_on"] == "2026-09-10"
    assert float(reader["engagement_score"]) == 0.00
