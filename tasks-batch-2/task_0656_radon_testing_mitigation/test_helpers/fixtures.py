"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so a broken setup step
surfaces as a clear "Setup failed" error instead of a confusing assertion.

Identity threading (PRD §2.1): entity-backed roles must call with the real
entity id. ClientContact uses the Property.id, Inspector uses the Inspector.id,
CrewLead uses the MitigationCrew.id. Every ownership-gated call below threads
the correct id via the make_<role>_headers builders.

Note on the logical clock: the server starts at 2026-04-01T00:00:00Z and never
falls back to wall-clock. Every retrieval needs the clock advanced >=
placement_window_hours past the placement instant.

The full cleared-job timeline is anchored so the post-mitigation retest (which
issues the warranty) records at exactly 2026-04-03T00:00:00Z, which several
test_suite assertions pin (warranty.started_at_utc, schedule.next_due_utc,
the §3.6 refund elapsed-days). Working backward from that anchor:

  2026-03-30T00:00:00Z  place INITIAL test (48h window)
  2026-04-01T00:00:00Z  retrieve+record INITIAL -> MITIGATION_REQUIRED
                        schedule install window [04-01T00:00, 04-01T04:00)
                        complete install (clock == install_start) -> INSTALLED
                        place POST_MITIGATION test (48h window)
  2026-04-03T00:00:00Z  retrieve+record POST_MITIGATION -> CLEARED,
                        warranty.started_at_utc == 2026-04-03T00:00:00Z
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_property_payload,
    create_inspector_payload,
    create_crew_payload,
    create_radon_test_payload,
    retrieve_short_term_payload,
    create_mitigation_job_payload,
    schedule_payload,
    create_payment_payload,
    create_permit_payload,
)
from .test_users import (
    TEST_USERS,
    make_inspector_headers,
    make_crew_lead_headers,
    make_client_contact_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DESIGNER = TEST_USERS["mitigation_designer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

CLOCK_DEFAULT = "2026-04-01T00:00:00Z"
CLOCK_AFTER_48H = "2026-04-03T00:00:00Z"

# Anchored cleared-job timeline (see module docstring).
CLOCK_INITIAL_PLACE = "2026-03-30T00:00:00Z"   # place INITIAL test here
CLOCK_INITIAL_RETRIEVE = "2026-04-01T00:00:00Z"  # +48h -> retrieve INITIAL
CLOCK_POST_MIT_RETRIEVE = "2026-04-03T00:00:00Z"  # +48h -> retrieve POST_MITIGATION
INSTALL_START_UTC = "2026-04-01T00:00:00Z"      # <= clock at complete-install
INSTALL_END_UTC = "2026-04-01T04:00:00Z"

# Monotonic license/permit suffixes so repeated fixture calls within one test
# never collide on a uniqueness constraint.
_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


# ─── primitives ────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance / set the logical clock (PlatformAdmin only)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_inspector(nrpp_license_id=None):
    """Register an ACTIVE inspector. Returns the inspector dict."""
    lic = nrpp_license_id or f"NRPP-{_next():04d}"
    res = api_client.create_inspector(
        create_inspector_payload(full_name="Ivy Insp", nrpp_license_id=lic), ADMIN)
    return get_success_data(res)


def create_crew(max_jobs_per_day=2):
    """Register an ACTIVE crew. Returns the crew dict."""
    res = api_client.create_crew(
        create_crew_payload(crew_name=f"Crew {_next()}",
                            max_jobs_per_day=max_jobs_per_day), ADMIN)
    return get_success_data(res)


def create_property(**overrides):
    """Create a property via ClientContact. Returns the property dict."""
    res = api_client.create_property(create_property_payload(**overrides),
                                     TEST_USERS["client_contact_headers"])
    return get_success_data(res)


def get_property(property_id):
    return get_success_data(
        api_client.get_property(property_id, make_client_contact_headers(property_id)))


# ─── Tier 1/2: actionable property (ACTION_RECOMMENDED initial result) ──────

def setup_actionable_property(foundation_type="SLAB", floor_area_sqft=1400,
                              lab_result=6.0, advance_clock=True, **prop_overrides):
    """Inspector ACTIVE + property + one INITIAL SHORT_TERM test driven to
    RESULT_READY with an ACTION_RECOMMENDED outcome (lab_result >= 4.0 default).
    Leaves the property posture at MITIGATION_REQUIRED so a job can be quoted.

    Returns (inspector, prop, init_test).
    """
    inspector = create_inspector()
    insp_headers = make_inspector_headers(inspector["id"])
    # Place the INITIAL test at 2026-03-30 so it can be retrieved at 2026-04-01
    # (48h window) and the downstream post-mitigation retest can land its own
    # 48h window on the 2026-04-03 anchor.
    set_clock(CLOCK_INITIAL_PLACE)
    prop = create_property(foundation_type=foundation_type,
                           floor_area_sqft=floor_area_sqft, **prop_overrides)

    test = get_success_data(api_client.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="SHORT_TERM_48HR", purpose="INITIAL",
                                  placement_window_hours=48),
        insp_headers))

    if advance_clock:
        set_clock(CLOCK_INITIAL_RETRIEVE)
    get_success_data(api_client.retrieve_radon_test(
        test["id"], retrieve_short_term_payload(lab_result), insp_headers))
    test = get_success_data(api_client.record_result(test["id"], insp_headers))
    return inspector, prop, test


