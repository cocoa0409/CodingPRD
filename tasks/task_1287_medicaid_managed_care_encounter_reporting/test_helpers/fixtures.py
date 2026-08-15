"""Composite setup helpers.

The reporting pipeline's interesting claims all require multi-step state: a cycle
plus roster, an acknowledged encounter (create -> validate -> stage -> seal ->
transmit -> acknowledge), an assessed penalty, a determined audit, and so on.
These helpers encapsulate the repeated chains so tests can assert, not plumb.

All helpers use get_success_data() internally so a setup failure surfaces as a
clear "Setup failed" error instead of a confusing assertion failure.
"""
import uuid as _uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import EDIT_CODES, TEST_DEFAULTS
from .factories import (
    create_audit_payload,
    create_batch_payload,
    create_cycle_payload,
    create_encounter_line,
    create_encounter_payload,
    create_member_payload,
    create_program_payload,
    create_provider_payload,
    create_rate_schedule_payload,
    create_replace_payload,
    create_statement_payload,
    create_submitter_payload,
)
from .test_users import (
    make_delegated_submitter_headers,
    make_mco_compliance_headers,
    make_mco_encounter_ops_headers,
    make_mco_finance_headers,
    make_state_agency_headers,
)

# ---------------------------------------------------------------------------
# Header shorthands (opaque operator ids; segregation-of-duties-safe pairs)
# ---------------------------------------------------------------------------
STATE = make_state_agency_headers("fx-state-1")
OPS = make_mco_encounter_ops_headers("fx-ops-1")
FIN = make_mco_finance_headers("fx-finance-1")
# Sealer and transmitter MUST be different X-User-ID values (PRD segregation of duties).
OPS_SEALER = make_mco_encounter_ops_headers(TEST_DEFAULTS["OPS_SEALER_USER_ID"])
COMP_TRANSMITTER = make_mco_compliance_headers(TEST_DEFAULTS["COMPLIANCE_TRANSMITTER_USER_ID"])


def _uid(prefix: str) -> str:
    return f"{prefix}-{_uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators
# ---------------------------------------------------------------------------

def create_program(name="Test Program", penalty_threshold_cents=TEST_DEFAULTS["SAFE_PENALTY_THRESHOLD_CENTS"], **overrides):
    """Create a program. Returns program data."""
    payload = create_program_payload(name=name, penalty_threshold_cents=penalty_threshold_cents, **overrides)
    return get_success_data(api_client.create_program(payload, STATE))


def create_cycle(program_id, **overrides):
    """Create an August 2026 submission cycle (overridable). Returns cycle data."""
    return get_success_data(api_client.create_cycle(create_cycle_payload(program_id, **overrides), STATE))


def create_rate_schedule(program_id, aid_category="TANF", pmpm_cents=TEST_DEFAULTS["PMPM_TANF_CENTS"], **overrides):
    return get_success_data(api_client.create_rate_schedule(
        create_rate_schedule_payload(program_id, aid_category=aid_category, pmpm_cents=pmpm_cents, **overrides), STATE))


def create_member(program_id, aid_category="TANF", medicaid_id=None, **overrides):
    return get_success_data(api_client.create_member(
        create_member_payload(program_id, aid_category=aid_category, medicaid_id=medicaid_id or _uid("M"), **overrides), OPS))


def create_provider(program_id, npi=None, **overrides):
    # NPI must be exactly ten digits (PRD §3.2); derive a unique digits-only value.
    digits_only_npi = npi or f"9{_uuid.uuid4().int % 10**9:09d}"
    return get_success_data(api_client.create_provider(
        create_provider_payload(program_id, npi=digits_only_npi, **overrides), OPS))


def create_submitter(program_id, **overrides):
    payload = create_submitter_payload(program_id, trading_partner_id=_uid("TP"), **overrides)
    return get_success_data(api_client.create_submitter(payload, OPS))


def create_encounter(program_id, member_id, provider_id, encounter_ref=None, **overrides):
    """Create an encounter (RECEIVED). Returns encounter data."""
    payload = create_encounter_payload(program_id, member_id, provider_id,
                                       encounter_ref=encounter_ref or _uid("E"), **overrides)
    return get_success_data(api_client.create_encounter(payload, OPS))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, STATE))


# ---------------------------------------------------------------------------
# Tier 2: base scenario (program + cycle + roster)
# ---------------------------------------------------------------------------

