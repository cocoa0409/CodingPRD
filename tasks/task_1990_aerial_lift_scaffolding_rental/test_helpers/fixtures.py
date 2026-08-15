"""Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server before every test, so each test starts against
an empty database). Setup calls use get_success_data() so failures surface as
clear "Setup step failed" errors instead of confusing assertion failures.

Identity threading: the Customer role is entity-backed (PRD §2.1) — after a
fixture creates a customer account, ownership-gated calls use
make_customer_headers(customer["id"]). Driver actions use
make_driver_headers(trip["driver_id"]).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_customer_account_payload, create_equipment_class_payload,
    create_equipment_unit_payload, create_rental_contract_payload,
    create_rental_line_payload, create_delivery_trip_payload,
    create_trip_completion_payload, create_trip_failure_payload,
    create_trip_reschedule_payload, create_inspection_record_payload,
    create_training_record_payload, create_damage_claim_payload,
    create_claim_assessment_payload, create_claim_resolution_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS, make_branch_manager_headers, make_driver_headers,
    make_customer_headers, make_yard_technician_headers,
)

BM = TEST_USERS["branch_manager_headers"]
RC = TEST_USERS["rental_coordinator_headers"]
YT = TEST_USERS["yard_technician_headers"]


# ─── Tier 1: clock and single-resource creation ─────────────────────────────

def set_clock(to_iso8601):
    """Advance the server-held logical clock (PRD §2.4). Returns the payload."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), BM))


def create_customer(company_name="Test Renter Co",
                    contact_email="ops@renter.example",
                    credit_limit_cents=100_000_000):
    """Create a customer account (starts ACTIVE, balance 0). Returns it."""
    return get_success_data(api_client.create_customer_account(
        create_customer_account_payload(company_name, contact_email,
                                        credit_limit_cents), BM), 201)


def create_equipment_class(class_code="S19", category="AERIAL_LIFT",
                           max_working_height_ft=25, min_rental_days=1,
                           daily_rate_cents=14500, weekly_rate_cents=43500,
                           monthly_rate_cents=99000,
                           replacement_value_cents=2_500_000,
                           requires_familiarization=False,
                           requires_engineering=False):
    """Create a catalog equipment class. Returns it."""
    return get_success_data(api_client.create_equipment_class(
        create_equipment_class_payload(
            class_code, category, max_working_height_ft, min_rental_days,
            daily_rate_cents, weekly_rate_cents, monthly_rate_cents,
            replacement_value_cents, requires_familiarization,
            requires_engineering), BM), 201)


def create_equipment_unit(class_id, serial_number="SN-0001",
                          ansi_standard_ref="ANSI A92.22"):
    """Register a serialized unit (AVAILABLE, factory PDI stamped). Returns it."""
    return get_success_data(api_client.create_equipment_unit(
        create_equipment_unit_payload(class_id, serial_number,
                                      ansi_standard_ref), BM), 201)


def create_contract(customer_id, jobsite_address="100 Main St",
                    damage_waiver_elected=False):
    """Open a rental contract in DRAFT. Returns the contract."""
    return get_success_data(api_client.create_rental_contract(
        create_rental_contract_payload(customer_id, jobsite_address,
                                       damage_waiver_elected), RC), 201)


def get_contract(contract_id):
    """Read one contract back (used to refresh its OCC version)."""
    return get_success_data(api_client.get_rental_contract(contract_id, RC))


# ─── Tier 2: booking — lines, activation ────────────────────────────────────

def add_line(contract_id, unit_id, requested_start_date, requested_end_date,
             required_working_height_ft, expected_contract_version=None,
             engineering_plan_ref=None):
    """Add a RESERVED rental line. When expected_contract_version is omitted,
    the parent contract's live version is read first. Returns the line."""
    if expected_contract_version is None:
        expected_contract_version = get_contract(contract_id)["version"]
    return get_success_data(api_client.create_rental_line(
        create_rental_line_payload(
            contract_id, unit_id, requested_start_date, requested_end_date,
            required_working_height_ft, expected_contract_version,
            engineering_plan_ref=engineering_plan_ref), RC), 201)


def activate_contract(contract_id):
    """Walk a DRAFT contract (with >=1 RESERVED line) to ACTIVE."""
    return get_success_data(api_client.activate_rental_contract(contract_id, RC))


def close_contract(contract_id):
    """Close an ACTIVE contract whose lines and claims are all resolved."""
    return get_success_data(api_client.close_rental_contract(contract_id, RC))