# ─── Tier 3: job lifecycle shortcuts ────────────────────────────────────────

def setup_designed_job(foundation_type="SLAB", floor_area_sqft=1400,
                       lab_result=6.0, job_overrides=None, **prop_overrides):
    """Actionable property + a MitigationJob opened in DESIGN.
    Returns (inspector, prop, init_test, job)."""
    inspector, prop, init_test = setup_actionable_property(
        foundation_type=foundation_type, floor_area_sqft=floor_area_sqft,
        lab_result=lab_result, **prop_overrides)
    job = get_success_data(api_client.create_mitigation_job(
        create_mitigation_job_payload(prop["id"], init_test["id"],
                                      **(job_overrides or {})),
        DESIGNER))
    return inspector, prop, init_test, job


def setup_quoted_job(foundation_type="SLAB", floor_area_sqft=1400,
                     lab_result=6.0, job_overrides=None, **prop_overrides):
    """Through DESIGN→QUOTED. Returns (inspector, prop, init_test, job) where
    job carries the frozen quote_total_cents / deposit_required_cents."""
    inspector, prop, init_test, job = setup_designed_job(
        foundation_type=foundation_type, floor_area_sqft=floor_area_sqft,
        lab_result=lab_result, job_overrides=job_overrides, **prop_overrides)
    job = get_success_data(api_client.quote_job(job["id"], DESIGNER))
    return inspector, prop, init_test, job


def pay(job_id, kind, amount_cents):
    """Append a ledger entry on the job (ClientContact)."""
    return get_success_data(api_client.create_payment_record(
        create_payment_payload(job_id, kind, amount_cents),
        TEST_USERS["client_contact_headers"]))


def setup_scheduled_job(foundation_type="SLAB", floor_area_sqft=1400,
                        lab_result=6.0, job_overrides=None,
                        crew=None, install_start_utc=INSTALL_START_UTC,
                        install_end_utc=INSTALL_END_UTC,
                        pay_balance=True, **prop_overrides):
    """Through QUOTED→SCHEDULED. Pays the full deposit (and balance by default)
    then schedules against an ACTIVE crew at the given window.

    Returns (inspector, prop, init_test, job, crew).
    """
    inspector, prop, init_test, job = setup_quoted_job(
        foundation_type=foundation_type, floor_area_sqft=floor_area_sqft,
        lab_result=lab_result, job_overrides=job_overrides, **prop_overrides)
    crew = crew or create_crew()

    deposit_req = job["deposit_required_cents"]
    total = job["quote_total_cents"]
    pay(job["id"], "DEPOSIT", deposit_req)
    if pay_balance:
        pay(job["id"], "BALANCE", total - deposit_req)

    prop_now = get_property(prop["id"])
    job = get_success_data(api_client.schedule_job(
        job["id"],
        schedule_payload(crew["id"], install_start_utc, install_end_utc,
                         prop_now["version"]),
        DESIGNER))
    return inspector, prop, init_test, job, crew


