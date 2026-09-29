"""Authorisation corners: role exclusivity, actor identity, and authentication.

The seven roles divide the pipeline into disjoint slices, so a role that is
merely adjacent to an operation is still refused; on top of that sit the four
actor-identity gates, which pass the role check and fail on who is calling.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_BOOKED_ON_SESSION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TALENT_TYPE_MISMATCH,
    ERR_TASK_NOT_ASSIGNED_TO_ACTOR,
    ERR_UNAUTHENTICATED,
)
from test_helpers.constants import ROLE_STUDIO_ADMIN
from test_helpers.test_users import (
    ADMIN,
    COORDINATOR,
    PRODUCER,
    QC_REVIEWER,
    make_headers,
    make_photographer_headers,
    make_qc_reviewer_headers,
    make_retoucher_headers,
)


def _an_expected_box_at_the_dock_door(api):
    """Vendor NRTH and sample SMP-1001, still EXPECTED."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    sample = fx.create_sample(api, vendor["id"])
    return vendor, sample


def test_the_studio_admin_cannot_book_a_box_into_the_dock(api):
    """The admin who registered the vendor is not authorised for intake.

    PRD: "Once the role is recognised but is not among the roles authorised for the endpoint being called, the rejection becomes `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/receive_is_exclusive_to_the_sample_coordinator_and_the_admin_cannot_call_it
    """
    _vendor, sample = _an_expected_box_at_the_dock_door(api)

    validate_error(
        api.receive_sample(sample["id"], ADMIN), ERR_FORBIDDEN_ROLE, 403
    )

    after = validate_success(api.get_sample(sample["id"], COORDINATOR))
    assert after["custody_state"] == "EXPECTED"
    assert after["received_at"] is None


def test_the_sample_coordinator_books_the_same_box_in(api):
    """The identical request under the owning role moves custody off EXPECTED.

    PRD: "Receiving the box books it into the dock, moving custody `EXPECTED → RECEIVED`."

    Design: Corner/rbac/receive_is_exclusive_to_the_sample_coordinator_and_the_admin_cannot_call_it
    """
    _vendor, sample = _an_expected_box_at_the_dock_door(api)

    received = validate_success(api.receive_sample(sample["id"], COORDINATOR))

    assert received["custody_state"] == "RECEIVED"
    assert received["received_at"] == "2026-08-03T08:00:00.000Z"


def test_the_accepted_receipt_charges_the_vendors_outstanding_ledger(api):
    """Intake is what raises the vendor's count of boxes still out.

    PRD: "On success the system stamps `received_at` from the logical clock, derives `due_return_at` by adding the vendor's `sample_sla_days` to `received_at` as exact instant arithmetic (so a 14-day service level received at 09:15 is due back at 09:15 fourteen days later, not at midnight), raises the vendor's `outstanding_sample_count` by one, and increments the vendor's `version` by one."

    Design: Corner/rbac/receive_is_exclusive_to_the_sample_coordinator_and_the_admin_cannot_call_it
    """
    vendor, sample = _an_expected_box_at_the_dock_door(api)

    fx.receive_sample(api, sample["id"])

    assert validate_success(api.get_vendor(vendor["id"], ADMIN))[
        "outstanding_sample_count"
    ] == 1


def _a_session_on_the_floor(api):
    """A SHOOTING 09:00-13:00 MODEL session with one ASSIGNED ON_MODEL/FRONT item."""
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    fx.build_style_on_the_rack(api, world)
    fx.build_planned_session(
        api, world, item_specs=[{"asset_kind": "ON_MODEL", "angle_code": "FRONT"}]
    )
    fx.build_shooting_session(api, world)
    return world


