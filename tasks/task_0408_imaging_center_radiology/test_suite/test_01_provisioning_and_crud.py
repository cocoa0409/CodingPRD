"""Provisioning, CRUD, defaults, computed/system fields, and listing.

Translates Corner/entities, Corner/endpoints (listing), and
Corner/consistency_model instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    assert_center, assert_order, assert_modality,
    create_center_payload, create_order_payload, create_modality_payload,
    create_staff_payload, set_clock_payload, create_screening_payload,
    TEST_USERS, RANDOM_UUID,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["center_admin_headers"]
CLERK = TEST_USERS["scheduling_clerk_headers"]


def test_create_center_returns_201_with_defaults(api):
    """PRD §3.1: "A new center starts with `posture` `OPEN`, `admin_locked`
    false, all three series counters at zero — `total_acquired_series`,
    `total_repeat_reject_series`, and `repeat_reject_rate_pct`".
    PRD §3.1: "a `critical_ack_sla_minutes` value (defaulting to 60 minutes),
    and a `repeat_rate_threshold_pct` (defaulting to 8.0 percent)."
    PRD §2.4: "The `version` begins at 1 on creation".

    Design: Corner/entities/create_imaging_center_returns_201_with_defaults
    """
    res = api.create_center(create_center_payload(name="C"), ADMIN)
    center = validate_success(res, 201)
    assert_center(center)
    assert center["posture"] == "OPEN"
    assert center["critical_ack_sla_minutes"] == 60
    assert center["repeat_rate_threshold_pct"] == 8.0
    assert center["repeat_reject_rate_pct"] == 0.0
    assert center["version"] == 1


def test_create_order_missing_modality_id_returns_invalid_request(api):
    """PRD §3.9: "then presence and type/enum validity of required body fields
    (`ERR_INVALID_REQUEST`)."
    PRD §3.2: "The order names the requested `modality_id`, the `patient_mrn`
    (a free-form medical record number), and the ordering clinician's
    `ordering_provider_npi`."

    Design: Corner/entities/create_order_missing_required_field_returns_invalid_request
    """
    center = fx.create_center(name="C")
    res = api.create_order(center["id"],
                           {"patient_mrn": "M1", "ordering_provider_npi": "N1"}, CLERK)
    validate_error(res, "ERR_INVALID_REQUEST", 400)


def test_create_order_defaults_priority_routine_requires_contrast_false(api):
    """PRD §3.2: "It optionally carries a `priority` of `STAT` or `ROUTINE`
    (defaulting to `ROUTINE`; `STAT` orders are read-prioritized and carry
    tighter turnaround targets) and a `requires_contrast` flag (defaulting to
    false)".
    PRD §3.2: "A new order is `REQUESTED` and also stores its
    `imaging_center_id`."

    Design: Corner/entities/create_order_defaults_priority_routine_requires_contrast_false
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="XRAY", name="XR", base_rvu=1.0)
    res = api.create_order(center["id"],
                           create_order_payload(modality_id=modality["id"],
                                                patient_mrn="M1", ordering_provider_npi="N1"),
                           CLERK)
    order = validate_success(res, 201)
    assert_order(order)
    assert order["priority"] == "ROUTINE"
    assert order["requires_contrast"] is False
    assert order["status"] == "REQUESTED"


def test_modality_requires_contrast_screening_computed_from_type(api):
    """PRD §3.1: "The modality's `requires_contrast_screening` is not supplied
    by the caller — it is derived as true exactly when the `modality_type` is
    `MRI` or `CT`, and false for `XRAY` and `US`, which never require contrast
    or safety screening."

    Design: Corner/entities/modality_requires_contrast_screening_computed_from_type
    """
    center = fx.create_center(name="C")
    mri = validate_success(api.create_modality(center["id"],
                           create_modality_payload(modality_type="MRI", name="MRI", base_rvu=2.0), ADMIN), 201)
    us = validate_success(api.create_modality(center["id"],
                          create_modality_payload(modality_type="US", name="US", base_rvu=1.0), ADMIN), 201)
    assert mri["requires_contrast_screening"] is True
    assert us["requires_contrast_screening"] is False


