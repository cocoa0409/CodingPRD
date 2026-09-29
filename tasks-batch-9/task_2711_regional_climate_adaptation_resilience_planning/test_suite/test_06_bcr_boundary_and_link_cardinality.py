"""The grant floor is drawn on the rounded ratio, and a case needs one link."""

from test_helpers import (
    ADMIN,
    REVIEWER,
    ApiErrorId,
    analysis_payload,
    api_client,
    assert_fields,
    certify_analysis,
    create_analysis,
    create_asset_link,
    make_project_sponsor_headers,
    create_screened_retrofit_project,
    read_analysis,
    read_project,
    screened_retrofit_context,
    validate_error,
    validate_paginated,
    validate_success,
)

COST_MEASURE_CENTS = 2118960


class TestBcrRoundingDecidesTheGrantFloor:
    """One cent of benefit either side of the rounding line changes the verdict."""

    @staticmethod
    def _three_cases_straddling_the_rounding_line():
        context = screened_retrofit_context(project_overrides={"name": "Retrofit At Floor"})
        harbor_id = context["harbor"]["id"]
        cases = {}
        specifications = (
            ("exact", context["project"], 2118960),
            ("edge", None, 2118855),
            ("under", None, 2118854),
        )
        names = {
            "edge": "Retrofit One Cent Above The Rounding Line",
            "under": "Retrofit One Cent Below The Rounding Line",
        }
        for key, existing_project, avoided_loss in specifications:
            project = existing_project or create_screened_retrofit_project(
                context["cycle"]["id"], harbor_id, name=names[key]
            )
            create_asset_link(
                project["id"], harbor_id, context["asset"]["id"], avoided_loss,
                benefit_reaches_disadvantaged=True,
            )
            analysis = create_analysis(
                project["id"], harbor_id, method="ANNUALIZED_EQUIVALENT", discount_rate_bps=700
            )
            cases[key] = {"project": project, "analysis": analysis}
        return context, cases

    def test_a_quotient_of_point_nine_nine_nine_nine_five_rounds_up_and_certifies(self):
        """Both the exact case and the case one cent under it reach bcr 1.0000.

        PRD 3.6: "In both cases `bcr` is `benefit_measure_cents` divided by
        `cost_measure_cents`, rounded half up to exactly 4 fractional digits, and
        `grant_eligible` is true exactly when that **rounded** `bcr` is at least
        1.0000. A case that computes to 0.99995 before rounding is therefore
        eligible, because it rounds to 1.0000."  2118855 divided by 2118960 is
        0.99995004..., so the rounded ratio clears the floor and PRD 3.6's fourth
        certification guard — "the `bcr` must be at least 1.0000, yielding
        `ERR_BCR_BELOW_FLOOR`" — is satisfied.

        Design: Difficulty/boundary_precision_check/bcr_rounded_to_four_places_decides_the_grant_floor
        """
        _, cases = self._three_cases_straddling_the_rounding_line()

        certify_analysis(cases["exact"]["analysis"]["id"])
        certify_analysis(cases["edge"]["analysis"]["id"])

        assert_fields(
            read_analysis(cases["exact"]["analysis"]["id"]),
            {
                "benefit_measure_cents": 2118960,
                "cost_measure_cents": COST_MEASURE_CENTS,
                "bcr": 1.0000,
                "grant_eligible": True,
                "status": "CERTIFIED",
            },
            "the case sitting exactly on the floor",
        )
        assert_fields(
            read_analysis(cases["edge"]["analysis"]["id"]),
            {
                "benefit_measure_cents": 2118855,
                "cost_measure_cents": COST_MEASURE_CENTS,
                "bcr": 1.0000,
                "grant_eligible": True,
                "status": "CERTIFIED",
            },
            "the case that only the rounding rescues",
        )
        assert_fields(
            read_project(cases["exact"]["project"]["id"]),
            {"analysis_status": "BCA_CERTIFIED"},
            "the project on the floor",
        )
        assert_fields(
            read_project(cases["edge"]["project"]["id"]),
            {"analysis_status": "BCA_CERTIFIED"},
            "the project rescued by the rounding",
        )

    def test_one_further_cent_quantizes_below_the_floor_and_is_refused(self):
        """A benefit of 2118854 quantizes to 0.9999 and cannot be certified.

        PRD 2.6 fixes the precision: "Computed magnitudes are rounded half up to
        their declared precision — `vulnerability_score` and `consequence_score` to 2
        fractional digits, `indicator_attainment_pct` to 2, and `screen_score`, `bcr`
        and `priority_score` to 4."  PRD 3.6 then refuses the case: "the `bcr` must
        be at least 1.0000, yielding `ERR_BCR_BELOW_FLOOR`", and only a successful
        certification moves the project, since on success "the owning project's
        `analysis_status` moves `BCA_PENDING → BCA_CERTIFIED`".

        Design: Difficulty/boundary_precision_check/bcr_rounded_to_four_places_decides_the_grant_floor
        """
        _, cases = self._three_cases_straddling_the_rounding_line()
        analysis_id = cases["under"]["analysis"]["id"]

        assert_fields(
            read_analysis(analysis_id),
            {
                "benefit_measure_cents": 2118854,
                "cost_measure_cents": COST_MEASURE_CENTS,
                "bcr": 0.9999,
                "grant_eligible": False,
            },
            "the case one cent below the rounding line",
        )

        response = api_client.certify_analysis(analysis_id, REVIEWER("reviewer-01"))

        validate_error(response, ApiErrorId.ERR_BCR_BELOW_FLOOR.value, 409)
        assert_fields(
            read_analysis(analysis_id), {"status": "DRAFT"}, "the refused case"
        )
        assert_fields(
            read_project(cases["under"]["project"]["id"]),
            {"analysis_status": "BCA_PENDING"},
            "the project whose case was refused",
        )


