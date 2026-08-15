"""Cross-reference listings (parent-to-child FK reachability) and immediate
read-after-write consistency of derived fields."""
from test_helpers import (
    TEST_USERS,
    create_lot,
    create_owner,
    create_pen,
    file_claim,
    get_pen,
    record_death_loss,
    validate_success,
)

ANY = TEST_USERS["any_headers"]


class TestReverseFkListings:
    def test_fk_reverse_reachability_lists_children(self, api):
        """PRD §3.1: "Owners can be listed and fetched individually, and each
        owner's lots and billed invoices are readable as nested collections,
        sorted by creation time ascending."
        PRD §3.4: "a lot's death losses and health events are readable as
        collections sorted by creation time ascending."
        PRD §3.5: "A death loss's claims are readable as a collection sorted by
        creation time ascending."

        Design: Corner/endpoints/fk_reverse_reachability_lists_children
        """
        owner = create_owner(owner_name="O-EP1", billing_email="ep1@x.com")
        lot = create_lot(owner["id"], lot_number="L-EP1", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        death_loss = record_death_loss(lot["id"], loss_date="2026-08-01",
                                       head_count=1, insured=True)
        claim = file_claim(death_loss["id"], 100000)

        lots_back = validate_success(api.list_owner_lots(owner["id"], ANY))
        assert isinstance(lots_back, list) and lots_back[0]["id"] == lot["id"]

        losses_back = validate_success(api.list_lot_death_losses(lot["id"], ANY))
        assert isinstance(losses_back, list)
        assert losses_back[0]["id"] == death_loss["id"]

        claims_back = validate_success(
            api.list_death_loss_claims(death_loss["id"], ANY))
        assert isinstance(claims_back, list)
        assert claims_back[0]["id"] == claim["id"]


class TestImmediateConsistency:
    def test_immediate_read_after_write_visibility(self, api):
        """PRD §2.9: "A pen's `current_occupancy_head` is always the sum of
        `head_count` over that pen's `ACTIVE` pen assignments, and the pen flips
        between `EMPTY` and `OCCUPIED` automatically as that sum rises above or
        falls to zero"
        PRD §1: "every aggregate on a lot — head counts, cost accumulators,
        provisional cost of gain — is reconciled immediately as events occur, so
        a reader of the API always sees the yard's current truth"

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        owner = create_owner(owner_name="O-IM1", billing_email="im1@x.com")
        pen = create_pen(pen_code="IM-01", capacity_head=50)
        lot = create_lot(owner["id"], lot_number="L-IM1", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        validate_success(api.create_assignment(
            {"pen_id": pen["id"], "lot_id": lot["id"], "head_count": 5,
             "start_date": "2026-08-01"},
            TEST_USERS["feedyard_manager_headers"],
        ), 201)

        pen_after = get_pen(pen["id"])
        assert pen_after["current_occupancy_head"] == 5, (
            "The very next GET sees the assignment's head in the occupancy sum"
        )
        assert pen_after["status"] == "OCCUPIED"
