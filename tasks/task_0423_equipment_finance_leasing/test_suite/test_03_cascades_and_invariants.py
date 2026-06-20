"""Cascades and conserved-quantity invariants: add-on apply depth-3, book
depth-2 credit cascade, credit conservation, schedule-line conservation.

Difficulty queue: transitive_cascade, compensating_invariant, boundary_precision
(addon empty-remaining boundary).
Corner queue: entities (lessee credit on mint), cross_cutting (portfolio value).
"""
import pytest
from test_helpers import (
    validate_success,
    get_success_data,
    assert_credit_envelope_conserved,
    create_lessor,
    create_approved_vendor,
    create_approved_lessee,
    create_lease,
    attach_equipment,
    setup_active_lease,
    setup_end_of_term_lease,
    bill_line,
    list_scheduled_lines,
    elect,
    exercise,
    create_addon_payload,
    TEST_USERS,
)

OFFICER = TEST_USERS["funding_officer_headers"]
SERVICER = TEST_USERS["servicer_headers"]


# ─── transitive_cascade / addon_apply_depth3_cascade ──────────────────
def test_addon_apply_cascades_through_financed_and_lessee_credit(api):
    """PRD §3.10: "The incremental monthly rent, `incremental_payment_cents`, is the
    added cost multiplied by the lease's `monthly_rate_factor_bps`, divided by
    10,000, rounded half up — but only when there is at least one remaining
    `SCHEDULED` schedule line to spread it over".
    PRD §3.10: "Application triggers a three-deep cascade. The `base_rent_cents` of
    every remaining `SCHEDULED` schedule line is increased by the incremental
    payment; the lease's `financed_amount_cents` is increased by `added_cost_cents`;
    and that in turn recomputes the lessee's committed and available credit and the
    lessor's portfolio value per Section 2.5."

    ACTIVE FMV lease (cost 500000, term 12, rate 2000, financed 500000), lessee
    approved 2000000. Applying an ADD_ON of added_cost 200000 yields incremental
    40000, financed 700000, committed 700000, available 1300000.

    Design: Difficulty/transitive_cascade/addon_apply_depth3_cascade
    """
    ctx = setup_active_lease(
        equipment_cost_cents=500_000, term_months=12, monthly_rate_factor_bps=2000,
        approved_amount_cents=2_000_000, serial_number="SN-500")
    lessor_id, lease_id, lessee_id = ctx["lessor_id"], ctx["lease"]["id"], ctx["lessee_id"]
    addon = get_success_data(api.create_addon(
        lessor_id, lease_id,
        create_addon_payload("ADD_ON", 200_000, "SN-501"), SERVICER))
    applied = get_success_data(api.apply_addon(lessor_id, lease_id, addon["id"], SERVICER))
    assert applied["incremental_payment_cents"] == 40_000, f"got {applied['incremental_payment_cents']}"
    lease = get_success_data(api.get_lease(lessor_id, lease_id, OFFICER))
    assert lease["financed_amount_cents"] == 700_000, f"got {lease['financed_amount_cents']}"
    lessee = get_success_data(api.get_lessee(lessor_id, lessee_id, OFFICER))
    assert lessee["committed_credit_cents"] == 700_000, f"got {lessee['committed_credit_cents']}"
    assert lessee["available_credit_cents"] == 1_300_000, f"got {lessee['available_credit_cents']}"


def test_addon_apply_bumps_remaining_scheduled_line_base_rent(api):
    """PRD §3.10: "Application triggers a three-deep cascade. The `base_rent_cents`
    of every remaining `SCHEDULED` schedule line is increased by the incremental
    payment".
    PRD §3.10: "The incremental monthly rent, `incremental_payment_cents`, is the
    added cost multiplied by the lease's `monthly_rate_factor_bps`, divided by
    10,000, rounded half up".

    The first cascade link: applying an ADD_ON (incremental 40000) on an ACTIVE
    FMV lease (base rent 100000) raises each remaining SCHEDULED line's
    base_rent_cents from 100000 to 140000.

    Design: Difficulty/transitive_cascade/addon_apply_depth3_cascade
    """
    ctx = setup_active_lease(
        equipment_cost_cents=500_000, term_months=12, monthly_rate_factor_bps=2000,
        approved_amount_cents=2_000_000, serial_number="SN-510")
    lessor_id, lease_id = ctx["lessor_id"], ctx["lease"]["id"]
    before = list_scheduled_lines(lessor_id, lease_id)
    assert before[0]["base_rent_cents"] == 100_000
    addon = get_success_data(api.create_addon(
        lessor_id, lease_id,
        create_addon_payload("ADD_ON", 200_000, "SN-511"), SERVICER))
    get_success_data(api.apply_addon(lessor_id, lease_id, addon["id"], SERVICER))
    after = list_scheduled_lines(lessor_id, lease_id)
    assert all(line["base_rent_cents"] == 140_000 for line in after), (
        f"remaining SCHEDULED lines should be bumped to 140000, "
        f"got {[l['base_rent_cents'] for l in after]}"
    )


