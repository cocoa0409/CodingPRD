"""Contingency Fee Agreement: singleton-per-case + immutability.

PRD §3.1 and §2.4.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_contingency_fee_agreement,
    create_case,
    create_client,
    create_contingency_fee_payload,
    setup_case_with_fee,
    validate_error,
    validate_success,
)


class TestContingencyFeeCreation:

    def test_create_returns_lean_entity_without_updated_at_or_version(
        self, api, managing_partner_headers,
    ):
        """PRD §2.4: "ContingencyFeeAgreement is immutable after
        creation and SettlementDisbursement is created once and never
        revised, so both carry only id and created_at — they expose
        neither updated_at nor version."

        Claim: contingency-fee response has no updated_at and no
        version field.
        """
        client = create_client()
        case = create_case(client["id"])
        resp = api.create_contingency_fee(
            case["id"], create_contingency_fee_payload(),
            managing_partner_headers,
        )
        fee = validate_success(resp, expected_status=201)
        assert_contingency_fee_agreement(fee)

    def test_second_fee_on_same_case_returns_already_exists(
        self, api, managing_partner_headers,
    ):
        """PRD §3.1: "The agreement is unique per case_id and immutable
        after creation; a second insert on the same case is rejected
        with ERR_FEE_AGREEMENT_ALREADY_EXISTS."

        Claim: Second POST /contingency-fee → 409
        ERR_FEE_AGREEMENT_ALREADY_EXISTS.
        """
        _, case, _ = setup_case_with_fee()
        resp = api.create_contingency_fee(
            case["id"], create_contingency_fee_payload(),
            managing_partner_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_FEE_AGREEMENT_ALREADY_EXISTS.value,
        )


class TestContingencyFeeRates:

    def test_default_rates_are_3333_4000_4500(
        self, api, managing_partner_headers,
    ):
        """PRD §3.1: "each defaulting respectively to 3333, 4000, and
        4500".

        Claim: when caller supplies the defaults explicitly, those
        rates are persisted.
        """
        client = create_client()
        case = create_case(client["id"])
        resp = api.create_contingency_fee(
            case["id"],
            create_contingency_fee_payload(
                pre_suit_rate_bps=3333,
                post_suit_rate_bps=4000,
                trial_rate_bps=4500,
            ),
            managing_partner_headers,
        )
        fee = validate_success(resp, expected_status=201)
        assert fee["pre_suit_rate_bps"] == 3333
        assert fee["post_suit_rate_bps"] == 4000
        assert fee["trial_rate_bps"] == 4500


class TestContingencyFeeRoleAuth:

    def test_paralegal_cannot_create_fee(
        self, api, paralegal_headers,
    ):
        """PRD §2.1: "If the role is recognized but is not authorized
        for the requested endpoint (per the RBAC implied by §4 and the
        workflow narratives in §3), the request is rejected with
        ERR_FORBIDDEN (HTTP 403)."

        Claim: Paralegal POST /contingency-fee → ERR_FORBIDDEN. PRD §4
        endpoint table restricts the operation to ManagingPartner and
        Attorney.
        """
        client = create_client()
        case = create_case(client["id"])
        resp = api.create_contingency_fee(
            case["id"], create_contingency_fee_payload(),
            paralegal_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
