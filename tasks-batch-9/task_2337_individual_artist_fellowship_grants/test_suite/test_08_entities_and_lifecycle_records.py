"""
Entity creation, declared defaults, derived counters, frozen snapshots, listing
metadata and the not-found mapping across the flat topology.
"""

import pytest

from conftest import UNKNOWN_ID

from test_helpers import (
    PROGRAM_OFFICER,
    PROGRAM_OFFICER_ID,
    api_client,
    application_payload,
    assert_cents,
    assert_common_fields,
    cornermain_application_draft,
    cornermain_application_submitted,
    cornermain_cycle_open,
    cycle_payload,
    cycle_payload_required_only,
    discipline_payload,
    read_application,
    read_artist,
    read_discipline,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    work_sample_payload,
)


class TestCycleCreation:
    """A new cycle arrives with its fiscal ledger already derived."""

    def test_a_new_cycle_is_born_with_its_ledger_already_computed(self):
        """
        The 201 body of a 6,000,000-cent cycle already carries a DRAFT status, an OPEN
        posture, a 300,000-cent contingency reserve, a zero commitment and 5,700,000 cents
        available, rather than leaving those figures for the first award to fill in.

        PRD: "`reserve_cents` is a contingency reserve withheld only while the cycle is still
        deciding: it equals five percent of `total_budget_cents`, rounded half up to a whole
        cent, while the cycle's `status` is `DRAFT`, `OPEN`, `CLOSED`, `PANEL_REVIEW` or
        `BOARD_REVIEW`, and it becomes 0 once the status reaches `AWARDED`, `CLOSED_OUT` or
        `CANCELLED`."

        Design: Corner/entities/cycle_creation_seeds_status_reserve_available_and_posture
        """
        set_clock("2026-09-01T00:00:00Z")
        response = api_client.create_cycle(cycle_payload(), PROGRAM_OFFICER)
        cycle = validate_success(response, expected_status=201)

        assert response.json()["response_type"] == "object", (
            "a single-entity create returns an object envelope"
        )
        assert_common_fields(cycle, "cycle")
        assert cycle["version"] == 1, f"a new row starts at version 1, got {cycle['version']}"
        assert cycle["created_at"] == cycle["updated_at"], (
            "an unmutated row has matching timestamps"
        )
        assert cycle["status"] == "DRAFT", f"a cycle is born DRAFT, got {cycle['status']}"
        assert cycle["posture"] == "OPEN", f"a new cycle is OPEN, got {cycle['posture']}"
        assert_cents(cycle["funded_total_cents"], 0, "cycle.funded_total_cents")
        assert cycle["admin_assessment_rate"] == pytest.approx(0.0, abs=1e-9), (
            f"no funding means no assessment rate, got {cycle['admin_assessment_rate']}"
        )
        assert_cents(cycle["admin_assessment_cents"], 0, "cycle.admin_assessment_cents")
        assert_cents(cycle["reserve_cents"], 300_000, "cycle.reserve_cents")
        assert_cents(cycle["committed_cents"], 0, "cycle.committed_cents")
        assert_cents(cycle["available_cents"], 5_700_000, "cycle.available_cents")
        assert cycle["unresolved_breach_count"] == 0, (
            f"no breach on a new cycle, got {cycle['unresolved_breach_count']}"
        )
        assert cycle["blocking_conflict_count"] == 0, (
            f"no conflict on a new cycle, got {cycle['blocking_conflict_count']}"
        )

    def test_omitted_policy_knobs_come_back_as_their_declared_defaults(self):
        """
        A creation body that omits all five optional policy settings reads back as PRORATE,
        two rounds, a fourteen-day acceptance window, a thirty-day appeal window and a
        sixty-day report offset, with the ledger of a 4,000,000-cent appropriation undisturbed.

        PRD: "`proration_policy` defaults to `PRORATE` and may instead be `SKIP_TO_ALTERNATE`;
        it decides what happens when a discipline remainder falls short of a full stipend.
        `max_review_rounds` defaults to 2 and is the hard ceiling on how many scoring rounds a
        panel may open. `acceptance_window_days` defaults to 14 and is how long an offered
        award stays acceptable. `appeal_window_days` defaults to 30 and is how long after
        notification an appeal may be filed. `final_report_due_offset_days` defaults to 60 and
        is how long after the grant period ends the final narrative report is due."

        Design: Corner/entities/omitted_optional_cycle_policy_fields_fall_back_to_declared_defaults
        """
        set_clock("2026-09-01T00:00:00Z")
        cycle = validate_success(
            api_client.create_cycle(
                cycle_payload_required_only(
                    name="FY2028 Fellowships (defaults probe)",
                    fiscal_year=2028,
                    application_open_at="2027-08-15T00:00:00Z",
                    application_deadline_at="2027-10-15T23:59:59Z",
                    grant_period_start="2028-01-01T00:00:00Z",
                    grant_period_end="2028-12-31T00:00:00Z",
                    total_budget_cents=4_000_000,
                    base_award_cents=1_000_000,
                    min_prorated_award_cents=400_000,
                ),
                PROGRAM_OFFICER,
            ),
            expected_status=201,
        )

        assert cycle["proration_policy"] == "PRORATE", (
            f"proration_policy defaults to PRORATE, got {cycle['proration_policy']}"
        )
        assert cycle["max_review_rounds"] == 2, (
            f"max_review_rounds defaults to 2, got {cycle['max_review_rounds']}"
        )
        assert cycle["acceptance_window_days"] == 14, (
            f"acceptance_window_days defaults to 14, got {cycle['acceptance_window_days']}"
        )
        assert cycle["appeal_window_days"] == 30, (
            f"appeal_window_days defaults to 30, got {cycle['appeal_window_days']}"
        )
        assert cycle["final_report_due_offset_days"] == 60, (
            "final_report_due_offset_days defaults to 60, got "
            f"{cycle['final_report_due_offset_days']}"
        )
        assert_cents(cycle["reserve_cents"], 200_000, "cycle.reserve_cents")
        assert_cents(cycle["available_cents"], 3_800_000, "cycle.available_cents")


