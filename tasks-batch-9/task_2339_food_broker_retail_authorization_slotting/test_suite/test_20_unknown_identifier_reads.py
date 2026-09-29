"""Every single-resource read names its own entity when the identifier is unknown."""

from test_helpers import (
    BROKER_ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    validate_error,
)


class TestUnknownIdentifierReads:
    def test_each_of_the_twelve_reads_carries_its_own_not_found_code(self, api):
        """One unknown identifier, twelve distinct entity-specific 404s.

        PRD: "The catalogue of not-found codes is one per entity type:
        `ERR_RETAILER_NOT_FOUND`, `ERR_PRINCIPAL_NOT_FOUND` (covering `principal_id`,
        `principal_a_id` and `principal_b_id`), `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_CONFLICT_RULE_NOT_FOUND`, `ERR_ITEM_NOT_FOUND` (covering an element of `item_ids`
        or of `authorized_item_ids`), `ERR_REVIEW_NOT_FOUND`, `ERR_PRESENTATION_NOT_FOUND`,
        `ERR_DEAL_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`,
        `ERR_PROMOTION_NOT_FOUND` and `ERR_DEDUCTION_NOT_FOUND` (covering
        `original_deduction_id`)."

        Design: Corner/entities/unknown_ids_on_every_single_resource_read_return_not_found
        """
        reads = [
            (api.get_retailer, ApiErrorId.RETAILER_NOT_FOUND),
            (api.get_principal, ApiErrorId.PRINCIPAL_NOT_FOUND),
            (api.get_agreement, ApiErrorId.AGREEMENT_NOT_FOUND),
            (api.get_conflict_rule, ApiErrorId.CONFLICT_RULE_NOT_FOUND),
            (api.get_item, ApiErrorId.ITEM_NOT_FOUND),
            (api.get_review, ApiErrorId.REVIEW_NOT_FOUND),
            (api.get_presentation, ApiErrorId.PRESENTATION_NOT_FOUND),
            (api.get_deal, ApiErrorId.DEAL_NOT_FOUND),
            (api.get_authorization, ApiErrorId.AUTHORIZATION_NOT_FOUND),
            (api.get_snapshot, ApiErrorId.SNAPSHOT_NOT_FOUND),
            (api.get_promotion, ApiErrorId.PROMOTION_NOT_FOUND),
            (api.get_deduction, ApiErrorId.DEDUCTION_NOT_FOUND),
        ]

        for read, expected_error_id in reads:
            validate_error(
                read(NON_EXISTENT_UUID, BROKER_ADMIN_HEADERS), expected_error_id, 404
            )

    def test_the_computed_voids_report_also_refuses_an_unknown_parent(self, api):
        """A derived read is not an excuse for an empty body.

        PRD: "Identifiers embedded in a URL path are resolved strictly left to right, and the
        first one that does not resolve determines the 404 response before any deeper lookup is
        attempted."

        Design: Corner/entities/unknown_ids_on_every_single_resource_read_return_not_found
        """
        response = api.get_voids_report(NON_EXISTENT_UUID, BROKER_ADMIN_HEADERS)

        validate_error(response, ApiErrorId.AUTHORIZATION_NOT_FOUND, 404)
