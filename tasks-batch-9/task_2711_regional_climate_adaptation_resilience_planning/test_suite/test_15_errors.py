"""Each declared failure mode is triggerable, and each has its own identifier.

The tests here reach the error rather than the happy path on purpose: PRD 2.5
makes validation "a strictly ordered ladder, not a set of independent checks", so
the identifier a call returns is itself part of the contract.
"""

from test_helpers import (
    ADMIN,
    ANALYST,
    REVIEWER,
    ApiErrorId,
    analysis_payload,
    api_client,
    asset_link_payload,
    assert_error_envelope,
    assert_fields,
    certify_analysis,
    commit_aid,
    commitment_payload,
    create_analysis,
    create_asset,
    create_asset_link,
    create_harbor,
    create_pact,
    create_plan_cycle,
    create_project,
    create_ridge,
    create_screened_project,
    grant_submission_payload,
    make_jurisdiction_delegate_headers,
    make_project_sponsor_headers,
    open_engagement,
    ranked_asset_context,
    read_analysis,
    read_assessment,
    read_pact,
    read_plan_cycle,
    read_project,
    screen_project,
    validate_error,
    validate_paginated,
    validate_success,
)

NON_EXISTENT = "00000000-0000-0000-0000-000000000000"

# PRD 2.5, priority 4: the identifier-to-code map, in the order PRD 2.5 lists it.
NOT_FOUND_PATHS = (
    ("jurisdiction_id", api_client.get_jurisdiction, ApiErrorId.ERR_JURISDICTION_NOT_FOUND),
    ("plan_cycle_id", api_client.get_plan_cycle, ApiErrorId.ERR_PLAN_CYCLE_NOT_FOUND),
    ("hazard_profile_id", api_client.get_hazard_profile, ApiErrorId.ERR_HAZARD_PROFILE_NOT_FOUND),
    ("asset_id", api_client.get_asset, ApiErrorId.ERR_ASSET_NOT_FOUND),
    ("assessment_id", api_client.get_assessment, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND),
    ("project_id", api_client.get_project, ApiErrorId.ERR_PROJECT_NOT_FOUND),
    ("link_id", api_client.get_asset_link, ApiErrorId.ERR_LINK_NOT_FOUND),
    ("analysis_id", api_client.get_analysis, ApiErrorId.ERR_ANALYSIS_NOT_FOUND),
    ("program_id", api_client.get_capital_program, ApiErrorId.ERR_PROGRAM_NOT_FOUND),
    ("session_id", api_client.get_engagement_session, ApiErrorId.ERR_SESSION_NOT_FOUND),
    ("endorsement_id", api_client.get_endorsement, ApiErrorId.ERR_ENDORSEMENT_NOT_FOUND),
    ("pact_id", api_client.get_pact, ApiErrorId.ERR_PACT_NOT_FOUND),
    ("commitment_id", api_client.get_commitment, ApiErrorId.ERR_COMMITMENT_NOT_FOUND),
)


