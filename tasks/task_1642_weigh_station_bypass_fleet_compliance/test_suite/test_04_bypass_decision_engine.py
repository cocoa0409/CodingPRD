"""The roadside decision engine: pinned check order, weight enforcement,
deterministic screen, rate cap, channel selection, and ruleset pinning."""
from test_helpers import (
    FINANCE,
    GATEWAY,
    SPM,
    ApiErrorId,
    activate_credential,
    assert_event,
    create_active_carrier,
    create_config,
    create_credential_for,
    create_station,
    create_subscription_for,
    create_vehicle_for,
    get_carrier,
    list_events_for,
    make_carrier_manager_headers,
    patch_config,
    post_snapshot,
    set_clock,
    setup_bypass_ready,
    transition_carrier,
    validate_error,
    validate_paginated,
    validate_success,
)

FULL_CREDS = ["IFTA", "IRP", "UCR"]


def _approach(api, fx, approach_at, **fields):
    payload = {"vehicle_id": fx["vehicle"]["id"],
               "station_id": fx["station"]["id"],
               "approach_at": approach_at}
    payload.update(fields)
    return api.create_event(payload, GATEWAY)


class TestWeightEnforcement:
    def test_weight_exactly_at_limit_clears(self, api):
        """PRD §3.5: "When a reading is present, it is compared against the
        vehicle's `gvwr_lbs` plus an allowance of five percent of the rating —
        500 basis points, computed in whole pounds with any fractional pound
        discarded. A reading strictly above that limit fails as `OVERWEIGHT`;
        a reading exactly at the limit clears."
        PRD §3.5: "`weight_verified` is true exactly when a reading is
        present and at or under the allowance limit."

        Design: Difficulty/boundary_precision_check/wim_weight_at_tolerance_boundary
        """
        fx = setup_bypass_ready()
        set_clock("2026-08-05T12:00:00Z")
        # gvwr 80000 -> limit 80000 + floor(80000*500/10000) = 84000.
        data = validate_success(_approach(api, fx, "2026-08-05T10:00:00Z",
                                          measured_weight_lbs=84000,
                                          credentials_presented=FULL_CREDS),
                                expected_status=201)
        assert_event(data)
        assert data["decision"] == "BYPASS_GRANTED"
        assert data["decision_reasons"] == []
        assert data["weight_verified"] is True

    def test_weight_one_pound_over_limit_pulls_in(self, api):
        """PRD §3.5: "A reading strictly above that limit fails as
        `OVERWEIGHT`; a reading exactly at the limit clears."
        PRD §3.5: "`weight_verified` is true exactly when a reading is
        present and at or under the allowance limit."

        Design: Difficulty/boundary_precision_check/wim_weight_at_tolerance_boundary
        """
        fx = setup_bypass_ready()
        set_clock("2026-08-05T12:00:00Z")
        data = validate_success(_approach(api, fx, "2026-08-05T10:30:00Z",
                                          measured_weight_lbs=84001,
                                          credentials_presented=FULL_CREDS),
                                expected_status=201)
        assert data["decision"] == "PULL_IN"
        assert data["decision_reasons"] == ["OVERWEIGHT"]
        assert data["weight_verified"] is False

    def test_absent_reading_with_clearance_required(self, api):
        """PRD §3.5: "When no reading was captured and the state does require
        weight clearance, the event fails as `WEIGHT_NOT_CLEARED`."

        Design: Corner/calculations/weight_not_cleared_when_reading_absent
        """
        fx = setup_bypass_ready()
        set_clock("2026-08-05T12:00:00Z")
        data = validate_success(_approach(api, fx, "2026-08-05T10:00:00Z",
                                          credentials_presented=FULL_CREDS),
                                expected_status=201)
        assert data["decision"] == "PULL_IN"
        assert data["decision_reasons"] == ["WEIGHT_NOT_CLEARED"]
        assert data["weight_verified"] is False


