"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup failed" errors instead of confusing assertion failures. The test harness
restarts the server with an empty database before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client


def _today_date():
    """Current wall-clock UTC date as YYYY-MM-DD (matches the server's updated_at date)."""
    return datetime.now(timezone.utc).date().isoformat()


def _far_future_date():
    """A date comfortably after today's wall-clock date, used as a wide invoice
    period_end so just-completed encounters (dated at wall-clock today) are inside it."""
    return (datetime.now(timezone.utc).date() + timedelta(days=3650)).isoformat()
from .factories import (
    create_employer_payload, create_protocol_payload, panel, create_worker_payload,
    create_encounter_payload, create_drug_screen_payload, create_custody_event_payload,
    create_injury_case_payload, create_work_status_payload, create_surveillance_exam_payload,
    create_clearance_payload, create_invoice_payload, set_clock_payload,
)
from .test_users import (
    TEST_USERS, make_clinician_headers, make_mro_headers, make_collector_headers,
    DEFAULT_CLINICIAN_ID, DEFAULT_MRO_ID,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
COLLECTOR = TEST_USERS["collector_headers"]

# A clock anchor that sits at or after every fixture/factory injury_date so the
# PRD §3.7 precondition ("injury_date must be on or before the employer's
# current_date") is satisfied. The factory default injury_date is 2026-01-02 and
# tests place injury/work-status dates through early 2026; this anchor is later
# than all of them. INJURY encounters are scheduled against an employer whose
# current_date is set to this value so the subsequent injury-case creation is
# accepted. (Encounter scheduling itself imposes no injury_date constraint.)
INJURY_CLOCK_ANCHOR = "2026-12-31"


# ─── Tier 1: Employer + active protocol ───────────────

def create_employer(legal_name="Test Co", mro_user_id="mro-1", dot_regulated=None,
                    net_terms_days=None, current_date=None):
    """Create a PROSPECT employer. Returns the employer dict."""
    overrides = {"legal_name": legal_name, "mro_user_id": mro_user_id}
    if dot_regulated is not None:
        overrides["dot_regulated"] = dot_regulated
    if net_terms_days is not None:
        overrides["net_terms_days"] = net_terms_days
    if current_date is not None:
        overrides["current_date"] = current_date
    return get_success_data(api_client.create_employer(create_employer_payload(**overrides), ADMIN))


def create_draft_protocol(employer_id, panels, effective_date="2026-01-01"):
    """Create a DRAFT protocol with the given panels. Returns the protocol dict."""
    return get_success_data(api_client.create_protocol(
        create_protocol_payload(employer_id, panels, effective_date=effective_date), ADMIN))


def setup_employer_with_active_protocol(panels=None, mro_user_id="mro-1", dot_regulated=None,
                                        net_terms_days=None, current_date=None,
                                        legal_name="Test Co"):
    """Create an employer, draft a protocol with `panels`, activate it (employer -> ACTIVE).
    Returns (employer_after_activation, protocol). The employer dict reflects post-activation
    state (account_status ACTIVE, version bumped)."""
    if panels is None:
        panels = [panel("PHYSICAL", "OP", 9000, 0)]
    emp = create_employer(legal_name=legal_name, mro_user_id=mro_user_id,
                          dot_regulated=dot_regulated, net_terms_days=net_terms_days,
                          current_date=current_date)
    proto = create_draft_protocol(emp["id"], panels)
    activate_res = api_client.activate_protocol(
        proto["id"], {"expected_employer_version": emp["version"]}, ADMIN)
    proto = get_success_data(activate_res)
    emp = get_success_data(api_client.get_employer(emp["id"], ADMIN))
    return emp, proto


def create_worker(employer_id, job_category="OP", full_name="Test Worker", dob="1990-01-01"):
    """Create a worker under an employer. Returns the worker dict."""
    return get_success_data(api_client.create_worker(
        create_worker_payload(employer_id, job_category=job_category,
                              full_name=full_name, dob=dob), ADMIN))


# ─── Tier 2: Scheduled / checked-in encounters ────────

def schedule_encounter(employer_id, worker_id, encounter_type, panel_code=None,
                       clinician_id=DEFAULT_CLINICIAN_ID):
    """Schedule an encounter (status SCHEDULED). Returns the encounter dict."""
    overrides = {}
    if panel_code is not None:
        overrides["panel_code"] = panel_code
    return get_success_data(api_client.create_encounter(
        create_encounter_payload(employer_id, worker_id, encounter_type, **overrides),
        make_clinician_headers(clinician_id)))


def schedule_and_checkin_encounter(employer_id, worker_id, encounter_type, panel_code=None,
                                   clinician_id=DEFAULT_CLINICIAN_ID):
    """Schedule then check in an encounter (status IN_PROGRESS). Returns the encounter dict."""
    enc = schedule_encounter(employer_id, worker_id, encounter_type, panel_code, clinician_id)
    enc = get_success_data(api_client.check_in_encounter(enc["id"], make_clinician_headers(clinician_id)))
    return enc


def setup_checked_in_encounter(encounter_type="PHYSICAL", panel_code="PHYSICAL",
                               job_category="OP", panels=None, clinician_id=DEFAULT_CLINICIAN_ID,
                               mro_user_id="mro-1", dot_regulated=None, current_date=None,
                               price_cents=9000):
    """Active employer + worker + a checked-in (IN_PROGRESS) encounter of the given type.
    Returns (employer, worker, encounter). For INJURY pass panel_code=None."""
    if panels is None:
        pc = panel_code if panel_code is not None else "PHYSICAL"
        panels = [panel(pc, job_category, price_cents, 0)]
    # An INJURY encounter is followed by injury-case creation whose injury_date
    # (factory default 2026-01-02) must be on or before the employer's current_date
    # (PRD §3.7). Anchor the clock late enough to satisfy that precondition unless
    # the caller pinned a specific current_date.
    if current_date is None and encounter_type == "INJURY":
        current_date = INJURY_CLOCK_ANCHOR
    emp, _ = setup_employer_with_active_protocol(
        panels=panels, mro_user_id=mro_user_id, dot_regulated=dot_regulated,
        current_date=current_date)
    wkr = create_worker(emp["id"], job_category=job_category)
    enc = schedule_and_checkin_encounter(emp["id"], wkr["id"], encounter_type, panel_code, clinician_id)
    return emp, wkr, enc


# ─── Tier 3: Drug-screen pipeline shortcuts ───────────

def setup_drug_screen(specimen_seal_intact=True, panel_code="DRUG_NON_DOT",
                      job_category="PACKER", mro_user_id="mro-1", dot_regulated=None,
                      clinician_id=DEFAULT_CLINICIAN_ID, price_cents=8000):
    """Active employer + worker + checked-in DRUG_SCREEN encounter + created DrugScreen
    (status AWAITING_COLLECTION, encounter PENDING_RESULTS).
    Returns (employer, worker, encounter, drug_screen)."""
    emp, wkr, enc = setup_checked_in_encounter(
        encounter_type="DRUG_SCREEN", panel_code=panel_code, job_category=job_category,
        mro_user_id=mro_user_id, dot_regulated=dot_regulated, clinician_id=clinician_id,
        price_cents=price_cents)
    ds = get_success_data(api_client.create_drug_screen(
        create_drug_screen_payload(enc["id"], specimen_seal_intact=specimen_seal_intact),
        make_clinician_headers(clinician_id)))
    return emp, wkr, enc, ds


def advance_drug_screen_to_at_lab(drug_screen_id):
    """Append COLLECT then LAB_RECEIVE custody events; screen ends AT_LAB."""
    get_success_data(api_client.create_custody_event(
        create_custody_event_payload(drug_screen_id, "COLLECT"), COLLECTOR))
    get_success_data(api_client.create_custody_event(
        create_custody_event_payload(drug_screen_id, "LAB_RECEIVE"), COLLECTOR))


def advance_drug_screen_to_lab_reported(drug_screen_id, lab_result="NEGATIVE",
                                        clinician_id=DEFAULT_CLINICIAN_ID):
    """Take an AT_LAB screen (after advance_drug_screen_to_at_lab) to LAB_REPORTED."""
    return get_success_data(api_client.record_lab_result(
        drug_screen_id, {"lab_result": lab_result}, make_clinician_headers(clinician_id)))


def advance_drug_screen_to_mro_review(drug_screen_id, mro_user_id="mro-1"):
    """Take a LAB_REPORTED screen to MRO_REVIEW (MRO receive)."""
    return get_success_data(api_client.mro_receive(drug_screen_id, make_mro_headers(mro_user_id)))


def setup_drug_screen_at_lab_reported(lab_result="NEGATIVE", specimen_seal_intact=True,
                                      mro_user_id="mro-1", clinician_id=DEFAULT_CLINICIAN_ID):
    """Full pipeline to LAB_REPORTED. Returns (employer, worker, encounter, drug_screen)."""
    emp, wkr, enc, ds = setup_drug_screen(
        specimen_seal_intact=specimen_seal_intact, mro_user_id=mro_user_id, clinician_id=clinician_id)
    advance_drug_screen_to_at_lab(ds["id"])
    advance_drug_screen_to_lab_reported(ds["id"], lab_result=lab_result, clinician_id=clinician_id)
    return emp, wkr, enc, ds


def setup_drug_screen_at_mro_review(lab_result="NEGATIVE", specimen_seal_intact=True,
                                    mro_user_id="mro-1", clinician_id=DEFAULT_CLINICIAN_ID):
    """Full pipeline to MRO_REVIEW. Returns (employer, worker, encounter, drug_screen)."""
    emp, wkr, enc, ds = setup_drug_screen_at_lab_reported(
        lab_result=lab_result, specimen_seal_intact=specimen_seal_intact,
        mro_user_id=mro_user_id, clinician_id=clinician_id)
    advance_drug_screen_to_mro_review(ds["id"], mro_user_id=mro_user_id)
    return emp, wkr, enc, ds


def setup_drug_screen_at_collected(specimen_seal_intact=True, mro_user_id="mro-1",
                                   clinician_id=DEFAULT_CLINICIAN_ID):
    """Full pipeline to COLLECTED (one COLLECT custody event).
    Returns (employer, worker, encounter, drug_screen)."""
    emp, wkr, enc, ds = setup_drug_screen(
        specimen_seal_intact=specimen_seal_intact, mro_user_id=mro_user_id, clinician_id=clinician_id)
    get_success_data(api_client.create_custody_event(
        create_custody_event_payload(ds["id"], "COLLECT"), COLLECTOR))
    return emp, wkr, enc, ds


# ─── Tier 4: Injury / work-status shortcuts ───────────

def setup_injury_case(treatment_level="MEDICAL_TREATMENT", days_away=0, days_restricted=0,
                      injury_date="2026-01-02", current_date=None, clinician_id=DEFAULT_CLINICIAN_ID):
    """Active employer + worker + checked-in INJURY encounter + created InjuryCase (OPEN).
    Returns (employer, worker, encounter, injury_case)."""
    emp, wkr, enc = setup_checked_in_encounter(
        encounter_type="INJURY", panel_code=None, job_category="OP",
        panels=[panel("PHYSICAL", "OP", 9000, 0)], current_date=current_date,
        clinician_id=clinician_id)
    ic = get_success_data(api_client.create_injury_case(
        create_injury_case_payload(enc["id"], treatment_level, injury_date=injury_date,
                                   days_away=days_away, days_restricted=days_restricted),
        make_clinician_headers(clinician_id)))
    return emp, wkr, enc, ic


def add_work_status(injury_case_id, disposition, valid_from, valid_to, restriction_text=None,
                    clinician_id=DEFAULT_CLINICIAN_ID):
    """Add a work-status note. Returns the WorkStatus dict."""
    overrides = {}
    if restriction_text is not None:
        overrides["restriction_text"] = restriction_text
    return get_success_data(api_client.create_work_status(
        create_work_status_payload(injury_case_id, disposition, valid_from, valid_to, **overrides),
        make_clinician_headers(clinician_id)))


# ─── Tier 5: Surveillance shortcuts ───────────────────

def setup_surveillance_exam(panel_code="AUDIOMETRIC", job_category="MACHINIST",
                            exam_overrides=None, current_date="2026-06-01",
                            recheck_interval_days=365, price_cents=5000,
                            clinician_id=DEFAULT_CLINICIAN_ID):
    """Active employer + worker + checked-in SURVEILLANCE encounter + created exam (SCHEDULED).
    Returns (employer, worker, encounter, exam)."""
    panels = [panel(panel_code, job_category, price_cents, recheck_interval_days)]
    emp, wkr, enc = setup_checked_in_encounter(
        encounter_type="SURVEILLANCE", panel_code=panel_code, job_category=job_category,
        panels=panels, current_date=current_date, clinician_id=clinician_id, price_cents=price_cents)
    ex = get_success_data(api_client.create_surveillance_exam(
        create_surveillance_exam_payload(enc["id"], **(exam_overrides or {})),
        make_clinician_headers(clinician_id)))
    return emp, wkr, enc, ex


# ─── Tier 6: Clearance + completion shortcuts ─────────

def issue_clearance(encounter_id, determination="FIT", restriction_text=None,
                    clinician_id=DEFAULT_CLINICIAN_ID):
    """Issue a clearance for an encounter. Returns the Clearance dict."""
    overrides = {}
    if restriction_text is not None:
        overrides["restriction_text"] = restriction_text
    return get_success_data(api_client.create_clearance(
        create_clearance_payload(encounter_id, determination, **overrides),
        make_clinician_headers(clinician_id)))


def complete_physical_encounter(employer_id=None, worker_id=None, encounter=None,
                                determination="FIT", price_cents=9000, current_date=None,
                                job_category="OP", clinician_id=DEFAULT_CLINICIAN_ID):
    """End-to-end: active employer + worker + checked-in PHYSICAL encounter + clearance +
    complete. Returns (employer, worker, completed_encounter, clearance)."""
    emp, wkr, enc = setup_checked_in_encounter(
        encounter_type="PHYSICAL", panel_code="PHYSICAL", job_category=job_category,
        price_cents=price_cents, current_date=current_date, clinician_id=clinician_id)
    clr = issue_clearance(enc["id"], determination=determination, clinician_id=clinician_id)
    enc = get_success_data(api_client.complete_encounter(enc["id"], make_clinician_headers(clinician_id)))
    return emp, wkr, enc, clr


def create_completed_physical_for_employer(employer_id, worker_id, price_cents=9000,
                                           clinician_id=DEFAULT_CLINICIAN_ID,
                                           panel_code="PHYSICAL"):
    """Schedule + check-in + clear + complete one PHYSICAL encounter for an EXISTING active
    employer + worker. Returns the completed encounter dict. Used to accumulate billable
    encounters for invoice line-item tests."""
    enc = schedule_and_checkin_encounter(employer_id, worker_id, "PHYSICAL", panel_code, clinician_id)
    issue_clearance(enc["id"], "FIT", clinician_id=clinician_id)
    return get_success_data(api_client.complete_encounter(enc["id"], make_clinician_headers(clinician_id)))


def setup_employer_with_n_completed_physicals(n, price_cents=10000, current_date="2026-03-15",
                                              job_category="OP"):
    """Active employer + worker + N completed PHYSICAL encounters (each FIT, billable price_cents).
    All completions occur at the employer's current_date so they fall in the same billing period.
    Returns (employer, worker, [encounters])."""
    emp, _ = setup_employer_with_active_protocol(
        panels=[panel("PHYSICAL", job_category, price_cents, 0)],
        current_date=current_date)
    wkr = create_worker(emp["id"], job_category=job_category)
    encounters = []
    for _ in range(n):
        encounters.append(create_completed_physical_for_employer(
            emp["id"], wkr["id"], price_cents=price_cents))
    emp = get_success_data(api_client.get_employer(emp["id"], ADMIN))
    return emp, wkr, encounters


# ─── Tier 7: Invoice shortcuts ────────────────────────

def create_draft_invoice(employer_id, period_start=None, period_end=None):
    """Create a DRAFT invoice (auto-selects line items, computes totals). Returns the invoice.

    Line-item selection keys on each encounter's completion date — the date portion
    of its `updated_at` at the moment it completed (PRD §3.13) — which is the
    server's wall-clock time (PRD §2.4 defines `updated_at` as the real-time
    last-modified timestamp, not the employer's deterministic clock). Encounters
    completed during the test therefore land at wall-clock "today", so the default
    billing period is a wide window that brackets the current wall-clock date,
    ensuring every just-completed billable encounter falls inside it."""
    if period_start is None:
        period_start = "1970-01-01"
    if period_end is None:
        period_end = _far_future_date()
    return get_success_data(api_client.create_invoice(
        create_invoice_payload(employer_id, period_start, period_end), ADMIN))


def issue_invoice(invoice_id, employer_id):
    """Re-read the employer's current version, then issue the DRAFT invoice. Returns the invoice."""
    emp = get_success_data(api_client.get_employer(employer_id, ADMIN))
    return get_success_data(api_client.issue_invoice(
        invoice_id, {"expected_employer_version": emp["version"]}, ADMIN))


def setup_issued_invoice(price_cents=9000, current_date="2026-03-15", net_terms_days=None):
    """Active employer + one completed PHYSICAL + a DRAFT invoice issued.
    Returns (employer, worker, encounter, invoice). The invoice is ISSUED with total price_cents."""
    emp, _ = setup_employer_with_active_protocol(
        panels=[panel("PHYSICAL", "OP", price_cents, 0)],
        current_date=current_date, net_terms_days=net_terms_days)
    wkr = create_worker(emp["id"], job_category="OP")
    enc = create_completed_physical_for_employer(emp["id"], wkr["id"], price_cents=price_cents)
    inv = create_draft_invoice(emp["id"])
    inv = issue_invoice(inv["id"], emp["id"])
    emp = get_success_data(api_client.get_employer(emp["id"], ADMIN))
    return emp, wkr, enc, inv


def set_clock(employer_id, to_iso8601):
    """Advance the employer clock. Returns the updated employer dict."""
    return get_success_data(api_client.set_clock(set_clock_payload(employer_id, to_iso8601), ADMIN))


def complete_surveillance_encounter_for_employer(employer_id, worker_id, panel_code="AUDIOMETRIC",
                                                 exam_overrides=None, clinician_id=DEFAULT_CLINICIAN_ID):
    """For an EXISTING active employer + worker: schedule + check-in a SURVEILLANCE encounter,
    create + record + finalize the exam, issue a FIT clearance, and complete the encounter.
    Returns (encounter, exam). Used to seed a prior FINALIZED exam for recheck-window tests."""
    enc = schedule_and_checkin_encounter(employer_id, worker_id, "SURVEILLANCE", panel_code, clinician_id)
    ex = get_success_data(api_client.create_surveillance_exam(
        create_surveillance_exam_payload(enc["id"], **(exam_overrides or {})),
        make_clinician_headers(clinician_id)))
    get_success_data(api_client.record_surveillance_exam(ex["id"], make_clinician_headers(clinician_id)))
    ex = get_success_data(api_client.finalize_surveillance_exam(ex["id"], make_clinician_headers(clinician_id)))
    issue_clearance(enc["id"], "FIT", clinician_id=clinician_id)
    enc = get_success_data(api_client.complete_encounter(enc["id"], make_clinician_headers(clinician_id)))
    return enc, ex
