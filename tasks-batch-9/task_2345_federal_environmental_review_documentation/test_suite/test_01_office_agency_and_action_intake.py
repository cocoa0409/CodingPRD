"""Standing up an office and its agency partners, opening a review, and reading
the append-only administrative record.

Each test builds its own preconditions through the declared endpoints because
the harness restarts the API server, and therefore empties the database, before
every individual test.
"""
from test_helpers import (
    NEPA_COORDINATOR_HEADERS,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    OFFICE_PARAMETER_DEFAULTS,
    POLICY_ADMIN_HEADERS,
    RESOURCE_SPECIALIST_HEADERS,
    REVIEWING_OFFICIAL_HEADERS,
    ApiErrorId,
    agency_payload,
    alternative_payload,
    approx_score,
    assert_instant_equals,
    assert_occurred_at_non_decreasing,
    assert_proposed_action,
    assert_record_entry,
    assert_review_office,
    assert_sequence_contiguous,
    cumulative_action_payload,
    fixtures,
    issue_payload,
    proposed_action_payload,
    review_office_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_STARTUP_INSTANT = "2026-08-01T00:00:00Z"


def _two_classified_actions():
    """One environmental-assessment action and one categorical-exclusion action
    under the same office, each screened CLEARED and classified."""
    ctx = fixtures.setup_classified_action()
    ce_action = fixtures.create_action(ctx["office"]["id"],
                                      **fixtures.CE_ACTION_OVERRIDES)
    ce_screen = fixtures.submit_screen(
        ce_action["id"], findings=fixtures.ALL_ABSENT_SCREEN_FINDINGS
    )
    fixtures.adjudicate_screen(ce_screen["id"], "CLEARED")
    ctx["ce_screen"] = ce_screen
    ctx["ce_action"] = fixtures.classify(ce_action["id"])
    return ctx


class TestOfficeAndAgencyRegistration:
    """Registering the policy container a review runs inside."""

    def test_office_creation_echoes_every_declared_field(self, client):
        """An office created with nothing but a code and a name comes back with
        its policy fields, its common fields and an empty obligation ledger.

        PRD 3.1: "Every policy parameter described in §2.10 may be supplied at
        the same time or left to its default. Creation initialises the office's
        `binding_obligation_cents` to 0."
        PRD 2.4: "Every resource the API creates carries a server-minted `id`,
        formatted as a UUID with no type prefix, and a `created_at` timestamp
        expressed as an ISO 8601 UTC instant with three fractional digits."

        Design: Corner/entities/corner_create_review_office_returns_every_declared_field
        """
        response = client.create_review_office(
            review_office_payload(office_code="ERO-1",
                                  name="Region 1 Environmental Review Office"),
            POLICY_ADMIN_HEADERS,
        )
        office = validate_success(response, expected_status=201)

        assert response.json()["response_type"] == "object", (
            "a single created resource is returned with response_type object"
        )
        assert office["office_code"] == "ERO-1"
        assert office["name"] == "Region 1 Environmental Review Office"
        assert office["binding_obligation_cents"] == 0, (
            "a new office starts with an empty obligation ledger"
        )
        assert office["version"] == 1, "version starts at 1 on creation"
        assert_review_office(office)

        meta = response.json()["meta"]
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with req_, got {meta['api_request_id']}"
        )
        assert meta["api_request_timestamp"], "api_request_timestamp must be present"

    def test_office_creation_applies_every_declared_default(self, client):
        """Omitting the policy parameters leaves every one of them at the value
        the document declares, because the rest of the review reads them.

        PRD 2.10: "Beyond its `office_code` and its human-readable `name`, an
        office carries twenty configurable parameters. Each may be supplied at
        creation; each omitted parameter takes the default below."

        Design: Corner/entities/corner_create_review_office_omitted_fields_apply_declared_defaults
        """
        response = client.create_review_office(
            review_office_payload(office_code="ERO-2",
                                  name="Region 2 Environmental Review Office"),
            POLICY_ADMIN_HEADERS,
        )
        office = validate_success(response, expected_status=201)

        for field, expected in OFFICE_PARAMETER_DEFAULTS.items():
            actual = office.get(field)
            if isinstance(expected, float):
                assert actual == approx_score(expected), (
                    f"omitted {field} should default to {expected}, got {actual}"
                )
            else:
                assert actual == expected, (
                    f"omitted {field} should default to {expected!r}, got {actual!r}"
                )

    def test_agency_creation_rejects_an_undeclared_body_key(self, client):
        """`active_consultation_count` is computed by the server, so supplying it
        is an unknown-field shape violation even though every declared field is
        well formed.

        PRD 2.5: "Request-body shape, on every write endpoint: every required
        field present, no unknown fields, correct types, valid enum members, and
        every numeric range and array constraint stated in this document
        satisfied — `ERR_INVALID_REQUEST`."
        PRD 3.1: "Its `active_consultation_count` is a computed field,
        initialised to 0, that always equals the number of that agency's
        consultation requests whose `status` is `PENDING`."

        Design: Corner/entities/corner_create_agency_with_unknown_body_key_is_rejected
        """
        response = client.create_agency(
            agency_payload(agency_code="USFWS",
                           name="US Fish and Wildlife Service",
                           agency_role="CONSULTING",
                           active_consultation_count=4),
            POLICY_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, expected_status=400)

        _, meta = validate_paginated(client.list_agencies(POLICY_ADMIN_HEADERS))
        assert meta["total_count"] == 0, (
            "a rejected creation must leave no agency row behind"
        )


