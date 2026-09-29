"""Cascaded writes are readable the instant the request that caused them returns."""
from test_helpers import fixtures as fx, parse_instant, validate_success
from test_helpers.factories import disclosure_response_payload
from test_helpers.test_users import PROJECT_COORDINATOR, make_homeowner_headers


class TestImmediateVisibilityOfCascades:
    RESPONSE_INSTANT = "2026-08-03T08:00:00Z"

    def test_a_decline_shows_its_whole_cascade_without_a_second_request(self, api):
        """PRD §3.2: "A decline is far more consequential. The notice transitions `PENDING → DECLINED` with `responded_at` stamped, and when the declined notice was a `SWEEP_FINDINGS` notice on a project in `SURVEYED`, the project is voided outright: `SURVEYED → VOID`."
        PRD §3.1: "It increments by 1 when a project is opened, and decrements by 1 when a project reaches either of those two terminal states."
        PRD §3.1: "Alongside the ordinary single-project read, a computed posture snapshot is available to the `ProjectCoordinator`, the `LicensedSiteProfessional` and the `ComplianceOfficer`."

        Design: Corner/consistency_model/cascaded_fields_are_visible_in_the_same_logical_instant
        """
        ctx = fx.project_at_surveyed()
        notice = fx.create_disclosure(
            ctx["project"]["id"], disclosure_kind="SWEEP_FINDINGS"
        )
        assert notice["status"] == "PENDING", (
            f"the notice must be awaiting an answer, got {notice['status']}"
        )
        assert fx.read_property(ctx["property"]["id"])["open_project_count"] == 1, (
            "opening the project put the property's live tally at one"
        )

        declined = validate_success(
            api.respond_to_disclosure(
                notice["id"],
                disclosure_response_payload(
                    response="DECLINED", response_channel="PORTAL"
                ),
                make_homeowner_headers(ctx["property"]["id"]),
            ),
            200,
        )
        assert declined["status"] == "DECLINED", (
            "the response body already carries the notice's terminal status, got "
            f"{declined['status']}"
        )
        assert parse_instant(declined["responded_at"]) == parse_instant(
            self.RESPONSE_INSTANT
        ), (
            "the answer is stamped at the current logical instant, got "
            f"{declined['responded_at']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["status"] == "VOID", (
            "the very next read, with no clock movement and no retry, already shows "
            f"the voided project, got {project['status']}"
        )

        assert fx.read_property(ctx["property"]["id"])["open_project_count"] == 0, (
            "the property's live tally is already back at zero in the same logical "
            "instant"
        )

        summary = validate_success(
            api.get_tank_project_summary(ctx["project"]["id"], PROJECT_COORDINATOR)
        )
        assert summary["status"] == "VOID", (
            "the computed snapshot agrees with the stored row rather than lagging it, "
            f"got {summary['status']}"
        )
