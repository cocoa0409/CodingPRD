"""Endpoint behaviour: the update that rewrites a derived block, the action that
moves an errored submission into its correction round, the two batch writers, the
cross-aggregate link check on attach-forms, and the derived monthly coverage-line
read reconciled against its parent statement's roll-ups.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_monthly_coverage_line,
    assert_transmittal,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

CO = TEST_USERS["compliance_officer"]
BA = TEST_USERS["benefits_admin"]
PREPARER = TEST_USERS["preparer"]


# ---------------------------------------------------------------------------
# World builders (compositions of test_helpers.fixtures / factories)
# ---------------------------------------------------------------------------
def _hire_salaried_employee(api, member_id, full_name, ssn_last4, **extra):
    """A salaried hire supplies `monthly_salary_cents` rather than an hourly rate,
    so the hourly figure is left out of the body entirely."""
    payload = factories.employee_payload(
        member_id,
        full_name,
        ssn_last4=ssn_last4,
        hire_date="2025-01-01",
        employment_type="FULL_TIME",
        is_hourly=False,
        monthly_salary_cents=400000,
        **extra,
    )
    payload.pop("hourly_rate_cents", None)
    return get_success_data(api.create_employee(payload, BA))


def _look_back_employee_with_two_hour_years(api):
    """A LOOK_BACK member with a standard cycle measuring 2025 and stabilising over
    2026; the employee's 2025 hours average 100 and its 2026 hours are 160."""
    ctx = fixtures.determined_ale_group_with_employee(
        api,
        member_measurement_method="LOOK_BACK",
        employee_overrides={
            "full_name": "Tomas Vega",
            "ssn_last4": "9090",
            "employment_type": "VARIABLE_HOUR",
            "is_hourly": True,
            "hourly_rate_cents": 1500,
        },
    )
    fixtures.create_measurement_cycle(
        api,
        ctx["member"]["id"],
        headers=CO,
        cycle_type="STANDARD",
        measurement_start_date="2025-01-01",
        measurement_end_date="2025-12-31",
        admin_period_end_date="2025-12-31",
        stability_start_date="2026-01-01",
        stability_end_date="2026-12-31",
        hours_threshold_monthly=130,
    )
    employee_id = ctx["employee"]["id"]
    fixtures.record_hours(api, employee_id, 2025, headers=BA, hours_of_service=100)
    fixtures.record_hours(api, employee_id, 2026, headers=BA, hours_of_service=160)
    get_success_data(api.recompute_employee_full_time(employee_id, BA))
    return ctx


def _transmittal_accepted_with_one_warning(api):
    """One statement carried to the agency, which answered ACCEPTED_WITH_ERRORS
    with a single WARNING-severity error naming that statement."""
    ctx = fixtures.determined_ale_group(api)
    member_id = ctx["member"]["id"]
    employee = _hire_salaried_employee(api, member_id, "Lena Ortiz", "4321")
    form = fixtures.generate_form(api, employee["id"], plan_start_month=1)
    transmittal = fixtures.open_transmittal(api, member_id)
    fixtures.attach_forms(api, transmittal["id"], [form["id"]])
    fixtures.build_transmittal(api, transmittal["id"])
    fixtures.transmit_transmittal(api, transmittal["id"], "ELECTRONIC")
    fixtures.record_agency_response(
        api,
        transmittal["id"],
        "ACCEPTED_WITH_ERRORS",
        "AIR-2026-1010",
        errors=[
            factories.agency_error_row(
                form["id"],
                error_code="AIRTN200",
                error_field="plan_start_month",
                severity="WARNING",
            )
        ],
    )
    ctx["employee"] = employee
    ctx["form"] = form
    ctx["transmittal"] = transmittal
    return ctx


def _monthly_employee_without_hours(api):
    return fixtures.determined_ale_group_with_employee(
        api,
        employee_overrides={
            "full_name": "Rosa Klein",
            "ssn_last4": "6060",
            "employment_type": "VARIABLE_HOUR",
            "is_hourly": True,
            "hourly_rate_cents": 1500,
        },
    )


