"""Survival surveys: threshold variants, boundary equality, survey window,
rounding, and replant-obligation waiver rules."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_ready_world, drive_to_planted, setup_replant_required_world,
    set_clock,
)

CO = TEST_USERS["contract_officer_headers"]
FA = TEST_USERS["field_auditor_headers"]
PA = TEST_USERS["program_administrator_headers"]


def _planted_world(api, enrollment=None):
    """A contract planted at exactly its required 4000 seedlings."""
    ctx = setup_ready_world(acres=10, trees_per_acre=400, contingency_pct=0,
                            order_quantity=4000, enrollment=enrollment)
    return drive_to_planted(ctx, plant_date="2027-04-01", crew_capacity=5000)


def test_survival_exactly_at_threshold_passes(api):
    """PRD §3.6: "The pass bar, `threshold_pct`, is 70.00" and "The survey's
    `below_threshold` flag is true exactly when `survival_pct` is strictly less
    than `threshold_pct`; equality passes."

    Design: Difficulty/boundary_precision_check/survival_exactly_at_threshold_passes
    """
    ctx = _planted_world(api)
    set_clock("2028-02-15T00:00:00Z")
    survey = get_success_data(
        api.create_survival_survey(
            {"planting_contract_id": ctx["contract"]["id"],
             "surveyed_on": "2028-02-15", "alive_count": 2800}, FA
        )
    )
    assert survey["survival_pct"] == pytest.approx(70.00, abs=0.001), (
        f"2800 of 4000 must be exactly 70.00, got {survey['survival_pct']}"
    )
    assert survey["below_threshold"] is False
    assert survey["obligation_status"] == "NONE", (
        "equality at the threshold passes: no obligation is created"
    )
    assert survey["owed_quantity"] == 0


def test_survival_at_threshold_closes_contract(api):
    """PRD §3.6: "a passing survey closes the contract (`SURVEYED` → `CLOSED`),
    while a failing one flips it to `REPLANT_REQUIRED` and fires CASCADE B"

    Design: Difficulty/boundary_precision_check/survival_exactly_at_threshold_passes
    """
    ctx = setup_ready_world(acres=25, trees_per_acre=400, contingency_pct=0,
                            order_quantity=10000, unit_capacity=25000)
    ctx = drive_to_planted(ctx, plant_date="2027-04-01", crew_capacity=5000)
    assert ctx["planted_qty"] == 10000

    set_clock("2028-02-15T00:00:00Z")
    get_success_data(
        api.create_survival_survey(
            {"planting_contract_id": ctx["contract"]["id"],
             "surveyed_on": "2028-02-15", "alive_count": 7000}, FA
        )
    )
    contract = get_success_data(api.get_planting_contract(ctx["contract"]["id"], CO))
    assert contract["status"] == "CLOSED", (
        f"70.00 of 70.00 passes and closes the contract, got {contract['status']}"
    )


def test_survey_threshold_standard_landowner(api):
    """PRD §3.6: "The pass bar, `threshold_pct`, is 70.00 — unless the
    contract's landowner holds any cost-share enrollment in `APPROVED`,
    `PAYMENT_HELD`, or `PAID`, in which case it rises to 80.00. Identical field
    data can therefore pass for one landowner and fail for another: a survey at
    75.00 passes the standard bar and fails the cost-share bar."

    Design: Difficulty/dual_variant_calc/survey_threshold_standard_vs_cost_share
    """
    ctx = _planted_world(api)  # landowner with no enrollment -> standard bar
    set_clock("2028-02-15T00:00:00Z")
    survey = get_success_data(
        api.create_survival_survey(
            {"planting_contract_id": ctx["contract"]["id"],
             "surveyed_on": "2028-02-15", "alive_count": 3000}, FA
        )
    )
    assert survey["survival_pct"] == pytest.approx(75.00, abs=0.001)
    assert survey["threshold_pct"] == pytest.approx(70.00, abs=0.001)

    contract = get_success_data(api.get_planting_contract(ctx["contract"]["id"], CO))
    assert contract["status"] == "CLOSED", (
        "75.00 passes the standard 70.00 bar and closes the contract"
    )


def test_survey_threshold_cost_share_landowner(api):
    """PRD §3.6: "The pass bar, `threshold_pct`, is 70.00 — unless the
    contract's landowner holds any cost-share enrollment in `APPROVED`,
    `PAYMENT_HELD`, or `PAID`, in which case it rises to 80.00." and "The
    required-survivors figure is the contract's `required_seedlings` multiplied
    by the survey's `threshold_pct` and divided by 100, rounded up to a whole
    seedling. The base shortfall is that figure minus the survey's
    `alive_count`, and never below zero."

    Design: Difficulty/dual_variant_calc/survey_threshold_standard_vs_cost_share
    """
    ctx = _planted_world(api, enrollment={})  # APPROVED enrollment -> 80.00 bar
    set_clock("2028-02-15T00:00:00Z")
    survey = get_success_data(
        api.create_survival_survey(
            {"planting_contract_id": ctx["contract"]["id"],
             "surveyed_on": "2028-02-15", "alive_count": 3000}, FA
        )
    )
    assert survey["survival_pct"] == pytest.approx(75.00, abs=0.001)
    assert survey["threshold_pct"] == pytest.approx(80.00, abs=0.001)
    assert survey["below_threshold"] is True
    assert survey["obligation_status"] == "OPEN"
    assert survey["owed_quantity"] == 200, (
        f"ceil(4000 * 0.80) - 3000 = 200 owed, got {survey['owed_quantity']}"
    )

    contract = get_success_data(api.get_planting_contract(ctx["contract"]["id"], CO))
    assert contract["status"] == "REPLANT_REQUIRED", (
        "75.00 fails the cost-share 80.00 bar and flips the contract"
    )


def test_survey_window_rejection_then_rounded_pct(api):
    """PRD §3.6: "`surveyed_on` must fall no earlier than 300 days and no later
    than 400 days after the contract's `last_planted_on`, both bounds inclusive
    — a survey outside that window is rejected with `ERR_SURVEY_WINDOW_INVALID`"
    and "The survey's `survival_pct` is the `alive_count` divided by the
    `planted_count_snapshot`, multiplied by 100, and rounded half-up to exactly
    two decimal places."

    Design: Corner/validations/survey_window_rejection_then_rounded_pct
    """
    ctx = _planted_world(api)
    contract_id = ctx["contract"]["id"]

    # 2027-08-01 is 122 days after the 2027-04-01 planting: below the 300-day floor.
    early = api.create_survival_survey(
        {"planting_contract_id": contract_id, "surveyed_on": "2027-08-01",
         "alive_count": 3000}, FA
    )
    validate_error(early, ApiErrorId.ERR_SURVEY_WINDOW_INVALID)

    set_clock("2028-02-15T00:00:00Z")
    survey = get_success_data(
        api.create_survival_survey(
            {"planting_contract_id": contract_id, "surveyed_on": "2028-02-15",
             "alive_count": 2666}, FA
        )
    )
    assert survey["survival_pct"] == pytest.approx(66.65, abs=0.001), (
        f"2666/4000 rounds half-up to 66.65 at two decimals, got {survey['survival_pct']}"
    )
    assert survey["below_threshold"] is True
    assert survey["obligation_status"] == "OPEN"
    assert survey["owed_quantity"] == 134, (
        f"ceil(4000 * 0.70) - 2666 = 134 owed, got {survey['owed_quantity']}"
    )

    contract = get_success_data(api.get_planting_contract(contract_id, CO))
    assert contract["status"] == "REPLANT_REQUIRED"


def test_waive_replant_reason_and_admin_denial(api):
    """PRD §3.6: "A `ProgramAdministrator` may instead waive an `OPEN`
    obligation with a non-empty `waiver_reason`, moving it to `WAIVED` and
    recording the reason on the survey." and PRD §4: "POST |
    `/reforestation/survival-surveys/{id}/waive-replant` | Waive the obligation
    | ProgramAdministrator" and PRD §2.6 rule 18: "Request shape: required
    fields present and well-typed, enum values within their declared sets —
    otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/validations/waive_replant_missing_required_reason_and_admin_denial
    """
    ctx = setup_replant_required_world(alive_count=2700)  # 67.50 < 70.00 -> OPEN
    survey = ctx["survey"]
    assert survey["obligation_status"] == "OPEN"

    missing = api.waive_replant(survey["id"], {}, PA)
    validate_error(missing, ApiErrorId.ERR_INVALID_REQUEST)

    wrong_role = api.waive_replant(
        survey["id"], {"waiver_reason": "landowner sold the parcel"}, CO
    )
    validate_error(wrong_role, ApiErrorId.ERR_UNAUTHORIZED)

    waived = get_success_data(
        api.waive_replant(survey["id"], {"waiver_reason": "landowner sold the parcel"}, PA)
    )
    assert waived["obligation_status"] == "WAIVED"
    assert waived["waiver_reason"] == "landowner sold the parcel"
