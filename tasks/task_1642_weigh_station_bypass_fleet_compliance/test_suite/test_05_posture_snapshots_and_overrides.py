"""Safety-score ingestion, eligibility posture bands, optimistic concurrency,
and eligibility override windows and version pinning."""
from test_helpers import (
    FEED,
    FINANCE,
    OFFICER,
    SPM,
    ApiErrorId,
    activate_credential,
    create_carrier,
    create_config,
    create_credential_for,
    create_subscription_for,
    create_vehicle_for,
    get_carrier,
    list_credentials_for,
    list_subscriptions_for,
    make_carrier_manager_headers,
    make_compliance_officer_headers,
    patch_config,
    post_event,
    post_snapshot,
    request_override,
    set_clock,
    setup_bypass_ready,
    transition_carrier,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPostureBoundaries:
    def test_iss_49_eligible_and_iss_50_conditional(self, api):
        """PRD §3.2: "The boundaries are inclusive at the lower edge of each
        band: a score of exactly 75 is `INELIGIBLE`, 74 is `CONDITIONAL`,
        exactly 50 is `CONDITIONAL`, and 49 is `ELIGIBLE`."

        Design: Corner/calculations/iss_conditional_floor_50_boundary
        """
        set_clock()
        car_a = create_carrier(dot_number="100001", legal_name="Carrier A")
        car_b = create_carrier(dot_number="100002", legal_name="Carrier B")
        post_snapshot(car_a["id"], iss_score=49,
                      expected_carrier_version=car_a["version"])
        post_snapshot(car_b["id"], iss_score=50,
                      expected_carrier_version=car_b["version"])
        assert get_carrier(car_a["id"])["eligibility_status"] == "ELIGIBLE"
        assert get_carrier(car_b["id"])["eligibility_status"] == "CONDITIONAL"

    def test_iss_74_conditional_and_approvable(self, api):
        """PRD §3.2: "a score of exactly 75 is `INELIGIBLE`, 74 is
        `CONDITIONAL`"
        PRD §3.1: "the transition is permitted only when the carrier's
        posture is `ELIGIBLE` or `CONDITIONAL`"

        Design: Difficulty/boundary_precision_check/iss_score_74_vs_75_posture_boundary
        """
        set_clock()
        carrier = create_carrier(dot_number="100001", legal_name="Boundary A")
        post_snapshot(carrier["id"], iss_score=74,
                      expected_carrier_version=carrier["version"])
        fresh = get_carrier(carrier["id"])
        assert fresh["eligibility_status"] == "CONDITIONAL"
        assert fresh["latest_iss_score"] == 74
        approved = transition_carrier(carrier["id"], "ACTIVE")
        assert approved["status"] == "ACTIVE", \
            "a CONDITIONAL posture may be approved to ACTIVE"

    def test_iss_75_ineligible_and_approval_rejected(self, api):
        """PRD §3.2: "a score of exactly 75 is `INELIGIBLE`, 74 is
        `CONDITIONAL`"
        PRD §3.1: "a carrier whose posture is `NOT_EVALUATED` or `INELIGIBLE`
        is rejected with `ERR_CARRIER_INELIGIBLE_FOR_APPROVAL` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/iss_score_74_vs_75_posture_boundary
        """
        set_clock()
        carrier = create_carrier(dot_number="100002", legal_name="Boundary B")
        post_snapshot(carrier["id"], iss_score=75,
                      expected_carrier_version=carrier["version"])
        fresh = get_carrier(carrier["id"])
        assert fresh["eligibility_status"] == "INELIGIBLE"
        assert fresh["latest_iss_score"] == 75
        resp = api.transition_carrier(carrier["id"], "ACTIVE", OFFICER)
        validate_error(resp, ApiErrorId.ERR_CARRIER_INELIGIBLE_FOR_APPROVAL)
        assert get_carrier(carrier["id"])["status"] == "ENROLLED"


class TestOptimisticConcurrency:
    def test_snapshot_post_with_stale_carrier_version(self, api):
        """PRD §2.9: "Posting a safety-score snapshot requires
        `expected_carrier_version` ... A mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.2: "Posting a snapshot also increments the carrier's `version`
        by one"

        Design: Corner/validations/snapshot_occ_stale_version_returns_412
        """
        set_clock()
        carrier = create_carrier(dot_number="100001", legal_name="Acme Hauling")
        v0 = carrier["version"]
        post_snapshot(carrier["id"], iss_score=30, expected_carrier_version=v0)
        assert get_carrier(carrier["id"])["version"] == v0 + 1

        resp = api.create_snapshot(
            {"carrier_id": carrier["id"], "iss_score": 40,
             "safety_rating": "SATISFACTORY", "source": "FMCSA_FEED",
             "effective_date": "2026-08-01", "expected_carrier_version": v0},
            FEED)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        snaps, meta = validate_paginated(api.list_snapshots(
            FEED, params={"carrier_id": carrier["id"]}))
        assert len(snaps) == 1 and meta["total_count"] == 1, \
            "the rejected write added no snapshot row"

    def test_config_patch_with_stale_version(self, api):
        """PRD §2.9: "patching a state program config requires
        `expected_state_program_config_version`. In each case the token is a
        non-optional input field and must equal the parent entity's current
        `version` at write time. A mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.3: "`bypass_rate_cap_bps` defaults to 10000 and spans 1 to
        10000"

        Design: Corner/validations/config_patch_occ_stale_returns_412
        """
        config = create_config(state_code="CA")
        v0 = config["version"]
        patched = patch_config(config["id"], v0, random_pull_in_rate_bps=500)
        assert patched["random_pull_in_rate_bps"] == 500

        resp = api.patch_config(
            config["id"],
            {"bypass_rate_cap_bps": 8000,
             "expected_state_program_config_version": v0},
            SPM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fresh = validate_success(api.get_config(config["id"], FINANCE))
        assert fresh["version"] == patched["version"], \
            "the rejected patch did not advance the config version"
        assert fresh["bypass_rate_cap_bps"] == 10000
        assert fresh["random_pull_in_rate_bps"] == 500

    def test_override_request_with_stale_carrier_version(self, api):
        """PRD §2.9: "requesting an eligibility override requires
        `expected_carrier_version` ... A mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412): a feed operating on a stale carrier
        view cannot silently reorder the score history"

        Design: Corner/validations/override_request_occ_stale_returns_412
        """
        set_clock()
        carrier = create_carrier(dot_number="100001", legal_name="Acme Hauling")
        stale_version = carrier["version"]  # observed at onboarding; the
        # snapshot and approval below each advance the carrier's version
        post_snapshot(carrier["id"], iss_score=30,
                      expected_carrier_version=stale_version)
        transition_carrier(carrier["id"], "ACTIVE")
        cm = make_carrier_manager_headers(carrier["id"])
        resp = api.create_override(
            {"carrier_id": carrier["id"], "reason": "stale view of carrier",
             "start_date": "2026-09-01", "end_date": "2026-10-01",
             "expected_carrier_version": stale_version},
            cm)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestSnapshotInputValidation:
    def test_iss_score_out_of_range(self, api):
        """PRD §3.2: "an `iss_score` from 0 to 100 where higher is worse
        (outside that range: `ERR_INVALID_ISS_SCORE`, HTTP 400)"

        Design: Corner/validations/snapshot_iss_out_of_range_returns_400
        """
        set_clock()
        carrier = create_carrier(dot_number="100001", legal_name="Acme Hauling")
        resp = api.create_snapshot(
            {"carrier_id": carrier["id"], "iss_score": 101,
             "safety_rating": "SATISFACTORY", "source": "FMCSA_FEED",
             "effective_date": "2026-08-01",
             "expected_carrier_version": carrier["version"]},
            FEED)
        validate_error(resp, ApiErrorId.ERR_INVALID_ISS_SCORE)

    def test_future_effective_date_rejected(self, api):
        """PRD §3.2: "the `effective_date` on which the score takes effect —
        never a future date, or the post fails with `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/snapshot_future_effective_returns_400
        """
        set_clock()
        carrier = create_carrier(dot_number="100001", legal_name="Acme Hauling")
        resp = api.create_snapshot(
            {"carrier_id": carrier["id"], "iss_score": 30,
             "safety_rating": "SATISFACTORY", "source": "FMCSA_FEED",
             "effective_date": "2026-08-02",
             "expected_carrier_version": carrier["version"]},
            FEED)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


class TestOverrideAdmission:
    def test_override_request_without_any_snapshot(self, api):
        """PRD §3.7: "the carrier must have at least one safety snapshot on
        file, since a waiver with no score history to waive is meaningless —
        that failure is `ERR_NO_SAFETY_SNAPSHOT` (HTTP 422)."

        Design: Corner/validations/override_without_snapshot_returns_422
        """
        set_clock()
        carrier = create_carrier(dot_number="100001", legal_name="Acme Hauling")
        # ENROLLED with no snapshot: override requests are accepted for
        # ENROLLED carriers, so the snapshot-presence gate is what fires.
        cm = make_carrier_manager_headers(carrier["id"])
        resp = api.create_override(
            {"carrier_id": carrier["id"], "reason": "no score yet",
             "start_date": "2026-08-01", "end_date": "2026-09-01",
             "expected_carrier_version": carrier["version"]},
            cm)
        validate_error(resp, ApiErrorId.ERR_NO_SAFETY_SNAPSHOT)


class TestLatestSnapshotReconciliation:
    def test_out_of_order_feed_keeps_latest_by_effective_date(self, api):
        """PRD §3.2: "The carrier keeps a derived pointer to its latest
        snapshot: `latest_snapshot_id` names the snapshot with the greatest
        `effective_date`, ties broken toward the most recently created
        record, and `latest_iss_score` and `latest_safety_rating` mirror that
        snapshot's values."

        Design: Corner/cross_cutting_layers/out_of_order_snapshot_keeps_latest_by_effective_date
        """
        set_clock("2026-08-10T12:00:00Z")
        carrier = create_carrier(dot_number="100001", legal_name="Acme Hauling")
        snap1 = post_snapshot(carrier["id"], iss_score=40,
                              effective_date="2026-08-10",
                              expected_carrier_version=carrier["version"])
        snap2 = post_snapshot(carrier["id"], iss_score=95,
                              safety_rating="UNSATISFACTORY",
                              source="MANUAL_AUDIT", effective_date="2026-08-05")
        fresh = get_carrier(carrier["id"])
        assert fresh["latest_snapshot_id"] == snap1["id"], \
            "effective_date 2026-08-10 beats the older 2026-08-05 row"
        assert fresh["latest_iss_score"] == 40
        assert fresh["eligibility_status"] == "ELIGIBLE", \
            "the out-of-order iss-95 row does not flip the posture"
        snaps, meta = validate_paginated(api.list_snapshots(
            FEED, params={"carrier_id": carrier["id"]}))
        assert len(snaps) == 2 and meta["total_count"] == 2, \
            "append-only history preserves both snapshots"
        assert snap2["id"] in {s["id"] for s in snaps}


class TestSafetyDeactivationCascade:
    def _setup_three_vehicle_fleet(self, api):
        """Carrier ACTIVE with three vehicles: veh1 and veh2 hold ACTIVE
        credentials and subscriptions; veh3 holds only a PROVISIONED
        credential alongside its subscription."""
        fx = setup_bypass_ready()
        carrier_id = fx["carrier"]["id"]
        veh2 = create_vehicle_for(carrier_id, vin="VIN-0002", plate_number="P-2")
        sub2 = create_subscription_for(carrier_id, veh2["id"])
        cred2 = activate_credential(
            create_credential_for(veh2["id"], carrier_id,
                                  device_serial="SN-0002")["id"], carrier_id)
        veh3 = create_vehicle_for(carrier_id, vin="VIN-0003", plate_number="P-3")
        sub3 = create_subscription_for(carrier_id, veh3["id"])
        cred3 = create_credential_for(veh3["id"], carrier_id,
                                      device_serial="SN-0003")
        set_clock("2026-08-20T12:00:00Z")
        fx.update({"veh2": veh2, "sub2": sub2, "cred2": cred2,
                   "veh3": veh3, "sub3": sub3, "cred3": cred3})
        return fx

    def test_cascade_suspends_only_active_credentials(self, api):
        """PRD §3.2: "Entering `INELIGIBLE` fires the safety deactivation
        cascade, and its effects are visible in the triggering response
        itself: every credential of the carrier in `ACTIVE` moves to
        `SUSPENDED` with `status_reason` `SAFETY_INELIGIBLE`"
        PRD §3.2: "An `ACTIVE` carrier whose posture collapses keeps its
        `ACTIVE` status"

        Design: Difficulty/transitive_cascade/safety_snapshot_deep_cascade
        """
        fx = self._setup_three_vehicle_fleet(api)
        post_snapshot(fx["carrier"]["id"], iss_score=90, effective_date="2026-08-20")

        carrier = get_carrier(fx["carrier"]["id"])
        assert carrier["eligibility_status"] == "INELIGIBLE"
        assert carrier["status"] == "ACTIVE", \
            "posture never touches the lifecycle machine"

        creds = {c["id"]: c for c in list_credentials_for(
            carrier_id=fx["carrier"]["id"])}
        for active_id in (fx["credential"]["id"], fx["cred2"]["id"]):
            assert creds[active_id]["status"] == "SUSPENDED"
            assert creds[active_id]["status_reason"] == "SAFETY_INELIGIBLE"
        assert creds[fx["cred3"]["id"]]["status"] == "PROVISIONED", \
            "a credential that never reached ACTIVE is skipped by the cascade"
        assert creds[fx["cred3"]["id"]]["status_reason"] == "NONE"

    def test_cascade_pause_flows_through_the_credential_link(self, api):
        """PRD §3.2: "each such suspension pauses its vehicle's subscription
        (`ACTIVE` to `PAUSED`, `paused_at` set to today)"
        PRD §3.2: "every roadside approach it makes will pull in at the
        carrier-eligibility check of §3.5."

        Design: Difficulty/transitive_cascade/safety_snapshot_deep_cascade
        """
        fx = self._setup_three_vehicle_fleet(api)
        post_snapshot(fx["carrier"]["id"], iss_score=90, effective_date="2026-08-20")

        subs = {s["id"]: s for s in list_subscriptions_for(
            carrier_id=fx["carrier"]["id"])}
        for paused_id in (fx["subscription"]["id"], fx["sub2"]["id"]):
            assert subs[paused_id]["status"] == "PAUSED"
            assert subs[paused_id]["paused_at"] == "2026-08-20"
        assert subs[fx["sub3"]["id"]]["status"] == "ACTIVE", \
            "veh3's credential was never suspended, so its subscription is untouched"

        event = post_event(fx["vehicle"]["id"], fx["station"]["id"],
                           "2026-08-20T10:00:00Z", measured_weight_lbs=80000,
                           credentials_presented=["IFTA", "IRP", "UCR"])
        assert event["decision"] == "PULL_IN"
        assert event["decision_reasons"] == ["CARRIER_INELIGIBLE"]


class TestOverrideWindowsAndPinning:
    def _carrier_with_snapshot(self, api):
        set_clock()
        carrier = create_carrier(dot_number="100001", legal_name="Acme Hauling")
        post_snapshot(carrier["id"], iss_score=30,
                      expected_carrier_version=carrier["version"])
        return transition_carrier(carrier["id"], "ACTIVE")

    def test_override_half_open_adjacency_acceptance(self, api):
        """PRD §3.7: "Windows for the same carrier may not overlap while any
        of them is `REQUESTED`, `APPROVED`, or `ACTIVE`: the comparison is
        half-open, so a request whose start date equals an existing window's
        end date is adjacent, not overlapping, and is permitted; a true
        intersection is rejected with `ERR_OVERRIDE_WINDOW_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/override_windows_half_open_adjacency
        """
        carrier = self._carrier_with_snapshot(api)
        o1 = request_override(carrier["id"], start_date="2026-09-01",
                              end_date="2026-10-01", reason="audit under appeal")
        assert o1["status"] == "REQUESTED"
        o2 = request_override(carrier["id"], start_date="2026-10-01",
                              end_date="2026-11-01", reason="back-to-back extension")
        assert o2["status"] == "REQUESTED", \
            "start == existing end is adjacency under half-open semantics"

        cm = make_carrier_manager_headers(carrier["id"])
        resp = api.create_override(
            {"carrier_id": carrier["id"], "reason": "straddling window",
             "start_date": "2026-09-15", "end_date": "2026-10-15",
             "expected_carrier_version": get_carrier(carrier["id"])["version"]},
            cm)
        validate_error(resp, ApiErrorId.ERR_OVERRIDE_WINDOW_OVERLAP)

    def test_override_adjacent_predecessor_accepted(self, api):
        """PRD §3.7: "the comparison is half-open, so a request whose start
        date equals an existing window's end date is adjacent, not
        overlapping, and is permitted"

        Design: Difficulty/resource_temporal_overlap/override_windows_half_open_adjacency
        """
        carrier = self._carrier_with_snapshot(api)
        request_override(carrier["id"], start_date="2026-09-01",
                         end_date="2026-10-01", reason="audit under appeal")
        request_override(carrier["id"], start_date="2026-10-01",
                         end_date="2026-11-01", reason="back-to-back extension")
        o4 = request_override(carrier["id"], start_date="2026-08-01",
                              end_date="2026-09-01", reason="adjacent predecessor")
        assert o4["status"] == "REQUESTED", \
            "a window ending exactly when another begins is also adjacency"

        overrides, meta = validate_paginated(api.list_overrides(
            OFFICER, params={"carrier_id": carrier["id"]}))
        assert len(overrides) == 3 and meta["total_count"] == 3

    def test_override_goes_stale_on_newer_snapshot(self, api):
        """PRD §3.7: "when a snapshot newer than
        `approved_against_snapshot_id` becomes the carrier's latest, an
        `ACTIVE` override flips to `STALE`, terminal, and posture is
        recomputed from the new snapshot without it."
        PRD §3.7: "it then pins `approved_against_snapshot_id` to the
        carrier's `latest_snapshot_id` at that instant, records `decided_by`,
        and — when the start date has already arrived — moves the override
        straight to `ACTIVE` with an immediate posture recompute."

        Design: Corner/cross_cutting_layers/override_goes_stale_on_newer_snapshot
        """
        set_clock()
        carrier = create_carrier(dot_number="100001", legal_name="Acme Hauling")
        snap1 = post_snapshot(carrier["id"], iss_score=90,
                              safety_rating="CONDITIONAL",
                              expected_carrier_version=carrier["version"])
        assert get_carrier(carrier["id"])["eligibility_status"] == "INELIGIBLE"
        override = request_override(carrier["id"], start_date="2026-08-01",
                                    end_date="2026-09-01",
                                    reason="score under formal appeal")

        officer = make_compliance_officer_headers("officer-a")
        approved = validate_success(api.decide_override(override["id"], "APPROVE",
                                                        officer))
        assert approved["status"] == "ACTIVE", \
            "start date already arrived: straight to ACTIVE"
        assert approved["approved_against_snapshot_id"] == snap1["id"]
        assert approved["decided_by"] == "officer-a"
        assert get_carrier(carrier["id"])["eligibility_status"] == "ELIGIBLE", \
            "an in-force override forces posture ELIGIBLE"

        # Same effective_date but created later -> becomes the latest snapshot.
        post_snapshot(carrier["id"], iss_score=85, safety_rating="CONDITIONAL",
                      effective_date="2026-08-01")
        stale = validate_success(api.get_override(override["id"], OFFICER))
        assert stale["status"] == "STALE"
        assert get_carrier(carrier["id"])["eligibility_status"] == "INELIGIBLE", \
            "posture recomputes from the new snapshot without the override"

        resp = api.decide_override(override["id"], "REVOKE", officer)
        # STALE is terminal, so any further decision is a state violation.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
