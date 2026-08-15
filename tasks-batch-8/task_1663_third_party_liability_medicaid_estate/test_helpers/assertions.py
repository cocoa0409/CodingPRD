"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_member(data: dict):
    _assert_common(data, "Member")
    assert isinstance(data["medicaid_id"], str) and data["medicaid_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["recovery_approach"] in ("SUBROGATION", "REIMBURSEMENT")
    assert data["status"] in ("ACTIVE", "DECEASED")
    assert data["date_of_death"] is None or isinstance(data["date_of_death"], str)


def assert_tpl_case(data: dict):
    _assert_common(data, "TplCase")
    assert is_valid_uuid(data.get("member_id", "")), "TplCase.member_id must be a UUID"
    assert isinstance(data["attorney_name"], str)
    assert isinstance(data["attorney_email"], str)
    assert isinstance(data["injury_date"], str)
    assert isinstance(data["third_party_insurer"], str)
    assert data["status"] in (
        "IDENTIFIED", "ATTORNEY_NOTIFIED", "LIEN_FILED", "SETTLEMENT_PENDING",
        "RESOLVED", "CLOSED_NO_RECOVERY", "SOL_EXPIRED",
    )
    assert data["litigation_status"] in (
        "NO_SUIT", "SUIT_FILED", "JUDGMENT", "SUIT_DISMISSED",
    )
    assert isinstance(data["sol_date"], str)
    assert data["attorney_notified_at"] is None or isinstance(
        data["attorney_notified_at"], str
    )
    assert isinstance(data["total_paid_claims_cents"], int)
    assert isinstance(data["total_recovered_cents"], int)


def assert_expense_claim(data: dict):
    _assert_common(data, "ExpenseClaim")
    assert is_valid_uuid(data.get("case_id", "")), "ExpenseClaim.case_id must be a UUID"
    assert isinstance(data["service_date"], str)
    assert isinstance(data["paid_amount_cents"], int)
    assert isinstance(data["claim_reference"], str)
    assert isinstance(data["included_in_lien_basis"], bool)


def assert_lien(data: dict):
    _assert_common(data, "Lien")
    assert is_valid_uuid(data.get("case_id", "")), "Lien.case_id must be a UUID"
    assert isinstance(data["lien_amount_cents"], int)
    assert isinstance(data["statutory_cap_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    assert data["status"] in ("FILED", "AMENDED", "SATISFIED", "RELEASED", "EXPIRED")
    assert isinstance(data["amended_count"], int)


def assert_settlement(data: dict):
    _assert_common(data, "Settlement")
    assert is_valid_uuid(data.get("case_id", "")), "Settlement.case_id must be a UUID"
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["status"] in (
        "OFFERED", "COUNTERED", "ACCEPTED", "REJECTED", "DISBURSED",
    )
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["litigation_costs_cents"], int)
    assert data["offered_by"] in ("INSURER", "STATE")
    assert isinstance(data["fee_amount_cents"], int)
    assert isinstance(data["cost_share_cents"], int)
    assert isinstance(data["state_recovery_cents"], int)
    assert isinstance(data["member_net_cents"], int)
    assert data["accepted_at"] is None or isinstance(data["accepted_at"], str)


def assert_recovery_posting(data: dict):
    _assert_common(data, "RecoveryPosting")
    assert is_valid_uuid(data.get("settlement_id", ""))
    assert is_valid_uuid(data.get("lien_id", ""))
    assert isinstance(data["contractor_code"], str)
    assert isinstance(data["gross_recovery_cents"], int)
    assert data["commission_cents"] is None or isinstance(data["commission_cents"], int)
    assert data["net_to_state_cents"] is None or isinstance(
        data["net_to_state_cents"], int
    )
    assert data["status"] in ("PENDING", "POSTED", "REVERSED")


def assert_estate_case(data: dict):
    _assert_common(data, "EstateCase")
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["date_of_death"], str)
    assert isinstance(data["lifetime_paid_cents"], int)
    assert data["probate_case_number"] is None or isinstance(
        data["probate_case_number"], str
    )
    assert data["exempt_services_cents"] is None or isinstance(
        data["exempt_services_cents"], int
    )
    assert isinstance(data["provisional_claim_cents"], int)
    assert data["claim_amount_cents"] is None or isinstance(
        data["claim_amount_cents"], int
    )
    assert isinstance(data["claim_outstanding_cents"], int)
    assert isinstance(data["total_paid_cents"], int)
    assert data["status"] in ("OPENED", "CLAIM_FILED", "PAID", "WAIVED", "TIME_BARRED")


def assert_hardship_waiver(data: dict):
    _assert_common(data, "HardshipWaiver")
    assert is_valid_uuid(data.get("estate_case_id", ""))
    assert data["waiver_type"] in ("FULL", "PARTIAL")
    assert isinstance(data["household_income_annual_cents"], int)
    assert isinstance(data["homestead_value_cents"], int)
    assert data["requested_reduction_cents"] is None or isinstance(
        data["requested_reduction_cents"], int
    )
    assert data["decided_reduction_cents"] is None or isinstance(
        data["decided_reduction_cents"], int
    )
    assert isinstance(data["appeal_count"], int)
    assert data["status"] in ("PENDING", "APPROVED", "DENIED", "RESCINDED")


def assert_communication_notice(data: dict):
    _assert_common(data, "CommunicationNotice")
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["case_id"] is None or isinstance(data["case_id"], str)
    assert data["estate_case_id"] is None or isinstance(data["estate_case_id"], str)
    assert data["notice_type"] in (
        "LIEN_FILED_NOTICE", "SETTLEMENT_NOTICE", "CASE_RESOLUTION_NOTICE",
        "ESTATE_CLAIM_NOTICE", "ESTATE_DECISION_NOTICE",
    )
    assert data["status"] in ("QUEUED", "DELIVERED", "FAILED")
    assert isinstance(data["due_date"], str)
    assert data["sent_at"] is None or isinstance(data["sent_at"], str)
    assert data["is_late"] is None or isinstance(data["is_late"], bool)


def assert_lien_outstanding_invariant(lien: dict, posted_gross_cents: int):
    """Domain invariant (PRD §3.5): outstanding == amount less posted recoveries."""
    assert lien["outstanding_cents"] == lien["lien_amount_cents"] - posted_gross_cents, (
        f"Lien outstanding {lien['outstanding_cents']} != "
        f"{lien['lien_amount_cents']} - {posted_gross_cents}"
    )


def assert_settlement_split_identity(settlement: dict):
    """Domain invariant (PRD §3.4): gross partitions into fee + costs + recovery + net."""
    total = (
        settlement["fee_amount_cents"]
        + settlement["litigation_costs_cents"]
        + settlement["state_recovery_cents"]
        + settlement["member_net_cents"]
    )
    assert total == settlement["gross_amount_cents"], (
        f"Settlement split {total} does not partition gross "
        f"{settlement['gross_amount_cents']}"
    )
