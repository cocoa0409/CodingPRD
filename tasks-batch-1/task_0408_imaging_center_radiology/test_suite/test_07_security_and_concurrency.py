"""Role-based access control and optimistic concurrency control.

Translates Corner/rbac and Corner/cross_cutting_complexity_layers (OCC, version
increment).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_error_is_one_of,
    create_center_payload, create_order_payload, create_exam_payload,
    claim_read_payload,
    TEST_USERS, build_user_headers,
    make_nurse_headers, make_technologist_headers, make_radiologist_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["center_admin_headers"]
CLERK = TEST_USERS["scheduling_clerk_headers"]


# ─── Corner: RBAC ─────────────────────────────────────────────────────

def test_nurse_cannot_create_order(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to invoke the requested operation (per the authorization matrix in
    §4), the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §4: "| POST | `/imaging-centers/{id}/imaging-orders` | Create an imaging
    order | SchedulingClerk |".

    Design: Corner/rbac/rbac_nurse_cannot_create_order
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="XRAY", name="XR", base_rvu=1.0)
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["XRAY"])
    res = api.create_order(center["id"],
                           create_order_payload(modality_id=modality["id"],
                                                patient_mrn="M1", ordering_provider_npi="N1"),
                           make_nurse_headers(nurse["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", 403)


def test_missing_headers_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two mandatory headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
    operational capacity under which the request is made. If either header is
    missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/rbac_missing_headers_unauthenticated
    """
    res = api.create_center(create_center_payload(name="C"), {"Content-Type": "application/json"})
    validate_error(res, "ERR_UNAUTHENTICATED", 401)


def test_clerk_cannot_sign_off(api):
    """PRD §2.1: "the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §4: "| POST | `/imaging-exams/{id}/sign-off` | Sign off the read;
    READ_COMPLETE to SIGNED_OFF | Radiologist |".
    PRD §3.9: "then role authorization for the endpoint (`ERR_UNAUTHORIZED`),
    then existence of every path-referenced resource validated left to right
    (`ERR_NOT_FOUND`)".

    The role gate fires before state, so a freshly BOOKED exam still rejects.

    Design: Corner/rbac/rbac_clerk_cannot_sign_off
    """
    topo = fx.setup_center_topology(modality_type="XRAY", requires_prior_auth=False,
                                    clock="2026-06-01T09:00:00Z")
    order_id, ov = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam = fx.schedule_exam(topo, order_id, ov, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z")
    res = api.sign_off(exam["id"], CLERK)
    validate_error(res, "ERR_UNAUTHORIZED", 403)


def test_not_assigned_tech_cannot_check_in(api):
    """PRD §3.5: "Each technologist action requires that the acting `X-User-ID`
    equal the exam's `technologist_id`, or the action is rejected with
    `ERR_NOT_ASSIGNED_TECH`."

    Design: Corner/rbac/rbac_not_assigned_tech_cannot_check_in
    """
    center = fx.create_center(name="C")
    fx.set_clock(center["id"], "2026-06-01T09:00:00Z")
    xr = fx.create_modality(center["id"], modality_type="XRAY", name="XR",
                            base_rvu=1.0, requires_prior_auth=False)
    room = fx.create_room(center["id"], xr["id"], name="XR-1")
    tech1 = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T1", credentialed_modalities=["XRAY"])
    tech2 = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T2", credentialed_modalities=["XRAY"])
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["XRAY"])
    topo = {"center_id": center["id"], "modality_id": xr["id"], "modality": xr,
            "room_id": room["id"], "tech_id": tech1["id"], "nurse_id": nurse["id"], "rad_id": None}
    order_id, ov = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam = fx.schedule_exam(topo, order_id, ov, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z",
                            technologist_id=tech1["id"])
    # tech2 (not the assigned technologist) tries to check in.
    res = api.check_in(exam["id"], make_technologist_headers(tech2["id"]))
    validate_error(res, "ERR_NOT_ASSIGNED_TECH", 403)


