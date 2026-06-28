"""Entity assertions and domain invariant checkers (Country Club Membership API)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_ACCOUNT_STATES = ["PENDING", "ACTIVE", "SUSPENDED", "RESIGNED_PENDING", "RESIGNED"]
_BILLING_STATES = ["CURRENT", "PAST_DUE", "DELINQUENT"]
_CATEGORY_CODES = ["GOLF", "SOCIAL", "CORPORATE"]
_RESOURCE_KINDS = ["TEE_TIME", "COURT", "DINING_TABLE"]
_RESERVATION_STATES = ["CONFIRMED", "AMEND_PENDING", "CANCELLED", "COMPLETED"]
_CHIT_KINDS = ["DINING", "PRO_SHOP", "GUEST_FEE", "EVENT"]
_CHIT_STATES = ["POSTED", "SETTLED", "VOIDED"]
_GUEST_STATES = ["REGISTERED", "CHECKED_IN", "CANCELLED"]
_ASSESSMENT_STATES = ["DRAFT", "LEVIED", "CANCELLED"]
_ALLOCATION_BASES = ["EQUAL", "DUES_WEIGHTED"]
_WAITLIST_STATES = ["WAITING", "OFFERED", "ACCEPTED", "DECLINED", "EXPIRED"]
_STATEMENT_STATES = ["OPEN", "FINALIZED", "PAID"]


def _assert_audit(data: dict) -> None:
    """Full audit set: id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_club(data: dict) -> None:
    _assert_audit(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["billing_period_index"], int)
    assert isinstance(data["closed_through_period_index"], int)
    assert isinstance(data["fb_minimum_carryover_allowed"], bool)
    assert isinstance(data["resignation_refund_pct"], int)
    assert isinstance(data["guest_visits_cap_per_period"], int)


def assert_category(data: dict) -> None:
    _assert_audit(data)
    assert data["code"] in _CATEGORY_CODES, f"code must be one of {_CATEGORY_CODES}"
    assert isinstance(data["initiation_fee_cents"], int)
    assert isinstance(data["refundable_equity_cents"], int)
    assert data["refundable_equity_cents"] <= data["initiation_fee_cents"], \
        "refundable_equity_cents must not exceed initiation_fee_cents"
    assert isinstance(data["monthly_dues_cents"], int)
    assert isinstance(data["fb_minimum_cents"], int)
    assert isinstance(data["capacity"], int)
    assert isinstance(data["guest_fee_cents"], int)
    assert isinstance(data["allows_golf"], bool)
    assert isinstance(data["active_member_count"], int) and data["active_member_count"] >= 0


def assert_membership(data: dict) -> None:
    _assert_audit(data)
    assert data["account_status"] in _ACCOUNT_STATES
    assert data["billing_status"] in _BILLING_STATES
    assert isinstance(data["charge_balance_cents"], int) and data["charge_balance_cents"] >= 0, \
        "charge_balance_cents is never below 0"
    assert isinstance(data["fb_spend_period_cents"], int) and data["fb_spend_period_cents"] >= 0
    assert isinstance(data["refund_owed_cents"], int) and data["refund_owed_cents"] >= 0
    assert isinstance(data["holder_name"], str) and len(data["holder_name"]) > 0


def assert_resource(data: dict) -> None:
    _assert_audit(data)
    assert data["kind"] in _RESOURCE_KINDS
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["turnaround_minutes"], int)
    assert isinstance(data["seat_capacity"], int)


def assert_reservation(data: dict) -> None:
    _assert_audit(data)
    assert data["status"] in _RESERVATION_STATES
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at must be ISO 8601"
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1


def assert_chit(data: dict) -> None:
    _assert_audit(data)
    assert data["kind"] in _CHIT_KINDS
    assert data["status"] in _CHIT_STATES
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["counts_toward_fb"], bool)
    assert isinstance(data["period_index"], int)
    # counts_toward_fb is true iff kind == DINING (PRD §3.5).
    assert data["counts_toward_fb"] == (data["kind"] == "DINING")


def assert_guest_pass(data: dict) -> None:
    _assert_audit(data)
    assert data["status"] in _GUEST_STATES
    assert isinstance(data["guest_name"], str) and len(data["guest_name"]) > 0


def assert_assessment(data: dict) -> None:
    _assert_audit(data)
    assert data["status"] in _ASSESSMENT_STATES
    assert data["allocation_basis"] in _ALLOCATION_BASES
    assert isinstance(data["total_target_cents"], int)
    assert isinstance(data["levied_amount_cents"], int)


def assert_assessment_charge(data: dict) -> None:
    """Append-only record: id + created_at only, no updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["amount_cents"], int)


def assert_waitlist_entry(data: dict) -> None:
    _assert_audit(data)
    assert data["status"] in _WAITLIST_STATES
    assert isinstance(data["applicant_name"], str) and len(data["applicant_name"]) > 0


def assert_statement(data: dict) -> None:
    _assert_audit(data)
    assert data["status"] in _STATEMENT_STATES
    assert isinstance(data["period_index"], int)
    for field in ("dues_cents", "fb_minimum_cents", "fb_spend_cents", "fb_shortfall_cents",
                  "chit_charges_cents", "assessment_cents", "total_due_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer cents value"


def assert_statement_breakdown_consistent(data: dict) -> None:
    """total_due = dues + fb_shortfall + chit_charges + assessment (PRD §3.7)."""
    expected = (data["dues_cents"] + data["fb_shortfall_cents"]
                + data["chit_charges_cents"] + data["assessment_cents"])
    assert data["total_due_cents"] == expected, (
        f"total_due_cents {data['total_due_cents']} != "
        f"dues+shortfall+chits+assessment {expected}"
    )
