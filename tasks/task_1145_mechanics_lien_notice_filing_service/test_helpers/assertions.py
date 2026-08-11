"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer counter"


def assert_company(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["prepaid_balance_cents"], int)
    assert isinstance(data["open_notice_count"], int)


def assert_jurisdiction_rule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["project_type"] in [
        "COMMERCIAL_PRIVATE", "RESIDENTIAL_PRIVATE", "STATE_PUBLIC", "FEDERAL_PUBLIC",
    ]
    assert data["status"] in ["PUBLISHED", "SUPERSEDED"]
    assert isinstance(data["prelim_days"], int)
    assert data["prelim_day_basis"] in ["CALENDAR", "BUSINESS"]
    assert isinstance(data["filing_window_days"], int)
    assert isinstance(data["foreclosure_deadline_days"], int)


def assert_project(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("company_id", "")), "company_id must be a UUID"
    assert data["research_status"] in ["UNRESEARCHED", "RESEARCHED", "VERIFIED"]
    assert data["lien_posture"] in ["CLEAR", "NOTICED", "ENCUMBERED", "LITIGATION"]
    assert isinstance(data["open_notice_count"], int)
    assert isinstance(data["open_lien_count"], int)
    assert isinstance(data["contract_value_cents"], int)
    assert isinstance(data["approved_extras_cents"], int)
    assert isinstance(data["retainage_held_cents"], int)


def assert_party(data: dict):
    _assert_common_fields(data)
    assert data["party_role"] in ["OWNER", "GC", "LENDER", "HIRER", "SURETY"]
    assert data["research_status"] in ["PENDING", "VERIFIED", "FAILED"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]


def assert_furnishing_span(data: dict):
    _assert_common_fields(data)
    assert data["span_kind"] in ["BASE_CONTRACT", "CHANGE_ORDER", "PUNCH_LIST", "WARRANTY"]
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)


def assert_notice_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "SERVED", "PROOF_CONFIRMED", "DELIVERY_FAILED", "EXPIRED",
    ]
    assert data["delivery_method"] in [
        "CERTIFIED_MAIL", "PERSONAL_SERVICE", "EMAIL_STATUTORY",
    ]
    assert isinstance(data["fee_cents"], int)


def assert_lien_claim(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "AMOUNT_LOCKED", "FILED", "RELEASED",
        "BONDED_OFF", "FORECLOSED", "EXPIRED",
    ]
    assert isinstance(data["verified_paid_cents"], int)
    assert isinstance(data["effective_waiver_cents"], int)
    assert isinstance(data["waived_to_extras_cents"], int)
    assert isinstance(data["waived_to_contract_cents"], int)


def assert_waiver(data: dict):
    _assert_common_fields(data)
    assert data["waiver_type"] in [
        "CONDITIONAL_PROGRESS", "UNCONDITIONAL_PROGRESS",
        "CONDITIONAL_FINAL", "UNCONDITIONAL_FINAL",
    ]
    assert data["status"] in ["RECEIVED", "APPLIED", "VOIDED"]
    assert isinstance(data["amount_cents"], int)


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PENDING", "VERIFIED"]
    assert isinstance(data["amount_cents"], int)


def assert_bonding_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["REQUESTED", "BOND_RECORDED", "REJECTED"]
    assert isinstance(data["bond_amount_cents"], int)


def assert_foreclosure_referral(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "SENT", "ACCEPTED", "DECLINED", "SUIT_FILED", "CANCELLED",
    ]
    assert isinstance(data["counsel_name"], str) and data["counsel_name"]


def assert_stop_notice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "SERVED", "RELEASED", "EXPIRED"]
    assert isinstance(data["amount_cents"], int)


def assert_bond_claim(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "PAID", "DENIED", "EXPIRED"]
    assert isinstance(data["amount_cents"], int)


def assert_claim_amounts_conserve_gross(claim: dict):
    """PRD §3.5 invariant: final == gross - verified payments - effective waivers,
    so verified_paid + effective_waiver + final must equal the gross snapshot
    for an AMOUNT_LOCKED claim under an UNCAPPED rule."""
    total = (
        claim["verified_paid_cents"]
        + claim["effective_waiver_cents"]
        + claim["final_amount_cents"]
    )
    assert total == claim["gross_snapshot_cents"], (
        f"Money not conserved: verified {claim['verified_paid_cents']} + waivers "
        f"{claim['effective_waiver_cents']} + final {claim['final_amount_cents']} "
        f"!= gross {claim['gross_snapshot_cents']}"
    )
