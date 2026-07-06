"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors, not confusing assertion failures. Each helper builds
its preconditions from scratch — the harness restarts the server (empty DB) before
every test.

The logical clock starts at 2026-05-01T00:00:00Z on every server restart (PRD 2.9),
so recipes that depend on "now" set the clock explicitly where they need to.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_program_payload, create_camera_payload, create_calibration_payload,
    create_owner_payload, create_citation_payload, review_payload,
    create_contest_payload, create_hearing_payload, rule_payload,
    create_payment_payload, create_vendor_contract_payload, settle_payload,
    clock_payload,
)
from .test_users import (
    TEST_USERS, make_review_officer_headers, make_adjudicator_headers,
    make_registered_owner_headers,
)

SYS = TEST_USERS["system_admin_headers"]
PA = TEST_USERS["program_admin_headers"]
RO = make_review_officer_headers("ro-1")
AUD = TEST_USERS["auditor_headers"]


# ─── Clock helper ─────────────────────────────────────
def set_clock(to_iso8601: str):
    """Advance/set the server logical clock (PRD 2.9)."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), SYS))


# ─── Tier 1 / Tier 2: Program + camera + calibration + owner ──────────

def create_program(**overrides):
    """Create a program with the standard fiscal config. Returns the program."""
    res = api_client.create_program(create_program_payload(**overrides), SYS)
    return get_success_data(res)


def create_camera(program_id, **overrides):
    """Register a camera under a program (starts ACTIVE)."""
    res = api_client.create_camera(create_camera_payload(program_id, **overrides), PA)
    return get_success_data(res)


def add_calibration(camera_id, **overrides):
    """Log a calibration record for a camera. Returns the record."""
    res = api_client.create_calibration(camera_id, create_calibration_payload(**overrides), PA)
    return get_success_data(res)


def create_owner(program_id, **overrides):
    """Register a plate owner. Returns the owner (incl. portal_access_pin)."""
    res = api_client.create_owner(create_owner_payload(program_id, **overrides), PA)
    return get_success_data(res)


def setup_program_camera_owner(camera_overrides=None, calibration_overrides=None,
                               owner_overrides=None, program_overrides=None,
                               with_calibration=True, with_owner=True):
    """Program + one camera (+ optional PASS calibration) (+ optional owner).

    Returns dict with keys: program, camera, calibration (or None), owner (or None).
    Defaults produce a RED_LIGHT camera with a PASS calibration covering the
    standard event time (2026-05-01T08:00:00Z) and a registered owner for ABC123.
    """
    program = create_program(**(program_overrides or {}))
    camera = create_camera(program["id"], **(camera_overrides or {}))
    calibration = None
    if with_calibration:
        calibration = add_calibration(camera["id"], **(calibration_overrides or {}))
    owner = None
    if with_owner:
        owner = create_owner(program["id"], **(owner_overrides or {}))
    return {
        "program": program,
        "camera": camera,
        "calibration": calibration,
        "owner": owner,
    }


# ─── Tier 3: capture + review shortcuts ──────────────────

def capture_citation(program_id, camera_id, review_officer_id="ro-1",
                     citation_overrides=None):
    """Capture a violation event (creates citation PENDING_REVIEW). Returns citation."""
    headers = make_review_officer_headers(review_officer_id)
    res = api_client.create_citation(
        create_citation_payload(program_id, camera_id, **(citation_overrides or {})),
        headers,
    )
    return get_success_data(res)


def review_to_cited(citation_id, review_officer_id="ro-1"):
    """Approve a pending citation -> CITED. Returns the updated citation."""
    headers = make_review_officer_headers(review_officer_id)
    res = api_client.review_citation(citation_id, review_payload("APPROVE"), headers)
    return get_success_data(res)


def setup_cited_citation(review_officer_id="ro-1", program_overrides=None,
                         camera_overrides=None, calibration_overrides=None,
                         owner_overrides=None, citation_overrides=None):
    """Full chain: program -> camera(+PASS cal) -> owner -> capture -> review APPROVE.

    Returns dict: program, camera, owner, citation (in CITED). For a standard
    RED_LIGHT program this yields assessed_amount_cents == 12500.
    """
    ctx = setup_program_camera_owner(
        program_overrides=program_overrides,
        camera_overrides=camera_overrides,
        calibration_overrides=calibration_overrides,
        owner_overrides=owner_overrides,
    )
    citation = capture_citation(
        ctx["program"]["id"], ctx["camera"]["id"],
        review_officer_id=review_officer_id, citation_overrides=citation_overrides,
    )
    cited = review_to_cited(citation["id"], review_officer_id=review_officer_id)
    ctx["citation"] = cited
    return ctx


# ─── Tier 3: contest + hearing shortcuts ─────────────────

def file_contest(citation_id, owner_id, pin, expected_citation_version, **overrides):
    """Owner files a contest via portal PIN auth. Returns the contest."""
    headers = make_registered_owner_headers(owner_id)
    res = api_client.create_contest(
        citation_id,
        create_contest_payload(owner_id, pin, expected_citation_version, **overrides),
        headers,
    )
    return get_success_data(res)


def schedule_hearing(contest_id, scheduled_at_utc, adjudicator_ref, **overrides):
    """ProgramAdmin schedules a hearing (assigns adjudicator). Returns the hearing."""
    res = api_client.create_hearing(
        contest_id,
        create_hearing_payload(scheduled_at_utc, adjudicator_ref, **overrides),
        PA,
    )
    return get_success_data(res)


def setup_hearing_scheduled(review_officer_id="ro-1", adjudicator_ref="adj-9",
                            ground="PLATE_MISREAD",
                            scheduled_at_utc="2026-05-15T10:00:00Z",
                            program_overrides=None, citation_overrides=None):
    """Chain: CITED citation -> owner contests -> hearing scheduled with a distinct
    adjudicator. Clock is NOT advanced (caller advances to hearing time before ruling).

    Returns dict: program, camera, owner, citation, contest, hearing.
    The citation is in HEARING_SCHEDULED; contest SCHEDULED; hearing SCHEDULED.
    """
    ctx = setup_cited_citation(
        review_officer_id=review_officer_id,
        program_overrides=program_overrides,
        citation_overrides=citation_overrides,
    )
    citation = ctx["citation"]
    owner = ctx["owner"]
    contest = file_contest(
        citation["id"], owner["id"], owner["portal_access_pin"],
        citation["version"], ground=ground,
    )
    hearing = schedule_hearing(contest["id"], scheduled_at_utc, adjudicator_ref)
    ctx["contest"] = contest
    ctx["hearing"] = hearing
    return ctx


def rule_hearing(hearing_id, outcome, expected_hearing_version, adjudicator_ref="adj-9",
                 **overrides):
    """Adjudicator rules on a hearing. Returns the ruled hearing."""
    headers = make_adjudicator_headers(adjudicator_ref)
    res = api_client.rule_hearing(
        hearing_id, rule_payload(outcome, expected_hearing_version, **overrides), headers,
    )
    return get_success_data(res)


# ─── Tier 3/4: vendor contract + payment shortcuts ───────

def create_vendor_contract(program_id, revenue_share_pct=0.3, **overrides):
    """Create an ACTIVE vendor contract. Returns the contract."""
    res = api_client.create_vendor_contract(
        create_vendor_contract_payload(program_id, revenue_share_pct, **overrides), PA,
    )
    return get_success_data(res)


def initiate_payment(citation_id, amount_cents, method="CARD", headers=None):
    """Initiate a payment (ProgramAdmin by default). Returns the payment."""
    res = api_client.create_payment(
        citation_id, create_payment_payload(amount_cents, method), headers or PA,
    )
    return get_success_data(res)


def settle_to_cleared(payment_id):
    """Settle an initiated payment to CLEARED. Returns the settled payment."""
    res = api_client.settle_payment(settle_payload(payment_id, "CLEARED"), SYS)
    return get_success_data(res)


def setup_paid_citation(revenue_share_pct=0.3, vendor_overrides=None,
                        program_overrides=None):
    """Chain: ACTIVE vendor contract + CITED citation -> pay full 12500 -> clears -> PAID.

    Returns dict: program, camera, owner, citation, vendor_contract, payment.
    For a standard RED_LIGHT program at 30% share this accrues 3000 to the vendor.
    """
    program = create_program(**(program_overrides or {}))
    vendor = create_vendor_contract(program["id"], revenue_share_pct,
                                    **(vendor_overrides or {}))
    camera = create_camera(program["id"])
    add_calibration(camera["id"])
    owner = create_owner(program["id"])
    citation = capture_citation(program["id"], camera["id"])
    review_to_cited(citation["id"])
    payment = initiate_payment(citation["id"], 12500)
    settle_to_cleared(payment["id"])
    return {
        "program": program,
        "camera": camera,
        "owner": owner,
        "citation": get_success_data(api_client.get_citation(citation["id"], PA)),
        "vendor_contract": vendor,
        "payment": payment,
    }