class TestSubmittedApplicationSnapshot:
    """Submission freezes a snapshot the read must echo unchanged."""

    def test_a_submitted_application_read_echoes_the_frozen_snapshot(self):
        """
        The read of an application submitted on 1 September 2026 shows the alias minted from
        the discipline counter, a residency measured at the 15 October deadline rather than at
        the submit instant, a null blackout gap for a first-time applicant, and the
        denormalized name and region.

        PRD: "`residency_months_at_deadline` is frozen. `blackout_gap_years` is frozen as the
        cycle's `fiscal_year` less the artist's `last_award_fiscal_year`, or as `null` when the
        artist has no recorded prior award."

        Design: Corner/entities/submitted_application_read_returns_the_frozen_applicant_snapshot
        """
        ctx = cornermain_application_submitted()

        application = read_application(ctx.app)
        assert application["status"] == "SUBMITTED", (
            f"the application should be SUBMITTED, got {application['status']}"
        )
        assert application["anonymity_status"] == "SEALED", (
            f"anonymity stays SEALED at submit, got {application['anonymity_status']}"
        )
        assert application["sealed_alias"] == "LIT-2027-0001", (
            f"the first LIT submission of 2027, got {application['sealed_alias']}"
        )
        assert str(application["submitted_at"]).startswith("2026-09-01"), (
            f"submitted_at comes from the logical clock, got {application['submitted_at']}"
        )
        assert application["residency_months_at_deadline"] == 45, (
            "residency is measured at the 2026-10-15 deadline, not at submit, got "
            f"{application['residency_months_at_deadline']}"
        )
        assert application["blackout_gap_years"] is None, (
            "a first-time applicant has no blackout gap, got "
            f"{application['blackout_gap_years']}"
        )
        assert application["applicant_legal_name"] == "Cleo Amari", (
            f"the name is denormalized at submit, got {application['applicant_legal_name']}"
        )
        assert application["applicant_region"] == "NORTH", (
            f"the region is denormalized at submit, got {application['applicant_region']}"
        )
        assert application["work_sample_count"] == 2, (
            f"two samples are attached, got {application['work_sample_count']}"
        )
        assert application["valid_review_count"] == 0, "no review exists yet"
        assert application["assigned_panel_id"] is None, "no panel has claimed it yet"

        discipline = read_discipline(ctx.disc)
        assert discipline["submitted_sequence_counter"] == 1, (
            "one submission has been counted, got "
            f"{discipline['submitted_sequence_counter']}"
        )
        assert discipline["eligible_application_count"] == 0, (
            "submission does not touch the eligible count, got "
            f"{discipline['eligible_application_count']}"
        )

    def test_editing_the_artist_never_rewrites_the_frozen_application_snapshot(self):
        """
        Renaming the artist, moving them to another region and rewriting their residency start
        bumps only the artist row; the submitted application still reports the name, region
        and residency duration captured at submit.

        PRD: "A `ProgramOfficer` may later update any of those seven fields — a taxpayer
        identification number that arrives after registration is the common case — but such an
        update never reaches backwards: an application's `residency_months_at_deadline`,
        `applicant_legal_name` and `applicant_region`, once frozen at submission, are immune to
        a subsequent profile edit."

        Design: Corner/entities/artist_patch_does_not_rewrite_the_already_frozen_snapshot
        """
        ctx = cornermain_application_submitted()
        before = read_application(ctx.app)

        patched = validate_success(
            api_client.patch_artist(
                ctx.art,
                {
                    "legal_name": "Cleo Amari-Vance",
                    "region": "SOUTH",
                    "residency_start_date": "2024-12-01",
                },
                PROGRAM_OFFICER,
            )
        )
        assert patched["legal_name"] == "Cleo Amari-Vance", (
            f"the patch should land on the artist, got {patched['legal_name']}"
        )
        assert patched["region"] == "SOUTH", f"region should change, got {patched['region']}"
        assert patched["version"] == 2, (
            f"one mutation moves the artist to version 2, got {patched['version']}"
        )
        assert patched["updated_at"] > patched["created_at"], (
            "a mutation refreshes updated_at"
        )

        after = read_application(ctx.app)
        assert after["applicant_legal_name"] == "Cleo Amari", (
            f"the frozen name must not follow the artist, got {after['applicant_legal_name']}"
        )
        assert after["applicant_region"] == "NORTH", (
            f"the frozen region must not follow the artist, got {after['applicant_region']}"
        )
        assert after["residency_months_at_deadline"] == 45, (
            "the frozen residency must not be recomputed, got "
            f"{after['residency_months_at_deadline']}"
        )
        assert after["version"] == before["version"], (
            "the application is not mutated by an artist edit, got version "
            f"{after['version']} against {before['version']}"
        )
        assert read_artist(ctx.art)["tin_status"] == "ON_FILE", (
            "an absent patch key must not be treated as null"
        )


