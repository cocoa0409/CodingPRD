"""Composite setup helpers.

Each test runs against a freshly-restarted, empty server, so every fixture
builds all of its preconditions from scratch using only PRD-declared endpoints.

Identity threading: the four entity-backed roles (IntakeScreener, Investigator,
Caseworker, LicensingWorker) must act under the id of the actual Caseworker row
they correspond to. The Workers tier creates those rows and every downstream
helper threads their ids into make_<role>_headers(...). The shared TEST_USERS
constants are NEVER used for ownership-gated writes here.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_caseworker_payload,
    create_referral_payload,
    decision_payload,
    create_case_payload,
    create_child_payload,
    create_foster_home_payload,
    create_screening_payload,
    create_placement_payload,
    license_payload,
    create_case_plan_payload,
    objectives_payload,
    create_visitation_payload,
    create_hearing_payload,
    hold_payload,
)
from .test_users import (
    make_admin_headers,
    make_judge_headers,
    make_screener_headers,
    make_investigator_headers,
    make_caseworker_headers,
    make_licensing_headers,
)

# Removal-grade safety factors: NO_FOOD(25)+MEDICAL_NEGLECT(28)+DRUG_ENV(22)+
# UNSAFE_SLEEP(18) = 93, no override factor -> UNSAFE / removal_recommended.
REMOVAL_FACTORS = ["NO_FOOD", "MEDICAL_NEGLECT", "DRUG_ENV", "UNSAFE_SLEEP"]

ADMIN = make_admin_headers()
JUDGE = make_judge_headers()

_DEFAULT_CLOCK = "2026-01-01T00:00:00Z"

# Unique-email generator so concurrent caseworker creates never collide within a
# single test's setup.
_email_seq = itertools.count(1)


def _email(tag: str) -> str:
    return f"{tag}-{next(_email_seq)}@x.gov"


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Fix the logical system UTC clock."""
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# --------------------------------------------------------------------------
# Tier 0: Workers — the four segregated-duty Caseworker rows + their headers.
# --------------------------------------------------------------------------
class Workers:
    """Bundle of the four entity-backed worker ids and their ownership headers."""

    def __init__(self, screener_id, investigator_id, caseworker_id, licensing_id):
        self.screener_id = screener_id
        self.investigator_id = investigator_id
        self.caseworker_id = caseworker_id
        self.licensing_id = licensing_id
        self.screener = make_screener_headers(screener_id)
        self.investigator = make_investigator_headers(investigator_id)
        self.caseworker = make_caseworker_headers(caseworker_id)
        self.licensing = make_licensing_headers(licensing_id)


def setup_workers(need_licensing: bool = True) -> Workers:
    """Register a SCREENER, INVESTIGATOR, CASEWORKER and (optionally) LICENSING."""
    scr = get_success_data(api_client.create_caseworker(
        create_caseworker_payload("SCREENER", full_name="Sara Screener", email=_email("scr")), ADMIN))
    inv = get_success_data(api_client.create_caseworker(
        create_caseworker_payload("INVESTIGATOR", full_name="Ivan Investigator", email=_email("inv")), ADMIN))
    cw = get_success_data(api_client.create_caseworker(
        create_caseworker_payload("CASEWORKER", full_name="Cara Caseworker", email=_email("cw")), ADMIN))
    lic_id = None
    if need_licensing:
        lic = get_success_data(api_client.create_caseworker(
            create_caseworker_payload("LICENSING", full_name="Lara Licensing", email=_email("lic")), ADMIN))
        lic_id = lic["id"]
    return Workers(scr["id"], inv["id"], cw["id"], lic_id)


# --------------------------------------------------------------------------
# Tier 1: State progression on the intake/investigation spine.
# --------------------------------------------------------------------------
def create_screened_in_referral(workers: Workers, **referral_overrides):
    """Create a referral and screen it IN. Returns the screened referral dict.

    Default factors yield score 73 (>= 45) -> SCREENED_IN.
    """
    ref = get_success_data(api_client.create_referral(
        create_referral_payload(**referral_overrides), workers.screener))
    screened = get_success_data(api_client.screen_referral(ref["id"], workers.screener))
    return screened