def setup_draft_contract_with_line(credit_limit_cents=100_000_000,
                                   damage_waiver_elected=False,
                                   class_kwargs=None, serial_number="SN-0001",
                                   ansi_standard_ref="ANSI A92.22",
                                   requested_start_date="2026-08-10",
                                   requested_end_date="2026-08-15",
                                   required_working_height_ft=20,
                                   engineering_plan_ref=None,
                                   jobsite_address="100 Main St",
                                   setup_clock="2026-08-01T09:00:00Z"):
    """Customer + class + unit + DRAFT contract + one RESERVED line.
    Returns dict(customer, equipment_class, unit, contract, line)."""
    if setup_clock is not None:
        set_clock(setup_clock)
    customer = create_customer(credit_limit_cents=credit_limit_cents)
    cls = create_equipment_class(**(class_kwargs or {}))
    unit = create_equipment_unit(cls["id"], serial_number, ansi_standard_ref)
    contract = create_contract(customer["id"], jobsite_address,
                               damage_waiver_elected)
    line = add_line(contract["id"], unit["id"], requested_start_date,
                    requested_end_date, required_working_height_ft,
                    engineering_plan_ref=engineering_plan_ref)
    return {"customer": customer, "equipment_class": cls, "unit": unit,
            "contract": contract, "line": line}


# ─── Tier 3: the rental cycle — delivery, off-rent, re-rent, pickup ─────────

def schedule_trip(contract_id, line_id, trip_type="DELIVERY", driver_id="drv-1",
                  planned_start_utc="2026-08-10T08:00:00Z",
                  planned_end_utc="2026-08-10T10:00:00Z"):
    """Schedule a delivery or pickup trip (SCHEDULED). Returns the trip."""
    return get_success_data(api_client.create_delivery_trip(
        create_delivery_trip_payload(contract_id, line_id, trip_type,
                                     driver_id, planned_start_utc,
                                     planned_end_utc), RC), 201)


def start_trip(trip_id, driver_id):
    """Assigned driver moves the trip SCHEDULED -> EN_ROUTE."""
    return get_success_data(api_client.start_delivery_trip(
        trip_id, make_driver_headers(driver_id)))


def complete_trip(trip_id, driver_id, standby_minutes=0, crew_labor_hours=0):
    """Assigned driver completes an EN_ROUTE trip (COMPLETED + cascades)."""
    return get_success_data(api_client.complete_delivery_trip(
        trip_id, create_trip_completion_payload(standby_minutes,
                                                crew_labor_hours),
        make_driver_headers(driver_id)))


def fail_trip(trip_id, driver_id, failure_reason="jobsite gate locked"):
    """Assigned driver moves the trip EN_ROUTE -> FAILED."""
    return get_success_data(api_client.fail_delivery_trip(
        trip_id, create_trip_failure_payload(failure_reason),
        make_driver_headers(driver_id)))


def deliver_line(contract_id, line_id, driver_id="drv-1",
                 planned_start_utc="2026-08-10T08:00:00Z",
                 planned_end_utc="2026-08-10T10:00:00Z",
                 deliver_at="2026-08-10T09:00:00Z",
                 standby_minutes=0, crew_labor_hours=0):
    """Schedule + start + complete a DELIVERY trip: line RESERVED ->
    OUT_ON_RENT, unit AVAILABLE -> ON_RENT. The logical clock is advanced to
    deliver_at first so on_rent_at is deterministic. Returns the trip."""
    trip = schedule_trip(contract_id, line_id, "DELIVERY", driver_id,
                         planned_start_utc, planned_end_utc)
    set_clock(deliver_at)
    start_trip(trip["id"], driver_id)
    complete_trip(trip["id"], driver_id, standby_minutes, crew_labor_hours)
    return trip


def setup_active_rental(credit_limit_cents=100_000_000,
                        damage_waiver_elected=False,
                        class_kwargs=None, serial_number="SN-0001",
                        ansi_standard_ref="ANSI A92.22",
                        requested_start_date="2026-08-10",
                        requested_end_date="2026-08-15",
                        required_working_height_ft=20,
                        engineering_plan_ref=None,
                        jobsite_address="100 Main St",
                        driver_id="drv-1",
                        planned_start_utc="2026-08-10T08:00:00Z",
                        planned_end_utc="2026-08-10T10:00:00Z",
                        deliver_at="2026-08-10T09:00:00Z",
                        setup_clock="2026-08-01T09:00:00Z"):
    """Full chain: customer, class, unit, contract, RESERVED line, ACTIVE
    contract, DELIVERY trip completed at deliver_at — the line is
    OUT_ON_RENT. Returns dict(customer, equipment_class, unit, contract,
    line, delivery_trip)."""
    ctx = setup_draft_contract_with_line(
        credit_limit_cents=credit_limit_cents,
        damage_waiver_elected=damage_waiver_elected,
        class_kwargs=class_kwargs, serial_number=serial_number,
        ansi_standard_ref=ansi_standard_ref,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        required_working_height_ft=required_working_height_ft,
        engineering_plan_ref=engineering_plan_ref,
        jobsite_address=jobsite_address, setup_clock=setup_clock)
    ctx["contract"] = activate_contract(ctx["contract"]["id"])
    ctx["delivery_trip"] = deliver_line(
        ctx["contract"]["id"], ctx["line"]["id"], driver_id,
        planned_start_utc, planned_end_utc, deliver_at)
    ctx["line"] = get_success_data(api_client.get_rental_line(ctx["line"]["id"], RC))
    return ctx


