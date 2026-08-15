"""Entity assertions and domain invariant checkers (PRD sections 2.5, 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """PRD 2.5: primary resources carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_event_fields(data: dict):
    """PRD 2.5: immutable records carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable record must not expose updated_at"
    assert "version" not in data, "immutable record must not expose version"


def assert_originator(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["sec_codes_allowed"], list)
    assert isinstance(data["exposure_limit_cents"], int)
    assert isinstance(data["fee_discount_bps"], int)
    assert data["status"] in ["PENDING_UNDERWRITING", "ACTIVE", "WATCH",
                              "SUSPENDED", "TERMINATED"]
    assert isinstance(data["unauth_rate_bps_trailing"], int)
    assert isinstance(data["unauth_rate_bps_mtd"], int)
    assert isinstance(data["outstanding_exposure_gross_cents"], int)
    assert isinstance(data["outstanding_exposure_debit_cents"], int)


def assert_cutoff_window(data: dict):
    _assert_common_fields(data)
    assert data["window_kind"] in ["SAME_DAY_1", "SAME_DAY_2", "SAME_DAY_3",
                                   "NEXT_DAY"]
    for field in ("per_entry_fee_cents", "file_fee_cents",
                  "large_entry_surcharge_cents"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_ach_file(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("originator_id", "")), \
        "originator_id must be a valid UUID"
    assert data["sec_code"] in ["PPD", "CCD", "WEB", "TEL"]
    assert data["requested_window_kind"] in ["SAME_DAY_1", "SAME_DAY_2",
                                             "SAME_DAY_3", "NEXT_DAY"]
    assert isinstance(data["effective_date"], str)
    assert data["status"] in ["WAREHOUSED", "RELEASED", "DISPATCHED", "SETTLED",
                              "CANCELLED", "REJECTED"]
    assert isinstance(data["entry_count"], int) and data["entry_count"] >= 0
    assert isinstance(data["total_amount_cents"], int)
    assert isinstance(data["quoted_fee_cents"], int)
    if data["status"] in ("RELEASED", "DISPATCHED", "SETTLED"):
        assert data["assigned_window_kind"] in ["SAME_DAY_1", "SAME_DAY_2",
                                                "SAME_DAY_3", "NEXT_DAY"]
        assert isinstance(data["settlement_date"], str)
        assert is_valid_uuid(data.get("settlement_batch_id", "")), \
            "settlement_batch_id must be a valid UUID once released"
        assert isinstance(data["assessed_fee_cents"], int)


def assert_ach_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("file_id", "")), "file_id must be a valid UUID"
    assert data["direction"] in ["DEBIT", "CREDIT"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["receiver_account"], str)
    assert isinstance(data["receiver_routing"], str)
    assert isinstance(data["representment_count"], int) \
        and 0 <= data["representment_count"] <= 2
    assert data["status"] in ["WAREHOUSED", "TRANSMITTED", "SETTLED", "RETURNED",
                              "CLOSED", "CANCELLED"]


def assert_return_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("entry_id", "")), "entry_id must be a valid UUID"
    assert data["return_code"] in ["R01", "R02", "R05", "R07", "R10"]
    assert is_iso8601_timestamp(data.get("received_at", "")), \
        "received_at must be ISO 8601"
    assert isinstance(data["is_unauthorized"], bool)
    assert data["is_unauthorized"] == (data["return_code"] in ("R05", "R07", "R10"))
    assert isinstance(data["representment_number"], int) \
        and 0 <= data["representment_number"] <= 2
    assert isinstance(data["gl_posted"], bool)
    assert data["disposition"] in ["OPEN", "REPRESENTED", "FINAL"]


def assert_noc_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("entry_id", "")), "entry_id must be a valid UUID"
    assert data["noc_code"] in ["C01", "C02", "C03"]
    assert isinstance(data["corrected_data"], str)
    assert is_iso8601_timestamp(data.get("received_at", "")), \
        "received_at must be ISO 8601"
    assert isinstance(data["due_date"], str) and len(data["due_date"]) == 10
    assert isinstance(data["late_applied"], bool)
    assert data["status"] in ["RECEIVED", "OVERDUE", "APPLIED"]


def assert_reversal_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("entry_id", "")), "entry_id must be a valid UUID"
    assert data["reason"] in ["DUPLICATE_ENTRY", "WRONG_AMOUNT", "WRONG_ACCOUNT"]
    assert is_iso8601_timestamp(data.get("requested_at", "")), \
        "requested_at must be ISO 8601"
    assert isinstance(data["window_expires_at"], str) \
        and len(data["window_expires_at"]) == 10
    assert data["status"] in ["REQUESTED", "TRANSMITTED", "SETTLED", "CANCELLED"]


def assert_return_rate_snapshot(data: dict):
    _assert_event_fields(data)
    assert is_valid_uuid(data.get("originator_id", "")), \
        "originator_id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("computed_at", "")), \
        "computed_at must be ISO 8601"
    for field in ("unauth_returns_60d", "debits_60d", "unauth_returns_mtd",
                  "debits_mtd", "rate_bps_trailing_60d", "rate_bps_mtd"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["breach"], bool)


def assert_risk_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("originator_id", "")), \
        "originator_id must be a valid UUID"
    assert data["source"] in ["RATE_BREACH", "MANUAL"]
    assert data["status"] in ["OPEN", "RESOLVED"]
    if data["status"] == "RESOLVED":
        assert data["resolution_action"] in ["SUSPEND", "WATCH", "REINSTATE",
                                             "TERMINATE", "DISMISS"]
        assert isinstance(data["resolved_by_user_id"], str) \
            and data["resolved_by_user_id"]


def assert_settlement_batch(data: dict):
    _assert_common_fields(data)
    assert data["window_kind"] in ["SAME_DAY_1", "SAME_DAY_2", "SAME_DAY_3",
                                   "NEXT_DAY"]
    assert isinstance(data["settlement_date"], str)
    assert data["status"] in ["OPEN", "DISPATCHED", "SETTLED", "RECONCILED"]
    if data["status"] in ("DISPATCHED", "SETTLED", "RECONCILED"):
        assert isinstance(data["expected_net_cents"], int)
        assert isinstance(data["dispatched_by_user_id"], str) \
            and data["dispatched_by_user_id"]
    if data["status"] in ("SETTLED", "RECONCILED"):
        assert isinstance(data["posted_net_cents"], int)
    if data["status"] == "RECONCILED":
        assert isinstance(data["reconciled_by_user_id"], str) \
            and data["reconciled_by_user_id"]


def assert_gl_posting(data: dict):
    _assert_event_fields(data)
    assert is_valid_uuid(data.get("settlement_batch_id", "")), \
        "settlement_batch_id must be a valid UUID"
    assert data["account_code"] in ["SETTLEMENT_CLEARING", "ORIGINATOR_RECEIVABLE",
                                    "FEE_INCOME"]
    assert isinstance(data["debit_cents"], int) and data["debit_cents"] >= 0
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0
    # PRD 3.5: exactly one of debit_cents or credit_cents is greater than zero.
    assert (data["debit_cents"] > 0) != (data["credit_cents"] > 0), \
        "exactly one of debit_cents/credit_cents must be > 0 per ledger row"
    assert is_iso8601_timestamp(data.get("posted_at", "")), \
        "posted_at must be ISO 8601"


def assert_gl_trial_balance(postings: list):
    """PRD 3.5 invariant: balanced pairs keep sum(debit) == sum(credit)."""
    total_debits = sum(p["debit_cents"] for p in postings)
    total_credits = sum(p["credit_cents"] for p in postings)
    assert total_debits == total_credits, (
        f"Trial balance broken: debits {total_debits} != credits {total_credits}")
    return total_debits
