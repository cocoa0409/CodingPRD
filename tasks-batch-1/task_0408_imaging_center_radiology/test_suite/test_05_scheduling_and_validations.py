"""Scheduling resource overlap (room cleanup buffer, technologist adjacency)
and the booking/decision validation errors.

Translates Difficulty/resource_temporal_overlap and Corner/validations
(the segregation_of_duties stub is owned by its named corner positive below).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_exam_payload, create_screening_payload, finalize_series_payload,
    prior_auth_decision_payload, create_prior_auth_payload, create_series_payload,
    create_report_payload, claim_read_payload,
    TEST_USERS, make_nurse_headers, make_technologist_headers, make_radiologist_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["center_admin_headers"]
CLERK = TEST_USERS["scheduling_clerk_headers"]


# ─── Difficulty: room overlap with cleanup buffer ─────────────────────

def test_room_overlap_with_cleanup_buffer(api):
    """PRD §3.4: "The room must be free for the requested window: the room's
    booking interval extended by its `cleanup_buffer_minutes` (the room is
    occupied across the half-open span from the start through the exam end plus
    the buffer) must not overlap any other non-cancelled exam in the same room,
    or the booking is rejected with `ERR_ROOM_DOUBLE_BOOKED`."

    Room buffer 15: exam A 09:00-09:30 occupies through 09:45; a second booking
    starting 09:40 falls inside the buffer => ERR_ROOM_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/room_overlap_with_cleanup_buffer
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="XRAY", name="XR",
                                  base_rvu=1.0, requires_prior_auth=False)
    room = fx.create_room(center["id"], modality["id"], name="XR-1", cleanup_buffer_minutes=15)
    tech1 = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T1", credentialed_modalities=["XRAY"])
    tech2 = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T2", credentialed_modalities=["XRAY"])
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["XRAY"])
    topo = {"center_id": center["id"], "modality_id": modality["id"],
            "modality": modality, "room_id": room["id"], "tech_id": tech1["id"],
            "nurse_id": nurse["id"], "rad_id": None}

    order1, o1v = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    fx.schedule_exam(topo, order1, o1v, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z",
                     room_id=room["id"], technologist_id=tech1["id"])
    order2, o2v = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    res = api.create_exam(order2,
            create_exam_payload(room_id=room["id"], technologist_id=tech2["id"],
                                scheduled_start_utc="2026-06-01T09:40:00Z",
                                scheduled_end_utc="2026-06-01T10:00:00Z",
                                expected_imaging_order_version=o2v), CLERK)
    validate_error(res, "ERR_ROOM_DOUBLE_BOOKED", 409)


