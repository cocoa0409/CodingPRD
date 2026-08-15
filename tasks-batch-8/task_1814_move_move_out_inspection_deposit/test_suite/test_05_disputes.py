"""Dispute workflow: branching paths (counter+accept vs escalate), dispute
window boundary, court resolution with and without penalty, and dispute
validation errors."""
import test_helpers as th
from test_helpers import (
    ApiErrorId,
    api_client,
    create_dispute_payload,
    create_statement_for,
    get_disbursement,
    get_dispute,
    get_statement,
    get_success_data,
    get_tenancy,
    make_manager_admin_headers,
    make_property_manager_headers,
    make_tenant_headers,
    setup_dispute_on_statement,
    setup_escalated_dispute,
    setup_issued_statement_with_damage,
    setup_issued_with_cleaning,
    setup_settled_tenancy,
    setup_vacated_with_statement,
    validate_error,
    validate_success,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()


def _list_disbursements(tenancy_id):
    resp = api_client.list_disbursements(PM, params={"tenancy_id": tenancy_id, "limit": 100})
    data = get_success_data(resp)
    return data if isinstance(data, list) else data.get("data", [])


class TestDisputeBranchingPaths:
    def _two_open_disputes(self):
        """Two identical tenancies, each with an issued timely statement
        (refund_due 149,337c) and an OPEN dispute of 20,000c. Jurisdiction
        codes must differ because codes are unique (PRD §2.10)."""
        ctx_a = setup_dispute_on_statement(
            disputed_amount=20_000, reason="paint wear",
            jurisdiction_overrides={"code": "CA-ACT"})
        ctx_b = setup_dispute_on_statement(
            disputed_amount=20_000, reason="paint wear",
            jurisdiction_overrides={"code": "CA-AC2"},
            tenancy_overrides={"tenant_display_name": "T B"})
        return ctx_a, ctx_b

    def test_counter_then_accept_releases_remainder(self):
        """PRD §3.6: "Accepting the counter — an action only the owning
        `Tenant` may perform, with the identity check against the dispute's
        tenancy enforced as `ERR_FORBIDDEN_FOR_ROLE` — closes the dispute as
        `CLOSED_AGREED`, releases the un-kept remainder (the disputed amount
        minus the counter amount) into the statement's `released_cents`, and
        returns the statement to `ISSUED` with `refund_due_cents` recomputed
        as the deposit plus interest minus the deduction total plus the
        released amount."

        Disputed 20,000, counter 12,000 => released 8,000; refund_due
        149,337 + 8,000 = 157,337.

        Design: Difficulty/non_linear_state_machine/dispute_branching_paths_divergent_effects
        """
        ctx_a, _ctx_b = self._two_open_disputes()
        ten_a = ctx_a["tenancy"]
        disp_a = ctx_a["dispute"]
        validate_success(api_client.counter_dispute(
            disp_a["id"], {"counter_amount_cents": 12_000}, PM))
        validate_success(api_client.close_agreed_dispute(
            disp_a["id"], make_tenant_headers(ten_a["id"])))
        assert get_dispute(disp_a["id"])["status"] == "CLOSED_AGREED"
        stmt = get_statement(ctx_a["statement"]["id"])
        assert stmt["status"] == "ISSUED"
        assert stmt["released_cents"] == 8_000
        assert stmt["refund_due_cents"] == 157_337, (
            f"149337 + 8000 = 157337, got {stmt['refund_due_cents']}"
        )

    def test_escalate_releases_nothing_and_computes_exposure(self):
        """PRD §3.6: "Escalating instead — likewise restricted to the owning
        tenant, and available from either `OPEN` or `MANAGER_COUNTERED` —
        moves the dispute to `ESCALATED_SMALL_CLAIMS` and computes the court
        exposure. The exposure base is the `disputed_amount_cents`; when the
        statement's `late` flag is set, the base is first multiplied by the
        jurisdiction's `bad_faith_multiplier`; the dispute's `exposure_cents`
        is then the smaller of that base and the jurisdiction's
        `small_claims_cap_cents`."

        Not late => exposure == disputed 20,000c; the statement keeps
        released 0 and refund_due 149,337c.

        Design: Difficulty/non_linear_state_machine/dispute_branching_paths_divergent_effects
        """
        _ctx_a, ctx_b = self._two_open_disputes()
        ten_b = ctx_b["tenancy"]
        disp_b = ctx_b["dispute"]
        validate_success(api_client.escalate_dispute(
            disp_b["id"], make_tenant_headers(ten_b["id"])))
        disp_after = get_dispute(disp_b["id"])
        assert disp_after["status"] == "ESCALATED_SMALL_CLAIMS"
        assert disp_after["exposure_cents"] == 20_000, (
            f"timely statement: no multiplier, expected 20000, "
            f"got {disp_after['exposure_cents']}"
        )
        stmt = get_statement(ctx_b["statement"]["id"])
        assert stmt["released_cents"] == 0
        assert stmt["refund_due_cents"] == 149_337


class TestDisputeWindowBoundary:
    def _two_issued_statements(self):
        ctx_a = setup_issued_statement_with_damage(
            jurisdiction_overrides={"code": "CA-ACT"},
            tenancy_overrides={"tenant_display_name": "T A"})
        ctx_b = setup_issued_statement_with_damage(
            jurisdiction_overrides={"code": "CA-AC2"},
            tenancy_overrides={"tenant_display_name": "T B"})
        return ctx_a, ctx_b

    def test_last_day_of_window_allowed(self):
        """PRD §3.6: "the dispute must arrive within the statutory window: the
        creation date must fall on or before the statement's issuance date
        plus the jurisdiction's `dispute_window_days`, or the attempt is
        rejected with `ERR_DISPUTE_WINDOW_CLOSED`."

        Issued 2026-08-10, window 30d => last day 2026-09-09 inclusive; the
        dispute is created (201).

        Design: Corner/validations/dispute_window_last_day_allowed_next_day_closed
        """
        ctx_a, _ctx_b = self._two_issued_statements()
        api_client.set_clock({"to_iso8601": "2026-09-09T23:00:00Z"}, ADMIN)
        resp = api_client.create_dispute(
            create_dispute_payload(statement_id=ctx_a["statement"]["id"],
                                   disputed_amount_cents=5_000, reason="last day"),
            make_tenant_headers(ctx_a["tenancy"]["id"]),
        )
        disp = validate_success(resp, expected_status=201)
        assert disp["status"] == "OPEN"

    def test_next_day_after_window_closed(self):
        """PRD §3.6: "the dispute must arrive within the statutory window: the
        creation date must fall on or before the statement's issuance date
        plus the jurisdiction's `dispute_window_days`, or the attempt is
        rejected with `ERR_DISPUTE_WINDOW_CLOSED`."

        The identical dispute on 2026-09-10 (one day past) fails.

        Design: Corner/validations/dispute_window_last_day_allowed_next_day_closed
        """
        _ctx_a, ctx_b = self._two_issued_statements()
        api_client.set_clock({"to_iso8601": "2026-09-10T00:00:00Z"}, ADMIN)
        resp = api_client.create_dispute(
            create_dispute_payload(statement_id=ctx_b["statement"]["id"],
                                   disputed_amount_cents=5_000, reason="one day late"),
            make_tenant_headers(ctx_b["tenancy"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)


class TestCourtResolution:
    def test_timely_statement_releases_award_without_penalty(self):
        """PRD §3.6: "Resolution moves the dispute from
        `ESCALATED_SMALL_CLAIMS` to `COURT_RESOLVED`, adds the awarded amount
        into the statement's `released_cents`, returns the statement to
        `ISSUED`, and recomputes `refund_due_cents`." and "whenever that
        penalty is greater than zero the system automatically creates a
        `PENALTY` disbursement for it in `SENT` status."

        Award 10,000 of 20,000 disputed on a timely statement: released 10,000,
        refund_due 159,337, and NO penalty disbursement exists.

        Design: Corner/state_machines/statement_returns_to_issued_on_court_resolved
        """
        ctx = setup_escalated_dispute(disputed_amount=20_000)
        ten = ctx["tenancy"]
        validate_success(api_client.resolve_court_dispute(
            ctx["dispute"]["id"], {"awarded_amount_cents": 10_000}, PM))
        assert get_dispute(ctx["dispute"]["id"])["status"] == "COURT_RESOLVED"
        stmt = get_statement(ctx["statement"]["id"])
        assert stmt["status"] == "ISSUED"
        assert stmt["released_cents"] == 10_000
        assert stmt["refund_due_cents"] == 159_337, (
            f"149337 + 10000 = 159337, got {stmt['refund_due_cents']}"
        )
        penalties = [d for d in _list_disbursements(ten["id"]) if d["kind"] == "PENALTY"]
        assert penalties == [], f"no penalty may be created when not late: {penalties}"

    def test_late_statement_creates_penalty_disbursement(self):
        """PRD §3.6: "When the statement was late, resolution additionally
        manufactures the penalty: the tenant's total recovery is the smaller
        of the dispute's `exposure_cents` and the awarded amount multiplied by
        the `bad_faith_multiplier` (or simply the awarded amount when the
        statement was not late); the recovery minus the awarded amount is the
        penalty portion, and whenever that penalty is greater than zero the
        system automatically creates a `PENALTY` disbursement for it in `SENT`
        status."

        Late statement, dispute 40,000 => exposure 80,000 (x2). Award 30,000
        => recovery min(80,000, 60,000) = 60,000 => penalty 30,000 SENT;
        released 30,000 and refund_due 141,337 + 30,000 = 171,337.

        Design: Corner/calculations/court_resolution_penalty_on_late_statement
        """
        ctx = setup_vacated_with_statement()  # paint 60,000; statement still DRAFT
        ten = ctx["tenancy"]
        get_success_data(api_client.create_deduction(
            {"tenancy_id": ten["id"], "source": "CLEANING",
             "description": "oven cleaning", "amount_cents": 8_000}, PM))
        # Issue LATE at 2026-08-23 (deadline was 2026-08-22).
        api_client.set_clock({"to_iso8601": "2026-08-23T00:00:00Z"}, ADMIN)
        validate_success(api_client.issue_statement(ctx["statement"]["id"], PM))
        stmt = get_statement(ctx["statement"]["id"])
        assert stmt["late"] is True

        resp = api_client.create_dispute(
            create_dispute_payload(statement_id=stmt["id"],
                                   disputed_amount_cents=40_000,
                                   reason="charges inflated"),
            make_tenant_headers(ten["id"]),
        )
        disp = get_success_data(resp)
        validate_success(api_client.escalate_dispute(
            disp["id"], make_tenant_headers(ten["id"])))
        assert get_dispute(disp["id"])["exposure_cents"] == 80_000

        validate_success(api_client.resolve_court_dispute(
            disp["id"], {"awarded_amount_cents": 30_000}, PM))
        assert get_dispute(disp["id"])["status"] == "COURT_RESOLVED"
        stmt_after = get_statement(stmt["id"])
        assert stmt_after["released_cents"] == 30_000
        assert stmt_after["refund_due_cents"] == 171_337, (
            f"141337 + 30000 = 171337, got {stmt_after['refund_due_cents']}"
        )
        penalties = [d for d in _list_disbursements(ten["id"]) if d["kind"] == "PENALTY"]
        assert len(penalties) == 1, f"expected one auto PENALTY, got {penalties}"
        assert penalties[0]["amount_cents"] == 30_000
        assert penalties[0]["status"] == "SENT"
        ten_after = get_tenancy(ten["id"])
        assert ten_after["penalty_paid_cents"] == 0
        assert ten_after["reserved_cents"] == 0, (
            "PENALTY disbursements bypass the balance reservation"
        )


class TestDisputeValidation:
    def test_dispute_zero_amount_rejected(self):
        """PRD §3.6: "The disputed amount must be at least one cent and no more
        than the statement's `deduction_total_cents`
        (`ERR_DISPUTE_AMOUNT_INVALID`)".

        disputed_amount_cents == 0 fails.

        Design: Corner/validations/dispute_zero_amount_rejected
        """
        ctx = setup_issued_statement_with_damage()
        resp = api_client.create_dispute(
            create_dispute_payload(statement_id=ctx["statement"]["id"],
                                   disputed_amount_cents=0, reason="nothing"),
            make_tenant_headers(ctx["tenancy"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_AMOUNT_INVALID)

    def test_second_dispute_while_open_rejected(self):
        """PRD §3.6: "at most one dispute per statement may sit in `OPEN`,
        `MANAGER_COUNTERED`, or `ESCALATED_SMALL_CLAIMS`
        (`ERR_DISPUTE_ALREADY_OPEN`)".

        A second dispute against the same statement fails; the first stays
        OPEN.

        Design: Corner/validations/second_dispute_while_open_rejected
        """
        ctx = setup_dispute_on_statement(disputed_amount=5_000, reason="first")
        resp = api_client.create_dispute(
            create_dispute_payload(statement_id=ctx["statement"]["id"],
                                   disputed_amount_cents=3_000, reason="second"),
            make_tenant_headers(ctx["tenancy"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN)
        assert get_dispute(ctx["dispute"]["id"])["status"] == "OPEN"

    def test_award_exceeds_disputed_rejected(self):
        """PRD §3.6: "Court resolution is recorded by a `PropertyManager`
        supplying `awarded_amount_cents`, the portion of the disputed amount
        awarded back to the tenant, which may not exceed the disputed amount
        (`ERR_AWARD_EXCEEDS_DISPUTED`)."

        Award 25,000 against a 20,000c dispute fails; the dispute stays
        ESCALATED_SMALL_CLAIMS.

        Design: Corner/validations/award_exceeds_disputed_rejected
        """
        ctx = setup_escalated_dispute(disputed_amount=20_000)
        resp = api_client.resolve_court_dispute(
            ctx["dispute"]["id"], {"awarded_amount_cents": 25_000}, PM)
        validate_error(resp, ApiErrorId.ERR_AWARD_EXCEEDS_DISPUTED)
        assert get_dispute(ctx["dispute"]["id"])["status"] == "ESCALATED_SMALL_CLAIMS"
