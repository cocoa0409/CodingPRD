"""Role authorization, ownership and segregation of duties.

The interesting cases here are the ones where a call would have failed anyway
for some later reason: each test proves the API answered with the *access* code
rather than the state code that a properly authorized caller would have earned.
"""

from test_helpers import (
    ADMIN,
    AGENT,
    ApiErrorId,
    adjudicate_claim,
    api_client,
    attribution_claim_payload,
    create_customer_row,
    create_model,
    create_retail_partner_row,
    file_quality_claim,
    inspect_payload,
    make_customer_headers,
    make_finance_controller_headers,
    make_logistics_coordinator_headers,
    make_retail_partner_headers,
    make_trial_support_agent_headers,
    read_order,
    read_quality_claim,
    read_refund,
    read_return_case,
    refund_authorization_payload,
    return_case_payload,
    set_clock,
    setup_delivered_order,
    setup_partner_channel_order,
    setup_return_lifecycle,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTheRoleCheckOutranksTheStateCheck:
    """Two calls that would have been refused on state grounds anyway."""

    def test_a_customer_inspecting_their_own_case_is_unauthorized_not_mis_staged(self):
        """PRD §2.1: "If both headers are well-formed but the named role is not authorized for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Inspection is listed for `LogisticsCoordinator` alone, and the case is
        still REQUESTED, so a coordinator making this same call would have been
        told ERR_INVALID_RETURN_STATE; the customer never gets that far.

        Design: Corner/rbac/a_customer_cannot_inspect_a_return_case_and_the_role_check_outranks_the_state_check
        """
        scenario = setup_return_lifecycle(
            stage="REQUESTED",
            model_overrides={
                "sku": "MDL-Q-R1", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "r1@example.com",
                "full_name": "Rae One",
                "household_hash": "HH-R1",
            },
        )
        return_case = scenario["return_case"]

        response = api_client.inspect_return_case(
            return_case["id"],
            inspect_payload("A", False, False),
            scenario["customer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

        reloaded = read_return_case(return_case["id"])
        assert reloaded["logistics_status"] == "REQUESTED"
        assert reloaded["condition_grade"] is None
        assert reloaded["version"] == return_case["version"]

    def test_a_logistics_coordinator_cannot_authorize_a_refund(self):
        """PRD §2.1: "A `FinanceController` owns money: refund authorization, release and void, quality-claim settlement, and attribution-claim review and resolution."

        The coordinator who would have run the pickup is refused on role
        grounds even though the case has not been inspected or dispositioned —
        the state objection a controller would have met never surfaces, and no
        ledger row is written.

        Design: Corner/rbac/a_logistics_coordinator_cannot_authorize_a_refund
        """
        scenario = setup_return_lifecycle(
            stage="REQUESTED",
            model_overrides={
                "sku": "MDL-Q-R2", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "r2@example.com",
                "full_name": "Ras Two",
                "household_hash": "HH-R2",
            },
        )
        return_case = scenario["return_case"]

        response = api_client.create_refund_authorization(
            refund_authorization_payload(return_case["id"], return_case["version"]),
            make_logistics_coordinator_headers("lc-r2"),
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

        _rows, meta = validate_paginated(
            api_client.list_refund_authorizations(
                make_finance_controller_headers("fin-r2"),
                params={"return_case_id": return_case["id"]},
            )
        )
        assert meta["total_count"] == 0, "the refused call must not mint a ledger row"

        reloaded = read_return_case(return_case["id"])
        assert reloaded["financial_status"] == "PENDING"
        assert reloaded["version"] == return_case["version"]


class TestOwnershipBindsOnlyTheEntityBackedRoles:
    """The two roles whose X-User-ID is a real row id, and the ones whose is not."""

    def test_a_customer_cannot_touch_another_households_order_for_write_or_read(self):
        """PRD §2.1: "A violation of either ownership rule is rejected with `ERR_NOT_OWNER` (HTTP 403)."

        Customer is an authorized role for both calls, so what fails is the
        comparison of X-User-ID against the order's `customer_id` — and the
        single-resource read is guarded exactly like the write.

        Design: Corner/rbac/a_customer_cannot_open_a_return_on_another_households_order
        """
        model = create_model(sku="MDL-Q-R3", name="Comfort Q", list_price_cents=120000)
        scenario = setup_delivered_order(
            model=model,
            customer_overrides={
                "email": "r3a@example.com",
                "full_name": "Rho A",
                "household_hash": "HH-R3A",
            },
        )
        order_a = scenario["order"]
        customer_b = create_customer_row(
            email="r3b@example.com", full_name="Rho B", household_hash="HH-R3B"
        )
        headers_b = make_customer_headers(customer_b["id"])

        set_clock("2026-09-10T00:00:00Z")

        write_response = api_client.create_return_case(
            return_case_payload(order_a["id"], "COMFORT"), headers_b
        )
        validate_error(write_response, ApiErrorId.ERR_NOT_OWNER)

        read_response = api_client.get_trial_order(order_a["id"], headers_b)
        validate_error(read_response, ApiErrorId.ERR_NOT_OWNER)

        _rows, meta = validate_paginated(
            api_client.list_return_cases(AGENT, params={"order_id": order_a["id"]})
        )
        assert meta["total_count"] == 0
        assert read_order(order_a["id"])["trial_status"] == "TRIAL_ACTIVE"

    def test_a_partner_cannot_claim_under_another_partners_id_but_the_owner_can(self):
        """PRD §2.1: "When `X-User-Role` is `RetailPartner`, `X-User-ID` is the `id` of the acting RetailPartner record; a partner may act on an attribution claim only when the claim's `partner_id` equals `X-User-ID`, and when submitting a new claim the `partner_id` in the request body must equal `X-User-ID`."

        For this role the ownership anchor sits in the request body, so partner B
        naming partner A is refused even though the order really was sold by A —
        and the byte-identical body from A itself is accepted.

        Design: Corner/rbac/a_retail_partner_cannot_file_an_attribution_claim_under_another_partners_id
        """
        scenario = setup_partner_channel_order(
            partner_overrides={
                "name": "Sleep Mart R4A",
                "region_code": "CA",
                "commission_bps": 800,
            },
            model_overrides={
                "sku": "MDL-Q-R4", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "r4@example.com",
                "full_name": "Ren Four",
                "household_hash": "HH-R4",
            },
        )
        partner_a = scenario["partner"]
        partner_b = create_retail_partner_row(
            name="Sleep Mart R4B", region_code="CA", commission_bps=800
        )

        set_clock("2026-08-10T00:00:00Z")
        body = attribution_claim_payload(
            partner_a["id"], scenario["order"]["id"], "SALES_ATTRIBUTION", 2
        )

        refused = api_client.create_attribution_claim(
            body, make_retail_partner_headers(partner_b["id"])
        )
        validate_error(refused, ApiErrorId.ERR_NOT_OWNER)

        accepted = validate_success(
            api_client.create_attribution_claim(
                body, make_retail_partner_headers(partner_a["id"])
            ),
            201,
        )

        rows, meta = validate_paginated(
            api_client.list_attribution_claims(
                make_finance_controller_headers("fin-r4"),
                params={"partner_id": partner_a["id"]},
            )
        )
        assert meta["total_count"] == 1, (
            "only the owning partner's submission may have landed, got "
            f"{meta['total_count']}"
        )
        assert [row["id"] for row in rows] == [accepted["id"]]

    def test_return_opening_is_shared_between_an_owning_customer_and_an_opaque_agent(self):
        """PRD §2.1: "The remaining four roles carry opaque identities. When `X-User-Role` is `TrialSupportAgent`, `LogisticsCoordinator`, `FinanceController`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity."

        POST /return-cases lists both `Customer` and `TrialSupportAgent`, so the
        same endpoint accepts the household that owns the order and an agent
        acting on a completely different household: ownership binds only the
        entity-backed role.

        Design: Corner/rbac/a_shared_operation_is_open_to_both_of_its_roles
        """
        model = create_model(sku="MDL-Q-R7", name="Comfort Q", list_price_cents=120000)
        scenario_a = setup_delivered_order(
            model=model,
            customer_overrides={
                "email": "r7a@example.com",
                "full_name": "Rue A",
                "household_hash": "HH-R7A",
            },
        )
        scenario_b = setup_delivered_order(
            model=model,
            customer_overrides={
                "email": "r7b@example.com",
                "full_name": "Rue B",
                "household_hash": "HH-R7B",
            },
        )

        set_clock("2026-09-10T00:00:00Z")

        case_a = validate_success(
            api_client.create_return_case(
                return_case_payload(scenario_a["order"]["id"], "COMFORT"),
                make_customer_headers(scenario_a["customer"]["id"]),
            ),
            201,
        )
        case_b = validate_success(
            api_client.create_return_case(
                return_case_payload(scenario_b["order"]["id"], "PRICE"),
                make_trial_support_agent_headers("ops-r7"),
            ),
            201,
        )

        assert case_a["logistics_status"] == "REQUESTED"
        assert case_b["logistics_status"] == "REQUESTED"
        assert case_a["order_id"] == scenario_a["order"]["id"]
        assert case_b["order_id"] == scenario_b["order"]["id"]

        assert read_order(scenario_a["order"]["id"])["trial_status"] == "RETURN_REQUESTED"
        assert read_order(scenario_b["order"]["id"])["trial_status"] == "RETURN_REQUESTED"

        _rows, meta = validate_paginated(api_client.list_return_cases(ADMIN))
        assert meta["total_count"] == 2


class TestSegregationOfDutiesIsKeyedOnTheOperatorNotTheRole:
    """Same role, two different operator ids — the second one is what unlocks the money."""

    def test_the_authorizing_controller_cannot_release_but_a_second_controller_can(self):
        """PRD §2.11: "Releasing a refund authorization requires that the acting `X-User-ID` differ from the `authorized_by_user_id` recorded when the authorization was created."

        fin-r5-1 priced the 114000-cent refund and is refused on its own
        authorization with the ledger untouched; the identical call from
        fin-r5-2 releases it, moving 114000 out of the outstanding balance and
        leaving the 6000-cent proration as retained principal.

        Design: Corner/rbac/the_authorizing_controller_cannot_also_release_the_refund
        """
        authorizer = make_finance_controller_headers("fin-r5-1")
        releaser = make_finance_controller_headers("fin-r5-2")
        scenario = setup_return_lifecycle(
            stage="AUTHORIZED",
            model_overrides={
                "sku": "MDL-Q-R5",
                "name": "Comfort Q",
                "list_price_cents": 120000,
                "donation_eligible": True,
            },
            customer_overrides={
                "email": "r5@example.com",
                "full_name": "Rin Five",
                "household_hash": "HH-R5",
            },
            authorizer_headers=authorizer,
        )
        refund_id = scenario["refund"]["id"]
        order_id = scenario["order"]["id"]

        refused = api_client.release_refund(refund_id, {}, authorizer)
        validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        held = read_refund(refund_id, authorizer)
        assert held["status"] == "AUTHORIZED"
        assert held["released_by_user_id"] is None
        assert read_order(order_id)["refunded_total_cents"] == 0, (
            "a refused release must not move any money"
        )

        released = validate_success(
            api_client.release_refund(refund_id, {}, releaser), 200
        )
        assert released["status"] == "RELEASED"
        assert released["released_by_user_id"] == "fin-r5-2"
        assert released["authorized_by_user_id"] == "fin-r5-1"
        assert released["net_refund_cents"] == 114000

        order = read_order(order_id)
        assert order["refunded_total_cents"] == 114000
        assert order["outstanding_refundable_cents"] == 0
        assert order["retained_amount_cents"] == 6000
        assert read_return_case(scenario["return_case"]["id"])["financial_status"] == (
            "RELEASED"
        )

    def test_the_adjudicating_agent_cannot_settle_but_a_different_operator_can(self):
        """PRD §2.11: "Settling an approved quality claim requires that the acting `X-User-ID` differ from the `approved_by_user_id` recorded at adjudication."

        The pair spans two roles, yet the comparison is on the operator id alone:
        a controller presenting ops-r6 — the id that adjudicated — is refused, so
        the 15-percent shipping-damage credit of 18000 cents posts only once
        fin-r6 settles it.

        Design: Corner/rbac/the_adjudicating_agent_cannot_also_settle_the_goodwill_credit
        """
        scenario = setup_delivered_order(
            model_overrides={
                "sku": "MDL-Q-R6", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "r6@example.com",
                "full_name": "Rob Six",
                "household_hash": "HH-R6",
            },
        )
        order_id = scenario["order"]["id"]

        set_clock("2026-08-05T00:00:00Z")
        claim = file_quality_claim(
            order_id, "SHIPPING_DAMAGE", 2, headers=scenario["customer_headers"]
        )
        adjudicated = adjudicate_claim(
            claim["id"], "CREDIT", headers=make_trial_support_agent_headers("ops-r6")
        )
        assert adjudicated["status"] == "APPROVED"
        assert adjudicated["credit_cents"] == 18000, (
            f"120000 * 1500 / 10000 is 18000 cents, got {adjudicated['credit_cents']}"
        )

        refused = api_client.settle_quality_claim(
            claim["id"], {}, make_finance_controller_headers("ops-r6")
        )
        validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        held = read_quality_claim(claim["id"])
        assert held["status"] == "APPROVED"
        assert held["settled_by_user_id"] is None
        assert read_order(order_id)["goodwill_credit_cents"] == 0, (
            "a refused settlement must not post the credit"
        )

        settled = validate_success(
            api_client.settle_quality_claim(
                claim["id"], {}, make_finance_controller_headers("fin-r6")
            ),
            200,
        )
        assert settled["status"] == "SETTLED"
        assert settled["settled_by_user_id"] == "fin-r6"
        assert settled["approved_by_user_id"] == "ops-r6"
        assert settled["credit_cents"] == 18000

        order = read_order(order_id)
        assert order["goodwill_credit_cents"] == 18000
        assert order["fulfillment_status"] == "DELIVERED", (
            "the CREDIT adjudication already reverted DAMAGED_REPORTED, got "
            f"{order['fulfillment_status']}"
        )
