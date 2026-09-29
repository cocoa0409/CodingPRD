"""Rules that guard the need case: references, divisions and the certification gate.

Every rejection here leaves the study exactly where it stood, with its four
computed figures still unwritten.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_is_null,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestAlternativeReferences:
    """A body reference that resolves to nothing, and a division that cannot exist."""

    def test_alternative_naming_a_study_that_does_not_exist_is_not_found(self, api):
        """PRD §2.5: "References supplied inside a request body are resolved
        separately and report `ERR_REFERENCE_NOT_FOUND` (HTTP 404). This covers
        `project_id`, `study_id`, `route_id`, `segment_id`, `landowner_id`,
        `application_id`, `certificate_id`, `condition_id`, `activity_id` and
        `certified_route_id` wherever a write endpoint accepts them."

        Design: Corner/validations/alternative_on_unknown_study_id_not_found
        """
        fx.create_project(api, {})

        response = api.create_alternative(
            f.alternative_payload(
                NON_EXISTENT_UUID, kind="TRANSMISSION",
                description="Ghost study alternative",
                capex_cents=80_000_000_000, deliverable_mw=400,
            ),
            fx.ROUTE_ANALYST_HEADERS,
        )
        validate_error(response, ApiErrorId.REFERENCE_NOT_FOUND, expected_status=404)

        _, meta = validate_paginated(api.list_alternatives(fx.ROUTE_ANALYST_HEADERS))
        assert meta["total_count"] == 0, (
            f"A dangling study reference writes nothing, got {meta['total_count']}"
        )

    def test_alternative_with_no_deliverable_capability_is_refused(self, api):
        """PRD §3.1: "Because the division must exist, a `deliverable_mw` of zero or
        below is refused with `ERR_ZERO_DELIVERABLE` (HTTP 422)."

        Design: Corner/validations/zero_deliverable_alternative_rejected
        """
        ctx = {}
        fx.create_project(api, ctx)
        study = get_success_data(
            api.create_planning_study(
                f.planning_study_payload(ctx["proj"]), fx.DEVELOPER_HEADERS
            )
        )

        response = api.create_alternative(
            f.alternative_payload(
                study["id"], kind="NON_TRANSMISSION",
                description="Efficiency program with no firm capacity",
                capex_cents=1_200_000_000, deliverable_mw=0,
            ),
            fx.ROUTE_ANALYST_HEADERS,
        )
        validate_error(response, ApiErrorId.ZERO_DELIVERABLE, expected_status=422)

        _, meta = validate_paginated(
            api.list_alternatives(fx.ROUTE_ANALYST_HEADERS, {"study_id": study["id"]})
        )
        assert meta["total_count"] == 0, (
            f"No alternative row survives the guard, got {meta['total_count']}"
        )
        assert fx.read_study(api, study["id"])["status"] == "DRAFT", (
            "A refused alternative cannot bubble the study out of DRAFT"
        )


class TestSufficiencyCertificationGates:
    """Three ways certification is refused, each leaving the arithmetic unwritten."""

    def test_the_author_may_not_certify_the_study_they_wrote(self, api):
        """PRD §2.10: "The developer who authored a planning study may not certify its
        own sufficiency: if the acting `X-User-ID` equals the study's
        `authored_by_user_id`, certification is refused with
        `ERR_SELF_CERTIFICATION`."

        Design: Corner/validations/self_certification_of_the_authored_study_rejected
        """
        ctx = fx.build_need_case(api)
        fx.screen_in_both_alternatives(api, ctx)

        response = api.certify_study_sufficiency(
            ctx["study"],
            f.sufficiency_certification_payload(attestation_note="Self review"),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.SELF_CERTIFICATION, expected_status=403)

        study = fx.read_study(api, ctx["study"])
        assert study["status"] == "ALTERNATIVES_ANALYZED", (
            f"The study stays where the screening left it, got {study['status']}"
        )
        assert_is_null(study, "need_margin_ratio", "PlanningStudy")
        assert_is_null(study, "certified_by_user_id", "PlanningStudy")

    def test_one_screened_in_alternative_is_not_enough_to_certify(self, api):
        """PRD §3.1: "then the requirement that the study have at least two
        screened-in alternatives of any kind, reported as
        `ERR_INSUFFICIENT_ALTERNATIVES` (HTTP 422)."

        Design: Corner/validations/certification_with_one_screened_alternative_rejected
        """
        ctx = fx.build_need_case(api)
        get_success_data(
            api.screen_alternative(
                ctx["alt2"],
                f.screening_payload(screen_reason="Credible non-wires portfolio"),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )

        response = api.certify_study_sufficiency(
            ctx["study"],
            f.sufficiency_certification_payload(
                attestation_note="Certifying on the non-wires screen alone"
            ),
            fx.DEVELOPER_CERTIFIER_HEADERS,
        )
        validate_error(response, ApiErrorId.INSUFFICIENT_ALTERNATIVES, expected_status=422)

        study = fx.read_study(api, ctx["study"])
        assert study["alternatives_screened_in_count"] == 1, (
            f"Exactly one alternative was screened in, got "
            f"{study['alternatives_screened_in_count']}"
        )
        assert fx.read_alternative(api, ctx["alt1"])["screening_status"] == "SUBMITTED", (
            "The wires alternative was never screened, so it stays SUBMITTED"
        )
        assert study["status"] == "ALTERNATIVES_ANALYZED", (
            f"The refusal leaves the study at ALTERNATIVES_ANALYZED, got "
            f"{study['status']}"
        )

    def test_a_wires_only_portfolio_leaves_the_selector_pool_empty(self, api):
        """PRD §3.1: "If the pool is empty the certification is refused with
        `ERR_NO_NONTRANSMISSION_ALTERNATIVE` and the study remains at
        `ALTERNATIVES_ANALYZED`."

        Design: Corner/validations/certification_without_a_non_transmission_candidate_rejected
        """
        ctx = {}
        fx.create_project(api, ctx)
        study = get_success_data(
            api.create_planning_study(
                f.planning_study_payload(ctx["proj"]), fx.DEVELOPER_HEADERS
            )
        )
        ctx["study"] = study["id"]
        wires_one = get_success_data(
            api.create_alternative(
                f.alternative_payload(
                    ctx["study"], kind="TRANSMISSION",
                    description="New 345kV single-circuit line",
                    capex_cents=80_000_000_000, deliverable_mw=400,
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )
        wires_two = get_success_data(
            api.create_alternative(
                f.alternative_payload(
                    ctx["study"], kind="TRANSMISSION",
                    description="Reconductor the parallel 138kV path",
                    capex_cents=52_000_000_000, deliverable_mw=260,
                ),
                fx.ROUTE_ANALYST_HEADERS,
            )
        )
        for alternative in (wires_one, wires_two):
            get_success_data(
                api.screen_alternative(
                    alternative["id"],
                    f.screening_payload(screen_reason="Wires option worth carrying"),
                    fx.ROUTE_ANALYST_HEADERS,
                )
            )

        response = api.certify_study_sufficiency(
            ctx["study"],
            f.sufficiency_certification_payload(attestation_note="Wires-only screening"),
            fx.DEVELOPER_CERTIFIER_HEADERS,
        )
        validate_error(
            response, ApiErrorId.NO_NONTRANSMISSION_ALTERNATIVE, expected_status=422
        )

        study = fx.read_study(api, ctx["study"])
        assert study["alternatives_screened_in_count"] == 2, (
            f"The count gate is satisfied by the two wires options, got "
            f"{study['alternatives_screened_in_count']}"
        )
        assert_is_null(study, "selected_nta_alternative_id", "PlanningStudy")
        assert_is_null(study, "need_margin_ratio", "PlanningStudy")
        assert study["status"] == "ALTERNATIVES_ANALYZED", (
            f"The study remains at ALTERNATIVES_ANALYZED, got {study['status']}"
        )
