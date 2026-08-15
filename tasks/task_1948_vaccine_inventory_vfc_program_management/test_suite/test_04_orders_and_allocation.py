"""Vaccine ordering, state-program approval (OCC), and allocation receipts."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_order_line,
    approve_order,
    assert_vaccine_order,
    create_approve_order_payload,
    get_order,
    get_site,
    make_approved_order,
    make_order,
    make_private_lot,
    make_product,
    make_site,
    make_unit,
    open_excursion,
    post_receipt,
    submit_order,
    validate_error,
    validate_success,
)

VM = TEST_USERS["vaccine_manager_headers"]
SPO = TEST_USERS["state_program_officer_headers"]
CA = TEST_USERS["compliance_auditor_headers"]


class TestOrderSubmission:
    def test_submit_from_submitted_rejected(self, api):
        """PRD §3.5: "Submission moves the order from `DRAFT` to `SUBMITTED`
        and enforces three checks in order: the order must currently be
        `DRAFT` (`ERR_INVALID_STATE` otherwise), at least one line must exist
        (`ERR_EMPTY_ORDER`), and the site must be `ACTIVE` rather than
        `SUSPENDED_ORDERING` (`ERR_SITE_SUSPENDED_ORDERING`)."

        Design: Corner/state_machines/vaccine_order_submit_from_submitted_returns_invalid_state
        """
        site = make_site()
        product = make_product()
        order = make_order(site["id"], expected_vfc_doses=5)
        add_order_line(site["id"], order["id"], product["id"], 5)
        submit_order(site["id"], order["id"])
        resp = api.submit_order(site["id"], order["id"], VM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_submit_empty_order_rejected(self, api):
        """PRD §3.5: "Submission moves the order from `DRAFT` to `SUBMITTED`
        and enforces three checks in order: the order must currently be
        `DRAFT` (`ERR_INVALID_STATE` otherwise), at least one line must exist
        (`ERR_EMPTY_ORDER`), and the site must be `ACTIVE` rather than
        `SUSPENDED_ORDERING` (`ERR_SITE_SUSPENDED_ORDERING`)."

        Design: Corner/errors/error_empty_order_blocks_submission
        """
        site = make_site()
        order = make_order(site["id"], expected_vfc_doses=5)
        resp = api.submit_order(site["id"], order["id"], VM)
        validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER)

    def test_suspended_site_cannot_submit(self, api):
        """PRD §3.1: "While suspended, the site cannot submit vaccine orders —
        submission is refused with `ERR_SITE_SUSPENDED_ORDERING`".

        Design: Corner/validations/suspended_site_order_submission_blocked
        """
        site = make_site()
        product = make_product()
        order = make_order(site["id"], expected_vfc_doses=5)
        add_order_line(site["id"], order["id"], product["id"], 5)
        validate_success(api.suspend_ordering(site["id"], CA))
        resp = api.submit_order(site["id"], order["id"], VM)
        validate_error(resp, ApiErrorId.ERR_SITE_SUSPENDED_ORDERING)


class TestOrderApproval:
    def test_approval_with_mismatched_line_allocation_rejected(self, api):
        """PRD §3.5: "finally the sum of the per-line `approved_doses` must
        equal the order-level `approved_vfc_doses` exactly, rejecting
        mismatches with `ERR_ALLOCATION_MISMATCH`."

        Design: Corner/errors/error_allocation_mismatch_on_order_approval
        """
        site = make_site()
        product = make_product()
        order = make_order(site["id"], expected_vfc_doses=10)
        line = add_order_line(site["id"], order["id"], product["id"], 10)
        submit_order(site["id"], order["id"])
        sv = get_site(site["id"])["version"]
        payload = create_approve_order_payload(
            99, sv,
            line_allocations=[{"order_line_id": line["id"], "approved_doses": 5}],
        )
        resp = api.approve_order(site["id"], order["id"], payload, SPO)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_MISMATCH)

    def test_approval_with_stale_site_version_rejected(self, api):
        """PRD §2.8: "If the site's current `version` has advanced since that
        read — because a prior approval, a receipt posting, a suspension, or an
        excursion cascade legitimately moved it forward — the approval is
        rejected with `ERR_STALE_VERSION` (HTTP 412), since the approver's view
        of the site's compliance posture is stale." PRD §3.5: "A successful
        approval moves the order to `APPROVED` and increments the site's
        `version` by one."

        Design: Corner/cross_cutting_layers/occ_order_approve_stale_version_returns_412
        """
        site = make_site()
        product = make_product()
        order1 = make_order(site["id"], expected_vfc_doses=5)
        add_order_line(site["id"], order1["id"], product["id"], 5)
        submit_order(site["id"], order1["id"])
        stale_version = get_site(site["id"])["version"]
        # First approval advances the site's version by one (PRD §3.5).
        approve_order(site["id"], order1["id"], approved_vfc_doses=5)
        order2 = make_order(site["id"], expected_vfc_doses=3)
        add_order_line(site["id"], order2["id"], product["id"], 3)
        submit_order(site["id"], order2["id"])
        payload = create_approve_order_payload(3, stale_version)
        resp = api.approve_order(site["id"], order2["id"], payload, SPO)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestAllocationReceipts:
    def test_over_receipt_rejected(self, api):
        """PRD §3.5: "The line's `received_doses` then grows by the receipt
        quantity, and it may never exceed the line's `approved_doses` — an
        over-shipment is rejected with `ERR_OVER_RECEIPT`."

        Design: Corner/validations/allocation_over_receipt_rejected
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        order, line = make_approved_order(site["id"], product["id"], 5)
        post_receipt(site["id"], order["id"], line["id"], unit["id"], 4)
        resp = api.create_allocation_receipt(
            site["id"], order["id"],
            {
                "order_line_id": line["id"],
                "storage_unit_id": unit["id"],
                "lot_number": "L2",
                "expires_on": "2027-06-30",
                "quantity_doses": 2,
            },
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_OVER_RECEIPT)

    def test_running_total_drives_partial_then_full_receipt(self, api):
        """PRD §3.5: "The order's `received_vfc_doses` is always the sum of its
        lines' `received_doses`; the first receipt that lifts that sum above
        zero (while it remains below the approved total) moves the order
        automatically from `APPROVED` to `PARTIALLY_RECEIVED`, and the moment
        the running total equals `approved_vfc_doses` the order becomes
        `FULLY_RECEIVED`".

        Design: Corner/calculations/allocation_receipt_running_total_auto_full_receipt
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        order, line = make_approved_order(site["id"], product["id"], 7)
        post_receipt(site["id"], order["id"], line["id"], unit["id"], 3)
        mid = get_order(site["id"], order["id"])
        assert_vaccine_order(mid)
        assert mid["status"] == "PARTIALLY_RECEIVED"
        assert mid["received_vfc_doses"] == 3
        post_receipt(site["id"], order["id"], line["id"], unit["id"], 4)
        end = get_order(site["id"], order["id"])
        assert end["status"] == "FULLY_RECEIVED"
        assert end["received_vfc_doses"] == 7

    def test_partial_receipt_branch_traverses_partially_received(self, api):
        """PRD §3.5: "the first receipt that lifts that sum above zero (while
        it remains below the approved total) moves the order automatically from
        `APPROVED` to `PARTIALLY_RECEIVED`, and the moment the running total
        equals `approved_vfc_doses` the order becomes `FULLY_RECEIVED`".

        Design: Difficulty/non_linear_state_machine/vaccine_order_fork_join_partial_or_full_receipt
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        order, line = make_approved_order(site["id"], product["id"], 10)
        post_receipt(site["id"], order["id"], line["id"], unit["id"], 4,
                     lot_number="LOT-O1A")
        mid = get_order(site["id"], order["id"])
        assert mid["status"] == "PARTIALLY_RECEIVED", (
            f"4 of 10 received must sit in PARTIALLY_RECEIVED, got {mid['status']}"
        )
        post_receipt(site["id"], order["id"], line["id"], unit["id"], 6,
                     lot_number="LOT-O1B")
        final = get_order(site["id"], order["id"])
        assert final["status"] == "FULLY_RECEIVED"

    def test_single_complete_receipt_skips_partial_state(self, api):
        """PRD §3.5: "the moment the running total equals `approved_vfc_doses`
        the order becomes `FULLY_RECEIVED` — including the case where a single
        receipt covers the entire allocation in one posting."

        Design: Difficulty/non_linear_state_machine/vaccine_order_fork_join_partial_or_full_receipt
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        order, line = make_approved_order(site["id"], product["id"], 5)
        post_receipt(site["id"], order["id"], line["id"], unit["id"], 5,
                     lot_number="LOT-O2A")
        final = get_order(site["id"], order["id"])
        assert final["status"] == "FULLY_RECEIVED", (
            f"a single complete receipt moves APPROVED straight to FULLY_RECEIVED, "
            f"got {final['status']}"
        )
        assert final["received_vfc_doses"] == 5


class TestReceiptSafetyBeforeFiscal:
    def test_quarantined_unit_receipt_rejected_even_when_over_receipt(self, api):
        """PRD §3.5: "The destination unit must belong to the order's site
        (`ERR_UNIT_SITE_MISMATCH`) and must not be quarantined
        (`ERR_STORAGE_UNIT_QUARANTINED`)." PRD §2.12: "quarantine and
        lot-availability safety checks ahead of eligibility and referential
        checks, and fiscal checks such as allocation consistency last."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_allocation_over_receipt
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        make_private_lot(site["id"], unit["id"], product["id"], quantity_on_hand=2)
        order, line = make_approved_order(site["id"], product["id"], 5)
        open_excursion(unit["id"])
        resp = api.create_allocation_receipt(
            site["id"], order["id"],
            {
                "order_line_id": line["id"],
                "storage_unit_id": unit["id"],
                "lot_number": "L2",
                "expires_on": "2027-06-30",
                "quantity_doses": 10,  # would also exceed approved_doses=5
            },
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_STORAGE_UNIT_QUARANTINED)

    def test_quarantined_unit_receipt_rejected_within_allocation(self, api):
        """PRD §3.5: "The destination unit must belong to the order's site
        (`ERR_UNIT_SITE_MISMATCH`) and must not be quarantined
        (`ERR_STORAGE_UNIT_QUARANTINED`)." With the receipt inside the
        approved allocation, the safety violation is the only failure and
        must still reject.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_allocation_over_receipt
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        order, line = make_approved_order(site["id"], product["id"], 5)
        open_excursion(unit["id"])
        resp = api.create_allocation_receipt(
            site["id"], order["id"],
            {
                "order_line_id": line["id"],
                "storage_unit_id": unit["id"],
                "lot_number": "L3",
                "expires_on": "2027-06-30",
                "quantity_doses": 3,
            },
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_STORAGE_UNIT_QUARANTINED)
