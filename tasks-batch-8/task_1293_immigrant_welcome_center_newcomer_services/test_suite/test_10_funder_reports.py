"""Funder reporting: outcome lines, pinned per-cell rounding with residual
reconciliation, freshness at submit, and the review cycle (PRD §3.9)."""

from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, ApiErrorId,
    create_funder_report_payload,
    register_client, create_staff_member, open_case, grant_consent,
    create_partner_org, create_sent_referral, confirm_appointment,
    create_funder_report, setup_report_outcome_mix,
    staff_headers, partner_headers, make_funder_auditor_headers,
    set_clock,
)

ADMIN = TEST_USERS["center_admin_headers"]


def _lines_by_unit_cost(report):
    """Index outcome lines by their PRD-pinned unit costs (7500 referral,
    12000 program enrollment, 2500 workshop attendance); each line carries
    `line_type`, `unit_cost_cents`, `quantity`, and `line_total_cents` (§3.9)."""
    return {line["unit_cost_cents"]: line for line in report["lines"]}


def _totals_by_stream(report):
    """Map stream name -> per-stream total. The PRD pins the per-stream VALUES
    and their computation order, so each entry is read tolerantly: the stream
    name plus its single integer total. `share_pct` is the PRD-named input
    field (§3.9) and an implementation may echo it on the entry, so it is
    excluded from the total candidates; a `total`-bearing key wins any tie."""
    totals = {}
    for entry in report["stream_totals"]:
        if isinstance(entry, dict):
            name = entry.get("stream_name")
            numeric = {k: v for k, v in entry.items()
                       if k not in ("stream_name", "share_pct")
                       and isinstance(v, (int, float)) and not isinstance(v, bool)}
            if len(numeric) > 1:
                numeric = {k: v for k, v in numeric.items() if "total" in k}
            assert name is not None and len(numeric) == 1, \
                f"stream_totals entry must name the stream and one total: {entry!r}"
            totals[name] = next(iter(numeric.values()))
        else:
            raise AssertionError(f"stream_totals entry must be an object: {entry!r}")
    return totals


class TestCellRoundThenSum:
    def test_lines_and_total_cost(self):
        """PRD §3.9: "Line assembly counts three outcome types within the
        half-open window from `period_start` to `period_end`: referrals whose
        status is `COMPLETED` with `completed_at` in the window, costed at 7500
        cents apiece; program enrollments `COMPLETED` with `completed_at` in the
        window, at 12000 cents apiece; and workshop enrollments `ATTENDED` with
        `attended_marked_at` in the window, at 2500 cents apiece."

        Design: Difficulty/combinatorial_formula/funder_allocation_cell_round_then_sum
        """
        setup_report_outcome_mix()
        report = create_funder_report(funding_streams=[
            {"stream_name": "A", "share_pct": 33.34},
            {"stream_name": "B", "share_pct": 33.33},
            {"stream_name": "C", "share_pct": 33.33},
        ])
        assert report["total_cost_cents"] == 29500, "12000 + 2*7500 + 2500"
        lines = _lines_by_unit_cost(report)
        assert lines[12000]["quantity"] == 1, "one COMPLETED program enrollment"
        assert lines[7500]["quantity"] == 2, "two COMPLETED referrals"
        assert lines[2500]["quantity"] == 1, "one ATTENDED workshop enrollment"

    def test_stream_totals_round_per_cell_then_sum_with_residual(self):
        """PRD §3.9: "for each line and each stream, taken in `funding_streams`
        array order, the cell value is the line total multiplied by the stream's
        `share_pct`, divided by 100, and rounded half-up to integer cents —
        rounding happens per cell, before any summation; each stream's total is
        the sum of its cells. Because per-cell rounding rarely sums exactly, the
        residual — `total_cost_cents` minus the sum of all stream totals — is
        assigned, even when negative, to the stream with the greatest `share_pct`;
        ties break to the stream appearing earliest in the `funding_streams`
        array, never to any entity id."
        PRD §3.9: "`aggregate_client_count` counts distinct clients behind the
        counted rows regardless of consent, while `reportable_client_count` counts
        only distinct clients whose `reportable` flag is true".

        Design: Difficulty/combinatorial_formula/funder_allocation_cell_round_then_sum
        """
        setup_report_outcome_mix()
        report = create_funder_report(funding_streams=[
            {"stream_name": "A", "share_pct": 33.34},
            {"stream_name": "B", "share_pct": 33.33},
            {"stream_name": "C", "share_pct": 33.33},
        ])
        totals = _totals_by_stream(report)
        # Per-cell round-half-up sums are 9836 / 9833 / 9833 (= 29502); the -2
        # residual lands on the largest-share stream A -> 9834.
        assert totals["A"] == 9834
        assert totals["B"] == 9833
        assert totals["C"] == 9833
        assert sum(totals.values()) == 29500, "no drift remains after residual assignment"
        assert report["aggregate_client_count"] == 2
        assert report["reportable_client_count"] == 1, \
            "the referral-only client holds no DATA_REPORTING consent"


