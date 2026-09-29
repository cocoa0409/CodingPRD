"""
Composite setup builders.

Because the API server is restarted before every individual test, each test
begins against an empty database with the logical clock back at its start
instant.  Every precondition therefore has to be built through the declared
endpoints, and the chain that most behaviour hangs off is long: a zone has to
be registered, signed, audited and designated; a line has to be registered and
assigned to the zone; an inspector and a rider have to exist; a deployment has
to be planned and activated inside its own window; and only then can an
encounter be recorded and a citation issued.

The builders here take the client as their first argument and return the
resource bodies, so a test can stop the chain wherever it needs to and can vary
any input that matters to it.  Setup calls are read leniently — the exact status
code of a setup call is the subject of other tests, not of the fixture.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import (
    BAND_A,
    CLOCK_EPOCH,
    ENFORCEMENT_POLICY_CITATION_IMMEDIATE,
    IDENTITY_GOVT_ID,
    MEDIA_NONE,
    MODE_LIGHT_RAIL,
    SAMPLING_SYSTEMATIC_INTERVAL,
)
from .test_users import (
    BOARD_MEMBER_HEADERS,
    HEARING_OFFICER_HEADERS,
    PLANNER_HEADERS,
    make_fare_inspector_headers,
    make_rider_headers,
)

# The instants the composite chain uses by default.
AUDIT_AT = "2026-08-01T01:00:00Z"
WINDOW_START = "2026-08-05T06:00:00Z"
WINDOW_END = "2026-08-05T14:00:00Z"
OBSERVATION_AT = "2026-08-05T09:00:00Z"
ENCOUNTER_AT = "2026-08-05T07:00:00Z"
CERTIFICATION_EXPIRY = "2027-01-01T00:00:00Z"


# ── Single-step builders ─────────────────────────────────────────────

def move_clock(api: ApiClient, to_iso8601: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    """Move the logical clock and return the echoed clock state."""
    response = api.set_clock(
        factories.clock_payload(to_iso8601), headers or PLANNER_HEADERS
    )
    return get_success_data(response)


def register_zone(
    api: ApiClient,
    zone_code: str = "ZN1",
    name: str = "Downtown POP Zone",
    required_sign_count: int = 10,
    penalty_multiplier_bps: Optional[int] = 12000,
    enforcement_policy: Optional[str] = ENFORCEMENT_POLICY_CITATION_IMMEDIATE,
    max_concurrent_deployments: Optional[int] = 2,
) -> Dict[str, Any]:
    response = api.create_fare_zone(
        factories.fare_zone_payload(
            zone_code=zone_code,
            name=name,
            required_sign_count=required_sign_count,
            penalty_multiplier_bps=penalty_multiplier_bps,
            enforcement_policy=enforcement_policy,
            max_concurrent_deployments=max_concurrent_deployments,
        ),
        PLANNER_HEADERS,
    )
    return get_success_data(response)


def file_audit(
    api: ApiClient,
    zone_id: str,
    signs_verified_count: int,
    audited_at: str = AUDIT_AT,
    deficiency_note: Optional[str] = None,
) -> Dict[str, Any]:
    response = api.create_signage_audit(
        factories.signage_audit_payload(
            zone_id=zone_id,
            audited_at=audited_at,
            signs_verified_count=signs_verified_count,
            deficiency_note=deficiency_note,
        ),
        PLANNER_HEADERS,
    )
    return get_success_data(response)


def sign_and_designate_zone(
    api: ApiClient,
    zone_id: str,
    signs_verified_count: int = 10,
    audited_at: str = AUDIT_AT,
) -> Dict[str, Any]:
    """Submit a zone for signage, file a passing audit, and designate it."""
    get_success_data(api.submit_zone_for_signage(zone_id, PLANNER_HEADERS))
    file_audit(api, zone_id, signs_verified_count, audited_at)
    return get_success_data(api.designate_zone(zone_id, PLANNER_HEADERS))


def register_line(
    api: ApiClient,
    line_code: str = "L1",
    mode: str = MODE_LIGHT_RAIL,
    daily_boardings: int = 42000,
    baseline_evasion_rate_bps: int = 600,
) -> Dict[str, Any]:
    response = api.create_transit_line(
        factories.transit_line_payload(
            line_code=line_code,
            mode=mode,
            daily_boardings=daily_boardings,
            baseline_evasion_rate_bps=baseline_evasion_rate_bps,
        ),
        PLANNER_HEADERS,
    )
    return get_success_data(response)


def assign_line(
    api: ApiClient,
    zone_id: str,
    line_id: str,
    platform_segment_count: int = 4,
    effective_from: str = CLOCK_EPOCH,
) -> Dict[str, Any]:
    response = api.create_zone_line_assignment(
        factories.zone_line_assignment_payload(
            zone_id=zone_id,
            line_id=line_id,
            platform_segment_count=platform_segment_count,
            effective_from=effective_from,
        ),
        PLANNER_HEADERS,
    )
    return get_success_data(response)


def register_inspector(
    api: ApiClient,
    badge_number: str = "B-100",
    display_name: str = "Inspector One",
    certification_expiry: str = CERTIFICATION_EXPIRY,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    response = api.create_inspector(
        factories.inspector_payload(
            badge_number=badge_number,
            display_name=display_name,
            certification_expiry=certification_expiry,
            status=status,
        ),
        PLANNER_HEADERS,
    )
    return get_success_data(response)


def register_rider(
    api: ApiClient,
    rider_ref: str = "R-100",
    display_name: str = "Rider One",
    demographic_band: Optional[str] = BAND_A,
    residence_geo_tract: Optional[str] = "T-001",
    fare_assistance_enrolled: Optional[bool] = False,
) -> Dict[str, Any]:
    response = api.create_rider(
        factories.rider_payload(
            rider_ref=rider_ref,
            display_name=display_name,
            demographic_band=demographic_band,
            residence_geo_tract=residence_geo_tract,
            fare_assistance_enrolled=fare_assistance_enrolled,
        ),
        PLANNER_HEADERS,
    )
    return get_success_data(response)


def plan_deployment(
    api: ApiClient,
    line_id: str,
    zone_id: str,
    window_start: str = WINDOW_START,
    window_end: str = WINDOW_END,
    planned_inspector_count: int = 3,
    sampling_method: str = SAMPLING_SYSTEMATIC_INTERVAL,
    target_sample_size: int = 5,
) -> Dict[str, Any]:
    response = api.create_inspection_deployment(
        factories.deployment_payload(
            line_id=line_id,
            zone_id=zone_id,
            window_start=window_start,
            window_end=window_end,
            planned_inspector_count=planned_inspector_count,
            sampling_method=sampling_method,
            target_sample_size=target_sample_size,
        ),
        PLANNER_HEADERS,
    )
    return get_success_data(response)


def record_encounter(
    api: ApiClient,
    deployment_id: str,
    inspector_id: str,
    occurred_at: str = ENCOUNTER_AT,
    fare_media_type: str = MEDIA_NONE,
    rider_id: Optional[str] = None,
    media_reference: Optional[str] = None,
    media_validated_at: Optional[str] = None,
    media_expires_at: Optional[str] = None,
    media_zone_code: Optional[str] = None,
    identity_capture_method: Optional[str] = IDENTITY_GOVT_ID,
) -> Dict[str, Any]:
    response = api.create_inspection_encounter(
        factories.encounter_payload(
            deployment_id=deployment_id,
            inspector_id=inspector_id,
            rider_id=rider_id,
            occurred_at=occurred_at,
            fare_media_type=fare_media_type,
            media_reference=media_reference,
            media_validated_at=media_validated_at,
            media_expires_at=media_expires_at,
            media_zone_code=media_zone_code,
            identity_capture_method=identity_capture_method,
        ),
        make_fare_inspector_headers(inspector_id),
    )
    return get_success_data(response)


def resolve(api: ApiClient, encounter_id: str, inspector_id: str, disposition: str) -> Dict[str, Any]:
    response = api.resolve_encounter(
        encounter_id,
        factories.resolve_payload(disposition),
        make_fare_inspector_headers(inspector_id),
    )
    return get_success_data(response)


def issue_citation(api: ApiClient, encounter_id: str, inspector_id: str) -> Dict[str, Any]:
    response = api.create_citation(
        factories.citation_payload(encounter_id),
        make_fare_inspector_headers(inspector_id),
    )
    return get_success_data(response)


def contest(api: ApiClient, citation_id: str, rider_id: str) -> Dict[str, Any]:
    """Contest a citation and return the scheduled hearing."""
    response = api.contest_citation(citation_id, make_rider_headers(rider_id))
    return get_success_data(response)


def decide_hearing(
    api: ApiClient,
    hearing_id: str,
    decision: str,
    reduced_penalty_cents: Optional[int] = None,
    dismissal_reason_code: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api.decide_hearing(
        hearing_id,
        factories.hearing_decision_payload(
            decision=decision,
            reduced_penalty_cents=reduced_penalty_cents,
            dismissal_reason_code=dismissal_reason_code,
        ),
        headers or HEARING_OFFICER_HEADERS,
    )
    return get_success_data(response)


def file_appeal(
    api: ApiClient,
    citation_id: str,
    hearing_id: str,
    rider_id: str,
    grounds_code: str,
    statement: str = "The inspector did not state the zone.",
) -> Dict[str, Any]:
    response = api.create_appeal(
        factories.appeal_payload(
            citation_id=citation_id,
            hearing_id=hearing_id,
            grounds_code=grounds_code,
            statement=statement,
        ),
        make_rider_headers(rider_id),
    )
    return get_success_data(response)


def request_supplement(
    api: ApiClient, appeal_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api.request_appeal_supplement(appeal_id, headers or BOARD_MEMBER_HEADERS)
    return get_success_data(response)


def pay_direct(api: ApiClient, citation_id: str, amount_cents: int, rider_id: str) -> Dict[str, Any]:
    response = api.create_citation_payment(
        citation_id,
        factories.citation_payment_payload(amount_cents),
        make_rider_headers(rider_id),
    )
    return get_success_data(response)


def read_citation(api: ApiClient, citation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_citation(citation_id, PLANNER_HEADERS))


def read_zone(api: ApiClient, zone_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_fare_zone(zone_id, PLANNER_HEADERS))


def read_deployment(api: ApiClient, deployment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_deployment(deployment_id, PLANNER_HEADERS))


def read_encounter(api: ApiClient, encounter_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_encounter(encounter_id, PLANNER_HEADERS))


def read_rider(api: ApiClient, rider_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_rider(rider_id, PLANNER_HEADERS))


def read_inspector(api: ApiClient, inspector_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_inspector(inspector_id, PLANNER_HEADERS))


def read_appeal(api: ApiClient, appeal_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_appeal(appeal_id, PLANNER_HEADERS))


def read_hearing(api: ApiClient, hearing_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_hearing(hearing_id, PLANNER_HEADERS))


def read_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_payment_plan(plan_id, PLANNER_HEADERS))


def read_service_assignment(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_service_assignment(assignment_id, PLANNER_HEADERS))


def citation_ledger(api: ApiClient, citation_id: str) -> List[Dict[str, Any]]:
    """Every ledger row on a citation, as the sub-collection read returns them."""
    response = api.list_citation_payments(citation_id, PLANNER_HEADERS, {"limit": 100})
    body = response.json()
    assert response.status_code == 200, f"ledger read failed: {response.status_code} {body}"
    return body["data"]


# ── Composite chains ─────────────────────────────────────────────────

def build_environment(
    api: ApiClient,
    *,
    clock_start: str = CLOCK_EPOCH,
    zone_code: str = "ZN1",
    zone_name: str = "Downtown POP Zone",
    required_sign_count: int = 10,
    signs_verified_count: int = 10,
    penalty_multiplier_bps: Optional[int] = 12000,
    enforcement_policy: Optional[str] = ENFORCEMENT_POLICY_CITATION_IMMEDIATE,
    max_concurrent_deployments: Optional[int] = 2,
    designate: bool = True,
    line_code: str = "L1",
    mode: str = MODE_LIGHT_RAIL,
    daily_boardings: int = 42000,
    baseline_evasion_rate_bps: int = 600,
    platform_segment_count: int = 4,
    assign_line_to_zone: bool = True,
    badge_number: str = "B-100",
    inspector_display_name: str = "Inspector One",
    certification_expiry: str = CERTIFICATION_EXPIRY,
    inspector_status: Optional[str] = None,
    rider_ref: str = "R-100",
    rider_display_name: str = "Rider One",
    demographic_band: Optional[str] = BAND_A,
    residence_geo_tract: Optional[str] = "T-001",
    fare_assistance_enrolled: Optional[bool] = False,
) -> Dict[str, Any]:
    """
    Build the network, registry and designation layer: a zone carrying a passing
    signage audit, a line attached to it, one inspector and one rider.
    """
    move_clock(api, clock_start)
    zone = register_zone(
        api,
        zone_code=zone_code,
        name=zone_name,
        required_sign_count=required_sign_count,
        penalty_multiplier_bps=penalty_multiplier_bps,
        enforcement_policy=enforcement_policy,
        max_concurrent_deployments=max_concurrent_deployments,
    )
    line = register_line(
        api,
        line_code=line_code,
        mode=mode,
        daily_boardings=daily_boardings,
        baseline_evasion_rate_bps=baseline_evasion_rate_bps,
    )
    assignment = None
    if assign_line_to_zone:
        assignment = assign_line(
            api, zone["id"], line["id"], platform_segment_count=platform_segment_count
        )
    if designate:
        zone = sign_and_designate_zone(
            api, zone["id"], signs_verified_count=signs_verified_count
        )
    inspector = register_inspector(
        api,
        badge_number=badge_number,
        display_name=inspector_display_name,
        certification_expiry=certification_expiry,
        status=inspector_status,
    )
    rider = register_rider(
        api,
        rider_ref=rider_ref,
        display_name=rider_display_name,
        demographic_band=demographic_band,
        residence_geo_tract=residence_geo_tract,
        fare_assistance_enrolled=fare_assistance_enrolled,
    )
    return {
        "zone": zone,
        "line": line,
        "assignment": assignment,
        "inspector": inspector,
        "rider": rider,
    }


def build_active_deployment(
    api: ApiClient,
    env: Dict[str, Any],
    *,
    window_start: str = WINDOW_START,
    window_end: str = WINDOW_END,
    planned_inspector_count: int = 3,
    sampling_method: str = SAMPLING_SYSTEMATIC_INTERVAL,
    target_sample_size: int = 5,
    observe_at: Optional[str] = OBSERVATION_AT,
) -> Dict[str, Any]:
    """
    Plan a deployment, move the clock to its window start, activate it, and
    leave the clock at the observation instant so encounters inside the window
    are already in the past.
    """
    deployment = plan_deployment(
        api,
        env["line"]["id"],
        env["zone"]["id"],
        window_start=window_start,
        window_end=window_end,
        planned_inspector_count=planned_inspector_count,
        sampling_method=sampling_method,
        target_sample_size=target_sample_size,
    )
    move_clock(api, window_start)
    deployment = get_success_data(api.activate_deployment(deployment["id"], PLANNER_HEADERS))
    if observe_at is not None:
        move_clock(api, observe_at)
    return deployment


def build_pending_encounter(
    api: ApiClient,
    env: Dict[str, Any],
    deployment: Dict[str, Any],
    *,
    occurred_at: str = ENCOUNTER_AT,
    fare_media_type: str = MEDIA_NONE,
    rider: Optional[Dict[str, Any]] = None,
    media_reference: Optional[str] = None,
    media_validated_at: Optional[str] = None,
    media_expires_at: Optional[str] = None,
    media_zone_code: Optional[str] = None,
    identity_capture_method: Optional[str] = IDENTITY_GOVT_ID,
) -> Dict[str, Any]:
    """Record one encounter under an active deployment."""
    subject = env["rider"] if rider is None else rider
    return record_encounter(
        api,
        deployment["id"],
        env["inspector"]["id"],
        occurred_at=occurred_at,
        fare_media_type=fare_media_type,
        rider_id=None if subject is None else subject["id"],
        media_reference=media_reference,
        media_validated_at=media_validated_at,
        media_expires_at=media_expires_at,
        media_zone_code=media_zone_code,
        identity_capture_method=identity_capture_method,
    )


def build_citation_chain(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """
    The chain most behaviour hangs off, run end to end: designated zone, active
    deployment, one non-compliant pending encounter, and the citation issued
    against it.

    Keyword arguments are split between the three stages by name, so a caller
    can vary the zone's multiplier, the deployment's window or the encounter's
    media in one call.
    """
    env_keys = {
        "clock_start", "zone_code", "zone_name", "required_sign_count",
        "signs_verified_count", "penalty_multiplier_bps", "enforcement_policy",
        "max_concurrent_deployments", "designate", "line_code", "mode",
        "daily_boardings", "baseline_evasion_rate_bps", "platform_segment_count",
        "assign_line_to_zone", "badge_number", "inspector_display_name",
        "certification_expiry", "inspector_status", "rider_ref",
        "rider_display_name", "demographic_band", "residence_geo_tract",
        "fare_assistance_enrolled",
    }
    deployment_keys = {
        "window_start", "window_end", "planned_inspector_count",
        "sampling_method", "target_sample_size", "observe_at",
    }
    encounter_keys = {
        "occurred_at", "fare_media_type", "rider", "media_reference",
        "media_validated_at", "media_expires_at", "media_zone_code",
        "identity_capture_method",
    }
    unknown = set(overrides) - env_keys - deployment_keys - encounter_keys
    assert not unknown, f"unrecognised chain override(s): {sorted(unknown)}"

    env = build_environment(api, **{k: v for k, v in overrides.items() if k in env_keys})
    deployment = build_active_deployment(
        api, env, **{k: v for k, v in overrides.items() if k in deployment_keys}
    )
    encounter = build_pending_encounter(
        api, env, deployment, **{k: v for k, v in overrides.items() if k in encounter_keys}
    )
    citation = issue_citation(api, encounter["id"], env["inspector"]["id"])
    return {
        **env,
        "deployment": deployment,
        "encounter": encounter,
        "citation": citation,
    }


def build_upheld_citation_chain(
    api: ApiClient,
    *,
    contest_at: str = OBSERVATION_AT,
    decided_at: str = "2026-08-05T09:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Carry the citation chain through a contest and an upholding hearing, which
    is the only shape an appeal can be filed against.
    """
    chain = build_citation_chain(api, **overrides)
    if contest_at is not None:
        move_clock(api, contest_at)
    hearing = contest(api, chain["citation"]["id"], chain["rider"]["id"])
    if decided_at is not None:
        move_clock(api, decided_at)
    hearing = decide_hearing(api, hearing["id"], "UPHOLD")
    chain["hearing"] = hearing
    chain["citation"] = read_citation(api, chain["citation"]["id"])
    return chain


# ── The client fixture ───────────────────────────────────────────────

@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    import os

    base_url = os.environ.get("_PRD_BENCH_API_URL") or os.environ.get("API_BASE_URL")
    return ApiClient(base_url)
