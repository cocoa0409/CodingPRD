"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. All callers are responsible for their own assertions.

Role defaults: creates are filed by the compliance analyst, reviews/approvals
by the director, monitoring by the SEA monitor, and affirmation signatures by
the ombudsman — with distinct operator ids so segregation-of-duties checks
(PRD §2.9) pass inside fixtures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    CAP_NARRATIVE,
    SNS_NARRATIVE,
    create_amendment_payload,
    create_consultation_payload,
    create_expenditure_payload,
    create_finding_payload,
    create_grant_payload,
    create_private_school_payload,
    create_school_payload,
    create_snapshot_payload,
    create_sns_payload,
    create_visit_payload,
    record_session_payload,
    snapshot_entry,
)
from .test_users import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
ANALYST = TEST_USERS["analyst_headers"]
MONITOR = TEST_USERS["monitor_headers"]
OMBUDSMAN = TEST_USERS["ombudsman_headers"]


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {step}: {exc}")


# ---------------------------------------------------------------------------
# Tier 1 — registry and grant lifecycle primitives
# ---------------------------------------------------------------------------

def register_school(name, nces_id, grade_span_low=0, grade_span_high=12,
                    is_active=None, as_headers=None):
    resp = api_client.create_school(
        create_school_payload(name=name, nces_id=nces_id,
                              grade_span_low=grade_span_low,
                              grade_span_high=grade_span_high,
                              is_active=is_active),
        as_headers or ANALYST,
    )
    return _ok("create_school", resp)


def register_private_school(name, low_income_resident_count,
                            contact_email=None, nonprofit_verified=True,
                            as_headers=None):
    resp = api_client.create_private_school(
        create_private_school_payload(
            name=name,
            low_income_resident_count=low_income_resident_count,
            contact_email=contact_email
            or f"om@{name.lower().replace(' ', '')}.example",
            nonprofit_verified=nonprofit_verified),
        as_headers or ANALYST,
    )
    return _ok("create_private_school", resp)


def open_grant(fiscal_year, total_allocation_cents,
               poverty_measure="CENSUS_SAIPE", carryover_in_cents=None,
               admin_reserve_cents=None, equitable_count_method="VERIFIED_COUNT",
               as_headers=None):
    """Create a grant. Defaults to VERIFIED_COUNT so the finalization
    consultation gate (PRD §3.3) does not fire unless requested."""
    resp = api_client.create_grant(
        create_grant_payload(
            fiscal_year=fiscal_year,
            total_allocation_cents=total_allocation_cents,
            poverty_measure=poverty_measure,
            carryover_in_cents=carryover_in_cents,
            admin_reserve_cents=admin_reserve_cents,
            equitable_count_method=equitable_count_method),
        as_headers or DIRECTOR,
    )
    return _ok("create_grant", resp)


def get_grant(grant_id, as_headers=None):
    resp = api_client.get_grant(grant_id, as_headers or DIRECTOR)
    return _ok("get_grant", resp)


def create_snapshot(grant_id, entries, measure="CENSUS_SAIPE",
                    as_headers=None):
    resp = api_client.create_snapshot(
        create_snapshot_payload(grant_id, entries, measure=measure),
        as_headers or ANALYST,
    )
    return _ok("create_snapshot", resp)


def certify_snapshot(snapshot_id, grant_id, as_headers=None):
    """Certify a snapshot, reading the grant's current version fresh so the
    optimistic-concurrency precondition (PRD §2.7) is satisfied."""
    grant = get_grant(grant_id)
    resp = api_client.certify_snapshot(
        snapshot_id, {"expected_grant_version": grant["version"]},
        as_headers or DIRECTOR,
    )
    return _ok("certify_snapshot", resp)


def lock_rankings(grant_id, as_headers=None):
    resp = api_client.lock_rankings(grant_id, as_headers or DIRECTOR)
    return _ok("lock_rankings", resp)


def finalize_allocations(grant_id, serve_below_threshold_school_ids=None,
                         as_headers=None):
    payload = {}
    if serve_below_threshold_school_ids is not None:
        payload["serve_below_threshold_school_ids"] = \
            serve_below_threshold_school_ids
    resp = api_client.finalize_allocations(grant_id, as_headers or DIRECTOR,
                                           payload)
    return _ok("finalize_allocations", resp)


# ---------------------------------------------------------------------------
# Tier 2 — grant scenario composites (ranking-locked / allocated)
# ---------------------------------------------------------------------------

