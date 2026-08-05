"""Entity assertions and domain invariant checkers for the Residential Parking
Permit Zone API. Uses the framework's generic validators internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


ZONE_STATUSES = ["ACTIVE", "SUSPENDED"]
HOUSEHOLD_STATUSES = ["ACTIVE", "SUSPENDED"]
PROOF_STATUSES = ["UNVERIFIED", "VERIFIED", "EXPIRED"]
VEHICLE_STATUSES = ["ACTIVE", "REMOVED"]
PROOF_SUBMISSION_STATUSES = ["PENDING", "VERIFIED", "REJECTED"]
APPLICATION_STATUSES = ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "WAITLISTED", "DENIED"]
PERMIT_STATUSES = ["ACTIVE", "SUSPENDED", "RENEWAL_PENDING", "EXPIRED", "REVOKED", "TRANSFERRED", "REFUNDED"]
VISITOR_PASS_STATUSES = ["ACTIVE", "EXPIRED", "CANCELLED"]
WAITLIST_STATUSES = ["WAITING", "PROMOTED", "CANCELLED", "EXPIRED"]
CITATION_STATUSES = ["ISSUED", "PAID", "DISPUTED", "UPHELD", "DISMISSED"]
COMPLAINT_STATUSES = ["OPEN", "RESOLVED", "DISMISSED", "ESCALATED"]


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_zone(data: dict):
    _common(data)
    assert data["status"] in ZONE_STATUSES, f"bad zone status {data['status']}"
    for f in ("permit_capacity", "max_permits_per_household", "guest_pass_daily_limit",
              "permit_annual_fee_cents", "visitor_pass_fee_cents", "active_permit_count",
              "waitlist_count", "fees_collected_cents", "fees_refunded_cents"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["active_permit_count"] >= 0
    assert data["fees_collected_cents"] >= 0
    assert data["fees_refunded_cents"] >= 0
    assert isinstance(data["zone_code"], str) and len(data["zone_code"]) > 0


def assert_household(data: dict):
    _common(data)
    assert data["status"] in HOUSEHOLD_STATUSES
    assert data["proof_status"] in PROOF_STATUSES
    assert isinstance(data["active_permit_count"], int) and data["active_permit_count"] >= 0
    assert isinstance(data["unit_address"], str)


def assert_vehicle(data: dict):
    _common(data)
    assert data["status"] in VEHICLE_STATUSES
    assert isinstance(data["license_plate"], str) and len(data["license_plate"]) > 0


def assert_proof_submission(data: dict):
    _common(data)
    assert data["status"] in PROOF_SUBMISSION_STATUSES
    assert data["document_type"] in ["LEASE", "UTILITY_BILL", "DEED", "ID_CARD"]


def assert_permit_application(data: dict):
    _common(data)
    assert data["status"] in APPLICATION_STATUSES


def assert_permit(data: dict):
    _common(data)
    assert data["status"] in PERMIT_STATUSES
    assert isinstance(data["fee_paid_cents"], int) and data["fee_paid_cents"] >= 0
    assert isinstance(data["refund_amount_cents"], int) and data["refund_amount_cents"] >= 0
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"


def assert_visitor_pass(data: dict):
    _common(data)
    assert data["status"] in VISITOR_PASS_STATUSES
    assert data["pass_type"] in ["GUEST_DAILY", "TEMPORARY"]
    assert isinstance(data["fee_charged_cents"], int) and data["fee_charged_cents"] >= 0


def assert_waitlist_entry(data: dict):
    _common(data)
    assert data["status"] in WAITLIST_STATUSES
    assert isinstance(data["position"], int) and data["position"] >= 1


def assert_citation(data: dict):
    _common(data)
    assert data["status"] in CITATION_STATUSES
    assert data["violation_type"] in ["NO_PERMIT", "EXPIRED_PERMIT", "ZONE_VIOLATION"]
    assert data["fine_variant"] in ["STANDARD", "REPEAT_OFFENDER"]
    assert isinstance(data["fine_amount_cents"], int) and data["fine_amount_cents"] >= 0
    assert isinstance(data["prior_upheld_count"], int) and data["prior_upheld_count"] >= 0


def assert_complaint(data: dict):
    _common(data)
    assert data["status"] in COMPLAINT_STATUSES
    assert data["complaint_type"] in ["ILLEGAL_PARKING", "PERMIT_ABUSE", "SIGNAGE", "OTHER"]


# --------------------------------------------------------------------------
# Domain invariant checkers (conserved quantities — PRD §2.9)
# --------------------------------------------------------------------------
def assert_fee_ledger_invariant(zone: dict, permits: list):
    """net = fees_collected_cents - fees_refunded_cents must equal the sum over
    permits of (fee_paid_cents - refund_amount_cents). PRD §2.9."""
    net = zone["fees_collected_cents"] - zone["fees_refunded_cents"]
    per_permit = sum(p["fee_paid_cents"] - p.get("refund_amount_cents", 0) for p in permits)
    assert net == per_permit, f"fee ledger not conserved: zone net {net} != per-permit sum {per_permit}"


def assert_slot_count(zone: dict, expected: int):
    assert zone["active_permit_count"] == expected, (
        f"expected active_permit_count {expected}, got {zone['active_permit_count']}"
    )