def issue_permit(job_id, jurisdiction_code="CTY-1", permit_number=None):
    """Issue an ISSUED permit for the job (ComplianceOfficer). Returns permit."""
    num = permit_number or f"P-{_next():05d}"
    return get_success_data(api_client.create_permit(
        create_permit_payload(job_id, jurisdiction_code, num), COMPLIANCE))


def setup_installed_job(foundation_type="SLAB", floor_area_sqft=1400,
                        lab_result=6.0, job_overrides=None, pay_balance=True,
                        **prop_overrides):
    """Through SCHEDULED→INSTALLED. Issues a permit and completes the install
    (the clock is already at the install window start = 2026-04-01, so the
    "current instant at or after install_start_utc" gate is satisfied).

    Returns (inspector, prop, init_test, job, crew, permit).
    """
    inspector, prop, init_test, job, crew = setup_scheduled_job(
        foundation_type=foundation_type, floor_area_sqft=floor_area_sqft,
        lab_result=lab_result, job_overrides=job_overrides,
        pay_balance=pay_balance, **prop_overrides)
    permit = issue_permit(job["id"])
    crew_headers = make_crew_lead_headers(crew["id"])
    job = get_success_data(api_client.complete_install(job["id"], crew_headers))
    return inspector, prop, init_test, job, crew, permit


def place_post_mitigation_retest(prop, inspector, job_id, lab_result=1.5,
                                 advance_clock=True):
    """Place a POST_MITIGATION test on an INSTALLED job, retrieve and record.
    lab_result < 4.0 (default 1.5) yields NO_ACTION → drives CLEARED.

    The test is placed at the current clock (2026-04-01 on the anchored path)
    and the clock is advanced +48h to 2026-04-03 so the retrieval clears its
    placement window; that 2026-04-03 instant is the warranty.started_at_utc
    anchor several assertions pin.

    Returns the RESULT_READY test dict."""
    insp_headers = make_inspector_headers(inspector["id"])
    test = get_success_data(api_client.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="SHORT_TERM_48HR",
                                  purpose="POST_MITIGATION",
                                  mitigation_job_id=job_id,
                                  placement_window_hours=48),
        insp_headers))
    if advance_clock:
        set_clock(CLOCK_POST_MIT_RETRIEVE)
    get_success_data(api_client.retrieve_radon_test(
        test["id"], retrieve_short_term_payload(lab_result), insp_headers))
    return get_success_data(api_client.record_result(test["id"], insp_headers))


def setup_cleared_job_with_warranty(foundation_type="SLAB", floor_area_sqft=1400,
                                    lab_result=6.0, post_lab_result=1.5,
                                    job_overrides=None, **prop_overrides):
    """Full lifecycle DESIGN→...→CLEARED via a passing POST_MITIGATION retest.
    The CLEARED cascade issues a Warranty (ACTIVE/NONE) and arms a RetestSchedule.

    Returns (inspector, prop, job, warranty, schedule, post_test).
    """
    inspector, prop, init_test, job, crew, permit = setup_installed_job(
        foundation_type=foundation_type, floor_area_sqft=floor_area_sqft,
        lab_result=lab_result, job_overrides=job_overrides, **prop_overrides)
    post_test = place_post_mitigation_retest(prop, inspector, job["id"],
                                             lab_result=post_lab_result)
    job = get_success_data(api_client.get_mitigation_job(job["id"], DESIGNER))

    client = make_client_contact_headers(prop["id"])
    warranties, _ = _list(api_client.list_warranties(client,
                                                      params={"property_id": prop["id"]}))
    warranty = warranties[0] if warranties else None
    schedules, _ = _list(api_client.list_retest_schedules(
        client, params={"property_id": prop["id"]}))
    schedule = schedules[0] if schedules else None
    return inspector, prop, job, warranty, schedule, post_test


def _list(response):
    """Lenient list reader: returns (data_list, meta) from a 2xx list response."""
    body = response.json()
    data = body.get("data", [])
    meta = body.get("meta", {})
    return data, meta
