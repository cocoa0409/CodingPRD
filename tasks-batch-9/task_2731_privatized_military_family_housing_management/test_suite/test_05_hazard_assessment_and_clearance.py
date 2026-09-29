"""The hazard protocol: the assessment fork, its cascade, clearance and the void."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as asserts
from test_helpers import constants as const
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as tu
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS

HAZARD_CLOCK = "2026-09-20T10:00:00Z"
REMEDIATION_CLOCK = "2026-09-25T09:00:00Z"
SEPTEMBER = "2026-09"

# Eleven inclusive days of September remain from the assessment date, so the
# junior family's credit would be 11 x 7172 and the senior family's 11 x 8153.
JUNIOR_ABATEMENT_CENTS = 78892
JUNIOR_BALANCE_AFTER_ABATEMENT_CENTS = 139258
SENIOR_ABATEMENT_CENTS = 89683
SENIOR_BALANCE_AFTER_ABATEMENT_CENTS = 158317

MILD_SQFT = 8
SEVERE_SQFT = 45


def _two_charged_tenancies_with_hazards_reported(api):
    """Two occupied units, both charged for September, both with a case open.

    The junior-enlisted family holds the two-bedroom TOWNHOME at 7172 a day and
    the senior-enlisted family the three-bedroom SFH at 8153 a day, so the two
    fork branches are told apart by their money as well as by their states.
    """
    state = fx.setup_two_occupied_tenancies(api)
    fx.set_clock(api, HAZARD_CLOCK)
    fx.run_allotment_run(api, state["installation"]["id"], SEPTEMBER)
    state["hazard_cases"] = [
        fx.report_hazard(
            api,
            state["units"][index]["id"],
            lease_id=state["leases"][index]["id"],
            hazard_type="MOLD",
            reported_symptoms=symptoms,
        )
        for index, symptoms in enumerate(
            (
                "Small patch behind the bathroom door frame",
                "Extensive growth across two bedroom walls",
            )
        )
    ]
    return state


def test_mild_finding_leaves_the_family_in_place_and_the_ledger_alone(api):
    """Eight square feet grades at the floor, so nothing but the case moves.

    PRD: "**Branch A** is taken when `displacement_required` is false: the case advances `ASSESSED → REMEDIATION_IN_PROGRESS`, the unit's `status` is **not** changed, the household stays in place, the lease's `allotment_status` is **not** changed, and **no** `ABATEMENT` row is posted."

    Design: Difficulty/non_linear_state_machine/hazard_case_assessment_fork_rejoins_at_clearance_pending
    """
    state = _two_charged_tenancies_with_hazards_reported(api)

    assessed = fx.assess_hazard(
        api,
        state["hazard_cases"][0]["id"],
        affected_area_sqft=MILD_SQFT,
        child_under_six_present=True,
    )

    asserts.assert_hazard_case(assessed)
    assert assessed["assessment_severity"] == "SEVERITY_1"
    assert assessed["displacement_required"] is False
    assert assessed["status"] == "REMEDIATION_IN_PROGRESS"
    lease = fx.read_lease(api, state["leases"][0]["id"])
    assert lease["allotment_status"] == "ACTIVE"
    assert lease["occupancy_status"] == "OCCUPIED"
    assert lease["allotment_balance_cents"] == const.BASE_NET_RENT_CENTS
    assert lease["abatement_total_cents"] == 0
    ledger = fx.read_ledger(api, lease["id"])
    assert [row["type"] for row in ledger] == ["CHARGE"]
    assert fx.read_housing_unit(api, state["units"][0]["id"])["status"] == "OCCUPIED"


def test_severe_finding_displaces_the_family_and_credits_the_month(api):
    """Forty-five square feet on the other unit runs the whole cascade instead.

    PRD: "**Branch B** is taken when `displacement_required` is true: the case advances `ASSESSED → DISPLACEMENT_ACTIVE`, and a four-deep cascade fires that branch A does not run."

    Design: Difficulty/non_linear_state_machine/hazard_case_assessment_fork_rejoins_at_clearance_pending
    """
    state = _two_charged_tenancies_with_hazards_reported(api)

    assessed = fx.assess_hazard(
        api,
        state["hazard_cases"][1]["id"],
        affected_area_sqft=SEVERE_SQFT,
        child_under_six_present=True,
    )

    assert assessed["assessment_severity"] == "SEVERITY_3"
    assert assessed["displacement_required"] is True
    assert assessed["status"] == "DISPLACEMENT_ACTIVE"
    lease = fx.read_lease(api, state["leases"][1]["id"])
    assert lease["allotment_status"] == "SUSPENDED"
    assert lease["occupancy_status"] == "OCCUPIED"
    assert lease["daily_rent_cents"] == const.E7_DAILY_RENT_CENTS
    assert lease["abatement_total_cents"] == SENIOR_ABATEMENT_CENTS
    assert lease["allotment_balance_cents"] == SENIOR_BALANCE_AFTER_ABATEMENT_CENTS
    ledger = fx.read_ledger(api, lease["id"])
    assert [row["type"] for row in ledger] == ["CHARGE", "ABATEMENT"]
    assert ledger[1]["amount_cents"] == -SENIOR_ABATEMENT_CENTS
    asserts.assert_ledger_conservation(ledger, lease)
    assert fx.read_housing_unit(api, state["units"][1]["id"])["status"] == "HAZARD_HOLD"
    installation = fx.read_installation(api, state["installation"]["id"])
    assert installation["occupied_unit_count"] == 1
    assert installation["hazard_hold_unit_count"] == 1
    assert installation["total_unit_count"] == 2
    asserts.assert_installation_counter_conservation(installation)


def test_both_fork_branches_rejoin_at_clearance_pending(api):
    """Disjoint side effects, one shared next state once the repairs are done.

    PRD: "From `REMEDIATION_IN_PROGRESS` the transition to `CLEARANCE_PENDING` carries no lodging and no ledger effects, because branch A never created any."

    Design: Difficulty/non_linear_state_machine/hazard_case_assessment_fork_rejoins_at_clearance_pending
    """
    state = _two_charged_tenancies_with_hazards_reported(api)
    mild = fx.assess_hazard(
        api,
        state["hazard_cases"][0]["id"],
        affected_area_sqft=MILD_SQFT,
        child_under_six_present=True,
    )
    severe = fx.assess_hazard(
        api,
        state["hazard_cases"][1]["id"],
        affected_area_sqft=SEVERE_SQFT,
        child_under_six_present=True,
    )
    assert mild["status"] != severe["status"]

    fx.set_clock(api, REMEDIATION_CLOCK)
    fx.complete_remediation(api, mild)
    fx.complete_remediation(api, severe)

    assert fx.read_hazard_case(api, mild["id"])["status"] == "CLEARANCE_PENDING"
    assert fx.read_hazard_case(api, severe["id"])["status"] == "CLEARANCE_PENDING"
    # Branch A's ledger is still untouched where branch B's carries the credit.
    assert len(fx.read_ledger(api, state["leases"][0]["id"])) == 1
    assert len(fx.read_ledger(api, state["leases"][1]["id"])) == 2


def _charged_tenancy_with_a_case_reported(api):
    """The canonical tenancy, charged for September, one MOLD case in REPORTED."""
    state = fx.setup_charged_lease(api)
    return fx.setup_reported_hazard(
        api,
        occupied_state=state,
        hazard_clock=HAZARD_CLOCK,
        lease_id=state["lease"]["id"],
        reported_symptoms="Extensive growth across master bedroom wall",
    )


def _assess_severely(api, state):
    return fx.assess_hazard(
        api,
        state["hazard_case"]["id"],
        affected_area_sqft=SEVERE_SQFT,
        child_under_six_present=True,
    )


def test_assessment_grades_the_finding_and_opens_the_remediation_order(api):
    """The first hop stamps the grading and dispatches the repair in one request.

    PRD: "Assessment stamps `assessment_severity`, `child_under_six_present` and `displacement_required`, records `assessed_by_user_id` from the acting `X-User-ID` and `assessed_at` from the logical clock, and creates the remediation work order on the unit — with `category` `MOLD_SUSPECTED` for a mold case or `LEAD_SUSPECTED` for either lead case, and `habitability_impact` set to whatever `displacement_required` came out as — storing the new order's identifier in `remediation_work_order_id`."

    Design: Difficulty/transitive_cascade/hazard_assessment_cascades_hold_suspension_and_abatement
    """
    state = _charged_tenancy_with_a_case_reported(api)
    assert state["hazard_case"]["status"] == "REPORTED"

    assessed = _assess_severely(api, state)

    asserts.assert_hazard_case(assessed)
    assert assessed["assessment_severity"] == "SEVERITY_3"
    assert assessed["displacement_required"] is True
    assert assessed["child_under_six_present"] is True
    assert assessed["status"] == "DISPLACEMENT_ACTIVE"
    assert assessed["assessed_by_user_id"] == tu.ENVIRONMENTAL_SPECIALIST_USER_ID
    asserts.assert_instant_equals(assessed["assessed_at"], HAZARD_CLOCK)
    assert assessed["affected_area_sqft"] == SEVERE_SQFT
    assert assessed["lead_level_ppm"] is None
    assert assessed["remediation_work_order_id"] is not None
    order = fx.find_remediation_work_order(api, assessed)
    asserts.assert_work_order(order)
    assert order["housing_unit_id"] == state["unit"]["id"]
    assert order["category"] == "MOLD_SUSPECTED"
    assert order["habitability_impact"] is True
    assert order["status"] == "SUBMITTED"


def test_displacement_puts_the_unit_on_hold_and_suspends_the_allotment(api):
    """Hops two and three reach the unit and then the lease standing on it.

    PRD: "As a second hop the unit advances `OCCUPIED → HAZARD_HOLD` and its `hazard_hold_reason` is stamped with the hazard type together with the reason for displacement — the severity being `SEVERITY_3`, or `SEVERITY_2` with a child under six — while the installation's `occupied_unit_count` and `hazard_hold_unit_count` are recomputed and the unit's `version` is incremented by 1."

    Design: Difficulty/transitive_cascade/hazard_assessment_cascades_hold_suspension_and_abatement
    """
    state = _charged_tenancy_with_a_case_reported(api)
    unit_before = fx.read_housing_unit(api, state["unit"]["id"])
    lease_before = fx.read_lease(api, state["lease"]["id"])

    _assess_severely(api, state)

    unit = fx.read_housing_unit(api, state["unit"]["id"])
    assert unit["status"] == "HAZARD_HOLD"
    assert unit["hazard_hold_reason"]
    assert unit["version"] == unit_before["version"] + 1
    installation = fx.read_installation(api, state["installation"]["id"])
    assert installation["hazard_hold_unit_count"] == 1
    assert installation["occupied_unit_count"] == 0
    assert installation["total_unit_count"] == 1
    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["allotment_status"] == "SUSPENDED"
    assert lease["occupancy_status"] == "OCCUPIED"
    assert lease["version"] > lease_before["version"]


def test_the_suspension_credits_the_remainder_of_the_assessment_month(api):
    """The fourth hop posts one negative row and recomputes the lease's totals.

    PRD: "The posted row is an `ABATEMENT` whose `period_month` is that month, whose `amount_cents` is the lease's stored `daily_rent_cents` multiplied by that day count and then **negated** — the negative sign is part of the amount, so the running balance decreases — and whose `source_ref` is the string `HAZARD_ABATEMENT:` followed by the hazard case's identifier."

    Design: Difficulty/transitive_cascade/hazard_assessment_cascades_hold_suspension_and_abatement
    """
    state = _charged_tenancy_with_a_case_reported(api)

    assessed = _assess_severely(api, state)

    ledger = fx.read_ledger(api, state["lease"]["id"])
    assert [row["type"] for row in ledger] == ["CHARGE", "ABATEMENT"]
    for row in ledger:
        asserts.assert_allotment_transaction(row)
    charge, abatement = ledger
    assert charge["amount_cents"] == const.BASE_NET_RENT_CENTS
    assert charge["running_balance_cents"] == const.BASE_NET_RENT_CENTS
    assert abatement["period_month"] == SEPTEMBER
    # Eleven inclusive days, 2026-09-20 through 2026-09-30, at 7172 a day.
    assert abatement["amount_cents"] == -JUNIOR_ABATEMENT_CENTS
    assert (
        abatement["running_balance_cents"] == JUNIOR_BALANCE_AFTER_ABATEMENT_CENTS
    )
    assert abatement["source_ref"] == f"HAZARD_ABATEMENT:{assessed['id']}"
    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["allotment_balance_cents"] == JUNIOR_BALANCE_AFTER_ABATEMENT_CENTS
    assert lease["abatement_total_cents"] == JUNIOR_ABATEMENT_CENTS
    asserts.assert_ledger_conservation(ledger, lease)


def _displaced_household(api):
    """A charged tenancy driven into displacement by a severe mold finding."""
    state = fx.setup_charged_lease(api)
    return fx.setup_displaced_household(
        api,
        occupied_state=state,
        hazard_clock=HAZARD_CLOCK,
        report_overrides={
            "lease_id": state["lease"]["id"],
            "reported_symptoms": "Widespread growth across the master bedroom wall",
        },
        assess_overrides={"child_under_six_present": True},
    )


def _clearance_attempt(api, hazard_case_id):
    """The clearance request, always from the specialist who did not assess."""
    return api.certify_clearance(
        hazard_case_id,
        f.clearance_payload(True),
        TEST_USERS["environmental_specialist_2_headers"],
    )


def test_clearance_before_the_remediation_order_completes_is_refused(api):
    """A well-formed clearance from the right specialist still has nowhere to go.

    PRD: "The request carries a single `clearance_test_passed` boolean and requires the case to be in `CLEARANCE_PENDING`."

    Design: Difficulty/cross_entity_state_dependency/hazard_clearance_gated_on_remediation_work_order_completion
    """
    state = _displaced_household(api)
    case = state["hazard_case"]
    assert case["status"] == "DISPLACEMENT_ACTIVE"
    assert fx.find_remediation_work_order(api, case)["status"] == "SUBMITTED"

    response = _clearance_attempt(api, case["id"])

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
    refused = fx.read_hazard_case(api, case["id"])
    assert refused["status"] == "DISPLACEMENT_ACTIVE"
    assert refused["clearance_test_passed"] is None
    assert refused["cleared_by_user_id"] is None
    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "HAZARD_HOLD"
    assert fx.read_lease(api, state["lease"]["id"])["allotment_status"] == "SUSPENDED"


def test_completing_the_remediation_order_is_what_arms_the_clearance(api):
    """There is no endpoint for it: the separate work order moves the case.

    PRD: "Both fork branches converge on `CLEARANCE_PENDING`, driven by the system when the work order named by `remediation_work_order_id` reaches `COMPLETED` or `CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/hazard_clearance_gated_on_remediation_work_order_completion
    """
    state = _displaced_household(api)
    case = state["hazard_case"]
    validate_error(
        _clearance_attempt(api, case["id"]), ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409
    )

    completed = fx.complete_remediation(api, case)

    assert completed["status"] == "COMPLETED"
    assert completed["id"] == case["remediation_work_order_id"]
    armed = fx.read_hazard_case(api, case["id"])
    assert armed["status"] == "CLEARANCE_PENDING"
    # Arming the clearance does not itself lift the hold or restart collection.
    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "HAZARD_HOLD"
    assert fx.read_lease(api, state["lease"]["id"])["allotment_status"] == "SUSPENDED"


def test_the_identical_clearance_request_then_closes_the_case(api):
    """The same bytes that were refused now pass, and the earned credit stays.

    PRD: "On a **pass**, `cleared_by_user_id` and `clearance_test_passed` are stamped, the case advances `CLEARANCE_PENDING → CLOSED`, which is terminal, the unit advances `HAZARD_HOLD → OCCUPIED` with `hazard_hold_reason` cleared — but only when no other hazard case on that unit is in `DISPLACEMENT_ACTIVE`, `REMEDIATION_IN_PROGRESS` or `CLEARANCE_PENDING`, since a second open case keeps the hold in place — and the lease advances `SUSPENDED → ACTIVE` with **no reinstating ledger row**: the abatement was earned by a real habitability failure and stays on the ledger."

    Design: Difficulty/cross_entity_state_dependency/hazard_clearance_gated_on_remediation_work_order_completion
    """
    state = _displaced_household(api)
    case = state["hazard_case"]
    validate_error(
        _clearance_attempt(api, case["id"]), ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409
    )
    fx.complete_remediation(api, case)

    cleared = fx.certify_clearance(api, case["id"], True)

    assert cleared["status"] == "CLOSED"
    assert cleared["clearance_test_passed"] is True
    assert cleared["cleared_by_user_id"] == tu.ENVIRONMENTAL_SPECIALIST_USER_ID_2
    assert cleared["cleared_by_user_id"] != cleared["assessed_by_user_id"]
    unit = fx.read_housing_unit(api, state["unit"]["id"])
    assert unit["status"] == "OCCUPIED"
    assert unit["hazard_hold_reason"] is None
    installation = fx.read_installation(api, state["installation"]["id"])
    assert installation["hazard_hold_unit_count"] == 0
    assert installation["occupied_unit_count"] == 1
    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["allotment_status"] == "ACTIVE"
    ledger = fx.read_ledger(api, lease["id"])
    assert [row["type"] for row in ledger] == ["CHARGE", "ABATEMENT"]
    assert lease["allotment_balance_cents"] == JUNIOR_BALANCE_AFTER_ABATEMENT_CENTS
    assert lease["abatement_total_cents"] == JUNIOR_ABATEMENT_CENTS


LODGING_START_DATE = "2026-09-20"
LODGING_END_DATE = "2026-09-30"
LODGING_NIGHTLY_RATE_CENTS = 22000
LODGING_OCCUPANTS = 4
VOID_REASON = (
    "Laboratory re-analysis identified the sample as harmless efflorescence, not mold"
)


def _displaced_with_lodging_and_a_capital_account(api):
    """Every side effect a void must unwind, all standing at once."""
    state = _displaced_household(api)
    fx.setup_account(api, occupied_state=state)
    state["lodging"] = fx.authorize_lodging(
        api,
        state["hazard_case"]["id"],
        state["lease"]["id"],
        start_date=LODGING_START_DATE,
        end_date=LODGING_END_DATE,
        nightly_rate_cents=LODGING_NIGHTLY_RATE_CENTS,
        occupants_count=LODGING_OCCUPANTS,
    )
    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["allotment_balance_cents"] == JUNIOR_BALANCE_AFTER_ABATEMENT_CENTS
    assert lease["abatement_total_cents"] == JUNIOR_ABATEMENT_CENTS
    return state


def _void(api, state):
    return fx.void_hazard(
        api,
        state["hazard_case"]["id"],
        VOID_REASON,
        TEST_USERS["installation_housing_office_headers"],
    )


def test_void_appends_a_reversing_row_instead_of_editing_history(api):
    """The credit that should not have been given is undone by a third row.

    PRD: "Rows are never updated and never deleted; a correction is always a new, oppositely signed row."

    Design: Difficulty/compensating_invariant/hazard_void_restores_allotment_ledger_without_drift
    """
    state = _displaced_with_lodging_and_a_capital_account(api)

    voided = _void(api, state)

    assert voided["status"] == "VOIDED"
    ledger = fx.read_ledger(api, state["lease"]["id"])
    assert [row["type"] for row in ledger] == [
        "CHARGE",
        "ABATEMENT",
        "ARREARS_ADJUSTMENT",
    ]
    asserts.assert_created_at_ascending(ledger)
    charge, abatement, reversal = ledger
    assert charge["amount_cents"] == const.BASE_NET_RENT_CENTS
    assert charge["running_balance_cents"] == const.BASE_NET_RENT_CENTS
    # The original credit is still on the ledger, untouched and still negative.
    assert abatement["amount_cents"] == -JUNIOR_ABATEMENT_CENTS
    assert abatement["running_balance_cents"] == JUNIOR_BALANCE_AFTER_ABATEMENT_CENTS
    assert reversal["amount_cents"] == JUNIOR_ABATEMENT_CENTS
    assert reversal["running_balance_cents"] == const.BASE_NET_RENT_CENTS
    for row in ledger:
        asserts.assert_allotment_transaction(row)


def test_void_returns_the_ledger_to_its_pre_abatement_value_without_drift(api):
    """The reversal lands on the old balance exactly, and the totals go to zero.

    PRD: "Every `ABATEMENT` row this case posted is reversed by an equal and opposite `ARREARS_ADJUSTMENT` row — a positive amount equal to the absolute value of the sum of the `ABATEMENT` rows whose `source_ref` names this case — which restores the lease's `allotment_balance_cents` to its pre-abatement value and drives `abatement_total_cents` back to exactly 0 with no drift."

    Design: Difficulty/compensating_invariant/hazard_void_restores_allotment_ledger_without_drift
    """
    state = _displaced_with_lodging_and_a_capital_account(api)

    _void(api, state)

    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["allotment_balance_cents"] == const.BASE_NET_RENT_CENTS
    assert lease["abatement_total_cents"] == 0
    assert lease["allotment_status"] == "ACTIVE"
    assert lease["occupancy_status"] == "OCCUPIED"
    asserts.assert_ledger_conservation(fx.read_ledger(api, lease["id"]), lease)
    unit = fx.read_housing_unit(api, state["unit"]["id"])
    assert unit["status"] == "OCCUPIED"
    assert unit["hazard_hold_reason"] is None
    installation = fx.read_installation(api, state["installation"]["id"])
    assert installation["hazard_hold_unit_count"] == 0
    assert installation["occupied_unit_count"] == 1
    assert installation["total_unit_count"] == 1
    asserts.assert_installation_counter_conservation(installation)


def test_void_closes_the_lodging_at_zero_nights_and_moves_no_capital(api):
    """Unwinding the case also unwinds the money it would have spent.

    PRD: "Every `AUTHORIZED` lodging on the case is closed with `actual_end_date` set equal to its own `start_date`, which yields `nights_displaced` of 0 and `lodging_authorized_cents` of 0."

    Design: Difficulty/compensating_invariant/hazard_void_restores_allotment_ledger_without_drift
    """
    state = _displaced_with_lodging_and_a_capital_account(api)
    assert state["lodging"]["status"] == "AUTHORIZED"
    assert state["lodging"]["actual_end_date"] is None

    _void(api, state)

    lodging = fx.read_lodging(api, state["lodging"]["id"])
    asserts.assert_displacement_lodging(lodging)
    assert lodging["status"] == "CLOSED"
    assert lodging["actual_end_date"] == LODGING_START_DATE
    assert lodging["nights_displaced"] == 0
    assert lodging["lodging_authorized_cents"] == 0
    assert lodging["rent_abatement_cents"] == 0
    account = fx.read_account(api, state["account"]["id"])
    asserts.assert_reinvestment_account(account)
    assert account["expenditures_cents"] == 0
    assert account["closing_balance_cents"] == const.TEST_DEFAULTS[
        "OPENING_BALANCE_CENTS"
    ]
    order = fx.read_work_order(api, state["hazard_case"]["remediation_work_order_id"])
    assert order["status"] == "CLOSED"
