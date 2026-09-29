"""Cross-entity state dependencies: two rows identical in their own state that
diverge because of a field on a third entity.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ASSET_MANAGER, COMMITTEE_OFFICER, MASTER_SERVICER


# ==========================================================================
# Execution is gated by a third entity's coverage window
# ==========================================================================
def _two_approved_plans_with_different_valuations(api):
    """Plan G's appraisal window ends 2027-08-01; plan H's ends 2028-01-01."""
    fx.set_clock(api, "2027-01-01T00:00:00Z")
    trust = fx.create_trust(api, deal_name="CMBS 2026-G1")

    built = {}
    for label, loan_number, as_of in (
        ("g", "L-G01", "2026-08-01T00:00:00Z"),
        ("h", "L-H01", "2027-01-01T00:00:00Z"),
    ):
        loan = fx.create_mid_size_loan(
            api,
            trust["id"],
            loan_number=loan_number,
            maturity_date="2029-06-01T00:00:00Z",
        )
        fx.record_bankruptcy_event(api, loan["id"])
        fx.transfer_to_special_servicing(api, loan["id"])
        appraisal = fx.accepted_appraisal(
            api, loan["id"], value_usd=9000000, as_of_date=as_of, ordered_on=as_of
        )
        plan = fx.approved_plan(api, trust["id"], loan["id"])
        built[label] = {
            "loan_id": loan["id"],
            "appraisal": appraisal,
            "plan_id": plan["plan_id"],
        }

    fx.set_clock(api, "2027-08-01T00:00:00Z")
    return trust["id"], built


def test_a_plan_whose_valuation_window_has_just_closed_cannot_execute(api):
    """The clock sits exactly on coverage_end_date, which is already outside.

    The PRD: "Execution — `APPROVED → EXECUTED` — is driven by the asset manager
    and requires a current valuation on the plan's loan on exactly the terms
    described in §3.6: an `ACCEPTED` appraisal whose half-open coverage window
    contains the current logical clock, failing which the move is refused with
    `ERR_STALE_APPRAISAL`."

    Design: Difficulty/cross_entity_state_dependency/plan_execution_gated_by_another_entitys_appraisal_coverage_window
    """
    _, built = _two_approved_plans_with_different_valuations(api)
    assert built["g"]["appraisal"]["coverage_start_date"].startswith("2026-08-01")
    assert built["g"]["appraisal"]["coverage_end_date"].startswith("2027-08-01")

    response = api.set_workout_plan_status(
        built["g"]["plan_id"], f.status_payload("EXECUTED"), ASSET_MANAGER
    )
    validate_error(response, e.ERR_STALE_APPRAISAL, 422)

    plan = validate_success(api.get_workout_plan(built["g"]["plan_id"], ASSET_MANAGER))
    a.assert_status(plan, "APPROVED")
    a.assert_fields_null(plan, "executed_on")
    loan = fx.read_loan(api, built["g"]["loan_id"])
    assert loan["is_modified"] is False


def test_an_otherwise_identical_plan_with_a_live_window_executes(api):
    """The only difference between the two plans lives on a third entity.

    The PRD: "an appraisal is current while the clock is at or after
    `coverage_start_date` and strictly before `coverage_end_date`, and a clock
    exactly equal to `coverage_end_date` is already stale."

    Design: Difficulty/cross_entity_state_dependency/plan_execution_gated_by_another_entitys_appraisal_coverage_window
    """
    _, built = _two_approved_plans_with_different_valuations(api)
    assert built["h"]["appraisal"]["coverage_end_date"].startswith("2028-01-01")

    executed = validate_success(
        api.set_workout_plan_status(
            built["h"]["plan_id"], f.status_payload("EXECUTED"), ASSET_MANAGER
        )
    )
    a.assert_status(executed, "EXECUTED")
    assert executed["executed_on"].startswith("2027-08-01")


def test_only_the_executed_modification_makes_its_loan_correctable(api):
    """Execution is what unlocks correction, so the two loans now differ.

    The PRD: "What execution unlocks depends on the selected alternative's type: a
    `MODIFICATION` sets the loan's `is_modified` flag to true and makes the loan
    eligible to be corrected; a `FORECLOSURE` or a `DEED_IN_LIEU` makes it
    eligible for a real-estate-owned acquisition; and a `NOTE_SALE` makes it
    eligible for liquidation."

    Design: Difficulty/cross_entity_state_dependency/plan_execution_gated_by_another_entitys_appraisal_coverage_window
    """
    _, built = _two_approved_plans_with_different_valuations(api)
    validate_error(
        api.set_workout_plan_status(
            built["g"]["plan_id"], f.status_payload("EXECUTED"), ASSET_MANAGER
        ),
        e.ERR_STALE_APPRAISAL,
    )
    fx.execute_plan(api, built["h"]["plan_id"])

    executable = fx.read_loan(api, built["h"]["loan_id"])
    assert executable["is_modified"] is True
    blocked = fx.read_loan(api, built["g"]["loan_id"])
    assert blocked["is_modified"] is False

    corrected = validate_success(
        api.set_loan_servicing_status(
            built["h"]["loan_id"], f.status_payload("CORRECTED"), COMMITTEE_OFFICER
        )
    )
    a.assert_status(corrected, "CORRECTED", "servicing_status")
    assert corrected["correction_source_plan_id"] == built["h"]["plan_id"]
    a.assert_fields_null(corrected, "active_workout_plan_id")


# ==========================================================================
# Taking title is gated by the source plan's selected alternative type
# ==========================================================================
def _executed_modification_and_foreclosure_plans(api):
    trust = fx.create_trust(api, deal_name="CMBS 2026-K1")
    built = {}
    for label, loan_number, builder in (
        ("modification", "L-K0M", fx.add_modification_alternative),
        ("foreclosure", "L-K0F", fx.add_foreclosure_alternative),
    ):
        loan = fx.create_mid_size_loan(api, trust["id"], loan_number=loan_number)
        fx.record_bankruptcy_event(api, loan["id"])
        fx.transfer_to_special_servicing(api, loan["id"])
        fx.accepted_appraisal(api, loan["id"], value_usd=9000000)
        plan = fx.executed_plan(
            api, trust["id"], loan["id"], alternative_builders=[builder]
        )
        built[label] = {"loan_id": loan["id"], "plan_id": plan["plan_id"]}
    return trust["id"], built


def test_a_modification_plan_cannot_be_used_to_take_title(api):
    """A FORECLOSURE acquisition on a MODIFICATION plan is a type mismatch.

    The PRD: "Whenever the operation being attempted implies a particular
    strategy, the service checks the executed plan's selected alternative against
    it and refuses a mismatch with `ERR_ALTERNATIVE_TYPE_MISMATCH`: correcting a
    loan requires a `MODIFICATION`, liquidating it directly requires a
    `NOTE_SALE`, and taking title requires the acquisition to match the selected
    `FORECLOSURE` or `DEED_IN_LIEU`."

    Design: Difficulty/cross_entity_state_dependency/reo_acquisition_gated_by_source_plan_selected_alternative_type
    """
    _, built = _executed_modification_and_foreclosure_plans(api)
    source = built["modification"]

    response = api.create_reo_asset(
        f.reo_asset_payload(
            source["loan_id"], source["plan_id"], acquisition_type="FORECLOSURE"
        ),
        ASSET_MANAGER,
    )
    validate_error(response, e.ERR_ALTERNATIVE_TYPE_MISMATCH, 422)

    loan = fx.read_loan(api, source["loan_id"])
    a.assert_status(loan, "IN_WORKOUT", "servicing_status")
    assert loan["active_workout_plan_id"] == source["plan_id"]
    rows, _ = validate_paginated(
        api.list_reo_assets(ASSET_MANAGER, {"loan_id": source["loan_id"]})
    )
    assert rows == []


def test_a_foreclosure_plan_cannot_yield_a_deed_in_lieu_acquisition(api):
    """Both acquisition types are REO-eligible, but only the matching one passes.

    The PRD: "the `acquisition_type` — either `FORECLOSURE` or `DEED_IN_LIEU`,
    which must equal the source plan's selected alternative type"

    Design: Difficulty/cross_entity_state_dependency/reo_acquisition_gated_by_source_plan_selected_alternative_type
    """
    _, built = _executed_modification_and_foreclosure_plans(api)
    source = built["foreclosure"]

    response = api.create_reo_asset(
        f.reo_asset_payload(
            source["loan_id"], source["plan_id"], acquisition_type="DEED_IN_LIEU"
        ),
        ASSET_MANAGER,
    )
    validate_error(response, e.ERR_ALTERNATIVE_TYPE_MISMATCH, 422)

    loan = fx.read_loan(api, source["loan_id"])
    a.assert_status(loan, "IN_WORKOUT", "servicing_status")


def test_the_exactly_matching_acquisition_takes_the_loan_into_reo(api):
    """The identical body shape succeeds once the two types agree.

    The PRD: "The loan moves `IN_WORKOUT → REO` and its `active_workout_plan_id`
    is cleared to null; that servicing-dimension move is system-driven, so a
    client naming `REO` directly is refused with
    `ERR_ROLE_NOT_PERMITTED_FOR_STATUS`."

    Design: Difficulty/cross_entity_state_dependency/reo_acquisition_gated_by_source_plan_selected_alternative_type
    """
    _, built = _executed_modification_and_foreclosure_plans(api)
    source = built["foreclosure"]

    reo = validate_success(
        api.create_reo_asset(
            f.reo_asset_payload(
                source["loan_id"], source["plan_id"], acquisition_type="FORECLOSURE"
            ),
            ASSET_MANAGER,
        ),
        201,
    )
    a.assert_status(reo, "ACQUIRED")
    assert reo["remic_disposition_deadline"].startswith("2029-08-01")
    assert reo["contract_fallthrough_count"] == 0

    loan = fx.read_loan(api, source["loan_id"], MASTER_SERVICER)
    a.assert_status(loan, "REO", "servicing_status")
    a.assert_fields_null(loan, "active_workout_plan_id")
