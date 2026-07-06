"""Bean lots: creation invariants, depletion/promotion cascade, reorder boundary."""
import test_helpers as th
from test_helpers import validate_success, validate_error, ApiErrorId


class TestFulfillDepletionCascade:
    def _fulfilled_depleting(self, api, headers):
        th.new_equipment(api, name="esp1", equipment_type="ESPRESSO", headers=headers)
        lot_a = th.new_active_lot(api, origin="ETHIOPIA", roast_level="MEDIUM",
                                  received_grams=54, par_grams=0, price_per_gram_cents=5,
                                  headers=headers)
        lot_b = th.new_bean_lot(api, origin="ETHIOPIA", roast_level="MEDIUM",
                                received_grams=500, par_grams=0, price_per_gram_cents=5,
                                headers=headers)
        shot = th.new_modifier(api, name="Extra Shot", modifier_group="SHOT",
                               surcharge_cents=90, extra_bean_grams=9, headers=headers)
        latte = th.new_menu_item(api, name="Latte LG", category="BEVERAGE", base_price_cents=450,
                                 required_equipment_type="ESPRESSO", size="LARGE", bean_grams=18,
                                 origin_required=True, bean_origin="ETHIOPIA", headers=headers)
        order = th.new_order(api, headers=headers,
                             lines=[{"menu_item_id": latte["id"], "quantity": 2,
                                     "modifier_ids": [shot["id"]]}])
        validate_success(api.fulfill_order(order["id"], headers))
        return lot_a, lot_b

    def test_drawn_lot_reaches_zero_and_depletes(self, api, manager_headers):
        """PRD 3.6: "If a drawn lot's `on_hand_grams` reaches zero it transitions
        `ACTIVE -> DEPLETED`, which in turn auto-activates the oldest `RESERVE` lot
        of that origin by `created_at` ascending."

        Design: Difficulty/transitive_cascade/fulfill_depletes_active_then_promotes_reserve
        """
        lot_a, _ = self._fulfilled_depleting(api, manager_headers)
        fetched = validate_success(api.get_bean_lot(lot_a["id"], manager_headers))
        assert fetched["on_hand_grams"] == 0, f"got {fetched['on_hand_grams']}"
        assert fetched["rotation_status"] == "DEPLETED", f"got {fetched['rotation_status']}"

    def test_reserve_lot_auto_promoted_to_active(self, api, manager_headers):
        """PRD 3.6: "If a drawn lot's `on_hand_grams` reaches zero it transitions
        `ACTIVE -> DEPLETED`, which in turn auto-activates the oldest `RESERVE` lot
        of that origin by `created_at` ascending."

        Design: Difficulty/transitive_cascade/fulfill_depletes_active_then_promotes_reserve
        """
        _, lot_b = self._fulfilled_depleting(api, manager_headers)
        fetched = validate_success(api.get_bean_lot(lot_b["id"], manager_headers))
        assert fetched["rotation_status"] == "ACTIVE", f"got {fetched['rotation_status']}"


def test_log_waste_depletes_and_promotes(api, manager_headers):
    """PRD 3.1: "If logging waste drives an `ACTIVE` lot's `on_hand_grams` to zero,
    that lot transitions `ACTIVE -> DEPLETED` and the oldest `RESERVE` lot of the
    same origin (by `created_at` ascending) is automatically activated if one
    exists."

    Design: Corner/state_machines/log_waste_depletes_active_then_promotes_reserve
    """
    lot_a = th.new_active_lot(api, origin="GUATEMALA", roast_level="MEDIUM", received_grams=100,
                              par_grams=0, price_per_gram_cents=5, headers=manager_headers)
    lot_b = th.new_bean_lot(api, origin="GUATEMALA", roast_level="MEDIUM", received_grams=300,
                            par_grams=0, price_per_gram_cents=5, headers=manager_headers)
    validate_success(api.log_waste(lot_a["id"], {"grams": 100, "reason": "SPOILAGE"}, manager_headers))
    a = validate_success(api.get_bean_lot(lot_a["id"], manager_headers))
    b = validate_success(api.get_bean_lot(lot_b["id"], manager_headers))
    assert a["on_hand_grams"] == 0, f"got {a['on_hand_grams']}"
    assert a["rotation_status"] == "DEPLETED", f"got {a['rotation_status']}"
    assert b["rotation_status"] == "ACTIVE", f"got {b['rotation_status']}"


def test_activate_already_active_lot_rejected(api, manager_headers):
    """PRD 3.1: "Attempting to activate a lot that is already `ACTIVE` is rejected
    with `ERR_ALREADY_ACTIVE`, and any activate or waste-logging attempt against a
    `DEPLETED` lot is rejected with `ERR_LOT_DEPLETED`."

    Design: Corner/state_machines/activate_already_active_lot_rejected
    """
    lot = th.new_active_lot(api, origin="BRAZIL", roast_level="MEDIUM", received_grams=500,
                            par_grams=50, price_per_gram_cents=4, headers=manager_headers)
    resp = api.activate_bean_lot(lot["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_ALREADY_ACTIVE.value)


def test_bean_lot_defaults_on_create(api, manager_headers):
    """PRD 3.1: "A newly created lot starts with `consumed_grams` and
    `waste_grams_total` at zero, `on_hand_grams` equal to `received_grams`, and
    `rotation_status` of `RESERVE`."

    Design: Corner/entities/bean_lot_on_hand_equals_received_on_create
    """
    lot = th.new_bean_lot(api, origin="COLOMBIA", roast_level="DARK", received_grams=800,
                          par_grams=100, price_per_gram_cents=4, headers=manager_headers)
    fetched = validate_success(api.get_bean_lot(lot["id"], manager_headers))
    assert fetched["on_hand_grams"] == 800, f"got {fetched['on_hand_grams']}"
    assert fetched["rotation_status"] == "RESERVE", f"got {fetched['rotation_status']}"


class TestReorderBoundary:
    def test_reorder_needed_true_at_par_inclusive(self, api, manager_headers):
        """PRD 2.9: "it is true exactly when `on_hand_grams` is at most `par_grams`
        (that is, less than or equal to the par threshold — the boundary is
        inclusive)."

        Design: Difficulty/boundary_precision_check/bean_reorder_par_boundary_inclusive
        """
        lot = th.new_bean_lot(api, origin="KENYA", roast_level="LIGHT", received_grams=250,
                              par_grams=250, price_per_gram_cents=6, headers=manager_headers)
        fetched = validate_success(api.get_bean_lot(lot["id"], manager_headers))
        assert fetched["reorder_needed"] is True, f"got {fetched['reorder_needed']}"

    def test_reorder_needed_false_just_above_par(self, api, manager_headers):
        """PRD 2.9: "it is true exactly when `on_hand_grams` is at most `par_grams`
        (that is, less than or equal to the par threshold — the boundary is
        inclusive)."

        Design: Difficulty/boundary_precision_check/bean_reorder_par_boundary_inclusive
        """
        lot = th.new_bean_lot(api, origin="KENYA", roast_level="LIGHT", received_grams=251,
                              par_grams=250, price_per_gram_cents=6, headers=manager_headers)
        fetched = validate_success(api.get_bean_lot(lot["id"], manager_headers))
        assert fetched["reorder_needed"] is False, f"got {fetched['reorder_needed']}"
