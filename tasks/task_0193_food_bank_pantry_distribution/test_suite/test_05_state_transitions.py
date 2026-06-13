"""State-machine corner cases: invalid/guarded transitions, terminal-state
lockdowns, the certify DENIED branch, and certification aging.

Covers Corner queue section state_machines.
"""
from prd_bench_local_runner.testing import validate_success, validate_error
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, fixtures, factories,
    make_agency_coordinator_headers,
)

MGR = TEST_USERS["allocation_manager_headers"]
OP = TEST_USERS["food_bank_operator_headers"]
AUD = TEST_USERS["compliance_auditor_headers"]


def test_dispose_already_disposed_lot_returns_invalid_state(api):
    """PRD §3.1: "Attempting to dispose a lot that is in neither EXPIRED nor
    AVAILABLE — for instance a RESERVED or already DISPOSED lot — has no defined
    transition and is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/dispose_already_disposed_lot_returns_invalid_state
    """
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    lot = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                        intake_lbs=100,
                                        expiration_date="2026-07-01T00:00:00.000Z")
    disposed = validate_success(api.dispose_inventory_lot(
        lot["id"], {"expected_lot_version": lot["version"]}, OP))
    resp = api.dispose_inventory_lot(
        lot["id"], {"expected_lot_version": disposed["version"]}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reject_already_approved_order_returns_invalid_state(api):
    """PRD §3.5: "A submitted order may instead be rejected by an AllocationManager:
    a SUBMITTED order moves to REJECTED"
    PRD §4: "then state-transition legality" — reject is defined only from
    SUBMITTED.

    Design: Corner/state_machines/reject_already_approved_order_returns_invalid_state
    """
    ctx = fixtures.setup_approved_order(requested_lbs=100, intake_lbs=300)
    resp = api.reject_agency_order(ctx["order"]["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_certify_branches_denied_on_ineligible_income(api):
    """PRD §3.3: "If the household is not tefap_eligible, the same certification
    action moves it from PENDING to DENIED."
    PRD §3.3: "The household is tefap_eligible when its monthly_income_cents is at
    or below this threshold"

    Design: Corner/state_machines/certify_household_branches_denied_on_ineligible_income
    """
    # size 1 threshold = 199800; income 199801 -> ineligible.
    agency = fixtures.create_agency()
    hh = fixtures.create_household(agency["id"], household_size=1, monthly_income_cents=199801)
    assert hh["tefap_eligible"] is False, \
        f"income 199801 > threshold 199800 should be ineligible, got {hh['tefap_eligible']}"
    certified = validate_success(api.certify_client_household(hh["id"], AUD))
    assert certified["certification_status"] == "DENIED", \
        f"ineligible household certifies to DENIED, got {certified['certification_status']}"


def test_certification_expires_after_365_days_on_clock_advance(api):
    """PRD §3.3: "when the logical clock advances to or past the point 365 days
    after certified_at, a CERTIFIED household ages from CERTIFIED to EXPIRED,
    bumping its version."

    Design: Corner/state_machines/certification_expires_after_365_days_on_clock_advance
    """
    api.set_clock("2026-06-01T00:00:00.000Z", MGR)
    agency = fixtures.create_agency()
    hh = fixtures.create_household(agency["id"], household_size=1, monthly_income_cents=100000)
    certified = validate_success(api.certify_client_household(hh["id"], AUD))
    assert certified["certification_status"] == "CERTIFIED"
    api.set_clock("2027-06-02T00:00:00.000Z", MGR)
    refetched = validate_success(api.get_client_household(hh["id"], AUD))
    assert refetched["certification_status"] == "EXPIRED", \
        f"certification should age to EXPIRED past 365 days, got {refetched['certification_status']}"


def test_terminal_fulfilled_order_cannot_cancel(api):
    """PRD §3.6: "An APPROVED order may be cancelled only when no DistributionEvent
    for it is PACKED or FINALIZED"
    PRD §4: "then state-transition legality" — cancel is undefined from FULFILLED.

    Design: Corner/state_machines/terminal_fulfilled_order_cannot_cancel
    """
    ctx = fixtures.setup_finalized_event(requested_lbs=100, intake_lbs=300,
                                         actual_distributed_lbs=100)
    agency_id = ctx["agency"]["id"]
    # order is now FULFILLED
    resp = api.cancel_agency_order(ctx["order"]["id"],
                                   make_agency_coordinator_headers(agency_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cycle_close_blocked_while_order_unresolved(api):
    """PRD §3.4: "The close transition moves a cycle from OPEN to CLOSED and is
    permitted only when no AgencyOrder in the cycle is still in SUBMITTED or
    APPROVED status"
    PRD §3.4: "A close attempted while an order remains open, or against a cycle
    not in OPEN, is refused as an invalid state transition."

    Design: Corner/state_machines/cycle_close_blocked_while_order_unresolved
    """
    agency = fixtures.create_agency()
    cycle = fixtures.create_open_cycle()
    fixtures.submit_order(agency["id"], cycle["id"],
                          lines=[{"food_category": "PRODUCE", "requested_lbs": 100}])
    resp = api.close_allocation_cycle(cycle["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    refetched = validate_success(api.get_allocation_cycle(cycle["id"], MGR))
    assert refetched["status"] == "OPEN", \
        f"cycle stays OPEN on blocked close, got {refetched['status']}"


def test_recall_blocked_when_order_finalized(api):
    """PRD §3.6: "An AllocationManager may recall an APPROVED order back to
    SUBMITTED for revision, provided no DistributionEvent for that order has
    reached PACKED or FINALIZED."
    PRD §4: "then state-transition legality" — recall is undefined from FULFILLED.

    Design: Corner/state_machines/recall_blocked_when_event_finalized
    """
    ctx = fixtures.setup_finalized_event(requested_lbs=100, intake_lbs=300,
                                         actual_distributed_lbs=100)
    resp = api.recall_agency_order(ctx["order"]["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