class TestProposedActionIntake:
    """Opening a review on a proposed federal action."""

    def test_action_without_disturbance_hectares_is_rejected(self, client):
        """`disturbance_hectares` has no default, so omitting it is a shape
        violation and no review is opened.

        PRD 3.2: "A `NepaCoordinator` opens a review by creating a
        `ProposedAction` under a named `office_id`, with a `title`, an estimated
        ground-disturbance footprint in `disturbance_hectares` that must not be
        negative, and a `reference_cost_cents` that must be strictly positive and
        which later serves as the denominator when alternatives are scored for
        cost."
        PRD 2.5: "Request-body shape, on every write endpoint: every required
        field present, no unknown fields, correct types, valid enum members, and
        every numeric range and array constraint stated in this document
        satisfied — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/corner_create_proposed_action_missing_required_field_is_rejected
        """
        office = fixtures.create_office()

        response = client.create_proposed_action(
            proposed_action_payload(office["id"], disturbance_hectares=None),
            NEPA_COORDINATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, expected_status=400)
        assert response.json()["response_type"] == "error"

        _, meta = validate_paginated(
            client.list_proposed_actions(NEPA_COORDINATOR_HEADERS)
        )
        assert meta["total_count"] == 0, (
            "a rejected creation must leave no proposed action behind"
        )

    def test_classified_action_reads_back_with_empty_set_rollups(self, client):
        """A freshly classified action carries its stored inputs untouched and
        every rollup at its empty-set value, with the two entries screening and
        classification appended.

        PRD 3.2: "Every derived field starts at its baseline: `ec_screen_outcome`
        and `record_certified_at` are null, `extraordinary_circumstance_flag` is
        false, `significant_issue_count`, `unaddressed_issue_count`,
        `alternatives_screened_in_count`, `finalized_analysis_count` and
        `record_entry_count` are 0, and `max_unmitigated_score` and
        `cumulative_intensity_index` are 0.00."
        PRD 3.3: "Classification advances the action `SCREENED → CLASSIFIED`,
        appends a `CLASSIFICATION_ASSIGNED` entry, increments
        `record_entry_count`, and increments the action's `version` by one."

        Design: Corner/entities/corner_get_proposed_action_returns_stored_and_derived_fields
        """
        ctx = fixtures.setup_classified_action()

        response = client.get_proposed_action(ctx["action"]["id"],
                                              NEPA_COORDINATOR_HEADERS)
        action = validate_success(response)
        assert_proposed_action(action)

        assert action["id"] == ctx["action"]["id"]
        assert action["disturbance_hectares"] == approx_score(40.0)
        assert action["reference_cost_cents"] == 10000000
        assert action["in_critical_habitat"] is True
        assert action["classification"] == "ENVIRONMENTAL_ASSESSMENT", (
            "40.0 hectares sits below the 100.0 hectare impact-statement "
            "threshold and at or above the 5.0 hectare exclusion threshold"
        )
        assert action["review_stage"] == "CLASSIFIED"
        assert action["ec_screen_outcome"] == "CLEARED"
        assert action["extraordinary_circumstance_flag"] is False
        assert action["significant_issue_count"] == 0
        assert action["unaddressed_issue_count"] == 0
        assert action["alternatives_screened_in_count"] == 0
        assert action["finalized_analysis_count"] == 0
        assert action["max_unmitigated_score"] == approx_score(0.00)
        assert action["cumulative_intensity_index"] == approx_score(0.00)
        assert action["record_entry_count"] == 2, (
            "screening adjudication and classification each append one entry"
        )
        assert action["record_certified_at"] is None

    def test_baseline_entry_with_an_unknown_temporal_scope_is_rejected(self, client):
        """`temporal_scope` is a closed enumeration, so an unrecognised token is
        a 400 shape error rather than a business conflict.

        PRD 3.7: "A `ResourceSpecialist` adds each past, present or reasonably
        foreseeable contributing action to an action's baseline with a
        `resource_area`, a `label` that must be unique within that action and
        resource area, an `intensity_contribution` between 0 and 100 inclusive, a
        `footprint_hectares` that must not be negative, a `distance_km` that must
        not be negative, and a `temporal_scope` of `PAST`, `PRESENT` or
        `REASONABLY_FORESEEABLE`."
        PRD 2.5: "Request-body shape, on every write endpoint: every required
        field present, no unknown fields, correct types, valid enum members, and
        every numeric range and array constraint stated in this document
        satisfied — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/corner_create_cumulative_action_with_invalid_enum_is_rejected
        """
        ctx = fixtures.setup_classified_action()
        action_id = ctx["action"]["id"]

        response = client.create_cumulative_action(
            action_id,
            cumulative_action_payload(label="Legacy grazing allotment",
                                      temporal_scope="HISTORICAL"),
            RESOURCE_SPECIALIST_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, expected_status=400)

        _, meta = validate_paginated(
            client.list_cumulative_actions(action_id, RESOURCE_SPECIALIST_HEADERS)
        )
        assert meta["total_count"] == 0, (
            "the rejected entry must not join the cumulative baseline"
        )


