"""Chemical applications: raw-vs-authorized divergence, temperature branch,
environmental caps, budget gate, dispense cascade, quota conservation, and
segregation of duties."""
from test_helpers import (
    ApiErrorId,
    assert_product_quota_invariant,
    authorize_application,
    dispense_application,
    get_chemical_application,
    get_chemical_product,
    make_maintenance_lead_headers,
    propose_application,
    setup_event_with_surface,
    setup_proposed_application,
    validate_error,
    validate_success,
    void_application,
)


class TestRawVsAuthorizedDivergence:
    def _setup_capped(self):
        return setup_proposed_application(
            event_code="SNOW-B", product_code="KA-02", seasonal_limit=20000,
            chemical_limit_lbs=100000, budget_cents=50000000,
            pavement_temp_f=20)

    def test_chemical_raw_physics_variant_at_creation(self, api):
        """PRD §3.8: "The raw quantity is the area units multiplied by the
        product's `base_rate_lbs_per_1000sqft` multiplied by the selected
        temperature factor, rounded half up to one decimal place."

        Design: Difficulty/dual_variant_calc/chemical_raw_vs_authorized_environmental_cap_divergence
        """
        ctx = self._setup_capped()
        assert ctx["application"]["raw_quantity_lbs"] == 24750, (
            "planned physics variant: 750 units x 30 lbs x 1.10 = 24750, "
            f"got {ctx['application']['raw_quantity_lbs']}")
        assert ctx["application"]["status"] == "PROPOSED"

    def test_chemical_authorized_variant_capped_by_environment(
            self, api):
        """PRD §3.8: "On successful authorization, `authorized_quantity_lbs`
        is set to the minimum of three values: `raw_quantity_lbs`,
        `event_remaining_lbs`, and `product_available_lbs`. The `capped` flag
        is set to `true` when `authorized_quantity_lbs` is strictly less than
        `raw_quantity_lbs`, and `false` when they are equal."

        Design: Difficulty/dual_variant_calc/chemical_raw_vs_authorized_environmental_cap_divergence
        """
        ctx = self._setup_capped()
        authorized = authorize_application(ctx["application"]["id"])
        assert authorized["authorized_quantity_lbs"] == 20000, (
            "environmental cap binds: min(24750, 100000, 20000) = 20000, "
            f"got {authorized['authorized_quantity_lbs']}")
        assert authorized["capped"] is True
        assert authorized["authorized_quantity_lbs"] != \
            ctx["application"]["raw_quantity_lbs"], (
                "the two variants must diverge when a cap binds")


class TestTemperatureBranch:
    def _setup_two_apps(self):
        ctx = setup_event_with_surface(
            event_code="SNOW-C", chemical_limit_lbs=1000000,
            budget_cents=50000000)
        from test_helpers import create_chemical_product, create_surface
        s2 = create_surface("RWY-09R", priority_rank=2)
        product = create_chemical_product("NAAC-01", base_rate=30,
                                          unit_cost=12,
                                          seasonal_limit=1000000)
        cool = propose_application(ctx["event"]["id"], ctx["surface"]["id"],
                                   product["id"], pavement_temp_f=20)
        cold = propose_application(ctx["event"]["id"], s2["id"],
                                   product["id"], pavement_temp_f=10)
        return ctx, cool, cold

    def test_chemical_quantity_cool_branch(self, api):
        """PRD §3.8: "A temperature factor is selected from `pavement_temp_f`:
        if the temperature is strictly below `15` degrees, the factor is
        `1.25`; if the temperature is between `15` and `28` degrees inclusive,
        the factor is `1.10`; otherwise (strictly above `28`) the factor is
        `1.00`."

        Design: Difficulty/combinatorial_formula/chemical_quantity_temperature_branch_nonlinearity
        """
        ctx, cool, cold = self._setup_two_apps()
        assert cool["raw_quantity_lbs"] == 24750, (
            "20F is inside [15, 28] -> factor 1.10: 750 x 30 x 1.10 = 24750, "
            f"got {cool['raw_quantity_lbs']}")

    def test_chemical_quantity_cold_branch_nonlinear(self, api):
        """PRD §3.8: "if the temperature is strictly below `15` degrees, the
        factor is `1.25`; if the temperature is between `15` and `28` degrees
        inclusive, the factor is `1.10`; otherwise (strictly above `28`) the
        factor is `1.00`."

        Design: Difficulty/combinatorial_formula/chemical_quantity_temperature_branch_nonlinearity
        """
        ctx, cool, cold = self._setup_two_apps()
        assert cold["raw_quantity_lbs"] == 28125, (
            "10F < 15 -> factor 1.25: 750 x 30 x 1.25 = 28125, got "
            f"{cold['raw_quantity_lbs']}")
        assert cold["raw_quantity_lbs"] - cool["raw_quantity_lbs"] == 3375, (
            "the conditional branch produces a non-linear delta, not a "
            "proportional one")


