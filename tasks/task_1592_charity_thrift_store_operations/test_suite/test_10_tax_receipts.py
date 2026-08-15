"""Tax receipts: compliance thresholds, batch close interlock, void locking."""
from test_helpers import (
    ApiErrorId,
    INTAKE,
    MGR,
    add_item,
    assert_receipt,
    begin_sort,
    complete_sort,
    create_batch,
    create_donor,
    create_sorted_batch,
    triage_item,
    validate_error,
    validate_paginated,
    validate_success,
)


def _sorted_batch_with_total(api, donor, target_cents, appraisal_confirmed=None,
                             category="FURNITURE", condition="GOOD"):
    """SORTED receipt_requested batch whose single item revalues to target_cents."""
    batch = create_batch(donor["id"], receipt_requested=True)
    item = add_item(batch["id"], category, condition)
    begin_sort(batch["id"])
    triage_kwargs = {}
    if appraisal_confirmed is not None:
        triage_kwargs["appraisal_confirmed"] = appraisal_confirmed
    triage_item(item["id"], "SALABLE", **triage_kwargs)
    sorted_batch = complete_sort(batch["id"])
    validate_success(
        api.revalue_batch(
            batch["id"],
            {
                "expected_batch_version": sorted_batch["version"],
                "adjustments": [
                    {"item_id": item["id"], "provisional_value_cents": target_cents}
                ],
            },
            INTAKE,
        )
    )
    return batch, item


class TestReceiptThresholds:
    def test_receipt_itemization_threshold_25000(self, api):
        """PRD 3.9: "Two flags scale with that total: `itemized_required` turns true
        when the total reaches 25000 cents — the $250 written-acknowledgment
        threshold — and `form_8283_required` turns true at 50000 cents — the $500
        noncash charitable threshold."

        Design: Difficulty/boundary_precision_check/receipt_itemization_threshold_25000
        """
        donor = create_donor("D Receipt", address_line="7 Elm St")
        batch_at, _ = _sorted_batch_with_total(api, donor, 25000)
        batch_below, _ = _sorted_batch_with_total(api, donor, 24999)

        receipt_at = validate_success(api.issue_receipt(batch_at["id"], INTAKE), 201)
        assert_receipt(receipt_at)
        assert receipt_at["total_value_cents"] == 25000
        assert receipt_at["itemized_required"] is True, "the $250 flag is inclusive"
        assert receipt_at["form_8283_required"] is False
        assert receipt_at["status"] == "ISSUED"

        receipt_below = validate_success(api.issue_receipt(batch_below["id"], INTAKE), 201)
        assert receipt_below["total_value_cents"] == 24999
        assert receipt_below["itemized_required"] is False
        assert receipt_below["form_8283_required"] is False
        assert receipt_below["status"] == "ISSUED"

    def test_form_8283_threshold_50000(self, api):
        """PRD 3.9: "Two flags scale with that total: `itemized_required` turns true
        when the total reaches 25000 cents — the $250 written-acknowledgment
        threshold — and `form_8283_required` turns true at 50000 cents — the $500
        noncash charitable threshold."

        Design: Difficulty/boundary_precision_check/receipt_itemization_threshold_25000
        """
        donor = create_donor("D Form", address_line="8 Elm St")
        batch_at, _ = _sorted_batch_with_total(api, donor, 50000)
        batch_below, _ = _sorted_batch_with_total(api, donor, 49999)

        receipt_at = validate_success(api.issue_receipt(batch_at["id"], INTAKE), 201)
        assert receipt_at["total_value_cents"] == 50000
        assert receipt_at["form_8283_required"] is True, "the $500 flag is inclusive"
        assert receipt_at["itemized_required"] is True

        receipt_below = validate_success(api.issue_receipt(batch_below["id"], INTAKE), 201)
        assert receipt_below["total_value_cents"] == 49999
        assert receipt_below["form_8283_required"] is False
        assert receipt_below["itemized_required"] is True, "49999 still crosses 25000"