# ─── transitive_cascade / lease_book_depth2_credit_cascade ────────────
def test_book_cascades_financed_into_lessee_credit(api):
    """PRD §3.4: "Next, `financed_amount_cents`, the credit exposure, is the
    equipment cost minus the product of `advance_payment_count` and the
    just-computed monthly payment, minus the security deposit".
    PRD §3.3: "`committed_credit_cents`, the sum of `financed_amount_cents` across
    this lessee's leases".
    PRD §3.3: "`available_credit_cents`, equal to `approved_credit_cents` minus
    `committed_credit_cents`".

    Booking an FMV lease (cost 500000, no advance/deposit) under a lessee approved
    for 1000000 sets financed 500000, committed 500000, available 500000.

    Design: Difficulty/transitive_cascade/lease_book_depth2_credit_cascade
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "SN-600", original_cost_cents=500_000)
    booked = get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER))
    assert booked["financed_amount_cents"] == 500_000, f"got {booked['financed_amount_cents']}"
    lessee = get_success_data(api.get_lessee(lessor_id, lessee_id, OFFICER))
    assert lessee["committed_credit_cents"] == 500_000, f"got {lessee['committed_credit_cents']}"
    assert lessee["available_credit_cents"] == 500_000, f"got {lessee['available_credit_cents']}"


def test_book_with_advance_and_deposit_reduces_financed_then_cascades(api):
    """PRD §3.4: "Next, `financed_amount_cents`, the credit exposure, is the
    equipment cost minus the product of `advance_payment_count` and the
    just-computed monthly payment, minus the security deposit".
    PRD §3.3: "`committed_credit_cents`, the sum of `financed_amount_cents` across
    this lessee's leases".

    The depth-2 cascade with non-zero advance/deposit: cost 500000, rate 2000
    (monthly_payment 100000), advance 1, deposit 50000 -> financed = 500000 -
    1*100000 - 50000 = 350000, which cascades to committed_credit 350000.

    Design: Difficulty/transitive_cascade/lease_book_depth2_credit_cascade
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000, advance_payment_count=1,
                         security_deposit_cents=50_000)
    attach_equipment(lessor_id, lease["id"], "SN-601", original_cost_cents=500_000)
    booked = get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER))
    assert booked["financed_amount_cents"] == 350_000, f"got {booked['financed_amount_cents']}"
    lessee = get_success_data(api.get_lessee(lessor_id, lessee_id, OFFICER))
    assert lessee["committed_credit_cents"] == 350_000, f"got {lessee['committed_credit_cents']}"


# ─── boundary_precision / addon_incremental_zero_on_empty_remaining ───
def test_addon_incremental_zero_when_no_scheduled_lines_remain(api):
    """PRD §3.10: "when no `SCHEDULED` installments remain, the incremental payment
    is zero because there is nothing left to charge it against."

    An ACTIVE FMV term-1 lease whose single installment has been INVOICED (0
    SCHEDULED remaining): applying an ADD_ON of added_cost 200000 yields
    incremental_payment_cents == 0 (not the raw 40000), and the add-on is APPLIED.

    Design: Difficulty/boundary_precision_check/addon_incremental_zero_on_empty_remaining_schedule
    """
    ctx = setup_active_lease(
        equipment_cost_cents=500_000, term_months=1, monthly_rate_factor_bps=2000,
        approved_amount_cents=2_000_000, serial_number="SN-800")
    lessor_id, lease_id = ctx["lessor_id"], ctx["lease"]["id"]
    lines = list_scheduled_lines(lessor_id, lease_id)
    bill_line(lessor_id, lease_id, lines[0]["id"])  # INVOICED, leaves 0 SCHEDULED
    addon = get_success_data(api.create_addon(
        lessor_id, lease_id,
        create_addon_payload("ADD_ON", 200_000, "SN-801"), SERVICER))
    applied = get_success_data(api.apply_addon(lessor_id, lease_id, addon["id"], SERVICER))
    assert applied["incremental_payment_cents"] == 0, f"got {applied['incremental_payment_cents']}"
    assert applied["status"] == "APPLIED", f"got {applied['status']}"


