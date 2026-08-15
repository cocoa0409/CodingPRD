"""Nexus case thresholds, confirmation gate, and the WATCH/THRESHOLD_MET cycle."""
from test_helpers import (
    ANALYST,
    ApiErrorId,
    approve_location_change,
    create_employee,
    create_nexus_case_payload,
    create_work_location,
    get_success_data,
    open_nexus_case,
    recompute_nexus_case,
    set_clock,
    setup_employee_or_to_nj,
    submit_location_change,
    validate_error,
    validate_success,
)


class TestNexusDayThresholdBoundary:
    def test_nexus_case_watch_at_19_days(self, api):
        """PRD §3.3: "Nexus thresholds are fixed: at least 20 attributable employee-days,
        or `wages_ytd_cents` of at least 5,000,000 cents (fifty thousand dollars). The
        computed `threshold_basis` records which are met — `NONE`, `DAYS`, `WAGES`, or
        `BOTH`."

        Design: Difficulty/boundary_precision_check/nexus_day_threshold_exactly_20
        """
        location = create_work_location("OR")
        create_employee(location["id"], employee_ref="E-1001", full_name="T One",
                        resident_state_code="OR", annual_wage_cents=3_000_000)
        case = open_nexus_case("OR")
        set_clock("2026-08-19T00:00:00Z")
        res = api.recompute_nexus_case(case["id"], ANALYST)
        data = validate_success(res, 200)
        assert data["employee_days_ytd"] == 19, (
            "hired 2026-08-01, clock 2026-08-19 -> 19 inclusive days"
        )
        assert data["status"] == "WATCH"
        assert data["threshold_basis"] == "NONE"

    def test_nexus_case_threshold_met_at_exactly_20_days(self, api):
        """PRD §3.3: "Nexus thresholds are fixed: at least 20 attributable employee-days,
        or `wages_ytd_cents` of at least 5,000,000 cents (fifty thousand dollars)."
        PRD §3.3: "Recomputation drives the cyclic core of the case: from `WATCH`, a
        basis other than `NONE` moves the case to `THRESHOLD_MET`"
        PRD §3.3: "`wages_ytd_cents`, the sum over employees of each employee's
        `annual_wage_cents` multiplied by that employee's year-to-date days in the
        state and divided by 365 — each employee's figure is rounded half up to cents
        before the per-employee figures are summed, and that order is pinned."

        Design: Difficulty/boundary_precision_check/nexus_day_threshold_exactly_20
        """
        location = create_work_location("OR")
        create_employee(location["id"], employee_ref="E-1001", full_name="T One",
                        resident_state_code="OR", annual_wage_cents=3_000_000)
        case = open_nexus_case("OR")
        set_clock("2026-08-20T00:00:00Z")
        res = api.recompute_nexus_case(case["id"], ANALYST)
        data = validate_success(res, 200)
        assert data["employee_days_ytd"] == 20
        assert data["status"] == "THRESHOLD_MET"
        assert data["threshold_basis"] == "DAYS", (
            "wage track is 164,384 cents (< 5,000,000), so only the DAYS basis fired"
        )
        assert data["wages_ytd_cents"] == 164_384, (
            "round_half_up(3,000,000 * 20 / 365) == 164,384"
        )


class TestNexusConfirmGate:
    def test_nexus_confirm_from_watch_rejected(self, api, nexus_analyst_headers):
        """PRD §3.3: "Confirmation is the human gate: a `NexusAnalyst` confirms a case
        only from `THRESHOLD_MET` (any other state draws `ERR_INVALID_STATE_TRANSITION`),
        moving it to `CONFIRMED` and stamping `established_date` with the clock; posture
        recomputes."

        Design: Corner/state_machines/nexus_confirm_from_watch_rejected
        """
        res = api.create_nexus_case(create_nexus_case_payload("OR"), nexus_analyst_headers)
        case = validate_success(res, 201)
        assert case["status"] == "WATCH", (
            "no employees exist, so the initial recompute finds zero days"
        )
        err = api.confirm_nexus_case(case["id"], nexus_analyst_headers)
        validate_error(err, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        still = get_success_data(api.get_nexus_case(case["id"], nexus_analyst_headers))
        assert still["status"] == "WATCH"

    def test_duplicate_nexus_case_rejected(self, api, nexus_analyst_headers):
        """PRD §3.3: "Only one case per state may exist among the statuses `WATCH`,
        `THRESHOLD_MET`, `CONFIRMED`, and `LAPSED`; a duplicate is rejected with
        `ERR_DUPLICATE_NEXUS_CASE`."

        Design: Corner/validations/duplicate_nexus_case_rejected
        """
        open_nexus_case("OR")
        res = api.create_nexus_case(create_nexus_case_payload("OR"), nexus_analyst_headers)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_NEXUS_CASE)


class TestNexusWatchThresholdWatchCycle:
    def _setup_move_scenario(self):
        """Employee in OR (hired 2026-08-01), OR + NJ cases, OR case THRESHOLD_MET at
        2026-08-20, and an APPROVED OR->NJ location change effective 2026-08-20."""
        out = setup_employee_or_to_nj(employee_ref="E-601", with_employer=True)
        employee = out["employee"]
        or_case = open_nexus_case("OR")
        nj_case = open_nexus_case("NJ")
        set_clock("2026-08-20T00:00:00Z")
        or_before = recompute_nexus_case(or_case["id"])
        change = validate_success(
            submit_location_change(
                employee, out["nj_location"]["id"],
                effective_date="2026-08-20T00:00:00Z", reason="Relocating",
            ),
            201,
        )
        approve_location_change(change["id"], user_id="na-1")
        out.update(or_case=or_case, nj_case=nj_case, or_before=or_before,
                   change=change)
        return out

    def test_or_case_reaches_threshold_met_at_20_days(self, api):
        """PRD §3.3: "Recomputation drives the cyclic core of the case: from `WATCH`, a
        basis other than `NONE` moves the case to `THRESHOLD_MET`"

        Design: Difficulty/non_linear_state_machine/nexus_case_watch_threshold_watch_cycle
        """
        scenario = self._setup_move_scenario()
        assert scenario["or_before"]["status"] == "THRESHOLD_MET"
        assert scenario["or_before"]["employee_days_ytd"] == 20

    def test_or_case_returns_to_watch_after_effectuation(self, api, tax_director_headers):
        """PRD §3.3: "from `THRESHOLD_MET`, a basis of `NONE` returns it to `WATCH`
        (for example when a reversed location change removes days)."
        PRD §3.6: "Once the clock reaches `effective_date`, an `APPROVED` change
        becomes `EFFECTIVE`"

        Design: Difficulty/non_linear_state_machine/nexus_case_watch_threshold_watch_cycle
        """
        scenario = self._setup_move_scenario()
        assert scenario["or_before"]["status"] == "THRESHOLD_MET"
        set_clock("2026-08-20T00:00:00Z")  # sweep effectuates the APPROVED change
        change = get_success_data(
            api.get_location_change(scenario["change"]["id"], tax_director_headers)
        )
        assert change["status"] == "EFFECTIVE"
        res = api.recompute_nexus_case(scenario["or_case"]["id"], ANALYST)
        data = validate_success(res, 200)
        assert data["employee_days_ytd"] == 19, (
            "OR segment truncated at 2026-08-20 -> Aug 1..19 remain attributed to OR"
        )
        assert data["status"] == "WATCH"