def setup_basic_scenario(program_name="P-BASE", penalty_threshold_cents=TEST_DEFAULTS["SAFE_PENALTY_THRESHOLD_CENTS"],
                         with_rate_schedule=False, aid_category="TANF", pmpm_cents=TEST_DEFAULTS["PMPM_TANF_CENTS"]):
    """Program + August cycle + one member + one provider.

    Returns dict(program, cycle, member, provider, rate_schedule|None).
    """
    program = create_program(name=program_name, penalty_threshold_cents=penalty_threshold_cents)
    cycle = create_cycle(program["id"])
    rate_schedule = None
    if with_rate_schedule:
        rate_schedule = create_rate_schedule(program["id"], aid_category=aid_category, pmpm_cents=pmpm_cents)
    member = create_member(program["id"], aid_category=aid_category)
    provider = create_provider(program["id"])
    return {
        "program": program,
        "cycle": cycle,
        "member": member,
        "provider": provider,
        "rate_schedule": rate_schedule,
    }


# ---------------------------------------------------------------------------
# Tier 3: encounter lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_validated_encounter(program_id, cycle_id, member_id, provider_id, encounter_ref=None, **overrides):
    """Create an encounter and validate it to VALIDATED (payload must be clean)."""
    encounter = create_encounter(program_id, member_id, provider_id, encounter_ref=encounter_ref, **overrides)
    assert encounter["attributed_cycle_id"] == cycle_id, (
        f"Setup failed: encounter attributed to {encounter['attributed_cycle_id']}, expected {cycle_id}"
    )
    validated = get_success_data(api_client.validate_encounter(encounter["id"], OPS))
    assert validated["status"] == "VALIDATED", f"Setup failed: encounter is {validated['status']}, expected VALIDATED"
    return validated


def create_batch(cycle_id):
    return get_success_data(api_client.create_batch(create_batch_payload(cycle_id), OPS))


def stage_encounter(batch, encounter_id):
    """Stage an encounter into a DRAFT batch; returns the refreshed batch."""
    resp = get_success_data(api_client.add_encounter_to_batch(
        batch["id"], {"encounter_id": encounter_id, "expected_batch_version": batch["version"]}, OPS))
    return resp


def seal_batch(batch):
    return get_success_data(api_client.seal_batch(batch["id"], OPS_SEALER))


def transmit_batch(batch):
    return get_success_data(api_client.transmit_batch(batch["id"], COMP_TRANSMITTER))


def acknowledge_batch(batch, outcomes):
    return get_success_data(api_client.acknowledge_batch(batch["id"], {"outcomes": outcomes}, STATE))


def create_acknowledged_encounter(program_id, cycle_id, member_id, provider_id,
                                  encounter_ref=None, paid_amount_cents=TEST_DEFAULTS["PAID_AMOUNT_CENTS"],
                                  **overrides):
    """Full pipeline: create -> validate -> stage -> seal -> transmit -> acknowledge ACCEPTED.

    Returns dict(encounter, batch).
    """
    encounter = create_validated_encounter(
        program_id, cycle_id, member_id, provider_id,
        encounter_ref=encounter_ref, paid_amount_cents=paid_amount_cents,
        lines=[create_encounter_line(paid_amount_cents=paid_amount_cents,
                                     billed_amount_cents=overrides.pop("billed_amount_cents", paid_amount_cents))],
        **overrides)
    batch = create_batch(cycle_id)
    batch = stage_encounter(batch, encounter["id"])
    batch = seal_batch(batch)
    batch = transmit_batch(batch)
    batch = acknowledge_batch(batch, [{"encounter_id": encounter["id"], "outcome": "ACCEPTED"}])
    final = get_success_data(api_client.get_encounter(encounter["id"], OPS))
    assert final["status"] == "ACKNOWLEDGED", f"Setup failed: encounter is {final['status']}, expected ACKNOWLEDGED"
    return {"encounter": final, "batch": batch}


# ---------------------------------------------------------------------------
# Tier 4: audit / statement / penalty shortcuts
# ---------------------------------------------------------------------------

def create_statement(cycle_id):
    return get_success_data(api_client.create_statement(create_statement_payload(cycle_id), FIN))


def create_audit(cycle_id, sample_size=10, defect_count=0):
    return get_success_data(api_client.create_audit(
        create_audit_payload(cycle_id, sample_size=sample_size, defect_count=defect_count), STATE))


def determine_audit(audit_id):
    return get_success_data(api_client.determine_audit(audit_id, STATE))


def list_cycle_penalties(cycle_id):
    data, _meta = _list(api_client.list_penalties(STATE, params={"cycle_id": cycle_id}))
    return data


def _list(resp):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(resp)


def get_program_outstanding(program_id):
    return get_success_data(api_client.get_program(program_id, STATE))["penalties_outstanding_cents"]