def create_investigation_in_progress(workers: Workers, **referral_overrides):
    """Screened-in referral -> ASSIGNED investigation -> IN_PROGRESS. Returns investigation."""
    ref = create_screened_in_referral(workers, **referral_overrides)
    inv = get_success_data(api_client.create_investigation(
        {"referral_id": ref["id"], "investigator_id": workers.investigator_id}, workers.caseworker))
    started = get_success_data(api_client.start_investigation(inv["id"], workers.investigator))
    return started


def decide_investigation(workers: Workers, investigation_id, safety_factors, protective_capacity):
    """Record a safety decision on an IN_PROGRESS investigation. Returns investigation."""
    return get_success_data(api_client.decide_investigation(
        investigation_id, decision_payload(safety_factors, protective_capacity), workers.investigator))


def create_removal_investigation(workers: Workers, **referral_overrides):
    """Screened-in referral driven all the way to an UNSAFE decision. Returns investigation."""
    inv = create_investigation_in_progress(workers, **referral_overrides)
    return decide_investigation(workers, inv["id"], REMOVAL_FACTORS, 0)


# --------------------------------------------------------------------------
# Tier 2: Case + child hierarchy.
# --------------------------------------------------------------------------
def open_case_with_child(workers: Workers, dob="2016-01-01T00:00:00Z",
                         alleged_maltreatment="PHYSICAL_ABUSE", child_name="Test Child"):
    """Full spine: screen IN -> investigate UNSAFE -> open Case -> register Child.

    Returns (case, child). Case is OPEN, child IN_HOME (not yet placed).
    """
    inv = create_removal_investigation(workers, alleged_maltreatment=alleged_maltreatment)
    case = get_success_data(api_client.create_case(
        create_case_payload(inv["id"]), workers.caseworker))
    child = get_success_data(api_client.create_child(
        create_child_payload(case["id"], full_name=child_name, date_of_birth=dob), workers.caseworker))
    return case, child


# --------------------------------------------------------------------------
# Tier 1b: Foster-home licensing.
# --------------------------------------------------------------------------
def create_licensed_home(workers: Workers, bed_capacity=1, max_age_years=18,
                         accepts_maltreatment=("PHYSICAL_ABUSE",), member_name="Foster Parent"):
    """Register a home, add one CLEARED screening, issue a full license.

    Returns the home dict as returned by /license (license_status LICENSED,
    version reflecting create + screening-add + resolve + license bumps).
    """
    home = get_success_data(api_client.create_foster_home(
        create_foster_home_payload(
            workers.licensing_id, bed_capacity=bed_capacity, max_age_years=max_age_years,
            accepts_maltreatment=list(accepts_maltreatment)), workers.licensing))
    scr = get_success_data(api_client.create_screening(
        create_screening_payload(home["id"], member_name=member_name), workers.licensing))
    get_success_data(api_client.resolve_screening(scr["id"], workers.licensing))
    # Adding and clearing a CaregiverScreening each bump the home's version
    # (PRD §2.8), so the create-time version is stale by license time; re-read
    # the home's CURRENT version for the optimistic-concurrency guard.
    licensed = get_success_data(api_client.license_home(
        home["id"], license_payload(current_home_version(workers, home["id"])),
        workers.licensing))
    return licensed


def create_pending_home(workers: Workers, bed_capacity=1, max_age_years=18,
                        accepts_maltreatment=("PHYSICAL_ABUSE",)):
    """Register a home and leave it PENDING (no license). Returns the home dict."""
    return get_success_data(api_client.create_foster_home(
        create_foster_home_payload(
            workers.licensing_id, bed_capacity=bed_capacity, max_age_years=max_age_years,
            accepts_maltreatment=list(accepts_maltreatment)), workers.licensing))


def current_home_version(workers: Workers, home_id) -> int:
    """Read the home's current version (e.g. after a placement bumped it)."""
    home = get_success_data(api_client.get_foster_home(home_id, workers.caseworker))
    return home["version"]


