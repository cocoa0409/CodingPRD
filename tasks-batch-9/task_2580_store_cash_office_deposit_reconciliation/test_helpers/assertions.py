"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ADDING_TXN_TYPES,
    PERMITTED_DENOMINATIONS,
    SUBTRACTING_TXN_TYPES,
)


def assert_common_fields(data: dict):
    """Most record types carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 on creation"


def assert_store(data: dict):
    assert_common_fields(data)
    assert isinstance(data["store_code"], str) and 1 <= len(data["store_code"]) <= 16
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["region_code"], str)
    assert 0 <= data["safe_time_delay_minutes"] <= 120
    assert 1 <= data["safe_open_window_minutes"] <= 240
    assert isinstance(data["dual_control_required"], bool)
    assert 0 <= data["pickup_buffer_minutes"] <= 240
    assert 1 <= data["max_daily_pickups"] <= 6
    assert data["single_event_variance_threshold_cents"] >= 0
    assert data["rolling_variance_threshold_cents"] >= 0
    assert 1 <= data["rolling_window_days"] <= 365
    assert data["theft_escalation_threshold_cents"] >= 0
    assert data["provisional_credit_cap_cents"] >= 0
    assert data["seasonal_profile"] in ["BASELINE", "BACK_TO_SCHOOL", "HOLIDAY"]


def assert_cashier(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["employee_code"], str) and len(data["employee_code"]) > 0
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert data["till_eligibility"] in ["ELIGIBLE", "RESTRICTED", "BARRED"]
    assert data["coaching_state"] in [
        "NONE",
        "COACHING_DUE",
        "COACHING_ACKNOWLEDGED",
    ]
    assert isinstance(data["rolling_absolute_variance_cents"], int)
    assert data["rolling_absolute_variance_cents"] >= 0
    assert isinstance(data["rolling_net_variance_cents"], int)
    assert data["reconciled_session_count"] >= 0
    assert data["open_case_count"] >= 0
    if data["coaching_state"] == "NONE":
        assert (
            data["coaching_due_at"] is None
        ), "coaching_due_at is null while coaching_state remains NONE"


def assert_safe(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["safe_code"], str) and len(data["safe_code"]) > 0
    assert data["safe_type"] in ["MANUAL", "SMART"]
    assert data["open_state"] in ["LOCKED", "OPEN_REQUESTED", "UNLOCKED"]
    assert data["posture"] in ["OPEN", "FROZEN"]
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["provisional_credit_balance_cents"], int)
    assert isinstance(data["suspect_note_cents"], int)
    if data["safe_type"] == "SMART":
        assert (
            data["open_state"] == "LOCKED"
        ), "a SMART safe's open_state stays LOCKED throughout its life"


def assert_sales_journal(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["business_date"], str) and len(data["business_date"]) == 10
    assert data["status"] in ["OPEN", "TENDERS_POSTED", "BALANCED", "OUT_OF_BALANCE"]
    assert data["session_count"] >= 0
    assert data["reconciled_session_count"] >= 0
    assert data["settlement_count"] >= 0
    assert isinstance(data["register_cash_tieout_cents"], int)
    assert data["settlement_variance_total_cents"] >= 0
    assert data["open_case_count"] >= 0
    assert isinstance(data["net_unexplained_cents"], int)


def assert_denomination_lines(lines):
    for line in lines:
        assert (
            line["denomination_cents"] in PERMITTED_DENOMINATIONS
        ), f"{line['denomination_cents']} is not a permitted denomination"
        assert line["quantity"] >= 0, "quantity must be zero or greater"


def assert_till_session(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["sales_journal_id"])
    assert is_valid_uuid(data["cashier_id"])
    assert is_valid_uuid(data["safe_id"])
    assert 1 <= data["register_number"] <= 99
    assert data["status"] in ["ACTIVE", "PENDING_COUNT", "COUNTED", "RECONCILED"]
    assert data["starting_bank_cents"] >= 0
    assert data["dropped_declared_cents"] >= 0
    assert data["recount_count"] >= 0
    assert isinstance(data["forced_close"], bool)
    assert_denomination_lines(data.get("counted_lines") or [])
    if data["status"] in ("PENDING_COUNT", "COUNTED"):
        assert (
            data["expected_cash_cents"] is None
        ), "expected_cash_cents is masked before reconciliation"
        assert (
            data["variance_cents"] is None
        ), "variance_cents is masked before reconciliation"
    if data["variance_basis"] is not None:
        assert data["variance_basis"] in ["DECLARED_DROPS", "VERIFIED_DROPS"]


def assert_safe_transaction(data: dict):
    """A safe transaction is immutable: it carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a safe transaction has no updated_at"
    assert "version" not in data, "a safe transaction has no version field at all"
    assert is_valid_uuid(data["safe_id"])
    assert data["txn_type"] in ADDING_TXN_TYPES + SUBTRACTING_TXN_TYPES
    assert data["declared_amount_cents"] >= 0, "declared_amount_cents is unsigned"
    assert isinstance(data["effective_amount_cents"], int)
    assert isinstance(data["actor_user_id"], str) and len(data["actor_user_id"]) > 0
    assert is_iso8601_timestamp(data["occurred_at"]), "occurred_at must be ISO 8601"
    assert_safe_transaction_sign(data)
    assert_safe_transaction_linkage(data)