class TestReceiptBatchInterlock:
    def test_receipt_and_close_gates_on_batch(self, api):
        """PRD 3.9: "A tax receipt is issued by an `IntakeAttendant` against a
        `SORTED` batch — issuing against a batch in any other state fails with
        `ERR_BATCH_INVALID_STATE`"
        PRD 3.9: "Closing a batch moves `SORTED` → `CLOSED` — a batch in any other
        state cannot close (`ERR_BATCH_INVALID_STATE`) — and the close is
        receipt-aware: when `receipt_requested` is true, an ISSUED receipt must
        already exist for the batch, or the close fails with
        `ERR_BATCH_RECEIPT_MISSING`."
        PRD 3.9: "A successful close stamps `closed_at`, bumps the batch's `version`,
        increments the donor's `lifetime_donation_count` by one, and recomputes the
        donor's `tier` — `FREQUENT` once the count is at least ten, `STANDARD` below
        that."

        Design: Difficulty/cross_entity_state_dependency/receipt_and_close_gates_on_batch
        """
        donor = create_donor("D Gates", address_line="3 Pine St")
        batch = create_batch(donor["id"], receipt_requested=True)
        item = add_item(batch["id"], "CLOTHING", "GOOD")

        # Receipt while OPEN: batch-side state gate.
        resp = api.issue_receipt(batch["id"], INTAKE)
        validate_error(resp, ApiErrorId.ERR_BATCH_INVALID_STATE)

        begin_sort(batch["id"])
        triage_item(item["id"], "SALABLE")
        complete_sort(batch["id"])

        # Close without the receipt: receipt-side gate.
        resp2 = api.close_batch(batch["id"], INTAKE)
        validate_error(resp2, ApiErrorId.ERR_BATCH_RECEIPT_MISSING)

        receipt = validate_success(api.issue_receipt(batch["id"], INTAKE), 201)
        assert receipt["status"] == "ISSUED"

        closed = validate_success(api.close_batch(batch["id"], INTAKE))
        assert closed["status"] == "CLOSED"
        assert closed.get("closed_at"), "close stamps the clock"

        donor_after = validate_success(api.get_donor(donor["id"], MGR))
        assert donor_after["lifetime_donation_count"] == 1
        assert donor_after["tier"] == "STANDARD"

    def test_close_without_receipt_request_succeeds(self, api):
        """PRD 3.9: "Closing a batch moves `SORTED` → `CLOSED` — a batch in any other
        state cannot close (`ERR_BATCH_INVALID_STATE`) — and the close is
        receipt-aware: when `receipt_requested` is true, an ISSUED receipt must
        already exist for the batch, or the close fails with
        `ERR_BATCH_RECEIPT_MISSING`."

        Design: Difficulty/cross_entity_state_dependency/receipt_and_close_gates_on_batch
        """
        donor = create_donor("D Plain")
        batch = create_batch(donor["id"])
        item = add_item(batch["id"], "TOYS", "GOOD")

        resp = api.close_batch(batch["id"], INTAKE)
        validate_error(resp, ApiErrorId.ERR_BATCH_INVALID_STATE)

        begin_sort(batch["id"])
        triage_item(item["id"], "SALABLE")
        complete_sort(batch["id"])

        # receipt_requested defaults false, so no receipt is required to close.
        closed = validate_success(api.close_batch(batch["id"], INTAKE))
        assert closed["status"] == "CLOSED"
        donor_after = validate_success(api.get_donor(donor["id"], MGR))
        assert donor_after["lifetime_donation_count"] == 1


