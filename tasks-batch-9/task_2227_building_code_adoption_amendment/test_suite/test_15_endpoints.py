"""Endpoint round trips: detail reads, collection links, status actions and bulk
writes."""
from test_helpers import (
    ADMIN_FILER_ID,
    ADMIN_OPS_ID,
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    make_council_admin_headers,
    make_jurisdiction_official_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# Three of Riverbend's five seated officials turn up; the other two are simply
# left out of the array.
PARTIAL_ATTENDANCE = {
    "riverbend_1": "ATTENDED",
    "riverbend_2": "ATTENDED",
    "riverbend_3": "ATTENDED",
}


def test_01_a_registered_jurisdiction_reads_back_through_both_endpoints(api):
    """A jurisdiction is registered with "a resident `population`, a
    `local_authority_level` of `FULL`, `LIMITED` or `NONE` ... a
    `host_seat_capacity` ... and an `official_headcount` of at least 1", and "a
    new jurisdiction starts with both `compliance_pct_enrollment_basis` and
    `compliance_pct_attendance_basis` at 0, `enforcement_readiness` at
    `NOT_READY`, and `effective_local_amendment_count` at 0". Since
    "jurisdictions filter on `local_authority_level` and `enforcement_readiness`",
    the `FULL` filter returns exactly this one row.

    Design: Corner/endpoints/jurisdiction_create_then_read_round_trips
    """
    world = {}
    fixtures.set_logical_clock(api, fixtures.CLOCK_INTAKE)
    riverbend = fixtures.add_riverbend(api, world)

    detail = validate_success(
        api.get_jurisdiction(
            riverbend["id"], make_jurisdiction_official_headers(riverbend["id"])
        )
    )
    assert detail["name"] == "Riverbend"
    assert detail["population"] == 1200000
    assert detail["local_authority_level"] == "FULL"
    assert detail["host_seat_capacity"] == 60
    assert detail["official_headcount"] == 5
    assert detail["compliance_pct_enrollment_basis"] == 0.00
    assert detail["compliance_pct_attendance_basis"] == 0.00
    assert detail["enforcement_readiness"] == "NOT_READY"
    assert detail["effective_local_amendment_count"] == 0

    page, meta = validate_paginated(
        api.list_jurisdictions(
            make_council_admin_headers(), params={"local_authority_level": "FULL"}
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert page[0]["id"] == riverbend["id"]


def test_02_opening_enrollment_leaves_the_seat_ledger_untouched(api):
    """"Opening enrollment moves the session `SCHEDULED` → `ENROLLMENT_OPEN` and
    requires the referenced rulemaking order to be `PUBLISHED` or `EFFECTIVE`",
    and only enrolling moves the ledger, since "enrolling adds one to
    `enrolled_count` and subtracts one from `seats_available`". With no attendee
    yet, the session keeps the opening figures it took when "a new session starts
    in `SCHEDULED` with `seats_available` equal to `seat_capacity`,
    `enrolled_count`, `attended_count` and `no_show_count` all 0, and
    `cancellation_reason` null".

    Design: Corner/endpoints/training_session_status_action_opens_enrollment
    """
    world = fixtures.setup_published_adoption_rule(api)
    fixtures.add_riverbend(api, world)
    fixtures.add_session(api, world)

    session = validate_success(
        fixtures.set_session_status(api, world, "ENROLLMENT_OPEN")
    )
    assert session["status"] == "ENROLLMENT_OPEN"
    assert session["seats_available"] == 60
    assert session["enrolled_count"] == 0
    assert session["attended_count"] == 0
    assert session["no_show_count"] == 0
    assert session["cancellation_reason"] is None


def test_03_an_enrollment_omitted_from_the_attendance_array_becomes_a_no_show(api):
    """Every enrollment still `ENROLLED` that the array does not name "is treated
    as a no-show and moves `ENROLLED` → `NO_SHOW`", and "either move shifts a seat
    between buckets without releasing it: `enrolled_count` falls by one and
    `attended_count` or `no_show_count` rises by one, while `seats_available` is
    unchanged". Three of Riverbend's five officials are listed, so the enrollment
    basis still credits all five at 100.00 while the attendance basis reads 60.00
    and `enforcement_readiness` stays `NOT_READY`.

    Design: Corner/endpoints/attendance_bulk_records_treat_omissions_as_no_show
    """
    world = fixtures.setup_closed_enrollment_session(api)

    session = validate_success(
        fixtures.record_attendance(
            api, world, fixtures.attendance_for(world, PARTIAL_ATTENDANCE)
        )
    )
    assert session["status"] == "DELIVERED"
    assert session["attended_count"] == 3
    assert session["no_show_count"] == 2
    assert session["enrolled_count"] == 0
    assert session["seats_available"] == 55

    for key in ("riverbend_4", "riverbend_5"):
        enrollment = get_success_data(
            api.get_training_enrollment(
                world["enrollments"][key]["id"], make_council_admin_headers()
            )
        )
        assert enrollment["status"] == "NO_SHOW"

    riverbend = fixtures.read_jurisdiction(api, world["riverbend_id"])
    assert riverbend["compliance_pct_enrollment_basis"] == 100.00
    assert riverbend["compliance_pct_attendance_basis"] == 60.00
    assert riverbend["enforcement_readiness"] == "NOT_READY"


def test_04_one_enrollment_is_readable_from_the_session_and_the_jurisdiction(api):
    """"The enrollment records `enrolled_by_user_id` and starts in `ENROLLED`",
    and on success "`enrolled_count` rises by one and `seats_available` falls by
    one, and both of the employer jurisdiction's compliance percentages are
    recomputed". The one row is the single member of both the session's
    enrollments collection and the employer jurisdiction's own collection.

    Design: Corner/endpoints/enrollment_links_session_and_jurisdiction_collections
    """
    world = fixtures.setup_enrollment_open_session(api)

    response = fixtures.enroll(
        api, world, "riverbend_1", "riverbend", "Riverbend Official 1"
    )
    enrollment = validate_success(response, 201)
    assert enrollment["training_session_id"] == world["session_id"]
    assert enrollment["jurisdiction_id"] == world["riverbend_id"]
    assert enrollment["status"] == "ENROLLED"
    assert enrollment["enrolled_by_user_id"] == ADMIN_OPS_ID

    owned, owned_meta = validate_paginated(
        api.list_jurisdiction_training_enrollments(
            world["riverbend_id"],
            make_jurisdiction_official_headers(world["riverbend_id"]),
        )
    )
    assert owned_meta["total_count"] == 1
    assert owned[0]["id"] == enrollment["id"]

    _, session_meta = validate_paginated(
        api.list_session_enrollments(world["session_id"], make_council_admin_headers())
    )
    assert session_meta["total_count"] == 1

    session = get_success_data(
        api.get_training_session(world["session_id"], make_council_admin_headers())
    )
    assert session["seats_available"] == 59


def test_05_filing_an_order_pins_the_versions_and_freezes_the_money(api):
    """"It pins versions: `pinned_amendment_versions` becomes a map from each
    `APPROVED` proposal's `id` to that proposal's `version` at this instant. It
    freezes money: `approved_incremental_cost_cents_at_filing` captures the
    cycle's `approved_incremental_cost_cents` as it stands." One approved
    amendment certified at 143,002,800 cents therefore yields a one-entry map,
    "the filer's identifier is stored in `filed_by_user_id`", and `published_at`
    is still null because it is only "stamped from the logical clock" at
    publication.

    Design: Corner/endpoints/filing_a_rule_pins_the_approved_amendment_versions
    """
    world = fixtures.setup_draft_adoption_rule(api)

    rule = validate_success(
        fixtures.advance_rule(
            api, world, "FILED", make_council_admin_headers(ADMIN_FILER_ID)
        )
    )
    assert rule["status"] == "FILED"
    assert rule["filed_by_user_id"] == ADMIN_FILER_ID
    assert rule["approved_incremental_cost_cents_at_filing"] == 143002800
    assert rule["published_at"] is None

    pinned = rule["pinned_amendment_versions"]
    assert len(pinned) == 1
    assert world["proposal_id"] in pinned

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert pinned[world["proposal_id"]] == proposal["version"]

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["approved_incremental_cost_cents"] == 143002800


def test_06_a_delivered_session_cannot_be_cancelled_by_hand(api):
    """A `DELIVERED` session may not be cancelled on request: the attempt "is
    refused with `ERR_SESSION_STATE_INVALID`", and the session "reaches
    `CANCELLED` only through the rule-withdrawal cascade of §3.7". The delivered
    figures therefore stand, and with four of five Riverbend officials having
    attended, `enforcement_readiness` reads "`READY` when
    `compliance_pct_attendance_basis` is at or above 80.00".

    Design: Corner/endpoints/cancelling_a_delivered_session_by_hand_is_rejected
    """
    world = fixtures.setup_delivered_session_riverbend_only(api)

    response = api.set_training_session_status(
        world["session_id"],
        factories.training_session_status_payload(
            "CANCELLED", cancellation_reason="Operator error."
        ),
        make_council_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_SESSION_STATE_INVALID, 409)

    session = get_success_data(
        api.get_training_session(world["session_id"], make_council_admin_headers())
    )
    assert session["status"] == "DELIVERED"
    assert session["cancellation_reason"] is None
    assert session["attended_count"] == 4
    assert session["no_show_count"] == 1

    riverbend = fixtures.read_jurisdiction(api, world["riverbend_id"])
    assert riverbend["compliance_pct_attendance_basis"] == 80.00
    assert riverbend["enforcement_readiness"] == "READY"
