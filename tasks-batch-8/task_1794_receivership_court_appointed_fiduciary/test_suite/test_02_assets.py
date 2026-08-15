"""Asset lifecycle: marshalling, liquidation, abandonment, authority-limit gate."""
from test_helpers import (
    COURT,
    RECEIVER,
    ApiErrorId,
    assert_asset,
    create_asset,
    create_case,
    get_case,
    liquidate_asset,
    validate_error,
    validate_success,
)


class TestAssetCreation:
    def test_asset_created_in_identified_state(self, api):
        """PRD §3.2: "A marshalled asset starts `IDENTIFIED`, and its arrival
        immediately recomputes the case's `marshalled_value_cents`."

        Design: Corner/state_machines/asset_created_in_identified_state
        """
        case = create_case()
        resp = api.create_asset(
            {
                "case_id": case["id"],
                "description": "Forklift",
                "asset_class": "EQUIPMENT",
                "estimated_value_cents": 25000,
            },
            RECEIVER,
        )
        data = validate_success(resp, 201)
        assert_asset(data)
        assert data["status"] == "IDENTIFIED"
        assert data["liquidation_value_cents"] is None


class TestAssetLiquidation:
    def test_asset_liquidate_from_liquidated_returns_invalid_state(self, api):
        """PRD §3.2: "Two guards stand in front of the transition: the asset
        must actually be `IDENTIFIED` (otherwise `ERR_INVALID_STATE`), and
        the owning case must be `ACTIVE` (otherwise `ERR_CASE_NOT_ACTIVE`)."

        Design: Corner/state_machines/asset_liquidate_from_liquidated_returns_invalid_state
        """
        case = create_case()
        asset = create_asset(case["id"], description="Forklift",
                             asset_class="EQUIPMENT", estimated_value_cents=25000)
        liquidate_asset(asset["id"], 20000)

        resp = api.liquidate_asset(asset["id"], {"liquidation_value_cents": 99999}, RECEIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        case_data = get_case(case["id"])
        assert case_data["cash_on_hand_cents"] == 20000, (
            "rejected second liquidation must not double-count proceeds"
        )

    def test_asset_terminal_lockdown_abandon_after_liquidation(self, api):
        """PRD §3.2: "Both terminal asset states — `LIQUIDATED` and
        `ABANDONED` — are irreversible."

        Design: Corner/state_machines/asset_terminal_lockdown_abandon_after_liquidation
        """
        case = create_case()
        asset = create_asset(case["id"], description="Forklift",
                             asset_class="EQUIPMENT", estimated_value_cents=25000)
        liquidate_asset(asset["id"], 20000)

        resp = api.abandon_asset(asset["id"], {}, RECEIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestAuthorityLimitGate:
    def test_authority_limit_exact_equality_no_approval(self, api):
        """PRD §3.2: "When the estimated value is less than or equal to the
        limit — equality included — no authorization is required at all."
        PRD §3.2: "a missing `authorization_id` is rejected with
        `ERR_AUTHORIZATION_REQUIRED`"

        Design: Difficulty/boundary_precision_check/authority_limit_exact_equality_no_approval
        """
        case = create_case(authority_limit_cents=500000)
        at_limit = create_asset(case["id"], description="At-limit asset",
                                asset_class="EQUIPMENT", estimated_value_cents=500000)
        over_limit = create_asset(case["id"], description="Over-limit asset",
                                  asset_class="EQUIPMENT", estimated_value_cents=500001)

        resp1 = api.liquidate_asset(at_limit["id"], {"liquidation_value_cents": 400000}, RECEIVER)
        data1 = validate_success(resp1, 200)
        assert data1["status"] == "LIQUIDATED", (
            "estimated == limit requires NO approval"
        )

        resp2 = api.liquidate_asset(over_limit["id"], {"liquidation_value_cents": 400000}, RECEIVER)
        validate_error(resp2, ApiErrorId.ERR_AUTHORIZATION_REQUIRED)

    def test_authority_limit_over_by_one_cent_requires_approval(self, api):
        """PRD §3.2: "When the asset's `estimated_value_cents` is strictly
        greater than the case's `authority_limit_cents`, the request must
        carry an `authorization_id` referencing an `APPROVED` authorization
        request of the same case whose `request_type` is `ASSET_LIQUIDATION`
        and whose `related_asset_id` names this very asset; a missing
        `authorization_id` is rejected with `ERR_AUTHORIZATION_REQUIRED`"

        Design: Difficulty/boundary_precision_check/authority_limit_exact_equality_no_approval
        """
        case = create_case(authority_limit_cents=500000)
        asset = create_asset(case["id"], estimated_value_cents=500001)

        resp = api.liquidate_asset(asset["id"], {"liquidation_value_cents": 400000}, RECEIVER)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_REQUIRED)

        # Supplying a properly-scoped APPROVED ASSET_LIQUIDATION authorization unlocks it.
        auth = validate_success(
            api.create_authorization_request(
                {
                    "case_id": case["id"],
                    "request_type": "ASSET_LIQUIDATION",
                    "description": "Sell the over-limit asset",
                    "amount_cents": 1,
                    "related_asset_id": asset["id"],
                },
                RECEIVER,
            ),
            201,
        )
        api.decide_authorization_request(auth["id"], {"decision": "APPROVE"}, COURT)
        resp2 = api.liquidate_asset(
            asset["id"],
            {"liquidation_value_cents": 400000, "authorization_id": auth["id"]},
            RECEIVER,
        )
        assert validate_success(resp2, 200)["status"] == "LIQUIDATED"

    def test_liquidation_with_mismatched_authorization_rejected(self, api):
        """PRD §3.2: "one that resolves to a request that is not approved,
        has the wrong type, or points at a different asset is rejected with
        `ERR_AUTHORIZATION_MISMATCH`."

        Design: Corner/errors/liquidation_with_mismatched_authorization_rejected
        """
        case = create_case()
        # Seed cash so the EXPENDITURE approval succeeds.
        seed = create_asset(case["id"], asset_class="CASH", estimated_value_cents=100000)
        liquidate_asset(seed["id"], 100000)
        expenditure = validate_success(
            api.create_authorization_request(
                {
                    "case_id": case["id"],
                    "request_type": "EXPENDITURE",
                    "description": "Pay security vendor",
                    "amount_cents": 50000,
                },
                RECEIVER,
            ),
            201,
        )
        api.decide_authorization_request(expenditure["id"], {"decision": "APPROVE"}, COURT)
        big_asset = create_asset(case["id"], description="Office building",
                                 asset_class="REAL_PROPERTY", estimated_value_cents=600000)

        resp = api.liquidate_asset(
            big_asset["id"],
            {"liquidation_value_cents": 550000, "authorization_id": expenditure["id"]},
            RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_MISMATCH)


class TestImmediateConsistency:
    def test_immediate_visibility_of_liquidation_in_case_read(self, api):
        """PRD §2.4: "All derived values are recomputed immediately as part
        of the mutating request — consistency is immediate, and every
        mutation is visible in that request's own response."

        Design: Corner/consistency_model/immediate_visibility_of_liquidation_in_case_read
        """
        case = create_case()
        asset = create_asset(case["id"], description="Warehouse",
                             asset_class="REAL_PROPERTY", estimated_value_cents=80000)

        resp = api.liquidate_asset(asset["id"], {"liquidation_value_cents": 75000}, RECEIVER)
        data = validate_success(resp, 200)
        assert data["status"] == "LIQUIDATED"
        assert data["liquidation_value_cents"] == 75000

        case_data = get_case(case["id"])
        assert case_data["cash_on_hand_cents"] == 75000
        assert case_data["marshalled_value_cents"] == 75000, (
            "marshalled now reads the realized value"
        )
