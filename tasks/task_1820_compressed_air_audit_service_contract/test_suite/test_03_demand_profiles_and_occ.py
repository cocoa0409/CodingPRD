"""Demand profile annualization, window rules, baseline locking, OCC, and rebase."""
from test_helpers import (
    ApiErrorId,
    assert_demand_profile,
    assert_savings_case,
    create_compressor,
    create_demand_profile,
    create_demand_profile_payload,
    create_facility,
    create_retrofit_project,
    create_savings_case,
    approve_retrofit_project,
    get_facility_version,
    lock_demand_profile,
    make_contract_manager_headers,
    make_dealer_admin_headers,
    make_energy_engineer_headers,
    model_savings_case,
    validate_error,
    validate_success,
)

ADMIN = make_dealer_admin_headers()
ENGINEER = make_energy_engineer_headers("eng-1")
CONTRACT_MGR = make_contract_manager_headers()


class TestBaselineAnnualization:
    def test_baseline_annualization_computed(self, api):
        """PRD §3.3: "At creation the profile is `COLLECTING` and its
        `baseline_annual_kwh` is annualized: the measured kilowatt-hours are
        multiplied by 365 and divided by the window's length in days — counting both
        the first and the last calendar day of the window — with the result rounded
        half-up to a whole kilowatt-hour."

        Design: Corner/entities/corner_baseline_annualization_computed
        """
        facility = create_facility(name="F-ANN")
        profile = validate_success(
            api.create_demand_profile(
                create_demand_profile_payload(
                    facility_id=facility["id"],
                    window_start_date="2026-03-01",
                    window_end_date="2026-03-31",
                    measured_kwh=248000,
                    measured_avg_cfm=350.0,
                    measured_peak_cfm=520.0,
                ),
                ENGINEER,
            ),
            201,
        )
        assert_demand_profile(profile)
        assert profile["baseline_annual_kwh"] == 2920000, (
            f"248000 kWh over a 31-day inclusive window annualizes to 2920000, "
            f"got {profile['baseline_annual_kwh']}"
        )
        assert profile["status"] == "COLLECTING"

    def test_profile_window_end_before_start_returns_invalid_request(self, api):
        """PRD §3.3: "An end date earlier than the start date is an input failure
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/corner_profile_window_end_before_start_returns_invalid_request
        """
        facility = create_facility(name="F-WIN", activate=False)
        resp = api.create_demand_profile(
            create_demand_profile_payload(
                facility_id=facility["id"],
                window_start_date="2026-03-31",
                window_end_date="2026-03-01",
                measured_kwh=1000,
                measured_avg_cfm=10.0,
                measured_peak_cfm=20.0,
            ),
            ENGINEER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestWindowOverlap:
    def test_demand_profile_shared_day_overlap_rejected(self, api):
        """PRD §3.3: "The inclusive window of a new profile must not intersect the
        window of any other profile of the same facility that is `COLLECTING` or
        `LOCKED`; sharing even a single calendar day already counts as an
        intersection, with no buffer day granted, and a collision is rejected with
        `ERR_MEASUREMENT_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/demand_profile_closed_window_overlap
        """
        facility = create_facility(name="F-OV2")
        create_demand_profile(
            facility["id"],
            window_start_date="2026-03-01",
            window_end_date="2026-03-31",
            measured_kwh=248000,
        )

        resp = api.create_demand_profile(
            create_demand_profile_payload(
                facility_id=facility["id"],
                window_start_date="2026-03-31",
                window_end_date="2026-04-29",
                measured_kwh=230000,
                measured_avg_cfm=340.0,
                measured_peak_cfm=500.0,
            ),
            ENGINEER,
        )
        validate_error(resp, ApiErrorId.ERR_MEASUREMENT_WINDOW_OVERLAP, 409)

    def test_demand_profile_next_day_window_accepted(self, api):
        """PRD §3.3: "The inclusive window of a new profile must not intersect the
        window of any other profile of the same facility that is `COLLECTING` or
        `LOCKED`; sharing even a single calendar day already counts as an
        intersection, with no buffer day granted, and a collision is rejected with
        `ERR_MEASUREMENT_WINDOW_OVERLAP` (HTTP 409)."
        PRD §3.3: "the measured kilowatt-hours are multiplied by 365 and divided by
        the window's length in days — counting both the first and the last calendar
        day of the window — with the result rounded half-up to a whole kilowatt-hour."

        Design: Difficulty/resource_temporal_overlap/demand_profile_closed_window_overlap
        """
        facility = create_facility(name="F-OV2B")
        create_demand_profile(
            facility["id"],
            window_start_date="2026-03-01",
            window_end_date="2026-03-31",
            measured_kwh=248000,
        )

        profile = validate_success(
            api.create_demand_profile(
                create_demand_profile_payload(
                    facility_id=facility["id"],
                    window_start_date="2026-04-01",
                    window_end_date="2026-04-30",
                    measured_kwh=240000,
                    measured_avg_cfm=345.0,
                    measured_peak_cfm=510.0,
                ),
                ENGINEER,
            ),
            201,
        )
        assert profile["status"] == "COLLECTING"
        assert profile["baseline_annual_kwh"] == 2920000, (
            f"240000 kWh over 30 inclusive days annualizes to 2920000, "
            f"got {profile['baseline_annual_kwh']}"
        )


class TestBaselineLocking:
    def test_lock_requires_active_facility(self, api):
        """PRD §3.3: "An `EnergyEngineer` locks a `COLLECTING` profile; the gates
        are evaluated in order — the facility must be `ACTIVE`
        (`ERR_FACILITY_NOT_ACTIVE`), and then the optimistic-concurrency check of
        §2.7 applies, rejecting a stale `expected_facility_version` with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/corner_lock_requires_active_facility
        """
        facility = create_facility(name="F-LNA", activate=False)
        profile = create_demand_profile(facility["id"])
        version = get_facility_version(facility["id"])

        resp = api.lock_demand_profile(
            profile["id"],
            {"expected_facility_version": version},
            make_energy_engineer_headers("eng-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_ACTIVE, 409)
        profile = validate_success(api.get_demand_profile(profile["id"], ENGINEER))
        assert profile["status"] == "COLLECTING", "rejected lock must leave the profile COLLECTING"

    def test_occ_stale_lock_rejected(self, api):
        """PRD §2.7: "If the facility's current `version` no longer equals the
        supplied value — because another lock or contract activation has advanced it
        since the caller last read the facility — the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_lock_rejected
        """
        facility = create_facility(name="F-OCC1")
        p1 = create_demand_profile(
            facility["id"], window_start_date="2026-03-01", window_end_date="2026-03-31"
        )
        p2 = create_demand_profile(
            facility["id"],
            window_start_date="2026-04-01",
            window_end_date="2026-04-30",
            measured_kwh=240000,
        )
        stale_version = get_facility_version(facility["id"])

        lock_demand_profile(facility["id"], p1["id"], user_id="eng-1")

        resp = api.lock_demand_profile(
            p2["id"],
            {"expected_facility_version": stale_version},
            make_energy_engineer_headers("eng-2"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        p1 = validate_success(api.get_demand_profile(p1["id"], ENGINEER))
        p2 = validate_success(api.get_demand_profile(p2["id"], ENGINEER))
        assert p1["status"] == "LOCKED"
        assert p2["status"] == "COLLECTING", "stale lock must be rejected, leaving P2 COLLECTING"

    def test_occ_stale_activate_rejected(self, api):
        """PRD §2.7: "Two writes are guarded by optimistic concurrency control on
        the Facility, because each of them supersedes an incumbent: locking a demand
        profile retires the facility's previously `LOCKED` profile, and activating a
        service contract retires the facility's currently `ACTIVE` contract."
        PRD §2.7: "If the facility's current `version` no longer equals the supplied
        value — because another lock or contract activation has advanced it since
        the caller last read the facility — the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_activate_rejected
        """
        facility = create_facility(name="F-OCC2")
        sc1 = validate_success(
            api.create_service_contract(
                {
                    "facility_id": facility["id"],
                    "tier": "STANDARD",
                    "start_date": "2026-08-01",
                    "term_months": 12,
                    "monthly_fee_cents": 400000,
                },
                CONTRACT_MGR,
            ),
            201,
        )
        sc2 = validate_success(
            api.create_service_contract(
                {
                    "facility_id": facility["id"],
                    "tier": "PREMIUM",
                    "start_date": "2026-08-01",
                    "term_months": 12,
                    "monthly_fee_cents": 900000,
                },
                CONTRACT_MGR,
            ),
            201,
        )
        stale_version = get_facility_version(facility["id"])
        validate_success(
            api.activate_service_contract(
                sc1["id"], {"expected_facility_version": stale_version}, CONTRACT_MGR
            )
        )

        resp = api.activate_service_contract(
            sc2["id"], {"expected_facility_version": stale_version}, CONTRACT_MGR
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        sc1 = validate_success(api.get_service_contract(sc1["id"], CONTRACT_MGR))
        sc2 = validate_success(api.get_service_contract(sc2["id"], CONTRACT_MGR))
        assert sc1["status"] == "ACTIVE"
        assert sc2["status"] == "DRAFT", "stale activation must be rejected, leaving SC2 DRAFT"


class TestRebase:
    def test_rebase_clears_stale_baseline(self, api):
        """PRD §3.3: "The lock also supersedes: the facility's previously `LOCKED`
        profile, if one exists, is transitioned to the terminal `SUPERSEDED` state
        with its `superseded_by_id` pointing at the newly locked profile, and every
        SavingsCase that pinned the superseded profile while its `savings_status` is
        `DRAFT` or `MODELED` has `baseline_stale` set to true."
        PRD §3.6: "A rebase re-pins `baseline_profile_id` and
        `baseline_profile_version` to the facility's currently `LOCKED` profile and
        clears `baseline_stale`; when a replacement project is supplied, the case
        re-points to it and clears `retrofit_stale`. Either way, `savings_status`
        returns to `DRAFT` and `deemed_annual_savings_kwh` resets to 0 until the
        case is re-modeled."
        PRD §3.6: "The transition from `DRAFT` to `MODELED` is gated by three checks
        in a pinned order: `baseline_stale` must be false — when both staleness
        flags happen to be set, `ERR_BASELINE_SUPERSEDED` is reported rather than
        `ERR_RETROFIT_STALE` — then `retrofit_stale` must be false
        (`ERR_RETROFIT_STALE`), and finally the referenced project must still be
        `APPROVED` or later (`ERR_RETROFIT_NOT_APPROVED`)."

        Design: Corner/cross_cutting_complexity_layers/corner_rebase_clears_stale_baseline
        """
        facility = create_facility(name="F-RBS")
        compressor = create_compressor(facility["id"])
        p1 = create_demand_profile(
            facility["id"], window_start_date="2026-03-01", window_end_date="2026-03-31"
        )
        p1 = lock_demand_profile(facility["id"], p1["id"], user_id="eng-1")
        project = create_retrofit_project(facility["id"], [compressor["id"]])
        project = approve_retrofit_project(project["id"], facility["id"])
        case = create_savings_case(facility["id"], p1["id"], project["id"])

        p2 = create_demand_profile(
            facility["id"],
            window_start_date="2026-04-01",
            window_end_date="2026-04-30",
            measured_kwh=240000,
        )
        p2 = lock_demand_profile(facility["id"], p2["id"], user_id="eng-1")

        p1 = validate_success(api.get_demand_profile(p1["id"], ENGINEER))
        assert p1["status"] == "SUPERSEDED"
        assert p1["superseded_by_id"] == p2["id"]

        resp = api.model_savings_case(case["id"], ENGINEER)
        validate_error(resp, ApiErrorId.ERR_BASELINE_SUPERSEDED, 409)

        case = validate_success(api.rebase_savings_case(case["id"], {}, ENGINEER))
        assert_savings_case(case)
        assert case["baseline_profile_id"] == p2["id"], "rebase must re-pin to the currently LOCKED profile"
        assert case["baseline_stale"] is False
        assert case["savings_status"] == "DRAFT"

        case = model_savings_case(case["id"])
        assert case["savings_status"] == "MODELED"
        assert case["deemed_annual_savings_kwh"] == 496400, (
            f"rebased model over P2 (annualized 2920000) with a 20 psi capped drop "
            f"yields 2920000 x 0.17 = 496400, got {case['deemed_annual_savings_kwh']}"
        )
