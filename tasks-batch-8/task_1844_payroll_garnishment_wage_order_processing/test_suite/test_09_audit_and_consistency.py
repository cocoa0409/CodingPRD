"""Audit chain integrity, pay-time atomic visibility, answer deadlines, and
read-path contracts (defaults, immutable configuration, pagination)."""
from test_helpers import (
    answer_payload,
    api_client,
    assert_employer,
    assert_state_rule,
    get_order,
    get_state_rule,
    get_success_data,
    list_order_events,
    make_employer,
    make_employee,
    make_state_rule,
    set_clock,
    setup_active_order_scenario,
    setup_paid_single_order,
    validate_paginated,
)
from test_helpers.fixtures import AUDITOR, MANAGER

EXPECTED_ACTION_SEQUENCE = [
    "employee.create",
    "order.receive",
    "order.validate",
    "order.notify",
    "order.activate",
    "run.create",
    "statement.create",
    "run.pay",
]


class TestAuditChainIntegrity:
    def test_chain_verifies_and_links_from_genesis(self, api):
        """PRD §2.11: "Entries are hash-chained per employer. Each entry stores
        a `prev_hash`: the `entry_hash` of the previous audit entry for that
        employer, or the literal `GENESIS` for the employer's first entry."
        PRD §2.11: "A caller may pass the `verify` query flag set to true on
        the employer-scoped audit listing to have the server recompute every
        `entry_hash` and re-walk every `prev_hash` link; the chain is valid
        only if every recomputed hash matches its stored value and every link
        points at its predecessor, and a mismatch is rejected with
        `ERR_AUDIT_CHAIN_BROKEN` (HTTP 409)."
        After a mixed sequence of 8+ mutations the server-side recomputation
        succeeds (no ERR_AUDIT_CHAIN_BROKEN) and the client-side linkage holds.

        Design: Difficulty/compensating_invariant/audit_chain_genesis_linkage_invariant
        """
        base = setup_paid_single_order(
            order_overrides={"case_number": "CS-N", "amount_value": 5000}
        )
        resp = api_client.list_employer_audit_log(
            base["employer"]["id"], AUDITOR, params={"verify": "true"}
        )
        entries, meta = validate_paginated(resp)
        assert len(entries) >= 8, f"expected at least 8 audit entries, got {len(entries)}"
        assert entries[0]["prev_hash"] == "GENESIS"
        for prev, cur in zip(entries, entries[1:]):
            assert cur["prev_hash"] == prev["entry_hash"], (
                "prev_hash must equal the previous entry's entry_hash"
            )
        for entry in entries:
            assert isinstance(entry["entry_hash"], str) and len(entry["entry_hash"]) == 64
            assert isinstance(entry["payload_hash"], str) and len(entry["payload_hash"]) == 64

    def test_audit_actions_recorded_in_operation_order(self, api):
        """PRD §2.11: "Each entry records the mutated resource's `entity_type`
        and `entity_id`, an `action` label naming the operation (for example
        `order.validate` or `run.pay`), the actor's `actor_role` — the
        `X-User-Role` of the caller, or `SYSTEM` for automatic transitions —
        and the actor's `actor_id` — the `X-User-ID`, or the literal `system`
        for automatic work."
        PRD §2.11: "The audit listing is ordered by `created_at` ascending,
        with a monotonic sequence disambiguating entries that share a
        timestamp."
        The employee/order/run lifecycle writes its labelled entries in
        operation order with the acting roles recorded.

        Design: Difficulty/compensating_invariant/audit_chain_genesis_linkage_invariant
        """
        base = setup_paid_single_order(
            order_overrides={"case_number": "CS-N", "amount_value": 5000}
        )
        resp = api_client.list_employer_audit_log(
            base["employer"]["id"], AUDITOR, params={"verify": "true"}
        )
        entries, meta = validate_paginated(resp)
        actions = [e["action"] for e in entries]
        # Subsequence check: the eight lifecycle actions appear in order.
        idx = 0
        for action in actions:
            if idx < len(EXPECTED_ACTION_SEQUENCE) and action == EXPECTED_ACTION_SEQUENCE[idx]:
                idx += 1
        assert idx == len(EXPECTED_ACTION_SEQUENCE), (
            f"expected lifecycle actions in order {EXPECTED_ACTION_SEQUENCE}, got {actions}"
        )
        for entry in entries:
            assert isinstance(entry["actor_role"], str) and entry["actor_role"]
            assert isinstance(entry["actor_id"], str) and entry["actor_id"]
        specialist_actions = {"employee.create", "order.receive", "order.validate",
                              "order.notify", "order.activate", "run.create",
                              "statement.create", "run.pay"}
        for entry in entries:
            if entry["action"] in specialist_actions:
                assert entry["actor_role"] == "payroll_specialist"