class TestAnalysisNeedsAtLeastOneLink:
    """The benefit summation refuses an empty link set and accepts exactly one.

    PRD 3.6 states the guard order for preparation: "Four conditions guard
    preparation, evaluated in this order: the project's `screening_status` must be
    `SCREENED_IN`, or `ERR_PROJECT_NOT_SCREENED_IN`; no analysis for the project may
    currently sit in `CERTIFIED`, or `ERR_BCA_ALREADY_CERTIFIED`; the project must
    have at least one linked asset, or `ERR_NO_LINKED_ASSETS`; and every lifeline
    asset reachable through the project's links must sit in `criticality_status`
    `RANKED`, or `ERR_ASSET_RANKING_REQUIRED`."
    """

    def test_preparation_is_refused_while_the_project_has_no_links(self):
        """At link count zero the case cannot be opened and the project does not move.

        PRD 3.6: "the project must have at least one linked asset, or
        `ERR_NO_LINKED_ASSETS`".  Because the ranked asset is already in place, PRD
        3.6's fourth guard — "every lifeline asset reachable through the project's
        links must sit in `criticality_status` `RANKED`, or
        `ERR_ASSET_RANKING_REQUIRED`" — cannot be the reason for the refusal.

        Design: Difficulty/boundary_precision_check/analysis_requires_at_least_one_asset_link
        """
        context = screened_retrofit_context(project_overrides={"name": "Harbor Pump Retrofit"})
        project_id = context["project"]["id"]

        response = api_client.create_analysis(
            project_id,
            analysis_payload(method="ANNUALIZED_EQUIVALENT", discount_rate_bps=700),
            make_project_sponsor_headers(context["harbor"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_NO_LINKED_ASSETS.value, 409)
        assert_fields(
            read_project(project_id),
            {"analysis_status": "NOT_ANALYZED"},
            "the project whose case was never opened",
        )
        rows, _meta = validate_paginated(
            api_client.list_analyses(ADMIN(), params={"project_id": project_id})
        )
        assert rows == [], (
            "a refused preparation must not leave a benefit-cost analysis row behind, "
            f"found {rows}"
        )

    def test_the_first_link_makes_the_identical_request_succeed(self):
        """At link count exactly one the same payload mints the case.

        PRD 3.6: "The calculation itself walks the project's links in
        `link_sequence` ascending order and produces four fields:
        `benefit_measure_cents`, `cost_measure_cents`, `bcr` and `grant_eligible`."
        The horizon is the project's own service life, since PRD 3.6 lists among the
        common inputs "the horizon in years, which is the project's
        `service_life_years`", and PRD 3.6 leaves a fresh case awaiting review, so
        the project reads `BCA_PENDING`.

        Design: Difficulty/boundary_precision_check/analysis_requires_at_least_one_asset_link
        """
        context = screened_retrofit_context(project_overrides={"name": "Harbor Pump Retrofit"})
        project_id = context["project"]["id"]
        harbor_id = context["harbor"]["id"]
        create_asset_link(
            project_id, harbor_id, context["asset"]["id"], 2118960,
            benefit_reaches_disadvantaged=True,
        )

        response = api_client.create_analysis(
            project_id,
            analysis_payload(method="ANNUALIZED_EQUIVALENT", discount_rate_bps=700),
            make_project_sponsor_headers(harbor_id),
        )

        analysis = validate_success(response, 201)
        assert_fields(
            analysis,
            {
                "benefit_measure_cents": 2118960,
                "cost_measure_cents": COST_MEASURE_CENTS,
                "bcr": 1.0000,
                "analysis_horizon_years": 25,
                "status": "DRAFT",
            },
            "the case the first link made possible",
        )
        assert_fields(
            read_project(project_id),
            {"analysis_status": "BCA_PENDING"},
            "the project now awaiting review",
        )
