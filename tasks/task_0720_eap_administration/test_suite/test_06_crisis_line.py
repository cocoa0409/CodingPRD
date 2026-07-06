"""Crisis line: intake, triage SLA, escalation, resolution dispositions."""
import pytest
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_paginated, ApiErrorId,
    create_crisis_contact_payload,
)
import test_helpers.fixtures as fx

ADMIN = TEST_USERS["program_admin_headers"]
CRISIS = TEST_USERS["crisis_counselor_headers"]


# ===========================================================================
# Boundary: crisis SLA strict > on triage  (Difficulty)
# ===========================================================================
def test_crisis_sla_strict_greater_than_boundary(api):
    """PRD §3.6: "The SLA is the elapsed time from `opened_at` to `triaged_at`
    measured in whole minutes; `sla_breached` is true only when that elapsed
    figure is strictly greater than the contract's `crisis_sla_minutes`, so an
    elapsed time exactly equal to the SLA is within bounds and not a breach."

    Design: Difficulty/boundary_precision_check/crisis_sla_strict_greater_than_boundary
    """
    # elapsed exactly 15 == crisis_sla_minutes -> NOT a breach
    contract, cc = fx.setup_triaged_crisis_contact(
        disposition="SELF_HELP", severity="MODERATE", crisis_sla_minutes=15,
        opened_clock="2026-03-02T08:00:00Z", triage_clock="2026-03-02T08:15:00Z")
    assert cc["status"] == "TRIAGED"
    assert cc["sla_breached"] is False


def test_crisis_sla_breach_one_minute_over(api):
    """PRD §3.6: "The SLA is the elapsed time from `opened_at` to `triaged_at`
    measured in whole minutes; `sla_breached` is true only when that elapsed
    figure is strictly greater than the contract's `crisis_sla_minutes`, so an
    elapsed time exactly equal to the SLA is within bounds and not a breach."

    Design: Difficulty/boundary_precision_check/crisis_sla_strict_greater_than_boundary
    """
    # elapsed 16 > 15 -> breach
    contract, cc = fx.setup_triaged_crisis_contact(
        disposition="SELF_HELP", severity="MODERATE", crisis_sla_minutes=15,
        opened_clock="2026-03-02T08:00:00Z", triage_clock="2026-03-02T08:16:00Z")
    assert cc["status"] == "TRIAGED"
    assert cc["sla_breached"] is True


# ===========================================================================
# Transitive cascade: escalate creates referral, bumps provider count  (Difficulty)
# ===========================================================================
def test_crisis_escalate_creates_referral_bumps_provider_count(api):
    """PRD §3.6: "Escalation supplies a `required_specialty` and, as a side
    effect, creates a `CLINICAL` referral in `REQUESTED` status with a provider
    auto-selected by the selection policy."
    PRD §3.7: "On creation the server auto-selects a provider, the referral's
    `status` becomes `REQUESTED`, the chosen provider is recorded in
    `provider_id`, and that provider's `active_referral_count` rises by one."

    Design: Difficulty/transitive_cascade/crisis_escalate_creates_referral_bumps_provider_count
    """
    contract = fx.create_contract(crisis_sla_minutes=15)
    provider = fx.create_provider(full_name="CrisisDoc", network_status="IN_NETWORK",
                                  specialties=["STRESS"], accepting=True)
    fx.set_clock("2026-03-02T08:00:00Z")
    cc = validate_success(api.create_crisis_contact(
        create_crisis_contact_payload(contract["id"], severity="HIGH"), CRISIS), 201)
    validate_success(api.triage_crisis_contact(
        cc["id"], {"disposition": "URGENT_REFERRAL"}, CRISIS))
    escalated = validate_success(api.escalate_crisis_contact(
        cc["id"], {"required_specialty": "STRESS"}, CRISIS))
    assert escalated["status"] == "ESCALATED"
    assert validate_success(api.get_provider(provider["id"], ADMIN))["active_referral_count"] == 1
    data, meta = validate_paginated(api.list_referrals(ADMIN, params={"provider_id": provider["id"]}))
    clinical = [r for r in data if r["referral_type"] == "CLINICAL" and r["status"] == "REQUESTED"]
    assert len(clinical) == 1


