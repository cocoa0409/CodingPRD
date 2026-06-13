"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures.

Each test runs against a freshly restarted, empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Driver-initiated,
ownership-gated calls thread the real Driver.id through make_driver_headers().
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_jurisdiction_payload,
    create_driver_payload,
    create_citation_payload,
    create_charge_payload,
    create_payment_payload,
    create_installment_plan_payload,
    create_contest_request_payload,
    create_schedule_payload,
    create_decide_payload,
    create_enrollment_payload,
)
from .test_users import TEST_USERS, make_driver_headers

CLERK = TEST_USERS["clerk_headers"]
HEARING = TEST_USERS["hearing_officer_headers"]
DMV = TEST_USERS["dmv_headers"]


# ─── Clock ───────────────────────────────────────────────────────────────
def set_clock(to_iso8601):
    """Advance the server clock; used for deterministic time-gated tests."""
    return get_success_data(api_client.set_clock(to_iso8601, CLERK))


# ─── Tier 1: Base entities ───────────────────────────────────────────────
def create_jurisdiction(**overrides):
    """Create a jurisdiction with the standard fee schedule (override as needed)."""
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_payload(**overrides), CLERK)
    )


def create_driver(jurisdiction_id, **overrides):
    return get_success_data(
        api_client.create_driver(
            create_driver_payload(jurisdiction_id, **overrides), CLERK
        )
    )


def setup_jurisdiction_and_driver(jurisdiction_overrides=None, driver_overrides=None):
    """Create a jurisdiction + one driver. Returns (jurisdiction, driver)."""
    jur = create_jurisdiction(**(jurisdiction_overrides or {}))
    driver = create_driver(jur["id"], **(driver_overrides or {}))
    return jur, driver


# ─── Tier 2: Citations in various states ─────────────────────────────────
def create_draft_citation(driver_id, charge_overrides=None, citation_overrides=None):
    """Create a DRAFT citation with one charge. Returns the citation dict.

    The returned citation is re-fetched so base_fine_cents reflects the charge.
    """
    cit = get_success_data(
        api_client.create_citation(
            create_citation_payload(driver_id, **(citation_overrides or {})), CLERK
        )
    )
    api_client.create_charge(
        create_charge_payload(cit["id"], **(charge_overrides or {})), CLERK
    )
    return get_success_data(api_client.get_citation(cit["id"], CLERK))


def setup_assessed_citation(jurisdiction_overrides=None, charge_overrides=None,
                            citation_overrides=None, driver_overrides=None):
    """Jurisdiction + driver + assessed citation (one charge).

    Returns (jurisdiction, driver, citation) where citation is ASSESSED.
    """
    jur, driver = setup_jurisdiction_and_driver(
        jurisdiction_overrides=jurisdiction_overrides,
        driver_overrides=driver_overrides,
    )
    cit = get_success_data(
        api_client.create_citation(
            create_citation_payload(driver["id"], **(citation_overrides or {})), CLERK
        )
    )
    api_client.create_charge(
        create_charge_payload(cit["id"], **(charge_overrides or {})), CLERK
    )
    assessed = get_success_data(api_client.assess_citation(cit["id"], CLERK))
    return jur, driver, assessed


def pay_citation_in_full(citation, driver_id):
    """Post a payment that drives balance_cents to zero. Returns the payment dict."""
    amount = citation["balance_cents"]
    return get_success_data(
        api_client.create_payment(
            citation["id"],
            create_payment_payload(amount, method="CARD"),
            make_driver_headers(driver_id),
        )
    )


# ─── Tier 3: Installment plans ───────────────────────────────────────────
def setup_citation_with_active_plan(term_count=4, jurisdiction_overrides=None,
                                    charge_overrides=None):
    """Assessed citation + one ACTIVE installment plan.

    Returns (jurisdiction, driver, citation, plan, installments) where
    installments is the ordered list of Installment rows for the plan.
    """
    jur, driver, cit = setup_assessed_citation(
        jurisdiction_overrides=jurisdiction_overrides,
        charge_overrides=charge_overrides,
    )
    plan = get_success_data(
        api_client.create_installment_plan(
            cit["id"],
            create_installment_plan_payload(term_count, cit["version"]),
            make_driver_headers(driver["id"]),
        )
    )
    installments = list_installments_for_plan(plan["id"])
    return jur, driver, cit, plan, installments


