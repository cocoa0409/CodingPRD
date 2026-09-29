"""Submission, the approval decision and the revision cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    assert_refund_approval,
    create_decision_payload,
    decide_request,
    make_credit_analyst_headers,
    make_refund_approver_headers,
    prepare_refund_request,
    read_account,
    read_credit_balance,
    read_refund_request,
    set_clock,
    setup_attributed_credit,
    submit_request,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["credit_analyst_headers"]
APPROVER = TEST_USERS["refund_approver_headers"]


def _submitted_request_prepared_by(user_id, **scenario_kwargs):
    """Attributed credit plus one SUBMITTED refund request prepared by `user_id`."""
    scenario = setup_attributed_credit(**scenario_kwargs)
    analyst = make_credit_analyst_headers(user_id)
    set_clock("2026-08-16T00:00:00Z")
    request = prepare_refund_request(
        scenario["credit_balance"]["id"], 12_000, "PAYER",
        scenario["credit_balance"]["version"], payee_name="Medicare Region A",
        payee_address_line="1 Payer Way", payee_state_code="CA", headers=analyst,
    )
    submit_request(request["id"], headers=analyst)
    scenario["refund_request"] = read_refund_request(request["id"])
    return scenario


def test_segregation_of_duties_outranks_the_signing_authority_check(api):
    """PRD §3.7: "Segregation of duties comes first: the deciding approver's `X-User-ID` must differ from the request's `prepared_by_user_id`, and an approver deciding on its own preparation is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD §3.7: "Because segregation and duplication outrank the tier check, an approver who both prepared the request and claims too low a tier is told about segregation of duties."

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_18_beats_fiscal_priority_41_on_refund_decision
    """
    scenario = _submitted_request_prepared_by(
        "dual-1", payer_type="MEDICARE", payer_code="MCR",
        account_number="ACCT-SD1", financial_class="INPATIENT",
        payment_source="PAYER", root_cause_confirmed=True,
    )
    request = scenario["refund_request"]
    assert request["required_approval_tier"] == 2

    response = api.decide_refund_request(
        request["id"], create_decision_payload("APPROVED", 1),
        make_refund_approver_headers("dual-1"),
    )
    error = validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert error["error_id"] != ApiErrorId.ERR_APPROVAL_TIER_INSUFFICIENT.value


def test_self_approval_writes_no_approval_record_and_leaves_the_request_submitted(api):
    """PRD §3.7: "Every decision — approval, rejection or return alike — writes an immutable approval record stamped with the deciding approver's `X-User-ID` as `approver_user_id`, the `refund_request_id` taken from the path, the supplied `approver_tier`, `decision` and `note`, and a `decided_at` read from the logical clock."
    PRD §3.7: "Segregation of duties comes first: the deciding approver's `X-User-ID` must differ from the request's `prepared_by_user_id`, and an approver deciding on its own preparation is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_18_beats_fiscal_priority_41_on_refund_decision
    """
    scenario = _submitted_request_prepared_by(
        "dual-1", payer_type="MEDICARE", payer_code="MCR",
        account_number="ACCT-SD1", financial_class="INPATIENT",
        payment_source="PAYER", root_cause_confirmed=True,
    )
    request = scenario["refund_request"]

    validate_error(
        api.decide_refund_request(
            request["id"], create_decision_payload("APPROVED", 1),
            make_refund_approver_headers("dual-1"),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    unchanged = read_refund_request(request["id"])
    assert unchanged["approval_state"] == "SUBMITTED"
    assert unchanged["approvals_received"] == 0
    _, meta = validate_paginated(
        api.list_refund_approvals(
            APPROVER, params={"refund_request_id": request["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_returned_request_is_revised_resubmitted_and_then_approved(api):
    """PRD §3.7: "A return moves the request `SUBMITTED → RETURNED_FOR_REVISION`, increments `revision_count` by 1, and — unlike a rejection — leaves the owning credit balance in `REFUND_PENDING`, because the analyst is expected to fix and resubmit rather than release the credit."
    PRD §3.7: "Submitting a request moves its `approval_state` from `DRAFT` to `SUBMITTED`, or from `RETURNED_FOR_REVISION` back to `SUBMITTED`, and re-runs the tier computation of §3.6."
    PRD §3.7: "When `required_approval_count` is 1, or when it is 2 and this approval brings `approvals_received` plus one to at least 2, the approval completes the request: `approval_state` moves `SUBMITTED → APPROVED` and `approved_amount_cents` is set equal to `requested_amount_cents`."

    Design: Corner/state_machines/refund_request_returned_for_revision_then_resubmitted_and_approved
    """
    scenario = setup_attributed_credit(account_number="ACCT-RV1")
    credit_balance = scenario["credit_balance"]
    set_clock("2026-08-16T00:00:00Z")
    request = prepare_refund_request(
        credit_balance["id"], 12_000, "PATIENT", credit_balance["version"],
        payee_name="Rae Volt", payee_address_line="11 Sage", payee_state_code="CA",
    )
    submit_request(request["id"])

    decide_request(
        request["id"], "RETURNED", 3, headers=make_refund_approver_headers("appr-1"),
        note="Attach the remittance advice",
    )
    returned = read_refund_request(request["id"])
    assert returned["approval_state"] == "RETURNED_FOR_REVISION"
    assert returned["revision_count"] == 1
    assert read_credit_balance(credit_balance["id"])["status"] == "REFUND_PENDING"

    resubmitted = validate_success(api.submit_refund_request(request["id"], {}, ANALYST))
    assert resubmitted["approval_state"] == "SUBMITTED"

    decide_request(
        request["id"], "APPROVED", 3, headers=make_refund_approver_headers("appr-2")
    )
    approved = read_refund_request(request["id"])
    assert approved["approval_state"] == "APPROVED"
    assert approved["approvals_received"] == 1
    assert approved["approved_amount_cents"] == 12_000

    _, meta = validate_paginated(
        api.list_refund_approvals(
            APPROVER, params={"refund_request_id": request["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_rejection_hands_the_credit_back_to_attributed(api):
    """PRD §3.7: "A rejection moves the request `SUBMITTED → REJECTED`, which is terminal, and hands the credit back: the owning credit balance moves `REFUND_PENDING → ATTRIBUTED` and its `version` is bumped by 1, provided no other refund request on that same credit balance is sitting in `SUBMITTED` or `APPROVED`."
    PRD §3.7: "In general, `approvals_received` is the count of approval records on the request whose `decision` is `APPROVED`, and `approved_amount_cents` is `requested_amount_cents` once and only once the request reaches `APPROVED`, and 0 in every other approval state."

    Design: Corner/state_machines/refund_request_reject_compensates_credit_balance_back_to_attributed
    """
    scenario = setup_attributed_credit(account_number="ACCT-RJ1")
    credit_balance = scenario["credit_balance"]
    set_clock("2026-08-16T00:00:00Z")
    request = prepare_refund_request(
        credit_balance["id"], 12_000, "PATIENT", credit_balance["version"],
        payee_name="Roy Jung", payee_address_line="13 Holly", payee_state_code="CA",
    )
    submit_request(request["id"])

    approval = validate_success(
        api.decide_refund_request(
            request["id"],
            create_decision_payload(
                "REJECTED", 3, note="Credit belongs to the payer, not the patient"
            ),
            make_refund_approver_headers("appr-1"),
        ),
        201,
    )
    assert_refund_approval(approval)
    assert approval["decision"] == "REJECTED"
    assert approval["approver_user_id"] == "appr-1"
    assert_instant_equals(approval["decided_at"], "2026-08-16T00:00:00Z", "decided_at")

    rejected = read_refund_request(request["id"])
    assert rejected["approval_state"] == "REJECTED"
    assert rejected["approved_amount_cents"] == 0

    released = read_credit_balance(credit_balance["id"])
    assert released["status"] == "ATTRIBUTED"
    assert released["outstanding_cents"] == 12_000
    assert read_account(scenario["account"]["id"])["credit_balance_cents"] == 12_000


def test_tier_three_decision_errors_duplicate_approver_tier_and_already_decided(api):
    """PRD §3.7: "Duplicate approval comes second: no approval record already on this request may carry the deciding approver's `X-User-ID`, so a tier-3 request genuinely needs two distinct human beings, and a second decision from the same operator is refused with `ERR_DUPLICATE_APPROVER` (HTTP 409)."
    PRD §3.7: "Signing authority comes last, and applies only to approvals: the supplied `approver_tier` must be at least the request's `required_approval_tier`, and a claim below it is refused with `ERR_APPROVAL_TIER_INSUFFICIENT` (HTTP 403)."
    PRD §3.7: "Only a `RefundApprover` decides, and only on a `SUBMITTED` request."

    Design: Corner/errors/refund_decision_errors_duplicate_approver_tier_and_already_decided
    """
    scenario = setup_attributed_credit(
        payer_type="MEDICARE", payer_code="MCR", account_number="ACCT-TA9",
        financial_class="INPATIENT", payment_source="PAYER",
        charge_cents=100_000, payment_cents=-400_000,
    )
    credit_balance = scenario["credit_balance"]
    set_clock("2026-08-16T00:00:00Z")
    request = prepare_refund_request(
        credit_balance["id"], 300_000, "PAYER", credit_balance["version"],
        payee_name="Medicare Region A", payee_address_line="1 Payer Way",
        payee_state_code="CA",
    )
    submit_request(request["id"])
    submitted = read_refund_request(request["id"])
    assert submitted["required_approval_tier"] == 3
    assert submitted["required_approval_count"] == 2

    decide_request(
        request["id"], "APPROVED", 3, headers=make_refund_approver_headers("appr-1")
    )

    validate_error(
        api.decide_refund_request(
            request["id"], create_decision_payload("APPROVED", 3),
            make_refund_approver_headers("appr-1"),
        ),
        ApiErrorId.ERR_DUPLICATE_APPROVER.value,
    )
    validate_error(
        api.decide_refund_request(
            request["id"], create_decision_payload("APPROVED", 2),
            make_refund_approver_headers("appr-2"),
        ),
        ApiErrorId.ERR_APPROVAL_TIER_INSUFFICIENT.value,
    )

    second = validate_success(
        api.decide_refund_request(
            request["id"], create_decision_payload("APPROVED", 3),
            make_refund_approver_headers("appr-2"),
        ),
        201,
    )
    assert second["approver_user_id"] == "appr-2"

    completed = read_refund_request(request["id"])
    assert completed["approval_state"] == "APPROVED"
    assert completed["approvals_received"] == 2
    assert completed["approved_amount_cents"] == 300_000

    validate_error(
        api.decide_refund_request(
            request["id"], create_decision_payload("REJECTED", 3),
            make_refund_approver_headers("appr-3"),
        ),
        ApiErrorId.ERR_REFUND_REQUEST_INVALID_STATE.value,
    )

    _, meta = validate_paginated(
        api.list_refund_approvals(
            APPROVER, params={"refund_request_id": request["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_fourth_submission_after_three_returns_exceeds_the_revision_allowance(api):
    """PRD §3.7: "Re-submission after a return is bounded: the request's `revision_count` must be at most 2 at the moment of re-submission, and a request that has already been sent back and revised more than that is refused with `ERR_MAX_REVISIONS_EXCEEDED` (HTTP 409)."

    Design: Corner/errors/max_revisions_exceeded_after_three_returned_decisions
    """
    scenario = setup_attributed_credit(account_number="ACCT-MX1")
    credit_balance = scenario["credit_balance"]
    set_clock("2026-08-16T00:00:00Z")
    request = prepare_refund_request(
        credit_balance["id"], 12_000, "PATIENT", credit_balance["version"],
        payee_name="Max Ives", payee_address_line="6 Kiln", payee_state_code="CA",
    )
    submit_request(request["id"])

    for round_number, approver in enumerate(("appr-1", "appr-2", "appr-3"), start=1):
        decide_request(
            request["id"], "RETURNED", 3,
            headers=make_refund_approver_headers(approver),
            note=f"Round {round_number}",
        )
        if round_number < 3:
            submit_request(request["id"])

    response = api.submit_refund_request(request["id"], {}, ANALYST)
    validate_error(response, ApiErrorId.ERR_MAX_REVISIONS_EXCEEDED.value)

    blocked = read_refund_request(request["id"])
    assert blocked["revision_count"] == 3
    assert blocked["approval_state"] == "RETURNED_FOR_REVISION"
    assert read_credit_balance(credit_balance["id"])["status"] == "REFUND_PENDING"


def test_credit_analyst_may_not_record_a_refund_decision(api):
    """PRD §2.1: "If the headers are well formed but the named role is not among the roles authorised for the endpoint being called (see the table in §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.7: "Only a `RefundApprover` decides, and only on a `SUBMITTED` request."
    PRD §2.1: "An analyst holds no approval and no disbursement authority."

    Design: Corner/rbac/credit_analyst_cannot_record_a_refund_decision
    """
    scenario = setup_attributed_credit(account_number="ACCT-RB1")
    credit_balance = scenario["credit_balance"]
    set_clock("2026-08-16T00:00:00Z")
    request = prepare_refund_request(
        credit_balance["id"], 12_000, "PATIENT", credit_balance["version"],
        payee_name="Rob Best", payee_address_line="7 Mill", payee_state_code="CA",
    )
    submit_request(request["id"])

    response = api.decide_refund_request(
        request["id"], create_decision_payload("APPROVED", 3), ANALYST
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    assert read_refund_request(request["id"])["approval_state"] == "SUBMITTED"
    _, meta = validate_paginated(
        api.list_refund_approvals(
            APPROVER, params={"refund_request_id": request["id"]}
        )
    )
    assert meta["total_count"] == 0