class TestEveryPathIdentifierHasItsOwnNotFoundCode:
    """Thirteen read paths, thirteen distinguishable 404 identifiers."""

    def test_each_of_the_thirteen_unknown_ids_names_its_own_entity(self):
        """No path falls back on a shared generic not-found identifier.

        PRD 2.5, priority 4: "Every identifier embedded in the URL must resolve to an
        existing row, and they are checked in the order they appear in the path from
        left to right, so on a nested path the leftmost unresolved identifier decides
        the error. An unresolved `jurisdiction_id` yields `ERR_JURISDICTION_NOT_FOUND`;
        `plan_cycle_id` yields `ERR_PLAN_CYCLE_NOT_FOUND`; `hazard_profile_id` yields
        `ERR_HAZARD_PROFILE_NOT_FOUND`; `asset_id` yields `ERR_ASSET_NOT_FOUND`;
        `assessment_id` yields `ERR_ASSESSMENT_NOT_FOUND`; `project_id` yields
        `ERR_PROJECT_NOT_FOUND`; `link_id` yields `ERR_LINK_NOT_FOUND`; `analysis_id`
        yields `ERR_ANALYSIS_NOT_FOUND`; `program_id` yields `ERR_PROGRAM_NOT_FOUND`;
        `session_id` yields `ERR_SESSION_NOT_FOUND`; `endorsement_id` yields
        `ERR_ENDORSEMENT_NOT_FOUND`; `pact_id` yields `ERR_PACT_NOT_FOUND`; and
        `commitment_id` yields `ERR_COMMITMENT_NOT_FOUND`. All thirteen are HTTP 404."

        Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_code
        """
        observed = []
        for path_field, getter, expected in NOT_FOUND_PATHS:
            response = getter(NON_EXISTENT, ADMIN())
            assert response.status_code == 404, (
                f"an unresolved {path_field} must answer 404, got {response.status_code}: "
                f"{response.text}"
            )
            assert_error_envelope(response.json(), expected.value)
            observed.append(response.json()["data"]["error_id"])

        assert observed == [expected.value for _, _, expected in NOT_FOUND_PATHS], (
            f"each path must map to its own identifier, got {observed}"
        )
        assert len(set(observed)) == 13, (
            f"all thirteen identifiers must be distinguishable, got {sorted(set(observed))}"
        )

    def test_an_unresolved_body_reference_reuses_the_same_identifier_map(self):
        """A body `jurisdiction_id` that resolves to nothing is also a jurisdiction 404.

        PRD 2.5, priority 5: "Every foreign reference carried in a request payload must
        resolve, checked in the order the endpoint declares its input fields, using the
        same identifier-to-code map as the path check. A body `jurisdiction_id`,
        `host_jurisdiction_id` or `requesting_jurisdiction_id` that does not resolve
        yields `ERR_JURISDICTION_NOT_FOUND`; a body `asset_id` or `upstream_asset_id`
        yields `ERR_ASSET_NOT_FOUND`."

        Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_code
        """
        harbor = create_harbor()
        cycle = create_plan_cycle()
        screened = create_screened_project(cycle["id"], harbor["id"])

        unknown_asset = api_client.create_asset_link(
            screened["id"],
            asset_link_payload(NON_EXISTENT, 3333333, benefit_reaches_disadvantaged=True),
            make_project_sponsor_headers(harbor["id"]),
        )

        validate_error(unknown_asset, ApiErrorId.ERR_ASSET_NOT_FOUND.value, 404)
        links, meta = validate_paginated(
            api_client.list_asset_links(ADMIN(), params={"project_id": screened["id"]})
        )
        assert meta["total_count"] == 0 and links == [], (
            f"a refused reference writes nothing at all, got {links}"
        )


class TestReassessingAnAssessedRowIsRefused:
    """The recompute is gated on the row's own status, not on the projection."""

    def test_a_second_assess_is_refused_and_keeps_the_first_score(self):
        """0.82 stays 0.82 and the row stays ASSESSED at version 2.

        PRD 3.3 orders the two guards: "**first** the referenced hazard profile must
        currently be in `PUBLISHED` status, and a profile still in `DRAFT` or already
        `SUPERSEDED` yields `ERR_HAZARD_PROFILE_NOT_PUBLISHED`; **then** the assessment
        itself must be in either `DRAFT` or `STALE`, and an assessment already sitting
        in `ASSESSED` yields `ERR_ASSESSMENT_NOT_PENDING`."  The score the first pass
        left behind follows PRD 3.3: "Under `ADDITIVE_WEIGHTED`, the raw figure is the
        exposure term weighted at 0.40, plus the sensitivity term weighted at 0.35, plus
        the adaptive gap weighted at 0.25", then "The raw figure is then multiplied by
        the social vulnerability multiplier, and the subject uplift is added to that
        product", with the multiplier "1.25 for `HIGH`" and the uplift "0.00 for
        `INFRASTRUCTURE`" — 0.655 times 1.25 is 0.81875, rounding to 0.82, and PRD 3.3
        bands it "`EXTREME` when the score is at least 0.75".

        Design: Corner/errors/assessing_an_already_assessed_row_returns_409
        """
        context = ranked_asset_context()
        assessment = context["assessment"]
        assert_fields(
            assessment,
            {
                "status": "ASSESSED",
                "vulnerability_score": 0.82,
                "vulnerability_band": "EXTREME",
                "version": 2,
            },
            "the assessment as first computed",
        )

        response = api_client.assess(assessment["id"], ANALYST())

        validate_error(response, ApiErrorId.ERR_ASSESSMENT_NOT_PENDING.value, 409)
        assert_fields(
            read_assessment(assessment["id"]),
            {
                "status": "ASSESSED",
                "vulnerability_score": 0.82,
                "vulnerability_band": "EXTREME",
                "version": 2,
            },
            "the assessment the refusal left alone",
        )


