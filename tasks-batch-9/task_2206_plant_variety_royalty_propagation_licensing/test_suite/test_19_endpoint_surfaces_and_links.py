"""Reading, listing and linking: the surfaces that are not state machines."""

from test_helpers import (
    AUDITOR,
    OFFICER,
    ApiErrorId,
    active_agreement,
    create_audit_engagement_payload,
    create_propagator,
    create_surveillance_case_payload,
    create_variety,
    draft_report,
    sample_case_payload,
    validate_error,
    validate_paginated,
    validate_success,
    NON_EXISTENT_UUID,
)


class TestThePropagatorReadAndListSurface:
    """Two registered nurseries, read singly and browsed."""

    def _two_propagators(self, api):
        first = create_propagator(api, legal_name="Juniper Hollow Nursery",
                                  home_territory_code="US-OR")
        second = create_propagator(api, legal_name="Kelso Valley Growers",
                                   home_territory_code="US-WA")
        return first, second

    def test_a_fresh_propagator_reads_back_at_every_clean_baseline(self, api):
        """The single-row read returns the two supplied fields plus the whole derived
        block, every part of which starts at its clean baseline.

        PRD 3.5: "Every one of a new propagator's derived fields starts at its clean baseline: `compliance_score` 100, `lifetime_compliance_score` 100, `royalty_payable_cents` 0, `royalty_settled_cents` 0, `damages_credit_cents` 0, `material_audit_finding_count` 0, and `version` 1."

        Design: Corner/endpoints/propagator_crud_surface_create_read_and_list
        """
        first, _second = self._two_propagators(api)

        row = validate_success(api.get_propagator(first["id"], AUDITOR))
        assert row["legal_name"] == "Juniper Hollow Nursery"
        assert row["home_territory_code"] == "US-OR"
        assert row["compliance_score"] == 100
        assert row["lifetime_compliance_score"] == 100
        assert row["royalty_payable_cents"] == 0
        assert row["royalty_settled_cents"] == 0
        assert row["damages_credit_cents"] == 0
        assert row["material_audit_finding_count"] == 0
        assert row["version"] == 1

    def test_the_register_is_browsable_and_filterable_by_home_territory(self, api):
        """Both rows come back unfiltered on one page, and the declared filter
        narrows the listing to the nursery operating from that territory.

        PRD 3.5: "Propagators can be browsed filtered by `home_territory_code`."

        Design: Corner/endpoints/propagator_crud_surface_create_read_and_list
        """
        _first, second = self._two_propagators(api)

        rows, meta = validate_paginated(api.list_propagators(OFFICER))
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(rows) == 2

        filtered, filtered_meta = validate_paginated(
            api.list_propagators(OFFICER, {"home_territory_code": "US-WA"})
        )
        assert filtered_meta["total_count"] == 1
        assert filtered[0]["id"] == second["id"]


