"""Cascade behavior, audit-log emissions, and version-counter tests
(PRD §2.7, §2.8, §3.4, §3.5, §3.9)."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    LIBRARIAN_HEADERS,
    advance_clock_days,
    api_client,
    assert_audit_log,
    assert_version_increased,
    create_active_loan,
    create_loan_then_return_late,
    create_loan_with_pending_reservation,
    make_reader_headers,
    pay_fine_full,
    return_loan_payload,
    run_sweep,
    setup_ready_for_pickup_reservation,
    validate_paginated,
    validate_success,
)


# =============================================================================
# Version-counter cascade (PRD §2.4, §2.7)
# =============================================================================


def test_loan_return_increments_loan_version(api):
    """PRD §2.4: "an integer version counter that begins at 1 and increments
    by 1 on every persisted mutation."

    Claim: returning a loan increments the Loan's version counter.
    """
    ctx = create_active_loan()
    before = ctx["loan"]["version"]
    returned = validate_success(
        api.return_loan(
            ctx["loan"]["id"], return_loan_payload(),
            make_reader_headers(ctx["reader"]["id"]),
        ),
        200,
    )
    assert_version_increased(returned, before)


def test_return_cascade_increments_reservation_version(api):
    """PRD §2.7: "Every entity touched by a cascade has its own updated_at
    refreshed and its version incremented, so a reader who observed
    Reservation.version = 3 and Copy.version = 7 before a return event will
    observe both values incremented after the return has been processed."

    Claim: the cascade from a loan-return promotion bumps the Reservation's
    version counter.
    """
    ctx = create_loan_with_pending_reservation()
    res_before_v = ctx["reservation"]["version"]
    validate_success(
        api.return_loan(
            ctx["loan"]["id"], return_loan_payload(),
            make_reader_headers(ctx["reader_a"]["id"]),
        ),
        200,
    )
    promoted = validate_success(
        api.get_reservation(
            ctx["reservation"]["id"], make_reader_headers(ctx["reader_b"]["id"])
        ),
        200,
    )
    assert_version_increased(promoted, res_before_v)


# =============================================================================
# Audit-log emissions (PRD §2.8)
# =============================================================================


def test_audit_log_loan_created(api, admin_headers):
    """PRD §2.8: "The event_type values are exactly LOAN_CREATED, LOAN_RENEWED,
    LOAN_RECALLED, LOAN_RETURNED, FINE_ACCRUED, FINE_WAIVED, FINE_PAID,
    RESERVATION_CREATED, and RESERVATION_FULFILLED."

    Claim: a borrow generates a LOAN_CREATED audit entry referencing the loan.
    """
    ctx = create_active_loan()
    data, meta = validate_paginated(
        api.list_audit_logs(
            admin_headers,
            params={"event_type": "LOAN_CREATED", "limit": 100},
        )
    )
    matching = [e for e in data if e["subject_id"] == ctx["loan"]["id"]]
    assert len(matching) >= 1, "PRD §2.8: LOAN_CREATED entry must exist for the new loan"
    assert_audit_log(matching[0])
    assert matching[0]["subject_type"] == "Loan"


def test_audit_log_loan_returned(api, admin_headers):
    """PRD §2.8 / §3.4: "Append AuditLog with event_type LOAN_RETURNED" on the
    return path.

    Claim: a return produces a LOAN_RETURNED audit entry referencing the loan.
    """
    ctx = create_active_loan()
    validate_success(
        api.return_loan(
            ctx["loan"]["id"], return_loan_payload(),
            make_reader_headers(ctx["reader"]["id"]),
        ),
        200,
    )
    data, _ = validate_paginated(
        api.list_audit_logs(
            admin_headers,
            params={"event_type": "LOAN_RETURNED", "limit": 100},
        )
    )
    matching = [e for e in data if e["subject_id"] == ctx["loan"]["id"]]
    assert len(matching) >= 1


def test_audit_log_only_admin(api, librarian_headers):
    """PRD §4 endpoint table: GET /library/audit-logs — Authorized Role(s):
    Admin. Combined with PRD §2.1: "If both headers are present but the role
    is not authorized for the requested endpoint, the request is rejected
    with ERR_FORBIDDEN (HTTP 403)."

    Claim: a Librarian reading /library/audit-logs gets ERR_FORBIDDEN.
    """
    from test_helpers import validate_error

    res = api.list_audit_logs(librarian_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_audit_log_append_only_no_version(api, admin_headers):
    """PRD §2.4: "AuditLog rows carry only id and created_at; they have no
    updated_at and no version."

    Claim: AuditLog entries omit updated_at and version fields.
    """
    ctx = create_active_loan()
    data, _ = validate_paginated(
        api.list_audit_logs(
            admin_headers,
            params={"event_type": "LOAN_CREATED", "limit": 100},
        )
    )
    matching = [e for e in data if e["subject_id"] == ctx["loan"]["id"]]
    assert matching
    entry = matching[0]
    assert "updated_at" not in entry, (
        "PRD §2.4: AuditLog rows have no updated_at"
    )
    assert "version" not in entry, "PRD §2.4: AuditLog rows have no version"


# =============================================================================
# Sweep (PRD §3.9)
# =============================================================================


def test_sweep_expires_ready_for_pickup_past_hold(api):
    """PRD §3.5: "the operational sweep is responsible for expiring stale
    holds: any reservation whose hold_expires_at is at or before the
    simulated now() is moved to the terminal EXPIRED state".

    Claim: after advancing past the 2-day hold and running sweep, a
    READY_FOR_PICKUP reservation transitions to EXPIRED.
    """
    ctx = setup_ready_for_pickup_reservation()
    advance_clock_days(3)
    run_sweep()
    res = validate_success(
        api.get_reservation(
            ctx["reservation"]["id"], make_reader_headers(ctx["reader_b"]["id"])
        ),
        200,
    )
    assert res["status"] == "EXPIRED"


def test_sweep_expires_card_past_valid_until(api):
    """PRD §3.2: "Cards whose valid_until is at or before the simulated now()
    are swept to the terminal EXPIRED state by the sweep capability".

    Claim: a card with valid_until in the (now-)past, after sweep, has
    status=EXPIRED.
    """
    from test_helpers import create_verified_reader, issue_card

    reader = create_verified_reader()
    # Issue with a short validity window: valid_from to valid_until.
    card = issue_card(
        reader["id"],
        card_type="REGULAR",
        valid_from="2020-01-01T00:00:00.000Z",
        valid_until="2020-01-15T00:00:00.000Z",  # in the past
    )
    run_sweep()
    # The card should be EXPIRED now. We probe by trying to freeze it.
    res = api.freeze_card(card["id"], None, LIBRARIAN_HEADERS)
    # PRD §3.2: freezing requires Card.status == ACTIVE. An EXPIRED card
    # rejects with ERR_INVALID_STATE.
    assert res.status_code == 409
    body = res.json()
    assert body["data"]["error_id"] == "ERR_INVALID_STATE"