def off_rent(line_id, customer_id=None):
    """Call a line off rent (finalizes the current billable segment). Pass
    customer_id to act as the owning Customer instead of the coordinator."""
    headers = make_customer_headers(customer_id) if customer_id else RC
    return get_success_data(api_client.off_rent_line(line_id, headers))


def re_rent(line_id, customer_id=None):
    """Re-rent an OFF_RENT line (cancels its SCHEDULED pickup trips)."""
    headers = make_customer_headers(customer_id) if customer_id else RC
    return get_success_data(api_client.re_rent_line(line_id, headers))


def pickup_line(contract_id, line_id, driver_id="drv-1",
                planned_start_utc="2026-08-11T13:00:00Z",
                planned_end_utc="2026-08-11T15:00:00Z"):
    """Schedule + start + complete a PICKUP trip: line OFF_RENT -> RETURNED.
    Caller sets the logical clock first. Returns the trip."""
    trip = schedule_trip(contract_id, line_id, "PICKUP", driver_id,
                         planned_start_utc, planned_end_utc)
    start_trip(trip["id"], driver_id)
    complete_trip(trip["id"], driver_id)
    return trip


def setup_returned_line(off_rent_at="2026-08-11T09:00:00Z", **kwargs):
    """setup_active_rental + off-rent + completed pickup — line RETURNED,
    unit back AVAILABLE (inspection current). Returns the setup dict with
    keys line, pickup_trip refreshed."""
    ctx = setup_active_rental(**kwargs)
    set_clock(off_rent_at)
    ctx["line"] = off_rent(ctx["line"]["id"])
    ctx["pickup_trip"] = pickup_line(ctx["contract"]["id"], ctx["line"]["id"],
                                     kwargs.get("driver_id", "drv-1"))
    ctx["line"] = get_success_data(api_client.get_rental_line(ctx["line"]["id"], RC))
    return ctx


# ─── Tier 4: claims, training, inspections ──────────────────────────────────

def create_training_record(customer_id, class_id, trainee_name="Op One",
                           trained_at="2026-08-01T10:00:00Z",
                           trainer_id="yt-1"):
    """Document familiarization training. Returns the record."""
    return get_success_data(api_client.create_training_record(
        create_training_record_payload(customer_id, class_id, trainee_name,
                                       trained_at),
        make_yard_technician_headers(trainer_id)), 201)


def create_inspection_record(unit_id, inspection_date, result="PASS",
                             ansi_standard_ref="ANSI A92.22",
                             inspector_id="yt-1"):
    """Yard technician submits an annual inspection (SUBMITTED). Returns it."""
    return get_success_data(api_client.create_inspection_record(
        create_inspection_record_payload(unit_id, inspection_date,
                                         ansi_standard_ref, result),
        make_yard_technician_headers(inspector_id)), 201)


def certify_inspection(record_id, manager_id="bm-1"):
    """Branch manager certifies a SUBMITTED record (must differ from the
    inspector). Returns the decided record."""
    return get_success_data(api_client.certify_inspection_record(
        record_id, make_branch_manager_headers(manager_id)))


def reject_inspection(record_id, manager_id="bm-1"):
    """Branch manager rejects a SUBMITTED record. Returns the record."""
    return get_success_data(api_client.reject_inspection_record(
        record_id, make_branch_manager_headers(manager_id)))


def create_claim(line_id, claim_type="DAMAGE", description="jobsite damage",
                 reporter_customer_id=None):
    """Report a claim on an OUT_ON_RENT / OFF_RENT / RETURNED line (OPEN).
    Acts as the owning Customer when reporter_customer_id is given."""
    headers = (make_customer_headers(reporter_customer_id)
               if reporter_customer_id else RC)
    return get_success_data(api_client.create_damage_claim(
        create_damage_claim_payload(line_id, claim_type, description),
        headers), 201)


