"""Cross-cutting claims: optimistic concurrency on the offering version, derived
paid-field reconciliation, and immediate read-after-write consistency
(PRD 2.5, 2.6, 2.8, 3.5, 3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_payment,
    confirm_enrollment,
    confirm_enrollment_raw,
    drop_enrollment,
    first_invoice_for_enrollment,
    get_enrollment,
    get_invoice,
    get_offering,
    get_offering_version,
    list_invoices_for_enrollment,
    pay_invoice,
    register_and_confirm,
    register_student,
    set_clock,
    setup_base,
    validate_error,
    validate_success,
    withdraw_enrollment,
    make_registrar_headers,
)

REGISTRAR = make_registrar_headers()


def test_occ_confirm_stale_version_rejected(api):
    """PRD 2.8: "The enrollment-confirm operation and the enrollment-reinstate
    operation each require the request body to carry `expected_offering_version`,
    holding the `version` of the offering as the client last observed it."
    PRD 2.8: "If another writer has advanced the offering's `version` since that
    read — because a seat was consumed or released by an intervening confirm, drop,
    withdraw, reinstate, or waitlist promotion — the client's view of
    `seats_available` is stale, and the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_confirm_stale_version_rejected
    """
    ctx = setup_base(capacity=2)
    pair1 = register_student(ctx, full_name="Alpha One", grade_level=11)
    pair2 = register_student(ctx, full_name="Beta Two", grade_level=12)

    stale_version = get_offering_version(ctx["offering"]["id"])
    confirm_enrollment(ctx["offering"]["id"], pair1["enrollment"]["id"])

    response = confirm_enrollment_raw(
        ctx["offering"]["id"], pair2["enrollment"]["id"], expected_version=stale_version
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    fresh_version = get_offering_version(ctx["offering"]["id"])
    retried = confirm_enrollment_raw(
        ctx["offering"]["id"], pair2["enrollment"]["id"], expected_version=fresh_version
    )
    assert validate_success(retried)["status"] == "REGISTERED", (
        "Retrying with the re-read version succeeds — capacity 2 leaves a seat"
    )
    assert get_offering(ctx["offering"]["id"])["seats_taken"] == 2


def test_occ_reinstate_stale_version_rejected(api):
    """PRD 2.8: "The enrollment-confirm operation and the enrollment-reinstate
    operation each require the request body to carry `expected_offering_version`,
    holding the `version` of the offering as the client last observed it."
    PRD 2.8: "If another writer has advanced the offering's `version` since that
    read — because a seat was consumed or released by an intervening confirm, drop,
    withdraw, reinstate, or waitlist promotion — the client's view of
    `seats_available` is stale, and the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_reinstate_stale_version_rejected
    """
    ctx = setup_base(capacity=2)
    pair1 = register_and_confirm(ctx, full_name="Alpha One", grade_level=11)
    pair2 = register_and_confirm(ctx, full_name="Beta Two", grade_level=12)

    # e1 withdraws inside the withdraw window.
    set_clock("2026-09-12T00:00:00Z")
    withdraw_enrollment(pair1["enrollment"]["id"])
    stale_version = get_offering_version(ctx["offering"]["id"])
    # An intervening drop (drop window re-opened at 08-20) advances the version.
    set_clock("2026-08-20T00:00:00Z")
    drop_enrollment(pair2["enrollment"]["id"])

    set_clock("2026-09-20T00:00:00Z")
    response = api.reinstate_enrollment(
        pair1["enrollment"]["id"],
        {"expected_offering_version": stale_version},
        REGISTRAR,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    fresh_version = get_offering_version(ctx["offering"]["id"])
    retried = api.reinstate_enrollment(
        pair1["enrollment"]["id"],
        {"expected_offering_version": fresh_version},
        REGISTRAR,
    )
    assert validate_success(retried)["status"] == "REGISTERED", (
        "After re-reading the version the reinstate succeeds — capacity 2 with "
        "only e2 dropped out leaves a free seat"
    )
    assert get_offering(ctx["offering"]["id"])["seats_taken"] == 1


def test_derived_invoice_paid_fields_reconcile(api):
    """PRD 3.7: "A successful payment adds `amount_cents` to the corresponding paid
    bucket and increments the invoice's `version`."
    PRD 3.7: "When the cumulative paid total across all three buckets is greater
    than 0 but less than `tuition_total_cents`, the invoice's `status` moves to
    `PARTIALLY_PAID`; when the cumulative total equals `tuition_total_cents`, it
    moves to `PAID`."
    PRD 2.6: "Three resources are deliberately lighter-weight and carry only `id`
    and `created_at`, with no `updated_at` and no `version`: `Prerequisite`,
    `PlacementRecord`, and `Payment`."

    Design: Corner/cross_cutting_layers/derived_invoice_paid_fields_reconcile
    """
    ctx = setup_base()
    pair = register_and_confirm(ctx)
    invoice = first_invoice_for_enrollment(pair["enrollment"]["id"])
    assert invoice["tuition_total_cents"] == 120000

    payment1 = pay_invoice(invoice["id"], "STATE", 40000)
    assert_payment(payment1)
    assert payment1["invoice_id"] == invoice["id"]
    assert payment1["payer"] == "STATE"
    assert payment1["amount_cents"] == 40000

    pay_invoice(invoice["id"], "FAMILY", 30000)
    mid = get_invoice(invoice["id"])
    assert mid["status"] == "PARTIALLY_PAID", (
        f"70000 of 120000 paid must read PARTIALLY_PAID, got {mid['status']}"
    )
    assert mid["paid_state_cents"] == 40000
    assert mid["paid_family_cents"] == 30000
    assert mid["paid_district_cents"] == 0

    pay_invoice(invoice["id"], "STATE", 50000)
    end = get_invoice(invoice["id"])
    assert end["status"] == "PAID", (
        f"Exact payoff (120000 == tuition_total_cents) must flip to PAID, got "
        f"{end['status']}"
    )
    assert end["paid_state_cents"] == 90000


def test_immediate_consistency_confirm_visible(api):
    """PRD 3.5: "If every check passes and at least one seat is free, the enrollment
    moves to `REGISTERED`: `seats_taken` increases by 1, the offering's `version`
    increments, and an `Invoice` is created per §3.7 with `status` `ISSUED` and
    `refund_status` `NONE`."
    PRD 2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    PRD 2.6: "`version`, an integer that increments by 1 on every mutation."

    Design: Corner/consistency_model/immediate_consistency_confirm_visible
    """
    ctx = setup_base(capacity=2)
    pair = register_student(ctx)
    version_before = get_offering_version(ctx["offering"]["id"])

    confirmed = confirm_enrollment(ctx["offering"]["id"], pair["enrollment"]["id"])
    assert confirmed["status"] == "REGISTERED", (
        "The mutation is visible in the confirm response itself"
    )

    offering_after = get_offering(ctx["offering"]["id"])
    assert offering_after["seats_taken"] == 1
    assert offering_after["version"] == version_before + 1, (
        f"The seat counter and the OCC version move together: expected version "
        f"{version_before + 1}, got {offering_after['version']}"
    )

    invoices = list_invoices_for_enrollment(pair["enrollment"]["id"])
    assert len(invoices) == 1, "The new invoice is visible to the very next read"
    assert invoices[0]["tuition_total_cents"] == 120000
    assert invoices[0]["status"] == "ISSUED"
    assert invoices[0]["refund_status"] == "NONE"
