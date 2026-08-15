"""Dual approval under segregation of duties, the capped repair loop with its
parallel screening dimension, and optimistic concurrency on approve/repair."""
from test_helpers import (
    ApiErrorId,
    assert_wire,
    approve_wire,
    create_submitted_wire,
    create_wire,
    get_wire,
    list_wire_approvals,
    repair_wire,
    resubmit_wire,
    setup_wire_room,
    simulate_hit,
    submit_wire,
    validate_error,
    validate_success,
    wire_version,
)
from test_helpers import TEST_USERS, make_wire_approver_headers, make_wire_operator_headers

OPERATOR = TEST_USERS["wire_operator_headers"]
APPROVER_1 = TEST_USERS["wire_approver_headers"]
REPAIR_SPECIALIST = TEST_USERS["repair_specialist_headers"]
SCREENER = TEST_USERS["sanctions_screener_headers"]


class TestSegregationOfDuties:
    def test_sod_initiator_and_repeat_approver_rejected(self, api):
        """PRD §3.4: "the approver must not be the wire's `initiated_by`, and
        the approver must not already hold a non-superseded approval record
        for this wire's current repair round. Either violation is rejected
        with `ERR_SOD_APPROVER_MISMATCH`."
        PRD §3.4: "A valid second approval — by a different approver who is
        likewise neither the initiator nor the first approver — creates the
        `SECOND` record"

        The initiating operator (presenting the WireApprover role) cannot
        approve their own wire, and one approver cannot supply both halves of
        the dual approval.

        Design: Corner/validations/sod_initiator_and_repeat_approver_rejected
        """
        room = setup_wire_room(business_date="2026-09-21")
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"],
                           100000, operator_user_id="op-1")
        submit_wire(wire["id"], "2026-09-21", operator_user_id="op-1")

        version = wire_version(wire["id"])
        resp_initiator = api.approve_wire(
            wire["id"], {"expected_wire_version": version},
            make_wire_approver_headers("op-1"))
        validate_error(resp_initiator, ApiErrorId.ERR_SOD_APPROVER_MISMATCH)

        approve_wire(wire["id"], "ap-1")
        version_after_first = wire_version(wire["id"])
        resp_repeat = api.approve_wire(
            wire["id"], {"expected_wire_version": version_after_first},
            make_wire_approver_headers("ap-1"))
        validate_error(resp_repeat, ApiErrorId.ERR_SOD_APPROVER_MISMATCH)

        wire_after = get_wire(wire["id"])
        assert wire_after["status"] == "PENDING_APPROVAL", (
            f"both SoD violations leave the wire pending, got {wire_after['status']}")


