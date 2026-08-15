"""Composite setup helpers.

Every helper builds its world through the public API only. The server is
restarted with an empty database before each test, so helpers never assume any
pre-existing row and every test re-creates whatever it needs.

Naming convention: setup_* helpers return a dict of named entities so test
code can pick the parts it cares about.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    COLLECTOR_USER, DEFAULT_CERTIFICATION_EXPIRY, DEFAULT_CONSENT_EXPIRY,
    DIRECTOR_USER, LEAD_USER, PRIVACY_USER, STEWARD_USER,
)
from .factories import (
    certification_payload, consent_payload, cycle_payload, engagement_payload,
    finding_payload, funder_payload, improvement_action_payload,
    indicator_payload, instrument_payload, logic_model_payload,
    milestone_payload, observation_payload, participant_payload,
    program_payload, report_payload,
)
from .test_users import (
    DIRECTOR, LEAD, PRIVACY, STEWARD,
    make_data_steward_headers, make_field_collector_headers,
)


# ==========================================================================
# Tier 0 -- single-call primitives
# ==========================================================================

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, DIRECTOR))


def create_program(name="Test Program", code="TP", **overrides) -> dict:
    return get_success_data(api_client.create_program(
        program_payload(name=name, code=code, **overrides), DIRECTOR))


def create_active_program(name="Test Program", code="TP", **overrides) -> dict:
    prog = create_program(name=name, code=code, **overrides)
    return get_success_data(api_client.activate_program(prog["id"], DIRECTOR))


def create_funder(name="Test Funder", code="FND", **overrides) -> dict:
    return get_success_data(api_client.create_funder(
        funder_payload(name=name, code=code, **overrides), DIRECTOR))


def create_logic_model(program_id, title="Logic Model", **overrides) -> dict:
    return get_success_data(api_client.create_logic_model(
        program_id, logic_model_payload(title=title, **overrides), LEAD))


def create_indicator(model_id, code="I1", **overrides) -> dict:
    return get_success_data(api_client.create_indicator(
        model_id, indicator_payload(code=code, **overrides), LEAD))


def create_cycle(program_id, **overrides) -> dict:
    return get_success_data(api_client.create_cycle(
        program_id, cycle_payload(**overrides), DIRECTOR))


def enroll_participant(cycle_id, external_ref="P-001") -> dict:
    return get_success_data(api_client.enroll_participant(
        cycle_id, participant_payload(external_ref=external_ref), DIRECTOR))


def grant_consent(participant_id, form_version=1, scope="FULL",
                  expires_at=DEFAULT_CONSENT_EXPIRY) -> dict:
    return get_success_data(api_client.grant_consent(
        participant_id,
        consent_payload(form_version=form_version, scope=scope, expires_at=expires_at),
        PRIVACY))


def create_instrument(program_id, code="SURV", title="Survey") -> dict:
    return get_success_data(api_client.create_instrument(
        program_id, instrument_payload(code=code, title=title), LEAD))


def publish_instrument(instrument_id) -> dict:
    return get_success_data(api_client.publish_instrument(instrument_id, LEAD))


def create_certification(instrument_id, staff_user_id=COLLECTOR_USER,
                         expires_at=DEFAULT_CERTIFICATION_EXPIRY) -> dict:
    return get_success_data(api_client.create_certification(
        certification_payload(staff_user_id=staff_user_id,
                              instrument_id=instrument_id,
                              expires_at=expires_at),
        LEAD))


def record_observation(participant_id, indicator_id, instrument_id, value,
                       collected_at="2026-09-05T00:00:00Z",
                       collector_user=COLLECTOR_USER) -> dict:
    return get_success_data(api_client.record_observation(
        participant_id,
        observation_payload(indicator_id=indicator_id, instrument_id=instrument_id,
                            value=value, collected_at=collected_at),
        make_field_collector_headers(collector_user)))


def validate_observation(observation_id, steward_user=STEWARD_USER) -> dict:
    return get_success_data(api_client.validate_observation(
        observation_id, make_data_steward_headers(steward_user)))


# ==========================================================================
# Tier 1 -- state progression helpers
# ==========================================================================

def approve_logic_model(model_id, program_id) -> dict:
    """Submit + approve a logic model under OCC on the parent program."""
    get_success_data(api_client.submit_logic_model(model_id, LEAD))
    program = get_success_data(api_client.get_program(program_id, DIRECTOR))
    return get_success_data(api_client.approve_logic_model(
        model_id, {"expected_program_version": program["version"]}, LEAD))


def activate_cycle(cycle_id) -> dict:
    """ENROLLING -> ACTIVE (cycle must already be ENROLLING)."""
    return get_success_data(api_client.activate_cycle(cycle_id, DIRECTOR))


# ==========================================================================
# Tier 2 -- entity hierarchy helpers
# ==========================================================================

def setup_program_with_approved_model(program_name="Prog", program_code="PRG",
                                      indicator_specs=None):
    """Active program + one APPROVED logic model carrying the given indicators.

    indicator_specs: list of dicts passed to indicator_payload as overrides.
    Defaults to a single HIGHER_IS_BETTER indicator I1 0->100.

    Returns {"program": ..., "model": ..., "indicators": {code: indicator}}.
    """
    if indicator_specs is None:
        indicator_specs = [{"code": "I1"}]
    program = create_active_program(name=program_name, code=program_code)
    model = create_logic_model(program["id"])
    indicators = {}
    for spec in indicator_specs:
        spec = dict(spec)
        code = spec.pop("code", "I1")
        indicators[code] = create_indicator(model["id"], code=code, **spec)
    approve_logic_model(model["id"], program["id"])
    return {"program": program, "model": model, "indicators": indicators}


def setup_active_cycle(program, **cycle_overrides):
    """Create a cycle under the given ACTIVE program, open enrollment and
    activate it (pins program.current_logic_model_id)."""
    cycle = create_cycle(program["id"], **cycle_overrides)
    get_success_data(api_client.open_enrollment(cycle["id"], DIRECTOR))
    return activate_cycle(cycle["id"])


def setup_participant_with_consent(cycle_id, external_ref="P-001",
                                   form_version=1,
                                   consent_expires_at=DEFAULT_CONSENT_EXPIRY):
    """Enroll a participant and grant CURRENT consent so the participant
    transitions ENROLLED -> ACTIVE."""
    participant = enroll_participant(cycle_id, external_ref=external_ref)
    consent = grant_consent(participant["id"], form_version=form_version,
                            expires_at=consent_expires_at)
    participant = get_success_data(api_client.get_participant(participant["id"], DIRECTOR))
    return {"participant": participant, "consent": consent}


def setup_published_instrument(program_id, code="SURV", title="Survey",
                               certify_collector=COLLECTOR_USER,
                               certification_expires_at=DEFAULT_CERTIFICATION_EXPIRY):
    """Create an instrument, publish it, and (optionally) certify a collector.

    Returns {"instrument": ..., "certification": ...|None}.
    """
    instrument = create_instrument(program_id, code=code, title=title)
    instrument = publish_instrument(instrument["id"])
    certification = None
    if certify_collector is not None:
        certification = create_certification(
            instrument["id"], staff_user_id=certify_collector,
            expires_at=certification_expires_at)
    return {"instrument": instrument, "certification": certification}


# ==========================================================================
# Tier 3 -- full observation-capable world
# ==========================================================================

def setup_observation_world(program_name="Prog", program_code="PRG",
                            indicator_specs=None,
                            participant_ref="P-001",
                            collector_user=COLLECTOR_USER,
                            **cycle_overrides):
    """The canonical 'ready to record observations' world used across the
    suite: ACTIVE program with APPROVED model, ACTIVE cycle with pinned model,
    one ACTIVE participant with CURRENT consent, PUBLISHED instrument, and a
    CERTIFIED certification for `collector_user`.

    Returns a dict with program, model, indicators, cycle, participant,
    consent, instrument, certification.
    """
    base = setup_program_with_approved_model(
        program_name=program_name, program_code=program_code,
        indicator_specs=indicator_specs)
    cycle = setup_active_cycle(base["program"], **cycle_overrides)
    pc = setup_participant_with_consent(cycle["id"], external_ref=participant_ref)
    ic = setup_published_instrument(base["program"]["id"],
                                    certify_collector=collector_user)
    return {
        "program": base["program"],
        "model": base["model"],
        "indicators": base["indicators"],
        "cycle": cycle,
        "participant": pc["participant"],
        "consent": pc["consent"],
        "instrument": ic["instrument"],
        "certification": ic["certification"],
        "collector_user": collector_user,
    }


def record_and_validate(participant_id, indicator_id, instrument_id, value,
                        collected_at="2026-09-05T00:00:00Z",
                        collector_user=COLLECTOR_USER,
                        steward_user=STEWARD_USER) -> dict:
    """Record an observation and validate it with a different steward."""
    observation = record_observation(
        participant_id, indicator_id, instrument_id, value,
        collected_at=collected_at, collector_user=collector_user)
    return validate_observation(observation["id"], steward_user=steward_user)


def setup_cycle_under_review(program_name="Prog", program_code="PRG",
                             indicator_specs=None,
                             validated_values=None,
                             pending_values=None,
                             collector_user=COLLECTOR_USER,
                             **cycle_overrides):
    """Build the canonical reporting world: ACTIVE program, APPROVED model,
    ACTIVE cycle, one consented participant, PUBLISHED instrument, CERTIFIED
    collector. Records `validated_values` (each validated by a steward) and
    `pending_values` (left PENDING) on the indicators in cycle order, then
    closes data, opens an audit (populating cycle.latest_dq_score), and moves
    the cycle to UNDER_REVIEW.

    validated_values / pending_values: lists of (indicator_code, value) pairs.
    Returns a dict including the audit.
    """
    world = setup_observation_world(
        program_name=program_name, program_code=program_code,
        indicator_specs=indicator_specs, collector_user=collector_user,
        **cycle_overrides)
    first_code = next(iter(world["indicators"]))
    for code, value in (validated_values or []):
        record_and_validate(world["participant"]["id"],
                            world["indicators"][code or first_code]["id"],
                            world["instrument"]["id"], value,
                            collector_user=collector_user)
    for code, value in (pending_values or []):
        record_observation(world["participant"]["id"],
                           world["indicators"][code or first_code]["id"],
                           world["instrument"]["id"], value,
                           collector_user=collector_user)
    cycle = get_success_data(api_client.close_data(world["cycle"]["id"], DIRECTOR))
    audit = get_success_data(api_client.open_audit(
        cycle["id"], make_data_steward_headers(STEWARD_USER)))
    cycle = get_success_data(api_client.begin_review(cycle["id"], DIRECTOR))
    world["cycle"] = cycle
    world["audit"] = audit
    return world


def setup_draft_report(world, funder=None, report_type="FUNDER_STANDARD"):
    """Under a cycle already in UNDER_REVIEW: create an ACTIVE funder (unless
    one is supplied) and a DRAFT report pinned to the cycle's current
    version."""
    if funder is None:
        funder = create_funder(name="Foundation", code="FND-X")
    cycle = get_success_data(api_client.get_cycle(world["cycle"]["id"], DIRECTOR))
    report = get_success_data(api_client.create_report(
        world["cycle"]["id"],
        report_payload(funder_id=funder["id"], report_type=report_type,
                       expected_program_cycle_version=cycle["version"]),
        LEAD))
    return {"funder": funder, "report": report}


def setup_generated_report(world, funder=None, report_type="FUNDER_STANDARD"):
    """DRAFT report driven to GENERATED."""
    draft = setup_draft_report(world, funder=funder, report_type=report_type)
    report = get_success_data(api_client.generate_report(draft["report"]["id"], LEAD))
    draft["report"] = report
    return draft


def setup_delivered_report(world, funder=None, report_type="FUNDER_STANDARD"):
    """DRAFT -> GENERATED -> DELIVERED."""
    gen = setup_generated_report(world, funder=funder, report_type=report_type)
    report = get_success_data(api_client.deliver_report(gen["report"]["id"], LEAD))
    gen["report"] = report
    return gen


# ==========================================================================
# Tier 4 -- audit / finding helpers
# ==========================================================================

def open_audit_for_cycle(cycle_id, steward_user=STEWARD_USER) -> dict:
    return get_success_data(api_client.open_audit(
        cycle_id, make_data_steward_headers(steward_user)))


def record_finding(audit_id, participant_id, finding_type="MISSING_DATA",
                   description="", steward_user=STEWARD_USER, **overrides) -> dict:
    return get_success_data(api_client.record_finding(
        audit_id,
        finding_payload(finding_type=finding_type, participant_id=participant_id,
                        description=description, **overrides),
        make_data_steward_headers(steward_user)))


# ==========================================================================
# Tier 5 -- vendor engagement and improvement action helpers
# ==========================================================================

def create_engagement(program_id, scope_cycle_ids, vendor_name="EvalCo",
                      access_start="2026-08-01T00:00:00Z",
                      access_end="2026-09-01T00:00:00Z",
                      deliverable_due="2026-09-10T00:00:00Z") -> dict:
    return get_success_data(api_client.create_engagement(
        program_id,
        engagement_payload(vendor_name=vendor_name,
                           scope_program_cycle_ids=scope_cycle_ids,
                           access_start=access_start,
                           access_end=access_end,
                           deliverable_due=deliverable_due),
        DIRECTOR))


def create_improvement_action(program_id, title="Tighten SOP",
                              description="retrain collectors",
                              creator_user=LEAD_USER, **overrides) -> dict:
    from .test_users import make_evaluation_lead_headers
    return get_success_data(api_client.create_improvement_action(
        program_id,
        improvement_action_payload(title=title, description=description, **overrides),
        make_evaluation_lead_headers(creator_user)))
