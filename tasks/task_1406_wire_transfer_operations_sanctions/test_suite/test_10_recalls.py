"""Recalls: amount bounds, the single in-flight rule, the two-bank role
partition, the deferred 72-hour response window, completion cascades, and the
principal decomposition invariant."""
from test_helpers import (
    ApiErrorId,
    assert_recall_request,
    assert_wire,
    create_executed_wire,
    create_recall,
    create_sent_recall,
    get_wire,
    list_wire_charges,
    parse_instant,
    respond_recall,
    send_recall,
    set_clock,
    setup_wire_room,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import TEST_USERS

OPERATOR = TEST_USERS["wire_operator_headers"]
BENEFICIARY_BANK = TEST_USERS["beneficiary_bank_headers"]


class TestRecallAmountBounds:
    def test_recall_amount_exceeds_principal_rejected(self, api):
        """PRD §3.9: "the `amount_to_recall_cents` sought, which must be
        strictly positive and no greater than the wire's `amount_cents`; an
        out-of-range amount is `ERR_RECALL_AMOUNT_EXCEEDS`."

        One cent over the principal is rejected with ERR_RECALL_AMOUNT_EXCEEDS;
        a zero amount is rejected with either ERR_RECALL_AMOUNT_EXCEEDS or
        ERR_INVALID_REQUEST (PRD §3.9 maps the field's "strictly positive"
        bound to ERR_RECALL_AMOUNT_EXCEEDS, while PRD §2.8 priority 4 maps
        strictly-positive amount fields to the schema-level
        ERR_INVALID_REQUEST — the PRD names both errors for this input without
        fixing which pre-empts); exactly the principal is accepted.

        Design: Corner/validations/recall_amount_exceeds_principal_rejected
        """
        room = setup_wire_room(business_date="2026-09-17")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-09-17",
            1000000, purpose="recall amount probe")

        resp_over = api.create_recall(
            {"wire_id": wire["id"], "reason": "ERROR_AMOUNT",
             "amount_to_recall_cents": 1000001},
            OPERATOR)
        validate_error(resp_over, ApiErrorId.ERR_RECALL_AMOUNT_EXCEEDS)

        resp_zero = api.create_recall(
            {"wire_id": wire["id"], "reason": "ERROR_AMOUNT",
             "amount_to_recall_cents": 0},
            OPERATOR)
        validate_error_is_one_of(
            resp_zero,
            [ApiErrorId.ERR_RECALL_AMOUNT_EXCEEDS, ApiErrorId.ERR_INVALID_REQUEST])

        exact = validate_success(api.create_recall(
            {"wire_id": wire["id"], "reason": "ERROR_AMOUNT",
             "amount_to_recall_cents": 1000000},
            OPERATOR), 201)
        assert_recall_request(exact)
        assert exact["status"] == "REQUESTED"


class TestSingleRecallInFlight:
    def test_second_recall_in_progress_rejected(self, api):
        """PRD §3.9: "Only one non-terminal recall may exist per wire at a
        time — a second attempt while one is in flight is
        `ERR_RECALL_IN_PROGRESS`."

        Design: Corner/validations/second_recall_in_progress_rejected
        """
        room = setup_wire_room(business_date="2026-09-23")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-09-23",
            1000000, purpose="dup recall probe")

        first = create_recall(wire["id"], reason="DUPLICATE",
                              amount_to_recall_cents=500000)
        assert first["status"] == "REQUESTED"

        resp = api.create_recall(
            {"wire_id": wire["id"], "reason": "FRAUD",
             "amount_to_recall_cents": 100000},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_RECALL_IN_PROGRESS)


