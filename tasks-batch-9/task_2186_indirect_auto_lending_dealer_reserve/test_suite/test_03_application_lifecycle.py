"""Credit application intake, the revision cycle, and submission gating."""
from test_helpers import (
    ADMIN, ANALYST, ApiErrorId, api_client, assert_application, dealer_status_action,
    decision_application, make_dealer_principal_headers, read_application,
    resubmit_application, setup_program, submit_application, validate_error,
    validate_paginated, validate_success,
)


def test_new_application_is_submitted_with_every_pinned_field_null(api):
    """PRD 3.3: "A new application is created in `SUBMITTED`, with `agreement_id`,
    `rate_sheet_id`, `assigned_tier_id`, `base_tier_code`, `assigned_tier_code`,
    `buy_rate_apr_bps`, `max_contract_apr_bps`, `held_from_status`,
    `decisioned_by_user_id`, `decisioned_at`, and `decline_reason` all null, and
    `demotion_count`, `resubmission_count`, and `stipulation_count` all zero."
    PRD 3.3: "`ltv_pct` is `amount_financed_cents` multiplied by 100, divided by
    `collateral_value_cents`, rounded half up to two decimal places."

    Design: Corner/state_machines/application_initial_state_is_submitted
    """
    program = setup_program()

    response = api.create_application(
        {
            "dealer_id": program["dealer_id"],
            "applicant_reference": "APP-INIT",
            "monitoring_cohort": "CONTROL",
            "credit_score": 725,
            "monthly_income_cents": 600000,
            "monthly_debt_cents": 180000,
            "amount_financed_cents": 1000000,
            "collateral_value_cents": 1000000,
            "term_months": 60,
            "vehicle_model_year": 2023,
            "requested_apr_bps": 749,
        },
        program["dealer_headers"],
    )
    application = validate_success(response, 201)
    assert_application(application)

    assert application["status"] == "SUBMITTED"
    assert application["ltv_pct"] == 100.00
    assert application["dti_pct"] == 30.00
    assert application["resubmission_count"] == 0
    assert application["stipulation_count"] == 0
    assert application["demotion_count"] == 0
    for field in (
        "agreement_id", "rate_sheet_id", "assigned_tier_id", "base_tier_code",
        "assigned_tier_code", "buy_rate_apr_bps", "max_contract_apr_bps",
        "held_from_status", "decisioned_by_user_id", "decisioned_at", "decline_reason",
    ):
        assert application[field] is None, f"{field} must start null"


