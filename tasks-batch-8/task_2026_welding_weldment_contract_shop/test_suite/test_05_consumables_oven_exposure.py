"""Consumable lot, oven, and exposure control: holding-temperature range,
floor-division exposure minutes, the 240-minute SMAW quarantine boundary,
rebake discipline, and the oven-offline cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_consumable_issue,
    assert_consumable_lot,
    create_consumable_lot,
    create_oven,
    create_shop,
    create_welder,
    get_success_data,
    issue_consumables,
    rebake_lot,
    return_issue,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["shop_admin_headers"]
MATERIAL_CONTROLLER = TEST_USERS["material_controller_headers"]


class TestOvenRegistration:
    @pytest.mark.parametrize("holding_temp_c,accepted", [
        (119, False),
        (301, False),
        (120, True),
        (300, True),
    ])
    def test_oven_creation_rejects_invalid_holding_temp(
            self, api, holding_temp_c, accepted):
        """PRD §3.3: "A `MaterialController` registers each oven with its
        physical `oven_code`, a `holding_temp_c` that must be at least 120
        and at most 300 degrees Celsius, and a `capacity_electrodes_kg`
        giving the maximum electrode mass the oven can hold."
        PRD §2.8: "A request whose body is malformed or missing a required
        field is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/oven_creation_rejects_invalid_holding_temp
        """
        shop = create_shop(shop_name="Oven Range Shop")
        resp = api.create_oven(
            shop["id"],
            {"oven_code": f"OV-{holding_temp_c}",
             "holding_temp_c": holding_temp_c,
             "capacity_electrodes_kg": 500},
            MATERIAL_CONTROLLER)
        if accepted:
            oven = validate_success(resp, 201)
            assert oven["holding_temp_c"] == holding_temp_c, (
                "The [120, 300] window is inclusive at both ends")
        else:
            validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestExposureAccounting:
    def test_exposure_minutes_floor_division(self, api):
        """PRD §3.3: "The issue must still be `OPEN`; the return stamps
        `returned_at_utc` from the shop clock, moves the issue to `RETURNED`,
        and computes its `exposure_minutes` as the whole minutes elapsed
        between `issued_at_utc` and the return, discarding any partial
        minute."

        Design: Corner/calculations/exposure_minutes_floor_division
        """
        shop = create_shop(shop_name="Exposure Floor Shop")
        shop_id = shop["id"]
        welder = create_welder(shop_id, stencil="WC1")
        oven = create_oven(shop_id, oven_code="OV-C1")
        lot = create_consumable_lot(shop_id, oven["id"], lot_number="L-C1",
                                    received_kg=50.0)

        issue = issue_consumables(shop_id, lot["id"], oven["id"],
                                  welder["id"], issued_kg=5.0)
        # 90 seconds elapse between issue and return.
        set_clock("2026-08-01T00:01:30Z")

        returned = return_issue(shop_id, issue["id"])
        assert_consumable_issue(returned)
        assert returned["status"] == "RETURNED"
        assert returned["exposure_minutes"] == 1, (
            f"floor(90s / 60s) == 1 minute, got "
            f"{returned['exposure_minutes']}")

    def test_smaw_exposure_239_minutes_stays_in_oven(self, api):
        """PRD §3.3: "The returned issue's exposure is added to the lot's
        cumulative `exposed_minutes_total`, and the lot is then re-evaluated:
        if the lot is an `SMAW` low-hydrogen lot whose cumulative exposure
        has reached or exceeded 240 minutes — four hours of total atmospheric
        exposure — it is quarantined; otherwise it returns to `IN_OVEN` while
        any `remaining_kg` is left, or becomes `EXHAUSTED` once nothing
        remains."

        Design: Corner/calculations/smaw_exposure_limit_boundary
        """
        shop = create_shop(shop_name="Exposure 239 Shop")
        shop_id = shop["id"]
        welder = create_welder(shop_id, stencil="WC2")
        oven = create_oven(shop_id, oven_code="OV-C2")
        lot = create_consumable_lot(shop_id, oven["id"], lot_number="L-239",
                                    received_kg=50.0)

        issue = issue_consumables(shop_id, lot["id"], oven["id"],
                                  welder["id"], issued_kg=5.0)
        set_clock("2026-08-01T03:59:00Z")  # 239 minutes later
        return_issue(shop_id, issue["id"])

        lot_now = get_success_data(
            api.get_consumable_lot(shop_id, lot["id"], ADMIN))
        assert_consumable_lot(lot_now)
        assert lot_now["exposed_minutes_total"] == 239
        assert lot_now["status"] == "IN_OVEN", (
            f"239 minutes is below the 240-minute limit, got "
            f"{lot_now['status']}")

    def test_smaw_exposure_240_minutes_quarantines(self, api):
        """PRD §3.3: "The returned issue's exposure is added to the lot's
        cumulative `exposed_minutes_total`, and the lot is then re-evaluated:
        if the lot is an `SMAW` low-hydrogen lot whose cumulative exposure
        has reached or exceeded 240 minutes — four hours of total atmospheric
        exposure — it is quarantined; otherwise it returns to `IN_OVEN` while
        any `remaining_kg` is left, or becomes `EXHAUSTED` once nothing
        remains."

        Design: Corner/calculations/smaw_exposure_limit_boundary
        """
        shop = create_shop(shop_name="Exposure 240 Shop")
        shop_id = shop["id"]
        welder = create_welder(shop_id, stencil="WC3")
        oven = create_oven(shop_id, oven_code="OV-C3")
        lot = create_consumable_lot(shop_id, oven["id"], lot_number="L-240",
                                    received_kg=50.0)

        issue = issue_consumables(shop_id, lot["id"], oven["id"],
                                  welder["id"], issued_kg=5.0)
        set_clock("2026-08-01T04:00:00Z")  # exactly 240 minutes later
        return_issue(shop_id, issue["id"])

        lot_now = get_success_data(
            api.get_consumable_lot(shop_id, lot["id"], ADMIN))
        assert lot_now["exposed_minutes_total"] == 240
        assert lot_now["status"] == "QUARANTINED", (
            f"Reaching 240 minutes quarantines the SMAW lot (inclusive), "
            f"got {lot_now['status']}")


class TestLotRebake:
    def test_lot_rebake_from_in_oven_returns_invalid_state(self, api):
        """PRD §3.3: "Rebaking — a `MaterialController` action — requires
        that the lot be `QUARANTINED` (otherwise `ERR_LOT_NOT_QUARANTINED`),
        that its `rebake_count` still be below 1, since AWS D1.1 permits at
        most one rebake (otherwise `ERR_LOT_REBAKE_LIMIT`), and that the oven
        referenced for the rebake be `ONLINE`."

        Design: Corner/state_machines/lot_rebake_from_in_oven_returns_invalid_state
        """
        shop = create_shop(shop_name="Rebake State Shop")
        shop_id = shop["id"]
        oven = create_oven(shop_id, oven_code="OV-Q3")
        lot = create_consumable_lot(shop_id, oven["id"], lot_number="L-Q3",
                                    received_kg=50.0)
        assert lot["status"] == "IN_OVEN"

        resp = api.rebake_lot(shop_id, lot["id"], {}, MATERIAL_CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_QUARANTINED)

    def test_lot_rebake_limit_enforced(self, api):
        """PRD §3.3: "Rebaking — a `MaterialController` action — requires
        that the lot be `QUARANTINED` (otherwise `ERR_LOT_NOT_QUARANTINED`),
        that its `rebake_count` still be below 1, since AWS D1.1 permits at
        most one rebake (otherwise `ERR_LOT_REBAKE_LIMIT`), and that the oven
        referenced for the rebake be `ONLINE`."
        PRD §3.3: "A lot that is quarantined while its `rebake_count` is
        already 1 has exhausted its rebake and remains `QUARANTINED`
        permanently."

        Design: Corner/state_machines/lot_rebake_limit_enforced
        """
        shop = create_shop(shop_name="Rebake Limit Shop")
        shop_id = shop["id"]
        welder = create_welder(shop_id, stencil="WQ4")
        oven = create_oven(shop_id, oven_code="OV-Q4")
        lot = create_consumable_lot(shop_id, oven["id"], lot_number="L-Q4",
                                    received_kg=50.0)

        # First quarantine: oven offline voids the open issue and quarantines
        # the issued lot; then bring the oven back online.
        issue_consumables(shop_id, lot["id"], oven["id"], welder["id"],
                          issued_kg=5.0)
        get_success_data(
            api.take_oven_offline(shop_id, oven["id"], MATERIAL_CONTROLLER))
        get_success_data(
            api.bring_oven_online(shop_id, oven["id"], MATERIAL_CONTROLLER))

        # First (and only permitted) rebake.
        rebaked = rebake_lot(shop_id, lot["id"])
        assert rebaked["status"] == "IN_OVEN"
        assert rebaked["rebake_count"] == 1
        assert rebaked["exposed_minutes_total"] == 0

        # Re-issue and re-quarantine the same lot.
        issue_consumables(shop_id, lot["id"], oven["id"], welder["id"],
                          issued_kg=5.0)
        get_success_data(
            api.take_oven_offline(shop_id, oven["id"], MATERIAL_CONTROLLER))
        get_success_data(
            api.bring_oven_online(shop_id, oven["id"], MATERIAL_CONTROLLER))
        lot_now = get_success_data(
            api.get_consumable_lot(shop_id, lot["id"], ADMIN))
        assert lot_now["status"] == "QUARANTINED"
        assert lot_now["rebake_count"] == 1

        resp = api.rebake_lot(shop_id, lot["id"], {}, MATERIAL_CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_LOT_REBAKE_LIMIT)


class TestOvenOfflineCascade:
    def _issued_lot(self, api):
        shop = create_shop(shop_name="Offline Cascade Shop")
        shop_id = shop["id"]
        welder = create_welder(shop_id, stencil="W-OC")
        oven = create_oven(shop_id, oven_code="OV-OC")
        lot = create_consumable_lot(shop_id, oven["id"], lot_number="L-OC",
                                    received_kg=50.0)
        issue = issue_consumables(shop_id, lot["id"], oven["id"],
                                  welder["id"], issued_kg=5.0)
        return shop, oven, lot, issue

    def test_take_offline_quarantines_issued_lot(self, api):
        """PRD §3.3: "Taking an oven offline cascades through its contents:
        every lot in that oven whose status is `ISSUED` with an issue still
        `OPEN` is cascaded to `QUARANTINED`, and those open issues are voided
        to `VOID`."

        Design: Difficulty/transitive_cascade/oven_offline_cascade_depth_2
        """
        shop, oven, lot, _ = self._issued_lot(api)
        shop_id = shop["id"]
        # A second lot that stays IN_OVEN (never issued).
        shelved = create_consumable_lot(shop_id, oven["id"],
                                        lot_number="L-SHELVED",
                                        received_kg=10.0)

        oven_now = validate_success(
            api.take_oven_offline(shop_id, oven["id"], MATERIAL_CONTROLLER),
            200)
        assert oven_now["status"] == "OFFLINE"

        lot_now = get_success_data(
            api.get_consumable_lot(shop_id, lot["id"], ADMIN))
        assert lot_now["status"] == "QUARANTINED", (
            "Issued lot with an open issue must quarantine on oven offline")

        # PRD §3.3: "Lots sitting `IN_OVEN` remain `IN_OVEN`, but nothing may
        # be issued from the oven until it is back online."
        shelved_now = get_success_data(
            api.get_consumable_lot(shop_id, shelved["id"], ADMIN))
        assert shelved_now["status"] == "IN_OVEN"

    def test_take_offline_voids_open_issues_and_blocks_new_issues(self, api):
        """PRD §3.3: "Taking an oven offline cascades through its contents:
        every lot in that oven whose status is `ISSUED` with an issue still
        `OPEN` is cascaded to `QUARANTINED`, and those open issues are voided
        to `VOID`."
        PRD §3.3: "The issue is permitted only when the oven is `ONLINE`
        (otherwise `ERR_OVEN_NOT_ONLINE`), the lot is sitting `IN_OVEN`
        (otherwise `ERR_LOT_NOT_IN_OVEN`), and the lot's `remaining_kg` is at
        least the `issued_kg` requested (otherwise
        `ERR_INSUFFICIENT_LOT_QUANTITY`)."

        Design: Difficulty/transitive_cascade/oven_offline_cascade_depth_2
        """
        shop, oven, lot, issue = self._issued_lot(api)
        shop_id = shop["id"]

        get_success_data(
            api.take_oven_offline(shop_id, oven["id"], MATERIAL_CONTROLLER))

        issue_now = get_success_data(
            api.get_consumable_issue_flat(issue["id"], ADMIN))
        assert issue_now["status"] == "VOID", (
            "The open issue must be voided by the oven-offline cascade")

        resp = api.create_consumable_issue(
            shop_id,
            {"lot_id": lot["id"], "oven_id": oven["id"],
             "issued_to_welder_id": issue["issued_to_welder_id"],
             "issued_kg": 1.0},
            MATERIAL_CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_OVEN_NOT_ONLINE)