class TestRecallResponseRoleGate:
    def test_recall_respond_forbidden_for_operator(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint — including disposition-tier mismatches on sanctions hits,
        where the permitted role depends on the hit's current state — is
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §3.9: "The counterparty — acting in the `BeneficiaryBank` role,
        whose write authority extends to this one action — records its answer
        by supplying a `response` of `FUNDS_RETURNED` or `FUNDS_DECLINED`."

        The originating operator cannot answer their own recall.

        Design: Corner/rbac/recall_respond_forbidden_for_operator
        """
        room = setup_wire_room(business_date="2026-10-05")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-10-05",
            1000000, purpose="rbac recall")
        recall = create_sent_recall(wire["id"], reason="FRAUD",
                                    amount_to_recall_cents=1000000)
        assert recall["status"] == "SENT_TO_BENEFICIARY_BANK"

        resp = api.respond_recall(recall["id"], {"response": "FUNDS_RETURNED"},
                                  OPERATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        recall_after = validate_success(api.get_recall(recall["id"], OPERATOR), 200)
        assert recall_after["status"] == "SENT_TO_BENEFICIARY_BANK"


class TestRecallCompletionCascade:
    def test_recall_completion_cascades_recall_wire(self, api):
        """PRD §3.9: "Completion moves the recall to `COMPLETED`, transitions
        the wire from `EXECUTED` to `RECALLED`, books the recall compensation,
        and writes `recall.complete`."
        PRD §3.9: "when the recovery falls short, the unrecovered remainder is
        booked as recall loss."

        The completion — not any direct wire call — moves the wire; a partial
        recall of 5000000 against a 10000000 net books the shortfall while the
        wire's own money fields are untouched.

        Design: Difficulty/transitive_cascade/recall_completion_cascades_recall_wire
        """
        room = setup_wire_room(business_date="2026-08-11")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-08-11",
            10000000, purpose="recall probe")
        assert wire["net_principal_cents"] == 10000000

        recall = create_sent_recall(wire["id"], reason="ERROR_AMOUNT",
                                    amount_to_recall_cents=5000000)
        respond_recall(recall["id"], response="FUNDS_RETURNED")

        completed = validate_success(api.complete_recall(recall["id"], OPERATOR), 200)
        assert_recall_request(completed)
        assert completed["status"] == "COMPLETED"

        wire_after = get_wire(wire["id"])
        assert_wire(wire_after)
        assert wire_after["status"] == "RECALLED", (
            "the recall completion, not a wire call, drove the transition")
        assert wire_after["net_principal_cents"] == 10000000
        assert wire_after["amount_cents"] == 10000000

    def test_declined_response_keeps_wire_executed(self, api):
        """PRD §3.9: "declining requires `BENEFICIARY_RESPONDED` and a
        `FUNDS_DECLINED` answer (a mismatch is `ERR_INVALID_STATE`), moves the
        recall to `DECLINED`, and writes `recall.declined`."
        PRD §3.9: "completion requires `BENEFICIARY_RESPONDED` status (a
        terminal recall again yields `ERR_RECALL_ALREADY_RESOLVED`) and
        requires `beneficiary_bank_response` to be `FUNDS_RETURNED`, else
        `ERR_RECALL_NOT_RETURNED`."

        On the FUNDS_DECLINED branch, completion is impossible and the
        decline leaves the wire EXECUTED — only a FUNDS_RETURNED completion
        recalls the wire.

        Design: Difficulty/transitive_cascade/recall_completion_cascades_recall_wire
        """
        room = setup_wire_room(business_date="2026-08-11")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-08-11",
            10000000, purpose="decline probe")

        recall = create_sent_recall(wire["id"], reason="ERROR_BENEFICIARY",
                                    amount_to_recall_cents=10000000)
        responded = respond_recall(recall["id"], response="FUNDS_DECLINED")
        assert responded["status"] == "BENEFICIARY_RESPONDED"
        assert responded["beneficiary_bank_response"] == "FUNDS_DECLINED"
        assert responded["responded_at"] is not None

        resp_complete = api.complete_recall(recall["id"], OPERATOR)
        validate_error(resp_complete, ApiErrorId.ERR_RECALL_NOT_RETURNED)

        declined = validate_success(api.decline_recall(recall["id"], OPERATOR), 200)
        assert declined["status"] == "DECLINED"

        wire_after = get_wire(wire["id"])
        assert wire_after["status"] == "EXECUTED", (
            "a declined recall never touches the wire")


class TestRecallResponseWindow:
    def test_recall_response_window_72h_deferred_deadline(self, api):
        """PRD §3.9: "Responding requires the recall to be in
        `SENT_TO_BENEFICIARY_BANK` — acting on a terminal recall is
        `ERR_RECALL_ALREADY_RESOLVED`, while acting on one still merely
        `REQUESTED` is `ERR_INVALID_STATE` — and requires the response
        strictly before `response_due_at`, with a late answer rejected as
        `ERR_RECALL_EXPIRED`."
        PRD §3.9: "The seventy-two-hour window is strict and lazily enforced:
        at or after `response_due_at`, an unanswered recall auto-expires to
        `EXPIRED` on any access, writes the `recall.expired` audit entry, and
        — critically — leaves the wire's status untouched: the recall dies,
        the payment stays `EXECUTED`."

        A response one second before the deadline lands; a response exactly
        at the deadline is rejected, and the expired recall leaves the wire
        EXECUTED.

        Design: Difficulty/resource_temporal_overlap/recall_response_window_72h_deferred_deadline
        """
        room = setup_wire_room(business_date="2026-08-18")
        account = room["account"]
        beneficiary = room["beneficiary"]

        set_clock("2026-08-01T00:00:00Z")
        wire_a = create_executed_wire(
            account["id"], beneficiary["id"], "2026-08-18", 1000000,
            purpose="recall window A")
        recall_a = create_sent_recall(wire_a["id"], reason="DUPLICATE",
                                      amount_to_recall_cents=1000000)

        wire_b = create_executed_wire(
            account["id"], beneficiary["id"], "2026-08-18", 1000000,
            purpose="recall window B")
        recall_b = create_recall(wire_b["id"], reason="FRAUD",
                                 amount_to_recall_cents=1000000)
        set_clock("2026-08-01T01:00:00Z")
        send_recall(recall_b["id"])  # due exactly 2026-08-04T01:00:00Z

        set_clock("2026-08-03T23:59:59Z")
        responded = respond_recall(recall_a["id"], response="FUNDS_RETURNED")
        assert responded["status"] == "BENEFICIARY_RESPONDED", (
            "one second before the 72-hour deadline is a valid response")

        set_clock("2026-08-04T01:00:00Z")
        resp_late = api.respond_recall(
            recall_b["id"], {"response": "FUNDS_RETURNED"}, BENEFICIARY_BANK)
        validate_error(resp_late, ApiErrorId.ERR_RECALL_EXPIRED)

        recall_b_after = validate_success(
            api.get_recall(recall_b["id"], OPERATOR), 200)
        assert recall_b_after["status"] == "EXPIRED"
        wire_b_after = get_wire(wire_b["id"])
        assert wire_b_after["status"] == "EXECUTED", (
            "recall expiry does not cancel the payment")

    def test_response_deadline_fixed_at_dispatch_time(self, api):
        """PRD §3.9: "The originating operator dispatches the recall to the
        beneficiary bank; dispatch requires `REQUESTED` status (else
        `ERR_INVALID_STATE`), moves the recall to `SENT_TO_BENEFICIARY_BANK`,
        sets `response_due_at` exactly seventy-two hours out, and is
        audit-logged as `recall.send`."

        The 72-hour window is anchored to the dispatch, not the creation: a
        recall created at T and sent at T+10h is due at T+82h.

        Design: Difficulty/resource_temporal_overlap/recall_response_window_72h_deferred_deadline
        """
        from datetime import timedelta

        room = setup_wire_room(business_date="2026-08-18")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-08-18",
            1000000, purpose="deferred window probe")

        set_clock("2026-08-01T00:00:00Z")
        recall = create_recall(wire["id"], reason="DUPLICATE",
                               amount_to_recall_cents=1000000)
        assert recall["status"] == "REQUESTED"

        set_clock("2026-08-01T10:00:00Z")
        sent = send_recall(recall["id"])
        assert_recall_request(sent)
        assert sent["status"] == "SENT_TO_BENEFICIARY_BANK"
        expected_due = parse_instant("2026-08-01T10:00:00Z") + timedelta(hours=72)
        assert parse_instant(sent["response_due_at"]) == expected_due, (
            f"response_due_at must be dispatch + 72h, got "
            f"{sent['response_due_at']}")


class TestPrincipalDecompositionInvariant:
    def test_principal_decomposition_invariant_across_recall(self, api):
        """PRD §3.9: "The compensation accounting conserves an invariant
        established at execution: the wire's `amount_cents` always equals its
        `net_principal_cents` plus the sum of the amounts of `POSTED` charges
        of type `DEDUCTED_FROM_PRINCIPAL` measured at the moment of execution,
        and that equality still holds after recall completion."

        With 4000 + 2000 deducted: at execution 10000000 == 9994000 + 6000;
        after the partial recall completes the wire is RECALLED and the
        decomposition is unmoved.

        Design: Difficulty/compensating_invariant/principal_decomposition_invariant_across_recall
        """
        room = setup_wire_room(business_date="2026-08-20")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-08-20",
            10000000, purpose="invariant probe",
            charges=[
                {"correspondent_name": "CorrP",
                 "charge_type": "DEDUCTED_FROM_PRINCIPAL", "amount_cents": 4000,
                 "source": "ACTUAL_ADVICE"},
                {"correspondent_name": "CorrQ",
                 "charge_type": "DEDUCTED_FROM_PRINCIPAL", "amount_cents": 2000,
                 "source": "ACTUAL_ADVICE"},
            ])
        assert wire["net_principal_cents"] == 9994000, (
            f"10000000 - 6000 deducted; got {wire['net_principal_cents']}")
        assert wire["amount_cents"] == wire["net_principal_cents"] + 6000

        recall = create_sent_recall(wire["id"], reason="ERROR_AMOUNT",
                                    amount_to_recall_cents=5000000)
        respond_recall(recall["id"], response="FUNDS_RETURNED")
        completed = validate_success(api.complete_recall(recall["id"], OPERATOR), 200)
        assert completed["status"] == "COMPLETED"

        wire_after = get_wire(wire["id"])
        assert wire_after["status"] == "RECALLED"
        assert wire_after["amount_cents"] == 10000000
        assert wire_after["net_principal_cents"] == 9994000, (
            "recall bookkeeping must not drift the wire's decomposition")

        charges = list_wire_charges(wire["id"])
        posted_amounts = sorted(
            c["amount_cents"] for c in charges if c["status"] == "POSTED")
        assert posted_amounts == [2000, 4000], (
            f"POSTED deducted charges unchanged, got {posted_amounts}")
        assert wire_after["amount_cents"] == (
            wire_after["net_principal_cents"] + sum(posted_amounts))

    def test_decomposition_invariant_with_non_deducted_charge(self, api):
        """PRD §3.5: "its `net_principal_cents` is computed as the wire's
        `amount_cents` minus the sum of the amounts of `POSTED` charges whose
        `charge_type` is `DEDUCTED_FROM_PRINCIPAL`."
        PRD §3.9: "the wire's `amount_cents` always equals its
        `net_principal_cents` plus the sum of the amounts of `POSTED` charges
        of type `DEDUCTED_FROM_PRINCIPAL` measured at the moment of execution,
        and that equality still holds after recall completion."

        An OUR-borne charge does not deduct: net equals principal at
        execution, and a full-recall completion preserves that decomposition
        with the charge still POSTED.

        Design: Difficulty/compensating_invariant/principal_decomposition_invariant_across_recall
        """
        room = setup_wire_room(business_date="2026-08-20")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-08-20",
            5000000, purpose="invariant probe two",
            charges=[
                {"correspondent_name": "CorrO", "charge_type": "OUR",
                 "amount_cents": 3000, "source": "ACTUAL_ADVICE"},
            ])
        assert wire["net_principal_cents"] == 5000000, (
            f"an OUR charge never deducts from principal, got "
            f"{wire['net_principal_cents']}")
        assert wire["amount_cents"] == wire["net_principal_cents"] + 0

        recall = create_sent_recall(wire["id"], reason="ERROR_AMOUNT",
                                    amount_to_recall_cents=5000000)
        respond_recall(recall["id"], response="FUNDS_RETURNED")
        completed = validate_success(api.complete_recall(recall["id"], OPERATOR), 200)
        assert completed["status"] == "COMPLETED"

        wire_after = get_wire(wire["id"])
        assert wire_after["status"] == "RECALLED"
        assert wire_after["amount_cents"] == 5000000
        assert wire_after["net_principal_cents"] == 5000000

        charges = list_wire_charges(wire["id"])
        posted = [c for c in charges if c["status"] == "POSTED"]
        assert len(posted) == 1 and posted[0]["amount_cents"] == 3000
        deducted = sum(c["amount_cents"] for c in posted
                       if c["charge_type"] == "DEDUCTED_FROM_PRINCIPAL")
        assert wire_after["amount_cents"] == (
            wire_after["net_principal_cents"] + deducted)
