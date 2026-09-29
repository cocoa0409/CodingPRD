"""Per-entity shape assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

DATE_LEN = len("YYYY-MM-DD")

POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
ORDER_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "ACCEPTED",
    "REJECTED",
    "SUSPENDED",
    "RUNNING",
    "COMPLETED",
    "CANCELLED",
]
PAYMENT_STATUSES = ["UNBILLED", "INVOICED", "PAID", "REFUND_DUE", "REFUNDED"]
SPOT_STATUSES = ["SCHEDULED", "AIRED", "PREEMPTED", "CANCELLED"]
ADVERTISER_STATUSES = [
    "SUBMITTED",
    "UNDER_REVIEW",
    "INFO_REQUESTED",
    "CLASSIFIED_CANDIDATE",
    "CLASSIFIED_ISSUE",
    "CLASSIFICATION_REJECTED",
]


def _assert_identity(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be an ISO 8601 UTC timestamp"


def _assert_versioned(data: dict, entity: str):
    _assert_identity(data, entity)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer of at least 1"
    )


def _assert_date(value, field):
    assert isinstance(value, str) and len(value) == DATE_LEN and value[4] == "-", (
        f"{field} must be a YYYY-MM-DD calendar date, got {value!r}"
    )


def assert_station(data: dict):
    _assert_versioned(data, "Station")
    assert isinstance(data["call_sign"], str) and data["call_sign"]
    assert isinstance(data["licensee_name"], str)
    assert isinstance(data["market_code"], str)
    assert isinstance(data["political_file_posting_deadline_hours"], int)
    assert data["political_file_posting_deadline_hours"] >= 1
    assert isinstance(data["daily_political_seconds_cap"], int)
    assert data["daily_political_seconds_cap"] >= 30
    assert data["eo_parity_basis"] in ["SPOT_COUNT", "DOLLAR_VALUE"]
    for counter in (
        "pending_file_entry_count",
        "overdue_file_entry_count",
        "late_posting_count",
        "open_complaint_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"Station.{counter} must be a non-negative integer"
        )
    assert data["compliance_posture"] in POSTURES


def assert_station_posture(data: dict):
    """The posture is the larger of the two breach counters, never their sum."""
    breach = max(data["overdue_file_entry_count"], data["open_complaint_count"])
    expected = "FROZEN" if breach >= 2 else ("RESTRICTED" if breach >= 1 else "OPEN")
    assert data["compliance_posture"] == expected, (
        f"posture must be {expected} at overdue={data['overdue_file_entry_count']} "
        f"and open complaints={data['open_complaint_count']}, "
        f"got {data['compliance_posture']}"
    )


def assert_election(data: dict):
    _assert_versioned(data, "Election")
    assert is_valid_uuid(data["station_id"])
    assert data["election_type"] in ["PRIMARY", "GENERAL", "RUNOFF", "SPECIAL"]
    _assert_date(data["election_date"], "Election.election_date")
    _assert_date(data["window_start_date"], "Election.window_start_date")
    _assert_date(data["window_end_date"], "Election.window_end_date")
    assert data["window_end_date"] == data["election_date"], (
        "window_end_date is simply equal to the election_date"
    )
    assert data["luc_window_days"] in [45, 60]
    assert data["status"] in ["SCHEDULED", "WINDOW_OPEN", "CLOSED"]


def assert_advertiser(data: dict):
    _assert_versioned(data, "Advertiser")
    assert is_valid_uuid(data["station_id"])
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["requested_class"] in ["CANDIDATE", "ISSUE"]
    assert data["status"] in ADVERTISER_STATUSES
    assert isinstance(data["review_round"], int) and 0 <= data["review_round"] <= 3
    assert isinstance(data["entitled_to_luc"], bool)
    assert data["entitled_to_luc"] == (data["status"] == "CLASSIFIED_CANDIDATE"), (
        "entitled_to_luc reads true if and only if the advertiser is CLASSIFIED_CANDIDATE"
    )


def assert_rate_class(data: dict):
    _assert_versioned(data, "RateClass")
    assert is_valid_uuid(data["station_id"])
    assert data["daypart"] in [
        "MORNING",
        "DAYTIME",
        "EARLY_NEWS",
        "PRIME",
        "LATE_NIGHT",
    ]
    assert isinstance(data["preemptible"], bool)
    assert isinstance(data["posted_rate_cents"], int) and data["posted_rate_cents"] >= 1
    priority = data["preemption_priority"]
    assert isinstance(priority, int)
    if data["preemptible"]:
        assert 1 <= priority <= 5, "preemption_priority is 1..5 on a preemptible class"
    else:
        assert priority == 0, "preemption_priority is exactly 0 on a fixed class"
    assert data["status"] in ["ACTIVE", "WITHDRAWN"]


def assert_order(data: dict):
    _assert_versioned(data, "CommercialOrder")
    assert is_valid_uuid(data["station_id"])
    assert is_valid_uuid(data["advertiser_id"])
    assert is_valid_uuid(data["rate_class_id"])
    assert data["payment_terms"] in ["PREPAY", "NET_30"]
    assert isinstance(data["agency_placed"], bool)
    assert data["disclosure_status"] in ["MISSING", "NONCONFORMING", "CONFORMING"]
    assert data["status"] in ORDER_STATUSES
    assert data["payment_status"] in PAYMENT_STATUSES
    for money in (
        "gross_charge_cents",
        "agency_commission_cents",
        "net_due_cents",
        "rebate_total_cents",
        "paid_cents",
        "refunded_cents",
    ):
        assert isinstance(data[money], int), f"CommercialOrder.{money} must be integer cents"
        assert data[money] >= 0, f"CommercialOrder.{money} must not be negative"
    assert isinstance(data["spot_count"], int) and data["spot_count"] >= 0


def assert_order_money_invariants(data: dict):
    """net_due_cents is gross plus commission, and no amount carries a fraction."""
    assert data["net_due_cents"] == data["gross_charge_cents"] + data["agency_commission_cents"], (
        "net_due_cents is gross_charge_cents plus agency_commission_cents"
    )
    if not data["agency_placed"]:
        assert data["agency_commission_cents"] == 0, (
            "agency_commission_cents is zero when agency_placed is false"
        )


def assert_spot(data: dict):
    _assert_versioned(data, "ScheduledSpot")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["rate_class_id"])
    _assert_date(data["air_date"], "ScheduledSpot.air_date")
    assert isinstance(data["start_offset_seconds"], int)
    assert 0 <= data["start_offset_seconds"] <= 86399
    assert data["duration_seconds"] in [30, 60]
    assert data["status"] in SPOT_STATUSES
    assert isinstance(data["charged_rate_cents"], int) and data["charged_rate_cents"] >= 0
    assert isinstance(data["unit_equivalent_rate_cents"], int)
    assert data["unit_equivalent_rate_cents"] >= 0
    assert isinstance(data["luc_capped"], bool)


def assert_unit_equivalent_normalisation(data: dict):
    """unit_equivalent_rate_cents is charged_rate_cents normalised to thirty seconds."""
    expected = round_half_up(data["charged_rate_cents"] * 30 / data["duration_seconds"])
    assert data["unit_equivalent_rate_cents"] == expected, (
        f"unit_equivalent_rate_cents must be {expected} for a "
        f"{data['duration_seconds']}-second spot charged {data['charged_rate_cents']}"
    )


def assert_file_entry(data: dict):
    _assert_versioned(data, "PoliticalFileEntry")
    assert is_valid_uuid(data["station_id"])
    assert is_valid_uuid(data["order_id"])
    assert data["event_type"] in [
        "ORDER_ACCEPTED",
        "RATE_ADJUSTMENT",
        "EQUAL_OPPORTUNITY_RESPONSE",
    ]
    assert is_iso8601_timestamp(data["event_occurred_at"])
    assert is_iso8601_timestamp(data["due_at"])
    assert data["posting_status"] in ["PENDING", "POSTED", "LATE_POSTED", "OVERDUE"]
    assert isinstance(data["late_by_seconds"], int) and data["late_by_seconds"] >= 0


def assert_eo_request(data: dict):
    _assert_versioned(data, "EqualOpportunityRequest")
    assert is_valid_uuid(data["station_id"])
    assert is_valid_uuid(data["requesting_advertiser_id"])
    assert is_valid_uuid(data["trigger_order_id"])
    assert is_iso8601_timestamp(data["received_at"])
    assert is_iso8601_timestamp(data["response_due_at"])
    assert data["status"] in ["RECEIVED", "GRANTED", "DENIED", "EXPIRED"]
    assert isinstance(data["owed_units"], int) and data["owed_units"] >= 0
    assert isinstance(data["fulfilled_units"], int) and data["fulfilled_units"] >= 0


def assert_luc_determination(data: dict):
    _assert_versioned(data, "LucDetermination")
    assert is_valid_uuid(data["station_id"])
    assert is_valid_uuid(data["election_id"])
    assert is_valid_uuid(data["rate_class_id"])
    assert data["variant"] in ["PROVISIONAL", "FINAL"]
    assert data["basis"] in ["LOWEST_QUALIFYING_SPOT", "POSTED_RATE_FALLBACK"]
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]
    assert isinstance(data["luc_cents"], int) and data["luc_cents"] >= 0
    assert isinstance(data["qualifying_spot_count"], int)
    assert isinstance(data["repriced_spot_count"], int)
    assert isinstance(data["rebate_total_cents"], int)
    _assert_date(data["window_start_date"], "LucDetermination.window_start_date")
    _assert_date(data["window_end_date"], "LucDetermination.window_end_date")
    assert is_iso8601_timestamp(data["computed_at"])
    if data["basis"] == "POSTED_RATE_FALLBACK":
        assert data["basis_spot_id"] is None
        assert data["qualifying_spot_count"] == 0


def assert_rebate_entry(data: dict):
    """The rebate ledger is immutable: it carries only id and created_at."""
    _assert_identity(data, "RebateLedgerEntry")
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["reason"] in ["LUC_FINAL_REPRICE", "SPOT_PREEMPTED", "ORDER_CANCELLED"]
    assert is_iso8601_timestamp(data["occurred_at"])
    assert "updated_at" not in data, (
        "a rebate ledger entry carries no updated_at at all"
    )
    assert "version" not in data, "a rebate ledger entry carries no version at all"


def assert_complaint(data: dict):
    _assert_versioned(data, "FccComplaint")
    assert is_valid_uuid(data["station_id"])
    assert isinstance(data["complainant_name"], str) and data["complainant_name"]
    assert data["allegation_code"] in [
        "LUC_OVERCHARGE",
        "FILE_TIMELINESS",
        "EQUAL_OPPORTUNITY_DENIED",
        "DISCLOSURE_DEFECT",
    ]
    assert is_iso8601_timestamp(data["filed_at"])
    assert is_iso8601_timestamp(data["response_due_at"])
    assert data["status"] in ["OPEN", "RESPONDED", "REOPENED", "CLOSED"]
    assert isinstance(data["late_response"], bool)


def round_half_up(value: float) -> int:
    """Resolve a fractional cent by rounding half away from zero."""
    import math

    return int(math.floor(value + 0.5)) if value >= 0 else -int(math.floor(-value + 0.5))
