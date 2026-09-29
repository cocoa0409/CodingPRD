"""Three requests that are impeccable in themselves and are refused anyway,
because a second entity is standing in the wrong state. Moving only that other
entity, and touching nothing on the request, makes the identical call succeed.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client, assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ANONYMOUS,
    CITY_CLERK,
    CITY_CLERK_ID,
    CODIFICATION_EDITOR,
    CODIFICATION_EDITOR_ALT,
    CODIFICATION_EDITOR_ID,
    PRESIDING_OFFICER,
    RECORDS_OFFICER_ID,
)

PROCEDURAL_MOTION = ("PROCEDURAL", "SIMPLE")


def _noticed_meeting_awaiting_its_gavel():
    """A compliantly noticed meeting, standing at its start instant with nobody
    having called it to order yet."""
    ctx = fx.noticed_meeting(item_types=["REPORT"])
    fx.set_clock("2026-09-15T18:00:00Z")
    return ctx["meeting"]


def test_a_motion_against_a_merely_noticed_meeting_is_refused():
    """Every field of the motion is valid and the clerk holds the right role, but
    the meeting has not been gavelled in, so nothing is recorded.

    PRD 3.3: "A `CityClerk` or `DeputyClerk` records one against the `meeting_id`
    of a meeting that must be `IN_SESSION` — recording against a meeting in any
    other state is `ERR_MEETING_NOT_IN_SESSION` (HTTP 409) — supplying the
    `motion_type`, the `majority_rule` that will be applied, the opaque
    `moved_by_member_id` of the mover and the opaque `seconded_by_member_id` of the
    seconder, which is required at creation."

    Design: Difficulty/cross_entity_state_dependency/motion_creation_blocked_until_its_meeting_is_in_session
    """
    meeting = _noticed_meeting_awaiting_its_gavel()

    response = api_client.create_motion(
        f.motion_payload(meeting["id"], *PROCEDURAL_MOTION), CITY_CLERK
    )

    validate_error(response, ApiErrorId.MEETING_NOT_IN_SESSION.value, 409)
    a.assert_status(fx.read_meeting(meeting["id"]), "NOTICED")
    _, meta = validate_paginated(
        api_client.list_motions(CITY_CLERK, {"meeting_id": meeting["id"]})
    )
    a.assert_pagination_meta(meta, total_count=0)


def test_the_identical_motion_is_accepted_once_the_body_is_called_to_order():
    """Convening changes nothing about the motion request, and the same payload
    now enters the register seconded and undecided.

    PRD 3.3: "The motion enters with `status` `SECONDED`, `outcome` `PENDING`,
    `result_official` false and all four vote counters at 0."

    Design: Difficulty/cross_entity_state_dependency/motion_creation_blocked_until_its_meeting_is_in_session
    """
    meeting = _noticed_meeting_awaiting_its_gavel()
    api_client.create_motion(
        f.motion_payload(meeting["id"], *PROCEDURAL_MOTION), CITY_CLERK
    )
    convened = validate_success(
        api_client.convene_meeting(
            meeting["id"], f.convene_payload(7), PRESIDING_OFFICER
        )
    )

    accepted = validate_success(
        api_client.create_motion(
            f.motion_payload(meeting["id"], *PROCEDURAL_MOTION), CITY_CLERK
        ),
        201,
    )

    a.assert_fields(
        accepted,
        status="SECONDED",
        outcome="PENDING",
        result_official=False,
        yes_count=0,
        no_count=0,
        abstain_count=0,
        recused_count=0,
    )
    a.assert_fields(convened, status="IN_SESSION", present_member_count=7)
    _, meta = validate_paginated(
        api_client.list_motions(CITY_CLERK, {"meeting_id": meeting["id"]})
    )
    a.assert_pagination_meta(meta, total_count=1)


def _eligible_batch_behind_an_open_request():
    """A batch of 40 items proposed off a fully eligible series of 100, with one
    records request still open against that same series."""
    fx.set_clock("2026-08-03T09:00:00Z")
    series = fx.series_eligible_for_destruction(
        item_count=100, accessioned_on="2019-06-15", retention_years=5
    )
    request = fx.create_records_request(
        ANONYMOUS,
        requester_name="Cleo Marsh",
        requester_email="cleo@example.org",
        subject_description="Correspondence about the depot",
        target_series_id=series["id"],
    )
    batch = fx.proposed_destruction_batch(series["id"], 40, "2024-06-15")
    return {"series": series, "request": request, "batch": batch}


def _drive_the_request_to_closed(request_id):
    validate_success(api_client.begin_review(request_id, CITY_CLERK))
    validate_success(
        api_client.record_disposition(
            request_id, f.disposition_payload("FULL_RELEASE"), CITY_CLERK
        )
    )
    return validate_success(api_client.close_records_request(request_id, CITY_CLERK))


def test_the_shredder_stops_while_a_request_still_reaches_into_the_series():
    """Retention has elapsed, no hold stands, the count fits and the signer is a
    second pair of hands — and the certificate is still refused.

    PRD 3.9: "`blocking_request_id` is **recomputed at this moment** rather than
    trusted from proposal time, and if it now resolves to a request, the
    certification is refused with `ERR_SERIES_HAS_OPEN_REQUEST` (HTTP 409) — a
    records request filed after the batch was proposed still stops the shredder."

    Design: Difficulty/cross_entity_state_dependency/destruction_certification_blocked_by_an_open_records_request_on_the_same_series
    """
    ctx = _eligible_batch_behind_an_open_request()

    response = api_client.certify_destruction_batch(
        ctx["batch"]["id"], f.certify_batch_payload("2026-08-03"), CITY_CLERK
    )

    validate_error(response, ApiErrorId.SERIES_HAS_OPEN_REQUEST.value, 409)
    a.assert_status(fx.read_batch(ctx["batch"]["id"]), "PROPOSED")
    a.assert_custody_triple(
        fx.read_record_series(ctx["series"]["id"]), total=100, active=100, destroyed=0
    )


def test_closing_that_request_lets_the_untouched_batch_be_signed():
    """The batch is never amended; closing the request is the whole difference,
    and the certificate then moves 40 items across the custody counters.

    PRD 3.9: "On success the batch moves `PROPOSED → CERTIFIED`,
    `certifying_officer_id` records the signer's `X-User-ID`, `certified_on`
    records the supplied date, and the custody counters move: `active_item_count`
    falls by the batch's `item_count` and `destroyed_item_count` rises by the same
    amount."

    Design: Difficulty/cross_entity_state_dependency/destruction_certification_blocked_by_an_open_records_request_on_the_same_series
    """
    ctx = _eligible_batch_behind_an_open_request()
    api_client.certify_destruction_batch(
        ctx["batch"]["id"], f.certify_batch_payload("2026-08-03"), CITY_CLERK
    )
    closed = _drive_the_request_to_closed(ctx["request"]["id"])
    a.assert_fields(closed, fulfillment_status="CLOSED", closed_on="2026-08-03")

    certified = validate_success(
        api_client.certify_destruction_batch(
            ctx["batch"]["id"], f.certify_batch_payload("2026-08-03"), CITY_CLERK
        )
    )

    a.assert_fields(
        certified,
        status="CERTIFIED",
        proposed_by_officer_id=RECORDS_OFFICER_ID,
        certifying_officer_id=CITY_CLERK_ID,
        certified_on="2026-08-03",
    )
    series = fx.read_record_series(ctx["series"]["id"])
    a.assert_custody_triple(series, total=100, active=60, destroyed=40)
    a.assert_fields(series, eligible_through_on="2024-06-15")


def _locked_cycle_holding_one_conflict():
    """A LOCKED cycle on title 12 whose only two submissions both claim section
    12.04.030 and are therefore held against each other."""
    fx.set_clock("2026-10-06T09:00:00Z")
    return fx.locked_cycle_with_conflict(
        window_open_on="2026-10-01", window_close_on="2026-10-31"
    )


def test_a_supplement_cannot_be_certified_over_a_held_conflict():
    """The cycle is LOCKED and otherwise ready, and certification is refused
    purely because two of its children are still holding each other.

    PRD 3.7: "Its `conflict_count` must be 0 and no submission may still be
    sitting in `CONFLICT_HELD`, or the attempt is `ERR_UNRESOLVED_CONFLICTS`
    (HTTP 409); no submission may still be `PENDING` or `IN_REVIEW`, or the
    attempt is `ERR_CYCLE_HAS_OPEN_SUBMISSIONS` (HTTP 409); and the acting
    `X-User-ID` must differ from every `resolved_by_user_id` recorded on the
    cycle's submissions, or the attempt is `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/supplement_cycle_certification_blocked_until_its_held_conflict_is_resolved
    """
    ctx = _locked_cycle_holding_one_conflict()

    response = api_client.certify_supplement_cycle(
        ctx["cycle"]["id"], f.certify_cycle_payload("2026-10-31"), CODIFICATION_EDITOR_ALT
    )

    validate_error(response, ApiErrorId.UNRESOLVED_CONFLICTS.value, 409)
    a.assert_fields(
        fx.read_cycle(ctx["cycle"]["id"]), status="LOCKED", conflict_count=1
    )
    a.assert_status(fx.read_submission(ctx["submission_one"]["id"]), "CONFLICT_HELD")
    a.assert_status(fx.read_submission(ctx["submission_two"]["id"]), "CONFLICT_HELD")
    a.assert_section_refs(fx.read_code_title(ctx["code_title"]["id"]), [])


def test_a_manual_override_settles_the_pair_and_frees_the_certificate():
    """Naming a winner settles both rows symmetrically, drops conflict_count to
    zero and lets the same certify request carry the accepted section into the
    title.

    PRD 3.7: "The winner moves `CONFLICT_HELD → ACCEPTED` and the loser moves
    `CONFLICT_HELD → REJECTED`; `conflict_with_submission_id` is cleared to null
    on both; `resolution_basis` and `resolved_by_user_id` — the acting
    `X-User-ID` — are stamped on both; and the cycle's `conflict_count` retreats
    by 1."

    Design: Difficulty/cross_entity_state_dependency/supplement_cycle_certification_blocked_until_its_held_conflict_is_resolved
    """
    ctx = _locked_cycle_holding_one_conflict()
    api_client.certify_supplement_cycle(
        ctx["cycle"]["id"], f.certify_cycle_payload("2026-10-31"), CODIFICATION_EDITOR_ALT
    )
    winner_id = ctx["submission_one"]["id"]
    loser_id = ctx["submission_two"]["id"]
    validate_success(
        api_client.resolve_submission_conflict(
            winner_id,
            f.resolve_conflict_payload("MANUAL_OVERRIDE", winner_id),
            CODIFICATION_EDITOR,
        )
    )

    certified = validate_success(
        api_client.certify_supplement_cycle(
            ctx["cycle"]["id"],
            f.certify_cycle_payload("2026-10-31"),
            CODIFICATION_EDITOR_ALT,
        )
    )

    a.assert_fields(certified, status="CERTIFIED", certified_on="2026-10-31", conflict_count=0)
    winner = fx.read_submission(winner_id)
    loser = fx.read_submission(loser_id)
    a.assert_fields(
        winner,
        status="ACCEPTED",
        resolution_basis="MANUAL_OVERRIDE",
        resolved_by_user_id=CODIFICATION_EDITOR_ID,
    )
    a.assert_fields(
        loser,
        status="REJECTED",
        resolution_basis="MANUAL_OVERRIDE",
        resolved_by_user_id=CODIFICATION_EDITOR_ID,
    )
    a.assert_nulls(winner, "conflict_with_submission_id")
    a.assert_nulls(loser, "conflict_with_submission_id")
    title = fx.read_code_title(ctx["code_title"]["id"])
    a.assert_section_refs(title, ["12.04.030"])
    a.assert_fields(title, current_supplement_number=7)
    a.assert_status(fx.read_instrument(ctx["instrument_one"]["id"]), "INTRODUCED")
