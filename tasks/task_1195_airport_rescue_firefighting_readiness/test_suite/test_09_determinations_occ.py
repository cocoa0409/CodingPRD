"""Index determinations (OCC) and determination business gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_aircraft,
    create_aircraft_payload,
    create_profile,
    get_success_data,
    set_clock,
    setup_profile_only,
    validate_error,
    validate_paginated,
    validate_success,
)

AM = TEST_USERS["airport_manager_headers"]


class TestDeterminationGateErrorBattery:
    def test_non_qualifying_aircraft_rejected(self, api):
        """PRD §3.6: "The named aircraft must qualify — meaning
        `in_scheduled_service` is `true` and `avg_daily_departures` is at
        least `5.0`; otherwise the request is rejected with
        `ERR_AIRCRAFT_NOT_QUALIFYING`."

        Design: Corner/errors/err_determination_gate_error_battery
        """
        set_clock("2026-05-01T00:00:00Z")
        create_profile("KDEMO", "D")
        ac_c = create_aircraft(model_name="B737-900", length_ft=138.2,
                               avg_daily_departures=6.0)
        ac_a = create_aircraft(model_name="C172", length_ft=27.0,
                               avg_daily_departures=2.0)
        ac_d = create_aircraft(model_name="B767-400", length_ft=180.0,
                               avg_daily_departures=5.5)
        profile = get_success_data(api.get_profile(AM))
        pv = profile["version"]
        resp = api.create_index_determination(
            {
                "largest_aircraft_id": ac_a["id"],
                "new_certificated_index": "D",
                "expected_profile_version": pv,
            },
            AM,
        )
        validate_error(resp, ApiErrorId.ERR_AIRCRAFT_NOT_QUALIFYING)

    def test_not_longest_qualifying_rejected(self, api):
        """PRD §3.6: "The named aircraft must be the longest qualifying
        aircraft by the ordering of §3.1; otherwise
        `ERR_NOT_LARGEST_QUALIFYING_AIRCRAFT`."

        Design: Corner/errors/err_determination_gate_error_battery
        """
        set_clock("2026-05-01T00:00:00Z")
        create_profile("KDEMO", "D")
        ac_c = create_aircraft(model_name="B737-900", length_ft=138.2,
                               avg_daily_departures=6.0)
        ac_a = create_aircraft(model_name="C172", length_ft=27.0,
                               avg_daily_departures=2.0)
        ac_d = create_aircraft(model_name="B767-400", length_ft=180.0,
                               avg_daily_departures=5.5)
        profile = get_success_data(api.get_profile(AM))
        pv = profile["version"]
        resp = api.create_index_determination(
            {
                "largest_aircraft_id": ac_c["id"],
                "new_certificated_index": "D",
                "expected_profile_version": pv,
            },
            AM,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_LARGEST_QUALIFYING_AIRCRAFT)

    def test_index_below_required_rejected(self, api):
        """PRD §3.6: "And `new_certificated_index` must be at-or-above the
        `required_index` computed across all qualifying aircraft at creation
        time; otherwise `ERR_INDEX_BELOW_REQUIRED`."

        Design: Corner/errors/err_determination_gate_error_battery
        """
        set_clock("2026-05-01T00:00:00Z")
        create_profile("KDEMO", "D")
        ac_c = create_aircraft(model_name="B737-900", length_ft=138.2,
                               avg_daily_departures=6.0)
        ac_a = create_aircraft(model_name="C172", length_ft=27.0,
                               avg_daily_departures=2.0)
        ac_d = create_aircraft(model_name="B767-400", length_ft=180.0,
                               avg_daily_departures=5.5)
        profile = get_success_data(api.get_profile(AM))
        pv = profile["version"]
        resp = api.create_index_determination(
            {
                "largest_aircraft_id": ac_d["id"],
                "new_certificated_index": "C",
                "expected_profile_version": pv,
            },
            AM,
        )
        validate_error(resp, ApiErrorId.ERR_INDEX_BELOW_REQUIRED)


class TestOccStaleProfileVersionRejected:
    def test_stale_expected_version_rejected(self, api):
        """PRD §2.8: "If the profile's `version` has advanced beyond what
        the caller last observed — whether because another determination
        superseded the prior `ACTIVE` one, or because any readiness cascade
        recomputed the profile — the create is rejected with
        `ERR_STALE_PROFILE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/x_occ_stale_profile_version_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        create_profile("KDEMO", "C")
        ac1 = create_aircraft(model_name="B737-900", length_ft=138.2,
                              avg_daily_departures=6.0)
        profile = get_success_data(api.get_profile(AM))
        pv = profile["version"]
        # First determination succeeds
        det1 = validate_success(
            api.create_index_determination(
                {
                    "largest_aircraft_id": ac1["id"],
                    "new_certificated_index": "C",
                    "expected_profile_version": pv,
                },
                AM,
            ),
            expected_status=201,
        )
        assert det1["status"] == "ACTIVE"
        # Second create reusing stale pv must be rejected
        resp = api.create_index_determination(
            {
                "largest_aircraft_id": ac1["id"],
                "new_certificated_index": "D",
                "expected_profile_version": pv,
            },
            AM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PROFILE_VERSION)

    def test_stale_version_preempts_state(self, api):
        """PRD §2.8: "If the profile's `version` has advanced beyond what
        the caller last observed — whether because another determination
        superseded the prior `ACTIVE` one, or because any readiness cascade
        recomputed the profile — the create is rejected with
        `ERR_STALE_PROFILE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/x_occ_stale_profile_version_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        create_profile("KDEMO", "C")
        ac1 = create_aircraft(model_name="B737-900", length_ft=138.2,
                              avg_daily_departures=6.0)
        profile = get_success_data(api.get_profile(AM))
        pv = profile["version"]
        # Bump version via cascade: register another aircraft
        create_aircraft(model_name="E190", length_ft=118.9,
                        avg_daily_departures=4.0)
        resp = api.create_index_determination(
            {
                "largest_aircraft_id": ac1["id"],
                "new_certificated_index": "C",
                "expected_profile_version": pv,
            },
            AM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PROFILE_VERSION)


