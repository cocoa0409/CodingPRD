"""Administrative dissolution, permanent closure and the reinstatement cycle."""
from test_helpers import (
    AGENT,
    DE_RULE_REINSTATEMENT_V1,
    DE_RULE_REINSTATEMENT_V2,
    DE_RULE_WINDOW_LAPSE,
    OFFICER,
    assess_fees,
    draft_standalone_filing,
    new_payment,
    capture,
    open_reinstatement_case,
    ops_run,
    publish_rule,
    read_case,
    read_client,
    read_filing,
    read_obligation,
    read_registration,
    set_clock,
    setup_admin_dissolved_registration,
    submit_filing,
    validate_success,
)


def test_lapsed_reinstatement_window_closes_the_registration_permanently(api):
    """PRD §3.11: "`reinstatement_deadline` is set at the same moment: it is
    `admin_dissolved_on` plus the `reinstatement_window_days` of the rule effective for
    the registration's `state_code` **on `admin_dissolved_on`**, with no weekend or
    holiday roll."
    PRD §3.11: "When the ops-run finds an `ADMIN_DISSOLVED` registration whose
    `reinstatement_deadline` is strictly behind the current clock date, the registration
    moves to `CLOSED_PERMANENT` and `closed_on` is stamped with the current clock date.
    Every reinstatement case still open on that registration moves to `EXPIRED`, and
    every obligation of the registration in one of the four open statuses is voided —
    set to `VOIDED` with `satisfied_on` stamped at the current clock date and
    `total_due_cents` zeroed, with its pending reminder notices suppressed."
    PRD §3.11: "`CLOSED_PERMANENT` is terminal, and a registration in it has
    `delinquency_rank` 4."

    Design: Corner/state_machines/corner_reinstatement_window_lapse_closes_registration_permanently
    """
    scene = setup_admin_dissolved_registration(DE_RULE_WINDOW_LAPSE)
    registration = scene["registration"]

    assert registration["status"] == "ADMIN_DISSOLVED"
    assert registration["admin_dissolved_on"] == "2027-06-01"
    # 2027-06-01 plus the rule's 365 reinstatement_window_days, over a span that
    # includes 2028-02-29, is 2028-05-31.
    assert registration["reinstatement_deadline"] == "2028-05-31"

    case = open_reinstatement_case(registration["id"])
    assert case["window_close_date"] == "2028-05-31"

    set_clock("2028-06-01T00:00:00Z")
    ops_run()

    closed = read_registration(registration["id"])
    assert closed["status"] == "CLOSED_PERMANENT"
    assert closed["closed_on"] == "2028-06-01"
    assert closed["delinquency_rank"] == 4

    assert read_case(case["id"], registration["id"])["status"] == "EXPIRED"

    voided = read_obligation(scene["obligation"]["id"])
    assert voided["status"] == "VOIDED"
    assert voided["total_due_cents"] == 0

    assert (
        read_client(scene["client"]["id"])["portfolio_delinquency_status"]
        == "ADMIN_DISSOLVED"
    )


def test_reinstatement_prices_each_missed_period_under_its_own_pinned_rule(api):
    """PRD §3.11: "Each missed period contributes its own `state_fee_cents`, plus its
    franchise tax recomputed under **its own pinned rule version**, plus its late fee
    recomputed under that same pinned version at the assessment date."
    PRD §3.11: "`back_fee_total_cents` is the sum of the per-period components plus the
    `reinstatement_fee_cents` of the rule effective for the registration's `state_code`
    on the assessment date, and each component is rounded to whole cents by its own
    calculation before the sum."
    PRD §3.11: "The missed periods are the registration's obligations whose `status` is
    `IN_GRACE` or `DELINQUENT` at assessment time; obligations in `SCHEDULED`,
    `SATISFIED`, `WAIVED` or `VOIDED` are excluded."

    Design: Corner/calculations/corner_reinstatement_prices_each_period_under_its_own_rule_and_cures_on_grant
    """
    scene = setup_admin_dissolved_registration(DE_RULE_REINSTATEMENT_V1)
    pinned_rule_id = scene["obligation"]["governing_rule_id"]

    publish_rule(DE_RULE_REINSTATEMENT_V2)
    set_clock("2027-08-01T00:00:00Z")
    case = open_reinstatement_case(scene["registration"]["id"])

    assessed = assess_fees(case["id"])

    assert assessed["assessment_date"] == "2027-08-01"
    assert assessed["missed_period_count"] == 1
    # The 2027 period is priced under its own pinned version v1: state 5000 plus the
    # flat late fee 20000 gives 25000. Only the reinstatement fee comes from the rule
    # effective on the assessment date, v2's 40000. 25000 + 40000 = 65000.
    assert assessed["back_fee_total_cents"] == 65000
    assert read_obligation(scene["obligation"]["id"])["governing_rule_id"] == pinned_rule_id


