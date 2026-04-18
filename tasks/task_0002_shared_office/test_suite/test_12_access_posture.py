"""Access posture tests — the tenant gate.

Covers PRD §2.10 (posture derivation) and §3.3 / §3.4 (posture-gated operations:
reservation confirm requires OPEN; visitor check-in blocked only on FROZEN).
"""

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    create_and_confirm_reservation,
    create_reservation,
    create_resource,
    get_tenant,
    make_tenant_member_headers,
    setup_tenant_at_outstanding_balance,
    setup_tenant_member_badge,
    validate_error,
    validate_success,
)


def test_access_posture_open_by_default(api, admin_headers):
    """PRD §3.1: "The new tenant is created with `status` of `ACTIVE`,
    `access_posture` of `OPEN`, and `outstanding_balance_cents` of 0."

    Claim: a freshly created Tenant has access_posture=OPEN.
    """
    from test_helpers import create_tenant
    tenant = create_tenant()
    assert tenant["access_posture"] == "OPEN"


def test_confirm_requires_open_posture(api, admin_headers):
    """PRD §2.10: "The gates are operation-specific. Confirming a reservation
    requires `access_posture` equal to `OPEN`; a tenant in `RESTRICTED` or `FROZEN`
    cannot confirm new reservations and the confirmation is rejected with
    `ERR_ACCESS_POSTURE_DENIES`."

    Claim: with tenant in RESTRICTED (via outstanding balance >= credit limit),
    POST /reservations/{id}/confirm → ERR_ACCESS_POSTURE_DENIES (422).
    """
    # Build tenant with a low credit limit and drive it into RESTRICTED.
    tenant, member, _resource, _bill = setup_tenant_at_outstanding_balance(
        target_balance_cents=100, credit_limit_cents=50, base_date="2026-11-01",
    )
    t = get_tenant(tenant["id"])
    assert t["access_posture"] == "RESTRICTED", (
        "Setup invariant: after issuing a bill whose total exceeds credit_limit_cents, "
        "posture must flip to RESTRICTED per PRD §2.10."
    )
    # Now create a NEW pending reservation on a new resource and attempt confirm.
    new_resource = create_resource(kind="WORKSTATION", code="WS-POST-1", hourly_rate_cents=500)
    advance_clock_to("2026-11-10T08:00:00.000Z")
    pending = create_reservation(
        tenant, member, new_resource,
        "2026-11-10T09:00:00.000Z", "2026-11-10T10:00:00.000Z",
    )
    headers = make_tenant_member_headers(member["id"])
    res = api.confirm_reservation(pending["id"], headers)
    validate_error(res, "ERR_ACCESS_POSTURE_DENIES", expected_status=422)


def test_outstanding_balance_reaches_credit_limit_flips_to_restricted(api, admin_headers):
    """PRD §2.10: "if `outstanding_balance_cents` is greater than or equal to
    `credit_limit_cents`, posture is `RESTRICTED`."
    PRD §3.7: "If the new outstanding balance is greater than or equal to the
    tenant's `credit_limit_cents`, the tenant's `access_posture` flips from `OPEN`
    to `RESTRICTED` per the evaluation ladder."

    Claim: outstanding_balance_cents >= credit_limit_cents ⇒ access_posture =
    RESTRICTED.
    """
    tenant, _member, _resource, _bill = setup_tenant_at_outstanding_balance(
        target_balance_cents=100, credit_limit_cents=50, base_date="2026-11-12",
    )
    t = get_tenant(tenant["id"])
    assert t["access_posture"] == "RESTRICTED"
    assert t["outstanding_balance_cents"] >= t["credit_limit_cents"]
