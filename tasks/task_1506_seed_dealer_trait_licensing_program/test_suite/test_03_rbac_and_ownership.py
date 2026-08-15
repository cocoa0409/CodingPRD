"""Role authorization (PRD §2.1/§4) and grower ownership checks."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_grower,
    create_pending_agreement,
    create_published_recommendation,
    create_plot_trial_payload,
    create_program_payload,
    create_trait_package,
    get_success_data,
    make_grower_headers,
    setup_market,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SALESREP = TEST_USERS["salesrep_headers"]
AGRONOMIST = TEST_USERS["agronomist_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


class TestRoleDenials:
    def test_agronomist_cannot_create_order_forbidden(self, api):
        """PRD §2.1: "Once the caller is identified, the caller's role must
        appear in the endpoint's authorized role list (§4); otherwise the
        request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4 authorizes POST /dealer/orders to DealerAdmin, SalesRep, Grower.

        Design: Corner/validations/agronomist_cannot_create_order_forbidden
        """
        ctx = setup_market(with_lot=False)
        resp = api.create_order(
            {"grower_id": ctx["grower"]["id"], "program_id": ctx["program"]["id"]},
            AGRONOMIST,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_salesrep_cannot_open_program_forbidden(self, api):
        """PRD §2.1: "Once the caller is identified, the caller's role must
        appear in the endpoint's authorized role list (§4); otherwise the
        request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4 authorizes POST /dealer/programs/{id}/open to DealerAdmin only.

        Design: Corner/rbac/salesrep_cannot_open_program_forbidden
        """
        program = validate_success(
            api.create_program(create_program_payload(), ADMIN), expected_status=201
        )
        resp = api.open_program(program["id"], SALESREP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        program_after = validate_success(api.get_program(program["id"], ADMIN))
        assert program_after["status"] == "DRAFT"

    def test_claims_adjuster_cannot_create_plot_forbidden(self, api):
        """PRD §2.1: "Once the caller is identified, the caller's role must
        appear in the endpoint's authorized role list (§4); otherwise the
        request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4 authorizes POST /dealer/plot-trials to Agronomist only.

        Design: Corner/rbac/claims_adjuster_cannot_create_plot_forbidden
        """
        ctx = setup_market(with_lot=False, with_field=True)
        resp = api.create_plot_trial(
            create_plot_trial_payload(
                ctx["program"]["id"], ctx["variety"]["id"], ctx["field"]["id"]
            ),
            ADJUSTER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_grower_cannot_read_inventory_lots_forbidden(self, api):
        """PRD §2.1: "Once the caller is identified, the caller's role must
        appear in the endpoint's authorized role list (§4); otherwise the
        request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4 authorizes GET /dealer/inventory-lots to DealerAdmin and SalesRep.

        Design: Corner/rbac/grower_cannot_read_inventory_lots_forbidden
        """
        grower = create_grower()
        resp = api.list_inventory_lots(make_grower_headers(grower["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestGrowerOwnership:
    def test_grower_cannot_confirm_another_growers_order_forbidden(self, api):
        """PRD §2.1: "A grower acting on a resource outside that chain is
        rejected with `ERR_GROWER_OWNERSHIP_MISMATCH`."

        Design: Corner/validations/grower_cannot_confirm_another_growers_order_forbidden
        """
        ctx = setup_market()
        other_grower = create_grower(account_name="Jones Ag", external_ref="EXT-002")
        order = get_success_data(
            api.create_order(
                {"grower_id": ctx["grower"]["id"], "program_id": ctx["program"]["id"]},
                SALESREP,
            )
        )
        get_success_data(
            api.add_order_line(
                order["id"], {"variety_id": ctx["variety"]["id"], "units": 10}, SALESREP
            )
        )
        resp = api.confirm_order(order["id"], make_grower_headers(other_grower["id"]))
        validate_error(resp, ApiErrorId.ERR_GROWER_OWNERSHIP_MISMATCH)
        order_after = validate_success(api.get_order(order["id"], SALESREP))
        assert order_after["status"] == "DRAFT"

    def test_order_referencing_other_growers_recommendation_rejected(self, api):
        """PRD §3.5: "the recommendation must belong to the same grower and be
        `PUBLISHED` or `ACCEPTED`, otherwise `ERR_RECOMMENDATION_MISMATCH`."

        Design: Corner/validations/order_referencing_other_growers_recommendation_rejected
        """
        ctx = setup_market(with_lot=False, with_field=True)
        other_grower = create_grower(account_name="Jones Ag", external_ref="EXT-002")
        rec = create_published_recommendation(ctx["program"], ctx["field"], ctx["variety"])
        assert rec["status"] == "PUBLISHED"

        resp = api.create_order(
            {
                "grower_id": other_grower["id"],
                "program_id": ctx["program"]["id"],
                "recommendation_id": rec["id"],
            },
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_RECOMMENDATION_MISMATCH)


class TestGrowerPositivePaths:
    def test_grower_can_sign_own_agreement_positive(self, api):
        """PRD §3.3: "Signing activates the license and may be performed by a
        `DealerAdmin` or by the `Grower`."
        PRD §3.3: "a grower signs only their own agreements, with an ownership
        mismatch rejected as `ERR_GROWER_OWNERSHIP_MISMATCH`".

        Design: Corner/rbac/grower_can_sign_own_agreement_positive
        """
        grower = create_grower()
        package = create_trait_package()
        agreement = create_pending_agreement(grower, package["id"])
        assert agreement["status"] == "PENDING_SIGNATURE"

        signed = validate_success(
            api.sign_trait_agreement(agreement["id"], make_grower_headers(grower["id"]))
        )
        assert signed["status"] == "ACTIVE"