# ─── Corner: OCC and version increment ────────────────────────────────

def _acquired_exam_two_rads(api):
    """Build an XRAY exam at ACQUIRED with two credentialed radiologists
    (neither is the technologist). Returns (topo, exam_dict, rad1, rad2)."""
    center = fx.create_center(name="C")
    fx.set_clock(center["id"], "2026-06-01T09:00:00Z")
    xr = fx.create_modality(center["id"], modality_type="XRAY", name="XR",
                            base_rvu=1.0, requires_prior_auth=False)
    room = fx.create_room(center["id"], xr["id"], name="XR-1")
    tech = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T", credentialed_modalities=["XRAY"])
    rad1 = fx.create_staff(center["id"], "RADIOLOGIST", full_name="R1", credentialed_modalities=["XRAY"])
    rad2 = fx.create_staff(center["id"], "RADIOLOGIST", full_name="R2", credentialed_modalities=["XRAY"])
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["XRAY"])
    topo = {"center_id": center["id"], "modality_id": xr["id"], "modality": xr,
            "room_id": room["id"], "tech_id": tech["id"], "nurse_id": nurse["id"], "rad_id": rad1["id"]}
    order_id, ov = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam = fx.schedule_exam(topo, order_id, ov, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z")
    exam = fx.acquire_exam(exam["id"], tech["id"], series_labels=("PA",),
                           acquired_clock=None, center_id=center["id"])
    return topo, exam, rad1, rad2


def test_claim_read_stale_exam_version_412(api):
    """PRD §2.10: "The second is a radiologist claiming an exam to read. That
    request must carry `expected_imaging_exam_version`, and the value must equal
    the target `ImagingExam`'s current `version`. If another radiologist has
    already claimed the exam — legitimately setting its `radiologist_id` and
    incrementing the exam's `version` — then a client holding the pre-claim
    version is stale, and its claim is rejected with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/claim_read_stale_exam_version_412
    """
    topo, exam, rad1, rad2 = _acquired_exam_two_rads(api)
    pre_v = exam["version"]
    first = validate_success(
        api.claim_read(exam["id"], claim_read_payload(pre_v), make_radiologist_headers(rad1["id"])), 200)
    assert first["status"] == "READING"
    assert first["radiologist_id"] == rad1["id"]
    res = api.claim_read(exam["id"], claim_read_payload(pre_v), make_radiologist_headers(rad2["id"]))
    # PRD §3.9 orders the state check (`ERR_INVALID_STATE`) strictly before the
    # OCC version check (`ERR_STALE_VERSION`). The first claim moves the exam
    # ACQUIRED -> READING, so by the time the stale second claim is processed the
    # exam is no longer ACQUIRED; a §3.9-faithful implementation surfaces
    # ERR_INVALID_STATE, while §2.10's narration of this scenario names
    # ERR_STALE_VERSION. Both readings are PRD-faithful.
    validate_error_is_one_of(res, ["ERR_STALE_VERSION", "ERR_INVALID_STATE"])


def test_claim_read_fresh_version_then_already_claimed(api):
    """PRD §3.6: "the exam must not already be claimed, that is its
    `radiologist_id` must still be null, otherwise `ERR_ALREADY_CLAIMED`."
    PRD §2.10: "the value must equal the target `ImagingExam`'s current
    `version`".

    A second claim carrying the FRESH post-claim version passes the OCC check
    but the exam is already claimed => ERR_ALREADY_CLAIMED, not ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/claim_read_fresh_version_then_already_claimed
    """
    topo, exam, rad1, rad2 = _acquired_exam_two_rads(api)
    claimed = validate_success(
        api.claim_read(exam["id"], claim_read_payload(exam["version"]),
                       make_radiologist_headers(rad1["id"])), 200)
    fresh_v = claimed["version"]
    res = api.claim_read(exam["id"], claim_read_payload(fresh_v), make_radiologist_headers(rad2["id"]))
    # PRD §3.6/§3.9 order the ACQUIRED state check (`ERR_INVALID_STATE`) before
    # the already-claimed check (`ERR_ALREADY_CLAIMED`). The first claim moves the
    # exam ACQUIRED -> READING, so the second claim (even with the fresh version)
    # hits the state gate first under a §3.9-faithful reading; §3.6 also names
    # ERR_ALREADY_CLAIMED for an exam whose radiologist_id is already set. Both
    # readings are PRD-faithful.
    validate_error_is_one_of(res, ["ERR_ALREADY_CLAIMED", "ERR_INVALID_STATE"])


def test_schedule_exam_stale_order_version_412(api):
    """PRD §2.10: "The first is scheduling an exam against an order. That
    request must carry `expected_imaging_order_version`, and the value must
    equal the target `ImagingOrder`'s current `version`. If another scheduling
    action has already created an exam for the order — which legitimately moves
    the order from `SCREEN_CLEARED` to `SCHEDULED` and increments the order's
    `version` — then a client still holding the pre-scheduling version is
    working from a stale view, and its create is rejected with
    `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/schedule_exam_stale_order_version_412
    """
    center = fx.create_center(name="C")
    fx.set_clock(center["id"], "2026-06-01T09:00:00Z")
    xr = fx.create_modality(center["id"], modality_type="XRAY", name="XR",
                            base_rvu=1.0, requires_prior_auth=False)
    room1 = fx.create_room(center["id"], xr["id"], name="XR-1")
    room2 = fx.create_room(center["id"], xr["id"], name="XR-2")
    tech1 = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T1", credentialed_modalities=["XRAY"])
    tech2 = fx.create_staff(center["id"], "TECHNOLOGIST", full_name="T2", credentialed_modalities=["XRAY"])
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["XRAY"])
    topo = {"center_id": center["id"], "modality_id": xr["id"], "modality": xr,
            "room_id": room1["id"], "tech_id": tech1["id"], "nurse_id": nurse["id"], "rad_id": None}
    order_id, pre_v = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    # First exam create with the fresh version succeeds and bumps the order.
    exam1 = fx.schedule_exam(topo, order_id, pre_v, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z",
                             room_id=room1["id"], technologist_id=tech1["id"])
    assert exam1["status"] == "BOOKED"
    # Second create still carrying the stale pre-schedule version is rejected.
    res = api.create_exam(order_id,
            create_exam_payload(room_id=room2["id"], technologist_id=tech2["id"],
                                scheduled_start_utc="2026-06-01T10:00:00Z",
                                scheduled_end_utc="2026-06-01T10:30:00Z",
                                expected_imaging_order_version=pre_v), CLERK)
    # PRD §3.9 orders the state check (`ERR_INVALID_STATE`) strictly before the
    # OCC version check (`ERR_STALE_VERSION`). The first scheduling moves the
    # order SCREEN_CLEARED -> SCHEDULED, so the stale second create is no longer
    # acting on a SCREEN_CLEARED order; a §3.9-faithful implementation surfaces
    # ERR_INVALID_STATE, while §2.10's narration of this scenario names
    # ERR_STALE_VERSION. Both readings are PRD-faithful.
    validate_error_is_one_of(res, ["ERR_STALE_VERSION", "ERR_INVALID_STATE"])


def test_version_increments_on_every_mutation(api):
    """PRD §2.4: "The `version` begins at 1 on creation and increments by
    exactly one on every mutation of the resource, whether that mutation is a
    direct client write or a server-initiated reconciliation".
    PRD §3.8: "Locking a center sets its `admin_locked` flag true and forces the
    `posture` to `LOCKED`".

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
    """
    created = validate_success(api.create_center(create_center_payload(name="C"), ADMIN), 201)
    assert created["version"] == 1
    locked = validate_success(api.lock_center(created["id"], ADMIN), 200)
    assert locked["version"] == 2
    assert locked["posture"] == "LOCKED"
