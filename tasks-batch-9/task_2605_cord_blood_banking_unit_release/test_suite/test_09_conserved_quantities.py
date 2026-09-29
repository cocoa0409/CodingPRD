"""Quantities a do-and-undo pair must leave exactly where it found them."""

import pytest

from test_helpers import (
    api_client,
    assert_balance_equals_unpaid_residual,
    build_billed_private_scenario,
    build_listed_public_scenario,
    cancel_reservation,
    confirm_reservation,
    make_billing_admin_headers,
    make_facilities_engineer_headers,
    nightly_run,
    pay_invoice,
    place_reservation,
    read_account,
    read_invoice,
    read_listing,
    read_reservation,
    read_tank,
    read_unit,
    set_clock,
    validate_success,
)


def _confirmable_hold_on_a_stored_unit():
    """One listed public unit in a five-slot tank, carrying one pending hold."""
    scenario = build_listed_public_scenario(
        tank_code="TANK-M",
        capacity_slots=5,
        primary_parent_name="Invariant Parent",
        collection_site_code="SITE-15",
        consent_document_hash="hash-iv-v1",
        kit_lot_code="LOT-2026-I",
        courier_tracking_code="TRK-1500",
        slot_code="M-01",
        hla_a="A*02:01",
        hla_b="B*08:01",
        hla_drb1="DRB1*03:01",
    )
    set_clock("2026-08-11T03:00:00Z")
    scenario["reservation"] = place_reservation(
        scenario["unit"]["id"],
        center_user_id="tc-001",
        requesting_center_name="Center Invariant",
        patient_weight_kg=35.0,
        patient_hla_match_count=6,
        hold_from="2026-09-01T00:00:00Z",
        hold_until="2026-09-05T00:00:00Z",
    )
    return scenario


class TestTankOccupancyConservedAcrossConfirmThenCancel:
    def test_occupancy_reads_one_at_all_three_observation_points(self):
        """Neither the confirm nor the cancel touches cryogenic capacity.

        "The tank's `occupied_slots` is provably identical before and after, since the unit
        never left its slot."

        Design: Difficulty/compensating_invariant/tank_occupied_slots_conserved_across_confirm_then_cancel
        """
        scenario = _confirmable_hold_on_a_stored_unit()
        tank_id = scenario["tank"]["id"]
        slots_before = read_tank(tank_id)["occupied_slots"]
        assert slots_before == 1

        confirm_reservation(
            scenario["reservation"]["id"],
            intended_transplant_date="2026-09-03",
            center_user_id="tc-001",
        )
        assert read_tank(tank_id)["occupied_slots"] == 1

        cancel_reservation(
            scenario["reservation"]["id"], reason_code="PATIENT_DECEASED", center_user_id="tc-001"
        )
        assert read_tank(tank_id)["occupied_slots"] == slots_before

    def test_the_confirm_reserves_the_unit_and_matches_the_listing(self):
        """The forward operation is what the compensation will have to undo.

        "the unit moves `LISTED → RESERVED` or `PRIVATE_STORED → RESERVED`, the unit's registry
        listing in `ACTIVE` moves to `MATCHED`"

        Design: Difficulty/compensating_invariant/tank_occupied_slots_conserved_across_confirm_then_cancel
        """
        scenario = _confirmable_hold_on_a_stored_unit()

        confirm_reservation(
            scenario["reservation"]["id"],
            intended_transplant_date="2026-09-03",
            center_user_id="tc-001",
        )

        assert read_unit(scenario["unit"]["id"])["availability_status"] == "RESERVED"
        assert read_listing(scenario["listing"]["id"])["listing_status"] == "MATCHED"

    def test_the_cancel_restores_a_public_unit_to_listed_and_its_listing_to_active(self):
        """A public donation unit returns to the registry, not to private storage.

        "the hold moves `CONFIRMED → CANCELLED`, the unit returns from `RESERVED` to `LISTED` if
        its `program_type` is `PUBLIC_DONATION` or to `PRIVATE_STORED` if it is
        `PRIVATE_FAMILY`, and the unit's `MATCHED` listing returns to `ACTIVE`."

        Design: Difficulty/compensating_invariant/tank_occupied_slots_conserved_across_confirm_then_cancel
        """
        scenario = _confirmable_hold_on_a_stored_unit()
        confirm_reservation(
            scenario["reservation"]["id"],
            intended_transplant_date="2026-09-03",
            center_user_id="tc-001",
        )

        cancelled = cancel_reservation(
            scenario["reservation"]["id"], reason_code="PATIENT_DECEASED", center_user_id="tc-001"
        )

        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason_code"] == "PATIENT_DECEASED"
        assert cancelled["released_at"] is None

        assert read_unit(scenario["unit"]["id"])["availability_status"] == "LISTED"
        listing = read_listing(scenario["listing"]["id"])
        assert listing["listing_status"] == "ACTIVE"
        assert listing["suspension_reason_code"] is None

    def test_the_unit_never_vacates_its_physical_slot(self):
        """The compensation restores exactly the state the forward act destroyed and no more.

        "Cancelling a confirmed hold returns the unit and its listing to exactly their
        pre-confirmation values."

        Design: Difficulty/compensating_invariant/tank_occupied_slots_conserved_across_confirm_then_cancel
        """
        scenario = _confirmable_hold_on_a_stored_unit()
        tank_id = scenario["tank"]["id"]
        held_before = validate_success(
            api_client.list_tank_units(tank_id, make_facilities_engineer_headers())
        )

        confirm_reservation(
            scenario["reservation"]["id"],
            intended_transplant_date="2026-09-03",
            center_user_id="tc-001",
        )
        cancel_reservation(
            scenario["reservation"]["id"], reason_code="PATIENT_DECEASED", center_user_id="tc-001"
        )

        unit = read_unit(scenario["unit"]["id"])
        assert unit["processing_status"] == "CRYOPRESERVED"
        assert unit["eligibility_status"] == "ELIGIBLE"
        assert unit["tank_id"] == tank_id
        assert unit["slot_code"] == "M-01"

        held_after = validate_success(
            api_client.list_tank_units(tank_id, make_facilities_engineer_headers())
        )
        assert len(held_before) == 1
        assert len(held_after) == 1


