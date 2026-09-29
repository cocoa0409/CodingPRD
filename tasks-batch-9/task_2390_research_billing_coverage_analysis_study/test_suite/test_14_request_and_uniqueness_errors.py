"""The early rungs of the validation order: headers, pagination, existence,
uniqueness, and the guards that protect a grid from being edited twice.
"""

from test_helpers import (
    ANALYST_ONE,
    COORDINATOR_ONE,
    MANAGER_ONE,
    NO_AUTH_HEADERS,
    REMOVE,
    REVIEWER_ONE,
    UNDECLARED_ROLE_HEADERS,
    UNKNOWN_UUID,
    accrual_payload,
    api_client,
    build_calendar_generation,
    charge_review_payload,
    consent_payload,
    create_calendar_visit_payload,
    create_coverage_analysis_payload,
    create_coverage_item_payload,
    create_study_payload,
    create_study_subject_payload,
    determine_qct,
    item_spec,
    make_analyst_headers,
    make_coordinator_headers,
    make_manager_headers,
    make_reviewer_headers,
    open_accrual,
    qct_determination_payload,
    read_analysis,
    read_calendar,
    read_study,
    register_study,
    return_analysis,
    route_spec,
    setup_consented_subject,
    setup_open_to_accrual,
    setup_study_with_analysis_under_review,
    setup_study_with_approved_analysis,
    setup_study_with_draft_grid,
    setup_study_with_executed_budget,
    submit_analysis,
    validate_error,
    validate_paginated,
    validate_success,
    visit_spec,
)

SPONSOR_INFUSION = item_spec(
    "J9999",
    classification="RESEARCH_PAID",
    budget_category="PER_PATIENT",
    charge_master_unit_cents=50000,
    negotiated_unit_cents=40000,
    expected_occurrences=1,
)
LAB_PANEL_FIELDS = {
    "item_code": "80053",
    "description": "Comprehensive metabolic panel",
    "classification": "RESEARCH_PAID",
    "medicare_coverage_basis": "NOT_COVERED",
    "budget_category": "PER_PATIENT",
    "charge_master_unit_cents": 9000,
    "negotiated_unit_cents": 9000,
    "expected_occurrences": 3,
}


def _all_studies():
    return validate_paginated(
        api_client.list_studies(make_manager_headers(MANAGER_ONE))
    )


class TestHeadersComeFirst:
    """Priority 1 runs before the body is even examined."""

    def test_01_a_request_without_role_headers_is_unauthenticated_not_invalid(self):
        """The body is also malformed, and the answer is still the header failure,
        with nothing persisted.

        PRD §2.11: "1. Header presence and role validity — `ERR_UNAUTHENTICATED`
        (401), on every endpoint. 2. Role authorization for the endpoint —
        `ERR_UNAUTHORIZED` (403), on every endpoint. 3. Body shape: required fields
        present, enum members valid, integers non-negative where constrained,
        dates in `YYYY-MM-DD` form"

        Design: Corner/errors/unauthenticated_request_without_role_header_is_rejected
        """
        malformed = create_study_payload(
            protocol_number="AMC-2390-C48", funding_source=REMOVE
        )
        validate_error(
            api_client.create_study(malformed, NO_AUTH_HEADERS),
            "ERR_UNAUTHENTICATED",
            401,
        )
        # An unrecognised role fails the same rung.
        validate_error(
            api_client.create_study(malformed, UNDECLARED_ROLE_HEADERS),
            "ERR_UNAUTHENTICATED",
            401,
        )
        validate_error(
            api_client.list_studies(NO_AUTH_HEADERS), "ERR_UNAUTHENTICATED", 401
        )

        _, meta = _all_studies()
        assert meta["total_count"] == 0

        # With headers, the body failure surfaces — and still persists nothing.
        validate_error(
            api_client.create_study(malformed, make_manager_headers(MANAGER_ONE)),
            "ERR_INVALID_REQUEST",
            400,
        )
        _, meta = _all_studies()
        assert meta["total_count"] == 0


