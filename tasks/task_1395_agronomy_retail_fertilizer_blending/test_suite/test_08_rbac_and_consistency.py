"""RBAC enforcement, authentication, and cross-cutting consistency."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, AGRON, COMPLIANCE, CREDIT, PLANT, DISPATCH, ADMIN,
    grower_headers,
    create_grower, create_field, create_soil_test, create_nutrient_plan,
    create_product, published_price_sheet, create_prepay_program,
    create_prepay_contract, create_permit_payload)


class TestAuthentication:
    def test_missing_headers_returns_401(self, api):
        """PRD 2.1: "Every request must carry two headers: `X-User-ID` and
        `X-User-Role`. A request missing either header, or carrying an unrecognized
        role value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/auth_missing_headers_returns_401
        """
        resp = api.list_growers(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRBACDenied:
    def test_grower_cannot_create_product(self, api):
        """PRD 2.1: "A request whose role is not permitted for the addressed
        operation, or a `Grower`-role request whose `X-User-ID` does not own the
        addressed grower-scoped resource, is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD 2.1: "products, price sheets, prepay programs, and the logical clock
        belong to `BranchAdmin`."

        Design: Corner/rbac/rbac_grower_cannot_create_product
        """
        grower = create_grower(legal_name="RBAC Farms", credit_limit_cents=100000)
        resp = api.create_product(
            {"name": "UREA 46-0-0", "analysis_n_pct": 46, "analysis_p2o5_pct": 0,
             "analysis_k2o_pct": 0, "form": "DRY"},
            grower_headers(grower))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_plant_operator_cannot_approve_nmp(self, api):
        """PRD 2.1: "recommendation and plan approval, plan suspension and
        reinstatement, and the entire environmental permit lifecycle belong to
        `ComplianceOfficer`."

        Design: Corner/rbac/rbac_plant_operator_cannot_approve_nmp
        """
        grower = create_grower(legal_name="RBAC2 Farms", credit_limit_cents=100000)
        field = create_field(grower, name="RB Field", acres=50)
        plan = create_nutrient_plan(field["id"])
        get_success_data(api.submit_nutrient_plan(plan["id"], AGRON))

        resp = api.approve_nutrient_plan(plan["id"], PLANT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        readback = get_success_data(api.get_nutrient_plan(plan["id"], COMPLIANCE))
        assert readback["status"] == "SUBMITTED", "plan remains SUBMITTED"

    def test_credit_manager_cannot_post_soil_results(self, api):
        """PRD 2.1: "soil sampling, lab results, recommendations, and nutrient-plan
        drafting belong to `Agronomist`."

        Design: Corner/rbac/rbac_credit_manager_cannot_post_soil_results
        """
        grower = create_grower(legal_name="RBAC3 Farms", credit_limit_cents=100000)
        field = create_field(grower, name="RC Field", acres=50)
        st = create_soil_test(field["id"], grower)
        get_success_data(api.record_sampling(st["id"], AGRON))

        resp = api.post_results(st["id"], {"p_ppm": 12, "k_ppm": 90, "ph": 6.1}, CREDIT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        readback = get_success_data(api.get_soil_test(st["id"], AGRON))
        assert readback["status"] == "SAMPLED", "soil test remains SAMPLED"

    def test_grower_cannot_read_other_grower_account(self, api):
        """PRD 2.1: "a `Grower`-role request whose `X-User-ID` does not own the
        addressed grower-scoped resource, is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD 2.1: "When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the
        acting `GrowerAccount`; ownership checks on any resource that references a
        `GrowerAccount` compare the resource's grower foreign-key field to
        `X-User-ID`."

        Design: Corner/rbac/rbac_grower_cannot_read_other_grower_account
        """
        grower_a = create_grower(legal_name="Grower A", credit_limit_cents=100000)
        grower_b = create_grower(legal_name="Grower B", credit_limit_cents=200000)
        resp = api.get_grower(grower_b["id"], grower_headers(grower_a))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_dispatcher_cannot_fund_prepay_contract(self, api):
        """PRD 2.1: "grower accounts, credit posture, payments, and prepay funding
        and refunds belong to `CreditManager`."

        Design: Corner/rbac/rbac_dispatcher_cannot_fund_prepay_contract
        """
        grower = create_grower(legal_name="RBAC5 Farms")
        mop = create_product("MOP 0-0-60", 0, 0, 60)
        published_price_sheet(mop["id"], 44500)
        program = create_prepay_program()
        contract = create_prepay_contract(grower, program["id"], mop["id"], committed_tons=20)

        resp = api.fund_prepay_contract(contract["id"], {"amount_cents": 100000}, DISPATCH)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        readback = get_success_data(api.get_prepay_contract(contract["id"], CREDIT))
        assert readback["funded_cents"] == 0

    def test_agronomist_cannot_manage_permits(self, api):
        """PRD 2.1: "the entire environmental permit lifecycle belong to
        `ComplianceOfficer`."

        Design: Corner/rbac/rbac_agronomist_cannot_manage_permits
        """
        resp = api.create_permit(create_permit_payload(), AGRON)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestImmediateConsistency:
    def test_read_after_write_consistency(self, api):
        """PRD 1 (Introduction): "an immediate consistency model: every mutation,
        together with all of its cascades, is atomic within the request."
        PRD 2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        created = get_success_data(api.create_product(
            {"name": "MAP 11-52-0", "analysis_n_pct": 11, "analysis_p2o5_pct": 52,
             "analysis_k2o_pct": 0, "form": "DRY", "regulated_flag": False},
            ADMIN))
        readback = get_success_data(api.get_product(created["id"], ADMIN))
        assert readback["name"] == "MAP 11-52-0"
        assert readback["analysis_p2o5_pct"] == 52
        assert readback["form"] == "DRY"


