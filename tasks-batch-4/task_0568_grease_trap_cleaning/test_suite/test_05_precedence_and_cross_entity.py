"""Validation precedence (state>fiscal, safety>temporal), cross-entity state dependencies,
and the zero-billable-lines boundary — all difficulty queue."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_technician_headers, get_success_data,
)
from test_helpers.fixtures import (
    new_customer, new_site, new_equipment, new_technician, new_work_order,
    new_active_contract, new_draft_invoice, dispatch_work_order, start_work_order,
    file_manifest, setup_issued_invoice, setup_draft_invoice_base_rate,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ─────────────── state (P5) outranks fiscal (P13) ───────────────
def test_reissue_issued_invoice_masked_by_state_check(api):
    """PRD §2.11: "a work order in the wrong from-state receives `ERR_INVALID_STATE` before
    any safety or schedule check runs."

    Design: Difficulty/priority_pair_validation_conflict/state_outranks_fiscal_on_reissue
    """
    # Issue once so outstanding == credit_limit (fiscal would also fail on reissue).
    ctx = setup_issued_invoice(credit_limit_cents=12500, base_rate_cents=12500, tax_rate_bps=0)
    res = api.issue_invoice(ctx["inv_id"], BILLING)
    validate_error(res, "ERR_INVALID_STATE")


def test_reissue_state_check_fires_even_when_fiscal_ok(api):
    """PRD §2.11: "Because this order is total, an earlier failure always masks a later one".

    Design: Difficulty/priority_pair_validation_conflict/state_outranks_fiscal_on_reissue
    """
    # Generous credit: fiscal standing is fine, yet the from-state check still rejects a reissue.
    ctx = setup_issued_invoice(credit_limit_cents=1000000, base_rate_cents=12500, tax_rate_bps=0)
    res = api.issue_invoice(ctx["inv_id"], BILLING)
    validate_error(res, "ERR_INVALID_STATE")


# ─────────────── safety (P7) outranks temporal (P9) ───────────────
def _basic_tech_with_dispatched_grease_and_pending_hood():
    cust = new_customer()
    site = new_site(cust["id"])
    eqg = new_equipment(site["id"], equipment_type="GREASE_TRAP")
    eqh = new_equipment(site["id"], equipment_type="HOOD", capacity_gallons=0, nominal_frequency_days=90)
    tech = new_technician("BASIC")
    wog = new_work_order(site["id"], eqg["id"], planned_start="2026-05-10T10:00:00Z",
                         planned_end="2026-05-10T12:00:00Z")
    woh = new_work_order(site["id"], eqh["id"], planned_start="2026-05-10T10:00:00Z",
                         planned_end="2026-05-10T12:00:00Z")
    dispatch_work_order(wog["id"], tech["id"])
    return woh, tech


def test_hood_dispatch_to_double_booked_basic_tech_is_safety_error(api):
    """PRD §2.11: "Safety — NFPA 96 certification rules on hood dispatch and completion
    (`ERR_TECHNICIAN_NOT_CERTIFIED`, 422 ...". This is priority 7, ahead of the priority-9
    technician-schedule check, so the certification failure masks the overlap.

    Design: Difficulty/priority_pair_validation_conflict/safety_outranks_temporal_on_dispatch
    """
    woh, tech = _basic_tech_with_dispatched_grease_and_pending_hood()
    res = api.transition_work_order(
        woh["id"], {"to_status": "DISPATCHED", "technician_id": tech["id"]}, DISPATCHER)
    validate_error(res, "ERR_TECHNICIAN_NOT_CERTIFIED")


def test_hood_dispatch_to_basic_tech_rejected_regardless_of_schedule(api):
    """PRD §3.3: "the referenced `Technician` must exist and, when the equipment is a `HOOD`,
    must have `certification_level` `NFPA96_CERTIFIED`, or the order is rejected with
    `ERR_TECHNICIAN_NOT_CERTIFIED`".

    Design: Difficulty/priority_pair_validation_conflict/safety_outranks_temporal_on_dispatch
    """
    # No competing assignment at all — the safety check alone still rejects a BASIC tech on HOOD.
    cust = new_customer()
    site = new_site(cust["id"])
    eqh = new_equipment(site["id"], equipment_type="HOOD", capacity_gallons=0, nominal_frequency_days=90)
    tech = new_technician("BASIC")
    woh = new_work_order(site["id"], eqh["id"], planned_end="2026-05-10T12:00:00Z")
    res = api.transition_work_order(
        woh["id"], {"to_status": "DISPATCHED", "technician_id": tech["id"]}, DISPATCHER)
    validate_error(res, "ERR_TECHNICIAN_NOT_CERTIFIED")


# ─────────────── cross-entity: dispatch requires Equipment ACTIVE ───────────────
def test_dispatch_to_decommissioned_equipment_rejected(api):
    """PRD §3.3: "the referenced `Equipment` must be `ACTIVE`, or the order is rejected with
    `ERR_EQUIPMENT_DECOMMISSIONED`".

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_equipment_active
    """
    cust = new_customer()
    site = new_site(cust["id"])
    eq = new_equipment(site["id"])
    get_success_data(api_client.decommission_equipment(eq["id"], ADMIN))
    tech = new_technician("BASIC")
    wo = new_work_order(site["id"], eq["id"])
    res = api.transition_work_order(
        wo["id"], {"to_status": "DISPATCHED", "technician_id": tech["id"]}, DISPATCHER)
    validate_error(res, "ERR_EQUIPMENT_DECOMMISSIONED")


def test_dispatch_to_active_equipment_succeeds(api):
    """PRD §3.3: "A `Dispatcher` routes a `SCHEDULED` order by supplying a target `to_status`
    of `DISPATCHED` together with a `technician_id`, which advances the order
    `SCHEDULED → DISPATCHED` and records the assignment."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_equipment_active
    """
    cust = new_customer()
    site = new_site(cust["id"])
    eq = new_equipment(site["id"])
    tech = new_technician("BASIC")
    wo = new_work_order(site["id"], eq["id"])
    res = api.transition_work_order(
        wo["id"], {"to_status": "DISPATCHED", "technician_id": tech["id"]}, DISPATCHER)
    dispatched = validate_success(res, 200)
    assert dispatched["status"] == "DISPATCHED", "dispatch to ACTIVE equipment must succeed"


# ─────────────── cross-entity: issue requires Customer not CLOSED ───────────────
def test_issue_for_closed_customer_rejected(api):
    """PRD §3.7: "the customer must not be `CLOSED`, else `ERR_CUSTOMER_CLOSED`".

    Design: Difficulty/cross_entity_state_dependency/issue_requires_customer_not_closed
    """
    cust = new_customer(credit_limit_cents=1000000)
    contract = new_active_contract(cust["id"], base_rate_cents=12500, tax_rate_bps=0)
    get_success_data(api_client.close_customer(cust["id"], ADMIN))  # balance is 0, close ok
    inv = new_draft_invoice(cust["id"], contract_id=contract["id"])
    res = api.issue_invoice(inv["id"], BILLING)
    validate_error(res, "ERR_CUSTOMER_CLOSED")


def test_issue_for_active_customer_succeeds(api):
    """PRD §3.7: "Issuing a `DRAFT` invoice moves it `DRAFT → ISSUED` and freezes the final amount."

    Design: Difficulty/cross_entity_state_dependency/issue_requires_customer_not_closed
    """
    ctx = setup_draft_invoice_base_rate(credit_limit_cents=1000000, base_rate_cents=12500,
                                        tax_rate_bps=0)
    res = api.issue_invoice(ctx["inv_id"], BILLING)
    issued = validate_success(res, 200)
    assert issued["status"] == "ISSUED", "issue must succeed for a non-CLOSED customer"


# ─────────────── boundary: zero vs one billable line at issue ───────────────
def test_issue_with_zero_billable_lines_rejected(api):
    """PRD §3.7: "the invoice must have at least one billable line — with no completed work
    and no positive base rate there is nothing to bill, and the issue is rejected with
    `ERR_NO_BILLABLE_ACTIVITY`".

    Design: Difficulty/boundary_precision_check/zero_billable_lines_boundary
    """
    cust = new_customer(credit_limit_cents=1000000)
    contract = new_active_contract(cust["id"], base_rate_cents=0, tax_rate_bps=0)
    inv = new_draft_invoice(cust["id"], contract_id=contract["id"])
    res = api.issue_invoice(inv["id"], BILLING)
    validate_error(res, "ERR_NO_BILLABLE_ACTIVITY")


def test_issue_with_one_billable_line_succeeds(api):
    """PRD §3.7: "There is then one line per included work order, each valued at that order's
    `service_fee_cents` plus its `emergency_surcharge_cents`."

    Design: Difficulty/boundary_precision_check/zero_billable_lines_boundary
    """
    # base_rate 0 (no base line) but one COMPLETED grease work order => exactly one billable line.
    cust = new_customer(credit_limit_cents=1000000)
    site = new_site(cust["id"])
    eq = new_equipment(site["id"])
    contract = new_active_contract(cust["id"], base_rate_cents=0, tax_rate_bps=0)
    tech = new_technician("BASIC")
    wo = new_work_order(site["id"], eq["id"], contract_id=contract["id"])
    dispatch_work_order(wo["id"], tech["id"])
    start_work_order(wo["id"], tech["id"])
    file_manifest(wo["id"], tech["id"], disposal_facility_permit="FAC-1", volume_gallons=50)
    get_success_data(api_client.complete_work_order(
        wo["id"], {"actual_hours": 2}, make_technician_headers(tech["id"])))
    inv = new_draft_invoice(cust["id"], contract_id=contract["id"])
    res = api.issue_invoice(inv["id"], BILLING)
    issued = validate_success(res, 200)
    assert issued["status"] == "ISSUED"
    assert issued["subtotal_cents"] == 12500, "the single completed grease line is 12500"