class TestLinkingIsGatedOnScreeningStatus:
    """The identical link payload is refused before screening and accepted after."""

    def test_the_gate_is_the_projects_screening_status_and_not_the_asset(self):
        """PROPOSED refuses the link, SCREENED_IN accepts it as link_sequence 1.

        PRD 3.6: "Linking is permitted only while the project's `screening_status` is
        `SCREENED_IN`; a project still in `PROPOSED`, or one that was `SCREENED_OUT`, is
        rejected with `ERR_PROJECT_NOT_SCREENED_IN`."  Screening supplies the transition,
        since PRD 3.5 says "A score of at least 0.4500 moves the project `PROPOSED →
        SCREENED_IN`", and PRD 3.6 numbers the accepted link: "Each accepted link is
        stamped with a `link_sequence` equal to one plus the count of links already held
        by that project, ordered by `created_at` ascending — so the first link on a
        project is 1, the second is 2, and so on."  The refused attempt therefore leaves
        the count at zero.

        Design: Corner/errors/linking_an_asset_to_an_unscreened_project_returns_409
        """
        context = ranked_asset_context()
        harbor_id = context["harbor"]["id"]
        cycle = create_plan_cycle()
        project = create_project(cycle["id"], harbor_id)
        payload = asset_link_payload(
            context["asset"]["id"], 3333333, benefit_reaches_disadvantaged=True
        )
        sponsor = make_project_sponsor_headers(harbor_id)

        refused = api_client.create_asset_link(project["id"], payload, sponsor)

        validate_error(refused, ApiErrorId.ERR_PROJECT_NOT_SCREENED_IN.value, 409)

        screened = screen_project(project["id"])
        assert_fields(
            screened,
            {"screening_status": "SCREENED_IN", "screen_score": 0.6925},
            "the newly screened project",
        )

        accepted = api_client.create_asset_link(project["id"], payload, sponsor)

        link = validate_success(accepted, 201)
        assert_fields(
            link,
            {"link_sequence": 1, "avoided_loss_annual_cents": 3333333},
            "the first link the project accepted",
        )
        _rows, meta = validate_paginated(
            api_client.list_asset_links(ADMIN(), params={"project_id": project["id"]})
        )
        assert meta["total_count"] == 1, (
            f"the refused attempt consumed no sequence number, got {meta['total_count']} links"
        )


class TestGrantSubmissionNeedsAProgrammedProject:
    """The program-status gate fires long before the eligibility gate."""

    def test_an_unprogrammed_project_cannot_submit_a_grant_application(self):
        """A SCREENED_IN but unfunded project is refused on the first guard.

        PRD 3.7 fixes the guard order: "Four conditions guard it, in this order: the
        project's `program_status` must be `PROGRAMMED`, or `ERR_PROJECT_NOT_PROGRAMMED`;
        the project's `prerequisite_project_id` must be null or the prerequisite
        project's own `program_status` must already be `AWARDED`, or
        `ERR_PREREQUISITE_NOT_AWARDED`; the project's certified analysis must be
        grant-eligible, meaning its `bcr` is at least 1.0000 and its `grant_eligible` is
        true, or `ERR_BCR_BELOW_FLOOR`; and the project's `grant_hold_flag` must be
        false, or `ERR_GRANT_ON_HOLD`."  Since this project has no analysis at all, the
        first guard is the only one that can decide.  PRD 3.5 fixes what stays untouched:
        `grant_funder` and `grant_submitted_at` "are all null until the action that
        produces each of them runs".

        Design: Corner/errors/grant_submission_on_an_unprogrammed_project_returns_409
        """
        harbor = create_harbor()
        cycle = create_plan_cycle()
        project = create_screened_project(cycle["id"], harbor["id"])
        assert_fields(
            project,
            {"screening_status": "SCREENED_IN", "program_status": "UNPROGRAMMED"},
            "the screened but unfunded project",
        )

        response = api_client.submit_grant(
            project["id"],
            grant_submission_payload(grant_funder="BRIC"),
            make_project_sponsor_headers(harbor["id"]),
        )

        validate_error(response, ApiErrorId.ERR_PROJECT_NOT_PROGRAMMED.value, 409)
        assert_fields(
            read_project(project["id"]),
            {
                "program_status": "UNPROGRAMMED",
                "grant_funder": None,
                "grant_submitted_at": None,
                "version": project["version"],
            },
            "the project no application touched",
        )