class TestOutcomeWindow:
    def test_report_window_end_exclusive_boundary(self):
        """PRD §3.9: "A `CenterAdmin` drafts a funder report with `period_start`
        (inclusive), `period_end` (exclusive, and it must fall after
        `period_start` or the request is `ERR_INVALID_REQUEST`)".
        PRD §3.9: "Line assembly counts three outcome types within the half-open
        window from `period_start` to `period_end`: referrals whose status is
        `COMPLETED` with `completed_at` in the window, costed at 7500 cents
        apiece".

        Design: Corner/calculations/report_window_end_exclusive_boundary
        """
        mgr = create_staff_member()
        client1 = register_client(full_name="Bia One")
        client2 = register_client(full_name="Bia Two")
        grant_consent(client1, "REFERRAL_SHARE")
        grant_consent(client2, "REFERRAL_SHARE")
        case1 = open_case(client1, mgr)
        case2 = open_case(client2, mgr)
        org1 = create_partner_org(name="Org W1", categories=("HEALTH",), capacity=5,
                                  email="w1@org.test")
        org2 = create_partner_org(name="Org W2", categories=("HEALTH",), capacity=5,
                                  email="w2@org.test")

        # r1 completes at the default clock 2026-08-01T00:00:00Z == period_start.
        r1 = create_sent_referral(case1, org1, "HEALTH", mgr)
        validate_success(api_client.respond_referral(r1["id"], {"decision": "ACCEPTED"},
                                                     partner_headers(org1)))
        validate_success(api_client.confirm_handoff(r1["id"], staff_headers(mgr)))
        validate_success(api_client.complete_referral(r1["id"], staff_headers(mgr)))

        # r2 completes at 2026-09-01T00:00:00Z == period_end (excluded).
        set_clock("2026-09-01T00:00:00Z")
        r2 = create_sent_referral(case2, org2, "HEALTH", mgr)
        validate_success(api_client.respond_referral(r2["id"], {"decision": "ACCEPTED"},
                                                     partner_headers(org2)))
        validate_success(api_client.confirm_handoff(r2["id"], staff_headers(mgr)))
        validate_success(api_client.complete_referral(r2["id"], staff_headers(mgr)))

        report = create_funder_report()
        lines = _lines_by_unit_cost(report)
        assert lines[7500]["quantity"] == 1, \
            "completion at period_start is included; completion at period_end is excluded"
        assert report["total_cost_cents"] == 7500
        assert report["aggregate_client_count"] == 1


class TestSubmissionFreshness:
    def test_report_submit_stale_after_data_change(self):
        """PRD §3.9: "the server recomputes the lines at submit time, and if the
        recomputation differs from the stored `lines` the submission fails with
        `ERR_REPORT_STALE` — the remedy is to regenerate first."

        Design: Corner/errors/report_submit_stale_after_data_change
        """
        report = create_funder_report()  # drafted while zero outcomes exist
        mgr = create_staff_member()
        client = register_client()
        grant_consent(client, "REFERRAL_SHARE")
        case = open_case(client, mgr)
        org = create_partner_org(name="Org R", categories=("HOUSING",), capacity=3,
                                 email="r@org.test")
        ref = create_sent_referral(case, org, "HOUSING", mgr)
        validate_success(api_client.respond_referral(ref["id"], {"decision": "ACCEPTED"},
                                                     partner_headers(org)))
        validate_success(api_client.confirm_handoff(ref["id"], staff_headers(mgr)))
        validate_success(api_client.complete_referral(ref["id"], staff_headers(mgr)))

        resp = api_client.submit_funder_report(report["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_REPORT_STALE)

        regen = validate_success(api_client.regenerate_funder_report(report["id"], ADMIN))
        assert regen["total_cost_cents"] == 7500
        submitted = validate_success(api_client.submit_funder_report(report["id"], ADMIN))
        assert submitted["status"] == "SUBMITTED"

    def test_funder_report_returned_resubmit_cycle(self):
        """PRD §3.9: "Review belongs to the `FunderAuditor`, whose `decision` of
        `ACCEPTED` or `RETURNED` is valid only against a `SUBMITTED` report and
        stamps `reviewed_by_id`. Acceptance is terminal; a returned report
        re-enters the draft cycle through regeneration and resubmission."
        PRD §2.8: "4. **State** — the target resource sits in a valid from-state
        for the requested transition, terminal states reject all further
        transitions".

        Design: Corner/state_machines/funder_report_returned_resubmit_cycle
        """
        auditor = make_funder_auditor_headers()
        report = create_funder_report()
        validate_success(api_client.submit_funder_report(report["id"], ADMIN))
        returned = validate_success(api_client.review_funder_report(
            report["id"], {"decision": "RETURNED"}, auditor))
        assert returned["status"] == "RETURNED"
        assert returned["reviewed_by_id"] is not None

        validate_success(api_client.regenerate_funder_report(report["id"], ADMIN))
        resubmitted = validate_success(api_client.submit_funder_report(report["id"], ADMIN))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["reviewed_by_id"] is None, \
            "resubmission of a returned report clears reviewed_by_id"
        accepted = validate_success(api_client.review_funder_report(
            report["id"], {"decision": "ACCEPTED"}, auditor))
        assert accepted["status"] == "ACCEPTED"

        # ACCEPTED is terminal: a further submit is rejected.
        resp = api_client.submit_funder_report(report["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPeriodOverlap:
    def test_funder_report_period_overlap(self):
        """PRD §3.9: "The period must not overlap any existing report whose status
        is not `RETURNED` — overlaps are rejected with
        `ERR_REPORT_PERIOD_OVERLAP`."
        PRD §3.9: "A `CenterAdmin` drafts a funder report with `period_start`
        (inclusive), `period_end` (exclusive, and it must fall after
        `period_start` or the request is `ERR_INVALID_REQUEST`)".

        Design: Corner/validations/funder_report_period_overlap
        """
        create_funder_report()  # [2026-08-01, 2026-09-01)
        resp = api_client.create_funder_report(create_funder_report_payload(
            period_start="2026-08-15T00:00:00Z", period_end="2026-09-15T00:00:00Z",
        ), ADMIN)
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

        # Adjacent half-open periods touch but do not overlap.
        ok = validate_success(api_client.create_funder_report(create_funder_report_payload(
            period_start="2026-09-01T00:00:00Z", period_end="2026-10-01T00:00:00Z",
        ), ADMIN), expected_status=201)
        assert ok["status"] == "DRAFT"
