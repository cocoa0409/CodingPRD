"""Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

Every helper builds preconditions from scratch via PRD-declared endpoints —
each test runs against a freshly restarted server with an empty database and
the logical clock at its startup default (2026-08-01T00:00:00Z, PRD §2.4).

Setup calls use get_success_data() (lenient) so a setup failure surfaces as a
clear "Setup failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_user_payload, create_instrument_payload, create_training_record_payload,
    create_grant_payload, create_rate_set_payload, create_rate_line_payload,
    create_booking_payload, create_usage_log_payload, create_recharge_batch_payload,
    create_subsidy_application_payload, create_award_approval_payload,
    create_maintenance_contract_payload, create_downtime_event_payload,
    create_publication_payload, create_fiscal_year_payload,
)
from .test_users import (
    TEST_USERS, make_researcher_headers, make_external_client_headers,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
STAFF2 = TEST_USERS["staff2_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _ok(response, what):
    data = get_success_data(response)
    assert isinstance(data, (dict, list)), (
        f"Setup failed ({what}): {response.text}"
    )
    return data


# ─── Tier 0: clock ──────────────────────────────────────────────────────────

def set_clock(to_iso8601):
    """Advance the logical clock (PRD §2.4 test-driving capability)."""
    _ok(api_client.set_logical_clock(to_iso8601, ADMIN), f"set clock {to_iso8601}")


# ─── Tier 1: single-entity creators ─────────────────────────────────────────

def create_user(affiliation="INTERNAL", is_pi=None, **overrides):
    """Register a user; defaults to INTERNAL (PRD §3.1). Returns the User."""
    payload = create_user_payload(affiliation=affiliation, **overrides)
    if is_pi is not None:
        payload["is_pi"] = is_pi
    return _ok(api_client.create_user(payload, ADMIN), "create user")


def create_instrument(**overrides):
    """Register an instrument with the canonical policy bundle (PRD §3.2)."""
    return _ok(
        api_client.create_instrument(create_instrument_payload(**overrides), ADMIN),
        "create instrument",
    )


def enroll_and_certify(user_id, instrument_id):
    """ENROLLED then CERTIFIED training record (PRD §3.3). Returns the record."""
    record = _ok(
        api_client.create_training_record(
            create_training_record_payload(user_id, instrument_id), STAFF
        ),
        "create training record",
    )
    return _ok(
        api_client.certify_training_record(record["id"], STAFF),
        "certify training record",
    )


def open_fiscal_year(fiscal_year=2026, **overrides):
    """Open a fiscal year period (PRD §3.13). Returns the FiscalYearPeriod."""
    return _ok(
        api_client.create_fiscal_year(
            create_fiscal_year_payload(fiscal_year=fiscal_year, **overrides), FINANCE
        ),
        "create fiscal year",
    )


def create_grant(pi_user_id, **overrides):
    """Create a grant (PRD §3.4). Returns the Grant."""
    return _ok(
        api_client.create_grant(create_grant_payload(pi_user_id, **overrides), FINANCE),
        "create grant",
    )


def create_draft_rate_set(instrument_id, fiscal_year=2026,
                          effective_from="2026-08-01T00:00:00Z",
                          line_overrides=None, lines=None):
    """Author a DRAFT rate set with one canonical line (PRD §3.5)."""
    if lines is None:
        lines = [create_rate_line_payload(instrument_id, **(line_overrides or {}))]
    payload = create_rate_set_payload(
        instrument_id, fiscal_year=fiscal_year,
        effective_from=effective_from, lines=lines,
    )
    return _ok(api_client.create_rate_set(payload, ADMIN), "create rate set")


def create_effective_rate_set(instrument_id, fiscal_year=2026,
                              effective_from="2026-08-01T00:00:00Z",
                              line_overrides=None):
    """Walk a rate set DRAFT -> UNDER_REVIEW -> APPROVED -> EFFECTIVE (PRD §3.5).

    developed_by is admin-1; approve/activate run as fin-1 (segregation of
    duties, PRD §3.5). Returns the EFFECTIVE RateSet.
    """
    rate_set = create_draft_rate_set(
        instrument_id, fiscal_year=fiscal_year,
        effective_from=effective_from, line_overrides=line_overrides,
    )
    _ok(api_client.submit_rate_set(rate_set["id"], ADMIN), "submit rate set")
    _ok(api_client.approve_rate_set(rate_set["id"], FINANCE), "approve rate set")
    return _ok(
        api_client.activate_rate_set(rate_set["id"], FINANCE), "activate rate set"
    )


def create_maintenance_contract(instrument_id, **overrides):
    """Register a maintenance contract (PRD §3.11)."""
    return _ok(
        api_client.create_maintenance_contract(
            create_maintenance_contract_payload(instrument_id, **overrides), ADMIN
        ),
        "create maintenance contract",
    )


def open_batch(period_year=2026, period_month=9):
    """Open a recharge batch (PRD §3.9). Returns the OPEN RechargeBatch."""
    return _ok(
        api_client.create_recharge_batch(
            create_recharge_batch_payload(
                period_year=period_year, period_month=period_month
            ),
            FINANCE,
        ),
        "create recharge batch",
    )


def finalize_batch(batch_id):
    """Finalize an OPEN batch (PRD §3.9). Returns the FINALIZED batch."""
    return _ok(api_client.finalize_recharge_batch(batch_id, FINANCE), "finalize batch")


# ─── Tier 2: the canonical stack ────────────────────────────────────────────

def setup_canonical_stack(grant_budget=100000, grant_end="2026-12-31",
                          with_grant=True, with_contract=False,
                          contract_overrides=None,
                          fiscal_year=2026,
                          effective_from="2026-08-01T00:00:00Z",
                          line_overrides=None,
                          instrument_overrides=None):
    """The shared preamble: INTERNAL PI user u1, canonical instrument i1,
    CERTIFIED training t1, FY period, EFFECTIVE rate set, and (optionally)
    grant g1 and a maintenance contract. Returns a dict of all entities.
    """
    u1 = create_user(affiliation="INTERNAL", is_pi=True)
    i1 = create_instrument(**(instrument_overrides or {}))
    t1 = enroll_and_certify(u1["id"], i1["id"])
    fy = open_fiscal_year(fiscal_year)
    mc1 = None
    if with_contract:
        mc1 = create_maintenance_contract(i1["id"], **(contract_overrides or {}))
    rs = create_effective_rate_set(
        i1["id"], fiscal_year=fiscal_year,
        effective_from=effective_from, line_overrides=line_overrides,
    )
    g1 = None
    if with_grant:
        g1 = create_grant(u1["id"], budget_total_cents=grant_budget, end_date=grant_end)
    return {"u1": u1, "i1": i1, "t1": t1, "fy": fy, "rs": rs, "g1": g1, "mc1": mc1}


def setup_external_user_with_training(instrument_id, email="eve@acme.com"):
    """An EXTERNAL user with a CERTIFIED record on the instrument (PRD §3.3)."""
    u2 = create_user(affiliation="EXTERNAL", full_name="Eve Ext", email=email)
    enroll_and_certify(u2["id"], instrument_id)
    return u2


# ─── Tier 3: booking lifecycle shortcuts ────────────────────────────────────

def create_booking_request(stack, start_at="2026-09-01T09:00:00Z",
                           end_at="2026-09-01T10:30:00Z", priority="STANDARD",
                           user=None, grant=None):
    """Create a REQUESTED booking as its owner (PRD §3.6).

    user defaults to stack['u1'] (INTERNAL, grant from stack['g1']);
    pass user=<external user> and grant=None for an external booking.
    """
    user = user or stack["u1"]
    if grant is None and user.get("affiliation") == "INTERNAL":
        grant = stack["g1"]
    payload = create_booking_payload(
        user["id"], stack["i1"]["id"], start_at=start_at, end_at=end_at,
        priority=priority,
    )
    if grant is not None:
        payload["grant_id"] = grant["id"] if isinstance(grant, dict) else grant
    headers = (make_researcher_headers(user["id"])
               if user.get("affiliation") == "INTERNAL"
               else make_external_client_headers(user["id"]))
    return _ok(api_client.create_booking(payload, headers), "create booking")


def approve_booking(booking_id):
    """Approve a REQUESTED booking as CoreStaff (PRD §3.6). Returns Booking."""
    return _ok(api_client.approve_booking(booking_id, STAFF), "approve booking")


def create_approved_booking(stack, start_at="2026-09-01T09:00:00Z",
                            end_at="2026-09-01T10:30:00Z", priority="STANDARD",
                            user=None, grant=None):
    """Create + approve. Returns the APPROVED booking."""
    booking = create_booking_request(
        stack, start_at=start_at, end_at=end_at, priority=priority,
        user=user, grant=grant,
    )
    return approve_booking(booking["id"])


def run_session_to_completed(booking, actual_start_at, actual_end_at,
                             checkin_at=None):
    """Drive APPROVED -> IN_PROGRESS -> COMPLETED (PRD §3.7).

    check-in defaults to five minutes before the booking's start_at (inside
    the fifteen-minute early-check-in window); completion runs with the clock
    at actual_end_at. Returns the COMPLETED booking.
    """
    start_at = booking["start_at"]
    checkin_at = checkin_at or _shift_iso_minutes(start_at, -5)
    set_clock(checkin_at)
    _ok(api_client.check_in_booking(booking["id"], STAFF), "check in booking")
    set_clock(actual_end_at)
    return _ok(api_client.complete_booking(booking["id"], STAFF), "complete booking")


def create_and_validate_usage_log(booking, actual_start_at, actual_end_at,
                                  consumable_fee_cents=None, open_batch_first=False):
    """Create -> submit -> validate a usage log (PRD §3.8).

    logged_by is staff-1; validation runs as staff-2 (segregation of duties,
    PRD §3.8). Returns the VALIDATED UsageLog.
    """
    overrides = {}
    if consumable_fee_cents is not None:
        overrides["consumable_fee_cents"] = consumable_fee_cents
    log = _ok(
        api_client.create_usage_log(
            create_usage_log_payload(
                booking["id"], actual_start_at, actual_end_at, **overrides
            ),
            STAFF,
        ),
        "create usage log",
    )
    _ok(api_client.submit_usage_log(log["id"], STAFF), "submit usage log")
    return _ok(api_client.validate_usage_log(log["id"], STAFF2), "validate usage log")


def _shift_iso_minutes(iso_ts, delta_minutes):
    from datetime import datetime, timedelta
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    dt = dt + timedelta(minutes=delta_minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Tier 4: ledger / entry locators (client-side filtering) ────────────────

def list_all_entries():
    """All recharge entries as FinanceOfficer (list endpoint, PRD §4)."""
    data = _ok(api_client.list_recharge_entries(FINANCE), "list entries")
    assert isinstance(data, list), f"Setup failed (list entries): {data!r}"
    return data


def find_entries(**match):
    """Client-side filter over all entries (exact equality on given fields)."""
    return [e for e in list_all_entries()
            if all(e.get(k) == v for k, v in match.items())]


def find_entry_for_usage_log(usage_log_id):
    """The single USAGE entry created by validating this log (PRD §3.8)."""
    entries = find_entries(usage_log_id=usage_log_id)
    assert len(entries) == 1, f"expected one entry for log {usage_log_id}: {entries!r}"
    return entries[0]


def list_all_bookings():
    """All bookings as CoreStaff (opaque role — no force-filter, PRD §2.1)."""
    data = _ok(api_client.list_bookings(STAFF), "list bookings")
    assert isinstance(data, list), f"Setup failed (list bookings): {data!r}"
    return data


def list_all_fiscal_years():
    data = _ok(api_client.list_fiscal_years(FINANCE), "list fiscal years")
    assert isinstance(data, list), f"Setup failed (list fiscal years): {data!r}"
    return data


def find_fiscal_year(fiscal_year):
    periods = [p for p in list_all_fiscal_years() if p.get("fiscal_year") == fiscal_year]
    assert len(periods) == 1, f"expected one period for FY{fiscal_year}: {periods!r}"
    return periods[0]


def get_grant(grant_id):
    return _ok(api_client.get_grant(grant_id, FINANCE), "get grant")


def get_booking(booking_id):
    return _ok(api_client.get_booking(booking_id, STAFF), "get booking")


def get_instrument(instrument_id):
    return _ok(api_client.get_instrument(instrument_id, ADMIN), "get instrument")


def get_award(award_id):
    return _ok(api_client.get_subsidy_award(award_id, FINANCE), "get award")


def get_batch(batch_id):
    return _ok(api_client.get_recharge_batch(batch_id, FINANCE), "get batch")


# ─── Tier 5: full recharge-chain composites ─────────────────────────────────

def setup_completed_booking_with_entry(grant_budget=100000, with_contract=False,
                                       contract_overrides=None,
                                       actual_start_at="2026-09-01T09:00:00Z",
                                       actual_end_at="2026-09-01T10:14:00Z",
                                       booking_start_at="2026-09-01T09:00:00Z",
                                       booking_end_at="2026-09-01T10:30:00Z",
                                       consumable_fee_cents=None,
                                       batch_year=2026, batch_month=9):
    """Canonical stack + APPROVED booking + COMPLETED session + OPEN batch +
    VALIDATED usage log. Returns dict(stack, booking, log, entry, batch).

    The default session is the canonical 74-actual-minute run: provisional
    estimate 18000 (90 scheduled min x 200 cents/min), final charge 15000
    (75 billable min x 200) per the PRD §3.6/§3.8 charge rules.
    """
    stack = setup_canonical_stack(
        grant_budget=grant_budget, with_contract=with_contract,
        contract_overrides=contract_overrides,
    )
    booking = create_approved_booking(
        stack, start_at=booking_start_at, end_at=booking_end_at,
    )
    batch = open_batch(batch_year, batch_month)
    booking = run_session_to_completed(booking, actual_start_at, actual_end_at)
    log = create_and_validate_usage_log(
        booking, actual_start_at, actual_end_at,
        consumable_fee_cents=consumable_fee_cents,
    )
    entry = find_entry_for_usage_log(log["id"])
    return {"stack": stack, "booking": booking, "log": log,
            "entry": entry, "batch": batch}


def setup_billed_entry(**kwargs):
    """Tier-5 chain plus batch finalization: the entry is BILLED (PRD §3.9)."""
    ctx = setup_completed_booking_with_entry(**kwargs)
    ctx["batch"] = finalize_batch(ctx["batch"]["id"])
    ctx["entry"] = find_entry_for_usage_log(ctx["log"]["id"])
    return ctx


# ─── Tier 6: subsidy / award composites ─────────────────────────────────────

def create_subsidy_award(user, kind="SUBSIDY", requested_amount_cents=5000,
                         awarded_amount_cents=5000,
                         valid_from="2026-08-01T00:00:00Z",
                         valid_until="2026-12-01T00:00:00Z",
                         conveys_priority=False):
    """Application -> submit -> review -> approve; returns the minted award
    (PRD §3.10). The approval response carries the created SubsidyAward.
    """
    application = _ok(
        api_client.create_subsidy_application(
            create_subsidy_application_payload(
                user["id"], kind=kind,
                requested_amount_cents=requested_amount_cents,
            ),
            make_researcher_headers(user["id"]),
        ),
        "create subsidy application",
    )
    _ok(
        api_client.submit_subsidy_application(
            application["id"], make_researcher_headers(user["id"])
        ),
        "submit subsidy application",
    )
    _ok(api_client.review_subsidy_application(application["id"], FINANCE),
        "review subsidy application")
    award = _ok(
        api_client.approve_subsidy_application(
            application["id"],
            create_award_approval_payload(
                awarded_amount_cents=awarded_amount_cents,
                valid_from=valid_from, valid_until=valid_until,
                conveys_priority=conveys_priority,
            ),
            FINANCE,
        ),
        "approve subsidy application",
    )
    return award


def setup_priority_user(stack, instrument_id, grant_budget=50000,
                        award_amount=40000,
                        valid_from="2026-08-01T00:00:00Z",
                        valid_until="2026-12-01T00:00:00Z"):
    """A second INTERNAL user u2, certified, with own grant g2 and an ACTIVE
    STARTUP award conveying priority (PRD §3.6/§3.10)."""
    u2 = create_user(affiliation="INTERNAL", is_pi=True,
                     full_name="Pri Ority", email="p2@uni.edu")
    enroll_and_certify(u2["id"], instrument_id)
    g2 = create_grant(u2["id"], grant_code="NIH-2", title="Startup lab",
                      budget_total_cents=grant_budget)
    aw1 = create_subsidy_award(
        u2, kind="STARTUP", requested_amount_cents=award_amount,
        awarded_amount_cents=award_amount, valid_from=valid_from,
        valid_until=valid_until, conveys_priority=True,
    )
    return {"u2": u2, "g2": g2, "aw1": aw1}