def test_granting_reinstatement_returns_the_registration_and_cures_its_periods(api):
    """PRD §3.11: "On success the case moves to `GRANTED` and `obligations_cured_count`
    is set equal to `missed_period_count`. The registration moves `ADMIN_DISSOLVED →
    ACTIVE` with `admin_dissolved_on` cleared to null, and every obligation counted in
    the case's `missed_period_count` is flipped to `SATISFIED` with `satisfied_on`
    stamped at the current clock date, which in turn suppresses each of their pending
    reminder notices."
    PRD §3.7: "for a `REINSTATEMENT` the `back_fee_total_cents` already assessed on the
    reinstatement case; and `service_fee_cents` is the base service charge of 4900
    cents."

    Design: Corner/calculations/corner_reinstatement_prices_each_period_under_its_own_rule_and_cures_on_grant
    """
    scene = setup_admin_dissolved_registration(DE_RULE_REINSTATEMENT_V1)
    publish_rule(DE_RULE_REINSTATEMENT_V2)
    set_clock("2027-08-01T00:00:00Z")
    case = open_reinstatement_case(scene["registration"]["id"])
    assess_fees(case["id"])

    filing = draft_standalone_filing(
        scene["registration"]["id"], "REINSTATEMENT", reinstatement_case_id=case["id"]
    )
    # 65000 back fees carried as the state fee plus the 4900 base service charge.
    assert filing["state_fee_cents"] == 65000
    assert filing["service_fee_cents"] == 4900
    assert filing["total_fee_cents"] == 69900

    payment = new_payment(scene["client"]["id"], 69900)
    capture(payment["id"], 69900, filing["id"])
    submit_filing(filing["id"])

    granted = validate_success(api.grant_reinstatement(case["id"], AGENT))

    assert granted["status"] == "GRANTED"
    assert granted["obligations_cured_count"] == 1

    registration = read_registration(scene["registration"]["id"])
    assert registration["status"] == "ACTIVE"
    assert registration["admin_dissolved_on"] is None

    cured = read_obligation(scene["obligation"]["id"])
    assert cured["status"] == "SATISFIED"
    assert cured["satisfied_on"] == "2027-08-01"

    assert (
        read_client(scene["client"]["id"])["portfolio_delinquency_status"] == "CURRENT"
    )
    assert read_filing(filing["id"])["status"] == "SUBMITTED"


def test_denied_case_can_be_assessed_again_while_the_window_is_open(api):
    """PRD §3.11: "The case moves to `DENIED`, records the reason, and its `version`
    increases by 1. The registration is not moved and its obligations are untouched. A
    denied case is not dead: it can be assessed again while the window is open, which
    returns it to `FEES_ASSESSED`."
    PRD §3.11: "The case must be in `OPEN` or in `DENIED` — the second is the retry path
    after a denial — and the current clock date must still be on or before
    `window_close_date`, else `ERR_REINSTATEMENT_WINDOW_CLOSED`. On success the case
    moves to `FEES_ASSESSED`, `assessment_date` is stamped with the current clock date,
    and the money is computed."

    Design: Corner/calculations/corner_reinstatement_denial_allows_a_second_assessment
    """
    scene = setup_admin_dissolved_registration(DE_RULE_REINSTATEMENT_V1)
    set_clock("2027-08-01T00:00:00Z")
    case = open_reinstatement_case(scene["registration"]["id"])

    assessed = assess_fees(case["id"])
    # Only version 1 of the Delaware rule exists here, so every component comes from
    # it: state 5000 + flat late fee 20000 + reinstatement fee 16900 = 41900.
    assert assessed["back_fee_total_cents"] == 41900

    filing = draft_standalone_filing(
        scene["registration"]["id"], "REINSTATEMENT", reinstatement_case_id=case["id"]
    )
    # 41900 back fees plus the 4900 base service charge.
    assert filing["total_fee_cents"] == 46800
    payment = new_payment(scene["client"]["id"], 46800)
    capture(payment["id"], 46800, filing["id"])
    submit_filing(filing["id"])

    denied = validate_success(
        api.deny_reinstatement(
            case["id"], {"denial_reason": "Franchise tax clearance letter missing"}, AGENT
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "Franchise tax clearance letter missing"

    set_clock("2027-09-01T00:00:00Z")
    reassessed = assess_fees(case["id"])

    assert reassessed["status"] == "FEES_ASSESSED"
    assert reassessed["assessment_date"] == "2027-09-01"
    assert read_registration(scene["registration"]["id"])["status"] == "ADMIN_DISSOLVED"
