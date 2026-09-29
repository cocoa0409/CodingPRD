"""Who is calling, in what capacity, on whose record, and whether they already acted."""

from test_helpers import (
    BREEDER,
    OFFICER,
    OFFICER_THREE,
    OFFICER_TWO,
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_line_item,
    build_user_headers,
    create_propagator,
    create_variety_payload,
    draft_report,
    licensed_quota,
    make_propagator_headers,
    validate_error,
    validate_success,
)


class TestEveryRequestMustCarryItsTwoHeaders:
    """Nothing at all is judged before the caller has identified itself."""

    def test_a_bodiless_creation_without_headers_never_reaches_the_schema_check(self, api):
        """Header presence is judged first, so a request that is also missing four
        required body fields is told it is unauthenticated rather than malformed.

        PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. If either header is absent or empty, the request fails immediately with `ERR_UNAUTHENTICATED` (HTTP 401); no statement about the role's permissions has been made at that point."

        Design: Corner/errors/request_without_a_role_header_returns_unauthenticated
        """
        validate_error(
            api.create_variety({"denomination": "Pinnacle Bramble"}, {}),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )

    def test_reads_are_authenticated_exactly_as_writes_are(self, api):
        """The rule is about every request rather than every mutation, so a listing
        without headers, and one whose identifier is empty, are both refused.

        PRD 2.8: "1. Header presence — `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/request_without_a_role_header_returns_unauthenticated
        """
        validate_error(
            api.list_varieties({}),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api.list_varieties(build_user_headers("", "BreederAdmin")),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )


