"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch through the public API, because
each test runs against a freshly restarted server with an empty database and
the logical clock at its startup instant 2026-08-01T00:00:00Z (PRD §2.5).
Setup calls use the lenient get_success_data validator so failures surface as
clear "Setup step failed" errors.
"""
from datetime import timedelta
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import parse_instant
from .factories import (
    create_consent_order_payload,
    create_custody_event_payload,
    create_dmr_payload,
    create_effluent_limit_payload,
    create_inspection_payload,
    create_lab_result_payload,
    create_outfall_payload,
    create_payment_payload,
    create_permit_payload,
    create_renewal_application_payload,
    create_sampling_event_payload,
    create_swppp_plan_payload,
    next_permit_number,
)
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_facility_inspector_headers,
    make_field_sampler_headers,
    make_lab_analyst_headers,
    make_lab_validator_headers,
    make_regulator_headers,
)

EM = TEST_USERS["environmental_manager_headers"]
FS = TEST_USERS["field_sampler_headers"]
LA = TEST_USERS["lab_analyst_headers"]
LV = TEST_USERS["lab_validator_headers"]
CO = TEST_USERS["compliance_officer_headers"]
FI = TEST_USERS["facility_inspector_headers"]
REG = TEST_USERS["regulator_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


def iso_after(iso: str, **delta_kwargs) -> str:
    """Render an ISO 8601 UTC instant offset from the given instant."""
    return (parse_instant(iso) + timedelta(**delta_kwargs)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Clock ──────────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (SystemAdmin-only, PRD §2.5)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ─── Permits / outfalls / limits (PRD §3.1) ─────────────────────────────────

def create_permit(**overrides) -> dict:
    payload = create_permit_payload(**overrides)
    return get_success_data(api_client.create_permit(payload, EM))


def create_outfall(permit_id: str, outfall_number: str = "001", **overrides) -> dict:
    payload = create_outfall_payload(permit_id, outfall_number=outfall_number, **overrides)
    return get_success_data(api_client.create_outfall(payload, EM))


def get_outfall_version(outfall_id: str) -> int:
    return get_success_data(api_client.get_outfall(outfall_id, EM))["version"]


def create_effluent_limit(outfall_id: str, expected_outfall_version: Optional[int] = None,
                          **overrides) -> dict:
    """Create a limit; the OCC field (PRD §2.7) is auto-filled from the live
    outfall version unless explicitly supplied."""
    if expected_outfall_version is None:
        expected_outfall_version = get_outfall_version(outfall_id)
    payload = create_effluent_limit_payload(
        outfall_id, expected_outfall_version, **overrides
    )
    return get_success_data(api_client.create_effluent_limit(payload, EM))


def issue_permit(permit_id: str) -> dict:
    return get_success_data(api_client.issue_permit(permit_id, EM))


def create_active_permit(parameter_code: str = "TSS", limit_value: float = 10.0,
                         limit_type: str = "DAILY_MAX", unit: str = "MG_L",
                         monitoring_frequency: str = "WEEKLY",
                         limit_effective_from: str = "2026-01-01T00:00:00Z",
                         limit_effective_to: Optional[str] = None,
                         average_method: Optional[str] = None,
                         permit_number: Optional[str] = None,
                         **permit_overrides) -> dict:
    """Permit + outfall 001 + one ACTIVE limit, issued to ACTIVE.

    Returns {"permit", "outfall", "limit"}.
    """
    if permit_number is None:
        permit_number = next_permit_number()
    permit = create_permit(permit_number=permit_number, **permit_overrides)
    outfall = create_outfall(permit["id"])
    limit = create_effluent_limit(
        outfall["id"],
        parameter_code=parameter_code,
        limit_type=limit_type,
        limit_value=limit_value,
        unit=unit,
        monitoring_frequency=monitoring_frequency,
        effective_from=limit_effective_from,
        effective_to=limit_effective_to,
        average_method=average_method,
    )
    permit = issue_permit(permit["id"])
    return {"permit": permit, "outfall": outfall, "limit": limit}


# ─── Sampling & custody (PRD §3.2) ──────────────────────────────────────────

def schedule_sample(outfall_id: str, parameter_code: str, scheduled_for: str,
                    collection_window_hours: Optional[int] = None,
                    sampler_id: str = "sampler-1") -> dict:
    payload = create_sampling_event_payload(
        outfall_id, parameter_code, scheduled_for,
        collection_window_hours=collection_window_hours,
    )
    return get_success_data(
        api_client.create_sampling_event(payload, make_field_sampler_headers(sampler_id))
    )


def collect_sample(sample_id: str, clock_iso: Optional[str] = None,
                   sampler_id: str = "sampler-1") -> dict:
    """Optionally move the logical clock, then collect (seals custody)."""
    if clock_iso is not None:
        set_clock(clock_iso)
    return get_success_data(
        api_client.collect_sampling_event(sample_id, make_field_sampler_headers(sampler_id))
    )


def advance_custody_to_analyzed(sample_id: str, collect_clock: str) -> None:
    """TRANSFER -> RECEIVE_LAB -> ANALYSIS_START with physical timestamps
    derived from the collection instant (PRD §3.2 custody chain)."""
    transfer_at = iso_after(collect_clock, minutes=10)
    receive_at = iso_after(collect_clock, minutes=20)
    analysis_at = iso_after(collect_clock, minutes=30)
    get_success_data(api_client.append_custody_event(
        sample_id,
        create_custody_event_payload(
            "TRANSFER", transfer_at, from_party="sampler", to_party="courier"
        ),
        FS,
    ))
    get_success_data(api_client.append_custody_event(
        sample_id,
        create_custody_event_payload(
            "RECEIVE_LAB", receive_at, from_party="courier", to_party="lab"
        ),
        LA,
    ))
    get_success_data(api_client.append_custody_event(
        sample_id,
        create_custody_event_payload("ANALYSIS_START", analysis_at),
        LA,
    ))


def create_analyzed_sample(outfall_id: str, parameter_code: str,
                           scheduled_for: str = "2026-08-05T08:00:00Z",
                           collect_clock: str = "2026-08-05T09:00:00Z") -> dict:
    """Schedule -> collect -> custody to ANALYZED. Returns the event."""
    sample = schedule_sample(outfall_id, parameter_code, scheduled_for)
    sample = collect_sample(sample["id"], clock_iso=collect_clock)
    advance_custody_to_analyzed(sample["id"], collect_clock)
    return sample


# ─── Lab results (PRD §3.3) ─────────────────────────────────────────────────

def record_lab_result(sample_id: str, parameter_code: str, reported_value: float,
                      analyzed_at: str, method_detection_limit: float = 0.02,
                      flow_mgd: float = 1.0, unit: str = "MG_L",
                      qualifier: Optional[str] = None,
                      analyst_id: str = "analyst-1") -> dict:
    payload = create_lab_result_payload(
        sample_id, parameter_code, reported_value, analyzed_at,
        method_detection_limit=method_detection_limit, flow_mgd=flow_mgd,
        unit=unit, qualifier=qualifier,
    )
    return get_success_data(
        api_client.create_lab_result(payload, make_lab_analyst_headers(analyst_id))
    )


def validate_lab_result(result_id: str, validator_id: str = "validator-1") -> dict:
    return get_success_data(
        api_client.validate_lab_result(result_id, make_lab_validator_headers(validator_id))
    )


def create_validated_result(outfall_id: str, parameter_code: str, reported_value: float,
                            scheduled_for: str = "2026-08-05T08:00:00Z",
                            collect_clock: str = "2026-08-05T09:00:00Z",
                            analyzed_at: str = "2026-08-05T09:45:00Z",
                            validate_clock: Optional[str] = "2026-08-05T10:00:00Z",
                            method_detection_limit: float = 0.02,
                            flow_mgd: float = 1.0, unit: str = "MG_L",
                            qualifier: Optional[str] = None,
                            analyst_id: str = "analyst-1",
                            validator_id: str = "validator-1") -> dict:
    """Full chain to one VALIDATED result. Returns {"sample", "result"}."""
    sample = create_analyzed_sample(outfall_id, parameter_code, scheduled_for, collect_clock)
    result = record_lab_result(
        sample["id"], parameter_code, reported_value, analyzed_at,
        method_detection_limit=method_detection_limit, flow_mgd=flow_mgd,
        unit=unit, qualifier=qualifier, analyst_id=analyst_id,
    )
    if validate_clock is not None:
        set_clock(validate_clock)
    result = validate_lab_result(result["id"], validator_id=validator_id)
    return {"sample": sample, "result": result}


def create_validated_results(outfall_id: str, parameter_code: str, specs: list,
                             collect_clock: str, analyzed_at: str,
                             validate_clock: str,
                             analyst_id: str = "analyst-1",
                             validator_id: str = "validator-1") -> list:
    """Several samples collected at one clock instant, each taken to VALIDATED.

    Each spec carries scheduled_for, reported_value and optionally flow_mgd,
    method_detection_limit, qualifier, unit. The clock is advanced once per
    phase so no clock-regression can occur (PRD §2.5 monotonicity).
    Returns [{"sample", "result"}, ...] in spec order.
    """
    samples = [
        schedule_sample(outfall_id, parameter_code, spec["scheduled_for"])
        for spec in specs
    ]
    set_clock(collect_clock)
    for sample in samples:
        collect_sample(sample["id"])  # clock already positioned
    for sample in samples:
        advance_custody_to_analyzed(sample["id"], collect_clock)
    results = [
        record_lab_result(
            sample["id"], parameter_code, spec["reported_value"], analyzed_at,
            method_detection_limit=spec.get("method_detection_limit", 0.02),
            flow_mgd=spec.get("flow_mgd", 1.0), unit=spec.get("unit", "MG_L"),
            qualifier=spec.get("qualifier"), analyst_id=analyst_id,
        )
        for sample, spec in zip(samples, specs)
    ]
    set_clock(validate_clock)
    validated = [validate_lab_result(r["id"], validator_id=validator_id) for r in results]
    return [{"sample": s, "result": r} for s, r in zip(samples, validated)]


# ─── Exceedance scenario (PRD §3.4 cascade) ─────────────────────────────────

def create_exceedance_scenario(parameter_code: str = "COPPER",
                               limit_value: float = 1.0,
                               reported_value: float = 1.5,
                               qualifier: Optional[str] = None,
                               method_detection_limit: float = 0.02,
                               flow_mgd: float = 2.0,
                               scheduled_for: str = "2026-08-05T08:00:00Z",
                               collect_clock: str = "2026-08-05T09:00:00Z",
                               analyzed_at: str = "2026-08-05T09:45:00Z",
                               validate_clock: str = "2026-08-05T10:00:00Z",
                               monitoring_frequency: str = "WEEKLY",
                               permit_number: Optional[str] = None) -> dict:
    """ACTIVE permit + one VALIDATED breaching result -> exceedance -> CA.

    Returns {"permit", "outfall", "limit", "sample", "result", "exceedance",
    "corrective_action"} with the exceedance in PENDING_ORAL / NONE.
    """
    env = create_active_permit(
        parameter_code=parameter_code, limit_value=limit_value,
        monitoring_frequency=monitoring_frequency, permit_number=permit_number,
    )
    chain = create_validated_result(
        env["outfall"]["id"], parameter_code, reported_value,
        scheduled_for=scheduled_for, collect_clock=collect_clock,
        analyzed_at=analyzed_at, validate_clock=validate_clock,
        method_detection_limit=method_detection_limit, flow_mgd=flow_mgd,
        qualifier=qualifier,
    )
    exceedance_id = chain["result"]["exceedance_id"]
    exceedance = get_success_data(api_client.get_exceedance(exceedance_id, CO))
    corrective_action = get_success_data(
        api_client.get_corrective_action(exceedance["corrective_action_id"], FI)
    )
    return {
        "permit": env["permit"], "outfall": env["outfall"], "limit": env["limit"],
        "sample": chain["sample"], "result": chain["result"],
        "exceedance": exceedance, "corrective_action": corrective_action,
    }


def get_corrective_action(action_id: str) -> dict:
    return get_success_data(api_client.get_corrective_action(action_id, FI))


def drive_corrective_action_to_verified(action_id: str, actual_cost_cents: int = 5000,
                                        resolver_id: str = "fi-1",
                                        verifier_id: str = "reg-1") -> dict:
    """OPEN -> IN_PROGRESS -> COMPLETED -> VERIFIED (PRD §3.6 work cycle)."""
    get_success_data(api_client.start_corrective_action(
        action_id, make_facility_inspector_headers(resolver_id)
    ))
    get_success_data(api_client.complete_corrective_action(
        action_id, {"actual_cost_cents": actual_cost_cents},
        make_facility_inspector_headers(resolver_id),
    ))
    return get_success_data(api_client.verify_corrective_action(
        action_id, make_regulator_headers(verifier_id)
    ))


def get_permit_state(permit_id: str) -> dict:
    return get_success_data(api_client.get_permit(permit_id, EM))


# ─── DMRs (PRD §3.5) ────────────────────────────────────────────────────────

def create_dmr(outfall_id: str,
               period_start: str = "2026-08-01T00:00:00Z",
               period_end: str = "2026-08-31T23:59:59Z",
               officer_id: str = "co-1") -> dict:
    payload = create_dmr_payload(outfall_id, period_start, period_end)
    return get_success_data(
        api_client.create_dmr(payload, make_compliance_officer_headers(officer_id))
    )


# ─── SWPPP plans & inspections (PRD §3.6) ───────────────────────────────────

def create_swppp_plan(permit_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_swppp_plan(create_swppp_plan_payload(permit_id, **overrides), FI)
    )


def get_permit_version(permit_id: str) -> int:
    return get_success_data(api_client.get_permit(permit_id, FI))["version"]


def activate_swppp_plan(plan_id: str, expected_permit_version: Optional[int] = None) -> dict:
    """Activate with the OCC guard (PRD §2.7) auto-filled from the live permit."""
    if expected_permit_version is None:
        plan = get_success_data(api_client.get_swppp_plan(plan_id, FI))
        expected_permit_version = get_permit_version(plan["permit_id"])
    return get_success_data(api_client.activate_swppp_plan(
        plan_id, {"expected_permit_version": expected_permit_version}, FI
    ))


def create_active_plan(permit_id: str, **overrides) -> dict:
    plan = create_swppp_plan(permit_id, **overrides)
    return activate_swppp_plan(plan["id"])


def create_inspection(plan_id: str, scheduled_for: str = "2026-08-10T08:00:00Z",
                      inspector_id: str = "fi-1") -> dict:
    payload = create_inspection_payload(plan_id, scheduled_for)
    return get_success_data(
        api_client.create_inspection(payload, make_facility_inspector_headers(inspector_id))
    )


# ─── Renewal applications (PRD §3.7) ────────────────────────────────────────

def create_renewal_application(permit_id: str,
                               proposed_expiration_date: str = "2031-12-31T00:00:00Z") -> dict:
    payload = create_renewal_application_payload(permit_id, proposed_expiration_date)
    return get_success_data(api_client.create_renewal_application(payload, EM))


def create_renewal_under_review(permit_id: str,
                                proposed_expiration_date: str = "2031-12-31T00:00:00Z") -> dict:
    renewal = create_renewal_application(permit_id, proposed_expiration_date)
    return get_success_data(api_client.start_renewal_review(renewal["id"], REG))


# ─── Consent orders & payments (PRD §3.8) ───────────────────────────────────

def create_consent_order(exceedance_id: str, **overrides) -> dict:
    payload = create_consent_order_payload(exceedance_id, **overrides)
    return get_success_data(api_client.create_consent_order(payload, REG))


def issue_consent_order(order_id: str) -> dict:
    return get_success_data(api_client.issue_consent_order(order_id, REG))


def finalize_consent_order(order_id: str) -> dict:
    return get_success_data(api_client.finalize_consent_order(order_id, REG))


def create_final_consent_order(exceedance_id: str, **overrides) -> dict:
    """PROPOSED -> ISSUED -> FINAL. Returns the FINAL order."""
    order = create_consent_order(exceedance_id, **overrides)
    issue_consent_order(order["id"])
    return finalize_consent_order(order["id"])


def post_payment(order_id: str, direction: str, amount_cents: int,
                 officer_id: str = "co-1") -> dict:
    payload = create_payment_payload(direction, amount_cents)
    return get_success_data(
        api_client.post_payment(order_id, payload, make_compliance_officer_headers(officer_id))
    )
