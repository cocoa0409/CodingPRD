"""
Conserved quantities and the two kinds of compensation that restore them: a
cents-valued equipment ledger and an integer workload counter.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_axes,
    assert_equipment_ledger,
    assert_pct,
    assert_workload,
)
from test_helpers.test_users import ACCOUNT_MANAGER_HEADERS, PLATFORM_ADMIN_HEADERS
from test_helpers.types import (
    DECISION_REJECTED,
    OP_OFFLINE,
    PLACEMENT_CANCELLED,
    PLACEMENT_INSTALLED,
    PLACEMENT_RETRIEVAL_SCHEDULED,
    PLACEMENT_RETRIEVED,
    TICKET_DISPATCHED,
    TICKET_QUEUED,
    VERDICT_ADJUSTED,
    VISIT_REJECTED,
)

MODEL_BOOK_VALUE_CENTS = 480000


def _two_capitalised_machines(api):
    """
    One account whose ledger starts at zero, then two PENDING_INSTALL placements
    of the 480000-cent DT-88, so the ledger peaks at 960000 before either machine
    has been installed. No ticket is ever filed, so retrieval never blocks.
    """
    base = X.program_base(api)
    assert_equipment_ledger(base["customer"], 0)

    first = X.create_placement(api, base, asset_tag="AT-D01")
    second = X.create_placement(api, base, asset_tag="AT-D02")

    peak = get_success_data(api.get_customer(base["customer_id"], ACCOUNT_MANAGER_HEADERS))
    assert_equipment_ledger(peak, 2 * MODEL_BOOK_VALUE_CENTS)

    base["first_id"] = first["id"]
    base["second_id"] = second["id"]
    return base


def _ledger(api, base):
    customer = get_success_data(
        api.get_customer(base["customer_id"], ACCOUNT_MANAGER_HEADERS)
    )
    return customer["equipment_on_placement_value_cents"]


def test_cancelling_a_never_installed_machine_credits_exactly_its_book_value(api):
    """
    Both machines are capitalised at creation, so the ledger stands at 960000; a
    retrieval order against the never-installed second machine cancels it outright
    and credits back exactly 480000 — neither a partial nor a doubled amount.

    PRD §2.10: "Placing a machine capitalises that model's book value onto the
    ledger; cancelling a never-installed placement or completing a retrieval
    credits exactly the same amount back, restoring the ledger to its
    pre-placement value."

    Design: Difficulty/compensating_invariant/equipment_value_ledger_returns_to_zero_after_cancel_and_retrieval
    """
    base = _two_capitalised_machines(api)

    cancelled = validate_success(
        api.create_retrieval_order(base["second_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(
        cancelled,
        placement_status=PLACEMENT_CANCELLED,
        operational_status=OP_OFFLINE,
    )
    assert _ledger(api, base) == MODEL_BOOK_VALUE_CENTS

    # Only creation and removal move money: install and scheduling do not.
    X.install_placement(api, base, base["first_id"])
    assert _ledger(api, base) == MODEL_BOOK_VALUE_CENTS

    scheduled = validate_success(
        api.create_retrieval_order(
            base["first_id"],
            ACCOUNT_MANAGER_HEADERS,
            F.retrieval_order_payload("2026-09-15"),
        )
    )
    assert_axes(scheduled, placement_status=PLACEMENT_RETRIEVAL_SCHEDULED)
    assert _ledger(api, base) == MODEL_BOOK_VALUE_CENTS


def test_two_different_compensations_bring_the_ledger_back_to_zero(api):
    """
    The never-installed machine is credited back by cancellation and the installed
    one by retrieval completion; both paths land on exactly zero with no residue,
    while the agreement itself is still ACTIVE — the compensation is scoped to the
    equipment ledger alone.

    PRD §2.10: "`Customer.equipment_on_placement_value_cents` is at all times the
    sum, over that customer's placements whose `placement_status` is
    `PENDING_INSTALL`, `INSTALLED` or `RETRIEVAL_SCHEDULED`, of the
    `equipment_value_cents` of each placement's machine model."

    Design: Difficulty/compensating_invariant/equipment_value_ledger_returns_to_zero_after_cancel_and_retrieval
    """
    base = _two_capitalised_machines(api)

    validate_success(
        api.create_retrieval_order(base["second_id"], ACCOUNT_MANAGER_HEADERS)
    )
    installed = X.install_placement(api, base, base["first_id"])
    assert_axes(installed, placement_status=PLACEMENT_INSTALLED)
    validate_success(
        api.create_retrieval_order(
            base["first_id"],
            ACCOUNT_MANAGER_HEADERS,
            F.retrieval_order_payload("2026-09-15"),
        )
    )

    retrieved = validate_success(
        api.complete_retrieval(base["first_id"], base["technician_headers"])
    )
    assert_axes(retrieved, placement_status=PLACEMENT_RETRIEVED)
    assert _ledger(api, base) == 0

    customer = get_success_data(
        api.get_customer(base["customer_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert customer["active_agreement_count"] == 1
    agreement = get_success_data(
        api.get_service_agreement(base["agreement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert agreement["placement_count"] == 0


def _submitted_visit_with_a_staged_dose_change(api):
    """
    One dispatched RACK_QUALITY ticket whose visit has arrived, filed a single
    ADJUSTED record (1380 ppm against a 1200 ppm target, drift +15.00, adjusted
    dose 9.20) and been submitted, so the engineer's workload stands at one.
    """
    base = X.program_base(api)
    assert_workload(base["technician"], 0)
    assert base["technician"]["quality_flag_count"] == 0

    placement = X.installed_placement(api, base, asset_tag="AT-D03")
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)

    work = X.visit_in_progress(api, base, placement["id"])
    assert work["ticket"]["assigned_technician_id"] == base["technician_id"]

    after_dispatch = get_success_data(
        api.get_technician(base["technician_id"], PLATFORM_ADMIN_HEADERS)
    )
    assert_workload(after_dispatch, 1)

    record = X.record_calibration(
        api,
        base,
        work["visit_id"],
        dispenser["id"],
        measured_ppm=1380,
        measured_dose_ml_per_rack=8.00,
        adjusted_dose_ml_per_rack=9.20,
    )
    assert record["calibration_verdict"] == VERDICT_ADJUSTED
    assert_pct(record["drift_pct"], 15.00)
    assert record["applied"] is False

    X.submit_visit(api, base, work["visit_id"], repair_confirmed=True)

    base.update(
        {
            "placement_id": placement["id"],
            "dispenser_id": dispenser["id"],
            "dispenser": dispenser,
            "ticket_id": work["ticket_id"],
            "ticket": work["ticket"],
            "visit_id": work["visit_id"],
            "record_id": record["id"],
        }
    )
    return base


def test_rejection_releases_the_slot_and_leaves_the_dose_ledger_untouched(api):
    """
    A REJECTED visit returns the ticket to QUEUED with its engineer cleared, drops
    the workload counter back to zero and raises the quality flag — the single
    monotone residue. The staged 9.20 dose is never applied, so every dose field
    on the dispenser stands as it did before the visit.

    PRD §3.6: "The ticket returns `PENDING_VERIFICATION → QUEUED` with
    `assigned_technician_id` cleared, the technician's `open_ticket_count` drops by
    one — restoring the conserved workload counter of §2.10 — and that technician's
    `quality_flag_count` rises by one."

    Design: Difficulty/compensating_invariant/technician_workload_slots_restored_by_visit_rejection
    """
    base = _submitted_visit_with_a_staged_dose_change(api)

    visit = X.verify_visit(
        api,
        base["visit_id"],
        decision=DECISION_REJECTED,
        rejection_reason="concentration not re-verified after the dose change",
    )
    assert visit["visit_status"] == VISIT_REJECTED
    assert visit["rejection_reason"] == (
        "concentration not re-verified after the dose change"
    )

    technician = get_success_data(
        api.get_technician(base["technician_id"], PLATFORM_ADMIN_HEADERS)
    )
    assert_workload(technician, 0)
    assert technician["quality_flag_count"] == 1

    ticket = get_success_data(
        api.get_service_ticket(base["ticket_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert ticket["status"] == TICKET_QUEUED
    assert ticket["assigned_technician_id"] is None

    dispenser = get_success_data(
        api.get_dispenser(base["dispenser_id"], base["technician_headers"])
    )
    assert dispenser["calibrated_dose_ml_per_rack"] == pytest.approx(8.00, abs=0.01)
    assert dispenser["prior_dose_ml_per_rack"] is None
    assert dispenser["last_calibrated_at"] is None
    assert dispenser["last_drift_pct"] is None
    assert dispenser["dose_effective_at"] == base["dispenser"]["created_at"]

    record = get_success_data(
        api.get_calibration_record(base["record_id"], base["technician_headers"])
    )
    assert record["applied"] is False


def test_re_dispatch_consumes_the_released_slot_without_restamping_priority(api):
    """
    The released slot is genuinely available again: re-dispatching the requeued
    ticket takes the counter back to one, and the priority score and response
    deadline are exactly the values stamped at ticket creation, never recomputed.

    PRD §3.6: "The ticket keeps its original `priority_score` and
    `response_deadline_at`, and may be dispatched again, possibly to a different
    engineer, who may then book a follow-up visit pointing at this rejected one
    through `follow_up_to_visit_id`."

    Design: Difficulty/compensating_invariant/technician_workload_slots_restored_by_visit_rejection
    """
    base = _submitted_visit_with_a_staged_dose_change(api)
    original = base["ticket"]

    X.verify_visit(
        api,
        base["visit_id"],
        decision=DECISION_REJECTED,
        rejection_reason="concentration not re-verified after the dose change",
    )

    redispatched = X.dispatch_ticket(api, base["ticket_id"])
    assert redispatched["status"] == TICKET_DISPATCHED
    assert redispatched["assigned_technician_id"] == base["technician_id"]
    assert redispatched["priority_score"] == original["priority_score"]
    assert redispatched["response_deadline_at"] == original["response_deadline_at"]

    technician = get_success_data(
        api.get_technician(base["technician_id"], PLATFORM_ADMIN_HEADERS)
    )
    assert_workload(technician, 1)
    assert technician["quality_flag_count"] == 1
