"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """PRD §2.4: every resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"


def assert_grower(data: dict):
    _assert_common(data)
    assert isinstance(data["grower_code"], str) and data["grower_code"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["performance_rating"] is None or isinstance(
        data["performance_rating"], (int, float))
    assert isinstance(data["loan_outstanding_cents"], int)
    assert isinstance(data["house_count"], int)


def assert_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("grower_id", ""))
    assert isinstance(data["contract_no"], str) and data["contract_no"]
    assert isinstance(data["base_pay_cents_per_lb"], int)
    assert data["base_pay_cents_per_lb"] > 0
    assert isinstance(data["committed_house_count"], int)
    assert isinstance(data["term_start_date"], str)
    assert isinstance(data["term_end_date"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "RENEWAL_PENDING", "RENEWED",
                              "EXPIRED", "TERMINATED")
    assert isinstance(data["upgrade_required"], bool)


def assert_house(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("grower_id", ""))
    assert isinstance(data["house_no"], str) and data["house_no"]
    assert isinstance(data["capacity_birds"], int) and data["capacity_birds"] > 0
    assert data["house_status"] in ("ACTIVE", "PLACED", "DOWNTIME",
                                    "QUARANTINED", "DECOMMISSIONED")
    assert data["downtime_until"] is None or isinstance(data["downtime_until"], str)


def assert_flock(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("house_id", ""))
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("settlement_group_id", ""))
    assert isinstance(data["flock_no"], str) and data["flock_no"]
    assert isinstance(data["placed_head"], int)
    assert data["status"] in ("PLANNED", "PLACED", "GROWING", "CATCH_SCHEDULED",
                              "HARVESTED", "SETTLED", "CONDEMNED_LOSS")
    assert isinstance(data["feed_delivered_lbs"], int)
    assert isinstance(data["mortality_head"], int)
    assert isinstance(data["condemnation_head"], int)
    assert isinstance(data["live_weight_lbs"], int)
    assert data["adj_fcr"] is None or isinstance(data["adj_fcr"], (int, float))
    assert data["livability_pct"] is None or isinstance(
        data["livability_pct"], (int, float))
    assert isinstance(data["condemnation_pct"], (int, float))
    assert data["performance_score"] is None or isinstance(
        data["performance_score"], (int, float))


def assert_placement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("flock_id", ""))
    assert isinstance(data["scheduled_date"], str)
    assert isinstance(data["head_count"], int) and data["head_count"] > 0
    assert data["status"] in ("SCHEDULED", "CONFIRMED", "CANCELLED")
    assert data["confirmed_date"] is None or isinstance(data["confirmed_date"], str)


def assert_feed_delivery(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("flock_id", ""))
    assert isinstance(data["delivered_date"], str)
    assert isinstance(data["feed_lbs"], int) and data["feed_lbs"] > 0
    assert data["feed_type"] in ("STARTER", "GROWER", "FINISHER", "WITHDRAWAL")
    assert isinstance(data["ticket_no"], str) and data["ticket_no"]


def assert_mortality_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("flock_id", ""))
    assert isinstance(data["report_date"], str)
    assert isinstance(data["dead_head"], int) and data["dead_head"] >= 0
    assert isinstance(data["condemned_head"], int) and data["condemned_head"] >= 0


def assert_catch_schedule(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("flock_id", ""))
    assert is_valid_uuid(data.get("crew_id", ""))
    assert isinstance(data["catch_date"], str)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_catch_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["crew_code"], str) and data["crew_code"]
    assert isinstance(data["max_catches_per_day"], int)
    assert data["max_catches_per_day"] > 0


def assert_weight_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("flock_id", ""))
    assert isinstance(data["ticket_no"], str) and data["ticket_no"]
    assert isinstance(data["weighed_at"], str)
    assert isinstance(data["live_weight_lbs"], int) and data["live_weight_lbs"] > 0


def assert_biosecurity_audit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("house_id", ""))
    assert isinstance(data["audit_date"], str)
    assert data["result"] in ("PASS", "FAIL")


def assert_settlement_group(data: dict):
    _assert_common(data)
    assert isinstance(data["group_code"], str) and data["group_code"]
    assert isinstance(data["week_ending_date"], str)
    assert data["status"] in ("OPEN", "LOCKED", "SETTLED")
    for field in ("group_avg_fcr", "group_avg_livability_pct",
                  "group_avg_condemnation_pct"):
        assert data[field] is None or isinstance(data[field], (int, float)), \
            f"{field} must be null or numeric, got {data[field]!r}"


def assert_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("flock_id", ""))
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("PENDING", "APPROVED", "PAID", "DISPUTED")
    for field in ("base_amount_cents", "fcr_bonus_cents",
                  "condemnation_deduction_cents", "loan_repayment_cents",
                  "net_amount_cents"):
        assert isinstance(data[field], int), f"{field} must be whole-cent int"
    # PRD §3.8: net = base + bonus - deduction - repayment.
    assert data["net_amount_cents"] == (
        data["base_amount_cents"] + data["fcr_bonus_cents"]
        - data["condemnation_deduction_cents"] - data["loan_repayment_cents"]
    ), "net_amount_cents must equal base + bonus - deduction - repayment"


def assert_grower_loan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("grower_id", ""))
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] > 0
    assert isinstance(data["recovery_pct"], int)
    assert 1 <= data["recovery_pct"] <= 50
    assert isinstance(data["outstanding_cents"], int)
    assert data["status"] in ("ISSUED", "REPAID", "CLOSED")
    assert data["purpose"] in ("CAPITAL_UPGRADE", "OPERATING")
