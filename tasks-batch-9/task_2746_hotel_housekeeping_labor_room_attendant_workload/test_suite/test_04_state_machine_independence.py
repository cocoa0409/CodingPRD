"""State machines that revisit states, and dimensions that advance independently."""

from test_helpers import (
    ASSIGN_COMPLETED,
    ASSIGN_RECLEAN_REQUIRED,
    CLAIM_APPROVE,
    CLAIM_DENY,
    CLEAN_CLEAN,
    CLEAN_IN_SERVICE,
    COMPLIANCE_AT_LIMIT,
    COMPLIANCE_BREACH_BLOCKED,
    DEFAULT_BUSINESS_DATE,
    DIRECTOR_HEADERS,
    DISPOSITION_RELEASED,
    FRONT_DESK_HEADERS,
    ITEM_CLAIM_PENDING,
    ITEM_RELEASED,
    ITEM_STORED,
    ORDINANCE_NONE,
    PROOF_DESCRIPTION_MATCH,
    PROOF_PHOTO_ID,
    ROSTER_CLOCKED_IN,
    ROSTER_PLANNED,
    SERVICE_CHECKOUT,
    SERVICE_DEEP_CLEAN,
    WAIVER_NONE,
    WAIVER_REQUESTED,
    assert_business_date,
    assert_credits,
    assert_instant_equals,
    assert_is_null,
    assert_roster_dimensions,
    build_lost_found,
    build_scenario,
    claim_decision_payload,
    claim_payload,
    clock_in,
    get_success_data,
    patch_attendant,
    read_assignment,
    read_room,
    read_roster,
    request_waiver,
    validate_paginated,
)

DENIAL_REASON = "Description did not match the recovered item"


def _reclean_of(api, assignment_id):
    """Re-clean rows are discovered only by filtering on `supersedes_assignment_id`."""
    rows, _ = validate_paginated(
        api.list_room_assignments(
            {"supersedes_assignment_id": assignment_id}, DIRECTOR_HEADERS
        )
    )
    assert len(rows) == 1, (
        f"exactly one re-clean should supersede {assignment_id}, got {len(rows)}"
    )
    return rows[0]


def _failed_then_pending_reclean(api):
    """A cleaned room condemned by its inspection, with the re-clean row waiting."""
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": "DUE_OUT"}],
        linen={"total_owned_sets": 20},
    )
    first = scenario.clean(
        "101",
        SERVICE_CHECKOUT,
        "2026-08-03T10:00:00.000Z",
        "2026-08-03T10:30:00.000Z",
    )
    scenario.inspect(first["id"], bathroom_points=5)
    return scenario, first, _reclean_of(api, first["id"])


def test_room_condition_traverses_in_service_a_second_time_on_the_reclean(api):
    """The re-clean drives the room back through IN_SERVICE and on to CLEAN.

    PRD 3.5: "for a system-generated re-clean — an assignment whose
    `reclean_generation` is 1 or more — it is the edge `RECLEAN_REQUIRED →
    IN_SERVICE`, which is what closes the service loop `RECLEAN_REQUIRED →
    IN_SERVICE → CLEAN` and makes the room-condition machine genuinely cyclic."

    Design: Difficulty/non_linear_state_machine/room_cleanliness_revisits_in_service_through_reclean_loop
    """
    scenario, _, reclean = _failed_then_pending_reclean(api)

    scenario.start(reclean["id"], "2026-08-03T11:00:00.000Z")
    mid_loop = read_room(api, scenario.room_id("101"))
    scenario.complete(reclean["id"], "2026-08-03T11:40:00.000Z")

    assert mid_loop["cleanliness_status"] == CLEAN_IN_SERVICE, (
        "the re-clean start must drive the room back into IN_SERVICE"
    )
    assert read_room(api, scenario.room_id("101"))["cleanliness_status"] == CLEAN_CLEAN