def _two_members_each_with_a_statement(api):
    """A determined-ALE group with ACTIVE members A and B, one statement under
    each, and a DRAFT transmittal opened on member A."""
    season = fixtures.create_filing_season(api, CO)
    group = fixtures.create_controlled_group(api, season["id"], CO)
    member_a = fixtures.create_group_member(
        api,
        group["id"],
        ein="999999991",
        headers=CO,
        legal_name="Ironwood Main",
        ownership_pct=60,
        measurement_method="MONTHLY",
    )
    member_b = fixtures.create_group_member(
        api,
        group["id"],
        ein="999999992",
        headers=CO,
        legal_name="Ironwood Annex",
        ownership_pct=40,
        measurement_method="MONTHLY",
    )
    fixtures.record_headcounts(api, member_a["id"], headers=CO)
    fixtures.record_headcounts(
        api,
        member_b["id"],
        headers=CO,
        full_time_employee_count=20,
        part_time_hours_total=0,
        total_employee_count=22,
    )
    fixtures.run_ale_determination(api, group["id"], CO)
    employee_a = _hire_salaried_employee(api, member_a["id"], "Ada Frost", "2001")
    employee_b = _hire_salaried_employee(api, member_b["id"], "Bo Lin", "2002")
    form_a = fixtures.generate_form(api, employee_a["id"], plan_start_month=1)
    form_b = fixtures.generate_form(api, employee_b["id"], plan_start_month=1)
    transmittal = fixtures.open_transmittal(api, member_a["id"])
    return {
        "season": season,
        "group": group,
        "member_a": member_a,
        "member_b": member_b,
        "form_a": form_a,
        "form_b": form_b,
        "transmittal": transmittal,
    }


def _statement_with_family_offer(api):
    """A monthly-measured salaried employee, twelve months of 160 hours, and one
    minimum-value family offer at 17800 cents running 2026-01-01 up to
    2027-01-01, with the statement generated under the W-2 preference."""
    ctx = fixtures.determined_ale_group(api)
    employee = _hire_salaried_employee(
        api, ctx["member"]["id"], "Lena Ortiz", "4321", w2_box1_wages_cents=2400000
    )
    fixtures.record_hours(api, employee["id"], 2026, headers=BA, hours_of_service=160)
    offer = fixtures.create_coverage_offer(
        api,
        employee["id"],
        headers=BA,
        offer_kind="MEC_MV_FAMILY",
        minimum_value=True,
        lowest_cost_self_only_cents=17800,
        offers_spouse=True,
        offers_dependents=True,
        effective_start_date="2026-01-01",
        effective_end_date="2027-01-01",
    )
    get_success_data(api.recompute_employee_full_time(employee["id"], BA))
    form = fixtures.generate_form(
        api, employee["id"], plan_start_month=1, safe_harbor_preference="W2"
    )
    ctx["employee"] = employee
    ctx["offer"] = offer
    ctx["form"] = form
    return ctx


def _coverage_lines(api, form_id):
    return validate_paginated(
        api.list_monthly_coverage_lines(
            PREPARER, params={"form_1095c_id": form_id, "limit": 100}
        )
    )