def test_the_producer_who_planned_the_shoot_cannot_ingest_its_files(api):
    """Producer and Photographer are peer slices, not a hierarchy.

    PRD: "A `Photographer` is the person behind the camera and is the only role that may call a session to order, submit its colour reading, ingest captured files, or wrap it."

    Design: Corner/rbac/the_producer_cannot_ingest_assets_which_belong_to_the_photographer
    """
    world = _a_session_on_the_floor(api)

    validate_error(
        api.create_asset(
            f.asset_payload(world.item_id, "TOP1001_FRONT_001"), PRODUCER
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    assert world.read_item()["item_state"] == "ASSIGNED"
    assert world.read_item()["live_asset_count"] == 0


def _a_submitted_file_awaiting_review(api):
    """TOP1001_FRONT_001 has a SUBMITTED task claimed by the studio's retoucher."""
    world = _a_session_on_the_floor(api)
    fx.set_clock(api, "2026-08-03T10:00:00Z")
    fx.build_ingested_asset(api, world)
    fx.build_queued_task(api, world)
    fx.claim_next(api, world.retoucher_id)
    fx.set_clock(api, "2026-08-03T11:00:00Z")
    fx.submit_task(api, world.task_id, world.retoucher_id)
    return world


def test_a_reviewer_whose_id_is_the_retouchers_own_is_refused(api):
    """The role check passes and the segregation gate closes anyway.

    PRD: "The reviewer's `X-User-ID` must differ from the task's `assigned_retoucher_id`; equality is refused with `ERR_SEGREGATION_OF_DUTIES`, and that check precedes the state check."

    Design: Corner/rbac/the_qc_reviewer_cannot_be_the_retoucher_who_submitted_the_file
    """
    world = _a_submitted_file_awaiting_review(api)

    validate_error(
        api.qc_decision(
            world.task_id,
            f.qc_decision_payload("APPROVE"),
            make_qc_reviewer_headers(world.retoucher_id),
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    assert world.read_task()["task_state"] == "SUBMITTED"


def test_a_different_reviewer_signs_off_the_identical_request(api):
    """Somebody else's identifier on the same body settles the task and the file.

    PRD: "Approval moves the task `SUBMITTED → APPROVED`, which is terminal, stamps `approved_at` from the logical clock, moves the asset `QC_PENDING → APPROVED`, and lowers the provider's `assigned_asset_count` by one."

    Design: Corner/rbac/the_qc_reviewer_cannot_be_the_retoucher_who_submitted_the_file
    """
    world = _a_submitted_file_awaiting_review(api)

    approved = validate_success(
        api.qc_decision(
            world.task_id, f.qc_decision_payload("APPROVE"), QC_REVIEWER
        )
    )

    assert approved["task_state"] == "APPROVED"
    assert world.read_asset()["asset_state"] == "APPROVED"


def _a_frozen_session_and_an_uninvited_photographer(api):
    """Only Pia Ren holds the CONFIRMED booking; Ira Voss is crew on nothing."""
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    outsider = fx.create_photographer(
        api, full_name="Ira Voss", hourly_rate_cents=11000, day_rate_cents=70000
    )
    fx.build_style_on_the_rack(api, world)
    fx.build_planned_session(
        api, world, item_specs=[{"asset_kind": "ON_MODEL", "angle_code": "FRONT"}]
    )
    fx.lock_session(api, world.session_id)
    fx.set_clock(api, "2026-08-03T09:00:00Z")
    return world, outsider


def test_a_photographer_with_no_booking_here_cannot_call_the_session_to_order(api):
    """Holding the role is not the same as holding the booking.

    PRD: "A photographer with only a `HELD` booking, a photographer booked on a different session, or any other talent profile is refused with `ERR_NOT_BOOKED_ON_SESSION`, and that identity gate is evaluated before the session's own state is considered."

    Design: Corner/rbac/the_photographer_identity_gate_demands_a_confirmed_booking_on_that_session
    """
    world, outsider = _a_frozen_session_and_an_uninvited_photographer(api)

    validate_error(
        api.start_session(
            world.session_id, make_photographer_headers(outsider["id"])
        ),
        ERR_NOT_BOOKED_ON_SESSION,
        403,
    )

    assert world.read_session()["session_state"] == "LOCKED"


def test_the_booked_photographer_starts_the_very_same_session(api):
    """The crew member the call sheet names moves it off LOCKED.

    PRD: "Calling the session to order then moves it `LOCKED → SHOOTING` and stamps `started_at` from the logical clock; a session that is not `LOCKED` refuses with `ERR_SESSION_NOT_LOCKED`."

    Design: Corner/rbac/the_photographer_identity_gate_demands_a_confirmed_booking_on_that_session
    """
    world, _outsider = _a_frozen_session_and_an_uninvited_photographer(api)

    started = validate_success(
        api.start_session(
            world.session_id, make_photographer_headers(world.photographer_id)
        )
    )

    assert started["session_state"] == "SHOOTING"
    assert started["started_at"] == "2026-08-03T09:00:00.000Z"


def _an_in_progress_task_and_two_wrong_actors(api):
    """Remy Ott owns the claim; Sol Adeyemi retouches elsewhere and Kip Lund styles."""
    world = _a_session_on_the_floor(api)
    second = fx.create_retoucher(
        api, full_name="Sol Adeyemi", hourly_rate_cents=6500, day_rate_cents=42000
    )
    stylist = fx.create_stylist(
        api, full_name="Kip Lund", hourly_rate_cents=9000, day_rate_cents=50000
    )
    fx.set_clock(api, "2026-08-03T10:00:00Z")
    fx.build_ingested_asset(api, world)
    fx.build_queued_task(api, world)
    fx.claim_next(api, world.retoucher_id)
    return world, second, stylist


def test_another_retoucher_cannot_submit_somebody_elses_claim(api):
    """The ownership comparison is against the task's own assigned retoucher.

    PRD: "Only the assigned retoucher may do it: a submission whose `X-User-ID` differs from the task's `assigned_retoucher_id` is refused with `ERR_TASK_NOT_ASSIGNED_TO_ACTOR`, and that ownership check precedes the state check."

    Design: Corner/rbac/retoucher_ownership_and_talent_type_gates_reject_the_wrong_actor
    """
    world, second, _stylist = _an_in_progress_task_and_two_wrong_actors(api)

    validate_error(
        api.submit_retouch_task(
            world.task_id,
            make_retoucher_headers(second["id"]),
            {"note": "cleaned up"},
        ),
        ERR_TASK_NOT_ASSIGNED_TO_ACTOR,
        403,
    )

    assert world.read_task()["task_state"] == "IN_PROGRESS"


def test_a_stylist_carrying_the_retoucher_header_cannot_claim(api):
    """The header names a role; the identifier has to resolve to a retoucher.

    PRD: "The acting `X-User-ID` must resolve to a talent profile whose `talent_type` is `RETOUCHER`, and anything else is refused with `ERR_TALENT_TYPE_MISMATCH`."

    Design: Corner/rbac/retoucher_ownership_and_talent_type_gates_reject_the_wrong_actor
    """
    _world, _second, stylist = _an_in_progress_task_and_two_wrong_actors(api)

    validate_error(
        api.claim_next_retouch_task(make_retoucher_headers(stylist["id"])),
        ERR_TALENT_TYPE_MISMATCH,
        422,
    )


def test_the_assigned_retoucher_submits_the_identical_request(api):
    """The owner of the claim hands the file to quality control.

    PRD: "The task moves to `SUBMITTED` and `submitted_at` is stamped from the logical clock."

    Design: Corner/rbac/retoucher_ownership_and_talent_type_gates_reject_the_wrong_actor
    """
    world, _second, _stylist = _an_in_progress_task_and_two_wrong_actors(api)

    submitted = validate_success(
        api.submit_retouch_task(
            world.task_id,
            make_retoucher_headers(world.retoucher_id),
            {"note": "cleaned up"},
        )
    )

    assert submitted["task_state"] == "SUBMITTED"
    assert submitted["assigned_retoucher_id"] == world.retoucher_id


def test_an_empty_acting_identifier_is_unauthenticated(api):
    """The header is effectively absent, so nothing about the body is considered.

    PRD: "If either header is absent or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/request_missing_x_user_id_header_is_unauthenticated
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")

    validate_error(
        api.create_vendor(
            {"vendor_code": "NRTH"}, make_headers("", ROLE_STUDIO_ADMIN)
        ),
        ERR_UNAUTHENTICATED,
        401,
    )


def test_a_role_string_outside_the_seven_is_unauthenticated(api):
    """`StudioIntern` is not a role this system recognises.

    PRD: "The same code and status are returned when `X-User-Role` carries a string that is not one of the seven roles this system recognises."

    Design: Corner/rbac/request_missing_x_user_id_header_is_unauthenticated
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")

    validate_error(
        api.create_vendor(
            {"vendor_code": "NRTH"}, make_headers("intern-01", "StudioIntern")
        ),
        ERR_UNAUTHENTICATED,
        401,
    )


def test_authentication_outranks_the_request_shape_check(api):
    """The payload is missing its required name, and that is never reported.

    PRD: "These three checks run before anything else, in exactly that order: header presence, then role recognition, then endpoint authorisation."

    Design: Corner/rbac/request_missing_x_user_id_header_is_unauthenticated
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")

    validate_error(
        api.create_vendor(
            {"vendor_code": "NRTH"}, make_headers("", ROLE_STUDIO_ADMIN)
        ),
        ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.create_vendor(
            {"vendor_code": "NRTH"}, make_headers("intern-01", "StudioIntern")
        ),
        ERR_UNAUTHENTICATED,
        401,
    )

    _, meta = validate_paginated(
        api.list_styles(ADMIN, {"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0