def test_completed_reclean_keeps_its_superseded_row_in_reclean_required(api):
    """The re-clean completes at generation 1 while the row it supersedes stays condemned.

    PRD 2.8: "Assignments in `CANCELLED` or `DEFERRED` are excluded from both
    sums; every other status is counted, including `RECLEAN_REQUIRED` rows that
    have already been superseded by a re-clean, so a failed clean continues to
    consume ordinance headroom alongside its replacement."

    Design: Difficulty/non_linear_state_machine/room_cleanliness_revisits_in_service_through_reclean_loop
    """
    scenario, first, reclean = _failed_then_pending_reclean(api)

    scenario.start(reclean["id"], "2026-08-03T11:00:00.000Z")
    finished = scenario.complete(reclean["id"], "2026-08-03T11:40:00.000Z")

    assert finished["reclean_generation"] == 1, (
        f"reclean_generation should be 1, got {finished['reclean_generation']}"
    )
    assert finished["supersedes_assignment_id"] == first["id"]
    assert finished["status"] == ASSIGN_COMPLETED
    assert read_assignment(api, first["id"])["status"] == ASSIGN_RECLEAN_REQUIRED
    assert_business_date(
        read_room(api, scenario.room_id("101"))["last_serviced_business_date"],
        DEFAULT_BUSINESS_DATE,
        "last_serviced_business_date",
    )


def _roster_at_its_credit_ceiling(api):
    """Two deep cleans land a PLANNED roster exactly on a 4.00-credit ceiling."""
    scenario = build_scenario(
        api,
        property_overrides={
            "ordinance_profile": ORDINANCE_NONE,
            "max_daily_credits": 4.00,
        },
        rooms=["103", "104"],
        linen={"total_owned_sets": 20},
        clocked_in=False,
    )
    scenario.assign("103", SERVICE_DEEP_CLEAN)
    scenario.assign("104", SERVICE_DEEP_CLEAN)
    return scenario


def test_clocking_in_advances_only_the_lifecycle_dimension(api):
    """Clock-in moves PLANNED to CLOCKED_IN and leaves the ordinance dimension at AT_LIMIT.

    PRD 2.8: "Clocking in advances `status` and leaves `compliance_state` and
    `waiver_state` untouched; filing a waiver advances `waiver_state` and leaves
    `status` and `compliance_state` untouched."

    Design: Difficulty/non_linear_state_machine/roster_lifecycle_and_compliance_dimensions_move_independently
    """
    scenario = _roster_at_its_credit_ceiling(api)
    before = read_roster(api, scenario.roster_id)
    assert_roster_dimensions(before, ROSTER_PLANNED, COMPLIANCE_AT_LIMIT, WAIVER_NONE)
    assert_credits(before["assigned_credits"], 4.00, "assigned_credits")

    after = clock_in(api, scenario.roster_id, scenario.worker_id)

    assert_roster_dimensions(
        after, ROSTER_CLOCKED_IN, COMPLIANCE_AT_LIMIT, WAIVER_NONE
    )


def test_restricted_duty_and_waiver_filing_move_two_dimensions_without_the_third(api):
    """The cap reduction flips compliance, the waiver filing moves waiver_state, status holds.

    PRD 3.3: "A successful filing stamps `waiver_requested_credits`, records
    `waiver_requested_by_user_id` from the acting `X-User-ID`, advances
    `waiver_state` from `NONE` to `REQUESTED`, and increments the roster's
    `version`; `status` and `compliance_state` are both left untouched."

    Design: Difficulty/non_linear_state_machine/roster_lifecycle_and_compliance_dimensions_move_independently
    """
    scenario = _roster_at_its_credit_ceiling(api)
    clock_in(api, scenario.roster_id, scenario.worker_id)

    patch_attendant(api, scenario.worker_id, restricted_duty=True)
    reduced = read_roster(api, scenario.roster_id)
    assert_credits(reduced["effective_credit_cap"], 3.00, "effective_credit_cap")
    assert_roster_dimensions(
        reduced, ROSTER_CLOCKED_IN, COMPLIANCE_BREACH_BLOCKED, WAIVER_NONE
    )

    filed = request_waiver(api, scenario.roster_id, 3.75, scenario.inspector_id)

    assert_roster_dimensions(
        filed, ROSTER_CLOCKED_IN, COMPLIANCE_BREACH_BLOCKED, WAIVER_REQUESTED
    )
    assert filed["waiver_requested_by_user_id"] == scenario.inspector_id, (
        "the filing supervisor's own identifier must be stamped on the roster"
    )
    assert_credits(filed["waiver_requested_credits"], 3.75, "waiver_requested_credits")


