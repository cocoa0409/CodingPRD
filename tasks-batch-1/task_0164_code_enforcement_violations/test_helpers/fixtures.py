"""Composite setup helpers.

The test harness relaunches the server before every test, so each test starts
against an empty database. Every fixture therefore builds its full precondition
chain from scratch using only PRD-declared endpoints.

All setup calls use get_success_data() (lenient) so a setup misstep surfaces as a
clear "Setup failed" rather than a confusing downstream assertion.

Identity threading: after creating an Owner, ownership-gated calls (notice
contest) use make_registrant_headers(owner_id) — never the shared constant.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_registrant_headers
from . import factories
from .constants import FEE_SCHEDULES

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["code_officer_headers"]
HEARING = TEST_USERS["hearing_officer_headers"]
CLERK = TEST_USERS["finance_clerk_headers"]


# --------------------------------------------------------------------------
# Clock + configuration primitives
# --------------------------------------------------------------------------
def set_clock(iso8601: str):
    """Set the server's logical UTC clock."""
    return get_success_data(api_client.set_clock(factories.set_clock_payload(iso8601), ADMIN))


def seed_fee_schedule(violation_class="MAJOR", **overrides):
    """Seed one of the standard fee-schedule rows (MINOR/MAJOR/HAZARD)."""
    base = dict(FEE_SCHEDULES[violation_class])
    base.update(overrides)
    payload = factories.create_fee_schedule_payload(**base)
    return get_success_data(api_client.create_fee_schedule(payload, ADMIN))


