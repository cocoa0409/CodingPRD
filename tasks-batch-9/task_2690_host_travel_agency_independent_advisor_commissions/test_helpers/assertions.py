"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

MONEY_FIELDS_NEVER_NEGATIVE = (
    "gross_sale_cents",
    "non_commissionable_cents",
    "deposit_amount_cents",
    "expected_commission_cents",
    "received_commission_cents",
    "shortfall_cents",
    "settled_share_cents",
    "chargeback_amount_cents",
)


def assert_common_fields(data: dict):
    """PRD §2.4: every persisted resource carries an id that is a server-minted
    UUID string with no type prefix and a created_at timestamp in ISO 8601 UTC
    format; most resources additionally carry updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_append_only_fields(data: dict):
    """PRD §2.4: a trust ledger row exposes only id and created_at alongside its
    own fields, carrying neither updated_at nor version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "a trust ledger line must not carry updated_at"
    assert "version" not in data, "a trust ledger line must not carry version"


def assert_list_meta(meta: dict, expected_total: int = None, expected_has_more: bool = None):
    """PRD §2.3: the meta block carries limit and offset as applied, total_count
    before pagination and has_more as a boolean."""
    assert isinstance(meta.get("limit"), int), "meta.limit must be an integer"
    assert isinstance(meta.get("offset"), int), "meta.offset must be an integer"
    assert isinstance(meta.get("total_count"), int), "meta.total_count must be an integer"
    assert isinstance(meta.get("has_more"), bool), "meta.has_more must be a boolean"
    if expected_total is not None:
        assert (
            meta["total_count"] == expected_total
        ), f"expected total_count {expected_total}, got {meta['total_count']}"
    if expected_has_more is not None:
        assert (
            meta["has_more"] is expected_has_more
        ), f"expected has_more {expected_has_more}, got {meta['has_more']}"