class TestApplicationListing:
    """total_count counts the filtered rows, not the page."""

    def test_the_application_list_counts_before_it_paginates(self):
        """
        With three applications in the cycle, a two-row page reports a total of three and
        more to come, the second page reports one row and no more, and a status filter
        narrows the total itself.

        PRD: "Every list response carries `limit`, `offset`, `total_count` and `has_more`
        inside the envelope's `meta` object, where `total_count` counts the rows matching the
        filters before pagination is applied."

        Design: Corner/entities/application_list_reports_total_count_and_has_more_across_two_pages
        """
        ctx = cornermain_application_submitted()
        for name, email, region, county in (
            ("Hana Ito", "hana.ito@example.org", "CENTRAL", "Harbor"),
            ("Ivo Serra", "ivo.serra@example.org", "SOUTH", "Ridge"),
        ):
            artist = validate_success(
                api_client.create_artist(
                    {
                        "legal_name": name,
                        "email": email,
                        "residency_start_date": "2022-05-04",
                        "residency_county": county,
                        "region": region,
                    },
                    PROGRAM_OFFICER,
                ),
                expected_status=201,
            )
            validate_success(
                api_client.create_application(
                    application_payload(ctx.cyc, ctx.disc, artist["id"]),
                    PROGRAM_OFFICER,
                ),
                expected_status=201,
            )

        first, first_meta = validate_paginated(
            api_client.list_applications(
                PROGRAM_OFFICER, {"cycle_id": ctx.cyc, "limit": 2, "offset": 0}
            )
        )
        assert len(first) == 2, f"the page holds two rows, got {len(first)}"
        assert first_meta["total_count"] == 3, (
            f"the total counts every matching row, got {first_meta['total_count']}"
        )
        assert first_meta["has_more"] is True, "a third row remains"
        assert first_meta["limit"] == 2, f"limit echo, got {first_meta['limit']}"
        assert first_meta["offset"] == 0, f"offset echo, got {first_meta['offset']}"

        second, second_meta = validate_paginated(
            api_client.list_applications(
                PROGRAM_OFFICER, {"cycle_id": ctx.cyc, "limit": 2, "offset": 2}
            )
        )
        assert len(second) == 1, f"one row is left, got {len(second)}"
        assert second_meta["total_count"] == 3, (
            f"the total is unchanged by the offset, got {second_meta['total_count']}"
        )
        assert second_meta["has_more"] is False, "nothing follows the last row"
        assert second_meta["offset"] == 2, f"offset echo, got {second_meta['offset']}"
        assert {row["id"] for row in first}.isdisjoint({row["id"] for row in second}), (
            "no application may appear on both pages"
        )

        drafts, draft_meta = validate_paginated(
            api_client.list_applications(
                PROGRAM_OFFICER, {"cycle_id": ctx.cyc, "status": "DRAFT"}
            )
        )
        assert len(drafts) == 2, f"two drafts remain, got {len(drafts)}"
        assert draft_meta["total_count"] == 2, (
            "the filter applies before the count, got "
            f"{draft_meta['total_count']}"
        )


