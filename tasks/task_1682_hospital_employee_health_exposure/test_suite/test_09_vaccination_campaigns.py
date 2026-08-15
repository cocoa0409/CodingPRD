"""Vaccination campaigns: fan-out, participation outcomes, coverage accounting,
and the delinquency cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_campaign,
    assert_participation,
    assert_instant,
    create_campaign,
    create_campaign_payload,
    find_participation,
    get_campaign,
    get_employee,
    get_participation,
    list_holds,
    make_cleared_employee,
    make_staff_employee_headers,
    open_cycle,
    set_clock,
    transition_campaign,
    validate_error,
    validate_success,
)

FLU_WINDOW = ("2026-09-01T00:00:00Z", "2026-09-30T23:59:59Z")
AUG_WINDOW = ("2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")


def _open_campaign_with_participations(api, compliance_headers, employees,
                                       window=FLU_WINDOW, scope=("ICU", "ED"),
                                       vaccine_type="INFLUENZA"):
    """Create + OPEN a campaign; returns (campaign, {employee_id: participation})."""
    campaign = create_campaign(
        vaccine_type=vaccine_type, window_start=window[0], window_end=window[1],
        department_scope=list(scope),
    )
    transition_campaign(campaign["id"], "OPEN")
    parts = {emp["id"]: find_participation(campaign["id"], emp["id"])
             for emp in employees}
    return campaign, parts


class TestCoverageRoundingOrder:
    def test_per_department_then_mean_two_departments(self, api,
                                                      compliance_headers,
                                                      nurse_headers):
        """PRD §3.9: "The rate is computed per department first: for each
        department with at least one participation, the department rate is one
        hundred times the share of that department's participations in
        `ADMINISTERED` or `EXEMPTED` among all of the department's
        participations, rounded half-up to two decimal places. The
        `coverage_rate` is then the mean of those per-department rates, itself
        rounded half-up to two decimal places, with departments having zero
        participations excluded from the mean. Computing a single aggregate
        rate across all rows first and rounding once is forbidden — the
        rounding order is pinned, and the two orders can differ in the
        hundredths place for the same data."

        Design: Difficulty/combinatorial_formula/coverage_per_department_rounding_order
        """
        i1 = make_cleared_employee("E-CF2I1", full_name="Icu One")
        i2 = make_cleared_employee("E-CF2I2", full_name="Icu Two",
                                   hire_date="2025-01-06T00:00:00Z")
        d1 = make_cleared_employee("E-CF2D1", full_name="Ed One",
                                   job_category="TECH", department="ED",
                                   hire_date="2025-01-07T00:00:00Z")
        campaign, parts = _open_campaign_with_participations(
            api, compliance_headers, [i1, i2, d1],
        )
        assert all(p["status"] == "PENDING" for p in parts.values())

        set_clock("2026-09-10T00:00:00Z")
        for emp in (i1, d1):
            validate_success(api.transition_participation(
                parts[emp["id"]]["id"],
                {"to_state": "ADMINISTERED", "administered_at": "2026-09-10T00:00:00Z"},
                nurse_headers,
            ))

        cov = validate_success(api.get_campaign_coverage(campaign["id"],
                                                         compliance_headers))
        assert cov["administered_count"] == 2
        assert cov["pending_count"] == 1
        # ICU round_half_up(100*1/2, 2) = 50.00; ED = 100.00; mean = 75.00.
        assert float(cov["coverage_rate"]) == pytest.approx(75.00, abs=0.005)
        # The forbidden aggregate-first order would produce 200/3 = 66.67.
        assert abs(float(cov["coverage_rate"]) - 66.67) > 0.005

    def test_per_department_then_mean_three_departments(self, api,
                                                        compliance_headers,
                                                        nurse_headers):
        """PRD §3.9: "The `coverage_rate` is then the mean of those
        per-department rates, itself rounded half-up to two decimal places,
        with departments having zero participations excluded from the mean."

        Design: Difficulty/combinatorial_formula/coverage_per_department_rounding_order
        """
        i1 = make_cleared_employee("E-CF3I1", full_name="Icu A")
        d1 = make_cleared_employee("E-CF3D1", full_name="Ed A",
                                   job_category="TECH", department="ED",
                                   hire_date="2025-01-06T00:00:00Z")
        l1 = make_cleared_employee("E-CF3L1", full_name="Lab A",
                                   job_category="TECH", department="LAB",
                                   hire_date="2025-01-07T00:00:00Z")
        i2 = make_cleared_employee("E-CF3I2", full_name="Icu B",
                                   hire_date="2025-01-08T00:00:00Z")
        campaign, parts = _open_campaign_with_participations(
            api, compliance_headers, [i1, d1, l1, i2], scope=("ICU", "ED", "LAB"),
        )

        set_clock("2026-09-10T00:00:00Z")
        for emp in (i1, d1, l1):
            validate_success(api.transition_participation(
                parts[emp["id"]]["id"],
                {"to_state": "ADMINISTERED", "administered_at": "2026-09-10T00:00:00Z"},
                nurse_headers,
            ))

        cov = validate_success(api.get_campaign_coverage(campaign["id"],
                                                         compliance_headers))
        assert cov["administered_count"] == 3
        assert cov["pending_count"] == 1
        # Per department: ICU 50.00, ED 100.00, LAB 100.00; mean = 83.33.
        assert float(cov["coverage_rate"]) == pytest.approx(83.33, abs=0.005)
        # The forbidden aggregate-first order would produce 300/4 = 75.00.
        assert abs(float(cov["coverage_rate"]) - 75.00) > 0.005


class TestCampaignCloseDelinquencyCascade:
    def _setup_open_campaign_one_pending(self):
        emp = make_cleared_employee("E-TC1", full_name="Cas Cade")
        campaign = create_campaign(department_scope=["ALL"])
        transition_campaign(campaign["id"], "OPEN")
        part = find_participation(campaign["id"], emp["id"])
        assert part["status"] == "PENDING"
        set_clock("2026-10-01T00:00:00Z")  # strictly past window_end
        return emp, campaign, part

    def test_close_fires_delinquency_hold_suspension_chain(self, api,
                                                           compliance_headers):
        """PRD §3.9: "Closing triggers the delinquency cascade. Every
        participation still `PENDING` becomes `DELINQUENT`; each newly
        delinquent participation auto-creates a `ComplianceHold` in `ACTIVE`
        status with `reason` `CAMPAIGN_DELINQUENT` and its `participation_id`
        set, with `applied_at` stamped from the clock; and each new hold
        increments that employee's `active_hold_count` by one, so an `ACTIVE`
        employee whose count rises above zero transitions automatically to
        `SUSPENDED` with posture `ON_HOLD`."

        Design: Difficulty/transitive_cascade/campaign_close_delinquency_hold_suspension
        """
        emp, campaign, part = self._setup_open_campaign_one_pending()

        closed = transition_campaign(campaign["id"], "CLOSED")
        assert closed["status"] == "CLOSED"

        part_after = get_participation(part["id"])
        assert part_after["status"] == "DELINQUENT"

        holds = list_holds(emp["id"], status="ACTIVE")
        assert len(holds) == 1
        hold = holds[0]
        assert hold["reason"] == "CAMPAIGN_DELINQUENT"
        assert hold["participation_id"] == part["id"]
        assert hold["cycle_id"] is None

        emp_after = get_employee(emp["id"])
        assert emp_after["status"] == "SUSPENDED"
        assert emp_after["compliance_posture"] == "ON_HOLD"
        assert emp_after["active_hold_count"] == 1

    def test_campaign_hold_not_releasable_while_participation_delinquent(
            self, api, compliance_headers):
        """PRD §3.9: "These campaign holds follow the release rules of §3.3:
        releasable only when the linked participation has reached
        `ADMINISTERED`, `DECLINED`, or `EXEMPTED`, and releasable only by
        explicit compliance-officer action."
        PRD §3.3: "an unmet underlying requirement is rejected with
        `ERR_UNDERLYING_REQUIREMENT_UNMET`."

        Design: Difficulty/transitive_cascade/campaign_close_delinquency_hold_suspension
        """
        emp, campaign, part = self._setup_open_campaign_one_pending()
        transition_campaign(campaign["id"], "CLOSED")
        hold = list_holds(emp["id"], status="ACTIVE")[0]

        resp = api.release_hold(hold["id"], {}, compliance_headers)
        validate_error(resp, ApiErrorId.ERR_UNDERLYING_REQUIREMENT_UNMET)

        assert get_employee(emp["id"])["active_hold_count"] == 1
        hold_after = validate_success(api.get_hold(hold["id"], compliance_headers))
        assert hold_after["status"] == "ACTIVE"


class TestCampaignWindowOverlap:
    def test_touching_same_vaccine_window_rejected(self, api, compliance_headers):
        """PRD §3.9: "Campaigns of the same `vaccine_type` may not have windows
        that intersect or even touch: a new campaign whose `window_start` falls
        on or before an existing same-vaccine campaign's `window_end` while its
        own `window_end` falls on or after that campaign's `window_start` is
        rejected with `ERR_CAMPAIGN_WINDOW_OVERLAP`." (The window is a closed
        interval, so an endpoint shared with the incumbent belongs to both.)

        Design: Difficulty/resource_temporal_overlap/campaign_closed_interval_touch_conflict
        """
        c1 = create_campaign()
        assert c1["status"] == "PLANNED"

        touching = api.create_campaign(
            create_campaign_payload(
                window_start="2026-09-30T23:59:59Z",  # == C1 window_end
                window_end="2026-10-31T23:59:59Z",
            ),
            compliance_headers,
        )
        validate_error(touching, ApiErrorId.ERR_CAMPAIGN_WINDOW_OVERLAP)
        assert get_campaign(c1["id"])["status"] == "PLANNED"

    def test_disjoint_and_different_vaccine_windows_allowed(self, api,
                                                            compliance_headers):
        """PRD §3.9: "The campaign window is a closed interval: both
        `window_start` and `window_end` are inclusive." and "Windows of
        different vaccine types may overlap freely."

        Design: Difficulty/resource_temporal_overlap/campaign_closed_interval_touch_conflict
        """
        c1 = create_campaign()

        # One second after the incumbent's inclusive window_end: disjoint.
        c3 = validate_success(api.create_campaign(
            create_campaign_payload(window_start="2026-10-01T00:00:00Z",
                                    window_end="2026-10-31T23:59:59Z"),
            compliance_headers,
        ), expected_status=201)
        assert_campaign(c3)
        assert c3["status"] == "PLANNED"
        assert get_campaign(c1["id"])["status"] == "PLANNED"

        # A different vaccine type may reuse the exact same window.
        covid = validate_success(api.create_campaign(
            create_campaign_payload(vaccine_type="COVID"),
            compliance_headers,
        ), expected_status=201)
        assert covid["status"] == "PLANNED"


class TestCampaignCloseGate:
    def test_close_before_window_end_rejected(self, api, compliance_headers):
        """PRD §3.9: "the compliance officer's transition from `OPEN` to
        `CLOSED` requires the current logical time to be strictly later than
        `window_end`, and an earlier attempt is rejected with
        `ERR_CAMPAIGN_WINDOW_NOT_ENDED`."

        Design: Corner/state_machines/campaign_close_before_window_end_rejected
        """
        campaign = create_campaign()
        transition_campaign(campaign["id"], "OPEN")
        set_clock("2026-09-15T00:00:00Z")  # inside the window

        resp = api.transition_campaign(
            campaign["id"], {"to_state": "CLOSED"}, compliance_headers
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_NOT_ENDED)
        assert get_campaign(campaign["id"])["status"] == "OPEN"


class TestParticipationOutcomes:
    def _open_august_campaign(self, *employees):
        campaign = create_campaign(window_start=AUG_WINDOW[0],
                                   window_end=AUG_WINDOW[1],
                                   department_scope=["ALL"])
        transition_campaign(campaign["id"], "OPEN")
        return campaign, {e["id"]: find_participation(campaign["id"], e["id"])
                          for e in employees}

    def test_decline_after_administered_rejected(self, api, nurse_headers):
        """PRD §3.9: "While the campaign is `OPEN`, each participation resolves
        in one of three ways, each requiring the participation still be
        `PENDING` (`ERR_PARTICIPATION_NOT_PENDING`)."

        Design: Corner/state_machines/participation_decline_after_administered_rejected
        """
        emp = make_cleared_employee("E-SM15", full_name="Already Vax")
        _campaign, parts = self._open_august_campaign(emp)
        part = parts[emp["id"]]

        administered = validate_success(api.transition_participation(
            part["id"],
            {"to_state": "ADMINISTERED", "administered_at": "2026-08-01T00:00:00Z"},
            nurse_headers,
        ))
        assert administered["status"] == "ADMINISTERED"

        resp = api.transition_participation(
            part["id"],
            {"to_state": "DECLINED",
             "declination_reason": "already administered elsewhere"},
            make_staff_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARTICIPATION_NOT_PENDING)
        assert get_participation(part["id"])["status"] == "ADMINISTERED"

    def test_employee_declines_only_own_participation(self, api):
        """PRD §3.9: "The employee themself, acting as a `StaffEmployee` with
        `X-User-ID` equal to the participation's employee id
        (`ERR_OWNERSHIP_REQUIRED`), may decline by submitting `to_state`
        `DECLINED` with a non-empty `declination_reason`
        (`ERR_DECLINATION_REASON_REQUIRED`); declining stamps `declined_at`
        from the logical clock"

        Design: Corner/rbac/staff_employee_declines_only_own_participation
        """
        emp1 = make_cleared_employee("E-RB6A", full_name="Decline Self")
        emp2 = make_cleared_employee("E-RB6B", full_name="Other Part",
                                     job_category="TECH", department="LAB",
                                     hire_date="2025-01-06T00:00:00Z")
        _campaign, parts = self._open_august_campaign(emp1, emp2)

        # emp1 attempting to decline emp2's participation.
        other = api.transition_participation(
            parts[emp2["id"]]["id"],
            {"to_state": "DECLINED", "declination_reason": "personal choice"},
            make_staff_employee_headers(emp1["id"]),
        )
        validate_error(other, ApiErrorId.ERR_OWNERSHIP_REQUIRED)

        own = validate_success(api.transition_participation(
            parts[emp1["id"]]["id"],
            {"to_state": "DECLINED", "declination_reason": "personal choice"},
            make_staff_employee_headers(emp1["id"]),
        ))
        assert own["status"] == "DECLINED"
        assert_instant(own["declined_at"], "2026-08-01T00:00:00")

    def test_decline_without_reason_rejected(self, api):
        """PRD §3.9: "may decline by submitting `to_state` `DECLINED` with a
        non-empty `declination_reason` (`ERR_DECLINATION_REASON_REQUIRED`)";
        both `declined_at` and `declination_reason` remain null on
        participations that have not been declined."

        Design: Corner/rbac/participation_decline_missing_reason_rejected
        """
        emp = make_cleared_employee("E-RB7", full_name="No Reason")
        campaign = create_campaign(vaccine_type="COVID",
                                   window_start=AUG_WINDOW[0],
                                   window_end=AUG_WINDOW[1],
                                   department_scope=["ALL"])
        transition_campaign(campaign["id"], "OPEN")
        part = find_participation(campaign["id"], emp["id"])

        resp = api.transition_participation(
            part["id"], {"to_state": "DECLINED"},
            make_staff_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DECLINATION_REASON_REQUIRED)

        after = get_participation(part["id"])
        assert after["status"] == "PENDING"
        assert after["declined_at"] is None
        assert after["declination_reason"] is None

    def test_suspended_employee_cannot_be_administered(self, api, nurse_headers):
        """PRD §3.9: "the employee must be `ACTIVE` at administration time, so
        a suspended employee cannot be vaccinated into compliance
        (`ERR_EMPLOYEE_NOT_ACTIVE`)"

        Design: Corner/state_machines/suspended_employee_vaccination_blocked
        """
        emp = make_cleared_employee("E-SM16", full_name="Sus Pended",
                                    hire_date="2024-06-01T00:00:00Z")
        _campaign, parts = self._open_august_campaign(emp)
        part = parts[emp["id"]]

        # A 2025 cycle (due 2025-12-31T23:59:59Z) lapses when the clock moves,
        # suspending the employee via the overdue hold cascade.
        open_cycle(emp["id"], cycle_year=2025, cycle_mode="CALENDAR_YEAR")
        set_clock("2026-08-10T00:00:00Z")

        suspended = get_employee(emp["id"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["compliance_posture"] == "ON_HOLD"

        resp = api.transition_participation(
            part["id"],
            {"to_state": "ADMINISTERED", "administered_at": "2026-08-10T00:00:00Z"},
            nurse_headers,
        )
        validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_ACTIVE)
        assert get_participation(part["id"])["status"] == "PENDING"
