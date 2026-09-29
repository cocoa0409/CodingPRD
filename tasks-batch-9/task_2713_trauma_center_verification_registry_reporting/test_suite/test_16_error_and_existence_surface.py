"""Identity refusals and the existence gate that precedes payload validation.

These cases pin the two refusals that apply before any domain rule is consulted: a
request that carries no identity headers at all, and a request that names a resource
which does not exist.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import NO_HEADERS, ApiClient
from test_helpers import ApiErrorId as E
from test_helpers import (
    DesignationLevel,
    PiEventType,
    PiSeverity,
    ResponderRole,
    factories as f,
    fixtures as fx,
    make_registry_abstractor_headers,
    make_system_admin_headers,
    make_verification_reviewer_headers,
)

UNKNOWN_CASE_ID = "3f1c9a52-0000-4000-8000-0000000000c1"
UNKNOWN_CYCLE_ID = "8b2d4e10-0000-4000-8000-0000000000f2"
UNKNOWN_PI_EVENT_ID = "11111111-1111-1111-1111-111111111111"


class TestUnauthenticatedRequests:
    """Authentication is not a write-only gate."""

    def test_header_less_read_and_write_are_both_refused_as_unauthenticated(
        self, api: ApiClient
    ) -> None:
        """A read without identity headers is refused exactly like a write without them.

        Design: Corner/errors/missing_auth_headers_return_unauthenticated_on_reads_and_writes
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Foxglove Trauma",
            state_code="TN",
            designation_level=DesignationLevel.LEVEL_II,
        )

        read = api.get_trauma_center(center["id"], NO_HEADERS)
        validate_error(read, E.UNAUTHENTICATED, 401)

        write = api.create_pi_event(
            f.pi_event_payload(
                center_id=center["id"],
                event_type=PiEventType.TRANSFER_DELAY,
                severity=PiSeverity.LOW,
            ),
            NO_HEADERS,
        )
        validate_error(write, E.UNAUTHENTICATED, 401)
        assert write.status_code != 403, (
            "an unauthenticated write is 401, never 403"
        )

        events = get_success_data(
            api.list_pi_events(
                make_system_admin_headers(), {"center_id": center["id"]}
            )
        )
        assert events == [], "the refused write must have persisted nothing"

    def test_header_less_write_leaves_the_center_untouched(self, api: ApiClient) -> None:
        """The refused write does not bump the addressed center's version.

        Design: Corner/errors/missing_auth_headers_return_unauthenticated_on_reads_and_writes
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Foxglove Trauma",
            state_code="TN",
            designation_level=DesignationLevel.LEVEL_II,
        )

        validate_error(
            api.create_pi_event(
                f.pi_event_payload(
                    center_id=center["id"],
                    event_type=PiEventType.TRANSFER_DELAY,
                    severity=PiSeverity.LOW,
                ),
                NO_HEADERS,
            ),
            E.UNAUTHENTICATED,
            401,
        )

        after = fx.get_center(api, center["id"])
        assert after["version"] == center["version"]
        assert after["open_pi_event_count"] == 0


class TestUnknownCaseIdentifier:
    """A well-formed but unknown case id settles the response before the body is read."""

    def test_unknown_case_is_not_found_on_both_the_read_and_the_nested_write(
        self, api: ApiClient
    ) -> None:
        """Existence is decided before payload shape, so a bad body never surfaces.

        Design: Corner/errors/unknown_case_id_on_read_and_action_returns_case_not_found
        """
        fx.anchor_clock(api)
        fx.create_center(
            api,
            name="Alderwood Trauma",
            state_code="WA",
            designation_level=DesignationLevel.LEVEL_II,
        )

        read = api.get_registry_case(
            UNKNOWN_CASE_ID, make_registry_abstractor_headers()
        )
        validate_error(read, E.CASE_NOT_FOUND, 404)

        nested_write = api.create_response_log(
            UNKNOWN_CASE_ID,
            {"responder_role": ResponderRole.SURGEON},
            make_registry_abstractor_headers(),
        )
        validate_error(nested_write, E.CASE_NOT_FOUND, 404)
        assert nested_write.json()["data"]["error_id"] != E.INVALID_REQUEST, (
            "the missing notified_at must stay invisible behind the 404"
        )


class TestUnknownCycleIdentifier:
    """The computed readiness read carries the same existence gate as the plain read."""

    def test_unknown_cycle_is_not_found_on_both_the_read_and_the_readiness_read(
        self, api: ApiClient
    ) -> None:
        """An unknown cycle yields a 404 rather than a default readiness score.

        Design: Corner/errors/unknown_cycle_id_on_read_and_readiness_returns_cycle_not_found
        """
        fx.anchor_clock(api)

        plain = api.get_verification_cycle(
            UNKNOWN_CYCLE_ID, make_verification_reviewer_headers()
        )
        validate_error(plain, E.CYCLE_NOT_FOUND, 404)

        readiness = api.get_cycle_readiness(
            UNKNOWN_CYCLE_ID, make_verification_reviewer_headers()
        )
        validate_error(readiness, E.CYCLE_NOT_FOUND, 404)

        for response in (plain, readiness):
            assert "readiness_score" not in response.json()["data"], (
                "a refused read must not report a score"
            )


class TestUnknownPiEventIdentifier:
    """A PI event that was never opened has its own existence error."""

    def test_unknown_pi_event_is_not_found_and_the_center_holds_no_events(
        self, api: ApiClient
    ) -> None:
        """The 404 names the PI event, and the center's event list stays empty.

        Design: Corner/entities/get_pi_event_with_unknown_id_returns_pi_event_not_found
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Junction Trauma",
            state_code="CO",
            designation_level=DesignationLevel.LEVEL_II,
        )

        read = api.get_pi_event(UNKNOWN_PI_EVENT_ID, make_system_admin_headers())
        validate_error(read, E.PI_EVENT_NOT_FOUND, 404)

        events = get_success_data(
            api.list_pi_events(make_system_admin_headers(), {"center_id": center["id"]})
        )
        assert events == []
