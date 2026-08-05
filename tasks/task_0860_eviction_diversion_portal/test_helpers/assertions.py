"""Entity assertions and domain invariant checkers for the Eviction Diversion Portal."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common_versioned(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _common_lightweight(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "lightweight record must NOT carry version"
    assert "updated_at" not in data, "lightweight record must NOT carry updated_at"


def assert_court(data: dict):
    _common_versioned(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["jurisdiction_code"], str)
    assert isinstance(data["hearing_daily_capacity"], int) and data["hearing_daily_capacity"] >= 1
    assert isinstance(data["hearings_scheduled_count"], int) and data["hearings_scheduled_count"] >= 0


def assert_landlord(data: dict):
    _common_lightweight(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["email"], str)


def assert_tenant(data: dict):
    _common_lightweight(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["household_income_cents"], int) and data["household_income_cents"] >= 0
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1


def assert_officer(data: dict):
    _common_lightweight(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["badge_number"], str)
    assert isinstance(data["agency"], str)


def assert_case(data: dict):
    _common_versioned(data)
    assert data["filing_type"] in ("NONPAYMENT", "HOLDOVER", "NUISANCE")
    assert isinstance(data["claimed_arrears_cents"], int) and data["claimed_arrears_cents"] >= 0
    assert isinstance(data["net_arrears_cents"], int) and data["net_arrears_cents"] >= 0
    assert is_iso8601_timestamp(data["answer_due_at"])
    assert data["status"] in (
        "FILED", "SERVED", "ANSWERED", "DEFAULTED", "IN_DIVERSION", "IN_LITIGATION",
        "JUDGMENT_ENTERED", "ENFORCEMENT", "CLOSED_ENFORCED", "DIVERSION_SATISFIED", "DISMISSED",
    )
    assert data["outcome"] in (
        "PENDING", "DIVERTED", "JUDGMENT_FOR_LANDLORD", "DISMISSED", "ENFORCED",
    )
    assert isinstance(data["sealed"], bool)


def assert_answer(data: dict):
    _common_lightweight(data)
    assert is_valid_uuid(data.get("case_id", "")), "answer.case_id must be a UUID"
    assert isinstance(data["defenses"], list)
    assert isinstance(data["rent_withheld_cents"], int) and data["rent_withheld_cents"] >= 0
    assert isinstance(data["is_late"], bool)


def assert_referral(data: dict):
    _common_versioned(data)
    assert data["referral_type"] in ("LEGAL_AID", "RENTAL_ASSISTANCE")
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "DISBURSED")
    assert isinstance(data["requested_amount_cents"], int) and data["requested_amount_cents"] >= 0
    assert isinstance(data["disbursed_amount_cents"], int) and data["disbursed_amount_cents"] >= 0


def assert_mediation_session(data: dict):
    _common_versioned(data)
    assert data["status"] in ("SCHEDULED", "HELD", "AGREEMENT", "IMPASSE")
    assert is_iso8601_timestamp(data["scheduled_at"])


def assert_payment_plan(data: dict):
    _common_versioned(data)
    assert data["proposed_by"] in ("LANDLORD", "TENANT")
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 1
    assert isinstance(data["installment_count"], int) and data["installment_count"] >= 1
    assert data["status"] in (
        "PROPOSED", "COUNTERED", "ACCEPTED", "REJECTED", "WITHDRAWN", "COMPLETED", "DEFAULTED",
    )
    assert data["current_proposer"] in ("LANDLORD", "TENANT", None)


def assert_installment(data: dict):
    _common_versioned(data)
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert is_iso8601_timestamp(data["due_date"])
    assert data["status"] in ("DUE", "PAID", "MISSED")


def assert_hearing(data: dict):
    _common_versioned(data)
    assert data["hearing_type"] in ("INITIAL", "TRIAL", "ENFORCEMENT")
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["continuance_count"], int) and data["continuance_count"] >= 0
    assert data["status"] in ("SCHEDULED", "HELD", "CONTINUED", "CANCELLED")


def assert_judgment(data: dict):
    _common_versioned(data)
    assert data["judgment_type"] in ("POSSESSION", "DISMISSAL", "DIVERSION")
    assert isinstance(data["money_amount_cents"], int) and data["money_amount_cents"] >= 0
    assert data["status"] in ("ENTERED", "STAYED", "VACATED", "SATISFIED")


def assert_lockout_order(data: dict):
    _common_versioned(data)
    assert data["status"] in ("REQUESTED", "SCHEDULED", "EXECUTED", "CANCELLED")


def assert_sealing_request(data: dict):
    _common_versioned(data)
    assert data["basis"] in ("DISMISSAL", "DIVERSION", "TIME_ELAPSED")
    assert data["status"] in ("REQUESTED", "GRANTED", "DENIED")


# --------------------------------------------------------------------------- #
# Domain invariant checkers                                                    #
# --------------------------------------------------------------------------- #
def assert_arrears_conservation(case: dict, paid_sum: int, disbursed_sum: int):
    """§2.9: net_arrears_cents + paid installments + disbursed assistance == claimed
    (floored at 0). Holds while claimed >= paid + disbursed."""
    assert case["net_arrears_cents"] == max(0, case["claimed_arrears_cents"] - paid_sum - disbursed_sum), (
        f"arrears conservation broken: net={case['net_arrears_cents']} "
        f"claimed={case['claimed_arrears_cents']} paid={paid_sum} disbursed={disbursed_sum}"
    )


def assert_court_slot_invariant(court: dict, scheduled_count: int):
    """§2.9: a court's hearings_scheduled_count equals the number of SCHEDULED hearings on it."""
    assert court["hearings_scheduled_count"] == scheduled_count, (
        f"court slot invariant broken: count={court['hearings_scheduled_count']} "
        f"expected={scheduled_count}"
    )