class TestNotFoundMapping:
    """Each route owns its own 404 code."""

    @pytest.mark.parametrize(
        "path,error_id",
        [
            ("cycles", "ERR_CYCLE_NOT_FOUND"),
            ("discipline-categories", "ERR_DISCIPLINE_CATEGORY_NOT_FOUND"),
            ("artists", "ERR_ARTIST_NOT_FOUND"),
            ("applications", "ERR_APPLICATION_NOT_FOUND"),
            ("work-samples", "ERR_WORK_SAMPLE_NOT_FOUND"),
            ("panels", "ERR_PANEL_NOT_FOUND"),
            ("panelists", "ERR_PANELIST_NOT_FOUND"),
            ("conflicts", "ERR_CONFLICT_NOT_FOUND"),
            ("reviews", "ERR_REVIEW_NOT_FOUND"),
            ("recommendation-slots", "ERR_SLOT_NOT_FOUND"),
            ("awards", "ERR_AWARD_NOT_FOUND"),
            ("payment-installments", "ERR_INSTALLMENT_NOT_FOUND"),
            ("final-reports", "ERR_FINAL_REPORT_NOT_FOUND"),
            ("appeals", "ERR_APPEAL_NOT_FOUND"),
        ],
    )
    def test_each_entity_route_reports_its_own_not_found_code(self, path, error_id):
        """
        The same syntactically valid identifier read against each of the fourteen entity
        routes of an empty database returns that entity's own 404 code, so only the route
        decides the answer.

        PRD: "Each entity has its own 404 code, and the mapping is fixed: `cycle_id` yields
        `ERR_CYCLE_NOT_FOUND`, `discipline_category_id` yields
        `ERR_DISCIPLINE_CATEGORY_NOT_FOUND`, `artist_id` yields `ERR_ARTIST_NOT_FOUND`,
        `application_id` yields `ERR_APPLICATION_NOT_FOUND`, `work_sample_id` yields
        `ERR_WORK_SAMPLE_NOT_FOUND`, `panel_id` yields `ERR_PANEL_NOT_FOUND`, `panelist_id`
        yields `ERR_PANELIST_NOT_FOUND`, `conflict_declaration_id` yields
        `ERR_CONFLICT_NOT_FOUND`, `review_id` yields `ERR_REVIEW_NOT_FOUND`,
        `recommendation_slot_id` yields `ERR_SLOT_NOT_FOUND`, `award_id` yields
        `ERR_AWARD_NOT_FOUND`, `payment_installment_id` yields `ERR_INSTALLMENT_NOT_FOUND`,
        `final_report_id` yields `ERR_FINAL_REPORT_NOT_FOUND`, and `appeal_id` yields
        `ERR_APPEAL_NOT_FOUND`."

        Design: Corner/entities/unknown_path_ids_return_the_entity_specific_not_found_error
        """
        response = api_client.get(f"/grants/{path}/{UNKNOWN_ID}", headers=PROGRAM_OFFICER)
        validate_error(response, error_id, expected_status=404)
        body = response.json()
        assert body["response_type"] == "error", (
            f"a failure carries an error envelope, got {body['response_type']}"
        )
        assert isinstance(body["meta"].get("api_request_id"), str), (
            "a failing response still carries meta.api_request_id"
        )