class TestCheckPrecedence:
    def _setup_compound_failure(self, api):
        """Bypass-ready fixture, then the station closes temporarily and the
        carrier's posture collapses to INELIGIBLE (which cascade-suspends the
        credential and pauses the subscription)."""
        fx = setup_bypass_ready()
        validate_success(api.patch_station(fx["station"]["id"],
                                           {"operational_status": "CLOSED_TEMP"},
                                           SPM))
        post_snapshot(fx["carrier"]["id"], iss_score=90,
                      safety_rating="SATISFACTORY")
        set_clock("2026-08-05T12:00:00Z")
        return fx

    def test_station_availability_and_posture_outrank_later_checks(self, api):
        """PRD §3.5: "The first check that fails fixes the outcome as
        `PULL_IN` with exactly that check's single reason code stored in
        `decision_reasons`"; check 1 is "If the station's `operational_status`
        is anything other than `OPERATIONAL`, the reason is
        `STATION_NOT_OPERATIONAL`." and check 5 is "An `eligibility_status` of
        `INELIGIBLE` or `NOT_EVALUATED`: `CARRIER_INELIGIBLE`."

        Design: Difficulty/combinatorial_formula/decision_engine_branch_precedence_order
        """
        fx = self._setup_compound_failure(api)

        e1 = validate_success(_approach(api, fx, "2026-08-05T10:00:00Z",
                                        measured_weight_lbs=90000,
                                        credentials_presented=FULL_CREDS),
                              expected_status=201)
        assert e1["decision"] == "PULL_IN"
        assert e1["decision_reasons"] == ["STATION_NOT_OPERATIONAL"], \
            "check 1 fires although the carrier is INELIGIBLE and the reading is over the limit"

        validate_success(api.patch_station(fx["station"]["id"],
                                           {"operational_status": "OPERATIONAL"},
                                           SPM))
        e2 = validate_success(_approach(api, fx, "2026-08-05T10:30:00Z",
                                        measured_weight_lbs=90000,
                                        credentials_presented=FULL_CREDS),
                              expected_status=201)
        assert e2["decision"] == "PULL_IN"
        assert e2["decision_reasons"] == ["CARRIER_INELIGIBLE"], \
            "check 5 fires although the credential is suspended and the reading is over the limit"

    def test_credential_then_weight_then_clean_grant(self, api):
        """PRD §3.5: check 8 is "With no credential of the vehicle in
        `ACTIVE` status: `NO_ACTIVE_CREDENTIAL`." and only "a clean pass
        through all fourteen yields `BYPASS_GRANTED` with an empty
        `decision_reasons`."
        PRD §3.4: "Reactivation reverses that bookkeeping: the vehicle's
        `PAUSED` subscription returns to `ACTIVE`, the day count between the
        recorded `paused_at` date and the resume date is added to
        `paused_days_current_period`, and `paused_at` is cleared."

        Design: Difficulty/combinatorial_formula/decision_engine_branch_precedence_order
        """
        fx = self._setup_compound_failure(api)
        validate_success(api.patch_station(fx["station"]["id"],
                                           {"operational_status": "OPERATIONAL"},
                                           SPM))
        # Posture recovers; the cascade-suspended credential stays suspended.
        post_snapshot(fx["carrier"]["id"], iss_score=20,
                      safety_rating="SATISFACTORY", effective_date="2026-08-05")
        assert get_carrier(fx["carrier"]["id"])["eligibility_status"] == "ELIGIBLE"

        e3 = validate_success(_approach(api, fx, "2026-08-05T11:00:00Z",
                                        measured_weight_lbs=90000,
                                        credentials_presented=FULL_CREDS),
                              expected_status=201)
        assert e3["decision"] == "PULL_IN"
        assert e3["decision_reasons"] == ["NO_ACTIVE_CREDENTIAL"]

        reactivated = activate_credential(fx["credential"]["id"], fx["carrier"]["id"])
        assert reactivated["status"] == "ACTIVE"
        sub = validate_success(api.get_subscription(fx["subscription"]["id"], FINANCE))
        assert sub["status"] == "ACTIVE", "PAUSED covering subscription auto-resumes"
        assert sub["paused_days_current_period"] == 4, \
            "2026-08-01 pause to the 2026-08-05 resume accrues four paused days"
        assert sub["paused_at"] is None

        e4 = validate_success(_approach(api, fx, "2026-08-05T11:30:00Z",
                                        measured_weight_lbs=90000,
                                        credentials_presented=FULL_CREDS),
                              expected_status=201)
        assert e4["decision"] == "PULL_IN"
        assert e4["decision_reasons"] == ["OVERWEIGHT"]

        e5 = validate_success(_approach(api, fx, "2026-08-05T12:00:00Z",
                                        measured_weight_lbs=80000,
                                        credentials_presented=FULL_CREDS),
                              expected_status=201)
        assert e5["decision"] == "BYPASS_GRANTED"
        assert e5["decision_reasons"] == []
        assert e5["weight_verified"] is True


