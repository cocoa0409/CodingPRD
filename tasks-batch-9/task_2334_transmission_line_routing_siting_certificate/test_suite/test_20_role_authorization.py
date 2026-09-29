"""Write authority, role by role, and the two segregation bars that sit beside it.

Each pair here shows the same operation succeeding for the role the contract
names and refused for a role that is otherwise deeply involved in the workflow.
"""

from test_helpers import (
    DEV_NORA,
    ApiErrorId,
    assert_is_null,
    assert_score,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _draft_route_a(api):
    """A project carrying a DRAFT Route A with its three segments, unmapped."""
    ctx = {}
    fx.create_project(api, ctx)
    fx.build_route_a(api, ctx, map_it=False)
    return ctx


class TestConstraintMappingAuthority:
    """Mapping is the analyst's act, and the developer's involvement does not extend."""

    def test_the_route_analyst_runs_constraint_mapping(self, api):
        """PRD §3.2: "**Constraint mapping** is the `RouteAnalyst` operation that turns
        segment ratings into a route-level score, and it is the same operation whether it
        is run for the first time on a `DRAFT` route ... All three carry the same
        preconditions and all three land the route at `CONSTRAINT_MAPPED`."

        Design: Corner/rbac/route_analyst_alone_runs_constraint_mapping
        """
        ctx = _draft_route_a(api)

        route = validate_success(
            api.run_constraint_mapping(
                ctx["routeA"],
                f.constraint_mapping_payload(
                    mapping_note="Desk study plus field-verified segments"
                ),
                fx.ROUTE_ANALYST_HEADERS,
            ),
            expected_status=201,
        )

        assert route["status"] == "CONSTRAINT_MAPPED", (
            f"Mapping lands the corridor at CONSTRAINT_MAPPED, got {route['status']}"
        )
        assert_score(
            route["constraint_score_preliminary"], 67.28, "constraint_score_preliminary"
        )
        assert_score(
            route["constraint_score_certified"], 69.58, "constraint_score_certified"
        )

    def test_the_developer_may_not_run_constraint_mapping(self, api):
        """PRD §2.1: "If `X-User-Role` is not one of the seven role names below, or is a
        valid role that the endpoint does not authorize, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/developer_running_constraint_mapping_unauthorized
        """
        ctx = _draft_route_a(api)

        response = api.run_constraint_mapping(
            ctx["routeA"],
            f.constraint_mapping_payload(mapping_note="Developer-run mapping"),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED, expected_status=403)

        route = fx.read_route(api, ctx["routeA"])
        assert route["status"] == "DRAFT", (
            f"The corridor is still unmapped, got {route['status']}"
        )
        assert_is_null(route, "constraint_score_preliminary", "Route")
        assert_is_null(route, "constraint_score_certified", "Route")


class TestNonconformanceAuthority:
    """Only the independent monitor may record a finding against a condition."""

    def test_the_compliance_monitor_files_a_finding(self, api):
        """PRD §3.9: "A `ComplianceMonitor` **files a nonconformance** against a
        `certificate_id` and a `condition_id`, with a `severity` of `MINOR`, `MAJOR` or
        `SEVERE` and the monitor's field `observation`."

        Design: Corner/rbac/compliance_monitor_alone_files_findings
        """
        ctx = fx.setup_issued_certificate(api)

        finding = validate_success(
            api.create_nonconformance(
                f.nonconformance_payload(
                    ctx["cert"], ctx["cond2"], severity="MINOR",
                    observation="Cultural monitor absent for one shift",
                ),
                fx.COMPLIANCE_MONITOR_HEADERS,
            ),
            expected_status=201,
        )

        assert finding["status"] == "OPEN", (
            f"Findings open at OPEN, got {finding['status']}"
        )
        assert_score(finding["deduction_points"], 4.80, "deduction_points")
        assert fx.read_condition(api, ctx["cond2"])["status"] == "VIOLATED", (
            "The named condition moves ACTIVE to VIOLATED"
        )
        certificate = fx.read_certificate(api, ctx["cert"])
        assert_score(
            certificate["compliance_index_rolling"], 95.20, "compliance_index_rolling"
        )
        assert certificate["posture"] == "ACTIVE", (
            f"95.20 clears both floors, got {certificate['posture']}"
        )

    def test_the_developer_may_not_file_a_finding(self, api):
        """PRD §2.1: "If `X-User-Role` is not one of the seven role names below, or is a
        valid role that the endpoint does not authorize, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/developer_filing_a_nonconformance_unauthorized
        """
        ctx = fx.setup_issued_certificate(api)

        response = api.create_nonconformance(
            f.nonconformance_payload(
                ctx["cert"], ctx["cond2"], severity="MINOR",
                observation="Self-reported lapse",
            ),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED, expected_status=403)

        _, meta = validate_paginated(
            api.list_nonconformances(
                fx.COMPLIANCE_MONITOR_HEADERS, {"certificate_id": ctx["cert"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"A self-reported finding writes nothing, got {meta['total_count']}"
        )
        assert fx.read_condition(api, ctx["cond2"])["status"] == "ACTIVE", (
            "The condition is untouched"
        )
        assert_score(
            fx.read_certificate(api, ctx["cert"])["compliance_index_rolling"],
            100.00, "compliance_index_rolling",
        )


class TestWaiverAuthority:
    """A waiver is relief granted on the record, not something the holder takes."""

    def test_the_developer_may_not_waive_a_condition(self, api):
        """PRD §3.7: "`CommissionStaff` may **waive** a condition on the record,
        supplying a `waiver_reason`. A waiver moves the condition `ACTIVE → WAIVED`,
        which is terminal."

        Design: Corner/rbac/condition_waiver_by_the_developer_unauthorized
        """
        ctx = fx.setup_issued_certificate(api)

        response = api.waive_certificate_condition(
            ctx["cond3"], f.waiver_payload(waiver_reason="Schedule pressure"),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED, expected_status=403)

        condition = fx.read_condition(api, ctx["cond3"])
        assert condition["status"] == "ACTIVE", (
            f"The crew-limit condition still binds, got {condition['status']}"
        )
        assert condition["crew_limit"] == 9, (
            f"Its ceiling is unchanged, got {condition['crew_limit']}"
        )
        assert_is_null(condition, "waiver_reason", "CertificateCondition")


class TestFederalPermitAuthority:
    """The permit dimension belongs to the federal officer alone."""

    def test_commission_staff_may_not_act_on_a_federal_permit(self, api):
        """PRD §3.3: "Wherever a corridor crosses federal land or navigable water, a
        `FederalPermitOfficer` drives the segment's permit dimension by recording an
        `action` of `APPLY`, `ISSUE` or `DENY`, optionally with an `agency` and a
        `determination_note`."

        Design: Corner/rbac/federal_permit_action_by_commission_staff_unauthorized
        """
        ctx = _draft_route_a(api)

        response = api.record_federal_permit_action(
            ctx["seg2"],
            f.federal_permit_action_payload(action="APPLY", agency="USACE"),
            fx.COMMISSION_STAFF_HEADERS,
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED, expected_status=403)

        segment = fx.read_segment(api, ctx["seg2"])
        assert segment["federal_permit_status"] == "REQUIRED", (
            f"The crossing still needs its permit, got "
            f"{segment['federal_permit_status']}"
        )
        assert_is_null(segment, "federal_permit_agency", "RouteSegment")


class TestDecisionAuthority:
    """The examiner builds the record; the commission decides on it."""

    def test_the_hearing_examiner_may_not_decide_the_docket(self, api):
        """PRD §3.7: "`CommissionStaff` record the commission's **decision** with an
        `outcome` of `GRANT` or `DENY`."

        Design: Corner/rbac/examiner_deciding_the_docket_unauthorized
        """
        ctx = fx.setup_closed_record(api)

        response = api.record_decision(
            ctx["app"],
            f.decision_payload(
                outcome="GRANT", certified_route_id=ctx["routeA"],
                eminent_domain_authorized=True, mitigation_base_cents=480_000_000,
                conditions=[
                    {
                        "code": "CUL-MON-9",
                        "category": "CULTURAL",
                        "constraint_kind": "MONITORING",
                        "severity_weight": 2,
                    }
                ],
            ),
            fx.HEARING_EXAMINER_HEADERS,
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED, expected_status=403)

        application = fx.read_application(api, ctx["app"])
        assert application["review_status"] == "ACCEPTED", (
            f"The merits dimension is untouched, got {application['review_status']}"
        )
        assert application["record_status"] == "RECORD_CLOSED", (
            f"The record dimension is untouched, got {application['record_status']}"
        )
        _, meta = validate_paginated(
            api.list_certificates(
                fx.COMMISSION_STAFF_HEADERS, {"application_id": ctx["app"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"No certificate is minted, got {meta['total_count']}"
        )
        assert fx.read_project(api, ctx)["stage"] == "APPLICATION_FILED", (
            "The project cannot reach CERTIFICATED without an order"
        )


class TestOwnershipAuthority:
    """The one entity-backed identity: a landowner answers only their own offer."""

    def test_a_landowner_may_not_answer_another_landowners_offer(self, api):
        """PRD §3.8: "The `Landowner` — and it must be the tract's own landowner, per
        §2.1 — **responds** with a `response` of `ACCEPT` or `REJECT` and an optional
        `response_note`, and may only do so while the tract sits at `OFFERED`."

        Design: Corner/rbac/landowner_answering_another_landowners_offer_unauthorized
        """
        ctx = fx.setup_issued_certificate(api)
        fx.create_landowner(api, ctx, "lo1")
        fx.create_landowner(
            api, ctx, "lo2", name="Ivor Nance", email="ivor@example.com",
            mailing_address="44 Boone Pike, Boone KY",
        )
        fx.create_tract(api, ctx, key="tract1", landowner_key="lo1")
        fx.extend_offer(api, ctx, key="tract1")

        response = api.respond_to_offer(
            ctx["tract1"],
            f.offer_response_payload(
                response="ACCEPT", response_note="Accepted by a neighbour"
            ),
            fx.make_landowner_headers(ctx["lo2"]),
        )
        validate_error(response, ApiErrorId.NOT_RESOURCE_OWNER, expected_status=403)

        tract = fx.read_tract(api, ctx["tract1"])
        assert tract["acquisition_status"] == "OFFERED", (
            f"The offer is still outstanding, got {tract['acquisition_status']}"
        )
        assert_is_null(tract, "agreed_compensation_cents", "EasementTract")
        assert tract["committed_cents"] == 0, (
            f"Nothing was committed, got {tract['committed_cents']}"
        )
        assert fx.read_project(api, ctx)["easement_committed_cents"] == 0, (
            "The project's exposure roll-up is untouched"
        )


class TestFilingSegregation:
    """The author of the need case may not be the one who files on it."""

    def test_the_study_author_may_not_file_the_application(self, api):
        """PRD §3.5: "the filer must not be the study's author
        (`ERR_SELF_CERTIFICATION`, HTTP 403)."

        Design: Corner/rbac/application_filed_by_the_study_author_rejected
        """
        ctx = fx.setup_nominated_routes(api)

        response = api.create_application(
            f.application_payload(
                ctx["proj"], ctx["study"], ctx["routeA"],
                docket_number="EL-2026-0900", filing_fee_cents=2_500_000,
            ),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.SELF_CERTIFICATION, expected_status=403)

        study = fx.read_study(api, ctx["study"])
        assert study["authored_by_user_id"] == DEV_NORA, (
            f"The acting developer is the recorded author, got "
            f"{study['authored_by_user_id']!r}"
        )
        _, meta = validate_paginated(
            api.list_applications(
                fx.COMMISSION_STAFF_HEADERS, {"project_id": ctx["proj"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"No application row is written, got {meta['total_count']}"
        )
        assert fx.read_project(api, ctx)["stage"] == "ROUTING", (
            "The project stays in ROUTING because the filing never landed"
        )
