"""Half-open seat occupancy, aggregate capacity, claiming guards and reclaim."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    api_client,
    assert_seat_capacity_conserved,
    create_active_institutional_plan,
    create_hold,
    create_registered_reader,
    fresh_group_version,
    invite_seat,
    invoice_for_cycle,
    list_seats,
    make_group_admin_headers,
    make_reader_headers,
    open_subscription,
    read_group,
    read_hold,
    read_reader,
    read_seat,
    read_subscription,
    record_payment,
    run_billing,
    set_clock_date,
    validate_error,
    validate_success,
)
from test_helpers import factories as f


def _institutional_group(plan_name, group_name, admin_local, seat_capacity):
    """An ACTIVE group on univ.edu whose funding subscription has been paid."""
    set_clock_date("2026-09-01")
    plan = create_active_institutional_plan(
        name=plan_name,
        intro_price_cents=5000,
        intro_cycles=1,
        standard_price_cents=5000,
        standard_from_cycle=2,
        cycle_days=30,
        per_seat_price_cents=400,
    )
    group = validate_success(
        api_client.create_group_account(
            f.create_group_account_payload(
                plan["id"],
                seat_capacity=seat_capacity,
                name=group_name,
                admin_email=f"{admin_local}@univ.edu",
                allowed_email_domain="univ.edu",
            ),
            OPS_AGENT_HEADERS,
        ),
        201,
    )
    funding_reader = create_registered_reader(f"{admin_local}@univ.edu")
    subscription = open_subscription(funding_reader["id"], plan["id"], group["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 5000)
    return {
        "plan": plan,
        "group": group,
        "admin_headers": make_group_admin_headers(group["id"]),
        "funding_reader": funding_reader,
        "subscription": read_subscription(subscription["id"]),
    }


def _arrange_expired_invitation_for_a_reader_from_another_domain():
    """An invitation left unclaimed past its expiry, held by an outsider address."""
    state = _institutional_group(
        "Institution Seats B", "Univ Library B", "libadminb", 3
    )
    outsider = create_registered_reader("outsider@other.edu")
    seat = invite_seat(
        state["group"]["id"],
        outsider["id"],
        "2026-09-05",
        "2026-09-20",
        admin_headers=state["admin_headers"],
    )
    set_clock_date("2026-09-16")
    report = run_billing("EXPIRY_ONLY")
    return {**state, "outsider": outsider, "seat": seat, "report": report}


def test_seat_state_check_is_reported_ahead_of_the_domain_check():
    """The claimant's address is wrong too, but the expired seat state answers first.

    PRD: "**State admissibility**, in this relative order: plan not active (`ERR_PLAN_NOT_ACTIVE`), plan already active (`ERR_PLAN_ALREADY_ACTIVE`), price-change pipeline state wrong for the requested step (`ERR_PRICE_CHANGE_STATE_INVALID`), subscription terminal (`ERR_SUBSCRIPTION_TERMINAL`), subscription not active (`ERR_SUBSCRIPTION_NOT_ACTIVE`), dunning episode exhausted (`ERR_DUNNING_EXHAUSTED`), invoice not payable (`ERR_INVOICE_NOT_PAYABLE`), retry attempted too early (`ERR_RETRY_TOO_EARLY`), cancellation request closed (`ERR_CANCELLATION_REQUEST_CLOSED`), save offer already decided (`ERR_SAVE_OFFER_ALREADY_DECIDED`), hold not releasable (`ERR_HOLD_NOT_RELEASABLE`), seat not invited (`ERR_SEAT_NOT_INVITED`), seat invite expired (`ERR_SEAT_INVITE_EXPIRED`)."
    PRD: "The seat must still be `INVITED`, otherwise `ERR_SEAT_NOT_INVITED`; the clock date must be on or before `invite_expires_on`, otherwise `ERR_SEAT_INVITE_EXPIRED`; the reader's `email` must end with an at-sign followed by the group's `allowed_email_domain`, otherwise `ERR_SEAT_DOMAIN_MISMATCH` (HTTP 422); and the group's funding subscription must still be `ACTIVE` with a `dunning_status` other than `FAILED_FINAL`, otherwise `ERR_GROUP_SUBSCRIPTION_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/seat_state_check_outranks_domain_check_rejected
    """
    state = _arrange_expired_invitation_for_a_reader_from_another_domain()

    response = api_client.activate_seat(
        state["seat"]["id"], make_reader_headers(state["outsider"]["id"])
    )

    error = validate_error(response, "ERR_SEAT_NOT_INVITED", 409)
    assert error["error_id"] != "ERR_SEAT_DOMAIN_MISMATCH"


def test_lapsed_invitation_frees_its_capacity_and_was_never_claimed():
    """The invitation expired fourteen days after it was issued, releasing the seat.

    PRD: "Invitations nobody claims lapse on their own: the EXPIRY pass of a run moves a seat whose `status` is `INVITED` and whose `invite_expires_on` is strictly behind the clock date to `EXPIRED`, recomputes the group's two counters, and reports the seat in `seats_expired`."
    PRD: "`RECLAIMED` and `EXPIRED` seats free their capacity immediately."

    Design: Difficulty/priority_pair_validation_conflict/seat_state_check_outranks_domain_check_rejected
    """
    state = _arrange_expired_invitation_for_a_reader_from_another_domain()

    seat = read_seat(state["seat"]["id"])
    assert seat["status"] == "EXPIRED"
    assert seat["claimed_on"] is None
    assert seat["invite_expires_on"] == "2026-09-15"
    group = read_group(state["group"]["id"])
    assert group["seats_assigned_count"] == 0
    assert group["seats_available_count"] == 3
    assert_seat_capacity_conserved(group)


def _arrange_paused_funding_subscription_with_an_open_invitation():
    """A PAUSE_BILLING hold in force, so the group's funding subscription is PAUSED."""
    state = _institutional_group(
        "Institution Seats C", "Univ Library C", "libadminc", 3
    )
    scholar = create_registered_reader("scholar@univ.edu")
    seat = invite_seat(
        state["group"]["id"],
        scholar["id"],
        "2026-09-05",
        admin_headers=state["admin_headers"],
    )
    hold = create_hold(
        state["subscription"]["id"],
        "PAUSE_BILLING",
        "2026-09-08",
        "2026-09-20",
        OPS_AGENT_HEADERS,
    )
    set_clock_date("2026-09-08")
    run_billing("HOLDS_ONLY")
    return {**state, "scholar": scholar, "seat": seat, "hold": read_hold(hold["id"])}


