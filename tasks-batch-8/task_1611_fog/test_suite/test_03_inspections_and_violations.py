"""Inspection scoring, violation lifecycle, cure deadlines, and escalation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_violation,
    create_establishment,
    create_failing_inspection,
    create_inspection,
    create_inspection_payload,
    get_establishment,
    get_open_violation,
    get_success_data,
    make_compliance_officer_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestInspectionScoring:
    def test_inspection_score_exactly_seventy_passes(self, api):
        """PRD: "Scoring happens atomically at creation: each `MINOR` finding
        deducts 3 points, each `MAJOR` deducts 8, and each `CRITICAL` deducts
        20, and the inspection's `score` is 100 minus the total deductions,
        never below zero. An inspection has `passed` when its score is at
        least 70 — exactly 70 passes, while 69 fails."
        PRD: "A passing inspection opens no violation."

        Design: Difficulty/boundary_precision_check/inspection_score_exactly_seventy_passes
        """
        e1 = create_establishment(name="Boundary One", street_address="60 D Dr")
        e2 = create_establishment(name="Boundary Two", street_address="61 D Dr")

        # 3 MAJOR + 2 MINOR = 24 + 6 = 30 deductions -> score exactly 70.
        insp1 = create_inspection(e1["id"], [
            {"category": "GREASE_TRAP_MAINTENANCE", "severity": "MAJOR"},
            {"category": "RECORD_KEEPING", "severity": "MAJOR"},
            {"category": "STRUCTURAL", "severity": "MAJOR"},
            {"category": "BMP_PRACTICES", "severity": "MINOR"},
            {"category": "BMP_PRACTICES", "severity": "MINOR"},
        ])
        assert insp1["score"] == 70, f"100 - 30 == 70, got {insp1['score']}"
        assert insp1["passed"] is True, "exactly 70 passes"
        violations1, meta1 = validate_paginated(
            api.list_violations(INSPECTOR, {"establishment_id": e1["id"]}))
        assert meta1["total_count"] == 0, "A passing inspection opens no violation"

        # 2 MAJOR + 5 MINOR = 16 + 15 = 31 deductions -> score 69, fails.
        insp2, viol2 = create_failing_inspection(e2["id"])
        assert insp2["score"] == 69, f"100 - 31 == 69, got {insp2['score']}"
        assert insp2["passed"] is False
        assert viol2["severity"] == "MAJOR"
        assert viol2["status"] == "NOTICED"

    def test_inspection_score_boundary_seventy_one_passes(self, api):
        """PRD: "An inspection has `passed` when its score is at least 70 —
        exactly 70 passes, while 69 fails."
        PRD: "A passing inspection opens no violation."

        Design: Difficulty/boundary_precision_check/inspection_score_exactly_seventy_passes
        """
        est = create_establishment(name="Boundary Three",
                                   street_address="62 D Dr")
        # 1 CRITICAL + 1 MAJOR + 1 MINOR = 20 + 8 + 3 = 31 -> 69 fails...
        # use 1 CRITICAL + 3 MINOR = 20 + 9 = 29 -> 71 passes.
        insp = create_inspection(est["id"], [
            {"category": "STRUCTURAL", "severity": "CRITICAL"},
            {"category": "RECORD_KEEPING", "severity": "MINOR"},
            {"category": "BMP_PRACTICES", "severity": "MINOR"},
            {"category": "GREASE_TRAP_MAINTENANCE", "severity": "MINOR"},
        ])
        assert insp["score"] == 71
        assert insp["passed"] is True, "71 >= 70 passes"
        violations, meta = validate_paginated(
            api.list_violations(INSPECTOR, {"establishment_id": est["id"]}))
        assert meta["total_count"] == 0

    def test_inspection_score_constants_and_floor(self, api):
        """PRD: "Scoring happens atomically at creation: each `MINOR` finding
        deducts 3 points, each `MAJOR` deducts 8, and each `CRITICAL` deducts
        20, and the inspection's `score` is 100 minus the total deductions,
        never below zero."
        PRD: "its `severity` is the highest severity present among the
        findings, with `CRITICAL` ranking above `MAJOR` above `MINOR`."

        Design: Corner/calculations/c_inspection_score_constants_and_floor
        """
        e1 = create_establishment(name="Score One", street_address="10 J St")
        e2 = create_establishment(name="Score Two", street_address="11 J St")

        insp1 = create_inspection(e1["id"], [
            {"category": "STRUCTURAL", "severity": "CRITICAL"},
            {"category": "RECORD_KEEPING", "severity": "MAJOR"},
        ])
        assert insp1["score"] == 72, "100 - 20 - 8 == 72"
        assert insp1["passed"] is True

        insp2 = create_inspection(e2["id"], [
            {"category": "STRUCTURAL", "severity": "CRITICAL"},
            {"category": "RECORD_KEEPING", "severity": "CRITICAL"},
            {"category": "GREASE_TRAP_MAINTENANCE", "severity": "CRITICAL"},
            {"category": "BMP_PRACTICES", "severity": "CRITICAL"},
            {"category": "STRUCTURAL", "severity": "CRITICAL"},
            {"category": "RECORD_KEEPING", "severity": "CRITICAL"},
        ])
        assert insp2["score"] == 0, "floor max(0, 100 - 120) binds"
        assert insp2["passed"] is False
        viol2 = get_open_violation(e2["id"])
        assert viol2["severity"] == "CRITICAL", (
            "Violation severity is the highest severity among the findings"
        )


class TestViolationSideEffects:
    def test_failing_inspection_sets_cure_deadline_and_fine_zero(self, api):
        """PRD: "It opens in `NOTICED` status with `fine_cents` at zero, a
        `cure_deadline` set from its creation time according to severity — 30
        days for `MINOR`, 14 days for `MAJOR`, 3 days for `CRITICAL` — and
        `recorded_by_user_id` holding the identity of the inspector whose
        inspection created it."
        PRD: "Before any clock-setting call has been made, the logical clock
        reads exactly 2026-08-01T00:00:00Z."

        Design: Corner/state_machines/c_failing_inspection_sets_cure_deadline_and_fine_zero
        """
        est = create_establishment(name="Deadline Deli", street_address="9 I St")
        _insp, violation = create_failing_inspection(est["id"],
                                                     inspector_user_id="insp-7")
        assert_violation(violation)
        assert violation["status"] == "NOTICED"
        # MAJOR -> created_at (2026-08-01, the default clock) + 14 days.
        assert violation["cure_deadline"].startswith("2026-08-15"), (
            f"MAJOR cure deadline is creation + 14 days, got "
            f"{violation['cure_deadline']}"
        )
        assert violation["fine_cents"] == 0, "fine_cents stays 0 while NOTICED"
        assert violation["recorded_by_user_id"] == "insp-7"

    def test_failing_inspection_raises_open_count_and_watch(self, api):
        """PRD: "The establishment's `open_violation_count` rises by one, and
        its posture is recomputed."
        PRD: "otherwise `WATCH` whenever any violation stands at `NOTICED`"

        Design: Difficulty/compensating_invariant/violation_dismiss_restores_open_count
        """
        est = create_establishment(name="Watch Cafe", street_address="98 H Way")
        assert est["open_violation_count"] == 0
        assert est["compliance_status"] == "COMPLIANT"

        create_failing_inspection(est["id"])
        after = get_establishment(est["id"])
        assert after["open_violation_count"] == 1
        assert after["compliance_status"] == "WATCH"


class TestViolationEscalation:
    def test_escalate_before_cure_deadline_rejected(self, api):
        """PRD: "A `ComplianceOfficer` may escalate a `NOTICED` violation once
        the logical clock has reached its `cure_deadline`; attempting it
        earlier is rejected with `ERR_ESCALATION_NOT_DUE` (HTTP 409), while
        escalating at exactly the deadline instant is allowed. Escalation
        stamps `escalated_at`, sets `fine_cents` by severity — 10000 cents for
        `MINOR`, 50000 cents for `MAJOR`, 250000 cents for `CRITICAL`"

        Design: Corner/validations/c_escalate_before_cure_deadline_rejected
        """
        est = create_establishment(name="Early Bird", street_address="18 O St")
        _insp, violation = create_failing_inspection(est["id"])

        set_clock("2026-08-14T00:00:00Z")
        resp = api.escalate_violation(violation["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_ESCALATION_NOT_DUE, 409)
        current = validate_success(api.get_violation(violation["id"], INSPECTOR))
        assert current["status"] == "NOTICED"

        set_clock("2026-08-15T00:00:00Z")
        escalated = validate_success(api.escalate_violation(violation["id"],
                                                            OFFICER))
        assert escalated["status"] == "CITATION", (
            "Escalating at exactly the deadline instant is allowed"
        )
        assert escalated["fine_cents"] == 50000, "MAJOR citation fine is 50000"

    def test_escalate_at_deadline_suspends_establishment(self, api):
        """PRD: "Escalation stamps `escalated_at`, sets `fine_cents` by
        severity — 10000 cents for `MINOR`, 50000 cents for `MAJOR`, 250000
        cents for `CRITICAL` — and recomputes the establishment's posture,
        which may now enter `SUSPENDED`"
        PRD: "`SUSPENDED` whenever any violation of the establishment stands
        at `CITATION`"

        Design: Corner/validations/c_escalate_before_cure_deadline_rejected
        """
        est = create_establishment(name="Escalate Eats",
                                   street_address="19 O St")
        _insp, violation = create_failing_inspection(est["id"])
        set_clock("2026-08-15T00:00:00Z")
        escalated = validate_success(api.escalate_violation(violation["id"],
                                                            OFFICER))
        assert escalated["status"] == "CITATION"
        after = get_establishment(est["id"])
        assert after["compliance_status"] == "SUSPENDED"


class TestViolationTerminalStates:
    def test_resolved_violation_terminal_lockdown(self, api):
        """PRD: "`RESOLVED` and `DISMISSED` are terminal: closed violations
        accept no further transitions."
        PRD: "Either outcome decrements the establishment's
        `open_violation_count` by one and recomputes its posture."

        Design: Corner/state_machines/c_resolved_violation_terminal_lockdown
        """
        est = create_establishment(name="Lockdown Lunch", street_address="7 G St")
        _insp, violation = create_failing_inspection(est["id"],
                                                     inspector_user_id="insp-7")
        resolved = validate_success(api.resolve_violation(violation["id"],
                                                          INSPECTOR))
        assert resolved["status"] == "RESOLVED"
        mid = get_establishment(est["id"])
        assert mid["open_violation_count"] == 0, "Exactly one decrement, at resolve"

        resp = api.dismiss_violation(
            violation["id"], make_compliance_officer_headers("officer-9"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        current = validate_success(api.get_violation(violation["id"], INSPECTOR))
        assert current["status"] == "RESOLVED"
        after = get_establishment(est["id"])
        assert after["open_violation_count"] == 0, "No double-decrement"


class TestViolationDismissCompensatingInvariant:
    def test_violation_dismiss_restores_open_count(self, api):
        """PRD: "The establishment's `open_violation_count` rises by one, and
        its posture is recomputed."
        PRD: "Either outcome decrements the establishment's
        `open_violation_count` by one and recomputes its posture."
        PRD: "a successful dismissal stamps `dismissed_at` and records
        `dismissed_by_user_id`"

        Design: Difficulty/compensating_invariant/violation_dismiss_restores_open_count
        """
        est = create_establishment(name="Counting Cafe", street_address="99 H Way")
        assert est["open_violation_count"] == 0

        _insp, violation = create_failing_inspection(est["id"],
                                                     inspector_user_id="insp-7")
        mid = get_establishment(est["id"])
        assert mid["open_violation_count"] == 1
        assert mid["compliance_status"] == "WATCH"

        dismissed = validate_success(api.dismiss_violation(
            violation["id"], make_compliance_officer_headers("officer-9")))
        assert dismissed["status"] == "DISMISSED"
        assert dismissed["dismissed_by_user_id"] == "officer-9"

        after = get_establishment(est["id"])
        assert after["open_violation_count"] == 0, (
            "create + dismiss conserves open_violation_count"
        )
        assert after["compliance_status"] == "COMPLIANT"

    def test_violation_resolve_restores_open_count_and_posture(self, api):
        """PRD: "An `Inspector` marks the problem corrected, moving the
        violation to `RESOLVED` with `resolved_at` stamped to the current
        clock."
        PRD: "Either outcome decrements the establishment's
        `open_violation_count` by one and recomputes its posture."
        PRD: "otherwise `WATCH` whenever any violation stands at `NOTICED`"

        Design: Difficulty/compensating_invariant/violation_dismiss_restores_open_count
        """
        est = create_establishment(name="Resolving Ramen",
                                   street_address="100 H Way")
        _insp, violation = create_failing_inspection(est["id"])
        assert get_establishment(est["id"])["open_violation_count"] == 1

        resolved = validate_success(api.resolve_violation(violation["id"],
                                                          INSPECTOR))
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_at"] is not None
        after = get_establishment(est["id"])
        assert after["open_violation_count"] == 0
        assert after["compliance_status"] == "COMPLIANT"
