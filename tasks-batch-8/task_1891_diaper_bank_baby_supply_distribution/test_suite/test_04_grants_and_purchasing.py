"""Grant funding, wholesale purchasing, segregation of duties, and valuations."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_grant_funds_invariants,
    create_active_grant,
    create_donation_batch,
    create_draft_po,
    get_grant,
    get_inventory,
    init_inventory,
    make_finance_manager_headers,
    make_warehouse_manager_headers,
    purchase_line,
    receive_po,
    size_entry,
    submit_po,
    supply_line,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bank_admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_manager_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]

# The pinned rounding inputs: 3 x 1055 at 10% and 7 x 333 at 10% round per line
# to 2849 and 2098, summing to 4947 (sum-then-round would yield 4946).
ROUNDING_LINES = [purchase_line("SIZE_1", 3, 1055), purchase_line("SIZE_2", 7, 333)]


class TestPurchaseOrderRounding:
    def test_po_total_rounds_each_line_before_summing(self, api):
        """PRD §3.3: "The order's `total_cost_cents` is computed once, at creation, and fixed thereafter: for each line, multiply `quantity` by `unit_cost_cents` by one minus `discount_pct`, round the result half up to whole cents, and only then sum the per-line totals. The rounding order is pinned — round each line first, then sum; summing first and rounding once would produce a different cent total and is rejected."

        Design: Difficulty/combinatorial_formula/purchase_order_per_line_rounding_then_sum
        """
        grant = create_active_grant(total_amount_cents=1000000, grant_code="GR-1")
        resp = api.create_purchase_order(
            {"grant_id": grant["id"], "vendor_name": "Wholesale Co",
             "discount_pct": 0.10,
             "lines": [{"size_code": "SIZE_1", "quantity": 3, "unit_cost_cents": 1055},
                       {"size_code": "SIZE_2", "quantity": 7, "unit_cost_cents": 333}]},
            WAREHOUSE,
        )
        po = validate_success(resp, 201)
        # Per line: round_half_up(3*1055*0.9) = 2849, round_half_up(7*333*0.9) = 2098.
        assert po["total_cost_cents"] == 4947, (
            "2849 + 2098 = 4947; the sum-then-round order would give 4946"
        )
        assert po["status"] == "DRAFT"
        assert po["created_by_user_id"] == "wm-user-1"

    def test_po_total_computed_once_fixed_after_submit(self, api):
        """PRD §3.3: "The order's `total_cost_cents` is computed once, at creation, and fixed thereafter: for each line, multiply `quantity` by `unit_cost_cents` by one minus `discount_pct`, round the result half up to whole cents, and only then sum the per-line totals."
        PRD §3.3: "On submission the order transitions `DRAFT` → `SUBMITTED`, the grant's `committed_cents` increases by `total_cost_cents` with `available_cents` recomputed, `submitted_by_user_id` is recorded, and both the order's and the grant's `version` increment."

        Design: Difficulty/combinatorial_formula/purchase_order_per_line_rounding_then_sum
        """
        grant = create_active_grant(total_amount_cents=1000000)
        po = create_draft_po(grant["id"], lines=ROUNDING_LINES, discount_pct=0.10)
        assert po["total_cost_cents"] == 4947

        submitted = submit_po(po["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["total_cost_cents"] == 4947, "The total is fixed at creation"
        assert submitted["submitted_by_user_id"] == "fm-user-1"

        grant_after = get_grant(grant["id"])
        assert grant_after["committed_cents"] == 4947
        assert grant_after["spent_cents"] == 0
        assert_grant_funds_invariants(grant_after)


class TestGrantFundsLedger:
    def test_grant_exhausted_at_exact_total_boundary(self, api):
        """PRD §3.3: "If the grant's `spent_cents` has reached or exceeded its `total_amount_cents` after crediting — equality exhausts — the grant automatically transitions `ACTIVE` → `EXHAUSTED`."
        PRD §3.3: "and finally the order's `total_cost_cents` must not exceed the grant's `available_cents` (otherwise `ERR_GRANT_BUDGET_EXCEEDED`); an exact fit, where the order consumes the grant's last available cent, is allowed."

        Design: Corner/calculations/grant_exhausted_at_exact_total_boundary
        """
        init_inventory()
        grant = create_active_grant(total_amount_cents=4947, grant_code="GR-E")
        po = create_draft_po(grant["id"], lines=ROUNDING_LINES, discount_pct=0.10)
        assert po["total_cost_cents"] == 4947
        submit_po(po["id"])  # exact-fit submit: 4947 <= 4947 is allowed

        received = receive_po(po["id"], [{"size_code": "SIZE_1", "quantity": 3},
                                         {"size_code": "SIZE_2", "quantity": 7}])
        assert received["status"] == "RECEIVED"

        grant_after = get_grant(grant["id"])
        assert grant_after["status"] == "EXHAUSTED", (
            "Equality exhausts: spent 4947 reached total 4947"
        )
        assert grant_after["spent_cents"] == 4947
        assert grant_after["committed_cents"] == 0
        assert grant_after["available_cents"] == 0

    def test_submit_commits_exact_po_total(self, api):
        """PRD §3.3: "On submission the order transitions `DRAFT` → `SUBMITTED`, the grant's `committed_cents` increases by `total_cost_cents` with `available_cents` recomputed, `submitted_by_user_id` is recorded, and both the order's and the grant's `version` increment."
        PRD §3.3: "Its funds position is always derivable: `committed_cents` is the sum of `total_cost_cents` over purchase orders referencing the grant whose status is `SUBMITTED`; `spent_cents` is the same sum over orders whose status is `RECEIVED`; `DRAFT` and `CANCELLED` orders contribute to neither sum; and `available_cents` is `total_amount_cents` minus `committed_cents` minus `spent_cents`."

        Design: Difficulty/compensating_invariant/po_submit_cancel_round_trip_conserves_grant_cents
        """
        grant = create_active_grant(total_amount_cents=100000, grant_code="GR-R")
        po = create_draft_po(grant["id"], lines=ROUNDING_LINES, discount_pct=0.10)

        submit_po(po["id"])
        grant_after = get_grant(grant["id"])
        assert grant_after["committed_cents"] == 4947
        assert grant_after["spent_cents"] == 0
        assert grant_after["available_cents"] == 95053, "100000 - 4947 - 0"

    def test_submit_then_cancel_restores_grant_funds(self, api):
        """PRD §3.3: "A `FinanceManager` cancels a `SUBMITTED` order, which decreases the grant's `committed_cents` by `total_cost_cents`, an exact reversal of submission, with `available_cents` recomputed and both versions incremented."
        PRD §3.3: "`CANCELLED` and `RECEIVED` are terminal."

        Design: Difficulty/compensating_invariant/po_submit_cancel_round_trip_conserves_grant_cents
        """
        grant = create_active_grant(total_amount_cents=100000, grant_code="GR-R")
        po = create_draft_po(grant["id"], lines=ROUNDING_LINES, discount_pct=0.10)
        submit_po(po["id"])

        cancelled = validate_success(api.cancel_purchase_order(po["id"], FINANCE), 200)
        assert cancelled["status"] == "CANCELLED"

        grant_after = get_grant(grant["id"])
        assert grant_after["committed_cents"] == 0, "Cancellation exactly reverses submission"
        assert grant_after["spent_cents"] == 0
        assert grant_after["available_cents"] == 100000, (
            "The submit-cancel round trip restores the exact pre-submit funds position"
        )
        assert grant_after["status"] == "ACTIVE"


class TestPurchaseOrderStates:
    def test_po_receive_from_draft_rejected(self, api):
        """PRD §3.3: "A `WarehouseManager` receives a `SUBMITTED` order — any other status yields `ERR_PO_NOT_RECEIVABLE` — against a grant that must still be `ACTIVE` (`ERR_GRANT_NOT_ACTIVE`)."

        Design: Corner/state_machines/po_receive_from_draft_rejected
        """
        grant = create_active_grant(total_amount_cents=100000, grant_code="GR-D")
        po = create_draft_po(grant["id"], lines=[purchase_line("SIZE_1", 1, 1000)])

        resp = api.receive_purchase_order(
            po["id"], {"received_lines": [{"size_code": "SIZE_1", "quantity": 1}]},
            WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_PO_NOT_RECEIVABLE)

        po_after = validate_success(api.get_purchase_order(po["id"], WAREHOUSE), 200)
        assert po_after["status"] == "DRAFT"
        _data, meta = validate_paginated(
            api.list_intake_batches(WAREHOUSE,
                                    params={"purchase_order_id": po["id"]}))
        assert meta["total_count"] == 0, "A rejected receive creates no intake batch"
        grant_after = get_grant(grant["id"])
        assert grant_after["committed_cents"] == 0
        assert grant_after["spent_cents"] == 0

    def test_state_error_beats_budget_error_on_submit(self, api):
        """PRD §3.3: "Submission commits the money and is guarded by five checks evaluated in a declared order: the order must be `DRAFT` (otherwise `ERR_PO_NOT_SUBMITTABLE`), the referenced grant must be `ACTIVE` (otherwise `ERR_GRANT_NOT_ACTIVE`), the submitter's `X-User-ID` must differ from `created_by_user_id` (otherwise `ERR_SOD_VIOLATION`, per §2.11), the grant's `restriction` must not be `OPERATIONS_ONLY` — a product purchase against an operations-only grant yields `ERR_GRANT_RESTRICTION_VIOLATION` — and finally the order's `total_cost_cents` must not exceed the grant's `available_cents` (otherwise `ERR_GRANT_BUDGET_EXCEEDED`); an exact fit, where the order consumes the grant's last available cent, is allowed."

        Design: Difficulty/priority_pair_validation_conflict/po_submit_state_error_beats_budget_error
        """
        grant = create_active_grant(total_amount_cents=10000, grant_code="GR-P")
        po = create_draft_po(grant["id"], lines=[purchase_line("SIZE_1", 20, 600)])
        assert po["total_cost_cents"] == 12000
        # WarehouseManager may cancel a DRAFT order; the order lands CANCELLED.
        validate_success(api.cancel_purchase_order(po["id"], WAREHOUSE), 200)

        # The cancelled order's total (12000) also exceeds available (10000), but
        # the DRAFT-state check is declared first in the submission guard order.
        resp = api.submit_purchase_order(po["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_PO_NOT_SUBMITTABLE)

    def test_rejected_submit_leaves_grant_untouched(self, api):
        """PRD §3.3: "On submission the order transitions `DRAFT` → `SUBMITTED`, the grant's `committed_cents` increases by `total_cost_cents` with `available_cents` recomputed, `submitted_by_user_id` is recorded, and both the order's and the grant's `version` increment."

        Design: Difficulty/priority_pair_validation_conflict/po_submit_state_error_beats_budget_error
        """
        grant = create_active_grant(total_amount_cents=10000, grant_code="GR-P")
        po = create_draft_po(grant["id"], lines=[purchase_line("SIZE_1", 20, 600)])
        validate_success(api.cancel_purchase_order(po["id"], WAREHOUSE), 200)

        resp = api.submit_purchase_order(po["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_PO_NOT_SUBMITTABLE)

        po_after = validate_success(api.get_purchase_order(po["id"], WAREHOUSE), 200)
        assert po_after["status"] == "CANCELLED", "The rejected submit moves nothing"
        grant_after = get_grant(grant["id"])
        assert grant_after["committed_cents"] == 0, (
            "No funds are committed by a submission that fails its first guard"
        )

    def test_po_submit_requires_active_grant(self, api):
        """PRD §3.3: "Draft orders referencing the grant are left in place, but they can never be submitted afterwards — submission requires an `ACTIVE` grant and will fail with `ERR_GRANT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/po_submit_requires_active_grant
        """
        grant = create_active_grant(total_amount_cents=100000, grant_code="GR-Q")
        po = create_draft_po(grant["id"], lines=[purchase_line("SIZE_1", 1, 1000)])
        # No SUBMITTED orders reference the grant, so closing it is legal.
        closed = validate_success(api.close_grant(grant["id"], FINANCE), 200)
        assert closed["status"] == "CLOSED"

        resp = api.submit_purchase_order(po["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_GRANT_NOT_ACTIVE)

    def test_closed_grant_rejection_leaves_po_draft(self, api):
        """PRD §3.3: "Draft orders referencing the grant are left in place, but they can never be submitted afterwards — submission requires an `ACTIVE` grant and will fail with `ERR_GRANT_NOT_ACTIVE`."
        PRD §3.3: "Its funds position is always derivable: `committed_cents` is the sum of `total_cost_cents` over purchase orders referencing the grant whose status is `SUBMITTED`; `spent_cents` is the same sum over orders whose status is `RECEIVED`; `DRAFT` and `CANCELLED` orders contribute to neither sum; and `available_cents` is `total_amount_cents` minus `committed_cents` minus `spent_cents`."

        Design: Difficulty/cross_entity_state_dependency/po_submit_requires_active_grant
        """
        grant = create_active_grant(total_amount_cents=100000, grant_code="GR-Q")
        po = create_draft_po(grant["id"], lines=[purchase_line("SIZE_1", 1, 1000)])
        validate_success(api.close_grant(grant["id"], FINANCE), 200)

        resp = api.submit_purchase_order(po["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_GRANT_NOT_ACTIVE)

        po_after = validate_success(api.get_purchase_order(po["id"], WAREHOUSE), 200)
        assert po_after["status"] == "DRAFT", "The draft order is left in place"
        grant_after = get_grant(grant["id"])
        assert grant_after["committed_cents"] == 0
        assert grant_after["status"] == "CLOSED"


class TestSegregationAndRestriction:
    def test_sod_same_user_submit_rejected(self, api):
        """PRD §2.11: "Submission — the act that commits grant money — belongs to a `FinanceManager`, and the submitting identity must differ from `created_by_user_id`; an attempt by the same operator to submit their own order is rejected with `ERR_SOD_VIOLATION`."

        Design: Corner/validations/sod_same_user_submit_rejected
        """
        grant = create_active_grant(total_amount_cents=100000, grant_code="GR-S")
        po = create_draft_po(
            grant["id"], lines=[purchase_line("SIZE_1", 1, 1000)],
            creator_headers=make_warehouse_manager_headers("dual-role-user"),
        )
        assert po["created_by_user_id"] == "dual-role-user"

        resp = api.submit_purchase_order(
            po["id"], make_finance_manager_headers("dual-role-user"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        po_after = validate_success(api.get_purchase_order(po["id"], WAREHOUSE), 200)
        assert po_after["status"] == "DRAFT"
        assert po_after["submitted_by_user_id"] is None
        assert get_grant(grant["id"])["committed_cents"] == 0

    def test_restriction_violation_on_operations_only_grant(self, api):
        """PRD §3.3: "the grant's `restriction` must not be `OPERATIONS_ONLY` — a product purchase against an operations-only grant yields `ERR_GRANT_RESTRICTION_VIOLATION`"

        Design: Corner/validations/restriction_violation_on_operations_only_grant
        """
        grant = create_active_grant(total_amount_cents=100000,
                                    restriction="OPERATIONS_ONLY",
                                    grant_code="GR-O")
        po = create_draft_po(grant["id"], lines=[purchase_line("SIZE_1", 1, 1000)])

        resp = api.submit_purchase_order(po["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_GRANT_RESTRICTION_VIOLATION)

        po_after = validate_success(api.get_purchase_order(po["id"], WAREHOUSE), 200)
        assert po_after["status"] == "DRAFT"
        assert get_grant(grant["id"])["committed_cents"] == 0

    def test_grant_close_with_submitted_po_rejected(self, api):
        """PRD §3.3: "A `FinanceManager` closes an `ACTIVE` grant only when no purchase order referencing it remains `SUBMITTED`; an open submitted order blocks the close with `ERR_GRANT_HAS_OPEN_POS`."

        Design: Corner/validations/grant_close_with_submitted_po_rejected
        """
        grant = create_active_grant(total_amount_cents=100000, grant_code="GR-C")
        po = create_draft_po(grant["id"], lines=[purchase_line("SIZE_1", 1, 1000)])
        submit_po(po["id"])

        resp = api.close_grant(grant["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_GRANT_HAS_OPEN_POS)

        grant_after = get_grant(grant["id"])
        assert grant_after["status"] == "ACTIVE", "A blocked close leaves the grant ACTIVE"
        assert grant_after["committed_cents"] == 1000


class TestIntakeValuationVariants:
    def test_intake_valuation_donation_vs_purchase_variants(self, api):
        """PRD §3.2: "Its `valued_total_cents` prices each line at a published fair-market table — 35 cents per `NEWBORN` diaper, 32 per `SIZE_1`, 30 per `SIZE_2`, 28 per `SIZE_3`, 26 per `SIZE_4`, 24 per `SIZE_5`, 22 per `SIZE_6`, and 40 cents per `TRAINING_PANTS` unit — and sums the results."
        PRD §3.2: "A second valuation variant exists for purchased product: batches created by receiving a purchase order carry `source_type` `PURCHASE`, reference their order through `purchase_order_id`, leave `donor_name` null, and are valued at the actual invoiced `unit_cost_cents` of the matching purchase-order line for each size, so identical quantities under the two source types generally produce different valuations."
        PRD §3.3: "a new intake batch is created directly in `POSTED` status with `source_type` `PURCHASE`, the order's id as its `purchase_order_id`, and the received lines as its `lines`, adding each received quantity to the inventory's `on_hand_units`"

        Design: Corner/calculations/intake_valuation_donation_vs_purchase_variants
        """
        init_inventory()
        donation = create_donation_batch([supply_line("SIZE_1", 500)],
                                         donor_name="Donor Val")
        assert donation["valued_total_cents"] == 16000, (
            "Donation variant: 500 SIZE_1 at the 32-cent fair-market rate"
        )

        grant = create_active_grant(total_amount_cents=1000000, grant_code="GR-V")
        po = create_draft_po(grant["id"], lines=[purchase_line("SIZE_1", 500, 28)])
        submit_po(po["id"])
        received = receive_po(po["id"], [{"size_code": "SIZE_1", "quantity": 500}])

        data, meta = validate_paginated(
            api.list_intake_batches(WAREHOUSE,
                                    params={"purchase_order_id": po["id"]}))
        assert meta["total_count"] == 1
        purchase_batch = data[0]
        assert purchase_batch["source_type"] == "PURCHASE"
        assert purchase_batch["status"] == "POSTED", "Receive posts the batch directly"
        assert purchase_batch["donor_name"] is None
        assert purchase_batch["purchase_order_id"] == po["id"]
        assert purchase_batch["valued_total_cents"] == 14000, (
            "Purchase variant: 500 SIZE_1 at the actual 28-cent invoiced cost"
        )
        assert received["received_intake_batch_id"] == purchase_batch["id"]

        inventory = get_inventory()
        assert size_entry(inventory, "SIZE_1")["on_hand_units"] == 500, (
            "Only the received purchase posts stock; the donation was never posted"
        )
