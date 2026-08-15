"""Log load receiving, scaling, access control, and listing."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    api_client, ApiErrorId, NON_EXISTENT_UUID,
    create_log_load, scale_load, deck_load, dispute_load, get_load,
    create_log_load_payload, scale_payload,
    make_scaler_headers, make_sales_rep_headers, make_mill_manager_headers,
)


class TestReceiving:
    def test_create_log_load_computed_input_ignored(self, api):
        """PRD Section 3.1: "The new load enters at `RECEIVED` with `degrade_pct` at zero and no commercial terms yet: `scaled_mbf` and `price_per_mbf_cents` are unset, `purchase_cost_cents` is null, and `decked_at`, `sawing_run_id`, and `days_in_deck` have no meaningful values."

        Design: Corner/entities/create_log_load_computed_input_ignored
        """
        payload = create_log_load_payload(purchase_cost_cents=999)
        res = api.create_log_load(payload, make_scaler_headers())
        data = validate_success(res, 201)
        assert data["status"] == "RECEIVED", f"new load must enter RECEIVED, got {data['status']}"
        assert data["purchase_cost_cents"] is None, (
            f"purchase_cost_cents is computed by scaling; client-supplied 999 must be ignored, got {data['purchase_cost_cents']}"
        )
        assert data["degrade_pct"] == 0
        assert data["days_in_deck"] == 0
        assert isinstance(data["version"], int)

    def test_create_log_load_missing_required_species(self, api):
        """PRD Section 2.7: "Body shape is validated next: missing required fields, wrong types, invalid enum values, non-positive numeric quantities, or empty arrays where an array is required all yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_log_load_missing_required_species
        """
        payload = {"supplier_name": "Olympic Log Co", "log_grade": "SAWLOG_1"}
        res = api.create_log_load(payload, make_scaler_headers())
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_log_load_invalid_enum_rejected(self, api):
        """PRD Section 2.7: "Body shape is validated next: missing required fields, wrong types, invalid enum values, non-positive numeric quantities, or empty arrays where an array is required all yield `ERR_INVALID_REQUEST`."
        PRD Section 2.8: "Species throughout the system are exactly `DOUGLAS_FIR`, `PONDEROSA_PINE`, `HEMLOCK_FIR`, and `CEDAR`."

        Design: Corner/entities/create_log_load_invalid_enum_rejected
        """
        payload = create_log_load_payload(species="REDWOOD_X")
        res = api.create_log_load(payload, make_scaler_headers())
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_load_returns_not_found(self, api):
        """PRD Section 2.7: "Path identifiers are then resolved left to right — each id in the URL must exist before the request proceeds, otherwise `ERR_NOT_FOUND`."

        Design: Corner/entities/get_nonexistent_load_returns_not_found
        """
        res = api.get_log_load(NON_EXISTENT_UUID, make_scaler_headers())
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestAccessControl:
    def test_create_log_load_missing_auth_returns_unauthenticated(self, api):
        """PRD Section 2.1: "A request missing either header, or presenting a role value the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/create_log_load_missing_auth_returns_unauthenticated
        """
        res = api.create_log_load(create_log_load_payload(), headers=None)
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_salesrep_cannot_scale_load_returns_forbidden(self, api):
        """PRD Section 2.1: "Once authenticated, the role is checked against the endpoint's authorized role list; a role not on that list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/salesrep_cannot_scale_load_returns_forbidden
        """
        load = create_log_load()
        res = api.scale_log_load(load["id"], scale_payload(), make_sales_rep_headers())
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        after = get_load(load["id"])
        assert after["status"] == "RECEIVED", f"forbidden scale must not mutate, got {after['status']}"

    def test_forbidden_role_beats_not_found(self, api):
        """PRD Section 2.7: "Authentication comes first: missing or invalid headers yield `ERR_UNAUTHENTICATED` before anything else is examined, and an authenticated role not permitted on the endpoint yields `ERR_FORBIDDEN` next. Path identifiers are then resolved left to right — each id in the URL must exist before the request proceeds, otherwise `ERR_NOT_FOUND`."

        Design: Corner/validations/forbidden_role_beats_not_found
        """
        res = api.scale_log_load(NON_EXISTENT_UUID, scale_payload(), make_sales_rep_headers())
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestScaleStateGuards:
    def test_scale_decked_load_returns_invalid_state(self, api):
        """PRD Section 3.1: "Attempting to scale a load that is not `RECEIVED`, dispute one that is not `SCALED`, or resolve one that is not `DISPUTED` is an `ERR_INVALID_STATE` rejection."

        Design: Corner/state_machines/scale_decked_load_returns_invalid_state
        """
        load = create_log_load()
        scale_load(load["id"], scaled_mbf=100, price_per_mbf_cents=25000)
        deck_load(load["id"])
        res = api.scale_log_load(
            load["id"], scale_payload(scaled_mbf=90, price_per_mbf_cents=24000), make_scaler_headers()
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = get_load(load["id"])
        assert after["scaled_mbf"] == 100, f"rejected scale must not overwrite, got {after['scaled_mbf']}"

    def test_scale_decked_load_missing_field_returns_invalid_request(self, api):
        """PRD Section 2.7: "Body shape is validated next: missing required fields, wrong types, invalid enum values, non-positive numeric quantities, or empty arrays where an array is required all yield `ERR_INVALID_REQUEST`. Only after the request is well-formed does the server evaluate entity state preconditions for the invoked transition (`ERR_INVALID_STATE`, or `ERR_CONTRACT_NOT_ACTIVE` where a contract order is involved), then business-temporal rules (schedule windows), then business constraints (chamber and line occupancy, deck capacity, run log-set integrity), then referential linkage (species and grade agreement), and finally fiscal rules (contract volume, price-list availability, allocation pool sufficiency, byproduct on-hand)."

        Design: Corner/validations/scale_decked_load_missing_field_returns_invalid_request
        """
        load = create_log_load()
        scale_load(load["id"], scaled_mbf=100, price_per_mbf_cents=25000)
        deck_load(load["id"])
        # Missing scaled_mbf entirely; the load is also in the wrong state.
        res = api.scale_log_load(load["id"], {"price_per_mbf_cents": 24000}, make_scaler_headers())
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestScaleDisputeCycle:
    def test_dispute_cycle_replaces_commercial_terms(self, api):
        """PRD Section 3.1: "Resolution is the `MillManager`'s prerogative: resolving a `DISPUTED` load returns it to `SCALED`, replaces `scaled_mbf` and `price_per_mbf_cents` with the resolved figures supplied on the resolution call, recomputes `purchase_cost_cents` from those new figures with the same half-up-to-whole-cents rule, and increments `version` again."

        Design: Difficulty/non_linear_state_machine/log_load_scale_dispute_cycle
        """
        load = create_log_load()
        scaled = scale_load(load["id"], scaled_mbf=100, price_per_mbf_cents=25000)
        assert scaled["purchase_cost_cents"] == 2500000, (
            f"round(100 * 25000, 0) = 2500000, got {scaled['purchase_cost_cents']}"
        )
        disputed = dispute_load(load["id"])
        assert disputed["status"] == "DISPUTED", f"first lap of the cycle, got {disputed['status']}"
        resolved = validate_success(api.resolve_scale_log_load(
            load["id"], scale_payload(scaled_mbf=96, price_per_mbf_cents=26000),
            make_mill_manager_headers(),
        ), 200)
        assert resolved["status"] == "SCALED", f"resolution returns the load to SCALED, got {resolved['status']}"
        assert resolved["purchase_cost_cents"] == 2496000, (
            f"resolution replaces terms: round(96 * 26000, 0) = 2496000, got {resolved['purchase_cost_cents']}"
        )

    def test_dispute_cycle_increments_version_each_lap(self, api):
        """PRD Section 2.4: "Most resources additionally carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and an integer `version` field that starts at creation and increments by exactly 1 on every state transition or mutating update applied to that resource."
        PRD Section 3.1: "The dispute loop `SCALED` → `DISPUTED` → `SCALED` is unbounded — a load may cycle through dispute and resolution any number of times, each resolution replacing the commercial terms wholesale."

        Design: Difficulty/non_linear_state_machine/log_load_scale_dispute_cycle
        """
        load = create_log_load()
        v0 = load["version"]
        scaled = scale_load(load["id"], scaled_mbf=100, price_per_mbf_cents=25000)
        assert scaled["version"] == v0 + 1, f"scale increments by exactly 1: {v0} -> {scaled['version']}"
        disputed = dispute_load(load["id"])
        assert disputed["version"] == v0 + 2, f"dispute increments by exactly 1: {v0 + 1} -> {disputed['version']}"
        resolved = validate_success(api.resolve_scale_log_load(
            load["id"], scale_payload(scaled_mbf=96, price_per_mbf_cents=26000),
            make_mill_manager_headers(),
        ), 200)
        assert resolved["version"] == v0 + 3, f"resolve increments by exactly 1: {v0 + 2} -> {resolved['version']}"
        assert resolved["scaled_mbf"] == 96 and resolved["price_per_mbf_cents"] == 26000


class TestListing:
    def test_pagination_and_status_filter_on_log_loads(self, api):
        """PRD Section 2.3: "Every list response sorts by `created_at` ascending, and every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` is the full count of matching resources ignoring pagination and `has_more` indicates whether further pages exist beyond the returned window."
        PRD Section 3.9: "Log loads list with optional `status`, `species`, and `sawing_run_id` filters; lumber packages list with optional `status`, `species`, `grade`, `sales_order_id`, `kiln_charge_id`, and `sawing_run_id` filters; sales orders list with optional `contract_id` and `status` filters; and all lists paginate per §2.3."

        Design: Corner/entities/pagination_and_status_filter_on_log_loads
        """
        l1 = create_log_load(supplier_name="A")
        scale_load(l1["id"], scaled_mbf=10, price_per_mbf_cents=25000)
        l2 = create_log_load(supplier_name="B", species="CEDAR", log_grade="UTILITY")
        scale_load(l2["id"], scaled_mbf=10, price_per_mbf_cents=20000)
        create_log_load(supplier_name="C", species="HEMLOCK_FIR", log_grade="PEELER")

        page, meta = validate_paginated(api.list_log_loads(make_scaler_headers(), params={"limit": 2}))
        assert len(page) == 2, f"limit=2 page must carry 2 items, got {len(page)}"
        assert meta["total_count"] == 3, f"total_count ignores pagination, got {meta['total_count']}"
        assert meta["has_more"] is True, "a third load lies beyond the window"

        filtered, fmeta = validate_paginated(
            api.list_log_loads(make_scaler_headers(), params={"status": "SCALED"})
        )
        assert len(filtered) == 2, f"two loads are SCALED, got {len(filtered)}"
        assert fmeta["total_count"] == 2
        assert fmeta["has_more"] is False
        assert all(row["status"] == "SCALED" for row in filtered)