class TestRateCap:
    def _setup_capped_fixture(self, api):
        fx = setup_bypass_ready(config_fields={
            "requires_weight_clearance": False,
            "random_pull_in_rate_bps": 0,
            "bypass_rate_cap_bps": 5000,
        })
        set_clock("2026-08-05T12:00:00Z")
        return fx

    def test_rate_cap_first_reject_then_equality_grant(self, api):
        """PRD §3.5: "The grant is permitted only when one more than the
        grants-so-far, multiplied by ten thousand, is no greater than the cap
        multiplied by one more than the approaches-so-far; equality permits
        the bypass."
        PRD §3.5: "the engine reads two pre-decision counters and freezes
        them onto the event as `cap_granted_before` ... and
        `cap_total_before`"

        Design: Difficulty/combinatorial_formula/rate_cap_self_referential_counter_order
        """
        fx = self._setup_capped_fixture(api)
        e1 = validate_success(_approach(api, fx, "2026-08-05T10:00:00Z",
                                        credentials_presented=FULL_CREDS),
                              expected_status=201)
        assert e1["decision"] == "PULL_IN"
        assert e1["decision_reasons"] == ["RATE_CAP_EXCEEDED"]
        assert e1["cap_granted_before"] == 0 and e1["cap_total_before"] == 0

        e2 = validate_success(_approach(api, fx, "2026-08-05T10:30:00Z",
                                        credentials_presented=FULL_CREDS),
                              expected_status=201)
        assert e2["decision"] == "BYPASS_GRANTED", \
            "equality (10000 <= 5000*2) permits the bypass"
        assert e2["cap_granted_before"] == 0 and e2["cap_total_before"] == 1

    def test_rate_cap_counter_progression_across_events(self, api):
        """PRD §3.5: "Evaluation order is pinned: counters are read before
        the decision, the decision is computed, and only then are the bucket
        counters and the station's screen ordinal advanced — exactly once per
        recorded event."

        Design: Difficulty/combinatorial_formula/rate_cap_self_referential_counter_order
        """
        fx = self._setup_capped_fixture(api)
        times = ["10:00:00", "10:30:00", "11:00:00", "11:30:00"]
        events = [validate_success(_approach(api, fx, f"2026-08-05T{t}Z",
                                             credentials_presented=FULL_CREDS),
                                   expected_status=201)
                  for t in times]
        assert [e["decision"] for e in events] == [
            "PULL_IN", "BYPASS_GRANTED", "PULL_IN", "BYPASS_GRANTED"]
        assert events[2]["decision_reasons"] == ["RATE_CAP_EXCEEDED"]
        # The pre-decision total counter advances exactly once per event.
        assert [e["cap_total_before"] for e in events] == [0, 1, 2, 3]
        assert [e["cap_granted_before"] for e in events] == [0, 0, 1, 1]

    def test_conditional_carrier_cap_is_halved(self, api):
        """PRD §3.5: "The cap itself is the config's `bypass_rate_cap_bps`,
        halved with the fraction discarded when the carrier's posture is
        `CONDITIONAL`."
        PRD §3.2: "failing that, a rating of `CONDITIONAL`, or an `iss_score`
        of 50 or higher, yields `CONDITIONAL`"

        Design: Corner/calculations/conditional_carrier_cap_halved_pattern
        """
        fx = setup_bypass_ready(
            config_fields={"requires_weight_clearance": False,
                           "random_pull_in_rate_bps": 0,
                           "bypass_rate_cap_bps": 5000},
            iss_score=60)
        assert fx["carrier"]["eligibility_status"] == "CONDITIONAL"
        set_clock("2026-08-05T12:00:00Z")
        # Effective cap floor(5000/2) = 2500 bps.
        decisions = []
        for t in ("10:00:00", "10:30:00", "11:00:00", "11:30:00"):
            e = validate_success(_approach(api, fx, f"2026-08-05T{t}Z",
                                           credentials_presented=FULL_CREDS),
                                 expected_status=201)
            decisions.append(e)
        assert [e["decision"] for e in decisions] == [
            "PULL_IN", "PULL_IN", "PULL_IN", "BYPASS_GRANTED"]
        for e in decisions[:3]:
            assert e["decision_reasons"] == ["RATE_CAP_EXCEEDED"]
        assert decisions[3]["cap_granted_before"] == 0
        assert decisions[3]["cap_total_before"] == 3, \
            "fourth approach: 10000 <= 2500*4 holds with equality"


