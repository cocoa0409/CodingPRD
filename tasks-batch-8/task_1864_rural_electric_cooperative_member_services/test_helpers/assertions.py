"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_cooperative(data: dict):
    _assert_common(data, "Cooperative")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("fiscal_year_end_month"), int)
    assert isinstance(data.get("capital_credits_pool_cents"), int)
    assert isinstance(data.get("retirement_methods_allowed"), list)
    assert isinstance(data.get("unclaimed_dormancy_years"), int)
    assert isinstance(data.get("irrigation_season_start_month"), int)
    assert isinstance(data.get("irrigation_season_end_month"), int)


def assert_member(data: dict):
    _assert_common(data, "Member")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert data.get("member_type") in ("RESIDENTIAL", "COMMERCIAL", "IRRIGATION")
    assert data.get("status") in ("APPLICANT", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data.get("capital_credit_balance_cents"), int)
    assert isinstance(data.get("unclaimed_credit_cents"), int)
    assert isinstance(data.get("patronage_base_kwh"), int)
    assert isinstance(data.get("patronage_base_irrigation_kwh"), int)
    assert isinstance(data.get("district_id"), int)


def assert_service_location(data: dict):
    _assert_common(data, "ServiceLocation")
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("address"), str)
    assert data.get("rate_class") in (
        "RESIDENTIAL", "COMMERCIAL_GENERAL", "COMMERCIAL_DEMAND", "IRRIGATION", "SEASONAL",
    )
    assert data.get("status") in ("PENDING_CONSTRUCTION", "ENERGIZED", "DISCONNECTED", "REMOVED")


def assert_rate_schedule(data: dict):
    _assert_common(data, "RateSchedule")
    assert isinstance(data.get("code"), str) and data["code"]
    assert data.get("status") in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    assert isinstance(data.get("customer_charge_cents"), int)
    assert isinstance(data.get("tiers"), list) and len(data["tiers"]) > 0


def assert_meter_reading(data: dict):
    # Append-only resource: id + created_at only; no version / updated_at (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "MeterReading.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "MeterReading.created_at must be ISO 8601"
    assert "version" not in data, "MeterReading must not expose version"
    assert "updated_at" not in data, "MeterReading must not expose updated_at"
    assert isinstance(data.get("service_location_id"), str)
    assert isinstance(data.get("kwh_register"), int)
    assert data.get("source") in ("AMR", "MANUAL", "ESTIMATED")


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert isinstance(data.get("service_location_id"), str)
    assert data.get("status") in ("PROVISIONAL", "FINALIZED", "PAID", "WRITTEN_OFF", "VOID")
    assert data.get("variant") in ("PROVISIONAL", "FINAL")
    for f in ("kwh_billed", "energy_charge_cents", "demand_charge_cents",
              "load_management_credit_cents", "total_due_cents"):
        assert isinstance(data.get(f), int), f"Invoice.{f} must be an integer"
    assert data["total_due_cents"] >= 0, "total_due_cents floored at zero"


def assert_allocation(data: dict):
    _assert_common(data, "CapitalCreditAllocation")
    assert isinstance(data.get("cooperative_id"), str)
    assert isinstance(data.get("fiscal_year"), int)
    assert data.get("status") in ("DRAFT", "APPROVED", "POSTED", "VOIDED")
    assert data.get("method") in ("PATRONAGE_WEIGHTED", "FLAT_PER_MEMBER")
    assert isinstance(data.get("total_allocated_cents"), int)


def assert_allocation_line(data: dict):
    _assert_common(data, "CapitalCreditAllocationLine")
    assert isinstance(data.get("allocation_id"), str)
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("allocated_cents"), int)
    assert isinstance(data.get("weight_kwh_effective"), (int, float))


def assert_retirement(data: dict):
    _assert_common(data, "CapitalCreditRetirement")
    assert isinstance(data.get("cooperative_id"), str)
    assert data.get("status") in ("PROPOSED", "BOARD_APPROVED", "EXECUTING", "SETTLED", "ABORTED")
    assert data.get("method") in ("FIFO_OLDEST", "PRO_RATA_PERCENTAGE")
    assert isinstance(data.get("total_retire_cents"), int)


def assert_payout(data: dict):
    _assert_common(data, "CapitalCreditPayout")
    assert isinstance(data.get("retirement_id"), str)
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("payout_cents"), int)
    assert data.get("status") in ("PENDING", "ISSUED", "CASHED", "UNCLAIMED", "ESCHEATED")


def assert_outage_report(data: dict):
    _assert_common(data, "OutageReport")
    assert isinstance(data.get("service_location_id"), str)
    assert data.get("status") in (
        "REPORTED", "ACKNOWLEDGED", "CREW_DISPATCHED", "RESTORED", "DUPLICATE", "CANCELLED",
    )
    assert data.get("cause") in ("WEATHER", "EQUIPMENT", "VEGETATION", "ANIMAL", "UNKNOWN")
    assert isinstance(data.get("notified_member_count"), int)


def assert_row_agreement(data: dict):
    _assert_common(data, "RightOfWayAgreement")
    assert isinstance(data.get("service_location_id"), str)
    assert data.get("status") in (
        "REQUESTED", "MEMBER_CONSENTED", "RECORDED", "CONTESTED", "CONDEMNATION", "RELEASED",
    )


def assert_device(data: dict):
    _assert_common(data, "LoadManagementDevice")
    assert isinstance(data.get("service_location_id"), str)
    assert data.get("device_type") in ("WATER_HEATER", "IRRIGATION_INTERRUPTIBLE", "AC_CYCLER")
    assert data.get("status") in ("ENROLLED", "ACTIVE", "SUSPENDED", "UNENROLLED")
    assert isinstance(data.get("monthly_credit_cents"), int)


def assert_service_order(data: dict):
    _assert_common(data, "ServiceOrder")
    assert isinstance(data.get("service_location_id"), str)
    assert data.get("order_type") in ("NEW_SERVICE", "UPGRADE", "RELOCATION", "TEMPORARY")
    assert data.get("status") in (
        "DRAFT", "ESTIMATED", "ATC_INVOICED", "PAID", "SCHEDULED",
        "CONSTRUCTED", "ENERGIZED", "CANCELLED",
    )
    assert isinstance(data.get("aid_to_construction_cents"), int)


def assert_election(data: dict):
    _assert_common(data, "BoardElection")
    assert isinstance(data.get("cooperative_id"), str)
    assert isinstance(data.get("year"), int)
    assert data.get("status") in (
        "DRAFT", "NOMINATION_OPEN", "NOMINATION_CLOSED", "VOTING_OPEN",
        "VOTING_CLOSED", "CERTIFIED", "VOIDED",
    )
    assert isinstance(data.get("seats"), list)
    assert isinstance(data.get("quorum_met"), bool)


def assert_ballot(data: dict):
    # Append-only resource: id + created_at only (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "Ballot.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Ballot.created_at must be ISO 8601"
    assert "version" not in data, "Ballot must not expose version"
    assert "updated_at" not in data, "Ballot must not expose updated_at"
    assert isinstance(data.get("election_id"), str)
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("district"), int)
    assert isinstance(data.get("candidate_name"), str)
    assert isinstance(data.get("is_proxy"), bool)
