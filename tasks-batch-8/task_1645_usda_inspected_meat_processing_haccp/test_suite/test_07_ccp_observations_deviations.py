"""CCP monitoring observations, deviation lifecycle, plant compliance scoring."""
from test_helpers import (
    INSPECTOR_1,
    QA_MANAGER_1,
    QA_MANAGER_2,
    QA_TECH_1,
    TEST_USERS,
    ApiErrorId,
    corrective_action_payload,
    observation_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures

QA = TEST_USERS["qa_manager_headers"]
PROD = TEST_USERS["production_manager_headers"]


def _setup_two_ccp_env(establishment_number: str) -> dict:
    """Plant with an EFFECTIVE plan carrying a BIOLOGICAL CCP (max 40.0) and a
    PHYSICAL CCP (max 10.0), inspector ON_PREMISE, OPEN day on 2026-08-01."""
    plant = fixtures.create_plant(establishment_number=establishment_number)
    plan = fixtures.create_draft_plan(plant["id"])
    ccp_b = fixtures.add_ccp(
        plan["id"], ccp_code="CCP-B", hazard_category="BIOLOGICAL",
        description="Chill cooler", critical_limit_max_f=40.0,
    )
    ccp_p = fixtures.add_ccp(
        plan["id"], ccp_code="CCP-P", hazard_category="PHYSICAL",
        description="Metal detector", critical_limit_max_f=10.0,
        monitoring_frequency_minutes=30,
    )
    fixtures.submit_plan(plan["id"])
    fixtures.approve_plan(plan["id"])
    fixtures.activate_plan(plan["id"])
    shift = fixtures.schedule_shift(plant["id"])
    fixtures.set_clock("2026-08-01T07:00:00Z")
    fixtures.check_in_shift(shift["id"])
    day = fixtures.plan_production_day(plant["id"])
    day = fixtures.open_day(day["id"])
    return {"plant": plant, "plan": plan, "ccp_b": ccp_b, "ccp_p": ccp_p,
            "shift": shift, "day": day}


def _spawn_three_deviations(env: dict):
    """D1 MAJOR (CCP-B at 41.0), D2 MINOR (CCP-P at 11.0), D3 MINOR (12.0)."""
    d1 = fixtures.record_observation(env["ccp_b"]["id"], 41.0)["deviation_id"]
    d2 = fixtures.record_observation(env["ccp_p"]["id"], 11.0)["deviation_id"]
    d3 = fixtures.record_observation(env["ccp_p"]["id"], 12.0)["deviation_id"]
    return d1, d2, d3


class TestComplianceScoreVariants:
    def test_provisional_score_tracks_unresolved_deviations_flatly(self, api):
        """PRD §3.1: "The `provisional_compliance_score` is a flat operational reading: 100 minus 2 points for each of the plant's deviations still in `OPEN` or `ACTION_LOGGED` status, regardless of severity, and ignoring verified deviations entirely."
        PRD §3.4: "A successful verify stamps `verified_by`, recomputes both plant scores — the official score now picks up the deviation's severity weight while the provisional score releases its flat two points — and recomputes the day's posture, which returns to `CLEAR` once no unresolved deviations, held lots, or quarantined finished lots remain."

        Design: Difficulty/dual_variant_calc/compliance_score_provisional_vs_official_divergence
        """
        env = _setup_two_ccp_env("EST-1645-B1")
        plant_id = env["plant"]["id"]
        d1, d2, d3 = _spawn_three_deviations(env)

        plant = validate_success(api.get_plant(plant_id, QA), 200)
        assert plant["provisional_compliance_score"] == 94, (
            "three unresolved deviations: 100 - 2*3"
        )

        fixtures.resolve_deviation(d1)
        plant = validate_success(api.get_plant(plant_id, QA), 200)
        assert plant["provisional_compliance_score"] == 96, (
            "verifying D1 releases its flat two points: 100 - 2*2"
        )

        fixtures.resolve_deviation(d2)
        plant = validate_success(api.get_plant(plant_id, QA), 200)
        assert plant["provisional_compliance_score"] == 98, (
            "only D3 remains unresolved: 100 - 2*1"
        )

    def test_official_score_weights_only_verified_deviations(self, api):
        """PRD §3.1: "The `official_compliance_score` is the severity-weighted standing: 100 minus the sum of severity weights over the plant's `VERIFIED` deviations only, where a `MINOR` deviation weighs 2 points and a `MAJOR` deviation weighs 5."
        PRD §3.1: "The `provisional_compliance_score` is a flat operational reading: 100 minus 2 points for each of the plant's deviations still in `OPEN` or `ACTION_LOGGED` status, regardless of severity, and ignoring verified deviations entirely."

        Design: Difficulty/dual_variant_calc/compliance_score_provisional_vs_official_divergence
        """
        env = _setup_two_ccp_env("EST-1645-B2")
        plant_id = env["plant"]["id"]
        d1, d2, d3 = _spawn_three_deviations(env)

        plant = validate_success(api.get_plant(plant_id, QA), 200)
        assert plant["official_compliance_score"] == 100, (
            "no VERIFIED deviations yet — the official score ignores OPEN ones"
        )

        fixtures.resolve_deviation(d1)  # MAJOR verified
        plant = validate_success(api.get_plant(plant_id, QA), 200)
        assert plant["official_compliance_score"] == 95, "100 - 5 (MAJOR)"

        fixtures.resolve_deviation(d2)  # MINOR verified
        plant = validate_success(api.get_plant(plant_id, QA), 200)
        assert plant["official_compliance_score"] == 93, "100 - 5 - 2"
        assert plant["provisional_compliance_score"] == 98
        assert plant["official_compliance_score"] != (
            plant["provisional_compliance_score"]
        ), "the two variants count different populations of the same data"


class TestCcpCriticalLimitInclusiveBoundary:
    def test_observation_at_exactly_max_is_within_limit(self, api):
        """PRD §3.4: "The server then computes `within_limit` with inclusive bounds: the reading passes when it is at least `critical_limit_min_f` (or the minimum is unset) and at most `critical_limit_max_f` (or the maximum is unset)."

        Design: Difficulty/boundary_precision_check/ccp_critical_limit_inclusive_boundary
        """
        env = fixtures.setup_open_day(establishment_number="EST-1645-K1")
        obs = fixtures.record_observation(env["ccp"]["id"], 40.0)
        assert obs["within_limit"] is True, "40.0 == max is inclusive"
        assert obs.get("deviation_id") is None, "no deviation for an in-limit reading"

        devs, meta = validate_paginated(
            api.list_deviations(QA, params={"ccp_id": env["ccp"]["id"]})
        )
        assert devs == []
        assert meta["total_count"] == 0

    def test_observation_above_max_spawns_major_open_deviation(self, api):
        """PRD §3.4: "An out-of-limit observation spawns a `Deviation` in `OPEN` status whose `severity` is copied from the CCP's `deviation_severity`, links the observation back through `deviation_id`, and records the originating `observation_id` and `ccp_id`."
        PRD §3.2: "From the hazard category the server derives `deviation_severity`: `MAJOR` for a `BIOLOGICAL` hazard, `MINOR` otherwise."

        Design: Difficulty/boundary_precision_check/ccp_critical_limit_inclusive_boundary
        """
        env = fixtures.setup_open_day(establishment_number="EST-1645-K2")
        obs = fixtures.record_observation(env["ccp"]["id"], 40.1)
        assert obs["within_limit"] is False
        assert obs.get("deviation_id"), "an out-of-limit reading spawns a Deviation"

        devs, meta = validate_paginated(
            api.list_deviations(QA, params={"ccp_id": env["ccp"]["id"]})
        )
        assert len(devs) == 1
        assert meta["total_count"] == 1
        assert devs[0]["severity"] == "MAJOR", "CCP is BIOLOGICAL"
        assert devs[0]["status"] == "OPEN"
        assert devs[0]["id"] == obs["deviation_id"]
        assert devs[0]["observation_id"] == obs["id"]


class TestObservationGateOrdering:
    def _setup_superseded_plan(self, establishment_number: str) -> dict:
        plant = fixtures.create_plant(establishment_number=establishment_number)
        plan1, ccp1 = fixtures.create_effective_plan(plant["id"])
        plan2 = fixtures.create_draft_plan(plant["id"])
        fixtures.add_ccp(plan2["id"], description="Chill cooler v2",
                         monitoring_frequency_minutes=30)
        fixtures.submit_plan(plan2["id"])
        fixtures.approve_plan(plan2["id"])
        fixtures.activate_plan(plan2["id"])
        return {"plant": plant, "plan1": plan1, "ccp1": ccp1, "plan2": plan2}

    def test_temporal_error_beats_referential_error(self, api):
        """PRD §3.4: "Two business gates guard the recording, evaluated in this order: an `OPEN` production day must exist for the CCP's plant whose `production_date` equals the current logical-clock date (`ERR_NO_OPEN_PRODUCTION_DAY`), and the plan owning the CCP must be `EFFECTIVE` (`ERR_PLAN_NOT_EFFECTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/observation_temporal_error_beats_referential_error
        """
        env = self._setup_superseded_plan("EST-1645-J")
        fixtures.set_clock("2026-08-01T07:00:00Z")
        # No OPEN production day exists for the current clock date; the CCP's
        # plan is SUPERSEDED. The temporal gate is evaluated first.
        resp = api.record_observation(
            env["ccp1"]["id"], observation_payload(observed_value_f=39.0),
            fixtures.make_qa_tech_headers(QA_TECH_1),
        )
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_PRODUCTION_DAY)
        assert resp.status_code == 422

        obs, meta = validate_paginated(
            api.list_observations(QA, params={"ccp_id": env["ccp1"]["id"]})
        )
        assert obs == [], "the rejected observation must not persist"

    def test_referential_error_surfaces_once_temporal_gate_passes(self, api):
        """PRD §3.4: "Two business gates guard the recording, evaluated in this order: an `OPEN` production day must exist for the CCP's plant whose `production_date` equals the current logical-clock date (`ERR_NO_OPEN_PRODUCTION_DAY`), and the plan owning the CCP must be `EFFECTIVE` (`ERR_PLAN_NOT_EFFECTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/observation_temporal_error_beats_referential_error
        """
        env = self._setup_superseded_plan("EST-1645-J2")
        # Satisfy the temporal gate: open a day (plan2 is EFFECTIVE, so the
        # open succeeds) — the SUPERSEDED plan's CCP still fails referentially.
        shift = fixtures.schedule_shift(env["plant"]["id"])
        fixtures.set_clock("2026-08-01T07:00:00Z")
        fixtures.check_in_shift(shift["id"])
        day = fixtures.plan_production_day(env["plant"]["id"])
        fixtures.open_day(day["id"])

        resp = api.record_observation(
            env["ccp1"]["id"], observation_payload(observed_value_f=39.0),
            fixtures.make_qa_tech_headers(QA_TECH_1),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_EFFECTIVE)


