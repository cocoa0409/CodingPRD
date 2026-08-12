"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ---------------------------------------------------------------------------
# Per-entity shape assertions — used to confirm a returned resource carries
# the fields the PRD specifies. Tests typically assert a subset of fields.
# ---------------------------------------------------------------------------

def assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_network(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("call_sign"), str) and data["call_sign"]
    assert isinstance(data.get("primary_feed_tz"), str) and data["primary_feed_tz"]
    assert isinstance(data.get("current_period_index"), int)
    assert data.get("posture") in ("NORMAL", "SWEEP_LOCKDOWN", "DISPUTE_FREEZE")


def assert_station_group(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("group_name"), str) and data["group_name"]
    assert data.get("leverage_tier") in ("SMALL", "MID", "LARGE", "MAJOR")
    assert isinstance(data.get("aggregate_retrans_cents"), int)


def assert_station(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("call_sign"), str) and data["call_sign"]
    assert isinstance(data.get("dma_code"), str) and data["dma_code"]
    assert data.get("posture") in ("CLEARANCE_OK", "CLEARANCE_DEFICIENT", "DARK")


def assert_territory(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("dma_code"), str) and data["dma_code"]
    assert is_iso8601_timestamp(data.get("protection_window_start_utc", ""))
    assert is_iso8601_timestamp(data.get("protection_window_end_utc", ""))


def assert_agreement(data: dict):
    assert_common_fields(data)
    assert data.get("status") in (
        "DRAFT", "PENDING_ACTIVATION", "ACTIVE", "EXPIRING",
        "RENEWAL_NEGOTIATION", "LAPSED", "TERMINATED",
    )
    assert isinstance(data.get("clearance_obligation_hours"), int)
    assert isinstance(data.get("renewal_round_count"), int)


def assert_program(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data.get("avail_minutes_total"), int)
    assert isinstance(data.get("avail_minutes_local_allocatable"), int)


def assert_clearance_report(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("DRAFT", "FILED", "AUDITED", "CLEARED", "DISPUTED")
    assert isinstance(data.get("period_index"), int)


def assert_preemption(data: dict):
    assert_common_fields(data)
    assert data.get("status") in (
        "SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED", "COUNTERED", "WITHDRAWN",
    )
    assert isinstance(data.get("counter_round_count"), int)


def assert_avail_allocation(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("CLAIMED", "CONFIRMED", "REVOKED", "EXPIRED")
    assert isinstance(data.get("local_minutes_claimed"), int)


def assert_retrans_settlement(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("DRAFT", "COMMITTED", "RECONCILED", "VOID")
    assert isinstance(data.get("gross_retrans_cents"), int)


def assert_outage_event(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("REPORTED", "CONFIRMED", "REJECTED")
    assert data.get("cause") in (
        "TRANSMITTER_FAILURE", "FIBER_CUT", "SATELLITE_JAM",
        "POWER_LOSS", "PLANNED_MAINTENANCE",
    )


def assert_outage_credit(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("PENDING", "APPLIED", "FORFEITED")
    assert isinstance(data.get("credit_cents"), int)


def assert_renewal_offer(data: dict):
    assert_common_fields(data)
    assert data.get("status") in (
        "PROPOSED", "COUNTERED", "ACCEPTED", "REJECTED", "WITHDRAWN", "SUPERSEDED",
    )
    assert data.get("proposed_by_role") in (
        "NETWORK_AFFILIATE_RELATIONS", "STATION_GROUP_OWNER",
    )
    assert isinstance(data.get("round_index"), int)


def assert_compliance_report(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("OPEN", "SUBMITTED", "AUDITED", "PASSED", "FAILED")
    assert data.get("report_kind") in (
        "FCC_302", "CHILDRENS_TELEVISION", "EEO", "POLITICAL_FILE",
    )


def assert_exclusivity_claim(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ("FILED", "VALIDATED", "DISMISSED", "SETTLED")
