"""Composite setup helpers for multi-step test prerequisites.

Each pytest test runs against a freshly-restarted, empty server, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. Fixtures
use get_success_data() (lenient) so setup failures surface as a clear "Setup
failed" rather than a confusing assertion failure.

Identity threading: Sponsor is entity-backed. Every ownership-gated sponsor call
(programs, journeyworkers, apprentices, agreements, OJT entries, milestone
attainments, EEO reports) threads the real Sponsor.id through
make_sponsor_headers(sponsor_id). RegistrationAgency and TrainingCoordinator are
opaque operators and use the shared headers.

These fixtures return plain dicts. The common pattern objects are bundled in a
ScenarioBundle namedtuple so a test can pick out exactly what it needs.
"""
from collections import namedtuple

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_sponsor_headers, make_apprentice_headers
from .constants import WAGE_LADDER_4
from .factories import (
    create_sponsor_payload,
    create_program_payload,
    create_wage_step_payload,
    create_milestone_payload,
    create_journeyworker_payload,
    create_apprentice_payload,
    create_agreement_payload,
    register_agreement_payload,
    create_ojt_entry_payload,
    create_rti_record_payload,
    create_milestone_attainment_payload,
    create_eeo_report_payload,
)

AGENCY = TEST_USERS["registration_agency_headers"]
COORD = TEST_USERS["training_coordinator_headers"]


# ===========================================================================
# Tier 0: primitives
# ===========================================================================
def create_sponsor(**overrides) -> dict:
    """Create a sponsor. Returns the sponsor dict."""
    return get_success_data(
        api_client.create_sponsor(create_sponsor_payload(**overrides), AGENCY)
    )


def create_journeyworker(sponsor_id: str, **overrides) -> dict:
    """Create a PROBATIONARY journeyworker under a sponsor."""
    return get_success_data(
        api_client.create_journeyworker(
            create_journeyworker_payload(sponsor_id, **overrides),
            make_sponsor_headers(sponsor_id),
        )
    )


def create_qualified_journeyworker(sponsor_id: str, **overrides) -> dict:
    """Create a journeyworker and promote it to QUALIFIED."""
    jw = create_journeyworker(sponsor_id, **overrides)
    return get_success_data(
        api_client.qualify_journeyworker(jw["id"], make_sponsor_headers(sponsor_id))
    )


def create_apprentice(sponsor_id: str, **overrides) -> dict:
    """Create an apprentice with EEO demographics under a sponsor."""
    return get_success_data(
        api_client.create_apprentice(
            create_apprentice_payload(sponsor_id, **overrides),
            make_sponsor_headers(sponsor_id),
        )
    )


def add_wage_step(program_id: str, sponsor_id: str, step_number: int,
                  ojt_hours_threshold: int, wage_pct: float) -> dict:
    return get_success_data(
        api_client.create_wage_step(
            create_wage_step_payload(program_id, step_number, ojt_hours_threshold, wage_pct),
            make_sponsor_headers(sponsor_id),
        )
    )


def add_milestone(program_id: str, sponsor_id: str, sequence: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_milestone(
            create_milestone_payload(program_id, sequence, **overrides),
            make_sponsor_headers(sponsor_id),
        )
    )


# ===========================================================================
# Tier 1: program state progression
# ===========================================================================
def create_draft_program(sponsor_id: str, wage_ladder=None, milestones=None,
                          **program_overrides) -> dict:
    """Create a DRAFT program and (optionally) populate its wage ladder and
    milestones while it is still DRAFT.

    wage_ladder: list of (step_number, threshold, pct); defaults to the single
        base step [(1, 0, 0.50)]. Pass WAGE_LADDER_4 for the full four-step ladder.
    milestones: list of dicts of milestone overrides (each gets sequence i+1).
    Returns the program dict (re-read so it reflects nothing yet beyond create).
    """
    program = get_success_data(
        api_client.create_program(
            create_program_payload(sponsor_id, **program_overrides),
            make_sponsor_headers(sponsor_id),
        )
    )
    ladder = wage_ladder if wage_ladder is not None else [(1, 0, 0.50)]
    for step_number, threshold, pct in ladder:
        add_wage_step(program["id"], sponsor_id, step_number, threshold, pct)
    if milestones:
        for i, ms in enumerate(milestones):
            add_milestone(program["id"], sponsor_id, i + 1, **ms)
    return program