def list_installments_for_plan(plan_id):
    """Return the plan's installments ordered by sequence_no."""
    data = get_success_data(
        api_client.list_installments(CLERK, params={"installment_plan_id": plan_id})
    )
    rows = data if isinstance(data, list) else data.get("items", [])
    return sorted(rows, key=lambda r: r["sequence_no"])


# ─── Tier 4: Contests, hearings, verdicts ────────────────────────────────
def file_contest(citation_id, driver_id, grounds="Disputed"):
    return get_success_data(
        api_client.create_contest_request(
            citation_id, create_contest_request_payload(grounds=grounds),
            make_driver_headers(driver_id),
        )
    )


def setup_contest_hearing_set(hearing_at="2026-03-01T00:00:00Z", clock=None,
                              charge_overrides=None, jurisdiction_overrides=None):
    """Assessed citation -> contest filed -> hearing scheduled (HEARING_SET).

    Returns (jurisdiction, driver, citation, contest).
    """
    if clock is not None:
        set_clock(clock)
    jur, driver, cit = setup_assessed_citation(
        jurisdiction_overrides=jurisdiction_overrides,
        charge_overrides=charge_overrides,
    )
    contest = file_contest(cit["id"], driver["id"])
    contest = get_success_data(
        api_client.schedule_hearing(
            contest["id"], create_schedule_payload(hearing_at), CLERK
        )
    )
    return jur, driver, cit, contest


def uphold_citation_points(driver, citation, hearing_at="2026-03-01T00:00:00Z"):
    """File a contest on an assessed citation, schedule, and UPHOLD it.

    Posts one PointLedgerEntry per charge with points>0. Returns the contest dict.
    """
    contest = file_contest(citation["id"], driver["id"])
    get_success_data(
        api_client.schedule_hearing(
            contest["id"], create_schedule_payload(hearing_at), CLERK
        )
    )
    return get_success_data(
        api_client.decide_contest(
            contest["id"], create_decide_payload("UPHOLD"), HEARING
        )
    )


def _future_hearing_at(clock_iso):
    """A hearing_at one day after the given clock instant (PRD §3.7 requires the
    scheduled hearing to be in the future relative to the server clock)."""
    from datetime import datetime, timedelta, timezone
    s = clock_iso[:-1] + "+00:00" if clock_iso.endswith("Z") else clock_iso
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt + timedelta(days=1)).astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def setup_driver_with_uphold(points=2, clock="2026-01-05T00:00:00Z",
                             jurisdiction_overrides=None):
    """One UPHELD citation carrying `points` points. Returns (jur, driver, citation).

    The citation is assessed at issued_at 2026-01-04 so its point entry is in
    the rolling window for a clock near 2026.
    """
    set_clock(clock)
    jur, driver, cit = setup_assessed_citation(
        jurisdiction_overrides=jurisdiction_overrides,
        citation_overrides={
            "issued_at": "2026-01-04T00:00:00Z",
            "appear_by": "2026-02-04T00:00:00Z",
        },
        charge_overrides={
            "violation_code": "VC23103", "description": "Reckless",
            "base_fine_cents": 10000, "points": points,
        },
    )
    # The hearing must be scheduled in the future relative to the (possibly
    # advanced) clock, else schedule is rejected with ERR_INVALID_HEARING_DATE.
    uphold_citation_points(driver, cit, hearing_at=_future_hearing_at(clock))
    return jur, driver, cit


