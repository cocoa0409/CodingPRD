"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data() so failures surface as clear
"Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_assignment_payload,
    create_engagement_payload,
    create_invoice_payload,
    create_milestone_payload,
    create_rate_card_payload,
    create_supplier_payload,
    create_timesheet_payload,
    create_worker_payload,
)
from .test_users import (
    TEST_USERS,
    make_supplier_coordinator_headers,
    make_worker_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
FIN = TEST_USERS["finance_analyst_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601: str = DEFAULT_CLOCK_ISO) -> dict:
    """Move the logical clock; returns {current_utc}."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_active_rate_card(**card_overrides) -> dict:
    """Create a rate card and activate it. Returns the ACTIVE card."""
    card = get_success_data(
        api_client.create_rate_card(create_rate_card_payload(**card_overrides), ADMIN)
    )
    return get_success_data(api_client.activate_rate_card(card["id"], ADMIN))


def onboard_supplier(tier: str = "PREFERRED", name: str = "Supplier Co",
                     supplier_code: str = "SUP-0001") -> dict:
    """Onboard a supplier. Returns the supplier (status ACTIVE, counters 0)."""
    return get_success_data(
        api_client.create_supplier(
            create_supplier_payload(name=name, supplier_code=supplier_code, tier=tier), ADMIN
        )
    )


def get_supplier(supplier_id: str) -> dict:
    return get_success_data(api_client.get_supplier(supplier_id, ADMIN))


def get_engagement(engagement_id: str) -> dict:
    return get_success_data(api_client.get_engagement(engagement_id, ADMIN))


def get_worker(worker_id: str) -> dict:
    return get_success_data(api_client.get_worker(worker_id, ADMIN))


def get_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, ADMIN))


def get_timesheet(timesheet_id: str) -> dict:
    return get_success_data(api_client.get_timesheet(timesheet_id, ADMIN))


def get_milestone(milestone_id: str) -> dict:
    return get_success_data(api_client.get_milestone(milestone_id, ADMIN))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, FIN))


# ---------------------------------------------------------------------------
# Tier 1: engagement state progression
# ---------------------------------------------------------------------------

def create_engagement_in_open(**engagement_overrides) -> dict:
    """Create an engagement and walk it DRAFT -> IN_REVIEW -> OPEN.

    Defaults to a LOW-risk shape (REQUISITION/HOURLY/DAILY) so classification
    APPROVE succeeds without an override.
    """
    engagement = get_success_data(
        api_client.create_engagement(create_engagement_payload(**engagement_overrides), HM)
    )
    get_success_data(api_client.submit_engagement_review(engagement["id"], HM))
    return get_success_data(
        api_client.classification_decision(engagement["id"], {"decision": "APPROVE"}, ADMIN)
    )


def pick_offer_for_supplier(offers: list, supplier_id: str) -> dict:
    """Select the offer belonging to supplier_id from a distribute response."""
    matches = [o for o in offers if o["supplier_id"] == supplier_id]
    assert len(matches) == 1, (
        f"Expected exactly one offer for supplier {supplier_id}, got {len(matches)}"
    )
    return matches[0]


# ---------------------------------------------------------------------------
# Tier 2/3: full staffing chain (REQUISITION) and SOW chain
# ---------------------------------------------------------------------------

def setup_bookable(
    *,
    clock: str | None = DEFAULT_CLOCK_ISO,
    card_overrides: dict | None = None,
    rate_card: dict | None = None,
    supplier: dict | None = None,
    supplier_tier: str = "PREFERRED",
    supplier_name: str = "Staffing Co",
    supplier_code: str = "SUP-0001",
    engagement_overrides: dict | None = None,
    tenure_carryover_days: int = 0,
    worker_name: str = "Worker One",
    worker_email: str = "worker1@example.com",
    respond_action: str = "ACCEPT",
) -> dict:
    """Staffing chain stopping right before assignment booking:

    clock -> ACTIVE rate card -> supplier -> engagement OPEN -> distribute ->
    supplier response (ACCEPT bubbles engagement to ACTIVE; offer ends
    ACCEPTED, or DECLINED when respond_action is DECLINE) -> worker
    registered under the supplier.

    Pass `rate_card`/`supplier` to reuse existing entities (multi-engagement
    scenarios); pass clock=None to leave the logical clock untouched.

    Returns dict(rate_card, supplier, engagement, offer, worker).
    """
    if clock is not None:
        set_logical_clock(clock)
    if rate_card is None:
        rate_card = create_active_rate_card(**(card_overrides or {}))
    if supplier is None:
        supplier = onboard_supplier(tier=supplier_tier, name=supplier_name,
                                    supplier_code=supplier_code)
    engagement = create_engagement_in_open(**(engagement_overrides or {}))
    offers = get_success_data(api_client.distribute_engagement(engagement["id"], ADMIN))
    offer = pick_offer_for_supplier(offers, supplier["id"])
    offer = get_success_data(
        api_client.respond_to_offer(
            offer["id"], {"action": respond_action},
            make_supplier_coordinator_headers(supplier["id"]),
        )
    )
    worker = get_success_data(
        api_client.create_worker(
            create_worker_payload(
                supplier["id"],
                full_name=worker_name,
                email=worker_email,
                tenure_carryover_days=tenure_carryover_days,
            ),
            make_supplier_coordinator_headers(supplier["id"]),
        )
    )
    return {
        "rate_card": rate_card,
        "supplier": supplier,
        "engagement": get_engagement(engagement["id"]),
        "offer": offer,
        "worker": worker,
    }


def setup_staffed_assignment(
    *,
    clock: str | None = DEFAULT_CLOCK_ISO,
    card_overrides: dict | None = None,
    rate_card: dict | None = None,
    supplier: dict | None = None,
    supplier_tier: str = "PREFERRED",
    supplier_name: str = "Staffing Co",
    supplier_code: str = "SUP-0001",
    engagement_overrides: dict | None = None,
    bill_rate_cents: int = 9500,
    pay_rate_cents: int = 8000,
    start_date: str = "2026-05-01",
    end_date: str = "2026-08-31",
    tenure_carryover_days: int = 0,
    worker_name: str = "Worker One",
    worker_email: str = "worker1@example.com",
    activate: bool = True,
) -> dict:
    """Full staffing chain against an otherwise empty database:

    everything setup_bookable does, then assignment booked (offer becomes
    CONSUMED, assignment PENDING) -> optional activate (assignment ACTIVE,
    worker bubbled to ACTIVE).

    Returns dict(rate_card, supplier, engagement, offer, worker, assignment).
    """
    base = setup_bookable(
        clock=clock,
        card_overrides=card_overrides,
        rate_card=rate_card,
        supplier=supplier,
        supplier_tier=supplier_tier,
        supplier_name=supplier_name,
        supplier_code=supplier_code,
        engagement_overrides=engagement_overrides,
        tenure_carryover_days=tenure_carryover_days,
        worker_name=worker_name,
        worker_email=worker_email,
    )
    assignment = get_success_data(
        api_client.create_assignment(
            create_assignment_payload(
                base["worker"]["id"], base["engagement"]["id"], base["offer"]["id"],
                base["rate_card"]["id"],
                bill_rate_cents=bill_rate_cents, pay_rate_cents=pay_rate_cents,
                start_date=start_date, end_date=end_date,
            ),
            ADMIN,
        )
    )
    if activate:
        assignment = get_success_data(api_client.activate_assignment(assignment["id"], ADMIN))
    base["assignment"] = assignment
    return base


def setup_sow_engagement(
    *,
    clock: str = DEFAULT_CLOCK_ISO,
    supplier_tier: str = "APPROVED",
    supplier_name: str = "SOW Supplier Co",
    supplier_code: str = "SUP-SOW1",
    budget_cents: int = 5_000_000,
    milestone: dict | None = None,
) -> dict:
    """SOW chain: supplier -> SOW engagement (FIXED/MILESTONE, LOW risk) ->
    OPEN -> distribute -> awarded supplier ACCEPT (engagement ACTIVE) ->
    optional milestone creation.

    Returns dict(supplier, engagement, offer, milestone|None).
    """
    set_logical_clock(clock)
    supplier = onboard_supplier(tier=supplier_tier, name=supplier_name,
                                supplier_code=supplier_code)
    engagement = create_engagement_in_open(
        title="SOW engagement", engagement_type="SOW", payment_basis="FIXED",
        supervision_level="MILESTONE", duration_months=9, budget_cents=budget_cents,
    )
    offers = get_success_data(api_client.distribute_engagement(engagement["id"], ADMIN))
    offer = pick_offer_for_supplier(offers, supplier["id"])
    offer = get_success_data(
        api_client.respond_to_offer(
            offer["id"], {"action": "ACCEPT"}, make_supplier_coordinator_headers(supplier["id"])
        )
    )
    engagement = get_engagement(engagement["id"])
    created_milestone = None
    if milestone is not None:
        created_milestone = get_success_data(
            api_client.create_milestone(engagement["id"], create_milestone_payload(**milestone), HM)
        )
    return {
        "supplier": supplier,
        "engagement": engagement,
        "offer": offer,
        "milestone": created_milestone,
    }


# ---------------------------------------------------------------------------
# Tier 3: timesheet lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_draft_timesheet(assignment_id: str, worker_id: str, *,
                           period_start: str = "2026-05-04",
                           period_end: str = "2026-05-10",
                           submitted_hours: float = 8.0) -> dict:
    """Worker creates a DRAFT timesheet on their own assignment."""
    return get_success_data(
        api_client.create_timesheet(
            create_timesheet_payload(
                assignment_id,
                period_start=period_start,
                period_end=period_end,
                submitted_hours=submitted_hours,
            ),
            make_worker_headers(worker_id),
        )
    )


def create_submitted_timesheet(assignment_id: str, worker_id: str, **kwargs) -> dict:
    """DRAFT -> SUBMITTED by the owning worker. Returns SUBMITTED timesheet."""
    timesheet = create_draft_timesheet(assignment_id, worker_id, **kwargs)
    return get_success_data(
        api_client.submit_timesheet(timesheet["id"], make_worker_headers(worker_id))
    )


def create_approved_timesheet(assignment_id: str, worker_id: str,
                              approved_hours: float | None = None, **kwargs) -> dict:
    """DRAFT -> SUBMITTED -> APPROVED. Returns APPROVED timesheet."""
    timesheet = create_submitted_timesheet(assignment_id, worker_id, **kwargs)
    payload = {} if approved_hours is None else {"approved_hours": approved_hours}
    return get_success_data(api_client.approve_timesheet(timesheet["id"], payload, HM))


# ---------------------------------------------------------------------------
# Tier 3: invoice helpers
# ---------------------------------------------------------------------------

def find_open_invoice_id(supplier_id: str) -> str:
    """Return the id of the supplier's single OPEN invoice."""
    data, meta = validate_paginated(
        api_client.list_invoices(FIN, params={"supplier_id": supplier_id, "status": "OPEN"})
    )
    assert meta["total_count"] == 1, (
        f"Expected exactly one OPEN invoice for supplier {supplier_id}, got {meta['total_count']}"
    )
    return data[0]["id"]


def create_manual_invoice(supplier_id: str, **overrides) -> dict:
    """FinanceAnalyst manually creates an empty OPEN invoice."""
    return get_success_data(
        api_client.create_invoice(create_invoice_payload(supplier_id, **overrides), FIN)
    )