def assert_created_at_ascending(rows: list):
    """PRD §2.3: list results are ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows must be in created_at ascending order: {stamps}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_split_schedule(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["tiers"], list) and len(data["tiers"]) >= 1
    assert isinstance(data["platform_fee_tiers"], list) and len(data["platform_fee_tiers"]) >= 1
    floors = [tier["min_production_cents"] for tier in data["tiers"]]
    assert floors == sorted(floors), "the production ladder is stored sorted by min_production_cents ascending"
    fee_floors = [tier["min_share_cents"] for tier in data["platform_fee_tiers"]]
    assert fee_floors == sorted(fee_floors), "the fee ladder is stored sorted by min_share_cents ascending"
    assert 0 <= data["chargeback_retention_pct"] < 1


def assert_consortium(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["membership_fee_cents"] >= 0
    assert 0 <= data["marketing_fund_accrual_pct"] < 1
    assert 0 <= data["consortium_channel_bonus_pct"] < 1
    assert data["marketing_fund_balance_cents"] >= 0


def assert_supplier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["accreditation_scheme"] in ["IATA", "CLIA", "ARC", "TIDS"]
    assert 0 < data["base_commission_pct"] < 1
    assert 0 < data["preferred_override_commission_pct"] < 1
    assert 0 < data["rate_ceiling_pct"] <= 1
    assert data["max_commission_per_booking_cents"] > 0
    assert data["remit_terms_days"] >= 0
    assert data["program_status"] in ["STANDARD", "PREFERRED", "PROBATION"]
    assert data["probation_chargeback_threshold"] >= 1
    assert data["chargeback_count"] >= 0
    assert_supplier_aging_invariants(data)


def assert_supplier_aging_invariants(data: dict):
    """PRD §3.7: total_outstanding_cents is the sum of the four buckets, and an
    empty cohort leaves all five figures at 0 rather than null."""
    buckets = [
        data["aging_0_30_cents"],
        data["aging_31_60_cents"],
        data["aging_61_90_cents"],
        data["aging_over_90_cents"],
    ]
    for value in buckets:
        assert value is not None, "aging buckets are never null"
        assert value >= 0, "aging buckets are never negative"
    assert data["total_outstanding_cents"] == sum(
        buckets
    ), f"total_outstanding_cents {data['total_outstanding_cents']} must equal the bucket sum {sum(buckets)}"


def assert_advisor(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and 0 < len(data["legal_name"]) <= 200
    assert isinstance(data["email"], str) and data["email"]
    state = data["seller_of_travel_state"]
    assert isinstance(state, str) and len(state) == 2 and state.isupper()
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "DEPARTING", "DEPARTED"]
    assert isinstance(data["trust_account_required"], bool)
    assert_advisor_production_invariants(data)


def assert_advisor_production_invariants(data: dict):
    """PRD §2.10: both tier fields default to 1 on a newly onboarded advisor and
    both production figures default to 0."""
    assert data["production_ytd_provisional_cents"] >= 0
    assert data["production_ytd_final_cents"] >= 0
    assert data["eo_coverage_verified_cents"] >= 0
    assert data["lifetime_settled_share_cents"] >= 0
    assert data["lifetime_chargeback_cents"] >= 0
    assert data["carryforward_chargeback_cents"] >= 0


def assert_trust_account_required_matches_state(data: dict, trust_states):
    """PRD §2.12: an advisor's trust_account_required is true when the advisor's
    seller_of_travel_state is one of California, Florida, Hawaii, Iowa or
    Washington and false for every other state."""
    expected = data["seller_of_travel_state"] in trust_states
    assert data["trust_account_required"] is expected, (
        f"trust_account_required for {data['seller_of_travel_state']} must be {expected}, "
        f"got {data['trust_account_required']}"
    )


def assert_advisor_agreement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["advisor_id"])
    assert is_valid_uuid(data["split_schedule_id"])
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "TERMINATED"]
    assert 0 <= data["post_departure_advisor_pct"] <= 1
    assert isinstance(data["effective_date"], str) and data["effective_date"]
    assert isinstance(data["signed_at"], str) and data["signed_at"]


def assert_compliance_credential(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["advisor_id"])
    assert data["credential_type"] in [
        "SELLER_OF_TRAVEL",
        "EO_POLICY",
        "TRAINING_CERT",
        "SUPPLIER_ACCREDITATION",
    ]
    assert isinstance(data["credential_number"], str) and data["credential_number"]
    assert data["status"] in ["PENDING_REVIEW", "VERIFIED", "REJECTED", "REVOKED", "EXPIRED"]
    assert data["effective_on"] < data["expires_on"], "expires_on must be strictly after effective_on"
    assert_credential_polymorphism(data)


def assert_credential_polymorphism(data: dict):
    """PRD §3.3: credential_type decides which conditional input is required and
    which must be absent."""
    kind = data["credential_type"]
    if kind == "SELLER_OF_TRAVEL":
        assert data["jurisdiction_state_code"], "a registration carries jurisdiction_state_code"
        assert data.get("supplier_id") is None
        assert data.get("coverage_amount_cents") is None
    elif kind == "EO_POLICY":
        assert data["coverage_amount_cents"] is not None
        assert data.get("jurisdiction_state_code") is None
        assert data.get("supplier_id") is None
    elif kind == "SUPPLIER_ACCREDITATION":
        assert data["supplier_id"], "an accreditation carries supplier_id"
        assert data.get("jurisdiction_state_code") is None
        assert data.get("coverage_amount_cents") is None
    else:
        assert data.get("jurisdiction_state_code") is None
        assert data.get("coverage_amount_cents") is None
        assert data.get("supplier_id") is None


def assert_client(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["owner_advisor_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    code = data["home_state_code"]
    assert isinstance(code, str) and len(code) == 2 and code.isupper()
    assert data["ownership_mode"] in ["HOST_OWNED", "ADVISOR_OWNED"]
    assert data["portability_status"] in ["RETAINED", "RELEASED"]
    assert data["max_concurrent_trips"] >= 1
    assert data["trust_balance_cents"] >= 0, "a client's trust balance is never negative"


def assert_trust_ledger_entry(data: dict):
    assert_append_only_fields(data)
    assert data["direction"] in ["DEPOSIT", "DISBURSEMENT", "REFUND"]
    assert data["amount_cents"] > 0, "amount_cents is a strictly positive magnitude"
    assert_signed_amount_matches_direction(data)


def assert_signed_amount_matches_direction(data: dict):
    """PRD §3.4: signed_amount_cents is a positive amount_cents for a DEPOSIT and
    a negative amount_cents for both a DISBURSEMENT and a REFUND."""
    if data["direction"] == "DEPOSIT":
        assert data["signed_amount_cents"] == data["amount_cents"]
    else:
        assert data["signed_amount_cents"] == -data["amount_cents"]


def assert_running_balance(rows: list):
    """PRD §3.4: accumulating the signed amounts from zero, each line's
    balance_after_cents is the accumulated total immediately after that line."""
    running = 0
    for row in rows:
        running += row["signed_amount_cents"]
        assert row["balance_after_cents"] == running, (
            f"balance_after_cents {row['balance_after_cents']} must equal the running "
            f"total {running} after line {row['id']}"
        )
        assert running >= 0, "the running balance is never negative"
    return running


def assert_booking(data: dict):
    assert_common_fields(data)
    assert data["booking_status"] in ["SUBMITTED", "CONFIRMED", "TRAVELED", "CANCELLED"]
    assert data["commission_status"] in [
        "PENDING",
        "EXPECTED",
        "RECEIVED",
        "CLAIMED",
        "WRITTEN_OFF",
        "CHARGED_BACK",
    ]
    assert data["channel"] in ["SUPPLIER_DIRECT", "CONSORTIUM", "INTERNAL_TOOL"]
    assert data["payment_method"] in ["CLIENT_TRUST", "MERCHANT_DIRECT", "HOST_MERCHANT"]
    assert data["gross_sale_cents"] > 0
    assert data["travel_start_date"] < data["travel_end_date"]
    for field in MONEY_FIELDS_NEVER_NEGATIVE:
        if field in data and data[field] is not None:
            assert data[field] >= 0, f"{field} must never be negative"
    assert 0 <= data["applied_commission_rate"] <= 1


def assert_commission_claim(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["advisor_id"])
    assert data["status"] in ["SUBMITTED", "DENIED", "RESOLVED_PAID", "RESOLVED_WRITTEN_OFF"]
    assert data["escalation_level"] in ["NORMAL", "ESCALATED", "CRITICAL"]
    assert data["claimed_amount_cents"] > 0
    assert 1 <= data["round_count"] <= 3
    assert data["aging_days"] >= 0
    assert data["resolved_amount_cents"] >= 0


def assert_settlement_run(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["OPEN", "CALCULATED", "POSTED", "CLOSED"]
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert data["statement_count"] >= 0
    for field in (
        "gross_commission_cents",
        "advisor_share_total_cents",
        "chargeback_total_cents",
        "platform_fee_total_cents",
        "marketing_fund_total_cents",
        "net_payout_total_cents",
    ):
        assert data[field] >= 0, f"{field} must never be negative"


def assert_advisor_statement(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "POSTED", "PAID"]
    assert is_valid_uuid(data["settlement_run_id"])
    assert is_valid_uuid(data["advisor_id"])
    assert data["booking_count"] >= 0
    for field in (
        "gross_commission_cents",
        "advisor_share_cents",
        "chargeback_cents",
        "carryforward_applied_cents",
        "platform_fee_cents",
        "marketing_fund_cents",
        "net_payout_cents",
    ):
        assert data[field] >= 0, f"{field} must never be negative"
    assert_statement_waterfall(data)


def assert_statement_waterfall(data: dict):
    """PRD §3.8: the raw net is the gross share less platform_fee_cents, less
    marketing_fund_cents, less the statement's chargeback_cents. When that raw
    net is zero or positive, net_payout_cents takes it and
    carryforward_applied_cents is 0. When it is negative, net_payout_cents is
    floored at 0 and carryforward_applied_cents takes the magnitude of the
    shortfall."""
    raw_net = (
        data["advisor_share_cents"]
        - data["platform_fee_cents"]
        - data["marketing_fund_cents"]
        - data["chargeback_cents"]
    )
    if raw_net >= 0:
        assert data["net_payout_cents"] == raw_net, (
            f"net_payout_cents {data['net_payout_cents']} must equal the raw net {raw_net}"
        )
        assert data["carryforward_applied_cents"] == 0
    else:
        assert data["net_payout_cents"] == 0, "a negative raw net floors net_payout_cents at 0"
        assert data["carryforward_applied_cents"] == -raw_net, (
            f"carryforward_applied_cents {data['carryforward_applied_cents']} must equal "
            f"the shortfall magnitude {-raw_net}"
        )


def assert_recognized_share_identity(advisor: dict, statements: list):
    """PRD §2.9: an advisor's recognized share — lifetime_settled_share_cents
    minus lifetime_chargeback_cents — always equals the sum, across that
    advisor's statements in status POSTED or PAID, of each statement's
    advisor_share_cents minus its chargeback_cents."""
    recognized = advisor["lifetime_settled_share_cents"] - advisor["lifetime_chargeback_cents"]
    from_statements = sum(
        row["advisor_share_cents"] - row["chargeback_cents"]
        for row in statements
        if row["status"] in ("POSTED", "PAID")
    )
    assert recognized == from_statements, (
        f"recognized share {recognized} must equal the posted/paid statement sum {from_statements}"
    )


def assert_error_envelope(error_data: dict):
    """PRD §2.2: the error_id is a unique, machine-readable string that
    identifies the specific error and the message provides a human-readable
    explanation of what went wrong."""
    assert isinstance(error_data.get("error_id"), str) and error_data["error_id"]
    assert isinstance(error_data.get("message"), str) and error_data["message"]


def assert_request_meta(body: dict):
    """PRD §2.2: the api_request_id is a server-generated unique identifier for
    the request that starts with req_."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta.get('api_request_id')!r}"
    )
    assert isinstance(meta.get("api_request_timestamp"), str) and meta["api_request_timestamp"]
