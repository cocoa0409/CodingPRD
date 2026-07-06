"""Inventory cascades and reconciliation: the fill -> depletion -> LOW ->
RestockTask cascade, the grams-conservation fill/void invariant, and shrink
reconciliation.

Difficulty-queue instances plus one Corner/calculations instance.
"""
from test_helpers import fixtures, validate_success, validate_paginated
from test_helpers.test_users import TEST_USERS

CLERK = TEST_USERS["store_clerk_headers"]


class TestFillCascadeToLowAndRestock:
    """A single fill depletes the bin, flips it OPEN -> LOW at the reorder
    threshold, and auto-creates a RestockTask in the same atomic step."""

    @staticmethod
    def _fill_into_low(api):
        # capacity 8000, reorder 3000, on_hand 3050; fill net 100 -> 2950 <= 3000.
        return fixtures.setup_final_line(
            api, estimated_gross_g=300, gross_weight_g=300, measured_tare_g=200,
            bin_overrides={"reorder_threshold_g": 3000, "last_recount_g": 3050})

    def test_fill_depletes_bin_to_low(self, api):
        """PRD §2.7: "when a line is finalized, the resolved bin's `on_hand_g` is
        decreased by the line's net weight; if that drives `on_hand_g` to at or
        below the bin's `reorder_threshold_g`, the bin's `status` flips from
        `OPEN` to `LOW` and a `RestockTask` is auto-created for that bin in the
        same step."

        Design: Difficulty/transitive_cascade/fill_depletes_bin_low_creates_restock
        """
        s = self._fill_into_low(api)
        assert s["line"]["net_weight_g"] == 100
        bin_after = validate_success(api.get_bin(s["bin"]["id"], CLERK), 200)
        assert bin_after["on_hand_g"] == 2950
        assert bin_after["status"] == "LOW"

    def test_low_bin_auto_creates_restock_task(self, api):
        """PRD §3.9: "the auto-created `RestockTask` names the `bin_id` and records
        a `requested_fill_g` equal to the bin's `capacity_g` minus its `on_hand_g`
        at creation time, and it starts `OPEN`."

        Design: Difficulty/transitive_cascade/fill_depletes_bin_low_creates_restock
        """
        s = self._fill_into_low(api)
        resp = api.list_restock_tasks(CLERK, params={"bin_id": s["bin"]["id"]})
        tasks, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, "exactly one restock task for the depleted bin"
        assert tasks[0]["status"] == "OPEN"
        assert tasks[0]["requested_fill_g"] == 5050, "capacity 8000 - on_hand 2950"


class TestGramsConservedFillThenVoid:
    """A FINAL fill decrements on_hand by the net weight; the compensating void
    re-increments by the same amount, restoring the recount baseline."""

    def test_fill_decrements_bin_on_hand(self, api):
        """PRD §2.7: "when a line is finalized, the resolved bin's `on_hand_g` is
        decreased by the line's net weight".

        Design: Difficulty/compensating_invariant/grams_conserved_fill_then_void
        """
        s = fixtures.setup_final_line(api, estimated_gross_g=500,
                                      gross_weight_g=500, measured_tare_g=200)  # net 300
        bin_after = validate_success(api.get_bin(s["bin"]["id"], CLERK), 200)
        assert bin_after["on_hand_g"] == 4700, "5000 baseline - 300 net"

    def test_void_restores_bin_on_hand(self, api):
        """PRD §3.5: "Voiding a `FINAL` line is permitted only while the parent
        order's `payment_status` is still `UNPAID` (a captured line cannot be
        voided); it moves the line `FINAL → VOIDED` and returns its `net_weight_g`
        to the bin's `on_hand_g` as a grams-conservation compensating action".

        Design: Difficulty/compensating_invariant/grams_conserved_fill_then_void
        """
        s = fixtures.setup_final_line(api, estimated_gross_g=500,
                                      gross_weight_g=500, measured_tare_g=200)  # net 300
        voided = validate_success(api.void_line(s["line"]["id"], CLERK), 200)
        assert voided["pricing_stage"] == "VOIDED"
        bin_after = validate_success(api.get_bin(s["bin"]["id"], CLERK), 200)
        assert bin_after["on_hand_g"] == 5000, "300 returned to the bin"


def test_recount_partial_dispense_computes_shrink(api):
    """PRD §3.9: "The theoretical book on-hand is the bin's `last_recount_g` minus
    dispensed plus restocked. Shrink is that book on-hand minus the counted
    `physical_g`, and a positive shrink means inventory is missing; the result is
    stored in `last_shrink_g`."
    PRD §3.9: "On commit, the bin's `on_hand_g` and `last_recount_g` are both set
    to `physical_g`".

    Design: Corner/calculations/corner_shrink_reconciliation_partial_dispense
    """
    # Baseline 5000, one FINAL dispense of net 300 (book 4700), recount physical 4650.
    s = fixtures.setup_final_line(api, estimated_gross_g=500,
                                  gross_weight_g=500, measured_tare_g=200,
                                  bin_overrides={"reorder_threshold_g": 100})
    recounted = fixtures.recount_bin(api, bin_id=s["bin"]["id"], physical_g=4650)
    assert recounted["last_shrink_g"] == 50, "book 4700 - physical 4650"
    assert recounted["on_hand_g"] == 4650
    assert recounted["status"] == "OPEN", "shrink 50 <= 200 allowance keeps it dispensable"