# ---------------------------------------------------------------------------
# PATCH /ale-reporting/employees/{employee_id}
# ---------------------------------------------------------------------------
class TestEmployeeMeasurementOverride:
    def test_look_back_average_below_threshold_yields_no_full_time_months(self, api):
        """PRD §3.5: "Otherwise `measured_average_hours` is the sum of `counted_hours`
        across the surviving rows divided by the number of surviving rows, rounded
        half up to two decimal places, and the single stability verdict is that this
        average is at least the cycle's `hours_threshold_monthly`."
        PRD §3.5: "Then, for each of the twelve months of the tax year: a month whose
        first day falls within the cycle's stability start and end dates inclusive
        takes that single verdict with `ft_source` of `LOOK_BACK_STABILITY`; any other
        month falls back to the monthly test against 130 counted hours with
        `ft_source` of `MONTHLY_ACTUAL`."

        Design: Corner/Endpoints/patch_employee_override_flips_ft_month_count
        """
        ctx = _look_back_employee_with_two_hour_years(api)

        employee = fixtures.read_employee(api, ctx["employee"]["id"])

        assert employee["effective_measurement_method"] == "LOOK_BACK"
        assert float(employee["measured_average_hours"]) == pytest.approx(100.00, abs=0.01), (
            "twelve 2025 measurement months of 100 counted hours average to 100.00"
        )
        assert employee["full_time_month_count"] == 0, (
            "an average of 100.00 is below the cycle threshold of 130, so the whole "
            "stability period is not full time"
        )
        assert employee["full_time_months"] == []

    def test_override_to_monthly_reresolves_effective_method_and_bumps_version(self, api):
        """PRD §3.3: "The resolved value is exposed as `effective_measurement_method`
        — the override when set, otherwise the member's `measurement_method` — and it
        is recomputed whenever the override changes or the employee moves to another
        member."
        PRD §3.3: "The admin may later amend `w2_box1_wages_cents`,
        `hourly_rate_cents`, `monthly_salary_cents` and `measurement_method_override`;
        each amendment re-resolves `effective_measurement_method` and increments the
        employee's `version`."

        Design: Corner/Endpoints/patch_employee_override_flips_ft_month_count
        """
        ctx = _look_back_employee_with_two_hour_years(api)
        before = fixtures.read_employee(api, ctx["employee"]["id"])

        response = api.update_employee(
            ctx["employee"]["id"], {"measurement_method_override": "MONTHLY"}, BA
        )

        patched = validate_success(response, 200)
        assert patched["measurement_method_override"] == "MONTHLY"
        assert patched["effective_measurement_method"] == "MONTHLY", (
            "the override, once set, is the resolved measurement method"
        )
        assert patched["version"] == before["version"] + 1, (
            f"expected version {before['version'] + 1}, got {patched['version']} "
            "after amending the override"
        )

    def test_recompute_after_override_flips_twelve_months_to_monthly_actual(self, api):
        """PRD §3.5: "The input set is the employee's hours rows whose
        `measurement_year` equals the season's `tax_year`; the month is full time
        exactly when that month's `counted_hours` is at least 130, and `ft_source` for
        the month is `MONTHLY_ACTUAL`."
        PRD §3.5: "`full_time_months` is the ascending list of the months that survive
        as full time, `full_time_month_count` is its length, and `ft_source_by_month`
        is the twelve source labels in calendar order starting with January, each one
        of `LOOK_BACK_STABILITY`, `MONTHLY_ACTUAL`, `LNAP` or `NOT_EMPLOYED`."
        PRD §3.5: "`measured_average_hours` stays null under this method."

        Design: Corner/Endpoints/patch_employee_override_flips_ft_month_count
        """
        ctx = _look_back_employee_with_two_hour_years(api)
        employee_id = ctx["employee"]["id"]
        get_success_data(
            api.update_employee(employee_id, {"measurement_method_override": "MONTHLY"}, BA)
        )

        response = api.recompute_employee_full_time(employee_id, BA)

        recomputed = validate_success(response, 200)
        assert recomputed["full_time_month_count"] == 12, (
            "the 2026 rows of 160 counted hours are all at or above 130, so the same "
            "unchanged hours data now yields twelve full-time months"
        )
        assert recomputed["full_time_months"] == list(range(1, 13))
        assert recomputed["ft_source_by_month"] == ["MONTHLY_ACTUAL"] * 12
        assert recomputed["measured_average_hours"] is None, (
            "the look-back average no longer applies once the method is monthly"
        )
        assert recomputed["last_recomputed_at"] is not None

    def test_override_and_recompute_leave_the_hours_ledger_intact(self, api):
        """PRD §2.4: "The remaining seven families are append-only ledger rows and
        carry only `id` and `created_at` — monthly headcounts, measurement cycles,
        hours records, employment events, coverage offers, monthly coverage lines and
        penalty evidence have **no** `updated_at` and **no** `version` field at all."
        PRD §3.3: "Hours arrive as **HoursRecord** batches, one row per month of a
        stated `measurement_year`, each carrying `hours_of_service` (paid working
        hours) and optionally `paid_leave_hours` (paid non-working hours, default 0)
        and `special_unpaid_leave_hours` (unpaid FMLA, USERRA or jury-duty hours,
        default 0)."

        Design: Corner/Endpoints/patch_employee_override_flips_ft_month_count
        """
        ctx = _look_back_employee_with_two_hour_years(api)
        employee_id = ctx["employee"]["id"]
        get_success_data(
            api.update_employee(employee_id, {"measurement_method_override": "MONTHLY"}, BA)
        )
        get_success_data(api.recompute_employee_full_time(employee_id, BA))

        rows, meta = validate_paginated(
            api.list_hours_records(BA, params={"employee_id": employee_id, "limit": 100})
        )

        assert meta["total_count"] == 24, (
            "twelve 2025 rows plus twelve 2026 rows survive the override untouched, "
            f"got total_count {meta['total_count']}"
        )
        for row in rows:
            assert "version" not in row, "hours rows are append-only ledger rows"