class TestDeterministicScreen:
    def test_every_nth_approach_is_screened(self, api):
        """PRD §3.5: "Otherwise, divide ten thousand by the configured rate
        and discard the fraction to get the period N — a rate of 5,000 basis
        points pulls in every second approach ... Each approach's ordinal is
        one plus the count of bypass events already recorded at the same
        station whose `approach_at` falls on the same calendar day; the
        screen fires exactly when that ordinal is a whole multiple of N, and
        the firing ordinal is preserved on the event as `screen_index` (null
        when the screen did not fire)."

        Design: Corner/calculations/deterministic_screen_every_nth_fires
        """
        fx = setup_bypass_ready(config_fields={
            "requires_weight_clearance": False,
            "random_pull_in_rate_bps": 5000,
            "bypass_rate_cap_bps": 10000,
        })
        set_clock("2026-08-05T12:00:00Z")
        events = [validate_success(_approach(api, fx, f"2026-08-05T{t}Z",
                                             credentials_presented=FULL_CREDS),
                                   expected_status=201)
                  for t in ("10:00:00", "10:30:00", "11:00:00", "11:30:00")]
        assert events[0]["decision"] == "BYPASS_GRANTED"
        assert events[0]["screen_index"] is None
        assert events[1]["decision"] == "PULL_IN"
        assert events[1]["decision_reasons"] == ["RANDOM_SCREEN"]
        assert events[1]["screen_index"] == 2
        assert events[2]["decision"] == "BYPASS_GRANTED"
        assert events[2]["screen_index"] is None
        assert events[3]["decision"] == "PULL_IN"
        assert events[3]["decision_reasons"] == ["RANDOM_SCREEN"]
        assert events[3]["screen_index"] == 4