def _certified_levee_case(avoided_loss_annual_cents=3333333, name="Harbor Levee Raise"):
    """A screened levee project with one link and a DRAFT annualized case."""
    context = ranked_asset_context()
    harbor_id = context["harbor"]["id"]
    cycle = create_plan_cycle(required_session_count=0)
    project = create_screened_project(cycle["id"], harbor_id, name=name)
    link = create_asset_link(
        project["id"], harbor_id, context["asset"]["id"], avoided_loss_annual_cents,
        benefit_reaches_disadvantaged=True,
    )
    analysis = create_analysis(
        project["id"], harbor_id, method="ANNUALIZED_EQUIVALENT", discount_rate_bps=None
    )
    context.update(
        {"cycle": cycle, "project": project, "link": link, "analysis": analysis}
    )
    return context


class TestOneCertifiedCasePerProject:
    """A sponsor cannot shop for a second variant once one case is certified."""

    def test_a_second_variant_is_refused_while_one_case_is_certified(self):
        """The certified annualized case blocks a fresh discounted attempt.

        PRD 3.6 lists the guard second in preparation order: "Four conditions guard
        preparation, evaluated in this order: the project's `screening_status` must be
        `SCREENED_IN`, or `ERR_PROJECT_NOT_SCREENED_IN`; no analysis for the project may
        currently sit in `CERTIFIED`, or `ERR_BCA_ALREADY_CERTIFIED`."  The certified
        figures follow PRD 3.6's annualized variant: "`benefit_measure_cents` is the
        exact integer sum of every link's `avoided_loss_annual_cents` — one undiscounted
        year of benefit. `cost_measure_cents` is the capital amount divided by the
        horizon in years and rounded half up to whole cents, plus the capital amount
        multiplied by two percent and rounded half up to whole cents", so 51273600 over
        30 years gives 1709120 plus 1025472, and 3333333 over 2734592 rounds to 1.2190
        with "`grant_eligible` is true exactly when that **rounded** `bcr` is at least
        1.0000".

        Design: Corner/errors/second_analysis_while_one_is_certified_returns_409
        """
        context = _certified_levee_case()
        certified = certify_analysis(context["analysis"]["id"])
        assert_fields(
            certified,
            {
                "status": "CERTIFIED",
                "benefit_measure_cents": 3333333,
                "cost_measure_cents": 2734592,
                "bcr": 1.2190,
                "grant_eligible": True,
            },
            "the certified annualized case",
        )

        response = api_client.create_analysis(
            context["project"]["id"],
            analysis_payload(method="DISCOUNTED_NPV", discount_rate_bps=None),
            make_project_sponsor_headers(context["harbor"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_BCA_ALREADY_CERTIFIED.value, 409)
        rows, meta = validate_paginated(
            api_client.list_analyses(ADMIN(), params={"project_id": context["project"]["id"]})
        )
        assert meta["total_count"] == 1, (
            f"the refused preparation wrote no second row, got {meta['total_count']}"
        )
        assert_fields(
            rows[0],
            {
                "id": context["analysis"]["id"],
                "status": "CERTIFIED",
                "bcr": 1.2190,
                "grant_eligible": True,
                "method": "ANNUALIZED_EQUIVALENT",
            },
            "the only case the project holds",
        )


class TestCertificationRefusesARatioBelowTheFloor:
    """A ratio of 0.9439 cannot become a certified but ineligible case."""

    def test_the_case_below_the_floor_stays_draft_and_the_project_stays_pending(self):
        """Certification is refused outright rather than recording an ineligible case.

        PRD 3.6 gives certification four ordered guards, the last of which is "the `bcr`
        must be at least 1.0000, yielding `ERR_BCR_BELOW_FLOOR`".  The ratio comes from
        PRD 3.6's annualized variant — "`benefit_measure_cents` is the exact integer sum
        of every link's `avoided_loss_annual_cents`" against a cost of 1709120 plus
        1025472 — and PRD 3.6 draws the eligibility line on the same rounded figure:
        "`grant_eligible` is true exactly when that **rounded** `bcr` is at least
        1.0000."  Only success would move the project, since PRD 3.6 says "the owning
        project's `analysis_status` moves `BCA_PENDING → BCA_CERTIFIED`" on success.

        Design: Corner/errors/certifying_an_analysis_below_the_bcr_floor_returns_409
        """
        context = _certified_levee_case(
            avoided_loss_annual_cents=2581083, name="Marginal Levee Raise"
        )
        analysis = context["analysis"]
        assert_fields(
            analysis,
            {
                "benefit_measure_cents": 2581083,
                "cost_measure_cents": 2734592,
                "bcr": 0.9439,
                "grant_eligible": False,
                "status": "DRAFT",
            },
            "the marginal case as prepared",
        )

        response = api_client.certify_analysis(analysis["id"], REVIEWER("reviewer-01"))

        validate_error(response, ApiErrorId.ERR_BCR_BELOW_FLOOR.value, 409)
        assert_fields(
            read_analysis(analysis["id"]),
            {"status": "DRAFT", "certified_at": None, "version": 1},
            "the case certification could not accept",
        )
        assert_fields(
            read_project(context["project"]["id"]),
            {"analysis_status": "BCA_PENDING"},
            "the project still awaiting a usable case",
        )


class TestPactCapacityAndExhaustionAreBothReachable:
    """A peak above the pledge is one failure; an exhausted pact is a different one."""

    @staticmethod
    def _pact_with_an_eight_unit_draw():
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
        big = commit_aid(
            pact["id"], ridge["id"], shared_asset["id"], 8,
            "2026-09-05T00:00:00Z", "2026-09-15T00:00:00Z", pact["version"],
        )
        return {"harbor": harbor, "ridge": ridge, "asset": shared_asset,
                "pact": read_pact(pact["id"]), "big": big}

    def _draw(self, context, units, window_start, window_end, expected_version):
        return api_client.create_commitment(
            context["pact"]["id"],
            commitment_payload(
                context["ridge"]["id"], context["asset"]["id"], units,
                window_start, window_end, expected_version,
            ),
            make_jurisdiction_delegate_headers(context["ridge"]["id"]),
        )

    def test_a_peak_of_eleven_against_a_pledge_of_ten_is_refused(self):
        """Three more units on top of eight breach the pledge at the shared instant.

        PRD 3.9 puts the unit check last of the nine ordered guards: "The peak **unit
        load** must be less than or equal to the pact's `pledged_units`; a peak that
        exceeds the pledge yields `ERR_AID_CAPACITY_EXCEEDED`. A peak landing exactly on
        `pledged_units` is admitted."  The peak itself follows PRD 3.9's procedure: "the
        server takes each distinct `window_start` across the candidate set in ascending
        order and, at each such instant, sums the `committed_units` of every commitment
        in the set whose `window_start` is at or before that instant and whose
        `window_end` is strictly after it; the peak is the largest of those sums", which
        at 2026-09-10 is 8 plus 3.  The concurrency guard cannot be the reason, because
        PRD 3.9 requires only that "The maximum **count** of overlapping commitments at
        any window-start instant must remain strictly below the pact's
        `max_concurrent_commitments`", and two overlapping draws stay below three.

        Design: Corner/errors/pact_capacity_and_exhausted_pact_are_both_triggerable
        """
        context = self._pact_with_an_eight_unit_draw()
        assert_fields(
            context["pact"],
            {"reserved_units": 8, "free_units": 2, "status": "OPEN", "version": 2},
            "the pact after its first draw",
        )

        refused = self._draw(
            context, 3, "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z",
            context["pact"]["version"],
        )

        validate_error(refused, ApiErrorId.ERR_AID_CAPACITY_EXCEEDED.value, 409)
        assert_fields(
            read_pact(context["pact"]["id"]),
            {"reserved_units": 8, "free_units": 2, "status": "OPEN", "version": 2},
            "the pact the refusal left untouched",
        )

    def test_a_peak_landing_exactly_on_the_pledge_exhausts_the_pact(self):
        """Two more units are admitted, and the exhausted pact then refuses everything.

        PRD 3.9 admits the exact landing — "A peak landing exactly on `pledged_units` is
        admitted" — and then re-derives the ledger: "`reserved_units` is set to the
        **peak** concurrent unit load over the pact's `COMMITTED` and `FULFILLED`
        commitments ... and `free_units` becomes `pledged_units` minus `reserved_units`",
        after which "The pact's `status` is then re-derived **in this exact order**:
        `EXPIRED` when the logical clock has reached or passed the pact's `window_end` —
        this temporal check runs *first*, before any capacity consideration ... then
        `EXHAUSTED` when `free_units` is exactly 0; then `OPEN` otherwise."  The third
        guard then rejects the free-window draw: "The pact's `status` must read `OPEN`; a
        pact reading `EXHAUSTED` or `EXPIRED` accepts nothing and yields
        `ERR_PACT_NOT_OPEN`."

        Design: Corner/errors/pact_capacity_and_exhausted_pact_are_both_triggerable
        """
        context = self._pact_with_an_eight_unit_draw()

        accepted = self._draw(
            context, 2, "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z",
            context["pact"]["version"],
        )

        second = validate_success(accepted, 201)
        assert_fields(
            second, {"committed_units": 2, "status": "COMMITTED"}, "the second draw"
        )
        exhausted = read_pact(context["pact"]["id"])
        assert_fields(
            exhausted,
            {"reserved_units": 10, "free_units": 0, "status": "EXHAUSTED", "version": 3},
            "the pact whose pledge is fully taken",
        )

        refused = self._draw(
            context, 1, "2026-09-25T00:00:00Z", "2026-09-30T00:00:00Z",
            exhausted["version"],
        )

        validate_error(refused, ApiErrorId.ERR_PACT_NOT_OPEN.value, 409)
        assert_fields(
            read_pact(context["pact"]["id"]),
            {"reserved_units": 10, "free_units": 0, "status": "EXHAUSTED", "version": 3},
            "the exhausted pact after the free-window attempt",
        )


class TestOpeningARoundNeedsAScreenedProject:
    """The engagement gate can be satisfied while the project gate is not."""

    def test_a_cycle_whose_only_project_is_proposed_cannot_open_its_round(self):
        """required_session_count 0 clears the session gate; screening clears the rest.

        PRD 3.8 orders the three checks: "the cycle must be in `ENGAGEMENT` or
        `REVISION`, or `ERR_PLAN_CYCLE_STATE_INVALID`; the cycle must have at least
        `required_session_count` engagement sessions in `COMPLETED` status, or
        `ERR_ENGAGEMENT_INCOMPLETE` — sessions still `SCHEDULED` and sessions `CANCELLED`
        never count; and the cycle must own at least one adaptation project whose
        `screening_status` is `SCREENED_IN`, or `ERR_NO_SCREENED_PROJECTS`."  On success
        "`round_number` increments by 1 and the cycle's `version` increments by 1."  A
        required session count of zero therefore leaves only the third check able to
        fire, and PRD 3.5's "A score of at least 0.4500 moves the project `PROPOSED →
        SCREENED_IN`" is what satisfies it.

        Design: Corner/errors/open_endorsement_round_without_a_screened_project_returns_409
        """
        harbor = create_harbor()
        cycle = create_plan_cycle(required_session_count=0)
        project = create_project(cycle["id"], harbor["id"])
        engaged = open_engagement(cycle["id"])

        refused = api_client.open_endorsement_round(cycle["id"], ADMIN())

        validate_error(refused, ApiErrorId.ERR_NO_SCREENED_PROJECTS.value, 409)
        assert_fields(
            read_plan_cycle(cycle["id"]),
            {
                "status": "ENGAGEMENT",
                "round_number": 0,
                "version": engaged["version"],
            },
            "the cycle the refusal left in engagement",
        )

        screened = screen_project(project["id"])
        assert_fields(screened, {"screening_status": "SCREENED_IN"}, "the screened project")

        opened = validate_success(api_client.open_endorsement_round(cycle["id"], ADMIN()), 200)

        assert_fields(
            opened,
            {"status": "ENDORSEMENT_ROUND", "round_number": 1, "version": engaged["version"] + 1},
            "the cycle that now has a screened project",
        )
