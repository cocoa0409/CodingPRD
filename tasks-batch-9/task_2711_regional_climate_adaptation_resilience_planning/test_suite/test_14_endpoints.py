"""Envelope shape, filter composition, computed reads and the action endpoints.

Every test here drives the HTTP surface of PRD 4 directly so that the two
envelopes of PRD 2.2, the pagination contract of PRD 2.3 and the logical clock of
PRD 2.4 are observed on the wire rather than through a helper's return value.
"""

from test_helpers import (
    ADMIN,
    CLOCK_EPOCH_STAMP,
    EQUITY,
    REVIEWER,
    NON_EXISTENT_UUID,
    ApiErrorId,
    allocation_payload,
    analysis_payload,
    api_client,
    assert_error_envelope,
    assert_fields,
    assert_iso8601,
    assert_millisecond_utc_timestamp,
    assert_pact_conservation,
    assert_sorted_by_created_at,
    assert_success_envelope,
    assert_version_is,
    cast_endorsement,
    commit_aid,
    create_analysis,
    create_asset,
    create_asset_link,
    create_capital_program,
    create_harbor,
    create_pact,
    create_plan_cycle,
    create_project,
    create_ridge,
    create_screened_project,
    is_valid_uuid,
    jurisdiction_payload,
    make_jurisdiction_delegate_headers,
    make_project_sponsor_headers,
    open_endorsement_round,
    open_engagement,
    ranked_asset_context,
    read_analysis,
    read_asset,
    read_capital_program,
    read_commitment,
    read_jurisdiction,
    read_pact,
    read_plan_cycle,
    read_project,
    reject_analysis,
    ridge_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_TARGET = "2026-10-05T12:00:00Z"
CLOCK_TARGET_STAMP = "2026-10-05T12:00:00.000Z"


class TestTheTwoDeclaredEnvelopes:
    """A created resource and an unknown identifier use different envelopes.

    PRD 2.2 declares them side by side: a success body carries `meta`,
    `response_type` and `data`, while for an error "The `meta` object for error
    responses contains only `api_request_id` and `api_request_timestamp`" and the
    payload moves inside `data` as `error_id` and `message`.
    """

    def test_a_creation_and_an_unknown_id_are_shaped_by_prd_two_point_two(self):
        """201 gives response_type object; 404 gives response_type error.

        PRD 2.2 fixes the success side: "The `response_type` is either "object" for
        a single resource or "array" for a list of resources", and "Unless otherwise
        noted, operations that create or modify a resource will return the created or
        updated resource object in the data field."  PRD 2.4 requires the minted
        identifier: "Every persisted record carries an `id` that is a server-minted
        UUID with no type prefix and no embedded semantics; clients never supply it."
        On the failure side PRD 2.2 states "The `error_id` is a unique,
        machine-readable string that identifies the specific error" and "The
        `message` provides a human-readable explanation of what went wrong", both
        living inside `data`, and PRD 5 assigns an unknown member government the code
        `ERR_JURISDICTION_NOT_FOUND`.

        Design: Corner/endpoints/response_envelope_shape_on_success_and_on_not_found
        """
        created = api_client.create_jurisdiction(jurisdiction_payload(), ADMIN())

        assert created.status_code == 201, (
            f"admitting a member government must answer 201, got {created.status_code}: "
            f"{created.text}"
        )
        body = created.json()
        assert_success_envelope(body, "object")
        assert is_valid_uuid(body["data"]["id"]), (
            f"data.id must be a server-minted UUID, got {body['data'].get('id')!r}"
        )

        missing = api_client.get_jurisdiction(NON_EXISTENT_UUID, ADMIN())

        assert missing.status_code == 404, (
            f"an unknown member government must answer 404, got {missing.status_code}: "
            f"{missing.text}"
        )
        failure = missing.json()
        assert_error_envelope(failure, ApiErrorId.ERR_JURISDICTION_NOT_FOUND.value)
        assert "error_id" not in failure, (
            "PRD 2.2 keeps error_id inside data, so the top level must not repeat it, "
            f"got {sorted(failure.keys())}"
        )
        assert "id" not in failure["data"], (
            "an error data object holds only error_id and message, so there is no id, "
            f"got {sorted(failure['data'].keys())}"
        )

    def test_the_error_envelope_never_carries_pagination_fields(self):
        """A 404 meta holds exactly two keys while an array meta holds six.

        PRD 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."  PRD 2.3 adds the contrast for
        collections: "For every response whose `response_type` is `"array"`, the four
        pagination fields `limit`, `offset`, `total_count` and `has_more` are returned
        inside `meta` alongside `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_on_not_found
        """
        create_harbor()

        listed = api_client.list_jurisdictions(ADMIN())
        rows, meta = validate_paginated(listed)

        assert_success_envelope(listed.json(), "array")
        assert len(rows) == 1, f"the register holds exactly the one member, got {rows}"
        assert set(meta.keys()) == {
            "api_request_id",
            "api_request_timestamp",
            "limit",
            "offset",
            "total_count",
            "has_more",
        }, f"an array meta carries the two request fields plus four pagination fields, got {sorted(meta)}"

        missing = api_client.get_jurisdiction(NON_EXISTENT_UUID, ADMIN())

        assert_error_envelope(missing.json(), ApiErrorId.ERR_JURISDICTION_NOT_FOUND.value)
        assert_millisecond_utc_timestamp(
            missing.json()["meta"]["api_request_timestamp"], "the failure's meta.api_request_timestamp"
        )


class TestAmendingOnlyTheNamedFields:
    """A PATCH carrying one field rebands the member and touches nothing else."""

    def test_a_new_svi_score_rebands_the_member_and_leaves_the_rest_intact(self):
        """0.62 amended to 0.20 moves HIGH to LOW and clears the flag.

        PRD 3.1 restricts the amendment surface: "Amending a member is likewise
        reserved to a `RegionalAdministrator`, who may supply any combination of
        `status`, `endorsement_weight` and `svi_score`."  It then fixes the derived
        pair: "Supplying a new `svi_score` recomputes `svi_tier` and
        `disadvantaged_flag` on the spot", with the banding "`LOW` otherwise" for a
        score below 0.25 and "`disadvantaged_flag` is true exactly when `svi_tier` is
        `HIGH` or `SEVERE`, and false for `MODERATE` and `LOW`".  Because `name`,
        `jurisdiction_code` and `population` are not on the amendment surface at all,
        they must read exactly what admission wrote.

        Design: Corner/endpoints/jurisdiction_patch_updates_only_the_named_fields
        """
        harbor = create_harbor()
        assert_fields(
            harbor,
            {"svi_score": 0.62, "svi_tier": "HIGH", "disadvantaged_flag": True, "version": 1},
            "the member government as admitted",
        )

        response = api_client.patch_jurisdiction(harbor["id"], {"svi_score": 0.20}, ADMIN())

        amended = validate_success(response, 200)
        assert_fields(
            amended,
            {
                "id": harbor["id"],
                "name": "City of Harbor",
                "jurisdiction_code": "CITY-HARBOR",
                "population": 180000,
                "svi_score": 0.20,
                "svi_tier": "LOW",
                "disadvantaged_flag": False,
                "endorsement_weight": 4,
                "status": "ACTIVE",
            },
            "the amended member government",
        )

    def test_the_amendment_bumps_the_version_without_moving_created_at(self):
        """One mutation takes version 1 to 2 and leaves created_at where it was.

        PRD 2.4: "Every record also carries a `created_at` timestamp, written once at
        creation", and "a `version` integer that starts at 1 when the record is
        created and increments by exactly 1 on every mutation that changes the
        record".  PRD 3.1 confirms the counter for this endpoint: "Every amendment
        increments the member's `version` by 1."  Since PRD 2.4 also states that the
        logical clock "starts at `2026-08-01T00:00:00Z` when the server boots and
        never advances on its own", the refreshed `updated_at` reads the same instant
        as `created_at`.

        Design: Corner/endpoints/jurisdiction_patch_updates_only_the_named_fields
        """
        harbor = create_harbor()

        amended = validate_success(
            api_client.patch_jurisdiction(harbor["id"], {"svi_score": 0.20}, ADMIN()), 200
        )

        assert_version_is(amended, 2, "the amended member government")
        assert amended["created_at"] == CLOCK_EPOCH_STAMP, (
            "created_at is written once at creation and the clock has not moved, so it "
            f"must still read {CLOCK_EPOCH_STAMP}, got {amended['created_at']!r}"
        )
        assert amended["updated_at"] == CLOCK_EPOCH_STAMP, (
            "the refreshed updated_at reads the unmoved logical clock, expected "
            f"{CLOCK_EPOCH_STAMP}, got {amended['updated_at']!r}"
        )
        assert_fields(read_jurisdiction(harbor["id"]), {"version": 2}, "the re-read member")


class TestFiltersComposeWithPagination:
    """A domain filter narrows the total_count that pagination then walks."""

    @staticmethod
    def _three_projects_two_of_them_flood():
        harbor = create_harbor()
        cycle = create_plan_cycle()
        levee = create_project(
            cycle["id"], harbor["id"], name="Levee Raise", hazard_type="FLOOD",
            strategy_type="PROTECT",
        )
        culvert = create_project(
            cycle["id"], harbor["id"], name="Culvert Upsizing", hazard_type="FLOOD",
            strategy_type="ACCOMMODATE", base_cost_cents=30000000, service_life_years=25,
            cobenefit_points=10, feasibility_score=0.65,
        )
        corridor = create_project(
            cycle["id"], harbor["id"], name="Cooling Corridor", hazard_type="HEAT",
            strategy_type="ACCOMMODATE", base_cost_cents=30000000, service_life_years=25,
            cobenefit_points=10, feasibility_score=0.65,
        )
        return {"harbor": harbor, "cycle": cycle, "levee": levee,
                "culvert": culvert, "corridor": corridor}

    def test_the_hazard_filter_sets_the_total_count_the_defaults_then_report(self):
        """Two of three projects match FLOOD, and meta reports the filtered total.

        PRD 2.3: "`total_count` counts every row matching the supplied filters across
        the whole collection, not merely the rows on the current page, and `has_more`
        is true exactly when rows matching the filters remain beyond the current
        page."  The same section supplies the untouched defaults — "`limit` defaults to
        10 ... `offset` defaults to 0" — and the ordering, "Collections are always
        returned sorted by `created_at` in ascending order".  PRD 2.3 lists
        `hazard_type` among the filters adaptation projects accept.

        Design: Corner/endpoints/project_list_filters_compose_with_pagination
        """
        context = self._three_projects_two_of_them_flood()

        response = api_client.list_projects(ADMIN(), params={"hazard_type": "FLOOD"})

        rows, meta = validate_paginated(response)
        assert_success_envelope(response.json(), "array")
        assert [row["id"] for row in rows] == [
            context["levee"]["id"], context["culvert"]["id"]
        ], f"only the two flood projects match, oldest first, got {[r['name'] for r in rows]}"
        assert_sorted_by_created_at(rows)
        assert_fields(
            meta,
            {"total_count": 2, "has_more": False, "limit": 10, "offset": 0},
            "the meta of the filtered collection",
        )

    def test_a_one_row_page_walk_holds_the_filtered_total_across_both_pages(self):
        """limit 1 splits the two matches into two pages without changing total_count.

        PRD 2.3: "a stable page walk is possible by holding `limit` fixed and
        advancing `offset`", while "`total_count` counts every row matching the
        supplied filters across the whole collection, not merely the rows on the
        current page, and `has_more` is true exactly when rows matching the filters
        remain beyond the current page."  Ascending `created_at` order puts the levee
        on the first page and the culvert on the second.

        Design: Corner/endpoints/project_list_filters_compose_with_pagination
        """
        context = self._three_projects_two_of_them_flood()
        params = {"hazard_type": "FLOOD", "limit": 1}

        first, first_meta = validate_paginated(
            api_client.list_projects(ADMIN(), params={**params, "offset": 0})
        )
        second, second_meta = validate_paginated(
            api_client.list_projects(ADMIN(), params={**params, "offset": 1})
        )

        assert [row["id"] for row in first] == [context["levee"]["id"]], (
            f"the first page holds the oldest flood project alone, got {first}"
        )
        assert_fields(
            first_meta,
            {"total_count": 2, "has_more": True, "limit": 1, "offset": 0},
            "the meta of the first page",
        )
        assert [row["id"] for row in second] == [context["culvert"]["id"]], (
            f"the second page holds the younger flood project alone, got {second}"
        )
        assert_fields(
            second_meta,
            {"total_count": 2, "has_more": False, "limit": 1, "offset": 1},
            "the meta of the last page",
        )

    def test_a_filter_matching_nothing_reports_a_total_count_of_zero(self):
        """No project has been screened, so the screening_status filter empties the page.

        PRD 2.3 lists `screening_status` among the filters adaptation projects accept
        and requires that "`total_count` counts every row matching the supplied
        filters across the whole collection".  PRD 3.5 fixes the standing of all three
        rows: "A freshly proposed project reads `screening_status` `PROPOSED`,
        `analysis_status` `NOT_ANALYZED`, `program_status` `UNPROGRAMMED` and
        `implementation_status` `NOT_STARTED`", and none of the three has been
        screened, so nothing matches `SCREENED_IN`.

        Design: Corner/endpoints/project_list_filters_compose_with_pagination
        """
        self._three_projects_two_of_them_flood()

        rows, meta = validate_paginated(
            api_client.list_projects(ADMIN(), params={"screening_status": "SCREENED_IN"})
        )

        assert rows == [], f"no project has been screened in, got {rows}"
        assert_fields(
            meta,
            {"total_count": 0, "has_more": False, "limit": 10, "offset": 0},
            "the meta of the empty result",
        )
        unfiltered, unfiltered_meta = validate_paginated(api_client.list_projects(ADMIN()))
        assert unfiltered_meta["total_count"] == 3, (
            "the unfiltered collection still holds all three projects, got "
            f"{unfiltered_meta['total_count']}"
        )
        assert all(row["screening_status"] == "PROPOSED" for row in unfiltered), (
            f"all three projects are still PROPOSED, got {[r['screening_status'] for r in unfiltered]}"
        )


class TestTheTallyProjectionWritesNothing:
    """Reading the projection twice leaves the cycle exactly where it stood."""

    def test_two_reads_agree_and_neither_advances_the_cycle(self):
        """Seven of seven supporting weight reads 10000 bps twice over.

        PRD 3.8 describes the endpoint as a pure read: "the system also exposes a
        **read-only projection** of it that writes nothing at all. It reports the
        cycle's current `round_number`, the `total_active_weight` denominator, the
        `supporting_weight` and `veto_weight` numerators, the resulting
        `achieved_weight_bps`, the cycle's configured `quorum_weight_bps`, and a
        `projected_outcome` string naming which of the three outcomes closing the round
        right now would produce."  The arithmetic is PRD 3.8's tally: "The
        **denominator** is the sum of `endorsement_weight` over every jurisdiction whose
        `status` is `ACTIVE`", giving 4 plus 3; "the **supporting weight** is the sum of
        `weight_at_cast` over the `ENDORSED` rows, plus half of the sum of
        `weight_at_cast` over the `CONDITIONED` rows", giving 7; and
        "`achieved_weight_bps` is 0 when the denominator is 0, and otherwise ten
        thousand multiplied by the supporting weight divided by the denominator,
        floored to whole basis points", giving 10000.  Because only closing the round
        writes anything, PRD 3.8's "On success `round_number` increments by 1 and the
        cycle's `version` increments by 1" is the last mutation the cycle saw.

        Design: Corner/endpoints/endorsement_tally_is_a_side_effect_free_computed_read
        """
        harbor = create_harbor()
        ridge = create_ridge()
        cycle = create_plan_cycle(quorum_weight_bps=6600, required_session_count=0)
        create_screened_project(cycle["id"], harbor["id"])
        open_engagement(cycle["id"])
        opened = open_endorsement_round(cycle["id"])
        cast_endorsement(cycle["id"], harbor["id"], decision="ENDORSED")
        cast_endorsement(cycle["id"], ridge["id"], decision="ENDORSED")

        first = validate_success(api_client.get_endorsement_tally(cycle["id"], EQUITY()), 200)
        second = validate_success(api_client.get_endorsement_tally(cycle["id"], EQUITY()), 200)

        expected = {
            "round_number": 1,
            "total_active_weight": 7,
            "supporting_weight": 7,
            "veto_weight": 0,
            "achieved_weight_bps": 10000,
            "quorum_weight_bps": 6600,
        }
        assert_fields(first, expected, "the first reading of the projection")
        assert_fields(second, expected, "the second reading of the projection")
        assert isinstance(first["projected_outcome"], str) and first["projected_outcome"], (
            "the projection must name the outcome closing the round would produce, got "
            f"{first.get('projected_outcome')!r}"
        )
        assert first["projected_outcome"] == second["projected_outcome"], (
            "a read that writes nothing cannot change its own answer, got "
            f"{first['projected_outcome']!r} then {second['projected_outcome']!r}"
        )

        after = read_plan_cycle(cycle["id"])
        assert_fields(
            after,
            {
                "status": "ENDORSEMENT_ROUND",
                "round_number": 1,
                "revision_count": 0,
                "version": opened["version"],
                "adopted_at": None,
                "achieved_weight_bps": None,
            },
            "the cycle after two projection reads",
        )
        assert opened["version"] == 3, (
            "creation, opening engagement and opening the round are three mutations, so "
            f"the cycle stands at version 3, got {opened['version']}"
        )
        rows, meta = validate_paginated(
            api_client.list_endorsements(ADMIN(), params={"plan_cycle_id": cycle["id"]})
        )
        assert meta["total_count"] == 2, (
            f"both endorsements survive the reads, got {meta['total_count']}"
        )
        assert [row["decision"] for row in rows] == ["ENDORSED", "ENDORSED"], (
            f"neither decision was rewritten, got {[row['decision'] for row in rows]}"
        )


class TestTheLogicalClockMovesOnlyLaterWrites:
    """Moving the clock stamps rows written afterwards and rewrites nothing earlier."""

    def test_the_clock_action_dates_the_next_row_and_leaves_the_first_alone(self):
        """Harbor keeps the boot instant while Ridge takes the new one.

        PRD 2.4: "The clock starts at `2026-08-01T00:00:00Z` when the server boots and
        never advances on its own. An administrative test-driving capability moves it:
        the request supplies the target instant as `to_iso8601`, and the response
        reports the resulting clock reading as `current_utc`."  Because PRD 2.4 also
        says "Every record also carries a `created_at` timestamp, written once at
        creation, formatted as an ISO 8601 UTC instant with exactly three fractional
        digits", the member admitted after the move carries the new instant while the
        earlier member's stamp — written once — cannot move, and its `version` stays
        at 1 because nothing mutated it.

        Design: Corner/endpoints/clock_set_action_moves_the_logical_now_for_later_writes
        """
        harbor = create_harbor()
        assert harbor["created_at"] == CLOCK_EPOCH_STAMP, (
            f"the boot clock stamps the first member {CLOCK_EPOCH_STAMP}, got "
            f"{harbor['created_at']!r}"
        )

        moved = validate_success(api_client.set_clock(CLOCK_TARGET, ADMIN()), 200)

        assert_iso8601(moved["current_utc"], "the clock reading reported by the move")
        assert moved["current_utc"].startswith("2026-10-05T12:00:00"), (
            f"the clock must report the supplied instant, got {moved['current_utc']!r}"
        )

        response = api_client.create_jurisdiction(ridge_payload(), ADMIN())

        ridge = validate_success(response, 201)
        assert ridge["created_at"] == CLOCK_TARGET_STAMP, (
            f"a row written after the move carries {CLOCK_TARGET_STAMP}, got "
            f"{ridge['created_at']!r}"
        )
        assert_fields(
            read_jurisdiction(harbor["id"]),
            {"created_at": CLOCK_EPOCH_STAMP, "updated_at": CLOCK_EPOCH_STAMP, "version": 1},
            "the member admitted before the clock moved",
        )


def _draft_case_and_program():
    """A screened project with one link, a DRAFT case, and an open program."""
    context = ranked_asset_context()
    harbor_id = context["harbor"]["id"]
    cycle = create_plan_cycle(required_session_count=0)
    project = create_screened_project(cycle["id"], harbor_id)
    create_asset_link(
        project["id"], harbor_id, context["asset"]["id"], 3333333,
        benefit_reaches_disadvantaged=True,
    )
    analysis = create_analysis(
        project["id"], harbor_id, method="ANNUALIZED_EQUIVALENT", discount_rate_bps=None
    )
    program = create_capital_program(authorized_cents=100000000, equity_target_bps=None)
    context.update(
        {"cycle": cycle, "project": project, "analysis": analysis, "program": program}
    )
    return context


class TestRejectionIsTerminalForItsRow:
    """A rejected case can never be rejected again, nor fund its project."""

    def test_the_second_rejection_of_the_same_case_is_refused(self):
        """The first reject lands REJECTED and the second sees ERR_ANALYSIS_NOT_DRAFT.

        PRD 3.6: "On success the analysis moves `DRAFT → REJECTED`, which is terminal
        for that row, the owning project's `analysis_status` moves `BCA_PENDING →
        BCA_REJECTED`, and the analysis's `version` increments by 1."  The same
        paragraph carries the guard the repeat trips: rejection "carries only two of
        those four guards: the analysis must be in `DRAFT`, or `ERR_ANALYSIS_NOT_DRAFT`,
        and the reviewer must not be the preparer, or `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/endpoints/analysis_reject_action_leaves_the_project_uncertified
        """
        context = _draft_case_and_program()
        analysis_id = context["analysis"]["id"]

        first = api_client.reject_analysis(analysis_id, REVIEWER("reviewer-01"))

        rejected = validate_success(first, 200)
        assert_fields(
            rejected,
            {"status": "REJECTED", "version": 2, "stale_reason": "NONE"},
            "the rejected case",
        )
        assert_fields(
            read_project(context["project"]["id"]),
            {"analysis_status": "BCA_REJECTED"},
            "the project whose case was turned down",
        )

        second = api_client.reject_analysis(analysis_id, REVIEWER("reviewer-01"))

        validate_error(second, ApiErrorId.ERR_ANALYSIS_NOT_DRAFT.value, 409)
        assert_fields(
            read_analysis(analysis_id),
            {"status": "REJECTED", "version": 2},
            "the case a second rejection could not touch",
        )

    def test_a_rejected_project_cannot_be_funded_but_may_be_re_analysed(self):
        """Allocation is refused at guard five, and a fresh DRAFT is still admitted.

        PRD 3.7 numbers the allocation guards and this project fails the fifth: "The
        project's `analysis_status` must be `BCA_CERTIFIED`, or `ERR_BCA_NOT_CERTIFIED`
        — a project whose analysis reads `BCA_PENDING`, `BCA_REJECTED` or `BCA_STALE`
        cannot be funded."  The program's ledger therefore stays as PRD 3.7 opened it:
        "A new program starts with `committed_cents` 0, `available_cents` equal to
        `authorized_cents`, `equity_committed_cents` 0, `equity_achieved_bps` 0 and
        `funding_posture` `OPEN`."  PRD 3.6 then permits the retry: "Re-preparation
        after a rejection does **not** require re-screening the project, and the
        rejected analysis keeps its `REJECTED` status forever — a fresh `DRAFT` row is
        created alongside it", and a new case "copies the project's
        `service_life_years` onto the analysis as `analysis_horizon_years`".

        Design: Corner/endpoints/analysis_reject_action_leaves_the_project_uncertified
        """
        context = _draft_case_and_program()
        project_id = context["project"]["id"]
        program = context["program"]
        reject_analysis(context["analysis"]["id"])

        refused = api_client.allocate(
            program["id"],
            allocation_payload(project_id, 51273600, program["version"]),
            ADMIN(),
        )

        validate_error(refused, ApiErrorId.ERR_BCA_NOT_CERTIFIED.value, 409)
        unchanged = read_capital_program(program["id"])
        assert_fields(
            unchanged,
            {
                "committed_cents": 0,
                "available_cents": 100000000,
                "equity_committed_cents": 0,
                "equity_achieved_bps": 0,
                "funding_posture": "OPEN",
                "version": 1,
            },
            "the program that funded nothing",
        )
        assert_fields(
            read_project(project_id),
            {"program_status": "UNPROGRAMMED", "capital_program_id": None, "allocated_cents": 0},
            "the project the refusal left unprogrammed",
        )

        fresh = api_client.create_analysis(
            project_id,
            analysis_payload(method="DISCOUNTED_NPV", discount_rate_bps=None),
            make_project_sponsor_headers(context["harbor"]["id"]),
        )

        second_case = validate_success(fresh, 201)
        assert_fields(
            second_case,
            {
                "status": "DRAFT",
                "method": "DISCOUNTED_NPV",
                "stale_reason": "NONE",
                "analysis_horizon_years": 30,
                "version": 1,
            },
            "the case prepared after the rejection",
        )
        assert_fields(
            read_analysis(context["analysis"]["id"]),
            {"status": "REJECTED"},
            "the rejected case that keeps its standing forever",
        )
        assert_fields(
            read_project(project_id),
            {"analysis_status": "BCA_PENDING"},
            "the project awaiting review again",
        )


def _cross_boundary_commitment():
    """Harbor pledges cooling units; Ridge draws four of them for Harbor's centre."""
    harbor = create_harbor()
    ridge = create_ridge()
    shared_asset = create_asset(
        harbor["id"], name="Harbor Cooling Centre", asset_class="HEALTH",
        replacement_value_cents=300000000, service_population=60000,
        redundancy_factor=0.10, is_shared=True,
    )
    pact = create_pact(
        harbor["id"], resource_class="COOLING_UNITS", pledged_units=10,
        window_start="2026-09-01T00:00:00Z", window_end="2026-10-01T00:00:00Z",
        max_concurrent_commitments=3,
    )
    commitment = commit_aid(
        pact["id"], ridge["id"], shared_asset["id"], 4,
        "2026-09-05T00:00:00Z", "2026-09-15T00:00:00Z", pact["version"],
    )
    return {"harbor": harbor, "ridge": ridge, "asset": shared_asset,
            "pact": pact, "commitment": commitment}


class TestTheCommitmentIsQueryableFromEitherEnd:
    """One draw is reachable by pact, by requester and by supported asset."""

    def test_all_three_declared_filters_return_the_same_single_row(self):
        """The pact belongs to Harbor, the requester is Ridge, and the asset is shared.

        PRD 2.3 declares the filter surface: "Mutual aid commitments accept `pact_id`,
        `requesting_jurisdiction_id`, `asset_id` and `status`."  PRD 3.9 makes the row
        genuinely cross-jurisdictional: "the commitment names the
        `requesting_jurisdiction_id` receiving the aid — necessarily the caller's own
        member government — the `asset_id` of the shared lifeline asset the aid
        supports", subject to two of the nine ordered guards, "The named lifeline
        asset's `is_shared` must be true, because only shared assets may be supported
        across jurisdictional lines; otherwise `ERR_ASSET_NOT_SHARED`" and
        "`requesting_jurisdiction_id` must differ from the pact's
        `host_jurisdiction_id`".  PRD 3.9 also fixes the fresh row's standing: "A
        successful commitment reads `status` `COMMITTED` with `released_at` and
        `fulfilled_at` both null."

        Design: Corner/endpoints/commitment_cross_reference_links_a_pact_to_another_jurisdictions_asset
        """
        context = _cross_boundary_commitment()
        commitment_id = context["commitment"]["id"]
        queries = (
            {"pact_id": context["pact"]["id"]},
            {"asset_id": context["asset"]["id"]},
            {"requesting_jurisdiction_id": context["ridge"]["id"], "status": "COMMITTED"},
        )

        for params in queries:
            rows, meta = validate_paginated(api_client.list_commitments(ADMIN(), params=params))
            assert meta["total_count"] == 1, (
                f"the filter {params} must reach exactly the one commitment, got "
                f"{meta['total_count']}"
            )
            assert [row["id"] for row in rows] == [commitment_id], (
                f"the filter {params} must return the commitment itself, got {rows}"
            )
            assert_fields(
                rows[0],
                {
                    "pact_id": context["pact"]["id"],
                    "requesting_jurisdiction_id": context["ridge"]["id"],
                    "asset_id": context["asset"]["id"],
                    "committed_units": 4,
                    "status": "COMMITTED",
                    "released_at": None,
                    "fulfilled_at": None,
                },
                f"the commitment reached through {params}",
            )

        assert_fields(
            read_asset(context["asset"]["id"]),
            {"jurisdiction_id": context["harbor"]["id"], "is_shared": True},
            "the shared asset the aid supports",
        )
        assert_fields(
            read_pact(context["pact"]["id"]),
            {"host_jurisdiction_id": context["harbor"]["id"]},
            "the pact the aid was drawn from",
        )


class TestFulfilmentAndReleaseExcludeEachOther:
    """Fulfilment consumes the units, so release has nothing left to give back."""

    def test_a_fulfilled_draw_refuses_release_and_keeps_its_units_reserved(self):
        """FULFILLED stamps fulfilled_at, blocks release, and holds reserved at four.

        PRD 3.9: "**Fulfilling** a commitment is the other terminal move and is
        likewise gated on the commitment being in `COMMITTED`, yielding
        `ERR_COMMITMENT_NOT_ACTIVE` otherwise. It moves the commitment `COMMITTED →
        FULFILLED` and stamps `fulfilled_at` from the logical clock. Crucially,
        fulfilment leaves `reserved_units` and `free_units` **unchanged**, because a
        fulfilled commitment stays inside the reserved set — the units were actually
        consumed, so releasing them back to the pledge would be double-counting. Only
        the commitment's `version` increments by 1."  Release is then closed off by
        "releasing one already `RELEASED` or `FULFILLED` yields
        `ERR_COMMITMENT_NOT_ACTIVE`", and the reserved figure is PRD 3.9's peak rule:
        "`reserved_units` is set to the **peak** concurrent unit load over the pact's
        `COMMITTED` and `FULFILLED` commitments ... and `free_units` becomes
        `pledged_units` minus `reserved_units`."

        Design: Corner/endpoints/commitment_fulfill_and_release_are_mutually_exclusive_actions
        """
        context = _cross_boundary_commitment()
        commitment_id = context["commitment"]["id"]
        # PRD 2.1: for a `JurisdictionDelegate` "ownership checks compare
        # `X-User-ID` to ... the `requesting_jurisdiction_id` of a mutual aid
        # commitment", so the commitment's own verbs belong to Ridge, the
        # requester, not to Harbor, which merely hosts the pledge.
        requester_headers = make_jurisdiction_delegate_headers(context["ridge"]["id"])

        fulfilled = validate_success(
            api_client.fulfill_commitment(commitment_id, requester_headers), 200
        )

        assert_fields(
            fulfilled,
            {
                "status": "FULFILLED",
                "fulfilled_at": CLOCK_EPOCH_STAMP,
                "released_at": None,
                "committed_units": 4,
                "version": 2,
            },
            "the fulfilled commitment",
        )

        refused = api_client.release_commitment(commitment_id, requester_headers)

        validate_error(refused, ApiErrorId.ERR_COMMITMENT_NOT_ACTIVE.value, 409)
        assert_fields(
            read_commitment(commitment_id),
            {"status": "FULFILLED", "released_at": None, "version": 2},
            "the commitment release could not touch",
        )

        pact = read_pact(context["pact"]["id"])
        assert_fields(
            pact,
            {
                "pledged_units": 10,
                "reserved_units": 4,
                "free_units": 6,
                "status": "OPEN",
                "version": 2,
            },
            "the pact whose pledge stays consumed",
        )
        assert_pact_conservation(pact)