def test_room_booking_after_cleanup_buffer_admissible(api):
    """Second translation of the room buffered-overlap rule, exercising the
    other side of the boundary: a booking starting exactly at end+buffer is free.

    PRD §3.4: "the room's booking interval extended by its
    `cleanup_buffer_minutes` (the room is occupied across the half-open span
    from the start through the exam end plus the buffer) must not overlap any
    other non-cancelled exam in the same room, or the booking is rejected with
    `ERR_ROOM_DOUBLE_BOOKED`."

    Room buffer 15: exam A 09:00-09:30 occupies the half-open span through 09:45,
    so a second booking starting at 09:45 does not overlap and is admissible.

    Design: Difficulty/resource_temporal_overlap/room_overlap_with_cleanup_buffer
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="XRAY", name="XR",
                                  base_rvu=1.0, requires_prior_auth=False)
    room = fx.create_room(center["id"], modality["id"], name="XR-1", cleanup_buffer_minutes=15)
    tech1 = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T1", credentialed_modalities=["XRAY"])
    tech2 = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T2", credentialed_modalities=["XRAY"])
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["XRAY"])
    topo = {"center_id": center["id"], "modality_id": modality["id"],
            "modality": modality, "room_id": room["id"], "tech_id": tech1["id"],
            "nurse_id": nurse["id"], "rad_id": None}

    order1, o1v = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    fx.schedule_exam(topo, order1, o1v, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z",
                     room_id=room["id"], technologist_id=tech1["id"])
    order2, o2v = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam2 = fx.schedule_exam(topo, order2, o2v, "2026-06-01T09:45:00Z", "2026-06-01T10:15:00Z",
                             room_id=room["id"], technologist_id=tech2["id"])
    assert exam2["status"] == "BOOKED"


def test_technologist_overlap_no_buffer_adjacent_ok(api):
    """PRD §3.4: "the technologist's interval — taken with no cleanup buffer —
    must not overlap any other non-cancelled exam assigned to the same
    technologist, or the booking is rejected with `ERR_TECH_DOUBLE_BOOKED`."

    Technologist interval is half-open [start, end) with no buffer: a second
    exam starting exactly at the prior exam's end (09:30) is adjacent (allowed),
    while one starting 09:15 overlaps => ERR_TECH_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/technologist_overlap_no_buffer_adjacent_ok
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="XRAY", name="XR",
                                  base_rvu=1.0, requires_prior_auth=False)
    room1 = fx.create_room(center["id"], modality["id"], name="XR-1")
    room2 = fx.create_room(center["id"], modality["id"], name="XR-2")
    room3 = fx.create_room(center["id"], modality["id"], name="XR-3")
    tech = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T", credentialed_modalities=["XRAY"])
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["XRAY"])
    topo = {"center_id": center["id"], "modality_id": modality["id"],
            "modality": modality, "room_id": room1["id"], "tech_id": tech["id"],
            "nurse_id": nurse["id"], "rad_id": None}

    order1, o1v = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    fx.schedule_exam(topo, order1, o1v, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z",
                     room_id=room1["id"], technologist_id=tech["id"])
    # Adjacent booking (start == prior end) must succeed.
    order2, o2v = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam2 = fx.schedule_exam(topo, order2, o2v, "2026-06-01T09:30:00Z", "2026-06-01T10:00:00Z",
                             room_id=room2["id"], technologist_id=tech["id"])
    assert exam2["status"] == "BOOKED"
    # Overlapping booking (09:15 inside 09:00-09:30) must fail.
    order3, o3v = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    res = api.create_exam(order3,
            create_exam_payload(room_id=room3["id"], technologist_id=tech["id"],
                                scheduled_start_utc="2026-06-01T09:15:00Z",
                                scheduled_end_utc="2026-06-01T09:45:00Z",
                                expected_imaging_order_version=o3v), CLERK)
    validate_error(res, "ERR_TECH_DOUBLE_BOOKED", 409)


def test_technologist_overlap_rejected_distinct_rooms(api):
    """Second translation of the technologist-overlap rule, isolating the
    rejection: even in a different room, a tech double-booked over an
    overlapping interval is rejected.

    PRD §3.4: "the technologist's interval — taken with no cleanup buffer — must
    not overlap any other non-cancelled exam assigned to the same technologist,
    or the booking is rejected with `ERR_TECH_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/technologist_overlap_no_buffer_adjacent_ok
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="XRAY", name="XR",
                                  base_rvu=1.0, requires_prior_auth=False)
    room1 = fx.create_room(center["id"], modality["id"], name="XR-1")
    room2 = fx.create_room(center["id"], modality["id"], name="XR-2")
    tech = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T", credentialed_modalities=["XRAY"])
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["XRAY"])
    topo = {"center_id": center["id"], "modality_id": modality["id"],
            "modality": modality, "room_id": room1["id"], "tech_id": tech["id"],
            "nurse_id": nurse["id"], "rad_id": None}
    order1, o1v = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    fx.schedule_exam(topo, order1, o1v, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z",
                     room_id=room1["id"], technologist_id=tech["id"])
    order2, o2v = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    res = api.create_exam(order2,
            create_exam_payload(room_id=room2["id"], technologist_id=tech["id"],
                                scheduled_start_utc="2026-06-01T09:10:00Z",
                                scheduled_end_utc="2026-06-01T09:40:00Z",
                                expected_imaging_order_version=o2v), CLERK)
    validate_error(res, "ERR_TECH_DOUBLE_BOOKED", 409)


# ─── Corner: validations ──────────────────────────────────────────────

def test_prior_auth_required_on_benefit_check(api):
    """PRD §3.2: "When the order's modality has `requires_prior_auth` true, the
    order must have a `PriorAuthorization` child in `AUTHORIZED` status, or the
    benefit check is rejected with `ERR_PRIOR_AUTH_REQUIRED`".

    Design: Corner/validations/error_prior_auth_required_on_benefit_check
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="MRI", name="MRI",
                                  base_rvu=2.0, requires_prior_auth=True)
    order = fx.create_order(center["id"], modality["id"], requires_contrast=False)
    res = api.benefit_check(order["id"], {}, CLERK)
    validate_error(res, "ERR_PRIOR_AUTH_REQUIRED", 402)


