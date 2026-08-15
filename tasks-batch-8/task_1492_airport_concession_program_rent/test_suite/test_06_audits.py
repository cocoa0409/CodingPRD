"""Audit rights and the restatement cascade: findings restate ACCEPTED reports,
reopen PAID settlements, and recompute lease arrears."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_audit,
    file_sales_report,
    get_lease,
    get_settlement,
    make_tenant_headers,
    setup_active_lease,
    setup_paid_settlement,
    submit_sales_report,
    validate_error,
    validate_success,
)


def _setup_paid_settlement_under_audit(api, auditor_headers):
    """PAID 2026 settlement (amount_due 1,200,000, MAG only) backed by ACCEPTED
    reports 2026-01 and 2026-02 of 600,000 each, plus an OPENED audit covering
    2026-01..2026-02."""
    sc = setup_paid_settlement(
        report_specs=[("2026-01", 600_000), ("2026-02", 600_000)]
    )
    assert sc["settlement"]["status"] == "PAID"
    audit = create_audit(
        sc["lease"], period_start_month="2026-01", period_end_month="2026-02"
    )
    return sc, audit


class TestFindingsCascade:
    def test_findings_restate_report_and_record_understatement(
        self, api, analyst_headers, auditor_headers
    ):
        """PRD §3.6: "Each referenced report moves `ACCEPTED → ADJUSTED`, with its
        `restated_gross_sales_cents` set to the finding's restated amount. The audit
        case records `understatement_cents`, the sum over the adjusted reports of the
        restated gross minus the originally reported gross — a figure that may
        legitimately be zero."

        Design: Difficulty/transitive_cascade/audit_findings_restate_reports_cascade
        """
        sc, audit = _setup_paid_settlement_under_audit(api, auditor_headers)
        report = sc["reports"][0]

        res = api.issue_findings(
            audit["id"],
            {
                "findings": [
                    {
                        "sales_report_id": report["id"],
                        "restated_gross_sales_cents": 20_600_000,
                    }
                ]
            },
            auditor_headers,
        )
        audit_after = validate_success(res, 200)
        assert audit_after["understatement_cents"] == 20_000_000
        assert audit_after["status"] == "FINDINGS_ISSUED"

        report_after = validate_success(
            api.get_sales_report(report["id"], analyst_headers), 200
        )
        assert report_after["status"] == "ADJUSTED"
        assert report_after["restated_gross_sales_cents"] == 20_600_000

    def test_findings_reopen_paid_settlement_and_recompute_arrears(
        self, api, analyst_headers, auditor_headers
    ):
        """PRD §3.6: "The owning settlement is then recalculated under `FINAL`
        semantics, and if the recalculated `amount_due_cents` rises above the
        `amount_paid_cents`, a `PAID` settlement reopens to `PARTIALLY_PAID` with its
        balance recomputed; this reopen is the only way out of `PAID`. Finally the
        lease's `arrears_cents` is recomputed from the settlement balances, and the
        case moves to `FINDINGS_ISSUED`."

        Design: Difficulty/transitive_cascade/audit_findings_restate_reports_cascade
        """
        sc, audit = _setup_paid_settlement_under_audit(api, auditor_headers)
        report = sc["reports"][0]

        validate_success(
            api.issue_findings(
                audit["id"],
                {
                    "findings": [
                        {
                            "sales_report_id": report["id"],
                            "restated_gross_sales_cents": 20_600_000,
                        }
                    ]
                },
                auditor_headers,
            ),
            200,
        )

        # January restated: 40,000 + 20,100,000 at 1000bp = 2,050,000;
        # February stays 50,000 -> percentage 2,100,000; true-up 900,000 over MAG.
        settlement = get_settlement(sc["settlement"]["id"])
        assert settlement["percentage_due_cents"] == 2_100_000
        assert settlement["true_up_due_cents"] == 900_000
        assert settlement["amount_due_cents"] == 2_100_000
        assert settlement["amount_paid_cents"] == 1_200_000
        assert settlement["balance_due_cents"] == 900_000
        assert settlement["status"] == "PARTIALLY_PAID", (
            "A PAID settlement reopens to PARTIALLY_PAID when the recalculated "
            "amount_due rises above amount_paid"
        )

        lease = get_lease(sc["lease"]["id"])
        assert lease["arrears_cents"] == 900_000


class TestFindingGuards:
    def test_audit_findings_on_unaccepted_report_returns_error(
        self, api, auditor_headers
    ):
        """PRD §3.6: "Every finding must reference a report in `ACCEPTED` status,
        belonging to the audit's lease, and falling within the audited window; a
        finding that misses any of those three conditions is rejected with
        `ERR_AUDIT_FINDING_REPORT_STATE`."

        Design: Corner/validations/audit_findings_on_unaccepted_report_returns_error
        """
        sc = setup_active_lease()
        report = file_sales_report(sc["lease"], sc["tenant"], "2026-01", 100_000)
        submit_sales_report(report, sc["tenant"])  # SUBMITTED, not ACCEPTED
        audit = create_audit(
            sc["lease"], period_start_month="2026-01", period_end_month="2026-03"
        )
        res = api.issue_findings(
            audit["id"],
            {
                "findings": [
                    {
                        "sales_report_id": report["id"],
                        "restated_gross_sales_cents": 900_000,
                    }
                ]
            },
            auditor_headers,
        )
        validate_error(res, ApiErrorId.ERR_AUDIT_FINDING_REPORT_STATE)

    def test_audit_issue_findings_after_close_returns_audit_state_forbids(
        self, api, auditor_headers
    ):
        """PRD §3.6: "Findings are issued from `OPENED` — from any other status the
        action is rejected with `ERR_AUDIT_STATE_FORBIDS`."

        Design: Corner/state_machines/audit_issue_findings_after_close_returns_audit_state_forbids
        """
        sc = setup_active_lease()
        audit = create_audit(
            sc["lease"], period_start_month="2026-01", period_end_month="2026-03"
        )
        validate_success(api.close_audit(audit["id"], auditor_headers), 200)
        res = api.issue_findings(audit["id"], {"findings": []}, auditor_headers)
        validate_error(res, ApiErrorId.ERR_AUDIT_STATE_FORBIDS)
