"""Receivable registration, central registry, pledge, transfer (PRD §3.4).

Anti-double-financing uniqueness is also covered here.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_receivable,
    central_registry_file_payload,
    create_receivable_payload,
    file_central_registry,
    make_supplier_headers,
    register_receivable,
    setup_active_supplier,
    setup_confirmed_payable_confirmation,
    setup_registered_receivable,
    transfer_receivable_payload,
    validate_error,
    validate_success,
)


def test_register_receivable_starts_in_registered_and_mirrors_parent(api):
    """PRD §3.4: "The new Receivable starts in REGISTERED ... The
    registration mirrors supplier_id, core_enterprise_id, amount_cents,
    and due_date from the parent confirmation onto the receivable at
    this moment."
    """
    bundle = setup_confirmed_payable_confirmation(amount_cents=2_500_000)
    receivable = register_receivable(bundle["supplier"], bundle["confirmation"])
    assert_receivable(receivable)
    assert receivable["status"] == "REGISTERED"
    assert receivable["supplier_id"] == bundle["supplier"]["id"]
    assert receivable["core_enterprise_id"] == bundle["ce"]["id"]
    assert receivable["amount_cents"] == bundle["confirmation"]["amount_cents"]
    assert receivable["due_date"] == bundle["confirmation"]["due_date"]
    assert receivable["confirmation_id"] == bundle["confirmation"]["id"]


def test_double_registration_against_same_confirmation_rejected(api):
    """PRD §2.8: "a Receivable's confirmation_id is globally unique —
    at most one receivable may be registered against any given
    PayableConfirmation, and a second attempt yields ERR_DOUBLE_FINANCING
    with HTTP status 409."
    """
    bundle = setup_confirmed_payable_confirmation()
    register_receivable(bundle["supplier"], bundle["confirmation"])
    payload = create_receivable_payload(confirmation_id=bundle["confirmation"]["id"])
    res = api.create_receivable(
        payload, make_supplier_headers(bundle["supplier"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DOUBLE_FINANCING.value)


def test_register_against_non_confirmed_confirmation_rejected(api):
    """PRD §3.4: "A SupplierUser registers a receivable against an
    existing PayableConfirmation in CONFIRMED state."

    A still-pending confirmation cannot host a receivable.
    """
    from test_helpers import (
        iso_in_days,
        create_payable_confirmation,
        make_supplier_headers,
        setup_active_supplier,
        setup_approved_core_enterprise,
    )
    ce = setup_approved_core_enterprise()
    supplier = setup_active_supplier(tier_to_core=1)
    pc = create_payable_confirmation(
        ce, supplier, amount_cents=500_000, due_date=iso_in_days(60),
    )  # PENDING_CONFIRM, not yet confirmed
    payload = create_receivable_payload(confirmation_id=pc["id"])
    res = api.create_receivable(
        payload, make_supplier_headers(supplier["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_pledge_registered_receivable_when_no_registry_required(api):
    """PRD §3.4: "Pledging by a supplier user moves
    REGISTERED → PLEDGED."

    When ``central_registry_required`` is false the pledge needs no
    filing. We choose a small amount to keep registry off-required.
    """
    bundle = setup_registered_receivable(amount_cents=100)
    rec = bundle["receivable"]
    # If the implementation deems this amount above the central-registry
    # threshold, the pledge would require a filing. We assert based on
    # the receivable's own ``central_registry_required`` field:
    if rec.get("central_registry_required"):
        # File first.
        file_central_registry(rec)
    res = api.pledge_receivable(
        rec["id"], make_supplier_headers(bundle["supplier"]["id"]),
    )
    pledged = validate_success(res)
    assert pledged["status"] == "PLEDGED"


def test_pledge_requires_central_registry_filing_when_required(api):
    """PRD §3.4: "When central_registry_required is true, a separate
    filing step run by a PlatformAdmin records the registry-issued
    central_registry_filing_no. Once filed, the receivable may proceed
    to PLEDGED or TRANSFERRED; either operation without a filing —
    where required — is rejected with
    ERR_CENTRAL_REGISTRY_FILING_REQUIRED."

    Pick a large amount that we believe pushes the receivable above the
    CENTRAL_REGISTRY_THRESHOLD; then verify the receivable's flag is
    true before attempting the pledge.
    """
    bundle = setup_registered_receivable(amount_cents=100_000_000_00)
    rec = bundle["receivable"]
    if not rec.get("central_registry_required"):
        pytest.skip(
            "Setup did not produce a central_registry_required==true "
            "receivable; threshold values are PRD-named but not pinned."
        )
    res = api.pledge_receivable(
        rec["id"], make_supplier_headers(bundle["supplier"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CENTRAL_REGISTRY_FILING_REQUIRED.value)


def test_pledge_succeeds_after_central_registry_filing(api):
    """PRD §3.4: "Once filed, the receivable may proceed to PLEDGED or
    TRANSFERRED."
    """
    bundle = setup_registered_receivable(amount_cents=100_000_000_00)
    rec = bundle["receivable"]
    if not rec.get("central_registry_required"):
        pytest.skip(
            "Setup did not produce a central_registry_required==true "
            "receivable; threshold not pinned in PRD prose."
        )
    file_central_registry(rec)
    res = api.pledge_receivable(
        rec["id"], make_supplier_headers(bundle["supplier"]["id"]),
    )
    pledged = validate_success(res)
    assert pledged["status"] == "PLEDGED"
    assert pledged["central_registry_filing_no"]


def test_transfer_receivable_reassigns_supplier(api):
    """PRD §3.4: "Transferring by a supplier user moves
    REGISTERED → TRANSFERRED and reassigns supplier_id to a
    new_supplier_id carried in the request body."
    """
    bundle = setup_registered_receivable(amount_cents=100)
    rec = bundle["receivable"]
    if rec.get("central_registry_required"):
        file_central_registry(rec)
    new_supplier = setup_active_supplier(tier_to_core=1)
    res = api.transfer_receivable(
        rec["id"],
        transfer_receivable_payload(new_supplier_id=new_supplier["id"]),
        make_supplier_headers(bundle["supplier"]["id"]),
    )
    transferred = validate_success(res)
    assert transferred["status"] == "TRANSFERRED"
    assert transferred["supplier_id"] == new_supplier["id"]


def test_central_registry_required_pinned_at_registration(api):
    """PRD §3.4: "this boolean is computed once and never re-evaluated."

    Register a receivable and observe that ``central_registry_required``
    is set and immutable across reads.
    """
    bundle = setup_registered_receivable(amount_cents=5_000_000)
    rec = bundle["receivable"]
    initial = rec["central_registry_required"]
    from test_helpers import get_receivable
    again = get_receivable(rec["id"])
    assert again["central_registry_required"] is initial