class TestNotFound:
    def test_product_get_nonexistent_returns_404(self, api):
        """PRD 2.9: "any unresolved path id yields `ERR_RESOURCE_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/product_get_nonexistent_returns_404
        """
        from test_helpers import NON_EXISTENT_UUID
        resp = api.get_product(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


class TestDefaults:
    def test_field_default_watershed_zone(self, api):
        """PRD 3.2: "an optional `watershed_zone` of `STANDARD`, `PROTECTED`, or
        `CRITICAL` that defaults to `STANDARD`."

        Design: Corner/entities/field_create_default_watershed_zone
        """
        grower = create_grower(legal_name="Defaults Farm", credit_limit_cents=1_000_000)
        resp = api.create_field(grower["id"], {"name": "No Zone Field", "acres": 40}, grower_headers(grower))
        data = validate_success(resp, 201)
        assert data["watershed_zone"] == "STANDARD"

    def test_product_regulated_flag_defaults_false(self, api):
        """PRD 3.4: "an optional `regulated_flag` (default false) marking products
        such as anhydrous ammonia that demand the extra permit check at receipt."

        Design: Corner/entities/product_regulated_flag_defaults_false
        """
        data = validate_success(api.create_product(
            {"name": "MOP 0-0-60", "analysis_n_pct": 0, "analysis_p2o5_pct": 0,
             "analysis_k2o_pct": 60, "form": "DRY"},
            ADMIN), 201)
        assert data["regulated_flag"] is False


class TestSoilTestTransitions:
    def test_results_from_requested_rejected(self, api):
        """PRD 3.2: "Results are immutable afterwards, and `RESULTED` is terminal;
        firing either transition from the wrong state yields
        `ERR_INVALID_TRANSITION`."

        Design: Corner/state_machines/soil_test_results_from_requested_rejected
        """
        grower = create_grower(legal_name="Skip State Farms", credit_limit_cents=1_000_000)
        field = create_field(grower, name="S1", acres=50)
        st = create_soil_test(field["id"], grower)
        assert st["status"] == "REQUESTED", "initial state"

        resp = api.post_results(st["id"], {"p_ppm": 12, "k_ppm": 90, "ph": 6.1}, AGRON)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        readback = get_success_data(api.get_soil_test(st["id"], AGRON))
        assert readback["status"] == "REQUESTED", "the soil test remains REQUESTED"