def test_crisis_escalate_moves_to_escalated_with_clinical_referral(api):
    """PRD §3.6: "It may be **escalated** by a `CrisisCounselor` — moving `status`
    to `ESCALATED` — but only when its recorded disposition is `URGENT_REFERRAL`
    or `EMERGENCY_DISPATCH` ... Escalation supplies a `required_specialty` and, as
    a side effect, creates a `CLINICAL` referral in `REQUESTED` status with a
    provider auto-selected by the selection policy."

    Design: Difficulty/transitive_cascade/crisis_escalate_creates_referral_bumps_provider_count
    """
    contract = fx.create_contract(crisis_sla_minutes=15)
    provider = fx.create_provider(full_name="CrisisDoc2", network_status="IN_NETWORK",
                                  specialties=["GRIEF"], accepting=True)
    fx.set_clock("2026-03-02T08:00:00Z")
    cc = validate_success(api.create_crisis_contact(
        create_crisis_contact_payload(contract["id"], severity="HIGH"), CRISIS), 201)
    validate_success(api.triage_crisis_contact(
        cc["id"], {"disposition": "EMERGENCY_DISPATCH"}, CRISIS))
    escalated = validate_success(api.escalate_crisis_contact(
        cc["id"], {"required_specialty": "GRIEF"}, CRISIS))
    assert escalated["status"] == "ESCALATED"
    data, meta = validate_paginated(api.list_referrals(ADMIN, params={"provider_id": provider["id"]}))
    clinical = [r for r in data if r["referral_type"] == "CLINICAL"]
    assert len(clinical) == 1
    assert clinical[0]["status"] == "REQUESTED"


# ===========================================================================
# Disposition gating corners
# ===========================================================================
def test_crisis_resolve_escalatable_disposition_returns_not_resolvable(api):
    """PRD §3.6: "a triaged contact may be **resolved** directly by a
    `CrisisCounselor` — moving `status` to `RESOLVED` — but only when its
    disposition is `SELF_HELP` or `ROUTINE_REFERRAL`; a direct-resolve attempt on
    any other disposition is rejected with `ERR_DISPOSITION_NOT_RESOLVABLE`."

    Design: Corner/state_machines/crisis_resolve_escalatable_disposition_returns_not_resolvable
    """
    contract, cc = fx.setup_triaged_crisis_contact(
        disposition="EMERGENCY_DISPATCH", severity="HIGH", crisis_sla_minutes=15,
        opened_clock="2026-03-02T08:00:00Z")
    validate_error(api.resolve_crisis_contact(cc["id"], CRISIS),
                   ApiErrorId.ERR_DISPOSITION_NOT_RESOLVABLE.value)


def test_crisis_imminent_resolve_blocked_requires_escalation(api):
    """PRD §3.6: "Overriding the direct-resolve branch entirely, a contact whose
    intake `severity` was `IMMINENT` can never be resolved directly out of triage;
    it must be escalated first, and any direct-resolve attempt on it is rejected
    with `ERR_IMMINENT_REQUIRES_ESCALATION`."

    Design: Corner/state_machines/crisis_imminent_resolve_blocked_requires_escalation
    """
    contract, cc = fx.setup_triaged_crisis_contact(
        disposition="ROUTINE_REFERRAL", severity="IMMINENT", crisis_sla_minutes=15,
        opened_clock="2026-03-02T08:00:00Z")
    validate_error(api.resolve_crisis_contact(cc["id"], CRISIS),
                   ApiErrorId.ERR_IMMINENT_REQUIRES_ESCALATION.value)