class TestTheRoleGateOutranksExistence:
    """A propagator reaching for a breeding-office action, on a record that is absent."""

    def test_a_propagator_releasing_a_variety_is_refused_on_its_role(self, api):
        """Release belongs to the breeding rights office, and the role check runs
        before the path identifier is resolved, so the caller is told about its
        capacity and not about the missing variety.

        PRD 2.1: "Once both headers are present, the server checks that `X-User-Role` names one of the five declared roles **and** that the role is authorized for the endpoint being called. A role that is not declared, or is declared but not authorized for that endpoint, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). This check runs before the request body is parsed, so an unauthorized caller never learns whether its payload was well formed."

        Design: Corner/errors/breeder_only_endpoint_called_by_a_propagator_returns_forbidden_role
        """
        validate_error(
            api.release_variety(NON_EXISTENT_UUID,
                                make_propagator_headers(NON_EXISTENT_UUID)),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

    def test_the_same_call_by_the_breeding_office_reaches_the_lookup(self, api):
        """With an authorized role the request proceeds to path resolution, which
        proves it was the role gate that fired the first time.

        PRD 2.8: "4. Path identifier resolution, left to right, with the per-entity 404 codes above."

        Design: Corner/errors/breeder_only_endpoint_called_by_a_propagator_returns_forbidden_role
        """
        validate_error(
            api.release_variety(NON_EXISTENT_UUID, BREEDER),
            ApiErrorId.ERR_VARIETY_NOT_FOUND.value,
            404,
        )


class TestAnotherNurserysReportIsForbiddenRatherThanHidden:
    """Two nurseries; one of them owns the draft report.
    """

    def _two_nurseries_one_report(self, api):
        chain = licensed_quota(
            api, quality_tier="TIER_B", territory_class="DOMESTIC",
            allocated_units=5000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides={
                "denomination": "Quillon Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "QN",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"], propagator_name="Quillon One",
            home_territory_code="US-WA",
        )
        outsider = create_propagator(api, legal_name="Quillon Two",
                                     home_territory_code="US-OR")
        report = draft_report(
            api, chain, period_code="2026Q3",
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-11-01T00:00:00Z",
            due_at="2026-11-15T00:00:00Z",
        )
        add_line_item(api, chain, report["id"], 100)
        chain["report_id"] = report["id"]
        chain["outsider_headers"] = make_propagator_headers(outsider["id"])
        return chain

    def test_the_outsider_may_not_submit_and_changes_nothing(self, api):
        """The propagator reached from the report's agreement is not the acting one,
        so the submission is forbidden and the report is left untouched.

        PRD 2.1: "When the acting propagator is not the one reached that way, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403) — another propagator's resources are indistinguishable from forbidden ones, never from missing ones."

        Design: Corner/errors/propagator_cannot_submit_a_report_belonging_to_another_propagator
        """
        chain = self._two_nurseries_one_report(api)

        validate_error(
            api.submit_royalty_report(chain["report_id"], chain["outsider_headers"]),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
            403,
        )

        report = validate_success(api.get_royalty_report(chain["report_id"], OFFICER))
        assert report["review_status"] == "DRAFT"
        assert report["provisional_total_cents"] == 0

    def test_the_outsider_may_still_read_the_row(self, api):
        """Ownership gates the submission, not the shared read, so the other
        nursery's request for the record itself succeeds.

        PRD 2.1: "Concretely, for a royalty report or one of its line items the comparison is against the `propagator_id` recorded on the report's agreement, and for a tag order it is against the `propagator_id` on the agreement of the tag order's quota."

        Design: Corner/errors/propagator_cannot_submit_a_report_belonging_to_another_propagator
        """
        chain = self._two_nurseries_one_report(api)

        seen = validate_success(
            api.get_royalty_report(chain["report_id"], chain["outsider_headers"])
        )
        assert seen["id"] == chain["report_id"]

    def test_the_owning_nursery_submits_the_very_same_report(self, api):
        """Nothing about the report blocked the action, so the propagator the report
        does belong to carries it through.

        PRD 3.7: "The `Propagator` that holds the licence — the acting `X-User-ID` must equal the agreement's `propagator_id`, or the request is refused with `ERR_NOT_RESOURCE_OWNER` — submits the report, driving `review_status` `DRAFT → SUBMITTED`."

        Design: Corner/errors/propagator_cannot_submit_a_report_belonging_to_another_propagator
        """
        chain = self._two_nurseries_one_report(api)

        submitted = validate_success(
            api.submit_royalty_report(chain["report_id"], chain["propagator_headers"])
        )
        assert submitted["review_status"] == "SUBMITTED"
        assert submitted["provisional_total_cents"] == 3500


class TestEachEntityAnswersWithItsOwnNotFoundCode:
    """Fourteen codes are only individually observable one absent id at a time."""

    def test_the_licensing_chain_reports_its_four_distinct_codes(self, api):
        """Propagator, agreement, quota and tag order each carry their own code, so
        an absent identifier names the entity that could not be resolved.

        PRD 2.8: "Each entity has its own 404 code: `ERR_VARIETY_NOT_FOUND` for a `variety_id`, `ERR_PROTECTION_FILING_NOT_FOUND` for a `filing_id`, `ERR_TRIAL_SITE_NOT_FOUND` for a `trial_site_id`, `ERR_VARIETY_TRIAL_NOT_FOUND` for a `trial_id`, `ERR_PROPAGATOR_NOT_FOUND` for a `propagator_id` or a `suspected_propagator_id`, `ERR_AGREEMENT_NOT_FOUND` for an `agreement_id`, `ERR_QUOTA_NOT_FOUND` for a `quota_id`, `ERR_TAG_ORDER_NOT_FOUND` for a `tag_order_id`, `ERR_ROYALTY_REPORT_NOT_FOUND` for a `report_id` or a `royalty_report_id`, `ERR_LINE_ITEM_NOT_FOUND` for a `line_item_id`, `ERR_SUBLICENSE_GRANT_NOT_FOUND` for a `grant_id`, `ERR_SURVEILLANCE_CASE_NOT_FOUND` for a `case_id`, `ERR_GENETIC_TEST_NOT_FOUND` for a `test_id`, and `ERR_AUDIT_ENGAGEMENT_NOT_FOUND` for an `engagement_id`."

        Design: Corner/errors/unknown_path_ids_return_each_entity_specific_not_found_code
        """
        for getter, error_id in (
            (api.get_propagator, ApiErrorId.ERR_PROPAGATOR_NOT_FOUND),
            (api.get_propagator_agreement, ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
            (api.get_production_quota, ApiErrorId.ERR_QUOTA_NOT_FOUND),
            (api.get_tag_order, ApiErrorId.ERR_TAG_ORDER_NOT_FOUND),
        ):
            validate_error(getter(NON_EXISTENT_UUID, OFFICER), error_id.value, 404)

    def test_the_billing_and_enforcement_records_report_theirs(self, api):
        """The same one-code-per-entity discipline holds across the money and audit
        surfaces, down to a line item being distinguished from its report.

        PRD 2.8: "Every one of these carries HTTP 404."

        Design: Corner/errors/unknown_path_ids_return_each_entity_specific_not_found_code
        """
        for getter, error_id in (
            (api.get_royalty_report, ApiErrorId.ERR_ROYALTY_REPORT_NOT_FOUND),
            (api.get_royalty_line_item, ApiErrorId.ERR_LINE_ITEM_NOT_FOUND),
            (api.get_sublicense_grant, ApiErrorId.ERR_SUBLICENSE_GRANT_NOT_FOUND),
            (api.get_surveillance_case, ApiErrorId.ERR_SURVEILLANCE_CASE_NOT_FOUND),
            (api.get_audit_engagement, ApiErrorId.ERR_AUDIT_ENGAGEMENT_NOT_FOUND),
        ):
            validate_error(getter(NON_EXISTENT_UUID, OFFICER), error_id.value, 404)

        validate_error(api.get_variety(NON_EXISTENT_UUID, BREEDER),
                       ApiErrorId.ERR_VARIETY_NOT_FOUND.value, 404)
        validate_error(api.get_trial_site(NON_EXISTENT_UUID, BREEDER),
                       ApiErrorId.ERR_TRIAL_SITE_NOT_FOUND.value, 404)

    def test_the_path_segment_is_resolved_before_the_body_is_looked_up(self, api):
        """Creating a variety under an unresolvable name would fail the same way, but
        here the well-formed body is irrelevant: the absent case in the path decides
        the answer.

        PRD 2.8: "When a URL carries a templated identifier, the server resolves it before doing anything else, and it resolves identifiers **strictly left to right** so that the leftmost unresolvable identifier decides the error."

        Design: Corner/errors/unknown_path_ids_return_each_entity_specific_not_found_code
        """
        validate_error(
            api.create_variety(create_variety_payload(denomination="Pinnacle Bramble",
                                                      breeder_code="PN"),
                               make_propagator_headers(NON_EXISTENT_UUID)),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
        validate_error(
            api.get_protection_filing(NON_EXISTENT_UUID, BREEDER),
            ApiErrorId.ERR_PROTECTION_FILING_NOT_FOUND.value,
            404,
        )


class TestTheDeskNeedsThreeDistinctOfficers:
    """The countersigner may not accept; the accepter may not settle."""

    def _submitted_report_under_a_countersigned_agreement(self, api):
        chain = licensed_quota(
            api, quality_tier="TIER_B", territory_class="DOMESTIC",
            allocated_units=5000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides={
                "denomination": "Redstone Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "RS",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"], propagator_name="Redstone Nursery",
            home_territory_code="US-WA",
        )
        report = draft_report(
            api, chain, period_code="2026Q3",
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-11-01T00:00:00Z",
            due_at="2026-11-15T00:00:00Z",
        )
        add_line_item(api, chain, report["id"], 100)
        chain["report_id"] = report["id"]
        validate_success(
            api.submit_royalty_report(report["id"], chain["propagator_headers"])
        )
        return chain

    def test_the_countersigning_officer_may_not_accept(self, api):
        """The barrier compares the acting identifier against the one recorded at
        countersignature, so the officer who activated the licence is barred and
        the report keeps every acceptance field empty.

        PRD 2.10: "The officer whose `X-User-ID` was recorded as `countersigned_by_user_id` when the agreement was activated may not accept a royalty report filed under that agreement."

        Design: Corner/errors/report_accepted_by_the_countersigning_officer_returns_403
        """
        chain = self._submitted_report_under_a_countersigned_agreement(api)

        validate_error(
            api.accept_royalty_report(chain["report_id"], OFFICER),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )

        report = validate_success(api.get_royalty_report(chain["report_id"], OFFICER))
        assert report["review_status"] == "SUBMITTED"
        assert report["final_total_cents"] == 0
        assert report["accepted_by_user_id"] is None

    def test_a_second_officer_accepts_and_is_recorded_as_having_done_so(self, api):
        """Nothing about the report itself was wrong, so a different officer books
        it and the identity of the acceptor is written down for the next barrier.

        PRD 2.1: "The server records it where a business rule requires an audit trail (as `countersigned_by_user_id` and later `accepted_by_user_id` or `settled_by_user_id`, and as `finalized_by_user_id` on an audit engagement) but never compares it to any entity's `id`."

        Design: Corner/errors/report_accepted_by_the_countersigning_officer_returns_403
        """
        chain = self._submitted_report_under_a_countersigned_agreement(api)

        accepted = validate_success(
            api.accept_royalty_report(chain["report_id"], OFFICER_TWO)
        )
        assert accepted["review_status"] == "ACCEPTED"
        assert accepted["booked_amount_cents"] == 3500
        assert accepted["accepted_by_user_id"] == "officer-2"

    def test_the_accepting_officer_may_not_settle_but_a_third_one_can(self, api):
        """The mirror barrier bars the acceptor from paying its own acceptance, and
        the payment goes through under a third identifier.

        PRD 2.10: "The officer whose `X-User-ID` was recorded as `accepted_by_user_id` when a report was accepted may not settle that same report."

        Design: Corner/errors/report_accepted_by_the_countersigning_officer_returns_403
        """
        chain = self._submitted_report_under_a_countersigned_agreement(api)
        validate_success(api.accept_royalty_report(chain["report_id"], OFFICER_TWO))

        validate_error(
            api.settle_royalty_report(chain["report_id"], OFFICER_TWO),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )

        settled = validate_success(
            api.settle_royalty_report(chain["report_id"], OFFICER_THREE)
        )
        assert settled["settlement_status"] == "SETTLED"
        assert settled["settled_by_user_id"] == "officer-3"
        assert settled["review_status"] == "ACCEPTED"
