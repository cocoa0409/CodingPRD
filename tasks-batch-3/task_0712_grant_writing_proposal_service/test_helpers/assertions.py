"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the common-field set (id UUID, timestamps,
integer version) plus entity-specific shape. All field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["org_name"], str) and len(data["org_name"]) > 0
    assert isinstance(data["ein"], str)
    assert isinstance(data["mission_areas"], list)
    assert isinstance(data["annual_budget_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "ARCHIVED")
    assert isinstance(data["proposals_submitted_count"], int)
    assert isinstance(data["proposals_won_count"], int)
    assert isinstance(data["win_rate_pct"], (int, float))


def assert_opportunity(data: dict):
    _assert_common(data)
    assert isinstance(data["focus_areas"], list)
    assert isinstance(data["ceiling_amount_cents"], int)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_engagement(data: dict):
    _assert_common(data)
    assert data["fee_model"] in ("SUCCESS_FEE", "HOURLY", "RETAINER")
    assert data["status"] in ("DRAFT", "ACTIVE", "PAUSED", "CLOSED")
    assert isinstance(data["ytd_billed_cents"], int)


def assert_match(data: dict):
    _assert_common(data)
    assert isinstance(data["score"], int)
    assert 0 <= data["score"] <= 100, f"score out of band: {data['score']}"
    assert isinstance(data["eligible"], bool)
    assert data["status"] in ("PROPOSED", "PURSUING", "DECLINED")


def assert_proposal(data: dict):
    _assert_common(data)
    assert isinstance(data["requested_amount_cents"], int)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert isinstance(data["budget_total_cents"], int)
    assert data["status"] in ("DRAFTING", "IN_REVIEW", "APPROVED", "SUBMITTED", "WITHDRAWN")


def assert_budget_line(data: dict):
    _assert_common(data)
    assert data["category"] in ("PERSONNEL", "EQUIPMENT", "TRAVEL", "INDIRECT", "OTHER")
    assert isinstance(data["amount_cents"], int)


def assert_deliverable(data: dict):
    _assert_common(data)
    assert data["kind"] in ("NARRATIVE", "BUDGET_JUSTIFICATION", "ATTACHMENT")
    assert data["content_status"] in ("OUTLINE", "DRAFTED", "FINAL")
    assert data["approval_status"] in ("UNREVIEWED", "CHANGES_REQUESTED", "APPROVED")
    assert isinstance(data["open_revision_count"], int)


def assert_revision_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "RESOLVED", "SUPERSEDED")


def assert_submission(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "ACCEPTED", "REJECTED", "WITHDRAWN")


def assert_time_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["minutes"], int) and data["minutes"] > 0
    assert data["status"] in ("LOGGED", "BILLED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["kind"] in ("SUCCESS_FEE", "HOURLY", "RETAINER")
    assert isinstance(data["line_count"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ("ISSUED", "VOID")


def assert_award(data: dict):
    _assert_common(data)
    assert isinstance(data["awarded_amount_cents"], int)
    assert data["compliance_status"] in ("GREEN", "AT_RISK", "DELINQUENT")
    assert data["status"] in ("ACTIVE", "CLOSED_OUT")


def assert_compliance_report(data: dict):
    _assert_common(data)
    assert data["report_type"] in ("SCHEDULED", "SUPPLEMENTAL")
    assert isinstance(data["sequence_index"], int)
    assert data["status"] in ("PENDING", "FILED", "LATE")


def assert_boilerplate(data: dict):
    _assert_common(data)
    assert isinstance(data["usage_count"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")