class TestStateRuleDifferences:
    def _setup_two_state_fixture(self, api, config_a_fields, config_b_fields,
                                 iss_score=60):
        set_clock()
        cfg_a = create_config(state_code="CA", promote_to_participating=True,
                              **config_a_fields)
        cfg_b = create_config(state_code="NV", promote_to_participating=True,
                              **config_b_fields)
        st_a = create_station(cfg_a["id"], station_code="CA-S1")
        st_b = create_station(cfg_b["id"], station_code="NV-S1")
        carrier = create_active_carrier(iss_score=iss_score)
        vehicle = create_vehicle_for(carrier["id"], vin="VIN-0001")
        create_subscription_for(carrier["id"], vehicle["id"])
        cred = create_credential_for(vehicle["id"], carrier["id"])
        activate_credential(cred["id"], carrier["id"])
        set_clock("2026-08-05T12:00:00Z")
        return carrier, vehicle, st_a, st_b

    def test_state_threshold_difference(self, api):
        """PRD §3.5: "If the carrier's `latest_iss_score` is at least the
        config's `iss_refusal_threshold`: `ISS_ABOVE_STATE_THRESHOLD` — a
        carrier can pass the posture gate and still be refused by a stricter
        state line."

        Design: Corner/calculations/state_threshold_difference_pulls_in
        """
        carrier, vehicle, st_ca, st_nv = self._setup_two_state_fixture(
            api,
            {"iss_refusal_threshold": 60, "requires_weight_clearance": False,
             "random_pull_in_rate_bps": 0, "bypass_rate_cap_bps": 10000},
            {"iss_refusal_threshold": 75, "requires_weight_clearance": False,
             "random_pull_in_rate_bps": 0, "bypass_rate_cap_bps": 10000})
        assert get_carrier(carrier["id"])["latest_iss_score"] == 60

        ca = validate_success(api.create_event(
            {"vehicle_id": vehicle["id"], "station_id": st_ca["id"],
             "approach_at": "2026-08-05T10:00:00Z",
             "credentials_presented": FULL_CREDS}, GATEWAY), expected_status=201)
        assert ca["decision"] == "PULL_IN"
        assert ca["decision_reasons"] == ["ISS_ABOVE_STATE_THRESHOLD"], \
            "60 >= 60 refuses at the CA line"

        nv = validate_success(api.create_event(
            {"vehicle_id": vehicle["id"], "station_id": st_nv["id"],
             "approach_at": "2026-08-05T10:30:00Z",
             "credentials_presented": FULL_CREDS}, GATEWAY), expected_status=201)
        assert nv["decision"] == "PULL_IN"
        assert nv["decision_reasons"] == ["RATE_CAP_EXCEEDED"], \
            "60 < 75 clears the NV state line, but the CONDITIONAL posture " \
            "halves the cap to 5000 bps: (0+1)*10000 > 5000*(0+1) on the " \
            "bucket's first approach"

        nv2 = validate_success(api.create_event(
            {"vehicle_id": vehicle["id"], "station_id": st_nv["id"],
             "approach_at": "2026-08-05T11:00:00Z",
             "credentials_presented": FULL_CREDS}, GATEWAY), expected_status=201)
        assert nv2["decision"] == "BYPASS_GRANTED", \
            "second NV approach: (0+1)*10000 <= 5000*(1+1) with equality, " \
            "so the same carrier is granted at the looser state line"

    def test_hazmat_state_difference(self, api):
        """PRD §3.5: "A `hazmat_load` approach in a state whose
        `hazmat_bypass_allowed` is false: `HAZMAT_NOT_PERMITTED`."

        Design: Corner/calculations/hazmat_state_difference
        """
        carrier, vehicle, st_ca, st_nv = self._setup_two_state_fixture(
            api,
            {"hazmat_bypass_allowed": False, "requires_weight_clearance": False,
             "random_pull_in_rate_bps": 0, "bypass_rate_cap_bps": 10000},
            {"hazmat_bypass_allowed": True, "requires_weight_clearance": False,
             "random_pull_in_rate_bps": 0, "bypass_rate_cap_bps": 10000},
            iss_score=30)

        ca = validate_success(api.create_event(
            {"vehicle_id": vehicle["id"], "station_id": st_ca["id"],
             "approach_at": "2026-08-05T10:00:00Z", "hazmat_load": True,
             "credentials_presented": FULL_CREDS}, GATEWAY), expected_status=201)
        assert ca["decision"] == "PULL_IN"
        assert ca["decision_reasons"] == ["HAZMAT_NOT_PERMITTED"]

        nv = validate_success(api.create_event(
            {"vehicle_id": vehicle["id"], "station_id": st_nv["id"],
             "approach_at": "2026-08-05T10:30:00Z", "hazmat_load": True,
             "credentials_presented": FULL_CREDS}, GATEWAY), expected_status=201)
        assert nv["decision"] == "BYPASS_GRANTED"