def _ledger_scenario():
    """A one-year private account carrying a single full-year invoice."""
    return build_billed_private_scenario(
        plan_term_years=1,
        tank_code="TANK-N",
        capacity_slots=5,
        primary_parent_name="Ledger Parent",
        collection_site_code="SITE-16",
        consent_document_hash="hash-lg-v1",
        kit_lot_code="LOT-2026-L",
        courier_tracking_code="TRK-1600",
        slot_code="N-01",
        billing_contact_email="lg@example.test",
        prepaid_through_date="2027-06-30",
        invoice_clock="2026-09-01T00:00:00Z",
        billing_period_start="2026-09-01",
        billing_period_end="2027-08-31",
        prorated_days=365,
    )


def _account_invoices(account_id):
    return validate_success(
        api_client.list_storage_account_invoices(account_id, make_billing_admin_headers())
    )


class TestAccountBalanceEqualsUnpaidResidual:
    def test_the_identity_holds_at_issue_and_after_every_accrual(self):
        """The balance is a reconciliation, recomputed after each mutation.

        "It is the sum, over the account's invoices whose `status` is `ISSUED`, `PAST_DUE` or
        `DELINQUENT`, of `amount_due_cents` minus `amount_paid_cents`."

        Design: Difficulty/compensating_invariant/account_balance_equals_unpaid_residual_across_delinquency_then_full_payment
        """
        scenario = _ledger_scenario()
        account_id = scenario["account"]["id"]
        invoice_id = scenario["invoice"]["id"]

        assert read_invoice(invoice_id)["amount_due_cents"] == 18225
        assert read_account(account_id)["balance_cents"] == 18225
        assert_balance_equals_unpaid_residual(
            read_account(account_id), _account_invoices(account_id)
        )

        set_clock("2026-11-01T00:00:00Z")
        nightly_run()
        assert read_invoice(invoice_id)["amount_due_cents"] == 18498
        assert read_invoice(invoice_id)["late_fee_line_cents"] == 273
        assert read_account(account_id)["balance_cents"] == 18498
        assert_balance_equals_unpaid_residual(
            read_account(account_id), _account_invoices(account_id)
        )

        set_clock("2027-01-01T00:00:00Z")
        nightly_run()
        assert read_invoice(invoice_id)["amount_due_cents"] == 18775
        assert read_invoice(invoice_id)["late_fee_line_cents"] == 550
        assert read_account(account_id)["balance_cents"] == 18775
        assert_balance_equals_unpaid_residual(
            read_account(account_id), _account_invoices(account_id)
        )

    def test_paying_the_exact_residual_settles_the_invoice(self):
        """A payment of exactly the residual is permitted and terminates the invoice.

        "When the payment brings `amount_paid_cents` exactly up to `amount_due_cents`, the
        invoice moves to the terminal `PAID` from whichever of `ISSUED`, `PAST_DUE` or
        `DELINQUENT` it was in"

        Design: Difficulty/compensating_invariant/account_balance_equals_unpaid_residual_across_delinquency_then_full_payment
        """
        scenario = _ledger_scenario()
        account_id = scenario["account"]["id"]
        invoice_id = scenario["invoice"]["id"]

        set_clock("2026-11-01T00:00:00Z")
        nightly_run()
        set_clock("2027-01-01T00:00:00Z")
        nightly_run()

        pay_invoice(invoice_id, 18775, payment_reference="WIRE-2027-0001")

        invoice = read_invoice(invoice_id)
        assert invoice["amount_paid_cents"] == 18775
        assert invoice["status"] == "PAID"

        account = read_account(account_id)
        assert account["balance_cents"] == 0
        assert account["lifetime_paid_cents"] == 18775
        assert_balance_equals_unpaid_residual(account, _account_invoices(account_id))

    def test_clearing_the_balance_cures_the_ladder_and_unflags_the_unit(self):
        """Payment is the compensation for the whole delinquency cascade.

        "from `DELINQUENT` and from `ABANDONMENT_NOTICE` the cure additionally returns every
        unit of that account whose `availability_status` is `PENDING_ABANDONMENT` to
        `PRIVATE_STORED`."

        Design: Difficulty/compensating_invariant/account_balance_equals_unpaid_residual_across_delinquency_then_full_payment
        """
        scenario = _ledger_scenario()

        set_clock("2026-11-01T00:00:00Z")
        nightly_run()
        set_clock("2027-01-01T00:00:00Z")
        nightly_run()
        assert read_account(scenario["account"]["id"])["status"] == "DELINQUENT"
        assert read_unit(scenario["unit"]["id"])["availability_status"] == "PENDING_ABANDONMENT"

        pay_invoice(scenario["invoice"]["id"], 18775, payment_reference="WIRE-2027-0001")

        account = read_account(scenario["account"]["id"])
        assert account["status"] == "ACTIVE"
        assert account["delinquency_stage_entered_at"] is None
        assert read_unit(scenario["unit"]["id"])["availability_status"] == "PRIVATE_STORED"

    def test_the_cure_rebates_nothing_and_moves_no_unit_out_of_its_slot(self):
        """Accrued fees stand and the paid history only ever grows.

        "`lifetime_paid_cents` is the monotonic sum of every payment ever accepted on the
        account and is never reduced by a void or a write-off"

        Design: Difficulty/compensating_invariant/account_balance_equals_unpaid_residual_across_delinquency_then_full_payment
        """
        scenario = _ledger_scenario()
        account_id = scenario["account"]["id"]

        set_clock("2026-11-01T00:00:00Z")
        nightly_run()
        set_clock("2027-01-01T00:00:00Z")
        nightly_run()
        pay_invoice(scenario["invoice"]["id"], 18775, payment_reference="WIRE-2027-0001")

        invoice = read_invoice(scenario["invoice"]["id"])
        assert invoice["late_fee_line_cents"] == 550
        assert read_account(account_id)["lifetime_paid_cents"] == 18775
        assert read_tank(scenario["tank"]["id"])["occupied_slots"] == 1
        assert len(_account_invoices(account_id)) == 1
