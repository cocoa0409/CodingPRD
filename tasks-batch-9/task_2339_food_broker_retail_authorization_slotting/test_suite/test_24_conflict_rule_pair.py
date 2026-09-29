"""A conflict rule is an unordered edge between two different principals."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    BROKER_ADMIN_HEADERS,
    PRIMARY_CATEGORY,
    ApiErrorId,
    ConflictRuleStatus,
    ConflictScope,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as F
from test_helpers.assertions import assert_conflict_rule


@pytest.fixture
def one_chain_and_two_principals(api):
    """Bigmart plus Northwind and Sunglow, the two sides of the prospective edge."""
    return {
        "retailer": fixtures.create_retailer(api, total_store_count=1200),
        "northwind": fixtures.create_principal(api, name="Northwind Foods", code="NWF"),
        "sunglow": fixtures.create_principal(api, name="Sunglow Frozen", code="SGF"),
    }


def declare(api, a_id, b_id, **overrides):
    return api.create_conflict_rule(
        F.conflict_rule_payload(a_id, b_id, **overrides), BROKER_ADMIN_HEADERS
    )


class TestConflictRulePair:
    def test_a_self_loop_is_refused(self, api, one_chain_and_two_principals):
        """One principal cannot conflict with itself.

        PRD: "A conflict rule is unique per combination of `category_code`, the *unordered* pair
        of `principal_a_id` and `principal_b_id`, `scope` and `retailer_id`
        (`ERR_CONFLICT_RULE_DUPLICATE`), and the two sides must differ
        (`ERR_CONFLICT_RULE_SELF`)."

        Design: Corner/entities/conflict_rule_is_an_unordered_pair_junction_rejecting_self_and_duplicates
        """
        northwind_id = one_chain_and_two_principals["northwind"]["id"]

        response = declare(api, northwind_id, northwind_id)

        validate_error(response, ApiErrorId.CONFLICT_RULE_SELF, 409)

    def test_the_scope_enum_drives_a_conditional_field_requirement(
        self, api, one_chain_and_two_principals
    ):
        """A national edge must not name a chain, and a chain-level edge must.

        PRD: "Supplying `retailer_id` on a `NATIONAL` rule, or omitting it on a
        `RETAILER_LEVEL` rule, is a malformed request."

        Design: Corner/entities/conflict_rule_is_an_unordered_pair_junction_rejecting_self_and_duplicates
        """
        scope = one_chain_and_two_principals

        validate_error(
            declare(
                api,
                scope["northwind"]["id"],
                scope["sunglow"]["id"],
                scope=ConflictScope.NATIONAL,
                retailer_id=scope["retailer"]["id"],
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )
        validate_error(
            declare(
                api,
                scope["northwind"]["id"],
                scope["sunglow"]["id"],
                scope=ConflictScope.RETAILER_LEVEL,
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

    def test_a_national_edge_starts_active_with_no_chain_and_no_waiver(
        self, api, one_chain_and_two_principals
    ):
        """The declared edge is live immediately and carries no retirement reason.

        PRD: "A new rule starts with `status` at `ACTIVE` and `waiver_reason` null."

        Design: Corner/entities/conflict_rule_is_an_unordered_pair_junction_rejecting_self_and_duplicates
        """
        scope = one_chain_and_two_principals

        rule = get_success_data(
            declare(api, scope["northwind"]["id"], scope["sunglow"]["id"]), 201
        )

        assert_conflict_rule(rule)
        assert rule["status"] == ConflictRuleStatus.ACTIVE
        assert rule["scope"] == ConflictScope.NATIONAL
        assert rule["waiver_reason"] is None
        assert rule["retailer_id"] is None

    def test_reversing_the_two_sides_is_the_same_edge(self, api, one_chain_and_two_principals):
        """{Sunglow, Northwind} duplicates {Northwind, Sunglow} because the pair is unordered.

        PRD: "A conflict rule is a symmetric edge between two principals scoped to a category:
        it takes a `category_code` from `FROZEN_SNACKS`, `DAIRY`, `BEVERAGE`, `SNACK_NUTS` and
        `HBC`, a `principal_a_id` and a `principal_b_id` that must not be the same principal, and
        a `scope` of either `NATIONAL` — applying at every retail chain — or `RETAILER_LEVEL`,
        which applies only at one chain and therefore *requires* `retailer_id`."

        Design: Corner/entities/conflict_rule_is_an_unordered_pair_junction_rejecting_self_and_duplicates
        """
        scope = one_chain_and_two_principals
        get_success_data(declare(api, scope["northwind"]["id"], scope["sunglow"]["id"]), 201)

        response = declare(api, scope["sunglow"]["id"], scope["northwind"]["id"])

        validate_error(response, ApiErrorId.CONFLICT_RULE_DUPLICATE, 409)

    def test_a_differently_scoped_edge_for_the_same_pair_is_a_different_row(
        self, api, one_chain_and_two_principals
    ):
        """Scope and retailer_id are part of the identity, so the chain-level edge coexists.

        PRD: "A conflict rule is unique per combination of `category_code`, the *unordered* pair
        of `principal_a_id` and `principal_b_id`, `scope` and `retailer_id`
        (`ERR_CONFLICT_RULE_DUPLICATE`), and the two sides must differ
        (`ERR_CONFLICT_RULE_SELF`)."

        Design: Corner/entities/conflict_rule_is_an_unordered_pair_junction_rejecting_self_and_duplicates
        """
        scope = one_chain_and_two_principals
        national = get_success_data(
            declare(api, scope["northwind"]["id"], scope["sunglow"]["id"]), 201
        )

        chain_level = get_success_data(
            declare(
                api,
                scope["northwind"]["id"],
                scope["sunglow"]["id"],
                scope=ConflictScope.RETAILER_LEVEL,
                retailer_id=scope["retailer"]["id"],
            ),
            201,
        )

        assert chain_level["id"] != national["id"]
        assert chain_level["scope"] == ConflictScope.RETAILER_LEVEL
        assert chain_level["retailer_id"] == scope["retailer"]["id"]

    def test_both_principal_sides_are_independently_reachable(
        self, api, one_chain_and_two_principals
    ):
        """The edge answers to a filter on either endpoint, not just on side A.

        PRD: "Conflict rules may be filtered by `category_code`, `principal_a_id`,
        `principal_b_id`, `retailer_id`, `scope` and `status`; each principal side is
        independently reachable."

        Design: Corner/entities/conflict_rule_is_an_unordered_pair_junction_rejecting_self_and_duplicates
        """
        scope = one_chain_and_two_principals
        rule = get_success_data(declare(api, scope["northwind"]["id"], scope["sunglow"]["id"]), 201)

        by_side_b, meta_b = validate_paginated(
            api.list_conflict_rules(
                ACCOUNT_MANAGER_HEADERS,
                {"principal_b_id": scope["sunglow"]["id"], "category_code": PRIMARY_CATEGORY},
            )
        )
        assert meta_b["total_count"] == 1
        assert by_side_b[0]["id"] == rule["id"]

        by_side_a, meta_a = validate_paginated(
            api.list_conflict_rules(
                ACCOUNT_MANAGER_HEADERS, {"principal_a_id": scope["northwind"]["id"]}
            )
        )
        assert meta_a["total_count"] == 1
        assert by_side_a[0]["id"] == rule["id"]