def test_seat_cannot_be_claimed_while_the_funding_subscription_is_paused():
    """The seat and the address are both fine; the funding relationship is not.

    PRD: "The funding relationship must be alive: the group must have a funding subscription — the subscription whose `group_account_id` is this group — with `lifecycle_status` `ACTIVE` and `dunning_status` other than `FAILED_FINAL`, otherwise `ERR_GROUP_SUBSCRIPTION_NOT_ACTIVE` (HTTP 422)."
    PRD: "A `PAUSE_BILLING` hold reaching its start date moves the hold to `ACTIVE` and drives the lifecycle dimension `ACTIVE → PAUSED`, then recomputes the reader's `entitlement_source` — and because `PAUSED` is not an entitling status, a reader with no seat drops to `NONE` and is metered again."

    Design: Difficulty/cross_entity_state_dependency/seat_cannot_activate_while_funding_subscription_paused_rejected
    """
    state = _arrange_paused_funding_subscription_with_an_open_invitation()
    assert read_subscription(state["subscription"]["id"])["lifecycle_status"] == "PAUSED"

    response = api_client.activate_seat(
        state["seat"]["id"], make_reader_headers(state["scholar"]["id"])
    )

    validate_error(response, "ERR_GROUP_SUBSCRIPTION_NOT_ACTIVE", 422)


def test_paused_funding_leaves_the_invitation_open_and_the_pause_credit_at_zero():
    """Paused days are never billed, so the pause carries no credit and no delivery days.

    PRD: "For a `PAUSE_BILLING` hold, `delivery_days_credited` is 0 and `credit_cents` is 0, because paused days are not billed at all and there is nothing to give back."
    PRD: "Claiming drives `INVITED → ACTIVE`, sets `claimed_on` to the clock date, and recomputes the reader's `entitlement_source` to `SEAT` when no subscription already entitles them — a reader with their own live subscription keeps `SUBSCRIPTION`, since it outranks `SEAT`."

    Design: Difficulty/cross_entity_state_dependency/seat_cannot_activate_while_funding_subscription_paused_rejected
    """
    state = _arrange_paused_funding_subscription_with_an_open_invitation()
    api_client.activate_seat(
        state["seat"]["id"], make_reader_headers(state["scholar"]["id"])
    )

    hold = read_hold(state["hold"]["id"])
    assert hold["status"] == "ACTIVE"
    assert hold["delivery_days_credited"] == 0
    assert hold["credit_cents"] == 0
    seat = read_seat(state["seat"]["id"])
    assert seat["status"] == "INVITED"
    assert seat["invite_expires_on"] == "2026-09-15"
    assert seat["claimed_on"] is None
    assert read_reader(state["scholar"]["id"])["entitlement_source"] == "NONE"