class TestChannelAndStationType:
    def test_pilot_channel_selection_rules(self, api):
        """PRD §3.5: "From the vehicle's `ACTIVE` credentials, the selector
        drops any whose `device_type` does not match the station's
        `supported_channel` unless the station supports `BOTH`; if that
        empties the candidate set, the reason is `CHANNEL_UNSUPPORTED`. Among
        the survivors, a config in `PILOT` prefers `MOBILE_APP` and any other
        config prefers `TRANSPONDER`, with remaining ties broken toward the
        earliest `created_at` — never by identifier. The chosen credential is
        recorded as `selected_credential_id` (null whenever no credential is
        `ACTIVE`). Finally, in a `PILOT` state, if the selected credential is
        not a `MOBILE_APP` credential, the event fails as `PILOT_APP_ONLY`."

        Design: Corner/cross_cutting_layers/decision_reasons_channel_pilot_mobile
        """
        set_clock()
        config = create_config(
            state_code="CA", promote_to_participating=False,
            requires_weight_clearance=False, random_pull_in_rate_bps=0,
            bypass_rate_cap_bps=10000)
        assert config["participation_status"] == "PILOT"
        st_both = create_station(config["id"], station_code="CA-S1",
                                 supported_channel="BOTH")
        st_tp = create_station(config["id"], station_code="CA-S2",
                               supported_channel="TRANSPONDER")
        carrier = create_active_carrier()
        cm = make_carrier_manager_headers(carrier["id"])
        veh1 = create_vehicle_for(carrier["id"], vin="VIN-0001", plate_number="P-1")
        veh2 = create_vehicle_for(carrier["id"], vin="VIN-0002", plate_number="P-2")
        create_subscription_for(carrier["id"], veh1["id"])
        create_subscription_for(carrier["id"], veh2["id"])
        cred_app = create_credential_for(veh1["id"], carrier["id"],
                                         device_type="MOBILE_APP",
                                         device_serial="SN-A1")
        activate_credential(cred_app["id"], carrier["id"])
        cred_tp2 = create_credential_for(veh2["id"], carrier["id"],
                                         device_type="TRANSPONDER",
                                         device_serial="SN-T2")
        activate_credential(cred_tp2["id"], carrier["id"])
        set_clock("2026-08-05T12:00:00Z")

        d1 = validate_success(api.create_event(
            {"vehicle_id": veh1["id"], "station_id": st_tp["id"],
             "approach_at": "2026-08-05T10:00:00Z",
             "credentials_presented": FULL_CREDS}, GATEWAY), expected_status=201)
        assert d1["decision"] == "PULL_IN"
        assert d1["decision_reasons"] == ["CHANNEL_UNSUPPORTED"]

        d2 = validate_success(api.create_event(
            {"vehicle_id": veh1["id"], "station_id": st_both["id"],
             "approach_at": "2026-08-05T10:30:00Z",
             "credentials_presented": FULL_CREDS}, GATEWAY), expected_status=201)
        assert d2["decision"] == "BYPASS_GRANTED"
        assert d2["selected_credential_id"] == cred_app["id"]

        cred_tp1 = create_credential_for(veh1["id"], carrier["id"],
                                         device_type="TRANSPONDER",
                                         device_serial="SN-T1")
        activate_credential(cred_tp1["id"], carrier["id"])
        d3 = validate_success(api.create_event(
            {"vehicle_id": veh1["id"], "station_id": st_both["id"],
             "approach_at": "2026-08-05T11:00:00Z",
             "credentials_presented": FULL_CREDS}, GATEWAY), expected_status=201)
        assert d3["decision"] == "BYPASS_GRANTED"
        assert d3["selected_credential_id"] == cred_app["id"], \
            "a PILOT config prefers MOBILE_APP even when a transponder is also ACTIVE"

        d4 = validate_success(api.create_event(
            {"vehicle_id": veh2["id"], "station_id": st_both["id"],
             "approach_at": "2026-08-05T11:30:00Z",
             "credentials_presented": FULL_CREDS}, GATEWAY), expected_status=201)
        assert d4["decision"] == "PULL_IN"
        assert d4["decision_reasons"] == ["PILOT_APP_ONLY"]
        assert d4["selected_credential_id"] == cred_tp2["id"]

    def test_mobile_patrol_vehicle_oos_and_suspended_carrier_reasons(self, api):
        """PRD §3.5: "A `MOBILE_PATROL` station never bypasses:
        `STATION_TYPE_NO_BYPASS`."; "Anything other than `IN_SERVICE`:
        `VEHICLE_OUT_OF_SERVICE`."; "If the carrier's `status` is not
        `ACTIVE`: `CARRIER_NOT_ACTIVE`."
        PRD §3.5: "The first check that fails fixes the outcome as `PULL_IN`
        with exactly that check's single reason code" — the carrier
        lifecycle check precedes the vehicle status check.

        Design: Corner/cross_cutting_layers/decision_mobile_patrol_and_vehicle_oos_reasons
        """
        fx = setup_bypass_ready(config_fields={
            "requires_weight_clearance": False,
            "random_pull_in_rate_bps": 0,
            "bypass_rate_cap_bps": 10000,
        })
        patrol = create_station(fx["config"]["id"], station_code="CA-MP",
                                station_type="MOBILE_PATROL",
                                supported_channel="BOTH")
        set_clock("2026-08-05T12:00:00Z")

        m1 = validate_success(api.create_event(
            {"vehicle_id": fx["vehicle"]["id"], "station_id": patrol["id"],
             "approach_at": "2026-08-05T10:00:00Z",
             "credentials_presented": FULL_CREDS}, GATEWAY), expected_status=201)
        assert m1["decision"] == "PULL_IN"
        assert m1["decision_reasons"] == ["STATION_TYPE_NO_BYPASS"]

        cm = fx["cm_headers"]
        validate_success(api.patch_vehicle(fx["vehicle"]["id"],
                                           {"service_status": "OUT_OF_SERVICE"}, cm))
        m2 = validate_success(_approach(api, fx, "2026-08-05T10:30:00Z",
                                        credentials_presented=FULL_CREDS),
                              expected_status=201)
        assert m2["decision"] == "PULL_IN"
        assert m2["decision_reasons"] == ["VEHICLE_OUT_OF_SERVICE"]

        transition_carrier(fx["carrier"]["id"], "SUSPENDED")
        m3 = validate_success(_approach(api, fx, "2026-08-05T11:00:00Z",
                                        credentials_presented=FULL_CREDS),
                              expected_status=201)
        assert m3["decision"] == "PULL_IN"
        assert m3["decision_reasons"] == ["CARRIER_NOT_ACTIVE"], \
            "the carrier lifecycle check precedes the vehicle status check"


