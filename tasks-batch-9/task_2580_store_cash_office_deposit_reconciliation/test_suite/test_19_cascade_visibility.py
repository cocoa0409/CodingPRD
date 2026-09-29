"""Immediate consistency: the reconcile response already carries every derived figure the follow-up reads report."""

from test_helpers import (
    CLERK_3,
    assign_till,
    blind_count,
    close_till,
    create_cashier,
    create_safe,
    create_sales_journal,
    create_store,
    set_clock,
    validate_paginated,
    validate_success,
)

BUSINESS_DATE = "2026-08-03"

#: Thirty twenty-dollar notes: the drawer held 60000 cents against 120000 expected.
COUNT_60000 = [{"denomination_cents": 2000, "quantity": 30}]


def test_every_cascade_effect_is_visible_in_the_same_response(
    api, clerk_headers, manager_headers
):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    PRD §3.5: "The expected till contents are then the session's `starting_bank_cents`, plus its `pos_cash_sales_cents`, minus its `pos_paid_out_cents`, minus the chosen drop total; the result is stored as `expected_cash_cents`."

    PRD §3.5: "From that set, `reconciled_session_count` becomes the number of sessions, `rolling_absolute_variance_cents` becomes the sum of the absolute values of their variances, and `rolling_net_variance_cents` becomes the signed sum of the same variances."

    PRD §3.5: "Note that a single reconciliation can breach both thresholds and therefore open two cases."

    PRD §3.1: "`net_unexplained_cents` is the sum of `unexplained_cents` over that same set of cases."

    PRD §3.8: "In the same instant, `suspected_theft` is set to true when `total_variance_cents` is at or above the store's `theft_escalation_threshold_cents` and to false otherwise — again evaluated once, at creation."

    Design: Corner/consistency_model/every_cascade_effect_is_visible_in_the_same_response
    """
    set_clock("2026-08-03T08:00:00Z")
    store = create_store(store_code="S-1984", name="Store 1984", region_code="WEST")
    safe = create_safe(
        store["id"],
        safe_code="SAFE-A",
        safe_type="MANUAL",
        opening_balance_cents=500000,
    )
    cashier = create_cashier(
        store["id"], employee_code="E-100", display_name="Cashier 100"
    )
    journal = create_sales_journal(store["id"], BUSINESS_DATE)
    session = assign_till(
        journal["id"],
        cashier["id"],
        safe["id"],
        register_number=1,
        shift_start_at="2026-08-03T09:00:00Z",
        shift_end_at="2026-08-03T17:00:00Z",
        starting_bank_cents=20000,
    )
    set_clock("2026-08-03T17:00:00Z")
    close_till(
        session["id"],
        pos_cash_sales_cents=100000,
        pos_card_sales_cents=0,
        pos_paid_out_cents=0,
    )
    blind_count(session["id"], COUNT_60000, CLERK_3)

    # The reconcile response itself must already carry the recomputed variance.
    reconciled = validate_success(
        api.reconcile_till_session(session["id"], clerk_headers)
    )
    assert reconciled["status"] == "RECONCILED", (
        f"expected status RECONCILED, got {reconciled['status']}"
    )
    assert reconciled["expected_cash_cents"] == 120000, (
        "20000 starting bank plus 100000 cash sales expects 120000, got "
        f"{reconciled['expected_cash_cents']}"
    )
    assert reconciled["variance_cents"] == -60000, (
        f"60000 counted against 120000 expected is -60000, "
        f"got {reconciled['variance_cents']}"
    )
    assert reconciled["variance_basis"] == "DECLARED_DROPS", (
        f"no bag was ever re-counted, got {reconciled['variance_basis']}"
    )

    # Reads issued immediately afterwards must agree with it exactly. The single
    # reconciliation breaches both the 2500 single-event threshold and the 10000
    # rolling threshold, so two cases stand open on the journal and the cashier.
    cashier_read = validate_success(api.get_cashier(cashier["id"], manager_headers))
    assert cashier_read["rolling_absolute_variance_cents"] == 60000, (
        "expected rolling_absolute_variance_cents 60000, got "
        f"{cashier_read['rolling_absolute_variance_cents']}"
    )
    assert cashier_read["rolling_net_variance_cents"] == -60000, (
        "expected rolling_net_variance_cents -60000, got "
        f"{cashier_read['rolling_net_variance_cents']}"
    )
    assert cashier_read["reconciled_session_count"] == 1, (
        f"expected reconciled_session_count 1, "
        f"got {cashier_read['reconciled_session_count']}"
    )
    assert cashier_read["coaching_state"] == "COACHING_DUE", (
        f"expected coaching_state COACHING_DUE, got {cashier_read['coaching_state']}"
    )
    assert cashier_read["till_eligibility"] == "RESTRICTED", (
        "60000 is at or above the 10000 rolling threshold, got "
        f"{cashier_read['till_eligibility']}"
    )
    assert cashier_read["open_case_count"] == 2, (
        "both the SESSION_VARIANCE and the ROLLING_PATTERN case name this cashier: "
        f"expected open_case_count 2, got {cashier_read['open_case_count']}"
    )

    journal_read = validate_success(
        api.get_sales_journal(journal["id"], manager_headers)
    )
    assert journal_read["net_unexplained_cents"] == 120000, (
        "60000 unexplained on each of the two open cases: expected 120000, got "
        f"{journal_read['net_unexplained_cents']}"
    )
    assert journal_read["open_case_count"] == 2, (
        f"expected open_case_count 2, got {journal_read['open_case_count']}"
    )
    assert journal_read["reconciled_session_count"] == 1, (
        f"expected reconciled_session_count 1, "
        f"got {journal_read['reconciled_session_count']}"
    )

    cases, _ = validate_paginated(
        api.list_variance_cases(
            clerk_headers, params={"sales_journal_id": journal["id"], "limit": 100}
        )
    )
    by_type = {case["case_type"]: case for case in cases}
    assert set(by_type) == {"SESSION_VARIANCE", "ROLLING_PATTERN"}, (
        f"expected one case of each type, got {sorted(by_type)}"
    )
    session_case = by_type["SESSION_VARIANCE"]
    assert session_case["total_variance_cents"] == 60000, (
        f"expected total_variance_cents 60000, "
        f"got {session_case['total_variance_cents']}"
    )
    assert session_case["suspected_theft"] is True, (
        "60000 is at or above the 50000 theft escalation threshold, got "
        f"{session_case['suspected_theft']}"
    )
    assert session_case["unexplained_cents"] == 60000, (
        f"expected unexplained_cents 60000, "
        f"got {session_case['unexplained_cents']}"
    )
    rolling_case = by_type["ROLLING_PATTERN"]
    assert rolling_case["total_variance_cents"] == 60000, (
        "the ROLLING_PATTERN magnitude is the freshly recomputed rolling absolute: "
        f"expected 60000, got {rolling_case['total_variance_cents']}"
    )

    # Nothing lags: a second identical round of reads changes no value.
    watched_cashier_fields = (
        "rolling_absolute_variance_cents",
        "rolling_net_variance_cents",
        "reconciled_session_count",
        "coaching_state",
        "till_eligibility",
        "open_case_count",
        "version",
    )
    cashier_again = validate_success(api.get_cashier(cashier["id"], manager_headers))
    for field in watched_cashier_fields:
        assert cashier_again[field] == cashier_read[field], (
            f"the first cashier response was already final: {field} moved from "
            f"{cashier_read[field]} to {cashier_again[field]}"
        )

    watched_journal_fields = (
        "status",
        "net_unexplained_cents",
        "open_case_count",
        "reconciled_session_count",
        "session_count",
        "register_cash_tieout_cents",
        "version",
    )
    journal_again = validate_success(
        api.get_sales_journal(journal["id"], manager_headers)
    )
    for field in watched_journal_fields:
        assert journal_again[field] == journal_read[field], (
            f"the first journal response was already final: {field} moved from "
            f"{journal_read[field]} to {journal_again[field]}"
        )

    session_again = validate_success(
        api.get_till_session(session["id"], clerk_headers)
    )
    for field in ("status", "expected_cash_cents", "variance_cents", "variance_basis"):
        assert session_again[field] == reconciled[field], (
            f"the reconcile response was already final: {field} moved from "
            f"{reconciled[field]} to {session_again[field]}"
        )