def get_allocation_for(grant_id, school_id, as_headers=None):
    resp = api_client.list_allocations(
        as_headers or DIRECTOR,
        params={"grant_id": grant_id, "school_id": school_id})
    rows = _ok("list_allocations", resp)
    assert len(rows) == 1, \
        f"expected exactly one allocation for school {school_id}, got {rows}"
    return rows[0]


def get_set_aside_for(grant_id, category, as_headers=None):
    resp = api_client.list_set_asides(
        as_headers or DIRECTOR,
        params={"grant_id": grant_id, "category": category})
    rows = _ok("list_set_asides", resp)
    assert len(rows) == 1, \
        f"expected exactly one {category} set-aside, got {rows}"
    return rows[0]


def list_allocations_for(grant_id, as_headers=None):
    resp = api_client.list_allocations(
        as_headers or DIRECTOR, params={"grant_id": grant_id, "limit": 100})
    return _ok("list_allocations", resp)


def list_set_asides_for(grant_id, as_headers=None):
    resp = api_client.list_set_asides(
        as_headers or DIRECTOR, params={"grant_id": grant_id, "limit": 100})
    return _ok("list_set_asides", resp)


def setup_ranking_locked(fiscal_year, school_entries,
                         total_allocation_cents=10_000_000,
                         name_prefix="School", nces_prefix="20",
                         schools=None,
                         **grant_kwargs):
    """Grant + one school per entry + certified snapshot + lock-rankings.

    school_entries: list of (low_income_student_count, total_student_count).
    schools: optional pre-registered school rows to reuse instead of
    registering new ones. Required when one test stands up a second grant
    against the same server: `nces_id` is unique across all schools and every
    certified snapshot must cover every active school exactly once (PRD
    §3.2), so registering a fresh roster would either collide on `nces_id`
    or leave the earlier schools uncovered.
    Returns dict(grant, schools, snapshot, allocations).
    """
    grant = open_grant(fiscal_year, total_allocation_cents, **grant_kwargs)
    if schools is None:
        schools = [
            register_school(f"{name_prefix} {i + 1}", f"{nces_prefix}{i + 1:05d}")
            for i in range(len(school_entries))
        ]
    assert len(schools) == len(school_entries), \
        "pre-registered schools must align one-to-one with school_entries"
    entries = [
        snapshot_entry(s["id"], li, tot)
        for s, (li, tot) in zip(schools, school_entries)
    ]
    snapshot = create_snapshot(grant["id"], entries,
                               measure=grant["poverty_measure"])
    certify_snapshot(snapshot["id"], grant["id"])
    lock_rankings(grant["id"])
    allocations = {
        s["id"]: get_allocation_for(grant["id"], s["id"]) for s in schools
    }
    return {
        "grant": get_grant(grant["id"]),
        "schools": schools,
        "snapshot": snapshot,
        "allocations": allocations,
    }


def setup_allocated(fiscal_year, school_entries,
                    total_allocation_cents=10_000_000,
                    serve_below_threshold_school_ids=None,
                    name_prefix="School", nces_prefix="20",
                    schools=None,
                    **grant_kwargs):
    """setup_ranking_locked + finalize-allocations. Adds set_asides."""
    ctx = setup_ranking_locked(
        fiscal_year, school_entries,
        total_allocation_cents=total_allocation_cents,
        name_prefix=name_prefix, nces_prefix=nces_prefix,
        schools=schools,
        **grant_kwargs)
    grant_id = ctx["grant"]["id"]
    finalize_allocations(grant_id, serve_below_threshold_school_ids)
    ctx["grant"] = get_grant(grant_id)
    ctx["allocations"] = {
        s["id"]: get_allocation_for(grant_id, s["id"])
        for s in ctx["schools"]
    }
    ctx["set_asides"] = {
        row["category"]: row for row in list_set_asides_for(grant_id)
    }
    return ctx


def certify_allocation(allocation_id, as_headers=None):
    resp = api_client.certify_allocation(allocation_id, as_headers or DIRECTOR)
    return _ok("certify_allocation", resp)


def setup_certified_allocation(fiscal_year, school_entries=((100, 100),),
                               total_allocation_cents=10_000_000,
                               schools=None,
                               **grant_kwargs):
    """Allocated grant whose first school's allocation is CERTIFIED.
    Returns ctx with ctx["allocation"] pointing at that row."""
    ctx = setup_allocated(fiscal_year, school_entries,
                          total_allocation_cents=total_allocation_cents,
                          schools=schools,
                          **grant_kwargs)
    first_school = ctx["schools"][0]
    allocation = certify_allocation(ctx["allocations"][first_school["id"]]["id"])
    ctx["allocation"] = allocation
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — expenditures, SNS documents, consultations, monitoring, amendments
# ---------------------------------------------------------------------------

