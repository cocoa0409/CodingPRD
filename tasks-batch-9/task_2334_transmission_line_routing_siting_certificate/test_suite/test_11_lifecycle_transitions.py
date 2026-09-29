"""Opening states, legitimate transitions, refused ones and terminal lockdown.

Each dimension is exercised where it opens, where it is allowed to move, and
where the service refuses to move it.
"""

from test_helpers import (
    ApiErrorId,
    assert_is_null,
    assert_score,
    assert_timestamp_equals,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestRouteOpeningState:
    """A route opens as an unmapped draft."""

    def test_new_route_opens_as_an_unmapped_draft(self, api):
        """PRD §3.2: "Routes open in `status` `DRAFT` and travel through
        `CONSTRAINT_MAPPED`, `PUBLISHED_FOR_COMMENT`, `REFINING` and `NOMINATED`
        before reaching one of the two terminal outcomes, `CERTIFIED` or
        `REJECTED`."

        Design: Corner/state_machines/new_route_starts_in_draft_status
        """
        ctx = {}
        fx.create_project(api, ctx)

        route = validate_success(
            api.create_route(
                f.route_payload(ctx["proj"], label="Route A - river crossing",
                                kind="PROPOSED"),
                fx.ROUTE_ANALYST_HEADERS,
            ),
            expected_status=201,
        )

        assert route["status"] == "DRAFT", (
            f"A new route opens in DRAFT, got {route['status']}"
        )
        assert route["refinement_round"] == 0, (
            f"No refinement cycle has run, got {route['refinement_round']}"
        )
        assert_is_null(route, "constraint_score_certified", "Route")
        assert_is_null(route, "constraint_score_preliminary", "Route")
        assert route["open_house_held_count"] == 0, (
            f"No open house has been recorded, got {route['open_house_held_count']}"
        )
        assert fx.read_project(api, ctx)["stage"] == "PLANNING", (
            "No study on this project is certified yet, so the project stays in "
            "PLANNING"
        )


class TestStudyCertificationOutcomes:
    """The certification gate has two successful outcomes and a way back."""

    def test_margin_below_the_threshold_lands_the_study_insufficient(self, api):
        """PRD §3.1: "A ratio at or above the threshold moves the study
        `ALTERNATIVES_ANALYZED → CERTIFIED_SUFFICIENT`; a ratio below it moves the
        study `ALTERNATIVES_ANALYZED → INSUFFICIENT`."

        Design: Corner/state_machines/study_certification_below_threshold_marks_insufficient
        """
        ctx = fx.build_need_case(api)
        lean = get_success_data(
            api.create_alternative(
                f.alternative_payload(
                    ctx["study"], kind="NON_TRANSMISSION",
                    description="Lean storage portfolio",
                    capex_cents=45_000_000_000, deliverable_mw=200,
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )
        get_success_data(
            api.screen_alternative(
                ctx["alt1"], f.screening_payload(), fx.ROUTE_ANALYST_HEADERS
            )
        )
        get_success_data(
            api.screen_alternative(
                lean["id"],
                f.screening_payload(screen_reason="Credible non-wires portfolio"),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )

        study = validate_success(
            api.certify_study_sufficiency(
                ctx["study"],
                f.sufficiency_certification_payload(
                    attestation_note="Independent review of the need case"
                ),
                fx.DEVELOPER_CERTIFIER_HEADERS,
            ),
            expected_status=201,
        )

        assert_score(
            lean["levelized_cost_cents_per_mw"], 225000000.00,
            "levelized_cost_cents_per_mw",
        )
        assert study["status"] == "INSUFFICIENT", (
            f"A margin of 1.1250 fails the 1.1500 threshold, got {study['status']}"
        )
        assert study["selected_nta_alternative_id"] == lean["id"], (
            "The only eligible non-wires candidate is still selected and recorded"
        )

    def test_screening_a_third_alternative_reopens_an_insufficient_study(self, api):
        """PRD §3.1: "a further screen-in against a study sitting at `INSUFFICIENT`
        carries it back `INSUFFICIENT → ALTERNATIVES_ANALYZED`. That second path
        also wipes the stale arithmetic: `need_margin_ratio`, `benefit_ratio`,
        `transmission_levelized_cents_per_mw`, `selected_nta_alternative_id` and
        `certified_by_user_id` all revert to null."

        Design: Corner/state_machines/insufficient_study_returns_to_alternatives_analyzed_on_new_screening
        """
        ctx = fx.build_need_case(api)
        lean = get_success_data(
            api.create_alternative(
                f.alternative_payload(
                    ctx["study"], kind="NON_TRANSMISSION",
                    description="Lean storage portfolio",
                    capex_cents=45_000_000_000, deliverable_mw=200,
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )
        for alternative_id in (ctx["alt1"], lean["id"]):
            get_success_data(
                api.screen_alternative(
                    alternative_id, f.screening_payload(), fx.ROUTE_ANALYST_HEADERS
                )
            )
        get_success_data(
            api.certify_study_sufficiency(
                ctx["study"],
                f.sufficiency_certification_payload(
                    attestation_note="First attempt on the lean portfolio"
                ),
                fx.DEVELOPER_CERTIFIER_HEADERS,
            )
        )
        hybrid = get_success_data(
            api.create_alternative(
                f.alternative_payload(
                    ctx["study"], kind="HYBRID",
                    description="Storage plus reconductoring",
                    capex_cents=60_000_000_000, deliverable_mw=200,
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )

        screened = validate_success(
            api.screen_alternative(
                hybrid["id"],
                f.screening_payload(screen_reason="Hybrid portfolio now credible"),
                fx.ROUTE_ANALYST_HEADERS,
            ),
            expected_status=201,
        )

        assert screened["screening_status"] == "SCREENED_IN", (
            f"The third alternative is screened in, got {screened['screening_status']}"
        )
        assert_score(
            hybrid["levelized_cost_cents_per_mw"], 300000000.00,
            "levelized_cost_cents_per_mw",
        )
        study = fx.read_study(api, ctx["study"])
        assert study["alternatives_screened_in_count"] == 3, (
            f"Three alternatives are now screened in, got "
            f"{study['alternatives_screened_in_count']}"
        )
        assert study["status"] == "ALTERNATIVES_ANALYZED", (
            "INSUFFICIENT is not terminal, so the study returns to "
            f"ALTERNATIVES_ANALYZED, got {study['status']}"
        )
        for field in ("need_margin_ratio", "benefit_ratio", "selected_nta_alternative_id"):
            assert_is_null(study, field, "PlanningStudy")


class TestRefusedRouteTransitions:
    """Publication and mapping both refuse a route that is not ready."""

    def test_publishing_a_draft_route_has_no_transition(self, api):
        """PRD §3.4: "Publication moves the route `CONSTRAINT_MAPPED →
        PUBLISHED_FOR_COMMENT` and sets `comment_window_closes_at` to the logical
        clock reading plus that many days."

        Design: Corner/state_machines/route_publication_from_draft_returns_invalid_state
        """
        ctx = {}
        fx.create_project(api, ctx)
        fx.create_route(api, ctx, key="routeA")
        for index, spec in enumerate(fx.ROUTE_A_SEGMENTS[:2], start=1):
            fx.add_segment(api, ctx, "routeA", f"seg{index}", **dict(spec))

        response = api.publish_route(
            ctx["routeA"], f.publication_payload(comment_window_days=30),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_STATE, expected_status=409)

        route = fx.read_route(api, ctx["routeA"])
        assert route["status"] == "DRAFT", (
            f"The refused publication leaves the route at DRAFT, got {route['status']}"
        )
        assert_is_null(route, "comment_window_closes_at", "Route")

    def test_mapping_a_single_segment_corridor_is_refused(self, api):
        """PRD §3.2: "Mapping requires at least two segments whose `sequence_index`
        values form a contiguous run from 1 to N with no gaps and no holes; anything
        else is refused with `ERR_SEGMENT_SEQUENCE_GAP` (HTTP 422)."

        Design: Corner/state_machines/constraint_mapping_with_single_segment_rejected
        """
        ctx = {}
        fx.create_project(api, ctx)
        fx.create_route(api, ctx, key="routeA")
        fx.add_segment(api, ctx, "routeA", "seg1", **dict(fx.ROUTE_A_SEGMENTS[0]))

        response = api.run_constraint_mapping(
            ctx["routeA"],
            f.constraint_mapping_payload(mapping_note="Premature mapping attempt"),
            fx.ROUTE_ANALYST_HEADERS,
        )
        validate_error(response, ApiErrorId.SEGMENT_SEQUENCE_GAP, expected_status=422)

        route = fx.read_route(api, ctx["routeA"])
        assert route["status"] == "DRAFT", (
            f"The refused mapping leaves the route at DRAFT, got {route['status']}"
        )
        assert_is_null(route, "constraint_score_preliminary", "Route")
        assert_is_null(route, "constraint_score_certified", "Route")


class TestAlternateRouteNomination:
    """An alternate corridor takes the short path to NOMINATED."""

    def test_alternate_route_nominates_straight_out_of_constraint_mapped(self, api):
        """PRD §3.5: "An `ALTERNATE` route is nominated out of `CONSTRAINT_MAPPED`,
        and only the density gate applies — the publication, comment-window,
        open-house and material-comment gates are all specific to proposed
        corridors."

        Design: Corner/state_machines/alternate_route_nomination_skips_the_comment_window
        """
        ctx = fx.build_certified_study(api)
        fx.build_route_a(api, ctx)
        fx.build_route_b(api, ctx, nominate=False)

        route = validate_success(
            api.nominate_route(
                ctx["routeB"],
                f.nomination_payload(nomination_note="Alternate route for the filing"),
                fx.DEVELOPER_HEADERS,
            ),
            expected_status=201,
        )

        assert route["status"] == "NOMINATED", (
            f"The alternate corridor is nominated, got {route['status']}"
        )
        assert_score(route["constraint_score_certified"], 17.48, "constraint_score_certified")
        assert_score(
            route["constraint_score_preliminary"], 17.48, "constraint_score_preliminary"
        )
        assert_score(route["total_miles"], 12.0, "total_miles")
        assert_score(
            route["constraint_density_certified"], 1.46, "constraint_density_certified"
        )
        assert_is_null(route, "comment_window_closes_at", "Route")


class TestDocketDimensionSideEffects:
    """One write moving two dimensions, and the caps that stop the loop."""

    def test_accepting_the_filing_opens_the_scheduling_record(self, api):
        """PRD §3.6: "it moves the application `FILED → ACCEPTED` on the review
        dimension and simultaneously `NOT_OPENED → SCHEDULING` on the record
        dimension, and it increments the application's `version` by 1."

        Design: Corner/state_machines/sufficiency_review_accept_opens_the_scheduling_record
        """
        ctx = fx.setup_filed_application(api)

        application = validate_success(
            api.review_application_sufficiency(
                ctx["app"], f.sufficiency_review_payload(outcome="ACCEPT"),
                fx.COMMISSION_STAFF_HEADERS,
            ),
            expected_status=201,
        )

        assert application["review_status"] == "ACCEPTED", (
            f"The merits dimension moves FILED -> ACCEPTED, got "
            f"{application['review_status']}"
        )
        assert application["record_status"] == "SCHEDULING", (
            f"The record dimension moves NOT_OPENED -> SCHEDULING in the same write, "
            f"got {application['record_status']}"
        )
        assert_timestamp_equals(application["filed_at"], "2026-08-31T00:00:00Z", "filed_at")
        assert_timestamp_equals(
            application["decision_deadline_at"], "2027-08-31T00:00:00Z",
            "decision_deadline_at",
        )
        assert application["suspension_days"] == 0, (
            f"No statutory suspension has attached, got {application['suspension_days']}"
        )
        assert application["version"] == 2, (
            f"The acceptance increments the application version to 2, got "
            f"{application['version']}"
        )
        assert fx.read_project(api, ctx)["stage"] == "APPLICATION_FILED", (
            "The project sits at APPLICATION_FILED from the filing onward"
        )

    def test_third_amendment_is_refused_by_the_round_cap(self, api):
        """PRD §3.6: "An amendment is capped: an application whose
        `amendment_round` has already reached 2 is refused with
        `ERR_AMENDMENT_LIMIT_REACHED` (HTTP 409)."

        Design: Corner/state_machines/third_amendment_beyond_round_limit_rejected
        """
        ctx = fx.setup_filed_application(api)
        fx.review_application(
            api, ctx, outcome="REJECT",
            deficiency_note="Alternate route impact assessment missing",
        )
        fx.amend_application(api, ctx, summary="Impact assessment added")
        fx.review_application(
            api, ctx, outcome="REJECT", deficiency_note="Cultural survey still unsigned",
        )
        fx.amend_application(api, ctx, summary="Signed cultural survey attached")
        fx.review_application(
            api, ctx, outcome="REJECT", deficiency_note="Landowner notice list incomplete",
        )

        response = api.amend_application(
            ctx["app"],
            f.amendment_payload(
                ctx["app_version"], amendment_summary="Notice list completed"
            ),
            fx.DEVELOPER_FILER_HEADERS,
        )
        validate_error(response, ApiErrorId.AMENDMENT_LIMIT_REACHED, expected_status=409)

        application = fx.read_application(api, ctx["app"])
        assert application["review_status"] == "DEFICIENT", (
            f"The refused amendment leaves the filing DEFICIENT, got "
            f"{application['review_status']}"
        )
        assert application["amendment_round"] == 2, (
            f"The cap holds the round at 2, got {application['amendment_round']}"
        )
        assert application["version"] == 6, (
            "Three reviews and two amendments each incremented the version, so it "
            f"stands at 6, got {application['version']}"
        )


class TestTerminalStateLockdown:
    """A ruled petition and an unfinished certificate both refuse to move."""

    def test_ruling_twice_on_a_denied_petition_reports_terminal_state(self, api):
        """PRD §3.6: "Denying requires a reason and moves the petition `PETITIONED →
        DENIED`. Both are terminal."

        Design: Corner/state_machines/second_ruling_on_a_denied_intervention_returns_terminal_state
        """
        ctx = fx.setup_accepted_application(api)
        fx.create_landowner(api, ctx, "lo1")
        fx.petition_to_intervene(api, ctx, "int1", landowner_key="lo1")
        fx.rule_on_petition(
            api, ctx, "int1", ruling="DENY",
            reason="No direct property interest shown",
        )

        response = api.rule_on_intervention(
            ctx["int1"],
            f.intervention_ruling_payload(
                ruling="GRANT", ruling_reason="Reconsidered on the papers"
            ),
            fx.COMMISSION_STAFF_HEADERS,
        )
        validate_error(response, ApiErrorId.TERMINAL_STATE, expected_status=409)

        intervention = fx.read_intervention(api, ctx["int1"])
        assert intervention["status"] == "DENIED", (
            f"The petition stays DENIED, got {intervention['status']}"
        )
        assert intervention["ruling_reason"] == "No direct property interest shown", (
            f"The first ruling's reason is preserved, got "
            f"{intervention['ruling_reason']!r}"
        )
        application = fx.read_application(api, ctx["app"])
        assert application["record_status"] == "SCHEDULING", (
            f"A denied petition never advances the record, got "
            f"{application['record_status']}"
        )
        assert application["party_count"] == 0, (
            f"A denial adds no party to the docket, got {application['party_count']}"
        )

    def test_closeout_with_every_segment_still_pending_is_refused(self, api):
        """PRD §3.9: "every segment on the certified route must have reached
        `construction_state` `COMPLETE` (`ERR_SEGMENTS_INCOMPLETE`, HTTP 409)".

        Design: Corner/state_machines/certificate_closeout_with_incomplete_segments_rejected
        """
        ctx = fx.setup_issued_certificate(api)

        response = api.close_out_certificate(
            ctx["cert"], f.closeout_payload(closeout_note="Premature closeout attempt"),
            fx.COMMISSION_STAFF_HEADERS,
        )
        validate_error(response, ApiErrorId.SEGMENTS_INCOMPLETE, expected_status=409)

        certificate = fx.read_certificate(api, ctx["cert"])
        assert certificate["status"] == "ISSUED", (
            f"The refused closeout leaves the certificate ISSUED, got "
            f"{certificate['status']}"
        )
        assert_score(
            certificate["compliance_index_cumulative"], 100.00,
            "compliance_index_cumulative",
        )
        assert certificate["posture"] == "ACTIVE", (
            f"Posture was never the problem, got {certificate['posture']}"
        )
        assert fx.read_project(api, ctx)["stage"] == "CERTIFICATED", (
            "The project stays at CERTIFICATED because nothing was energized"
        )


class TestFederalPermitDenialCascade:
    """A denial on one segment suspends only that segment's work."""

    def test_denying_the_crossing_permit_suspends_the_scheduled_activity(self, api):
        """PRD §3.3: "A denial is a cascade origin: every construction activity on
        that segment whose status is `SCHEDULED` or `IN_PROGRESS` is moved to
        `SUSPENDED` with `suspension_reason` recorded as `FEDERAL_PERMIT_DENIED`,
        and the segment's `committed_crew_count` is deliberately left unchanged,
        because a suspended activity still occupies its crew slots."

        Design: Corner/state_machines/federal_permit_denial_suspends_the_scheduled_activity
        """
        ctx = fx.setup_issued_certificate(api)
        fx.schedule_activity(
            api, ctx, key="act2", segment_key="seg2", activity_kind="FOUNDATION",
            crew_count=4,
        )
        fx.apply_for_federal_permit(api, ctx, segment_key="seg2", agency="USACE")

        segment = validate_success(
            api.record_federal_permit_action(
                ctx["seg2"],
                f.federal_permit_action_payload(
                    action="DENY", agency=None,
                    determination_note="Crossing alignment not permittable as filed",
                ),
                fx.FEDERAL_PERMIT_OFFICER_HEADERS,
            ),
            expected_status=201,
        )

        assert segment["federal_permit_status"] == "DENIED", (
            f"The permit dimension moves APPLIED -> DENIED, got "
            f"{segment['federal_permit_status']}"
        )
        assert segment["federal_permit_agency"] == "USACE", (
            f"The agency recorded at application survives the denial, got "
            f"{segment['federal_permit_agency']!r}"
        )
        assert segment["construction_state"] == "PENDING", (
            "The segment was never ACTIVE, so there is nothing to halt, got "
            f"{segment['construction_state']}"
        )
        assert segment["committed_crew_count"] == 4, (
            "A suspended activity keeps its crew slots, got "
            f"{segment['committed_crew_count']}"
        )
        activity = fx.read_activity(api, ctx["act2"])
        assert activity["status"] == "SUSPENDED", (
            f"The scheduled activity on the denied segment is suspended, got "
            f"{activity['status']}"
        )
        assert activity["suspension_reason"] == "FEDERAL_PERMIT_DENIED", (
            f"The suspension reason names the permit denial, got "
            f"{activity['suspension_reason']!r}"
        )
        certificate = fx.read_certificate(api, ctx["cert"])
        assert certificate["posture"] == "ACTIVE", (
            f"A permit denial does not touch certificate posture, got "
            f"{certificate['posture']}"
        )
        assert_score(
            certificate["compliance_index_rolling"], 100.00, "compliance_index_rolling"
        )
