"""Calendar exclusivity, cross-aggregate gating and the program's three ledgers.

This module drives the places where the residual earthquake program lets one
aggregate's state decide another's, and where money has to come back exactly the
way it went out. A verification visit may not be booked within sixty minutes of
another pending visit on the same contractor's calendar; a funding cycle's
application window is exclusive within its program track and stays reserved even
after the cycle closes; a renewal stalls because the annual re-offer pushed the
mandatory offer out of ACCEPTED; a bind stalls because the take-up evaluation
sanctioned the carrier over its undocumented declines. The remaining tests walk
the three conservation identities to the cent: the funding pool across
reservation, disbursement and withdrawal, the premium ledger across a mitigation
discount and its revocation, and an event's loss waterfall across finalization,
reopening and re-finalization.
"""
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CLAIM_ADJUSTER_ALT_HEADERS,
    CLAIM_ADJUSTER_HEADERS,
    FIELD_INSPECTOR_HEADERS,
    PROGRAM_ADMIN_ALT_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
)
from test_helpers.test_users import make_insurer_headers, make_policyholder_headers


def _instant(value: str) -> datetime:
    """Read an ISO 8601 UTC instant, tolerating the trailing Z and any fractions."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _read_cycle(api, cycle_id):
    """Re-read a funding cycle and its pool ledger."""
    return validate_success(api.get_grant_cycle(cycle_id, PROGRAM_ADMIN_HEADERS))


def _read_event(api, event_id):
    """Re-read a catastrophe event and its loss waterfall."""
    return validate_success(api.get_catastrophe_event(event_id, PROGRAM_ADMIN_HEADERS))


def _read_layer(api, layer_id):
    """Re-read one reinsurance layer and the amount ceded to it."""
    return validate_success(api.get_reinsurance_layer(layer_id, PROGRAM_ADMIN_HEADERS))


def _read_policy(api, policy_id):
    """Re-read a policy and its premium ledger."""
    return validate_success(api.get_policy(policy_id, PROGRAM_ADMIN_HEADERS))


def _cripple_wall_project_awaiting_inspection(api, cycle, contractor):
    """A funded cripple-wall retrofit, assigned to one shared contractor and ready
    to be visited."""
    bound = fixtures.setup_bound_policy(
        api, dwelling_overrides={"structure_type": "WOOD_FRAME_CRIPPLE_WALL"}
    )
    return fixtures.setup_project_awaiting_inspection(
        api,
        ctx=bound,
        cycle=cycle,
        contractor=contractor,
        project_cost_estimate_cents=250000,
    )


def _book_visit(api, project_id, window_start, window_end):
    """Ask for a verification visit on the contractor calendar."""
    return api.create_inspection(
        factories.create_inspection_payload(project_id, window_start, window_end),
        FIELD_INSPECTOR_HEADERS,
    )


def _open_brace_and_bolt_cycle(api, total_pool_cents=2000000):
    """A BRACE_AND_BOLT funding cycle open across the whole test calendar."""
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    return fixtures.create_grant_cycle(
        api, program_track="BRACE_AND_BOLT", total_pool_cents=total_pool_cents
    )


def test_01_visit_abutting_the_late_buffer_is_booked_and_one_minute_inside_is_refused(api):
    """PRD §3.6: "The calendar rule is the sharpest of the temporal constraints: widen the requested window by sixty minutes on **both** sides, and if the widened interval intersects the half-open window of any existing inspection that is still `PENDING`, belongs to the same `contractor_id`, and sits on a project that is not `ABANDONED`, the booking is refused with `ERR_INSPECTION_SLOT_OVERLAP`."

    PRD §3.6: "The window is half-open — it includes `window_start` and excludes `window_end` — must be at least thirty and at most two hundred and forty minutes long, both bounds inclusive, and must begin at or after the current logical clock; a visit booked into the past is refused with `ERR_INSPECTION_IN_PAST`."

    PRD §3.6: "The project must be in `AWAITING_INSPECTION`, and the inspection's `contractor_id` is copied from the project rather than taken from the caller; a caller-supplied `contractor_id` that disagrees with the project's is refused with `ERR_INSPECTION_PROJECT_MISMATCH`."

    Design: Difficulty/resource_temporal_overlap/contractor_calendar_half_open_windows_widened_60_minutes_on_both_sides
    """
    cycle = _open_brace_and_bolt_cycle(api)
    contractor = fixtures.create_contractor(api, ["CRIPPLE_WALL_BRACING"])
    held = _cripple_wall_project_awaiting_inspection(api, cycle, contractor)
    probed = _cripple_wall_project_awaiting_inspection(api, cycle, contractor)

    incumbent = validate_success(
        _book_visit(
            api,
            held["project"]["id"],
            "2026-10-05T09:00:00Z",
            "2026-10-05T11:00:00Z",
        ),
        201,
    )
    assert incumbent["contractor_id"] == contractor["id"], (
        "the visit must take its contractor from the project it inspects"
    )
    assert incumbent["result"] == "PENDING"

    # Widened to 10:59-13:59, this request still catches the last minute of the
    # incumbent's half-open 09:00-11:00 window.
    validate_error(
        _book_visit(
            api,
            probed["project"]["id"],
            "2026-10-05T11:59:00Z",
            "2026-10-05T12:59:00Z",
        ),
        ApiErrorId.INSPECTION_SLOT_OVERLAP,
    )

    # Widened to 11:00-14:00, this request only reaches the excluded end of the
    # incumbent's window, so the calendar is free.
    booked = validate_success(
        _book_visit(
            api,
            probed["project"]["id"],
            "2026-10-05T12:00:00Z",
            "2026-10-05T13:00:00Z",
        ),
        201,
    )
    assert booked["result"] == "PENDING"
    assert booked["contractor_id"] == contractor["id"]
    assert _instant(booked["window_start"]) == _instant("2026-10-05T12:00:00Z")


def test_02_visit_abutting_the_early_buffer_is_booked_and_one_minute_inside_is_refused(api):
    """PRD §3.6: "The calendar rule is the sharpest of the temporal constraints: widen the requested window by sixty minutes on **both** sides, and if the widened interval intersects the half-open window of any existing inspection that is still `PENDING`, belongs to the same `contractor_id`, and sits on a project that is not `ABANDONED`, the booking is refused with `ERR_INSPECTION_SLOT_OVERLAP`."

    PRD §3.6: "The window is half-open — it includes `window_start` and excludes `window_end` — must be at least thirty and at most two hundred and forty minutes long, both bounds inclusive, and must begin at or after the current logical clock; a visit booked into the past is refused with `ERR_INSPECTION_IN_PAST`."

    Design: Difficulty/resource_temporal_overlap/contractor_calendar_half_open_windows_widened_60_minutes_on_both_sides
    """
    cycle = _open_brace_and_bolt_cycle(api)
    contractor = fixtures.create_contractor(api, ["CRIPPLE_WALL_BRACING"])
    held = _cripple_wall_project_awaiting_inspection(api, cycle, contractor)
    probed = _cripple_wall_project_awaiting_inspection(api, cycle, contractor)

    validate_success(
        _book_visit(
            api,
            held["project"]["id"],
            "2026-10-05T09:00:00Z",
            "2026-10-05T11:00:00Z",
        ),
        201,
    )

    # Widened to 06:01-09:01, this request catches the first minute of the
    # incumbent's window, so the buffer bites on the early side too.
    validate_error(
        _book_visit(
            api,
            probed["project"]["id"],
            "2026-10-05T07:01:00Z",
            "2026-10-05T08:01:00Z",
        ),
        ApiErrorId.INSPECTION_SLOT_OVERLAP,
    )

    # Widened to 06:00-09:00, this request ends exactly where the incumbent's
    # included start sits, and a half-open interval ending there does not reach it.
    booked = validate_success(
        _book_visit(
            api,
            probed["project"]["id"],
            "2026-10-05T07:00:00Z",
            "2026-10-05T08:00:00Z",
        ),
        201,
    )
    assert booked["result"] == "PENDING"
    assert _instant(booked["window_end"]) == _instant("2026-10-05T08:00:00Z")


def test_03_a_freshly_booked_visit_joins_the_contractor_calendar(api):
    """PRD §3.6: "The calendar rule is the sharpest of the temporal constraints: widen the requested window by sixty minutes on **both** sides, and if the widened interval intersects the half-open window of any existing inspection that is still `PENDING`, belongs to the same `contractor_id`, and sits on a project that is not `ABANDONED`, the booking is refused with `ERR_INSPECTION_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/contractor_calendar_half_open_windows_widened_60_minutes_on_both_sides
    """
    cycle = _open_brace_and_bolt_cycle(api)
    contractor = fixtures.create_contractor(api, ["CRIPPLE_WALL_BRACING"])
    first = _cripple_wall_project_awaiting_inspection(api, cycle, contractor)
    second = _cripple_wall_project_awaiting_inspection(api, cycle, contractor)
    third = _cripple_wall_project_awaiting_inspection(api, cycle, contractor)

    validate_success(
        _book_visit(
            api,
            first["project"]["id"],
            "2026-10-05T09:00:00Z",
            "2026-10-05T11:00:00Z",
        ),
        201,
    )
    joined = validate_success(
        _book_visit(
            api,
            second["project"]["id"],
            "2026-10-05T12:00:00Z",
            "2026-10-05T13:00:00Z",
        ),
        201,
    )
    assert joined["result"] == "PENDING"

    # Widened to 12:00-15:00, this request now collides with the appointment that
    # the previous booking put on the same contractor's calendar.
    validate_error(
        _book_visit(
            api,
            third["project"]["id"],
            "2026-10-05T13:00:00Z",
            "2026-10-05T14:00:00Z",
        ),
        ApiErrorId.INSPECTION_SLOT_OVERLAP,
    )


def test_04_the_same_window_is_free_on_another_contractors_calendar(api):
    """PRD §3.6: "The calendar rule is the sharpest of the temporal constraints: widen the requested window by sixty minutes on **both** sides, and if the widened interval intersects the half-open window of any existing inspection that is still `PENDING`, belongs to the same `contractor_id`, and sits on a project that is not `ABANDONED`, the booking is refused with `ERR_INSPECTION_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/contractor_calendar_half_open_windows_widened_60_minutes_on_both_sides
    """
    cycle = _open_brace_and_bolt_cycle(api)
    bracing_crew = fixtures.create_contractor(api, ["CRIPPLE_WALL_BRACING"])
    rival_crew = fixtures.create_contractor(api, ["CRIPPLE_WALL_BRACING"])
    booked_work = _cripple_wall_project_awaiting_inspection(api, cycle, bracing_crew)
    rival_work = _cripple_wall_project_awaiting_inspection(api, cycle, rival_crew)

    held = validate_success(
        _book_visit(
            api,
            booked_work["project"]["id"],
            "2026-10-05T09:00:00Z",
            "2026-10-05T11:00:00Z",
        ),
        201,
    )
    assert held["contractor_id"] == bracing_crew["id"]

    # The very same instants, on a different contractor's calendar: the buffer is
    # scoped to one contractor, so nothing collides.
    twin = validate_success(
        _book_visit(
            api,
            rival_work["project"]["id"],
            "2026-10-05T09:00:00Z",
            "2026-10-05T11:00:00Z",
        ),
        201,
    )
    assert twin["contractor_id"] == rival_crew["id"]
    assert twin["result"] == "PENDING"


def test_05_recording_an_outcome_releases_the_window_it_held(api):
    """PRD §3.6: "Only `PENDING` inspections occupy the calendar; once an outcome is recorded, that window releases."

    PRD §3.6: "A **partial** result is the strange middle case: it records `result` as `PARTIAL` and raises `inspection_attempts`, but leaves the project exactly where it was, still `AWAITING_INSPECTION`."

    Design: Difficulty/resource_temporal_overlap/contractor_calendar_half_open_windows_widened_60_minutes_on_both_sides
    """
    cycle = _open_brace_and_bolt_cycle(api)
    contractor = fixtures.create_contractor(api, ["CRIPPLE_WALL_BRACING"])
    visited = _cripple_wall_project_awaiting_inspection(api, cycle, contractor)
    waiting = _cripple_wall_project_awaiting_inspection(api, cycle, contractor)

    occupying = validate_success(
        _book_visit(
            api,
            visited["project"]["id"],
            "2026-10-05T09:00:00Z",
            "2026-10-05T11:00:00Z",
        ),
        201,
    )

    # While that appointment is still PENDING the identical window is unavailable.
    validate_error(
        _book_visit(
            api,
            waiting["project"]["id"],
            "2026-10-05T09:00:00Z",
            "2026-10-05T11:00:00Z",
        ),
        ApiErrorId.INSPECTION_SLOT_OVERLAP,
    )

    fixtures.set_clock(api, "2026-10-05T09:00:00Z")
    reported = validate_success(
        api.record_inspection_result(
            occupying["id"],
            factories.record_result_payload(
                "PARTIAL", deficiency_note="anchor bolts only half installed"
            ),
            FIELD_INSPECTOR_HEADERS,
        )
    )
    assert reported["result"] == "PARTIAL"

    released = validate_success(
        _book_visit(
            api,
            waiting["project"]["id"],
            "2026-10-05T09:00:00Z",
            "2026-10-05T11:00:00Z",
        ),
        201,
    )
    assert released["result"] == "PENDING"
    assert released["contractor_id"] == contractor["id"]


def _apply_for_cycle(api, program_track, label, opens_at, closes_at, pool_cents=5000000):
    """Ask for a funding cycle on one program track over one application window."""
    return api.create_grant_cycle(
        factories.create_grant_cycle_payload(
            program_track=program_track,
            label=label,
            opens_at=opens_at,
            closes_at=closes_at,
            total_pool_cents=pool_cents,
        ),
        PROGRAM_ADMIN_HEADERS,
    )


def test_06_a_cycle_opening_on_the_incumbents_closing_instant_collides(api):
    """PRD §3.5: "Windows may not collide within a track: the closed interval running from `opens_at` through `closes_at` inclusive must not intersect the closed interval of any other cycle on the same `program_track`, in *any* status, since a closed cycle still reserves its historical window."

    PRD §3.5: "There is no buffer and no tolerance — two cycles that merely touch at an endpoint do collide, and the second is refused with `ERR_GRANT_CYCLE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/grant_cycle_windows_collide_on_touching_endpoints_within_one_track
    """
    incumbent = validate_success(
        _apply_for_cycle(
            api,
            "BRACE_AND_BOLT",
            "2026 H1 Brace and Bolt",
            "2026-01-01T00:00:00Z",
            "2026-06-30T00:00:00Z",
        ),
        201,
    )
    assert incumbent["status"] == "OPEN"
    assert incumbent["uncommitted_cents"] == incumbent["total_pool_cents"]

    # The single shared instant at the incumbent's closes_at is a collision,
    # because both bounds of both windows are inclusive.
    validate_error(
        _apply_for_cycle(
            api,
            "BRACE_AND_BOLT",
            "Touching H2",
            "2026-06-30T00:00:00Z",
            "2026-12-31T00:00:00Z",
        ),
        ApiErrorId.GRANT_CYCLE_WINDOW_OVERLAP,
    )

    # One second of clearance is enough: the rule carries no buffer at all.
    successor = validate_success(
        _apply_for_cycle(
            api,
            "BRACE_AND_BOLT",
            "One second clear",
            "2026-06-30T00:00:01Z",
            "2026-12-31T00:00:00Z",
        ),
        201,
    )
    assert successor["status"] == "OPEN"
    assert _instant(successor["opens_at"]) == _instant("2026-06-30T00:00:01Z")


def test_07_the_window_rule_bites_on_the_early_endpoint_and_only_within_one_track(api):
    """PRD §3.5: "Windows may not collide within a track: the closed interval running from `opens_at` through `closes_at` inclusive must not intersect the closed interval of any other cycle on the same `program_track`, in *any* status, since a closed cycle still reserves its historical window."

    PRD §3.5: "Public retrofit money is appropriated in **funding cycles**, each belonging to exactly one `program_track` — `BRACE_AND_BOLT`, `MOBILE_HOME` or `SOFT_STORY` — and each carrying a human `label` such as "2026 Fall", an application window bounded by `opens_at` and `closes_at`, and a `total_pool_cents` of at least 100,000 cents."

    Design: Difficulty/resource_temporal_overlap/grant_cycle_windows_collide_on_touching_endpoints_within_one_track
    """
    validate_success(
        _apply_for_cycle(
            api,
            "BRACE_AND_BOLT",
            "2026 H1 Brace and Bolt",
            "2026-01-01T00:00:00Z",
            "2026-06-30T00:00:00Z",
        ),
        201,
    )

    # Closing exactly on the incumbent's opens_at collides on the early side.
    validate_error(
        _apply_for_cycle(
            api,
            "BRACE_AND_BOLT",
            "Touching the early end",
            "2025-06-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
        ApiErrorId.GRANT_CYCLE_WINDOW_OVERLAP,
    )

    # The very same colliding window is free on another program track.
    other_track = validate_success(
        _apply_for_cycle(
            api,
            "MOBILE_HOME",
            "Same window other track",
            "2026-06-30T00:00:00Z",
            "2026-12-31T00:00:00Z",
        ),
        201,
    )
    assert other_track["program_track"] == "MOBILE_HOME"
    assert other_track["status"] == "OPEN"


def test_08_a_closed_cycle_still_reserves_its_historical_window(api):
    """PRD §3.5: "Windows may not collide within a track: the closed interval running from `opens_at` through `closes_at` inclusive must not intersect the closed interval of any other cycle on the same `program_track`, in *any* status, since a closed cycle still reserves its historical window."

    PRD §3.5: "Closing a cycle moves `status` `OPEN → CLOSED`, which refuses both new applications and new reservations while leaving money already reserved exactly where it is."

    Design: Difficulty/resource_temporal_overlap/grant_cycle_windows_collide_on_touching_endpoints_within_one_track
    """
    incumbent = validate_success(
        _apply_for_cycle(
            api,
            "BRACE_AND_BOLT",
            "2026 H1 Brace and Bolt",
            "2026-01-01T00:00:00Z",
            "2026-06-30T00:00:00Z",
        ),
        201,
    )
    retired = validate_success(
        api.close_grant_cycle(incumbent["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert retired["status"] == "CLOSED"

    validate_error(
        _apply_for_cycle(
            api,
            "BRACE_AND_BOLT",
            "Retry after close",
            "2026-06-30T00:00:00Z",
            "2026-12-30T00:00:00Z",
        ),
        ApiErrorId.GRANT_CYCLE_WINDOW_OVERLAP,
    )


def _bound_term_at_epoch(api):
    """A household with cover incepting at the epoch, so its term ends 2027-08-01."""
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(api)
    assert ctx["policy"]["lifecycle_status"] == "ACTIVE"
    assert ctx["policy"]["term_number"] == 1
    assert _instant(ctx["policy"]["effective_at"]) == _instant(constants.CLOCK_EPOCH)
    assert _instant(ctx["policy"]["expires_at"]) == _instant("2027-08-01T00:00:00Z")
    return ctx


def test_09_re_extending_the_accepted_offer_blocks_the_roll_over_until_it_is_reaccepted(api):
    """PRD §3.4: "The insurer must not be `SANCTIONED` (a merely `WITHDRAWN` carrier may still renew its in-force book), and the offer named by `accepted_offer_id` must be in `ACCEPTED`, which is what makes a re-extended offer block the roll-over until the household re-accepts."

    PRD §3.1: "There is a sting in the tail — re-extending an `ACCEPTED` offer un-accepts it, and any policy that named that offer as the basis of its coverage can no longer roll into its next term until the household accepts the new round."

    Design: Difficulty/cross_entity_state_dependency/policy_renewal_gated_on_the_reoffered_mandatory_offer_being_reaccepted
    """
    ctx = _bound_term_at_epoch(api)
    insurer_headers = make_insurer_headers(ctx["insurer"]["id"])
    holder_headers = make_policyholder_headers(ctx["policyholder"]["id"])

    # Move into the renewal window: it opens forty-five days before expiry.
    fixtures.set_clock(api, "2027-07-01T00:00:00Z")

    reoffered = validate_success(
        api.reoffer(ctx["offer"]["id"], None, insurer_headers)
    )
    assert reoffered["status"] == "PENDING"
    assert reoffered["offer_round"] == 2
    assert reoffered["responded_at"] is None
    assert _instant(reoffered["offered_at"]) == _instant("2027-07-01T00:00:00Z")
    assert _instant(reoffered["expires_at"]) == _instant("2027-08-30T00:00:00Z")

    # The coverage cannot roll over while the household is silent on the new round.
    validate_error(
        api.renew_policy(ctx["policy"]["id"], None, insurer_headers),
        ApiErrorId.MANDATORY_OFFER_NOT_ACCEPTED,
    )

    reaccepted = validate_success(
        api.respond_to_offer(
            ctx["offer"]["id"],
            factories.respond_to_offer_payload("ACCEPT"),
            holder_headers,
        )
    )
    assert reaccepted["status"] == "ACCEPTED"

    renewed = validate_success(
        api.renew_policy(ctx["policy"]["id"], None, insurer_headers)
    )
    assert renewed["lifecycle_status"] == "ACTIVE"
    assert renewed["term_number"] == 2
    assert renewed["accepted_offer_id"] == ctx["offer"]["id"]
    assert _instant(renewed["effective_at"]) == _instant(ctx["policy"]["expires_at"])
    assert _instant(renewed["expires_at"]) == _instant("2028-07-31T00:00:00Z")
    assert renewed["rating_variant"] == "RENEWAL_TIME"
    assert renewed["mitigation_discount_cents"] == 0
    assert renewed["prorated_credit_cents"] == 0
    # Byte-identical dwelling data with no retrofit posture reprices identically.
    assert renewed["base_premium_cents"] == ctx["policy"]["base_premium_cents"]
    assertions.assert_premium_ledger_consistent(renewed)


def test_10_the_reoffer_gate_is_a_renewal_precondition_and_not_a_change_to_the_policy(api):
    """PRD §3.1: "That is enforced as a precondition of the renewal, not as a mutation of the policy."

    PRD §3.4: "The insurer must not be `SANCTIONED` (a merely `WITHDRAWN` carrier may still renew its in-force book), and the offer named by `accepted_offer_id` must be in `ACCEPTED`, which is what makes a re-extended offer block the roll-over until the household re-accepts."

    Design: Difficulty/cross_entity_state_dependency/policy_renewal_gated_on_the_reoffered_mandatory_offer_being_reaccepted
    """
    ctx = _bound_term_at_epoch(api)
    insurer_headers = make_insurer_headers(ctx["insurer"]["id"])
    holder_headers = make_policyholder_headers(ctx["policyholder"]["id"])

    fixtures.set_clock(api, "2027-07-01T00:00:00Z")
    validate_success(
        api.reoffer(ctx["offer"]["id"], None, insurer_headers)
    )

    # The policy itself is untouched by the re-extension.
    held = _read_policy(api, ctx["policy"]["id"])
    assert held["lifecycle_status"] == "ACTIVE"
    assert held["term_number"] == 1
    assert held["accepted_offer_id"] == ctx["offer"]["id"]
    assert held["annual_premium_cents"] == ctx["policy"]["annual_premium_cents"]
    assert _instant(held["expires_at"]) == _instant("2027-08-01T00:00:00Z")

    # Answering the new round with a refusal leaves the roll-over just as blocked.
    declined = validate_success(
        api.respond_to_offer(
            ctx["offer"]["id"],
            factories.respond_to_offer_payload("DECLINE", decline_documented=True),
            holder_headers,
        )
    )
    assert declined["status"] == "DECLINED"
    validate_error(
        api.renew_policy(ctx["policy"]["id"], None, insurer_headers),
        ApiErrorId.MANDATORY_OFFER_NOT_ACCEPTED,
    )

    # A later round that the household does accept restores the basis of cover.
    third_round = validate_success(
        api.reoffer(ctx["offer"]["id"], None, insurer_headers)
    )
    assert third_round["offer_round"] == 3
    validate_success(
        api.respond_to_offer(
            ctx["offer"]["id"],
            factories.respond_to_offer_payload("ACCEPT"),
            holder_headers,
        )
    )
    renewed = validate_success(
        api.renew_policy(ctx["policy"]["id"], None, insurer_headers)
    )
    assert renewed["term_number"] == 2
    assert renewed["lifecycle_status"] == "ACTIVE"


def _read_insurer(api, insurer_id):
    """Read one participating insurer's counters and both status dimensions."""
    return validate_success(api.get_insurer(insurer_id, PROGRAM_ADMIN_HEADERS))


