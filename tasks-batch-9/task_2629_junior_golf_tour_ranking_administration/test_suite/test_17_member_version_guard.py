"""The concurrency layer: the three writes guarded by expected_member_version."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_STALE_MEMBER_VERSION
from test_helpers.assertions import assert_grant_status, assert_version_is
from test_helpers.test_users import COACH, RULES_OFFICIAL, TOUR_ADMIN, member_headers
from test_helpers.types import (
    AID_SUBMITTED,
    COACH_GRANT_REQUESTED,
    HANDICAP_SOURCE_STATE_ASSOC,
    HANDICAP_SOURCE_WHS_CLUB,
    SCOPE_FULL_PROFILE,
    SCOPE_RESULTS_ONLY,
)


class TestStaleMemberVersion:
    def test_a_revision_in_between_makes_an_assistance_application_stale(self, api):
        """The application must carry the version the revision left behind.

        PRD: "Each of them requires a non-optional input field named
        `expected_member_version`, carrying the `version` value the client last
        observed on that junior's record. If `expected_member_version` does not
        equal the junior's current `version`, the request is rejected with
        `ERR_STALE_MEMBER_VERSION` (HTTP 412) and nothing is written."

        Design: Corner/cross-cutting complexity layers/stale_member_version_blocks_an_assistance_application
        """
        fx.set_clock(api, fx.CLOCK_ENTRY_WINDOW)
        season = fx.create_season(api)
        member = fx.register_member(api, season["id"])
        fx.verify_member(api, member["id"])
        stale_version = fx.member_version(api, member["id"])

        revised = validate_success(
            api.revise_handicap(
                member["id"], f.handicap_revision_payload(stale_version), TOUR_ADMIN
            ),
            200,
        )
        assert_version_is(revised, stale_version + 1)

        application = f.aid_application_payload(
            member["id"], season["id"], stale_version
        )
        validate_error(
            api.submit_aid_application(application, member_headers(member["id"])),
            ERR_STALE_MEMBER_VERSION,
            412,
        )
        _, meta = validate_paginated(api.list_aid_applications(None, TOUR_ADMIN))
        assert meta["total_count"] == 0

        fresh_version = fx.member_version(api, member["id"])
        assert fresh_version == stale_version + 1
        application["expected_member_version"] = fresh_version
        created = validate_success(
            api.submit_aid_application(application, member_headers(member["id"])), 201
        )
        assert created["status"] == AID_SUBMITTED
        assert created["member_id"] == member["id"]
        assert fx.read_member(api, member["id"])["handicap_index"] == 3.5

    def test_a_coach_replaying_a_version_does_not_supersede_its_own_grant(self, api):
        """The refused replay leaves the coach's first request standing.

        PRD: "Any prior grant of the same junior and the same coach whose
        `status` is `REQUESTED` or `GRANTED` moves to `SUPERSEDED`, and the new
        grant starts at `REQUESTED` — which means a coach who re-requests
        **loses** the access they already had until the junior decides again."

        Design: Corner/cross-cutting complexity layers/stale_member_version_blocks_a_recruiting_access_request
        """
        fx.set_clock(api, fx.CLOCK_ENTRY_WINDOW)
        season = fx.create_season(api)
        member = fx.register_member(api, season["id"])
        fx.verify_member(api, member["id"])
        observed_version = fx.member_version(api, member["id"])

        grant = validate_success(
            api.request_coach_access(
                f.coach_access_payload(member["id"], observed_version), COACH
            ),
            201,
        )
        assert_grant_status(grant, COACH_GRANT_REQUESTED)

        validate_error(
            api.request_coach_access(
                f.coach_access_payload(
                    member["id"], observed_version, scope=SCOPE_FULL_PROFILE
                ),
                COACH,
            ),
            ERR_STALE_MEMBER_VERSION,
            412,
        )

        survivor = validate_success(
            api.get_coach_access_grant(grant["id"], TOUR_ADMIN), 200
        )
        assert_grant_status(survivor, COACH_GRANT_REQUESTED)
        assert survivor["scope"] == SCOPE_RESULTS_ONLY
        assert fx.member_version(api, member["id"]) == observed_version + 1

    def test_only_the_landed_revision_moves_the_version_counter(self, api):
        """Two revisions on one version leave the first index and one increment.

        PRD: "Every one of the three operations increments `Member.version` when
        it succeeds, which is precisely why a second write presenting the same
        `expected_member_version` will fail."

        Design: Corner/cross-cutting complexity layers/stale_member_version_blocks_a_second_handicap_revision
        """
        fx.set_clock(api, fx.CLOCK_ENTRY_WINDOW)
        season = fx.create_season(api)
        member = fx.register_member(api, season["id"])
        fx.verify_member(api, member["id"])
        observed_version = fx.member_version(api, member["id"])

        first = validate_success(
            api.revise_handicap(
                member["id"], f.handicap_revision_payload(observed_version), TOUR_ADMIN
            ),
            200,
        )
        assert first["handicap_index"] == 3.5
        assert_version_is(first, observed_version + 1)

        loser = f.handicap_revision_payload(
            observed_version,
            handicap_index=4.1,
            handicap_source=HANDICAP_SOURCE_STATE_ASSOC,
        )
        validate_error(
            api.revise_handicap(member["id"], loser, RULES_OFFICIAL),
            ERR_STALE_MEMBER_VERSION,
            412,
        )

        held = fx.read_member(api, member["id"])
        assert held["handicap_index"] == 3.5
        assert held["handicap_source"] == HANDICAP_SOURCE_WHS_CLUB
        assert_version_is(held, observed_version + 1)

        loser["expected_member_version"] = held["version"]
        second = validate_success(
            api.revise_handicap(member["id"], loser, RULES_OFFICIAL), 200
        )
        assert second["handicap_index"] == 4.1
        assert second["handicap_source"] == HANDICAP_SOURCE_STATE_ASSOC
        assert_version_is(second, observed_version + 2)
