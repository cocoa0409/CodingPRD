"""Who may act: each write bound to the role that declares it, authentication
ahead of authorization, entity-backed ownership on the operator's own contract,
and the acting user id checked separately from the role on deviation activation.
"""
from test_helpers import (
    AUG_05,
    NOV_START,
    SEP_START,
    TERM_START,
    add_coverage,
    add_tier,
    api_client,
    bootstrap_partners,
    build_signed_contract,
    clock_payload,
    contract_payload,
    contract_tier_payload,
    create_contract_draft,
    create_deviation,
    create_manufacturer,
    create_operator,
    create_product,
    decide_deviation,
    deviation_agreement_payload,
    product_payload,
    rebate_period_payload,
    submit_deviation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST, AUDITOR, NAM
from test_helpers.test_users import (
    ANALYST_USER_ID,
    NAM_USER_ID,
    NO_AUTH_HEADERS,
    make_national_account_manager_headers,
    make_operator_buyer_headers,
)

FLAT_COST = {
    "last_cost_cents": 4000,
    "avg_cost_cents": 4000,
    "replacement_cost_cents": 4000,
}


def _chicken(manufacturer_id, **overrides):
    return create_product(manufacturer_id, **dict(FLAT_COST, **overrides))


class TestExclusiveOperations:
    def test_each_write_is_refused_to_every_role_but_its_own(self):
        """PRD §2.1: "If the headers are well formed but the role is not authorized
        for the endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."

        PRD §2.8: "Role authorization, including entity-backed ownership —
        `ERR_UNAUTHORIZED` (403)."

        PRD §2.1: "`SystemAdmin` owns reference data — operators, manufacturers,
        distribution centers, products — and the logical clock."

        Design: Corner/RBAC/exclusive_operations_are_denied_to_other_roles
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"])
        contract = create_contract_draft(
            world["operator_id"], world["manufacturer_id"]
        )
        contract_id = contract["id"]
        assert contract["status"] == "DRAFT"
        assert contract["version"] == 1

        # Contract construction belongs to the manager, not the analyst.
        validate_error(
            api_client.create_contract(
                contract_payload(
                    world["operator_id"],
                    world["manufacturer_id"],
                    contract_code="HLG-2027",
                ),
                ANALYST,
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.create_contract_tier(
                contract_tier_payload(contract_id, markup_value=25.00), ANALYST
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        # A valid payload with a fresh expected_contract_version: the denial
        # still precedes every business check on the ladder.
        validate_error(
            api_client.create_deviation_agreement(
                deviation_agreement_payload(
                    contract_id,
                    chicken["id"],
                    world["manufacturer_id"],
                    contract["version"],
                    5000,
                    TERM_START,
                    NOV_START,
                    requested_net_price_cents=4200,
                ),
                NAM,
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.create_rebate_period(
                rebate_period_payload(contract_id, TERM_START, SEP_START),
                world["buyer"],
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.set_clock(clock_payload(AUG_05), AUDITOR),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api_client.create_product(
                product_payload(
                    world["manufacturer_id"],
                    sku="P-BEEF",
                    description="Beef Chuck 4/10#",
                    **FLAT_COST,
                ),
                NAM,
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        # No denied call wrote anything.
        contracts, contract_page = validate_paginated(
            api_client.list_contracts(NAM, {"limit": 10, "offset": 0})
        )
        assert [row["id"] for row in contracts] == [contract_id]
        assert contract_page["total_count"] == 1
        products, product_page = validate_paginated(
            api_client.list_products(NAM, {"limit": 10, "offset": 0})
        )
        assert [row["id"] for row in products] == [chicken["id"]]
        assert product_page["total_count"] == 1

        # And the clock never moved: a signature taken now is stamped from it.
        add_tier(contract_id, markup_value=25.00)
        add_coverage(contract_id, world["dc_id"])
        validate_success(
            api_client.submit_contract_for_signature(contract_id, NAM)
        )
        signed = validate_success(
            api_client.sign_contract(contract_id, world["buyer"])
        )
        assert signed["status"] == "ACTIVE"
        assert signed["signed_at"].startswith("2026-08-01T00:00:00")


class TestAuthenticationPrecedesAuthorization:
    def test_a_missing_or_unknown_role_is_a_401_not_a_403(self):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
        identifying the acting principal, and `X-User-Role`, naming the role it
        acts in."

        PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
        the seven declared roles, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD §2.1: "The seven roles are `SystemAdmin`, `NationalAccountManager`,
        `PricingAnalyst`, `OperatorBuyer`, `ManufacturerRep`, `RebateAccountant`,
        and `ContractAuditor`."

        Design: Corner/RBAC/missing_or_unknown_role_header_is_rejected
        """
        operator = create_operator()
        manufacturer = create_manufacturer()
        payload = contract_payload(operator["id"], manufacturer["id"])

        no_role_headers = {
            "Content-Type": "application/json",
            "X-User-ID": NAM_USER_ID,
        }
        unknown_role_headers = {
            "Content-Type": "application/json",
            "X-User-ID": NAM_USER_ID,
            "X-User-Role": "Wholesaler",
        }

        missing = validate_error(
            api_client.create_contract(payload, no_role_headers),
            "ERR_UNAUTHENTICATED",
            401,
        )
        assert missing["message"].strip() != ""
        # Wholesaler is well formed but outside the declared seven, so it is
        # unauthenticated rather than merely unauthorized.
        validate_error(
            api_client.create_contract(payload, unknown_role_headers),
            "ERR_UNAUTHENTICATED",
            401,
        )
        # Reads are authenticated too.
        validate_error(
            api_client.list_contracts(NO_AUTH_HEADERS, {"limit": 10, "offset": 0}),
            "ERR_UNAUTHENTICATED",
            401,
        )

        rows, page = validate_paginated(
            api_client.list_contracts(ADMIN, {"limit": 10, "offset": 0})
        )
        assert rows == []
        assert page["total_count"] == 0


class TestEntityBackedOwnership:
    def test_only_the_contracts_own_operator_may_sign_or_return_it(self):
        """PRD §2.1: "When `X-User-Role` is `OperatorBuyer`, `X-User-ID` is the
        `id` of the acting `Operator`; ownership checks on any resource that
        references an `Operator` compare the resource's foreign-key field to
        `X-User-ID` — concretely, the governing `Contract`'s `operator_id` must
        equal `X-User-ID` for signing, returning to draft, placing or
        substituting order lines, acknowledging, objecting to or (through the
        line's contract) disputing prices, and withdrawing a dispute."

        PRD §3.3: "Signature stamps `signed_at` from the logical clock and
        `signed_by_user_id` from `X-User-ID`, recomputes `compliance_posture`
        (which on a fresh contract with no closed period resolves to `OPEN`), and
        increments the contract's `version` by 1."

        Design: Corner/RBAC/entity_backed_buyer_cannot_act_for_another_operator
        """
        world = bootstrap_partners()
        other_operator = create_operator(
            legal_name="Cedar Ridge Dining", operator_code="CRD"
        )
        other_buyer = make_operator_buyer_headers(other_operator["id"])

        contract = create_contract_draft(
            world["operator_id"], world["manufacturer_id"]
        )
        contract_id = contract["id"]
        add_tier(contract_id, markup_value=25.00)
        add_coverage(contract_id, world["dc_id"])
        pending = validate_success(
            api_client.submit_contract_for_signature(contract_id, NAM)
        )
        assert pending["status"] == "PENDING_SIGNATURE"

        # Operator B carries the right role but the wrong entity id.
        validate_error(
            api_client.sign_contract(contract_id, other_buyer),
            "ERR_UNAUTHORIZED",
            403,
        )
        assert (
            validate_success(api_client.get_contract(contract_id, NAM))["status"]
            == "PENDING_SIGNATURE"
        )
        validate_error(
            api_client.return_contract_to_draft(
                contract_id, other_buyer, {"note": "Not my paper"}
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        signed = validate_success(
            api_client.sign_contract(contract_id, world["buyer"])
        )
        assert signed["status"] == "ACTIVE"
        assert signed["signed_by_user_id"] == world["operator_id"]
        assert signed["signed_at"].startswith("2026-08-01T00:00:00")
        assert signed["compliance_posture"] == "OPEN"


class TestSegregationOfDutiesOnActivation:
    def test_the_submitting_user_cannot_also_activate_the_agreement(self):
        """PRD §3.4: "Activation is the distributor's own final act and belongs to
        a `NationalAccountManager`."

        PRD §3.4: "It moves `MANUFACTURER_APPROVED → ACTIVE` and carries four
        preconditions beyond the from-state: the contract must be `ACTIVE`; the
        contract's `compliance_posture` must not be `RESTRICTED`; the activating
        `X-User-ID` must differ from the agreement's `submitted_by_user_id`; and
        the resolved `deviated_price_cents` must still be at or below
        `max_operator_price_cents`, since an intervening cost change may have
        moved it."

        PRD §2.8: "The activating manager is not the analyst who submitted —
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (409), on deviation activate."

        Design: Corner/RBAC/deviation_activation_cannot_be_performed_by_its_submitter
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"])
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[
                {
                    "product_class_code": "PROTEIN",
                    "cost_basis": "LAST_COST",
                    "markup_type": "PERCENT_OF_COST",
                    "markup_value": 25.00,
                    "min_case_volume": 0,
                }
            ],
        )
        contract_id = signed["contract_id"]

        deviation = create_deviation(
            contract_id,
            chicken["id"],
            world["manufacturer_id"],
            5000,
            TERM_START,
            NOV_START,
            requested_net_price_cents=4200,
        )
        submitted = submit_deviation(deviation["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == ANALYST_USER_ID
        approved = decide_deviation(
            deviation["id"], world["manufacturer_id"], "APPROVE", "Funded"
        )
        assert approved["status"] == "MANUFACTURER_APPROVED"

        # Same role, same endpoint — but the acting user id is the submitter's.
        validate_error(
            api_client.activate_deviation_agreement(
                deviation["id"],
                make_national_account_manager_headers(ANALYST_USER_ID),
            ),
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            409,
        )
        assert (
            validate_success(
                api_client.get_deviation_agreement(deviation["id"], ANALYST)
            )["status"]
            == "MANUFACTURER_APPROVED"
        )

        activated = validate_success(
            api_client.activate_deviation_agreement(
                deviation["id"], make_national_account_manager_headers(NAM_USER_ID)
            )
        )
        assert activated["status"] == "ACTIVE"
        assert activated["deviated_price_cents"] == 4200