class TestWriteShapeConstraints:
    """Shape is judged before anything is looked up."""

    def test_a_missing_prose_component_is_a_shape_error_before_any_lookup(self):
        """
        An application body without its artist statement is refused as a shape error, and a
        body that is missing the career narrative *and* names an unknown artist reports the
        shape error too rather than the reference's 404.

        PRD: "**Request shape** — required fields present, correct JSON types, enum members
        inside their declared sets, integers inside their declared ranges, strings meeting
        their declared minimum lengths, datetimes in ISO 8601 UTC (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/application_create_without_artist_statement_returns_invalid_request
        """
        ctx = cornermain_cycle_open()
        artist = validate_success(
            api_client.create_artist(
                {
                    "legal_name": "Cleo Amari",
                    "email": "cleo.amari@example.org",
                    "residency_start_date": "2023-01-10",
                    "residency_county": "Harbor",
                    "region": "NORTH",
                    "is_enrolled_student": False,
                    "tin_status": "ON_FILE",
                },
                PROGRAM_OFFICER,
            ),
            expected_status=201,
        )["id"]

        validate_error(
            api_client.create_application(
                {
                    "cycle_id": ctx.cyc,
                    "discipline_category_id": ctx.disc,
                    "artist_id": artist,
                    "career_narrative": "Twelve years of small-press publication.",
                },
                PROGRAM_OFFICER,
            ),
            "ERR_INVALID_REQUEST",
        )
        validate_error(
            api_client.create_application(
                {
                    "cycle_id": ctx.cyc,
                    "discipline_category_id": ctx.disc,
                    "artist_id": UNKNOWN_ID,
                    "artist_statement": "Prose poems about harbour towns.",
                },
                PROGRAM_OFFICER,
            ),
            "ERR_INVALID_REQUEST",
        )

        _, meta = validate_paginated(
            api_client.list_applications(PROGRAM_OFFICER, {"cycle_id": ctx.cyc})
        )
        assert meta["total_count"] == 0, (
            f"no application row may survive a shape error, got {meta['total_count']}"
        )

    def test_enum_membership_and_declared_ranges_are_both_enforced(self):
        """
        An out-of-set proration policy, an out-of-set work-sample medium and an ordinal of
        zero against a declared minimum of one are each refused as shape errors, leaving no
        row behind.

        PRD: "Each sample names its `application_id`, a `medium` from `MANUSCRIPT_PAGES`,
        `AUDIO`, `VIDEO` and `IMAGE_SET` that must fall inside the discipline's
        `allowed_media`, and an `ordinal` of at least 1 that is unique within the application
        and fixes presentation order."

        Design: Corner/entities/enum_and_range_constraints_are_enforced_on_write
        """
        ctx = cornermain_application_draft()

        validate_error(
            api_client.create_cycle(
                cycle_payload(
                    name="Bad policy",
                    fiscal_year=2028,
                    application_open_at="2027-08-15T00:00:00Z",
                    application_deadline_at="2027-10-15T23:59:59Z",
                    grant_period_start="2028-01-01T00:00:00Z",
                    grant_period_end="2028-12-31T00:00:00Z",
                    total_budget_cents=4_000_000,
                    base_award_cents=1_000_000,
                    min_prorated_award_cents=400_000,
                    proration_policy="SKIP",
                ),
                PROGRAM_OFFICER,
            ),
            "ERR_INVALID_REQUEST",
        )
        validate_error(
            api_client.create_work_sample(
                {"application_id": ctx.app, "medium": "SCULPTURE", "ordinal": 3},
                ctx.art_headers,
            ),
            "ERR_INVALID_REQUEST",
        )
        validate_error(
            api_client.create_work_sample(
                {
                    "application_id": ctx.app,
                    "medium": "MANUSCRIPT_PAGES",
                    "ordinal": 0,
                    "page_count": 4,
                },
                ctx.art_headers,
            ),
            "ERR_INVALID_REQUEST",
        )

        _, meta = validate_paginated(
            api_client.list_work_samples(PROGRAM_OFFICER, {"application_id": ctx.app})
        )
        assert meta["total_count"] == 2, (
            "only the two valid samples exist, got "
            f"{meta['total_count']}"
        )
        assert read_application(ctx.app)["work_sample_count"] == 2, (
            "no refused sample may be counted, got "
            f"{read_application(ctx.app)['work_sample_count']}"
        )