def _arrange_capacity_two_group_with_two_overlapping_seats():
    """Two seats overlapping between 2026-09-10 and 2026-09-20 on a capacity-two group."""
    state = _institutional_group(
        "Institution Seats D", "Univ Library D", "libadmind", 2
    )
    readers = {
        local: create_registered_reader(f"{local}@univ.edu")
        for local in ("s1", "s2", "s3", "s4")
    }
    first = invite_seat(
        state["group"]["id"],
        readers["s1"]["id"],
        "2026-09-05",
        "2026-09-20",
        admin_headers=state["admin_headers"],
    )
    second = invite_seat(
        state["group"]["id"],
        readers["s2"]["id"],
        "2026-09-10",
        "2026-09-25",
        admin_headers=state["admin_headers"],
    )
    return {**state, "readers": readers, "first": first, "second": second}


def test_seat_starting_the_day_an_existing_seat_ends_is_admitted_free_of_contention():
    """Half-open geometry makes 2026-09-20 adjacency free even at full capacity.

    PRD: "A **seat** occupies a `[starts_on, ends_on)` **half-open** interval on a group account: the start day is inside the occupancy and the end day is outside it."
    PRD: "Because the geometry is half-open, adjacency is free: an existing seat ending 2026-09-09 and a candidate starting 2026-09-09 never contend."
    PRD: "the seat is created with `status` `INVITED`, its `group_account_id` set from the path, `invited_on` at the clock date, `invite_expires_on` at `invited_on` advanced by fourteen days (two weeks to claim), and `claimed_on` null."

    Design: Difficulty/resource_temporal_overlap/seat_half_open_intervals_admit_adjacency_but_cap_aggregate
    """
    state = _arrange_capacity_two_group_with_two_overlapping_seats()

    adjacent = validate_success(
        api_client.create_seat(
            state["group"]["id"],
            f.create_seat_payload(
                state["readers"]["s3"]["id"],
                "2026-09-20",
                fresh_group_version(state["group"]["id"], state["admin_headers"]),
                "2026-09-30",
            ),
            state["admin_headers"],
        ),
        201,
    )

    assert adjacent["status"] == "INVITED"
    assert adjacent["invited_on"] == "2026-09-01"
    assert adjacent["invite_expires_on"] == "2026-09-15"


def test_seat_inside_the_peak_window_is_refused_by_aggregate_concurrency():
    """Three rows may coexist, but a fourth interval inside the peak breaks capacity two.

    PRD: "Take the half-open intervals of every seat on the group whose `status` is `INVITED` or `ACTIVE`, treating a null `ends_on` as extending indefinitely, and add the candidate's interval. Collect every start and end date as a sorted set of boundaries, and for each consecutive pair of boundaries count how many intervals cover that sub-window; the peak of those counts is the maximum concurrent occupancy."
    PRD: "The invitation is admitted only when that peak is less than or equal to `seat_capacity`, and refused with `ERR_SEAT_CAPACITY_EXCEEDED` otherwise."

    Design: Difficulty/resource_temporal_overlap/seat_half_open_intervals_admit_adjacency_but_cap_aggregate
    """
    state = _arrange_capacity_two_group_with_two_overlapping_seats()
    validate_success(
        api_client.create_seat(
            state["group"]["id"],
            f.create_seat_payload(
                state["readers"]["s3"]["id"],
                "2026-09-20",
                fresh_group_version(state["group"]["id"], state["admin_headers"]),
                "2026-09-30",
            ),
            state["admin_headers"],
        ),
        201,
    )

    response = api_client.create_seat(
        state["group"]["id"],
        f.create_seat_payload(
            state["readers"]["s4"]["id"],
            "2026-09-15",
            fresh_group_version(state["group"]["id"], state["admin_headers"]),
            "2026-09-16",
        ),
        state["admin_headers"],
    )
    validate_error(response, "ERR_SEAT_CAPACITY_EXCEEDED")

    rows = list_seats({"group_account_id": state["group"]["id"], "limit": 100})
    assert len(rows) == 3
    assert list_seats({"reader_id": state["readers"]["s4"]["id"]}) == []
    group = read_group(state["group"]["id"])
    assert group["seats_assigned_count"] == 2
    assert group["seats_available_count"] == 0
    assert_seat_capacity_conserved(group)


