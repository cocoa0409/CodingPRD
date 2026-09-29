"""Interval geometry and the conservation invariants of the program API.

Two intervals live in this contract and they are deliberately shaped in opposite
ways: a test slot is half-open with no buffer, so zero-gap adjacency is legal,
while a change window is a closed interval guarded by an inclusive seven-day
quiet buffer that only submitted and approved windows impose. Alongside them sit
the compensating ledgers — an engagement's contracted hours and an
authorization's reuse seats — whose identities must hold after every single
write, including the writes that are refused.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as at
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CHANGE_WINDOW_BUFFER_VIOLATION,
    ERR_ENGAGEMENT_HOURS_EXHAUSTED,
    ERR_TEST_SLOT_OVERLAP,
)

# ---------------------------------------------------------------------------
# Shared preconditions
# ---------------------------------------------------------------------------


def _engagement_ready_for_slots(client, *, contracted_hours):
    """An offering in IN_ASSESSMENT whose engagement sits in PLAN_APPROVED."""
    env = fx.seed_reference_data(client, clock=fx.SETUP_CLOCK)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_engagement(client, env, contracted_hours=contracted_hours)
    return env


def _engagement_with_eight_hour_slot(client):
    """A 200.00 h pool carrying one SCHEDULED slot 2026-03-02 09:00..17:00."""
    env = _engagement_ready_for_slots(client, contracted_hours=200.00)
    env = fx.seed_test_slot(
        client,
        env,
        start_at="2026-03-02T09:00:00Z",
        end_at="2026-03-02T17:00:00Z",
        hours=8.00,
        family_code="AC",
        key="slot_a",
    )
    return env


def _engagement_with_ninety_two_hour_slot(client):
    """A 100.00 h pool almost entirely drawn by one four-day slot."""
    env = _engagement_ready_for_slots(client, contracted_hours=100.00)
    env = fx.seed_test_slot(
        client,
        env,
        start_at="2026-03-02T00:00:00Z",
        end_at="2026-03-05T20:00:00Z",
        hours=92.00,
        family_code="AC",
        key="slot_a",
    )
    return env


def _engagement_with_a_full_forty_hour_pool(client):
    """A 40.00 h pool fully allocated across an 8.00 h and a 32.00 h slot."""
    env = _engagement_ready_for_slots(client, contracted_hours=40.00)
    env = fx.seed_test_slot(
        client,
        env,
        start_at="2026-03-02T00:00:00Z",
        end_at="2026-03-02T08:00:00Z",
        hours=8.00,
        family_code="AC",
        key="slot_a",
    )
    env = fx.seed_test_slot(
        client,
        env,
        start_at="2026-03-03T00:00:00Z",
        end_at="2026-03-04T08:00:00Z",
        hours=32.00,
        family_code="SC",
        key="slot_b",
    )
    return env


def _authorized_with_denied_and_approved_windows(client):
    """A live authorization carrying one DENIED and one APPROVED change window."""
    env = fx.seed_authorized_offering(client)
    env = fx.seed_change_request(
        client,
        env,
        change_kind="BOUNDARY_CHANGE",
        window_start="2026-05-01T00:00:00Z",
        window_end="2026-05-10T00:00:00Z",
        decision="DENY",
        key="denied_change",
    )
    env = fx.seed_change_request(
        client,
        env,
        change_kind="NEW_SERVICE",
        window_start="2026-06-01T00:00:00Z",
        window_end="2026-06-10T00:00:00Z",
        added_service_count=1,
        decision="APPROVE",
        key="approved_change",
    )
    return env


def _authorized_with_three_decided_windows(client):
    """The two decided windows above plus an APPROVED tech-refresh window."""
    env = _authorized_with_denied_and_approved_windows(client)
    env = fx.seed_change_request(
        client,
        env,
        change_kind="TECH_REFRESH",
        window_start="2026-05-02T00:00:00Z",
        window_end="2026-05-05T00:00:00Z",
        decision="APPROVE",
        key="refresh_change",
    )
    return env


# ---------------------------------------------------------------------------
# Half-open test-slot geometry
# ---------------------------------------------------------------------------


def test_test_slot_starting_one_second_inside_an_existing_slot_is_refused(client):
    """A slot whose start falls one second before an existing slot's end conflicts.

    PRD: "Two slots of the same engagement conflict when the new slot's start falls strictly before the existing slot's end *and* the existing slot's start falls strictly before the new slot's end, evaluated against the engagement's slots in `SCHEDULED` or `COMPLETED` status; a conflict is refused with `ERR_TEST_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/test_slot_half_open_adjacency_is_legal_at_the_shared_instant
    """
    env = _engagement_with_eight_hour_slot(client)

    response = client.create_test_slot(
        f.build_test_slot_payload(
            env["engagement_id"],
            start_at="2026-03-02T16:59:59Z",
            end_at="2026-03-02T20:00:00Z",
            hours=3.00,
            family_code="SC",
        ),
        env["assessor_headers"],
    )
    validate_error(response, ERR_TEST_SLOT_OVERLAP, 409)

    engagement = fx.read_engagement(client, env["engagement_id"])
    at.assert_money(engagement["allocated_hours"], 8.00, "allocated_hours")
    at.assert_money(engagement["unallocated_hours"], 192.00, "unallocated_hours")
    at.assert_hour_conservation(engagement)

    slots, meta = validate_paginated(
        client.list_test_slots(env["engagement_id"], env["assessor_headers"])
    )
    assert meta["total_count"] == 1, (
        f"the refused slot must not have been written, got {meta['total_count']} rows"
    )
    assert at.ids_of(slots) == [env["slot_a_id"]]


def test_test_slot_starting_at_the_instant_the_previous_slot_ends_is_scheduled(client):
    """Zero-gap adjacency is legal: the shared instant belongs to the new slot only.

    PRD: "Slot geometry is half-open — the interval runs from `start_at` inclusive to `end_at` exclusive — and carries no buffer, so a slot beginning at the exact instant a previous slot ends is legal."

    Design: Difficulty/resource_temporal_overlap/test_slot_half_open_adjacency_is_legal_at_the_shared_instant
    """
    env = _engagement_with_eight_hour_slot(client)

    response = client.create_test_slot(
        f.build_test_slot_payload(
            env["engagement_id"],
            start_at="2026-03-02T17:00:00Z",
            end_at="2026-03-02T20:00:00Z",
            hours=3.00,
            family_code="SC",
        ),
        env["assessor_headers"],
    )
    adjacent = validate_success(response, 201)
    at.assert_instant(
        adjacent["start_at"], env["slots"]["slot_a"]["end_at"], "adjacent slot start_at"
    )
    at.assert_instant(adjacent["start_at"], "2026-03-02T17:00:00Z", "start_at")
    assert adjacent["status"] == "SCHEDULED", (
        f"an accepted slot opens at SCHEDULED, got {adjacent['status']}"
    )

    engagement = fx.read_engagement(client, env["engagement_id"])
    at.assert_money(engagement["allocated_hours"], 11.00, "allocated_hours")
    at.assert_money(engagement["unallocated_hours"], 189.00, "unallocated_hours")
    at.assert_hour_conservation(engagement)

    slots, meta = validate_paginated(
        client.list_test_slots(env["engagement_id"], env["assessor_headers"])
    )
    assert meta["total_count"] == 2, (
        f"both slots must coexist, got {meta['total_count']} rows"
    )
    assert adjacent["id"] in at.ids_of(slots)


# ---------------------------------------------------------------------------
# A cancelled slot frees its interval and its hours
# ---------------------------------------------------------------------------


def test_interval_occupied_by_a_scheduled_slot_cannot_be_booked_twice(client):
    """The overlap population is the SCHEDULED and COMPLETED slots of the engagement.

    PRD: "Two slots of the same engagement conflict when the new slot's start falls strictly before the existing slot's end *and* the existing slot's start falls strictly before the new slot's end, evaluated against the engagement's slots in `SCHEDULED` or `COMPLETED` status; a conflict is refused with `ERR_TEST_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/cancelled_test_slot_frees_its_interval_for_reuse
    """
    env = _engagement_with_ninety_two_hour_slot(client)

    response = client.create_test_slot(
        f.build_test_slot_payload(
            env["engagement_id"],
            start_at="2026-03-02T00:00:00Z",
            end_at="2026-03-05T20:00:00Z",
            hours=8.00,
            family_code="SC",
        ),
        env["assessor_headers"],
    )
    validate_error(response, ERR_TEST_SLOT_OVERLAP, 409)

    engagement = fx.read_engagement(client, env["engagement_id"])
    at.assert_money(engagement["allocated_hours"], 92.00, "allocated_hours")
    at.assert_money(engagement["unallocated_hours"], 8.00, "unallocated_hours")
    at.assert_hour_conservation(engagement)

    _, meta = validate_paginated(
        client.list_test_slots(env["engagement_id"], env["assessor_headers"])
    )
    assert meta["total_count"] == 1, (
        f"the refused slot must not have been written, got {meta['total_count']} rows"
    )


def test_cancelling_a_test_slot_returns_its_hours_to_the_unallocated_pool(client):
    """Cancellation is terminal for the slot and compensating for the hour pool.

    PRD: "Cancelling a slot moves it `SCHEDULED → CANCELLED`, which is terminal — a slot that is not `SCHEDULED` is refused with `ERR_ALREADY_TERMINAL` — requires the acting `X-User-ID` to equal the engagement's `assessor_user_id`, returns the slot's `hours` to `unallocated_hours` while removing them from `allocated_hours`, and increments the engagement's `version` by one."

    Design: Difficulty/resource_temporal_overlap/cancelled_test_slot_frees_its_interval_for_reuse
    """
    env = _engagement_with_ninety_two_hour_slot(client)

    cancelled = validate_success(
        client.cancel_test_slot(env["slot_a_id"], env["assessor_headers"]), 200
    )
    assert cancelled["status"] == "CANCELLED", (
        f"the cancelled slot must read CANCELLED, got {cancelled['status']}"
    )

    engagement = fx.read_engagement(client, env["engagement_id"])
    at.assert_money(engagement["allocated_hours"], 0.00, "allocated_hours")
    at.assert_money(engagement["unallocated_hours"], 100.00, "unallocated_hours")
    at.assert_hour_conservation(engagement)

    rows, meta = validate_paginated(
        client.list_test_slots(
            env["engagement_id"], env["assessor_headers"], {"status": "CANCELLED"}
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one slot is cancelled, got {meta['total_count']}"
    )
    assert at.ids_of(rows) == [env["slot_a_id"]]


def test_interval_of_a_cancelled_test_slot_can_be_booked_again(client):
    """The very interval refused while the slot was SCHEDULED is bookable once cancelled.

    PRD: "Cancelled slots free their interval and never conflict."

    Design: Difficulty/resource_temporal_overlap/cancelled_test_slot_frees_its_interval_for_reuse
    """
    env = _engagement_with_ninety_two_hour_slot(client)
    validate_success(
        client.cancel_test_slot(env["slot_a_id"], env["assessor_headers"]), 200
    )

    reused = validate_success(
        client.create_test_slot(
            f.build_test_slot_payload(
                env["engagement_id"],
                start_at="2026-03-02T00:00:00Z",
                end_at="2026-03-05T20:00:00Z",
                hours=8.00,
                family_code="SC",
            ),
            env["assessor_headers"],
        ),
        201,
    )
    at.assert_instant(reused["start_at"], "2026-03-02T00:00:00Z", "start_at")
    at.assert_instant(reused["end_at"], "2026-03-05T20:00:00Z", "end_at")
    assert reused["status"] == "SCHEDULED", (
        f"the re-booked slot opens at SCHEDULED, got {reused['status']}"
    )
    assert reused["id"] != env["slot_a_id"]

    engagement = fx.read_engagement(client, env["engagement_id"])
    at.assert_money(engagement["allocated_hours"], 8.00, "allocated_hours")
    at.assert_money(engagement["unallocated_hours"], 92.00, "unallocated_hours")
    at.assert_hour_conservation(engagement)


# ---------------------------------------------------------------------------
# Closed change windows and the inclusive seven-day buffer
# ---------------------------------------------------------------------------


def test_change_window_inside_a_denied_window_is_accepted(client):
    """A denied change request imposes no quiet buffer at all.

    PRD: "A `DENIED` change request never blocks a new window."

    Design: Difficulty/resource_temporal_overlap/change_window_buffer_uses_closed_intervals_and_skips_denied_windows
    """
    env = _authorized_with_denied_and_approved_windows(client)

    filed = validate_success(
        client.create_change_request(
            f.build_change_request_payload(
                env["offering_id"],
                "2026-05-02T00:00:00Z",
                "2026-05-05T00:00:00Z",
                change_kind="TECH_REFRESH",
            ),
            env["lead_headers"],
        ),
        201,
    )
    assert filed["status"] == "SUBMITTED", (
        f"a filed change request opens at SUBMITTED, got {filed['status']}"
    )
    assert filed["requires_reassessment"] is False, (
        "a TECH_REFRESH adding no service does not require reassessment, got "
        f"{filed['requires_reassessment']!r}"
    )
    at.assert_instant(filed["window_start"], "2026-05-02T00:00:00Z", "window_start")
    at.assert_instant(filed["window_end"], "2026-05-05T00:00:00Z", "window_end")


def test_approving_a_tech_refresh_leaves_the_boundary_untouched(client):
    """Only a boundary change or a new service moves the offering's boundary version.

    PRD: "An `APPROVE` of a `BOUNDARY_CHANGE` or a `NEW_SERVICE` increments the offering's `boundary_version` by one, and an `APPROVE` of a `NEW_SERVICE` additionally increases the offering's `included_service_count` by the request's `added_service_count`; an `APPROVE` of a `TECH_REFRESH` leaves both untouched."

    Design: Difficulty/resource_temporal_overlap/change_window_buffer_uses_closed_intervals_and_skips_denied_windows
    """
    env = _authorized_with_denied_and_approved_windows(client)
    before = fx.read_offering(client, env["offering_id"])
    at.assert_integer(before["boundary_version"], 2, "boundary_version before")
    at.assert_integer(before["included_service_count"], 1, "included_service_count before")

    env = fx.seed_change_request(
        client,
        env,
        change_kind="TECH_REFRESH",
        window_start="2026-05-02T00:00:00Z",
        window_end="2026-05-05T00:00:00Z",
        decision="APPROVE",
        key="refresh_change",
    )
    assert env["refresh_change"]["status"] == "APPROVED", (
        f"the decided request is terminal at APPROVED, got {env['refresh_change']['status']}"
    )

    after = fx.read_offering(client, env["offering_id"])
    at.assert_integer(after["boundary_version"], 2, "boundary_version after")
    assert after["boundary_version"] != 3, (
        "a TECH_REFRESH approval must not bump boundary_version"
    )
    at.assert_integer(after["included_service_count"], 1, "included_service_count after")
    assert after["status"] == "AUTHORIZED", (
        f"the offering returns to AUTHORIZED after the decision, got {after['status']}"
    )


def test_change_window_six_days_after_an_approved_window_violates_the_buffer(client):
    """Six days of clearance from an approved window is too close.

    PRD: "For every other change request of the same offering whose `status` is `SUBMITTED` or `APPROVED`, the new window is acceptable only if it is separated from that window by at least seven days on one side or the other: either the new `window_start` is at least seven days after the existing `window_end`, or the existing `window_start` is at least seven days after the new `window_end`."

    Design: Difficulty/resource_temporal_overlap/change_window_buffer_uses_closed_intervals_and_skips_denied_windows
    """
    env = _authorized_with_three_decided_windows(client)

    response = client.create_change_request(
        f.build_change_request_payload(
            env["offering_id"],
            "2026-06-16T00:00:00Z",
            "2026-06-20T00:00:00Z",
            change_kind="BOUNDARY_CHANGE",
        ),
        env["lead_headers"],
    )
    validate_error(response, ERR_CHANGE_WINDOW_BUFFER_VIOLATION, 409)

    rows, meta = validate_paginated(
        client.list_change_requests(
            env["lead_headers"], {"offering_id": env["offering_id"]}
        )
    )
    assert meta["total_count"] == 3, (
        f"the refused window must not have been written, got {meta['total_count']} rows"
    )
    assert all(
        not at.instants_equal(row["window_start"], "2026-06-16T00:00:00Z")
        for row in rows
    ), "no change request may carry the refused window_start 2026-06-16T00:00:00Z"

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "AUTHORIZED", (
        f"a refused filing leaves the offering AUTHORIZED, got {offering['status']}"
    )


def test_change_window_exactly_seven_days_after_an_approved_window_is_accepted(client):
    """The seven-day buffer is inclusive, so exactly seven days of clearance passes.

    PRD: "The comparison is on full instants and the seven-day figure is inclusive, so exactly seven days of separation is accepted while six days, 23 hours, 59 minutes and 59 seconds is not."

    Design: Difficulty/resource_temporal_overlap/change_window_buffer_uses_closed_intervals_and_skips_denied_windows
    """
    env = _authorized_with_three_decided_windows(client)

    filed = validate_success(
        client.create_change_request(
            f.build_change_request_payload(
                env["offering_id"],
                "2026-06-17T00:00:00Z",
                "2026-06-21T00:00:00Z",
                change_kind="BOUNDARY_CHANGE",
            ),
            env["lead_headers"],
        ),
        201,
    )
    assert filed["status"] == "SUBMITTED", (
        f"a filed change request opens at SUBMITTED, got {filed['status']}"
    )
    assert filed["requires_reassessment"] is True, (
        "a BOUNDARY_CHANGE always requires reassessment, got "
        f"{filed['requires_reassessment']!r}"
    )

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "CHANGE_UNDER_REVIEW", (
        f"filing drives the offering to CHANGE_UNDER_REVIEW, got {offering['status']}"
    )
    at.assert_integer(offering["included_service_count"], 1, "included_service_count")

    _, meta = validate_paginated(
        client.list_change_requests(
            env["lead_headers"], {"offering_id": env["offering_id"]}
        )
    )
    assert meta["total_count"] == 4, (
        f"the offering now holds four change requests, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Assessment hour conservation
# ---------------------------------------------------------------------------


def test_refused_slot_over_an_exhausted_hour_pool_leaves_the_ledger_untouched(client):
    """A free interval does not help once the unallocated pool is empty.

    PRD: "Before a slot row is written the requested hours are compared against `unallocated_hours`: hours exceeding the unallocated pool are refused with `ERR_ENGAGEMENT_HOURS_EXHAUSTED`, while hours exactly equal to the pool are accepted and drive `unallocated_hours` to 0.00."

    Design: Difficulty/compensating_invariant/engagement_hour_pool_is_conserved_across_allocation_cancel_and_reallocation
    """
    env = _engagement_with_a_full_forty_hour_pool(client)
    before = fx.read_engagement(client, env["engagement_id"])
    at.assert_money(before["contracted_hours"], 40.00, "contracted_hours")
    at.assert_money(before["allocated_hours"], 40.00, "allocated_hours")
    at.assert_money(before["unallocated_hours"], 0.00, "unallocated_hours")
    at.assert_hour_conservation(before)

    response = client.create_test_slot(
        f.build_test_slot_payload(
            env["engagement_id"],
            start_at="2026-03-05T00:00:00Z",
            end_at="2026-03-05T01:00:00Z",
            hours=0.01,
            family_code="SC",
        ),
        env["assessor_headers"],
    )
    validate_error(response, ERR_ENGAGEMENT_HOURS_EXHAUSTED, 422)

    after = fx.read_engagement(client, env["engagement_id"])
    at.assert_money(after["allocated_hours"], 40.00, "allocated_hours")
    at.assert_money(after["unallocated_hours"], 0.00, "unallocated_hours")
    at.assert_hour_conservation(after)


def test_cancelling_one_slot_restores_the_hour_identity_without_touching_the_other(
    client,
):
    """Cancelling the 32.00 h slot moves exactly those hours back to the pool.

    PRD: "Cancelling a test slot returns that slot's hours to the unallocated pool and removes them from the allocated total, restoring the identity exactly."

    Design: Difficulty/compensating_invariant/engagement_hour_pool_is_conserved_across_allocation_cancel_and_reallocation
    """
    env = _engagement_with_a_full_forty_hour_pool(client)

    cancelled = validate_success(
        client.cancel_test_slot(env["slot_b_id"], env["assessor_headers"]), 200
    )
    assert cancelled["status"] == "CANCELLED", (
        f"the cancelled slot must read CANCELLED, got {cancelled['status']}"
    )

    engagement = fx.read_engagement(client, env["engagement_id"])
    at.assert_money(engagement["allocated_hours"], 8.00, "allocated_hours")
    at.assert_money(engagement["unallocated_hours"], 32.00, "unallocated_hours")
    at.assert_money(engagement["contracted_hours"], 40.00, "contracted_hours")
    at.assert_hour_conservation(engagement)

    surviving, _ = validate_paginated(
        client.list_test_slots(
            env["engagement_id"], env["assessor_headers"], {"status": "SCHEDULED"}
        )
    )
    assert at.ids_of(surviving) == [env["slot_a_id"]], (
        "the 8.00 h slot stays SCHEDULED throughout"
    )


def test_reallocating_the_freed_hours_returns_the_pool_to_fully_allocated(client):
    """Re-booking the cancelled slot's 32.00 h drives the pool back to 40.00 + 0.00.

    PRD: "An engagement's `contracted_hours` always equals its `allocated_hours` plus its `unallocated_hours`."

    Design: Difficulty/compensating_invariant/engagement_hour_pool_is_conserved_across_allocation_cancel_and_reallocation
    """
    env = _engagement_with_a_full_forty_hour_pool(client)
    validate_success(
        client.cancel_test_slot(env["slot_b_id"], env["assessor_headers"]), 200
    )
    at.assert_hour_conservation(fx.read_engagement(client, env["engagement_id"]))

    reallocated = validate_success(
        client.create_test_slot(
            f.build_test_slot_payload(
                env["engagement_id"],
                start_at="2026-03-03T00:00:00Z",
                end_at="2026-03-04T08:00:00Z",
                hours=32.00,
                family_code="SC",
            ),
            env["assessor_headers"],
        ),
        201,
    )
    at.assert_money(reallocated["hours"], 32.00, "hours")
    assert reallocated["status"] == "SCHEDULED", (
        f"the re-allocated slot opens at SCHEDULED, got {reallocated['status']}"
    )

    engagement = fx.read_engagement(client, env["engagement_id"])
    at.assert_money(engagement["allocated_hours"], 40.00, "allocated_hours")
    at.assert_money(engagement["unallocated_hours"], 0.00, "unallocated_hours")
    at.assert_money(engagement["contracted_hours"], 40.00, "contracted_hours")
    at.assert_hour_conservation(engagement)


# ---------------------------------------------------------------------------
# Reuse seat conservation
# ---------------------------------------------------------------------------


def _authorized_with_two_further_agencies(client):
    """A live authorization plus the EPA and HHS agencies that will reuse it."""
    env = fx.seed_authorized_offering(client)
    env = fx.add_agency(
        client,
        env,
        name="Environmental Protection Agency",
        agency_code="EPA",
        key="epa",
    )
    env = fx.add_agency(
        client,
        env,
        name="Department of Health and Human Services",
        agency_code="HHS",
        key="hhs",
    )
    return env


def _request_reuse(client, env, agency_key):
    """Request reuse for one agency against the freshly observed authorization version."""
    return client.create_reuse_grant(
        f.build_reuse_grant_payload(
            env["authorization_id"],
            env[f"{agency_key}_id"],
            fx.authorization_version(client, env["authorization_id"]),
        ),
        env[f"{agency_key}_headers"],
    )


def test_two_reuse_grants_consume_two_seats_and_conserve_the_pool(client):
    """Each grant moves one seat from available to granted, leaving the total at 5.

    PRD: "An authorization's `reuse_seats_total` always equals its `reuse_seats_granted` plus its `reuse_seats_available`."

    Design: Difficulty/compensating_invariant/reuse_seat_pool_is_conserved_across_grant_revoke_and_regrant
    """
    env = _authorized_with_two_further_agencies(client)
    opening = fx.read_authorization(client, env["authorization_id"])
    at.assert_integer(opening["reuse_seats_total"], 5, "reuse_seats_total")
    at.assert_integer(opening["reuse_seats_granted"], 0, "reuse_seats_granted")
    at.assert_integer(opening["reuse_seats_available"], 5, "reuse_seats_available")
    at.assert_seat_conservation(opening)

    epa_grant = validate_success(_request_reuse(client, env, "epa"), 201)
    assert epa_grant["access_state"] == "REQUESTED", (
        f"a new grant opens at REQUESTED, got {epa_grant['access_state']}"
    )
    after_epa = fx.read_authorization(client, env["authorization_id"])
    at.assert_integer(after_epa["reuse_seats_granted"], 1, "reuse_seats_granted")
    at.assert_integer(after_epa["reuse_seats_available"], 4, "reuse_seats_available")
    at.assert_integer(after_epa["reuse_seats_total"], 5, "reuse_seats_total")
    at.assert_seat_conservation(after_epa)

    hhs_grant = validate_success(_request_reuse(client, env, "hhs"), 201)
    assert hhs_grant["access_state"] == "REQUESTED", (
        f"a new grant opens at REQUESTED, got {hhs_grant['access_state']}"
    )
    after_hhs = fx.read_authorization(client, env["authorization_id"])
    at.assert_integer(after_hhs["reuse_seats_granted"], 2, "reuse_seats_granted")
    at.assert_integer(after_hhs["reuse_seats_available"], 3, "reuse_seats_available")
    at.assert_integer(after_hhs["reuse_seats_total"], 5, "reuse_seats_total")
    at.assert_seat_conservation(after_hhs)

    at.assert_integer(
        fx.read_agency(client, env["epa_id"])["reuse_grant_count"],
        1,
        "EPA reuse_grant_count",
    )
    at.assert_integer(
        fx.read_agency(client, env["hhs_id"])["reuse_grant_count"],
        1,
        "HHS reuse_grant_count",
    )


def test_revoking_a_reuse_grant_returns_its_seat_and_decrements_the_agency_counter(
    client,
):
    """Revocation compensates the seat ledger and the grantee agency's counter together.

    PRD: "It returns the seat — the authorization's `reuse_seats_granted` decreases by one and `reuse_seats_available` increases by one — decrements the agency's `reuse_grant_count` by one, decrements that agency's `open_notice_count` by one when the grant was sitting in `NOTICE_ISSUED`, and increments the authorization's `version` by one."

    Design: Difficulty/compensating_invariant/reuse_seat_pool_is_conserved_across_grant_revoke_and_regrant
    """
    env = _authorized_with_two_further_agencies(client)
    epa_grant = validate_success(_request_reuse(client, env, "epa"), 201)
    validate_success(_request_reuse(client, env, "hhs"), 201)

    revoked = validate_success(
        client.revoke_reuse_grant(
            epa_grant["id"],
            f.build_revoke_payload("AGENCY_REQUEST"),
            env["epa_headers"],
        ),
        200,
    )
    assert revoked["access_state"] == "REVOKED", (
        f"the revoked grant must read REVOKED, got {revoked['access_state']}"
    )
    assert revoked["revoked_reason"] == "AGENCY_REQUEST", (
        f"revoked_reason records the supplied reason, got {revoked['revoked_reason']!r}"
    )

    authorization = fx.read_authorization(client, env["authorization_id"])
    at.assert_integer(authorization["reuse_seats_granted"], 1, "reuse_seats_granted")
    at.assert_integer(authorization["reuse_seats_available"], 4, "reuse_seats_available")
    at.assert_integer(authorization["reuse_seats_total"], 5, "reuse_seats_total")
    at.assert_seat_conservation(authorization)

    at.assert_integer(
        fx.read_agency(client, env["epa_id"])["reuse_grant_count"],
        0,
        "EPA reuse_grant_count",
    )
    at.assert_integer(
        fx.read_agency(client, env["hhs_id"])["reuse_grant_count"],
        1,
        "HHS reuse_grant_count",
    )


def test_reuse_may_be_requested_again_once_the_earlier_grant_is_revoked(client):
    """A revoked grant is not a live grant, so the same pair may take a fresh seat.

    PRD: "The same pair of authorization and agency may not hold two live grants: an existing grant for that pair in any state other than `REVOKED` causes `ERR_DUPLICATE_REUSE_GRANT`."

    Design: Difficulty/compensating_invariant/reuse_seat_pool_is_conserved_across_grant_revoke_and_regrant
    """
    env = _authorized_with_two_further_agencies(client)
    epa_grant = validate_success(_request_reuse(client, env, "epa"), 201)
    validate_success(_request_reuse(client, env, "hhs"), 201)
    validate_success(
        client.revoke_reuse_grant(
            epa_grant["id"],
            f.build_revoke_payload("AGENCY_REQUEST"),
            env["epa_headers"],
        ),
        200,
    )

    regrant = validate_success(_request_reuse(client, env, "epa"), 201)
    assert regrant["id"] != epa_grant["id"], (
        "the re-grant is a new row, not a revival of the revoked one"
    )
    assert regrant["access_state"] == "REQUESTED", (
        f"a new grant opens at REQUESTED, got {regrant['access_state']}"
    )

    authorization = fx.read_authorization(client, env["authorization_id"])
    at.assert_integer(authorization["reuse_seats_granted"], 2, "reuse_seats_granted")
    at.assert_integer(authorization["reuse_seats_available"], 3, "reuse_seats_available")
    at.assert_integer(authorization["reuse_seats_total"], 5, "reuse_seats_total")
    at.assert_seat_conservation(authorization)

    at.assert_integer(
        fx.read_agency(client, env["epa_id"])["reuse_grant_count"],
        1,
        "EPA reuse_grant_count",
    )
    earlier = fx.read_reuse_grant(client, epa_grant["id"])
    assert earlier["access_state"] == "REVOKED", (
        f"the earlier grant stays REVOKED, got {earlier['access_state']}"
    )