class TestExactAvailabilityBoundary:
    def _setup_exact(self):
        return setup_proposed_application(
            event_code="SNOW-L", product_code="NAAC-EXACT",
            seasonal_limit=24750, chemical_limit_lbs=100000,
            budget_cents=50000000, pavement_temp_f=20)

    def test_authorize_exact_availability_boundary_inclusive(self, api):
        """PRD §3.8: "Authorization requires the smaller of those two pools to
        be strictly greater than zero; the boundary at equality is inclusive,
        so if the raw quantity exactly equals the available capacity,
        authorization proceeds in full."

        Design: Difficulty/boundary_precision_check/authorize_exact_availability_boundary_inclusive
        """
        ctx = self._setup_exact()
        assert ctx["application"]["raw_quantity_lbs"] == 24750
        authorized = authorize_application(ctx["application"]["id"])
        assert authorized["status"] == "AUTHORIZED"
        assert authorized["authorized_quantity_lbs"] == 24750, (
            "raw exactly equals availability (24750): the inclusive boundary "
            "must authorize in full")
        assert authorized["capped"] is False

    def test_authorize_exact_availability_drains_pool(self, api):
        """PRD §3.8: "the boundary at equality is inclusive, so if the raw
        quantity exactly equals the available capacity, authorization proceeds
        in full."
        PRD §3.7: "`seasonal_available_lbs` is `seasonal_limit_lbs` minus
        `seasonal_dispensed_lbs` minus `seasonal_reserved_lbs`."

        Design: Difficulty/boundary_precision_check/authorize_exact_availability_boundary_inclusive
        """
        ctx = self._setup_exact()
        authorize_application(ctx["application"]["id"])
        product = get_chemical_product(ctx["product"]["id"])
        assert product["seasonal_available_lbs"] == 0, (
            f"the pool is fully consumed, not overdrawn; got "
            f"{product['seasonal_available_lbs']}")
        assert_product_quota_invariant(product)


