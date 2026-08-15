"""Issuance deadline boundary: timely on the deadline day vs late the next
day, and the late flag's effect on small-claims exposure."""
import test_helpers as th
from test_helpers import (
    api_client,
    create_dispute_payload,
    get_dispute,
    get_statement,
    get_success_data,
    make_manager_admin_headers,
    make_property_manager_headers,
    make_tenant_headers,
    setup_vacated_with_statement,
    validate_success,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()


def _setup_pair_with_cleaning():
    """Two identical tenancies, each VACATED with paint damage 60,000c plus a
    manual CLEANING 8,000c (deduction_total will be 68,000c; refund_due
    141,337c), each with a DRAFT statement awaiting issuance."""
    ctx_a = setup_vacated_with_statement(
        jurisdiction_overrides={"code": "CA-ACT"},
        tenancy_overrides={"tenant_display_name": "T A"})
    ctx_b = setup_vacated_with_statement(
        jurisdiction_overrides={"code": "CA-AC2"},
        tenancy_overrides={"tenant_display_name": "T B"})
    for ctx in (ctx_a, ctx_b):
        get_success_data(api_client.create_deduction(
            {"tenancy_id": ctx["tenancy"]["id"], "source": "CLEANING",
             "description": "oven cleaning", "amount_cents": 8_000}, PM))
    return ctx_a, ctx_b


def _issue_and_dispute_escalate(ctx, issue_clock, disputed=20_000):
    api_client.set_clock({"to_iso8601": issue_clock}, ADMIN)
    validate_success(api_client.issue_statement(ctx["statement"]["id"], PM))
    ten_id = ctx["tenancy"]["id"]
    resp = api_client.create_dispute(
        create_dispute_payload(statement_id=ctx["statement"]["id"],
                               disputed_amount_cents=disputed,
                               reason="oven was clean"),
        make_tenant_headers(ten_id),
    )
    disp = get_success_data(resp)
    validate_success(api_client.escalate_dispute(
        disp["id"], make_tenant_headers(ten_id)))
    return get_statement(ctx["statement"]["id"]), get_dispute(disp["id"])


class TestIssueDeadlineBoundary:
    def test_issue_on_deadline_day_is_timely(self):
        """PRD §3.5: "At issuance the system stamps `issued_at` from the
        logical clock, computes `deadline_on` as `move_out_on` plus the
        jurisdiction's `deposit_return_deadline_days`, and sets the `late`
        flag: issuance is timely when the calendar date of `issued_at` is on
        or before `deadline_on`, and `late` is true exactly when the issuance
        date falls after `deadline_on`."

        move_out 2026-08-01 + 21 days = deadline 2026-08-22; issuing ON
        2026-08-22 is timely (late false), deadline_on reads 2026-08-22,
        totals 68,000 / 141,337.

        Design: Difficulty/boundary_precision_check/issue_on_deadline_day_timely_vs_next_day_late
        """
        ctx_a, _ctx_b = _setup_pair_with_cleaning()
        stmt_a, disp_a = _issue_and_dispute_escalate(ctx_a, "2026-08-22T12:00:00Z")
        assert stmt_a["late"] is False
        assert stmt_a["deadline_on"] == "2026-08-22"
        assert stmt_a["deduction_total_cents"] == 68_000
        assert stmt_a["refund_due_cents"] == 141_337, (
            f"200000 + 9337 - 68000 = 141337, got {stmt_a['refund_due_cents']}"
        )
        assert disp_a["exposure_cents"] == 20_000, (
            f"timely: no bad-faith multiplier, expected 20000, "
            f"got {disp_a['exposure_cents']}"
        )

    def test_issue_next_day_is_late_and_doubles_exposure(self):
        """PRD §3.5: "`late` is true exactly when the issuance date falls
        after `deadline_on`." and "deductions are billed even when the
        statement is late, because lateness is exposed through the `late`
        flag and punished through the small-claims multiplier rather than by
        forfeiting the charges." PRD §3.6: "when the statement's `late` flag
        is set, the base is first multiplied by the jurisdiction's
        `bad_faith_multiplier`".

        Issuing on 2026-08-23 (one day past): late true, lines still billed
        (68,000c), and the identical 20,000c dispute escalates to exposure
        40,000c via the x2 multiplier.

        Design: Difficulty/boundary_precision_check/issue_on_deadline_day_timely_vs_next_day_late
        """
        _ctx_a, ctx_b = _setup_pair_with_cleaning()
        stmt_b, disp_b = _issue_and_dispute_escalate(ctx_b, "2026-08-23T00:00:00Z")
        assert stmt_b["late"] is True
        assert stmt_b["deduction_total_cents"] == 68_000, (
            "late statements still bill; lateness is not forfeiture"
        )
        assert stmt_b["refund_due_cents"] == 141_337
        assert disp_b["exposure_cents"] == 40_000, (
            f"late: bad_faith_multiplier 2 applies, expected 40000, "
            f"got {disp_b['exposure_cents']}"
        )