def assert_safe_transaction_sign(row: dict):
    """effective_amount_cents is the row's basis carried with the sign its
    txn_type implies; the basis is verified_amount_cents when populated."""
    basis = (
        row["verified_amount_cents"]
        if row.get("verified_amount_cents") is not None
        else row["declared_amount_cents"]
    )
    if row["txn_type"] in ADDING_TXN_TYPES:
        assert row["effective_amount_cents"] == basis, (
            f"{row['txn_type']} adds to the safe: expected {basis}, "
            f"got {row['effective_amount_cents']}"
        )
    else:
        assert row["effective_amount_cents"] == -basis, (
            f"{row['txn_type']} subtracts from the safe: expected {-basis}, "
            f"got {row['effective_amount_cents']}"
        )


def assert_safe_transaction_linkage(row: dict):
    """Rows are polymorphic in their linkage; the remaining slots stay null."""
    till_kinds = ["STARTING_BANK_ISSUE", "MID_SHIFT_DROP", "CLOSING_DROP"]
    deposit_kinds = ["SMART_DEPOSIT", "DEPOSIT_REMOVAL", "DEPOSIT_RETURN"]
    if row["txn_type"] not in till_kinds:
        assert row.get("till_session_id") is None, (
            f"till_session_id must be null on a {row['txn_type']} row"
        )
    if row["txn_type"] not in deposit_kinds:
        assert row.get("deposit_id") is None, (
            f"deposit_id must be null on a {row['txn_type']} row"
        )
    if row["txn_type"] != "CHANGE_ORDER_RECEIPT":
        assert row.get("change_order_id") is None, (
            f"change_order_id must be null on a {row['txn_type']} row"
        )


def assert_deposit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["safe_id"])
    assert is_valid_uuid(data["sales_journal_id"])
    assert data["deposit_type"] in ["MANUAL_ARMORED", "SMART_SAFE"]
    assert data["status"] in [
        "PREPARING",
        "SEALED",
        "SCHEDULED",
        "IN_TRANSIT",
        "RECONCILED",
        "DISCREPANT",
        "VOIDED",
    ]
    assert data["credit_basis"] in ["CARRIER_PROVISIONAL", "SMART_PROVISIONAL"]
    assert_denomination_lines(data.get("counted_lines") or [])
    assert data["declared_total_cents"] >= 0
    assert data["suspect_note_cents"] >= 0
    assert data["provisional_credit_cents"] >= 0
    assert data["carrier_fee_cents"] >= 0
    assert isinstance(data["expected_credit_cents"], int)
    assert isinstance(data["credited_total_cents"], int)


def assert_bank_credit_record(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert data["credit_type"] in ["PROVISIONAL", "FINAL", "ADJUSTMENT"]
    assert isinstance(data["amount_cents"], int)
    if data["credit_type"] in ("PROVISIONAL", "FINAL"):
        assert (
            data["amount_cents"] > 0
        ), "provisional and final bank credit rows must be strictly greater than zero"
    assert isinstance(data["value_date"], str) and len(data["value_date"]) == 10
    assert isinstance(data["bank_reference"], str)
    assert data["match_state"] in ["UNMATCHED", "MATCHED"]


def assert_card_settlement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["sales_journal_id"])
    assert data["card_network"] in ["VISA_MC", "AMEX"]
    assert data["gross_card_sales_cents"] >= 0
    assert data["txn_count"] >= 0
    assert data["chargeback_cents"] >= 0
    assert data["monthly_volume_cents"] >= 0
    assert isinstance(data["expected_fee_cents"], int)
    assert isinstance(data["expected_funded_cents"], int)
    assert isinstance(data["settlement_variance_cents"], int)
    assert data["settlement_status"] in ["MATCHED", "VARIANCE"]
    assert data["expected_funded_cents"] == (
        data["gross_card_sales_cents"]
        - data["expected_fee_cents"]
        - data["chargeback_cents"]
    ), "expected_funded_cents is gross minus expected fee minus chargebacks"
    assert data["settlement_variance_cents"] == (
        data["funded_amount_cents"] - data["expected_funded_cents"]
    ), "settlement_variance_cents is funded_amount_cents minus expected_funded_cents"