class TestQuotaConservation:
    def _setup_authorized(self):
        ctx = setup_proposed_application(
            event_code="SNOW-Q", product_code="NAAC-01", seasonal_limit=100000,
            chemical_limit_lbs=100000, budget_cents=50000000,
            pavement_temp_f=20)
        authorized = authorize_application(ctx["application"]["id"])
        return ctx, authorized

    def test_chemical_quota_authorize_moves_reserve(self, api):
        """PRD §3.7: "The three counters obey a conserved-quota invariant: at
        all times, `seasonal_dispensed_lbs` plus `seasonal_reserved_lbs` plus
        `seasonal_available_lbs` equals `seasonal_limit_lbs`."
        PRD §3.8: "The product's `seasonal_reserved_lbs` increases by
        `authorized_quantity_lbs` (and `seasonal_available_lbs` is
        recomputed)".

        Design: Difficulty/compensating_invariant/chemical_quota_authorize_void_conservation
        """
        ctx, authorized = self._setup_authorized()
        product = get_chemical_product(ctx["product"]["id"])
        assert product["seasonal_reserved_lbs"] == 24750
        assert product["seasonal_available_lbs"] == 75250
        assert product["seasonal_dispensed_lbs"] == 0
        assert_product_quota_invariant(product)

    def test_chemical_quota_void_compensates_exactly(self, api):
        """PRD §3.8: "Voiding (`AUTHORIZED → VOIDED`) compensates the
        authorization: the product's `seasonal_reserved_lbs` decreases by
        `authorized_quantity_lbs` (with `seasonal_available_lbs` recomputed)".
        PRD §3.7: "The three counters obey a conserved-quota invariant: at
        all times, `seasonal_dispensed_lbs` plus `seasonal_reserved_lbs` plus
        `seasonal_available_lbs` equals `seasonal_limit_lbs`."

        Design: Difficulty/compensating_invariant/chemical_quota_authorize_void_conservation
        """
        ctx, authorized = self._setup_authorized()
        void_application(ctx["application"]["id"])
        product = get_chemical_product(ctx["product"]["id"])
        assert product["seasonal_reserved_lbs"] == 0, (
            "VOID must return the reservation exactly")
        assert product["seasonal_available_lbs"] == 100000
        assert product["seasonal_dispensed_lbs"] == 0
        assert_product_quota_invariant(product)


class TestDispenseConstrainedCascade:
    def _setup_cascade(self):
        ctx = setup_proposed_application(
            event_code="SNOW-H", product_code="KA-03", base_rate=95,
            unit_cost=10, seasonal_limit=10000, chemical_limit_lbs=100000,
            budget_cents=100000000, surface_code="TWY-A",
            surface_type="TAXIWAY", length_ft=1000, width_ft=100,
            pavement_temp_f=30)
        assert ctx["application"]["raw_quantity_lbs"] == 9500, (
            f"100 units x 95 x 1.00 at 30F = 9500, got "
            f"{ctx['application']['raw_quantity_lbs']}")
        authorize_application(ctx["application"]["id"])
        app2 = propose_application(ctx["event"]["id"], ctx["surface"]["id"],
                                   ctx["product"]["id"], pavement_temp_f=30)
        return ctx, app2

    def test_dispense_threshold_flips_product_constrained(self, api):
        """PRD §3.7: "A product's `status` flips from `ACTIVE` to
        `CONSTRAINED` automatically when a dispense pushes
        `seasonal_dispensed_lbs` to at least 90% of `seasonal_limit_lbs`."
        PRD §3.8: "A successful dispense moves the product's
        `seasonal_reserved_lbs` down by `authorized_quantity_lbs` and its
        `seasonal_dispensed_lbs` up by the same amount, with
        `seasonal_available_lbs` recomputed".

        Design: Difficulty/transitive_cascade/dispense_threshold_to_product_constraint_cascade
        """
        ctx, app2 = self._setup_cascade()
        dispense_application(ctx["application"]["id"])
        product = get_chemical_product(ctx["product"]["id"])
        assert product["seasonal_dispensed_lbs"] == 9500, (
            "link 1: the dispensed counter reflects the dispense")
        assert product["seasonal_reserved_lbs"] == 0
        assert product["status"] == "CONSTRAINED", (
            f"link 2: 9500 >= 0.9 x 10000 flips the product, got "
            f"{product['status']}")
        assert_product_quota_invariant(product)

    def test_dispense_threshold_rejects_proposed_applications(self, api):
        """PRD §3.7: "That flip has teeth: every `ChemicalApplication` on this
        product still in `PROPOSED` status becomes `REJECTED`."

        Design: Difficulty/transitive_cascade/dispense_threshold_to_product_constraint_cascade
        """
        ctx, app2 = self._setup_cascade()
        dispense_application(ctx["application"]["id"])
        rejected = get_chemical_application(app2["id"])
        assert rejected["status"] == "REJECTED", (
            "link 3: the product flip rejects the still-PROPOSED sibling, "
            f"got {rejected['status']}")