# ---------------------------------------------------------------------------
# POST /ale-reporting/transmittals/{transmittal_id}/start-correction-cycle
# ---------------------------------------------------------------------------
class TestStartCorrectionCycle:
    def test_start_correction_cycle_moves_errored_submission_to_correction_required(self, api):
        """PRD §3.8: "Once errors exist, a `Preparer` starts the correction cycle,
        moving the transmittal from `ACCEPTED_WITH_ERRORS` or `PARTIALLY_ACCEPTED` to
        `CORRECTION_REQUIRED`."

        Design: Corner/Endpoints/start_correction_cycle_moves_accepted_with_errors_to_correction_required
        """
        ctx = _transmittal_accepted_with_one_warning(api)

        response = api.start_correction_cycle(ctx["transmittal"]["id"], PREPARER)

        moved = validate_success(response, 200)
        assert_transmittal(moved, status="CORRECTION_REQUIRED")

    def test_start_correction_cycle_changes_no_counters(self, api):
        """PRD §3.8: "That move requires at least one open error and a `cycle_number`
        still below the limit of 3, and changes no counters — it simply marks the
        submission as needing another round, buildable again once every error has been
        resolved."
        PRD §3.8: "**First**, the receipt identifier is recorded and one
        **TransmittalError** row is created per entry, with `resolution_status` of
        `OPEN`, a null `resolution_note`, a null `corrected_form_id` and a null
        `resolved_by_user_id`; `error_count` and `open_error_count` are set from those
        rows."

        Design: Corner/Endpoints/start_correction_cycle_moves_accepted_with_errors_to_correction_required
        """
        ctx = _transmittal_accepted_with_one_warning(api)

        api.start_correction_cycle(ctx["transmittal"]["id"], PREPARER)

        after = fixtures.read_transmittal(api, ctx["transmittal"]["id"])
        assert after["cycle_number"] == 1, (
            f"the transition changes no counters, so cycle_number stays 1, got "
            f"{after['cycle_number']}"
        )
        assert after["error_count"] == 1
        assert after["open_error_count"] == 1
        assert after["receipt_id"] == "AIR-2026-1010"
        assert after["form_count"] == 1

    def test_start_correction_cycle_opens_no_correction_on_group_or_season(self, api):
        """PRD §3.8: "**Third**, because a statement entered `FILED_WITH_ERRORS`, any
        such statement already sitting at `FURNISHED_PAPER` or `FURNISHED_ELECTRONIC`
        also moves to `REDELIVERY_REQUIRED`. **Fourth**, that redelivery flag
        increments the controlled group's `open_correction_count` and moves a
        `DETERMINED_ALE` group to `CORRECTION_OPEN`."
        PRD §2.10: "When a statement of a group enters `REDELIVERY_REQUIRED` on its
        furnishing dimension or `CORRECTION_DRAFTED` on its filing dimension, that
        group's `open_correction_count` increments; if the group was `DETERMINED_ALE`
        and the count moves from zero to a positive value, the group itself moves to
        `CORRECTION_OPEN`, and that move increments the season's
        `open_correction_count`."

        Design: Corner/Endpoints/start_correction_cycle_moves_accepted_with_errors_to_correction_required
        """
        ctx = _transmittal_accepted_with_one_warning(api)

        api.start_correction_cycle(ctx["transmittal"]["id"], PREPARER)

        group = fixtures.read_group(api, ctx["group"]["id"])
        season = fixtures.read_season(api, ctx["season"]["id"])
        assert group["open_correction_count"] == 0, (
            "the statement was never delivered, so no redelivery flag was raised and "
            "no correction opened on the group"
        )
        assert group["determination_state"] == "DETERMINED_ALE"
        assert season["open_correction_count"] == 0


