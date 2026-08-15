"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be an integer >= 1"


def _assert_ledger_fields(data: dict, label: str):
    """Ledger rows carry only id + created_at (no updated_at / version)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"


def assert_union_agreement(data: dict):
    _assert_common_fields(data, "UnionAgreement")
    assert data["union_code"] in ("SAG_AFTRA", "WGA", "DGA", "AFM", "IATSE")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)
    assert isinstance(data["rate_tiers"], list) and len(data["rate_tiers"]) >= 1
    assert isinstance(data["meal_penalty_cents"], int)
    assert isinstance(data["rest_penalty_cents"], int)
    assert isinstance(data["residual_base_pct_by_market"], dict)
    assert data["status"] in ("DRAFT", "RATIFIED")


def assert_production(data: dict):
    _assert_common_fields(data, "Production")
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["jurisdictions"], list)
    assert data["status"] in ("PRE_PRODUCTION", "SHOOTING", "WRAPPED", "ARCHIVED")


def assert_performer(data: dict):
    _assert_common_fields(data, "Performer")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["ytd_gross_cents"], int)
    assert isinstance(data["ytd_garnished_cents"], int)


def assert_engagement(data: dict):
    _assert_common_fields(data, "Engagement")
    for fk in ("production_id", "union_agreement_id", "performer_id"):
        assert is_valid_uuid(data.get(fk, "")), f"Engagement.{fk} must be a UUID"
    assert data["payee_type"] in ("DIRECT", "LOAN_OUT")
    assert data["status"] in ("DRAFT", "PENDING_APPROVAL", "ACTIVE",
                              "AMENDMENT_PENDING", "SUPERSEDED", "WRAPPED")
    assert isinstance(data["accrued_penalty_cents"], int)
    assert isinstance(data["accrued_adjustment_cents"], int)
    assert isinstance(data["ytd_paid_cents"], int)


def assert_timecard(data: dict):
    _assert_common_fields(data, "Timecard")
    assert is_valid_uuid(data.get("engagement_id", "")), "Timecard.engagement_id UUID"
    assert isinstance(data["worked_minutes"], int)
    assert isinstance(data["overtime_minutes"], int)
    assert isinstance(data["provisional_penalty_cents"], int)
    assert data["review_status"] in ("SUBMITTED", "FLAGGED", "APPROVED")
    assert data["payment_status"] in ("UNBATCHED", "BATCHED", "PAID")


def assert_penalty_assessment(data: dict):
    _assert_ledger_fields(data, "PenaltyAssessment")
    assert "version" not in data, "PenaltyAssessment must not expose version"
    assert "updated_at" not in data, "PenaltyAssessment must not expose updated_at"
    assert data["penalty_type"] in ("MEAL", "REST", "TURNAROUND")
    assert isinstance(data["units"], int) and data["units"] > 0
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("CONFIRMED", "WAIVED")


def assert_residual_obligation(data: dict):
    _assert_common_fields(data, "ResidualObligation")
    assert is_valid_uuid(data.get("engagement_id", "")), "Residual.engagement_id UUID"
    assert data["reuse_market"] in ("NETWORK_REBROADCAST", "SYNDICATION",
                                    "STREAMING", "FOREIGN", "HOME_VIDEO")
    assert isinstance(data["base_pct"], (int, float))
    assert isinstance(data["window_sequence"], int) and data["window_sequence"] >= 1
    assert isinstance(data["provisional_amount_cents"], int)
    assert data["status"] in ("REPORTED", "CALCULATED", "APPROVED",
                              "DISPUTED", "BATCHED", "PAID")


def assert_pay_batch(data: dict):
    _assert_common_fields(data, "PayBatch")
    assert isinstance(data["period_label"], str)
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    for total in ("total_gross_cents", "total_tax_cents", "total_garnished_cents",
                  "total_phw_cents", "total_net_cents"):
        assert isinstance(data[total], int), f"PayBatch.{total} must be int"
    assert data["status"] in ("OPEN", "CLOSED", "APPROVED", "DISBURSED")


def assert_pay_line(data: dict):
    _assert_ledger_fields(data, "PayLine")
    assert "version" not in data, "PayLine must not expose version"
    assert "updated_at" not in data, "PayLine must not expose updated_at"
    assert data["source_type"] in ("TIMECARD", "RESIDUAL", "GRIEVANCE_ADJUSTMENT")
    for amount in ("gross_cents", "tax_cents", "garnished_cents",
                   "phw_cents", "net_cents"):
        assert isinstance(data[amount], int), f"PayLine.{amount} must be int"
    assert data["status"] in ("UNPAID", "PAID")


def assert_garnishment_order(data: dict):
    _assert_common_fields(data, "GarnishmentOrder")
    assert is_valid_uuid(data.get("performer_id", "")), "GarnishmentOrder.performer_id"
    assert data["order_type"] in ("CHILD_SUPPORT", "FEDERAL_TAX_LEVY",
                                  "STATE_TAX_LEVY", "CREDITOR_JUDGMENT")
    assert isinstance(data["priority_rank"], int)
    assert isinstance(data["total_withheld_cents"], int)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_remittance_report(data: dict):
    _assert_common_fields(data, "RemittanceReport")
    for amount in ("pension_cents", "health_cents", "welfare_cents"):
        assert isinstance(data[amount], int), f"RemittanceReport.{amount} must be int"
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACKNOWLEDGED")


def assert_grievance_case(data: dict):
    _assert_common_fields(data, "GrievanceCase")
    assert is_valid_uuid(data.get("engagement_id", "")), "GrievanceCase.engagement_id"
    assert data["category"] in ("UNDERPAYMENT", "PENALTY_OMITTED",
                                "RESIDUAL_MISCALC", "PHW_SHORTAGE")
    assert isinstance(data["claimed_amount_cents"], int)
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]
    assert data["status"] in ("FILED", "UNDER_REVIEW", "ESCALATED", "RESOLVED")


def assert_payline_net_identity(line: dict):
    """PRD §3.13 step 6: net == gross - tax - garnished on every pay line."""
    assert line["net_cents"] == (
        line["gross_cents"] - line["tax_cents"] - line["garnished_cents"]
    ), (f"net_cents {line['net_cents']} != gross {line['gross_cents']} "
        f"- tax {line['tax_cents']} - garnished {line['garnished_cents']}")


def assert_batch_totals_equal_line_sums(batch: dict, lines: list):
    """PRD §3.11: batch totals are recomputed as sums over the pay lines."""
    for total_key, line_key in (
        ("total_gross_cents", "gross_cents"),
        ("total_tax_cents", "tax_cents"),
        ("total_garnished_cents", "garnished_cents"),
        ("total_phw_cents", "phw_cents"),
        ("total_net_cents", "net_cents"),
    ):
        expected = sum(line[line_key] for line in lines)
        assert batch[total_key] == expected, (
            f"PayBatch.{total_key} {batch[total_key]} != sum of lines {expected}"
        )