class TestAuthorizeGates:
    def test_authorize_state_error_beats_budget_error(self, api,
                                                      maintenance_lead_headers):
        """PRD §3.8: "the referenced event must be `ACTIVATED` or `ESCALATED`
        (else `ERR_EVENT_NOT_ACTIVE`); the referenced product must be
        `ACTIVE` (else `ERR_PRODUCT_CONSTRAINED`); at least one pound of
        capacity must remain in *both* environmental pools (else
        `ERR_ENV_LIMIT_EXCEEDED`); and the projected event cost after this
        authorization must not exceed `budget_cents` (else
        `ERR_BUDGET_EXCEEDED`)."
        PRD §2.9: "The order is not stylistic — a caller hitting two
        violations must see the earlier one."

        Design: Difficulty/priority_pair_validation_conflict/authorize_state_error_beats_budget_error
        """
        from test_helpers import create_chemical_product, event_action
        ctx = setup_event_with_surface(
            event_code="SNOW-I", chemical_limit_lbs=1000000,
            budget_cents=200000)
        product = create_chemical_product("NAAC-01", base_rate=30,
                                          unit_cost=100,
                                          seasonal_limit=1000000)
        app = propose_application(ctx["event"]["id"], ctx["surface"]["id"],
                                  product["id"], pavement_temp_f=20)
        # Would-be line cost 24750 x 100 = 2475000 > budget 200000.
        event_action(ctx["event"]["id"], "STAND_DOWN")

        resp = api.application_action(
            app["id"], {"action": "AUTHORIZE"},
            make_maintenance_lead_headers("ml-authorizer-1"))
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_ACTIVE, 409)

    def test_authorize_state_rejection_leaves_no_reservation(
            self, api, maintenance_lead_headers):
        """PRD §3.8: "On successful authorization, `authorized_quantity_lbs` is
        set to the minimum of three values: `raw_quantity_lbs`,
        `event_remaining_lbs`, and `product_available_lbs`."
        PRD §3.8: "The product's `seasonal_reserved_lbs` increases by
        `authorized_quantity_lbs` (and `seasonal_available_lbs` is
        recomputed)" — a
        rejected authorization performs none of these side effects.

        Design: Difficulty/priority_pair_validation_conflict/authorize_state_error_beats_budget_error
        """
        from test_helpers import create_chemical_product, event_action
        ctx = setup_event_with_surface(
            event_code="SNOW-I", chemical_limit_lbs=1000000,
            budget_cents=200000)
        product = create_chemical_product("NAAC-01", base_rate=30,
                                          unit_cost=100,
                                          seasonal_limit=1000000)
        app = propose_application(ctx["event"]["id"], ctx["surface"]["id"],
                                  product["id"], pavement_temp_f=20)
        event_action(ctx["event"]["id"], "STAND_DOWN")

        resp = api.application_action(
            app["id"], {"action": "AUTHORIZE"},
            make_maintenance_lead_headers("ml-authorizer-1"))
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_ACTIVE, 409)
        assert get_chemical_application(app["id"])["status"] == "PROPOSED", (
            "no partial authorization may leak through the rejection")
        assert get_chemical_product(product["id"])["seasonal_reserved_lbs"] \
            == 0

    def test_authorize_on_constrained_product_rejected(self, api,
                                                       maintenance_lead_headers):
        """PRD §3.8: "the referenced product must be `ACTIVE` (else
        `ERR_PRODUCT_CONSTRAINED`)".

        Design: Corner/errors/authorize_on_constrained_product_rejected
        """
        ctx = setup_proposed_application(
            event_code="SNOW-X1", product_code="KA-03", base_rate=95,
            unit_cost=10, seasonal_limit=10000, chemical_limit_lbs=100000,
            budget_cents=100000000, surface_code="TWY-A",
            surface_type="TAXIWAY", length_ft=1000, width_ft=100,
            pavement_temp_f=30)
        authorize_application(ctx["application"]["id"])
        propose_application(ctx["event"]["id"], ctx["surface"]["id"],
                            ctx["product"]["id"], pavement_temp_f=30)
        dispense_application(ctx["application"]["id"])
        assert get_chemical_product(
            ctx["product"]["id"])["status"] == "CONSTRAINED"
        app3 = propose_application(ctx["event"]["id"], ctx["surface"]["id"],
                                   ctx["product"]["id"], pavement_temp_f=30)

        resp = api.application_action(
            app3["id"], {"action": "AUTHORIZE"},
            make_maintenance_lead_headers("ml-authorizer-1"))
        # PRD §3.8/§2.9 name ERR_PRODUCT_CONSTRAINED verbatim but the §5
        # catalogue omits its HTTP status row, so only the error_id is pinned.
        validate_error(resp, ApiErrorId.ERR_PRODUCT_CONSTRAINED)
        assert get_chemical_application(app3["id"])["status"] == "PROPOSED"

    def test_authorize_with_zero_environmental_pool_rejected(
            self, api, maintenance_lead_headers):
        """PRD §3.8: "Authorization requires the smaller of those two pools to
        be strictly greater than zero". PRD §2.9: "Environmental pools for chemical authorization: at least one
        pound of capacity remains in *both* the per-event pool and the
        product's seasonal pool (else `ERR_ENV_LIMIT_EXCEEDED`)."

        Design: Corner/errors/authorize_with_zero_environmental_pool_rejected
        """
        ctx = setup_proposed_application(
            event_code="SNOW-X2", product_code="KA-04", base_rate=100,
            unit_cost=10, seasonal_limit=10000, chemical_limit_lbs=1000000,
            budget_cents=100000000, surface_code="TWY-A",
            surface_type="TAXIWAY", length_ft=1000, width_ft=100,
            pavement_temp_f=30)
        app1 = ctx["application"]
        assert app1["raw_quantity_lbs"] == 10000
        first = authorize_application(app1["id"])
        assert first["authorized_quantity_lbs"] == 10000, (
            "the first application takes the whole pool at the inclusive "
            "boundary; the product stays ACTIVE because nothing dispensed")
        assert get_chemical_product(
            ctx["product"]["id"])["status"] == "ACTIVE"
        app2 = propose_application(ctx["event"]["id"], ctx["surface"]["id"],
                                   ctx["product"]["id"], pavement_temp_f=30)

        resp = api.application_action(
            app2["id"], {"action": "AUTHORIZE"},
            make_maintenance_lead_headers("ml-authorizer-1"))
        validate_error(resp, ApiErrorId.ERR_ENV_LIMIT_EXCEEDED, 422)

    def test_authorize_over_budget_rejected(self, api,
                                            maintenance_lead_headers):
        """PRD §3.8: "and the projected event cost after this authorization
        must not exceed `budget_cents` (else `ERR_BUDGET_EXCEEDED`)."

        Design: Corner/errors/authorize_over_budget_rejected
        """
        ctx = setup_proposed_application(
            event_code="SNOW-X3", product_code="NAAC-HI", base_rate=30,
            unit_cost=100, seasonal_limit=1000000,
            chemical_limit_lbs=1000000, budget_cents=200000,
            pavement_temp_f=20)
        # Projected 24750 lbs x 100 cents = 2475000 > budget 200000.
        resp = api.application_action(
            ctx["application"]["id"], {"action": "AUTHORIZE"},
            make_maintenance_lead_headers("ml-authorizer-1"))
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED, 422)
        assert get_chemical_application(
            ctx["application"]["id"])["status"] == "PROPOSED", (
                "no reservation may leak through the budget rejection")
        assert get_chemical_product(
            ctx["product"]["id"])["seasonal_reserved_lbs"] == 0


