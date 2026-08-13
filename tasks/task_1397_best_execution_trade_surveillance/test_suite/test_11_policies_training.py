"""Compliance policies and training: publish fan-out, supersede compensation,
the training-overdue preclearance gate, completion ownership, and list
pagination (PRD §2.3, §3.6, §3.9)."""
from test_helpers import (
    ApiErrorId,
    create_compliance_policy_payload,
    make_covered_employee_headers,
    make_employee,
    make_personal_trade,
    ops_run,
    publish_policy,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CA = TEST_USERS["compliance_admin_headers"]


def _assignment_for(employee_id, policy_id):
    data, meta = validate_paginated(api_client.list_training_assignments(
        CA, params={"employee_id": employee_id, "policy_id": policy_id}))
    assert meta["total_count"] == 1, f"expected exactly one assignment, got {meta['total_count']}"
    return data[0]


def _setup_two_employees_two_versions():
    """EMP-121 completes the v1 assignment; EMP-122 leaves it ASSIGNED; then
    v2 of the same policy code publishes (PRD §3.9)."""
    e1 = make_employee(employee_ref="EMP-121", full_name="Ola Done", department="COMPLIANCE")
    e2 = make_employee(employee_ref="EMP-122", full_name="Pam Pending")
    p1 = publish_policy(version_label="v2026.1")
    a1 = _assignment_for(e1["id"], p1["id"])
    validate_success(api_client.complete_training_assignment(
        a1["id"], make_covered_employee_headers(e1["id"])))
    p2_draft = validate_success(api_client.create_compliance_policy(
        create_compliance_policy_payload(version_label="v2026.2"), CA), expected_status=201)
    p2 = validate_success(api_client.publish_compliance_policy(p2_draft["id"], CA))
    return e1, e2, p1, p2


class TestPublishSupersedeInvariant:
    def test_publish_supersedes_prior_and_cancels_open_assignments(self, api):
        """PRD §3.9: "First, the prior `EFFECTIVE` policy of the same code, if
        any, moves to the terminal `SUPERSEDED`." and "Third, compensation:
        the superseded policy's assignments still in `ASSIGNED` or `OVERDUE`
        are cancelled, while completed ones are left untouched."

        Design: Difficulty/compensating_invariant/policy_publish_supersede_conserves_single_open_assignment
        """
        _e1, e2, p1, p2 = _setup_two_employees_two_versions()
        p1_after = validate_success(api.get_compliance_policy(p1["id"], CA))
        assert p1_after["status"] == "SUPERSEDED"

        old = _assignment_for(e2["id"], p1["id"])
        assert old["status"] == "CANCELLED", "the open assignment on the superseded policy is cancelled"
        new = _assignment_for(e2["id"], p2["id"])
        assert new["status"] == "ASSIGNED", "the successor publish fans out a fresh assignment"

    def test_completed_assignment_survives_supersede(self, api):
        """PRD §3.9: "Second, training fans out: a `TrainingAssignment` is
        created for every employee whose `employment_status` is `ACTIVE` at
        publish time, each starting `ASSIGNED` with a `due_date` of the
        publish instant plus 30 days" and "the superseded policy's assignments
        still in `ASSIGNED` or `OVERDUE` are cancelled, while completed ones
        are left untouched."

        Design: Difficulty/compensating_invariant/policy_publish_supersede_conserves_single_open_assignment
        """
        e1, _e2, p1, p2 = _setup_two_employees_two_versions()
        old = _assignment_for(e1["id"], p1["id"])
        assert old["status"] == "COMPLETED", "COMPLETED assignments are conserved, not compensated"
        new = _assignment_for(e1["id"], p2["id"])
        assert new["status"] == "ASSIGNED", (
            "exactly one open assignment per (employee, policy code) survives each publish")


class TestTrainingGate:
    def test_training_overdue_blocks_preclearance_until_completed(self, api):
        """PRD §3.6: "the employee's `training_overdue_count` must be zero
        (`ERR_TRAINING_OVERDUE`)". PRD §3.9: "A `CoveredEmployee` completes
        their own assignment — the caller's `X-User-ID` must equal the
        assignment's `employee_id`, else `ERR_NOT_RESOURCE_OWNER` — from
        either `ASSIGNED` or `OVERDUE`, moving it to the terminal `COMPLETED`
        and stamping `completed_at` with the logical now."

        Design: Corner/errors/training_overdue_blocks_preclearance_until_completed
        """
        employee = make_employee(employee_ref="EMP-190", full_name="Train Late",
                                 attestation_due_at="2027-06-01T00:00:00Z")
        publish_policy(version_label="v2026.1")  # due_date = 2026-08-01 + 30 days
        set_clock("2026-09-01T00:00:00Z")
        tally = ops_run()
        assert tally["training_marked_overdue"] == 1

        trade = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=10)
        assignments, _meta = validate_paginated(
            api.list_training_assignments(CA, params={"employee_id": employee["id"]}))
        assert assignments[0]["status"] == "OVERDUE"

        resp = api.personal_trade_transition(trade["id"], {"to_status": "APPROVED"}, CA)
        validate_error(resp, ApiErrorId.ERR_TRAINING_OVERDUE)

        validate_success(api.complete_training_assignment(
            assignments[0]["id"], make_covered_employee_headers(employee["id"])))
        ok = validate_success(api.personal_trade_transition(trade["id"], {"to_status": "APPROVED"}, CA))
        assert ok["status"] == "APPROVED", "completing the OVERDUE assignment clears the gate"

    def test_employee_cannot_complete_others_training_returns_403(self, api):
        """PRD §3.9: "the caller's `X-User-ID` must equal the assignment's
        `employee_id`, else `ERR_NOT_RESOURCE_OWNER`".

        Design: Corner/rbac/employee_cannot_complete_others_training_returns_403
        """
        owner = make_employee(employee_ref="EMP-RC", full_name="Owner A")
        other = make_employee(employee_ref="EMP-RD", full_name="Other B")
        policy = publish_policy(version_label="v2026.1")
        assignment = _assignment_for(owner["id"], policy["id"])
        resp = api.complete_training_assignment(
            assignment["id"], make_covered_employee_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


class TestPagination:
    def test_list_pagination_defaults_and_offset_page(self, api):
        """PRD §2.3: "The `limit` parameter defaults to 10, with a minimum of
        1 and a maximum of 100; the `offset` parameter defaults to 0." and
        "The `meta` object of a list response carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more`, where `total_count`
        reports the full size of the filtered result set and `has_more`
        indicates whether additional pages follow the returned one."

        Design: Corner/endpoints/list_pagination_defaults_and_offset_page
        """
        for i in range(1, 12):
            make_employee(employee_ref=f"EMP-P{i:02d}", full_name=f"Pg {i:02d}")
        publish_policy(version_label="v2026.1")  # fans out 11 ASSIGNED assignments

        page1, meta1 = validate_paginated(api.list_training_assignments(CA))
        assert len(page1) == 10, "default limit is 10"
        assert meta1["total_count"] == 11
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_training_assignments(CA, params={"offset": 10}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page2[0]["id"] != page1[0]["id"]