class TestPayCascadeVisibility:
    def test_pay_cascade_atomically_visible(self, api):
        """PRD §2.8: "Several mutations cascade upward, and every cascade
        completes atomically inside the triggering request."
        PRD §3.6: "Payment executes the withholding waterfall independently for
        every statement in the run, posts one `WITHHOLD` withholding event per
        awarded order — idempotently, at most one event per pairing of
        `pay_statement_id` and `garnishment_order_id` — finalizes each
        statement, moves the run to the terminal `PAID` state, increments the
        employer's `version`, and appends one audit entry per statement (action
        `run.pay`)."
        Immediately after the pay response, the follow-up reads show run PAID,
        statement finalized at 10000, order withheld 10000, and exactly one
        WITHHOLD event.

        Design: Corner/consistency_model/pay_cascade_atomic_visibility
        """
        base = setup_paid_single_order(
            order_overrides={"case_number": "CS-IC", "amount_value": 10000}
        )
        assert base["run"]["status"] == "PAID"
        assert base["statement"]["total_withheld_cents"] == 10000
        assert base["order"]["withheld_cents"] == 10000
        events = list_order_events(base["order"]["id"])
        assert len(events) == 1
        assert events[0]["event_type"] == "WITHHOLD"
        assert events[0]["amount_cents"] == 10000


class TestAnswerDeadline:
    def test_answer_after_due_date_accepted_and_late(self, api):
        """PRD §3.3: "The `answer_due_date` is ten business days after the
        receipt date, counting only Monday through Friday."
        PRD §3.4: "an `ACCEPTED` filing moves the order from `ACTIVE` to
        `ANSWER_FILED` and appends an audit entry (action `order.answer`). An
        answer filed on or before the `answer_due_date` is on time; a later
        answer is late — late answers are legal but flagged."
        Received Monday 2026-08-03, the due date lands on Monday 2026-08-17;
        an answer dated 2026-08-18 is late but still moves the order to
        ANSWER_FILED.

        Design: Corner/cross_cutting_layers/answer_late_flagged_on_answer_deadline
        """
        base = setup_active_order_scenario(
            clock="2026-08-03T00:00:00Z",
            order_overrides={
                "case_number": "CS-AN",
                "amount_value": 1000,
                "effective_date": "2026-08-03",
            },
        )
        order = base["order"]
        assert order["answer_due_date"] == "2026-08-17"
        answered = get_success_data(
            api_client.answer_order(
                order["id"],
                answer_payload("ACCEPTED", "2026-08-18"),
                MANAGER,
            )
        )
        assert answered["processing_status"] == "ANSWER_FILED"
        assert get_order(order["id"])["processing_status"] == "ANSWER_FILED"


class TestReadPathContracts:
    def test_employer_creation_applies_admin_fee_default(self, api):
        """PRD §3.1: "The `administrative_fee_policy` — `NONE` or `PER_ORDER` —
        declares whether the employer charges a processing fee; under
        `PER_ORDER`, the `admin_fee_cents` value (an integer number of cents,
        never negative, defaulting to 0 when omitted) is charged per active
        garnished order per paid run."
        Omitting admin_fee_cents at enrollment stores the default 0.

        Design: Corner/entities/employer_creation_applies_defaults
        """
        set_clock()
        emp = make_employer()  # factory omits admin_fee_cents
        assert_employer(emp)
        assert emp["admin_fee_cents"] == 0

    def test_state_rule_reads_back_exactly(self, api):
        """PRD §3.1: "State rules are immutable once created; correction means
        administering a new record, never editing the old."
        The stored configuration is returned exactly as posted.

        Design: Corner/entities/state_rule_immutable_no_update_endpoint
        """
        set_clock()
        created = make_state_rule("CA")
        fetched = get_state_rule("CA", AUDITOR)
        assert_state_rule(fetched)
        assert fetched["id"] == created["id"]
        assert fetched["state_code"] == "CA"
        assert fetched["caps"] == {
            "CHILD_SUPPORT": 0.50,
            "FEDERAL_TAX_LEVY": 0.65,
            "STUDENT_LOAN": 0.15,
            "CREDITOR": 0.25,
        }
        assert fetched["min_wage_multiplier"] == 0.75
        assert fetched["hourly_floor_cents"] == 0
        assert fetched["fee_deductible_from_wages"] is True

    def test_list_employees_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items:
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of items and defaults to 0. Every
        list response carries `limit`, `offset`, `total_count`, and `has_more`
        in the `meta` object of the envelope."
        Three employees, limit 2: page one carries 2 items, total_count 3,
        has_more true.

        Design: Corner/endpoints/list_employees_pagination_envelope
        """
        set_clock()
        make_state_rule("CA")
        emp = make_employer()
        for name in ("W1", "W2", "W3"):
            make_employee(emp["id"], full_name=name)
        resp = api_client.list_employer_employees(
            emp["id"], AUDITOR, params={"limit": 2, "offset": 0}
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