def _decline_a_fresh_offer(api, insurer, documented):
    """Record one more offer for this carrier and have the household refuse it."""
    ctx = fixtures.setup_pending_offer(
        api, parties=fixtures.setup_parties(api, insurer=insurer)
    )
    payload = (
        factories.respond_to_offer_payload("DECLINE", decline_documented=True)
        if documented
        else factories.respond_to_offer_payload("DECLINE")
    )
    declined = validate_success(
        api.respond_to_offer(
            ctx["offer"]["id"],
            payload,
            make_policyholder_headers(ctx["policyholder"]["id"]),
        )
    )
    assert declined["status"] == "DECLINED"
    return declined


def _carrier_with_a_quote_and_three_declines(api, documented):
    """One carrier holding a quote, one acceptance and three refusals at the epoch."""
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    ctx = fixtures.setup_quoted_policy(
        api, parties=fixtures.setup_parties(api, insurer=insurer)
    )
    for _ in range(3):
        _decline_a_fresh_offer(api, insurer, documented)
    return ctx


def _evaluate_take_up(api, insurer_id, window_start, window_end):
    """Measure the carrier's take-up over a half-open window of offer instants."""
    return validate_success(
        api.insurer_take_up_evaluation(
            insurer_id,
            factories.take_up_evaluation_payload(window_start, window_end),
            PROGRAM_ADMIN_HEADERS,
        )
    )