def create_active_program(sponsor_id: str, wage_ladder=None, milestones=None,
                          **program_overrides) -> dict:
    """Create a DRAFT program with wage ladder/milestones then activate it.

    Returns the ACTIVE program dict (the activate response, which carries the
    bumped version)."""
    program = create_draft_program(
        sponsor_id, wage_ladder=wage_ladder, milestones=milestones, **program_overrides
    )
    return get_success_data(api_client.activate_program(program["id"], AGENCY))


# ===========================================================================
# Tier 2: agreement lifecycle shortcuts
# ===========================================================================
def create_draft_agreement(sponsor_id: str, program_id: str, apprentice_id: str,
                           journeyworker_id: str, **overrides) -> dict:
    """Create a DRAFT agreement linking apprentice, program, journeyworker."""
    return get_success_data(
        api_client.create_agreement(
            create_agreement_payload(program_id, apprentice_id, journeyworker_id, **overrides),
            make_sponsor_headers(sponsor_id),
        )
    )


def register_agreement(sponsor_id: str, agreement_id: str, program_version: int) -> dict:
    """Register a DRAFT agreement against the program version. Returns response."""
    return get_success_data(
        api_client.register_agreement(
            agreement_id,
            register_agreement_payload(program_version),
            make_sponsor_headers(sponsor_id),
        )
    )


def current_program_version(sponsor_id: str, program_id: str) -> int:
    prog = get_success_data(
        api_client.get_program(program_id, make_sponsor_headers(sponsor_id))
    )
    return prog["version"]


def create_active_agreement(sponsor_id: str, program_id: str, apprentice_id: str,
                            journeyworker_id: str, program_version: int = None,
                            **overrides) -> dict:
    """Create -> register -> activate an agreement. Returns the ACTIVE agreement.

    If program_version is None it is read fresh from the program before register.
    """
    agr = create_draft_agreement(
        sponsor_id, program_id, apprentice_id, journeyworker_id, **overrides
    )
    pv = program_version if program_version is not None else current_program_version(sponsor_id, program_id)
    register_agreement(sponsor_id, agr["id"], pv)
    return get_success_data(
        api_client.activate_agreement(agr["id"], make_sponsor_headers(sponsor_id))
    )


# ===========================================================================
# Tier 3: training data (OJT / RTI / milestone attainment)
# ===========================================================================
def log_ojt_entry(sponsor_id: str, agreement_id: str, start_time: int, end_time: int,
                  credited_hours: float, **overrides) -> dict:
    """Log a PENDING OJT session (as the sponsor)."""
    return get_success_data(
        api_client.create_ojt_entry(
            create_ojt_entry_payload(agreement_id, start_time, end_time, credited_hours, **overrides),
            make_sponsor_headers(sponsor_id),
        )
    )


def log_and_approve_ojt(sponsor_id: str, agreement_id: str, start_time: int,
                        end_time: int, credited_hours: float, **overrides) -> dict:
    """Log a PENDING OJT entry then have the coordinator approve it. Returns the
    approved entry (the approve response)."""
    entry = log_ojt_entry(sponsor_id, agreement_id, start_time, end_time, credited_hours, **overrides)
    return get_success_data(api_client.approve_ojt_entry(entry["id"], COORD))