# ---------------------------------------------------------------------------
# POST /ale-reporting/hours-records
# ---------------------------------------------------------------------------
class TestHoursRecordBatch:
    def test_hours_batch_creates_one_row_per_named_month(self, api):
        """PRD §3.3: "Hours arrive as **HoursRecord** batches, one row per month of a
        stated `measurement_year`, each carrying `hours_of_service` (paid working
        hours) and optionally `paid_leave_hours` (paid non-working hours, default 0)
        and `special_unpaid_leave_hours` (unpaid FMLA, USERRA or jury-duty hours,
        default 0)."
        PRD §2.11: "Recording hours of service behaves identically over its own
        `months` array and its employee-year-month triples."

        Design: Corner/Endpoints/hours_records_bulk_create_returns_twelve_rows
        """
        ctx = _monthly_employee_without_hours(api)

        response = api.create_hours_records(
            factories.hours_records_payload(
                ctx["employee"]["id"],
                2026,
                list(range(1, 13)),
                hours_of_service=120,
                paid_leave_hours=10,
                special_unpaid_leave_hours=0,
            ),
            BA,
        )

        rows = validate_success(response, 201)
        assert len(rows) == 12, f"one row per named month, got {len(rows)}"
        assert sorted(row["month"] for row in rows) == list(range(1, 13))
        for row in rows:
            assert row["measurement_year"] == 2026
            assert row["employee_id"] == ctx["employee"]["id"]

    def test_counted_hours_add_paid_leave_but_never_special_unpaid_leave(self, api):
        """PRD §3.3: "`counted_hours` is `hours_of_service` plus `paid_leave_hours` —
        special unpaid leave is *never* added to the numerator."
        PRD §3.3: "`excluded_from_denominator` is true exactly when
        `special_unpaid_leave_hours` is at least 130, and a month so marked drops out
        of the look-back average altogether, from numerator and denominator alike."

        Design: Corner/Endpoints/hours_records_bulk_create_returns_twelve_rows
        """
        ctx = _monthly_employee_without_hours(api)

        rows = validate_success(
            api.create_hours_records(
                factories.hours_records_payload(
                    ctx["employee"]["id"],
                    2026,
                    list(range(1, 13)),
                    hours_of_service=120,
                    paid_leave_hours=10,
                    special_unpaid_leave_hours=0,
                ),
                BA,
            ),
            201,
        )

        for row in rows:
            assert row["counted_hours"] == 130, (
                f"month {row['month']}: 120 worked plus 10 paid leave, got "
                f"{row['counted_hours']}"
            )
            assert row["excluded_from_denominator"] is False, (
                f"month {row['month']}: special unpaid leave of 0 is below 130"
            )

    def test_overlapping_hours_batch_is_rejected_and_writes_nothing(self, api):
        """PRD §2.6: "No hours row already exists for any requested
        employee-year-month triple — `ERR_DUPLICATE_HOURS_MONTH` (409), on
        hours-record creation."
        PRD §2.11: "Recording hours of service behaves identically over its own
        `months` array and its employee-year-month triples."
        PRD §2.11: "Partial application is never acceptable in any of the three."

        Design: Corner/Endpoints/hours_records_bulk_create_returns_twelve_rows
        """
        ctx = _monthly_employee_without_hours(api)
        employee_id = ctx["employee"]["id"]
        fixtures.record_hours(
            api,
            employee_id,
            2026,
            headers=BA,
            hours_of_service=120,
            paid_leave_hours=10,
            special_unpaid_leave_hours=0,
        )

        response = api.create_hours_records(
            factories.hours_records_payload(employee_id, 2026, [12], hours_of_service=90), BA
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_HOURS_MONTH, 409)
        rows, meta = validate_paginated(
            api.list_hours_records(
                BA, params={"employee_id": employee_id, "measurement_year": 2026, "limit": 100}
            )
        )
        assert meta["total_count"] == 12, (
            f"the rejected batch must add nothing, got total_count {meta['total_count']}"
        )
        december = [row for row in rows if row["month"] == 12]
        assert len(december) == 1
        assert december[0]["hours_of_service"] == 120, (
            "the surviving December row keeps its original hours, not the rejected 90"
        )