class TestOccFreshVersionSuccessIncrementsAndSupersedes:
    def test_fresh_version_increments_and_supersedes(self, api):
        """PRD §3.6: "The previous `ACTIVE` determination flips to
        `SUPERSEDED`. The profile's `certificated_index` updates to
        `new_certificated_index`, the profile recomputes `effective_index`
        and `index_compliance_status`, and the profile's `version` increments
        by 1. Exactly one `ACTIVE` determination exists at any time."

        Design: Corner/cross_cutting_complexity_layers/x_occ_fresh_version_success_increments_and_supersedes
        """
        set_clock("2026-05-01T00:00:00Z")
        create_profile("KDEMO", "C")
        ac1 = create_aircraft(model_name="B737-900", length_ft=138.2,
                              avg_daily_departures=6.0)
        profile0 = get_success_data(api.get_profile(AM))
        pv0 = profile0["version"]
        det1 = validate_success(
            api.create_index_determination(
                {
                    "largest_aircraft_id": ac1["id"],
                    "new_certificated_index": "C",
                    "expected_profile_version": pv0,
                },
                AM,
            ),
            expected_status=201,
        )
        profile1 = get_success_data(api.get_profile(AM))
        pv1 = profile1["version"]
        # Now supersedes with fresh pv1
        det2 = validate_success(
            api.create_index_determination(
                {
                    "largest_aircraft_id": ac1["id"],
                    "new_certificated_index": "D",
                    "expected_profile_version": pv1,
                },
                AM,
            ),
            expected_status=201,
        )
        assert det2["supersedes_determination_id"] == det1["id"]
        profile2 = get_success_data(api.get_profile(AM))
        assert profile2["version"] == pv1 + 1
        assert profile2["certificated_index"] == "D"

    def test_aircraft_determinations_list_reflects_supersede(self, api):
        """PRD §3.6: "Exactly one `ACTIVE` determination exists at any time."

        Design: Corner/cross_cutting_complexity_layers/x_occ_fresh_version_success_increments_and_supersedes
        """
        set_clock("2026-05-01T00:00:00Z")
        create_profile("KDEMO", "C")
        ac1 = create_aircraft(model_name="B737-900", length_ft=138.2,
                              avg_daily_departures=6.0)
        profile0 = get_success_data(api.get_profile(AM))
        det1 = validate_success(
            api.create_index_determination(
                {
                    "largest_aircraft_id": ac1["id"],
                    "new_certificated_index": "C",
                    "expected_profile_version": profile0["version"],
                },
                AM,
            ),
            expected_status=201,
        )
        profile1 = get_success_data(api.get_profile(AM))
        det2 = validate_success(
            api.create_index_determination(
                {
                    "largest_aircraft_id": ac1["id"],
                    "new_certificated_index": "D",
                    "expected_profile_version": profile1["version"],
                },
                AM,
            ),
            expected_status=201,
        )
        # List determinations naming this aircraft
        data, meta = validate_paginated(
            api.list_aircraft_index_determinations(ac1["id"], AM)
        )
        statuses = {d["id"]: d["status"] for d in data}
        assert statuses[det1["id"]] == "SUPERSEDED"
        assert statuses[det2["id"]] == "ACTIVE"
