"""Preparing, approving, paying, liening and voiding the cost-recovery bill."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_cost_recovery_invoice,
    city_abate,
    make_program_admin_headers,
    make_property_owner_headers,
    make_supervisor_headers,
    read_order_version,
    set_clock,
    setup_approved_invoice,
    setup_draft_invoice,
    setup_served_order,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]

LOW_SCORES = {
    "harborage_score": 2, "attractant_score": 2,
    "sanitation_score": 1, "burrow_count": 0,
}


def test_stale_order_version_blocks_invoice_preparation(api):
    """PRD §2.6: "If `expected_abatement_order_version` does not equal the
    order's current `version`, the preparation is rejected with
    `ERR_STALE_ORDER_VERSION` and HTTP 412."
    PRD §3.7: "The invoice is created with `billing_status` `DRAFT` and
    `lien_status` `NONE`. Its `prepared_by_user_id` is the preparer's
    `X-User-ID`, its `property_id` is copied from the order and its `owner_id`
    from that parcel."

    Design: Corner/cross_cutting_layers/corner_occ_stale_order_version_blocks_invoice
    """
    env = setup_served_order()
    stale_version = read_order_version(env["order_id"])

    set_clock("2026-05-12T10:00:00Z")
    city_abate(env["order_id"], env["sup_id"], 4, 12000)

    stale = api.create_invoice(
        {"abatement_order_id": env["order_id"],
         "expected_abatement_order_version": stale_version},
        FINANCE,
    )
    assert stale.status_code == 412
    validate_error(stale, ApiErrorId.ERR_STALE_ORDER_VERSION.value)
    rows, meta = validate_paginated(
        api.list_invoices(FINANCE, params={"abatement_order_id": env["order_id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0

    fresh_version = read_order_version(env["order_id"])
    assert fresh_version == stale_version + 1

    accepted = api.create_invoice(
        {"abatement_order_id": env["order_id"],
         "expected_abatement_order_version": fresh_version},
        FINANCE,
    )
    invoice = validate_success(accepted, 201)
    assert_cost_recovery_invoice(invoice)
    assert invoice["billing_status"] == "DRAFT"
    assert invoice["lien_status"] == "NONE"
    assert invoice["estimated_total_cents"] == 107180
    assert invoice["final_total_cents"] is None
    assert invoice["prepared_by_user_id"] == "fin-001"
    assert invoice["owner_id"] == env["owner_id"]


def test_invoice_may_not_be_prepared_for_a_merely_served_order(api):
    """PRD §3.7: "The order must be in `CITY_ABATED`, else
    `ERR_ORDER_NOT_ABATED`; in particular an order that reached `COMPLIED`
    because the owner did the work can never be billed."
    PRD §2.6: "Preparing a cost-recovery invoice requires
    `expected_abatement_order_version` in the body — likewise mandatory —
    carrying the `version` of the target abatement order as the finance officer
    last observed it."

    Design: Difficulty/cross_entity_state_dependency/cost_recovery_invoice_requires_city_abated_order
    """
    env = setup_served_order()
    version = read_order_version(env["order_id"])

    resp = api.create_invoice(
        {"abatement_order_id": env["order_id"],
         "expected_abatement_order_version": version},
        FINANCE,
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ABATED.value)


def test_rejected_invoice_leaves_the_order_and_the_owner_balance_alone(api):
    """PRD §3.7: "The order must be in `CITY_ABATED`, else
    `ERR_ORDER_NOT_ABATED`; in particular an order that reached `COMPLIED`
    because the owner did the work can never be billed."
    PRD §3.7: "`outstanding_balance_cents` is the sum of `balance_due_cents`
    across that owner's invoices whose `billing_status` is `APPROVED` or
    `PARTIALLY_PAID`; invoices in `DRAFT`, `PAID` or `VOID` contribute nothing."

    Design: Difficulty/cross_entity_state_dependency/cost_recovery_invoice_requires_city_abated_order
    """
    env = setup_served_order()
    version = read_order_version(env["order_id"])
    resp = api.create_invoice(
        {"abatement_order_id": env["order_id"],
         "expected_abatement_order_version": version},
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ABATED.value)

    order = validate_success(
        api.get_abatement_order(env["order_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert order["status"] == "SERVED"
    assert order["version"] == version

    rows, meta = validate_paginated(
        api.list_invoices(FINANCE, params={"abatement_order_id": env["order_id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0

    owner = validate_success(api.get_property_owner(env["owner_id"], FINANCE))
    assert owner["outstanding_balance_cents"] == 0


def test_estimate_run_bills_the_tier_standard_allowances(api):
    """PRD §3.7: "The **estimate** run, performed at preparation and stored in
    `estimated_total_cents`, uses the tier-standard allowances keyed on the
    order's `infestation_tier_at_issue`: 2 labour hours and 5000 cents of
    materials for `LOW`, 4 hours and 12000 cents for `MODERATE`, 8 hours and
    25000 cents for `SEVERE`."
    PRD §3.7: "The `estimated_total_cents` is written immediately by the
    estimate run of the costing rule."

    Design: Difficulty/dual_variant_calc/invoice_estimate_vs_final_total
    """
    env = setup_draft_invoice(
        route="ESCALATED", education_advisory=True,
        actual_labor_hours=5.5, actual_materials_cents=18750,
    )
    invoice = validate_success(api.get_invoice(env["inv_id"], FINANCE))
    assert invoice["estimated_total_cents"] == 123257
    assert invoice["billing_status"] == "DRAFT"
    assert invoice["final_total_cents"] is None


def test_final_run_bills_the_recorded_actuals_and_keeps_the_estimate(api):
    """PRD §3.7: "The **final** run, performed at approval and stored in
    `final_total_cents` together with the six line fields, uses the crew's
    recorded `actual_labor_hours` and `actual_materials_cents` instead. The
    estimate is never overwritten by the final run, so both numbers stay
    observable on the same row and will ordinarily differ."
    PRD §3.7: "On success `billing_status` moves `DRAFT → APPROVED`,
    `approved_by_user_id` is set from `X-User-ID`, `final_total_cents` and the
    six line fields are written, `balance_due_cents` is set equal to
    `final_total_cents`, `due_at` is set to the current logical clock plus 30
    days, and the owner's `outstanding_balance_cents` is recomputed to include
    the newly approved balance."

    Design: Difficulty/dual_variant_calc/invoice_estimate_vs_final_total
    """
    env = setup_approved_invoice(
        route="ESCALATED", education_advisory=True,
        actual_labor_hours=5.5, actual_materials_cents=18750,
    )
    invoice = validate_success(api.get_invoice(env["inv_id"], FINANCE))
    assert invoice["final_total_cents"] == 86807
    assert invoice["estimated_total_cents"] == 123257
    assert invoice["estimated_total_cents"] != invoice["final_total_cents"]
    assert invoice["balance_due_cents"] == 86807
    assert invoice["billing_status"] == "APPROVED"

    owner = validate_success(api.get_property_owner(env["owner_id"], FINANCE))
    assert owner["outstanding_balance_cents"] == 86807


def test_labour_line_is_rounded_before_it_enters_the_subtotal(api):
    """PRD §3.7: "The **labour line** is the number of labour hours in play
    multiplied by the crew rate of 8525 cents per hour, rounded half-up to a
    whole number of cents, and stored as `labor_line_cents`."
    PRD §3.7: "The **materials line** is the material figure in play, taken as
    whole cents with no adjustment, and stored as `materials_line_cents`."
    PRD §2.7: "Half-up means a value exactly on the midpoint rounds away from
    zero, so 12.345 becomes 12.35."

    Design: Difficulty/combinatorial_formula/invoice_line_rounding_order_pinned_per_line
    """
    env = setup_approved_invoice(
        route="ESCALATED", education_advisory=True,
        actual_labor_hours=5.5, actual_materials_cents=18750,
    )
    invoice = validate_success(api.get_invoice(env["inv_id"], FINANCE))
    assert invoice["labor_line_cents"] == 46888
    assert invoice["materials_line_cents"] == 18750


def test_every_derived_line_is_rounded_before_the_next_step(api):
    """PRD §3.7: "The **penalty line** is the subtotal multiplied by the order's
    penalty multiplier less 1.00, rounded half-up to whole cents, and stored as
    `penalty_line_cents`."
    PRD §3.7: "The **education credit** is the subtotal multiplied by 0.10,
    rounded half-up to whole cents, when the order's `education_advisory_served`
    is true; when it is false the credit is exactly 0."
    PRD §3.7: "The **administrative fee** is the fee base multiplied by 0.15,
    rounded half-up to whole cents, and stored as `admin_fee_cents`."
    PRD §3.7: "Every line produced in steps 1, 4, 5, 7 and 10 is rounded to
    whole cents *before* it enters any later step; carrying unrounded products
    forward and rounding once at the end produces a different number of cents and
    is wrong."

    Design: Difficulty/combinatorial_formula/invoice_line_rounding_order_pinned_per_line
    """
    env = setup_approved_invoice(
        route="ESCALATED", education_advisory=True,
        actual_labor_hours=5.5, actual_materials_cents=18750,
    )
    invoice = validate_success(api.get_invoice(env["inv_id"], FINANCE))
    assert invoice["penalty_line_cents"] == 16410
    assert invoice["education_credit_cents"] == 6564
    assert invoice["admin_fee_cents"] == 11323
    assert invoice["hardship_discount_cents"] == 0
    assert invoice["final_total_cents"] == 86807, (
        "rounding each line before the next step yields 86807, not 86806"
    )


def test_hardship_tier_is_selected_on_the_pre_discount_total(api):
    """PRD §3.7: "The **hardship rate** is chosen next. When the owner's
    `hardship_certified` is true and the pre-discount total is at least 100000
    cents, the rate is 0.10; when the owner's `hardship_certified` is true and the
    pre-discount total is at least 50000 cents but below 100000, the rate is
    0.05; in every other case — including every case where `hardship_certified`
    is false — the rate is 0.00."
    PRD §3.7: "The **hardship discount** is the *subtotal from step 3*
    multiplied by that rate, rounded half-up to whole cents, and stored as
    `hardship_discount_cents`."
    PRD §3.7: "And the hardship tier is selected on the **pre-discount total of
    step 8**, which already includes the administrative fee, while the discount
    itself is applied to the **subtotal of step 3**; the administrative fee is
    never recomputed after the discount is taken."

    Design: Corner/calculations/corner_hardship_tier_keyed_on_pre_discount_total
    """
    env = setup_approved_invoice(
        route="SERVED", actual_labor_hours=4, actual_materials_cents=12000,
        bootstrap_kwargs={"owner_overrides": {"hardship_certified": True},
                          "inspectors": 2},
    )
    invoice = validate_success(api.get_invoice(env["inv_id"], FINANCE))
    assert invoice["labor_line_cents"] == 34100
    assert invoice["materials_line_cents"] == 12000
    assert invoice["penalty_line_cents"] == 0
    assert invoice["admin_fee_cents"] == 6915
    assert invoice["hardship_discount_cents"] == 2305
    assert invoice["final_total_cents"] == 50710

    owner = validate_success(api.get_property_owner(env["owner_id"], FINANCE))
    assert owner["outstanding_balance_cents"] == 50710


def test_low_tier_order_gets_the_base_window_and_the_low_estimate(api):
    """PRD §3.6: "The window starts at 14 days."
    PRD §3.7: "The **estimate** run, performed at preparation and stored in
    `estimated_total_cents`, uses the tier-standard allowances keyed on the
    order's `infestation_tier_at_issue`: 2 labour hours and 5000 cents of
    materials for `LOW`, 4 hours and 12000 cents for `MODERATE`, 8 hours and
    25000 cents for `SEVERE`."
    PRD §3.4: "From the index follows the `infestation_tier`: `SEVERE` when the
    index is at least 65.00, otherwise `MODERATE` when it is at least 35.00,
    otherwise `LOW`."

    Design: Corner/calculations/corner_low_tier_uses_base_window_and_tier_standard_estimate
    """
    env = setup_approved_invoice(
        route="SERVED", scores=LOW_SCORES, delivery_method="FIRST_CLASS_MAIL",
        service_outcome="REFUSED", actual_labor_hours=1.5,
        actual_materials_cents=4000,
    )
    sup = make_supervisor_headers(env["sup_id"])
    assessments, _meta = validate_paginated(
        api.list_assessments(env["visit_id"], sup)
    )
    assert assessments[0]["infestation_index"] == pytest.approx(17.50, abs=0.001)
    assert assessments[0]["infestation_tier"] == "LOW"

    order = validate_success(api.get_abatement_order(env["order_id"], sup))
    assert order["compliance_deadline"] == "2026-05-19T10:00:00.000Z"
    assert order["served_at"] == "2026-05-05T10:00:00.000Z"
    assert order["status"] == "CITY_ABATED"

    invoice = validate_success(api.get_invoice(env["inv_id"], FINANCE))
    assert invoice["estimated_total_cents"] == 25358
    assert invoice["final_total_cents"] == 19306
    assert invoice["labor_line_cents"] == 12788
    assert invoice["admin_fee_cents"] == 2518


def test_self_approval_outranks_the_approval_ceiling(api):
    """PRD §3.7: "The invoice must be in `DRAFT`, else `ERR_INVALID_STATE`, and
    the approver's `X-User-ID` must differ from `prepared_by_user_id`, else
    `ERR_SELF_APPROVAL_FORBIDDEN`."
    PRD §2.5: "Requests are screened by a fixed fourteen-step ladder, and the
    **first** step that fails determines the response."

    Design: Difficulty/priority_pair_validation_conflict/self_approval_outranks_approval_limit
    """
    env = setup_draft_invoice(
        route="ESCALATED", actual_labor_hours=60, actual_materials_cents=200000,
    )
    resp = api.approve_invoice(
        env["inv_id"], {}, make_program_admin_headers("fin-001")
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN.value)

    invoice = validate_success(api.get_invoice(env["inv_id"], FINANCE))
    assert invoice["billing_status"] == "DRAFT"


def test_approval_ceiling_surfaces_once_a_different_admin_approves(api):
    """PRD §3.7: "The final run of the costing rule is then evaluated: if the
    resulting `final_total_cents` exceeds 500000 cents and `escalated_approval`
    was not sent as true, the approval is refused with
    `ERR_APPROVAL_LIMIT_EXCEEDED`; a total exactly equal to 500000 needs no
    escalation."
    PRD §3.7: "On success `billing_status` moves `DRAFT → APPROVED`,
    `approved_by_user_id` is set from `X-User-ID`, `final_total_cents` and the
    six line fields are written, `balance_due_cents` is set equal to
    `final_total_cents`, `due_at` is set to the current logical clock plus 30
    days, and the owner's `outstanding_balance_cents` is recomputed to include
    the newly approved balance."

    Design: Difficulty/priority_pair_validation_conflict/self_approval_outranks_approval_limit
    """
    env = setup_draft_invoice(
        route="ESCALATED", actual_labor_hours=60, actual_materials_cents=200000,
    )
    over_limit = api.approve_invoice(env["inv_id"], {}, ADMIN)
    assert over_limit.status_code == 422
    validate_error(over_limit, ApiErrorId.ERR_APPROVAL_LIMIT_EXCEEDED.value)
    still_draft = validate_success(api.get_invoice(env["inv_id"], FINANCE))
    assert still_draft["billing_status"] == "DRAFT"

    escalated = validate_success(
        api.approve_invoice(env["inv_id"], {"escalated_approval": True}, ADMIN)
    )
    assert escalated["final_total_cents"] == 1022781
    assert escalated["billing_status"] == "APPROVED"
    assert escalated["approved_by_user_id"] == "admin-001"


def test_payment_and_lien_guard_rails(api):
    """PRD §3.7: "Payments are only accepted while `billing_status` is `APPROVED`
    or `PARTIALLY_PAID`; a `DRAFT`, `PAID` or `VOID` invoice rejects them with
    `ERR_INVOICE_NOT_APPROVED`."
    PRD §3.7: "Only one live invoice may exist per order: if a non-`VOID` invoice
    already exists for that order, preparation is refused with
    `ERR_INVOICE_ALREADY_EXISTS`."
    PRD §3.7: "Two thresholds must both be met: `balance_due_cents` must be at
    least 25000 cents, and the current logical clock must be at or past `due_at`
    plus 60 days. A balance below 25000, or a clock strictly earlier than that
    60-day mark, is refused with `ERR_LIEN_THRESHOLD_NOT_MET`."
    PRD §3.7: "An amount greater than `balance_due_cents` is refused with
    `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Corner/validations/corner_invoice_payment_and_lien_guard_rails
    """
    env = setup_draft_invoice(
        route="SERVED", actual_labor_hours=4, actual_materials_cents=12000
    )
    order_version = read_order_version(env["order_id"])

    on_draft = api.create_payment(
        env["inv_id"], {"amount_cents": 1000, "method": "CHECK"}, FINANCE
    )
    assert on_draft.status_code == 409
    validate_error(on_draft, ApiErrorId.ERR_INVOICE_NOT_APPROVED.value)

    duplicate = api.create_invoice(
        {"abatement_order_id": env["order_id"],
         "expected_abatement_order_version": order_version},
        FINANCE,
    )
    assert duplicate.status_code == 409
    validate_error(duplicate, ApiErrorId.ERR_INVOICE_ALREADY_EXISTS.value)

    approved = validate_success(api.approve_invoice(env["inv_id"], {}, ADMIN))
    assert approved["balance_due_cents"] == 53015
    assert approved["due_at"] == "2026-06-11T10:00:00.000Z"

    early_lien = api.file_lien(env["inv_id"], FINANCE)
    assert early_lien.status_code == 422
    validate_error(early_lien, ApiErrorId.ERR_LIEN_THRESHOLD_NOT_MET.value)
    assert validate_success(api.get_invoice(env["inv_id"], FINANCE))["lien_status"] == "NONE"

    overpayment = api.create_payment(
        env["inv_id"], {"amount_cents": 53016, "method": "CHECK"}, FINANCE
    )
    assert overpayment.status_code == 422
    validate_error(overpayment, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)
    assert validate_success(api.get_invoice(env["inv_id"], FINANCE))["amount_paid_cents"] == 0

    settled = validate_success(
        api.create_payment(
            env["inv_id"], {"amount_cents": 53015, "method": "CHECK"}, FINANCE
        )
    )
    assert settled["billing_status"] == "PAID"
    assert settled["balance_due_cents"] == 0

    owner = validate_success(api.get_property_owner(env["owner_id"], FINANCE))
    assert owner["outstanding_balance_cents"] == 0
    order = validate_success(
        api.get_abatement_order(env["order_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert order["status"] == "CLOSED"
    complaint = validate_success(api.get_complaint(env["comp_id"], CLERK))
    assert complaint["status"] == "CLOSED_RESOLVED"


def test_lien_may_be_filed_while_the_invoice_is_partially_paid(api):
    """PRD §3.7: "A payment strictly smaller than the outstanding balance adds
    its amount to `amount_paid_cents`, subtracts it from `balance_due_cents`,
    reduces the owner's `outstanding_balance_cents` by the same amount and raises
    the owner's `lifetime_paid_cents` by it."
    PRD §3.7: "The lien axis evolves independently of the billing axis: an
    invoice may be `APPROVED` with a lien `FILED`, or `PARTIALLY_PAID` with a
    lien `FILED`, and `lien_status` moves `FILED → RELEASED` exactly when the
    billing axis reaches `PAID` or `VOID`."
    PRD §3.7: "Filing moves `lien_status` `NONE → FILED`, stamps
    `lien_filed_at`, sets the parcel's `lien_encumbered` to true and increments
    the parcel's `version` by one."

    Design: Difficulty/non_linear_state_machine/invoice_billing_and_lien_axes_evolve_independently
    """
    env = setup_approved_invoice(
        route="ESCALATED", education_advisory=True,
        actual_labor_hours=5.5, actual_materials_cents=18750,
    )
    partial = validate_success(
        api.create_payment(
            env["inv_id"], {"amount_cents": 20000, "method": "CHECK"}, FINANCE
        )
    )
    assert partial["billing_status"] == "PARTIALLY_PAID"
    assert partial["balance_due_cents"] == 66807
    assert partial["lien_status"] == "NONE"

    set_clock("2026-08-10T11:00:00Z")
    liened = validate_success(api.file_lien(env["inv_id"], FINANCE))
    assert liened["lien_status"] == "FILED"
    assert liened["billing_status"] == "PARTIALLY_PAID"

    prop = validate_success(
        api.get_property(env["prop_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert prop["lien_encumbered"] is True


def test_settling_payment_moves_both_axes_at_once(api):
    """PRD §3.7: "First, `amount_paid_cents` rises by the amount,
    `balance_due_cents` becomes 0, `paid_at` is stamped from the logical clock,
    `billing_status` becomes `PAID` — reached from either `APPROVED` or
    `PARTIALLY_PAID` — the owner's `outstanding_balance_cents` is reduced by the
    cleared amount and their `lifetime_paid_cents` raised by it, and if the
    invoice's `lien_status` was `FILED` it moves to `RELEASED` with the parcel's
    `lien_encumbered` recomputed."
    PRD §3.7: "On release, the parcel's `lien_encumbered` is set back to false
    only if no other invoice on that parcel still holds a `FILED` lien."

    Design: Difficulty/non_linear_state_machine/invoice_billing_and_lien_axes_evolve_independently
    """
    env = setup_approved_invoice(
        route="ESCALATED", education_advisory=True,
        actual_labor_hours=5.5, actual_materials_cents=18750,
    )
    validate_success(
        api.create_payment(
            env["inv_id"], {"amount_cents": 20000, "method": "CHECK"}, FINANCE
        )
    )
    set_clock("2026-08-10T11:00:00Z")
    validate_success(api.file_lien(env["inv_id"], FINANCE))

    settled = validate_success(
        api.create_payment(
            env["inv_id"], {"amount_cents": 66807, "method": "ACH"},
            make_property_owner_headers(env["owner_id"]),
        )
    )
    assert settled["billing_status"] == "PAID"
    assert settled["lien_status"] == "RELEASED"
    assert settled["amount_paid_cents"] == 86807
    assert settled["balance_due_cents"] == 0

    prop = validate_success(
        api.get_property(env["prop_id"], make_supervisor_headers(env["sup_id"]))
    )
    assert prop["lien_encumbered"] is False


def test_settling_payment_closes_the_order_and_the_complaint(api):
    """PRD §3.7: "Second, the linked abatement order moves `CITY_ABATED →
    CLOSED`, stamping the order's `closed_at`, dropping the parcel's
    `open_order_count` by one and incrementing the parcel's `version` by one.
    Third, the complaint that originated the order moves `ABATEMENT_ORDERED →
    CLOSED_RESOLVED` with `closure_reason` `RESOLVED` and `closed_at` stamped."
    PRD §3.7: "A payment exactly equal to the outstanding balance settles the
    invoice and opens a four-hop cascade."

    Design: Difficulty/transitive_cascade/payment_settlement_chain_invoice_order_complaint_zone
    """
    env = setup_approved_invoice(
        route="ESCALATED", education_advisory=True,
        actual_labor_hours=5.5, actual_materials_cents=18750,
    )
    settled = validate_success(
        api.create_payment(
            env["inv_id"], {"amount_cents": 86807, "method": "ACH"}, FINANCE
        )
    )
    assert settled["billing_status"] == "PAID"
    assert settled["balance_due_cents"] == 0
    assert settled["paid_at"] == "2026-05-12T11:00:00.000Z"

    sup = make_supervisor_headers(env["sup_id"])
    order = validate_success(api.get_abatement_order(env["order_id"], sup))
    assert order["status"] == "CLOSED"
    assert order["closed_at"] == "2026-05-12T11:00:00.000Z"

    complaint = validate_success(api.get_complaint(env["comp_id"], CLERK))
    assert complaint["status"] == "CLOSED_RESOLVED"
    assert complaint["closure_reason"] == "RESOLVED"

    prop = validate_success(api.get_property(env["prop_id"], sup))
    assert prop["open_order_count"] == 0


def test_settlement_cascade_reaches_the_zone_and_the_owner_aggregates(api):
    """PRD §3.7: "Fourth, the zone's `open_complaint_count` falls by one and its
    `rodent_index` and `posture` are recomputed."
    PRD §3.7: "`lifetime_paid_cents` is the sum of `amount_paid_cents` across
    that owner's invoices whose `billing_status` is `APPROVED`,
    `PARTIALLY_PAID` or `PAID`."

    Design: Difficulty/transitive_cascade/payment_settlement_chain_invoice_order_complaint_zone
    """
    env = setup_approved_invoice(
        route="ESCALATED", education_advisory=True,
        actual_labor_hours=5.5, actual_materials_cents=18750,
    )
    validate_success(
        api.create_payment(
            env["inv_id"], {"amount_cents": 86807, "method": "ACH"}, FINANCE
        )
    )

    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["open_complaint_count"] == 0
    assert zone["rodent_index"] == pytest.approx(0.00, abs=0.001)
    assert zone["posture"] == "NORMAL"

    owner = validate_success(api.get_property_owner(env["owner_id"], FINANCE))
    assert owner["outstanding_balance_cents"] == 0
    assert owner["lifetime_paid_cents"] == 86807


def test_approval_then_void_restores_the_owner_balance_exactly(api):
    """PRD §3.7: "From `APPROVED`, the owner's `outstanding_balance_cents` is
    reduced by exactly the `balance_due_cents` that is being cancelled, which
    restores the owner's balance to precisely the figure it held before the
    approval — the invariant the void exists to guarantee — and if the
    `lien_status` was `FILED` it moves to `RELEASED` with the parcel's
    `lien_encumbered` recomputed."
    PRD §3.7: "From `PARTIALLY_PAID`, the owner's `outstanding_balance_cents` is
    likewise reduced by the cancelled `balance_due_cents`, while
    `amount_paid_cents` is retained on the invoice: money already collected is
    not unwound, and the owner's `lifetime_paid_cents` is unaffected by the void."

    Design: Difficulty/compensating_invariant/owner_balance_conserved_on_invoice_void
    """
    env = setup_draft_invoice(
        route="SERVED", actual_labor_hours=4, actual_materials_cents=12000
    )
    before = validate_success(api.get_property_owner(env["owner_id"], FINANCE))
    assert before["outstanding_balance_cents"] == 0

    approved = validate_success(api.approve_invoice(env["inv_id"], {}, ADMIN))
    assert approved["final_total_cents"] == 53015
    assert approved["penalty_line_cents"] == 0
    assert approved["balance_due_cents"] == 53015
    mid = validate_success(api.get_property_owner(env["owner_id"], FINANCE))
    assert mid["outstanding_balance_cents"] == 53015

    validate_success(
        api.void_invoice(
            env["inv_id"],
            {"void_reason": "Owner produced proof of prior abatement"},
            FINANCE,
        )
    )
    after = validate_success(api.get_property_owner(env["owner_id"], FINANCE))
    assert after["outstanding_balance_cents"] == 0
    assert after["lifetime_paid_cents"] == 0


def test_void_zeroes_the_balance_and_leaves_the_order_city_abated(api):
    """PRD §3.7: "Voiding always stamps `voided_at` from the logical clock and
    sets `balance_due_cents` to 0, and the accounting consequence depends on
    where the invoice was."
    PRD §3.7: "In every case the linked abatement order stays in `CITY_ABATED`,
    deliberately, so that a corrected replacement invoice can be prepared against
    it."
    PRD §3.7: "The **estimate** run, performed at preparation and stored in
    `estimated_total_cents`, uses the tier-standard allowances keyed on the
    order's `infestation_tier_at_issue`: 2 labour hours and 5000 cents of
    materials for `LOW`, 4 hours and 12000 cents for `MODERATE`, 8 hours and
    25000 cents for `SEVERE`."

    Design: Difficulty/compensating_invariant/owner_balance_conserved_on_invoice_void
    """
    env = setup_draft_invoice(
        route="SERVED", actual_labor_hours=4, actual_materials_cents=12000
    )
    sup = make_supervisor_headers(env["sup_id"])
    order = validate_success(api.get_abatement_order(env["order_id"], sup))
    assert order["status"] == "CITY_ABATED"
    assert order["escalation_level"] == 0

    invoice = validate_success(api.get_invoice(env["inv_id"], FINANCE))
    assert invoice["estimated_total_cents"] == 107180

    validate_success(api.approve_invoice(env["inv_id"], {}, ADMIN))
    voided = validate_success(
        api.void_invoice(
            env["inv_id"],
            {"void_reason": "Owner produced proof of prior abatement"},
            FINANCE,
        )
    )
    assert voided["billing_status"] == "VOID"
    assert voided["balance_due_cents"] == 0

    order_after = validate_success(api.get_abatement_order(env["order_id"], sup))
    assert order_after["status"] == "CITY_ABATED"
