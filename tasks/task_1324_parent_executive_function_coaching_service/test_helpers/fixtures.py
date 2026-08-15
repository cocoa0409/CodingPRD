"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a freshly restarted
server using only PRD-declared endpoints, and uses get_success_data() internally
so a broken setup step fails with a clear "Setup step failed" message.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_checkin_payload,
    create_client_payload,
    create_coach_payload,
    create_consent_payload,
    create_contact_payload,
    create_family_payload,
    create_goal_payload,
    create_intake_payload,
    create_note_payload,
    create_plan_payload,
    create_session_payload,
    create_supervision_payload,
    create_workshop_payload,
    create_enrollment_payload,
    purchase_package_payload,
)
from .test_users import (
    TEST_USERS,
    make_coach_headers,
    make_family_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock / sweep
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_sweep() -> dict:
    return get_success_data(api_client.run_daily_sweep(ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-entity builders
# ---------------------------------------------------------------------------

def create_family(account_name="Test Family", primary_email="fam@example.com") -> dict:
    return get_success_data(
        api_client.create_family(
            create_family_payload(account_name=account_name, primary_email=primary_email),
            ADMIN,
        )
    )


def add_client(family_id, track="INDIVIDUAL", full_name="Kid Test",
               date_of_birth="2014-01-01") -> dict:
    return get_success_data(
        api_client.create_client(
            family_id,
            create_client_payload(
                full_name=full_name, date_of_birth=date_of_birth, track=track
            ),
            ADMIN,
        )
    )


def activate_family(family_id) -> dict:
    return get_success_data(api_client.transition_family(family_id, "ACTIVE", ADMIN))


def create_coach(credential_level="CERTIFIED", full_name="Coach Test") -> dict:
    return get_success_data(
        api_client.create_coach(
            create_coach_payload(full_name=full_name, credential_level=credential_level),
            ADMIN,
        )
    )


def transition_family(family_id, to_state) -> dict:
    return get_success_data(api_client.transition_family(family_id, to_state, ADMIN))


def purchase_package(family_id, track="INDIVIDUAL", credits_total=8) -> dict:
    return get_success_data(
        api_client.purchase_package(
            family_id,
            purchase_package_payload(track=track, credits_total=credits_total),
            ADMIN,
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: intake workflow
# ---------------------------------------------------------------------------

def create_intake(client_id, presenting_concerns="focus", baseline_score=50) -> dict:
    return get_success_data(
        api_client.create_intake(
            client_id,
            create_intake_payload(
                presenting_concerns=presenting_concerns, baseline_score=baseline_score
            ),
            ADMIN,
        )
    )


def create_approved_intake(client_id, family_id, reviewer_coach_id,
                           presenting_concerns="focus", baseline_score=50) -> dict:
    """Intake walked DRAFT -> SUBMITTED -> UNDER_REVIEW -> APPROVED.

    The reviewer must hold CERTIFIED or SUPERVISOR; callers passing an ASSOCIATE
    plan coach must pass a separate SUPERVISOR reviewer.
    """
    intake = create_intake(client_id, presenting_concerns, baseline_score)
    family_headers = make_family_headers(family_id)
    reviewer_headers = make_coach_headers(reviewer_coach_id)
    get_success_data(
        api_client.transition_intake(intake["id"], "SUBMITTED", family_headers)
    )
    get_success_data(
        api_client.transition_intake(intake["id"], "UNDER_REVIEW", reviewer_headers)
    )
    return get_success_data(
        api_client.transition_intake(intake["id"], "APPROVED", reviewer_headers)
    )


# ---------------------------------------------------------------------------
# Tier 3: plan lifecycle
# ---------------------------------------------------------------------------

def create_plan_for_client(client_id, coach_id, intake_id, cadence="WEEKLY") -> dict:
    """Create a plan draft, re-reading the client first so the OCC version is fresh."""
    client = get_success_data(api_client.get_client(client_id, ADMIN))
    return get_success_data(
        api_client.create_plan(
            client_id,
            create_plan_payload(
                coach_id,
                intake_id,
                expected_client_version=client["version"],
                cadence=cadence,
            ),
            make_coach_headers(coach_id),
        )
    )


def add_goal(plan_id, coach_id, title="Goal G", target_date="2026-09-01") -> dict:
    return get_success_data(
        api_client.create_goal(
            plan_id,
            create_goal_payload(title=title, target_date=target_date),
            make_coach_headers(coach_id),
        )
    )


def propose_plan(plan_id, coach_id) -> dict:
    return get_success_data(
        api_client.transition_plan(plan_id, "PROPOSED", make_coach_headers(coach_id))
    )


def accept_plan(plan_id, family_id) -> dict:
    return get_success_data(
        api_client.transition_plan(plan_id, "ACTIVE", make_family_headers(family_id))
    )


def draft_plan_with_goal(client_id, coach_id, intake_id, cadence="WEEKLY",
                         goal_title="Goal G") -> dict:
    plan = create_plan_for_client(client_id, coach_id, intake_id, cadence)
    add_goal(plan["id"], coach_id, title=goal_title)
    return plan


# ---------------------------------------------------------------------------
# Tier 4: the ubiquitous ACTIVE-plan scenario
# ---------------------------------------------------------------------------

def setup_active_plan_scenario(
    account_name="Fam S",
    primary_email="s@example.com",
    num_clients=1,
    tracks=None,
    coach_level="CERTIFIED",
    cadence="WEEKLY",
    package=None,
    goals_per_plan=1,
) -> dict:
    """ACTIVE family + coach + one approved intake and ACTIVE plan per client.

    Returns {"family", "coach", "reviewer", "clients", "intakes", "plans",
    "goals", "packages"}. When coach_level is ASSOCIATE a separate SUPERVISOR
    reviewer coach approves the intakes (associates cannot approve).
    """
    family = create_family(account_name, primary_email)
    fam_id = family["id"]
    if tracks is None:
        tracks = ["INDIVIDUAL"] * num_clients
    clients = [
        add_client(fam_id, track=tracks[i], full_name=f"Kid {account_name} {i + 1}")
        for i in range(num_clients)
    ]
    activate_family(fam_id)
    coach = create_coach(coach_level, full_name=f"Coach {account_name}")
    if coach_level == "ASSOCIATE":
        reviewer = create_coach("SUPERVISOR", full_name=f"Reviewer {account_name}")
    else:
        reviewer = coach
    if package is not None:
        packages = [purchase_package(fam_id, package["track"], package["credits_total"])]
    else:
        packages = []
    intakes, plans, goals = [], [], []
    for client in clients:
        intake = create_approved_intake(client["id"], fam_id, reviewer["id"])
        plan = draft_plan_with_goal(client["id"], coach["id"], intake["id"], cadence)
        propose_plan(plan["id"], coach["id"])
        plan = accept_plan(plan["id"], fam_id)
        intakes.append(intake)
        plans.append(plan)
        goals.append(get_success_data(api_client.list_goals(plan["id"], ADMIN))[0])
    return {
        "family": family,
        "coach": coach,
        "reviewer": reviewer,
        "clients": clients,
        "intakes": intakes,
        "plans": plans,
        "goals": goals,
        "packages": packages,
    }


def add_family_with_active_plan(coach, reviewer=None, account_name="Aux Fam",
                                primary_email="aux@example.com", track="INDIVIDUAL",
                                cadence="WEEKLY", package_credits=None) -> dict:
    """An additional ACTIVE family whose client holds an ACTIVE plan coached by
    an already-existing coach (used for cross-family schedule-conflict setups)."""
    if reviewer is None:
        reviewer = coach
    family = create_family(account_name, primary_email)
    client = add_client(family["id"], track=track, full_name=f"Kid {account_name}")
    activate_family(family["id"])
    package = None
    if package_credits is not None:
        package = purchase_package(family["id"], "INDIVIDUAL", package_credits)
    intake = create_approved_intake(client["id"], family["id"], reviewer["id"])
    plan = draft_plan_with_goal(client["id"], coach["id"], intake["id"], cadence)
    propose_plan(plan["id"], coach["id"])
    plan = accept_plan(plan["id"], family["id"])
    return {
        "family": family,
        "client": client,
        "intake": intake,
        "plan": plan,
        "package": package,
    }


# ---------------------------------------------------------------------------
# Tier 5: sessions / check-ins / snapshots
# ---------------------------------------------------------------------------

def schedule_session(plan_id, coach_id, package_id, scheduled_start, scheduled_end):
    """Raw response — callers asserting rejection use this."""
    return api_client.create_session(
        plan_id,
        create_session_payload(package_id, scheduled_start, scheduled_end),
        make_coach_headers(coach_id),
    )


def schedule_session_ok(plan_id, coach_id, package_id, scheduled_start, scheduled_end) -> dict:
    return get_success_data(
        schedule_session(plan_id, coach_id, package_id, scheduled_start, scheduled_end)
    )


def create_checkin(plan_id, coach_id, due_at) -> dict:
    return get_success_data(
        api_client.create_checkin(
            plan_id, create_checkin_payload(due_at=due_at), make_coach_headers(coach_id)
        )
    )


def submit_checkin(checkin_id, family_id) -> dict:
    return get_success_data(
        api_client.submit_checkin(checkin_id, make_family_headers(family_id))
    )


def take_snapshot(client_id, coach_id) -> dict:
    return get_success_data(
        api_client.create_progress_snapshot(client_id, make_coach_headers(coach_id))
    )


# ---------------------------------------------------------------------------
# Tier 6: contacts / consents / notes
# ---------------------------------------------------------------------------

def create_contact(family_id, name="Dr Test", organization="Clinic",
                   contact_type="CLINICIAN", email="c@clinic.example.com") -> dict:
    return get_success_data(
        api_client.create_contact(
            family_id,
            create_contact_payload(
                name=name,
                organization=organization,
                contact_type=contact_type,
                email=email,
            ),
            make_family_headers(family_id),
        )
    )


def create_consent(family_id, contact_id, scope="FULL_PLAN",
                   expires_at="2027-01-01T00:00:00Z") -> dict:
    """Create a PENDING_SIGNATURE consent, re-reading the family version first."""
    family = get_success_data(api_client.get_family(family_id, ADMIN))
    return get_success_data(
        api_client.create_consent(
            family_id,
            create_consent_payload(
                contact_id,
                expected_family_version=family["version"],
                scope=scope,
                expires_at=expires_at,
            ),
            make_family_headers(family_id),
        )
    )


def sign_consent(consent_id, family_id) -> dict:
    return get_success_data(
        api_client.transition_consent(consent_id, "ACTIVE", make_family_headers(family_id))
    )


def create_active_consent(family_id, contact_id, scope="FULL_PLAN",
                          expires_at="2027-01-01T00:00:00Z") -> dict:
    return sign_consent(
        create_consent(family_id, contact_id, scope, expires_at)["id"], family_id
    )


def create_note(client_id, coach_id, topic="PROGRESS", body="note body") -> dict:
    return get_success_data(
        api_client.create_note(
            client_id,
            create_note_payload(topic=topic, body=body),
            make_coach_headers(coach_id),
        )
    )


def finalize_note(note_id, coach_id) -> dict:
    return get_success_data(
        api_client.transition_note(note_id, "FINALIZED", make_coach_headers(coach_id))
    )


def create_finalized_note(client_id, coach_id, topic="PROGRESS", body="note body") -> dict:
    return finalize_note(create_note(client_id, coach_id, topic, body)["id"], coach_id)


# ---------------------------------------------------------------------------
# Tier 7: workshops / enrollments
# ---------------------------------------------------------------------------

def create_workshop(coach_id, title="Workshop", capacity=5, price_cents=15000,
                    window_start="2026-09-05T17:00:00Z",
                    window_end="2026-09-05T20:00:00Z") -> dict:
    return get_success_data(
        api_client.create_workshop(
            create_workshop_payload(
                coach_id,
                title=title,
                capacity=capacity,
                price_cents=price_cents,
                window_start=window_start,
                window_end=window_end,
            ),
            ADMIN,
        )
    )


def create_open_workshop(coach_id, **kwargs) -> dict:
    workshop = create_workshop(coach_id, **kwargs)
    return get_success_data(api_client.transition_workshop(workshop["id"], "OPEN", ADMIN))


def enroll(workshop_id, client_id, family_id):
    """Raw response — callers asserting rejection use this."""
    return api_client.create_enrollment(
        workshop_id, create_enrollment_payload(client_id), make_family_headers(family_id)
    )


def enroll_ok(workshop_id, client_id, family_id) -> dict:
    return get_success_data(enroll(workshop_id, client_id, family_id))


# ---------------------------------------------------------------------------
# Tier 8: supervision
# ---------------------------------------------------------------------------

def create_supervision_record(coach_id, supervisor_id, hours=1.0,
                              scheduled_at="2026-08-05T10:00:00Z") -> dict:
    return get_success_data(
        api_client.create_supervision_record(
            coach_id,
            create_supervision_payload(
                supervisor_id, scheduled_at=scheduled_at, hours=hours
            ),
            ADMIN,
        )
    )


def verify_supervision_record(record_id, supervisor_id) -> dict:
    """SCHEDULED -> HELD (named supervisor) -> VERIFIED (PracticeAdmin)."""
    get_success_data(
        api_client.transition_supervision_record(
            record_id, "HELD", make_coach_headers(supervisor_id)
        )
    )
    return get_success_data(
        api_client.transition_supervision_record(record_id, "VERIFIED", ADMIN)
    )


def create_verified_supervision(coach_id, supervisor_id, hours=1.0,
                                scheduled_at="2026-08-02T10:00:00Z") -> dict:
    record = create_supervision_record(coach_id, supervisor_id, hours, scheduled_at)
    return verify_supervision_record(record["id"], supervisor_id)


# ---------------------------------------------------------------------------
# Composite scenarios keyed to the design-index setup chains
# ---------------------------------------------------------------------------

def setup_dual_variant_package() -> dict:
    """Family with TWO clients, one ACTIVE WEEKLY plan for client 1, and a
    16-credit INDIVIDUAL package with four completed sessions."""
    ctx = setup_active_plan_scenario(
        account_name="Fam DV",
        primary_email="dv@example.com",
        num_clients=2,
        package={"track": "INDIVIDUAL", "credits_total": 16},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    sessions = []
    for day in ("03", "08", "13", "18"):
        sessions.append(
            schedule_session_ok(
                plan["id"], coach["id"], package["id"],
                f"2026-08-{day}T15:00:00Z", f"2026-08-{day}T16:00:00Z",
            )
        )
    for session, day in zip(sessions, ("03", "08", "13", "18")):
        set_clock(f"2026-08-{day}T15:30:00Z")
        get_success_data(
            api_client.complete_session(session["id"], make_coach_headers(coach["id"]))
        )
    ctx["sessions"] = sessions
    return ctx


def setup_three_session_package(credits_total=8) -> dict:
    """ACTIVE plan + 8-credit INDIVIDUAL package with sessions reserved at
    2026-08-03 / 2026-08-08 / 2026-08-13 (5-day gaps, WEEKLY cadence)."""
    ctx = setup_active_plan_scenario(
        account_name="Fam 3S",
        primary_email="3s@example.com",
        package={"track": "INDIVIDUAL", "credits_total": credits_total},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    sessions = [
        schedule_session_ok(
            plan["id"], coach["id"], package["id"],
            f"2026-08-{day}T15:00:00Z", f"2026-08-{day}T16:00:00Z",
        )
        for day in ("03", "08", "13")
    ]
    ctx["sessions"] = sessions
    return ctx


def setup_one_credit_session(scheduled_start="2026-08-03T15:00:00Z",
                             scheduled_end="2026-08-03T16:00:00Z") -> dict:
    """ACTIVE plan funded by a 1-credit INDIVIDUAL package with one session
    reserved at the given instant."""
    ctx = setup_active_plan_scenario(
        account_name="Fam 1C",
        primary_email="1c@example.com",
        package={"track": "INDIVIDUAL", "credits_total": 1},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    ctx["session"] = schedule_session_ok(
        plan["id"], coach["id"], package["id"], scheduled_start, scheduled_end
    )
    return ctx


def setup_deficit_scenario() -> dict:
    """ASSOCIATE coach holding two ACTIVE plans (caseload 2, required 1 hour,
    zero verified => deficit lands after the second acceptance) plus a third
    client's plan already PROPOSED. Intakes are approved by a SUPERVISOR."""
    ctx = setup_active_plan_scenario(
        account_name="Fam SD",
        primary_email="sd@example.com",
        num_clients=2,
        coach_level="ASSOCIATE",
    )
    family, coach = ctx["family"], ctx["coach"]
    # Third client with an approved intake and a PROPOSED plan for coach A.
    client3 = add_client(family["id"], track="INDIVIDUAL", full_name="Kid SD 3")
    intake3 = create_approved_intake(client3["id"], family["id"], ctx["reviewer"]["id"])
    plan3 = draft_plan_with_goal(client3["id"], coach["id"], intake3["id"])
    propose_plan(plan3["id"], coach["id"])
    ctx["clients"].append(client3)
    ctx["intakes"].append(intake3)
    ctx["plans"].append(plan3)
    return ctx


def setup_caseload_cap_boundary() -> dict:
    """ASSOCIATE coach pre-loaded with 6 verified supervision hours and holding
    12 ACTIVE plans (== caseload cap); a 13th client's plan sits PROPOSED."""
    family = create_family("Fam Cap12", "cap12@example.com")
    coach = create_coach("ASSOCIATE", full_name="Coach A12")
    supervisor = create_coach("SUPERVISOR", full_name="Coach S12")
    create_verified_supervision(coach["id"], supervisor["id"], hours=6.0)
    clients, plans = [], []
    for i in range(13):
        client = add_client(family["id"], track="INDIVIDUAL",
                            full_name=f"Kid C{i + 1}", date_of_birth="2013-01-01")
        clients.append(client)
        if i == 0:
            activate_family(family["id"])
        intake = create_approved_intake(client["id"], family["id"], supervisor["id"],
                                        presenting_concerns=f"c{i + 1}")
        plan = draft_plan_with_goal(client["id"], coach["id"], intake["id"],
                                    goal_title=f"G{i + 1}")
        propose_plan(plan["id"], coach["id"])
        if i < 12:
            plan = accept_plan(plan["id"], family["id"])
        plans.append(plan)
    return {
        "family": family,
        "coach": coach,
        "supervisor": supervisor,
        "clients": clients,
        "plans": plans,
    }


def setup_overlap_families() -> dict:
    """One CERTIFIED coach shared by three families, each with an ACTIVE plan
    and a 1-credit INDIVIDUAL package."""
    coach = create_coach("CERTIFIED", full_name="Coach OL")
    legs = {
        letter: add_family_with_active_plan(
            coach,
            account_name=f"Fam O{letter}",
            primary_email=f"o{letter.lower()}@example.com",
            package_credits=1,
        )
        for letter in ("A", "B", "C")
    }
    return {"coach": coach, **legs}


def setup_buffer_families() -> dict:
    """One coach facilitating an OPEN workshop 2026-08-10 10:00-11:45Z, plus two
    families each with an ACTIVE plan and a 1-credit INDIVIDUAL package."""
    coach = create_coach("CERTIFIED", full_name="Coach WB")
    workshop = create_open_workshop(
        coach["id"],
        title="Buffer Lab",
        capacity=5,
        price_cents=0,
        window_start="2026-08-10T10:00:00Z",
        window_end="2026-08-10T11:45:00Z",
    )
    leg_a = add_family_with_active_plan(
        coach, account_name="Fam WA", primary_email="wa@example.com", package_credits=1
    )
    leg_b = add_family_with_active_plan(
        coach, account_name="Fam WB", primary_email="wb@example.com", package_credits=1
    )
    return {"coach": coach, "workshop": workshop, "A": leg_a, "B": leg_b}


def setup_capacity_workshop(capacity=2) -> dict:
    """Family with three HYBRID clients, each in an ACTIVE plan, plus an OPEN
    workshop with the given capacity priced 15000."""
    ctx = setup_active_plan_scenario(
        account_name="Fam Cap",
        primary_email="cap@example.com",
        num_clients=3,
        tracks=["HYBRID", "HYBRID", "HYBRID"],
    )
    workshop = create_open_workshop(
        ctx["coach"]["id"], title="Focus Lab", capacity=capacity, price_cents=15000
    )
    ctx["workshop"] = workshop
    return ctx


def setup_waitlist_workshop() -> dict:
    """Families A and B each with an ACTIVE HYBRID client; an OPEN capacity-1
    workshop priced 15000 where A is ENROLLED (MONEY) and B is WAITLISTED."""
    coach = create_coach("CERTIFIED", full_name="Coach W")
    leg_a = add_family_with_active_plan(
        coach, account_name="Fam A", primary_email="a@example.com", track="HYBRID"
    )
    leg_b = add_family_with_active_plan(
        coach, account_name="Fam B", primary_email="b@example.com", track="HYBRID"
    )
    workshop = create_open_workshop(
        coach["id"], title="Study Skills", capacity=1, price_cents=15000
    )
    enrollment_a = enroll_ok(
        workshop["id"], leg_a["client"]["id"], leg_a["family"]["id"]
    )
    enrollment_b = enroll_ok(
        workshop["id"], leg_b["client"]["id"], leg_b["family"]["id"]
    )
    return {
        "coach": coach,
        "workshop": workshop,
        "A": leg_a,
        "B": leg_b,
        "enrollment_a": enrollment_a,
        "enrollment_b": enrollment_b,
    }


def setup_note_consent_scenario(topic="PROGRESS", scope="FULL_PLAN",
                                sign=True) -> dict:
    """Family + client + coach-authored FINALIZED note + contact + consent
    (signed to ACTIVE unless sign=False)."""
    family = create_family("Fam CG", "cg@example.com")
    client = add_client(family["id"], track="INDIVIDUAL", full_name="Kid CG")
    coach = create_coach("CERTIFIED", full_name="Coach CG")
    note = create_finalized_note(client["id"], coach["id"], topic=topic)
    contact = create_contact(family["id"])
    consent = create_consent(family["id"], contact["id"], scope=scope)
    if sign:
        consent = sign_consent(consent["id"], family["id"])
    return {
        "family": family,
        "client": client,
        "coach": coach,
        "note": note,
        "contact": contact,
        "consent": consent,
    }
