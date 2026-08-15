"""Authentication, role authorization, and the response envelope (PRD §2)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    create_customer, create_profile, create_die, create_formulation,
    publish_index_points,
)

PM = TEST_USERS["plant_manager_headers"]
PE = TEST_USERS["process_engineer_headers"]
LO = TEST_USERS["line_operator_headers"]
QI = TEST_USERS["quality_inspector_headers"]
SE = TEST_USERS["sales_engineer_headers"]


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api.create_customer(
            {"name": "Acme", "resin_index_basis": "MONTHLY_AVG",
             "credit_limit_cents": 10000000},
            {"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_role_gate_precedes_existence_check(self, api):
        """PRD §2.8: "Authentication comes first: missing or malformed identity
        headers surface `ERR_UNAUTHENTICATED` before anything else is examined.
        Role authorization follows, surfacing `ERR_UNAUTHORIZED_ROLE`. Third
        comes existence: every referenced resource must exist, validated
        left-to-right — path identifiers first, in path order, then
        body-referenced identifiers in the order the request body declares them —
        with the first missing reference surfacing `ERR_NOT_FOUND`."

        Design: Corner/validations/role_checked_before_existence
        """
        # LineOperator may not drive die transitions; the die id does not exist.
        resp = api.transition_die(NON_EXISTENT_UUID, {"to": "TRIAL"}, LO)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestRoleAuthorization:
    def test_line_operator_cannot_create_customer(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized
        role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.1: "a `PlantManager` owns customers and their credit posture,
        publishes and restates resin index points, posts manual tooling
        amortization adjustments, invoices closed orders, and sets the logical
        clock."

        Design: Corner/validations/customer_create_forbidden_for_operator
        """
        resp = api.create_customer(
            {"name": "Acme", "resin_index_basis": "MONTHLY_AVG",
             "credit_limit_cents": 10000000}, LO)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_quality_inspector_cannot_create_work_order(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized
        role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.1: "A `SalesEngineer` owns the commercial order lifecycle:
        creating, confirming, repricing, and cancelling work orders."

        Design: Corner/rbac/quality_inspector_cannot_create_work_order
        """
        publish_index_points((("2026-08", 140.0),))
        cust = create_customer()
        prof = create_profile(cust["id"])
        die = create_die(prof["id"])
        form = create_formulation(prof["id"])
        resp = api.create_work_order(
            {"customer_id": cust["id"], "profile_id": prof["id"],
             "formulation_id": form["id"], "die_id": die["id"],
             "ordered_length_m": 5000, "cut_length_mm": 2000,
             "pieces_per_bundle": 25, "base_unit_price_cents_per_m": 1000}, QI)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestReferentialIntegrity:
    def test_work_order_with_other_customers_profile_rejected(self, api):
        """PRD §3.4: "Referential integrity is enforced before anything else
        domain-specific: the profile must belong to the order's customer, the
        formulation must belong to the order's profile, and the die must belong
        to the order's profile; any mismatch is rejected with `ERR_BAD_REQUEST`."

        Design: Corner/validations/work_order_referential_mismatch_rejected
        """
        publish_index_points((("2026-08", 140.0),))
        cust_a = create_customer(name="Acme A")
        cust_b = create_customer(name="Acme B")
        prof_a = create_profile(cust_a["id"], profile_code="P-A")
        die = create_die(prof_a["id"])
        form = create_formulation(prof_a["id"], formula_code="F-A")
        resp = api.create_work_order(
            {"customer_id": cust_b["id"], "profile_id": prof_a["id"],
             "formulation_id": form["id"], "die_id": die["id"],
             "ordered_length_m": 5000, "cut_length_mm": 2000,
             "pieces_per_bundle": 25, "base_unit_price_cents_per_m": 1000}, SE)
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST)


class TestRetrievalAndEnvelope:
    def test_profile_get_roundtrip_preserves_control_plan(self, api):
        """PRD §3.1: "First, the quality plan: `critical_dimensions`, a non-empty
        array of dimension specifications, each naming the dimension via `name`
        and giving its `nominal_mm`, the tolerances `tol_plus_mm` and
        `tol_minus_mm`, and the control limits `ucl_mm` and `lcl_mm`; alongside
        `spc_subgroup_size`, the number of measurements each SPC sample must
        contain, and `sample_every_m`, the metres of good output that trigger
        one required sample."

        Design: Corner/entities/profile_get_roundtrip
        """
        cust = create_customer(resin_index_basis="SHIPMENT_DATE")
        dims = [{"name": "wall", "nominal_mm": 2.0, "tol_plus_mm": 0.1,
                 "tol_minus_mm": 0.1, "ucl_mm": 2.05, "lcl_mm": 1.95}]
        created = validate_success(api.create_profile(
            {"customer_id": cust["id"], "profile_code": "P-RT",
             "critical_dimensions": dims, "spc_subgroup_size": 3, "sample_every_m": 2000,
             "resin_content_kg_per_m": 0.8, "min_line_speed_mpm": 10,
             "max_line_speed_mpm": 40}, PE), 201)
        fetched = get_success_data(api.get_profile(created["id"], PE))
        assert fetched["customer_id"] == cust["id"]
        assert fetched["critical_dimensions"][0]["ucl_mm"] == pytest.approx(2.05)
        assert fetched["critical_dimensions"][0]["lcl_mm"] == pytest.approx(1.95)
        assert fetched["critical_dimensions"][0]["nominal_mm"] == pytest.approx(2.0)
        assert fetched["spc_subgroup_size"] == 3
        assert fetched["sample_every_m"] == 2000

    def test_success_and_error_envelope_shapes(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape
        """
        cust = create_customer()
        ok = api.get_customer(cust["id"], PM)
        data = validate_success(ok, 200)  # validator checks meta + response_type
        assert data["id"] == cust["id"]
        body = ok.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")

        err = api.get_customer(NON_EXISTENT_UUID, PM)
        validate_error(err, ApiErrorId.ERR_NOT_FOUND)
        err_body = err.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
