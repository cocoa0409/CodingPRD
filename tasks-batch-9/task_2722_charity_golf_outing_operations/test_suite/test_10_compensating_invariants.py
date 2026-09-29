"""Forward walks undone in one step, with the conserved quantity re-checked.

The first case conserves integer inventory counters; the second conserves a
signed money ledger that is append-only, so nothing is ever edited away.
"""

from test_helpers import (
    TREASURER_HEADERS,
    ApiErrorId,
    assert_inventory_conservation,
    assert_receipt_ledger,
    assert_receipt_numbers_sequential,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

CONSERVATION_OUTING = {
    "name": "Conservation Open",
    "field_capacity_teams": 1,
    "prize_pool_cents": 0,
}
ONE_SIGN_TIER = {
    "code": "GOLD",
    "price_cents": 250000,
    "inventory_cap": 5,
    "entitled_asset_type": "HOLE_SIGN",
    "entitled_asset_count": 1,
}
TRIPLE_SIGN = {
    "label": "Hole 14 triple sign",
    "hole_number": 14,
    "capacity": 3,
    "exclusive": False,
    "list_price_cents": 50000,
}


def _reserved_entitlement_allocation(api):
    """A three-capacity sign carrying one freshly reserved entitlement allocation."""
    ctx = fx.open_outing(api, outing=CONSERVATION_OUTING, tier=ONE_SIGN_TIER, sponsor_tier=True)
    registration = fx.new_registration(
        api, ctx["outing_id"], ctx["tier_id"], buyer_name="Anchor Insurance", player_count=0
    )
    fx.pay_registration(api, registration["id"], 250000)
    asset = fx.new_asset(api, ctx["outing_id"], **TRIPLE_SIGN)
    allocation = fx.new_allocation(api, registration["id"], asset["id"])
    ctx["registration_id"] = registration["id"]
    ctx["asset_id"] = asset["id"]
    ctx["allocation_id"] = allocation["id"]
    return ctx


def _asset_shape(asset):
    """The four inventory numbers plus the derived posture of one unit."""
    return (
        asset["remaining_capacity"],
        asset["reserved_count"],
        asset["committed_count"],
        asset["fulfilled_count"],
        asset["status"],
    )


class TestAllocationReleaseRestoresInventoryConservation:
    """One RELEASE unwinds a three-step forward walk without breaking the identity."""

    def test_the_identity_holds_at_every_step_and_the_release_returns_the_unit(self, api):
        """Occupancy moves between counters on the way out and comes all the way back.

        The PRD writes the inventory rule as an identity: "For each sponsorship
        asset, its declared `capacity` always equals `remaining_capacity` plus
        `reserved_count` plus `committed_count` plus `fulfilled_count`", with
        "`committed_count` counts those at `COMMITTED`, `ARTWORK_APPROVED`, or
        `INSTALLED`". Release is the compensation: "a unit that loses its last
        occupying allocation of any kind falls back to `AVAILABLE`, with
        `remaining_capacity` re-derived to the full declared `capacity` and the
        outing's aggregate counter reduced accordingly."

        Design: Difficulty/compensating_invariant/allocation_release_restores_the_asset_capacity_conservation_identity
        """
        ctx = _reserved_entitlement_allocation(api)

        reserved = fx.read_asset(api, ctx["asset_id"])
        assert _asset_shape(reserved) == (2, 1, 0, 0, "RESERVED")
        assert_inventory_conservation(reserved)

        for action, shape in (
            ("COMMIT", (2, 0, 1, 0, "COMMITTED")),
            ("APPROVE_ARTWORK", (2, 0, 1, 0, "COMMITTED")),
            ("INSTALL", (2, 0, 1, 0, "COMMITTED")),
        ):
            fx.drive_fulfillment(api, ctx["allocation_id"], action)
            asset = fx.read_asset(api, ctx["asset_id"])
            assert _asset_shape(asset) == shape, f"unit shape after {action}"
            assert_inventory_conservation(asset)

        assert fx.read_allocation(api, ctx["allocation_id"])["status"] == "INSTALLED"
        assert fx.read_outing(api, ctx["outing_id"])["reserved_asset_slot_count"] == 1
        assert fx.read_registration(api, ctx["registration_id"])["entitled_asset_balance"] == 0

        released = fx.drive_fulfillment(api, ctx["allocation_id"], "RELEASE")
        assert released["status"] == "RELEASED"

        asset = fx.read_asset(api, ctx["asset_id"])
        assert _asset_shape(asset) == (3, 0, 0, 0, "AVAILABLE")
        assert_inventory_conservation(asset)
        assert fx.read_outing(api, ctx["outing_id"])["reserved_asset_slot_count"] == 0
        assert fx.read_registration(api, ctx["registration_id"])["entitled_asset_balance"] == 1

    def test_a_second_reserve_commit_release_cycle_shows_no_drift(self, api):
        """The entitlement is handed back, so the same cycle runs again to the same numbers.

        The balance is defined as a derivation rather than a decrementing tally:
        "that balance is always the held tier's `entitled_asset_count` minus the
        count of this registration's entitlement-sourced allocations whose status
        is not `RELEASED`", which is what makes the second cycle possible at all.

        Design: Difficulty/compensating_invariant/allocation_release_restores_the_asset_capacity_conservation_identity
        """
        ctx = _reserved_entitlement_allocation(api)
        fx.drive_fulfillment(api, ctx["allocation_id"], "COMMIT")
        fx.drive_fulfillment(api, ctx["allocation_id"], "RELEASE")

        after_first = _asset_shape(fx.read_asset(api, ctx["asset_id"]))
        assert after_first == (3, 0, 0, 0, "AVAILABLE")

        second = fx.new_allocation(api, ctx["registration_id"], ctx["asset_id"])
        assert _asset_shape(fx.read_asset(api, ctx["asset_id"])) == (2, 1, 0, 0, "RESERVED")
        fx.drive_fulfillment(api, second["id"], "COMMIT")
        assert _asset_shape(fx.read_asset(api, ctx["asset_id"])) == (2, 0, 1, 0, "COMMITTED")
        fx.drive_fulfillment(api, second["id"], "RELEASE")

        asset = fx.read_asset(api, ctx["asset_id"])
        assert _asset_shape(asset) == after_first
        assert_inventory_conservation(asset)
        assert fx.read_outing(api, ctx["outing_id"])["reserved_asset_slot_count"] == 0
        assert fx.read_registration(api, ctx["registration_id"])["entitled_asset_balance"] == 1


LEDGER_OUTING = {
    "name": "Ledger Symmetry Open",
    "field_capacity_teams": 1,
    "prize_pool_cents": 0,
}
LEDGER_TIER = {"code": "TEAM4", "price_cents": 120000, "player_slots": 4, "gsv_cents": 24000}
REVERSAL_REASON = "Sponsor asked for the receipt to be reissued to a subsidiary"
IMMUTABLE_FIELDS = (
    "receipt_kind",
    "receipt_number",
    "payment_cents",
    "gsv_cents",
    "deductible_amount_cents",
    "created_at",
)


def _receipted_registration(api):
    """A confirmed 120000 package carrying its first charitable receipt."""
    ctx = fx.open_outing(api, outing=LEDGER_OUTING, tier=LEDGER_TIER)
    registration = fx.new_registration(
        api, ctx["outing_id"], ctx["tier_id"], buyer_name="Ledger Lions", player_count=4
    )
    fx.pay_registration(api, registration["id"], 120000)
    receipt = fx.issue_registration_receipt(api, ctx["outing_id"], registration["id"])
    ctx["registration_id"] = registration["id"]
    ctx["receipt"] = receipt
    return ctx


def _outing_receipts(api, outing_id):
    return validate_success(api.list_receipts(TREASURER_HEADERS, outing_id=outing_id), 200)


class TestReceiptReversalRestoresTheSignedLedger:
    """The correction is an appended mirror row, never an edit of the original."""

    def test_the_reversal_mirrors_every_sign_and_the_total_returns_to_zero(self, api):
        """Two rows survive, and their signed sum is exactly the pre-receipt total.

        The forward receipt reads 96000 because "The `deductible_amount_cents` is
        then the `payment_cents` minus the applicable `gsv_cents`, floored at 0 so
        it is never negative." The correction is defined as a mirror: "A receipt
        of kind `REVERSAL` mirrors the row it reverses with every sign flipped: its
        `payment_cents` is the negation of the original's `payment_cents`, its
        `gsv_cents` the negation of the original's `gsv_cents`, and its
        `deductible_amount_cents` the negation of the original's
        `deductible_amount_cents`." The ledger is the signed sum, since "The
        outing's `receipted_deductible_total_cents` is the signed sum of
        `deductible_amount_cents` over every receipt of the outing, reversals
        included".

        Design: Difficulty/compensating_invariant/receipt_reversal_restores_the_signed_deductible_ledger
        """
        ctx = _receipted_registration(api)
        original = ctx["receipt"]
        assert original["payment_cents"] == 120000
        assert original["gsv_cents"] == 24000
        assert original["deductible_amount_cents"] == 96000
        assert original["receipt_number"] == "GR-0001"
        assert fx.read_outing(api, ctx["outing_id"])["receipted_deductible_total_cents"] == 96000

        reversal = fx.reverse_receipt(api, original["id"], REVERSAL_REASON)
        assert reversal["receipt_kind"] == "REVERSAL"
        assert reversal["reverses_receipt_id"] == original["id"]
        assert reversal["payment_cents"] == -120000
        assert reversal["gsv_cents"] == -24000
        assert reversal["deductible_amount_cents"] == -96000
        assert reversal["receipt_number"] == "GR-0002"

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["receipted_deductible_total_cents"] == 0

        rows = _outing_receipts(api, ctx["outing_id"])
        assert len(rows) == 2
        assert_receipt_numbers_sequential(rows)
        assert_receipt_ledger(outing, rows)

    def test_the_original_row_is_never_touched_and_cannot_be_reversed_twice(self, api):
        """Append-only means the forward row keeps its figures and the ledger cannot go negative.

        Receipts "are append-only in the strongest sense: a `CharitableReceipt`
        carries no `updated_at` and no `version`, no endpoint mutates one, and the
        only correction mechanism is to append a reversal", and a repeat attempt is
        blocked: "A reversal may never itself be reversed, and a receipt that
        already carries a live reversal may not be reversed a second time; both are
        refused with `ERR_RECEIPT_IMMUTABLE`." Because "Appending a reversal clears
        the subject registration's `receipt_issued` flag back to false", a
        corrected forward receipt is admissible and carries the ledger back up.

        Design: Difficulty/compensating_invariant/receipt_reversal_restores_the_signed_deductible_ledger
        """
        ctx = _receipted_registration(api)
        original = ctx["receipt"]
        fx.reverse_receipt(api, original["id"], REVERSAL_REASON)

        second = api.reverse_receipt(
            original["id"], f.reversal_payload("Duplicate reversal attempt"), TREASURER_HEADERS
        )
        validate_error(second, ApiErrorId.RECEIPT_IMMUTABLE.value, 409)
        assert fx.read_outing(api, ctx["outing_id"])["receipted_deductible_total_cents"] == 0

        stored = fx.read_receipt(api, original["id"])
        for field in IMMUTABLE_FIELDS:
            assert stored[field] == original[field], f"{field} was mutated by the reversal"
        assert fx.read_registration(api, ctx["registration_id"])["receipt_issued"] is False

        reissued = fx.issue_registration_receipt(
            api, ctx["outing_id"], ctx["registration_id"]
        )
        assert reissued["receipt_number"] == "GR-0003"
        assert reissued["deductible_amount_cents"] == 96000

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["receipted_deductible_total_cents"] == 96000
        rows = _outing_receipts(api, ctx["outing_id"])
        assert len(rows) == 3
        assert_receipt_ledger(outing, rows)
