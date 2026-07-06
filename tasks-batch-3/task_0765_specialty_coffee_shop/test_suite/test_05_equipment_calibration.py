"""Equipment calibration cycle and cross-entity fulfillment gating."""
import test_helpers as th
from test_helpers import validate_success, validate_error, ApiErrorId


class TestCalibrationCycle:
    def _shop_and_order(self, api, headers):
        esp = th.new_equipment(api, name="esp1", equipment_type="ESPRESSO", headers=headers)
        th.new_active_lot(api, origin="ETHIOPIA", roast_level="MEDIUM", received_grams=1000,
                          par_grams=200, price_per_gram_cents=5, headers=headers)
        shot = th.new_modifier(api, name="Extra Shot", modifier_group="SHOT",
                               surcharge_cents=90, extra_bean_grams=9, headers=headers)
        latte = th.new_menu_item(api, name="Latte LG", category="BEVERAGE", base_price_cents=450,
                                 required_equipment_type="ESPRESSO", size="LARGE", bean_grams=18,
                                 origin_required=True, bean_origin="ETHIOPIA", headers=headers)
        order = th.new_order(api, headers=headers,
                             lines=[{"menu_item_id": latte["id"], "quantity": 2,
                                     "modifier_ids": [shot["id"]]}])
        return esp, order

    def test_fulfill_pushes_machine_to_needs_calibration(self, api, manager_headers):
        """PRD 3.6: "this total is added to the `OPERATIONAL` espresso machine's
        `shots_since_calibration`, and if that count reaches the limit of 4 or more,
        the machine transitions `OPERATIONAL -> NEEDS_CALIBRATION`."

        Design: Difficulty/non_linear_state_machine/equipment_calibration_cycle
        """
        esp, order = self._shop_and_order(api, manager_headers)
        validate_success(api.fulfill_order(order["id"], manager_headers))
        fetched = validate_success(api.get_equipment(esp["id"], manager_headers))
        # (1 base + 1 SHOT) * qty 2 = 4 shots -> reaches limit 4
        assert fetched["shots_since_calibration"] == 4, f"got {fetched['shots_since_calibration']}"
        assert fetched["status"] == "NEEDS_CALIBRATION", f"got {fetched['status']}"

    def test_calibrate_returns_operational_and_resets_counter(self, api, manager_headers):
        """PRD 3.3: "Calibrating a machine sets `shots_since_calibration` back to 0,
        sets `calibration_drift_pct` back to 0, and stamps `last_calibrated_at` with
        the current time."
        PRD 3.3: "in the first case it drives the machine
        `NEEDS_CALIBRATION -> OPERATIONAL`, and in the second the machine remains
        `OPERATIONAL` while its counters reset."

        Design: Difficulty/non_linear_state_machine/equipment_calibration_cycle
        """
        esp, order = self._shop_and_order(api, manager_headers)
        validate_success(api.fulfill_order(order["id"], manager_headers))
        calibrated = validate_success(api.calibrate_equipment(esp["id"], manager_headers))
        assert calibrated["status"] == "OPERATIONAL", f"got {calibrated['status']}"
        assert calibrated["shots_since_calibration"] == 0, f"got {calibrated['shots_since_calibration']}"


class TestFulfillBlockedByEquipment:
    def test_fulfill_rejected_when_equipment_offline(self, api, manager_headers):
        """PRD 3.6: "First, every line's menu item must have an `OPERATIONAL` machine
        of its `required_equipment_type`; if any required type has no operational
        machine, fulfillment is rejected with `ERR_EQUIPMENT_UNAVAILABLE`."

        Design: Difficulty/cross_entity_state_dependency/fulfill_blocked_by_non_operational_equipment
        """
        esp = th.new_equipment(api, name="esp1", equipment_type="ESPRESSO", headers=manager_headers)
        th.new_active_lot(api, origin="ETHIOPIA", roast_level="MEDIUM", received_grams=1000,
                          par_grams=200, price_per_gram_cents=5, headers=manager_headers)
        latte = th.new_menu_item(api, name="Latte LG", category="BEVERAGE", base_price_cents=450,
                                 required_equipment_type="ESPRESSO", size="LARGE", bean_grams=18,
                                 origin_required=True, bean_origin="ETHIOPIA", headers=manager_headers)
        order = th.new_order(api, headers=manager_headers,
                             lines=[{"menu_item_id": latte["id"], "quantity": 1, "modifier_ids": []}])
        validate_success(api.create_maintenance_window(
            {"equipment_id": esp["id"], "start_at": "2026-03-02T09:00:00Z",
             "end_at": "2026-03-02T12:00:00Z", "kind": "REPAIR"}, manager_headers), 201)
        resp = api.fulfill_order(order["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_UNAVAILABLE.value)

    def test_fulfillment_status_stays_placed_after_rejection(self, api, manager_headers):
        """PRD 3.6: "Fulfillment is performed by a `Barista` or `Manager` and drives
        `fulfillment_status` `PLACED -> FULFILLED`."
        PRD 3.6: "if any required type has no operational machine, fulfillment is
        rejected with `ERR_EQUIPMENT_UNAVAILABLE`."

        Design: Difficulty/cross_entity_state_dependency/fulfill_blocked_by_non_operational_equipment
        """
        esp = th.new_equipment(api, name="esp1", equipment_type="ESPRESSO", headers=manager_headers)
        th.new_active_lot(api, origin="ETHIOPIA", roast_level="MEDIUM", received_grams=1000,
                          par_grams=200, price_per_gram_cents=5, headers=manager_headers)
        latte = th.new_menu_item(api, name="Latte LG", category="BEVERAGE", base_price_cents=450,
                                 required_equipment_type="ESPRESSO", size="LARGE", bean_grams=18,
                                 origin_required=True, bean_origin="ETHIOPIA", headers=manager_headers)
        order = th.new_order(api, headers=manager_headers,
                             lines=[{"menu_item_id": latte["id"], "quantity": 1, "modifier_ids": []}])
        validate_success(api.create_maintenance_window(
            {"equipment_id": esp["id"], "start_at": "2026-03-02T09:00:00Z",
             "end_at": "2026-03-02T12:00:00Z", "kind": "REPAIR"}, manager_headers), 201)
        api.fulfill_order(order["id"], manager_headers)
        fetched = validate_success(api.get_order(order["id"], manager_headers))
        assert fetched["fulfillment_status"] == "PLACED", f"got {fetched['fulfillment_status']}"


def test_fulfill_insufficient_beans_rejected(api, manager_headers):
    """PRD 3.6: "if an active lot exists but its `on_hand_grams` is less than the
    line's `line_bean_grams`, the rejection is `ERR_INSUFFICIENT_BEANS`."

    Design: Corner/validations/insufficient_beans_on_fulfill_rejected
    """
    th.new_equipment(api, name="esp1", equipment_type="ESPRESSO", headers=manager_headers)
    th.new_active_lot(api, origin="ETHIOPIA", roast_level="MEDIUM", received_grams=10,
                      par_grams=0, price_per_gram_cents=5, headers=manager_headers)
    latte = th.new_menu_item(api, name="Latte MD", category="BEVERAGE", base_price_cents=450,
                             required_equipment_type="ESPRESSO", size="MEDIUM", bean_grams=18,
                             origin_required=True, bean_origin="ETHIOPIA", headers=manager_headers)
    order = th.new_order(api, headers=manager_headers,
                         lines=[{"menu_item_id": latte["id"], "quantity": 1, "modifier_ids": []}])
    resp = api.fulfill_order(order["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BEANS.value)