def test_insufficient_auth_units_on_authorize(api):
    """PRD §3.2: "the supplied `authorized_units` must be at least the
    `requested_units`, and a decision that authorizes fewer units than were
    requested is rejected with `ERR_INSUFFICIENT_AUTH_UNITS`."

    Design: Corner/validations/error_insufficient_auth_units_on_authorize
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="MRI", name="MRI",
                                  base_rvu=2.0, requires_prior_auth=True)
    order = fx.create_order(center["id"], modality["id"])
    pa = validate_success(api.create_prior_auth(order["id"],
            create_prior_auth_payload(payer_name="Acme", requested_units=5), CLERK), 201)
    res = api.prior_auth_decision(pa["id"],
            prior_auth_decision_payload("AUTHORIZE", authorized_units=2), CLERK)
    validate_error(res, "ERR_INSUFFICIENT_AUTH_UNITS", 422)


def test_invalid_interval_end_not_after_start(api):
    """PRD §3.4: "The interval itself must be valid — `scheduled_end_utc`
    strictly after `scheduled_start_utc`, otherwise `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/error_invalid_interval_end_before_start
    """
    topo = fx.setup_center_topology(modality_type="XRAY", requires_prior_auth=False,
                                    clock="2026-06-01T08:00:00Z")
    order_id, ov = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    res = api.create_exam(order_id,
            create_exam_payload(room_id=topo["room_id"], technologist_id=topo["tech_id"],
                                scheduled_start_utc="2026-06-01T09:30:00Z",
                                scheduled_end_utc="2026-06-01T09:00:00Z",
                                expected_imaging_order_version=ov), CLERK)
    validate_error(res, "ERR_INVALID_INTERVAL", 422)


def test_room_modality_mismatch(api):
    """PRD §3.4: "The booked room must host the same modality as the order
    requests and must not be `OUT_OF_SERVICE`; a mismatch or an out-of-service
    room is rejected with `ERR_ROOM_MODALITY_MISMATCH`."

    Design: Corner/validations/error_room_modality_mismatch
    """
    center = fx.create_center(name="C")
    fx.set_clock(center["id"], "2026-06-01T08:00:00Z")
    mri = fx.create_modality(center["id"], modality_type="MRI", name="MRI",
                             base_rvu=2.0, requires_prior_auth=False)
    ct = fx.create_modality(center["id"], modality_type="CT", name="CT",
                            base_rvu=3.0, requires_prior_auth=False)
    ct_room = fx.create_room(center["id"], ct["id"], name="CT-1")
    tech = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T",
                           credentialed_modalities=["MRI", "CT"])
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["MRI"])
    topo = {"center_id": center["id"], "modality_id": mri["id"], "modality": mri,
            "room_id": ct_room["id"], "tech_id": tech["id"], "nurse_id": nurse["id"], "rad_id": None}
    order_id, ov = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    res = api.create_exam(order_id,
            create_exam_payload(room_id=ct_room["id"], technologist_id=tech["id"],
                                scheduled_start_utc="2026-06-01T09:00:00Z",
                                scheduled_end_utc="2026-06-01T09:30:00Z",
                                expected_imaging_order_version=ov), CLERK)
    validate_error(res, "ERR_ROOM_MODALITY_MISMATCH", 422)


def test_tech_not_credentialed(api):
    """PRD §3.4: "The assigned technologist must be credentialed on the order's
    modality type, or the booking is rejected with `ERR_TECH_NOT_CREDENTIALED`."

    Design: Corner/validations/error_tech_not_credentialed
    """
    center = fx.create_center(name="C")
    fx.set_clock(center["id"], "2026-06-01T08:00:00Z")
    mri = fx.create_modality(center["id"], modality_type="MRI", name="MRI",
                             base_rvu=2.0, requires_prior_auth=False)
    room = fx.create_room(center["id"], mri["id"], name="MR-1")
    tech = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T", credentialed_modalities=["US"])
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["MRI"])
    topo = {"center_id": center["id"], "modality_id": mri["id"], "modality": mri,
            "room_id": room["id"], "tech_id": tech["id"], "nurse_id": nurse["id"], "rad_id": None}
    order_id, ov = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    res = api.create_exam(order_id,
            create_exam_payload(room_id=room["id"], technologist_id=tech["id"],
                                scheduled_start_utc="2026-06-01T09:00:00Z",
                                scheduled_end_utc="2026-06-01T09:30:00Z",
                                expected_imaging_order_version=ov), CLERK)
    validate_error(res, "ERR_TECH_NOT_CREDENTIALED", 422)


def test_radiologist_not_credentialed_on_claim(api):
    """PRD §3.6: "the acting radiologist must be credentialed on the order's
    modality type, or the claim is rejected with
    `ERR_RADIOLOGIST_NOT_CREDENTIALED`".

    Design: Corner/validations/error_radiologist_not_credentialed_on_claim
    """
    # XRAY exam at ACQUIRED; radiologist credentialed only US (distinct from tech).
    topo = fx.setup_center_topology(modality_type="XRAY", requires_prior_auth=False,
                                    clock="2026-06-01T09:00:00Z", rad_creds=["US"])
    order_id, ov = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam = fx.schedule_exam(topo, order_id, ov, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z")
    exam = fx.acquire_exam(exam["id"], topo["tech_id"], series_labels=("PA",),
                           acquired_clock=None, center_id=topo["center_id"])
    res = api.claim_read(exam["id"], claim_read_payload(exam["version"]),
                         make_radiologist_headers(topo["rad_id"]))
    validate_error(res, "ERR_RADIOLOGIST_NOT_CREDENTIALED", 422)


def test_segregation_of_duties_tech_cannot_read(api):
    """PRD §3.6: "the acting `X-User-ID` must not equal the exam's
    `technologist_id`, enforcing segregation of duties — the same person may not
    both acquire and read a study — otherwise `ERR_SEGREGATION_OF_DUTIES`".

    Design: Corner/validations/segregation_of_duties_tech_cannot_read
    """
    # A single staff member who is the technologist and is credentialed to read.
    topo = fx.setup_center_topology(modality_type="XRAY", requires_prior_auth=False,
                                    clock="2026-06-01T09:00:00Z", with_radiologist=False)
    order_id, ov = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam = fx.schedule_exam(topo, order_id, ov, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z")
    exam = fx.acquire_exam(exam["id"], topo["tech_id"], series_labels=("PA",),
                           acquired_clock=None, center_id=topo["center_id"])
    # The dual-role staff (the technologist) attempts to claim-read.
    res = api.claim_read(exam["id"], claim_read_payload(exam["version"]),
                         make_radiologist_headers(topo["tech_id"]))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", 409)


def test_reject_reason_required(api):
    """PRD §3.5: "a `REPEATED` or `REJECTED` series must carry a `reject_reason`
    of `MOTION`, `POSITIONING`, `EXPOSURE`, `ARTIFACT`, or `EQUIPMENT`, and
    finalizing to `REPEATED` or `REJECTED` without one is rejected with
    `ERR_REJECT_REASON_REQUIRED`."

    Design: Corner/validations/error_reject_reason_required
    """
    acq = fx.setup_acquiring_exam(modality_type="XRAY", repeat_rate_threshold_pct=200.0)
    th = make_technologist_headers(acq["topo"]["tech_id"])
    ser = validate_success(api.create_series(acq["exam_id"], create_series_payload("PA"), th), 201)
    res = api.finalize_series(ser["id"], finalize_series_payload("REJECTED"), th)
    validate_error(res, "ERR_REJECT_REASON_REQUIRED", 422)