def assert_variance_case(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["sales_journal_id"])
    assert data["case_type"] in [
        "SESSION_VARIANCE",
        "ROLLING_PATTERN",
        "DEPOSIT_CREDIT",
    ]
    assert data["status"] in [
        "OPEN",
        "RESEARCHING",
        "EXPLAINED",
        "ESCALATED",
        "CLOSED_SUBSTANTIATED",
        "CLOSED_UNSUBSTANTIATED",
    ]
    assert (
        data["total_variance_cents"] >= 0
    ), "total_variance_cents is an unsigned magnitude"
    assert isinstance(data["attributions"], list)
    assert isinstance(data["suspected_theft"], bool)
    assert_variance_decomposition(data)
    for entry in data["attributions"]:
        assert entry["bucket"] in ["REGISTER", "SAFE", "BANK"]
        assert isinstance(entry["amount_cents"], int)


def assert_variance_decomposition(case: dict):
    """total_variance_cents always equals attributed_register_cents plus
    attributed_safe_cents plus attributed_bank_cents plus unexplained_cents."""
    total = (
        case["attributed_register_cents"]
        + case["attributed_safe_cents"]
        + case["attributed_bank_cents"]
        + case["unexplained_cents"]
    )
    assert total == case["total_variance_cents"], (
        "decomposition must hold: "
        f"{case['attributed_register_cents']} + {case['attributed_safe_cents']} + "
        f"{case['attributed_bank_cents']} + {case['unexplained_cents']} != "
        f"{case['total_variance_cents']}"
    )


def assert_change_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["store_id"])
    assert 1 <= data["days_covered"] <= 14
    assert data["baseline_daily_cash_demand_cents"] >= 0
    assert data["applied_seasonal_profile"] in [
        "BASELINE",
        "BACK_TO_SCHOOL",
        "HOLIDAY",
    ]
    assert data["forecast_demand_cents"] >= 0
    assert data["status"] in ["DRAFT", "APPROVED", "REJECTED", "RECEIVED"]
    assert_denomination_plan(data)


def assert_denomination_plan(order: dict):
    """Five denomination rows are always planned, always in descending order of
    denomination, and total_planned_cents is the sum of the lines' planned_cents."""
    plan = order["planned_lines"]
    assert len(plan) == 5, f"five denomination rows are always planned, got {len(plan)}"
    assert [line["denomination_cents"] for line in plan] == [
        2000,
        1000,
        500,
        100,
        25,
    ], "planned_lines must be in descending order of denomination"
    for line in plan:
        assert line["strap_count"] >= 0
        assert line["planned_cents"] == line["units"] * line["denomination_cents"]
    assert order["total_planned_cents"] == sum(
        line["planned_cents"] for line in plan
    ), "total_planned_cents is the sum of the lines' planned_cents"


def assert_safe_balance_from_ledger(safe: dict, rows) -> int:
    """A safe's balance_cents is the sum of effective_amount_cents over every
    ledger row whose safe_id names that safe."""
    expected = sum(row["effective_amount_cents"] for row in rows)
    assert safe["balance_cents"] == expected, (
        f"balance_cents {safe['balance_cents']} must equal the ledger sum {expected}"
    )
    return expected


def assert_expected_cash(session: dict, drop_total: int):
    """expected_cash_cents is starting_bank_cents plus pos_cash_sales_cents minus
    pos_paid_out_cents minus the chosen drop total."""
    expected = (
        session["starting_bank_cents"]
        + (session["pos_cash_sales_cents"] or 0)
        - (session["pos_paid_out_cents"] or 0)
        - drop_total
    )
    assert session["expected_cash_cents"] == expected, (
        f"expected_cash_cents {session['expected_cash_cents']} != {expected}"
    )
    assert session["variance_cents"] == (
        session["counted_cash_cents"] - session["expected_cash_cents"]
    ), "variance_cents is counted_cash_cents minus expected_cash_cents"


def assert_close_projection(data: dict):
    """The register close returns only the session's id, status, register_number,
    shift_end_at, dropped_declared_cents and version."""
    assert set(data.keys()) == {
        "id",
        "status",
        "register_number",
        "shift_end_at",
        "dropped_declared_cents",
        "version",
    }, f"unexpected close projection keys: {sorted(data.keys())}"


def assert_blind_count_projection(data: dict):
    """The blind count response carries only the session's id, status,
    counted_cash_cents, recount_count and version."""
    assert set(data.keys()) == {
        "id",
        "status",
        "counted_cash_cents",
        "recount_count",
        "version",
    }, f"unexpected blind-count projection keys: {sorted(data.keys())}"


def assert_pagination_meta(meta: dict, limit: int, offset: int, total_count: int):
    assert meta["limit"] == limit
    assert meta["offset"] == offset
    assert meta["total_count"] == total_count
    assert meta["has_more"] == (offset + limit < total_count)


def assert_ordered_by_created_at(rows):
    """Results are always ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"results must be created_at ascending: {stamps}"