# ---------------------------------------------------------------------------
# POST /ale-reporting/transmittals/{transmittal_id}/attach-forms
# ---------------------------------------------------------------------------
class TestAttachFormsScopeAgreement:
    def test_attaching_a_form_of_another_member_is_refused(self, api):
        """PRD §3.8: "Every named form must currently be `NOT_FILED` and must belong
        to an employee whose `group_member_id` matches the transmittal's — a form from
        another member is refused with `ERR_SCOPE_MISMATCH`."
        PRD §2.6: "Cross-aggregate scope agreement — `ERR_SCOPE_MISMATCH` (409), on
        attach-forms, ale-determination, measurement-cycle creation, agency-error
        creation, penalty evidence and employment events."

        Design: Corner/Endpoints/attach_forms_cross_member_scope_mismatch_rejected
        """
        ctx = _two_members_each_with_a_statement(api)

        response = api.attach_forms(
            ctx["transmittal"]["id"],
            factories.attach_forms_payload([ctx["form_a"]["id"], ctx["form_b"]["id"]]),
            PREPARER,
        )

        validate_error(response, ApiErrorId.ERR_SCOPE_MISMATCH, 409)

    def test_scope_mismatch_attaches_neither_form_of_the_batch(self, api):
        """PRD §2.11: "Attaching statements to a submission takes a `form_ids` array;
        if any named form is not in `NOT_FILED`, the whole call is refused and no form
        is attached. Partial application is never acceptable in any of the three."
        PRD §3.8: "Each attached form moves `NOT_FILED` → `ATTACHED` and records the
        transmittal in its `transmittal_id`, the transmittal's `form_count`
        increments, and the member's `unattached_form_count` moves into
        `attached_form_count`; the member's `version` advances."

        Design: Corner/Endpoints/attach_forms_cross_member_scope_mismatch_rejected
        """
        ctx = _two_members_each_with_a_statement(api)

        api.attach_forms(
            ctx["transmittal"]["id"],
            factories.attach_forms_payload([ctx["form_a"]["id"], ctx["form_b"]["id"]]),
            PREPARER,
        )

        form_a = fixtures.read_form(api, ctx["form_a"]["id"])
        form_b = fixtures.read_form(api, ctx["form_b"]["id"])
        assert form_a["filing_status"] == "NOT_FILED", (
            "the correctly scoped member-A statement must not be attached either"
        )
        assert form_a.get("transmittal_id") is None
        assert form_b["filing_status"] == "NOT_FILED"

    def test_scope_mismatch_leaves_transmittal_and_member_counters_at_zero(self, api):
        """PRD §3.8: "A new transmittal starts at `DRAFT` with `cycle_number` 1, every
        counter at zero and null `channel`, `receipt_id`, `built_at` and
        `transmitted_at`; creating it sets the member's `open_transmittal_id` and
        increments the member's `version`."
        PRD §3.6: "Generation also requires the employee's controlled group to be in
        `DETERMINED_ALE` or `CORRECTION_OPEN`, and it increments the member's
        `generated_form_count` and `unattached_form_count`."

        Design: Corner/Endpoints/attach_forms_cross_member_scope_mismatch_rejected
        """
        ctx = _two_members_each_with_a_statement(api)

        api.attach_forms(
            ctx["transmittal"]["id"],
            factories.attach_forms_payload([ctx["form_a"]["id"], ctx["form_b"]["id"]]),
            PREPARER,
        )

        transmittal = fixtures.read_transmittal(api, ctx["transmittal"]["id"])
        assert_transmittal(
            transmittal, status="DRAFT", form_count=0, aggregate_return_count=0
        )
        member_a = fixtures.read_member(api, ctx["member_a"]["id"])
        assert member_a["attached_form_count"] == 0
        assert member_a["unattached_form_count"] == 1, (
            "member A's single generated statement is still unattached"
        )