class TestTheSampleActionWritesAndTransitionsAtOnce:
    """One call stores the sampled count and moves the case off OPENED."""

    def _opened_case(self, api, market_survey_ref="MS-2026-070"):
        variety = create_variety(
            api, denomination="Larkin Bramble", species="Rubus idaeus",
            breeder_code="LK", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        return validate_success(
            api.create_surveillance_case(
                create_surveillance_case_payload(
                    variety["id"], market_survey_ref=market_survey_ref
                ),
                AUDITOR,
            ),
            201,
        )

    def test_the_count_is_stored_and_the_status_moves_in_the_same_call(self, api):
        """Recording the collection both stores the payload figure and drives the
        transition, and the row's version turns once.

        PRD 3.9: "The auditor records the sample collection, driving `OPENED → SAMPLED`, supplying `sampled_unit_count` — the number of plants sampled in the market survey, which must be at least 1 when supplied."

        Design: Corner/endpoints/surveillance_sample_action_endpoint_drives_its_transition
        """
        case = self._opened_case(api)

        sampled = validate_success(
            api.sample_surveillance_case(case["id"], sample_case_payload(40), AUDITOR)
        )
        assert sampled["status"] == "SAMPLED"
        assert sampled["sampled_unit_count"] == 40
        assert sampled["version"] == 2

    def test_a_second_collection_is_refused_and_the_stored_count_stands(self, api):
        """The action has one declared origin, so repeating it finds the case past
        that origin and the first figure is not overwritten.

        PRD 3.9: "The transition stores the count and increments the case's `version` by 1."

        Design: Corner/endpoints/surveillance_sample_action_endpoint_drives_its_transition
        """
        case = self._opened_case(api)
        validate_success(
            api.sample_surveillance_case(case["id"], sample_case_payload(40), AUDITOR)
        )

        validate_error(
            api.sample_surveillance_case(case["id"], sample_case_payload(12), AUDITOR),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )
        assert validate_success(api.get_surveillance_case(case["id"], AUDITOR))[
            "sampled_unit_count"
        ] == 40

    def test_a_sample_of_zero_units_fails_the_field_constraint(self, api):
        """The field's own constraint is at least one, and that shape check runs
        before anything is looked up, so the case never moves.

        PRD 2.8: "Body shape and field-level constraints — `ERR_INVALID_REQUEST` (HTTP 400). The body must parse, must carry every required field, must carry no unknown field, and every value must satisfy its declared constraints: enum values must be declared members, integer quantities must be at least zero (or at least one where the field says so), decimal fields must carry no more precision than declared, and timestamps must be ISO 8601."

        Design: Corner/endpoints/surveillance_sample_action_endpoint_drives_its_transition
        """
        case = self._opened_case(api, market_survey_ref="MS-2026-071")

        validate_error(
            api.sample_surveillance_case(case["id"], sample_case_payload(0), AUDITOR),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        assert validate_success(api.get_surveillance_case(case["id"], AUDITOR))[
            "status"
        ] == "OPENED"

    def test_a_sampled_case_may_not_skip_the_testing_stage(self, api):
        """Concluding is declared only from the testing state, so a case that has
        merely been sampled cannot jump to a verdict.

        PRD 2.8: "This covers non-terminal but wrong-state attempts — granting a `DRAFT` filing, paying an annuity on a `GRANTED` filing, evaluating a `PLANNED` trial, reconciling a `REQUESTED` tag order, accepting a `DRAFT` report, settling a `SUBMITTED` report, disputing an already-`DISPUTED` report, activating an already-`ACTIVE` sublicense, concluding testing on a `SAMPLED` case."

        Design: Corner/endpoints/surveillance_sample_action_endpoint_drives_its_transition
        """
        case = self._opened_case(api)
        validate_success(
            api.sample_surveillance_case(case["id"], sample_case_payload(40), AUDITOR)
        )

        validate_error(
            api.conclude_testing(case["id"], AUDITOR),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )
        assert validate_success(api.get_surveillance_case(case["id"], AUDITOR))[
            "status"
        ] == "SAMPLED"


class TestTheEngagementLinkMustBeSelfConsistent:
    """Two licences, two reports, and the pairings between them."""

    def _two_agreements_each_with_a_report(self, api):
        create_variety(
            api, denomination="Mossvale Bramble", species="Rubus idaeus",
            breeder_code="MV", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        first = active_agreement(
            api, quality_tier="TIER_B", territory_codes=["US-WA"],
            propagator_name="Mossvale One", home_territory_code="US-WA",
        )
        second = active_agreement(
            api, quality_tier="TIER_B", territory_codes=["US-OR"],
            propagator_name="Mossvale Two", home_territory_code="US-OR",
        )
        first["report"] = draft_report(
            api, first, period_code="2026Q3",
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-11-01T00:00:00Z",
            due_at="2026-11-15T00:00:00Z",
        )
        second["report"] = draft_report(
            api, second, period_code="2026Q3",
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-11-01T00:00:00Z",
            due_at="2026-11-15T00:00:00Z",
        )
        return first, second

    def test_auditing_one_licence_against_anothers_report_is_refused(self, api):
        """Both identifiers resolve, but they do not belong together, and the
        engagement is refused rather than created on an inconsistent pair.

        PRD 3.9: "The two must belong together: the report's `agreement_id` must equal the supplied `agreement_id`, and a mismatch is rejected with `ERR_REPORT_ENGAGEMENT_MISMATCH` (HTTP 422)."

        Design: Corner/endpoints/audit_engagement_link_rejects_a_report_from_another_agreement
        """
        first, second = self._two_agreements_each_with_a_report(api)

        validate_error(
            api.create_audit_engagement(
                create_audit_engagement_payload(first["agreement_id"],
                                                second["report"]["id"]),
                AUDITOR,
            ),
            ApiErrorId.ERR_REPORT_ENGAGEMENT_MISMATCH.value,
            422,
        )

        _rows, meta = validate_paginated(api.list_audit_engagements(AUDITOR))
        assert meta["total_count"] == 0

    def test_the_matching_pair_opens_an_engagement_that_is_browsable_by_either_side(self, api):
        """Pairing the licence with its own report is accepted, the new engagement
        opens with nothing found yet, and it is discoverable from the agreement
        side while the other report shows no audit at all.

        PRD 3.9: "A new engagement starts in `OPENED` with `underreported_units` 0, null `finding_severity`, null `finalized_at` and `finalized_by_user_id`, and `version` 1."

        Design: Corner/endpoints/audit_engagement_link_rejects_a_report_from_another_agreement
        """
        first, second = self._two_agreements_each_with_a_report(api)

        engagement = validate_success(
            api.create_audit_engagement(
                create_audit_engagement_payload(first["agreement_id"],
                                                first["report"]["id"]),
                AUDITOR,
            ),
            201,
        )
        assert engagement["status"] == "OPENED"
        assert engagement["finding_severity"] is None
        assert engagement["underreported_units"] == 0
        assert engagement["version"] == 1

        _mine, mine_meta = validate_paginated(
            api.list_audit_engagements(AUDITOR, {"agreement_id": first["agreement_id"]})
        )
        assert mine_meta["total_count"] == 1

        _theirs, theirs_meta = validate_paginated(
            api.list_audit_engagements(
                AUDITOR, {"royalty_report_id": second["report"]["id"]}
            )
        )
        assert theirs_meta["total_count"] == 0

    def test_an_unknown_report_is_reported_as_missing_before_any_mismatch(self, api):
        """Body foreign keys are resolved before the business cross-check, so an
        identifier that names nothing yields the report's own 404 code.

        PRD 2.8: "Foreign keys supplied in the request **body** are resolved next, using the same per-entity 404 codes, and they are resolved in the order the fields are listed for that operation."

        Design: Corner/endpoints/audit_engagement_link_rejects_a_report_from_another_agreement
        """
        first, _second = self._two_agreements_each_with_a_report(api)

        validate_error(
            api.create_audit_engagement(
                create_audit_engagement_payload(first["agreement_id"],
                                                NON_EXISTENT_UUID),
                AUDITOR,
            ),
            ApiErrorId.ERR_ROYALTY_REPORT_NOT_FOUND.value,
            404,
        )
