"""
Validation priority conflicts: two guards violated at once on a single request.

The ladder of the validation section is ascending and the first failing rung wins, so
a request that breaks both a state rule and a fiscal rule must report the state rule,
and a request that breaks both a referential rule and an evidence-count rule must
report the referential one. In each case the losing rule's own side effects must also
be absent, which is what proves nothing was half-applied.
"""

from test_helpers import (
    ApiErrorId,
    DESK_REVIEWER_HEADERS,
    CHIEF_APPRAISER_HEADERS,
    factories as f,
    fixtures as fx,
    validate_error,
)


def _grid(street):
    return [
        {
            "street_address": f"71 {street}",
            "sale_price_cents": 39000000,
            "gross_adjustment_cents": 390000,
            "net_adjustment_cents": 390000,
            "distance_miles": 1.0,
            "sale_date": "2026-05-01T00:00:00Z",
        },
        {
            "street_address": f"72 {street}",
            "sale_price_cents": 40000000,
            "gross_adjustment_cents": 400000,
            "net_adjustment_cents": 0,
            "distance_miles": 1.5,
            "sale_date": "2026-06-01T00:00:00Z",
        },
        {
            "street_address": f"73 {street}",
            "sale_price_cents": 41000000,
            "gross_adjustment_cents": 410000,
            "net_adjustment_cents": -410000,
            "distance_miles": 2.0,
            "sale_date": "2026-06-15T00:00:00Z",
        },
    ]


def _assigned_order_with_no_budget_left(api):
    """A field-review order already staffed at 45000 cents against a 50000 cent budget,
    plus a third eligible appraiser holding no windows at all."""
    env = fx.escalated_and_assigned(
        api,
        window_start="2026-08-02T09:00:00Z",
        window_end="2026-08-02T12:00:00Z",
        amc={
            "name": "Thrift Appraisal Management",
            "escalation_budget_cents": 50000,
        },
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-5001",
            "license_state": "CA",
        },
        reviewer={
            "full_name": "Bob Reviewer",
            "license_number": "CA-BR-5001",
            "license_state": "CA",
        },
        loan={
            "loan_number": "LN-2747-5A1",
            "risk_tier": "HIGH",
            "borrower_display_name": "Gil Borrower",
        },
        appraisal={"exhibit_count": 1},
        comparables=_grid("Chestnut Street"),
    )
    assert env["order"]["total_cost_cents"] == 45000
    assert env["amc"]["ytd_escalation_spend_cents"] == 45000

    standby = fx.create_appraiser(
        api, full_name="Cara Standby", license_number="CA-CS-5001",
        license_state="CA",
    )
    fx.enroll_on_panel(api, standby["id"], env["amc"]["id"], tier="REVIEW_SPECIALIST")
    env["standby"] = standby
    return env


