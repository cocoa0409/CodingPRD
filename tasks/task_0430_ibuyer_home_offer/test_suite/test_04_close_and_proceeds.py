"""Scheduling the close: repair credit, lease-back charge, final net proceeds,
the provisional-vs-final divergence, and the close-date / lease-back boundaries.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_seller_headers,
    set_clock,
    setup_finalized_assessment,
    setup_scheduled_transaction,
    setup_inspection_transaction,
    schedule_close,
    close_transaction,
    STANDARD_REPAIR_LINES,
)

_ANALYST = TEST_USERS["pricing_analyst_headers"]
_ADMIN = TEST_USERS["operations_admin_headers"]


def test_leaseback_total_round_daily_then_multiply(api):
    """PRD §3.5: "The lease-back daily rate, `leaseback_daily_rate`, is the property's
    effective AVM multiplied by 0.0004, rounded half-up to two decimal places; the
    lease-back total, `leaseback_total`, is that daily rate multiplied by
    `leaseback_days`, rounded half-up to two decimal places (round the daily rate
    first, then multiply)."

    Design: Corner/calculations/leaseback_total_round_daily_then_multiply
    """
    seller, prop, offer, txn, assessment, _ = setup_scheduled_transaction(
        leaseback_days=10, final_concession=0
    )
    # avm=510000 -> daily=round(510000*0.0004,2)=204.00; total=round(204.00*10,2)=2040.00.
    assert txn["leaseback_daily_rate"] == 204.00, txn["leaseback_daily_rate"]
    assert txn["leaseback_total"] == 2040.00, txn["leaseback_total"]
    assert txn["final_net_proceeds"] == 482460.00, txn["final_net_proceeds"]


def test_schedule_close_final_net_proceeds_diverges_from_preliminary(api):
    """PRD §3.5: "It is the effective AVM, minus the effective service fee, minus the
    `final_concession`, minus the `repair_credit`, minus the `leaseback_total`,
    rounded half-up to two decimal places."
    PRD §3.5: "This final payout deliberately diverges from the offer's
    `preliminary_net_proceeds`: the provisional figure assumed a zero repair credit,
    no lease-back, and a one-percent concession estimate, whereas the final figure
    uses the possibly-re-traded effective AVM, the actual round-per-line repair
    credit, the negotiated `final_concession`, and the lease-back total."

    Design: Difficulty/dual_variant_calc/net_proceeds_provisional_vs_final_diverge_on_transaction
    """
    seller, prop, offer, txn, assessment, _ = setup_scheduled_transaction(
        repair_lines=STANDARD_REPAIR_LINES,
        leaseback_days=0,
        final_concession=7650.00,
    )
    # 510000 - 25500 - 7650 - 6634.57 - 0 = 470215.43.
    assert txn["final_net_proceeds"] == 470215.43, txn["final_net_proceeds"]
    assert txn["repair_credit"] == 6634.57, txn["repair_credit"]
    assert offer["preliminary_net_proceeds"] == 479400.00, offer["preliminary_net_proceeds"]
    assert txn["final_net_proceeds"] != offer["preliminary_net_proceeds"]


def test_full_close_sets_property_sold_and_final_proceeds(api):
    """PRD §3.7: "On close, the platform recomputes `final_net_proceeds` one last time
    from the prevailing inputs and locks it, moves the transaction
    `INSPECTION → CLOSED`, and moves the property to the terminal `SOLD` status; the
    accepted offer remains `ACCEPTED`."

    Design: Corner/state_machines/full_close_sets_property_sold_and_final_proceeds
    """
    seller, prop, offer, txn, assessment, _ = setup_inspection_transaction(
        repair_lines=STANDARD_REPAIR_LINES,
        leaseback_days=0,
        final_concession=7650.00,
    )
    closed = validate_success(api.close_transaction(txn["id"], {}, _ADMIN))
    assert closed["status"] == "CLOSED", closed["status"]
    assert closed["final_net_proceeds"] == 470215.43, closed["final_net_proceeds"]
    prop_after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert prop_after["status"] == "SOLD", prop_after["status"]


def test_close_date_at_min_lead_allowed(api):
    """PRD §3.5: "The chosen `close_date` must fall within the window that opens at
    least 7 days from the current logical-clock instant and extends no more than 90
    days from now; a date outside `[now + 7 days, now + 90 days]` is rejected with
    `ERR_CLOSE_DATE_OUT_OF_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/close_date_window_closed_interval_lower_bound
    """
    seller, prop, offer, txn, assessment, _ = setup_finalized_assessment()
    # clock at 2026-03-01; now+7d = 2026-03-08 exactly is inside the closed interval.
    scheduled = validate_success(
        api.schedule_close(
            txn["id"],
            {"close_date": "2026-03-08T00:00:00Z", "leaseback_days": 0, "final_concession": 0},
            make_seller_headers(seller["id"]),
        )
    )
    assert scheduled["status"] == "SCHEDULED", scheduled["status"]


def test_close_date_below_min_lead_rejected(api):
    """PRD §3.5: "a date outside `[now + 7 days, now + 90 days]` is rejected with
    `ERR_CLOSE_DATE_OUT_OF_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/close_date_window_closed_interval_lower_bound
    """
    seller, prop, offer, txn, assessment, _ = setup_finalized_assessment()
    # clock at 2026-03-01; close_date 2026-03-07 is now+6d, below MIN_CLOSE_LEAD_DAYS=7.
    validate_error(
        api.schedule_close(
            txn["id"],
            {"close_date": "2026-03-07T00:00:00Z", "leaseback_days": 0, "final_concession": 0},
            make_seller_headers(seller["id"]),
        ),
        ApiErrorId.ERR_CLOSE_DATE_OUT_OF_WINDOW,
    )


def test_leaseback_days_above_max_rejected(api):
    """PRD §3.5: "The requested `leaseback_days` must be between 0 and the maximum of
    60 nights inclusive; exceeding 60 is rejected with `ERR_LEASEBACK_EXCEEDS_MAX`."

    Design: Corner/calculations/leaseback_days_above_max_rejected
    """
    seller, prop, offer, txn, assessment, _ = setup_finalized_assessment()
    validate_error(
        api.schedule_close(
            txn["id"],
            {"close_date": "2026-03-15T00:00:00Z", "leaseback_days": 61, "final_concession": 0},
            make_seller_headers(seller["id"]),
        ),
        ApiErrorId.ERR_LEASEBACK_EXCEEDS_MAX,
    )


def test_close_from_scheduled_without_inspection_rejected(api):
    """PRD §3.7: "Closing a transaction is a back-office action available only while
    the transaction is in `INSPECTION`"
    PRD §3.7: "A close attempted on a transaction that is not in `INSPECTION`, like
    any other transition attempted from an invalid state, is rejected with
    `ERR_INVALID_STATE`"

    Design: Corner/state_machines/close_from_scheduled_without_inspection_returns_invalid_state
    """
    seller, prop, offer, txn, assessment, _ = setup_scheduled_transaction()
    # Transaction is SCHEDULED; start-inspection not called.
    validate_error(
        api.close_transaction(txn["id"], {}, _ADMIN),
        ApiErrorId.ERR_INVALID_STATE,
    )