class TestUniquenessOfTheProtocolNumber:
    """The identity of a study is its protocol number, globally."""

    def test_02_a_second_registration_of_one_protocol_number_is_refused(self):
        """Every other field differs and the number alone decides.

        PRD §3.1: "The `protocol_number` is between 1 and 40 characters long and
        must be unique across every study on file; a repeat is refused with
        `ERR_DUPLICATE_PROTOCOL_NUMBER`."

        Design: Corner/errors/duplicate_protocol_number_is_rejected
        """
        first = register_study(
            protocol_number="AMC-2390-C50",
            title="A Phase II Study of Investigational Therapy",
            sponsor_name="Northgate Therapeutics",
            funding_source="INDUSTRY_SPONSORED",
            ind_ide_status="IND_HELD",
            therapeutic_intent=True,
        )

        validate_error(
            api_client.create_study(
                create_study_payload(
                    protocol_number="AMC-2390-C50",
                    title="An entirely different protocol",
                    sponsor_name="Harborline Biosciences",
                    funding_source="FEDERALLY_FUNDED",
                    ind_ide_status="NONE",
                    therapeutic_intent=False,
                    registry_number="NCT10000150",
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            "ERR_DUPLICATE_PROTOCOL_NUMBER",
            409,
        )

        rows, meta = _all_studies()
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["title"] == "A Phase II Study of Investigational Therapy"
        assert rows[0]["funding_source"] == "INDUSTRY_SPONSORED"

        # The rule is on the value, so one character of difference is enough.
        second = validate_success(
            api_client.create_study(
                create_study_payload(protocol_number="AMC-2390-C51"),
                make_manager_headers(MANAGER_ONE),
            ),
            201,
        )
        assert second["protocol_number"] == "AMC-2390-C51"
        _, meta = _all_studies()
        assert meta["total_count"] == 2


class TestPaginationBoundsAreRejectedNotClamped:
    """The maximum is a validation boundary, not a ceiling."""

    def test_03_a_limit_one_past_the_maximum_is_refused(self):
        """101 is refused, 100 is accepted and echoed, and the two other bounds
        behave the same way.

        PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10,
        may not be smaller than 1, and may not be larger than 100. `offset` is the
        number of rows to skip and defaults to 0; it may not be negative. A `limit`
        outside the range 1 through 100 inclusive, or a negative `offset`, is
        rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/errors/pagination_limit_above_the_maximum_is_rejected
        """
        register_study(protocol_number="AMC-2390-C52")
        headers = make_manager_headers(MANAGER_ONE)

        for params in ({"limit": 101}, {"limit": 0}, {"offset": -1}):
            validate_error(
                api_client.list_studies(headers, params=params),
                "ERR_INVALID_PAGINATION",
                400,
            )

        rows, meta = validate_paginated(
            api_client.list_studies(headers, params={"limit": 100})
        )
        assert meta["limit"] == 100
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1

        _, default_meta = validate_paginated(api_client.list_studies(headers))
        assert default_meta["limit"] == 10
        assert default_meta["offset"] == 0


class TestTheNotFoundFamilyIsPerResource:
    """One unused identifier, eight different codes."""

    def test_04_each_resource_path_reports_its_own_404(self):
        """Existence is decided before state, so the action endpoints answer 404
        rather than a state conflict.

        PRD §2.11: "6. Existence of the other path-segment resources, each on its
        own paths: `ERR_ANALYSIS_NOT_FOUND` under
        `/research-billing/coverage-analyses/{id}`, and likewise
        `ERR_CALENDAR_NOT_FOUND`, `ERR_SUBJECT_NOT_FOUND`,
        `ERR_SUBJECT_VISIT_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
        `ERR_AMENDMENT_NOT_FOUND`, and `ERR_ROUTE_NOT_FOUND` (all 404)."

        Design: Corner/errors/not_found_family_is_distinct_per_resource_path
        """
        manager = make_manager_headers(MANAGER_ONE)
        reads = (
            (api_client.get_study(UNKNOWN_UUID, manager), "ERR_STUDY_NOT_FOUND"),
            (
                api_client.get_coverage_analysis(UNKNOWN_UUID, manager),
                "ERR_ANALYSIS_NOT_FOUND",
            ),
            (
                api_client.get_study_calendar(UNKNOWN_UUID, manager),
                "ERR_CALENDAR_NOT_FOUND",
            ),
            (
                api_client.get_study_subject(UNKNOWN_UUID, manager),
                "ERR_SUBJECT_NOT_FOUND",
            ),
            (
                api_client.get_subject_visit(UNKNOWN_UUID, manager),
                "ERR_SUBJECT_VISIT_NOT_FOUND",
            ),
            (api_client.get_charge(UNKNOWN_UUID, manager), "ERR_CHARGE_NOT_FOUND"),
            (
                api_client.get_audit_finding(UNKNOWN_UUID, manager),
                "ERR_FINDING_NOT_FOUND",
            ),
            (
                api_client.get_visit_charge_route(UNKNOWN_UUID, manager),
                "ERR_ROUTE_NOT_FOUND",
            ),
        )
        for response, expected in reads:
            validate_error(response, expected, 404)

        actions = (
            (
                api_client.set_accrual(
                    UNKNOWN_UUID, accrual_payload(), manager
                ),
                "ERR_STUDY_NOT_FOUND",
            ),
            (
                api_client.submit_coverage_analysis(
                    UNKNOWN_UUID, make_analyst_headers(ANALYST_ONE)
                ),
                "ERR_ANALYSIS_NOT_FOUND",
            ),
            (
                api_client.publish_study_calendar(
                    UNKNOWN_UUID, make_reviewer_headers(REVIEWER_ONE)
                ),
                "ERR_CALENDAR_NOT_FOUND",
            ),
            (
                api_client.review_charge(
                    UNKNOWN_UUID,
                    charge_review_payload("HOLD_FOR_SPONSOR"),
                    make_reviewer_headers(REVIEWER_ONE),
                ),
                "ERR_CHARGE_NOT_FOUND",
            ),
            (
                api_client.submit_sponsor_invoice(UNKNOWN_UUID, manager),
                "ERR_INVOICE_NOT_FOUND",
            ),
            (
                api_client.implement_amendment(UNKNOWN_UUID, manager),
                "ERR_AMENDMENT_NOT_FOUND",
            ),
        )
        for response, expected in actions:
            validate_error(response, expected, 404)


class TestOnlyOneOpenRevisionPerStudy:
    """DRAFT, UNDER_REVIEW and RETURNED all count as open."""

    def test_05_a_second_revision_is_refused_in_all_three_open_statuses(self):
        """The refusal consumes nothing: the study version quoted on the rejected
        request is still current afterwards.

        PRD §3.2: "Only one analysis per study may be open at a time: if the study
        already has an analysis whose `status` is `DRAFT`, `UNDER_REVIEW`, or
        `RETURNED`, the create is refused with `ERR_OPEN_ANALYSIS_EXISTS`."

        Design: Corner/errors/second_open_analysis_on_one_study_is_rejected
        """
        ctx = setup_study_with_draft_grid(
            [SPONSOR_INFUSION], study_overrides={"protocol_number": "AMC-2390-C53"}
        )
        study_id = ctx["study"]["id"]
        assert ctx["study"]["version"] == 2
        assert ctx["analysis"]["status"] == "DRAFT"

        def _attempt():
            return api_client.create_coverage_analysis(
                create_coverage_analysis_payload(study_id, 2),
                make_analyst_headers(ANALYST_ONE),
            )

        validate_error(_attempt(), "ERR_OPEN_ANALYSIS_EXISTS", 409)
        assert read_study(study_id)["version"] == 2

        submit_analysis(ctx["analysis"]["id"])
        assert read_analysis(ctx["analysis"]["id"])["status"] == "UNDER_REVIEW"
        validate_error(_attempt(), "ERR_OPEN_ANALYSIS_EXISTS", 409)

        return_analysis(ctx["analysis"]["id"])
        assert read_analysis(ctx["analysis"]["id"])["status"] == "RETURNED"
        validate_error(_attempt(), "ERR_OPEN_ANALYSIS_EXISTS", 409)

        _, meta = validate_paginated(
            api_client.list_coverage_analyses(
                make_manager_headers(MANAGER_ONE), params={"study_id": study_id}
            )
        )
        assert meta["total_count"] == 1
        assert read_study(study_id)["version"] == 2


class TestTheGridIsEditableOnlyInTwoStatuses:
    """The domain-specific code wins over the generic one on this endpoint."""

    def test_06_an_item_add_to_an_under_review_analysis_is_refused_then_allowed(self):
        """Returning the analysis makes the identical add succeed and reopens the
        analysis to `DRAFT` in the same request.

        PRD §3.2: "Items may only be added while the analysis is `DRAFT` or
        `RETURNED`; on any other status the add fails with
        `ERR_ANALYSIS_NOT_EDITABLE`. Adding an item to a `RETURNED` analysis is
        also how the analyst reopens it — the analysis moves `RETURNED → DRAFT` in
        the same request, which closes the review cycle and lets the analyst submit
        again."

        Design: Corner/errors/adding_an_item_to_an_under_review_analysis_is_rejected
        """
        ctx = setup_study_with_analysis_under_review(
            [SPONSOR_INFUSION], study_overrides={"protocol_number": "AMC-2390-C54"}
        )
        analysis_id = ctx["analysis"]["id"]
        assert ctx["analysis"]["status"] == "UNDER_REVIEW"
        assert ctx["analysis"]["version"] == 3

        validate_error(
            api_client.create_coverage_item(
                create_coverage_item_payload(analysis_id, 3, **LAB_PANEL_FIELDS),
                make_analyst_headers(ANALYST_ONE),
            ),
            "ERR_ANALYSIS_NOT_EDITABLE",
            409,
        )
        blocked = read_analysis(analysis_id)
        assert blocked["item_count"] == 1
        assert blocked["status"] == "UNDER_REVIEW"
        assert blocked["version"] == 3

        returned = return_analysis(analysis_id)
        assert returned["status"] == "RETURNED"
        assert returned["version"] == 4

        added = validate_success(
            api_client.create_coverage_item(
                create_coverage_item_payload(analysis_id, 4, **LAB_PANEL_FIELDS),
                make_analyst_headers(ANALYST_ONE),
            ),
            201,
        )
        assert added["item_code"] == "80053"
        reopened = read_analysis(analysis_id)
        assert reopened["status"] == "DRAFT"
        assert reopened["item_count"] == 2
        assert reopened["return_count"] == 1


class TestUniquenessIsScopedToItsOwner:
    """An item code is unique within one analysis; a sequence index within one
    calendar."""

    def test_07_the_same_item_code_twice_on_one_analysis_is_refused(self):
        """The identical code is accepted on another study's analysis in the same
        run, so the scope is the analysis and not the institution.

        PRD §2.11: "24. Uniqueness (all 409): `protocol_number` globally on study
        registration reports `ERR_DUPLICATE_PROTOCOL_NUMBER`; `item_code` within
        one analysis reports `ERR_DUPLICATE_ITEM_CODE`"

        Design: Corner/errors/duplicate_item_code_on_one_analysis_is_rejected
        """
        ctx = setup_study_with_draft_grid(
            [], study_overrides={"protocol_number": "AMC-2390-C55"}
        )
        other = setup_study_with_draft_grid(
            [], study_overrides={"protocol_number": "AMC-2390-C55B"}
        )

        validate_success(
            api_client.create_coverage_item(
                create_coverage_item_payload(ctx["analysis"]["id"], 1, **LAB_PANEL_FIELDS),
                make_analyst_headers(ANALYST_ONE),
            ),
            201,
        )
        after_first = read_analysis(ctx["analysis"]["id"])
        assert after_first["item_count"] == 1

        validate_error(
            api_client.create_coverage_item(
                create_coverage_item_payload(
                    ctx["analysis"]["id"], after_first["version"], **LAB_PANEL_FIELDS
                ),
                make_analyst_headers(ANALYST_ONE),
            ),
            "ERR_DUPLICATE_ITEM_CODE",
            409,
        )
        unchanged = read_analysis(ctx["analysis"]["id"])
        assert unchanged["item_count"] == 1
        assert unchanged["version"] == after_first["version"]

        elsewhere = validate_success(
            api_client.create_coverage_item(
                create_coverage_item_payload(
                    other["analysis"]["id"], 1, **LAB_PANEL_FIELDS
                ),
                make_analyst_headers(ANALYST_ONE),
            ),
            201,
        )
        assert elsewhere["item_code"] == "80053"
        assert read_analysis(other["analysis"]["id"])["item_count"] == 1

    def test_08_a_repeated_sequence_index_is_refused_even_with_no_window_clash(self):
        """The second visit sits far away in the day space, so the duplicate index
        is the only defect left to report.

        PRD §3.4: "a `sequence_index` giving the visit's order within the
        calendar" … "which must be at least 1 and must be unique within the
        calendar — a repeat is `ERR_DUPLICATE_SEQUENCE_INDEX`."

        Design: Corner/errors/duplicate_calendar_visit_sequence_index_is_rejected
        """
        ctx = setup_study_with_approved_analysis(
            [SPONSOR_INFUSION],
            qct_basis=None,
            study_overrides={"protocol_number": "AMC-2390-C56"},
        )
        ctx = build_calendar_generation(ctx, [visit_spec("Screening", 1, 0, 0, 3)])
        calendar_id = ctx["calendar"]["id"]

        far_away = create_calendar_visit_payload(
            calendar_id,
            visit_name="Follow-up",
            sequence_index=1,
            target_day_offset=40,
            window_before_days=0,
            window_after_days=0,
        )
        validate_error(
            api_client.create_calendar_visit(
                far_away, make_analyst_headers(ANALYST_ONE)
            ),
            "ERR_DUPLICATE_SEQUENCE_INDEX",
            409,
        )
        blocked = read_calendar(calendar_id)
        assert blocked["visit_count"] == 1

        accepted = dict(far_away)
        accepted["sequence_index"] = 2
        added = validate_success(
            api_client.create_calendar_visit(
                accepted, make_analyst_headers(ANALYST_ONE)
            ),
            201,
        )
        assert added["sequence_index"] == 2
        assert added["window_start_day"] == 40
        assert added["window_end_day"] == 40
        assert read_calendar(calendar_id)["visit_count"] == 2


class TestAccrualGatesOnSubjectRegistration:
    """A subject may not exist before the protocol is open."""

    def test_09_registering_a_subject_on_a_closed_protocol_is_refused(self):
        """The study exists, so this is the cross-entity state guard rather than a
        404, and opening the protocol is the only change needed.

        PRD §3.6: "Registration requires the study's `lifecycle_status` to be
        `OPEN_TO_ACCRUAL`, or the attempt is `ERR_STUDY_NOT_OPEN_TO_ACCRUAL`."

        Design: Corner/errors/registering_a_subject_before_accrual_opens_is_rejected
        """
        ctx = setup_study_with_executed_budget(
            [SPONSOR_INFUSION],
            qct_registry_number="NCT10000157",
            study_overrides={"protocol_number": "AMC-2390-C57"},
        )
        ctx = build_calendar_generation(
            ctx,
            [visit_spec("Cycle 1 Day 1", 1, 0, 0, 3)],
            [route_spec("Cycle 1 Day 1", "J9999")],
            publish=True,
        )
        assert ctx["study"]["lifecycle_status"] == "COVERAGE_APPROVED"

        payload = create_study_subject_payload(ctx["study"]["id"], subject_number="S-001")
        validate_error(
            api_client.create_study_subject(
                payload, make_coordinator_headers(COORDINATOR_ONE)
            ),
            "ERR_STUDY_NOT_OPEN_TO_ACCRUAL",
            409,
        )
        _, meta = validate_paginated(
            api_client.list_study_subjects(
                make_manager_headers(MANAGER_ONE),
                params={"study_id": ctx["study"]["id"]},
            )
        )
        assert meta["total_count"] == 0

        opened = open_accrual(ctx["study"]["id"])
        assert opened["lifecycle_status"] == "OPEN_TO_ACCRUAL"

        subject = validate_success(
            api_client.create_study_subject(
                payload, make_coordinator_headers(COORDINATOR_ONE)
            ),
            201,
        )
        assert subject["status"] == "SCREENING"
        assert subject["subject_number"] == "S-001"
        assert subject["consented_calendar_id"] is None
        assert subject["consented_calendar_generation"] is None
        assert subject["consent_date"] is None
        assert subject["charge_count"] == 0


class TestTheDeterminationMustMatchTheStudysFooting:
    """The basis is checked against the study's own facts, one pairing each."""

    def test_10_a_federal_basis_on_an_industry_study_is_unsupported(self):
        """The very same study qualifies under the IND basis, so the refusal is
        about the pairing and not about qualifying in general.

        PRD §3.1: "Each basis must be supported by the study's own facts, or the
        request fails with `ERR_QCT_BASIS_UNSUPPORTED`. `DEEMED_IND_IDE` requires
        the study's `ind_ide_status` to be either `IND_HELD` or `IDE_CATEGORY_B` —
        notably `IDE_CATEGORY_A` does not qualify. `DEEMED_FEDERALLY_FUNDED`
        requires the `funding_source` to be `FEDERALLY_FUNDED`. `SELF_CERTIFIED`
        requires `therapeutic_intent` to be true."

        Design: Corner/errors/qct_basis_unsupported_by_the_studys_footing_is_rejected
        """
        industry = register_study(
            protocol_number="AMC-2390-C58",
            funding_source="INDUSTRY_SPONSORED",
            ind_ide_status="IND_HELD",
            therapeutic_intent=True,
        )
        validate_error(
            api_client.record_qct_determination(
                industry["id"],
                qct_determination_payload(
                    basis="DEEMED_FEDERALLY_FUNDED", registry_number="NCT10000158"
                ),
                make_reviewer_headers(REVIEWER_ONE),
            ),
            "ERR_QCT_BASIS_UNSUPPORTED",
            422,
        )
        unchanged = read_study(industry["id"])
        assert unchanged["qct_determination"] == "UNDETERMINED"
        assert unchanged["qct_basis"] is None
        assert unchanged["registry_number"] is None
        assert unchanged["version"] == 1

        # The other two pairings fail on their own facts too.
        category_a = register_study(
            protocol_number="AMC-2390-C59",
            ind_ide_status="IDE_CATEGORY_A",
            therapeutic_intent=False,
        )
        validate_error(
            api_client.record_qct_determination(
                category_a["id"],
                qct_determination_payload(
                    basis="DEEMED_IND_IDE", registry_number="NCT10000159"
                ),
                make_reviewer_headers(REVIEWER_ONE),
            ),
            "ERR_QCT_BASIS_UNSUPPORTED",
            422,
        )
        validate_error(
            api_client.record_qct_determination(
                category_a["id"],
                qct_determination_payload(
                    basis="SELF_CERTIFIED", registry_number="NCT10000159"
                ),
                make_reviewer_headers(REVIEWER_ONE),
            ),
            "ERR_QCT_BASIS_UNSUPPORTED",
            422,
        )

        # The supported basis on the industry study is accepted.
        determined = determine_qct(
            industry["id"], basis="DEEMED_IND_IDE", registry_number="NCT10000158"
        )
        assert determined["qct_determination"] == "DEEMED_QUALIFYING"
        assert determined["qct_basis"] == "DEEMED_IND_IDE"
        assert determined["billing_hold_posture"] == "OPEN"


class TestSubjectIdentityAndOneShotConsent:
    """A subject number is unique per study, and consent happens once."""

    def test_11_a_repeated_subject_number_and_a_second_consent_are_both_refused(self):
        """The two refusals are distinct codes, and the same number is free on
        another protocol.

        PRD §3.6: "A `StudyCoordinator` registers a subject on a study open to
        accrual with a `study_id` and a `subject_number` that must be unique within
        the study, or `ERR_DUPLICATE_SUBJECT_NUMBER`."

        Design: Corner/errors/duplicate_subject_number_and_second_consent_are_rejected
        """
        ctx = setup_open_to_accrual(
            [SPONSOR_INFUSION],
            [visit_spec("Cycle 1 Day 1", 1, 0, 0, 3)],
            [route_spec("Cycle 1 Day 1", "J9999")],
            qct_registry_number="NCT10000160",
            study_overrides={"protocol_number": "AMC-2390-C60"},
        )
        subject = setup_consented_subject(ctx, subject_number="S-001")
        assert subject["status"] == "CONSENTED"
        assert subject["consented_calendar_id"] == ctx["calendar"]["id"]
        assert subject["consented_calendar_generation"] == 1

        validate_error(
            api_client.create_study_subject(
                create_study_subject_payload(ctx["study"]["id"], subject_number="S-001"),
                make_coordinator_headers(COORDINATOR_ONE),
            ),
            "ERR_DUPLICATE_SUBJECT_NUMBER",
            409,
        )
        _, meta = validate_paginated(
            api_client.list_study_subjects(
                make_manager_headers(MANAGER_ONE),
                params={"study_id": ctx["study"]["id"]},
            )
        )
        assert meta["total_count"] == 1

        validate_error(
            api_client.consent_study_subject(
                subject["id"],
                consent_payload(consent_date="2026-09-02"),
                make_coordinator_headers(COORDINATOR_ONE),
            ),
            "ERR_SUBJECT_NOT_SCREENING",
            409,
        )
        after = validate_success(
            api_client.get_study_subject(
                subject["id"], make_coordinator_headers(COORDINATOR_ONE)
            ),
            200,
        )
        assert after["status"] == "CONSENTED"
        assert after["consent_date"] == subject["consent_date"]
        assert after["version"] == subject["version"]

        # A different number on the same study is free.
        second = validate_success(
            api_client.create_study_subject(
                create_study_subject_payload(ctx["study"]["id"], subject_number="S-002"),
                make_coordinator_headers(COORDINATOR_ONE),
            ),
            201,
        )
        assert second["status"] == "SCREENING"

        # And S-001 is free again on a second protocol: the scope is the study.
        sibling = setup_open_to_accrual(
            [SPONSOR_INFUSION],
            [visit_spec("Cycle 1 Day 1", 1, 0, 0, 3)],
            [route_spec("Cycle 1 Day 1", "J9999")],
            qct_registry_number="NCT10000161",
            study_overrides={"protocol_number": "AMC-2390-C61"},
        )
        elsewhere = validate_success(
            api_client.create_study_subject(
                create_study_subject_payload(
                    sibling["study"]["id"], subject_number="S-001"
                ),
                make_coordinator_headers(COORDINATOR_ONE),
            ),
            201,
        )
        assert elsewhere["subject_number"] == "S-001"
        assert elsewhere["study_id"] == sibling["study"]["id"]
