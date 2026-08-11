"""Participant registration, account computed totals, and money-source rules."""
from test_helpers import (
    ApiErrorId,
    api_client,
    make_account,
    make_admin_headers,
    make_participant,
    make_plan,
    make_processor_headers,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_participant_create_missing_required_dob(api):
    """PRD §3.2: "`PlanSponsorAdmin` registers a **Participant** with a
    `full_name`, a `date_of_birth`, an `employment_status` of `ACTIVE`,
    `SEPARATED`, `RETIRED`, or `DISABLED`, and a `marital_status` of `SINGLE`,
    `MARRIED`, `WIDOWED`, or `DIVORCED`."
    PRD §3.2: "When `employment_status` is `SEPARATED` or `RETIRED`, a
    `separation_date` must accompany the registration; omitting it is a
    malformed-payload `ERR_VALIDATION`."

    Design: Corner/entities/participant_create_missing_required_dob
    """
    resp = api.create_participant(
        {"full_name": "No Dob", "employment_status": "ACTIVE", "marital_status": "SINGLE"},
        make_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_account_computed_totals(api):
    """PRD §3.2: "`total_balance_cents` is the plain sum of `balance_cents`
    across all of the account's money-source rows, regardless of any status.
    `vested_balance_cents` applies the floor-per-row-then-sum discipline of
    §2.7: for each row, truncate the product of `balance_cents` and `vested_pct`
    divided by 100 down to a whole cent, then sum the truncated values.
    `basis_cents` on the account is the sum of `basis_cents` across all rows —
    the participant's total tax-paid basis, after-tax contributions plus Roth
    tax-paid amounts."

    Design: Corner/entities/account_computed_totals
    """
    plan = make_plan()
    participant = make_participant()
    resp = api.create_account(
        {
            "participant_id": participant["id"],
            "plan_id": plan["id"],
            "initial_balances": [
                {"source_type": "PRE_TAX", "balance_cents": 8000000, "basis_cents": 0, "vested_pct": 100},
                {"source_type": "EMPLOYER_PRETAX", "balance_cents": 2000000, "basis_cents": 0, "vested_pct": 60},
                {"source_type": "ROTH", "balance_cents": 1000000, "basis_cents": 800000, "vested_pct": 100},
                {"source_type": "AFTER_TAX", "balance_cents": 600000, "basis_cents": 500000, "vested_pct": 100},
            ],
        },
        make_admin_headers(),
    )
    account = validate_success(resp, expected_status=201)
    assert account["total_balance_cents"] == 11600000, (
        f"total must be the plain sum 11600000, got {account['total_balance_cents']}"
    )
    # vested: 8,000,000 + floor(2,000,000*60/100)=1,200,000 + 1,000,000 + 600,000
    assert account["vested_balance_cents"] == 10800000, (
        f"vested must be 10800000 (employer floored at 60%), got {account['vested_balance_cents']}"
    )
    assert account["basis_cents"] == 1300000, (
        f"basis must be 1300000, got {account['basis_cents']}"
    )


def test_account_duplicate_participant_plan_rejected(api):
    """PRD §3.2: "The pair (`participant_id`, `plan_id`) is unique: a second
    account for the same participant at the same plan is rejected with
    `ERR_ACCOUNT_ALREADY_EXISTS`."

    Design: Corner/entities/account_duplicate_participant_plan_rejected
    """
    plan = make_plan()
    participant = make_participant()
    make_account(participant["id"], plan["id"])
    resp = api.create_account(
        {"participant_id": participant["id"], "plan_id": plan["id"]}, make_admin_headers()
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_ALREADY_EXISTS, expected_status=409)


def test_money_source_invalid_enum_rejected(api):
    """PRD §3.2: "The `source_type` is one of `PRE_TAX`, `EMPLOYER_PRETAX`,
    `ROTH`, or `AFTER_TAX`, and is unique per account: at most one row per
    (account, source type) pair."
    PRD §2.9: "9. **Amount checks, last** — only after every other gate has
    passed are magnitudes validated (`ERR_AMOUNT_EXCEEDS_VESTED`,
    `ERR_DEPOSIT_EXCEEDS_REMAINING`, and `ERR_VALIDATION` for non-positive
    amounts or malformed fields)."

    Design: Corner/entities/money_source_invalid_enum_rejected
    """
    plan = make_plan()
    participant = make_participant()
    resp = api.create_account(
        {
            "participant_id": participant["id"],
            "plan_id": plan["id"],
            "initial_balances": [
                {"source_type": "CRYPTO", "balance_cents": 1000, "basis_cents": 0, "vested_pct": 100},
            ],
        },
        make_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)

    # No partial persistence: the failed creation leaves no account behind.
    resp = api.list_accounts(
        make_processor_headers("proc-1"), params={"participant_id": participant["id"]}
    )
    accounts, meta = validate_paginated(resp)
    assert meta["total_count"] == 0, f"no account may persist, got {meta['total_count']}"
    assert accounts == []


def test_participant_age_computed_from_clock(api):
    """PRD §3.2: "Two read-only ages are derived from `date_of_birth` against
    the logical clock: `age_months`, the count of complete calendar months
    elapsed — computed as twelve times the year difference plus the month
    difference, minus one when the clock's day-of-month is earlier than the
    birth day-of-month — and `current_age_years`, which is `age_months` divided
    by twelve and truncated to two decimal places."

    Design: Corner/entities/participant_age_computed_from_clock
    """
    set_logical_clock("2026-05-01T00:00:00Z")
    participant = make_participant(
        full_name="Age Probe", date_of_birth="1966-11-01", employment_status="ACTIVE",
        marital_status="SINGLE", separation_date=None,
    )
    proc = make_processor_headers("proc-1")

    data = validate_success(api.get_participant(participant["id"], proc))
    # (2026-1966)*12 + (5-11) = 714; clock day 1 is not earlier than birth day 1.
    assert data["age_months"] == 714, f"age_months must be 714, got {data['age_months']}"
    assert data["current_age_years"] == 59.5, (
        f"current_age_years must be 59.5, got {data['current_age_years']}"
    )

    set_logical_clock("2026-04-01T00:00:00Z")
    data = validate_success(api.get_participant(participant["id"], proc))
    # (2026-1966)*12 + (4-11) = 713.
    assert data["age_months"] == 713, (
        f"age_months recomputed against the clock must be 713, got {data['age_months']}"
    )


def test_vested_balance_floor_per_row(api):
    """PRD §3.2: "`vested_balance_cents` applies the floor-per-row-then-sum
    discipline of §2.7: for each row, truncate the product of `balance_cents`
    and `vested_pct` divided by 100 down to a whole cent, then sum the truncated
    values."

    Design: Corner/calculations/vested_balance_floor_per_row
    """
    plan = make_plan()
    participant = make_participant(full_name="Vest Ing")
    resp = api.create_account(
        {
            "participant_id": participant["id"],
            "plan_id": plan["id"],
            "initial_balances": [
                {"source_type": "EMPLOYER_PRETAX", "balance_cents": 333333, "basis_cents": 0, "vested_pct": 50},
            ],
        },
        make_admin_headers(),
    )
    account = validate_success(resp, expected_status=201)
    # floor(333333 * 50 / 100) = floor(166666.5) = 166666 — per-row floor, never 166667.
    assert account["vested_balance_cents"] == 166666, (
        f"per-row floor must yield 166666, got {account['vested_balance_cents']}"
    )
    assert account["total_balance_cents"] == 333333