def funds_period_date(grant, month=9, day=1):
    """A date comfortably inside the grant's funds period (PRD §3.1: July 1
    of fiscal_year-1 through June 30 of fiscal_year)."""
    return f"{grant['fiscal_year'] - 1}-{month:02d}-{day:02d}"


def charge_expenditure(grant, amount_cents, school_allocation_id=None,
                       set_aside_id=None, incurred_date=None,
                       function_code="INSTRUCTION", supplant_screen=None,
                       description="program cost", as_headers=None):
    resp = api_client.create_expenditure(
        create_expenditure_payload(
            grant["id"], amount_cents,
            incurred_date=incurred_date or funds_period_date(grant),
            function_code=function_code, description=description,
            school_allocation_id=school_allocation_id,
            set_aside_id=set_aside_id, supplant_screen=supplant_screen),
        as_headers or ANALYST,
    )
    return _ok("create_expenditure", resp)


def review_expenditure(expenditure_id, decision, disallow_reason=None,
                       review_note=None, as_headers=None):
    payload = {"decision": decision}
    if disallow_reason is not None:
        payload["disallow_reason"] = disallow_reason
    if review_note is not None:
        payload["review_note"] = review_note
    resp = api_client.review_expenditure(expenditure_id, payload,
                                         as_headers or DIRECTOR)
    return _ok("review_expenditure", resp)


def allow_expenditure(expenditure_id, as_headers=None):
    return review_expenditure(expenditure_id, "ALLOW",
                              as_headers=as_headers or DIRECTOR)


def disallow_expenditure(expenditure_id,
                         disallow_reason="UNALLOWABLE_COST",
                         review_note="not an allowable cost",
                         as_headers=None):
    return review_expenditure(expenditure_id, "DISALLOW",
                              disallow_reason=disallow_reason,
                              review_note=review_note,
                              as_headers=as_headers or DIRECTOR)


def reclassify_expenditure(expenditure_id,
                           fund_source="NON_TITLE_I_STATE", as_headers=None):
    resp = api_client.reclassify_expenditure(
        expenditure_id, {"reclassified_to_fund_source": fund_source},
        as_headers or ANALYST)
    return _ok("reclassify_expenditure", resp)


def create_sns(allocation_id, methodology="PER_PUPIL_FORMULA",
               coverage_start_date="2026-07-01",
               coverage_end_date="2027-07-01", narrative=SNS_NARRATIVE,
               as_headers=None):
    resp = api_client.create_sns_document(
        create_sns_payload(allocation_id, methodology=methodology,
                           coverage_start_date=coverage_start_date,
                           coverage_end_date=coverage_end_date,
                           narrative=narrative),
        as_headers or ANALYST,
    )
    return _ok("create_sns_document", resp)


def submit_sns(doc_id, as_headers=None):
    resp = api_client.submit_sns_document(doc_id, as_headers or ANALYST)
    return _ok("submit_sns_document", resp)


def review_sns(doc_id, decision, review_note=None, as_headers=None):
    payload = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    resp = api_client.review_sns_document(doc_id, payload,
                                          as_headers or DIRECTOR)
    return _ok("review_sns_document", resp)


def setup_accepted_sns(allocation_id, **kwargs):
    """Create + submit (analyst) + ACCEPT (director) an SNS document.
    Distinct operator ids keep the segregation-of-duties rule satisfied."""
    doc = create_sns(allocation_id, **kwargs)
    submit_sns(doc["id"])
    return review_sns(doc["id"], "ACCEPT")


def open_consultation(grant_id, private_school_id, as_headers=None):
    resp = api_client.create_consultation(
        create_consultation_payload(grant_id, private_school_id),
        as_headers or ANALYST,
    )
    return _ok("create_consultation", resp)


def record_session(consultation_id, session_date="2026-08-01",
                   topics="needs assessment", attendee_count=3,
                   as_headers=None):
    resp = api_client.record_session(
        consultation_id,
        record_session_payload(session_date=session_date, topics=topics,
                               attendee_count=attendee_count),
        as_headers or ANALYST,
    )
    return _ok("record_session", resp)


