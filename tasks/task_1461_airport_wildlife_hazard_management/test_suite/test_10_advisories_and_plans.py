"""Operational advisories and annual plans: OCC stale-version rejection,
review/return cycle, terminal lockdown, duplicate-year guard, window checks."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_airport,
    create_biologist,
    create_regulator,
    create_draft_advisory,
    activate_advisory,
    create_draft_plan,
    submit_plan,
    approve_plan,
    publish_plan,
    get_airport,
    make_biologist_headers,
    make_regulator_headers,
    ApiErrorId,
)


def test_invalid_window_advisory_end_before_start(api):
    """PRD §3.5: "the `effective_from` and `effective_to` bounds (with
    `effective_to` strictly after `effective_from`)"
    PRD §2.6: "then temporal-window validity (`ERR_INVALID_WINDOW`)"

    Design: Corner/validations/invalid_window_advisory_end_before_start
    """
    set_clock()
    airport = create_airport(icao_code="KKKK", name="Kilo Airport")
    b1 = create_biologist(airport["id"], is_senior=True, certification_id="CERT-K01")
    res = api.create_operational_advisory(
        {
            "airport_id": airport["id"],
            "issued_by_biologist_id": b1["id"],
            "issued_at": "2026-07-15T10:00:00Z",
            "effective_from": "2026-08-01T00:00:00Z",
            "effective_to": "2026-07-01T00:00:00Z",
            "hazard_level": "ELEVATED",
            "reason_code": "OTHER",
        },
        make_biologist_headers(b1["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_WINDOW.value, expected_status=422)


def test_plan_duplicate_year_rejected(api):
    """PRD §3.6: "At most one plan per airport per year may be in
    `SUBMITTED_FOR_REVIEW`, `APPROVED`, or `PUBLISHED` at any time; a
    duplicate attempt surfaces `ERR_PLAN_DUPLICATE_YEAR` (HTTP 409), enforced
    both at creation and at submission."

    Design: Corner/validations/plan_duplicate_year_rejected
    """
    set_clock()
    airport = create_airport(icao_code="KLLL", name="Lima Airport")
    b1 = create_biologist(airport["id"], is_senior=True, certification_id="CERT-L01")
    plan1 = create_draft_plan(airport["id"], b1, plan_year=2027, version_note="v1")
    submit_plan(plan1["id"], b1)

    res = api.create_annual_plan(
        {"airport_id": airport["id"], "plan_year": 2027,
         "version_note": "v2 duplicate"},
        make_biologist_headers(b1["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PLAN_DUPLICATE_YEAR.value, expected_status=409)


class TestAnnualPlanReviewCycle:
    """The DRAFT -> SUBMITTED_FOR_REVIEW -> RETURNED -> DRAFT loop can repeat
    before approval."""

    def _setup_plan(self, icao_code, cert, badge):
        set_clock()
        airport = create_airport(icao_code=icao_code)
        b1 = create_biologist(airport["id"], is_senior=True,
                              full_name="B One", certification_id=cert)
        reg = create_regulator(agency="USFWS", badge_number=badge)
        plan = create_draft_plan(airport["id"], b1, plan_year=2027,
                                 version_note="v1")
        return airport, b1, reg, plan

    def test_return_revision_cycle_reaches_approved_with_version_six(self, api):
        """PRD §3.6: "A `RegulatorAgent` may return the plan
        (`SUBMITTED_FOR_REVIEW → RETURNED`) or approve it
        (`SUBMITTED_FOR_REVIEW → APPROVED`); approval stamps
        `approved_by_regulator_id`. A returned plan can be revised by a
        biologist back to `DRAFT` (`RETURNED → DRAFT`)."
        PRD §2.4: "a `version` integer that starts at 1 and is incremented by
        1 on every state transition or other mutation of that resource."

        Design: Difficulty/non_linear_state_machine/annual_plan_review_return_revision_cycle
        """
        airport, b1, reg, plan = self._setup_plan("KEEE", "CERT-401", "USFWS-9101")
        b1h = make_biologist_headers(b1["id"])

        submit_plan(plan["id"], b1)
        validate_success(api.return_annual_plan_for_revision(plan["id"], make_regulator_headers(reg["id"])), 200)
        validate_success(api.revise_annual_plan(plan["id"], b1h), 200)
        submit_plan(plan["id"], b1)
        approved = approve_plan(plan["id"], reg)

        assert approved["status"] == "APPROVED"
        fetched = validate_success(api.get_annual_plan(plan["id"], b1h), 200)
        assert fetched["version"] == 6, (
            f"create=1 plus five transitions must yield version 6, got "
            f"{fetched['version']}"
        )
        assert fetched["approved_by_regulator_id"] == reg["id"]

    def test_each_cycle_step_lands_in_expected_state(self, api):
        """PRD §3.6: "Submission moves `DRAFT → SUBMITTED_FOR_REVIEW` and
        stamps `submitted_at`" and "A returned plan can be revised by a
        biologist back to `DRAFT` (`RETURNED → DRAFT`)."

        Design: Difficulty/non_linear_state_machine/annual_plan_review_return_revision_cycle
        """
        airport, b1, reg, plan = self._setup_plan("KEEF", "CERT-402", "USFWS-9102")
        b1h = make_biologist_headers(b1["id"])
        rh = make_regulator_headers(reg["id"])

        submitted = validate_success(api.submit_annual_plan(plan["id"], b1h), 200)
        assert submitted["status"] == "SUBMITTED_FOR_REVIEW"
        assert submitted["submitted_at"], "submission must stamp submitted_at"

        returned = validate_success(
            api.return_annual_plan_for_revision(plan["id"], rh), 200,
        )
        assert returned["status"] == "RETURNED"

        revised = validate_success(api.revise_annual_plan(plan["id"], b1h), 200)
        assert revised["status"] == "DRAFT"

        resubmitted = validate_success(api.submit_annual_plan(plan["id"], b1h), 200)
        assert resubmitted["status"] == "SUBMITTED_FOR_REVIEW"


def test_annual_plan_terminal_lockdown(api):
    """PRD §3.6: "Publication moves `APPROVED → PUBLISHED`, is blocked while
    the airport is at `CRITICAL`, stamps `published_at`, and — because it
    supersedes any prior published plan for the same airport — both cascades
    that prior plan to `SUPERSEDED` and bumps the airport's `version`."
    PRD §2.6: "A request failing several of these surfaces only the earliest
    error in this order." (state-machine legality surfaces
    `ERR_INVALID_STATE`; PUBLISHED is terminal, so a further submit is an
    illegal transition.)

    Design: Corner/state_machines/annual_plan_terminal_lockdown
    """
    set_clock()
    airport = create_airport(icao_code="KEEG", name="Echo Airport")
    b1 = create_biologist(airport["id"], is_senior=True, certification_id="CERT-E01")
    reg = create_regulator(agency="USFWS", badge_number="USFWS-9601")
    plan = create_draft_plan(airport["id"], b1, plan_year=2027, version_note="v1")
    submit_plan(plan["id"], b1)
    approve_plan(plan["id"], reg)
    published = publish_plan(plan["id"], b1, airport["id"])
    assert published["status"] == "PUBLISHED"

    res = api.submit_annual_plan(plan["id"], make_biologist_headers(b1["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


class TestOptimisticConcurrencyOnAirport:
    """expected_airport_version guards both advisory activation and plan
    publication against stale views of the parent airport."""

    def test_advisory_activate_stale_airport_occ_conflict(self, api):
        """PRD §2.7: "Both advisory activation and annual-plan publication
        accept a required `expected_airport_version` field in the request
        body. If the supplied value does not match the `Airport` record's
        current `version`, the write is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/advisory_activate_stale_airport_occ_conflict
        """
        set_clock()
        airport = create_airport(icao_code="KSSS", name="Sierra Airport")
        b1 = create_biologist(airport["id"], is_senior=True, certification_id="CERT-S01")
        b1h = make_biologist_headers(b1["id"])
        oa1 = create_draft_advisory(
            airport["id"], b1, hazard_level="ELEVATED",
            reason_code="STRIKE_SPIKE", issued_at="2026-07-15T10:00:00Z",
        )
        oa2 = create_draft_advisory(
            airport["id"], b1, hazard_level="HIGH",
            reason_code="MIGRATION", issued_at="2026-07-15T11:00:00Z",
        )

        observed_version = get_airport(airport["id"], b1h)["version"]
        # First activation succeeds and mutates the airport (hazard recompute
        # is persisted), advancing its version.
        activated = validate_success(
            api.activate_operational_advisory(
                oa1["id"], {"expected_airport_version": observed_version}, b1h,
            ),
            200,
        )
        assert activated["status"] == "ACTIVE"

        res = api.activate_operational_advisory(
            oa2["id"], {"expected_airport_version": observed_version}, b1h,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

        oa2_after = validate_success(api.get_operational_advisory(oa2["id"], b1h), 200)
        assert oa2_after["status"] == "DRAFT"

    def test_plan_publish_stale_airport_occ_conflict(self, api):
        """PRD §3.6: "Because publication mutates the airport, the publish
        call also requires `expected_airport_version`; a stale value is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.6: "both cascades that prior plan to `SUPERSEDED` and bumps the
        airport's `version`."

        Design: Corner/cross_cutting_complexity_layers/plan_publish_stale_airport_occ_conflict
        """
        set_clock()
        airport = create_airport(icao_code="KTTT", name="Tango Airport")
        b1 = create_biologist(airport["id"], is_senior=True, certification_id="CERT-T01")
        reg = create_regulator(agency="USFWS", badge_number="USFWS-9801")
        b1h = make_biologist_headers(b1["id"])

        plan1 = create_draft_plan(airport["id"], b1, plan_year=2027, version_note="v2027")
        submit_plan(plan1["id"], b1)
        approve_plan(plan1["id"], reg)
        plan2 = create_draft_plan(airport["id"], b1, plan_year=2028, version_note="v2028")
        submit_plan(plan2["id"], b1)
        approve_plan(plan2["id"], reg)

        observed_version = get_airport(airport["id"], b1h)["version"]
        published = validate_success(
            api.publish_annual_plan(
                plan1["id"], {"expected_airport_version": observed_version}, b1h,
            ),
            200,
        )
        assert published["status"] == "PUBLISHED"

        res = api.publish_annual_plan(
            plan2["id"], {"expected_airport_version": observed_version}, b1h,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

        plan2_after = validate_success(api.get_annual_plan(plan2["id"], b1h), 200)
        assert plan2_after["status"] == "APPROVED"
