"""Dispatch-time regulatory gates: eligibility, permit, term, and their
pipeline ordering."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    book_shipment,
    get_shipment,
    set_logical_clock,
    setup_dispatch_ready_chain,
    validate_error,
    validate_paginated,
    validate_success,
)

BROKER = TEST_USERS["broker_ops_headers"]
CO_FILE = TEST_USERS["compliance_officer_file_headers"]


def test_dispatch_without_permit_returns_permit_required(api):
    """PRD §3.5: "An `ACTIVE` state permit must cover the destination state and
    the stream's material, with the current logical date on or after its
    `issued_on` and on or before its `expires_on`, else `ERR_PERMIT_REQUIRED`."

    Design: Corner/validations/dispatch_without_permit_returns_permit_required
    """
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=100, committed_commitment_tons=100,
        include_permit=False,
    )
    shipment = book_shipment(chain, gross_tons=10)

    resp = api.dispatch_shipment(shipment["id"], chain["generator_headers"])
    validate_error(resp, ApiErrorId.ERR_PERMIT_REQUIRED)

    shipment_after = get_shipment(shipment["id"])
    assert shipment_after["status"] == "BOOKED", "failed dispatch must leave the shipment BOOKED"


def test_dispatch_after_eligibility_expiry_rejected(api):
    """PRD §3.5: "An `APPROVED` reuse-eligibility determination must exist for
    the agreement's stream and the commitment's destination state whose window
    covers the current logical date — that is, the date falls on or after
    `valid_from` and strictly before `valid_until`; determinations in
    `SUSPENDED` or `EXPIRED` do not qualify, and absence of a qualifying
    determination is rejected with `ERR_REUSE_NOT_ELIGIBLE`."
    PRD §2.4: "A reuse-eligibility determination in `APPROVED` or `SUSPENDED`
    status whose `valid_until` date has been reached or passed by the current
    logical date transitions to `EXPIRED`, which is terminal."

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_expired_eligibility
    """
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=100, committed_commitment_tons=100,
        eligibility_valid_until="2026-08-10",
    )
    shipment = book_shipment(chain, gross_tons=20, pickup_date="2026-08-05")
    set_logical_clock("2026-08-11T00:00:00Z")

    resp = api.dispatch_shipment(shipment["id"], chain["generator_headers"])
    validate_error(resp, ApiErrorId.ERR_REUSE_NOT_ELIGIBLE)

    shipment_after = get_shipment(shipment["id"])
    assert shipment_after["status"] == "BOOKED", "failed dispatch must leave the shipment BOOKED"


def test_expired_determination_visible_on_list_read(api):
    """PRD §2.4: "A reuse-eligibility determination in `APPROVED` or `SUSPENDED`
    status whose `valid_until` date has been reached or passed by the current
    logical date transitions to `EXPIRED`, which is terminal." and "Listing
    endpoints for determinations and permits apply the same lazy reconciliation
    before returning their collections."

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_expired_eligibility
    """
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=100, committed_commitment_tons=100,
        eligibility_valid_until="2026-08-10",
    )
    determination = chain["eligibility"]
    assert determination["status"] == "APPROVED"

    set_logical_clock("2026-08-11T00:00:00Z")

    dets, _ = validate_paginated(
        api.list_eligibility_determinations(chain["stream"]["id"], BROKER)
    )
    expired = next(d for d in dets if d["id"] == determination["id"])
    assert (
        expired["status"] == "EXPIRED"
    ), f"determination must lazily expire once the clock reaches valid_until, got {expired['status']}"


def test_dispatch_reports_safety_error_over_temporal(api):
    """PRD §2.10: "Every request passes through a fixed validation pipeline, and
    an earlier failure masks all later checks." — "Ninth, dispatch safety gates
    (`ERR_REUSE_NOT_ELIGIBLE`, then `ERR_PERMIT_REQUIRED`). Tenth, temporal
    windows (`ERR_OUTSIDE_AGREEMENT_TERM`, `ERR_ELIGIBILITY_WINDOW_OVERLAP`,
    `ERR_ELIGIBILITY_WINDOW_PAST`, `ERR_RESERVATION_WINDOW_INVALID`)."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_suspended_eligibility_and_expired_term_reports_safety_error
    """
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=100, committed_commitment_tons=100,
        term_end="2026-08-05",
    )
    shipment = book_shipment(chain, gross_tons=20, pickup_date="2026-08-04")
    validate_success(api.suspend_eligibility(chain["eligibility"]["id"], CO_FILE), 200)
    set_logical_clock("2026-08-06T00:00:00Z")

    # Both ERR_REUSE_NOT_ELIGIBLE (determination SUSPENDED, safety, ninth) and
    # ERR_OUTSIDE_AGREEMENT_TERM (2026-08-06 past term_end, temporal, tenth)
    # are violated; the earlier pipeline stage wins.
    resp = api.dispatch_shipment(shipment["id"], chain["generator_headers"])
    validate_error(resp, ApiErrorId.ERR_REUSE_NOT_ELIGIBLE)


def test_failed_dispatch_leaves_shipment_booked(api):
    """PRD §3.5: "A cleared dispatch moves the shipment from `BOOKED` to
    `DISPATCHED`." — a dispatch rejected by the safety gates is not cleared and
    must not move the shipment.

    Design: Difficulty/priority_pair_validation_conflict/dispatch_suspended_eligibility_and_expired_term_reports_safety_error
    """
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=100, committed_commitment_tons=100,
        term_end="2026-08-05",
    )
    shipment = book_shipment(chain, gross_tons=20, pickup_date="2026-08-04")
    validate_success(api.suspend_eligibility(chain["eligibility"]["id"], CO_FILE), 200)
    set_logical_clock("2026-08-06T00:00:00Z")

    resp = api.dispatch_shipment(shipment["id"], chain["generator_headers"])
    validate_error(resp, ApiErrorId.ERR_REUSE_NOT_ELIGIBLE)

    shipment_after = get_shipment(shipment["id"])
    assert shipment_after["status"] == "BOOKED", "rejected dispatch must not move the shipment"