def test_addon_incremental_nonzero_when_scheduled_lines_remain(api):
    """PRD §3.10: "The incremental monthly rent, `incremental_payment_cents`, is the
    added cost multiplied by the lease's `monthly_rate_factor_bps`, divided by
    10,000, rounded half up — but only when there is at least one remaining
    `SCHEDULED` schedule line to spread it over".

    Boundary partner: when SCHEDULED installments DO remain (term-12 lease, none
    billed), applying an ADD_ON of added_cost 200000 at rate 2000 yields the raw
    incremental 40000, not the empty-set zero.

    Design: Difficulty/boundary_precision_check/addon_incremental_zero_on_empty_remaining_schedule
    """
    ctx = setup_active_lease(
        equipment_cost_cents=500_000, term_months=12, monthly_rate_factor_bps=2000,
        approved_amount_cents=2_000_000, serial_number="SN-810")
    lessor_id, lease_id = ctx["lessor_id"], ctx["lease"]["id"]
    addon = get_success_data(api.create_addon(
        lessor_id, lease_id,
        create_addon_payload("ADD_ON", 200_000, "SN-811"), SERVICER))
    applied = get_success_data(api.apply_addon(lessor_id, lease_id, addon["id"], SERVICER))
    assert applied["incremental_payment_cents"] == 40_000, f"got {applied['incremental_payment_cents']}"


# ─── compensating_invariant / credit_conservation_book_then_terminate ─
def test_credit_returns_to_full_after_book_then_terminate(api):
    """PRD §3.3: "`available_credit_cents`, equal to `approved_credit_cents` minus
    `committed_credit_cents`".
    PRD §3.11: "Termination records the security-deposit refund obligation, then
    runs the credit and portfolio cascades of Section 2.5 as the lease drops out of
    the committed-credit set and out of the active portfolio."

    A full lifecycle (book commits 500000, terminate releases it) returns the
    lessee to committed 0 and available 1000000, conserving the credit envelope.

    Design: Difficulty/compensating_invariant/credit_conservation_book_then_terminate
    """
    ctx = setup_end_of_term_lease(
        equipment_cost_cents=500_000, term_months=1, monthly_rate_factor_bps=2000,
        approved_amount_cents=1_000_000, serial_number="SN-1200")
    lessor_id, lease_id, lessee_id = ctx["lessor_id"], ctx["lease"]["id"], ctx["lessee_id"]
    election = elect(lessor_id, lease_id, "BUYOUT")
    exercise(lessor_id, lease_id, election["id"],
             buyout_payment_cents=election["quoted_amount_cents"])
    get_success_data(api.terminate_lease(lessor_id, lease_id, SERVICER))
    lessee = get_success_data(api.get_lessee(lessor_id, lessee_id, OFFICER))
    assert lessee["committed_credit_cents"] == 0, f"got {lessee['committed_credit_cents']}"
    assert lessee["available_credit_cents"] == 1_000_000, f"got {lessee['available_credit_cents']}"
    assert_credit_envelope_conserved(lessee)