def test_create_staff_empty_credentials_returns_error(api):
    """PRD §3.1: "The `credentialed_modalities` array must be non-empty;
    creating a staff member with an empty credential list is rejected with
    `ERR_EMPTY_CREDENTIALS`."

    Design: Corner/entities/create_staff_empty_credentials_returns_error
    """
    center = fx.create_center(name="C")
    res = api.create_staff(center["id"],
                           create_staff_payload(staff_role="TECHNOLOGIST", full_name="T",
                                                credentialed_modalities=[]), ADMIN)
    validate_error(res, "ERR_EMPTY_CREDENTIALS", 422)


def test_get_order_not_found_returns_404(api):
    """PRD §2.5: "the server validates them strictly left to right and rejects
    the request with `ERR_NOT_FOUND` at the first identifier that does not
    resolve to an existing resource."

    Design: Corner/entities/get_order_not_found_returns_404
    """
    res = api.get_order(RANDOM_UUID, CLERK)
    validate_error(res, "ERR_NOT_FOUND", 404)


def test_create_order_unknown_modality_reference_not_found(api):
    """PRD §2.5: "if any of them references a resource that does not exist, the
    request is rejected with `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/create_order_unknown_modality_reference_not_found
    """
    center = fx.create_center(name="C")
    res = api.create_order(center["id"],
                           create_order_payload(modality_id="00000000-0000-4000-8000-000000000001",
                                                patient_mrn="M1", ordering_provider_npi="N1"),
                           CLERK)
    validate_error(res, "ERR_REFERENCE_NOT_FOUND", 404)


def test_system_fields_ignored_on_create(api):
    """PRD §2.6: "A freshly created center has `now_utc` equal to
    `1970-01-01T00:00:00.000Z`".
    PRD §3.1: "A new center starts with `posture` `OPEN`".

    Design: Corner/entities/system_fields_ignored_on_create
    """
    res = api.create_center(create_center_payload(name="C"), ADMIN)
    center = validate_success(res, 201)
    assert center["now_utc"] == "1970-01-01T00:00:00.000Z"
    assert center["posture"] == "OPEN"


def test_list_center_orders_pagination_envelope(api):
    """PRD §2.3: "Every list response includes the following fields inside the
    envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_center_orders_pagination_envelope
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="XRAY", name="XR", base_rvu=1.0)
    fx.create_order(center["id"], modality["id"], patient_mrn="M1", ordering_provider_npi="N1")
    fx.create_order(center["id"], modality["id"], patient_mrn="M2", ordering_provider_npi="N1")
    resp = api.list_center_orders(center["id"], CLERK, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_get_room_exams_reverse_reachability(api):
    """PRD §3.4: "a `SchedulingClerk` schedules it by creating an `ImagingExam`,
    which both books resources and advances the order from `SCREEN_CLEARED` to
    `SCHEDULED`. The scheduling payload names the `room_id` to reserve".
    PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."

    Design: Corner/endpoints/get_room_exams_reverse_reachability
    """
    topo = fx.setup_center_topology(modality_type="XRAY", requires_prior_auth=False,
                                    clock="2026-06-01T08:00:00Z")
    order_id, ov = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam = fx.schedule_exam(topo, order_id, ov,
                            "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z")
    resp = api.list_room_exams(topo["room_id"], CLERK)
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == exam["id"]


def test_immediate_consistency_rate_visible_in_same_response(api):
    """PRD §2.9: "the parent must already reflect the new state by the time the
    triggering request returns."
    PRD §3.5: "On each finalization the center's `total_acquired_series`
    increases by one; additionally, when the outcome is `REPEATED` or
    `REJECTED`, the center's `total_repeat_reject_series` also increases by one.
    The `repeat_reject_rate_pct` is then recomputed as 100 multiplied by
    `total_repeat_reject_series` divided by `total_acquired_series`".

    Design: Corner/consistency_model/immediate_consistency_rate_visible_in_same_response
    """
    acq = fx.setup_acquiring_exam(modality_type="XRAY", repeat_rate_threshold_pct=200.0)
    fx.finalize_n_series(acq["exam_id"], acq["topo"]["tech_id"], n_accepted=0, n_repeated=1)
    center = validate_success(api.get_center(acq["topo"]["center_id"], ADMIN), 200)
    assert center["repeat_reject_rate_pct"] == 100.0
    assert center["total_acquired_series"] == 1
    assert center["total_repeat_reject_series"] == 1
