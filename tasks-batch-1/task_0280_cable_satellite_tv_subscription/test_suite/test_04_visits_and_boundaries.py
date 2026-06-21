"""Boundary precision (ETF >=12 breakpoint, technician zero-gap adjacency) and
resource temporal overlap geometry (technician half-open, account closed+buffer).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    create_package,
    create_technician,
    create_active_account,
    create_prospect_account,
    activate_first_subscription,
    set_clock,
    schedule_visit,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CSA = TEST_USERS["customer_service_agent_headers"]


# ===========================================================================
# boundary_precision_check / etf_remaining_exactly_12_lands_in_max_tier
# ===========================================================================
def test_etf_remaining_exactly_twelve_uses_max_tier(api):
    """PRD §3.8: "If the remaining months are at least 12, the fee is the maximum of 240 dollars
    (24,000 cents)."
    PRD §3.8: "The breakpoints are inclusive at their lower edge: exactly 12 remaining months
    lands in the at-least-12 tier (24,000 cents), exactly 6 remaining months lands in the mid
    tier (15,000 cents), and exactly 5 remaining months lands in the low per-month tier."

    Design: Difficulty/boundary_precision_check/etf_remaining_exactly_12_lands_in_max_tier
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    account, _ = create_active_account(package, service_state_code="CA", contract_term_months=12)
    validate_success(api.cancel_account(account["id"], CSA), 200)
    stmt = validate_success(
        api.issue_billing_statement(
            account["id"], {"cycle_index": 0, "proration_mode": "FULL_CYCLE", "days_in_cycle": 30}, ADMIN
        ),
        201,
    )
    # contract 12, tenure 0 -> remaining 12 -> MAX tier 24000
    assert stmt["etf_charge_cents"] == 24000, f"ETF at remaining==12 expected 24000, got {stmt['etf_charge_cents']}"