def test_credit_envelope_conserved_after_book_before_terminate(api):
    """PRD §3.3: "`committed_credit_cents`, the sum of `financed_amount_cents`
    across this lessee's leases in lifecycle `ORIGINATION`, `BOOKED`, `ACTIVE`, or
    `END_OF_TERM`; and `available_credit_cents`, equal to `approved_credit_cents`
    minus `committed_credit_cents`".

    The conserved quantity holds at the committed mid-point too: after booking a
    500000-financed lease under a 1000000 lessee, committed 500000 + available
    500000 == approved 1000000 — zero drift before the terminate release.

    Design: Difficulty/compensating_invariant/credit_conservation_book_then_terminate
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=1,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "SN-1201", original_cost_cents=500_000)
    get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER))
    lessee = get_success_data(api.get_lessee(lessor_id, lessee_id, OFFICER))
    assert lessee["committed_credit_cents"] == 500_000, f"got {lessee['committed_credit_cents']}"
    assert lessee["available_credit_cents"] == 500_000, f"got {lessee['available_credit_cents']}"
    assert_credit_envelope_conserved(lessee)


# ─── compensating_invariant / schedule_line_count_conservation ────────
def test_invoice_then_void_conserves_scheduled_line_count(api):
    """PRD §3.9: "Voiding moves the invoice to `VOID` and cascades the linked
    schedule line's status back to `SCHEDULED`, making it billable again."
    PRD §3.4: "exactly `term_months` **Schedule Line** rows are created".

    An ACTIVE FMV term-2 lease has 2 SCHEDULED lines. Billing one (SCHEDULED ->
    INVOICED) then voiding the invoice (INVOICED -> SCHEDULED) restores exactly 2
    SCHEDULED lines — no line lost or duplicated.

    Design: Difficulty/compensating_invariant/schedule_line_count_conservation_invoice_then_void
    """
    ctx = setup_active_lease(
        equipment_cost_cents=500_000, term_months=2, monthly_rate_factor_bps=2000,
        serial_number="SN-1300")
    lessor_id, lease_id = ctx["lessor_id"], ctx["lease"]["id"]
    lines = list_scheduled_lines(lessor_id, lease_id)
    assert len(lines) == 2
    line0 = lines[0]
    inv = bill_line(lessor_id, lease_id, line0["id"])
    voided = get_success_data(api.void_invoice(lessor_id, inv["id"], SERVICER))
    assert voided["status"] == "VOID", f"got {voided['status']}"
    line0_after = get_success_data(api.get_schedule_line(lessor_id, line0["id"], SERVICER))
    assert line0_after["status"] == "SCHEDULED", f"got {line0_after['status']}"
    scheduled_after = list_scheduled_lines(lessor_id, lease_id)
    assert len(scheduled_after) == 2, f"expected 2 SCHEDULED lines, got {len(scheduled_after)}"


def test_voided_schedule_line_is_billable_again(api):
    """PRD §3.9: "Voiding moves the invoice to `VOID` and cascades the linked
    schedule line's status back to `SCHEDULED`, making it billable again."

    Conservation is observable through re-billability: after voiding the invoice on
    a line, re-billing that same line succeeds (status returns to billable) — the
    schedule line was not consumed or lost by the void.

    Design: Difficulty/compensating_invariant/schedule_line_count_conservation_invoice_then_void
    """
    ctx = setup_active_lease(
        equipment_cost_cents=500_000, term_months=2, monthly_rate_factor_bps=2000,
        serial_number="SN-1301")
    lessor_id, lease_id = ctx["lessor_id"], ctx["lease"]["id"]
    line0 = list_scheduled_lines(lessor_id, lease_id)[0]
    inv = bill_line(lessor_id, lease_id, line0["id"])
    get_success_data(api.void_invoice(lessor_id, inv["id"], SERVICER))
    # Re-billing the freed line succeeds (201), proving it was returned to the
    # billable SCHEDULED set rather than lost.
    rebill = api.create_invoice(lessor_id, lease_id, {"schedule_line_id": line0["id"]}, SERVICER)
    rebilled = validate_success(rebill, 201)
    assert rebilled["schedule_line_id"] == line0["id"], f"got {rebilled['schedule_line_id']}"


# ─── Corner: entities / lessee_computed_available_credit_on_mint ──────
def test_minted_lessee_has_full_available_credit(api):
    """PRD §3.3: "its `approved_credit_cents` is copied from the application's
    `approved_amount_cents` at mint time".
    PRD §3.3: "Both begin effectively at zero committed and full availability".

    A freshly minted Lessee (approval 1000000) has committed 0, available 1000000,
    approved 1000000, with no leases yet.

    Design: Corner/entities/lessee_computed_available_credit_on_mint
    """
    lessor_id = create_lessor()["id"]
    lessee = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)
    assert lessee["committed_credit_cents"] == 0, f"got {lessee['committed_credit_cents']}"
    assert lessee["available_credit_cents"] == 1_000_000, f"got {lessee['available_credit_cents']}"
    assert lessee["approved_credit_cents"] == 1_000_000, f"got {lessee['approved_credit_cents']}"


# ─── Corner: cross_cutting / portfolio_value_derived_field_after_book ─
def test_portfolio_value_reflects_booked_unit_cost(api):
    """PRD §2.5: "A lessor's `portfolio_value_cents` is the sum of
    `original_cost_cents` over every equipment unit whose owning lease is in
    `BOOKED`, `ACTIVE`, or `END_OF_TERM`; it is recomputed whenever a unit is
    added, a lease's lifecycle changes, or a unit's disposition changes its
    membership in that set."

    After booking a lease with one 500000-cost unit, the lessor's
    portfolio_value_cents == 500000.

    Design: Corner/cross_cutting/portfolio_value_derived_field_after_book
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "YY-SN-1", original_cost_cents=500_000)
    get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER))
    lessor = get_success_data(api.get_lessor(lessor_id, OFFICER))
    assert lessor["portfolio_value_cents"] == 500_000, f"got {lessor['portfolio_value_cents']}"