def test_11_three_undocumented_declines_sanction_the_carrier_and_close_the_bind(api):
    """PRD §3.1: "This default is the enforcement hook of the whole compliance regime: **an undocumented decline is one where the program has no written record that the household actually refused**, and every such decline raises the insurer's `undocumented_decline_count` by one."

    PRD §3.1: "If the recomputed `undocumented_decline_count` is at least three, the insurer's `compliance_status` becomes `SANCTIONED`; this path may jump straight from `COMPLIANT` without passing through `UNDER_REVIEW`."

    PRD §3.1: "`REINSTATE` moves `SANCTIONED → COMPLIANT` and is likewise refused with `ERR_INSURER_NOT_SANCTIONED` when the carrier is not sanctioned; reinstatement deliberately does **not** reset `undocumented_decline_count`, because that counter is the audit trail of the original failure."

    Design: Difficulty/cross_entity_state_dependency/bind_gated_on_insurer_compliance_driven_by_undocumented_decline_count
    """
    ctx = _carrier_with_a_quote_and_three_declines(api, documented=False)
    insurer_id = ctx["insurer"]["id"]
    insurer_headers = make_insurer_headers(insurer_id)
    assert _read_insurer(api, insurer_id)["undocumented_decline_count"] == 3

    measured = _evaluate_take_up(
        api, insurer_id, "2026-07-01T00:00:00Z", "2026-09-01T00:00:00Z"
    )
    assert measured["offers_recorded_count"] == 4
    assert measured["last_take_up_rate_bp"] == 2500
    assert measured["undocumented_decline_count"] == 3
    assert measured["compliance_status"] == "SANCTIONED"

    # A sanctioned carrier cannot bring its own quote into force.
    validate_error(
        api.bind_policy(ctx["policy"]["id"], None, insurer_headers),
        ApiErrorId.INSURER_SANCTIONED,
    )

    reinstated = validate_success(
        api.insurer_compliance_action(
            insurer_id,
            factories.compliance_action_payload("REINSTATE"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert reinstated["compliance_status"] == "COMPLIANT"
    assert reinstated["undocumented_decline_count"] == 3

    bound = validate_success(
        api.bind_policy(ctx["policy"]["id"], None, insurer_headers)
    )
    assert bound["lifecycle_status"] == "ACTIVE"
    assert _read_insurer(api, insurer_id)["policies_bound_count"] == 1


def test_12_an_evaluation_window_holding_no_offers_leaves_the_bind_open(api):
    """PRD §3.1: "The evaluation writes the result to `last_take_up_rate_bp`, writes the considered count to `offers_recorded_count`, and rewrites `undocumented_decline_count` as the count of considered offers that are `DECLINED` with `decline_documented` false."

    PRD §3.1: "Fewer than four considered offers is treated as statistically meaningless: no downgrade occurs at any measured rate, including the case where nothing was considered and the rate is reported as zero."

    Design: Difficulty/cross_entity_state_dependency/bind_gated_on_insurer_compliance_driven_by_undocumented_decline_count
    """
    ctx = _carrier_with_a_quote_and_three_declines(api, documented=False)
    insurer_id = ctx["insurer"]["id"]

    # Every offer instant sits at the epoch, so a later window considers nothing.
    measured = _evaluate_take_up(
        api, insurer_id, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
    )
    assert measured["offers_recorded_count"] == 0
    assert measured["last_take_up_rate_bp"] == 0
    assert measured["undocumented_decline_count"] == 0
    assert measured["compliance_status"] == "COMPLIANT"

    bound = validate_success(
        api.bind_policy(ctx["policy"]["id"], None, make_insurer_headers(insurer_id))
    )
    assert bound["lifecycle_status"] == "ACTIVE"


def test_13_documented_declines_leave_the_carrier_compliant_and_able_to_bind(api):
    """PRD §3.1: "A documented decline raises nothing."

    PRD §3.1: "Otherwise, if at least four offers were considered *and* the computed rate is strictly below 2500 basis points — that is, below a twenty-five percent take-up — *and* the insurer is currently `COMPLIANT`, then `compliance_status` moves `COMPLIANT → UNDER_REVIEW`."

    Design: Difficulty/cross_entity_state_dependency/bind_gated_on_insurer_compliance_driven_by_undocumented_decline_count
    """
    ctx = _carrier_with_a_quote_and_three_declines(api, documented=True)
    insurer_id = ctx["insurer"]["id"]
    assert _read_insurer(api, insurer_id)["undocumented_decline_count"] == 0

    measured = _evaluate_take_up(
        api, insurer_id, "2026-07-01T00:00:00Z", "2026-09-01T00:00:00Z"
    )
    assert measured["offers_recorded_count"] == 4
    assert measured["last_take_up_rate_bp"] == 2500
    assert measured["undocumented_decline_count"] == 0
    assert measured["compliance_status"] == "COMPLIANT"

    bound = validate_success(
        api.bind_policy(ctx["policy"]["id"], None, make_insurer_headers(insurer_id))
    )
    assert bound["lifecycle_status"] == "ACTIVE"


def _bound_household(api, structure_type="WOOD_FRAME_CRIPPLE_WALL", **policy_overrides):
    """A household with cover in force on a grant-eligible structure."""
    return fixtures.setup_bound_policy(
        api,
        dwelling_overrides={"structure_type": structure_type},
        **policy_overrides,
    )


def test_14_the_pool_ledger_conserves_across_a_reservation_a_disbursement_and_a_withdrawal(api):
    """PRD §3.5: "Three figures keep the pool honest, and the third is the residual of the first two: `reserved_cents` is the sum of the awards on this cycle's grants currently in `FUNDS_RESERVED`, `disbursed_cents` is the sum of the awards on its grants in `VERIFIED_COMPLETE`, and `uncommitted_cents` is `total_pool_cents` less `reserved_cents` less `disbursed_cents`."

    PRD §3.5: "The remaining exit from `FUNDS_RESERVED` is success rather than retreat: when the funded work passes inspection, the grant advances `FUNDS_RESERVED → VERIFIED_COMPLETE`, which is terminal, and the cycle's ledger performs the *transfer* rather than a release — `reserved_cents` falls by the award and `disbursed_cents` rises by the same award, leaving `uncommitted_cents` unchanged, with the cycle's `version` rising by one."

    PRD §3.5: "Withdrawing from `FUNDS_RESERVED` reverses the reservation exactly: `reserved_cents` falls by the award, `uncommitted_cents` is recomputed, the cycle's `version` rises by one, `funded_from_bucket` is set back to `NONE` — which is what releases the bucket usage for the next applicant — every retrofit project on the grant that is in `SCHEDULED`, `IN_PROGRESS`, `AWAITING_INSPECTION` or `REWORK_REQUIRED` is moved to the terminal `ABANDONED`, and the policy's `mitigation_status` steps back `RETROFIT_PENDING → UNMITIGATED`."

    Design: Difficulty/compensating_invariant/grant_pool_conservation_across_reserve_disburse_and_withdraw
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    cycle = fixtures.create_grant_cycle(
        api, program_track="BRACE_AND_BOLT", total_pool_cents=1000000
    )
    assert cycle["reserved_cents"] == 0
    assert cycle["disbursed_cents"] == 0
    assert cycle["uncommitted_cents"] == 1000000

    # First household: a cripple-wall brace at the lowest income tier.
    first = fixtures.setup_scheduled_inspection(
        api,
        ctx=_bound_household(api),
        cycle=cycle,
        income_tier="TIER_LOW",
        project_cost_estimate_cents=250000,
        requested_scope="CRIPPLE_WALL_BRACING",
    )
    assert first["grant"]["approved_amount_cents"] == 250000
    assert first["grant"]["funded_from_bucket"] == "TIER_LOW"
    after_first = _read_cycle(api, cycle["id"])
    assert after_first["reserved_cents"] == 250000
    assert after_first["disbursed_cents"] == 0
    assert after_first["uncommitted_cents"] == 750000
    assertions.assert_grant_pool_conserved(after_first)

    # Second household: a mobile home at the middle income tier.
    second = fixtures.setup_reserved_grant(
        api,
        ctx=_bound_household(api, structure_type="MOBILE_HOME"),
        cycle=cycle,
        income_tier="TIER_MID",
        project_cost_estimate_cents=400000,
        requested_scope="EARTHQUAKE_BRACING_SYSTEM",
    )
    assert second["grant"]["approved_amount_cents"] == 300000
    assert second["grant"]["funded_from_bucket"] == "TIER_MID"
    after_second = _read_cycle(api, cycle["id"])
    assert after_second["reserved_cents"] == 550000
    assert after_second["disbursed_cents"] == 0
    assert after_second["uncommitted_cents"] == 450000
    assertions.assert_grant_pool_conserved(after_second)

    # The first project passes: the award moves from reserved to disbursed only.
    fixtures.set_clock(api, "2026-08-04T09:00:00Z")
    first = fixtures.record_inspection(api, first, "PASS")
    assert first["grant"]["status"] == "VERIFIED_COMPLETE"
    after_pass = _read_cycle(api, cycle["id"])
    assert after_pass["reserved_cents"] == 300000
    assert after_pass["disbursed_cents"] == 250000
    assert after_pass["uncommitted_cents"] == 450000
    assertions.assert_grant_pool_conserved(after_pass)

    # The second household walks away: the reservation reverses exactly.
    withdrawn = validate_success(
        api.withdraw_grant(
            second["grant"]["id"], factories.reason_payload(), PROGRAM_ADMIN_HEADERS
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["funded_from_bucket"] == "NONE"
    after_withdrawal = _read_cycle(api, cycle["id"])
    assert after_withdrawal["reserved_cents"] == 0
    assert after_withdrawal["disbursed_cents"] == 250000
    assert after_withdrawal["uncommitted_cents"] == 750000
    assertions.assert_grant_pool_conserved(after_withdrawal)
    assert _read_policy(api, second["policy"]["id"])["mitigation_status"] == "UNMITIGATED"

    # A disbursed award is beyond recall, and the refusal moves no money.
    validate_error(
        api.withdraw_grant(
            first["grant"]["id"], factories.reason_payload(), PROGRAM_ADMIN_HEADERS
        ),
        ApiErrorId.GRANT_INVALID_STATE,
    )
    unmoved = _read_cycle(api, cycle["id"])
    assert unmoved["reserved_cents"] == 0
    assert unmoved["disbursed_cents"] == 250000
    assert unmoved["uncommitted_cents"] == 750000
    assertions.assert_grant_pool_conserved(unmoved)


def test_15_withdrawing_before_the_money_was_committed_touches_no_ledger(api):
    """PRD §3.5: "What it does depends entirely on whether money was ever committed. Withdrawing from any of the four pre-reservation statuses touches no ledger at all, because nothing was reserved."

    PRD §3.5: "An approved award becomes a real charge against the pool only when program staff reserve it, moving `APPROVED → FUNDS_RESERVED`."

    Design: Difficulty/compensating_invariant/grant_pool_conservation_across_reserve_disburse_and_withdraw
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    cycle = fixtures.create_grant_cycle(
        api, program_track="BRACE_AND_BOLT", total_pool_cents=1000000
    )
    approved = fixtures.setup_approved_grant(
        api,
        ctx=_bound_household(api),
        cycle=cycle,
        income_tier="TIER_LOW",
        project_cost_estimate_cents=250000,
        requested_scope="CRIPPLE_WALL_BRACING",
    )
    assert approved["grant"]["status"] == "APPROVED"
    assert approved["grant"]["approved_amount_cents"] == 250000

    # An award that has only been approved is not yet a charge against the pool.
    before = _read_cycle(api, cycle["id"])
    assert before["reserved_cents"] == 0
    assert before["disbursed_cents"] == 0
    assert before["uncommitted_cents"] == 1000000
    assertions.assert_grant_pool_conserved(before)

    withdrawn = validate_success(
        api.withdraw_grant(
            approved["grant"]["id"], factories.reason_payload(), PROGRAM_ADMIN_HEADERS
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"

    after = _read_cycle(api, cycle["id"])
    assert after["reserved_cents"] == 0
    assert after["disbursed_cents"] == 0
    assert after["uncommitted_cents"] == 1000000
    assert after["version"] == before["version"]
    assertions.assert_grant_pool_conserved(after)
    assert _read_policy(api, approved["policy"]["id"])["mitigation_status"] == "UNMITIGATED"


def _reserve_award(api, grant_id, cycle_id):
    """Commit an approved award, pinning the cycle version just read."""
    cycle = _read_cycle(api, cycle_id)
    return api.reserve_grant_funds(
        grant_id,
        factories.reserve_funds_payload(cycle["version"]),
        PROGRAM_ADMIN_ALT_HEADERS,
    )


def test_16_a_released_award_restores_exactly_the_room_the_pool_ceiling_reads(api):
    """PRD §3.5: "Step three is the hard ceiling, and it is checked **after** a bucket has been resolved, which is exactly why a bucket with room can still fail: if `reserved_cents` plus `disbursed_cents` plus this award exceeds `total_pool_cents`, the reservation is refused with `ERR_GRANT_CYCLE_POOL_EXHAUSTED`."

    PRD §3.5: "Withdrawing from `FUNDS_RESERVED` reverses the reservation exactly: `reserved_cents` falls by the award, `uncommitted_cents` is recomputed, the cycle's `version` rises by one, `funded_from_bucket` is set back to `NONE` — which is what releases the bucket usage for the next applicant — every retrofit project on the grant that is in `SCHEDULED`, `IN_PROGRESS`, `AWAITING_INSPECTION` or `REWORK_REQUIRED` is moved to the terminal `ABANDONED`, and the policy's `mitigation_status` steps back `RETROFIT_PENDING → UNMITIGATED`."

    Design: Difficulty/compensating_invariant/grant_pool_conservation_across_reserve_disburse_and_withdraw
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    cycle = fixtures.create_grant_cycle(
        api, program_track="BRACE_AND_BOLT", total_pool_cents=600000
    )

    lowest = fixtures.setup_reserved_grant(
        api,
        ctx=_bound_household(api),
        cycle=cycle,
        income_tier="TIER_LOW",
        project_cost_estimate_cents=300000,
        requested_scope="CRIPPLE_WALL_BRACING",
    )
    assert lowest["grant"]["approved_amount_cents"] == 300000
    assert lowest["grant"]["funded_from_bucket"] == "TIER_LOW"

    middle = fixtures.setup_reserved_grant(
        api,
        ctx=_bound_household(api),
        cycle=cycle,
        income_tier="TIER_MID",
        project_cost_estimate_cents=320000,
        requested_scope="CRIPPLE_WALL_BRACING",
    )
    assert middle["grant"]["approved_amount_cents"] == 240000
    assert middle["grant"]["funded_from_bucket"] == "TIER_MID"

    crowded = _read_cycle(api, cycle["id"])
    assert crowded["reserved_cents"] == 540000
    assert crowded["uncommitted_cents"] == 60000
    assertions.assert_grant_pool_conserved(crowded)

    # The shared bucket has room for this award, but the pool no longer does.
    latecomer = fixtures.setup_approved_grant(
        api,
        ctx=_bound_household(api),
        cycle=cycle,
        income_tier="TIER_ANY",
        project_cost_estimate_cents=300000,
        requested_scope="CRIPPLE_WALL_BRACING",
    )
    assert latecomer["grant"]["approved_amount_cents"] == 150000
    validate_error(
        _reserve_award(api, latecomer["grant"]["id"], cycle["id"]),
        ApiErrorId.GRANT_CYCLE_POOL_EXHAUSTED,
    )
    still_crowded = _read_cycle(api, cycle["id"])
    assert still_crowded["reserved_cents"] == 540000
    assert still_crowded["uncommitted_cents"] == 60000
    assertions.assert_grant_pool_conserved(still_crowded)

    # Releasing the largest commitment frees precisely its award.
    validate_success(
        api.withdraw_grant(
            lowest["grant"]["id"], factories.reason_payload(), PROGRAM_ADMIN_HEADERS
        )
    )
    released = _read_cycle(api, cycle["id"])
    assert released["reserved_cents"] == 240000
    assert released["disbursed_cents"] == 0
    assert released["uncommitted_cents"] == 360000
    assertions.assert_grant_pool_conserved(released)

    # And the room is real: the refused award now commits.
    committed = validate_success(_reserve_award(api, latecomer["grant"]["id"], cycle["id"]))
    assert committed["status"] == "FUNDS_RESERVED"
    assert committed["funded_from_bucket"] == "TIER_ANY"
    final = _read_cycle(api, cycle["id"])
    assert final["reserved_cents"] == 390000
    assert final["disbursed_cents"] == 0
    assert final["uncommitted_cents"] == 210000
    assertions.assert_grant_pool_conserved(final)


def _round_half_up(value):
    """Round an exact decimal to whole cents, halves away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _verified_retrofit_with_discount(api, inspection_instant="2026-08-04T09:00:00Z"):
    """A household whose cripple-wall brace has passed and earned its discount."""
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    cycle = fixtures.create_grant_cycle(
        api, program_track="BRACE_AND_BOLT", total_pool_cents=1000000
    )
    ctx = fixtures.setup_scheduled_inspection(
        api,
        ctx=_bound_household(api),
        cycle=cycle,
        income_tier="TIER_LOW",
        project_cost_estimate_cents=250000,
        requested_scope="CRIPPLE_WALL_BRACING",
    )
    ctx["premium_before_discount"] = ctx["policy"]["annual_premium_cents"]
    fixtures.set_clock(api, inspection_instant)
    ctx["clock"] = inspection_instant
    return fixtures.record_inspection(api, ctx, "PASS")


def test_17_revoking_the_discount_restores_the_premium_ledger_exactly(api):
    """PRD §3.6: "Revocation is an exact restoration: `mitigation_discount_cents` and `prorated_credit_cents` both return to zero and `annual_premium_cents` returns to exactly `base_premium_cents` — the premium ledger conserves, so that a discount granted and revoked leaves the billed premium byte-identical to what it was before."

    PRD §3.6: "`mitigation_discount_cents` is `base_premium_cents` multiplied by the effective percentage, rounded half up to whole cents, and `annual_premium_cents` becomes `base_premium_cents` less that discount."

    PRD §3.6: "What revocation does **not** do is unwind the physical record: the dwelling's `retrofit_status` stays `VERIFIED` and its `verified_retrofit_scope` is untouched, because the inspection happened. Only the money is withdrawn."

    Design: Difficulty/compensating_invariant/premium_ledger_conservation_after_mitigation_discount_revocation
    """
    ctx = _verified_retrofit_with_discount(api)
    discounted = ctx["policy"]
    base = discounted["base_premium_cents"]

    # A cripple-wall brace on a cripple-wall house earns twenty-five percent, less
    # the five points that the public award costs the household.
    expected_discount = _round_half_up(Decimal(base) * Decimal("0.20"))
    days_left = (
        _instant(discounted["expires_at"]) - _instant(ctx["clock"])
    ).days
    expected_credit = _round_half_up(
        Decimal(expected_discount) * min(days_left, 365) / Decimal(365)
    )

    assert discounted["mitigation_status"] == "DISCOUNT_APPLIED"
    assert discounted["mitigation_discount_cents"] == expected_discount
    assert discounted["prorated_credit_cents"] == expected_credit
    assert discounted["annual_premium_cents"] == base - expected_discount
    assertions.assert_premium_ledger_consistent(discounted)

    restored = validate_success(
        api.revoke_mitigation_discount(
            discounted["id"], factories.reason_payload(), PROGRAM_ADMIN_HEADERS
        )
    )
    assert restored["mitigation_status"] == "UNMITIGATED"
    assert restored["mitigation_discount_cents"] == 0
    assert restored["prorated_credit_cents"] == 0
    assert restored["base_premium_cents"] == base
    assert restored["annual_premium_cents"] == base
    assert restored["annual_premium_cents"] == ctx["premium_before_discount"]
    assert restored["lifecycle_status"] == "ACTIVE"
    assertions.assert_premium_ledger_consistent(restored)

    # The inspection happened, so the physical record survives the clawback.
    dwelling = validate_success(
        api.get_dwelling(ctx["dwelling"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert dwelling["retrofit_status"] == "VERIFIED"
    assert dwelling["verified_retrofit_scope"] == "CRIPPLE_WALL_BRACING"

    # And the public money stays disbursed: the two ledgers are independent.
    cycle = _read_cycle(api, ctx["cycle"]["id"])
    assert cycle["disbursed_cents"] == 250000
    assert cycle["reserved_cents"] == 0
    assertions.assert_grant_pool_conserved(cycle)

    # A second clawback has nothing left to take, and takes nothing.
    validate_error(
        api.revoke_mitigation_discount(
            discounted["id"], factories.reason_payload(), PROGRAM_ADMIN_HEADERS
        ),
        ApiErrorId.NO_MITIGATION_DISCOUNT,
    )
    unchanged = _read_policy(api, discounted["id"])
    assert unchanged["mitigation_discount_cents"] == 0
    assert unchanged["prorated_credit_cents"] == 0
    assert unchanged["annual_premium_cents"] == base
    assertions.assert_premium_ledger_consistent(unchanged)


def test_18_a_policy_with_no_discount_to_lose_keeps_its_billed_premium(api):
    """PRD §3.6: "The policy must be `ACTIVE`, its `mitigation_status` must currently be `DISCOUNT_APPLIED` and its `mitigation_discount_cents` must be strictly greater than zero, or the request is refused with `ERR_NO_MITIGATION_DISCOUNT`."

    PRD §3.6: "Revocation is an exact restoration: `mitigation_discount_cents` and `prorated_credit_cents` both return to zero and `annual_premium_cents` returns to exactly `base_premium_cents` — the premium ledger conserves, so that a discount granted and revoked leaves the billed premium byte-identical to what it was before."

    Design: Difficulty/compensating_invariant/premium_ledger_conservation_after_mitigation_discount_revocation
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    cycle = fixtures.create_grant_cycle(
        api, program_track="BRACE_AND_BOLT", total_pool_cents=1000000
    )

    # Nothing has been verified, so there is no pricing incentive to claw back.
    plain = _bound_household(api)
    assert plain["policy"]["mitigation_status"] == "UNMITIGATED"
    assert plain["policy"]["mitigation_discount_cents"] == 0
    validate_error(
        api.revoke_mitigation_discount(
            plain["policy"]["id"], factories.reason_payload(), PROGRAM_ADMIN_HEADERS
        ),
        ApiErrorId.NO_MITIGATION_DISCOUNT,
    )
    held = _read_policy(api, plain["policy"]["id"])
    assert held["mitigation_discount_cents"] == 0
    assert held["prorated_credit_cents"] == 0
    assert held["annual_premium_cents"] == plain["policy"]["annual_premium_cents"]
    assertions.assert_premium_ledger_consistent(held)

    # Reserved public money moves the retrofit posture but not the premium.
    pending = fixtures.setup_reserved_grant(
        api,
        ctx=_bound_household(api),
        cycle=cycle,
        income_tier="TIER_LOW",
        project_cost_estimate_cents=250000,
        requested_scope="CRIPPLE_WALL_BRACING",
    )
    awaiting = _read_policy(api, pending["policy"]["id"])
    assert awaiting["mitigation_status"] == "RETROFIT_PENDING"
    assert awaiting["mitigation_discount_cents"] == 0
    validate_error(
        api.revoke_mitigation_discount(
            awaiting["id"], factories.reason_payload(), PROGRAM_ADMIN_HEADERS
        ),
        ApiErrorId.NO_MITIGATION_DISCOUNT,
    )
    still_billed = _read_policy(api, awaiting["id"])
    assert still_billed["mitigation_status"] == "RETROFIT_PENDING"
    assert still_billed["annual_premium_cents"] == still_billed["base_premium_cents"]
    assert still_billed["prorated_credit_cents"] == 0
    assertions.assert_premium_ledger_consistent(still_billed)


_LARGE_DWELLING = {
    "county_hazard_tier": "TIER_1",
    "soil_class": "ROCK",
    "structure_type": "WOOD_FRAME_SLAB",
    "year_built": 2000,
    "dwelling_limit_cents": 300000000,
}


def _event_with_a_two_layer_tower(api):
    """A declared earthquake behind two active layers, with cover in force at loss."""
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    first_layer = fixtures.create_reinsurance_layer(
        api,
        treaty_year=2026,
        layer_index=1,
        attachment_point_cents=100000000,
        limit_cents=50000000,
        ceded_pct=0.90,
    )
    second_layer = fixtures.create_reinsurance_layer(
        api,
        treaty_year=2026,
        layer_index=2,
        attachment_point_cents=150000000,
        limit_cents=60000000,
        ceded_pct=0.75,
    )
    ctx = fixtures.setup_event_with_policy(
        api,
        clock="2026-09-21T00:00:00Z",
        dwelling_overrides=dict(_LARGE_DWELLING),
        policy_overrides={"deductible_pct": 5},
        event_overrides={
            "magnitude": 6.9,
            "occurred_at": "2026-09-20T00:00:00Z",
            "retention_cents": 100000000,
        },
        with_layer=False,
    )
    ctx["first_layer"] = first_layer
    ctx["second_layer"] = second_layer
    return ctx


def _big_loss_claim(api, ctx):
    """One finalized total-loss claim on the tower's event."""
    return fixtures.setup_finally_adjusted_claim(
        api,
        ctx=ctx,
        structural_damage_cents=250000000,
        cosmetic_damage_cents=20000000,
        contents_damage_cents=0,
        loss_of_use_cents=0,
    )


def test_19_finalizing_a_settlement_splits_the_gross_into_retained_ceded_and_uncovered(api):
    """PRD §3.7: "`ceded_total_cents` is the sum of the `ceded_cents` of the participating layers, and `uncovered_cents` is the gross less `retained_cents` less `ceded_total_cents`, floored at zero — it is a residual and is never independently rounded."

    PRD §3.8: "Hop two, caused by the claim reaching `FINAL_ADJUSTED`: the event's `aggregate_incurred_cents` rises by the claim's `final_payable_cents` and the event's `version` rises by one, and if the event was `DECLARED` it advances `DECLARED → LOSS_AGGREGATION`."

    PRD §3.7: "Finally, if the recomputed `uncovered_cents` is strictly greater than zero and the event is currently `LOSS_AGGREGATION`, the event advances `LOSS_AGGREGATION → CAPACITY_EXHAUSTED`."

    Design: Difficulty/compensating_invariant/event_loss_conservation_across_finalize_reopen_and_refinalize
    """
    ctx = _big_loss_claim(api, _event_with_a_two_layer_tower(api))
    claim = ctx["claim"]
    assert claim["adjustment_status"] == "FINAL_ADJUSTED"
    assert claim["deductible_applied_cents"] == 15000000
    assert claim["provisional_payable_cents"] == 235000000
    assert claim["final_payable_cents"] == 255000000
    assert claim["payable_cents"] == 255000000

    event = _read_event(api, ctx["event"]["id"])
    assert event["aggregate_incurred_cents"] == 255000000
    assert event["retained_cents"] == 100000000
    assert event["ceded_total_cents"] == 90000000
    assert event["uncovered_cents"] == 65000000
    assert event["status"] == "CAPACITY_EXHAUSTED"
    assert event["claim_count"] == 1
    assertions.assert_event_loss_conserved(event)

    assert _read_layer(api, ctx["first_layer"]["id"])["ceded_cents"] == 45000000
    assert _read_layer(api, ctx["second_layer"]["id"])["ceded_cents"] == 45000000


def test_20_reopening_and_refinalizing_returns_the_loss_aggregate_to_the_same_figures(api):
    """PRD §3.8: "First, the event's `aggregate_incurred_cents` falls by exactly the claim's `final_payable_cents` and the event's `version` rises. Second, the loss waterfall re-runs over the reduced gross, rewriting `retained_cents`, every layer's `ceded_cents`, `ceded_total_cents` and `uncovered_cents`. Third, if `uncovered_cents` has returned to zero and the event is currently `CAPACITY_EXHAUSTED`, the event steps back `CAPACITY_EXHAUSTED → LOSS_AGGREGATION` — the one cycle in the event machine."

    PRD §3.8: "On the claim itself, `final_payable_cents` returns to zero, `payable_cents` returns to `provisional_payable_cents`, `final_adjuster_user_id` is cleared to null, and `reopen_count` rises by one."

    PRD §3.8: "Neither `payment_status` nor `paid_cents` is touched: a partially paid claim keeps every cent it has been paid."

    Design: Difficulty/compensating_invariant/event_loss_conservation_across_finalize_reopen_and_refinalize
    """
    ctx = _big_loss_claim(api, _event_with_a_two_layer_tower(api))
    claim_id = ctx["claim"]["id"]

    part_paid = validate_success(
        api.record_claim_payment(
            claim_id, factories.record_payment_payload(100000000), PROGRAM_ADMIN_HEADERS
        )
    )
    assert part_paid["paid_cents"] == 100000000
    assert part_paid["payment_status"] == "PARTIALLY_PAID"

    reopened = validate_success(
        api.reopen_claim(claim_id, factories.reason_payload(), CLAIM_ADJUSTER_HEADERS)
    )
    assert reopened["adjustment_status"] == "PROVISIONAL_ADJUSTED"
    assert reopened["final_payable_cents"] == 0
    assert reopened["payable_cents"] == 235000000
    assert reopened["final_adjuster_user_id"] is None
    assert reopened["reopen_count"] == 1
    assert reopened["paid_cents"] == 100000000
    assert reopened["payment_status"] == "PARTIALLY_PAID"

    emptied = _read_event(api, ctx["event"]["id"])
    assert emptied["aggregate_incurred_cents"] == 0
    assert emptied["retained_cents"] == 0
    assert emptied["ceded_total_cents"] == 0
    assert emptied["uncovered_cents"] == 0
    assert emptied["status"] == "LOSS_AGGREGATION"
    assertions.assert_event_loss_conserved(emptied)
    assert _read_layer(api, ctx["first_layer"]["id"])["ceded_cents"] == 0
    assert _read_layer(api, ctx["second_layer"]["id"])["ceded_cents"] == 0

    refinalized = validate_success(
        api.finalize_claim_adjustment(claim_id, None, CLAIM_ADJUSTER_ALT_HEADERS)
    )
    assert refinalized["adjustment_status"] == "FINAL_ADJUSTED"
    assert refinalized["final_payable_cents"] == 255000000
    assert refinalized["payable_cents"] == 255000000
    assert refinalized["reopen_count"] == 1
    assert refinalized["paid_cents"] == 100000000

    restored = _read_event(api, ctx["event"]["id"])
    assert restored["aggregate_incurred_cents"] == 255000000
    assert restored["retained_cents"] == 100000000
    assert restored["ceded_total_cents"] == 90000000
    assert restored["uncovered_cents"] == 65000000
    assert restored["status"] == "CAPACITY_EXHAUSTED"
    assertions.assert_event_loss_conserved(restored)
    assert _read_layer(api, ctx["first_layer"]["id"])["ceded_cents"] == 45000000
    assert _read_layer(api, ctx["second_layer"]["id"])["ceded_cents"] == 45000000


def test_21_reopening_one_claim_withdraws_only_its_own_contribution_to_the_gross(api):
    """PRD §3.7: "The gross is the event's `aggregate_incurred_cents`, which is the sum of `final_payable_cents` over exactly those of its claims whose `adjustment_status` is `FINAL_ADJUSTED` or `CLOSED`; claims still at `FNOL_RECEIVED` or `PROVISIONAL_ADJUSTED`, and claims that were `DENIED`, contribute nothing."

    PRD §3.8: "First, the event's `aggregate_incurred_cents` falls by exactly the claim's `final_payable_cents` and the event's `version` rises. Second, the loss waterfall re-runs over the reduced gross, rewriting `retained_cents`, every layer's `ceded_cents`, `ceded_total_cents` and `uncovered_cents`."

    Design: Difficulty/compensating_invariant/event_loss_conservation_across_finalize_reopen_and_refinalize
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    first_layer = fixtures.create_reinsurance_layer(
        api,
        treaty_year=2026,
        layer_index=1,
        attachment_point_cents=100000000,
        limit_cents=50000000,
        ceded_pct=0.90,
    )
    second_layer = fixtures.create_reinsurance_layer(
        api,
        treaty_year=2026,
        layer_index=2,
        attachment_point_cents=150000000,
        limit_cents=60000000,
        ceded_pct=0.75,
    )
    # Both households must hold cover before the ground moves.
    large = fixtures.setup_bound_policy(
        api, dwelling_overrides=dict(_LARGE_DWELLING), deductible_pct=5
    )
    modest = fixtures.setup_bound_policy(api)

    fixtures.set_clock(api, "2026-09-21T00:00:00Z")
    declared = fixtures.setup_declared_event(
        api,
        with_layer=False,
        magnitude=6.9,
        occurred_at="2026-09-20T00:00:00Z",
        retention_cents=100000000,
    )
    large.update(declared)
    large = fixtures.setup_finally_adjusted_claim(
        api,
        ctx=large,
        structural_damage_cents=250000000,
        cosmetic_damage_cents=20000000,
        contents_damage_cents=0,
        loss_of_use_cents=0,
    )
    modest["event"] = _read_event(api, declared["event"]["id"])
    modest = fixtures.setup_finally_adjusted_claim(
        api,
        ctx=modest,
        structural_damage_cents=10000000,
        cosmetic_damage_cents=0,
        contents_damage_cents=0,
        loss_of_use_cents=0,
    )
    assert large["claim"]["final_payable_cents"] == 255000000
    assert modest["claim"]["final_payable_cents"] == 8000000

    both = _read_event(api, declared["event"]["id"])
    assert both["claim_count"] == 2
    assert both["aggregate_incurred_cents"] == 263000000
    assert both["retained_cents"] == 100000000
    assert both["ceded_total_cents"] == 90000000
    assert both["uncovered_cents"] == 73000000
    assert both["status"] == "CAPACITY_EXHAUSTED"
    assertions.assert_event_loss_conserved(both)

    reopened = validate_success(
        api.reopen_claim(
            modest["claim"]["id"], factories.reason_payload(), CLAIM_ADJUSTER_HEADERS
        )
    )
    assert reopened["final_payable_cents"] == 0
    assert reopened["payable_cents"] == 8000000
    assert reopened["reopen_count"] == 1

    remaining = _read_event(api, declared["event"]["id"])
    assert remaining["aggregate_incurred_cents"] == 255000000
    assert remaining["retained_cents"] == 100000000
    assert remaining["ceded_total_cents"] == 90000000
    assert remaining["uncovered_cents"] == 65000000
    assert remaining["status"] == "CAPACITY_EXHAUSTED"
    assert remaining["claim_count"] == 2
    assertions.assert_event_loss_conserved(remaining)
    assert _read_layer(api, first_layer["id"])["ceded_cents"] == 45000000
    assert _read_layer(api, second_layer["id"])["ceded_cents"] == 45000000