def sign_affirmation(consultation_id, agreed_low_income_count,
                     as_headers=None):
    resp = api_client.sign_affirmation(
        consultation_id,
        {"agreed_low_income_count": agreed_low_income_count},
        as_headers or OMBUDSMAN,
    )
    return _ok("sign_affirmation", resp)


def setup_signed_consultation(grant_id, private_school_id,
                              agreed_low_income_count):
    """Open consultation + two sessions + signed affirmation (PRD §3.6
    requires at least two logged sessions before signing)."""
    consultation = open_consultation(grant_id, private_school_id)
    record_session(consultation["id"], topics="needs assessment")
    record_session(consultation["id"], topics="proportionate share")
    return sign_affirmation(consultation["id"], agreed_low_income_count)


def schedule_visit(grant_id, visit_start_date="2026-08-01",
                   visit_end_date="2026-08-05", scope="PROGRAMMATIC",
                   as_headers=None):
    resp = api_client.create_visit(
        create_visit_payload(grant_id,
                             visit_start_date=visit_start_date,
                             visit_end_date=visit_end_date, scope=scope),
        as_headers or MONITOR,
    )
    return _ok("create_visit", resp)


def start_visit(visit_id, as_headers=None):
    resp = api_client.start_visit(visit_id, as_headers or MONITOR)
    return _ok("start_visit", resp)


def issue_report(visit_id, as_headers=None):
    resp = api_client.issue_report(visit_id, as_headers or MONITOR)
    return _ok("issue_report", resp)


def setup_visit_in_progress(grant_id, visit_start_date="2026-08-01",
                            visit_end_date="2026-08-05",
                            scope="PROGRAMMATIC"):
    """Visit scheduled and started (default clock 2026-08-01 must fall
    inside the window, PRD §3.9)."""
    visit = schedule_visit(grant_id, visit_start_date, visit_end_date, scope)
    return start_visit(visit["id"])


def record_finding(visit_id, citation="34 CFR 200.77", severity="FINDING",
                   description="ranking documentation incomplete",
                   cap_due_date="2026-08-10", as_headers=None):
    resp = api_client.create_finding(
        create_finding_payload(visit_id, citation=citation, severity=severity,
                               description=description,
                               cap_due_date=cap_due_date),
        as_headers or MONITOR,
    )
    return _ok("create_finding", resp)


def submit_cap(finding_id, cap_narrative=CAP_NARRATIVE, as_headers=None):
    resp = api_client.submit_cap(finding_id, {"cap_narrative": cap_narrative},
                                 as_headers or ANALYST)
    return _ok("submit_cap", resp)


def return_cap(finding_id, return_note="insufficient evidence attached",
               as_headers=None):
    resp = api_client.return_cap(finding_id, {"return_note": return_note},
                                 as_headers or MONITOR)
    return _ok("return_cap", resp)


def accept_cap(finding_id, as_headers=None):
    resp = api_client.accept_cap(finding_id, as_headers or MONITOR)
    return _ok("accept_cap", resp)


def set_clock(to_iso8601, as_headers=None):
    resp = api_client.set_current_utc({"to_iso8601": to_iso8601},
                                      as_headers or DIRECTOR)
    return _ok("set_current_utc", resp)


def draft_amendment(grant_id, lines, as_headers=None):
    """Create a DRAFT amendment, reading the grant version fresh for the
    optimistic-concurrency field (PRD §2.7)."""
    grant = get_grant(grant_id)
    resp = api_client.create_amendment(
        create_amendment_payload(grant_id, grant["version"], lines),
        as_headers or ANALYST,
    )
    return _ok("create_amendment", resp)


def submit_amendment(amendment_id, as_headers=None):
    resp = api_client.submit_amendment(amendment_id, as_headers or ANALYST)
    return _ok("submit_amendment", resp)


def approve_amendment(amendment_id, as_headers=None):
    resp = api_client.approve_amendment(amendment_id, {},
                                        as_headers or DIRECTOR)
    return _ok("approve_amendment", resp)


def reject_amendment(amendment_id, decision_note, as_headers=None):
    resp = api_client.reject_amendment(amendment_id,
                                       {"decision_note": decision_note},
                                       as_headers or DIRECTOR)
    return _ok("reject_amendment", resp)


def void_amendment(amendment_id, as_headers=None):
    resp = api_client.void_amendment(amendment_id, {}, as_headers or DIRECTOR)
    return _ok("void_amendment", resp)


