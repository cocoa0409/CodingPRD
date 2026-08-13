"""Composite setup helpers for the Therapy Animal Visits API test suite.

The harness restarts the API server (empty database) before every test, so
each helper builds its preconditions from scratch using only PRD-declared
endpoints. Setup calls use the lenient get_success_data() validator so a
setup failure surfaces as a clear "Setup step failed" error rather than a
confusing assertion mismatch.

Identity threading: every ownership-gated call uses make_*_headers() with the
real entity id (Handler.id / Evaluator.id / Facility.id), per PRD §2.1.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_adjustment_payload,
    create_animal_payload,
    create_certification_payload,
    create_evaluator_payload,
    create_facility_agreement_payload,
    create_facility_payload,
    create_handler_payload,
    create_incident_payload,
    create_insurance_policy_payload,
    create_liability_waiver_payload,
    create_orientation_payload,
    create_team_payload,
    create_vaccination_record_payload,
    create_visit_payload,
    create_visit_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_evaluator_headers,
    make_facility_coordinator_headers,
    make_handler_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
COMPLIANCE_2 = TEST_USERS["compliance_officer_2_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]

# Default evaluation slot (PRD §3.2: 30..120 minutes, start not in the past
# relative to the default logical clock 2026-08-01T00:00:00Z).
DEFAULT_EVAL_START = "2026-08-02T10:00:00Z"
DEFAULT_EVAL_END = "2026-08-02T11:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: logical clock and sweeps (PRD §2.4)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock to the supplied ISO 8601 UTC instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def run_sweeps() -> dict:
    """Run all deterministic time-based transitions in pinned order."""
    return get_success_data(api_client.run_sweeps(ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and progression
# ---------------------------------------------------------------------------

def create_applicant_handler(**overrides) -> dict:
    """Self-register a handler (Anonymous). Returns the APPLICANT handler."""
    return get_success_data(api_client.create_handler(create_handler_payload(**overrides), ANONYMOUS))


def create_active_handler(**overrides) -> dict:
    """Self-register + ProgramAdmin approve. Returns the ACTIVE handler."""
    handler = create_applicant_handler(**overrides)
    return get_success_data(api_client.approve_handler(handler["id"], ADMIN))


def register_animal(handler_id: str, **overrides) -> dict:
    """Register an animal for the given handler. Returns the REGISTERED animal."""
    return get_success_data(
        api_client.create_animal(create_animal_payload(**overrides), make_handler_headers(handler_id))
    )


def create_forming_team(handler_id: str, animal_id: str, team_name: str = "Team One") -> dict:
    """Form a team from an owned animal. Returns the FORMING team."""
    return get_success_data(
        api_client.create_team(create_team_payload(animal_id, team_name), make_handler_headers(handler_id))
    )


def create_active_evaluator(max_evaluations_per_day: Optional[int] = None, **overrides) -> dict:
    """Create an ACTIVE evaluator."""
    payload = create_evaluator_payload(**overrides)
    if max_evaluations_per_day is not None:
        payload["max_evaluations_per_day"] = max_evaluations_per_day
    return get_success_data(api_client.create_evaluator(payload, ADMIN))


def request_evaluation(handler_id: str, team_id: str) -> dict:
    """Request a team evaluation. Returns the REQUESTED evaluation."""
    return get_success_data(
        api_client.create_evaluation({"team_id": team_id}, make_handler_headers(handler_id))
    )


def schedule_evaluation_ok(evaluation_id: str, evaluator_id: str,
                           start: str = DEFAULT_EVAL_START,
                           end: str = DEFAULT_EVAL_END) -> dict:
    """ProgramAdmin schedules the evaluation. Returns the SCHEDULED evaluation."""
    return get_success_data(
        api_client.schedule_evaluation(
            evaluation_id,
            {"evaluator_id": evaluator_id, "scheduled_start": start, "scheduled_end": end},
            ADMIN,
        )
    )


def score_evaluation_ok(evaluation_id: str, evaluator_id: str,
                        aptitude_score: int = 80, obedience_score: int = 70,
                        score_at: Optional[str] = None) -> dict:
    """Move the clock to the session end (or score_at) and score."""
    set_clock(score_at or DEFAULT_EVAL_END)
    return get_success_data(
        api_client.score_evaluation(
            evaluation_id,
            {"aptitude_score": aptitude_score, "obedience_score": obedience_score},
            make_evaluator_headers(evaluator_id),
        )
    )


def record_rabies(handler_id: str, animal_id: str,
                  valid_until: str = "2029-12-31",
                  administered_on: str = "2026-07-01") -> dict:
    """Record a RABIES vaccination. Returns the VALID record."""
    return get_success_data(
        api_client.create_vaccination_record(
            create_vaccination_record_payload(
                animal_id, valid_until=valid_until, administered_on=administered_on,
            ),
            make_handler_headers(handler_id),
        )
    )


def create_verified_policy(handler_id: str, coverage_cents: int = 200_000_000,
                           effective_from: str = "2026-01-01",
                           effective_until: str = "2029-12-31") -> dict:
    """Register + verify a policy. Returns the ACTIVE policy."""
    policy = get_success_data(
        api_client.create_insurance_policy(
            create_insurance_policy_payload(
                coverage_cents=coverage_cents,
                effective_from=effective_from,
                effective_until=effective_until,
            ),
            make_handler_headers(handler_id),
        )
    )
    return get_success_data(api_client.verify_insurance_policy(policy["id"], ADMIN))


def issue_certification(team_id: str, evaluation_id: str) -> dict:
    """Issue a PROVISIONAL certification from a PASSED evaluation."""
    return get_success_data(
        api_client.create_certification(
            create_certification_payload(team_id, evaluation_id), ADMIN
        )
    )


def activate_certification_ok(certification_id: str) -> dict:
    """Activate a PROVISIONAL certification (vaccination + insurance gates green)."""
    return get_success_data(api_client.activate_certification(certification_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — certified team, active facility
# ---------------------------------------------------------------------------

def setup_certified_team(*, species: str = "DOG", volunteer_since: str = "2024-08-01",
                         coverage_cents: int = 200_000_000,
                         policy_from: str = "2026-01-01", policy_until: str = "2029-12-31",
                         rabies_until: str = "2029-12-31",
                         aptitude: int = 80, obedience: int = 70,
                         evaluator: Optional[dict] = None,
                         eval_start: str = DEFAULT_EVAL_START,
                         eval_end: str = DEFAULT_EVAL_END,
                         handler_name: str = "Handler One",
                         team_name: Optional[str] = None,
                         animal_name: str = "Rex", breed: str = "Beagle") -> dict:
    """Full certification chain: handler (ACTIVE) -> animal -> team (FORMING)
    -> evaluation REQUESTED -> SCHEDULED -> PASSED -> rabies record -> ACTIVE
    policy -> certification PROVISIONAL -> ACTIVE.

    On return the team is ACTIVE, the animal is ACTIVE, and the certification
    is ACTIVE with expires_on = (activation day) + 730 days.

    Returns dict(handler, animal, team, evaluator, evaluation, vaccination,
    policy, certification).
    """
    handler = create_active_handler(full_name=handler_name, volunteer_since=volunteer_since)
    animal = register_animal(handler["id"], name=animal_name, species=species, breed=breed)
    team = create_forming_team(handler["id"], animal["id"], team_name or f"{animal_name} Team")
    evaluation = request_evaluation(handler["id"], team["id"])
    if evaluator is None:
        evaluator = create_active_evaluator(specializations=[species])
    schedule_evaluation_ok(evaluation["id"], evaluator["id"], eval_start, eval_end)
    evaluation = score_evaluation_ok(
        evaluation["id"], evaluator["id"], aptitude, obedience, score_at=eval_end
    )
    vaccination = record_rabies(handler["id"], animal["id"], valid_until=rabies_until)
    policy = create_verified_policy(
        handler["id"], coverage_cents=coverage_cents,
        effective_from=policy_from, effective_until=policy_until,
    )
    certification = issue_certification(team["id"], evaluation["id"])
    certification = activate_certification_ok(certification["id"])
    return {
        "handler": handler,
        "animal": animal,
        "team": team,
        "evaluator": evaluator,
        "evaluation": evaluation,
        "vaccination": vaccination,
        "policy": policy,
        "certification": certification,
    }


def setup_active_facility(*, name: str = "Facility One",
                          facility_type: str = "SCHOOL",
                          region_code: str = "WA",
                          max_visit_minutes: int = 60,
                          allowed_species: Sequence[str] = ("DOG",),
                          min_liability_coverage_cents: int = 100_000_000,
                          max_overlapping_teams: int = 2,
                          visits_per_week_cap: int = 5,
                          required_waiver_version: Optional[str] = None,
                          agreed_max_visit_minutes: int = 90,
                          insurance_minimum_cents: Optional[int] = None,
                          agreement_start: str = "2026-07-01",
                          agreement_end: str = "2027-06-30",
                          terms_version: str = "t1") -> dict:
    """Facility + agreement walked DRAFT -> submit -> sign-facility ->
    sign-program, so the agreement is ACTIVE and the facility is ACTIVE.

    Returns dict(facility, agreement).
    """
    facility_payload = create_facility_payload(
        name=name,
        facility_type=facility_type,
        region_code=region_code,
        max_visit_minutes=max_visit_minutes,
        allowed_species=list(allowed_species),
        min_liability_coverage_cents=min_liability_coverage_cents,
        max_overlapping_teams=max_overlapping_teams,
        visits_per_week_cap=visits_per_week_cap,
    )
    if required_waiver_version is not None:
        facility_payload["required_waiver_version"] = required_waiver_version
    facility = get_success_data(api_client.create_facility(facility_payload, ADMIN))
    agreement = get_success_data(
        api_client.create_facility_agreement(
            create_facility_agreement_payload(
                facility["id"],
                start_on=agreement_start,
                end_on=agreement_end,
                agreed_max_visit_minutes=agreed_max_visit_minutes,
                insurance_minimum_cents=(
                    insurance_minimum_cents
                    if insurance_minimum_cents is not None
                    else min_liability_coverage_cents
                ),
                terms_version=terms_version,
            ),
            ADMIN,
        )
    )
    get_success_data(api_client.submit_facility_agreement(agreement["id"], ADMIN))
    get_success_data(
        api_client.sign_facility_agreement(
            agreement["id"], make_facility_coordinator_headers(facility["id"])
        )
    )
    agreement = get_success_data(api_client.sign_program_agreement(agreement["id"], ADMIN))
    facility = get_success_data(api_client.get_facility(facility["id"], ADMIN))
    return {"facility": facility, "agreement": agreement}


def complete_orientation(team_id: str, facility_id: str,
                         attended_on: str = "2026-08-02") -> dict:
    """Assign + complete orientation for a team at a facility (coordinator of
    that facility). Returns the COMPLETED orientation record."""
    orientation = get_success_data(
        api_client.create_orientation_record(
            create_orientation_payload(team_id), make_facility_coordinator_headers(facility_id)
        )
    )
    return get_success_data(
        api_client.complete_orientation_record(
            orientation["id"], {"attended_on": attended_on},
            make_facility_coordinator_headers(facility_id),
        )
    )


def sign_waiver(handler_id: str, team_id: str, facility_id: str,
                waiver_version: str = "v1", signed_on: str = "2026-08-02") -> dict:
    """Sign a facility liability waiver for an owned team. Returns SIGNED waiver."""
    return get_success_data(
        api_client.create_liability_waiver(
            create_liability_waiver_payload(
                team_id, facility_id, waiver_version=waiver_version, signed_on=signed_on
            ),
            make_handler_headers(handler_id),
        )
    )


def setup_visit_ready_team(team_ctx: dict, fac_ctx: dict,
                           attended_on: str = "2026-08-02",
                           waiver_version: str = "v1",
                           signed_on: str = "2026-08-02") -> dict:
    """Add COMPLETED orientation + SIGNED waiver so the team can be booked at
    the facility. Returns the merged context."""
    orientation = complete_orientation(
        team_ctx["team"]["id"], fac_ctx["facility"]["id"], attended_on
    )
    waiver = sign_waiver(
        team_ctx["handler"]["id"], team_ctx["team"]["id"], fac_ctx["facility"]["id"],
        waiver_version=waiver_version, signed_on=signed_on,
    )
    return {**team_ctx, **fac_ctx, "orientation": orientation, "waiver": waiver}


def setup_certified_team_at_facility(*, team_kwargs: Optional[dict] = None,
                                     facility_kwargs: Optional[dict] = None,
                                     attended_on: str = "2026-08-02",
                                     waiver_version: str = "v1",
                                     signed_on: str = "2026-08-02") -> dict:
    """The canonical fully-bookable scenario: ACTIVE certified team + ACTIVE
    facility + COMPLETED orientation + SIGNED waiver."""
    team_ctx = setup_certified_team(**(team_kwargs or {}))
    fac_ctx = setup_active_facility(**(facility_kwargs or {}))
    return setup_visit_ready_team(
        team_ctx, fac_ctx,
        attended_on=attended_on, waiver_version=waiver_version, signed_on=signed_on,
    )


# ---------------------------------------------------------------------------
# Tier 3: visit lifecycle shortcuts
# ---------------------------------------------------------------------------

def get_team_version(team_id: str) -> int:
    return get_success_data(api_client.get_team(team_id, ADMIN))["version"]


def schedule_visit_ok(team_id: str, facility_id: str, start: str, end: str) -> dict:
    """Directly schedule a visit (reads the team's current version for OCC)."""
    version = get_team_version(team_id)
    return get_success_data(
        api_client.create_visit(
            create_visit_payload(team_id, facility_id, start, end, version), ADMIN
        )
    )


def check_in_visit_ok(visit_id: str, handler_id: str, at: str) -> dict:
    """Set the clock and check in. Returns the IN_PROGRESS visit."""
    set_clock(at)
    return get_success_data(api_client.check_in_visit(visit_id, make_handler_headers(handler_id)))


def check_out_visit_ok(visit_id: str, handler_id: str, at: str) -> dict:
    """Set the clock and check out. Returns the COMPLETED visit."""
    set_clock(at)
    return get_success_data(api_client.check_out_visit(visit_id, make_handler_headers(handler_id)))


def complete_visit_ok(visit_id: str, handler_id: str,
                      checkin_at: str, checkout_at: str) -> dict:
    """Check in at checkin_at and check out at checkout_at. Returns COMPLETED visit."""
    check_in_visit_ok(visit_id, handler_id, checkin_at)
    return check_out_visit_ok(visit_id, handler_id, checkout_at)


def verify_visit_ok(visit_id: str, facility_id: str) -> dict:
    """Facility coordinator verifies a completed visit. Returns VERIFIED visit."""
    return get_success_data(
        api_client.verify_visit(visit_id, make_facility_coordinator_headers(facility_id))
    )


def complete_and_verify_visit(ctx: dict, start: str, end: str,
                              checkin_at: Optional[str] = None,
                              checkout_at: Optional[str] = None) -> dict:
    """Schedule + complete + verify a visit in one call. Returns the VERIFIED visit."""
    visit = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"], start, end)
    complete_visit_ok(visit["id"], ctx["handler"]["id"], checkin_at or start, checkout_at or end)
    return verify_visit_ok(visit["id"], ctx["facility"]["id"])


# ---------------------------------------------------------------------------
# Tier 3b: visit requests / offers
# ---------------------------------------------------------------------------

def create_request_ok(facility_id: str, start: str, end: str,
                      visit_program: str = "GENERAL", priority: str = "ROUTINE",
                      species_preference: Optional[str] = None) -> dict:
    """Post an OPEN visit request for a facility (coordinator identity)."""
    payload = create_visit_request_payload(
        requested_start=start, requested_end=end,
        visit_program=visit_program, priority=priority,
    )
    if species_preference is not None:
        payload["species_preference"] = species_preference
    return get_success_data(
        api_client.create_visit_request(payload, make_facility_coordinator_headers(facility_id))
    )


def get_request_version(request_id: str) -> int:
    return get_success_data(api_client.get_visit_request(request_id, ADMIN))["version"]


def offer_request_ok(request_id: str, team_id: str) -> dict:
    """Offer an OPEN request to a team (reads the current request version)."""
    version = get_request_version(request_id)
    return get_success_data(
        api_client.create_offer(
            request_id, {"team_id": team_id, "expected_visit_request_version": version}, ADMIN
        )
    )


def accept_request_ok(request_id: str, handler_id: str) -> dict:
    """The offered team's handler accepts. Returns the created SCHEDULED Visit."""
    return get_success_data(
        api_client.accept_visit_request(request_id, make_handler_headers(handler_id))
    )


def setup_accepted_request(ctx: dict, start: str = "2026-08-10T14:00:00Z",
                           end: str = "2026-08-10T15:00:00Z",
                           **request_kwargs) -> dict:
    """Create a request, offer it to the context's team, and accept it.
    Returns dict(request, visit)."""
    request = create_request_ok(ctx["facility"]["id"], start, end, **request_kwargs)
    offer_request_ok(request["id"], ctx["team"]["id"])
    visit = accept_request_ok(request["id"], ctx["handler"]["id"])
    return {"request": request, "visit": visit}


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def post_adjustment(handler_id: str, minutes: int, reason: str = "seed",
                    officer_headers: Optional[dict] = None) -> dict:
    """Post a manual hour adjustment. Returns the ADJUSTMENT ledger row."""
    return get_success_data(
        api_client.create_hour_adjustment(
            create_adjustment_payload(handler_id, minutes, reason),
            officer_headers or COMPLIANCE,
        )
    )


def seed_lifetime(handler_id: str, minutes: int) -> None:
    """Seed a handler's lifetime_minutes via a single adjustment."""
    post_adjustment(handler_id, minutes, reason="seed")


def list_hour_credits_for(handler_id: Optional[str] = None,
                          visit_id: Optional[str] = None) -> List[dict]:
    """List hour-credit rows filtered by handler and/or visit."""
    params = {}
    if handler_id is not None:
        params["handler_id"] = handler_id
    if visit_id is not None:
        params["visit_id"] = visit_id
    data, _meta = _list_paginated(api_client.list_hour_credits(ADMIN, params=params))
    return data


def _list_paginated(response):
    """Internal: validate a paginated response and return (data, meta)."""
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


def get_handler(handler_id: str) -> dict:
    return get_success_data(api_client.get_handler(handler_id, ADMIN))


def get_animal(animal_id: str) -> dict:
    return get_success_data(api_client.get_animal(animal_id, ADMIN))


def get_team(team_id: str) -> dict:
    return get_success_data(api_client.get_team(team_id, ADMIN))


def get_certification(certification_id: str) -> dict:
    return get_success_data(api_client.get_certification(certification_id, ADMIN))


def get_facility(facility_id: str) -> dict:
    return get_success_data(api_client.get_facility(facility_id, ADMIN))


def get_visit(visit_id: str) -> dict:
    return get_success_data(api_client.get_visit(visit_id, ADMIN))


def get_visit_request(request_id: str) -> dict:
    return get_success_data(api_client.get_visit_request(request_id, ADMIN))


def get_orientation_record(record_id: str) -> dict:
    return get_success_data(api_client.get_orientation_record(record_id, ADMIN))


def get_recognition(handler_id: str) -> dict:
    return get_success_data(api_client.get_handler_recognition(handler_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 5: renewal-ready certification (six verified visits inside the term)
# ---------------------------------------------------------------------------

def setup_renewable_certification(*, rabies_until: str = "2029-12-31",
                                  policy_until: str = "2029-12-31",
                                  facility_kwargs: Optional[dict] = None) -> dict:
    """Certified team + ACTIVE facility + six COMPLETED+VERIFIED 30-minute
    visits on 2026-08-03..2026-08-05 (two per day), inside the certification
    window. Returns the visit-ready context with key 'visits'."""
    ctx = setup_certified_team_at_facility(
        team_kwargs={"rabies_until": rabies_until, "policy_until": policy_until},
        facility_kwargs={"visits_per_week_cap": 8, **(facility_kwargs or {})},
    )
    slots = [
        ("2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z"),
        ("2026-08-03T11:30:00Z", "2026-08-03T12:00:00Z"),
        ("2026-08-04T10:00:00Z", "2026-08-04T10:30:00Z"),
        ("2026-08-04T11:30:00Z", "2026-08-04T12:00:00Z"),
        ("2026-08-05T10:00:00Z", "2026-08-05T10:30:00Z"),
        ("2026-08-05T11:30:00Z", "2026-08-05T12:00:00Z"),
    ]
    visits = [complete_and_verify_visit(ctx, start, end) for start, end in slots]
    ctx["visits"] = visits
    return ctx


def file_incident_ok(visit_id: str, filer_headers: dict,
                     severity: str = "HIGH", category: str = "ANIMAL_STRESS",
                     description: str = "animal showed sustained stress signals") -> dict:
    """File an incident against an IN_PROGRESS or COMPLETED visit."""
    return get_success_data(
        api_client.create_incident_report(
            create_incident_payload(
                visit_id, severity=severity, category=category, description=description
            ),
            filer_headers,
        )
    )


def triage_incident_ok(incident_id: str, officer_headers: Optional[dict] = None) -> dict:
    """Triage a FILED incident. Returns the UNDER_REVIEW incident."""
    return get_success_data(
        api_client.triage_incident(incident_id, officer_headers or COMPLIANCE)
    )