def test_the_state_rung_beats_the_budget_rung_on_a_second_assignment(api):
    """Re-staffing an already assigned order reports the state rule, not the budget rule.

    Both guards fail on the same request: the order is in ASSIGNED rather than one of the
    two assignable states, and a second 45000 cent charge against a 50000 cent budget
    would breach the ceiling. The state rung sits earlier in the ladder, so its conflict
    is what comes back.

    PRD: "Validation always proceeds strictly in the following ascending order, and the
    **first** failing rung is the error returned; a later rung never masks an earlier
    one."

    Design: Difficulty/priority_pair_validation_conflict/escalation_assign_state_error_precedes_budget_error
    """
    env = _assigned_order_with_no_budget_left(api)

    response = api.assign_escalation_order(
        env["order"]["id"],
        f.assign_payload(
            env["standby"]["id"], "2026-08-05T09:00:00Z", "2026-08-05T12:00:00Z",
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ESCALATION_NOT_PENDING, 409)


def test_the_rejected_second_assignment_charges_and_moves_nothing(api):
    """Neither guard's side effects run: the order, the ledger and the counters hold.

    The order keeps its status, its original assignee and its priced total; the company's
    year-to-date spend still shows one charge rather than two; and the third appraiser,
    who was never accepted, carries no open assignment.

    PRD: "15. An escalation order being assigned is in `PENDING_ASSIGNMENT` or
    `REASSIGNMENT_REQUIRED` — otherwise `ERR_ESCALATION_NOT_PENDING` (409)."

    Design: Difficulty/priority_pair_validation_conflict/escalation_assign_state_error_precedes_budget_error
    """
    env = _assigned_order_with_no_budget_left(api)
    api.assign_escalation_order(
        env["order"]["id"],
        f.assign_payload(
            env["standby"]["id"], "2026-08-05T09:00:00Z", "2026-08-05T12:00:00Z",
        ),
        CHIEF_APPRAISER_HEADERS,
    )

    order = fx.read_escalation_order(api, env["order"]["id"])
    assert order["status"] == "ASSIGNED"
    assert order["assigned_appraiser_id"] == env["reviewer"]["id"]
    assert order["total_cost_cents"] == 45000

    amc = fx.read_amc(api, env["amc"]["id"])
    assert amc["ytd_escalation_spend_cents"] == 45000

    standby = fx.read_appraiser(api, env["standby"]["id"])
    assert standby["open_assignment_count"] == 0


WILLOW_GRID = [
    {
        "street_address": "81 Willow Street",
        "sale_price_cents": 39000000,
        "gross_adjustment_cents": 390000,
        "net_adjustment_cents": 390000,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "82 Willow Street",
        "sale_price_cents": 40000000,
        "gross_adjustment_cents": 400000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.5,
        "sale_date": "2026-06-01T00:00:00Z",
    },
    {
        "street_address": "83 Willow Street",
        "sale_price_cents": 41000000,
        "gross_adjustment_cents": 410000,
        "net_adjustment_cents": -410000,
        "distance_miles": 2.0,
        "sale_date": "2026-06-15T00:00:00Z",
    },
]


def _withdrawn_loan_with_thin_evidence(api):
    """A reconsideration holding one admissible item on a loan that has since been
    withdrawn, so routing it breaks the eligibility rule and the evidence rule at once."""
    env = fx.accepted_report(
        api,
        amc={"name": "Meridian Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-5002",
            "license_state": "CA",
        },
        loan={
            "loan_number": "LN-2747-5B1",
            "borrower_display_name": "Hana Borrower",
        },
        comparables=WILLOW_GRID,
    )
    assert env["appraisal"]["review_status"] == "VALUE_ACCEPTED"

    rov = fx.open_rov(
        api, env["loan"]["id"], env["appraisal"]["id"],
        requested_value_cents=42000000,
        borrower_statement="The gross living area was taken from a neighbor's tax card.",
    )
    fx.file_evidence(
        api, rov["id"], "DATA_ERROR_CITATION",
        street_address="84 Willow Street",
        citation_note="Gross living area transcribed from the adjacent parcel.",
    )
    fx.file_evidence(
        api, rov["id"], "OPINION_STATEMENT",
        street_address="85 Willow Street",
    )
    env["rov"] = fx.read_rov_request(api, rov["id"])
    assert env["rov"]["admissible_evidence_count"] == 1

    fx.move_underwriting(
        api, env["loan"]["id"], "WITHDRAWN",
        note="Borrower withdrew the refinance.",
    )
    return env


def test_the_eligibility_rung_beats_the_evidence_rung_on_routing(api):
    """Routing a thin reconsideration on a withdrawn loan reports the eligibility rule.

    Two guards fail together: the loan has left the eligible set of underwriting
    statuses, and the current round holds one admissible item where two are needed.
    The eligibility rung is the earlier of the two, so that is the refusal.

    PRD: "Validation always proceeds strictly in the following ascending order, and the
    **first** failing rung is the error returned; a later rung never masks an earlier
    one."

    Design: Difficulty/priority_pair_validation_conflict/rov_submit_referential_error_precedes_evidence_constraint
    """
    env = _withdrawn_loan_with_thin_evidence(api)

    response = api.submit_rov_request(
        env["rov"]["id"],
        f.rov_submit_payload(intake_note="Borrower package logged."),
        DESK_REVIEWER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_LOAN_NOT_ROV_ELIGIBLE, 422)


def test_the_refused_routing_leaves_the_reconsideration_untouched(api):
    """No routing side effect lands: the request stays in intake with no deadline.

    The reconsideration keeps its intake status, its single admissible item and a null
    response deadline, while the loan and the appraisal keep the statuses they held
    before the attempt.

    PRD: "27. The loan is eligible for reconsideration — otherwise
    `ERR_LOAN_NOT_ROV_ELIGIBLE` (422)."

    Design: Difficulty/priority_pair_validation_conflict/rov_submit_referential_error_precedes_evidence_constraint
    """
    env = _withdrawn_loan_with_thin_evidence(api)
    api.submit_rov_request(
        env["rov"]["id"],
        f.rov_submit_payload(intake_note="Borrower package logged."),
        DESK_REVIEWER_HEADERS,
    )

    rov = fx.read_rov_request(api, env["rov"]["id"])
    assert rov["status"] == "INTAKE"
    assert rov["admissible_evidence_count"] == 1
    assert rov["response_deadline_at"] is None

    loan = fx.read_loan_file(api, env["loan"]["id"])
    assert loan["underwriting_status"] == "WITHDRAWN"
    assert loan["collateral_status"] == "VALUE_ACCEPTED"

    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["review_status"] == "VALUE_ACCEPTED"
