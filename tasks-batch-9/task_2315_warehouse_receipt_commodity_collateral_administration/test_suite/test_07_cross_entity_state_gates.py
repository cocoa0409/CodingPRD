"""
Operations refused because of the state of an entity the caller never named:
the bin behind a delivery order, and the warehouse behind an indemnity claim.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal
from test_helpers.test_users import REGULATOR_HEADERS

APPOINTMENT_START = "2026-08-06T10:00:00Z"
APPOINTMENT_END = "2026-08-06T12:00:00Z"


class TestDeliveryOrderBlockedByBinCondition:
    @pytest.fixture
    def impaired_bin_scenario(self, base_full, assess_bin):
        assess_bin(base_full["warehouse_id"], base_full["bin_id"], 16.0, 70)
        return base_full

    def test_delivery_order_is_refused_while_the_bin_is_out_of_condition(
        self, api, impaired_bin_scenario
    ):
        """
        The receipt itself is ISSUED and unencumbered and the holder is booking
        its own grain, yet the booking is refused because the bin holding that
        grain is frozen — and no hold is placed on the bin.

        PRD: "All five refusals carry `ERR_BIN_OUT_OF_CONDITION`."

        Design: Difficulty/cross_entity_state_dependency/delivery_order_blocked_by_bin_out_of_condition
        """
        scenario = impaired_bin_scenario
        response = api.create_delivery_order(
            f.delivery_order_payload(
                scenario["receipt_id"], 400, APPOINTMENT_START, APPOINTMENT_END
            ),
            scenario["depositor_headers"],
        )

        validate_error(response, E.ERR_BIN_OUT_OF_CONDITION, 422)

        storage_bin = get_success_data(
            api.get_bin(scenario["bin_id"], scenario["operator_headers"]), 200
        )
        assert storage_bin["held_bushels"] == 0

    def test_the_same_booking_succeeds_once_the_bin_is_conditioned_back_to_watch(
        self, api, impaired_bin_scenario, assess_bin
    ):
        """
        A 14.2 percent reading at 70F derives WATCH rather than
        OUT_OF_CONDITION, which restores the receipt's quality flag to SOUND and
        unfreezes grain movement, so the identical request is admitted onto lane
        0 and places its 400-bushel hold.

        PRD: "Otherwise, if `moisture_pct` is at least 14.0 **or**
        `temperature_f` is strictly above 85, the target is `WATCH`."

        Design: Difficulty/cross_entity_state_dependency/delivery_order_blocked_by_bin_out_of_condition
        """
        scenario = impaired_bin_scenario
        api.create_delivery_order(
            f.delivery_order_payload(
                scenario["receipt_id"], 400, APPOINTMENT_START, APPOINTMENT_END
            ),
            scenario["depositor_headers"],
        )

        conditioned = assess_bin(scenario["warehouse_id"], scenario["bin_id"], 14.2, 70)
        assert conditioned["condition_state"] == "WATCH"
        receipt = get_success_data(
            api.get_receipt(scenario["receipt_id"], scenario["operator_headers"]), 200
        )
        assert receipt["quality_flag"] == "SOUND"

        order = get_success_data(
            api.create_delivery_order(
                f.delivery_order_payload(
                    scenario["receipt_id"], 400, APPOINTMENT_START, APPOINTMENT_END
                ),
                scenario["depositor_headers"],
            ),
            201,
        )
        assert_fields_equal(order, {"delivery_state": "REQUESTED", "lane_index": 0})

        storage_bin = get_success_data(
            api.get_bin(scenario["bin_id"], scenario["operator_headers"]), 200
        )
        assert storage_bin["held_bushels"] == 400


class TestIndemnityClaimRequiresClaimsOpen:
    @pytest.fixture
    def declared_warehouse(self, api, base_full):
        get_success_data(
            api.insolvency_action(
                base_full["warehouse_id"],
                f.insolvency_payload(
                    "DECLARE",
                    insolvency_price_cents_per_bushel=400,
                    note="operator default",
                ),
                REGULATOR_HEADERS,
            ),
            200,
        )
        return base_full

    def test_claim_filing_is_refused_while_the_insolvency_is_only_declared(
        self, api, declared_warehouse
    ):
        """
        Declaration alone does not open the claims window, so the filing is
        refused as an inadmissible transition and no claim row is created.

        PRD: "`OPEN_CLAIMS` then makes claim filing permitted for this warehouse
        and does nothing else."

        Design: Difficulty/cross_entity_state_dependency/indemnity_claim_requires_warehouse_claims_open
        """
        scenario = declared_warehouse
        response = api.create_indemnity_claim(
            f.indemnity_claim_payload(
                scenario["warehouse_id"],
                scenario["receipt_id"],
                scenario["depositor_id"],
                300000,
            ),
            scenario["depositor_headers"],
        )

        validate_error(response, E.ERR_INVALID_STATE, 409)

        claims, meta = validate_paginated(
            api.list_indemnity_claims(
                {"warehouse_id": scenario["warehouse_id"]}, REGULATOR_HEADERS
            )
        )
        assert claims == []
        assert meta["total_count"] == 0

    def test_the_identical_claim_is_accepted_the_moment_claims_are_open(
        self, api, declared_warehouse
    ):
        """
        With no change to the payload, moving the same warehouse to CLAIMS_OPEN
        admits the claim, which lands FILED for the asserted 300000 cents with
        both allocation shares still at zero.

        PRD: "A new claim starts `FILED` with `entitlement_cents`,
        `allowed_cents`, `bond_share_cents`, `fund_share_cents` and
        `unpaid_cents` all zero or unset and `adjudicated_by_user_id` and
        `adjudication_note` null."

        Design: Difficulty/cross_entity_state_dependency/indemnity_claim_requires_warehouse_claims_open
        """
        scenario = declared_warehouse
        api.create_indemnity_claim(
            f.indemnity_claim_payload(
                scenario["warehouse_id"],
                scenario["receipt_id"],
                scenario["depositor_id"],
                300000,
            ),
            scenario["depositor_headers"],
        )

        warehouse = get_success_data(
            api.insolvency_action(
                scenario["warehouse_id"],
                f.insolvency_payload("OPEN_CLAIMS"),
                REGULATOR_HEADERS,
            ),
            200,
        )
        assert warehouse["insolvency_state"] == "CLAIMS_OPEN"

        claim = get_success_data(
            api.create_indemnity_claim(
                f.indemnity_claim_payload(
                    scenario["warehouse_id"],
                    scenario["receipt_id"],
                    scenario["depositor_id"],
                    300000,
                ),
                scenario["depositor_headers"],
            ),
            201,
        )
        assert_fields_equal(
            claim,
            {
                "claim_state": "FILED",
                "claimed_cents": 300000,
                "bond_share_cents": 0,
                "fund_share_cents": 0,
            },
        )
