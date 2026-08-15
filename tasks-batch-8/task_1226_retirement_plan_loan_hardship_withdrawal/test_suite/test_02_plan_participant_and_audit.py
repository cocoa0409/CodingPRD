"""Plan defaults, enrollment schema, nested-path existence, and the append-only
audit trail (PRD §3.1, §3.2, §2.10, §2.11)."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_participant_payload,
    create_plan_payload,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_plan_creation_applies_documented_defaults_status_and_version(api):
    """PRD §3.1: "`max_loans_outstanding` (default 1), ... `min_loan_amount_cents`
    (default 100,000 cents — one thousand dollars); `max_loan_amount_cents`
    (default 5,000,000 cents); `max_term_months` (default 60); `interest_rate_bps`
    (default 500), the fixed annual loan rate". PRD §2.7: "Every Plan carries a
    `status` of `ACTIVE`, `FROZEN`, or `TERMINATED`, beginning at `ACTIVE` upon
    creation."

    Design: Corner/entities/plan_creation_applies_documented_defaults
    """
    res = api.create_plan(create_plan_payload(name="Defaulted Plan"), ADMIN)
    plan = validate_success(res, 201)
    assert plan["status"] == "ACTIVE"
    assert plan["version"] == 1
    assert plan["max_loans_outstanding"] == 1
    assert plan["min_loan_amount_cents"] == 100_000
    assert plan["max_loan_amount_cents"] == 5_000_000
    assert plan["interest_rate_bps"] == 500


def test_plan_creation_applies_documented_defaults_remaining_levers(api):
    """PRD §3.1: "`day_count_convention`, either `THIRTY_360` (the default) or
    `ACT_360`; `allows_refinance` (default false); and
    `refinance_min_months_since_disbursement` (default 12), ...
    `hardship_suspension_months` (default 6), ... `substantiation_standard`, either
    `FULL_DOCUMENTATION` (the default) or `SELF_CERTIFY`; `withholding_rate_bps`
    (default 2000), ... Two further levers govern workflow rather than money:
    `loan_approval_chain` and `hardship_approval_chain` are ordered lists of
    approver roles, each defaulting to `PLAN_SPONSOR` followed by
    `RECORDKEEPER_ADMIN`".

    Design: Corner/entities/plan_creation_applies_documented_defaults
    """
    plan = validate_success(
        api.create_plan(create_plan_payload(name="Defaulted Plan 2"), ADMIN), 201
    )
    assert plan["day_count_convention"] == "THIRTY_360"
    assert plan["allows_refinance"] is False
    assert plan["refinance_min_months_since_disbursement"] == 12
    assert plan["hardship_suspension_months"] == 6
    assert plan["substantiation_standard"] == "FULL_DOCUMENTATION"
    assert plan["withholding_rate_bps"] == 2000
    assert plan["loan_approval_chain"] == ["PLAN_SPONSOR", "RECORDKEEPER_ADMIN"]
    assert plan["hardship_approval_chain"] == ["PLAN_SPONSOR", "RECORDKEEPER_ADMIN"]


def test_participant_enrollment_missing_required_field_rejected(api):
    """PRD §2.8: "Request-body schema. Required fields are present and types and
    enum members are valid — ... the error is `ERR_INVALID_REQUEST`."

    Design: Corner/entities/participant_enrollment_missing_required_field_rejected
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    res = api.create_participant(plan["id"], {"full_name": "No Balance"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_get_nonexistent_entities_return_typed_not_found(api):
    """PRD §2.10: "The not-found errors are resource-specific:
    `ERR_PLAN_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND` (also used when the
    participant does not belong to the plan in the path), `ERR_LOAN_NOT_FOUND`,
    `ERR_HARDSHIP_NOT_FOUND`, `ERR_REMITTANCE_NOT_FOUND`,
    `ERR_APPROVAL_TASK_NOT_FOUND`, and `ERR_TAX_EVENT_NOT_FOUND`."

    Design: Corner/entities/get_nonexistent_entities_return_typed_not_found
    """
    bad = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
    validate_error(
        api.get_participant(bad, ADMIN),
        ApiErrorId.ERR_PARTICIPANT_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.get_loan(bad, ADMIN),
        ApiErrorId.ERR_LOAN_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.get_hardship_request(bad, ADMIN),
        ApiErrorId.ERR_HARDSHIP_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.reverse_remittance(bad, ADMIN),
        ApiErrorId.ERR_REMITTANCE_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.decide_approval_task(bad, {"decision": "APPROVE"}, TEST_USERS["sponsor_headers"]),
        ApiErrorId.ERR_APPROVAL_TASK_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.mark_tax_event_reported(bad, ADMIN),
        ApiErrorId.ERR_TAX_EVENT_NOT_FOUND,
        expected_status=404,
    )


def test_enrollment_under_nonexistent_plan_returns_plan_not_found(api):
    """PRD §2.10: "When a path contains multiple identifiers, the system validates
    existence sequentially, left to right — plan first, then participant, then
    the loan, hardship request, remittance, approval task, or tax event — and
    rejects the request immediately with the not-found error corresponding to
    the first identifier that does not resolve."

    Design: Corner/entities/enrollment_under_nonexistent_plan_returns_plan_not_found
    """
    bad = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
    res = api.create_participant(
        bad,
        create_participant_payload(
            full_name="Orphan Ora", vested_balance_cents=1_000_000
        ),
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_PLAN_NOT_FOUND, expected_status=404)


def test_audit_events_immutable_and_append_only(api):
    """PRD §2.11: "Every mutating endpoint appends exactly one `AuditEvent`, scoped
    to the affected plan, before returning." PRD §2.11: "Audit events are never
    updated or deleted, and a plan's audit trail is listed in ascending
    `created_at` order to `RecordkeeperAdmin` and `Auditor` readers."
    PRD §3.1: "Plan creation appends a `PLAN_CREATED` audit record."
    PRD §3.2: "Enrollment appends `PARTICIPANT_ENROLLED`."

    Design: Corner/entities/audit_events_immutable_and_append_only
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    get_success_data(
        api.create_participant(
            plan["id"],
            create_participant_payload(
                full_name="Audit Amy", vested_balance_cents=1_000_000
            ),
            ADMIN,
        )
    )
    res = api.list_plan_audit_events(plan["id"], AUDITOR)
    events, meta = validate_paginated(res)
    assert meta["total_count"] >= 2
    assert events[0]["action"] == "PLAN_CREATED"
    assert events[1]["action"] == "PARTICIPANT_ENROLLED"
    assert events[0]["actor_role"] == "RecordkeeperAdmin"
    # Append-only shape: no updated_at, no version (PRD §2.4)
    assert "updated_at" not in events[0]
    assert "version" not in events[0]