class TestRulesetPinningAndImmutability:
    def test_event_under_suspended_config_pins_ruleset(self, api):
        """PRD §3.5: "A config whose `participation_status` is `SUSPENDED`
        pulls everyone in: `STATE_NOT_PARTICIPATING`."
        PRD §2.7: "Because each event pins `ruleset_version`, later patches
        to a state program config are never retroactive: they raise the
        config's `version` and govern only decisions made after the patch."

        Design: Difficulty/cross_entity_state_dependency/bypass_decision_depends_on_config_participation
        """
        fx = setup_bypass_ready()
        set_clock("2026-08-05T12:00:00Z")
        suspended_cfg = patch_config(fx["config"]["id"], fx["config"]["version"],
                                     participation_status="SUSPENDED")

        p1 = validate_success(_approach(api, fx, "2026-08-05T10:00:00Z",
                                        measured_weight_lbs=80000,
                                        credentials_presented=FULL_CREDS),
                              expected_status=201)
        assert p1["decision"] == "PULL_IN"
        assert p1["decision_reasons"] == ["STATE_NOT_PARTICIPATING"]
        assert p1["ruleset_version"] == suspended_cfg["version"], \
            "the event pins the config version in force at decision time"

    def test_resume_governs_only_later_events(self, api):
        """PRD §2.7: "Its `decision` and `decision_reasons` are computed at
        creation and never change afterward, and the same is true of every
        supporting fact the engine froze onto the record"
        PRD §2.7: "Because each event pins `ruleset_version`, later patches
        to a state program config are never retroactive: they raise the
        config's `version` and govern only decisions made after the patch."

        Design: Difficulty/cross_entity_state_dependency/bypass_decision_depends_on_config_participation
        """
        fx = setup_bypass_ready()
        set_clock("2026-08-05T12:00:00Z")
        suspended_cfg = patch_config(fx["config"]["id"], fx["config"]["version"],
                                     participation_status="SUSPENDED")
        p1 = validate_success(_approach(api, fx, "2026-08-05T10:00:00Z",
                                        measured_weight_lbs=80000,
                                        credentials_presented=FULL_CREDS),
                              expected_status=201)
        resumed_cfg = patch_config(fx["config"]["id"], suspended_cfg["version"],
                                   participation_status="PARTICIPATING")

        p2 = validate_success(_approach(api, fx, "2026-08-05T10:30:00Z",
                                        measured_weight_lbs=80000,
                                        credentials_presented=FULL_CREDS),
                              expected_status=201)
        assert p2["decision"] == "BYPASS_GRANTED"
        assert p2["ruleset_version"] == resumed_cfg["version"]

        reread = validate_success(api.get_event(p1["id"], FINANCE))
        assert reread["decision"] == "PULL_IN"
        assert reread["decision_reasons"] == ["STATE_NOT_PARTICIPATING"]
        assert reread["ruleset_version"] == suspended_cfg["version"], \
            "the recorded event still describes the rule set that produced it"

    def test_event_record_is_append_only_and_immutable(self, api):
        """PRD §2.5: "Three record types are append-only feed or audit
        records and carry only `id` and `created_at`: safety-score snapshots,
        bypass events, and inspection reports. On those records, both
        `updated_at` and `version` are absent."
        PRD §2.7: "Its `decision` and `decision_reasons` are computed at
        creation and never change afterward"

        Design: Corner/entities/bypass_event_immutability_common_fields
        """
        fx = setup_bypass_ready()
        set_clock("2026-08-05T12:00:00Z")
        data = validate_success(_approach(api, fx, "2026-08-05T10:00:00Z",
                                          measured_weight_lbs=80000,
                                          credentials_presented=FULL_CREDS),
                                expected_status=201)
        assert_event(data)
        assert "version" not in data and "updated_at" not in data
        assert data["decision"] == "BYPASS_GRANTED"
        assert data["decision_reasons"] == []
        assert data["ruleset_version"] == fx["config"]["version"]

        events = list_events_for(carrier_id=fx["carrier"]["id"])
        assert len(events) == 1
        assert events[0]["decision"] == "BYPASS_GRANTED"
        assert "version" not in events[0] and "updated_at" not in events[0]