def setup_determined_fail_audit(program_name="P-AUDIT-FAIL", aid_category="SSI",
                                pmpm_cents=TEST_DEFAULTS["PMPM_SSI_CENTS"], member_count=4,
                                acknowledged_count=1, sample_size=20, defect_count=4,
                                penalty_threshold_cents=TEST_DEFAULTS["SAFE_PENALTY_THRESHOLD_CENTS"]):
    """Program + cycle + N members + `acknowledged_count` ACKNOWLEDGED encounters +
    provisional statement + a FAIL-determination audit (determined).

    Returns dict(program, cycle, members, provider, audit, penalties, statement).
    """
    program = create_program(name=program_name, penalty_threshold_cents=penalty_threshold_cents)
    create_rate_schedule(program["id"], aid_category=aid_category, pmpm_cents=pmpm_cents)
    cycle = create_cycle(program["id"])
    members = [create_member(program["id"], aid_category=aid_category) for _ in range(member_count)]
    provider = create_provider(program["id"])
    for i in range(acknowledged_count):
        create_acknowledged_encounter(program["id"], cycle["id"], members[i]["id"], provider["id"])
    statement = create_statement(cycle["id"])
    audit = create_audit(cycle["id"], sample_size=sample_size, defect_count=defect_count)
    audit = determine_audit(audit["id"])
    penalties = list_cycle_penalties(cycle["id"])
    return {
        "program": program,
        "cycle": cycle,
        "members": members,
        "provider": provider,
        "audit": audit,
        "penalties": penalties,
        "statement": statement,
    }


def setup_late_penalty(program_name="P-LATE", penalty_threshold_cents=TEST_DEFAULTS["SAFE_PENALTY_THRESHOLD_CENTS"],
                       transmit_at="2026-09-15T00:00:01Z"):
    """Program + cycle + one staged/sealed batch transmitted late, spawning a
    LATE_SUBMISSION PenaltyAssessment.

    Default transmit time is one second past the deadline (0 whole days late, flat only).
    Returns dict(program, cycle, member, provider, encounter, batch, penalty).
    """
    program = create_program(name=program_name, penalty_threshold_cents=penalty_threshold_cents)
    cycle = create_cycle(program["id"])
    member = create_member(program["id"])
    provider = create_provider(program["id"])
    encounter = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"])
    batch = create_batch(cycle["id"])
    batch = stage_encounter(batch, encounter["id"])
    batch = seal_batch(batch)
    set_clock(transmit_at)
    batch = transmit_batch(batch)
    penalties = list_cycle_penalties(cycle["id"])
    assert len(penalties) == 1, f"Setup failed: expected 1 late penalty, got {len(penalties)}"
    return {
        "program": program,
        "cycle": cycle,
        "member": member,
        "provider": provider,
        "encounter": encounter,
        "batch": batch,
        "penalty": penalties[0],
    }


def setup_partial_batch_with_denial(program_name="P-PARTIAL", denied_edit_code=EDIT_CODES["STATE_DENIAL"]):
    """Batch acknowledged with a mixed outcome (one DENIED, one ACCEPTED) -> PARTIAL.

    Returns dict(program, cycle, member, provider, denied_encounter, accepted_encounter, batch).
    """
    program = create_program(name=program_name)
    cycle = create_cycle(program["id"])
    member = create_member(program["id"])
    provider = create_provider(program["id"])
    denied = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        paid_amount_cents=10000)
    accepted = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                          paid_amount_cents=4000,
                                          lines=[create_encounter_line(procedure_code="99212",
                                                                       billed_amount_cents=4000,
                                                                       paid_amount_cents=4000)])
    batch = create_batch(cycle["id"])
    batch = stage_encounter(batch, denied["id"])
    batch = stage_encounter(batch, accepted["id"])
    batch = seal_batch(batch)
    batch = transmit_batch(batch)
    batch = acknowledge_batch(batch, [
        {"encounter_id": denied["id"], "outcome": "DENIED", "edit_code": denied_edit_code},
        {"encounter_id": accepted["id"], "outcome": "ACCEPTED"},
    ])
    assert batch["status"] == "PARTIAL", f"Setup failed: batch is {batch['status']}, expected PARTIAL"
    return {
        "program": program,
        "cycle": cycle,
        "member": member,
        "provider": provider,
        "denied_encounter": get_success_data(api_client.get_encounter(denied["id"], OPS)),
        "accepted_encounter": get_success_data(api_client.get_encounter(accepted["id"], OPS)),
        "batch": batch,
    }


def replace_encounter(encounter_id, **overrides):
    """Replace a DENIED/ACKNOWLEDGED encounter; returns the replacement (201 data)."""
    return get_success_data(api_client.replace_encounter(encounter_id, create_replace_payload(**overrides), OPS))


def get_scorecard_for(provider_id, cycle_id):
    """Fetch the unique scorecard for (provider, cycle); fails setup if absent."""
    data, _meta = _list(api_client.list_scorecards(OPS, params={"provider_id": provider_id, "cycle_id": cycle_id}))
    assert len(data) == 1, f"Setup failed: expected exactly 1 scorecard for provider {provider_id} / cycle {cycle_id}, got {len(data)}"
    return data[0]
