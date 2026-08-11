"""Cancellation: the closure timeline, the single-occupancy rule and the refund waterfall."""

from test_helpers import (
    CMRA_OPERATOR,
    ApiErrorId,
    assert_cancellation_request,
    assert_refund_waterfall_conservation,
    letter_payload,
    set_clock,
    setup_releasable_box,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_box_ready_to_give_notice():
    return setup_releasable_box(
        "S-1901",
        "Sid Leave",
        holder_email="sid@example.com",
        box_overrides={"security_deposit_cents": 4000, "prepaid_balance_cents": 9000},
    )


def test_giving_notice_computes_the_four_closure_dates_and_locks_the_mailbox(api):
    """PRD §3.13: "Lodging stamps `requested_on` with the clock's calendar date,
    snapshots `prepaid_at_request_cents` from the mailbox's `prepaid_balance_cents` and
    `deposit_held_cents` from its `security_deposit_cents` as of that instant, creates
    the request in status `REQUESTED`, drives the mailbox `ACTIVE → CLOSING`, and bumps
    `Box.version` by one."
    PRD §3.13: "`notice_end_date` is `requested_on` plus 30 days, and service ends at the
    start of that date."
    PRD §3.13: "The mailbox must be `ACTIVE`, and no cancellation request on it may
    already sit in `REQUESTED` or `FINAL_FORWARD`, failing which the request is
    `ERR_CANCELLATION_ALREADY_PENDING`."

    Design: Difficulty/resource_temporal_overlap/cancellation_occupies_the_box_until_withdrawn
    """
    ctx = _setup_box_ready_to_give_notice()

    first = validate_success(
        api.create_cancellation(
            ctx["box_id"], {"forwarding_address": "18 Departure Blvd"}, ctx["holder_headers"]
        ),
        201,
    )
    assert_cancellation_request(first)
    assert first["requested_on"] == "2026-05-01"
    assert first["notice_end_date"] == "2026-05-31"
    assert first["final_forward_deadline"] == "2026-06-15"
    assert first["abandonment_date"] == "2026-06-25"
    assert first["destruction_eligible_on"] == "2026-07-25"
    assert first["prepaid_at_request_cents"] == 9000
    assert first["deposit_held_cents"] == 4000

    collision = api.create_cancellation(
        ctx["box_id"], {"forwarding_address": "18 Departure Blvd"}, ctx["holder_headers"]
    )
    validate_error(collision, ApiErrorId.ERR_CANCELLATION_ALREADY_PENDING.value)


def test_withdrawing_the_notice_frees_the_mailbox_for_a_fresh_one(api):
    """PRD §3.13: "Withdrawal is available from both live states and is the holder's
    privilege: from `REQUESTED` unconditionally, and from `FINAL_FORWARD` only while the
    clock date is **less than or equal to** `final_forward_deadline`."
    PRD §3.13: "Either withdrawal moves the request to `WITHDRAWN`, drives the mailbox
    `CLOSING → ACTIVE`, and bumps both the request's and the mailbox's `version` by one."

    Design: Difficulty/resource_temporal_overlap/cancellation_occupies_the_box_until_withdrawn
    """
    ctx = _setup_box_ready_to_give_notice()
    first = validate_success(
        api.create_cancellation(
            ctx["box_id"], {"forwarding_address": "18 Departure Blvd"}, ctx["holder_headers"]
        ),
        201,
    )

    withdrawn = validate_success(
        api.withdraw_cancellation(ctx["box_id"], ctx["holder_headers"])
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["id"] == first["id"]

    second = validate_success(
        api.create_cancellation(
            ctx["box_id"], {"forwarding_address": "18 Departure Blvd"}, ctx["holder_headers"]
        ),
        201,
    )
    assert second["status"] == "REQUESTED"
    assert validate_success(api.get_box(ctx["box_id"], CMRA_OPERATOR))["service_status"] == (
        "CLOSING"
    )


def test_finalizing_before_the_retention_floor_is_refused_and_on_it_succeeds(api):
    """PRD §3.13: "It requires the mailbox to be `CLOSING`, its cancellation request to
    be in `FINAL_FORWARD`, the clock date to be **greater than or equal to**
    `destruction_eligible_on` — failing which the request is
    `ERR_RETENTION_FLOOR_NOT_REACHED` — and no service-of-process piece on the mailbox to
    be still inside its statutory retention period while an active add-on covers it,
    failing which the request is `ERR_RA_RETENTION_ACTIVE`."
    PRD §3.13: "Step three sets `forfeited_cents` to that whole remainder when the
    mailbox carries a compliance review whose `resolution` is `ESCALATED_CLOSURE`, and to
    zero otherwise — money is only forfeited when USPS ordered the closure."

    2026-07-24 sits one day below the inclusive `destruction_eligible_on` edge of
    2026-07-25.

    Design: Corner/validations/finalize_before_the_retention_floor_is_rejected
    """
    ctx = setup_releasable_box(
        "Z-3009",
        "Kit Wait",
        holder_email="kit@example.com",
        box_overrides={"security_deposit_cents": 3000, "prepaid_balance_cents": 7000},
    )
    cancellation = validate_success(
        api.create_cancellation(
            ctx["box_id"], {"forwarding_address": "77 Later Ln"}, ctx["holder_headers"]
        ),
        201,
    )
    set_clock("2026-07-24T00:00:00Z")

    too_early = api.finalize_cancellation(ctx["box_id"], CMRA_OPERATOR)
    validate_error(too_early, ApiErrorId.ERR_RETENTION_FLOOR_NOT_REACHED.value)

    rows, _ = validate_paginated(api.list_cancellations(ctx["box_id"], CMRA_OPERATOR))
    pending = next(r for r in rows if r["id"] == cancellation["id"])
    assert pending["status"] == "FINAL_FORWARD"

    set_clock("2026-07-25T00:00:00Z")
    finalized = validate_success(api.finalize_cancellation(ctx["box_id"], CMRA_OPERATOR))
    assert finalized["status"] == "FINALIZED"
    assert finalized["applied_to_overage_cents"] == 0
    assert finalized["forfeited_cents"] == 0
    assert finalized["refund_total_cents"] == 10000
    assert_refund_waterfall_conservation(finalized)
    assert validate_success(api.get_box(ctx["box_id"], CMRA_OPERATOR))["service_status"] == (
        "CLOSED"
    )


def test_a_closed_mailbox_refuses_every_further_write(api):
    """PRD §2.8: "A mailbox therefore projects a derived `release_gate_state`:
    `GATED_SUSPENDED` when `service_status` is `SUSPENDED`, `GATED_LIFECYCLE` when
    `service_status` is `PENDING_SETUP` or `CLOSED`, and `OPEN` in every other case,
    which is to say when `service_status` is `ACTIVE` or `CLOSING`."
    PRD §2.9 rung 12: "The target mailbox is `PENDING_SETUP` or `CLOSED` and the
    operation requires an in-service mailbox. Otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/closed_box_rejects_every_further_write
    """
    ctx = setup_releasable_box("Z-1007", "Ola Close", holder_email="ola@example.com")
    cancellation = validate_success(
        api.create_cancellation(
            ctx["box_id"], {"forwarding_address": "1 Exit Way"}, ctx["holder_headers"]
        ),
        201,
    )
    set_clock("2026-07-25T00:00:00Z")
    validate_success(api.finalize_cancellation(ctx["box_id"], CMRA_OPERATOR))

    blocked = api.create_mail_item(
        ctx["box_id"], letter_payload("Ola Close"), CMRA_OPERATOR
    )
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value)

    box = validate_success(api.get_box(ctx["box_id"], CMRA_OPERATOR))
    assert box["service_status"] == "CLOSED"
    assert box["release_gate_state"] == "GATED_LIFECYCLE"

    rows, _ = validate_paginated(api.list_cancellations(ctx["box_id"], CMRA_OPERATOR))
    assert next(r for r in rows if r["id"] == cancellation["id"])["status"] == "FINALIZED"