def setup_driver_suspended_two_upholds(jurisdiction_overrides=None,
                                       clock="2026-01-05T00:00:00Z"):
    """Driver with two UPHELD 2-point citations => point_balance 4 => SUSPENDED.

    Returns (jurisdiction, driver, citation_a, citation_b).
    """
    set_clock(clock)
    jur, driver = setup_jurisdiction_and_driver(
        jurisdiction_overrides=jurisdiction_overrides
    )
    cits = []
    for i, (issued, appear) in enumerate(
        [("2026-01-02T00:00:00Z", "2026-02-02T00:00:00Z"),
         ("2026-01-03T00:00:00Z", "2026-02-03T00:00:00Z")]
    ):
        cit = get_success_data(
            api_client.create_citation(
                create_citation_payload(
                    driver["id"], issued_at=issued, appear_by=appear
                ),
                CLERK,
            )
        )
        api_client.create_charge(
            create_charge_payload(
                cit["id"], violation_code="VC23103", description="Reckless",
                base_fine_cents=10000, points=2,
            ),
            CLERK,
        )
        assessed = get_success_data(api_client.assess_citation(cit["id"], CLERK))
        uphold_citation_points(
            driver, assessed, hearing_at=f"2026-03-0{i + 1}T00:00:00Z"
        )
        cits.append(assessed)
    return jur, driver, cits[0], cits[1]


# ─── Tier 5: Traffic-school readiness ────────────────────────────────────
def setup_paid_school_eligible_enrollment(clock="2026-01-05T00:00:00Z",
                                          completion_due_at="2026-04-01T00:00:00Z",
                                          jurisdiction_overrides=None):
    """A paid, school-eligible citation with an open ENROLLED enrollment.

    Citation has one 1-point charge (<= default school_eligible_max_points),
    paid in full. Returns (jurisdiction, driver, citation, enrollment).
    """
    set_clock(clock)
    jur, driver, cit = setup_assessed_citation(
        jurisdiction_overrides=jurisdiction_overrides,
        citation_overrides={
            "issued_at": "2026-01-04T00:00:00Z",
            "appear_by": "2026-02-04T00:00:00Z",
        },
        charge_overrides={"base_fine_cents": 20000, "points": 1},
    )
    pay_citation_in_full(cit, driver["id"])
    paid = get_success_data(api_client.get_citation(cit["id"], CLERK))
    enrollment = get_success_data(
        api_client.create_enrollment(
            paid["id"], create_enrollment_payload(completion_due_at),
            make_driver_headers(driver["id"]),
        )
    )
    return jur, driver, paid, enrollment


# ─── Lookup helpers ──────────────────────────────────────────────────────
def _list_rows(response_data):
    return response_data if isinstance(response_data, list) else response_data.get("items", [])


def list_license_holds(driver_id=None, citation_id=None, status=None):
    params = {}
    if driver_id:
        params["driver_id"] = driver_id
    if citation_id:
        params["citation_id"] = citation_id
    if status:
        params["status"] = status
    data = get_success_data(api_client.list_license_holds(DMV, params=params or None))
    return _list_rows(data)


def find_hold(driver_id=None, citation_id=None, hold_type=None, status=None):
    """Return the first matching LicenseHold or None."""
    for hold in list_license_holds(driver_id=driver_id, citation_id=citation_id):
        if hold_type and hold["hold_type"] != hold_type:
            continue
        if status and hold["status"] != status:
            continue
        return hold
    return None


def list_warrants(citation_id=None, driver_id=None, status=None):
    params = {}
    if citation_id:
        params["citation_id"] = citation_id
    if driver_id:
        params["driver_id"] = driver_id
    if status:
        params["status"] = status
    data = get_success_data(api_client.list_warrants(CLERK, params=params or None))
    return _list_rows(data)


def list_point_ledger(driver_id=None, citation_id=None, state=None):
    params = {}
    if driver_id:
        params["driver_id"] = driver_id
    if citation_id:
        params["citation_id"] = citation_id
    if state:
        params["state"] = state
    data = get_success_data(api_client.list_point_ledger(DMV, params=params or None))
    return _list_rows(data)
