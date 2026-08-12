"""Destruction orders: SLA lateness boundary and the segregated confirm control."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_donor_with_consent,
    create_returned_kit,
    accession_specimen,
    create_pending_destruction_order,
    set_clock_to,
    get_destruction_order,
    get_specimen,
    make_quality_officer_headers,
    make_lab_headers,
)


def _accession_10ml(reference_suffix):
    donor, consent = create_donor_with_consent()
    kit = create_returned_kit(donor["id"])
    specimen = accession_specimen(donor["id"], kit["id"], consent["id"],
                                  initial_volume_ml=10.0)
    return specimen


def test_destruction_completed_late_strict_boundary(api):
    """PRD §3.9: "Confirmation records the officer as `confirmed_by_user_id`, computes
    `completed_late` as true exactly when the confirmation time is strictly later than
    `due_at` (confirmation precisely at the deadline counts as on time), moves the
    order to `COMPLETED`, and finishes the destruction: the specimen flips from
    `DESTRUCTION_PENDING` to `DESTROYED`, every child aliquot in `DESTRUCTION_PENDING`
    flips to `DESTROYED` with its `remaining_volume_ml` zeroed, and each `ACTIVE`
    de-identification key of the specimen flips to `REVOKED`."
    PRD §3.9: "Creating an order — manual or automatic — flips the target specimen to
    `DESTRUCTION_PENDING` (a specimen may enter this state from `ACCESSIONED` or
    `IN_STORAGE` alike), flips every child aliquot in `IN_STORAGE`, `RESERVED`, or
    `QUARANTINED` to `DESTRUCTION_PENDING` as well, and sets the order's `due_at` to
    exactly 48 hours after its creation."

    Design: Corner/calculations/destruction_completed_late_strict_boundary
    """
    # Orders created at the default clock 2026-05-01T00:00:00Z: due_at 2026-05-03T00:00:00Z.
    specimen_1 = _accession_10ml("a")
    specimen_2 = _accession_10ml("b")
    order_1 = create_pending_destruction_order(specimen_1["id"], reason="QUALITY_FAILURE",
                                               creator="qo-1")
    order_2 = create_pending_destruction_order(specimen_2["id"], reason="OTHER",
                                               creator="qo-1")
    # Confirm the first exactly at due_at: on time (strict >).
    set_clock_to("2026-05-03T00:00:00Z")
    resp = api.confirm_destruction_order(order_1["id"], {}, make_quality_officer_headers("qo-2"))
    validate_success(resp, expected_status=200)
    # Confirm the second one minute past due_at: late.
    set_clock_to("2026-05-03T00:01:00Z")
    resp = api.confirm_destruction_order(order_2["id"], {}, make_quality_officer_headers("qo-2"))
    validate_success(resp, expected_status=200)
    order_1 = get_destruction_order(order_1["id"])
    assert order_1["status"] == "COMPLETED"
    assert order_1["completed_late"] is False, "confirm exactly at due_at is on time"
    order_2 = get_destruction_order(order_2["id"])
    assert order_2["status"] == "COMPLETED"
    assert order_2["completed_late"] is True, "confirm one minute past due_at is late"
    assert get_specimen(specimen_1["id"])["lifecycle_status"] == "DESTROYED"
    assert get_specimen(specimen_2["id"])["lifecycle_status"] == "DESTROYED"


def test_destruction_confirm_by_creator_rejected(api):
    """PRD §2.9: "The operator who creates a destruction order may not confirm its
    execution — `confirmed_by_user_id` must differ from `created_by_user_id`."
    PRD §3.9: "Confirmation records the officer as `confirmed_by_user_id`, computes
    `completed_late` as true exactly when the confirmation time is strictly later than
    `due_at` (confirmation precisely at the deadline counts as on time), moves the
    order to `COMPLETED`, and finishes the destruction"

    Design: Corner/validations/destruction_confirm_by_creator_rejected
    """
    specimen = _accession_10ml("sod")
    order = create_pending_destruction_order(specimen["id"], reason="QUALITY_FAILURE",
                                             creator="qo-1")
    # The creating officer cannot confirm.
    resp = api.confirm_destruction_order(order["id"], {}, make_quality_officer_headers("qo-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_destruction_order(order["id"])["status"] == "PENDING"
    # A different officer can.
    resp = api.confirm_destruction_order(order["id"], {}, make_quality_officer_headers("qo-2"))
    validate_success(resp, expected_status=200)
    assert get_destruction_order(order["id"])["status"] == "COMPLETED"
    assert get_specimen(specimen["id"])["lifecycle_status"] == "DESTROYED"


def test_lab_technician_cannot_confirm_destruction(api):
    """PRD §2.1: "A `QualityOfficer` owns quality and compliance contingencies: freezer
    failure declaration and return-to-service, destruction orders and their
    confirmation, and re-identification reveals."
    PRD §2.1: "Attempting an operation outside one's role — or, for the requester-owned
    mutations described in §3.6, acting on a request whose `requester_user_id` differs
    from `X-User-ID` — is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/lab_technician_cannot_confirm_destruction
    """
    specimen = _accession_10ml("rbac")
    order = create_pending_destruction_order(specimen["id"], reason="OTHER", creator="qo-1")
    resp = api.confirm_destruction_order(order["id"], {}, make_lab_headers("lab-9"))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert get_destruction_order(order["id"])["status"] == "PENDING"