# --------------------------------------------------------------------------
# Tier 3: Placement shortcuts.
# --------------------------------------------------------------------------
def place_child(workers: Workers, child_id, home_id, expected_version):
    """Create a placement. Returns the placement dict."""
    return get_success_data(api_client.create_placement(
        create_placement_payload(child_id, home_id, expected_version), workers.caseworker))


def setup_placed_child(workers: Workers, dob="2016-01-01T00:00:00Z",
                       alleged_maltreatment="PHYSICAL_ABUSE", bed_capacity=1, max_age_years=18):
    """OPEN case + child + licensed home + first placement.

    Returns (case, child, home, placement). After this: child PLACED, case
    IN_PLACEMENT, placement ACTIVE, home active_placement_count == 1.
    """
    case, child = open_case_with_child(workers, dob=dob, alleged_maltreatment=alleged_maltreatment)
    home = create_licensed_home(workers, bed_capacity=bed_capacity, max_age_years=max_age_years,
                                accepts_maltreatment=(alleged_maltreatment,))
    # The license issued by create_licensed_home bumped the home's version, so
    # re-read the CURRENT version for the placement's concurrency guard.
    placement = place_child(workers, child["id"], home["id"],
                            current_home_version(workers, home["id"]))
    return case, child, home, placement


# --------------------------------------------------------------------------
# Tier 4: Hearings + case-plan lifecycle (gates for permanency).
# --------------------------------------------------------------------------
def schedule_and_hold_hearing(workers: Workers, case_id, hearing_type, ruling,
                              scheduled_at=_DEFAULT_CLOCK):
    """Schedule a hearing (clock must already be >= scheduled_at to hold), then hold it
    with the given ruling. Returns the held hearing dict.

    Default scheduled_at == the suite's default clock so the inclusive
    "current clock has reached or passed scheduled_at" hold-gate (PRD §3.9) is
    satisfied. The prior hearing is HELD before the next is scheduled, so a
    same-instant schedule never trips the SCHEDULED-only overlap buffer."""
    hearing = get_success_data(api_client.create_hearing(
        create_hearing_payload(case_id, hearing_type, scheduled_at), workers.caseworker))
    held = get_success_data(api_client.hold_hearing(hearing["id"], hold_payload(ruling), JUDGE))
    return held


def create_active_case_plan(workers: Workers, case_id, objectives_total=5,
                            disposition_at=_DEFAULT_CLOCK):
    """Create a DRAFT plan, hold a DISPOSITION hearing, activate the plan to ACTIVE.
    Returns the activated plan dict."""
    plan = get_success_data(api_client.create_case_plan(
        create_case_plan_payload(case_id, objectives_total=objectives_total), workers.caseworker))
    schedule_and_hold_hearing(workers, case_id, "DISPOSITION", "CONTINUE_PLACEMENT",
                              scheduled_at=disposition_at)
    activated = get_success_data(api_client.activate_case_plan(plan["id"], workers.caseworker))
    return activated


def set_plan_compliance(workers: Workers, plan_id, objectives_met):
    """Update objectives_met (absolute). Returns the plan dict with recomputed compliance_pct."""
    return get_success_data(api_client.update_objectives(
        plan_id, objectives_payload(objectives_met), workers.caseworker))


def create_completed_case_plan(workers: Workers, case_id, objectives_total=5):
    """ACTIVE plan with all objectives met -> COMPLETED. Returns the completed plan dict."""
    plan = create_active_case_plan(workers, case_id, objectives_total=objectives_total)
    set_plan_compliance(workers, plan["id"], objectives_total)
    return get_success_data(api_client.complete_case_plan(plan["id"], workers.caseworker))


# --------------------------------------------------------------------------
# Tier 5: Permanency-planning entry.
# --------------------------------------------------------------------------
def advance_to_permanency_planning(workers: Workers, case_id,
                                   permanency_at=_DEFAULT_CLOCK, ruling="CONTINUE_PLACEMENT"):
    """Hold a PERMANENCY hearing (with the given ruling) and advance the in-placement
    case to PERMANENCY_PLANNING. Returns the advanced case dict."""
    schedule_and_hold_hearing(workers, case_id, "PERMANENCY", ruling, scheduled_at=permanency_at)
    return get_success_data(api_client.advance_permanency(case_id, workers.caseworker))
