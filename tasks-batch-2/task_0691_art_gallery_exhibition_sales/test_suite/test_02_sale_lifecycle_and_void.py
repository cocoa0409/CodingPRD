"""Sale lifecycle: the parallel settlement/shipping dimensions, the cyclic
artwork status under void, void compensations, and terminal lockdown."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_reserved_sale, setup_settled_sale, setup_exhibition_with_placed_artwork,
    setup_invoiced_sale_with_plan,
    create_sale,
    TEST_USERS,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["gallery_admin_headers"]
SALES = TEST_USERS["sales_associate_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


class TestParallelDimensions:
    def test_shipping_advances_while_settlement_stays_reserved(self, api):
        """PRD §3.5: "A sale's fulfilment dimension runs independently of its money
        dimension."
        PRD §3.5: "A `SalesAssociate` or `GalleryAdmin` ships a sale — moving
        `PENDING → SHIPPED` and appending a shipped provenance entry to the
        artwork — only when `shipping_status` is `PENDING` and the sale's
        `settlement_status` is not `VOID`."

        Design: Difficulty/non_linear_state_machine/sale_parallel_settlement_and_shipping_dimensions
        """
        gallery, artist, artwork, sale = setup_reserved_sale(
            sale_overrides={"buyer_state_code": "NY", "gross_amount_cents": 200_000})
        assert sale["settlement_status"] == "RESERVED"
        assert sale["shipping_status"] == "PENDING"
        shipped = validate_success(api.ship_sale(sale["id"], SALES))
        assert shipped["shipping_status"] == "SHIPPED", "shipping advances to SHIPPED"
        assert shipped["settlement_status"] == "RESERVED", \
            "settlement dimension is untouched by shipping"

    def test_sale_may_ship_before_being_settled(self, api):
        """PRD §3.5: "Because the two dimensions are independent, a sale may ship
        before or after it is settled."

        Design: Difficulty/non_linear_state_machine/sale_parallel_settlement_and_shipping_dimensions
        """
        gallery, artist, artwork, sale = setup_reserved_sale(
            sale_overrides={"buyer_state_code": "NY", "gross_amount_cents": 200_000})
        # Ship while RESERVED, then deliver — money dimension never advanced.
        shipped = validate_success(api.ship_sale(sale["id"], SALES))
        assert shipped["shipping_status"] == "SHIPPED"
        delivered = validate_success(api.deliver_sale(sale["id"], SALES))
        assert delivered["shipping_status"] == "DELIVERED"
        assert delivered["settlement_status"] == "RESERVED", \
            "delivering does not settle the money dimension"


class TestArtworkCycleOnVoid:
    def test_artwork_returns_to_consigned_after_void(self, api):
        """PRD §3.5: "Voiding reverts the artwork `RESERVED → CONSIGNED`, appends a
        sale-voided provenance entry, cancels any `ACTIVE` payment plan on the sale
        (moving it to `CANCELLED`)".

        Design: Difficulty/non_linear_state_machine/artwork_cyclic_reserved_back_to_consigned_on_void
        """
        gallery, artist, artwork, sale = setup_reserved_sale(
            sale_overrides={"buyer_state_code": "NY", "gross_amount_cents": 300_000})
        # Reservation moved artwork CONSIGNED -> RESERVED.
        reserved_aw = get_success_data(api.get_artwork(artwork["id"], ADMIN))
        assert reserved_aw["status"] == "RESERVED"
        validate_success(api.void_sale(sale["id"], SALES))
        after = get_success_data(api.get_artwork(artwork["id"], ADMIN))
        assert after["status"] == "CONSIGNED", \
            "void must cycle the artwork back to CONSIGNED"

    def test_void_marks_sale_void(self, api):
        """PRD §3.5: "A `SalesAssociate` or `GalleryAdmin` may void a sale whose
        `settlement_status` is `RESERVED`, `INVOICED`, or `PARTIALLY_PAID` — never
        one already `SETTLED` — moving it to `VOID`."

        Design: Difficulty/non_linear_state_machine/artwork_cyclic_reserved_back_to_consigned_on_void
        """
        gallery, artist, artwork, sale = setup_reserved_sale(
            sale_overrides={"buyer_state_code": "NY", "gross_amount_cents": 300_000})
        voided = validate_success(api.void_sale(sale["id"], SALES))
        assert voided["settlement_status"] == "VOID", "voided sale is VOID"


class TestVoidConservesWallSlot:
    def test_void_releases_slot_and_restores_occupancy(self, api):
        """PRD §3.5: "if the work was placed in the sale's exhibition, sets that
        `PLACED` wall slot to `RELEASED` and recomputes the exhibition's slot
        counts."
        PRD §2.11: "the live `slots_occupied` is the number of wall slots
        currently `PLACED` for the show and `slots_available` is `wall_capacity`
        minus `slots_occupied`, never negative."

        Design: Difficulty/compensating_invariant/sale_void_conserves_wall_slot_occupancy
        """
        gallery, artist, artwork, exhibition, wall_slot = \
            setup_exhibition_with_placed_artwork(wall_capacity=2)
        # Reserve the placed artwork via a sale referencing the exhibition.
        sale = create_sale(gallery["id"], artwork["id"], buyer_state_code="NY",
                           gross_amount_cents=300_000, exhibition_id=exhibition["id"])
        # While reserved, the slot is still PLACED (occupied == 1).
        before = get_success_data(api.get_exhibition(exhibition["id"], ADMIN))
        assert before["slots_occupied"] == 1
        validate_success(api.void_sale(sale["id"], SALES))
        after = get_success_data(api.get_exhibition(exhibition["id"], ADMIN))
        assert after["slots_occupied"] == 0, "void releases the slot"
        assert after["slots_available"] == 2, "availability restored to capacity"

    def test_void_returns_artwork_to_consigned_with_slot_released(self, api):
        """PRD §3.5: "Voiding reverts the artwork `RESERVED → CONSIGNED`".
        PRD §3.3: "A successful placement creates a `WallSlot` in `status` of
        `PLACED`".

        Design: Difficulty/compensating_invariant/sale_void_conserves_wall_slot_occupancy
        """
        gallery, artist, artwork, exhibition, wall_slot = \
            setup_exhibition_with_placed_artwork(wall_capacity=2)
        sale = create_sale(gallery["id"], artwork["id"], buyer_state_code="NY",
                           gross_amount_cents=300_000, exhibition_id=exhibition["id"])
        validate_success(api.void_sale(sale["id"], SALES))
        aw_after = get_success_data(api.get_artwork(artwork["id"], ADMIN))
        assert aw_after["status"] == "CONSIGNED"
        slot_after = get_success_data(api.get_wall_slot(wall_slot["id"], ADMIN))
        assert slot_after["status"] == "RELEASED", "the held slot is RELEASED on void"


class TestInvalidTransitionsAndLockdown:
    def test_settle_reserved_sale_without_invoice_rejected(self, api):
        """PRD §3.5: "A `SalesAssociate` or `GalleryAdmin` settles a sale only when
        `settlement_status` is `INVOICED` or `PARTIALLY_PAID` and
        `amount_collected_cents` exactly equals `buyer_total_cents`".

        Design: Corner/state_machines/settle_from_reserved_without_invoice_returns_invalid_state
        """
        gallery, artist, artwork, sale = setup_reserved_sale(
            sale_overrides={"buyer_state_code": "NY", "gross_amount_cents": 200_000})
        resp = api.settle_sale(sale["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        # No ledger accrual from a rejected settle.
        artist_after = get_success_data(api.get_artist(artist["id"], ADMIN))
        assert artist_after["ledger_accrued_cents"] == 0

    def test_void_settled_sale_rejected_terminal(self, api):
        """PRD §3.5: "A `SalesAssociate` or `GalleryAdmin` may void a sale whose
        `settlement_status` is `RESERVED`, `INVOICED`, or `PARTIALLY_PAID` — never
        one already `SETTLED` — moving it to `VOID`."
        PRD §3.2: "advance to `SOLD` when the sale settles; `SOLD` is terminal."

        Design: Corner/state_machines/settle_sold_artwork_terminal_lockdown
        """
        gallery, artist, artwork, settled = setup_settled_sale(
            sale_overrides={"buyer_state_code": "NY", "gross_amount_cents": 400_000})
        resp = api.void_sale(settled["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        aw_after = get_success_data(api.get_artwork(artwork["id"], ADMIN))
        assert aw_after["status"] == "SOLD", "artwork stays SOLD; no resurrection"

    def test_void_partially_paid_sale_cancels_active_plan(self, api):
        """PRD §3.5: "Voiding reverts the artwork `RESERVED → CONSIGNED`, appends a
        sale-voided provenance entry, cancels any `ACTIVE` payment plan on the sale
        (moving it to `CANCELLED`)".

        Design: Corner/cross_cutting_complexity_layers/cascade_void_cancels_payment_plan
        """
        gallery, artist, artwork, invoiced, plan = setup_invoiced_sale_with_plan(
            gross=400_000, installment_count=4)
        # Post a partial payment so the sale is PARTIALLY_PAID.
        paid = get_success_data(api.post_payment(
            invoiced["id"], f.payment_payload(100_000, invoiced["version"]), SALES))
        assert paid["settlement_status"] == "PARTIALLY_PAID"
        validate_success(api.void_sale(invoiced["id"], SALES))
        plan_after = get_success_data(api.get_payment_plan(plan["id"], SALES))
        assert plan_after["status"] == "CANCELLED", "active plan cancelled on void"
        aw_after = get_success_data(api.get_artwork(artwork["id"], ADMIN))
        assert aw_after["status"] == "CONSIGNED"
        sale_after = get_success_data(api.get_sale(invoiced["id"], SALES))
        assert sale_after["settlement_status"] == "VOID"
