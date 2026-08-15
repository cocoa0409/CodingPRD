"""Composite setup helpers.

Most testable claims in this PRD require the system to be in a state that
takes 5-15 API calls to reach (an APPROVED protocol, a cleared personnel
member, a posted billing run, a suspended protocol reached through the
deviation chain). These fixtures encapsulate those preambles so tests can
focus on assertions. Every fixture builds its state from scratch via the
public endpoints — the server is restarted before every test, so each test
starts against an empty database and a logical clock of 2026-08-01T00:00:00Z
(PRD §2.4).

Identity threading: Investigator is an entity-backed role (PRD §2.1). After
creating an Investigator, ownership-gated calls (protocol create / submit /
personnel attach) use make_investigator_headers(investigator["id"]) — never
the shared fallback constant.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ADULT_MOUSE_DOB,
    CLOCK_DEFAULT_ISO,
    DEFAULT_PERIOD_END,
    DEFAULT_PERIOD_START,
    GRANT_EXPIRES_ISO,
    TEST_DEFAULTS,
)
from .factories import (
    create_adverse_event_payload,
    create_animal_payload,
    create_billing_run_payload,
    create_cage_payload,
    create_census_record_payload,
    create_grant_payload,
    create_inspection_payload,
    create_investigator_payload,
    create_litter_payload,
    create_occ_health_enrollment_payload,
    create_personnel_payload,
    create_protocol_deviation_payload,
    create_protocol_payload,
    create_room_booking_payload,
    create_training_enrollment_payload,
    dmr_decision_payload,
    fcr_decision_payload,
)
from .test_users import TEST_USERS, make_investigator_headers

ADMIN = TEST_USERS["admin_headers"]
FACILITY = TEST_USERS["facility_headers"]
BILLING = TEST_USERS["billing_headers"]
TRAINING = TEST_USERS["training_headers"]
OCC_HEALTH = TEST_USERS["occ_health_headers"]
STAFF = TEST_USERS["staff_headers"]
VET = TEST_USERS["vet_headers"]

REQUIRED_COURSES = (
    "ANIMAL_HANDLING",
    "ASEPTIC_TECHNIQUE",
    "EUTHANASIA",
    "SPECIES_SPECIFIC",
)


def _day_iso(offset_days: int, base: str = DEFAULT_PERIOD_START) -> str:
    """Return midnight-UTC ISO for base + offset_days."""
    base_dt = datetime.fromisoformat(base.replace("Z", "+00:00"))
    dt = base_dt + timedelta(days=offset_days)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _period_days(period_start: str, period_end: str) -> list:
    """Midnight-UTC ISO for each calendar day in [period_start, period_end)."""
    start = datetime.fromisoformat(period_start.replace("Z", "+00:00"))
    end = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
    days = []
    d = start
    while d < end:
        days.append(d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        d += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Tier 1: leaf creators and clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Set the logical clock (IacucAdministrator). Returns {current_utc}."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def create_investigator(**overrides) -> dict:
    """Register an investigator (IacucAdministrator). Returns Investigator."""
    return get_success_data(
        api_client.create_investigator(create_investigator_payload(**overrides), ADMIN)
    )


def create_grant_for(investigator_id: str, **overrides) -> dict:
    """Register a grant owned by the investigator (IacucAdministrator)."""
    return get_success_data(
        api_client.create_grant(
            create_grant_payload(investigator_id, **overrides), ADMIN,
        )
    )


def create_personnel_record(**overrides) -> dict:
    """Register a personnel member (IacucAdministrator). Returns Personnel."""
    return get_success_data(
        api_client.create_personnel(create_personnel_payload(**overrides), ADMIN)
    )


def enroll_and_complete_course(personnel_id: str, course_code: str) -> dict:
    """Enroll in one course and mark it completed (TrainingCoordinator)."""
    enrollment = get_success_data(
        api_client.create_training_enrollment(
            create_training_enrollment_payload(personnel_id, course_code=course_code),
            TRAINING,
        )
    )
    return get_success_data(
        api_client.complete_training_enrollment(enrollment["id"], TRAINING)
    )


def clear_occ_health(personnel_id: str) -> dict:
    """Enroll in occupational health and clear it (OccHealthNurse)."""
    enrollment = get_success_data(
        api_client.create_occ_health_enrollment(
            create_occ_health_enrollment_payload(personnel_id), OCC_HEALTH,
        )
    )
    return get_success_data(
        api_client.clear_occ_health_enrollment(enrollment["id"], OCC_HEALTH)
    )


def create_cleared_personnel(**overrides) -> dict:
    """Personnel member with all four required courses COMPLETED and an
    occupational-health enrollment CLEARED — passes both personnel gates
    (PRD §3.2). Returns Personnel."""
    person = create_personnel_record(**overrides)
    for course in REQUIRED_COURSES:
        enroll_and_complete_course(person["id"], course)
    clear_occ_health(person["id"])
    return get_success_data(api_client.get_personnel(person["id"], ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: protocol lifecycle
# ---------------------------------------------------------------------------

def create_draft_protocol(
    species="MOUSE",
    max_animals=TEST_DEFAULTS["MAX_ANIMALS_JUSTIFIED"],
    budget=TEST_DEFAULTS["GRANT_BUDGET_CENTS"],
    review_path="DMR",
    pain_category="C",
    grant_expires=GRANT_EXPIRES_ISO,
) -> dict:
    """Investigator + grant + DRAFT protocol. Returns a dict with the three
    entities plus investigator_headers for ownership-gated follow-up calls."""
    investigator = create_investigator()
    grant = create_grant_for(
        investigator["id"], budget_total_cents=budget, expires_on=grant_expires,
    )
    inv_headers = make_investigator_headers(investigator["id"])
    protocol = get_success_data(
        api_client.create_protocol(
            create_protocol_payload(
                investigator["id"],
                grant["id"],
                species=species,
                max_animals_justified=max_animals,
                review_path=review_path,
                pain_category=pain_category,
            ),
            inv_headers,
        )
    )
    return {
        "investigator": investigator,
        "grant": grant,
        "protocol": protocol,
        "investigator_headers": inv_headers,
    }


def submit_protocol(protocol_id: str, investigator_id: str) -> dict:
    """Submit a DRAFT protocol as its owning investigator. Returns Protocol."""
    return get_success_data(
        api_client.submit_protocol(
            protocol_id, make_investigator_headers(investigator_id),
        )
    )


def record_dmr_decision(protocol_id: str, decision: str) -> dict:
    """Record the single designated-member decision (IacucAdministrator).

    The protocol's reviewer rows are listed first so the decision references
    the protocol's own DESIGNATED_MEMBER row by id (PRD §3.3: "the payload
    must carry exactly one decision for the single `DESIGNATED_MEMBER` row").
    """
    reviewers = get_success_data(
        api_client.list_protocol_reviewers(protocol_id, ADMIN)
    )
    designated = [r for r in reviewers if r["reviewer_kind"] == "DESIGNATED_MEMBER"]
    return get_success_data(
        api_client.record_review_decisions(
            protocol_id, dmr_decision_payload(designated[0]["id"], decision), ADMIN,
        )
    )


def record_fcr_decisions(protocol_id: str, *decisions: str) -> dict:
    """Record one decision per COMMITTEE_MEMBER reviewer row, zipped in listed
    order (IacucAdministrator; PRD §3.3: "decisions for all three
    `COMMITTEE_MEMBER` rows")."""
    reviewers = get_success_data(
        api_client.list_protocol_reviewers(protocol_id, ADMIN)
    )
    committee = [r for r in reviewers if r["reviewer_kind"] == "COMMITTEE_MEMBER"]
    return get_success_data(
        api_client.record_review_decisions(
            protocol_id,
            fcr_decision_payload([r["id"] for r in committee], *decisions),
            ADMIN,
        )
    )


def create_approved_protocol(**kwargs) -> dict:
    """Full DMR path: draft -> submit -> designated-member APPROVE.
    Returns the create_draft_protocol dict with the APPROVED protocol."""
    scenario = create_draft_protocol(**kwargs)
    submit_protocol(scenario["protocol"]["id"], scenario["investigator"]["id"])
    scenario["protocol"] = record_dmr_decision(
        scenario["protocol"]["id"], "APPROVE",
    )
    return scenario


def create_fcr_protocol_in_review(**kwargs) -> dict:
    """FCR path: draft -> submit -> FCR_REVIEW with three PENDING
    committee-member reviewers."""
    kwargs["review_path"] = "FCR"
    scenario = create_draft_protocol(**kwargs)
    scenario["protocol"] = submit_protocol(
        scenario["protocol"]["id"], scenario["investigator"]["id"],
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier 2: cages / animals / litters / census
# ---------------------------------------------------------------------------

def add_cage(protocol_id: str, **overrides) -> dict:
    """Create a cage billed to a protocol (FacilityManager). Returns Cage."""
    return get_success_data(
        api_client.create_cage(create_cage_payload(protocol_id, **overrides), FACILITY)
    )


def add_animal(cage_id: str, protocol_id: str, **overrides) -> dict:
    """Add an animal to a cage (AnimalCareStaff). Returns Animal."""
    return get_success_data(
        api_client.create_animal(
            create_animal_payload(cage_id, protocol_id, **overrides), STAFF,
        )
    )


def add_mouse(cage_id: str, protocol_id: str, **overrides) -> dict:
    """Add an adult MOUSE (default dob) to a cage. Returns Animal."""
    overrides.setdefault("species", "MOUSE")
    overrides.setdefault("date_of_birth", ADULT_MOUSE_DOB)
    return add_animal(cage_id, protocol_id, **overrides)


def setup_approved_with_cage(
    species="MOUSE",
    cage_kind="STANDARD",
    capacity_adults=5,
    max_animals=TEST_DEFAULTS["MAX_ANIMALS_JUSTIFIED"],
    budget=TEST_DEFAULTS["GRANT_BUDGET_CENTS"],
    pain_category="C",
    room_code="VIV-101",
) -> dict:
    """APPROVED protocol plus one EMPTY cage of matching species."""
    scenario = create_approved_protocol(
        species=species, max_animals=max_animals, budget=budget,
        pain_category=pain_category,
    )
    scenario["cage"] = add_cage(
        scenario["protocol"]["id"],
        species=species,
        cage_kind=cage_kind,
        capacity_adults=capacity_adults,
        room_code=room_code,
    )
    return scenario


def setup_occupied_cage(num_animals=1, **kwargs) -> dict:
    """APPROVED protocol + cage + num_animals adult mice placed in the cage."""
    scenario = setup_approved_with_cage(**kwargs)
    scenario["animals"] = [
        add_mouse(scenario["cage"]["id"], scenario["protocol"]["id"])
        for _ in range(num_animals)
    ]
    return scenario


def file_census(cage_id: str, census_date: str, physical_count: int) -> dict:
    """File one census record (AnimalCareStaff). Returns CensusRecord."""
    return get_success_data(
        api_client.create_census_record(
            create_census_record_payload(
                cage_id, census_date=census_date, physical_count=physical_count,
            ),
            STAFF,
        )
    )


def file_daily_census(cage_id: str, days: int, physical_count: int,
                      start: str = DEFAULT_PERIOD_START) -> list:
    """File one clean census record per day for `days` consecutive days."""
    return [
        file_census(cage_id, _day_iso(d, start), physical_count)
        for d in range(days)
    ]


# ---------------------------------------------------------------------------
# Tier 3: billing run lifecycle
# ---------------------------------------------------------------------------

def create_billing_run(period_start=DEFAULT_PERIOD_START,
                       period_end=DEFAULT_PERIOD_END) -> dict:
    """Open a DRAFT billing run (BillingCoordinator). Returns BillingRun."""
    return get_success_data(
        api_client.create_billing_run(
            create_billing_run_payload(
                period_start=period_start, period_end=period_end,
            ),
            BILLING,
        )
    )


def compute_provisional_ok(run_id: str) -> dict:
    """DRAFT -> PROVISIONAL. Returns updated BillingRun."""
    return get_success_data(api_client.compute_provisional(run_id, BILLING))


def finalize_run(run_id: str, expected_version: int) -> dict:
    """PROVISIONAL -> FINALIZED under OCC. Returns updated BillingRun."""
    return get_success_data(
        api_client.finalize_billing_run(
            run_id, {"expected_billing_run_version": expected_version}, BILLING,
        )
    )


def post_run(run_id: str) -> dict:
    """FINALIZED -> POSTED. Returns updated BillingRun."""
    return get_success_data(api_client.post_billing_run(run_id, BILLING))


def list_run_charges(run_id: str) -> list:
    """All per-diem charge rows of a run (BillingCoordinator)."""
    return get_success_data(api_client.list_billing_run_charges(run_id, BILLING))


def setup_provisional_run(
    period_start=DEFAULT_PERIOD_START,
    period_end=DEFAULT_PERIOD_END,
    budget=TEST_DEFAULTS["GRANT_BUDGET_CENTS"],
    census_dates=None,
) -> dict:
    """APPROVED mouse protocol + occupied cage + clean census + billing run
    computed to PROVISIONAL. Returns scenario dict with run and charges.

    By default one clean (discrepancy-0) census record is filed for every day
    of the period, so the FINAL reconciled-census model (PRD §3.7: "a day
    counts only when a reconciled census — a census record whose `discrepancy`
    is zero — confirms occupancy for that day") reproduces the provisional
    amount on finalize. Pass an explicit `census_dates` tuple to file less."""
    scenario = setup_occupied_cage(num_animals=1, budget=budget)
    if census_dates is None:
        census_dates = _period_days(period_start, period_end)
    for date in census_dates:
        file_census(scenario["cage"]["id"], date, 1)
    scenario["run"] = create_billing_run(period_start, period_end)
    scenario["run"] = compute_provisional_ok(scenario["run"]["id"])
    scenario["charges"] = list_run_charges(scenario["run"]["id"])
    return scenario


def setup_posted_mouse_run(budget=TEST_DEFAULTS["GRANT_BUDGET_CENTS"]) -> dict:
    """Provisional run carried through finalize and post (grant debited)."""
    scenario = setup_provisional_run(budget=budget)
    scenario["run"] = finalize_run(
        scenario["run"]["id"], scenario["run"]["version"],
    )
    scenario["run"] = post_run(scenario["run"]["id"])
    return scenario


def setup_dual_variant_billing() -> dict:
    """One mouse cage with a clean census for every day of 2026-08-01..21,
    a billing run for [2026-08-01, 2026-08-22) computed PROVISIONAL while the
    mouse is ALIVE, the mouse retired with the logical clock standing at
    2026-08-11 (so its status-change date is 2026-08-11), the clock advanced
    to 2026-08-22, and the run FINALIZED. Returns the scenario with both
    `provisional_charges` and `final_charges` captured (PRD §3.7)."""
    scenario = setup_occupied_cage(num_animals=1)
    cage_id = scenario["cage"]["id"]
    file_daily_census(cage_id, 21, 1)
    run = create_billing_run(DEFAULT_PERIOD_START, DEFAULT_PERIOD_END)
    run = compute_provisional_ok(run["id"])
    scenario["run"] = run
    scenario["provisional_charges"] = list_run_charges(run["id"])

    set_clock("2026-08-11T00:00:00Z")
    get_success_data(
        api_client.retire_animal(scenario["animals"][0]["id"], STAFF)
    )
    set_clock("2026-08-22T00:00:00Z")

    scenario["run"] = finalize_run(run["id"], run["version"])
    scenario["final_charges"] = list_run_charges(run["id"])
    return scenario


def setup_rat_tier_billing() -> dict:
    """APPROVED rat protocol with two cages: R-AGED holds one adult rat
    (dob 2026-01-01) and one aged rat (dob 2024-01-01); R-ADULT holds one
    adult rat. Clean census for both cages and a run computed PROVISIONAL
    over [2026-08-01, 2026-08-22). Returns scenario with `charges`."""
    scenario = create_approved_protocol(species="RAT", max_animals=20)
    proto_id = scenario["protocol"]["id"]
    cage_aged = add_cage(proto_id, species="RAT", capacity_adults=2,
                         cage_barcode="R-AGED", room_code="VIV-102")
    cage_adult = add_cage(proto_id, species="RAT", capacity_adults=2,
                          cage_barcode="R-ADULT", room_code="VIV-102")
    add_animal(cage_aged["id"], proto_id, species="RAT",
               date_of_birth="2026-01-01T00:00:00Z", sex="M")
    add_animal(cage_aged["id"], proto_id, species="RAT",
               date_of_birth="2024-01-01T00:00:00Z", sex="M")
    add_animal(cage_adult["id"], proto_id, species="RAT",
               date_of_birth="2026-01-01T00:00:00Z", sex="F")
    file_census(cage_aged["id"], DEFAULT_PERIOD_START, 2)
    file_census(cage_adult["id"], DEFAULT_PERIOD_START, 1)
    run = create_billing_run(DEFAULT_PERIOD_START, DEFAULT_PERIOD_END)
    scenario["run"] = compute_provisional_ok(run["id"])
    scenario["cage_aged"] = cage_aged
    scenario["cage_adult"] = cage_adult
    scenario["charges"] = list_run_charges(run["id"])
    return scenario


def setup_flat_rate_billing(species="ZEBRAFISH", capacity_adults=20,
                            max_animals=50) -> dict:
    """APPROVED protocol + one occupied cage of the given species + clean
    census + PROVISIONAL run over [2026-08-01, 2026-08-22)."""
    scenario = create_approved_protocol(species=species, max_animals=max_animals,
                                        pain_category="B")
    proto_id = scenario["protocol"]["id"]
    cage = add_cage(proto_id, species=species, capacity_adults=capacity_adults,
                    room_code="AQUA-01")
    add_animal(cage["id"], proto_id, species=species,
               date_of_birth="2026-01-01T00:00:00Z", sex="M")
    file_census(cage["id"], DEFAULT_PERIOD_START, 1)
    run = create_billing_run(DEFAULT_PERIOD_START, DEFAULT_PERIOD_END)
    scenario["run"] = compute_provisional_ok(run["id"])
    scenario["cage"] = cage
    scenario["charges"] = list_run_charges(run["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 3: adverse events / deviations / suspension chain
# ---------------------------------------------------------------------------

def file_adverse_event(protocol_id: str, animal_id: str, reporter_id: str,
                       severity="MINOR", description="clinical note") -> dict:
    """File an adverse-event report (AttendingVeterinarian)."""
    return get_success_data(
        api_client.create_adverse_event(
            create_adverse_event_payload(
                protocol_id, animal_id, reporter_id,
                severity=severity, description=description,
            ),
            VET,
        )
    )


def report_deviation(protocol_id: str, reporter_id: str,
                     seriousness="SERIOUS", description="deviation") -> dict:
    """Report a protocol deviation (AttendingVeterinarian)."""
    return get_success_data(
        api_client.create_protocol_deviation(
            create_protocol_deviation_payload(
                protocol_id, reporter_id,
                seriousness=seriousness, description=description,
            ),
            VET,
        )
    )


def impose_suspension_from_deviation(deviation_id: str) -> dict:
    """REPORTED -> UNDER_REVIEW -> SUSPENSION_IMPOSED (IacucAdministrator);
    cascades to the protocol (PRD §3.8). Returns the deviation."""
    get_success_data(api_client.begin_deviation_review(deviation_id, ADMIN))
    return get_success_data(api_client.impose_suspension(deviation_id, ADMIN))


def setup_suspended_protocol(with_animal=True, with_open_event=False) -> dict:
    """APPROVED protocol driven to SUSPENDED through the deviation chain:
    a SERIOUS deviation is reported, reviewed, and suspension imposed.
    Returns scenario dict with protocol (SUSPENDED), cage, deviation, and
    the reporting personnel member."""
    scenario = setup_occupied_cage(num_animals=1 if with_animal else 0)
    scenario["reporter"] = create_cleared_personnel()
    if with_open_event:
        scenario["event"] = file_adverse_event(
            scenario["protocol"]["id"], scenario["animals"][0]["id"],
            scenario["reporter"]["id"],
        )
    scenario["deviation"] = report_deviation(
        scenario["protocol"]["id"], scenario["reporter"]["id"],
    )
    scenario["deviation"] = impose_suspension_from_deviation(
        scenario["deviation"]["id"],
    )
    scenario["protocol"] = get_success_data(
        api_client.get_protocol(scenario["protocol"]["id"], ADMIN)
    )
    return scenario


def setup_reinstated_protocol() -> dict:
    """Protocol suspended through the deviation chain and then reinstated —
    the deviation stands SUSPENSION_IMPOSED, so the direct-suspend
    precondition of PRD §3.8 remains satisfied while the protocol is
    APPROVED again. Returns scenario dict."""
    scenario = setup_suspended_protocol()
    scenario["protocol"] = get_success_data(
        api_client.reinstate_protocol(scenario["protocol"]["id"], ADMIN)
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier 3: breeding / litters
# ---------------------------------------------------------------------------

def setup_breeding_cage(pup_count=4, born_on=DEFAULT_PERIOD_START,
                        capacity_adults=2, target_capacity=5) -> dict:
    """APPROVED mouse protocol + BREEDING cage with two adults + one NURSING
    litter + one empty STANDARD target cage for weaning. Returns scenario."""
    scenario = setup_approved_with_cage(
        species="MOUSE", cage_kind="BREEDING", capacity_adults=capacity_adults,
        max_animals=40, pain_category="B", room_code="VIV-402",
    )
    scenario["wean_cage"] = add_cage(
        scenario["protocol"]["id"], species="MOUSE", cage_kind="STANDARD",
        capacity_adults=target_capacity, room_code="VIV-402",
    )
    scenario["animals"] = [
        add_animal(
            scenario["cage"]["id"], scenario["protocol"]["id"],
            date_of_birth="2026-01-01T00:00:00Z", sex=sex,
        )
        for sex in ("M", "F")
    ]
    scenario["litter"] = get_success_data(
        api_client.create_litter(
            create_litter_payload(
                scenario["cage"]["id"], scenario["protocol"]["id"],
                born_on=born_on, pup_count=pup_count,
            ),
            STAFF,
        )
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier 3: procedure rooms
# ---------------------------------------------------------------------------

def setup_booking_scenario() -> dict:
    """APPROVED protocol + gate-cleared booking member. Ready for
    room-booking calls (PRD §3.9)."""
    scenario = create_approved_protocol()
    scenario["booker"] = create_cleared_personnel()
    return scenario


def book_room(protocol_id: str, booker_id: str, room_code: str,
              start_at: str, end_at: str):
    """Raw create-room-booking call (AnimalCareStaff). Returns Response."""
    return api_client.create_room_booking(
        create_room_booking_payload(
            protocol_id, booker_id,
            room_code=room_code, start_at=start_at, end_at=end_at,
        ),
        STAFF,
    )


# ---------------------------------------------------------------------------
# Tier 3: inspections
# ---------------------------------------------------------------------------

def create_inspection(inspection_kind="FACILITY", scheduled_for="2026-01-15T00:00:00Z",
                      **overrides) -> dict:
    """Schedule an inspection (IacucAdministrator). Returns FacilityInspection."""
    return get_success_data(
        api_client.create_inspection(
            create_inspection_payload(
                inspection_kind=inspection_kind, scheduled_for=scheduled_for,
                **overrides,
            ),
            ADMIN,
        )
    )


def complete_inspection_ok(inspection_id: str, completed_at: str,
                           deficiency_count=0) -> dict:
    """Complete an inspection on time (IacucAdministrator)."""
    return get_success_data(
        api_client.complete_inspection(
            inspection_id,
            {"completed_at": completed_at, "deficiency_count": deficiency_count},
            ADMIN,
        )
    )
