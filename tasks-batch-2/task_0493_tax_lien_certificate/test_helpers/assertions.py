"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')}"


def assert_county(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["max_interest_rate_bps"], int)
    assert isinstance(data["bid_down_increment_bps"], int)
    assert isinstance(data["redemption_period_days"], int)
    assert isinstance(data["penalty_rate_bps"], int)
    assert isinstance(data["sub_tax_interest_rate_bps"], int)
    assert isinstance(data["premium_bidding_enabled"], bool)
    assert isinstance(data["premium_earns_interest"], bool)
    assert data["day_count_basis"] in (360, 365)


def assert_parcel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["apn"], str)
    assert isinstance(data["owner_name"], str)
    assert isinstance(data["assessed_value_cents"], int) and data["assessed_value_cents"] >= 0
    assert isinstance(data["base_tax_due_cents"], int) and data["base_tax_due_cents"] >= 1
    assert data["status"] in (
        "DELINQUENT", "ON_SALE", "LIENED", "REDEEMED", "DEEDED"
    )


def assert_investor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["tax_id"], str)
    assert isinstance(data["escrow_balance_cents"], int)
    assert isinstance(data["deposit_total_cents"], int)
    assert isinstance(data["registered"], bool)
    assert data["escrow_balance_cents"] >= 0, "escrow_balance_cents must never go negative"


def assert_tax_sale(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sale_name"], str)
    assert data["sale_type"] in ("RATE_BID_DOWN", "PREMIUM")
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED", "SETTLED")
    assert isinstance(data["listing_count"], int) and data["listing_count"] >= 0


def assert_sale_listing(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["parcel_id"], str)
    assert isinstance(data["opening_rate_bps"], int)
    assert data["status"] in ("LISTED", "SOLD", "STRUCK_OFF", "WITHDRAWN")


def assert_bid(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["investor_id"], str)
    assert data["status"] in ("PLACED", "WON", "LOST", "REFUNDED")


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["county_id"], str)
    assert isinstance(data["parcel_id"], str)
    assert isinstance(data["listing_id"], str)
    assert isinstance(data["holder_investor_id"], str)
    assert isinstance(data["face_amount_cents"], int) and data["face_amount_cents"] >= 1
    assert isinstance(data["rate_bps"], int)
    assert isinstance(data["premium_cents"], int)
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["redeem_deadline_at"])
    assert isinstance(data["sub_tax_total_cents"], int)
    assert isinstance(data["assignment_seq"], int) and data["assignment_seq"] >= 0
    assert data["status"] in ("ACTIVE", "FORECLOSURE_PENDING", "REDEEMED", "DEEDED")


def assert_subsequent_tax(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["certificate_id"], str)
    assert isinstance(data["investor_id"], str)
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] >= 1
    assert is_iso8601_timestamp(data["posted_at"])
    assert data["status"] in ("POSTED", "REDEEMED")


def assert_redemption(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["certificate_id"], str)
    assert is_iso8601_timestamp(data["redeemed_at"])
    for fld in (
        "face_payoff_cents", "face_interest_cents", "penalty_cents",
        "sub_tax_payoff_cents", "sub_tax_interest_cents",
        "premium_refund_cents", "total_payoff_cents",
    ):
        assert isinstance(data[fld], int), f"{fld} must be an integer"
        assert data[fld] >= 0, f"{fld} must be non-negative"


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["certificate_id"], str)
    assert isinstance(data["from_investor_id"], str)
    assert isinstance(data["to_investor_id"], str)
    assert isinstance(data["consideration_cents"], int) and data["consideration_cents"] >= 0
    assert isinstance(data["seq"], int) and data["seq"] >= 1
    assert data["status"] == "RECORDED"


def assert_deed_application(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["certificate_id"], str)
    assert isinstance(data["applicant_investor_id"], str)
    assert isinstance(data["deed_cost_cents"], int) and data["deed_cost_cents"] >= 0
    assert isinstance(data["minimum_bid_cents"], int)
    assert data["status"] in ("FILED", "AWARDED", "CANCELLED")


def assert_surplus_distribution(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["deed_application_id"], str)
    assert isinstance(data["certificate_id"], str)
    assert isinstance(data["gross_proceeds_cents"], int)
    assert isinstance(data["lien_satisfied_cents"], int)
    assert isinstance(data["surplus_cents"], int)
    assert isinstance(data["claimed"], bool)


def assert_surplus_conserves_gross(data: dict):
    """Waterfall invariant (PRD §3.11): lien_satisfied + surplus == gross."""
    assert data["lien_satisfied_cents"] + data["surplus_cents"] == data["gross_proceeds_cents"], (
        "lien_satisfied_cents + surplus_cents must equal gross_proceeds_cents "
        f"(got {data['lien_satisfied_cents']} + {data['surplus_cents']} != "
        f"{data['gross_proceeds_cents']})"
    )
