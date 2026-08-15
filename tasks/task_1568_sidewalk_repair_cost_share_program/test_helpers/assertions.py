"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_SEGMENT_STATES = ["IN_SERVICE", "FLAGGED", "UNDER_NOTICE",
                   "REPAIR_IN_PROGRESS", "RESTORED"]
_DEFECT_STATES = ["OPEN", "AWAITING_FORESTRY", "UNDER_REPAIR", "VERIFIED"]
_NOTICE_STATES = ["DRAFT", "ISSUED", "UNDER_APPEAL", "COMPLIANT", "DELINQUENT",
                  "CITY_REPAIR_SCHEDULED", "CITY_REPAIR_COMPLETED", "LIENED",
                  "CLOSED", "VOID"]
_REVIEW_STATES = ["SUBMITTED", "APPROVED", "DENIED", "RETURNED", "OBLIGATED",
                  "REIMBURSED", "EXPIRED", "WITHDRAWN", "CANCELLED"]
_PAYMENT_STATES = ["UNFUNDED", "RESERVED", "DISBURSED", "RELEASED"]
_BATCH_STATES = ["OPEN_FOR_ITEMS", "SEALED_FOR_BIDDING", "AWARDED",
                 "WORK_IN_PROGRESS", "COMPLETED", "CANCELLED"]
_ITEM_STATES = ["POOLED", "SCHEDULED", "WORK_COMPLETED", "VERIFIED", "REMOVED"]
_BID_STATES = ["SUBMITTED", "SUPERSEDED", "WITHDRAWN", "AWARDED", "NOT_AWARDED"]
_LIEN_STATES = ["ASSESSED", "RECORDED", "PARTIALLY_PAID", "SATISFIED",
                "FORECLOSURE_REFERRED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_program_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["cycle_year"], int)
    assert isinstance(data["appropriation_cents"], int)
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["disbursed_cents"], int)
    assert isinstance(data["available_cents"], int)
    assert data["status"] in ["OPEN", "LOCKED", "CLOSED"]


def assert_funds_identity(cycle: dict):
    """The program ledger identity must hold after every mutation (PRD §2.8)."""
    assert cycle["appropriation_cents"] == (
        cycle["committed_cents"] + cycle["disbursed_cents"]
        + cycle["available_cents"]
    ), (
        "funds identity violated: "
        f"{cycle['appropriation_cents']} != {cycle['committed_cents']} + "
        f"{cycle['disbursed_cents']} + {cycle['available_cents']}"
    )


def assert_property_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["hardship_tier"] in ["NONE", "SENIOR_65", "LOW_INCOME"]


def assert_parcel(data: dict):
    _assert_common(data)
    assert isinstance(data["parcel_number"], str) and data["parcel_number"]
    assert data["street_class"] in ["LOCAL", "COLLECTOR", "ARTERIAL"]
    assert data["owner_responsibility_pct"] in (0, 100)
    assert isinstance(data["delinquency_flag"], bool)


def assert_segment(data: dict):
    _assert_common(data)
    assert isinstance(data["segment_code"], str) and data["segment_code"]
    assert data["open_defect_count"] >= 0
    assert data["status"] in _SEGMENT_STATES


def assert_defect(data: dict):
    _assert_common(data)
    assert data["defect_type"] in [
        "VERTICAL_SEPARATION", "HORIZONTAL_OPENING", "SPALLING", "SETTLEMENT",
        "TREE_ROOT_UPHEAVAL", "CRUMBLED_JOINT",
    ]
    assert data["severity_class"] in ["MINOR", "MAJOR", "TRIP_HAZARD"]
    assert data["status"] in _DEFECT_STATES
    assert isinstance(data["recorded_by_inspector_id"], str)


def assert_notice(data: dict):
    _assert_common(data)
    assert data["status"] in _NOTICE_STATES
    assert data["appeal_status"] in ["NONE", "PENDING", "UPHELD", "REVERSED"]
    assert isinstance(data["defect_ids"], list)


def assert_application(data: dict):
    _assert_common(data)
    assert data["review_status"] in _REVIEW_STATES
    assert data["payment_status"] in _PAYMENT_STATES
    assert isinstance(data["share_pct"], int)
    assert isinstance(data["provisional_award_cents"], int)


def assert_batch(data: dict):
    _assert_common(data)
    assert data["status"] in _BATCH_STATES
    assert isinstance(data["estimated_total_cents"], int)


def assert_work_item(data: dict):
    _assert_common(data)
    assert data["status"] in _ITEM_STATES
    assert isinstance(data["includes_ramp_upgrade"], bool)


def assert_contractor(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["is_suspended"], bool)


def assert_bid(data: dict):
    _assert_common(data)
    assert data["status"] in _BID_STATES
    assert isinstance(data["unit_rate_cents"], int)
    assert isinstance(data["evaluated_total_cents"], int)


def assert_forestry_review(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "DECIDED", "CLEARED"]
    assert data["decision"] in ["PENDING", "PRUNE_APPROVED", "REMOVAL_ORDERED",
                                "NO_CITY_CONFLICT"]


def assert_lien(data: dict):
    _assert_common(data)
    assert data["status"] in _LIEN_STATES
    assert isinstance(data["owner_principal_cents"], int)
    assert isinstance(data["principal_remaining_cents"], int)
    assert isinstance(data["accrued_interest_cents"], int)


def assert_inspection_record(data: dict):
    """Append-only row: id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "InspectionRecord must not carry updated_at"
    assert "version" not in data, "InspectionRecord must not carry version"
    assert data["result"] in ["PASS", "FAIL"]