class TestDerivedSampleCount:
    """work_sample_count follows the child rows in both directions."""

    def test_the_sample_count_follows_the_child_rows_including_a_rejection(self):
        """
        A third sample lifts the count to three and screening it REJECTED brings the count
        back to two, while the rejected row itself is retained on the list.

        PRD: "`REJECTED` moves it to `REJECTED` and decrements the application's
        `work_sample_count` by one."

        Design: Corner/entities/work_sample_count_is_derived_from_child_rows_not_supplied
        """
        ctx = cornermain_application_draft()
        assert read_application(ctx.app)["work_sample_count"] == 2, (
            "two samples are attached to begin with"
        )

        third = validate_success(
            api_client.create_work_sample(
                {
                    "application_id": ctx.app,
                    "medium": "AUDIO",
                    "ordinal": 3,
                    "duration_seconds": 240,
                    "contains_identifying_metadata": False,
                },
                ctx.art_headers,
            ),
            expected_status=201,
        )["id"]
        assert read_application(ctx.app)["work_sample_count"] == 3, (
            "the third sample should be counted, got "
            f"{read_application(ctx.app)['work_sample_count']}"
        )

        screened = validate_success(
            api_client.screen_work_sample(third, "REJECTED", PROGRAM_OFFICER)
        )
        assert screened["status"] == "REJECTED", (
            f"the disposition should stick, got {screened['status']}"
        )
        assert screened["screened_by"] == PROGRAM_OFFICER_ID, (
            f"the screening officer is stamped, got {screened['screened_by']}"
        )

        assert read_application(ctx.app)["work_sample_count"] == 2, (
            "the rejection should decrement the derived count, got "
            f"{read_application(ctx.app)['work_sample_count']}"
        )
        _, meta = validate_paginated(
            api_client.list_work_samples(PROGRAM_OFFICER, {"application_id": ctx.app})
        )
        assert meta["total_count"] == 3, (
            f"the rejected row is retained, not deleted, got {meta['total_count']}"
        )


