"""Entity-level breadth: what a create returns, what a read echoes, how a list
pages, which fields the server owns, and how unresolvable ids are answered."""

import pytest

from test_helpers import (
    LEAD,
    REVIEWER,
    TESTER,
    UNKNOWN_UUIDS,
    component_payload,
    create_component,
    create_criterion,
    create_environment,
    create_product,
    create_standard,
    criterion_payload,
    is_valid_uuid,
    log_issue,
    read_product,
    read_run,
    run_payload,
    schedule_run,
    standard_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The bench in the buffer-default scenario is registered without the optional
# buffer field, so the declared default of 30 minutes must apply.
BOOKED_WINDOW = ("2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z")
INSIDE_DEFAULT_BUFFER = ("2026-08-03T12:20:00Z", "2026-08-03T13:20:00Z")

PAGE_SIZE = 2


def build_standard_and_product():
    standard = create_standard(
        code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
    )
    product = create_product(
        standard["id"],
        name="Insight Portal",
        version_label="7.0",
        target_level="AA",
        surface_type="WEB",
    )
    return {"standard": standard, "product": product}


def build_three_open_issues():
    ctx = build_standard_and_product()
    criterion = create_criterion(
        ctx["standard"]["id"],
        criterion_number="1.1.1",
        title="Non-text Content",
        level="A",
        disability_categories=["VISION", "COGNITIVE"],
        applies_to_surfaces=["WEB"],
    )
    component = create_component(
        ctx["product"]["id"],
        name="Web UI",
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=40,
        user_reach_pct=60,
    )
    for severity, effort, summary in (
        ("BLOCKER", 2, "Primary navigation is unreachable by keyboard"),
        ("SERIOUS", 1, "Media library thumbnails expose no accessible name"),
        ("MINOR", 1, "Decorative icons expose redundant alternative text"),
    ):
        log_issue(
            ctx["product"]["id"],
            component["id"],
            criterion["id"],
            severity=severity,
            effort_points=effort,
            target_remediation_date="2026-09-10",
            publish_intent="INCLUDED",
            summary=summary,
        )
    return {**ctx, "criterion": criterion, "component": component}


class TestConfigurationCreatesAndReads:
    """A create echoes what was declared; a read echoes what was stored."""

    def test_registering_a_standard_returns_its_declared_configuration(self, api):
        """PRD §3.1: "An `AccessibilityLead` registers each accessibility standard
        the company works against by supplying its `code`, a human-readable
        `title` of 1 to 200 characters, the `surface_scope` describing which
        product surfaces the standard governs, and the `max_target_level` naming
        the highest conformance level the standard itself defines."
        PRD §3.1: "A freshly registered standard reports a `criteria_count` of 0;
        that counter is derived, and it always equals the number of success
        criteria whose owning standard is this one."

        Design: Corner/entities/corner_standard_creation_returns_declared_fields
        """
        created = validate_success(
            api.create_standard(
                standard_payload(
                    code="WCAG_2_2",
                    title="WCAG 2.2",
                    surface_scope="WEB",
                    max_target_level="AAA",
                ),
                LEAD,
            ),
            201,
        )

        assert created["code"] == "WCAG_2_2"
        assert created["surface_scope"] == "WEB"
        assert created["max_target_level"] == "AAA", (
            f"the declared highest level is stored as given, got {created['max_target_level']}"
        )
        assert created["title"] == "WCAG 2.2"
        assert created["criteria_count"] == 0, (
            f"no criterion has been attached yet, got {created['criteria_count']}"
        )

    def test_reading_a_criterion_echoes_the_row_that_was_posted(self, api):
        """PRD §3.1: "Each carries a `criterion_number` written as dotted decimal
        groups — two or three groups of digits separated by single dots, as in
        "1.4.3" or "2.1" — a `title` of 1 to 200 characters, the `level` at which
        the criterion applies, a non-empty and duplicate-free list of
        `disability_categories` the criterion protects, and a non-empty and
        duplicate-free list of `applies_to_surfaces` drawn from `WEB` and
        `SOFTWARE`."
        PRD §3.1: "The owning standard is recorded on the criterion as its
        `standard_id` and can never be changed."

        Design: Corner/entities/corner_get_criterion_returns_stored_row
        """
        standard = create_standard(
            code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
        )
        criterion = create_criterion(
            standard["id"],
            criterion_number="1.1.1",
            title="Non-text Content",
            level="A",
            disability_categories=["VISION", "COGNITIVE"],
            applies_to_surfaces=["WEB"],
        )

        read = validate_success(api.get_criterion(criterion["id"], TESTER))

        assert read["criterion_number"] == "1.1.1"
        assert sorted(read["disability_categories"]) == ["COGNITIVE", "VISION"], (
            "both protected categories are echoed, got "
            f"{read['disability_categories']}"
        )
        assert read["level"] == "A"
        assert read["standard_id"] == standard["id"], (
            f"the owning standard is recorded on the row, got {read['standard_id']}"
        )

    def test_a_created_standard_carries_server_minted_identity(self, api):
        """PRD §2.4: "Every resource carries a server-minted `id` that is a UUID
        string with no type prefix; clients never supply an `id`."
        PRD §2.4: "Most resources additionally carry `updated_at`, formatted
        identically to `created_at` and refreshed on every mutation of the row,
        and `version`, an integer that starts at 1 when the row is created and
        increases by exactly 1 on every mutation of that row."
        PRD §2.4: "The clock begins at `2026-08-01T00:00:00Z` and an
        `AccessibilityLead` may move it to any instant supplied as `to_iso8601`."

        Design: Corner/entities/corner_system_fields_generated_on_create
        """
        created = validate_success(
            api.create_standard(
                standard_payload(
                    code="WCAG_2_2",
                    title="WCAG 2.2",
                    surface_scope="WEB",
                    max_target_level="AAA",
                ),
                LEAD,
            ),
            201,
        )

        assert is_valid_uuid(created["id"]), (
            f"the identifier is a server-minted UUID with no type prefix, got {created['id']}"
        )
        assert created["version"] == 1, (
            f"a freshly created row is at version 1, got {created['version']}"
        )
        assert created["created_at"].startswith("2026-08-01T00:00:00"), (
            "the row is stamped from the logical clock's starting instant, got "
            f"{created['created_at']}"
        )
        assert created["updated_at"] == created["created_at"], (
            "nothing has mutated the row since insertion, got "
            f"{created['updated_at']} against {created['created_at']}"
        )

    def test_a_success_criterion_exposes_no_version_or_update_bookkeeping(self, api):
        """PRD §2.4: "There is one deliberate exception: a success criterion is
        immutable configuration."
        PRD §2.4: "Success criteria carry only `id` and `created_at` — they have
        no `updated_at` and no `version` field at all, and there is no endpoint
        that modifies one."

        Design: Corner/entities/corner_success_criterion_is_immutable
        """
        standard = create_standard(
            code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
        )
        criterion = create_criterion(
            standard["id"],
            criterion_number="1.4.3",
            title="Contrast Minimum",
            level="AA",
            disability_categories=["VISION"],
            applies_to_surfaces=["WEB"],
        )

        read = validate_success(api.get_criterion(criterion["id"], REVIEWER))

        assert read["level"] == "AA"
        assert "version" not in read, (
            f"an immutable row carries no version field, got keys {sorted(read)}"
        )
        assert "updated_at" not in read, (
            f"an immutable row carries no updated_at field, got keys {sorted(read)}"
        )
        assert read["created_at"] is not None


class TestListingAndPagination:
    """Three issues walked two at a time, with the total reported both times."""

    def test_listing_known_issues_pages_and_reports_the_total(self, api):
        """PRD §2.3: "Every list endpoint accepts two optional query parameters.
        `limit` defaults to 10, has a minimum of 1 and a maximum of 100; `offset`
        defaults to 0 and has a minimum of 0."
        PRD §2.3: "The `meta` object of a list response carries `limit` and
        `offset` as applied, `total_count` as the total number of rows matching
        the filter before pagination, and `has_more`, which is true exactly when
        `offset` plus the number of returned rows is less than `total_count`."
        PRD §2.3: "Filters offered by a list endpoint are combined
        conjunctively, and a filter value that is not a member of the field's
        enumeration is a request-shape failure."

        Design: Corner/entities/corner_known_issue_list_paginates_with_total_count
        """
        ctx = build_three_open_issues()

        first_rows, first_meta = validate_paginated(
            api.list_known_issues(
                LEAD, {"product_id": ctx["product"]["id"], "limit": PAGE_SIZE, "offset": 0}
            )
        )

        assert len(first_rows) == PAGE_SIZE, (
            f"a limit of 2 returns two rows, got {len(first_rows)}"
        )
        assert first_meta["total_count"] == 3, (
            f"all three issues match the filter before pagination, got {first_meta['total_count']}"
        )
        assert first_meta["has_more"] is True, (
            "0 plus 2 is less than 3, so more rows remain, got "
            f"{first_meta['has_more']}"
        )

        second_rows, second_meta = validate_paginated(
            api.list_known_issues(
                LEAD, {"product_id": ctx["product"]["id"], "limit": PAGE_SIZE, "offset": 2}
            )
        )

        assert len(second_rows) == 1, f"one row is left on the second page, got {len(second_rows)}"
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False, (
            "2 plus 1 equals the total, so nothing remains, got "
            f"{second_meta['has_more']}"
        )
        for row in first_rows + second_rows:
            assert row["product_id"] == ctx["product"]["id"]
            assert row["state"] == "OPEN", (
                f"no issue has been triaged, got {row['state']}"
            )


class TestServerOwnedFieldsAndDefaults:
    """Fields the client never supplies: computed counters and declared defaults."""

    def test_a_new_components_computed_fields_are_initialised_by_the_server(self, api):
        """PRD §3.2: "A new component starts with `assessment_state` at `PLANNED`,
        `design_review_state` at `NOT_REVIEWED`, `coverage_pct` at 0.00,
        `evidence_units_total` at 0, an empty `validated_disability_categories`
        list and no `design_review_note`."
        PRD §2.9: "Counters, coverage percentages, indices, postures, funding
        states and readiness flags are never supplied by clients and never
        accepted in a request body; they are recomputed by the server from their
        inputs whenever an operation changes one of those inputs."
        PRD §3.1: "The two component counters have precise definitions that
        matter downstream: `components_in_scope_count` is the number of the
        product's components whose in-scope flag is true, and
        `components_complete_count` is the number of those in-scope components
        whose assessment dimension has reached `COMPLETE`."

        Design: Corner/entities/corner_component_computed_fields_initialise_from_system
        """
        ctx = build_standard_and_product()

        created = validate_success(
            api.create_component(
                ctx["product"]["id"],
                component_payload(
                    name="Web UI",
                    component_type="WEB_UI",
                    in_scope=True,
                    assessment_scope="FULL",
                    applicable_criteria_count=40,
                    user_reach_pct=60,
                ),
                LEAD,
            ),
            201,
        )

        assert created["coverage_pct"] == pytest.approx(0.00, abs=0.01), (
            f"no run has been booked, so coverage is 0.00, got {created['coverage_pct']}"
        )
        assert created["evidence_units_total"] == 0
        assert created["validated_disability_categories"] == [], (
            "no manual run has validated anything, got "
            f"{created['validated_disability_categories']}"
        )
        assert created["assessment_state"] == "PLANNED"
        assert created["design_review_state"] == "NOT_REVIEWED"
        assert read_product(ctx["product"]["id"])["components_in_scope_count"] == 1, (
            "the in-scope component is counted on the product immediately"
        )

    def test_a_bench_registered_without_a_buffer_uses_the_declared_default(self, api):
        """PRD §3.3: "When the buffer is omitted it defaults to half an hour, that
        is 30 minutes."
        PRD §3.3: "And the bench must be free: the new run's half-open window,
        from its `scheduled_start` up to but not including its `scheduled_end`,
        must not intersect the occupation window of any other run on the same
        bench whose `status` is `SCHEDULED` or `COMPLETED`, where each existing
        run's occupation window runs from its own `scheduled_start` up to but not
        including its `scheduled_end` extended forward by that bench's
        `reconfiguration_buffer_minutes`."
        PRD §3.3: "Any intersection is `ERR_ENVIRONMENT_WINDOW_CONFLICT`."

        Design: Corner/entities/corner_environment_buffer_default_applied_when_omitted
        """
        ctx = build_standard_and_product()
        component = create_component(
            ctx["product"]["id"],
            name="Web UI",
            component_type="WEB_UI",
            in_scope=True,
            assessment_scope="FULL",
            applicable_criteria_count=40,
            user_reach_pct=60,
        )
        bench = create_environment(name="NVDA Bench 1", at_profile="SCREEN_READER")

        assert bench["reconfiguration_buffer_minutes"] == 30, (
            "the omitted buffer defaults to half an hour, got "
            f"{bench['reconfiguration_buffer_minutes']}"
        )

        booked = schedule_run(
            component["id"],
            bench["id"],
            method="MANUAL",
            at_profile="SCREEN_READER",
            scheduled_start=BOOKED_WINDOW[0],
            scheduled_end=BOOKED_WINDOW[1],
            criteria_exercised=40,
            disability_categories_validated=["VISION", "COGNITIVE"],
        )

        validate_error(
            api.create_run(
                run_payload(
                    component["id"],
                    bench["id"],
                    method="AUTOMATED",
                    at_profile="SCREEN_READER",
                    scheduled_start=INSIDE_DEFAULT_BUFFER[0],
                    scheduled_end=INSIDE_DEFAULT_BUFFER[1],
                    criteria_exercised=10,
                    disability_categories_validated=["VISION"],
                ),
                TESTER,
            ),
            "ERR_ENVIRONMENT_WINDOW_CONFLICT",
            409,
        )

        assert read_run(booked["id"])["status"] == "SCHEDULED", (
            "the incumbent booking is untouched by the refusal"
        )


class TestUnresolvableReferencesAndRequestShape:
    """Path existence answers before body shape, and neither writes anything."""

    def test_reading_an_unknown_product_is_a_not_found(self, api):
        """PRD §2.6: "A product identifier that does not resolve yields
        `ERR_PRODUCT_NOT_FOUND`; a standard yields `ERR_STANDARD_NOT_FOUND`; a
        component `ERR_COMPONENT_NOT_FOUND`; a test environment
        `ERR_ENVIRONMENT_NOT_FOUND`; an assessment run `ERR_RUN_NOT_FOUND`; a
        criterion assessment `ERR_ASSESSMENT_NOT_FOUND`; a conformance report
        `ERR_REPORT_NOT_FOUND`; a release train `ERR_RELEASE_TRAIN_NOT_FOUND`; a
        known issue `ERR_KNOWN_ISSUE_NOT_FOUND`; a questionnaire response
        `ERR_QUESTIONNAIRE_NOT_FOUND`; and a complaint
        `ERR_COMPLAINT_NOT_FOUND`."
        PRD §2.6: "All of these carry HTTP 404."

        Design: Corner/entities/corner_get_product_with_unknown_id_not_found
        """
        validate_error(
            api.get_product(UNKNOWN_UUIDS["product"], LEAD),
            "ERR_PRODUCT_NOT_FOUND",
            404,
        )

    def test_adding_a_component_under_an_unknown_product_is_a_not_found(self, api):
        """PRD §2.6: "Endpoints with path parameters validate their path segments
        from left to right, and the first unresolvable segment determines the
        error."
        PRD §2.7: "4. Path-segment existence, left to right — the 404 codes of
        §2.6."
        PRD §2.7: "Checks are evaluated strictly in the following order, and the
        first failing check produces the response; later checks are never reached
        and never mask an earlier one."

        Design: Corner/entities/corner_component_under_unknown_product_not_found
        """
        ctx = build_standard_and_product()

        validate_error(
            api.create_component(
                UNKNOWN_UUIDS["product"],
                component_payload(
                    name="Web UI",
                    component_type="WEB_UI",
                    in_scope=True,
                    assessment_scope="FULL",
                    applicable_criteria_count=40,
                    user_reach_pct=60,
                ),
                LEAD,
            ),
            "ERR_PRODUCT_NOT_FOUND",
            404,
        )

        assert read_product(ctx["product"]["id"])["components_in_scope_count"] == 0, (
            "the real product gained nothing from a request aimed at a phantom parent"
        )

    def test_creating_a_component_without_its_criteria_count_is_rejected(self, api):
        """PRD §2.7: "6. Request-body shape: required fields present, types
        correct, enum members valid, numeric ranges respected, `limit` within 1
        through 100, `offset` at least 0, arrays non-empty and free of
        duplicates, a run's `scheduled_end` strictly after its `scheduled_start`,
        and a train's `window_end` on or after its `window_start` —
        `ERR_INVALID_REQUEST` (400)."
        PRD §3.2: "Adding a component requires its `name` (1 to 160 characters,
        unique among that product's components — a repeat is
        `ERR_DUPLICATE_COMPONENT_NAME`), its `component_type`, the boolean
        `in_scope` flag stating whether the component sits inside the report's
        assessment scope, the declared `assessment_scope` depth, the
        `applicable_criteria_count` between 1 and 500 that the tester declares to
        be in this component's scope, and the `user_reach_pct` between 0 and 100
        describing what share of the product's users touch the component."
        PRD §3.2: "Its creation immediately rebuilds the owning product's
        `components_in_scope_count`, `assessment_readiness`,
        `conformance_index_provisional` and `publication_posture`, and raises the
        product's `version` by 1."

        Design: Corner/entities/corner_component_create_missing_required_field_rejected
        """
        ctx = build_standard_and_product()
        payload = component_payload(
            name="Web UI",
            component_type="WEB_UI",
            in_scope=True,
            assessment_scope="FULL",
            user_reach_pct=60,
        )
        payload.pop("applicable_criteria_count")

        validate_error(
            api.create_component(ctx["product"]["id"], payload, LEAD),
            "ERR_INVALID_REQUEST",
            400,
        )

        product = read_product(ctx["product"]["id"])
        assert product["components_in_scope_count"] == 0, (
            "the rejected create inserted no row, got "
            f"{product['components_in_scope_count']}"
        )
        assert product["version"] == 1, (
            f"the rejected create bumped no version, got {product['version']}"
        )

    def test_a_criterion_level_outside_the_enumeration_is_rejected(self, api):
        """PRD §2.10: "Conformance levels — a standard's `max_target_level`, a
        criterion's `level` and a product's `target_level` — are `A`, `AA` or
        `AAA`."
        PRD §2.7: "6. Request-body shape: required fields present, types correct,
        enum members valid, numeric ranges respected, `limit` within 1 through
        100, `offset` at least 0, arrays non-empty and free of duplicates, a run's
        `scheduled_end` strictly after its `scheduled_start`, and a train's
        `window_end` on or after its `window_start` — `ERR_INVALID_REQUEST`
        (400)."
        PRD §3.1: "A `criterion_number` that already exists on that same standard
        is rejected with `ERR_DUPLICATE_CRITERION_NUMBER`, and a criterion whose
        `level` is stricter than the standard's `max_target_level` — for instance
        `AAA` on a standard that stops at `AA` — is rejected with
        `ERR_LEVEL_OR_SURFACE_UNSUPPORTED`."

        Design: Corner/entities/corner_criterion_level_invalid_enum_rejected
        """
        standard = create_standard(
            code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
        )

        validate_error(
            api.create_criterion(
                standard["id"],
                criterion_payload(
                    criterion_number="1.1.1",
                    title="Non-text Content",
                    level="AAAA",
                    disability_categories=["VISION"],
                    applies_to_surfaces=["WEB"],
                ),
                LEAD,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        rows, meta = validate_paginated(api.list_criteria(standard["id"], LEAD))
        assert meta["total_count"] == 0, (
            f"the rejected create attached no criterion, got {meta['total_count']}"
        )
        assert rows == []