def _uniq_parcel(prefix="APN"):
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _uniq_email(prefix="owner"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@x.com"


# --------------------------------------------------------------------------
# Owner / Property / Case primitives
# --------------------------------------------------------------------------
def create_owner(full_name="Test Owner", mailing_email=None, **overrides):
    payload = factories.create_owner_payload(
        full_name=full_name,
        mailing_email=mailing_email or _uniq_email(),
        **overrides,
    )
    return get_success_data(api_client.create_owner(payload, ADMIN))


def create_property(owner_id, parcel_number=None, occupancy="OCCUPIED", **overrides):
    payload = factories.create_property_payload(
        owner_id=owner_id,
        parcel_number=parcel_number or _uniq_parcel(),
        occupancy=occupancy,
        **overrides,
    )
    return get_success_data(api_client.create_property(payload, OFFICER))


def create_case(property_id, **overrides):
    payload = factories.create_case_payload(property_id, **overrides)
    return get_success_data(api_client.create_case(payload, OFFICER))


def case_version(case_id):
    """Read the case and return its current version (for OCC writes)."""
    return get_success_data(api_client.get_case(case_id, CLERK))["version"]


# --------------------------------------------------------------------------
# Tier 2: Case with a substantiating inspection
# --------------------------------------------------------------------------
def setup_owner_property_case(occupancy="OCCUPIED"):
    """Owner + ACTIVE Property + fresh INTAKE Case. Returns (owner, prop, case)."""
    owner = create_owner()
    prop = create_property(owner["id"], occupancy=occupancy)
    case = create_case(prop["id"])
    return owner, prop, case


def add_violation_found_inspection(case_id):
    """Create an INITIAL inspection and submit VIOLATION_FOUND. Returns inspection."""
    insp = get_success_data(
        api_client.create_inspection(factories.create_inspection_payload(case_id, "INITIAL"), OFFICER)
    )
    get_success_data(
        api_client.submit_inspection(
            insp["id"], factories.submit_inspection_payload("VIOLATION_FOUND"), OFFICER
        )
    )
    return insp


def setup_case_with_substantiation(occupancy="OCCUPIED"):
    """Owner + Property + Case + a VIOLATION_FOUND INITIAL inspection.

    Returns (owner, prop, case, inspection).
    """
    owner, prop, case = setup_owner_property_case(occupancy=occupancy)
    insp = add_violation_found_inspection(case["id"])
    return owner, prop, case, insp


# --------------------------------------------------------------------------
# Tier 3: Issued notice (and progressions)
# --------------------------------------------------------------------------
def issue_notice(case_id, source_inspection_id, violation_class="MAJOR"):
    """Issue a notice (DRAFT->ISSUED in one call). Returns the notice."""
    payload = factories.create_notice_payload(case_id, source_inspection_id, violation_class)
    return get_success_data(api_client.create_notice(payload, OFFICER))


def setup_issued_notice(violation_class="MAJOR", occupancy="OCCUPIED", clock="2026-01-01T00:00:00Z"):
    """Full chain to one ISSUED notice on a fresh case.

    Seeds the clock to `clock`, the fee schedule for `violation_class`, an owner,
    property, case, VIOLATION_FOUND inspection, then issues the notice.

    Returns a dict: owner, prop, case, inspection, notice.
    """
    set_clock(clock)
    seed_fee_schedule(violation_class)
    owner, prop, case, insp = setup_case_with_substantiation(occupancy=occupancy)
    notice = issue_notice(case["id"], insp["id"], violation_class)
    return {"owner": owner, "prop": prop, "case": case, "inspection": insp, "notice": notice}


def setup_overdue_notice(
    violation_class="MAJOR",
    issue_clock="2026-01-01T00:00:00Z",
    overdue_clock="2026-01-25T00:00:00Z",
    occupancy="OCCUPIED",
):
    """Issue a notice then advance the clock so it is OVERDUE.

    Returns the same dict as setup_issued_notice (notice not re-read; read it in
    the test to observe the lazy ISSUED->OVERDUE transition).
    """
    ctx = setup_issued_notice(violation_class, occupancy=occupancy, clock=issue_clock)
    set_clock(overdue_clock)
    return ctx


# --------------------------------------------------------------------------
# Tier 3b: Contest / Hearing
# --------------------------------------------------------------------------
def contest_notice(notice_id, owner_id, scheduled_for):
    """Registrant (owner) contests a notice -> CONTESTED + SCHEDULED hearing.

    Uses make_registrant_headers(owner_id) for the ownership-gated call.
    Returns the created Hearing.
    """
    headers = make_registrant_headers(owner_id)
    payload = factories.contest_notice_payload(scheduled_for)
    return get_success_data(api_client.contest_notice(notice_id, payload, headers))


def setup_contested_notice(
    issue_clock="2026-01-01T00:00:00Z",
    scheduled_for="2026-01-10T00:00:00Z",
    violation_class="MAJOR",
):
    """Issue a MAJOR notice and contest it within the window.

    Returns the setup dict plus a "hearing" key.
    """
    ctx = setup_issued_notice(violation_class, clock=issue_clock)
    hearing = contest_notice(ctx["notice"]["id"], ctx["owner"]["id"], scheduled_for)
    ctx["hearing"] = hearing
    return ctx


def decide_hearing(hearing_id, decision):
    """HearingOfficer decides a ripe hearing UPHELD/DISMISSED."""
    payload = factories.decide_hearing_payload(decision)
    return get_success_data(api_client.decide_hearing(hearing_id, payload, HEARING))


# --------------------------------------------------------------------------
# Tier 3c: Reinspection / cure
# --------------------------------------------------------------------------
def schedule_reinspection(notice_id):
    payload = factories.create_reinspection_payload(notice_id)
    return get_success_data(api_client.create_reinspection(payload, OFFICER))


def record_reinspection(reinspection_id, result="PASSED"):
    payload = factories.reinspection_result_payload(result)
    return get_success_data(
        api_client.record_reinspection_result(reinspection_id, payload, OFFICER)
    )


def cure_notice_to_complied(notice_id):
    """Schedule + pass a reinspection so the notice reaches COMPLIED. Returns reinspection."""
    reinsp = schedule_reinspection(notice_id)
    record_reinspection(reinsp["id"], "PASSED")
    return reinsp


# --------------------------------------------------------------------------
# Tier 4: Abatement
# --------------------------------------------------------------------------
def order_abatement(case_id, action_kind="BOARD_UP", estimated_cost_cents=30000):
    payload = factories.create_abatement_order_payload(
        case_id, action_kind, estimated_cost_cents
    )
    return get_success_data(api_client.create_abatement_order(payload, OFFICER))


def complete_abatement(case_id, action_kind="BOARD_UP", actual_cost_cents=30000):
    """Order -> start -> complete an abatement, capturing actual_cost into the ledger.

    Returns the COMPLETED AbatementOrder.
    """
    order = order_abatement(case_id, action_kind, estimated_cost_cents=actual_cost_cents)
    get_success_data(api_client.start_abatement_order(order["id"], OFFICER))
    payload = factories.complete_abatement_payload(actual_cost_cents)
    return get_success_data(api_client.complete_abatement_order(order["id"], payload, OFFICER))


# --------------------------------------------------------------------------
# Tier 5: Lien recording / payment
# --------------------------------------------------------------------------
def record_lien(case_id, expected_version=None):
    """Record a lien against the case using the current (or supplied) version."""
    if expected_version is None:
        expected_version = case_version(case_id)
    payload = factories.create_lien_payload(case_id, expected_version)
    return get_success_data(api_client.create_lien(payload, CLERK))


def post_payment(case_id, amount_cents, expected_version=None):
    if expected_version is None:
        expected_version = case_version(case_id)
    payload = factories.payment_payload(amount_cents, expected_version)
    return get_success_data(api_client.post_payment(case_id, payload, CLERK))


def setup_recorded_lien(
    issue_clock="2026-01-01T00:00:00Z",
    overdue_clock="2026-01-25T00:00:00Z",
):
    """MAJOR notice OVERDUE then a RECORDED lien on the case.

    Returns the setup dict plus a "lien" key.
    """
    ctx = setup_overdue_notice(issue_clock=issue_clock, overdue_clock=overdue_clock)
    lien = record_lien(ctx["case"]["id"])
    ctx["lien"] = lien
    return ctx


# --------------------------------------------------------------------------
# Repeat-offender history: drive an owner to REPEAT tier (2 prior COMPLIED)
# --------------------------------------------------------------------------
def raise_owner_to_repeat(owner_id, violation_class="MAJOR"):
    """Create two notices on the owner's properties and cure each to COMPLIED, so the
    owner has prior_violation_count == 2 (REPEAT tier).

    Assumes the clock and the relevant fee schedule are already seeded. Each prior
    notice is issued on its own fresh property/case (single-active-case rule), so the
    cases never need to be closed — the rolling count keys on notice status
    (COMPLIED/UPHELD), not on case closure (PRD §3.5). Closing a cured case is not
    even possible: a COMPLIED notice's settlement fine_total_cents stays in the case
    balance (PRD §3.10), so the case never reaches balance 0.
    """
    for _ in range(2):
        prop = create_property(owner_id)
        case = create_case(prop["id"])
        insp = add_violation_found_inspection(case["id"])
        notice = issue_notice(case["id"], insp["id"], violation_class)
        cure_notice_to_complied(notice["id"])