# ---------------------------------------------------------------------------
# Tier 4 — the four-school equitable-services signature scenario
# ---------------------------------------------------------------------------
#
# Four schools at 400/500, 300/500, 200/500, 195/500 and two verified private
# schools with resident counts 50 and 30, on a grant of total 100,000,000 with
# a 5,000,000 administrative reserve. Under PRD §3.3/§3.4 arithmetic this
# yields deterministic figures the tests assert verbatim:
#   net_allocable = 95,000,000; PE min 1,000,000; HOMELESS min 500,000;
#   PD min 4,750,000; residual base P = 88,750,000.
#   VERIFIED_COUNT (LIp = 80):  EQUITABLE_SERVICES min 6,042,553,
#                               school pool 82,707,447.
#   CONSULTATION_AGREED with signed 55 + 30 (LIp = 85): EQ min 6,393,008.
# School rows under VERIFIED_COUNT:
#   S1 8000bp MUST_SERVE rank 1 per-pupil 87,367 amount 34,946,768
#   S2 6000bp ELIGIBLE   rank 2 per-pupil 72,806 amount 21,841,768
#   S3 4000bp ELIGIBLE   rank 3 per-pupil 72,806 amount 14,561,168
#   S4 3900bp ELIGIBLE   rank 4 per-pupil 58,245 amount 11,357,743

EQUITABLE_SCENARIO_COUNTS = ((400, 500), (300, 500), (200, 500), (195, 500))
PRIVATE_RESIDENT_COUNTS = (50, 30)

EQ_MIN_VERIFIED = 6_042_553
EQ_MIN_AGREED_55_30 = 6_393_008
SCHOOL_POOL_VERIFIED = 82_707_447
ALLOC_AMOUNTS_VERIFIED = (34_946_768, 21_841_768, 14_561_168, 11_357_743)
PER_PUPIL_VERIFIED = (87_367, 72_806, 72_806, 58_245)
PD_MINIMUM_VERIFIED = 4_750_000
PE_MINIMUM_OVER_THRESHOLD = 1_000_000
HOMELESS_MINIMUM = 500_000


def setup_equitable_scenario(fiscal_year=2027,
                             total_allocation_cents=100_000_000,
                             admin_reserve_cents=5_000_000,
                             equitable_count_method="VERIFIED_COUNT",
                             signed_agreed_counts=None,
                             include_fifth_school=False,
                             registry=None):
    """The four-school + two-private-school scenario through ALLOCATED.

    signed_agreed_counts: when the grant's count method is
    CONSULTATION_AGREED, a list with one agreed count per registered private
    school; each consultation is signed before finalization (PRD §3.3 gate).
    registry: an earlier scenario's context — reuse its schools and private
    schools instead of registering duplicates (two grants may share them).
    """
    if registry is None:
        counts = list(EQUITABLE_SCENARIO_COUNTS)
        if include_fifth_school:
            counts.append((100, 500))
        schools = [
            register_school(name, nces)
            for name, nces in zip(
                ("Alpha Elementary", "Beta Middle", "Gamma High",
                 "Delta Elementary", "Epsilon Prep")[:len(counts)],
                ("000001", "000002", "000003", "000004", "000005"),
            )
        ]
        private_schools = [
            register_private_school("St Mary", 50, "om@stmary.example"),
            register_private_school("Grace Academy", 30, "om@grace.example"),
        ]
    else:
        schools = registry["schools"]
        private_schools = registry["private_schools"]
        counts = registry["counts"]

    grant = open_grant(
        fiscal_year, total_allocation_cents,
        admin_reserve_cents=admin_reserve_cents,
        equitable_count_method=equitable_count_method)
    entries = [
        snapshot_entry(s["id"], li, tot)
        for s, (li, tot) in zip(schools, counts)
    ]
    snapshot = create_snapshot(grant["id"], entries,
                               measure=grant["poverty_measure"])
    certify_snapshot(snapshot["id"], grant["id"])

    consultations = []
    if signed_agreed_counts is not None:
        for ps, agreed in zip(private_schools, signed_agreed_counts):
            consultations.append(
                setup_signed_consultation(grant["id"], ps["id"], agreed))

    lock_rankings(grant["id"])
    finalize_allocations(grant["id"])
    return {
        "grant": get_grant(grant["id"]),
        "schools": schools,
        "counts": counts,
        "private_schools": private_schools,
        "snapshot": snapshot,
        "consultations": consultations,
        "allocations": {
            s["id"]: get_allocation_for(grant["id"], s["id"])
            for s in schools
        },
        "set_asides": {
            row["category"]: row for row in list_set_asides_for(grant["id"])
        },
    }