def _arrange_capacity_three_group_before_any_invitation():
    """A capacity-three group with two invitees standing by."""
    state = _institutional_group(
        "Institution Seats E", "Univ Library E", "libadmine", 3
    )
    state["e1"] = create_registered_reader("e1@univ.edu")
    state["e2"] = create_registered_reader("e2@univ.edu")
    return state


def test_two_overlapping_invitations_raise_assigned_capacity_to_the_peak_of_two():
    """Capacity accounting starts at zero assigned and follows peak occupancy.

    PRD: "The group is created with `status` `ACTIVE`, `seats_assigned_count` at 0 and `seats_available_count` equal to `seat_capacity`."
    PRD: "This is why three staggered seat rows can coexist on a capacity-two group — the raw row count is 3 but the peak concurrency is 2 — and why the conservation invariant `seat_capacity` equals `seats_assigned_count` plus `seats_available_count` holds after every seat transition."

    Design: Difficulty/compensating_invariant/seat_capacity_conserved_across_invite_and_reclaim
    """
    state = _arrange_capacity_three_group_before_any_invitation()
    before = read_group(state["group"]["id"])
    assert before["seats_assigned_count"] == 0
    assert before["seats_available_count"] == 3

    invite_seat(
        state["group"]["id"],
        state["e1"]["id"],
        "2026-09-05",
        "2026-09-20",
        admin_headers=state["admin_headers"],
    )
    invite_seat(
        state["group"]["id"],
        state["e2"]["id"],
        "2026-09-10",
        "2026-09-25",
        admin_headers=state["admin_headers"],
    )

    group = read_group(state["group"]["id"])
    assert group["seats_assigned_count"] == 2
    assert group["seats_available_count"] == 1
    assert_seat_capacity_conserved(group)


def test_reclaiming_an_unclaimed_invitation_returns_its_capacity_to_the_group():
    """Reclaim from INVITED ends the seat today and the invariant still balances.

    PRD: "**Reclaiming a seat** is the `GroupAdmin`'s exclusive act and works from either `INVITED` — revoking a pending invitation before it is claimed — or `ACTIVE`. Either way the seat becomes `RECLAIMED` with `ends_on` set to the clock date, the group's `seats_assigned_count` and `seats_available_count` are recomputed so the conservation invariant still holds, the group's `version` increments, and the reader's `entitlement_source` is recomputed to `NONE` unless a subscription entitles them."

    Design: Difficulty/compensating_invariant/seat_capacity_conserved_across_invite_and_reclaim
    """
    state = _arrange_capacity_three_group_before_any_invitation()
    seat_e1 = invite_seat(
        state["group"]["id"],
        state["e1"]["id"],
        "2026-09-05",
        "2026-09-20",
        admin_headers=state["admin_headers"],
    )
    seat_e2 = invite_seat(
        state["group"]["id"],
        state["e2"]["id"],
        "2026-09-10",
        "2026-09-25",
        admin_headers=state["admin_headers"],
    )

    reclaimed = validate_success(
        api_client.reclaim_seat(seat_e1["id"], state["admin_headers"]), 200
    )

    assert reclaimed["status"] == "RECLAIMED"
    assert reclaimed["ends_on"] == "2026-09-01"
    assert reclaimed["claimed_on"] is None
    assert read_seat(seat_e2["id"])["status"] == "INVITED"
    group = read_group(state["group"]["id"])
    assert group["seat_capacity"] == 3
    assert group["seats_assigned_count"] == 1
    assert group["seats_available_count"] == 2
    assert_seat_capacity_conserved(group)
    assert read_reader(state["e1"]["id"])["entitlement_source"] == "NONE"
