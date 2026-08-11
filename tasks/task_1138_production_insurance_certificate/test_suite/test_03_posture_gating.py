"""Coverage posture derivation, activation gates, and posture-blocked writes."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_policy_payload, create_clearance_item_payload,
    set_logical_clock, create_production, create_and_bind_policy,
    activate_production, get_production_version,
    setup_active_production_with_bound_policy, setup_cast_policy_bound,
    add_cast_member, create_issued_endorsement, create_clearance_item,
    create_draft_certificate, report_claim,
    TEST_USERS,
)

BROKER = TEST_USERS["broker_headers"]
PM = TEST_USERS["production_manager_headers"]
UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
CC = TEST_USERS["clearance_counsel_headers"]


# ─── Activation gate (corner) ─────────────────────────

def test_production_activate_requires_bound_policy(api):
    """PRD §3.4: "At least one policy must be `BOUND`, `ENDORSED_PENDING`, or
    `ACTIVE`, or the activation fails with `ERR_NO_BOUND_POLICY`."

    Design: Corner/validations/production_activate_requires_bound_policy
    """
    set_logical_clock()
    prod = create_production()
    res = api.activate_production(prod["id"], BROKER)
    validate_error(res, "ERR_NO_BOUND_POLICY", expected_status=422)


# ─── Posture derive dual-variant (difficulty) ─────────

def _setup_commercial_with_gl(code_title_suffix: str):
    """COMMERCIAL production with only a GL policy bound, then activated."""
    prod = create_production(title=f"Posture {code_title_suffix}",
                             production_type="COMMERCIAL")
    create_and_bind_policy(prod["id"], coverage_line="GENERAL_LIABILITY")
    return activate_production(prod["id"])


def test_posture_varies_bound_partial_vs_restricted(api):
    """PRD §3.4: "with nothing bound at all it is `UNBOUND`; and anything else
    — some but not all required lines bound — is `BOUND_PARTIAL`."
    PRD §3.4: "Otherwise, any open injury claim makes the production
    `RESTRICTED`; so does any uncleared mandatory clearance; so does a required
    completion bond that is not yet `ISSUED`."

    Design: Difficulty/dual_variant_calc/posture_derive_varies_with_clearance_vs_claim_states
    """
    set_logical_clock()
    # P1: GL bound only; EQUIPMENT still required for COMMERCIAL -> BOUND_PARTIAL.
    p1 = _setup_commercial_with_gl("A")
    assert p1["coverage_posture"] == "BOUND_PARTIAL"

    # P2: identical, plus one open INJURY claim -> RESTRICTED.
    p2 = _setup_commercial_with_gl("B")
    policies, _ = validate_paginated(api.list_policies(p2["id"], BROKER))
    claim = report_claim(p2["id"], policies[0]["id"], claim_type="INJURY")
    validate_success(api.acknowledge_claim(p2["id"], claim["id"], ADJ), 200)
    p2_after = validate_success(api.get_production(p2["id"], BROKER), 200)
    assert p2_after["coverage_posture"] == "RESTRICTED"


def test_posture_reasons_name_contributing_causes(api):
    """PRD §3.4: "The `posture_reasons` list names every contributing cause,
    sorted lexicographically for determinism: one `MISSING_LINE_<COVERAGE_LINE>`
    code per missing required line, `OPEN_INJURY_CLAIM` when open injury claims
    exist"

    Design: Difficulty/dual_variant_calc/posture_derive_varies_with_clearance_vs_claim_states
    """
    set_logical_clock()
    p1 = _setup_commercial_with_gl("R1")
    assert "MISSING_LINE_EQUIPMENT" in p1["posture_reasons"]
    assert p1["posture_reasons"] == sorted(p1["posture_reasons"])

    p2 = _setup_commercial_with_gl("R2")
    policies, _ = validate_paginated(api.list_policies(p2["id"], BROKER))
    claim = report_claim(p2["id"], policies[0]["id"], claim_type="INJURY")
    validate_success(api.acknowledge_claim(p2["id"], claim["id"], ADJ), 200)
    p2_after = validate_success(api.get_production(p2["id"], BROKER), 200)
    assert "OPEN_INJURY_CLAIM" in p2_after["posture_reasons"]
    assert p2_after["posture_reasons"] == sorted(p2_after["posture_reasons"])


# ─── Posture cascade via injury claim (corner) ────────

def test_posture_cascade_via_injury_claim(api):
    """PRD §3.8: "whenever the new claim is an `INJURY` claim the production's
    posture is recomputed, because open injuries restrict it."
    PRD §3.4: "any open injury claim makes the production `RESTRICTED`"

    Design: Corner/cross_cutting_complexity_layers/posture_cascade_via_injury_claim
    """
    prod, policy = setup_active_production_with_bound_policy()
    assert prod["coverage_posture"] == "BOUND_PARTIAL"
    report_claim(prod["id"], policy["id"], claim_type="INJURY")
    prod_after = validate_success(api.get_production(prod["id"], BROKER), 200)
    assert prod_after["coverage_posture"] == "RESTRICTED"
    assert "OPEN_INJURY_CLAIM" in prod_after["posture_reasons"]


# ─── Posture blocks certificate issuance (corner) ─────

def test_posture_blocks_certificate_issuance_when_restricted(api):
    """PRD §2.7: "Certificate issuance, foreign travel approval, and completion
    bond issuance are only permitted when the posture is `BOUND_PARTIAL` or
    `BOUND_FULL`; a `RESTRICTED` or `SUSPENDED` production is refused with
    `ERR_POSTURE_BLOCKS_ISSUANCE` (HTTP 422)"

    Design: Corner/validations/posture_blocks_certificate_issuance_when_restricted
    """
    prod, policy = setup_active_production_with_bound_policy()
    claim = report_claim(prod["id"], policy["id"], claim_type="INJURY")
    validate_success(api.acknowledge_claim(prod["id"], claim["id"], ADJ), 200)
    cert = create_draft_certificate(
        prod["id"], certificate_type="LOCATION", additional_insured_name="Lot Owner")
    version = get_production_version(prod["id"])
    res = api.issue_certificate(prod["id"], cert["id"],
                                {"expected_production_version": version}, BROKER)
    validate_error(res, "ERR_POSTURE_BLOCKS_ISSUANCE", expected_status=422)


# ─── Posture recompute after endorsement revoke (corner) ───

def test_posture_recompute_after_endorsement_revoke(api):
    """PRD §3.2: "Every issuance and every revocation of an issued endorsement
    recomputes the production's posture."
    PRD §3.4: "and anything else — some but not all required lines bound — is
    `BOUND_PARTIAL`."

    Design: Corner/calculations/posture_recompute_after_endorsement_revoke
    """
    prod, cast_policy, members = setup_cast_policy_bound(
        cast_members=[{"role_tier": "PRINCIPAL", "essential_element": True,
                       "exam_outcome": "CLEARED"}])
    create_and_bind_policy(prod["id"], coverage_line="GENERAL_LIABILITY")
    endo = create_issued_endorsement(prod["id"], members[0]["id"],
                                     cast_policy["id"], "ESSENTIAL_ELEMENT")
    activate_production(prod["id"])

    validate_success(api.revoke_cast_endorsement(prod["id"], endo["id"], UW), 200)
    # Revocation recomputes posture; the derivation inputs (bound lines, exam
    # status) are unchanged, so the reconciled value stays BOUND_PARTIAL with
    # the missing EQUIPMENT line named.
    prod_after = validate_success(api.get_production(prod["id"], BROKER), 200)
    assert prod_after["coverage_posture"] == "BOUND_PARTIAL"
    assert "MISSING_LINE_EQUIPMENT" in prod_after["posture_reasons"]


# ─── Clearance waiver precondition (corner) ───────────

def test_clearance_waiver_requires_justification(api):
    """PRD §3.3: "a `FLAGGED` item can subsequently be `CLEARED`, or it can be
    `WAIVED` — but a waiver additionally requires a non-empty
    `waiver_justification` explaining why the production proceeds despite the
    flag."
    PRD §2.9: "Requests whose bodies are missing required fields or carry
    malformed types, outside the specific checks above, are rejected with
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/state_machines/clearance_waiver_requires_justification
    """
    set_logical_clock()
    prod = create_production(production_type="FEATURE")
    item = create_clearance_item(prod["id"], clearance_kind="SCRIPT")
    validate_success(
        api.resolve_clearance_item(prod["id"], item["id"], {"outcome": "FLAGGED"}, CC),
        200)
    res = api.resolve_clearance_item(prod["id"], item["id"], {"outcome": "WAIVED"}, CC)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
