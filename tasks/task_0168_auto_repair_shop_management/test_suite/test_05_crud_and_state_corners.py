"""Breadth coverage: entity CRUD corners, state-machine corners, and the part
install action endpoint.

Covers corner queue sections: entities, state_machines, endpoints.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    NON_EXISTENT_UUID,
    fixtures as fx,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_technician_headers
from test_helpers import factories as f

SM = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["service_advisor_headers"]
PM = TEST_USERS["parts_manager_headers"]


# ===========================================================================
# entities
# ===========================================================================
class TestEntityCorners:
    def test_customer_creation_returns_all_fields(self, api):
        """PRD §3.1: "A `ServiceAdvisor` or `ShopManager` registers a customer with
        a `full_name`, a `phone` number, and an `email`."
        PRD §2.4: "an integer `version` that begins at its initial value and
        increments by one on each mutation."

        Design: Corner/entities/customer_creation_returns_all_fields
        """
        resp = api.create_customer(
            f.create_customer_payload(full_name="Cora Cust", phone="555-100", email="cora@x.com"),
            SA,
        )
        data = validate_success(resp, 201)
        assert data["full_name"] == "Cora Cust"
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])

    def test_vehicle_missing_required_vin_returns_invalid_request(self, api):
        """PRD §3.1: "a vehicle is created with the owning `customer_id`, its `vin`,
        its `make`, `model`, and `model_year`, and a current `odometer_miles`
        reading."
        PRD §2.6: "the body must be well-formed with required fields present and
        numeric fields within range (`ERR_INVALID_REQUEST`)".

        Design: Corner/entities/vehicle_missing_required_vin_returns_invalid_request
        """
        customer = fx.create_customer(api)
        resp = api.create_vehicle(
            {"customer_id": customer["id"], "make": "Ford", "model": "Focus",
             "model_year": 2015, "odometer_miles": 10000},
            SA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_vehicle_duplicate_vin_returns_error(self, api):
        """PRD §3.1: "The VIN must be unique across all vehicles in the shop — an
        attempt to register a vehicle whose `vin` already exists is rejected with
        `ERR_DUPLICATE_VIN`."

        Design: Corner/entities/vehicle_duplicate_vin_returns_error
        """
        customer = fx.create_customer(api)
        fx.create_vehicle(api, customer["id"], vin="DUPVIN")
        resp = api.create_vehicle(
            f.create_vehicle_payload(customer["id"], vin="DUPVIN"), SA
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VIN.value)

    def test_repair_order_get_nonexistent_returns_not_found(self, api):
        """PRD §2.5: "the system validates them strictly left to right and rejects
        the request with `ERR_NOT_FOUND` at the first identifier that does not
        resolve to an existing resource."

        Design: Corner/entities/repair_order_get_nonexistent_returns_not_found
        """
        resp = api.get_repair_order(NON_EXISTENT_UUID, SM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_technician_skill_level_default_b_applied(self, api):
        """PRD §3.1: "an optional `skill_level`, which is a grade of `A`, `B`, or
        `C` and defaults to `B` when omitted."

        Design: Corner/entities/technician_skill_level_default_b_applied
        """
        resp = api.create_technician(f.create_technician_payload(full_name="Def Tech"), SM)
        data = validate_success(resp, 201)
        assert data["skill_level"] == "B"

    def test_labor_line_book_hours_is_snapshot_computed_not_input(self, api):
        """PRD §3.4: "At creation the line snapshots its `book_hours` from the labor
        operation".

        Design: Corner/entities/labor_line_book_hours_is_snapshot_computed_not_input
        """
        operation = fx.create_labor_operation(api, book_hours=3.0, default_rate_cents=10000)
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
        resp = api.create_labor_line(
            ro["id"], f.create_labor_line_payload(operation["id"]), SM
        )
        data = validate_success(resp, 201)
        assert data["book_hours"] == 3.0, "book_hours must be snapshotted from the operation"

    def test_repair_order_list_paginated_envelope(self, api):
        """PRD §2.3: "Every list-based response includes the following fields in the
        `meta` object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/repair_order_list_paginated_envelope
        """
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
        resp = api.list_repair_orders(SM, params={"customer_id": customer["id"]})
        data, meta = validate_paginated(resp)
        ids = [r["id"] for r in data]
        assert ro["id"] in ids
        assert meta["total_count"] >= 1
        assert meta["has_more"] is False


# ===========================================================================
# state_machines
# ===========================================================================
class TestStateMachineCorners:
    def test_transition_start_from_estimate_returns_invalid_state(self, api):
        """PRD §3.3: "Starting work advances an order from `APPROVED` to
        `IN_PROGRESS`; it requires the order to currently be `APPROVED` (else
        `ERR_INVALID_STATE`)".

        Design: Corner/state_machines/transition_start_from_estimate_returns_invalid_state
        """
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
        resp = api.transition_repair_order(ro["id"], {"action": "START"}, SA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        unchanged = validate_success(api.get_repair_order(ro["id"], SM), 200)
        assert unchanged["status"] == "ESTIMATE"

    def test_inspection_review_from_draft_returns_invalid_state(self, api):
        """PRD §3.10: "Reviewing a submitted inspection, by a `ServiceAdvisor` or
        `ShopManager`, requires it to be `SUBMITTED` (else `ERR_INVALID_STATE`)".

        Design: Corner/state_machines/inspection_review_from_draft_returns_invalid_state
        """
        technician = fx.create_technician(api)
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
        insp = fx.create_inspection(api, ro["id"], technician["id"])
        resp = api.review_inspection(insp["id"], SA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        unchanged = validate_success(api.get_inspection(insp["id"], SM), 200)
        assert unchanged["status"] == "DRAFT"

    def test_inspection_submit_empty_returns_inspection_empty(self, api):
        """PRD §3.10: "Submitting a draft inspection, by a `Technician` or
        `ShopManager`, requires the inspection to be `DRAFT` (else
        `ERR_INVALID_STATE`) and to have at least one item (else
        `ERR_INSPECTION_EMPTY`)".

        Design: Corner/state_machines/inspection_submit_empty_returns_inspection_empty
        """
        technician = fx.create_technician(api)
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
        insp = fx.create_inspection(api, ro["id"], technician["id"])
        resp = api.submit_inspection(insp["id"], make_technician_headers(technician["id"]))
        validate_error(resp, ApiErrorId.ERR_INSPECTION_EMPTY.value)

    def test_core_charge_return_twice_returns_invalid_state(self, api):
        """PRD §3.12: "Recording the old core as returned, by a `PartsManager` or
        `ShopManager`, requires the core charge to be `CHARGED` (else
        `ERR_INVALID_STATE`)".

        Design: Corner/state_machines/core_charge_return_twice_returns_invalid_state
        """
        s = fx.setup_ro_with_charged_core(api, deposit_cents=5000, quantity=1, unit_cost_cents=8000)
        cc_id = s["core_charge"]["id"]
        validate_success(api.return_core_charge(cc_id, PM), 200)
        resp = api.return_core_charge(cc_id, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_repair_order_initial_state_is_estimate(self, api):
        """PRD §3.2: "A new order begins in `ESTIMATE` status."
        PRD §2.4: "an integer `version` that begins at its initial value".

        Design: Corner/state_machines/repair_order_initial_state_is_estimate
        """
        customer, vehicle = fx.create_customer_and_vehicle(api)
        resp = api.create_repair_order(
            f.create_repair_order_payload(customer["id"], vehicle["id"]), SM
        )
        data = validate_success(resp, 201)
        assert data["status"] == "ESTIMATE"
        assert data["grand_total_cents"] == 0
        assert data["version"] == 1

    def test_labor_line_complete_with_open_session_returns_open_time_entry(self, api):
        """PRD §3.4: "it requires the line to be `IN_PROGRESS` or `PAUSED` (else
        `ERR_INVALID_STATE`) and no open session to remain (`open_clock_at` must be
        null, else `ERR_OPEN_TIME_ENTRY`)."

        Design: Corner/state_machines/labor_line_complete_with_open_session_returns_open_time_entry
        """
        state = fx.setup_ro_in_progress(
            api, create_line=False, bay_start="2026-06-09T08:00:00Z", bay_end="2026-06-09T12:00:00Z"
        )
        operation = fx.create_labor_operation(api)
        technician = fx.create_technician(api)
        ll = validate_success(
            api.create_labor_line(
                state["ro"]["id"],
                f.create_labor_line_payload(operation["id"], technician_id=technician["id"]),
                SM,
            ),
            201,
        )
        fx.clock_in(api, ll["id"], technician["id"], "2026-06-09T09:00:00Z")
        resp = api.complete_labor_line(ll["id"], make_technician_headers(technician["id"]))
        validate_error(resp, ApiErrorId.ERR_OPEN_TIME_ENTRY.value)

    def test_ro_cancel_forfeits_charged_cores(self, api):
        """PRD §3.3: "Cancelling moves an order that is in either `ESTIMATE` or
        `APPROVED` status to `CANCELLED` ...; every still-`CHARGED` core charge on
        the order is forfeited to `FORFEITED` as a side effect."

        Design: Corner/state_machines/ro_cancel_forfeits_charged_cores
        """
        s = fx.setup_ro_with_charged_core(api, deposit_cents=4000, quantity=1, unit_cost_cents=9000)
        ro_id = s["ro"]["id"]
        cc_id = s["core_charge"]["id"]
        cancelled = validate_success(
            api.transition_repair_order(ro_id, {"action": "CANCEL"}, SA), 200
        )
        assert cancelled["status"] == "CANCELLED"
        cc = validate_success(api.get_core_charge(cc_id, PM), 200)
        assert cc["status"] == "FORFEITED"


# ===========================================================================
# endpoints
# ===========================================================================
class TestEndpointCorners:
    def test_part_line_install_action_transitions_to_installed(self, api):
        """PRD §3.5: "A `Technician`, `PartsManager`, or `ShopManager` marks a part
        line installed, moving it from `QUOTED` to `INSTALLED`."

        Design: Corner/endpoints/part_line_install_action_transitions_to_installed
        """
        fx.setup_markup_matrix(api, [(0, 0, 20000, 0.40)])
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
        pl = fx.add_part_line(api, ro["id"], "IN-1", 1, 3000, markup_mode="FLAT_BRACKET")
        installed = validate_success(api.install_part_line(pl["id"], PM), 200)
        assert installed["status"] == "INSTALLED"