class TestFeedTimeliness:
    def _minimal_fixture(self, api):
        set_clock()
        config = create_config(state_code="CA")
        station = create_station(config["id"], station_code="CA-S1")
        carrier = create_active_carrier()
        vehicle = create_vehicle_for(carrier["id"])
        return station, vehicle

    def test_future_approach_rejected(self, api):
        """PRD §3.5: "an approach timestamped after the logical now is
        `ERR_FUTURE_APPROACH` (HTTP 400)"

        Design: Corner/validations/event_future_approach_returns_400
        """
        station, vehicle = self._minimal_fixture(api)
        set_clock("2026-08-05T12:00:00Z")
        resp = api.create_event(
            {"vehicle_id": vehicle["id"], "station_id": station["id"],
             "approach_at": "2026-08-06T00:00:00Z"}, GATEWAY)
        validate_error(resp, ApiErrorId.ERR_FUTURE_APPROACH)
        events, meta = validate_paginated(api.list_events(FINANCE))
        assert events == [] and meta["total_count"] == 0, "no event persisted"

    def test_stale_approach_rejected(self, api):
        """PRD §3.5: "one older than forty-eight hours before now is rejected
        as late-arriving with `ERR_STALE_APPROACH` (HTTP 422)"

        Design: Corner/validations/event_stale_approach_returns_422
        """
        station, vehicle = self._minimal_fixture(api)
        set_clock("2026-08-10T12:00:00Z")
        resp = api.create_event(
            {"vehicle_id": vehicle["id"], "station_id": station["id"],
             "approach_at": "2026-08-05T10:00:00Z"}, GATEWAY)
        validate_error(resp, ApiErrorId.ERR_STALE_APPROACH)