def record_rti(sponsor_id: str, agreement_id: str, instruction_hours: float, **overrides) -> dict:
    """Record an RTI session (as the sponsor)."""
    return get_success_data(
        api_client.create_rti_record(
            create_rti_record_payload(agreement_id, instruction_hours, **overrides),
            make_sponsor_headers(sponsor_id),
        )
    )


def submit_attainment(sponsor_id: str, agreement_id: str, milestone_id: str, **overrides) -> dict:
    """Submit a milestone attainment (as the sponsor). Returns SUBMITTED attainment."""
    return get_success_data(
        api_client.create_milestone_attainment(
            create_milestone_attainment_payload(agreement_id, milestone_id, **overrides),
            make_sponsor_headers(sponsor_id),
        )
    )


def submit_and_approve_attainment(sponsor_id: str, agreement_id: str, milestone_id: str,
                                  **overrides) -> dict:
    """Submit a milestone attainment then have the coordinator approve it."""
    att = submit_attainment(sponsor_id, agreement_id, milestone_id, **overrides)
    return get_success_data(api_client.approve_milestone_attainment(att["id"], COORD))


# ===========================================================================
# Tier 4: bundled end-to-end scenarios
# ===========================================================================
Scenario = namedtuple(
    "Scenario",
    ["sponsor_id", "journeyworker_id", "apprentice_id", "program_id", "agreement_id"],
)


def setup_active_agreement(completion_type="HOURS_BASED", wage_ladder=None,
                           milestones=None, journeyman_ratio=4,
                           agreement_overrides=None, **program_overrides) -> Scenario:
    """Sponsor + QUALIFIED journeyworker + apprentice + ACTIVE program (with the
    given wage ladder / milestones) + an ACTIVE agreement. The single most common
    precondition for OJT / milestone / completion tests.

    Returns a Scenario bundle of ids.
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    program = create_active_program(
        sponsor["id"], wage_ladder=wage_ladder, milestones=milestones,
        completion_type=completion_type, journeyman_ratio=journeyman_ratio,
        **program_overrides,
    )
    agr = create_active_agreement(
        sponsor["id"], program["id"], ap["id"], jw["id"],
        program_version=program["version"], **(agreement_overrides or {}),
    )
    return Scenario(sponsor["id"], jw["id"], ap["id"], program["id"], agr["id"])


def setup_completion_ready_agreement(completion_type="HOURS_BASED",
                                     ojt_hours_required=16, rti_hours_required=8,
                                     milestones=None) -> Scenario:
    """An ACTIVE agreement that has met its HOURS_BASED completion requirements:
    16 approved OJT hours + 8 RTI hours. Used by complete / certificate tests.

    For COMPETENCY_BASED / HYBRID callers pass the matching milestones and the
    caller is responsible for approving them.
    """
    scenario = setup_active_agreement(
        completion_type=completion_type, wage_ladder=[(1, 0, 0.50)],
        milestones=milestones, ojt_hours_required=ojt_hours_required,
        rti_hours_required=rti_hours_required,
    )
    log_and_approve_ojt(scenario.sponsor_id, scenario.agreement_id, 0, 600, ojt_hours_required)
    record_rti(scenario.sponsor_id, scenario.agreement_id, rti_hours_required)
    return scenario


def complete_agreement(agreement_id: str) -> dict:
    """Have the RegistrationAgency complete an eligible ACTIVE agreement."""
    return get_success_data(api_client.complete_agreement(agreement_id, AGENCY))


def setup_completed_agreement_with_certificate() -> tuple:
    """Drive a HOURS_BASED agreement all the way to COMPLETED and fetch its
    cascade-created CompletionCertificate.

    Returns (scenario, certificate_dict).
    """
    scenario = setup_completion_ready_agreement()
    complete_agreement(scenario.agreement_id)
    certs = get_success_data(
        api_client.list_certificates(
            make_sponsor_headers(scenario.sponsor_id),
            params={"agreement_id": scenario.agreement_id},
        )
    )
    return scenario, (certs[0] if certs else None)