class TestApprovalRepairRoleGates:
    def test_approve_forbidden_for_operator(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint — including disposition-tier mismatches on sanctions hits,
        where the permitted role depends on the hit's current state — is
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /wire-ops/wires/{id}/approve is authorized for
        `WireApprover` only.

        The role gate fires before any identity-level segregation check: a
        WireOperator who did NOT initiate the wire still cannot approve it.

        Design: Corner/rbac/approve_forbidden_for_operator
        """
        room = setup_wire_room(business_date="2026-09-29")
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"],
                           100000, operator_user_id="op-1")
        submit_wire(wire["id"], "2026-09-29", operator_user_id="op-1")

        resp = api.approve_wire(
            wire["id"], {"expected_wire_version": wire_version(wire["id"])},
            make_wire_operator_headers("op-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_repair_forbidden_for_operator(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint — including disposition-tier mismatches on sanctions hits,
        where the permitted role depends on the hit's current state — is
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /wire-ops/wires/{id}/repair is authorized for
        `RepairSpecialist` only.

        The WireOperator who drives the wire's lifecycle still cannot repair
        it, and the failed attempt consumes no repair budget.

        Design: Corner/rbac/repair_forbidden_for_operator
        """
        room = setup_wire_room(business_date="2026-09-30")
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"], 100000)
        submit_wire(wire["id"], "2026-09-30")

        resp = api.repair_wire(
            wire["id"],
            {"expected_wire_version": wire_version(wire["id"]),
             "purpose": "operator overreach"},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        wire_after = get_wire(wire["id"])
        assert wire_after["repair_attempts"] == 0, (
            f"no repair budget consumed, got {wire_after['repair_attempts']}")


class TestRepairLoopCap:
    def test_repair_limit_exceeded_at_third_attempt(self, api):
        """PRD §3.4: "Repairing a wire — allowed only from `PENDING_APPROVAL`,
        and only while the wire's `repair_attempts` count is below two, with a
        third attempt rejected as `ERR_REPAIR_LIMIT_EXCEEDED` — moves the wire
        to `REPAIR`, increments `repair_attempts`, applies the corrected
        fields supplied in the payload"

        Repairs one and two succeed; the third is rejected and the wire is
        back in PENDING_APPROVAL awaiting an approve/reject/cancel decision.

        Design: Corner/state_machines/repair_limit_exceeded_at_third_attempt
        """
        room = setup_wire_room(business_date="2026-09-02")
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"], 100000)
        submit_wire(wire["id"], "2026-09-02")

        first = repair_wire(wire["id"], purpose="fix one")
        assert first["repair_attempts"] == 1
        assert first["status"] == "REPAIR"
        resubmit_wire(wire["id"])

        second = repair_wire(wire["id"], purpose="fix two")
        assert second["repair_attempts"] == 2
        resubmit_wire(wire["id"])

        resp = api.repair_wire(
            wire["id"],
            {"expected_wire_version": wire_version(wire["id"]),
             "purpose": "fix three"},
            REPAIR_SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_REPAIR_LIMIT_EXCEEDED)

        wire_after = get_wire(wire["id"])
        assert wire_after["status"] == "PENDING_APPROVAL"
        assert wire_after["repair_attempts"] == 2


class TestRepairCycleParallelScreening:
    def test_repair_cycle_with_parallel_screening_dimension(self, api):
        """PRD §3.4: "Resubmission invalidates the prior round's approvals:
        every approval record from the prior round is marked `superseded` true
        and stops counting toward dual approval, and the wire's
        `first_approved_by` and `second_approved_by` reset to null, so a fresh
        `FIRST`/`SECOND` pair is required."
        PRD §3.6: "if the wire has already been submitted its
        `screening_status` is recomputed immediately — becoming `REVIEW` while
        the hit is unresolved"
        PRD §3.6: "When the released hit was the wire's **last unresolved
        hit**, the wire's `screening_status` transitions from `REVIEW` to
        `CLEAR`"

        The status dimension loops PENDING_APPROVAL -> REPAIR ->
        PENDING_APPROVAL while the screening dimension independently walks
        CLEAR -> REVIEW -> CLEAR; the superseded first approver may then
        approve again and a second distinct approver completes the cycle.

        Design: Difficulty/non_linear_state_machine/wire_repair_cycle_with_parallel_screening_dimension
        """
        room = setup_wire_room(business_date="2026-08-06")
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"],
                           100000, operator_user_id="op-1")
        submit_wire(wire["id"], "2026-08-06", operator_user_id="op-1")
        approve_wire(wire["id"], "ap-1")

        repaired = repair_wire(wire["id"], purpose="corrected purpose text")
        assert repaired["status"] == "REPAIR"
        assert repaired["repair_attempts"] == 1

        resubmit_wire(wire["id"])
        hit = simulate_hit(wire["id"], matched_list="INTERNAL_WATCH",
                           matched_party="Vendor Five", match_score=61)
        mid = get_wire(wire["id"])
        assert mid["status"] == "PENDING_APPROVAL"
        assert mid["screening_status"] == "REVIEW", (
            "the screening dimension moved while the processing dimension held")

        validate_success(api.release_sanctions_hit(
            hit["id"], {"rationale": "false positive: different Vendor Five"},
            SCREENER), 200)
        after_release = get_wire(wire["id"])
        assert after_release["screening_status"] == "CLEAR"
        assert after_release["status"] == "PENDING_APPROVAL"

        # ap-1's prior record was superseded by the resubmission, so ap-1 may
        # approve again; a second distinct approver completes the pair.
        first_again = approve_wire(wire["id"], "ap-1")
        assert first_again["status"] == "PENDING_APPROVAL"
        completed = approve_wire(wire["id"], "ap-2")
        assert completed["status"] == "APPROVED"

        records = list_wire_approvals(wire["id"])
        superseded = [r for r in records if r["superseded"]]
        live = [r for r in records if not r["superseded"]]
        assert len(superseded) == 1, f"the pre-repair record is superseded: {records}"
        assert len(live) == 2, f"a fresh FIRST/SECOND pair counts: {records}"

    def test_screening_moves_while_status_in_repair(self, api):
        """PRD §3.6: "Releasing and confirming additionally require the hit's
        wire to be in `PENDING_APPROVAL`, `REPAIR`, or `APPROVED`; any other
        wire state is `ERR_INVALID_STATE`."
        PRD §3.6: "When the released hit was the wire's **last unresolved
        hit**, the wire's `screening_status` transitions from `REVIEW` to
        `CLEAR`"

        While the wire sits in REPAIR, a simulated hit flips screening to
        REVIEW and the screener's release flips it back to CLEAR — the
        processing dimension stays REPAIR throughout, then resubmission
        returns the wire to PENDING_APPROVAL.

        Design: Difficulty/non_linear_state_machine/wire_repair_cycle_with_parallel_screening_dimension
        """
        room = setup_wire_room(business_date="2026-08-06")
        wire = create_submitted_wire(
            room["account"]["id"], room["beneficiary"]["id"],
            "2026-08-06", 100000)

        repaired = repair_wire(wire["id"], purpose="field fix")
        assert repaired["status"] == "REPAIR"

        hit = simulate_hit(wire["id"], matched_list="INTERNAL_WATCH",
                           matched_party="Vendor Five", match_score=61)
        in_review = get_wire(wire["id"])
        assert in_review["status"] == "REPAIR"
        assert in_review["screening_status"] == "REVIEW"

        validate_success(api.release_sanctions_hit(
            hit["id"], {"rationale": "cleared while in repair"}, SCREENER), 200)
        cleared = get_wire(wire["id"])
        assert cleared["status"] == "REPAIR", (
            "screening disposition does not move the processing dimension")
        assert cleared["screening_status"] == "CLEAR"

        resubmitted = resubmit_wire(wire["id"])
        assert resubmitted["status"] == "PENDING_APPROVAL"


class TestOptimisticConcurrency:
    def test_occ_approve_stale_version_conflict(self, api):
        """PRD §2.7: "Approving a wire, releasing a wire, and repairing a wire
        each require the request body to include `expected_wire_version`,
        carrying the wire's `version` as the client last observed it. If the
        value does not equal the wire's current `version` — because another
        writer has meanwhile acted on the wire (a first approval recorded, a
        repair submitted, a cancellation, a hold placed, or a screening-driven
        rejection) — the request is rejected with `ERR_STALE_VERSION` (HTTP
        412)."

        A second approval replaying the pre-first-approval version is stale:
        it applies nothing and the wire still carries exactly one approval.

        Design: Corner/cross_cutting_layers/occ_approve_stale_version_conflict
        """
        room = setup_wire_room(business_date="2026-10-06")
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"], 100000)
        submit_wire(wire["id"], "2026-10-06")
        stale_version = wire_version(wire["id"])

        first = validate_success(api.approve_wire(
            wire["id"], {"expected_wire_version": stale_version}, APPROVER_1), 200)
        assert_wire(first)

        resp = api.approve_wire(
            wire["id"], {"expected_wire_version": stale_version},
            make_wire_approver_headers("ap-2"))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        wire_after = get_wire(wire["id"])
        assert wire_after["status"] == "PENDING_APPROVAL"
        summary = validate_success(api.get_wire_summary(wire["id"], OPERATOR), 200)
        assert summary["approvals"] == 1, (
            f"the stale write applied nothing; approvals == 1, got "
            f"{summary['approvals']}")

    def test_occ_repair_stale_version_conflict(self, api):
        """PRD §2.7: "Approving a wire, releasing a wire, and repairing a wire
        each require the request body to include `expected_wire_version`,
        carrying the wire's `version` as the client last observed it."
        PRD §2.7: "If the value does not equal the wire's current `version` —
        because another writer has meanwhile acted on the wire (a first
        approval recorded, a repair submitted, a cancellation, a hold placed,
        or a screening-driven rejection) — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        A repair prepared against the pre-first-repair version is stale once
        the first repair landed; it is rejected and consumes no repair budget.

        Design: Corner/cross_cutting_layers/occ_repair_stale_version_conflict
        """
        room = setup_wire_room(business_date="2026-10-08")
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"], 100000)
        submit_wire(wire["id"], "2026-10-08")
        stale_version = wire_version(wire["id"])

        first = repair_wire(wire["id"], purpose="fix one")
        assert first["repair_attempts"] == 1
        resubmit_wire(wire["id"])

        resp = api.repair_wire(
            wire["id"],
            {"expected_wire_version": stale_version,
             "purpose": "fix two on stale view"},
            REPAIR_SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        wire_after = get_wire(wire["id"])
        assert wire_after["repair_attempts"] == 1, (
            f"the stale repair consumed no attempt budget, got "
            f"{wire_after['repair_attempts']}")
