"""Fleet credit headroom, the outstanding-balance ledger, and compensating credits.

Translates difficulty rules: transitive_cascade (finish -> ledger debit),
dual_variant_calc (headroom estimate vs invoice variant), boundary_precision_check
(inclusive headroom at finish), priority_pair_validation_conflict (credit beats
suspended), cross_entity_state_dependency (approve blocked by suspended fleet),
compensating_invariant (refund conserves balance); plus corner cross-cutting ledger
reconciliation and the fleet-payments reverse list.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    make_customer_headers, make_mechanic_headers, make_fleet_manager_headers,
    set_clock, create_fleet_account, create_customer, create_mechanic,
    create_service_request, create_catalog_part, send_quote, approve_quote,
    dispatch, source_part_line, finish_visit, add_finding, resolve_addons,
    setup_dispatched_request, setup_quoted_request, get_request_payment,
    _sr_version, create_approve_quote_payload,
)
from test_helpers.test_users import TEST_USERS

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _drive_fleet_job_to_finish(email, fleet_discount=0.20, credit_limit=1_000_000,
                               part_wholesale=4000, part_qty=2, est_hours=2.0,
                               est_parts=8000, rate=9000, logged_hours=2.0):
    """Helper: fleet-billed request driven through finish (Payment INVOICED).

    Returns (fleet, customer, mechanic, service_request, payment).
    """
    fleet = create_fleet_account(credit_limit_cents=credit_limit,
                                 labor_discount_pct=fleet_discount)
    part = create_catalog_part(wholesale_cost_cents=part_wholesale, sku="LP-" + email[:4],
                               name="Pad")
    customer = create_customer(home_zone_code="Z1", fleet_account_id=fleet["id"],
                               email=email)
    mechanic = create_mechanic(zone_code="Z1", skill_tier="TIER2",
                               labor_rate_cents_per_hour=rate)
    sr = create_service_request(customer["id"], vehicle_vin="1HGCM82633A004370")
    quote = send_quote(sr["id"], mechanic["id"], estimated_labor_hours=est_hours,
                       estimated_parts_cents=est_parts, labor_rate_cents_per_hour=rate)
    approve_quote(quote["id"], customer["id"], sr["id"])
    jv = dispatch(sr["id"], mechanic["id"], routing_mode="ON_SITE",
                  scheduled_start_utc="2026-04-02T09:00:00Z",
                  scheduled_end_utc="2026-04-02T11:00:00Z")
    source_part_line(sr["id"], mechanic["id"], part["id"], quantity=part_qty)
    mech_headers = make_mechanic_headers(mechanic["id"])
    get_success_data(api_client.depart(jv["id"], mech_headers))
    get_success_data(api_client.start_work(jv["id"], mech_headers))
    finish_visit(jv["id"], mechanic["id"], logged_labor_hours=logged_hours,
                 payment_method="FLEET_CREDIT")
    payment = get_request_payment(sr["id"])
    return fleet, customer, mechanic, sr, payment


# ── Difficulty: depth-3 cascade finish -> request -> payment -> ledger ──

def test_finish_cascade_visit_to_request_to_payment_to_fleet_ledger(api):
    """PRD §3.6: "creates a `Payment` in `INVOICED` status whose `total_due_cents` is
    copied from the request's `final_total_cents`".
    PRD §3.6: "on success the payment's `fleet_account_id` is snapshotted from the request
    and the fleet account's `outstanding_balance_cents` is increased by the payment's
    `total_due_cents`."

    Design: Difficulty/transitive_cascade/finish_cascade_visit_to_request_to_payment_to_fleet_ledger
    """
    set_clock()
    fleet, customer, mechanic, sr, payment = _drive_fleet_job_to_finish(
        "m7@x.com", fleet_discount=0.20, credit_limit=1_000_000)
    jv_id = get_success_data(
        api.get_service_request(sr["id"], DISPATCHER))  # confirm completion
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "COMPLETED"
    assert sr_after["final_total_cents"] == 26000
    assert payment["status"] == "INVOICED"
    assert payment["total_due_cents"] == 26000
    fleet_after = validate_success(api.get_fleet_account(fleet["id"],
                                   make_fleet_manager_headers(fleet["id"])), 200)
    assert fleet_after["outstanding_balance_cents"] == 26000


def test_finish_cascade_marks_visit_finished(api):
    """PRD §3.6: "moves the visit `ON_SITE_WORKING → FINISHED` or `AT_SHOP → FINISHED`
    (which in turn drives the request `IN_PROGRESS → COMPLETED`)".

    Design: Difficulty/transitive_cascade/finish_cascade_visit_to_request_to_payment_to_fleet_ledger
    """
    set_clock()
    fleet, customer, mechanic, sr, payment = _drive_fleet_job_to_finish(
        "m7b@x.com", fleet_discount=0.20, credit_limit=1_000_000)
    data, _meta = validate_paginated(api.list_job_visits(
        DISPATCHER, params={"service_request_id": sr["id"]}))
    assert len(data) == 1
    assert data[0]["visit_status"] == "FINISHED"


# ── Difficulty: headroom estimate variant passes, invoice variant fails ──

def test_fleet_headroom_estimate_passes_invoice_variant_fails(api):
    """PRD §3.7: "At quote approval the projected charge is the request's
    `estimate_total_cents`. At job finish, immediately before the ledger debit, the
    projected charge is the request's `final_total_cents`. Because the final total may
    exceed the estimate, a request that cleared the headroom check at approval can still
    fail it at finish."
    PRD §3.7: "A failure is rejected with `ERR_FLEET_CREDIT_EXCEEDED` (HTTP 402)."

    Design: Difficulty/dual_variant_calc/fleet_headroom_estimate_variant_vs_invoice_variant
    """
    set_clock()
    addon_part = create_catalog_part(wholesale_cost_cents=200, sku="CP2", name="Sensor")
    fleet = create_fleet_account(credit_limit_cents=30000, labor_discount_pct=0,
                                 company_name="Acme Fleet")
    customer = create_customer(home_zone_code="Z1", fleet_account_id=fleet["id"],
                               email="m2@x.com")
    mechanic = create_mechanic(zone_code="Z1", skill_tier="TIER2",
                               labor_rate_cents_per_hour=12000)
    sr = create_service_request(customer["id"], vehicle_vin="1HGCM82633A004353")
    quote = send_quote(sr["id"], mechanic["id"], estimated_labor_hours=2.5,
                       estimated_parts_cents=0, labor_rate_cents_per_hour=12000)
    approve_quote(quote["id"], customer["id"], sr["id"])  # estimate 30000 == limit, passes
    sr_approved = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_approved["estimate_total_cents"] == 30000

    jv = dispatch(sr["id"], mechanic["id"], routing_mode="ON_SITE",
                  scheduled_start_utc="2026-04-02T09:00:00Z",
                  scheduled_end_utc="2026-04-02T11:00:00Z")
    mech_headers = make_mechanic_headers(mechanic["id"])
    get_success_data(api.depart(jv["id"], mech_headers))
    get_success_data(api.start_work(jv["id"], mech_headers))
    finding = add_finding(sr["id"], mechanic["id"], jv["id"], description="extra sensor",
                          recommended_part_id=addon_part["id"], recommended_quantity=1,
                          add_on_labor_hours=0)
    resolve_addons(sr["id"], customer["id"],
                   [{"finding_id": finding["id"], "decision": "APPROVED"}])

    from test_helpers import create_finish_payload
    res = api.finish(jv["id"], create_finish_payload(2.5, payment_method="FLEET_CREDIT"),
                     mech_headers)
    validate_error(res, "ERR_FLEET_CREDIT_EXCEEDED", expected_status=402)
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "IN_PROGRESS"
    fleet_after = validate_success(api.get_fleet_account(fleet["id"],
                                   make_fleet_manager_headers(fleet["id"])), 200)
    assert fleet_after["outstanding_balance_cents"] == 0


def test_fleet_headroom_estimate_variant_approval_uses_estimate(api):
    """PRD §3.7: "This headroom check is applied at two distinct moments with two distinct
    projected charges. At quote approval the projected charge is the request's
    `estimate_total_cents`."
    PRD §3.2: "the request copies the quote's `quoted_total_cents` into its own
    `estimate_total_cents`".

    Design: Difficulty/dual_variant_calc/fleet_headroom_estimate_variant_vs_invoice_variant
    """
    set_clock()
    fleet = create_fleet_account(credit_limit_cents=30000, labor_discount_pct=0,
                                 company_name="Acme Fleet 2")
    customer = create_customer(home_zone_code="Z1", fleet_account_id=fleet["id"],
                               email="m2b@x.com")
    mechanic = create_mechanic(zone_code="Z1", skill_tier="TIER2",
                               labor_rate_cents_per_hour=12000)
    sr = create_service_request(customer["id"], vehicle_vin="1HGCM82633A004383")
    quote = send_quote(sr["id"], mechanic["id"], estimated_labor_hours=2.5,
                       estimated_parts_cents=0, labor_rate_cents_per_hour=12000)
    # estimate 30000 == credit limit: the at-approval headroom passes (inclusive boundary).
    approve_quote(quote["id"], customer["id"], sr["id"])
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "APPROVED"
    assert sr_after["estimate_total_cents"] == 30000


# ── Difficulty: inclusive headroom boundary at finish (== limit passes) ──

def test_fleet_headroom_inclusive_boundary_at_finish(api):
    """PRD §3.7: "The boundary is inclusive: a projected balance exactly equal to
    `credit_limit_cents` passes, while a projected balance of even one cent more fails."

    Design: Difficulty/boundary_precision_check/fleet_headroom_inclusive_boundary_at_finish
    """
    set_clock()
    fleet = create_fleet_account(credit_limit_cents=30000, labor_discount_pct=0,
                                 company_name="Edge Fleet")
    customer = create_customer(home_zone_code="Z1", fleet_account_id=fleet["id"],
                               email="m11@x.com")
    mechanic = create_mechanic(zone_code="Z1", skill_tier="TIER2",
                               labor_rate_cents_per_hour=12000)
    sr = create_service_request(customer["id"], vehicle_vin="1HGCM82633A004362")
    quote = send_quote(sr["id"], mechanic["id"], estimated_labor_hours=2.5,
                       estimated_parts_cents=0, labor_rate_cents_per_hour=12000)
    approve_quote(quote["id"], customer["id"], sr["id"])
    jv = dispatch(sr["id"], mechanic["id"], routing_mode="ON_SITE",
                  scheduled_start_utc="2026-04-02T09:00:00Z",
                  scheduled_end_utc="2026-04-02T12:00:00Z")
    mech_headers = make_mechanic_headers(mechanic["id"])
    get_success_data(api.depart(jv["id"], mech_headers))
    get_success_data(api.start_work(jv["id"], mech_headers))
    finish_visit(jv["id"], mechanic["id"], logged_labor_hours=2.5,
                 payment_method="FLEET_CREDIT")  # final exactly 30000 == limit

    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "COMPLETED"
    assert sr_after["final_total_cents"] == 30000
    fleet_after = validate_success(api.get_fleet_account(fleet["id"],
                                   make_fleet_manager_headers(fleet["id"])), 200)
    assert fleet_after["outstanding_balance_cents"] == 30000


def test_fleet_headroom_just_over_limit_at_finish_rejected(api):
    """PRD §3.7: "The boundary is inclusive: a projected balance exactly equal to
    `credit_limit_cents` passes, while a projected balance of even one cent more fails. A
    failure is rejected with `ERR_FLEET_CREDIT_EXCEEDED` (HTTP 402)."

    Design: Difficulty/boundary_precision_check/fleet_headroom_inclusive_boundary_at_finish
    """
    set_clock()
    # Limit one cent below the exact final (30000) so finish projects 30000 > 29999 -> fail.
    fleet = create_fleet_account(credit_limit_cents=29999, labor_discount_pct=0,
                                 company_name="Edge Fleet 2")
    customer = create_customer(home_zone_code="Z1", fleet_account_id=fleet["id"],
                               email="m11b@x.com")
    mechanic = create_mechanic(zone_code="Z1", skill_tier="TIER2",
                               labor_rate_cents_per_hour=12000)
    sr = create_service_request(customer["id"], vehicle_vin="1HGCM82633A004382")
    quote = send_quote(sr["id"], mechanic["id"], estimated_labor_hours=2.0,
                       estimated_parts_cents=0, labor_rate_cents_per_hour=12000)
    # estimate 24000 <= 29999: approval passes.
    approve_quote(quote["id"], customer["id"], sr["id"])
    jv = dispatch(sr["id"], mechanic["id"], routing_mode="ON_SITE",
                  scheduled_start_utc="2026-04-02T09:00:00Z",
                  scheduled_end_utc="2026-04-02T12:00:00Z")
    mech_headers = make_mechanic_headers(mechanic["id"])
    get_success_data(api.depart(jv["id"], mech_headers))
    get_success_data(api.start_work(jv["id"], mech_headers))
    from test_helpers import create_finish_payload
    # logged 2.5h -> final 30000 == limit+1 -> rejected.
    res = api.finish(jv["id"], create_finish_payload(2.5, payment_method="FLEET_CREDIT"),
                     mech_headers)
    validate_error(res, "ERR_FLEET_CREDIT_EXCEEDED", expected_status=402)
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "IN_PROGRESS"


# ── Difficulty: credit-exceeded (P12) beats suspended (P13) on approve ──

def test_fleet_credit_exceeded_beats_suspended_on_approve(api):
    """PRD §3.2: "the fleet headroom check of §3.7 runs at this point using the estimate,
    and if the fleet account is suspended the approval is rejected with
    `ERR_FLEET_ACCOUNT_SUSPENDED` (HTTP 409)."
    PRD §3.7: "A failure is rejected with `ERR_FLEET_CREDIT_EXCEEDED` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/fleet_suspended_beats_credit_exceeded_on_approve
    """
    set_clock()
    fleet = create_fleet_account(credit_limit_cents=10000, labor_discount_pct=0,
                                 company_name="Crane Fleet")
    customer = create_customer(home_zone_code="Z1", fleet_account_id=fleet["id"],
                               email="m10@x.com")
    mechanic = create_mechanic(zone_code="Z1", skill_tier="TIER2",
                               labor_rate_cents_per_hour=9000)
    sr = create_service_request(customer["id"], vehicle_vin="1HGCM82633A004361")
    quote = send_quote(sr["id"], mechanic["id"], estimated_labor_hours=2.0,
                       estimated_parts_cents=0, labor_rate_cents_per_hour=9000)  # est 18000 > 10000
    get_success_data(api.suspend_fleet_account(fleet["id"], TEST_USERS["platform_admin_headers"]))

    version = _sr_version(sr["id"])
    res = api.approve_quote(quote["id"], create_approve_quote_payload(version),
                            make_customer_headers(customer["id"]))
    validate_error(res, "ERR_FLEET_CREDIT_EXCEEDED", expected_status=402)
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "QUOTED"
    assert sr_after["estimate_total_cents"] is None


def test_fleet_credit_exceeded_beats_suspended_leaves_quote_sent(api):
    """PRD §3.2: "On success the quote moves `SENT → APPROVED`".
    PRD §3.7: "A failure is rejected with `ERR_FLEET_CREDIT_EXCEEDED` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/fleet_suspended_beats_credit_exceeded_on_approve
    """
    set_clock()
    fleet = create_fleet_account(credit_limit_cents=10000, labor_discount_pct=0,
                                 company_name="Crane Fleet 2")
    customer = create_customer(home_zone_code="Z1", fleet_account_id=fleet["id"],
                               email="m10b@x.com")
    mechanic = create_mechanic(zone_code="Z1", skill_tier="TIER2",
                               labor_rate_cents_per_hour=9000)
    sr = create_service_request(customer["id"], vehicle_vin="1HGCM82633A004381")
    quote = send_quote(sr["id"], mechanic["id"], estimated_labor_hours=2.0,
                       estimated_parts_cents=0, labor_rate_cents_per_hour=9000)  # est 18000 > 10000
    get_success_data(api.suspend_fleet_account(fleet["id"], TEST_USERS["platform_admin_headers"]))
    version = _sr_version(sr["id"])
    res = api.approve_quote(quote["id"], create_approve_quote_payload(version),
                            make_customer_headers(customer["id"]))
    validate_error(res, "ERR_FLEET_CREDIT_EXCEEDED", expected_status=402)
    # The quote is untouched — still SENT and approvable on a corrected setup.
    quote_after = validate_success(api.get_quote(quote["id"], DISPATCHER), 200)
    assert quote_after["status"] == "SENT"


# ── Difficulty: approve blocked when fleet suspended (estimate within limit) ──

def test_quote_approve_blocked_when_fleet_suspended(api):
    """PRD §3.2: "if the request carries a `fleet_account_id` — the referenced fleet
    account is `ACTIVE`."
    PRD §3.2: "if the fleet account is suspended the approval is rejected with
    `ERR_FLEET_ACCOUNT_SUSPENDED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/quote_approve_blocked_when_fleet_suspended
    """
    set_clock()
    fleet = create_fleet_account(credit_limit_cents=1_000_000, labor_discount_pct=0,
                                 company_name="Delta Fleet")
    customer = create_customer(home_zone_code="Z1", fleet_account_id=fleet["id"],
                               email="m13@x.com")
    mechanic = create_mechanic(zone_code="Z1", skill_tier="TIER2",
                               labor_rate_cents_per_hour=9000)
    sr = create_service_request(customer["id"], vehicle_vin="1HGCM82633A004364")
    quote = send_quote(sr["id"], mechanic["id"], estimated_labor_hours=2.0,
                       estimated_parts_cents=0, labor_rate_cents_per_hour=9000)  # est 18000 < limit
    get_success_data(api.suspend_fleet_account(fleet["id"], TEST_USERS["platform_admin_headers"]))

    version = _sr_version(sr["id"])
    res = api.approve_quote(quote["id"], create_approve_quote_payload(version),
                            make_customer_headers(customer["id"]))
    validate_error(res, "ERR_FLEET_ACCOUNT_SUSPENDED", expected_status=409)
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "QUOTED"
    quote_after = validate_success(api.get_quote(quote["id"], DISPATCHER), 200)
    assert quote_after["status"] == "SENT"


def test_quote_approve_suspended_fleet_leaves_quote_sent(api):
    """PRD §3.2: "Approving a quote is the pivotal transition. It is permitted only when
    the request is in `QUOTED`, the target quote is in `SENT`, and — if the request
    carries a `fleet_account_id` — the referenced fleet account is `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/quote_approve_blocked_when_fleet_suspended
    """
    set_clock()
    fleet = create_fleet_account(credit_limit_cents=1_000_000, labor_discount_pct=0,
                                 company_name="Delta Fleet 2")
    customer = create_customer(home_zone_code="Z1", fleet_account_id=fleet["id"],
                               email="m13b@x.com")
    mechanic = create_mechanic(zone_code="Z1", skill_tier="TIER2",
                               labor_rate_cents_per_hour=9000)
    sr = create_service_request(customer["id"], vehicle_vin="1HGCM82633A004384")
    quote = send_quote(sr["id"], mechanic["id"], estimated_labor_hours=2.0,
                       estimated_parts_cents=0, labor_rate_cents_per_hour=9000)
    get_success_data(api.suspend_fleet_account(fleet["id"], TEST_USERS["platform_admin_headers"]))
    version = _sr_version(sr["id"])
    res = api.approve_quote(quote["id"], create_approve_quote_payload(version),
                            make_customer_headers(customer["id"]))
    validate_error(res, "ERR_FLEET_ACCOUNT_SUSPENDED", expected_status=409)
    quote_after = validate_success(api.get_quote(quote["id"], DISPATCHER), 200)
    assert quote_after["status"] == "SENT"


# ── Difficulty: refund conserves the fleet outstanding balance ──

def test_refund_conserves_fleet_outstanding_balance(api):
    """PRD §3.8: "A dispatcher may instead refund an invoiced payment, moving it
    `INVOICED → REFUNDED`; if the payment is fleet-billed the fleet ledger is likewise
    credited by `total_due_cents` to compensate the original invoice debit".

    Design: Difficulty/compensating_invariant/refund_conserves_fleet_outstanding_balance
    """
    set_clock()
    fleet, customer, mechanic, sr, payment = _drive_fleet_job_to_finish(
        "m17@x.com", fleet_discount=0.20, credit_limit=1_000_000)
    assert payment["total_due_cents"] == 26000

    res = api.refund_payment(payment["id"], DISPATCHER)
    refunded = validate_success(res, 200)
    assert refunded["status"] == "REFUNDED"
    fleet_after = validate_success(api.get_fleet_account(fleet["id"],
                                   make_fleet_manager_headers(fleet["id"])), 200)
    assert fleet_after["outstanding_balance_cents"] == 0


def test_refund_marks_payment_refunded(api):
    """PRD §3.8: "A dispatcher may instead refund an invoiced payment, moving it
    `INVOICED → REFUNDED`".
    PRD §2.9: "settlement and refund each subtract exactly the amount the invoice
    originally added."

    Design: Difficulty/compensating_invariant/refund_conserves_fleet_outstanding_balance
    """
    set_clock()
    fleet, customer, mechanic, sr, payment = _drive_fleet_job_to_finish(
        "m17b@x.com", fleet_discount=0.20, credit_limit=1_000_000)
    # Pre-refund ledger holds exactly the invoice.
    fleet_before = validate_success(api.get_fleet_account(fleet["id"],
                                    make_fleet_manager_headers(fleet["id"])), 200)
    assert fleet_before["outstanding_balance_cents"] == 26000

    refunded = validate_success(api.refund_payment(payment["id"], DISPATCHER), 200)
    assert refunded["status"] == "REFUNDED"
    fleet_after = validate_success(api.get_fleet_account(fleet["id"],
                                   make_fleet_manager_headers(fleet["id"])), 200)
    assert fleet_after["outstanding_balance_cents"] == 0


# ── Corner: settle reconciles the ledger to zero ──

def test_ledger_credit_on_settle_reconciles(api):
    """PRD §3.8: "On success the payment moves `INVOICED → SETTLED`, and if the payment
    carries a fleet account the fleet's `outstanding_balance_cents` is decreased by the
    payment's `total_due_cents`, conserving the ledger invariant."

    Design: Corner/cross_cutting_complexity_layers/ledger_credit_on_settle_reconciles
    """
    set_clock()
    fleet, customer, mechanic, sr, payment = _drive_fleet_job_to_finish(
        "c27@x.com", fleet_discount=0.20, credit_limit=1_000_000)
    assert payment["total_due_cents"] == 26000

    res = api.settle_payment(payment["id"], make_fleet_manager_headers(fleet["id"]))
    settled = validate_success(res, 200)
    assert settled["status"] == "SETTLED"
    fleet_after = validate_success(api.get_fleet_account(fleet["id"],
                                   make_fleet_manager_headers(fleet["id"])), 200)
    assert fleet_after["outstanding_balance_cents"] == 0


# ── Corner: fleet payments reverse list ──

def test_fleet_payments_reverse_list(api):
    """PRD §2.9: "A `FleetAccount` carries a running `outstanding_balance_cents` ... It is
    debited — increased — when a fleet-billed job is invoiced".
    PRD §3.6: "the payment's `fleet_account_id` is snapshotted from the request".

    Design: Corner/endpoints/fleet_payments_reverse_list
    """
    set_clock()
    fleet, customer, mechanic, sr, payment = _drive_fleet_job_to_finish(
        "c18@x.com", fleet_discount=0.20, credit_limit=1_000_000)
    data, meta = validate_paginated(
        api.list_fleet_account_payments(fleet["id"], make_fleet_manager_headers(fleet["id"])))
    assert meta["total_count"] == 1
    assert data[0]["total_due_cents"] == 26000
    assert data[0]["status"] == "INVOICED"