def test_etf_remaining_above_twelve_stays_in_max_tier(api):
    """PRD §3.8: "If the remaining months are at least 12, the fee is the maximum of 240 dollars
    (24,000 cents)."

    Design: Difficulty/boundary_precision_check/etf_remaining_exactly_12_lands_in_max_tier
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    account, _ = create_active_account(package, service_state_code="CA", contract_term_months=18)
    validate_success(api.cancel_account(account["id"], CSA), 200)
    stmt = validate_success(
        api.issue_billing_statement(
            account["id"], {"cycle_index": 0, "proration_mode": "FULL_CYCLE", "days_in_cycle": 30}, ADMIN
        ),
        201,
    )
    # contract 18, tenure 0 -> remaining 18 (>=12) -> MAX tier 24000
    assert stmt["etf_charge_cents"] == 24000, f"ETF at remaining==18 expected 24000, got {stmt['etf_charge_cents']}"


# ===========================================================================
# boundary_precision_check / technician_adjacent_window_zero_gap_allowed
# ===========================================================================
def test_technician_zero_gap_adjacent_window_allowed(api):
    """PRD §3.9: "Technician intervals are treated as half-open `[start, end)`, so exact
    adjacency is allowed — an existing visit ending precisely when the new one starts, or a new
    visit ending precisely when an existing one starts, does not conflict — but any strictly
    positive overlap is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/technician_adjacent_window_zero_gap_allowed
    """
    set_clock("2026-06-01T00:00:00Z")
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    tech = create_technician(name="Tech One", home_state_code="CA")
    # Two distinct accounts so the test isolates the technician half-open rule;
    # placing both visits on one account would trip the PRD §3.9 account-level
    # 60-minute-buffer rule (gap 0 < 60), which is a separate required check.
    account_a, _ = create_active_account(package, customer_name="AcctA", service_state_code="CA")
    prospect_b = create_prospect_account(customer_name="AcctB", service_state_code="CA")
    activate_first_subscription(prospect_b["id"], package["id"])
    schedule_visit(account_a["id"], tech["id"], "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z", visit_type="SERVICE")

    res = api.schedule_service_visit(
        prospect_b["id"],
        {
            "visit_type": "SERVICE",
            "window_start": "2026-06-02T10:00:00Z",
            "window_end": "2026-06-02T11:00:00Z",
            "technician_id": tech["id"],
        },
        CSA,
    )
    second = validate_success(res, 201)
    assert second["status"] == "SCHEDULED"


def test_technician_back_to_back_before_existing_allowed(api):
    """PRD §3.9: "Technician intervals are treated as half-open `[start, end)`, so exact
    adjacency is allowed — an existing visit ending precisely when the new one starts, or a new
    visit ending precisely when an existing one starts, does not conflict — but any strictly
    positive overlap is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/technician_adjacent_window_zero_gap_allowed
    """
    set_clock("2026-06-01T00:00:00Z")
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    tech = create_technician(name="Tech One", home_state_code="CA")
    # Two distinct accounts so the test isolates the technician half-open rule;
    # placing both visits on one account would trip the PRD §3.9 account-level
    # 60-minute-buffer rule (gap 0 < 60), which is a separate required check.
    account_a, _ = create_active_account(package, customer_name="AcctA", service_state_code="CA")
    prospect_b = create_prospect_account(customer_name="AcctB", service_state_code="CA")
    activate_first_subscription(prospect_b["id"], package["id"])
    # existing 11:00-12:00 ; new ends precisely when existing starts (new.end == existing.start)
    schedule_visit(account_a["id"], tech["id"], "2026-06-02T11:00:00Z", "2026-06-02T12:00:00Z", visit_type="SERVICE")

    res = api.schedule_service_visit(
        prospect_b["id"],
        {
            "visit_type": "SERVICE",
            "window_start": "2026-06-02T10:00:00Z",
            "window_end": "2026-06-02T11:00:00Z",
            "technician_id": tech["id"],
        },
        CSA,
    )
    second = validate_success(res, 201)
    assert second["status"] == "SCHEDULED"


# ===========================================================================
# resource_temporal_overlap / technician_overlap_half_open_strict
# ===========================================================================
def test_technician_strict_overlap_rejected(api):
    """PRD §3.9: "The window must not collide with another non-terminal visit (one whose status
    is `SCHEDULED` or `DISPATCHED`) for the **same technician**. Technician intervals are treated
    as half-open `[start, end)`, so exact adjacency is allowed ... but any strictly positive
    overlap is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/technician_overlap_half_open_strict
    """
    set_clock("2026-06-01T00:00:00Z")
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    tech = create_technician(name="Tech One", home_state_code="CA")
    # Two distinct accounts so the conflict is technician-only, not account-level.
    account_a, _ = create_active_account(package, customer_name="AcctA", service_state_code="CA")
    package_b = package
    prospect_b = create_prospect_account(customer_name="AcctB", service_state_code="CA")
    activate_first_subscription(prospect_b["id"], package_b["id"])
    schedule_visit(account_a["id"], tech["id"], "2026-06-03T09:00:00Z", "2026-06-03T10:00:00Z", visit_type="SERVICE")

    res = api.schedule_service_visit(
        prospect_b["id"],
        {
            "visit_type": "SERVICE",
            "window_start": "2026-06-03T09:30:00Z",
            "window_end": "2026-06-03T10:30:00Z",
            "technician_id": tech["id"],
        },
        CSA,
    )
    validate_error(res, "ERR_TECHNICIAN_DOUBLE_BOOKED")


def test_technician_double_booked_uses_409(api):
    """PRD §3.9: "any strictly positive overlap is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/technician_overlap_half_open_strict
    """
    set_clock("2026-06-01T00:00:00Z")
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    tech = create_technician(name="Tech One", home_state_code="CA")
    account_a, _ = create_active_account(package, customer_name="AcctA", service_state_code="CA")
    prospect_b = create_prospect_account(customer_name="AcctB", service_state_code="CA")
    activate_first_subscription(prospect_b["id"], package["id"])
    schedule_visit(account_a["id"], tech["id"], "2026-06-05T09:00:00Z", "2026-06-05T10:00:00Z", visit_type="SERVICE")

    res = api.schedule_service_visit(
        prospect_b["id"],
        {
            "visit_type": "SERVICE",
            "window_start": "2026-06-05T09:30:00Z",
            "window_end": "2026-06-05T10:30:00Z",
            "technician_id": tech["id"],
        },
        CSA,
    )
    validate_error(res, "ERR_TECHNICIAN_DOUBLE_BOOKED", expected_status=409)


# ===========================================================================
# resource_temporal_overlap / account_overlap_closed_plus_buffer
# ===========================================================================
def test_account_visit_within_buffer_rejected(api):
    """PRD §3.9: "The window must not collide with another non-terminal visit (again `SCHEDULED`
    or `DISPATCHED`) for the **same account**, and must additionally keep at least a 60-minute
    buffer from any other visit on that account. Account intervals are treated as closed plus a
    60-minute buffer: if the gap between the new window and another account visit is less than
    60 minutes, it is rejected with `ERR_ACCOUNT_VISIT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/account_overlap_closed_plus_buffer
    """
    set_clock("2026-06-01T00:00:00Z")
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    tech1 = create_technician(name="Tech One", home_state_code="CA")
    tech2 = create_technician(name="Tech Two", home_state_code="CA")
    account, _ = create_active_account(package, service_state_code="CA")
    schedule_visit(account["id"], tech1["id"], "2026-06-04T09:00:00Z", "2026-06-04T10:00:00Z", visit_type="SERVICE")

    # New visit on a free technician starting 30 min after prior ends (gap 30 < 60).
    res = api.schedule_service_visit(
        account["id"],
        {
            "visit_type": "SERVICE",
            "window_start": "2026-06-04T10:30:00Z",
            "window_end": "2026-06-04T11:30:00Z",
            "technician_id": tech2["id"],
        },
        CSA,
    )
    validate_error(res, "ERR_ACCOUNT_VISIT_CONFLICT")


def test_account_visit_conflict_uses_409(api):
    """PRD §3.9: "if the gap between the new window and another account visit is less than 60
    minutes, it is rejected with `ERR_ACCOUNT_VISIT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/account_overlap_closed_plus_buffer
    """
    set_clock("2026-06-01T00:00:00Z")
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    tech1 = create_technician(name="Tech One", home_state_code="CA")
    tech2 = create_technician(name="Tech Two", home_state_code="CA")
    account, _ = create_active_account(package, service_state_code="CA")
    schedule_visit(account["id"], tech1["id"], "2026-06-06T09:00:00Z", "2026-06-06T10:00:00Z", visit_type="SERVICE")

    res = api.schedule_service_visit(
        account["id"],
        {
            "visit_type": "SERVICE",
            "window_start": "2026-06-06T10:30:00Z",
            "window_end": "2026-06-06T11:30:00Z",
            "technician_id": tech2["id"],
        },
        CSA,
    )
    validate_error(res, "ERR_ACCOUNT_VISIT_CONFLICT", expected_status=409)
