"""Validation order of evaluation (PRD §2.11): authentication, schema,
authorization, existence, then the state-vs-safety and safety-vs-fiscal
priority pairs."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    make_customer_headers, make_operator_headers,
    make_customer, make_employee, make_ingredient, add_price_tick,
    make_active_formula, make_order, get_customer,
    setup_medicated_mix_on_line, setup_standard_order_after_med,
    setup_active_grow_formula, create_ingredient_payload,
)

MM = TEST_USERS["mill_manager_headers"]
NUT = TEST_USERS["nutritionist_headers"]


class TestLayerOrdering:
    def test_call_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`."
        PRD §2.11: "Authentication — headers present and role recognized (`ERR_UNAUTHENTICATED`)."

        Design: Corner/validations/call_missing_auth_headers_returns_401
        """
        resp = api.list_contracts(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_schema_invalid_request_beats_forbidden_role(self, api):
        """PRD §2.11: "Request schema — required fields present, types valid, enum members in range, tonnages positive, datetimes parseable, and any planned end strictly after its planned start (`ERR_INVALID_REQUEST`)."
        PRD §2.11: "Authorization — the role is admitted to the endpoint and, for the floor roles, the employee's capability covers the role (`ERR_FORBIDDEN`)."

        Design: Corner/validations/schema_invalid_request_beats_forbidden_role
        """
        customer = make_customer("Acme Farms", 1000000)
        # The Customer role is not admitted to POST /api/ingredients, and the
        # body is also malformed — the schema layer (earlier) reports first.
        resp = api.create_ingredient({"name": "no code field"},
                                     make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_nonexistent_batch_start_returns_404(self, api):
        """PRD §2.11: "Existence — path identifiers resolve left to right, and body identifiers (formula, order, line, bin, ingredient, truck, contract) exist; customer-scoped callers see only their own resources (`ERR_NOT_FOUND`)."

        Design: Corner/validations/nonexistent_batch_start_returns_404
        """
        op = make_employee("Olly Operator", "OPERATOR")
        resp = api.start_batch(NON_EXISTENT_UUID, make_operator_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestStateBeatsSafety:
    def _cancelled_on_contaminated_line(self, api):
        """Line L1 contaminated by a medicated mix; a non-medicated batch on L1
        cancelled while PLANNED (its window freed)."""
        ctx = setup_medicated_mix_on_line()
        batch_std = setup_standard_order_after_med(
            ctx, planned_start_at="2026-05-02T10:00:00Z",
            planned_end_at="2026-05-02T11:00:00Z")
        cancelled = validate_success(api.cancel_batch(batch_std["id"], MM), 200)
        assert cancelled["status"] == "CANCELLED"
        ctx["batch_std"] = cancelled
        return ctx

    def test_cancelled_batch_start_reports_state_error(self, api):
        """PRD §2.11: "State preconditions — transition from-states and cross-entity state requirements, including blocked bins and blocked orders (`ERR_INVALID_STATE`, `ERR_BIN_BLOCKED`, `ERR_ORDER_BLOCKED`)."
        PRD §2.11: "When a request fails several rules at once, the layer that reports first is fixed."

        Design: Difficulty/priority_pair_validation_conflict/start_cancelled_batch_with_flush_due_state_beats_safety
        """
        ctx = self._cancelled_on_contaminated_line(api)
        # The batch is CANCELLED (state layer 6) AND the line needs a flush
        # (safety layer 7): the earlier layer reports.
        resp = api.start_batch(ctx["batch_std"]["id"],
                               make_operator_headers(ctx["op"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cancelled_batch_start_does_not_leak_flush_error(self, api):
        """PRD §2.11: "When a request fails several rules at once, the layer that reports first is fixed. The layers, earliest first:"
        PRD §2.11: "Medicated and safety gates (`ERR_FLUSH_REQUIRED`, `ERR_MEDICATED_PERMIT_REQUIRED`, `ERR_SOD_VIOLATION`, `ERR_QUALITY_NOT_PASSED`, `ERR_CARGO_CLASS_MIX`, `ERR_TRUCK_NOT_MEDICATED_CAPABLE`)."

        Design: Difficulty/priority_pair_validation_conflict/start_cancelled_batch_with_flush_due_state_beats_safety
        """
        ctx = self._cancelled_on_contaminated_line(api)
        line = validate_success(api.get_line(ctx["line"]["id"], MM), 200)
        assert line["contamination"] == "MEDICATED", (
            "the safety gate would fail too, but it is never reached")

        resp = api.start_batch(ctx["batch_std"]["id"],
                               make_operator_headers(ctx["op"]["id"]))
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert err["error_id"] != "ERR_FLUSH_REQUIRED"

        batch = validate_success(api.get_batch(ctx["batch_std"]["id"], MM), 200)
        assert batch["status"] == "CANCELLED"


class TestSafetyBeatsFiscal:
    def _no_permit_thin_credit_setup(self, api):
        """F-MED ACTIVE (med70/SBM30, medicated); customer with NO permit and a
        1000-cent credit limit; a 1t order QUOTED at 35212 cents."""
        med = make_ingredient("MED-A")
        sbm = make_ingredient("SBM")
        add_price_tick(med["id"], 10000)
        add_price_tick(sbm["id"], 52000)
        formula = make_active_formula("F-MED", min_protein_pct=20.0,
                                      max_fiber_pct=5.0, min_energy_kcal_kg=2500)
        customer = make_customer("No Permit Pete", 1000)  # no permit on file
        order = make_order(customer, formula["id"], 1)
        # med 0.7*10000 + SBM 0.3*52000 = 22600; margin 2712; surcharge 1500;
        # delivery 8400 -> quoted 35212, far beyond the 1000-cent limit.
        assert order["quoted_total_cents"] == 35212
        assert order["is_medicated"] is True
        return {"customer": customer, "order": order}

    def test_medicated_confirm_without_permit_reports_safety_error(self, api):
        """PRD §3.5: "a medicated order requires a non-null `medicated_permit_ref` (`ERR_MEDICATED_PERMIT_REQUIRED`); the quote must be fresh (`ERR_QUOTE_STALE`); and `credit_used_cents` plus `quoted_total_cents` must not exceed `credit_limit_cents`, with equality passing (`ERR_CREDIT_LIMIT_EXCEEDED`)."
        PRD §3.5: "Confirmation by the customer moves `QUOTED` → `CONFIRMED` through four gates evaluated in order"

        Design: Difficulty/priority_pair_validation_conflict/confirm_medicated_without_permit_and_over_credit_safety_beats_fiscal
        """
        ctx = self._no_permit_thin_credit_setup(api)
        resp = api.confirm_order(
            ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MEDICATED_PERMIT_REQUIRED)

    def test_medicated_confirm_without_permit_does_not_leak_fiscal_error(self, api):
        """PRD §2.11: "Fiscal gates, evaluated last: quote freshness at confirmation (`ERR_QUOTE_STALE`), then credit headroom (`ERR_CREDIT_LIMIT_EXCEEDED`)."
        PRD §2.11: "Medicated and safety gates (`ERR_FLUSH_REQUIRED`, `ERR_MEDICATED_PERMIT_REQUIRED`, `ERR_SOD_VIOLATION`, `ERR_QUALITY_NOT_PASSED`, `ERR_CARGO_CLASS_MIX`, `ERR_TRUCK_NOT_MEDICATED_CAPABLE`)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_medicated_without_permit_and_over_credit_safety_beats_fiscal
        """
        ctx = self._no_permit_thin_credit_setup(api)
        resp = api.confirm_order(
            ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"]))
        err = validate_error(resp, ApiErrorId.ERR_MEDICATED_PERMIT_REQUIRED)
        assert err["error_id"] != "ERR_CREDIT_LIMIT_EXCEEDED", (
            "the fiscal gate is evaluated last and is never reached")

        order = validate_success(api.get_order(ctx["order"]["id"], MM), 200)
        assert order["status"] == "QUOTED"
        assert get_customer(ctx["customer"]["id"])["credit_used_cents"] == 0
