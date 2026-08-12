"""Invoices: creation gates, pricing with the local-purchase incentive,
lifecycle guards, and the revision loop."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_invoice,
    check_in_delivery,
    create_accepted_delivery,
    create_approved_invoice,
    create_invoice,
    create_verified_offering,
    make_farm_manager_headers,
    schedule_delivery,
    setup_procurement_chain,
    sign_agreement,
    create_agreement,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_admin_headers

ADMIN = TEST_USERS["admin_headers"]


def _chain_with_draft_invoice(committed=200, qty=40, number="INV-1"):
    chain = setup_procurement_chain(committed_quantity=committed)
    delivery = create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", qty,
    )
    invoice = validate_success(
        create_invoice(delivery["id"], chain.farm["id"], number), 201
    )
    return chain, delivery, invoice


def test_invoice_requires_accepted_delivery_checked_in(api):
    """PRD section 3.6: "Once a delivery has been accepted, the grower's
    `FarmManager` invoices it by supplying the `delivery_id` and an
    `invoice_number`. The delivery must stand in `ACCEPTED`
    (`ERR_DELIVERY_NOT_ACCEPTED`)"

    Design: Difficulty/cross_entity_state_dependency/invoice_requires_accepted_delivery
    """
    chain = setup_procurement_chain()
    delivery = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 40,
        ),
        201,
    )
    # CHECKED_IN is received at the dock but not yet accepted.
    check_in_delivery(delivery["id"], chain.kitchen["id"])
    resp = create_invoice(delivery["id"], chain.farm["id"], "INV-X")
    validate_error(resp, ApiErrorId.ERR_DELIVERY_NOT_ACCEPTED)


def test_invoice_requires_accepted_delivery_scheduled(api):
    """PRD section 3.6: "Once a delivery has been accepted, the grower's
    `FarmManager` invoices it by supplying the `delivery_id` and an
    `invoice_number`. The delivery must stand in `ACCEPTED`
    (`ERR_DELIVERY_NOT_ACCEPTED`)"

    Design: Difficulty/cross_entity_state_dependency/invoice_requires_accepted_delivery
    """
    chain = setup_procurement_chain()
    delivery = validate_success(
        schedule_delivery(
            chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
            chain.farm["id"], "2026-08-10", 40,
        ),
        201,
    )
    assert delivery["status"] == "SCHEDULED"
    resp = create_invoice(delivery["id"], chain.farm["id"], "INV-X")
    validate_error(resp, ApiErrorId.ERR_DELIVERY_NOT_ACCEPTED)


def test_invoice_revision_cycle_loop(api):
    """PRD section 3.6: "Rejection is not the end: the farm may revise,
    returning `REJECTED` → `DRAFT` (`ERR_INVOICE_NOT_REVISABLE` from any other
    state) for correction and resubmission."

    Design: Corner/state_machines/sm_invoice_revision_cycle_loop
    """
    chain, _delivery, invoice = _chain_with_draft_invoice()
    farm_headers = make_farm_manager_headers(chain.farm["id"])

    submitted = validate_success(api.submit_invoice(invoice["id"], farm_headers), 200)
    assert submitted["status"] == "SUBMITTED"
    rejected = validate_success(
        api.reject_invoice(invoice["id"], {"reason": "missing signature"}, ADMIN), 200
    )
    assert rejected["status"] == "REJECTED"
    revised = validate_success(api.revise_invoice(invoice["id"], farm_headers), 200)
    assert revised["status"] == "DRAFT"
    resubmitted = validate_success(api.submit_invoice(invoice["id"], farm_headers), 200)
    assert resubmitted["status"] == "SUBMITTED", (
        "the revision loop admits a second submission"
    )


def test_paid_invoice_terminal_lockdown(api):
    """PRD section 3.6: "Two terminal states exist — `PAID` and `VOIDED`"
    PRD section 3.6: "the farm's `FarmManager` submits it (`DRAFT` →
    `SUBMITTED`), which requires a `DRAFT` invoice (`ERR_INVOICE_NOT_SUBMITTABLE`)"

    Design: Corner/state_machines/sm_paid_invoice_terminal_lockdown
    """
    chain, _delivery, invoice = _chain_with_draft_invoice()
    farm_headers = make_farm_manager_headers(chain.farm["id"])
    validate_success(api.submit_invoice(invoice["id"], farm_headers), 200)
    validate_success(api.approve_invoice(invoice["id"], ADMIN), 200)
    paid = validate_success(api.pay_invoice(invoice["id"], ADMIN), 200)
    assert paid["status"] == "PAID"

    resp = api.submit_invoice(invoice["id"], farm_headers)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_SUBMITTABLE)
    after = validate_success(api.get_invoice(invoice["id"], ADMIN), 200)
    assert after["status"] == "PAID"


def test_invoice_state_family_errors(api):
    """PRD section 3.6: "A `DistrictProgramAdmin` adjudicates submissions:
    approval moves `SUBMITTED` → `APPROVED` and captures the approver's
    identity in `approved_by_user_id`, while rejection — which carries a
    mandatory `reason` — moves the invoice to `REJECTED`; both require a
    `SUBMITTED` invoice (`ERR_INVOICE_NOT_APPROVABLE`)."
    PRD section 3.6: "Rejection is not the end: the farm may revise, returning
    `REJECTED` → `DRAFT` (`ERR_INVOICE_NOT_REVISABLE` from any other state)
    for correction and resubmission."
    PRD section 3.6: "Payment moves `APPROVED` → `PAID`
    (`ERR_INVOICE_NOT_PAYABLE` otherwise) and stamps `paid_at` with the current
    logical clock timestamp."

    Design: Corner/state_machines/sm_invoice_state_family_errors
    """
    chain, _delivery, invoice = _chain_with_draft_invoice()
    iid = invoice["id"]
    farm_headers = make_farm_manager_headers(chain.farm["id"])

    # Approve and revise both require a state the DRAFT invoice is not in.
    validate_error(api.approve_invoice(iid, ADMIN), ApiErrorId.ERR_INVOICE_NOT_APPROVABLE)
    validate_error(api.revise_invoice(iid, farm_headers), ApiErrorId.ERR_INVOICE_NOT_REVISABLE)

    # Pay requires APPROVED; SUBMITTED is not enough.
    validate_success(api.submit_invoice(iid, farm_headers), 200)
    validate_error(api.pay_invoice(iid, ADMIN), ApiErrorId.ERR_INVOICE_NOT_PAYABLE)

    # Approve is single-shot.
    validate_success(api.approve_invoice(iid, ADMIN), 200)
    validate_error(api.approve_invoice(iid, ADMIN), ApiErrorId.ERR_INVOICE_NOT_APPROVABLE)

    # Pay is single-shot.
    validate_success(api.pay_invoice(iid, ADMIN), 200)
    validate_error(api.pay_invoice(iid, ADMIN), ApiErrorId.ERR_INVOICE_NOT_PAYABLE)


def test_invoice_uniqueness_pair(api):
    """PRD section 3.6: "it may carry at most one invoice
    (`ERR_INVOICE_EXISTS_FOR_DELIVERY`), and the invoice number must be unique
    among this farm's invoices (`ERR_DUPLICATE_INVOICE_NUMBER`)."

    Design: Corner/validations/val_invoice_uniqueness_pair
    """
    chain = setup_procurement_chain()
    del1 = create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-10", 40,
    )
    del2 = create_accepted_delivery(
        chain.agreement["id"], chain.kitchen["id"], chain.window["id"],
        chain.farm["id"], "2026-08-17", 40,
    )
    validate_success(create_invoice(del1["id"], chain.farm["id"], "INV-1"), 201)

    # A second invoice on the same delivery.
    resp = create_invoice(del1["id"], chain.farm["id"], "INV-2")
    validate_error(resp, ApiErrorId.ERR_INVOICE_EXISTS_FOR_DELIVERY)

    # The same invoice number on a different delivery of the same farm.
    resp = create_invoice(del2["id"], chain.farm["id"], "INV-1")
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVOICE_NUMBER)


def _setup_incentive_tier_chain():
    """Farm with an APPROVED invoice of subtotal 999900 (YTD local), plus a
    second signed agreement with an ACCEPTED delivery of subtotal 200."""
    chain = setup_procurement_chain(with_agreement=False)
    farm_id = chain.farm["id"]

    off_a = create_verified_offering(
        farm_id, chain.year["id"], chain.product["id"], price_cents_per_unit=9999
    )
    agr_a = validate_success(
        create_agreement(chain.year["id"], off_a["id"], committed_quantity=100), 201
    )
    sign_agreement(agr_a["id"], farm_id)
    del_a = create_accepted_delivery(
        agr_a["id"], chain.kitchen["id"], chain.window["id"], farm_id,
        "2026-08-10", 100,
    )
    inv_a = create_approved_invoice(del_a["id"], farm_id, "INV-YTD")

    off_b = create_verified_offering(
        farm_id, chain.year["id"], chain.product["id"], price_cents_per_unit=200
    )
    agr_b = validate_success(
        create_agreement(chain.year["id"], off_b["id"], committed_quantity=1), 201
    )
    sign_agreement(agr_b["id"], farm_id)
    del_b = create_accepted_delivery(
        agr_b["id"], chain.kitchen["id"], chain.window["id"], farm_id,
        "2026-08-17", 1,
    )
    return chain, inv_a, del_b


def test_incentive_tier_excludes_current_invoice(api):
    """PRD section 3.6: "Second, the incentive tier is read from the farm's
    year-to-date local invoicing: the sum of `subtotal_cents` over this farm's
    invoices in `APPROVED` or `PAID` status for the same program year whose
    agreements are local-eligible, excluding the invoice being created. While
    that year-to-date figure is below 1,000,000 cents the rate is two percent"
    PRD section 3.6: "Because the tier is read excluding the current invoice,
    an invoice that itself crosses a threshold does not change its own rate."

    Design: Difficulty/combinatorial_formula/incentive_tier_excludes_current_invoice_mode_c
    """
    _chain, inv_a, del_b = _setup_incentive_tier_chain()
    assert inv_a["subtotal_cents"] == 999900  # farm YTD local subtotal

    invoice = validate_success(create_invoice(del_b["id"], _chain.farm["id"], "INV-NEW"), 201)
    assert_invoice(invoice)
    assert invoice["subtotal_cents"] == 200
    # YTD 999900 + 200 crosses the 1,000,000 tier boundary, but the rate is
    # read excluding this invoice: two percent of 200 is 4, not 6.
    assert invoice["incentive_credit_cents"] == 4, (
        f"expected 4 cents at the 2% tier, got {invoice['incentive_credit_cents']}"
    )
    assert invoice["total_cents"] == 204


def test_incentive_tier_baseline_invoice_also_two_percent(api):
    """PRD section 3.6: "Third, `incentive_credit_cents` is the subtotal
    multiplied by that rate, rounded half-up to a whole cent, when the
    agreement is local-eligible — and zero otherwise. Fourth, `total_cents` is
    the subtotal plus the incentive credit."

    Design: Difficulty/combinatorial_formula/incentive_tier_excludes_current_invoice_mode_c
    """
    _chain, inv_a, del_b = _setup_incentive_tier_chain()
    # The baseline invoice was created with an empty YTD: 2% of 999900.
    assert inv_a["subtotal_cents"] == 999900
    assert inv_a["incentive_credit_cents"] == 19998
    assert inv_a["total_cents"] == 1019898

    # The follow-up invoice is priced at the same 2% tier because the tier is
    # read excluding it, even though its own subtotal crosses the boundary.
    invoice = validate_success(create_invoice(del_b["id"], _chain.farm["id"], "INV-NEW"), 201)
    assert invoice["incentive_credit_cents"] == 4
    assert invoice["total_cents"] == 204
