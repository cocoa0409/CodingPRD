"""Manufacturer authorizations, diversion controls, and Rx safety gates
(PRD §3.3, §3.5)."""
from test_helpers import (
    ACCOUNT_MANAGER,
    OFFICER,
    ApiErrorId,
    assert_authorization,
    create_active_clinic,
    create_approved_authorization,
    create_authorization,
    create_lot,
    create_order,
    create_product,
    get_authorization,
    get_order,
    get_success_data,
    make_clinic_buyer_headers,
    order_line_spec,
    set_clock,
    setup_rx_scenario,
    sole_line,
    submit_order,
    validate_error,
    validate_success,
)


def _zoetis_auth_payload(clinic_id, valid_from, valid_until, ship_to):
    return {
        "clinic_id": clinic_id,
        "manufacturer_code": "ZOETIS",
        "valid_from": valid_from,
        "valid_until": valid_until,
        "approved_ship_to_address": ship_to,
        "quarterly_quantity_cap": 100,
    }


class TestAuthorizationWindowOverlap:
    def test_authorization_window_shared_boundary_date_conflicts(self, api):
        """PRD §3.3: "Windows are exclusive per clinic and manufacturer: for the
        same `clinic_id` and `manufacturer_code`, no two authorizations in
        `PENDING`, `APPROVED`, or `SUSPENDED` may share any calendar date, and
        because the intervals are closed, one authorization's `valid_from`
        landing exactly on another's `valid_until` is already a conflict —
        reported as `ERR_AUTHORIZATION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/authorization_window_closed_overlap
        """
        clinic = create_active_clinic(clinic_name="Clinic AW",
                                      license_number="LIC-AW",
                                      ship_to_address="18 Groom Gln")
        first = validate_success(api.create_authorization(
            _zoetis_auth_payload(clinic["id"], "2026-01-01", "2026-06-30",
                                 clinic["ship_to_address"]), OFFICER), 201)
        assert_authorization(first)
        assert first["status"] == "PENDING"

        # valid_from 2026-06-30 shares the boundary date 2026-06-30 — conflict
        # under closed-interval semantics.
        resp = api.create_authorization(
            _zoetis_auth_payload(clinic["id"], "2026-06-30", "2026-12-31",
                                 clinic["ship_to_address"]), OFFICER)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_WINDOW_OVERLAP)

    def test_authorization_window_disjoint_successor_accepted(self, api):
        """PRD §3.3: "Windows are exclusive per clinic and manufacturer: for the
        same `clinic_id` and `manufacturer_code`, no two authorizations in
        `PENDING`, `APPROVED`, or `SUSPENDED` may share any calendar date" — a
        successor whose `valid_from` falls strictly after the predecessor's
        `valid_until` shares no date and is accepted.
        PRD §3.3: "A new authorization starts `PENDING` with
        `quantity_approved_this_quarter` at zero."

        Design: Difficulty/resource_temporal_overlap/authorization_window_closed_overlap
        """
        clinic = create_active_clinic(clinic_name="Clinic AW2",
                                      license_number="LIC-AW2",
                                      ship_to_address="18 Groom Gln")
        first = validate_success(api.create_authorization(
            _zoetis_auth_payload(clinic["id"], "2026-01-01", "2026-06-30",
                                 clinic["ship_to_address"]), OFFICER), 201)

        second = validate_success(api.create_authorization(
            _zoetis_auth_payload(clinic["id"], "2026-07-01", "2026-12-31",
                                 clinic["ship_to_address"]), OFFICER), 201)
        assert second["status"] == "PENDING"
        assert second["quantity_approved_this_quarter"] == 0

        unchanged = get_authorization(first["id"])
        assert unchanged["status"] == "PENDING"
        assert unchanged["version"] == first["version"], (
            "The rejected-then-accepted sibling must not mutate the first record")

    def test_authorization_invalid_date_range_rejected(self, api):
        """PRD §3.3: "a validity window from `valid_from` through `valid_until`
        (the window is a closed interval, and `valid_until` before `valid_from`
        is an `ERR_INVALID_REQUEST`)..."

        Design: Corner/entities/authorization_invalid_date_range_rejected
        """
        clinic = create_active_clinic(clinic_name="Clinic DR",
                                      license_number="LIC-DR")
        resp = api.create_authorization(
            _zoetis_auth_payload(clinic["id"], "2026-12-31", "2026-01-01",
                                 clinic["ship_to_address"]), OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAuthorizationLifecycle:
    def test_authorization_revoked_terminal_lockdown(self, api):
        """PRD §3.3: "Revocation is terminal and available from any of
        `PENDING`, `APPROVED`, or `SUSPENDED`, moving the authorization to
        `REVOKED`."
        PRD §3.3: "An `APPROVED` authorization may be suspended (`APPROVED` →
        `SUSPENDED`) ... as does either transition from the wrong source state"
        — i.e. from `REVOKED` the suspend attempt fails with
        `ERR_AUTHORIZATION_INVALID_STATE`.

        Design: Corner/state_machines/authorization_revoked_terminal_lockdown
        """
        clinic = create_active_clinic(clinic_name="Clinic TL",
                                      license_number="LIC-TL")
        auth = create_approved_authorization(clinic["id"])
        revoked = get_success_data(api.revoke_authorization(auth["id"], OFFICER))
        assert revoked["status"] == "REVOKED"

        resp = api.suspend_authorization(auth["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_INVALID_STATE)
        assert get_authorization(auth["id"])["status"] == "REVOKED"

    def test_authorization_suspend_reinstate_cycle_statuses(self, api):
        """PRD §3.3: "An `APPROVED` authorization may be suspended (`APPROVED` →
        `SUSPENDED`), and a `SUSPENDED` one reinstated back to `APPROVED` —
        but reinstatement is only possible while the window is still open, that
        is, while `valid_until` is on or after the current clock date..."

        Design: Difficulty/non_linear_state_machine/authorization_suspend_reinstate_cycle
        """
        clinic = create_active_clinic(clinic_name="Clinic A",
                                      license_number="LIC-A1",
                                      ship_to_address="7 Coral Dr")
        auth = create_approved_authorization(
            clinic["id"], manufacturer_code="ZOETIS",
            valid_from="2026-01-01", valid_until="2026-12-31",
            approved_ship_to_address="7 Coral Dr")
        assert auth["status"] == "APPROVED"

        suspended = get_success_data(api.suspend_authorization(auth["id"], OFFICER))
        assert suspended["status"] == "SUSPENDED"

        reinstated = get_success_data(api.reinstate_authorization(auth["id"], OFFICER))
        assert reinstated["status"] == "APPROVED", (
            "The APPROVED -> SUSPENDED -> APPROVED cycle must complete")

    def test_authorization_cycle_version_increments_monotonically(self, api):
        """PRD §2.5: "`version` (integer): starts at 1 when the resource is
        created and increments by one on every modification."
        PRD §3.3: "An `APPROVED` authorization may be suspended (`APPROVED` →
        `SUSPENDED`), and a `SUSPENDED` one reinstated back to `APPROVED`..."

        Design: Difficulty/non_linear_state_machine/authorization_suspend_reinstate_cycle
        """
        clinic = create_active_clinic(clinic_name="Clinic AV",
                                      license_number="LIC-AV",
                                      ship_to_address="7 Coral Dr")
        auth = create_authorization(clinic["id"], manufacturer_code="ZOETIS")
        assert auth["version"] == 1, "version starts at 1 at creation"

        approved = get_success_data(api.approve_authorization(auth["id"], OFFICER))
        assert approved["version"] == 2
        suspended = get_success_data(api.suspend_authorization(auth["id"], OFFICER))
        assert suspended["version"] == 3
        reinstated = get_success_data(api.reinstate_authorization(auth["id"], OFFICER))
        assert reinstated["version"] == 4, (
            "Four writes (create, approve, suspend, reinstate) advance version 1 -> 4")


class TestRxSafetyGates:
    def test_order_approve_rejected_while_authorization_pending(self, api):
        """PRD §3.5: "For every `RX_PHARMACEUTICAL` line, the clinic must hold a
        ManufacturerAuthorization for that line's manufacturer that is
        `APPROVED` and whose window covers the current clock date on both ends —
        `valid_from` on or before the date and `valid_until` on or after it —
        otherwise the approval is rejected with `ERR_RX_AUTHORIZATION_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/order_approve_requires_approved_authorization
        """
        clinic = create_active_clinic(clinic_name="Clinic X2",
                                      license_number="LIC-X2",
                                      ship_to_address="16 Saddle St")
        product = create_product(sku="RX-X2", product_name="Rimadyl 75mg",
                                 manufacturer_code="ZOETIS",
                                 product_type="RX_PHARMACEUTICAL",
                                 unit_price_cents=10000)
        lot = create_lot(product["id"], qty_on_hand=10)
        # Authorization exists but stays PENDING (never approved).
        create_authorization(clinic["id"], manufacturer_code="ZOETIS",
                             approved_ship_to_address="16 Saddle St")
        order = create_order(clinic["id"], [order_line_spec(product["id"], 1)])
        submit_order(order["id"], clinic["id"])

        resp = api.approve_order(order["id"], ACCOUNT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_RX_AUTHORIZATION_REQUIRED)

        assert get_order(order["id"])["status"] == "SUBMITTED"
        lot_after = get_success_data(api.get_lot(lot["id"], ACCOUNT_MANAGER))
        assert lot_after["qty_allocated"] == 0, (
            "A rejected approval must not allocate stock")

    def test_order_approve_succeeds_once_authorization_approved(self, api):
        """PRD §3.5: "For every `RX_PHARMACEUTICAL` line, the clinic must hold a
        ManufacturerAuthorization for that line's manufacturer that is
        `APPROVED` and whose window covers the current clock date on both ends"
        — once the authorization moves PENDING → APPROVED, the gate passes.
        PRD §3.5: "when every line allocated, the order moves `SUBMITTED` →
        `APPROVED`"

        Design: Difficulty/cross_entity_state_dependency/order_approve_requires_approved_authorization
        """
        clinic = create_active_clinic(clinic_name="Clinic X3",
                                      license_number="LIC-X3",
                                      ship_to_address="16 Saddle St")
        product = create_product(sku="RX-X3", product_name="Rimadyl 25mg",
                                 manufacturer_code="ZOETIS",
                                 product_type="RX_PHARMACEUTICAL",
                                 unit_price_cents=10000)
        create_lot(product["id"], qty_on_hand=10)
        auth = create_authorization(clinic["id"], manufacturer_code="ZOETIS",
                                    approved_ship_to_address="16 Saddle St")
        order = create_order(clinic["id"], [order_line_spec(product["id"], 1)])
        submit_order(order["id"], clinic["id"])

        # Approve the authorization, then the order succeeds.
        get_success_data(api.approve_authorization(auth["id"], OFFICER))
        approved = validate_success(api.approve_order(order["id"], ACCOUNT_MANAGER))
        assert approved["status"] == "APPROVED"
        line = sole_line(order["id"])
        assert line["status"] == "ALLOCATED"
        assert line["lot_id"] is not None

    def test_dea_registration_required_for_controlled_substance(self, api):
        """PRD §3.5: "If any line's product has `is_controlled_substance` set,
        the clinic's `dea_registration_number` must be non-null, otherwise
        `ERR_DEA_REGISTRATION_REQUIRED`."
        PRD §3.1: "it is optional at onboarding and defaults to null, but its
        absence blocks controlled-substance orders later."

        Design: Corner/validations/dea_registration_required_for_controlled_substance
        """
        scenario = setup_rx_scenario(
            product_overrides={"sku": "RX-DEA", "product_name": "Tramadol 50mg",
                               "is_controlled_substance": True})
        clinic = scenario["clinic"]
        product = scenario["product"]
        assert clinic["dea_registration_number"] is None

        order = create_order(clinic["id"], [order_line_spec(product["id"], 1)])
        submit_order(order["id"], clinic["id"])

        resp = api.approve_order(order["id"], ACCOUNT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_DEA_REGISTRATION_REQUIRED)
        assert get_order(order["id"])["status"] == "SUBMITTED"

    def test_ship_to_diversion_mismatch(self, api):
        """PRD §3.5: "Whenever the order carries any prescription line, the
        order's `ship_to_address` must equal the authorization's
        `approved_ship_to_address` exactly — diversion prevention — otherwise
        `ERR_SHIP_TO_DIVERSION_MISMATCH`."

        Design: Corner/validations/ship_to_diversion_mismatch
        """
        clinic = create_active_clinic(clinic_name="Clinic DV",
                                      license_number="LIC-DV",
                                      ship_to_address="1 Auth St")
        product = create_product(sku="RX-DV", product_name="Cerenia 24mg",
                                 manufacturer_code="ZOETIS",
                                 product_type="RX_PHARMACEUTICAL",
                                 unit_price_cents=10000)
        create_lot(product["id"], qty_on_hand=10)
        auth = create_approved_authorization(
            clinic["id"], manufacturer_code="ZOETIS",
            approved_ship_to_address="1 Auth St")
        order = create_order(clinic["id"], [order_line_spec(product["id"], 1)],
                             ship_to_address="9 Other Rd")
        submit_order(order["id"], clinic["id"])

        resp = api.approve_order(order["id"], ACCOUNT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_SHIP_TO_DIVERSION_MISMATCH)

        assert get_order(order["id"])["status"] == "SUBMITTED"
        auth_after = get_authorization(auth["id"])
        assert auth_after["quantity_approved_this_quarter"] == 0, (
            "A rejected approval must not accrue prescription units")


class TestAuthorizationExpirySweep:
    def test_authorization_expiry_via_clock_sweep(self, api):
        """PRD §2.4: "every ManufacturerAuthorization in `APPROVED` whose
        `valid_until` falls strictly before the new current date moves to
        `EXPIRED`"
        PRD §3.5: "For every `RX_PHARMACEUTICAL` line, the clinic must hold a
        ManufacturerAuthorization for that line's manufacturer that is
        `APPROVED` and whose window covers the current clock date on both ends —
        ... otherwise the approval is rejected with
        `ERR_RX_AUTHORIZATION_REQUIRED`."

        Design: Corner/errors/authorization_expiry_via_clock_sweep
        """
        clinic = create_active_clinic(clinic_name="Clinic AX",
                                      license_number="LIC-AX",
                                      ship_to_address="59 Exp Exd")
        product = create_product(sku="RX-AX", product_name="Baytril 68mg",
                                 manufacturer_code="ZOETIS",
                                 product_type="RX_PHARMACEUTICAL",
                                 unit_price_cents=10000)
        create_lot(product["id"], qty_on_hand=10)
        auth = create_approved_authorization(
            clinic["id"], manufacturer_code="ZOETIS",
            valid_from="2026-01-01", valid_until="2026-08-31",
            approved_ship_to_address="59 Exp Exd")
        order = create_order(clinic["id"], [order_line_spec(product["id"], 1)])
        submit_order(order["id"], clinic["id"])

        set_clock("2026-09-01T00:00:00Z")

        auth_after = get_authorization(auth["id"])
        assert auth_after["status"] == "EXPIRED", (
            "valid_until 2026-08-31 falls strictly before 2026-09-01")

        resp = api.approve_order(order["id"], ACCOUNT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_RX_AUTHORIZATION_REQUIRED)
        assert get_order(order["id"])["status"] == "SUBMITTED"


class TestQuarterlyCap:
    def test_quarterly_cap_inclusive_boundary(self, api):
        """PRD §3.5: "The quarterly volume cap is evaluated per distinct
        manufacturer on the order's prescription lines: the authorization's
        `quantity_approved_this_quarter` plus this order's prescription units
        for that manufacturer may reach but must not exceed
        `quarterly_quantity_cap` — the cap is inclusive, so landing exactly on
        it is allowed and only exceeding it yields
        `ERR_QUARTERLY_CAP_EXCEEDED`."
        PRD §3.3: "it accrues the order's prescription units at each approval..."

        Design: Corner/calculations/quarterly_cap_inclusive_boundary
        """
        scenario = setup_rx_scenario(
            clinic_overrides={"clinic_name": "Clinic QC", "license_number": "LIC-QC",
                              "ship_to_address": "41 Cap Ct"},
            product_overrides={"sku": "RX-QC", "product_name": "Clavamox 62.5mg"},
            auth_overrides={"quarterly_quantity_cap": 10},
            lot_qty=50)
        clinic = scenario["clinic"]
        product = scenario["product"]
        auth = scenario["authorization"]

        windows = [("2026-08-03T13:00:00Z", "2026-08-03T15:00:00Z"),
                   ("2026-08-04T13:00:00Z", "2026-08-04T15:00:00Z"),
                   ("2026-08-05T13:00:00Z", "2026-08-05T15:00:00Z")]
        orders = [
            create_order(clinic["id"], [order_line_spec(product["id"], qty)],
                         window_start=w0, window_end=w1)
            for qty, (w0, w1) in zip((6, 4, 1), windows)
        ]
        for order in orders:
            submit_order(order["id"], clinic["id"])

        # 6 units: cumulative 6 <= 10 -> APPROVED.
        first = validate_success(api.approve_order(orders[0]["id"], ACCOUNT_MANAGER))
        assert first["status"] == "APPROVED"
        # 4 more: cumulative 10 == cap -> still allowed (cap is inclusive).
        second = validate_success(api.approve_order(orders[1]["id"], ACCOUNT_MANAGER))
        assert second["status"] == "APPROVED"
        # 1 more: cumulative 11 > 10 -> rejected.
        resp = api.approve_order(orders[2]["id"], ACCOUNT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_QUARTERLY_CAP_EXCEEDED)
        assert get_order(orders[2]["id"])["status"] == "SUBMITTED"

        auth_after = get_authorization(auth["id"])
        assert auth_after["quantity_approved_this_quarter"] == 10