class TestApplicationStateAndSegregation:
    def test_application_dispense_before_authorize_rejected(
            self, api, maintenance_lead_headers):
        """PRD §3.8: "`DISPENSED`, `REJECTED`, and `VOIDED` are terminal for
        an application; attempting an action that does not match the current
        status — for example dispensing a `PROPOSED` application or voiding a
        `DISPENSED` one — is rejected with `ERR_INVALID_APPLICATION_STATE`."

        Design: Corner/state_machines/application_dispense_before_authorize_rejected
        """
        ctx = setup_proposed_application(event_code="SNOW-C10",
                                         budget_cents=50000000)
        resp = api.application_action(
            ctx["application"]["id"], {"action": "DISPENSE"},
            make_maintenance_lead_headers("ml-dispenser-2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE, 409)
        assert get_chemical_application(
            ctx["application"]["id"])["status"] == "PROPOSED"

    def test_segregation_of_duties_same_user_dispense_rejected(
            self, api, maintenance_lead_headers):
        """PRD §3.8: "Dispensing (`AUTHORIZED → DISPENSED`) enforces
        **segregation of duties**: the caller's `X-User-ID` must differ from
        the application's `authorized_by`, otherwise the dispense is rejected
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/segregation_of_duties_same_user_dispense_rejected
        """
        ctx = setup_proposed_application(event_code="SNOW-R2",
                                         budget_cents=50000000)
        app_id = ctx["application"]["id"]
        authorized = authorize_application(app_id, user_id="ml-same")
        assert authorized["authorized_by"] == "ml-same"

        resp = api.application_action(
            app_id, {"action": "DISPENSE"},
            make_maintenance_lead_headers("ml-same"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        resp2 = api.application_action(
            app_id, {"action": "DISPENSE"},
            make_maintenance_lead_headers("ml-other"))
        data = validate_success(resp2, 200)
        assert data["status"] == "DISPENSED", (
            "a different MaintenanceLead user may dispense the application")


class TestConstrainedThreshold:
    def test_constrained_threshold_at_exactly_ninety_percent(self, api):
        """PRD §3.7: "A product's `status` flips from `ACTIVE` to
        `CONSTRAINED` automatically when a dispense pushes
        `seasonal_dispensed_lbs` to at least 90% of `seasonal_limit_lbs`."

        Design: Corner/cross_cutting_layers/constrained_threshold_at_exactly_ninety_percent
        """
        ctx = setup_proposed_application(
            event_code="SNOW-L4", product_code="KA-90", base_rate=90,
            unit_cost=10, seasonal_limit=10000, chemical_limit_lbs=100000,
            budget_cents=100000000, surface_code="TWY-A",
            surface_type="TAXIWAY", length_ft=1000, width_ft=100,
            pavement_temp_f=30)
        assert ctx["application"]["raw_quantity_lbs"] == 9000
        authorize_application(ctx["application"]["id"])
        dispense_application(ctx["application"]["id"])
        product = get_chemical_product(ctx["product"]["id"])
        assert product["seasonal_dispensed_lbs"] == 9000
        assert product["status"] == "CONSTRAINED", (
            "exactly 9000 of 10000 meets the inclusive 90% threshold, got "
            f"{product['status']}")


class TestImmediateConsistency:
    def test_authorize_response_reflects_mutation_immediately(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.8: "The application's `line_cost_cents` is set to
        `authorized_quantity_lbs` multiplied by the product's
        `unit_cost_cents_per_lb`, rounded half up to the cent."

        Design: Corner/consistency_model/authorize_response_reflects_mutation_immediately
        """
        ctx = setup_proposed_application(event_code="SNOW-M1",
                                         budget_cents=50000000)
        resp = api.application_action(
            ctx["application"]["id"], {"action": "AUTHORIZE"},
            make_maintenance_lead_headers("ml-authorizer-1"))
        data = validate_success(resp, 200)
        assert data["status"] == "AUTHORIZED"
        assert data["authorized_quantity_lbs"] == 24750
        assert data["line_cost_cents"] == 297000, (
            "24750 lbs x 12 cents = 297000 visible in the action response "
            f"itself, got {data['line_cost_cents']}")