def test_application_missing_a_required_field_is_rejected(api):
    """PRD 3.3: "The credit and deal facts follow: `credit_score` between 300 and
    900, `monthly_income_cents` strictly greater than zero, `monthly_debt_cents` zero
    or greater, `amount_financed_cents` strictly greater than zero,
    `collateral_value_cents` strictly greater than zero, `term_months` between 12 and
    96, `vehicle_model_year` between 1990 and 2030, and `requested_apr_bps` — the APR
    the dealership intends to quote the customer — between 0 and 3600."
    PRD 2.7: "Request-body shape validation covers required fields being present,
    values being of the declared type, enum members being drawn from the declared
    set, numbers lying inside the ranges §3 states for them"

    Design: Corner/entities/application_missing_required_field_returns_invalid_request
    """
    program = setup_program()

    response = api.create_application(
        {
            "dealer_id": program["dealer_id"],
            "applicant_reference": "APP-BAD",
            "monitoring_cohort": "CONTROL",
            "credit_score": 725,
            "monthly_income_cents": 600000,
            "monthly_debt_cents": 180000,
            "amount_financed_cents": 1000000,
            "term_months": 60,
            "vehicle_model_year": 2023,
            "requested_apr_bps": 749,
        },
        program["dealer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(
        api.list_applications(ADMIN, params={"dealer_id": program["dealer_id"]})
    )
    assert meta["total_count"] == 0


def test_application_with_an_undeclared_monitoring_cohort_is_rejected(api):
    """PRD 3.3: "The payload also carries a `monitoring_cohort`, either `CONTROL` or
    `MONITORED`, a regulatory label used by nothing except the fair-lending markup
    analysis of §3.8."
    PRD 2.7: "Any of these failures is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/application_invalid_enum_monitoring_cohort_rejected
    """
    program = setup_program()

    response = api.create_application(
        {
            "dealer_id": program["dealer_id"],
            "applicant_reference": "APP-ENUM",
            "monitoring_cohort": "OTHER",
            "credit_score": 725,
            "monthly_income_cents": 600000,
            "monthly_debt_cents": 180000,
            "amount_financed_cents": 1000000,
            "collateral_value_cents": 1000000,
            "term_months": 60,
            "vehicle_model_year": 2023,
            "requested_apr_bps": 749,
        },
        program["dealer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_submission_for_a_suspended_dealership_is_refused(api):
    """PRD 3.3: "Submission requires the dealership to be `ACTIVE`; otherwise
    `ERR_DEALER_NOT_ACTIVE` (HTTP 409)."
    PRD 3.9: "`suspension_reason` is set to the supplied `reason` or to the sentinel
    `MANUAL_SUSPENSION` when none was supplied"

    Design: Corner/validations/application_submission_on_suspended_dealer_returns_dealer_not_active
    """
    program = setup_program()
    existing = submit_application(
        program["dealer_id"], applicant_reference="APP-sd",
        amount_financed_cents=1000000, collateral_value_cents=1000000,
        monthly_debt_cents=180000,
    )
    dealer_status_action(program["dealer_id"], "SUSPEND", "AUDIT")

    response = api.create_application(
        {
            "dealer_id": program["dealer_id"],
            "applicant_reference": "APP-SUSP",
            "monitoring_cohort": "CONTROL",
            "credit_score": 725,
            "monthly_income_cents": 600000,
            "monthly_debt_cents": 180000,
            "amount_financed_cents": 1000000,
            "collateral_value_cents": 1000000,
            "term_months": 60,
            "vehicle_model_year": 2023,
            "requested_apr_bps": 749,
        },
        program["dealer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_DEALER_NOT_ACTIVE.value, 409)

    _, meta = validate_paginated(
        api.list_applications(ADMIN, params={"dealer_id": program["dealer_id"]})
    )
    assert meta["total_count"] == 1
    held = read_application(existing["id"])
    assert held["status"] == "ON_HOLD"
    assert held["held_from_status"] == "SUBMITTED"


def test_conditioned_and_resubmitted_states_form_a_true_cycle(api):
    """PRD 3.3: "A `CONDITION` returns the file to the dealership with
    stipulations: the application moves to `CONDITIONED`, `stipulation_count` is set
    to the supplied value or to 1 when it is omitted"
    PRD 3.3: "A `DealerPrincipal` whose application sits in `CONDITIONED` may return
    it with revised terms, moving it `CONDITIONED → RESUBMITTED`."
    PRD 3.3: "A resubmitted file can be decisioned again, and a second `CONDITION`
    returns it to `CONDITIONED`, so the cycle `CONDITIONED → RESUBMITTED →
    CONDITIONED` may run until the revision limit bites."

    Design: Difficulty/non_linear_state_machine/application_conditioned_resubmit_cycle
    """
    program = setup_program()
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-cyc",
        amount_financed_cents=1000000, collateral_value_cents=1000000,
        monthly_debt_cents=180000,
    )

    first = decision_application(
        application["id"], "CONDITION", stipulation_count=1,
        decision_note="PROOF_OF_INCOME",
    )
    assert first["status"] == "CONDITIONED"
    assert first["stipulation_count"] == 1

    resubmitted = resubmit_application(
        application["id"], program["dealer_id"], credit_score=700
    )
    assert resubmitted["status"] == "RESUBMITTED"
    assert resubmitted["resubmission_count"] == 1

    second = decision_application(
        application["id"], "CONDITION", stipulation_count=1,
        decision_note="PROOF_OF_RESIDENCE",
    )
    assert second["status"] == "CONDITIONED", (
        "the machine has returned to a state it already left"
    )

    again = resubmit_application(
        application["id"], program["dealer_id"], credit_score=725
    )
    assert again["status"] == "RESUBMITTED"
    assert again["resubmission_count"] == 2


def test_third_revision_attempt_hits_the_resubmission_limit(api):
    """PRD 3.3: "`resubmission_count` must be strictly less than 2 — a third
    revision attempt is refused with `ERR_RESUBMISSION_LIMIT` (HTTP 409)."
    PRD 3.3: "`resubmission_count` increases by one, and `ltv_pct` and `dti_pct` are
    recomputed from the merged values."

    Design: Difficulty/non_linear_state_machine/application_conditioned_resubmit_cycle
    """
    program = setup_program()
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-cyc2",
        amount_financed_cents=1000000, collateral_value_cents=1000000,
        monthly_debt_cents=180000,
    )

    decision_application(
        application["id"], "CONDITION", stipulation_count=1, decision_note="STIP_ONE"
    )
    resubmit_application(application["id"], program["dealer_id"], credit_score=700)
    decision_application(
        application["id"], "CONDITION", stipulation_count=1, decision_note="STIP_TWO"
    )
    resubmit_application(application["id"], program["dealer_id"], credit_score=725)
    decision_application(
        application["id"], "CONDITION", stipulation_count=1, decision_note="STIP_THREE"
    )

    response = api.resubmit_application(
        application["id"], {"credit_score": 725},
        make_dealer_principal_headers(program["dealer_id"]),
    )
    validate_error(response, ApiErrorId.ERR_RESUBMISSION_LIMIT.value, 409)

    unchanged = read_application(application["id"])
    assert unchanged["resubmission_count"] == 2
    assert unchanged["status"] == "CONDITIONED"


def test_revision_merges_only_the_fields_it_supplies(api):
    """PRD 3.3: "The revision payload may carry any of `credit_score`,
    `amount_financed_cents`, `collateral_value_cents`, `term_months`, and
    `requested_apr_bps`; every field supplied overwrites the stored value and every
    field omitted leaves the stored value untouched."
    PRD 3.3: "`resubmission_count` increases by one, and `ltv_pct` and `dti_pct` are
    recomputed from the merged values."

    Design: Corner/endpoints/resubmit_merges_only_supplied_fields
    """
    program = setup_program()
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-rm",
        amount_financed_cents=2801000, collateral_value_cents=2500000,
        monthly_income_cents=600000, monthly_debt_cents=210000,
    )
    decision_application(
        application["id"], "CONDITION", stipulation_count=2, decision_note="TWO_STIPS"
    )

    response = api.resubmit_application(
        application["id"], {"term_months": 48},
        make_dealer_principal_headers(program["dealer_id"]),
    )
    revised = validate_success(response, 200)

    assert revised["status"] == "RESUBMITTED"
    assert revised["term_months"] == 48
    assert revised["credit_score"] == 725
    assert revised["amount_financed_cents"] == 2801000
    assert revised["collateral_value_cents"] == 2500000
    assert revised["ltv_pct"] == 112.04
    assert revised["dti_pct"] == 35.00
    assert revised["resubmission_count"] == 1
    assert revised["stipulation_count"] == 2
