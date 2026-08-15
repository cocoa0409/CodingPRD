"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer starting at 1"


def assert_writer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["ipi_number"], str) and data["ipi_number"]
    assert data["pro_affiliation"] in [
        "ASCAP", "BMI", "SESAC", "PRS", "GEMA", "SACEM", "NONE"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    for field in ("payable_balance_cents", "advance_outstanding_cents",
                  "lifetime_earned_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_work(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["alternate_titles"], list)
    assert isinstance(data["work_code"], str) and data["work_code"].startswith("W-")
    assert data["registration_status"] in [
        "UNREGISTERED", "PENDING_SOCIETY", "REGISTERED"]
    assert data["copyright_status"] in [
        "UNFILED", "FILED", "COPCO_REGISTERED", "TERMINATED"]
    for field in ("total_collected_cents", "total_distributed_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_society(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]
    assert data["society_type"] in ["PRO", "MECHANICAL", "COLLECTION"]
    assert isinstance(data["territory_code"], str) and data["territory_code"]


def assert_society_registration(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("work_id", ""))
    assert is_valid_uuid(data.get("society_id", ""))
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "ACKNOWLEDGED", "REGISTERED", "REJECTED"]


def assert_split_set(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("work_id", ""))
    assert isinstance(data["revision_index"], int) and data["revision_index"] >= 1
    assert data["status"] in [
        "DRAFT", "PENDING_CONFIRMATIONS", "DISPUTED", "CONFIRMED",
        "SUPERSEDED", "CANCELLED"]
    for field in ("writer_pool_total_bp", "publisher_pool_total_bp"):
        assert isinstance(data[field], int), f"{field} must be integer bp"


def assert_split_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("split_set_id", ""))
    assert data["participant_type"] in ["WRITER", "PUBLISHER"]
    assert isinstance(data["share_bp"], int) and data["share_bp"] >= 1
    assert data["confirmation_status"] in ["PENDING", "CONFIRMED", "REJECTED"]
    if data["participant_type"] == "WRITER":
        assert is_valid_uuid(data.get("writer_id", ""))
        assert data.get("publisher_name") is None
    else:
        assert isinstance(data["publisher_name"], str) and data["publisher_name"]
        assert data.get("writer_id") is None


def assert_sub_publisher(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["home_territory_code"], str)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_sub_publishing_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("sub_publisher_id", ""))
    assert isinstance(data["territory_codes"], list) and data["territory_codes"]
    assert isinstance(data["income_types"], list) and data["income_types"]
    assert isinstance(data["retention_bp"], int)
    assert 1 <= data["retention_bp"] <= 5000
    assert data["status"] in ["DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"]


def assert_licensee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["licensee_type"] in ["STREAMING", "LABEL", "SYNC_HOUSE", "OTHER"]


def assert_royalty_statement(data: dict):
    _assert_common_fields(data)
    assert data["source_type"] in ["SOCIETY", "LICENSEE", "SUB_PUBLISHER"]
    assert is_valid_uuid(data.get("source_id", ""))
    assert data["income_type"] in [
        "PERFORMANCE", "MECHANICAL", "SYNC", "PRINT", "OTHER"]
    assert isinstance(data["territory_code"], str)
    assert isinstance(data["gross_amount_cents"], int)
    assert data["status"] in [
        "RECEIVED", "MATCHING_REVIEW", "ALLOCATED", "FINALIZED", "DISTRIBUTED",
        "SUPERSEDED", "REJECTED"]
    for field in ("retained_cents", "suspense_cents", "allocated_total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_statement_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("statement_id", ""))
    assert isinstance(data["line_number"], int) and data["line_number"] >= 1
    assert isinstance(data["reported_title"], str)
    assert isinstance(data["gross_cents"], int) and data["gross_cents"] >= 1
    assert data["match_status"] in ["UNMATCHED", "AUTO_MATCHED", "MANUAL_MATCHED"]


def assert_allocation_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("statement_line_id", ""))
    assert is_valid_uuid(data.get("split_line_id", ""))
    assert is_valid_uuid(data.get("statement_id", ""))
    assert data["participant_type"] in ["WRITER", "PUBLISHER"]
    assert isinstance(data["provisional_amount_cents"], int)
    assert isinstance(data["advance_applied_cents"], int)
    assert isinstance(data["net_payable_cents"], int)
    assert data["status"] in ["PROVISIONAL", "FINAL", "REVERSED"]


def assert_advance(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("writer_id", ""))
    assert isinstance(data["agreement_ref"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["recoup_rate_bp"], int)
    assert 1 <= data["recoup_rate_bp"] <= 10000
    assert data["status"] in [
        "DRAFT", "APPROVED", "PAID", "RECOUPING", "RECOUPED", "CANCELLED"]
    assert isinstance(data["recouped_cents"], int)
    assert isinstance(data["outstanding_cents"], int)


def assert_advance_principal_invariant(data: dict):
    """PRD: for every advance in PAID, RECOUPING, or RECOUPED,
    amount_cents always equals recouped_cents plus outstanding_cents."""
    if data["status"] in ("PAID", "RECOUPING", "RECOUPED"):
        total = data["recouped_cents"] + data["outstanding_cents"]
        assert total == data["amount_cents"], (
            f"advance principal not conserved: {data['amount_cents']} != "
            f"{data['recouped_cents']} + {data['outstanding_cents']}")


def assert_distribution_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["period_label"], str) and data["period_label"]
    assert data["status"] in ["OPEN", "CALCULATED", "APPROVED", "PAID"]
    assert isinstance(data["writer_payouts"], list)
    assert isinstance(data["included_statement_ids"], list)
    assert isinstance(data["total_payable_cents"], int)


def assert_licensee_audit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("licensee_id", ""))
    assert data["valuation_method"] in ["ACTUAL_SHORTFALL", "EXTRAPOLATED"]
    assert data["status"] in [
        "OPEN", "FIELDWORK", "FINDINGS_ISSUED", "UNDER_APPEAL", "SETTLED",
        "CLOSED"]


def assert_termination_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("work_id", ""))
    assert data["statute_basis"] in ["SEC_203", "SEC_304"]
    assert data["status"] in [
        "TRACKING", "NOTICE_WINDOW_OPEN", "NOTICE_FILED", "EFFECTIVE", "LAPSED",
        "REJECTED"]
    for field in ("window_open_date", "window_close_date",
                  "notice_earliest_date", "notice_latest_date"):
        assert isinstance(data[field], str) and data[field], \
            f"{field} must be a projected calendar date"