# ---------------------------------------------------------------------------
# GET /ale-reporting/monthly-coverage-lines
# ---------------------------------------------------------------------------
class TestMonthlyCoverageLineRead:
    def test_coverage_lines_are_reachable_only_by_filtering_on_the_statement(self, api):
        """PRD §2.5: "Monthly coverage lines are only discoverable by filtering on
        `form_1095c_id` or `month`; agency error rows created by an agency response
        are only discoverable by filtering on `transmittal_id`, `form_1095c_id`,
        `corrected_form_id` or `resolution_status`; a correction form is only
        discoverable by filtering forms on `corrected_from_form_id`."
        PRD §3.6: "It creates a **Form1095C** with `form_type` of `ORIGINAL`, a
        `furnishing_status` of `NOT_FURNISHED` and a `filing_status` of `NOT_FILED` —
        the two status dimensions move independently of one another for the rest of
        the statement's life — and twelve **MonthlyCoverageLine** rows created
        together, one per month, each stamped with the parent statement's identity
        through `form_1095c_id` and its own `month`."

        Design: Corner/Endpoints/monthly_coverage_lines_computed_read_matches_form_rollups
        """
        ctx = _statement_with_family_offer(api)

        lines, meta = _coverage_lines(api, ctx["form"]["id"])

        assert meta["total_count"] == 12, (
            f"one line per month of the reporting year, got {meta['total_count']}"
        )
        assert sorted(line["month"] for line in lines) == list(range(1, 13))
        for line in lines:
            assert line["form_1095c_id"] == ctx["form"]["id"]

    def test_family_offer_above_the_poverty_line_figure_prints_1e_and_line15(self, api):
        """PRD §3.6: "Otherwise an offer of kind `MEC_MV_FAMILY` whose
        `lowest_cost_self_only_cents` is at most the federal-poverty-line threshold
        described below is `1A`. Otherwise `MEC_MV_FAMILY` is `1E`."
        PRD §3.6: "`line15_amount_cents` is the offer's `lowest_cost_self_only_cents`
        when the month's `line14_code` is `1B`, `1C`, `1D`, `1E` or `1K`, and null for
        every other code."
        PRD §3.6: "The federal-poverty-line threshold is `mainland_fpl_annual_cents`
        multiplied by `affordability_pct` and divided by 12, and it is the same flat
        monthly figure for every employee — it is also the figure the `1A` test in step
        C compares against."

        Design: Corner/Endpoints/monthly_coverage_lines_computed_read_matches_form_rollups
        """
        ctx = _statement_with_family_offer(api)

        lines, _ = _coverage_lines(api, ctx["form"]["id"])

        for line in lines:
            assert_monthly_coverage_line(
                line, line14_code="1E", line15_amount_cents=17800
            )

    def test_w2_threshold_divides_by_offered_month_count_and_prints_2f(self, api):
        """PRD §3.6: "The W-2 threshold is the employee's `w2_box1_wages_cents`
        multiplied by the season's `affordability_pct` and divided by
        `offered_month_count`."
        PRD §3.6: "The chosen harbor is recorded per month as `safe_harbor_applied`
        and the figure it produced as `affordability_threshold_cents`, which is null
        when no harbor applied. A month is affordable exactly when the governing
        offer's `lowest_cost_self_only_cents` is at most that threshold; a month with
        no covering offer is never affordable, and when the applied harbor is `NONE`
        no month is affordable."
        PRD §3.6: "Otherwise an affordable month is `2F` when the applied harbor is
        `W2`, `2G` when it is `FPL`, and `2H` when it is `RATE_OF_PAY`."

        Design: Corner/Endpoints/monthly_coverage_lines_computed_read_matches_form_rollups
        """
        ctx = _statement_with_family_offer(api)

        lines, _ = _coverage_lines(api, ctx["form"]["id"])

        for line in lines:
            assert line["safe_harbor_applied"] == "W2"
            assert line["affordability_threshold_cents"] == 18040, (
                f"month {line['month']}: 2400000 cents at 0.0902 over twelve offered "
                f"months is 18040, got {line['affordability_threshold_cents']}"
            )
            assert line["line16_code"] == "2F", (
                f"month {line['month']}: 17800 is at most 18040, so the month is "
                "affordable under the W-2 harbor"
            )

    def test_full_time_months_are_monthly_actual_and_not_assessable(self, api):
        """PRD §3.5: "The input set is the employee's hours rows whose
        `measurement_year` equals the season's `tax_year`; the month is full time
        exactly when that month's `counted_hours` is at least 130, and `ft_source` for
        the month is `MONTHLY_ACTUAL`."
        PRD §3.6: "A month's `assessable` flag is true exactly when `full_time_flag`
        is true and `line16_code` is null."

        Design: Corner/Endpoints/monthly_coverage_lines_computed_read_matches_form_rollups
        """
        ctx = _statement_with_family_offer(api)

        lines, _ = _coverage_lines(api, ctx["form"]["id"])

        for line in lines:
            assert line["full_time_flag"] is True, (
                f"month {line['month']}: 160 counted hours is at least 130"
            )
            assert line["ft_source"] == "MONTHLY_ACTUAL"
            assert line["assessable"] is False, (
                f"month {line['month']}: line 16 is populated, so the month is covered"
            )

    def test_statement_rollups_reconcile_with_the_twelve_coverage_lines(self, api):
        """PRD §3.6: "The statement then rolls up: `all_12_months_code` is the shared
        line 14 code when all twelve months agree and null otherwise; `ft_month_count`
        counts months with `full_time_flag` true; `offered_month_count` counts months
        whose `line14_code` is not `1H`; `assessable_month_count` counts months with
        `assessable` true; and `line15_total_cents` sums `line15_amount_cents` over
        the months where it is not null."

        Design: Corner/Endpoints/monthly_coverage_lines_computed_read_matches_form_rollups
        """
        ctx = _statement_with_family_offer(api)

        lines, _ = _coverage_lines(api, ctx["form"]["id"])
        form = fixtures.read_form(api, ctx["form"]["id"])

        assert form["all_12_months_code"] == "1E"
        assert form["ft_month_count"] == 12
        assert form["offered_month_count"] == 12
        assert form["assessable_month_count"] == 0
        assert form["line15_total_cents"] == 213600, (
            f"twelve months at 17800 cents, got {form['line15_total_cents']}"
        )
        assert form["line15_total_cents"] == sum(
            line["line15_amount_cents"] for line in lines
        ), "the roll-up must equal the sum of the twelve line-15 amounts"

    def test_half_open_offer_interval_covers_every_month_of_the_reporting_year(self, api):
        """PRD §3.6: "A `BenefitsAdmin` records each offer of coverage as a
        **CoverageOffer** over a half-open interval: `effective_start_date` is the
        first date the offer is in force and `effective_end_date` is the first date it
        is no longer in force, so the end date itself is outside the offer.
        `covered_months` is computed as the ascending months of the reporting year
        every single day of which lies inside that interval."

        Design: Corner/Endpoints/monthly_coverage_lines_computed_read_matches_form_rollups
        """
        ctx = _statement_with_family_offer(api)

        offer = get_success_data(api.get_coverage_offer(ctx["offer"]["id"], BA))

        assert offer["covered_months"] == list(range(1, 13)), (
            "an interval running 2026-01-01 up to 2027-01-01 wholly contains every "
            f"month of 2026, got {offer['covered_months']}"
        )
