"""Entity assertions and domain invariant checkers.

Validate response structures against the PRD contract. All persisted resources
carry id/created_at/updated_at/version (§2.4). Monetary amounts are integer
cents (§2.8).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


CASE_STATUSES = ["DRAFT", "FILED", "MEETING_HELD", "CONFIRMED", "DISCHARGED", "DISMISSED"]
STAY_POSTURES = ["NONE", "ACTIVE", "LIFTED_PARTIAL", "TERMINATED"]
MEANS_RESULTS = ["NOT_RUN", "PRESUMPTION_OK", "PRESUMPTION_ABUSE"]
DEBT_CLASSES = ["SECURED", "PRIORITY", "UNSECURED"]
SCHEDULE_LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]


def _assert_audit_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_case(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in CASE_STATUSES, f"unexpected status {data.get('status')}"
    assert data["stay_posture"] in STAY_POSTURES, f"unexpected stay_posture {data.get('stay_posture')}"
    assert data["means_test_result"] in MEANS_RESULTS
    assert data["filed_chapter"] in ["CHAPTER_7", "CHAPTER_13"]
    assert isinstance(data["total_exempt_value_cents"], int)
    assert isinstance(data["nonexempt_estate_cents"], int)
    assert data["nonexempt_estate_cents"] >= 0, "nonexempt estate is floored at 0"


def assert_debtor(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["prior_discharge_within_8y"], bool)


def assert_means_test(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["annualized_cmi_cents"], int)
    assert isinstance(data["disposable_monthly_cents"], int)
    assert data["disposable_monthly_cents"] >= 0, "disposable income never below zero"
    assert data["result"] in MEANS_RESULTS


def assert_schedule(data: dict):
    _assert_audit_fields(data)
    assert data["schedule_letter"] in SCHEDULE_LETTERS
    assert isinstance(data["asset_value_cents"], int) and data["asset_value_cents"] >= 0
    assert isinstance(data["claimed_exempt_value_cents"], int) and data["claimed_exempt_value_cents"] >= 0


def assert_debt(data: dict):
    _assert_audit_fields(data)
    assert data["debt_class"] in DEBT_CLASSES
    assert isinstance(data["scheduled_amount_cents"], int) and data["scheduled_amount_cents"] >= 1
    assert isinstance(data["allowed_amount_cents"], int)


def assert_creditor(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0


def assert_trustee(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0


def assert_meeting(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ["SCHEDULED", "HELD"]


def assert_claim(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ["FILED", "ALLOWED", "DISALLOWED"]
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] >= 1
    assert isinstance(data["allowed_amount_cents"], int)


def assert_plan(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ["DRAFT", "FILED", "CONFIRMED", "DENIED", "COMPLETED"]
    assert isinstance(data["is_active"], bool)
    assert isinstance(data["total_committed_cents"], int)
    assert isinstance(data["paid_to_date_cents"], int)
    assert (data["total_committed_cents"]
            == data["monthly_payment_cents"] * data["plan_duration_months"]), \
        "total_committed = monthly_payment * duration_months"


def assert_plan_payment(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert is_iso8601_timestamp(data.get("applied_at", "")), "applied_at must be ISO 8601"


def assert_motion(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ["PENDING", "GRANTED", "DENIED"]


# ─── Domain invariant checkers ───────────────────────────────────────────

def assert_estate_split_conserved(case: dict, gross_asset_cents: int):
    """Estate conservation (§3.8 monetary precision / §3.10 discharge settlement):
    nonexempt is floored at 0; when exempt <= gross the split conserves gross.
    """
    exempt = case["total_exempt_value_cents"]
    nonexempt = case["nonexempt_estate_cents"]
    assert nonexempt >= 0, "nonexempt estate floored at 0"
    if exempt <= gross_asset_cents:
        assert exempt + nonexempt == gross_asset_cents, \
            f"exempt {exempt} + nonexempt {nonexempt} should equal gross {gross_asset_cents}"
    else:
        assert nonexempt == 0, "over-claimed exemptions floor nonexempt at 0"


def assert_fund_conserved(distribution: dict, surplus_cents: int, paid_to_date_cents: int):
    """Fund conservation (§3.8): every cent of paid_to_date is conserved across
    the waterfall — sum(distribution) + surplus == paid_to_date.
    """
    distributed = sum(distribution.values())
    assert distributed + surplus_cents == paid_to_date_cents, \
        f"distributed {distributed} + surplus {surplus_cents} should equal {paid_to_date_cents}"
