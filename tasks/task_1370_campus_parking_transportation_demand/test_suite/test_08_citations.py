"""Citation issuance, fine schedule, payment, and the appeals cycle."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    appeal_citation,
    create_closure,
    create_lot,
    create_patron,
    decide_appeal,
    get_allocation,
    get_citation,
    get_patron,
    get_permit,
    issue_and_pay_citations,
    issue_citation,
    make_appeals_headers,
    make_commuter_headers,
    make_officer_headers,
    pay_citation,
    purchase_permit,
    set_clock,
    setup_patron_with_permit,
    validate_error,
    validate_success,
)


def _violation_lot():
    return create_lot(lot_code="LB", name="Lot B", zone="REMOTE")


class TestRepeatEscalationDivergence:
    """P has two PAID NO_VALID_PERMIT citations in the trailing 365 days;
    Q has none. The third identical citation prices differently."""

    def _setup(self):
        p_ctx = setup_patron_with_permit(name="P", plate="P111", campus_role="STAFF",
                                         eligible_roles=["STUDENT", "STAFF", "FACULTY"],
                                         quota=10)
        q = create_patron(full_name="Q", campus_role="STAFF", residency="OFF_CAMPUS",
                          primary_commute_mode="DRIVE_ALONE")
        purchase_permit(q["id"], p_ctx["allocation"]["id"], "Q222")
        lot_b = _violation_lot()
        issue_and_pay_citations(lot_b["id"], "P111", p_ctx["patron"]["id"], 2)
        return p_ctx, q, lot_b

    def test_repeat_offender_fine_escalated(self, api):
        """PRD §3.6.1: "`repeat_count` is the number of the patron's citations
        with status `PAID` whose `issued_at` is at or after the current
        logical time minus `365` days — a citation exactly `365` days old
        still counts." and "If `repeat_count` is at least `2`, the escalated
        base is the schedule amount multiplied by `1.5`, rounded half-up to
        the nearest integer cent."

        Design: Difficulty/dual_variant_calc/citation_fine_repeat_escalation_divergence
        """
        p_ctx, _, lot_b = self._setup()
        citation = issue_citation(lot_b["id"], "P111", "NO_VALID_PERMIT")
        # repeat_count == 2 meets the threshold -> round_half_up(7500 * 1.5).
        assert citation["fine_amount_cents"] == 11250, (
            f"escalated fine must be 11250, got {citation['fine_amount_cents']}"
        )

    def test_clean_history_fine_standard_schedule(self, api):
        """PRD §3.6.1: "The base is the violation's schedule amount:
        `NO_VALID_PERMIT` is `7500` cents, `EXPIRED_PERMIT` is `5000` cents,
        `WRONG_ZONE` is `4000` cents, `CLOSED_LOT` is `6000` cents." and "A
        patron with two prior paid citations within the trailing year
        therefore pays a larger fine than a first-time offender for an
        identical violation on an identical lot at an identical time."

        Design: Difficulty/dual_variant_calc/citation_fine_repeat_escalation_divergence
        """
        p_ctx, q, lot_b = self._setup()
        p_third = issue_citation(lot_b["id"], "P111", "NO_VALID_PERMIT")
        q_first = issue_citation(lot_b["id"], "Q222", "NO_VALID_PERMIT")
        assert q_first["fine_amount_cents"] == 7500, (
            f"repeat_count 0 keeps the standard 7500, got {q_first['fine_amount_cents']}"
        )
        assert p_third["fine_amount_cents"] != q_first["fine_amount_cents"], (
            "identical violation/lot/time must price differently on patron history"
        )


class TestRepeatWindowBoundary:
    def test_repeat_window_365_day_boundary(self, api):
        """PRD §3.6.1: "`repeat_count` is the number of the patron's citations
        with status `PAID` whose `issued_at` is at or after the current
        logical time minus `365` days — a citation exactly `365` days old
        still counts."
        PRD §3.11: "An admin-only test-driving capability advances the
        server's logical clock by submitting `to_iso8601`. The endpoint
        returns the new `current_utc`."

        Design: Corner/calculations/repeat_window_365_day_boundary
        """
        a_ctx = setup_patron_with_permit(name="A", plate="A111", campus_role="STAFF",
                                         quota=10)
        b = create_patron(full_name="B", campus_role="STAFF", residency="OFF_CAMPUS",
                          primary_commute_mode="DRIVE_ALONE")
        purchase_permit(b["id"], a_ctx["allocation"]["id"], "B111")
        lot_b = _violation_lot()

        # B's older citation: 2025-08-19 (366 days before the final reading).
        set_clock("2025-08-19T00:00:00Z")
        cb1 = issue_citation(lot_b["id"], "B111", "NO_VALID_PERMIT")
        pay_citation(cb1["id"], b["id"])
        # A's older citation: 2025-08-20 (exactly 365 days before).
        set_clock("2025-08-20T00:00:00Z")
        ca1 = issue_citation(lot_b["id"], "A111", "NO_VALID_PERMIT")
        pay_citation(ca1["id"], a_ctx["patron"]["id"])
        # Both patrons pick up a second paid citation at 2026-08-01.
        set_clock("2026-08-01T00:00:00Z")
        ca2 = issue_citation(lot_b["id"], "A111", "NO_VALID_PERMIT")
        pay_citation(ca2["id"], a_ctx["patron"]["id"])
        cb2 = issue_citation(lot_b["id"], "B111", "NO_VALID_PERMIT")
        pay_citation(cb2["id"], b["id"])

        set_clock("2026-08-20T00:00:00Z")
        ca3 = issue_citation(lot_b["id"], "A111", "NO_VALID_PERMIT")
        cb3 = issue_citation(lot_b["id"], "B111", "NO_VALID_PERMIT")
        assert ca3["fine_amount_cents"] == 11250, (
            f"A's exactly-365-day-old citation still counts -> escalated 11250, "
            f"got {ca3['fine_amount_cents']}"
        )
        assert cb3["fine_amount_cents"] == 7500, (
            f"B's 366-day-old citation falls outside -> standard 7500, "
            f"got {cb3['fine_amount_cents']}"
        )


class TestEventDaySurcharge:
    def test_event_day_surcharge_during_active_event(self, api, admin_headers):
        """PRD §3.6.1: "If the cited lot has a closure with reason `EVENT` and
        status `ACTIVE` whose `[starts_at, ends_at)` window contains the
        current logical time, add a flat `1500`-cent event surcharge;
        otherwise the surcharge is zero." and "`fine_amount_cents` is the
        escalated base plus the event surcharge."

        Design: Corner/calculations/event_day_surcharge_during_active_event
        """
        ctx = setup_patron_with_permit(name="E", plate="E111", campus_role="STAFF")
        lot_b = _violation_lot()
        closure = create_closure(
            lot_b["id"], reason="EVENT", event_name="GameDay", reserved_spaces=10,
            starts_at="2026-08-10T00:00:00Z", ends_at="2026-08-12T00:00:00Z",
        )
        api.activate_closure(closure["id"], admin_headers)
        set_clock("2026-08-11T00:00:00Z")

        fine_b = issue_citation(lot_b["id"], "E111", "NO_VALID_PERMIT")
        assert fine_b["fine_amount_cents"] == 9000, (
            f"7500 base + 1500 event surcharge = 9000, got {fine_b['fine_amount_cents']}"
        )
        fine_a = issue_citation(ctx["lot"]["id"], "E111", "WRONG_ZONE")
        assert fine_a["fine_amount_cents"] == 4000, (
            f"no active event on lot A -> plain WRONG_ZONE base 4000, "
            f"got {fine_a['fine_amount_cents']}"
        )


class TestAppealCycle:
    def _setup(self):
        ctx = setup_patron_with_permit(name="R", plate="R333", campus_role="STAFF")
        lot_b = _violation_lot()
        citation = issue_citation(lot_b["id"], "R333", "NO_VALID_PERMIT")
        return ctx, citation

    def test_appeal_excludes_fine_from_outstanding(self, api):
        """PRD §3.6.4: "On filing, the citation transitions to
        `UNDER_APPEAL`, `appeal_outcome` becomes `PENDING`, `appeal_reason` is
        recorded, and the fine is excluded from the patron's
        `outstanding_balance_cents` while under appeal — so
        `outstanding_balance_cents` decreases by `fine_amount_cents`,
        `standing` is recomputed, and `SUSPENDED` permits may return to
        `ACTIVE`."
        PRD §3.1: "A patron's `outstanding_balance_cents` is the sum of
        `fine_amount_cents` across all of that patron's citations whose status
        is exactly `ISSUED` — citations that are `UNDER_APPEAL`, `PAID`, or
        `VOIDED` are excluded."

        Design: Difficulty/non_linear_state_machine/citation_issue_appeal_upheld_cycle
        """
        ctx, citation = self._setup()
        patron_id = ctx["patron"]["id"]
        issued_patron = get_patron(patron_id)
        assert issued_patron["outstanding_balance_cents"] == 7500, (
            f"issuance adds the fine, got {issued_patron['outstanding_balance_cents']}"
        )

        appealed = appeal_citation(citation["id"], patron_id, "LPR misread plate")
        assert appealed["status"] == "UNDER_APPEAL"
        assert appealed["appeal_outcome"] == "PENDING"

        appealed_patron = get_patron(patron_id)
        assert appealed_patron["outstanding_balance_cents"] == 0, (
            f"UNDER_APPEAL excludes the fine, got {appealed_patron['outstanding_balance_cents']}"
        )

    def test_upheld_decision_restores_fine_and_balance(self, api):
        """PRD §3.6.4: "**UPHELD** — the citation returns to `ISSUED` with
        `fine_amount_cents` unchanged. `appeal_outcome` becomes `UPHELD`,
        `appeal_decided_by` records the decider, and the patron's
        `outstanding_balance_cents` increases by the (unchanged)
        `fine_amount_cents`."

        Design: Difficulty/non_linear_state_machine/citation_issue_appeal_upheld_cycle
        """
        ctx, citation = self._setup()
        patron_id = ctx["patron"]["id"]
        appeal_citation(citation["id"], patron_id, "LPR misread plate")
        decided = decide_appeal(citation["id"], "UPHELD", officer_id="off-9")
        assert decided["status"] == "ISSUED", (
            f"UPHELD returns the citation to ISSUED, got {decided['status']}"
        )
        assert decided["appeal_outcome"] == "UPHELD"
        assert decided["appeal_decided_by"] == "off-9"
        assert decided["fine_amount_cents"] == 7500, (
            f"UPHELD leaves the fine unchanged, got {decided['fine_amount_cents']}"
        )
        final_patron = get_patron(patron_id)
        assert final_patron["outstanding_balance_cents"] == 7500, (
            f"the cycle completes with no balance drift, "
            f"got {final_patron['outstanding_balance_cents']}"
        )


class TestVoidRestoresBalance:
    def _setup(self):
        ctx = setup_patron_with_permit(name="H", plate="H999", campus_role="STAFF")
        lot_b = _violation_lot()
        return ctx, lot_b

    def test_issue_appeal_void_restores_outstanding_balance(self, api):
        """PRD §3.6.4: "**VOIDED** — the citation transitions to `VOIDED`
        (terminal), `appeal_outcome` becomes `VOIDED`, and there is no balance
        effect (the fine was already excluded while under appeal)."
        PRD §3.1: "A patron's `outstanding_balance_cents` is the sum of
        `fine_amount_cents` across all of that patron's citations whose status
        is exactly `ISSUED` — citations that are `UNDER_APPEAL`, `PAID`, or
        `VOIDED` are excluded."

        Design: Difficulty/compensating_invariant/issue_appeal_void_restores_outstanding_balance
        """
        ctx, lot_b = self._setup()
        patron_id = ctx["patron"]["id"]
        pre = get_patron(patron_id)
        assert pre["outstanding_balance_cents"] == 0

        citation = issue_citation(lot_b["id"], "H999", "NO_VALID_PERMIT")
        issued = get_patron(patron_id)
        assert issued["outstanding_balance_cents"] == 7500

        appeal_citation(citation["id"], patron_id, "Permit was valid; LPR camera fault")
        decide_appeal(citation["id"], "VOIDED", officer_id="off-9")

        final = get_patron(patron_id)
        assert final["outstanding_balance_cents"] == 0, (
            f"issue/appeal/void must conserve the balance, "
            f"got {final['outstanding_balance_cents']}"
        )
        assert final["standing"] == "GOOD_STANDING"

    def test_voided_citation_terminal_outcome(self, api):
        """PRD §3.6.4: "**VOIDED** — the citation transitions to `VOIDED`
        (terminal), `appeal_outcome` becomes `VOIDED`, and there is no balance
        effect (the fine was already excluded while under appeal)."

        Design: Difficulty/compensating_invariant/issue_appeal_void_restores_outstanding_balance
        """
        ctx, lot_b = self._setup()
        patron_id = ctx["patron"]["id"]
        citation = issue_citation(lot_b["id"], "H999", "NO_VALID_PERMIT")
        appeal_citation(citation["id"], patron_id, "Permit was valid; LPR camera fault")
        decided = decide_appeal(citation["id"], "VOIDED", officer_id="off-9")
        assert decided["status"] == "VOIDED"
        assert decided["appeal_outcome"] == "VOIDED"
        assert decided["appeal_decided_by"] == "off-9"


class TestAppealStateGate:
    def _setup_paid(self):
        ctx = setup_patron_with_permit(name="W", plate="W999", campus_role="STAFF")
        lot_b = _violation_lot()
        citation = issue_citation(lot_b["id"], "W999", "WRONG_ZONE")
        pay_citation(citation["id"], ctx["patron"]["id"])
        return ctx, citation

    def test_appeal_paid_citation_rejected(self, api):
        """PRD §3.6.4: "A `Commuter` files an appeal against an `ISSUED`
        citation they own by supplying a `reason`. The citation must be
        `ISSUED` and its `appeal_outcome` must be `NONE` — a citation may be
        appealed at most once, and a repeat attempt is rejected with
        `ERR_APPEAL_ALREADY_EXISTS` (HTTP 409)."
        PRD §3.6.3: "A citation not in `ISSUED` status is rejected with
        `ERR_CITATION_NOT_ISSUED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/appeal_requires_citation_issued
        """
        ctx, citation = self._setup_paid()
        resp = api.appeal_citation(
            citation["id"], {"reason": "I already paid, but the signage was wrong"},
            make_commuter_headers(ctx["patron"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CITATION_NOT_ISSUED, 409)

    def test_paid_citation_state_untouched_by_rejected_appeal(self, api):
        """PRD §3.6.3: "The citation transitions to `PAID` (terminal), the
        patron's `outstanding_balance_cents` decreases by `fine_amount_cents`,
        `standing` is recomputed, and if `standing` flips back to
        `GOOD_STANDING` any `SUSPENDED` permits return to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/appeal_requires_citation_issued
        """
        ctx, citation = self._setup_paid()
        api.appeal_citation(
            citation["id"], {"reason": "second try"},
            make_commuter_headers(ctx["patron"]["id"]),
        )
        after = get_citation(citation["id"])
        assert after["status"] == "PAID", (
            f"no appeal may be recorded against a terminal citation, got {after['status']}"
        )
        assert after["appeal_outcome"] == "NONE"


class TestVoidedTerminalLockdown:
    def test_citation_voided_rejects_pay_and_appeal(self, api):
        """PRD §3.6.3: "A citation not in `ISSUED` status is rejected with
        `ERR_CITATION_NOT_ISSUED` (HTTP 409)."
        PRD §3.6.4: "The citation must be `ISSUED` and its `appeal_outcome`
        must be `NONE` — a citation may be appealed at most once, and a repeat
        attempt is rejected with `ERR_APPEAL_ALREADY_EXISTS` (HTTP 409)."
        (The state tier precedes the uniqueness tier per PRD §2.8, so both
        calls on a VOIDED citation fail with ERR_CITATION_NOT_ISSUED.)

        Design: Corner/state_machines/citation_voided_rejects_pay_and_appeal
        """
        ctx = setup_patron_with_permit(name="V", plate="V555", campus_role="STAFF")
        lot_b = _violation_lot()
        citation = issue_citation(lot_b["id"], "V555", "NO_VALID_PERMIT")
        appeal_citation(citation["id"], ctx["patron"]["id"], "Camera fault")
        decide_appeal(citation["id"], "VOIDED", officer_id="off-9")

        pay = api.pay_citation(citation["id"], make_commuter_headers(ctx["patron"]["id"]))
        validate_error(pay, ApiErrorId.ERR_CITATION_NOT_ISSUED, 409)
        appeal = api.appeal_citation(
            citation["id"], {"reason": "second try"},
            make_commuter_headers(ctx["patron"]["id"]),
        )
        validate_error(appeal, ApiErrorId.ERR_CITATION_NOT_ISSUED, 409)


class TestAppealUniqueness:
    def test_second_appeal_rejected_after_upheld(self, api):
        """PRD §3.6.4: "A `Commuter` files an appeal against an `ISSUED`
        citation they own by supplying a `reason`. The citation must be
        `ISSUED` and its `appeal_outcome` must be `NONE` — a citation may be
        appealed at most once, and a repeat attempt is rejected with
        `ERR_APPEAL_ALREADY_EXISTS` (HTTP 409)."

        Design: Corner/validations/second_appeal_rejected_after_upheld
        """
        ctx = setup_patron_with_permit(name="A", plate="A222", campus_role="STAFF")
        lot_b = _violation_lot()
        citation = issue_citation(lot_b["id"], "A222", "WRONG_ZONE")
        appeal_citation(citation["id"], ctx["patron"]["id"], "signage unclear")
        decide_appeal(citation["id"], "UPHELD", officer_id="off-9")
        # Citation is ISSUED again (state check passes) but already appealed.
        resp = api.appeal_citation(
            citation["id"], {"reason": "new evidence"},
            make_commuter_headers(ctx["patron"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_EXISTS, 409)


class TestSegregationOfDuties:
    def test_sod_decide_own_citation_rejected(self, api):
        """PRD §2.1: "Segregation of duties requires that an `AppealsOfficer`
        may not decide an appeal on a citation whose `issued_by_officer_id`
        equals their `X-User-ID`; violations are rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/sod_decide_own_citation_rejected
        """
        ctx = setup_patron_with_permit(name="S", plate="S777", campus_role="STAFF")
        lot_b = _violation_lot()
        citation = issue_citation(lot_b["id"], "S777", "NO_VALID_PERMIT",
                                  officer_id="off-7")
        appeal_citation(citation["id"], ctx["patron"]["id"], "not my car")

        resp = api.decide_appeal(
            citation["id"], {"outcome": "UPHELD"}, make_appeals_headers("off-7")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        ok = api.decide_appeal(
            citation["id"], {"outcome": "UPHELD"}, make_appeals_headers("off-9")
        )
        decided = validate_success(ok, 200)
        assert decided["status"] == "ISSUED"
        assert decided["appeal_decided_by"] == "off-9", (
            f"the independent officer's decision is recorded, "
            f"got {decided['appeal_decided_by']}"
        )


class TestReducedDecision:
    def test_appeal_reduced_recomputes_fine_and_balance(self, api):
        """PRD §3.6.4: "**REDUCED** — `reduction_pct` must be present and in
        the range `1` through `99`; otherwise the request is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400). The new `fine_amount_cents` is the
        current `fine_amount_cents` multiplied by `(100 - reduction_pct)` and
        divided by `100`, rounded half-up to the nearest integer cent. The
        citation returns to `ISSUED`, `appeal_outcome` becomes `REDUCED`, and
        the patron's `outstanding_balance_cents` increases by the new
        (reduced) `fine_amount_cents`."

        Design: Corner/validations/appeal_reduced_recomputes_fine_and_balance
        """
        ctx = setup_patron_with_permit(name="R", plate="R555", campus_role="STAFF")
        lot_b = _violation_lot()
        citation = issue_citation(lot_b["id"], "R555", "NO_VALID_PERMIT")
        appeal_citation(citation["id"], ctx["patron"]["id"],
                        "first offense, signage faded")
        decided = decide_appeal(citation["id"], "REDUCED", officer_id="off-9",
                                reduction_pct=20)
        assert decided["status"] == "ISSUED"
        assert decided["appeal_outcome"] == "REDUCED"
        # round_half_up(7500 * 80 / 100) = 6000
        assert decided["fine_amount_cents"] == 6000, (
            f"reduced fine must be 6000, got {decided['fine_amount_cents']}"
        )
        patron = get_patron(ctx["patron"]["id"])
        assert patron["outstanding_balance_cents"] == 6000, (
            f"the reduced fine re-enters outstanding, "
            f"got {patron['outstanding_balance_cents']}"
        )


class TestPlateResolution:
    def test_unregistered_plate_citation_rejected(self, api, admin_headers):
        """PRD §3.6: "The plate must resolve to at least one existing permit —
        the citation binds to the permit with that `plate_number` having the
        latest `created_at`, regardless of that permit's status, and a plate
        that matches no permit at all is rejected with
        `ERR_PLATE_NOT_REGISTERED` (HTTP 422)."

        Design: Corner/validations/unregistered_plate_citation_rejected
        """
        lot = create_lot(lot_code="LU", name="Lot U")
        resp = api.create_citation(
            {"lot_id": lot["id"], "plate_number": "GHOST1",
             "violation_type": "NO_VALID_PERMIT"},
            make_officer_headers("off-1"),
        )
        validate_error(resp, ApiErrorId.ERR_PLATE_NOT_REGISTERED, 422)


class TestStandingSuspensionCascade:
    """Two prior paid citations make the third issue escalate to 11250, which
    alone crosses the 10000-cent block threshold."""

    def _setup(self):
        ctx = setup_patron_with_permit(name="P", plate="S555", campus_role="STAFF",
                                       quota=5)
        lot_b = _violation_lot()
        issue_and_pay_citations(lot_b["id"], "S555", ctx["patron"]["id"], 2)
        return ctx, lot_b

    def test_escalated_citation_blocks_patron_standing(self, api):
        """PRD §3.1: "`standing` flips to `BLOCKED` whenever
        `outstanding_balance_cents` reaches or exceeds `10000` cents, and
        returns to `GOOD_STANDING` when the balance falls back below that
        threshold."
        PRD §3.6.1: "If `repeat_count` is at least `2`, the escalated base is
        the schedule amount multiplied by `1.5`, rounded half-up to the
        nearest integer cent."
        PRD §3.6.2: "The patron's `outstanding_balance_cents` increases by
        `fine_amount_cents`, `standing` is recomputed, and if `standing` flips
        to `BLOCKED` the patron's `ACTIVE` permits flip to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/citation_issue_standing_suspension_cascade
        """
        ctx, lot_b = self._setup()
        citation = issue_citation(lot_b["id"], "S555", "NO_VALID_PERMIT")
        assert citation["fine_amount_cents"] == 11250, (
            f"repeat escalation, got {citation['fine_amount_cents']}"
        )
        patron = get_patron(ctx["patron"]["id"])
        assert patron["outstanding_balance_cents"] == 11250
        assert patron["standing"] == "BLOCKED", (
            f"11250 >= 10000 must flip standing to BLOCKED, got {patron['standing']}"
        )

    def test_blocked_standing_suspends_active_permit(self, api):
        """PRD §3.1: "When standing flips to `BLOCKED`, every `ACTIVE` permit
        the patron holds flips to `SUSPENDED`; when standing flips back to
        `GOOD_STANDING`, those `SUSPENDED` permits return to `ACTIVE`. A
        `SUSPENDED` permit still occupies its allocation seat —
        `allocated_count` does not change on suspension — but it is not valid
        for parking."

        Design: Difficulty/transitive_cascade/citation_issue_standing_suspension_cascade
        """
        ctx, lot_b = self._setup()
        issue_citation(lot_b["id"], "S555", "NO_VALID_PERMIT")  # 11250, unpaid
        permit = get_permit(ctx["permit"]["id"])
        assert permit["status"] == "SUSPENDED", (
            f"the standing flip must suspend the ACTIVE permit, got {permit['status']}"
        )
        allocation = get_allocation(ctx["allocation"]["id"])
        assert allocation["allocated_count"] == 1, (
            "a SUSPENDED permit still occupies its seat"
        )


class TestDefaultClockStamp:
    def test_default_clock_stamps_citation_issued_at(self, api):
        """PRD §2.5: "Before any clock-set call, the logical clock is exactly
        `2026-08-01T00:00:00Z`. The server MUST NOT fall back to wall-clock
        time at any point."
        PRD §3.6.2: "On issuance the citation is created with status `ISSUED`,
        `appeal_outcome` of `NONE`, `issued_by_officer_id` set to the caller's
        `X-User-ID`, and `issued_at` set to the current logical time."

        Design: Corner/endpoints/default_clock_stamps_citation_issued_at
        """
        ctx = setup_patron_with_permit(name="D", plate="D111", campus_role="STAFF")
        lot_b = _violation_lot()
        citation = issue_citation(lot_b["id"], "D111", "WRONG_ZONE")
        issued_at = datetime.fromisoformat(citation["issued_at"].replace("Z", "+00:00"))
        assert issued_at == datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc), (
            f"issued_at must come from the fixed startup logical clock, "
            f"got {citation['issued_at']}"
        )
