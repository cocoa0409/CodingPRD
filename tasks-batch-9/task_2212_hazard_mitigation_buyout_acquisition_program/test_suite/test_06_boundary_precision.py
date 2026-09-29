"""Boundary precision: exact-equality thresholds, rounding before comparison, signed zero."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


# ─── The benefit-cost ratio threshold ─────────────────────────────────────────

AT_THRESHOLD_BCA = {
    "analysis_method": "PRE_CALCULATED_BENEFIT",
    "annualized_loss_avoided_cents": 1_500_000,
    "project_useful_life_years": 30,
    "mitigation_cost_cents": 45_000_000,
}

BELOW_THRESHOLD_BCA = dict(AT_THRESHOLD_BCA, annualized_loss_avoided_cents=1_000_000)


def _approve(api, project):
    return api.approve_mitigation_project(
        project["id"],
        factories.approve_project_payload(project["id"], "APPROVE"),
        TEST_USERS["project_approver_headers"],
    )


def test_a_validated_ratio_of_exactly_one_point_zero_zero_zero_is_approvable(api):
    """The inclusive floor admits the project that lands exactly on it.

    "`APPROVE` requires that exactly one analysis on the project holds `status`
    `VALIDATED` and that the project's `validated_bcr` is at least 1.0. The
    threshold is inclusive: a `validated_bcr` of exactly 1.000 is approvable, and
    a `validated_bcr` of 0.999 is not."

    "`validated_bcr` takes the analysis's `bcr`, `validated_bca_method` takes its
    `analysis_method`, and the project's `validated_by_user_id` takes the same
    acting `X-User-ID` that SoD-2 will later read."

    Design: Difficulty/boundary_precision_check/benefit_cost_ratio_exactly_one_point_zero_permits_approval
    """
    state = fixtures.create_validated_project(api, bca_overrides=AT_THRESHOLD_BCA)
    assert state["bca"]["npv_benefits_cents"] == 45_000_000
    assert float(state["bca"]["bcr"]) == 1.000

    project = validate_success(_approve(api, state["project"]))

    assert project["status"] == "APPROVED"
    assert float(project["validated_bcr"]) == 1.000
    assert project["validated_bca_method"] == "PRE_CALCULATED_BENEFIT"
    assert project["validated_by_user_id"] == "pa-validator"


def test_a_validated_ratio_below_the_floor_is_refused_and_the_project_stays_submitted(api):
    """A ratio of 0.667 fails the same strict comparison and moves nothing.

    "A `validated_bcr` below the threshold - and equally the case where no
    analysis ever reached `VALIDATED`, so `validated_bcr` is still null - is
    refused with `ERR_BCR_BELOW_THRESHOLD`."

    "On approval the project moves to `APPROVED`, the whole neighborhood-viability
    family (`participating_parcel_count`, `holdout_parcel_count`,
    `contiguous_open_space_parcel_count`, `largest_component_parcel_ids`,
    `neighborhood_viability_ratio`, `viability_status`) is recomputed, and the
    project's `version` advances by 1."

    Design: Difficulty/boundary_precision_check/benefit_cost_ratio_exactly_one_point_zero_permits_approval
    """
    state = fixtures.create_validated_project(api, bca_overrides=BELOW_THRESHOLD_BCA)
    assert state["bca"]["npv_benefits_cents"] == 30_000_000
    assert float(state["bca"]["bcr"]) == 0.667

    validate_error(
        _approve(api, state["project"]),
        ApiErrorId.ERR_BCR_BELOW_THRESHOLD.value,
        422,
    )

    project = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert project["status"] == "SUBMITTED"


# ─── The debris diversion gate ────────────────────────────────────────────────

def _work_order_in_progress_on_its_own_contractor(api, project, parcel, license_suffix):
    contractor = fixtures.create_contractor(
        api,
        name=f"Wrecking {license_suffix}",
        license_no=f"DEM-{license_suffix}",
        asbestos_certified=True,
        max_concurrent_work_orders=1,
    )
    work_order = fixtures.issue_work_order(
        api, project, parcel["id"], contractor["id"], asbestos_survey_status="CLEARED"
    )
    disconnections = fixtures.order_all_utility_disconnections(
        api, project, work_order["id"]
    )
    fixtures.confirm_all_utility_disconnections(api, project, disconnections)
    return validate_success(
        api.start_demolition_work_order(
            work_order["id"], make_subrecipient_coordinator_headers(project["id"])
        )
    )


def _two_mobilized_work_orders(api):
    """Two IN_PROGRESS work orders, each under its own contractor."""
    project = fixtures.create_draft_project(api)
    parcel_a = fixtures.create_parcel(
        api, project, apn="APN-D1", site_address="401 River Rd", acreage=0.30,
        occupancy_type="VACANT",
    )
    parcel_b = fixtures.create_parcel(
        api, project, apn="APN-D2", site_address="403 River Rd", acreage=0.30,
        occupancy_type="VACANT",
    )
    return {
        "project": project,
        "parcel_a": parcel_a,
        "parcel_b": parcel_b,
        "work_order_pass": _work_order_in_progress_on_its_own_contractor(
            api, project, parcel_a, "A"
        ),
        "work_order_fail": _work_order_in_progress_on_its_own_contractor(
            api, project, parcel_b, "B"
        ),
    }


def _complete(api, project, work_order, total_debris_tons, recycled_tons, manifest):
    return api.complete_demolition_work_order(
        work_order["id"],
        factories.complete_work_order_payload(
            work_order["id"],
            total_debris_tons=total_debris_tons,
            recycled_tons=recycled_tons,
            disposal_manifest_no=manifest,
            disposal_facility_type="COMBINED",
        ),
        make_subrecipient_coordinator_headers(project["id"]),
    )


def test_a_raw_ratio_below_the_minimum_passes_once_it_rounds_up_to_it(api):
    """25.00 over 100.02 is 24.995 percent raw, rounds to 25.00 and clears the gate.

    "`diversion_pct` is 0.00 when `total_debris_tons` is 0, and otherwise
    `recycled_tons` divided by `total_debris_tons`, multiplied by 100, rounded
    half up to two decimal places."

    "The comparison is made against the **rounded** `diversion_pct`, so a raw
    ratio of 24.9958 percent that rounds to 25.00 passes, and a `diversion_pct`
    of exactly 25.00 passes because the threshold is inclusive."

    "Completion stores the four reported fields and `diversion_pct`, moves
    `status` to `COMPLETED`, moves the parcel's `acquisition_status` from `CLOSED`
    to `DEMOLISHED`."

    Design: Difficulty/boundary_precision_check/debris_diversion_rounds_up_to_the_minimum_before_the_gate_compares
    """
    state = _two_mobilized_work_orders(api)

    completed = validate_success(
        _complete(
            api, state["project"], state["work_order_pass"], 100.02, 25.00, "MAN-PASS"
        )
    )

    assert float(completed["diversion_pct"]) == 25.00
    assert completed["status"] == "COMPLETED"
    assert completed["disposal_manifest_no"] == "MAN-PASS"

    parcel = validate_success(
        api.get_parcel(
            state["parcel_a"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert parcel["acquisition_status"] == "NOT_STARTED"


def test_a_raw_ratio_that_rounds_down_fails_and_stores_nothing(api):
    """25.00 over 100.04 rounds to 24.99 and the completion is refused outright.

    "The gate is then: a `total_debris_tons` of 0 passes under the zero-quantity
    waiver, since a work order that generated no debris cannot be held to a
    diversion percentage; otherwise a `diversion_pct` of at least 25.0 passes;
    anything else is `ERR_DEBRIS_DIVERSION_BELOW_MINIMUM`."

    "The work order opens in `status` `ISSUED` at `version` 1 with
    `failed_inspection_count` 0, `required_utility_types` copied as the four
    values `WATER`, `ELECTRIC`, `GAS` and `SEWER`, `confirmed_utility_types` an
    empty array, `total_debris_tons` 0, `recycled_tons` 0, `diversion_pct` 0, and
    `disposal_manifest_no` and `disposal_facility_type` null."

    Design: Difficulty/boundary_precision_check/debris_diversion_rounds_up_to_the_minimum_before_the_gate_compares
    """
    state = _two_mobilized_work_orders(api)

    validate_error(
        _complete(
            api, state["project"], state["work_order_fail"], 100.04, 25.00, "MAN-FAIL"
        ),
        ApiErrorId.ERR_DEBRIS_DIVERSION_BELOW_MINIMUM.value,
        422,
    )

    work_order = validate_success(
        api.get_demolition_work_order(
            state["work_order_fail"]["id"],
            TEST_USERS["program_administrator_headers"],
        )
    )
    assert work_order["status"] == "IN_PROGRESS"
    assert work_order["disposal_manifest_no"] is None


# ─── The program income balance floor ─────────────────────────────────────────

def _project_with_one_credit(api):
    """An APPROVED project carrying a single 100,002-cent lease-revenue credit."""
    state = fixtures.create_approved_project(api)
    state["credit"] = fixtures.post_program_income(
        api,
        state["project"]["id"],
        entry_type="LEASE_REVENUE",
        amount_cents=100_002,
        posted_on="2026-08-01",
    )
    project = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert project["program_income_balance_cents"] == 75_002
    state["project"] = project
    return state


def test_an_expenditure_that_lands_the_balance_on_exactly_zero_is_accepted(api):
    """The debit rounds on its positive magnitude, so credit and debit cancel exactly.

    "An expenditure that brings the balance to exactly 0 is accepted, since 0 is
    not negative - and that is in fact the state closeout requires."

    "The magnitude is `amount_cents` multiplied by the project's
    `cost_share_federal_pct`, rounded half up to whole cents. `federal_share_cents`
    is then the sign multiplied by that magnitude."

    "`program_income_balance_cents` is the sum of `federal_share_cents` over every
    entry of the project whose `status` is `ACTIVE`, accumulated in order of
    `posted_on` ascending and then `created_at` ascending."

    Design: Difficulty/boundary_precision_check/program_income_expenditure_to_exactly_zero_balance_is_permitted
    """
    state = _project_with_one_credit(api)
    assert state["credit"]["federal_share_cents"] == 75_002

    debit = fixtures.post_program_income(
        api,
        state["project"]["id"],
        entry_type="EXPENDITURE",
        amount_cents=100_002,
        posted_on="2026-08-02",
    )

    assert debit["federal_share_cents"] == -75_002
    assert debit["status"] == "ACTIVE"

    project = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert project["program_income_balance_cents"] == 0


def test_a_further_debit_against_a_zero_balance_is_refused_and_creates_nothing(api):
    """Once the balance is exactly zero, the next expenditure would go negative.

    "Posting an entry whose signed `federal_share_cents` would drive
    `program_income_balance_cents` below zero is refused with
    `ERR_PROGRAM_INCOME_OVERDRAWN` and no entry is created."

    "In practice this means a project cannot spend program income it has not
    earned."

    Design: Difficulty/boundary_precision_check/program_income_expenditure_to_exactly_zero_balance_is_permitted
    """
    state = _project_with_one_credit(api)
    fixtures.post_program_income(
        api,
        state["project"]["id"],
        entry_type="EXPENDITURE",
        amount_cents=100_002,
        posted_on="2026-08-02",
    )

    project = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert project["program_income_balance_cents"] == 0

    response = api.create_program_income_entry(
        project["id"],
        factories.create_program_income_entry_payload(
            project["id"],
            project["version"],
            entry_type="EXPENDITURE",
            amount_cents=4,
            posted_on="2026-08-03",
        ),
        make_subrecipient_coordinator_headers(project["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_INCOME_OVERDRAWN.value, 422)

    after = validate_success(
        api.get_mitigation_project(
            project["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert after["program_income_balance_cents"] == 0