def _denied_claim(api):
    """A STORED standard item whose first claim was denied on the description."""
    context = build_lost_found(
        api, clock="2026-08-03T08:00:00.000Z", stored=True, storage_bin="B-12"
    )
    get_success_data(
        api.claim_item(
            context.item_id,
            claim_payload(
                claimant_name="Dana Wu",
                claimant_contact="dana@example.com",
                proof_kind=PROOF_DESCRIPTION_MATCH,
            ),
            FRONT_DESK_HEADERS,
        )
    )
    denied = get_success_data(
        api.decide_claim(
            context.item_id,
            claim_decision_payload(CLAIM_DENY, denial_reason=DENIAL_REASON),
            context.supervisor_headers(),
        )
    )
    return context, denied


def test_denied_claim_reenters_stored_and_admits_a_second_claimant(api):
    """A denial returns the item to STORED with its retention clock still running.

    PRD 3.9: "That last point is the reason denial returns the item to `STORED`
    rather than to a terminal state: the retention clock keeps running, so a
    second claimant may file inside the same window, and `claim_attempt_count`
    records every attempt including the denied ones."

    Design: Difficulty/non_linear_state_machine/lost_found_claim_denial_reenters_stored_and_permits_second_claim
    """
    context, denied = _denied_claim(api)
    assert denied["status"] == ITEM_STORED
    assert denied["retention_days"] == 30
    assert_instant_equals(
        denied["retention_expires_at"],
        "2026-09-02T08:00:00.000Z",
        "retention_expires_at",
    )

    second = get_success_data(
        api.claim_item(
            context.item_id,
            claim_payload(
                claimant_name="Dana Wu",
                claimant_contact="dana@example.com",
                proof_kind=PROOF_PHOTO_ID,
            ),
            FRONT_DESK_HEADERS,
        )
    )

    assert second["status"] == ITEM_CLAIM_PENDING
    assert second["claim_attempt_count"] == 2, (
        f"claim_attempt_count should count both attempts, got {second['claim_attempt_count']}"
    )
    assert second["proof_kind"] == PROOF_PHOTO_ID


def test_second_claim_can_be_approved_and_released_after_the_first_was_denied(api):
    """The re-entered item reaches RELEASED, keeping the recorded denial reason.

    PRD 3.9: "An approved pickup advances `CLAIM_PENDING → RELEASED`, clears
    `storage_bin` because the item has left the property, and leaves
    `tracking_code` null."

    Design: Difficulty/non_linear_state_machine/lost_found_claim_denial_reenters_stored_and_permits_second_claim
    """
    context, _ = _denied_claim(api)
    get_success_data(
        api.claim_item(
            context.item_id,
            claim_payload(
                claimant_name="Dana Wu",
                claimant_contact="dana@example.com",
                proof_kind=PROOF_PHOTO_ID,
            ),
            FRONT_DESK_HEADERS,
        )
    )

    released = get_success_data(
        api.decide_claim(
            context.item_id,
            claim_decision_payload(
                CLAIM_APPROVE, disposition=DISPOSITION_RELEASED
            ),
            context.supervisor_headers(),
        )
    )

    assert released["status"] == ITEM_RELEASED
    assert_is_null(released["storage_bin"], "storage_bin")
    assert released["denial_reason"] == DENIAL_REASON, (
        "the recorded denial reason must survive the later approval"
    )
    assert_instant_equals(
        released["retention_expires_at"],
        "2026-09-02T08:00:00.000Z",
        "retention_expires_at",
    )
