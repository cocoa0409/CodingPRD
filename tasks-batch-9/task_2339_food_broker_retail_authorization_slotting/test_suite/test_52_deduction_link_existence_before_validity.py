"""Optional body foreign keys are looked up before their semantics are judged."""

import pytest

from test_helpers import (
    AUDIT_MANAGER_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    DeductionReasonCode,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as F

AMOUNT_CENTS = 60000


@pytest.fixture
def two_principals_with_equal_shortages(api):
    """One chain, two principals, and one 60,000 SHORTAGE apiece."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    first_principal = fixtures.create_principal(api, slotting_budget_cents=20000000)
    second_principal = fixtures.create_principal(
        api, name="Sunglow Frozen", code="SGF", slotting_budget_cents=20000000
    )

    def shortage(principal):
        return fixtures.create_deduction(
            api,
            retailer["id"],
            principal["id"],
            reason_code=DeductionReasonCode.SHORTAGE,
            amount_cents=AMOUNT_CENTS,
            deduction_date="2026-08-01",
        )

    return {
        "retailer": retailer,
        "first_principal": first_principal,
        "second_principal": second_principal,
        "own_shortage": shortage(first_principal),
        "other_principals_shortage": shortage(second_principal),
    }


def attempt_deduction(api, scope, **overrides):
    payload = F.deduction_payload(
        scope["retailer"]["id"],
        scope["first_principal"]["id"],
        amount_cents=AMOUNT_CENTS,
        deduction_date="2026-08-01",
        **overrides,
    )
    return api.create_deduction(payload, make_retailer_buyer_headers(scope["retailer"]["id"]))


def file_the_duplicate_billback(api, scope):
    return get_success_data(
        attempt_deduction(
            api,
            scope,
            reason_code=DeductionReasonCode.DUPLICATE_BILLBACK,
            original_deduction_id=scope["own_shortage"]["id"],
        ),
        201,
    )


class TestDeductionLinkExistenceBeforeValidity:
    def test_an_unknown_promotion_link_is_a_not_found_rather_than_a_link_error(
        self, api, two_principals_with_equal_shortages
    ):
        """The optional body foreign key is resolved in the existence band, well before the link rule.

        PRD: "Body foreign keys are resolved after the path, in the order the payload declares them."

        PRD: "A `PROMO_BILLBACK` requires `promotion_event_id`, and the referenced event's
        authorization must belong to the same principal and the same chain, otherwise
        `ERR_PROMO_LINK_INVALID`; the field must be omitted for every other reason code."

        Design: Corner/endpoints/deduction_link_targets_must_exist_before_link_validity_is_judged
        """
        scope = two_principals_with_equal_shortages

        response = attempt_deduction(
            api,
            scope,
            reason_code=DeductionReasonCode.PROMO_BILLBACK,
            promotion_event_id=NON_EXISTENT_UUID,
        )

        validate_error(response, ApiErrorId.PROMOTION_NOT_FOUND, 404)

    def test_an_unknown_original_deduction_is_also_a_not_found(
        self, api, two_principals_with_equal_shortages
    ):
        """The 404 catalogue names one code per entity type, and it covers this field explicitly.

        PRD: "`ERR_PROMOTION_NOT_FOUND` and `ERR_DEDUCTION_NOT_FOUND` (covering
        `original_deduction_id`)."

        PRD: "**Existence.** Path identifiers are resolved left to right, then body foreign keys,
        yielding the 404 family described in §2.10."

        Design: Corner/endpoints/deduction_link_targets_must_exist_before_link_validity_is_judged
        """
        scope = two_principals_with_equal_shortages

        response = attempt_deduction(
            api,
            scope,
            reason_code=DeductionReasonCode.DUPLICATE_BILLBACK,
            original_deduction_id=NON_EXISTENT_UUID,
        )

        validate_error(response, ApiErrorId.DEDUCTION_NOT_FOUND, 404)

    def test_an_existing_link_of_another_principal_is_a_link_error_not_a_lookup_error(
        self, api, two_principals_with_equal_shortages
    ):
        """Same chain and the very same amount, but the wrong principal.

        PRD: "A `DUPLICATE_BILLBACK` requires `original_deduction_id` referencing a *different*
        deduction of the same chain and principal with an equal `amount_cents`, otherwise
        `ERR_DUPLICATE_LINK_INVALID`; that field too must be omitted for every other reason code."

        PRD: "`ERR_ITEM_NOT_IN_SUBMITTED_PRESENTATION` (422) applies to the award decision,
        `ERR_ITEM_PRINCIPAL_MISMATCH` (422) to presentation creation, and `ERR_DUPLICATE_LINK_INVALID`
        and `ERR_PROMO_LINK_INVALID` (422) to deduction creation."

        Design: Corner/endpoints/deduction_link_targets_must_exist_before_link_validity_is_judged
        """
        scope = two_principals_with_equal_shortages

        response = attempt_deduction(
            api,
            scope,
            reason_code=DeductionReasonCode.DUPLICATE_BILLBACK,
            original_deduction_id=scope["other_principals_shortage"]["id"],
        )

        validate_error(response, ApiErrorId.DUPLICATE_LINK_INVALID, 422)

    def test_the_correctly_scoped_link_is_accepted_and_both_charges_stay_open(
        self, api, two_principals_with_equal_shortages
    ):
        """Same chain, same principal, equal amount, different row — the link the rule describes.

        PRD: "A new deduction begins with `settlement_state` at `OPEN`, `dispute_state` at
        `NOT_DISPUTED`, `open_cents` equal to `amount_cents`, `claim_amount_cents`, `recovered_cents`,
        `conceded_cents`, `substantiation_doc_count` and `refile_count` all at 0, and
        `filed_by_user_id`, `approved_by_user_id` and `denial_reason` all null."

        PRD: "Creation immediately re-derives the principal's `open_deduction_cents`,
        `liability_ratio_bps` and `credit_posture`."

        Design: Corner/endpoints/deduction_link_targets_must_exist_before_link_validity_is_judged
        """
        scope = two_principals_with_equal_shortages

        duplicate = file_the_duplicate_billback(api, scope)

        assert duplicate["original_deduction_id"] == scope["own_shortage"]["id"]
        assert duplicate["open_cents"] == AMOUNT_CENTS
        assert duplicate["refile_count"] == 0
        principal = fixtures.get_principal(api, scope["first_principal"]["id"])
        assert principal["open_deduction_cents"] == AMOUNT_CENTS * 2

    def test_the_link_is_reverse_reachable_through_the_list_filter(
        self, api, two_principals_with_equal_shortages
    ):
        """Filtering by the target returns the billback that points at it, not the target itself.

        PRD: "Deductions may be filtered by `retailer_id`, `principal_id`, `promotion_event_id`,
        `original_deduction_id`, `reason_code`, `settlement_state` and `dispute_state`."

        Design: Corner/endpoints/deduction_link_targets_must_exist_before_link_validity_is_judged
        """
        scope = two_principals_with_equal_shortages
        duplicate = file_the_duplicate_billback(api, scope)

        rows, meta = validate_paginated(
            api.list_deductions(
                AUDIT_MANAGER_HEADERS, {"original_deduction_id": scope["own_shortage"]["id"]}
            )
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [duplicate["id"]]

    def test_the_reason_code_filter_excludes_the_linked_shortage(
        self, api, two_principals_with_equal_shortages
    ):
        """The first principal holds one SHORTAGE and one DUPLICATE_BILLBACK.

        PRD: "The `reason_code` is one of `PROMO_BILLBACK`, `SHORTAGE`, `COMPLIANCE_FINE` or
        `DUPLICATE_BILLBACK`, and two of them require a link."

        Design: Corner/endpoints/deduction_link_targets_must_exist_before_link_validity_is_judged
        """
        scope = two_principals_with_equal_shortages
        duplicate = file_the_duplicate_billback(api, scope)

        rows, meta = validate_paginated(
            api.list_deductions(
                AUDIT_MANAGER_HEADERS,
                {
                    "principal_id": scope["first_principal"]["id"],
                    "reason_code": DeductionReasonCode.DUPLICATE_BILLBACK,
                },
            )
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [duplicate["id"]]