class TestBodyForeignKeys:
    """A body reference reports the referenced entity's own code."""

    def test_a_work_sample_under_an_unknown_application_reports_the_parent(self):
        """
        A work sample whose parent application id names no row is refused with the
        application's own 404 code even though that reference arrives in the body rather than
        the path, and no orphan child row is left behind.

        PRD: "The same codes serve references carried inside a request body, and body
        references are checked only after every path identifier has resolved."

        Design: Corner/entities/work_sample_under_an_unknown_application_returns_application_not_found
        """
        cornermain_cycle_open()

        validate_error(
            api_client.create_work_sample(
                work_sample_payload(UNKNOWN_ID, ordinal=1, page_count=6),
                PROGRAM_OFFICER,
            ),
            "ERR_APPLICATION_NOT_FOUND",
            expected_status=404,
        )
        _, meta = validate_paginated(api_client.list_work_samples(PROGRAM_OFFICER))
        assert meta["total_count"] == 0, (
            f"no dangling sample may be created, got {meta['total_count']}"
        )

    def test_body_level_references_report_the_referenced_entitys_code(self):
        """
        An unknown discipline on a panel, an unknown panel on a panelist and an unknown cycle
        on a discipline each surface the referenced entity's 404 rather than the code of the
        entity being created.

        PRD: "**Body foreign-key existence** — every reference inside the request body
        resolves to a row, evaluated in the order the fields are declared for that endpoint,
        so a body with two bad references reports the first declared one (the entity-specific
        404)."

        Design: Corner/entities/body_foreign_keys_are_validated_across_the_flat_topology
        """
        ctx = cornermain_cycle_open()

        validate_error(
            api_client.create_panel(
                {
                    "cycle_id": ctx.cyc,
                    "discipline_category_id": UNKNOWN_ID,
                    "required_seats": 3,
                    "required_regions": ["NORTH", "CENTRAL", "SOUTH"],
                    "deliberation_window_start": "2026-11-01T00:00:00Z",
                    "deliberation_window_end": "2026-12-01T00:00:00Z",
                },
                PROGRAM_OFFICER,
            ),
            "ERR_DISCIPLINE_CATEGORY_NOT_FOUND",
            expected_status=404,
        )
        validate_error(
            api_client.create_panelist(
                {
                    "panel_id": UNKNOWN_ID,
                    "person_email": "ghost@example.org",
                    "full_name": "Ghost Reader",
                    "region": "NORTH",
                    "expertise_codes": ["LITERARY_ARTS"],
                },
                PROGRAM_OFFICER,
            ),
            "ERR_PANEL_NOT_FOUND",
            expected_status=404,
        )
        validate_error(
            api_client.create_discipline(
                discipline_payload(
                    UNKNOWN_ID,
                    code="VISUAL_ARTS",
                    alias_prefix="VIS",
                    allocation_cents=500_000,
                    required_work_sample_count=3,
                    allowed_media=["IMAGE_SET"],
                    required_panel_seats=3,
                    required_regions=["NORTH"],
                ),
                PROGRAM_OFFICER,
            ),
            "ERR_CYCLE_NOT_FOUND",
            expected_status=404,
        )

        _, panel_meta = validate_paginated(
            api_client.list_panels(PROGRAM_OFFICER, {"cycle_id": ctx.cyc})
        )
        assert panel_meta["total_count"] == 0, (
            f"no panel may be created, got {panel_meta['total_count']}"
        )
        _, discipline_meta = validate_paginated(
            api_client.list_disciplines(PROGRAM_OFFICER, {"cycle_id": ctx.cyc})
        )
        assert discipline_meta["total_count"] == 1, (
            "the cycle keeps its one discipline, got "
            f"{discipline_meta['total_count']}"
        )
