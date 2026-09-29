"""One unknown-identifier probe per collection: each single-resource read answers
with its own entity-specific not-found code rather than a shared generic one.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    validate_error,
)
from test_helpers.fixtures import ACCOUNTANT, ADMIN, ANALYST, AUDITOR, NAM


class TestNotFoundCodesArePerEntity:
    def test_each_collection_answers_with_its_own_not_found_code(self):
        """PRD §2.4: "Where a path does carry a parameter, it is validated left to
        right before any body field is examined; the path parameters in use are
        `operator_id`, `manufacturer_id`, `distribution_center_id`, `product_id`,
        `contract_id`, `contract_tier_id`, `dc_coverage_id`,
        `deviation_agreement_id`, `substitution_rule_id`,
        `price_change_notice_id`, `order_line_id`, `bill_back_claim_id`,
        `bill_back_remittance_id`, `rebate_period_id` and `pricing_dispute_id`."

        PRD §2.4: "Each has its own not-found code: `ERR_OPERATOR_NOT_FOUND`,
        `ERR_MANUFACTURER_NOT_FOUND`, `ERR_DISTRIBUTION_CENTER_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_CONTRACT_TIER_NOT_FOUND`, `ERR_DC_COVERAGE_NOT_FOUND`,
        `ERR_DEVIATION_NOT_FOUND`, `ERR_SUBSTITUTION_RULE_NOT_FOUND`,
        `ERR_PRICE_CHANGE_NOTICE_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`,
        `ERR_BILL_BACK_CLAIM_NOT_FOUND`, `ERR_BILL_BACK_REMITTANCE_NOT_FOUND`,
        `ERR_REBATE_PERIOD_NOT_FOUND` and `ERR_PRICING_DISPUTE_NOT_FOUND`, all
        HTTP 404."

        PRD §2.8: "Existence of every referenced id, path parameters first (left
        to right), then body foreign keys in declaration order — the matching
        `*_NOT_FOUND` code (404)."

        Design: Corner/Errors/unknown_identifier_probes_cover_the_remaining_not_found_codes
        """
        # Nothing is created: on an empty database every id is unknown, so the
        # code that comes back can only have been chosen by the collection.
        probes = [
            (
                api_client.get_operator(NON_EXISTENT_UUID, ADMIN),
                "ERR_OPERATOR_NOT_FOUND",
            ),
            (
                api_client.get_manufacturer(NON_EXISTENT_UUID, ADMIN),
                "ERR_MANUFACTURER_NOT_FOUND",
            ),
            (
                api_client.get_contract_tier(NON_EXISTENT_UUID, NAM),
                "ERR_CONTRACT_TIER_NOT_FOUND",
            ),
            (
                api_client.get_dc_coverage(NON_EXISTENT_UUID, NAM),
                "ERR_DC_COVERAGE_NOT_FOUND",
            ),
            (
                api_client.get_substitution_rule(NON_EXISTENT_UUID, NAM),
                "ERR_SUBSTITUTION_RULE_NOT_FOUND",
            ),
            (
                api_client.get_price_change_notice(NON_EXISTENT_UUID, ANALYST),
                "ERR_PRICE_CHANGE_NOTICE_NOT_FOUND",
            ),
            (
                api_client.get_bill_back_claim(NON_EXISTENT_UUID, ACCOUNTANT),
                "ERR_BILL_BACK_CLAIM_NOT_FOUND",
            ),
            (
                api_client.get_bill_back_remittance(NON_EXISTENT_UUID, ACCOUNTANT),
                "ERR_BILL_BACK_REMITTANCE_NOT_FOUND",
            ),
            (
                api_client.get_pricing_dispute(NON_EXISTENT_UUID, AUDITOR),
                "ERR_PRICING_DISPUTE_NOT_FOUND",
            ),
        ]

        seen = []
        for response, expected_error_id in probes:
            error = validate_error(response, expected_error_id, 404)
            assert error["error_id"] == expected_error_id
            assert error["message"].strip() != ""
            seen.append(error["error_id"])

        # Nine distinct codes: no collection borrowed another's.
        assert len(set(seen)) == 9