class TestListingsAndIdentifierResolution:
    """Filters, pagination and the two distinct not-found bands."""

    def test_action_listing_counts_the_filtered_set_not_the_table(self, client):
        """A classification filter narrows `total_count` to the matching rows,
        while an office filter over the same two actions reports both.

        PRD 2.3: "Both values are echoed back in the `meta` object of the
        envelope alongside `total_count`, the number of rows matching the request
        before pagination, and `has_more`, a boolean that is true when rows
        remain beyond the current page."
        PRD 2.3: "Proposed actions may be filtered by `office_id`,
        `classification` and `review_stage`."

        Design: Corner/entities/corner_list_proposed_actions_filters_and_paginates
        """
        ctx = _two_classified_actions()

        filtered, filtered_meta = validate_paginated(
            client.list_proposed_actions(
                NEPA_COORDINATOR_HEADERS,
                params={"classification": "ENVIRONMENTAL_ASSESSMENT",
                        "limit": 1, "offset": 0},
            )
        )
        assert len(filtered) == 1, f"expected exactly one row, got {len(filtered)}"
        assert filtered[0]["id"] == ctx["action"]["id"]
        assert filtered_meta["total_count"] == 1, (
            "total_count counts the environmental-assessment action only"
        )
        assert filtered_meta["has_more"] is False

        by_office, office_meta = validate_paginated(
            client.list_proposed_actions(
                NEPA_COORDINATOR_HEADERS,
                params={"office_id": ctx["office"]["id"], "limit": 1, "offset": 0},
            )
        )
        assert len(by_office) == 1, "the page holds one row because limit is 1"
        assert office_meta["total_count"] == 2, (
            "both actions belong to the office named by the filter"
        )
        assert office_meta["has_more"] is True

        ce_action = validate_success(
            client.get_proposed_action(ctx["ce_action"]["id"], NEPA_COORDINATOR_HEADERS)
        )
        assert ce_action["classification"] == "CATEGORICAL_EXCLUSION", (
            "2.0 hectares with no circumstance present and no critical habitat "
            "lands in the categorical-exclusion pathway"
        )

    def test_action_listing_pages_report_total_count_and_has_more(self, client):
        """Paging a two-row set one row at a time keeps `total_count` at two and
        flips `has_more` off on the last page.

        PRD 2.3: "`limit` is the maximum number of rows returned; it defaults to
        10, may not be smaller than 1, and may not be larger than 100. `offset`
        is the number of rows skipped before the page begins; it defaults to 0
        and may not be negative."
        PRD 2.3: "Both values are echoed back in the `meta` object of the
        envelope alongside `total_count`, the number of rows matching the request
        before pagination, and `has_more`, a boolean that is true when rows
        remain beyond the current page."

        Design: Corner/endpoints/corner_list_endpoints_return_total_count_and_has_more
        """
        ctx = _two_classified_actions()
        office_id = ctx["office"]["id"]

        first_response = client.list_proposed_actions(
            NEPA_COORDINATOR_HEADERS,
            params={"office_id": office_id, "limit": 1, "offset": 0},
        )
        first_page, first_meta = validate_paginated(first_response)
        assert first_response.json()["response_type"] == "array"
        assert len(first_page) == 1
        assert first_meta["total_count"] == 2
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 1
        assert first_meta["offset"] == 0

        second_page, second_meta = validate_paginated(
            client.list_proposed_actions(
                NEPA_COORDINATOR_HEADERS,
                params={"office_id": office_id, "limit": 1, "offset": 1},
            )
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 2, (
            "total_count reports the matching set, not the page"
        )
        assert second_meta["has_more"] is False, "no rows remain beyond the last page"

        exclusions, exclusion_meta = validate_paginated(
            client.list_proposed_actions(
                NEPA_COORDINATOR_HEADERS,
                params={"office_id": office_id,
                        "classification": "CATEGORICAL_EXCLUSION"},
            )
        )
        assert len(exclusions) == 1
        assert exclusion_meta["total_count"] == 1
        assert exclusion_meta["has_more"] is False

        first_envelope_meta = first_response.json()["meta"]
        assert first_envelope_meta["api_request_id"], (
            "every response carries an api_request_id"
        )
        assert first_envelope_meta["api_request_timestamp"], (
            "every response carries an api_request_timestamp"
        )

    def test_screen_listing_covers_only_the_action_named_in_the_path(self, client):
        """Two actions each hold one screen; each nested listing returns its own
        action's screen and never the sibling's.

        PRD 2.3: "Both values are echoed back in the `meta` object of the
        envelope alongside `total_count`, the number of rows matching the request
        before pagination, and `has_more`, a boolean that is true when rows
        remain beyond the current page."
        PRD 4, `GET /proposed-actions/{id}/ec-screens`: "List the action's
        extraordinary-circumstances screens".

        Design: Corner/endpoints/corner_ec_screen_listing_is_scoped_to_the_parent_action
        """
        ctx = _two_classified_actions()
        ridgeline_id = ctx["action"]["id"]
        trailhead_id = ctx["ce_action"]["id"]

        ridgeline_rows, ridgeline_meta = validate_paginated(
            client.list_ec_screens(ridgeline_id, NEPA_COORDINATOR_HEADERS)
        )
        assert ridgeline_meta["total_count"] == 1
        assert ridgeline_rows[0]["id"] == ctx["screen"]["id"]
        assert ridgeline_rows[0]["action_id"] == ridgeline_id

        trailhead_rows, trailhead_meta = validate_paginated(
            client.list_ec_screens(trailhead_id, NEPA_COORDINATOR_HEADERS)
        )
        assert trailhead_meta["total_count"] == 1
        assert trailhead_rows[0]["id"] == ctx["ce_screen"]["id"]
        assert trailhead_rows[0]["action_id"] == trailhead_id

        assert ctx["ce_screen"]["id"] not in [row["id"] for row in ridgeline_rows], (
            "the Ridgeline listing must not carry the Trailhead screen"
        )
        assert ctx["screen"]["id"] not in [row["id"] for row in trailhead_rows], (
            "the Trailhead listing must not carry the Ridgeline screen"
        )

    def test_unknown_action_id_in_the_path_is_not_found(self, client):
        """A well-formed identifier that names no row fails at the path-resolution
        band.

        PRD 2.5: "Path-identifier resolution, on every endpoint with a path
        parameter, validated left to right — `ERR_NOT_FOUND`."
        PRD 2.6: "Path identifiers are resolved strictly left to right. A request
        addressed to a nested collection under a proposed action fails on the
        action's `id` before the server looks at anything further right, and the
        failure is always `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/corner_get_proposed_action_unknown_id_returns_not_found
        """
        fixtures.create_office()

        response = client.get_proposed_action(NON_EXISTENT_UUID,
                                              NEPA_COORDINATOR_HEADERS)
        validate_error(response, ApiErrorId.NOT_FOUND.value, expected_status=404)
        assert response.json()["response_type"] == "error"
        assert response.json()["meta"]["api_request_id"], (
            "an error envelope still carries api_request_id"
        )

    def test_alternative_naming_an_unknown_action_is_a_reference_miss(self, client):
        """An unresolvable body identifier is a distinct failure from an
        unresolvable path identifier, even though both answer 404.

        PRD 2.6: "Identifiers carried in a request body are a different matter:
        `office_id`, `action_id`, `agency_id`, `document_id`, `decision_id`,
        `selected_alternative_id`, `source_analysis_id`, `scoping_period_id` and
        `assigned_issue_id` must all resolve to existing rows, and a body
        identifier that does not resolve yields `ERR_REFERENCE_NOT_FOUND` (HTTP
        404)."

        Design: Corner/entities/corner_create_alternative_with_unknown_action_id_returns_reference_not_found
        """
        office = fixtures.create_office()

        response = client.create_alternative(
            alternative_payload(office["id"], label="A - No Action",
                                alternative_kind="NO_ACTION",
                                goal_alignment_codes=None,
                                estimated_cost_cents=0),
            NEPA_COORDINATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.REFERENCE_NOT_FOUND.value,
                       expected_status=404)

        _, meta = validate_paginated(
            client.list_alternatives(NEPA_COORDINATOR_HEADERS)
        )
        assert meta["total_count"] == 0, (
            "an office id passed as an action_id must not be silently accepted"
        )

    def test_unknown_path_id_outranks_an_unknown_body_reference(self, client):
        """When the path action and the body scoping period are both unknown, the
        earlier band answers.

        PRD 2.5: "Path-identifier resolution, on every endpoint with a path
        parameter, validated left to right — `ERR_NOT_FOUND`."
        PRD 2.5: "Foreign-key resolution for identifiers carried in the request
        body — `ERR_REFERENCE_NOT_FOUND`."

        Design: Corner/validations/corner_unknown_path_id_outranks_unknown_body_reference_not_found
        """
        office = fixtures.create_office()

        response = client.create_issue(
            NON_EXISTENT_UUID,
            issue_payload(office["id"], resource_area="WATER", origin="PUBLIC",
                          significance="SIGNIFICANT", summary="Downstream turbidity"),
            NEPA_COORDINATOR_HEADERS,
        )
        error = validate_error(response, ApiErrorId.NOT_FOUND.value,
                               expected_status=404)
        assert error["error_id"] != ApiErrorId.REFERENCE_NOT_FOUND.value, (
            "the unknown path identifier is reported ahead of the unknown body "
            "reference"
        )

        _, meta = validate_paginated(client.list_issues(NEPA_COORDINATOR_HEADERS))
        assert meta["total_count"] == 0, "no issue row is created"

    def test_request_without_identity_headers_is_unauthenticated(self, client):
        """A request carrying neither identity header fails on header presence
        before the endpoint's role list is consulted.

        PRD 2.1: "Every request — read or write — must carry two headers.
        `X-User-ID` identifies the acting principal, and `X-User-Role` declares
        the capacity in which that principal is acting. If either header is
        absent, or if the value of `X-User-Role` is not one of the eight
        recognised role names, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD 2.5: "Header presence and role recognition, on every endpoint —
        `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/corner_unauthenticated_request_is_rejected_before_role_check
        """
        response = client.create_review_office(
            review_office_payload(office_code="ERO-9",
                                  name="Unheaded Request Office"),
            NO_AUTH_HEADERS,
        )
        error = validate_error(response, ApiErrorId.UNAUTHENTICATED.value,
                               expected_status=401)
        assert error["error_id"] != ApiErrorId.ROLE_NOT_PERMITTED.value, (
            "missing headers are reported as unauthenticated, not as a role "
            "authorisation failure"
        )

        _, meta = validate_paginated(client.list_review_offices(POLICY_ADMIN_HEADERS))
        assert meta["total_count"] == 0, "no office row is created"


class TestAdministrativeRecordEntries:
    """The litigation artefact: append-only, versionless and gap-free."""

    def test_record_entries_carry_no_version_or_updated_at(self, client):
        """The record entry is the one resource without `updated_at` and
        `version`, and the two entries of a classified action read in append
        order.

        PRD 2.4: "The administrative record entry is the one exception. Record
        entries are immutable by construction, so an entry carries only `id` and
        `created_at`; it has neither `updated_at` nor `version`."
        PRD 2.4: "Each entry names its `action_id`, carries a `sequence_no` that
        is 1-based, gap-free and unique within that action, an `entry_code`
        naming the recorded event, an `occurred_at` holding the logical-clock
        instant at which the event happened, an `actor_role` naming the role that
        performed it, an `actor_user_id` holding that principal's `X-User-ID`, a
        one-line human-readable `summary`, and a polymorphic pair —
        `related_entity_type` naming which kind of row the entry describes and
        `related_entity_ref` holding that row's identifier."

        Design: Corner/entities/corner_admin_record_entry_is_immutable_and_versionless
        """
        ctx = fixtures.setup_classified_action()

        response = client.list_record_entries(ctx["action"]["id"],
                                              REVIEWING_OFFICIAL_HEADERS)
        entries, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert meta["total_count"] == 2

        assert entries[0]["sequence_no"] == 1
        assert entries[0]["entry_code"] == "EC_SCREEN_ADJUDICATED"
        assert entries[1]["sequence_no"] == 2
        assert entries[1]["entry_code"] == "CLASSIFICATION_ASSIGNED"

        for entry in entries:
            assert_record_entry(entry)
            assert entry["action_id"] == ctx["action"]["id"]
            assert "version" not in entry, (
                f"record entry {entry['sequence_no']} must expose no version"
            )
            assert "updated_at" not in entry, (
                f"record entry {entry['sequence_no']} must expose no updated_at"
            )
            assert entry["actor_role"], "actor_role names the role that acted"
            assert entry["related_entity_type"], "related_entity_type is present"
            assert entry["related_entity_ref"], "related_entity_ref is present"

    def test_record_sequence_numbers_restart_per_action(self, client):
        """Two reviews progress in the same database; each action's entries are
        numbered from one with no gaps, in chronological append order.

        PRD 2.4: "A new entry takes as its `sequence_no` one more than the
        highest `sequence_no` already present among that action's entries, or 1
        if the action has none."
        PRD 2.3: "The administrative record listing is the single exception: its
        rows are returned in `sequence_no` ascending order."

        Design: Corner/calculations/corner_admin_record_sequence_is_contiguous_in_chronological_order
        """
        ctx = _two_classified_actions()
        ridgeline_id = ctx["action"]["id"]
        trailhead_id = ctx["ce_action"]["id"]

        statement = fixtures.draft_purpose_need(ridgeline_id)
        period = fixtures.open_scoping_period(ridgeline_id)
        fixtures.adopt_purpose_need(statement["id"], ridgeline_id)
        fixtures.close_scoping_period(period["id"])

        ridgeline_entries, ridgeline_meta = validate_paginated(
            client.list_record_entries(ridgeline_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert ridgeline_meta["total_count"] == 4
        assert_sequence_contiguous(ridgeline_entries)
        assert [entry["entry_code"] for entry in ridgeline_entries] == [
            "EC_SCREEN_ADJUDICATED",
            "CLASSIFICATION_ASSIGNED",
            "PN_ADOPTED",
            "SCOPING_CLOSED",
        ]
        assert_occurred_at_non_decreasing(ridgeline_entries)

        trailhead_entries, trailhead_meta = validate_paginated(
            client.list_record_entries(trailhead_id, REVIEWING_OFFICIAL_HEADERS)
        )
        assert trailhead_meta["total_count"] == 2, (
            "the interleaved second review carries only its own two entries"
        )
        assert_sequence_contiguous(trailhead_entries)
        assert_occurred_at_non_decreasing(trailhead_entries)

        assert fixtures.read_action(ridgeline_id)["record_entry_count"] == 4
        assert fixtures.read_action(trailhead_id)["record_entry_count"] == 2

    def test_record_instants_follow_the_logical_clock(self, client):
        """Entries written before the clock is ever set carry the startup
        default, and an entry written after an override carries the new instant
        while the earlier entry stays put.

        PRD 2.7: "Before the clock is ever set, it reads exactly
        `2026-08-01T00:00:00Z`; that is the server startup default, and the
        server never falls back to real time. A `PolicyAdmin` may move the clock
        by supplying a `current_utc` instant, and every subsequent evaluation of
        a deadline, window or duration uses the new value."
        PRD 2.4: "Each entry names its `action_id`, carries a `sequence_no` that
        is 1-based, gap-free and unique within that action, an `entry_code`
        naming the recorded event, an `occurred_at` holding the logical-clock
        instant at which the event happened, an `actor_role` naming the role that
        performed it, an `actor_user_id` holding that principal's `X-User-ID`, a
        one-line human-readable `summary`, and a polymorphic pair —
        `related_entity_type` naming which kind of row the entry describes and
        `related_entity_ref` holding that row's identifier."

        Design: Corner/endpoints/corner_clock_startup_default_and_override_drive_recorded_instants
        """
        ctx = fixtures.setup_screened_action(pin_clock=False)
        action_id = ctx["action"]["id"]

        before, _ = validate_paginated(
            client.list_record_entries(action_id, REVIEWING_OFFICIAL_HEADERS)
        )
        adjudication = [entry for entry in before
                        if entry["entry_code"] == "EC_SCREEN_ADJUDICATED"][0]
        assert_instant_equals(adjudication["occurred_at"], CLOCK_STARTUP_INSTANT,
                              "the screening entry's occurred_at")

        clock_response = client.set_clock("2026-08-20T09:30:00Z", POLICY_ADMIN_HEADERS)
        validate_success(clock_response)

        fixtures.classify(action_id)

        after, _ = validate_paginated(
            client.list_record_entries(action_id, REVIEWING_OFFICIAL_HEADERS)
        )
        classification = [entry for entry in after
                          if entry["entry_code"] == "CLASSIFICATION_ASSIGNED"][0]
        assert_instant_equals(classification["occurred_at"], "2026-08-20T09:30:00Z",
                              "the classification entry's occurred_at")

        replayed = [entry for entry in after
                    if entry["entry_code"] == "EC_SCREEN_ADJUDICATED"][0]
        assert_instant_equals(replayed["occurred_at"], CLOCK_STARTUP_INSTANT,
                              "the screening entry's occurred_at after the clock move")