def assess_claim(claim_id, repair_estimate_cents=None):
    """Branch manager assesses an OPEN claim (ASSESSED)."""
    return get_success_data(api_client.assess_damage_claim(
        claim_id, create_claim_assessment_payload(repair_estimate_cents), BM))


def charge_claim(claim_id):
    """Branch manager charges an ASSESSED claim (CHARGED + cascades)."""
    return get_success_data(api_client.charge_damage_claim(claim_id, BM))


def dispute_claim(claim_id, customer_id):
    """Owning Customer disputes a CHARGED claim (DISPUTED)."""
    return get_success_data(api_client.dispute_damage_claim(
        claim_id, make_customer_headers(customer_id)))


def resolve_claim(claim_id, decision="UPHOLD"):
    """Branch manager resolves a DISPUTED claim (UPHOLD -> CHARGED,
    WAIVE -> WAIVED)."""
    return get_success_data(api_client.resolve_damage_claim(
        claim_id, create_claim_resolution_payload(decision), BM))


def setup_charged_damage_claim(repair_estimate_cents=50_000,
                               reporter_via="coordinator", **rental_kwargs):
    """Active rental + DAMAGE claim walked OPEN -> ASSESSED -> CHARGED.
    Returns the setup dict with claim added."""
    ctx = setup_active_rental(**rental_kwargs)
    reporter = (ctx["customer"]["id"] if reporter_via == "customer" else None)
    ctx["claim"] = create_claim(ctx["line"]["id"], "DAMAGE",
                                "bent guardrail", reporter)
    ctx["claim"] = assess_claim(ctx["claim"]["id"], repair_estimate_cents)
    ctx["claim"] = charge_claim(ctx["claim"]["id"])
    return ctx


# ─── Tier 5: credit standing and close-out composites ───────────────────────

def setup_suspended_customer(credit_limit_cents=100_000,
                             repair_estimate_cents=500_000,
                             class_kwargs=None, **rental_kwargs):
    """Drive a customer ACTIVE -> SUSPENDED through the claim-charge cascade:
    a 1-day rental is delivered and called off rent, then a DAMAGE claim is
    charged so the recomputed outstanding balance exceeds the credit limit.
    Returns the setup dict with claim and customer (refreshed) added."""
    kwargs = dict(
        credit_limit_cents=credit_limit_cents,
        class_kwargs=class_kwargs or {
            "class_code": "LFT", "max_working_height_ft": 30,
            "daily_rate_cents": 10000, "weekly_rate_cents": 70000,
            "monthly_rate_cents": 200000,
            "replacement_value_cents": 2_000_000,
        },
        requested_start_date="2026-08-05", requested_end_date="2026-08-06",
        required_working_height_ft=25,
        planned_start_utc="2026-08-05T08:00:00Z",
        planned_end_utc="2026-08-05T10:00:00Z",
        deliver_at="2026-08-05T09:00:00Z",
    )
    kwargs.update(rental_kwargs)
    ctx = setup_active_rental(**kwargs)
    set_clock("2026-08-06T09:00:00Z")
    ctx["line"] = off_rent(ctx["line"]["id"])
    ctx["claim"] = create_claim(ctx["line"]["id"], "DAMAGE", "crushed platform")
    ctx["claim"] = assess_claim(ctx["claim"]["id"], repair_estimate_cents)
    ctx["claim"] = charge_claim(ctx["claim"]["id"])
    ctx["customer"] = get_success_data(
        api_client.get_customer_account(ctx["customer"]["id"], BM))
    return ctx


def get_invoice(contract_id):
    """Read the computed invoice view of a contract."""
    return get_success_data(api_client.get_contract_invoice(contract_id, RC))


def get_line(line_id):
    return get_success_data(api_client.get_rental_line(line_id, RC))


def get_unit(unit_id):
    return get_success_data(api_client.get_equipment_unit(unit_id, BM))


def get_customer(customer_id):
    return get_success_data(api_client.get_customer_account(customer_id, BM))


def get_trip(trip_id):
    return get_success_data(api_client.get_delivery_trip(trip_id, RC))


def get_claim(claim_id):
    return get_success_data(api_client.get_damage_claim(claim_id, BM))


def count_units(class_id, status):
    """Count units of a class in a given status via the filtered list."""
    data, meta = validate_paginated(api_client.list_equipment_units(
        BM, params={"class_id": class_id, "status": status, "limit": 100}))
    return meta["total_count"]
