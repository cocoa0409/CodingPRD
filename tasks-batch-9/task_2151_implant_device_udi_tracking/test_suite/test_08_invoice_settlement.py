"""Invoice approval, the settlement waterfall and the dispute cycle."""

from test_helpers import (
    ApiErrorId,
    CC,
    CO,
    IL,
    RI,
    approve_invoice,
    dispute_invoice,
    get_explant,
    get_invoice,
    get_unit,
    get_vendor,
    make_vendor_rep_headers,
    match_invoice,
    record_explant,
    setup_billable_units,
    setup_matched_invoice,
    submit_invoice,
    validate_error,
    validate_success,
    verify_record,
)

SPINAL_CAGE = {
    "device_identifier": "00812345678943",
    "description": "Spinal Cage",
    "category": "HIGH_COST_IMPLANT",
    "list_charge_cents": 1_800_000,
    "charge_code": "CDM-77180",
}
KNEE_CATALOG = {
    "device_identifier": "00812345678981",
    "description": "Knee Femoral Component",
    "category": "HIGH_COST_IMPLANT",
    "list_charge_cents": 1_500_000,
    "charge_code": "CDM-77220",
}


def _settlement_world():
    """Two invoiced units at 1,300,000 each and a third, explanted unit sitting
    in CREDIT_PENDING that forms a 1,400,000 credit pool under the agreement."""
    world = setup_billable_units(
        (1_300_000, 1_300_000, 1_400_000),
        agreement_overrides={"agreement_code": "AGR-C"},
        catalog_overrides=SPINAL_CAGE,
        case_overrides={
            "case_number": "CASE-3",
            "or_room_code": "OR-6",
            "scheduled_start_utc": "2026-09-12T08:00:00Z",
            "scheduled_end_utc": "2026-09-12T12:00:00Z",
        },
    )
    verify_record(world["records"][2]["id"])
    world["explant"] = record_explant(world["records"][2]["id"], reason="DEVICE_FAILURE")

    world["invoice"] = submit_invoice(
        world["vendor"]["id"],
        world["agreement"]["id"],
        [world["units"][0]["id"], world["units"][1]["id"]],
        2_600_000,
        invoice_number="INV-1",
    )
    world["invoice"] = match_invoice(world["invoice"]["id"])
    return world


class TestSettlementWaterfall:
    def test_the_credit_cap_tier_is_keyed_on_the_gross_amount_due(self, api):
        """PRD §3.10: "Begin with the gross amount due, which is the invoice's
        already-written `expected_total_cents` — never its `submitted_total_cents`."
        PRD §3.10: "Next select a credit-cap percentage from a tier ladder **keyed
        on the gross amount due and on nothing else**: a gross below 500,000 cents
        caps credit at 20 percent; a gross of at least 500,000 cents and below
        2,500,000 cents caps it at 35 percent; a gross of 2,500,000 cents or more
        caps it at 50 percent. The tier is never re-selected using the net payable —
        re-keying it that way is the wrong reading and produces a different,
        unstable answer."
        PRD §3.10: "Then `credit_applied_cents` is the lesser of the credit pool and
        the gross amount due multiplied by the cap percentage rounded half up to a
        whole cent. Finally `net_payable_cents` is the gross amount due minus
        `credit_applied_cents`."

        Design: Difficulty/combinatorial_formula/settlement_credit_tier_keyed_on_gross_not_on_net
        """
        world = _settlement_world()
        assert world["invoice"]["expected_total_cents"] == 2_600_000
        assert world["invoice"]["variance_bps"] == 0

        approved = validate_success(api.approve_invoice(world["invoice"]["id"], {}, CO), 200)
        assert approved["credit_applied_cents"] == 1_300_000
        assert approved["net_payable_cents"] == 1_300_000
        assert approved["net_payable_cents"] != 2_145_000, (
            "2145000 is the answer produced by re-keying the cap tier on the net "
            "payable, which the PRD calls the wrong reading"
        )

    def test_approval_reconciles_every_unit_on_the_invoice(self, api):
        """PRD §3.10: "Both branches then run the identical settlement side-effect
        set: `credit_applied_cents` and `net_payable_cents` are computed and
        written, `approved_by_user_id` is recorded, the invoice moves to `APPROVED`,
        every device unit on the invoice moves `INVOICED → RECONCILED`, and that
        billing change in turn re-derives the vendor's
        `open_consignment_liability_cents`, since reconciled units leave the
        liability base."
        PRD §3.9: "The basis is the unit's frozen `contract_price_cents` when that
        is non-null, and zero when it is null — so a hospital-owned unit that never
        became billable produces a `credit_expected_cents` of 0."

        Design: Difficulty/combinatorial_formula/settlement_credit_tier_keyed_on_gross_not_on_net
        """
        world = _settlement_world()

        approved = validate_success(api.approve_invoice(world["invoice"]["id"], {}, CO), 200)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "co-01"

        assert get_unit(world["units"][0]["id"])["billing_state"] == "RECONCILED"
        assert get_unit(world["units"][1]["id"])["billing_state"] == "RECONCILED"
        assert get_explant(world["explant"]["id"])["credit_expected_cents"] == 1_400_000