class TestDeviationDisposition:
    def test_verify_before_action_logged_returns_invalid_state(self, api):
        """PRD §3.4: "Logging a corrective action moves the deviation from `OPEN` to `ACTION_LOGGED` — any other from-state draws `ERR_DEVIATION_INVALID_STATE` — recording the payload's `corrective_action_note` and stamping `action_logged_by` with the actor's `X-User-ID`; the plant's `provisional_compliance_score` and the day's `posture` are recomputed."
        PRD §3.4: "Verification then moves `ACTION_LOGGED` to `VERIFIED`: after the state check, the verifier's `X-User-ID` must differ both from the spawning observation's `monitor_user_id` and from `action_logged_by`, otherwise the request fails with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        Design: Corner/state_machines/deviation_verify_before_action_logged_returns_invalid_state
        """
        env, _obs, dev_id = fixtures.setup_deviation(
            establishment_number="EST-1645-06"
        )
        resp = api.verify_deviation(
            dev_id, fixtures.make_qa_manager_headers(QA_MANAGER_2)
        )
        validate_error(resp, ApiErrorId.ERR_DEVIATION_INVALID_STATE)
        assert resp.status_code == 409

        after = validate_success(api.get_deviation(dev_id, QA), 200)
        assert after["status"] == "OPEN"

    def test_verify_by_monitor_or_logger_returns_segregation_error(self, api):
        """PRD §3.4: "Verification then moves `ACTION_LOGGED` to `VERIFIED`: after the state check, the verifier's `X-User-ID` must differ both from the spawning observation's `monitor_user_id` and from `action_logged_by`, otherwise the request fails with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        Design: Corner/validations/deviation_verify_by_monitor_returns_segregation_error
        """
        env, _obs, dev_id = fixtures.setup_deviation(
            establishment_number="EST-1645-32", monitor_id=QA_TECH_1
        )

        logged = validate_success(
            api.log_corrective_action(
                dev_id, corrective_action_payload(),
                fixtures.make_qa_manager_headers(QA_MANAGER_1),
            ),
            200,
        )
        assert logged["status"] == "ACTION_LOGGED"
        assert logged["action_logged_by"] == QA_MANAGER_1

        # The monitoring technician may not verify, even with a QAManager role.
        by_monitor = api.verify_deviation(
            dev_id, fixtures.make_qa_manager_headers(QA_TECH_1)
        )
        validate_error(by_monitor, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        assert by_monitor.status_code == 403

        # Neither may the operator who logged the corrective action.
        by_logger = api.verify_deviation(
            dev_id, fixtures.make_qa_manager_headers(QA_MANAGER_1)
        )
        validate_error(by_logger, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

        # A third, uninvolved QAManager verifies successfully.
        ok = validate_success(
            api.verify_deviation(
                dev_id, fixtures.make_qa_manager_headers(QA_MANAGER_2)
            ),
            200,
        )
        assert ok["status"] == "VERIFIED"
        assert ok["verified_by"] == QA_MANAGER_2


class TestDayCloseBlockedByDeviation:
    def test_close_day_with_open_deviation_returns_day_invalid_state(self, api):
        """PRD §3.3: "Closing a day — permitted from `OPEN` or `SUSPENDED` — is blocked with `ERR_DAY_INVALID_STATE` while any deviation of the day remains `OPEN` or `ACTION_LOGGED`, or while any carcass lot of the day sits outside the terminal-for-close pair `FABRICATED` and `CONDEMNED`."
        PRD §3.3: "A successful close freezes the day's reconciliation: `total_cut_weight_lbs` and `total_cold_weight_lbs` are summed over the day's `FABRICATED` lots only (`CONDEMNED` lots are excluded from both sums), and `day_yield_pct` is set to one hundred times the frozen cut total divided by the frozen cold total, rounded half-up to two decimal places — or null when the frozen cold total is zero."

        Design: Corner/endpoints/close_day_with_open_deviation_returns_day_invalid_state
        """
        env, _obs, dev_id = fixtures.setup_deviation(
            establishment_number="EST-1645-38"
        )
        blocked = api.close_production_day(env["day"]["id"], PROD)
        validate_error(blocked, ApiErrorId.ERR_DAY_INVALID_STATE)
        assert blocked.status_code == 409

        fixtures.resolve_deviation(dev_id)
        closed = validate_success(
            api.close_production_day(env["day"]["id"], PROD), 200
        )
        assert closed["status"] == "CLOSED"
        assert closed.get("day_yield_pct") is None, (
            "no FABRICATED lots: the frozen cold total is zero, so "
            "day_yield_pct is null"
        )


class TestObservationOnSupersededPlan:
    def test_observation_on_superseded_plan_returns_plan_not_effective(self, api):
        """PRD §3.4: "Two business gates guard the recording, evaluated in this order: an `OPEN` production day must exist for the CCP's plant whose `production_date` equals the current logical-clock date (`ERR_NO_OPEN_PRODUCTION_DAY`), and the plan owning the CCP must be `EFFECTIVE` (`ERR_PLAN_NOT_EFFECTIVE`)."

        Design: Corner/validations/observation_on_superseded_plan_returns_plan_not_effective
        """
        # Day opens while plan1 is EFFECTIVE; plan2 then supersedes it.
        env = fixtures.setup_open_day(establishment_number="EST-1645-28")
        plan2 = fixtures.create_draft_plan(env["plant"]["id"])
        fixtures.add_ccp(plan2["id"], description="Chill cooler v2",
                         monitoring_frequency_minutes=30)
        fixtures.submit_plan(plan2["id"])
        fixtures.approve_plan(plan2["id"])
        fixtures.activate_plan(plan2["id"])

        resp = api.record_observation(
            env["ccp"]["id"], observation_payload(observed_value_f=39.0),
            fixtures.make_qa_tech_headers(QA_TECH_1),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_EFFECTIVE)
        assert resp.status_code == 422

        obs, meta = validate_paginated(
            api.list_observations(QA, params={"ccp_id": env["ccp"]["id"]})
        )
        assert obs == []
