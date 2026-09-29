"""
Queue A — §1.8 rule ``priority_pair_validation_conflict``.

Each instance sends one unchanged request body more than once, changing only the
world around it, so that the answer has to move from the lower-priority rule to
the higher-priority one (or the other way) purely because of PRD §2.10 ordering.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.assertions import assert_fields, assert_loan_ledger, assert_ratio
from test_helpers.factories import (
    board_verification_payload,
    committee_referral_payload,
    construction_completion_payload,
    denominational_decision_payload,
    draw_request_payload,
)
from test_helpers.fixtures import (
    assign_asset,
    build_collateral_asset,
    build_draft_application,
    build_giving_periods,
    build_institution,
    build_submitted_authorization,
    chain_through_loan,
    submit_to_underwriting,
)
from test_helpers.test_users import (
    ANALYST_1,
    CREDIT_ANALYST,
    GOVERNANCE_OFFICER,
    LOAN_SERVICER,
    make_credit_analyst_headers,
    make_governance_officer_headers,
)
OVERSIZED_DRAW = {"project_phase": "FINAL", "requested_amount_cents": 500000000, "percent_complete": 0.9500}


def test_oversized_draw_in_the_draw_phase_reports_only_the_fiscal_rule(api):
    """
    Priority 20 is satisfied while the loan is PENDING_FIRST_DRAW, so priority 49 answers.

    PRD §2.10: "The loan is still in its draw phase, meaning `servicing_status` is
    `PENDING_FIRST_DRAW` or `CONSTRUCTION_DRAW` — `ERR_LOAN_NOT_IN_DRAW_PHASE` (HTTP
    409), on draw creation, approval, disbursement and voiding."

    PRD §3.7: "A request whose gross amount exceeds the free commitment of §2.11 —
    `undrawn_commitment_cents` less `reserved_draw_cents` — is refused with
    `ERR_DRAW_EXCEEDS_COMMITMENT`."

    Design: Difficulty/priority_pair_validation_conflict/draw_create_state_precedes_commitment_fiscal_check
    """
    chain = chain_through_loan(api)
    before = chain.read_loan()
    assert_loan_ledger(
        before,
        servicing_status="PENDING_FIRST_DRAW",
        undrawn_commitment_cents=225000000,
        reserved_draw_cents=0,
    )

    validate_error(
        api.create_draw_request(draw_request_payload(chain.loan_id, **OVERSIZED_DRAW), LOAN_SERVICER),
        "ERR_DRAW_EXCEEDS_COMMITMENT",
        422,
    )

    rows, meta = validate_paginated(api.list_draw_requests(LOAN_SERVICER, {"loan_id": chain.loan_id}))
    assert rows == []
    assert meta["total_count"] == 0
    assert_fields(chain.read_loan(), version=before["version"])


def test_the_identical_body_after_construction_completion_reports_the_phase_rule(api):
    """
    Once both rules are broken the ladder must pick priority 20 over priority 49.

    PRD §2.10: "Validations are evaluated in the ascending order set out below; the
    **first** rule that a request violates determines the single error the response
    carries, and no later rule can mask an earlier one."

    PRD §3.6: "Both variants perform the same two ledger movements — the whole of
    `undrawn_commitment_cents` moves into `cancelled_commitment_cents` and
    `undrawn_commitment_cents` is set to 0, and the whole of `retainage_held_cents`
    moves into `retainage_released_cents` and `retainage_held_cents` is set to 0 — and
    both advance `version` by 1."

    PRD §3.7: "A request against a loan whose `servicing_status` is `AMORTIZING` or
    `PAID_OFF` is refused with `ERR_LOAN_NOT_IN_DRAW_PHASE`."

    Design: Difficulty/priority_pair_validation_conflict/draw_create_state_precedes_commitment_fiscal_check
    """
    chain = chain_through_loan(api)
    validate_error(
        api.create_draw_request(draw_request_payload(chain.loan_id, **OVERSIZED_DRAW), LOAN_SERVICER),
        "ERR_DRAW_EXCEEDS_COMMITMENT",
        422,
    )

    completed = get_success_data(
        api.construction_completion(
            chain.loan_id,
            construction_completion_payload(
                completion_note="Project abandoned before the first draw; commitment cancelled"
            ),
            LOAN_SERVICER,
        )
    )
    assert_loan_ledger(
        completed,
        servicing_status="AMORTIZING",
        undrawn_commitment_cents=0,
        cancelled_commitment_cents=225000000,
        disbursed_principal_cents=0,
    )

    validate_error(
        api.create_draw_request(draw_request_payload(chain.loan_id, **OVERSIZED_DRAW), LOAN_SERVICER),
        "ERR_LOAN_NOT_IN_DRAW_PHASE",
        409,
    )

    rows, meta = validate_paginated(api.list_draw_requests(LOAN_SERVICER, {"loan_id": chain.loan_id}))
    assert rows == []
    assert meta["total_count"] == 0


def _denominational_setup(api):
    """
    An institution that requires denominational approval, so board verification stops
    at BOARD_VERIFIED, with an unassigned sanctuary asset and an application in
    UNDERWRITING — both the priority-30 and the priority-38 referral gates are broken.
    """
    institution = build_institution(api, requires_denominational_approval=True)
    build_giving_periods(api, institution["id"])
    authorization = build_submitted_authorization(
        api, institution["id"], denominational_body="Presbytery of the Mid-South"
    )
    verified = get_success_data(
        api.board_verify_governance_authorization(
            authorization["id"], board_verification_payload(), make_governance_officer_headers()
        )
    )
    asset = build_collateral_asset(api, institution["id"])
    application = build_draft_application(
        api,
        institution["id"],
        authorization["id"],
        purpose="SANCTUARY_CONSTRUCTION",
        requested_amount_cents=100000000,
        term_months=240,
        interest_rate_bps=625,
    )
    application = submit_to_underwriting(
        api, application["id"], analyst_note="Four audited periods on file"
    )
    return institution, verified, asset, application


def _read_application(api, application_id):
    return get_success_data(api.get_loan_application(application_id, CREDIT_ANALYST))


def test_referral_reports_the_governance_gate_while_both_referral_gates_are_broken(api):
    """
    Priority 30 answers first even though the priority-38 collateral link is also broken.

    PRD §3.2: "Where the institution's `requires_denominational_approval` is true, the
    packet moves `SUBMITTED → BOARD_VERIFIED` and still owes a denominational
    decision."

    PRD §3.5: "The governance packet must be `AUTHORIZED`, or the referral is refused
    with `ERR_GOVERNANCE_NOT_AUTHORIZED`."

    PRD §2.10: "At least one collateral asset is assigned to the application in
    first-lien position — `ERR_COLLATERAL_LINK_BROKEN` (HTTP 409), on committee
    referral."

    Design: Difficulty/priority_pair_validation_conflict/committee_referral_governance_compliance_precedes_collateral_referential
    """
    _institution, verified, asset, application = _denominational_setup(api)
    assert_fields(verified, status="BOARD_VERIFIED")
    assert_ratio(verified["board_quorum_pct"], 0.6667, "board_quorum_pct")
    assert_fields(asset, assigned_loan_application_id=None)
    before = _read_application(api, application["id"])

    validate_error(
        api.committee_referral(
            application["id"],
            committee_referral_payload(
                referral_note="Attempt 1 - packet still with the presbytery, no lien filed"
            ),
            make_credit_analyst_headers(ANALYST_1),
        ),
        "ERR_GOVERNANCE_NOT_AUTHORIZED",
        409,
    )

    after = _read_application(api, application["id"])
    assert_fields(after, status="UNDERWRITING", version=before["version"])


def test_referral_reaches_the_collateral_gate_only_once_governance_is_authorized(api):
    """
    The same body walks from the priority-30 refusal to the priority-38 refusal to success.

    PRD §3.2: "`APPROVE` moves the packet `BOARD_VERIFIED → AUTHORIZED`; `REJECT` moves
    it `BOARD_VERIFIED → DENOM_REJECTED`."

    PRD §3.5: "At least one collateral asset must be assigned to this application in
    first-lien position, or the referral is refused with `ERR_COLLATERAL_LINK_BROKEN`."

    PRD §3.5: "`collateral_lending_value_cents` becomes the sum of `lending_value_cents`
    over the collateral assets assigned to this application whose `lien_position` is 1
    — second-lien and worse assignments are excluded from the snapshot entirely."

    PRD §3.5: "The **collateral cap** is the sum of `lending_value_cents` over the
    collateral assets assigned to this application whose `lien_position` is 1."

    Design: Difficulty/priority_pair_validation_conflict/committee_referral_governance_compliance_precedes_collateral_referential
    """
    _institution, verified, asset, application = _denominational_setup(api)
    validate_error(
        api.committee_referral(
            application["id"],
            committee_referral_payload(
                referral_note="Attempt 1 - packet still with the presbytery, no lien filed"
            ),
            make_credit_analyst_headers(ANALYST_1),
        ),
        "ERR_GOVERNANCE_NOT_AUTHORIZED",
        409,
    )

    authorized = get_success_data(
        api.denominational_decision(
            verified["id"],
            denominational_decision_payload(
                "APPROVE", note="Presbytery approved the borrowing resolution"
            ),
            GOVERNANCE_OFFICER,
        )
    )
    assert_fields(authorized, status="AUTHORIZED")

    validate_error(
        api.committee_referral(
            application["id"],
            committee_referral_payload(referral_note="Attempt 2 - packet authorized, lien still missing"),
            make_credit_analyst_headers(ANALYST_1),
        ),
        "ERR_COLLATERAL_LINK_BROKEN",
        409,
    )
    assert_fields(_read_application(api, application["id"]), status="UNDERWRITING")

    assign_asset(api, asset["id"], application["id"])
    referred = get_success_data(
        api.committee_referral(
            application["id"],
            committee_referral_payload(
                referral_note="Attempt 3 - packet authorized and first lien recorded"
            ),
            make_credit_analyst_headers(ANALYST_1),
        )
    )
    assert_fields(
        referred,
        status="COMMITTEE_REVIEW",
        collateral_lending_value_cents=225000000,
        max_supportable_principal_cents=225000000,
    )
