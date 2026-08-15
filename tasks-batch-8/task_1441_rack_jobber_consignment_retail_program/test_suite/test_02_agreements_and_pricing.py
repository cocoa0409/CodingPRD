"""Consignment agreement lifecycle, commercial-term amendments (OCC), and
maintained retail pricing with create-with-supersede semantics."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_price_directive,
    create_agreement_payload,
    create_price_directive_payload,
    get_agreement,
    get_success_data,
    new_active_agreement,
    new_agreement,
    new_audit,
    new_product,
    new_program,
    new_promotion,
    new_service_visit,
    new_store,
    set_clock,
    setup_shop,
    submit_agreement,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["jobber_admin_headers"]


class TestAgreementCreateValidation:
    def test_agreement_create_invalid_enum_rejected(self, api):
        """PRD section 3.1: "`markdown_liability`, one of `JOBBER`, `RETAILER`,
        or `SHARED`, defaulting to `SHARED`".
        PRD section 2.8: "Enumerations: enum fields must carry a declared
        member, failing with `ERR_INVALID_ENUM` (HTTP 422)."

        Design: Corner/entities/agreement_create_invalid_enum_rejected
        """
        set_clock()
        program = new_program(name="EnumCo")
        store = new_store(name="EnumStore", store_code="EN1")
        res = api.create_agreement(
            create_agreement_payload(program["id"], store["id"],
                                     markdown_liability="SPLIT"),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_ENUM)

    def test_agreement_create_duplicate_live_rejected(self, api):
        """PRD section 3.1: "Uniqueness is enforced across the pair: at most
        one agreement for a given `program_id` and `store_id` may exist in
        `DRAFT`, `PENDING_ACCEPTANCE`, `ACTIVE`, or `SUSPENDED`; a second
        creation attempt against the same pair while one is live is rejected
        with `ERR_AGREEMENT_EXISTS`."

        Design: Corner/entities/agreement_create_duplicate_live_rejected
        """
        set_clock()
        program = new_program(name="DupCo")
        store = new_store(name="DupStore", store_code="DP1")
        first = new_agreement(program["id"], store["id"])
        assert first["status"] == "DRAFT"
        res = api.create_agreement(
            create_agreement_payload(program["id"], store["id"],
                                     base_margin_pct=0.30,
                                     shrink_retailer_share_pct=0.6,
                                     restock_value_cap_cents=60000),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_EXISTS)


class TestAgreementLifecycle:
    def test_initial_states_on_create(self, api):
        """PRD section 3.1: "An agreement is born `DRAFT`."
        PRD section 3.5: "A visit is born `SCHEDULED`."
        PRD section 3.7: "The audit is born `SCHEDULED`."
        PRD section 3.3: "A promotion is born `DRAFT`."
        PRD section 3.8: "The authorization is born `REQUESTED`."
        PRD section 3.4: "The set is born `PLANNED`."

        Design: Corner/state_machines/initial_states_on_create
        """
        ctx = setup_shop(with_route=True)
        agreement = ctx["agreement"]

        visit = new_service_visit(ctx["route"]["id"], agreement["id"])
        assert visit["status"] == "SCHEDULED", "a visit is born SCHEDULED"
        audit = new_audit(agreement["id"])
        assert audit["status"] == "SCHEDULED", "an audit is born SCHEDULED"
        promo = new_promotion(ctx["program"]["id"], ctx["product"]["id"],
                              name="Init Promo", start_date="2026-08-10",
                              end_date="2026-08-15")
        assert promo["status"] == "DRAFT", "a promotion is born DRAFT"
        markdown = validate_success(api.create_markdown_authorization(
            {"store_agreement_id": agreement["id"],
             "product_id": ctx["product"]["id"], "auth_type": "MARKDOWN",
             "units": 1, "markdown_price_cents": 180},
            ADMIN), 201)
        assert markdown["status"] == "REQUESTED", (
            "an authorization is born REQUESTED")
        seasonal = validate_success(api.create_seasonal_set(
            {"store_agreement_id": agreement["id"], "theme": "Back to School",
             "category": "SEASONAL", "allocated_facings": 2,
             "set_window_start": "2026-08-05", "set_window_end": "2026-08-10",
             "teardown_deadline": "2026-08-20"},
            ADMIN), 201)
        assert seasonal["status"] == "PLANNED", "a set is born PLANNED"

    def test_agreement_submit_twice_rejected(self, api):
        """PRD section 3.1: "An agreement is born `DRAFT`. Submission by a
        `JobberAdmin` moves `DRAFT` to `PENDING_ACCEPTANCE`."
        PRD section 2.8: "From-state validity: the target resource must be in a
        state from which the requested transition exists, failing with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/agreement_submit_twice_rejected
        """
        set_clock()
        program = new_program(name="TwiceCo")
        store = new_store(name="TwiceStore", store_code="TW1")
        agreement = new_agreement(program["id"], store["id"])
        assert agreement["status"] == "DRAFT", "an agreement is born DRAFT"
        submit_agreement(agreement["id"])
        res = api.submit_agreement(agreement["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = get_agreement(agreement["id"])
        assert after["status"] == "PENDING_ACCEPTANCE"

    def test_agreement_terminated_is_locked_down(self, api):
        """PRD section 3.1: "Termination by a `JobberAdmin` moves an `ACTIVE`
        or `SUSPENDED` agreement to `TERMINATED`, the other terminal state".
        PRD section 2.8: "Terminality: an action addressed to a resource
        already in a terminal state fails with `ERR_ALREADY_TERMINAL`
        (HTTP 409)."

        Design: Corner/state_machines/agreement_terminated_is_locked_down
        """
        set_clock()
        program = new_program(name="TermCo")
        store = new_store(name="TermStore", store_code="TM1")
        agreement = new_active_agreement(program["id"], store["id"])
        terminated = validate_success(
            api.terminate_agreement(agreement["id"], ADMIN), 200)
        assert terminated["status"] == "TERMINATED"
        res = api.resume_agreement(agreement["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)
        after = get_agreement(agreement["id"])
        assert after["status"] == "TERMINATED"


class TestAgreementAmendOcc:
    def test_amend_advances_version_then_stale_rejected(self, api):
        """PRD section 2.7: "Amending an agreement's commercial terms requires
        the request to carry `expected_store_agreement_version` equal to the
        agreement's current `version`."
        PRD section 2.7: "In all four cases the field is non-optional, and a
        mismatch — the parent entity's version has advanced since the client
        last observed it, for instance because a price-directive supersede or a
        shrink-ratio recompute intervened — is rejected with
        `ERR_STALE_VERSION` (HTTP 412), so the client always acts on the state
        it actually verified."

        Design: Corner/cross_cutting_complexity/occ_agreement_amend_stale_rejected
        """
        ctx = setup_shop(with_product=False)
        agreement = ctx["agreement"]
        observed = agreement["version"]
        amended = validate_success(api.patch_agreement(
            agreement["id"],
            {"expected_store_agreement_version": observed,
             "base_margin_pct": 0.30},
            ADMIN), 200)
        assert amended["version"] == observed + 1, (
            "version increments by exactly one per mutation")
        res = api.patch_agreement(
            agreement["id"],
            {"expected_store_agreement_version": observed,
             "shrink_retailer_share_pct": 0.6},
            ADMIN)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        after = get_agreement(agreement["id"])
        assert after["base_margin_pct"] == 0.30, "first amendment persisted"
        assert after["shrink_retailer_share_pct"] == 0.5, (
            "the loser's write was not applied")


class TestPriceDirectiveGates:
    def test_price_below_floor_rejected(self, api):
        """PRD section 3.2: "Beyond concurrency, creation requires the
        agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise), the
        product to belong to the agreement's program
        (`ERR_PRODUCT_NOT_IN_PROGRAM` otherwise), the product to still be
        `ACTIVE` (`ERR_PRODUCT_DISCONTINUED` otherwise), and the price to meet
        or exceed the product's `min_retail_cents` (`ERR_PRICE_BELOW_FLOOR`
        otherwise)."

        Design: Corner/validations/price_below_floor_rejected
        """
        ctx = setup_shop(with_directive=False,
                         product_overrides={"min_retail_cents": 150})
        agreement = ctx["agreement"]
        res = api.create_price_directive(
            create_price_directive_payload(
                agreement["id"], ctx["product"]["id"],
                agreement["version"], price_cents=140),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_PRICE_BELOW_FLOOR)

    def test_product_not_in_program_rejected(self, api):
        """PRD section 3.2: "Beyond concurrency, creation requires the
        agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise), the
        product to belong to the agreement's program
        (`ERR_PRODUCT_NOT_IN_PROGRAM` otherwise), the product to still be
        `ACTIVE` (`ERR_PRODUCT_DISCONTINUED` otherwise), and the price to meet
        or exceed the product's `min_retail_cents` (`ERR_PRICE_BELOW_FLOOR`
        otherwise)."

        Design: Corner/validations/product_not_in_program_rejected
        """
        ctx = setup_shop(with_product=False)
        other_program = new_program(name="Prog B")
        foreign = new_product(other_program["id"], sku="XB-001",
                              name="Other Program Item")
        agreement = ctx["agreement"]
        res = api.create_price_directive(
            create_price_directive_payload(
                agreement["id"], foreign["id"], agreement["version"]),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_PRODUCT_NOT_IN_PROGRAM)

    def test_product_discontinued_blocks_directive(self, api):
        """PRD section 3.2: "A product is born `ACTIVE`; a later update may
        revise `jobber_cost_cents` or `min_retail_cents`, or move `status` to
        `DISCONTINUED`."
        PRD section 3.2: "Beyond concurrency, creation requires the agreement
        to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise), the product to
        belong to the agreement's program (`ERR_PRODUCT_NOT_IN_PROGRAM`
        otherwise), the product to still be `ACTIVE`
        (`ERR_PRODUCT_DISCONTINUED` otherwise), and the price to meet or exceed
        the product's `min_retail_cents` (`ERR_PRICE_BELOW_FLOOR` otherwise)."

        Design: Corner/validations/product_discontinued_blocks_directive
        """
        ctx = setup_shop(with_directive=False)
        agreement = ctx["agreement"]
        product = ctx["product"]
        discontinued = validate_success(
            api.patch_product(product["id"], {"status": "DISCONTINUED"}, ADMIN),
            200)
        assert discontinued["status"] == "DISCONTINUED"
        fresh_version = get_agreement(agreement["id"])["version"]
        res = api.create_price_directive(
            create_price_directive_payload(
                agreement["id"], product["id"], fresh_version),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_PRODUCT_DISCONTINUED)


class TestPriceDirectiveSupersedeOcc:
    def test_create_with_supersede_then_stale_rejected(self, api):
        """PRD section 3.2: "When `effective_from` is at or before the logical
        clock, the new directive is born `EFFECTIVE` and whatever directive was
        previously `EFFECTIVE` for the same agreement and product moves to
        `SUPERSEDED`, stamped with a `superseded_at` equal to the clock."
        PRD section 3.2: "Either form of creation advances the agreement's
        `version` by one, which is why amending terms and setting prices
        serialize against each other through §2.7."

        Design: Corner/cross_cutting_complexity/occ_price_directive_supersede_stale_rejected
        """
        ctx = setup_shop()  # directive D1 (200) born EFFECTIVE at clock 08-01
        agreement = ctx["agreement"]
        product = ctx["product"]
        d1 = ctx["directive"]
        observed = get_agreement(agreement["id"])["version"]
        # D2 at the current clock supersedes D1 and consumes the version.
        d2 = validate_success(api.create_price_directive(
            create_price_directive_payload(
                agreement["id"], product["id"], observed, price_cents=210),
            ADMIN), 201)
        assert_price_directive(d2)
        assert d2["status"] == "EFFECTIVE"
        d1_after = get_success_data(api.get_price_directive(d1["id"], ADMIN))
        assert d1_after["status"] == "SUPERSEDED"
        assert d1_after.get("superseded_at"), "superseded_at stamped"
        # D3 replays the version D2 consumed.
        res = api.create_price_directive(
            create_price_directive_payload(
                agreement["id"], product["id"], observed, price_cents=220),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        directives = get_success_data(api.list_price_directives(
            ADMIN, params={"store_agreement_id": agreement["id"],
                           "product_id": product["id"]}))
        assert isinstance(directives, list)
        assert len(directives) == 2, (
            "the rejected third directive persisted nothing")
