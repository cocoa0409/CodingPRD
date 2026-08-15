"""Composite setup helpers for the rental house API tests.

Every helper builds preconditions from scratch via the public endpoints (each test
runs against a freshly restarted server with an empty database). Helpers use the
lenient get_success_data() validator so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.
"""
from uuid import uuid4

from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_certificate_payload,
    create_check_in_payload,
    create_claim_payload,
    create_item_payload,
    create_production_payload,
    create_rate_card_payload,
    create_renter_payload,
    create_reservation_payload,
    create_unit_payload,
)
from .test_users import (
    TEST_USERS,
    make_accountant_headers,
    make_house_admin_headers,
    make_renter_contact_headers,
    make_wardrobe_staff_headers,
)

ADMIN = TEST_USERS["house_admin_headers"]
STAFF = TEST_USERS["wardrobe_staff_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]

DISPATCH_CLOCK = "2026-08-31T00:00:00Z"
ON_DUE_DATE_CLOCK = "2026-09-10T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: logical clock and daily operations sweep
# ---------------------------------------------------------------------------

def set_logical_clock(api, to_iso8601: str) -> dict:
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def run_daily_ops(api) -> dict:
    return get_success_data(api.run_daily_ops(ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators
# ---------------------------------------------------------------------------

def publish_rate_card(api, **overrides) -> dict:
    """Create a rate card (the previously PUBLISHED card becomes SUPERSEDED)."""
    return get_success_data(api.create_rate_card(create_rate_card_payload(**overrides), ADMIN))


def create_catalog_item(api, **overrides) -> dict:
    """Create a catalog item (starts ACTIVE with serviceable_unit_count 0)."""
    return get_success_data(api.create_item(create_item_payload(**overrides), ADMIN))


def acquire_unit(api, item_id, barcode=None, condition_grade="B",
                 acquisition_date="2025-01-15", acquisition_cost_cents=40000) -> dict:
    """Acquire one physical unit of an item (starts AVAILABLE)."""
    payload = create_unit_payload(
        barcode=barcode or f"BC-{uuid4().hex[:10]}",
        condition_grade=condition_grade,
        acquisition_date=acquisition_date,
        acquisition_cost_cents=acquisition_cost_cents,
    )
    return get_success_data(api.create_unit(item_id, payload, ADMIN))


def register_renter(api, name=None, renter_type="THEATRE", credit_limit_cents=10000000) -> dict:
    """Register a renter (starts PENDING_VERIFICATION)."""
    payload = create_renter_payload(
        name=name or f"Renter-{uuid4().hex[:6]}",
        renter_type=renter_type,
        credit_limit_cents=credit_limit_cents,
    )
    return get_success_data(api.create_renter(payload, ADMIN))


def submit_certificate(api, renter_id, coverage_cents=600000,
                       effective_date="2026-01-01", expiry_date="2027-06-30",
                       policy_number=None) -> dict:
    """Submit an insurance certificate for a renter (starts SUBMITTED)."""
    payload = create_certificate_payload(
        coverage_cents=coverage_cents,
        effective_date=effective_date,
        expiry_date=expiry_date,
        policy_number=policy_number or f"POL-{uuid4().hex[:8]}",
    )
    return get_success_data(api.submit_certificate(renter_id, payload, ADMIN))


def decide_certificate(api, cert_id, decision="VERIFIED", admin_id="admin-1") -> dict:
    return get_success_data(
        api.decide_certificate(cert_id, decision, make_house_admin_headers(admin_id))
    )


def create_active_renter(api, renter_type="THEATRE", credit_limit_cents=10000000,
                         coverage_cents=600000, effective_date="2026-01-01",
                         expiry_date="2027-06-30", name=None, admin_id="admin-1") -> dict:
    """Renter + certificate decided VERIFIED -> renter ACTIVE.

    Returns {"renter": <refreshed renter>, "certificate": <cert>}.
    """
    renter = register_renter(api, name=name, renter_type=renter_type,
                             credit_limit_cents=credit_limit_cents)
    cert = submit_certificate(api, renter["id"], coverage_cents=coverage_cents,
                              effective_date=effective_date, expiry_date=expiry_date)
    decide_certificate(api, cert["id"], decision="VERIFIED", admin_id=admin_id)
    renter = get_renter(api, renter["id"])
    return {"renter": renter, "certificate": cert}


def get_renter(api, renter_id) -> dict:
    return get_success_data(api.get_renter(renter_id, ADMIN))


def get_item(api, item_id) -> dict:
    return get_success_data(api.get_item(item_id, ADMIN))


def get_unit(api, unit_id) -> dict:
    return get_success_data(api.get_unit(unit_id, ADMIN))


def get_production(api, production_id) -> dict:
    return get_success_data(api.get_production(production_id, ADMIN))


def get_reservation(api, reservation_id) -> dict:
    return get_success_data(api.get_reservation(reservation_id, ADMIN))


def get_pull_list(api, pull_list_id) -> dict:
    return get_success_data(api.get_pull_list(pull_list_id, ADMIN))


def get_line(api, line_id) -> dict:
    return get_success_data(api.get_line(line_id, ADMIN))


def get_invoice(api, invoice_id) -> dict:
    return get_success_data(api.get_invoice(invoice_id, ACCOUNTANT))


# ---------------------------------------------------------------------------
# Tier 2: productions and reservations (OCC-aware)
# ---------------------------------------------------------------------------

def create_production_draft(api, renter, title=None,
                            rehearsal_start_date="2026-08-10",
                            performance_start_date="2026-09-01",
                            closing_date="2026-10-26") -> dict:
    """Create a DRAFT production for the given renter (entity-backed identity)."""
    payload = create_production_payload(
        renter_id=renter["id"],
        title=title or f"Prod-{uuid4().hex[:6]}",
        rehearsal_start_date=rehearsal_start_date,
        performance_start_date=performance_start_date,
        closing_date=closing_date,
    )
    return get_success_data(
        api.create_production(payload, make_renter_contact_headers(renter["id"]))
    )


def confirm_production(api, production, renter) -> dict:
    return get_success_data(
        api.confirm_production(production["id"], make_renter_contact_headers(renter["id"]))
    )


def create_confirmed_production(api, renter, **kwargs) -> dict:
    """Create a production and confirm it (pins the PUBLISHED rate card)."""
    draft = create_production_draft(api, renter, **kwargs)
    return confirm_production(api, draft, renter)


def place_reservation(api, production_id, renter, item_id, quantity=1,
                      window_start_date="2026-09-01", window_end_date="2026-09-10") -> dict:
    """Place a HELD reservation. Re-reads the production first so the OCC guard
    expected_production_version always carries the current version."""
    version = get_production(api, production_id)["version"]
    payload = create_reservation_payload(
        production_id=production_id,
        item_id=item_id,
        quantity=quantity,
        window_start_date=window_start_date,
        window_end_date=window_end_date,
        expected_production_version=version,
    )
    return get_success_data(
        api.create_reservation(payload, make_renter_contact_headers(renter["id"]))
    )


def confirm_reservation(api, reservation, renter) -> dict:
    return get_success_data(
        api.confirm_reservation(reservation["id"], make_renter_contact_headers(renter["id"]))
    )


def create_confirmed_reservation(api, production_id, renter, item_id, **kwargs) -> dict:
    reservation = place_reservation(api, production_id, renter, item_id, **kwargs)
    return confirm_reservation(api, reservation, renter)


# ---------------------------------------------------------------------------
# Tier 3: pull lists, lines, dispatch
# ---------------------------------------------------------------------------

def create_pull_list_for(api, production_id, renter) -> dict:
    """Create a DRAFT pull list (OCC-guarded; re-reads the production version)."""
    version = get_production(api, production_id)["version"]
    return get_success_data(
        api.create_pull_list(
            {"production_id": production_id, "expected_production_version": version},
            make_renter_contact_headers(renter["id"]),
        )
    )


def list_lines(api, **params) -> list:
    return get_success_data(api.list_lines(STAFF, params=params or None))


def submit_pull_list(api, pull_list_id) -> dict:
    return get_success_data(api.submit_pull_list(pull_list_id, STAFF))


def submit_and_get_lines(api, pull_list_id):
    """Submit a DRAFT pull list; returns (PICKING pull list, created lines)."""
    pull_list = submit_pull_list(api, pull_list_id)
    lines = list_lines(api, pull_list_id=pull_list_id, limit=100)
    return pull_list, lines


def pick_all_lines(api, lines) -> None:
    for line in lines:
        get_success_data(api.pick_line(line["id"], STAFF))


def dispatch_pull_list(api, pull_list_id, at=DISPATCH_CLOCK) -> dict:
    """Set the logical clock and dispatch a fully-picked pull list."""
    set_logical_clock(api, at)
    return get_success_data(api.dispatch_pull_list(pull_list_id, STAFF))


def check_in_line(api, line_id, condition_grade_after="B", damage_severity="NONE",
                  restoration_complete=True, staff_id="ws-1") -> dict:
    payload = create_check_in_payload(
        condition_grade_after=condition_grade_after,
        damage_severity=damage_severity,
        restoration_complete=restoration_complete,
    )
    return get_success_data(
        api.check_in_line(line_id, payload, make_wardrobe_staff_headers(staff_id))
    )


def get_assessment_for_line(api, line_id) -> dict:
    """Return the single return assessment for a checked-in line (array of 1)."""
    data = get_success_data(api.get_line_assessment(line_id, STAFF))
    assert isinstance(data, list) and len(data) == 1, (
        f"Expected exactly one assessment for line {line_id}, got {data!r}"
    )
    return data[0]


def cleaning_ticket_for_unit(api, unit_id) -> dict:
    data = get_success_data(api.list_unit_tickets(unit_id, STAFF))
    assert isinstance(data, list) and len(data) >= 1, (
        f"Expected at least one cleaning ticket for unit {unit_id}, got {data!r}"
    )
    return data[0]


def advance_ticket(api, ticket_id) -> dict:
    return get_success_data(api.advance_ticket(ticket_id, STAFF))


def run_ticket_to_ready(api, ticket_id, requires_repair=False) -> dict:
    """Advance a ticket through its stages to READY (optionally via the REPAIR loop)."""
    ticket = advance_ticket(api, ticket_id)   # QUEUED -> IN_CLEANING
    ticket = advance_ticket(api, ticket["id"])  # IN_CLEANING -> INSPECTION
    if requires_repair:
        ticket = advance_ticket(api, ticket["id"])  # INSPECTION -> REPAIR
        ticket = advance_ticket(api, ticket["id"])  # REPAIR -> INSPECTION
    ticket = advance_ticket(api, ticket["id"])  # INSPECTION -> READY
    return ticket


# ---------------------------------------------------------------------------
# Tier 4: claims and invoices
# ---------------------------------------------------------------------------

def create_damage_claim(api, line_id, assessment_id, staff_id="ws-1") -> dict:
    payload = create_claim_payload(
        pull_list_line_id=line_id,
        claim_type="DAMAGE",
        return_assessment_id=assessment_id,
    )
    return get_success_data(api.create_claim(payload, make_wardrobe_staff_headers(staff_id)))


def create_loss_claim(api, line_id, staff_id="ws-1") -> dict:
    payload = create_claim_payload(pull_list_line_id=line_id, claim_type="LOSS")
    return get_success_data(api.create_claim(payload, make_wardrobe_staff_headers(staff_id)))


def post_claim(api, claim_id, accountant_id="acct-1") -> dict:
    return get_success_data(api.post_claim(claim_id, make_accountant_headers(accountant_id)))


def get_claim(api, claim_id) -> dict:
    return get_success_data(api.get_claim(claim_id, ACCOUNTANT))


def generate_invoice(api, production_id) -> dict:
    return get_success_data(api.generate_invoice(production_id, ACCOUNTANT))


def issue_invoice(api, invoice_id) -> dict:
    return get_success_data(api.issue_invoice(invoice_id, ACCOUNTANT))


def record_payment(api, invoice_id, amount_cents) -> dict:
    return get_success_data(api.record_payment(invoice_id, amount_cents, ACCOUNTANT))


def apply_credit_note(api, invoice_id, amount_cents, reason=None) -> dict:
    return get_success_data(api.credit_note(invoice_id, amount_cents, ACCOUNTANT, reason=reason))


# ---------------------------------------------------------------------------
# Tier 5: composite lifecycle scenarios
# ---------------------------------------------------------------------------

def setup_confirmed_reservation_scenario(
    api,
    *,
    quantity=1,
    window_start_date="2026-09-01",
    window_end_date="2026-09-10",
    closing_date="2026-10-26",
    num_units=2,
    condition_grade="B",
    item_overrides=None,
    unit_overrides=None,
    rate_card_overrides=None,
    renter_type="THEATRE",
    credit_limit_cents=10000000,
    coverage_cents=600000,
    cert_expiry_date="2027-06-30",
    confirm_reservation_flag=True,
) -> dict:
    """Rate card + item + units + ACTIVE renter + CONFIRMED production + reservation.

    Default scenario: long-run production (closing 2026-10-26), reservation window
    Sep 1-10 qty 1 -> LONG_RUN quote 8000 under the standard rate card.
    """
    rate_card = publish_rate_card(api, **(rate_card_overrides or {}))
    item = create_catalog_item(api, **(item_overrides or {}))
    units = []
    for _ in range(num_units):
        unit_kw = dict(unit_overrides or {})
        units.append(acquire_unit(
            api, item["id"], condition_grade=unit_kw.pop("condition_grade", condition_grade),
            **unit_kw,
        ))
    renter_ctx = create_active_renter(
        api, renter_type=renter_type, credit_limit_cents=credit_limit_cents,
        coverage_cents=coverage_cents, expiry_date=cert_expiry_date,
    )
    renter = renter_ctx["renter"]
    production = create_confirmed_production(api, renter, closing_date=closing_date)
    reservation = place_reservation(
        api, production["id"], renter, item["id"], quantity=quantity,
        window_start_date=window_start_date, window_end_date=window_end_date,
    )
    if confirm_reservation_flag:
        reservation = confirm_reservation(api, reservation, renter)
    return {
        "rate_card": rate_card,
        "item": item,
        "units": units,
        "renter": renter,
        "certificate": renter_ctx["certificate"],
        "production": production,
        "reservation": reservation,
    }


def setup_dispatched_scenario(api, *, quantity=1, dispatch_at=DISPATCH_CLOCK, **kwargs) -> dict:
    """Full chain through dispatch: reservation CONFIRMED -> pull list submitted,
    every line PICKED, list DISPATCHED (lines OUT, units OUT, reservation FULFILLED)."""
    ctx = setup_confirmed_reservation_scenario(api, quantity=quantity, **kwargs)
    pull_list = create_pull_list_for(api, ctx["production"]["id"], ctx["renter"])
    pull_list, lines = submit_and_get_lines(api, pull_list["id"])
    pick_all_lines(api, lines)
    pull_list = dispatch_pull_list(api, pull_list["id"], at=dispatch_at)
    lines = [get_line(api, line["id"]) for line in lines]
    ctx["pull_list"] = pull_list
    ctx["lines"] = lines
    return ctx


def setup_checked_in_scenario(api, *, condition_grade_after="B", damage_severity="NONE",
                              restoration_complete=True, checkin_at=ON_DUE_DATE_CLOCK,
                              staff_id="ws-1", **kwargs) -> dict:
    """Dispatched single-line scenario, then the line is checked in.

    Returns the dispatched context plus "line" (post-check-in) and "assessment".
    """
    ctx = setup_dispatched_scenario(api, quantity=1, **kwargs)
    set_logical_clock(api, checkin_at)
    line = check_in_line(
        api, ctx["lines"][0]["id"],
        condition_grade_after=condition_grade_after,
        damage_severity=damage_severity,
        restoration_complete=restoration_complete,
        staff_id=staff_id,
    )
    ctx["line"] = line
    ctx["assessment"] = get_assessment_for_line(api, line["id"])
    return ctx


def setup_damaged_line_with_claim(api, *, damage_severity="MINOR",
                                  condition_grade_after="C", staff_id="ws-1",
                                  **kwargs) -> dict:
    """Checked-in DAMAGED line plus a DRAFT damage claim created by staff_id."""
    ctx = setup_checked_in_scenario(
        api, damage_severity=damage_severity,
        condition_grade_after=condition_grade_after, staff_id=staff_id, **kwargs,
    )
    ctx["claim"] = create_damage_claim(
        api, ctx["line"]["id"], ctx["assessment"]["id"], staff_id=staff_id,
    )
    return ctx


def setup_issued_invoice_scenario(api, *, pay_fully=False, **kwargs) -> dict:
    """Dispatched single-line scenario with its rental invoice generated and ISSUED.

    Default: long-run quote 8000 -> invoice total 8000, renter outstanding 8000.
    """
    ctx = setup_dispatched_scenario(api, quantity=1, **kwargs)
    invoice = generate_invoice(api, ctx["production"]["id"])
    invoice = issue_invoice(api, invoice["id"])
    if pay_fully:
        invoice = record_payment(api, invoice["id"], invoice["balance_cents"])
    ctx["invoice"] = invoice
    return ctx