class TestVarianceHoldApproval:
    def test_a_held_invoice_needs_an_override_reason_to_be_approved(self, api):
        """PRD §3.10: "Approving from `VARIANCE_HOLD` additionally requires a
        present, non-empty `override_reason` — approving a held invoice without one
        is rejected with `ERR_INVOICE_TOLERANCE_EXCEEDED`. Approving from `MATCHED`
        needs no reason and ignores one if supplied."
        PRD §3.10: "Both branches then run the identical settlement side-effect set:
        `credit_applied_cents` and `net_payable_cents` are computed and written,
        `approved_by_user_id` is recorded, the invoice moves to `APPROVED`, every
        device unit on the invoice moves `INVOICED → RECONCILED`, and that billing
        change in turn re-derives the vendor's `open_consignment_liability_cents`,
        since reconciled units leave the liability base."

        Design: Corner/validations/variance_hold_approve_requires_override_reason
        """
        world = setup_matched_invoice(
            1_200_000,
            (1_000_000,),
            catalog_overrides=KNEE_CATALOG,
            invoice_number="INV-1",
        )
        assert world["invoice"]["variance_bps"] == 2_000
        assert world["invoice"]["status"] == "VARIANCE_HOLD"

        validate_error(
            api.approve_invoice(world["invoice"]["id"], {}, CO),
            ApiErrorId.ERR_INVOICE_TOLERANCE_EXCEEDED,
            422,
        )
        assert get_invoice(world["invoice"]["id"])["status"] == "VARIANCE_HOLD"

        approved = validate_success(
            api.approve_invoice(
                world["invoice"]["id"],
                {"override_reason": "negotiated freight surcharge accepted by supply chain"},
                CO,
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["credit_applied_cents"] == 0
        assert approved["net_payable_cents"] == 1_000_000
        assert approved["approved_by_user_id"] == "co-01"
        assert approved["matched_by_user_id"] == "ri-01"

        assert get_unit(world["units"][0]["id"])["billing_state"] == "RECONCILED"
        assert get_vendor(world["vendor"]["id"])["open_consignment_liability_cents"] == 0


class TestDisputeAndResubmission:
    def test_dispute_releases_the_stock_and_resubmission_rebinds_it(self, api):
        """PRD §3.10: "Disputing moves the invoice to `DISPUTED` and releases its
        stock: every device unit on it moves `INVOICED → BILLABLE` and has its
        `vendor_invoice_id` cleared, and that billing change in turn re-derives the
        vendor's `open_consignment_liability_cents`."
        PRD §3.10: "It moves the invoice back to `SUBMITTED`, moves every newly
        listed unit `BILLABLE → INVOICED` with `vendor_invoice_id` set, and resets
        `expected_total_cents`, `variance_cents`, `variance_bps`,
        `reconciliation_variant` and `matched_by_user_id` all back to null so that
        the invoice must be matched afresh by someone who is then free to approve it
        — the separation resets with the match."

        Design: Corner/state_machines/invoice_dispute_then_resubmit_restores_units_to_invoiced
        """
        world = setup_matched_invoice(
            1_200_000,
            (1_000_000,),
            catalog_overrides=KNEE_CATALOG,
            invoice_number="INV-1",
        )
        invoice_id = world["invoice"]["id"]
        unit_id = world["units"][0]["id"]

        assert world["invoice"]["expected_total_cents"] == 1_000_000
        assert world["invoice"]["variance_cents"] == 200_000
        assert world["invoice"]["variance_bps"] == 2_000
        assert world["invoice"]["status"] == "VARIANCE_HOLD"

        disputed = validate_success(api.dispute_invoice(invoice_id, RI), 200)
        assert disputed["status"] == "DISPUTED"
        released = get_unit(unit_id)
        assert released["billing_state"] == "BILLABLE"
        assert released["vendor_invoice_id"] is None

        resubmitted = validate_success(
            api.resubmit_invoice(
                invoice_id,
                {"submitted_total_cents": 1_000_000, "device_unit_ids": [unit_id]},
                make_vendor_rep_headers(world["vendor"]["id"]),
            ),
            200,
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["expected_total_cents"] is None
        assert resubmitted["variance_cents"] is None
        assert resubmitted["variance_bps"] is None
        assert resubmitted["reconciliation_variant"] is None
        assert resubmitted["matched_by_user_id"] is None
        assert get_unit(unit_id)["billing_state"] == "INVOICED"

        rematched = match_invoice(invoice_id)
        assert rematched["variance_cents"] == 0
        assert rematched["variance_bps"] == 0
        assert rematched["status"] == "MATCHED"


class TestOutOfStateOperations:
    def test_three_machines_reject_three_different_out_of_state_operations(self, api):
        """PRD §3.2: "Attempting to waste a unit in any other custody state — an
        `IMPLANTED` one, for instance — is rejected with `ERR_INVALID_UNIT_STATE`."
        PRD §3.10: "A `RevenueIntegrityAnalyst` may dispute an invoice, legal only
        from `VARIANCE_HOLD`; a `MATCHED` or `SUBMITTED` invoice cannot be disputed
        and is rejected with `ERR_INVALID_INVOICE_STATE`."
        PRD §3.9: "Shipping an authorized return is an `InventoryLead` action legal
        only from `RETURN_AUTHORIZED`."
        PRD §2.6: "Path-target state — the resource named by the path is in a state
        from which the requested transition is declared."

        Design: Corner/validations/invalid_state_guards_for_unit_invoice_and_lifecycle_machines
        """
        world = setup_billable_units(
            (462_500, 462_500),
            case_overrides={"scheduled_end_utc": "2026-09-10T12:00:00Z"},
        )
        verify_record(world["records"][1]["id"])
        explant = record_explant(world["records"][1]["id"], reason="INFECTION")

        invoice = submit_invoice(
            world["vendor"]["id"],
            world["agreement"]["id"],
            [world["units"][0]["id"]],
            462_500,
            invoice_number="INV-1",
        )

        validate_error(
            api.waste_device_unit(world["units"][0]["id"], CC),
            ApiErrorId.ERR_INVALID_UNIT_STATE,
            409,
        )
        assert get_unit(world["units"][0]["id"])["custody_state"] == "IMPLANTED"

        validate_error(
            api.dispute_invoice(invoice["id"], RI),
            ApiErrorId.ERR_INVALID_INVOICE_STATE,
            409,
        )
        assert get_invoice(invoice["id"])["status"] == "SUBMITTED"

        validate_error(
            api.ship_explant(explant["id"], IL),
            ApiErrorId.ERR_INVALID_LIFECYCLE_STATE,
            409,
        )
        assert get_explant(explant["id"])["status"] == "RECORDED"
        assert get_unit(world["units"][1]["id"])["custody_state"] == "EXPLANTED"