class TestReceiptComplianceGates:
    def test_appraisal_gate_exact_boundary(self, api):
        """PRD 3.9: "Second, every item in the batch whose `provisional_value_cents`
        is at least 500000 cents must carry `appraisal_confirmed` true — the flag
        captured at triage in §3.2 — else `ERR_APPRAISAL_REQUIRED`."

        Design: Corner/validations/appraisal_gate_exact_boundary
        """
        donor = create_donor("D App", address_line="4 Main St")
        batch_unconfirmed, _ = _sorted_batch_with_total(
            api, donor, 500000, appraisal_confirmed=None,
            category="COLLECTIBLES", condition="NEW_WITH_TAGS",
        )
        batch_confirmed, _ = _sorted_batch_with_total(
            api, donor, 500000, appraisal_confirmed=True,
            category="COLLECTIBLES", condition="NEW_WITH_TAGS",
        )

        resp = api.issue_receipt(batch_unconfirmed["id"], INTAKE)
        validate_error(resp, ApiErrorId.ERR_APPRAISAL_REQUIRED)

        receipt = validate_success(api.issue_receipt(batch_confirmed["id"], INTAKE), 201)
        assert receipt["total_value_cents"] == 500000
        assert receipt["itemized_required"] is True
        assert receipt["form_8283_required"] is True

    def test_donor_address_gate_at_50000(self, api):
        """PRD 3.9: "Third, when the receipt total reaches 50000 cents the donor's
        `address_line` must be present, else `ERR_DONOR_ADDRESS_REQUIRED`."

        Design: Corner/validations/donor_address_gate_at_50000
        """
        donor = create_donor("D Addr")  # no address_line on file
        batch, _item = _sorted_batch_with_total(api, donor, 50000,
                                                category="TOYS", condition="GOOD")

        resp = api.issue_receipt(batch["id"], INTAKE)
        validate_error(resp, ApiErrorId.ERR_DONOR_ADDRESS_REQUIRED)

        validate_success(
            api.update_donor(donor["id"], {
                "address_line": "11 River Rd",
                "city": "Springfield",
                "state": "IL",
                "postal_code": "62701",
            }, INTAKE)
        )
        receipt = validate_success(api.issue_receipt(batch["id"], INTAKE), 201)
        assert receipt["total_value_cents"] == 50000
        assert receipt["form_8283_required"] is True
        assert receipt["itemized_required"] is True

    def test_receipt_not_requested_rejected(self, api):
        """PRD 3.9: "First, the batch must have been opened with `receipt_requested`
        true, else `ERR_RECEIPT_NOT_REQUESTED`."

        Design: Corner/validations/receipt_not_requested_rejected
        """
        # receipt_requested omitted at creation: it defaults to false.
        donor, batch, _items = create_sorted_batch(
            [{"category": "TOYS", "condition": "GOOD"}],
            donor_kwargs={"full_name": "D Nr", "address_line": "1 Main"},
            decision="SALVAGE",
        )
        resp = api.issue_receipt(batch["id"], INTAKE)
        validate_error(resp, ApiErrorId.ERR_RECEIPT_NOT_REQUESTED)


class TestReceiptStateMachine:
    def test_receipt_double_issue_rejected(self, api):
        """PRD 3.9: "At most one ISSUED receipt exists per batch: issuing while one
        is still ISSUED fails with `ERR_RECEIPT_INVALID_STATE`."

        Design: Corner/state_machines/receipt_double_issue_rejected
        """
        donor, batch, _items = create_sorted_batch(
            [{"category": "TOYS", "condition": "GOOD"}],
            donor_kwargs={"full_name": "D R2", "address_line": "1 Main St"},
            receipt_requested=True,
        )
        first = validate_success(api.issue_receipt(batch["id"], INTAKE), 201)
        assert first["status"] == "ISSUED"

        resp = api.issue_receipt(batch["id"], INTAKE)
        validate_error(resp, ApiErrorId.ERR_RECEIPT_INVALID_STATE)

        receipts, meta = validate_paginated(
            api.list_receipts(MGR, params={"batch_id": batch["id"]})
        )
        assert len(receipts) == 1, "exactly one receipt row exists for the batch"
        assert receipts[0]["id"] == first["id"]

    def test_receipt_void_after_batch_close_locked(self, api):
        """PRD 3.9: "Closing also locks the paperwork: once the batch is `CLOSED`,
        voiding its receipt fails with `ERR_RECEIPT_LOCKED`."

        Design: Corner/state_machines/receipt_void_after_batch_close_locked
        """
        donor, batch, _items = create_sorted_batch(
            [{"category": "TOYS", "condition": "GOOD"}],
            donor_kwargs={"full_name": "D Lock", "address_line": "2 Main St"},
            receipt_requested=True,
        )
        receipt = validate_success(api.issue_receipt(batch["id"], INTAKE), 201)
        validate_success(api.close_batch(batch["id"], INTAKE))

        resp = api.void_receipt(receipt["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_RECEIPT_LOCKED)
        after = validate_success(api.get_receipt(receipt["id"], MGR))
        assert after["status"] == "ISSUED"
