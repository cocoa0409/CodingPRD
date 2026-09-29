"""Payload factories — one per created resource, input fields only.

Every factory takes `**overrides`; pass `field=None` is NOT a removal — use
`payload.pop("field")` in the caller when a test needs the field absent.
"""

from .constants import DEFAULT_CLOCK_ISO, TEST_DEFAULTS


def clock_payload(to_iso8601: str = DEFAULT_CLOCK_ISO) -> dict:
    return {"to_iso8601": to_iso8601}


def create_cycle_payload(**overrides) -> dict:
    payload = {
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "distributable_pool_cents": TEST_DEFAULTS["DISTRIBUTABLE_POOL_CENTS"],
        "lockstep_unit_cents": TEST_DEFAULTS["LOCKSTEP_UNIT_CENTS"],
        "discretionary_pool_pct": TEST_DEFAULTS["DISCRETIONARY_POOL_PCT"],
        "draw_pct": TEST_DEFAULTS["DRAW_PCT"],
        "claim_deadline_on": TEST_DEFAULTS["CLAIM_DEADLINE_ON"],
        "assessment_deadline_on": TEST_DEFAULTS["ASSESSMENT_DEADLINE_ON"],
    }
    payload.update(overrides)
    return payload


def create_partner_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ada Origin",
        "practice_group": "CORPORATE",
        "compensation_model": "FORMULA",
        "admission_year": TEST_DEFAULTS["ADMISSION_YEAR"],
    }
    payload.update(overrides)
    return payload


def create_matter_payload(**overrides) -> dict:
    payload = {
        "client_key": "CLI-A1",
        "client_display_name": "Alpha Holdings",
        "matter_type": "NEW_CLIENT",
        "practice_group": "CORPORATE",
        "opened_on": "2026-01-15",
    }
    payload.update(overrides)
    return payload


def matter_financials_payload(expected_matter_version: int, **overrides) -> dict:
    payload = {
        "billed_delta_cents": 0,
        "collected_delta_cents": 0,
        "direct_cost_delta_cents": 0,
        "expected_matter_version": expected_matter_version,
    }
    payload.update(overrides)
    return payload


def matter_status_payload(target_state: str, **overrides) -> dict:
    payload = {"target_state": target_state}
    payload.update(overrides)
    return payload


def advance_cycle_payload(target_state: str) -> dict:
    return {"target_state": target_state}


def create_contribution_record_payload(**overrides) -> dict:
    payload = {
        "kind": "BILLABLE",
        "category": "CLIENT_WORK",
        "hours": 10.00,
        "standard_rate_cents": 50000,
        "service_period_start": "2026-01-15",
        "service_period_end": "2026-06-30",
    }
    payload.update(overrides)
    return payload


def create_credit_claim_payload(**overrides) -> dict:
    payload = {
        "claim_basis": "NEW_CLIENT",
        "requested_pct": 100.00,
        "narrative": "I introduced this client to the firm and led the pitch.",
    }
    payload.update(overrides)
    return payload


def dispute_claim_payload(**overrides) -> dict:
    payload = {
        "contested_pct": 40.00,
        "dispute_grounds": "The introduction came through my long-standing contact.",
    }
    payload.update(overrides)
    return payload


def adjudicate_claim_payload(decision: str, expected_matter_version: int, **overrides) -> dict:
    payload = {"decision": decision, "expected_matter_version": expected_matter_version}
    payload.update(overrides)
    return payload


def create_self_assessment_payload(**overrides) -> dict:
    payload = {
        "narrative": "A strong year of client development and firm building.",
        "claimed_origination_pct_total": 100.00,
        "claimed_non_billable_hours": 40.00,
    }
    payload.update(overrides)
    return payload


def review_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_peer_review_payload(self_assessment_id: str, reviewer_partner_id: str) -> dict:
    return {
        "self_assessment_id": self_assessment_id,
        "reviewer_partner_id": reviewer_partner_id,
    }


def peer_review_score_payload(technical=4, collaboration=4, client_service=4, **overrides) -> dict:
    payload = {
        "outcome": "SCORE",
        "technical_score": technical,
        "collaboration_score": collaboration,
        "client_service_score": client_service,
        "comment": "Solid.",
    }
    payload.update(overrides)
    return payload


def peer_review_recuse_payload(recusal_reason="Longstanding co-counsel relationship.") -> dict:
    return {"outcome": "RECUSE", "recusal_reason": recusal_reason}


def cast_ballot_payload(points_proposed: float, expected_cycle_version: int, **overrides) -> dict:
    payload = {
        "action": "CAST",
        "points_proposed": points_proposed,
        "rationale": "Strong year.",
        "expected_cycle_version": expected_cycle_version,
    }
    payload.update(overrides)
    return payload


def abstain_ballot_payload(expected_cycle_version: int, **overrides) -> dict:
    payload = {"action": "ABSTAIN", "expected_cycle_version": expected_cycle_version}
    payload.update(overrides)
    return payload


def recuse_ballot_payload(expected_cycle_version: int, recusal_reason="I am the subject.", **overrides) -> dict:
    payload = {
        "action": "RECUSE",
        "recusal_reason": recusal_reason,
        "expected_cycle_version": expected_cycle_version,
    }
    payload.update(overrides)
    return payload


def draw_run_payload(period_year: int, period_month: int, **overrides) -> dict:
    payload = {"period_year": period_year, "period_month": period_month}
    payload.update(overrides)
    return payload


def notice_of_departure_payload(departure_effective_on: str = "2026-12-31") -> dict:
    return {"departure_effective_on": departure_effective_on}


def capital_contribution_payload(amount_cents: int, expected_partner_version: int) -> dict:
    return {
        "amount_cents": amount_cents,
        "expected_partner_version": expected_partner_version,
    }


def effectuate_transition_payload(
    successor_partner_id: str, effective_on: str, expected_matter_version: int
) -> dict:
    return {
        "successor_partner_id": successor_partner_id,
        "effective_on": effective_on,
        "expected_matter_version": expected_matter_version,
    }


def void_transition_payload(void_reason: str, expected_matter_version: int) -> dict:
    return {"void_reason": void_reason, "expected_matter_version": expected_matter_version}
