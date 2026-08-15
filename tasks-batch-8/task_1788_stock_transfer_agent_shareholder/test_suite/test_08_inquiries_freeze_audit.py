"""Freeze-window closed-interval semantics, the inquiry claim/answer cycle,
list pagination, the tamper-evident audit chain, and clock-set idempotence."""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    SERVICE,
    ApiErrorId,
    answer_inquiry,
    claim_inquiry,
    create_account,
    create_declaration,
    create_freeze_window,
    create_inquiry,
    create_issuer,
    freeze_window_payload,
    get_declaration,
    get_inquiry,
    make_service_agent_headers,
    officer_headers,
    seed_position,
    set_clock,
    settle_transfer,
    setup_approved_transfer,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFreezeWindowOverlap:
    def test_touching_boundary_window_rejected(self, api):
        """PRD §3.1: "Windows on the same issuer may not overlap: a new window
        conflicts with any existing window that has not yet reached `EXPIRED`
        status whenever the new window's `start_date` falls on or before the
        existing window's `end_date` and the existing window's `start_date`
        falls on or before the new window's `end_date` — closed-interval
        semantics under which two windows sharing even a single boundary day
        conflict — and such a declaration is refused with
        `ERR_FREEZE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/freeze_window_closed_interval_overlap
        """
        issuer = create_issuer(name="Pi Corp", cusip="000000016", ticker="PICO")
        create_freeze_window(issuer, "2026-09-01T00:00:00Z",
                             "2026-09-05T00:00:00Z", "record date blackout")

        # 2026-09-05 belongs to both windows under closed-interval semantics.
        resp = api.create_freeze_window(
            issuer["id"],
            freeze_window_payload("2026-09-05T00:00:00Z", "2026-09-10T00:00:00Z",
                                  "touching window"),
            officer_headers(issuer),
        )
        validate_error(resp, ApiErrorId.ERR_FREEZE_WINDOW_OVERLAP)

    def test_disjoint_window_accepted(self, api):
        """PRD §3.1: "a new window conflicts with any existing window that has
        not yet reached `EXPIRED` status whenever the new window's `start_date`
        falls on or before the existing window's `end_date` and the existing
        window's `start_date` falls on or before the new window's `end_date`"
        PRD §3.1: "An officer may also declare a **transfer freeze window**
        over the security — a closed interval of days during which no transfer
        of the security may settle."

        Design: Difficulty/resource_temporal_overlap/freeze_window_closed_interval_overlap
        """
        issuer = create_issuer(name="Pi Corp", cusip="000000016", ticker="PICO")
        create_freeze_window(issuer, "2026-09-01T00:00:00Z",
                             "2026-09-05T00:00:00Z", "record date blackout")

        second = validate_success(api.create_freeze_window(
            issuer["id"],
            freeze_window_payload("2026-09-06T00:00:00Z", "2026-09-10T00:00:00Z",
                                  "adjacent disjoint window"),
            officer_headers(issuer)), 201)
        assert second["status"] == "SCHEDULED"

        _, meta = validate_paginated(api.list_freeze_windows(
            officer_headers(issuer), {"issuer_id": issuer["id"]}))
        assert meta["total_count"] == 2

    def test_freeze_window_inverted_range_rejected(self, api):
        """PRD §3.1: "An `end_date` earlier than the `start_date` is rejected
        with `ERR_INVALID_DATE_RANGE`, while a window whose end equals its
        start describes a valid single-day freeze."

        Design: Corner/validations/freeze_window_inverted_range_rejected
        """
        issuer = create_issuer(name="Mu Freeze", cusip="000000036",
                               ticker="MFRZ")
        resp = api.create_freeze_window(
            issuer["id"],
            freeze_window_payload("2026-09-10T00:00:00Z", "2026-09-05T00:00:00Z",
                                  "inverted"),
            officer_headers(issuer),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


class TestInquiryCycle:
    def test_inquiry_followup_reopen_cycle(self, api):
        """PRD §3.8: "An `ANSWERED` inquiry can be claimed again — the
        follow-up reopen cycle returns it `ANSWERED` → `IN_REVIEW` under the
        new claimer"
        PRD §3.8: "A `ServiceAgent` claiming an inquiry moves it `OPEN` →
        `IN_REVIEW` and records their identifier in `claimed_by_agent_id`."
        PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource"

        Design: Corner/state_machines/inquiry_followup_reopen_cycle
        """
        account = create_account(holder_name="Inquiry Ivy", postal_code="74108",
                                 tax_id="252-12-1212")
        inquiry = create_inquiry(account["id"], "EMAIL",
                                 "where is my dividend")
        claim_inquiry(inquiry["id"], agent_id="agent_1")
        answered = answer_inquiry(inquiry["id"], "mailed 2026-08-03",
                                  agent_id="agent_1")
        assert answered["status"] == "ANSWERED"

        reclaimed = claim_inquiry(inquiry["id"], agent_id="agent_2")
        assert reclaimed["status"] == "IN_REVIEW", "ANSWERED -> IN_REVIEW follow-up"
        assert reclaimed["claimed_by_agent_id"] == "agent_2"
        assert reclaimed["version"] == 4, "create, claim, answer, re-claim"

    def test_inquiry_answer_by_other_agent_denied(self, api):
        """PRD §3.8: "Only the claiming agent may answer: the answer call
        requires `X-User-ID` to equal the inquiry's `claimed_by_agent_id`, and
        a different agent's attempt is refused with
        `ERR_INQUIRY_CLAIMED_BY_OTHER`."

        Design: Corner/rbac/inquiry_answer_by_other_agent_denied
        """
        account = create_account(holder_name="Inquiry Ivan", postal_code="74133",
                                 tax_id="542-12-1212")
        inquiry = create_inquiry(account["id"], "PHONE", "statement copy")
        claim_inquiry(inquiry["id"], agent_id="agent_1")

        resp = api.answer_inquiry(inquiry["id"], {"answer_text": "impostor"},
                                  make_service_agent_headers("agent_2"))
        validate_error(resp, ApiErrorId.ERR_INQUIRY_CLAIMED_BY_OTHER)
        fresh = get_inquiry(inquiry["id"])
        assert fresh["status"] == "IN_REVIEW"
        assert fresh["claimed_by_agent_id"] == "agent_1"


class TestPagination:
    def test_inquiries_pagination_limit_offset(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10 when omitted, accepts a minimum of 1, and is clamped
        at a maximum of 100. The `offset` parameter specifies how many items to
        skip and defaults to 0."
        PRD §2.3: "Paginated list responses carry the fields `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope"

        Design: Corner/endpoints/inquiries_pagination_limit_offset
        """
        account = create_account(holder_name="Page Paul", postal_code="74127",
                                 tax_id="482-12-1212")
        ids = set()
        for channel, subject in (("EMAIL", "q1"), ("PHONE", "q2"),
                                 ("MAIL", "q3")):
            ids.add(create_inquiry(account["id"], channel, subject)["id"])

        page1, meta1 = validate_paginated(api.list_inquiries(
            SERVICE, {"account_id": account["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_inquiries(
            SERVICE, {"account_id": account["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        seen = {row["id"] for row in page1} | {row["id"] for row in page2}
        assert seen == ids, "the two pages are disjoint and cover all three"


class TestAuditTrail:
    def test_audit_trail_records_full_transition_chain(self, api):
        """PRD §2.9: "Every mutation in the system appends an `AuditEvent` to a
        hash-chained, append-only log."
        PRD §2.9: "The `from_state` records the resource's state before the
        transition — left empty for creations — and `to_state` records the
        state after."
        PRD §2.9: "`prev_entry_hash` is the SHA-256 of the previous event in
        the chain, or the literal value `GENESIS` for the first entry, and
        `entry_hash` is the SHA-256 computed over `prev_entry_hash` together
        with the event's canonical fields"
        PRD §3.3: "the creation is audited as `transfer.create`", "the
        verification is audited as `transfer.medallion_verified`", "the
        settlement is audited as `transfer.settle`."

        Design: Corner/cross_cutting_layers/audit_trail_records_full_transition_chain
        """
        ctx = setup_approved_transfer(share_quantity=10)
        settle_transfer(ctx["transfer"]["id"])
        tid = ctx["transfer"]["id"]

        events, _ = validate_paginated(api.list_audit_events(
            COMPLIANCE, {"entity_type": "TransferRequest", "entity_id": tid}))
        assert len(events) == 4, (
            "create, medallion verification, approval, and settlement each "
            "append one event for the transfer"
        )
        actions = [e["action"] for e in events]
        assert actions[0] == "transfer.create"
        assert actions[-1] == "transfer.settle"
        assert "transfer.medallion_verified" in actions

        create_event = events[0]
        assert create_event["from_state"] in (None, ""), "empty for creations"
        settle_event = next(e for e in events if e["action"] == "transfer.settle")
        assert settle_event["from_state"] == "APPROVED"
        assert settle_event["to_state"] == "SETTLED"
        assert settle_event["actor_role"] == "TransferSupervisor"

        # The unfiltered chain links every entry to its predecessor.
        all_events, _ = validate_paginated(api.list_audit_events(
            COMPLIANCE, {"limit": 100}))
        assert all_events[0]["prev_entry_hash"] == "GENESIS"
        for prev, cur in zip(all_events, all_events[1:]):
            assert cur["prev_entry_hash"] == prev["entry_hash"], (
                "each entry chains to its predecessor's hash"
            )


class TestClockIdempotence:
    def test_clock_set_is_idempotent_for_passed_transitions(self, api):
        """PRD §2.4: "Each time the clock is set, the server evaluates every
        time-gated system transition at the new instant"
        PRD §3.1: "when the clock reaches the `start_date` the window moves
        `SCHEDULED` → `ACTIVE`, and once the clock passes the `end_date` it
        moves `ACTIVE` → `EXPIRED` and never blocks settlement again."
        PRD §3.5: "When the logical clock reaches a `DECLARED` declaration's
        `record_date`, the declaration moves `DECLARED` → `ACCRUED`"

        Design: Corner/cross_cutting_layers/clock_set_is_idempotent_for_passed_transitions
        """
        issuer = create_issuer(name="Kappa Clock", cusip="000000053",
                               ticker="KCLK", shares_outstanding=50)
        account = create_account(holder_name="Clock Cleo", postal_code="74139",
                                 tax_id="602-12-1212", tin_status="CERTIFIED")
        seed_position(account["id"], issuer["id"], 50)
        declaration = create_declaration(issuer)
        create_freeze_window(issuer, "2026-08-01T00:00:00Z",
                             "2026-12-31T00:00:00Z", "long freeze")

        set_clock("2026-09-05T00:00:00Z")
        set_clock("2026-09-05T00:00:00Z")  # same instant again

        data, meta = validate_paginated(api.list_dividend_payments(
            ADMIN, {"declaration_id": declaration["id"]}))
        assert meta["total_count"] == 1, (
            "accrual fired exactly once across the two identical clock sets"
        )
        assert get_declaration(declaration["id"])["status"] == "ACCRUED", (
            "payable_date 2026-09-15 not yet reached"
        )

        windows, wmeta = validate_paginated(api.list_freeze_windows(
            officer_headers(issuer), {"issuer_id": issuer["id"]}))
        assert wmeta["total_count"] == 1, "the window remains a single row"
        assert windows[0]["status"] == "ACTIVE"
