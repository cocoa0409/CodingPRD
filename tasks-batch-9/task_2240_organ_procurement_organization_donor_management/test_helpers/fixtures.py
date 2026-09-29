"""Composite setup helpers and pytest fixtures.

The API is a long pipeline: a hospital partner precedes a death referral, which
precedes an eligibility screening, a risk assessment, a director's ruling, an
authorization packet, its finalization, a donor case, an organ, an evaluation, a
match run, an offer response, a recovery team, an operating-room booking, a
cross-clamp, a transport asset and finally a dispatch.  Almost every behavioural
claim in the specification sits somewhere along that chain, so the builders here
are layered:

* Tier 1 -- single-step primitives, one per create/action endpoint.
* Tier 2 -- entity-hierarchy builders that walk the chain to a named point.
* Tier 3 -- full-lifecycle shortcuts (allocatable, offering, accepted,
  recovered, dispatched).
* Tier 4 -- accumulation and threshold targeting (posture samples, info-request
  budgets, increased-risk donors, expiring offers).
* Tier 5 -- finalization and terminal postures (restricted, frozen, rescinded,
  closed).

Every builder uses the lenient success extractor, so a broken setup step fails
loudly with the server's own error identifier instead of surfacing later as a
confusing assertion.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import OpoApiClient, candidate, candidate_sequence
from .api_errors import register_error_status_map
from .assertions import shift_minutes
from .constants import CIT_LIMIT_MINUTES, DEFAULT_CLOCK
from .test_users import (
    ALLOCATION_USER,
    AUTH_USER_1,
    AUTH_USER_2,
    DIRECTOR_USER,
    DIRECTOR_USER_2,
    make_allocation_specialist_headers,
    make_anonymous_headers,
    make_authorization_specialist_headers,
    make_donor_coordinator_headers,
    make_hospital_referral_clerk_headers,
    make_medical_director_headers,
    make_opo_admin_headers,
    make_recovery_logistics_headers,
    make_referral_coordinator_headers,
    make_serology_lab_headers,
)


# ===========================================================================
# The acting environment
# ===========================================================================
@dataclass
class Env:
    """One API client plus a pre-built header set for every declared role."""

    api: OpoApiClient
    admin: Dict[str, str]
    coordinator: Dict[str, str]
    lab: Dict[str, str]
    director: Dict[str, str]
    director_two: Dict[str, str]
    auth_one: Dict[str, str]
    auth_two: Dict[str, str]
    donor: Dict[str, str]
    alloc: Dict[str, str]
    logistics: Dict[str, str]
    anonymous: Dict[str, str]
    clock: str = DEFAULT_CLOCK

    # -- logical clock ---------------------------------------------------
    def set_clock(self, instant: str) -> str:
        get_success_data(self.api.set_clock(instant, self.admin))
        self.clock = instant
        return instant

    def advance_minutes(self, minutes: int) -> str:
        return self.set_clock(shift_minutes(self.clock, minutes))

    def clerk_for(self, hospital_id: str) -> Dict[str, str]:
        return make_hospital_referral_clerk_headers(hospital_id)


# ===========================================================================
# Tier 1 -- single-step primitives
# ===========================================================================
def create_hospital(env: Env, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        env.api.create_hospital_partner(f.hospital_partner_payload(**overrides), env.admin)
    )


def create_team(env: Env, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        env.api.create_recovery_team(f.recovery_team_payload(**overrides), env.admin)
    )


def create_asset(env: Env, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        env.api.create_transport_asset(f.transport_asset_payload(**overrides), env.admin)
    )


def create_referral(
    env: Env,
    hospital_id: str,
    trigger_event_at: str,
    *,
    as_clerk: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """Place a referral, optionally acting as the hospital's own clerk."""
    headers = env.clerk_for(hospital_id) if as_clerk else env.coordinator
    return get_success_data(
        env.api.create_death_referral(
            f.death_referral_payload(hospital_id, trigger_event_at, **overrides),
            headers,
        )
    )


def open_screening(env: Env, referral_id: str) -> Dict[str, Any]:
    return get_success_data(env.api.create_screening(referral_id, env.coordinator))


def submit_assessment(
    env: Env,
    screening_id: str,
    version: int,
    risk_factors: Optional[List[str]] = None,
    informant_reliability: str = "PRIMARY_NEXT_OF_KIN",
    as_user: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = (
        make_referral_coordinator_headers(as_user) if as_user else env.coordinator
    )
    payload = f.risk_assessment_payload(
        version, risk_factors, informant_reliability, **overrides
    )
    return get_success_data(
        env.api.submit_risk_assessment(screening_id, payload, headers)
    )


def rule_screening(
    env: Env,
    screening_id: str,
    decision: str = "CLEARED",
    as_user: str = DIRECTOR_USER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        env.api.submit_screening_decision(
            screening_id,
            f.screening_decision_payload(decision, **overrides),
            make_medical_director_headers(as_user),
        )
    )


def file_serology(
    env: Env, screening_id: str, marker: str, result: str, **overrides: Any
) -> Dict[str, Any]:
    resulted_at = overrides.pop("resulted_at", env.clock)
    return get_success_data(
        env.api.file_serology_result(
            screening_id,
            f.serology_result_payload(marker, result, resulted_at, **overrides),
            env.lab,
        )
    )


def open_registry_authorization(
    env: Env, referral_id: str, as_user: str = AUTH_USER_1, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        env.api.create_authorization(
            referral_id,
            f.registry_authorization_payload(**overrides),
            make_authorization_specialist_headers(as_user),
        )
    )


def open_nok_authorization(
    env: Env, referral_id: str, as_user: str = AUTH_USER_1, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        env.api.create_authorization(
            referral_id,
            f.nok_authorization_payload(**overrides),
            make_authorization_specialist_headers(as_user),
        )
    )


def record_nok_contact(
    env: Env,
    authorization_id: str,
    relationship: str,
    response: str,
    as_user: str = AUTH_USER_1,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        env.api.create_nok_contact(
            authorization_id,
            f.nok_contact_payload(relationship, response, **overrides),
            make_authorization_specialist_headers(as_user),
        )
    )


def upload_document(
    env: Env,
    authorization_id: str,
    document_type: str,
    as_user: str = AUTH_USER_1,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        env.api.upload_document(
            authorization_id,
            f.document_payload(document_type, **overrides),
            make_authorization_specialist_headers(as_user),
        )
    )


def finalize_authorization(
    env: Env, authorization_id: str, as_user: str = AUTH_USER_2
) -> Dict[str, Any]:
    return get_success_data(
        env.api.finalize_authorization(
            authorization_id, make_authorization_specialist_headers(as_user)
        )
    )


def create_case(env: Env, referral_id: str, authorization_id: str, **overrides: Any):
    return get_success_data(
        env.api.create_donor_case(
            f.donor_case_payload(referral_id, authorization_id, **overrides), env.donor
        )
    )


def chart_observation(env: Env, case_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(env.api.create_observation(case_id, payload, env.donor))


def register_organ(env: Env, case_id: str, organ_type: str) -> Dict[str, Any]:
    return get_success_data(
        env.api.create_organ(case_id, f.organ_payload(organ_type), env.donor)
    )


def evaluate_organ(
    env: Env,
    organ_id: str,
    decision: str = "ALLOCATABLE",
    as_user: str = DIRECTOR_USER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        env.api.submit_organ_evaluation(
            organ_id,
            f.organ_evaluation_payload(decision, **overrides),
            make_medical_director_headers(as_user),
        )
    )


def read_organ(env: Env, organ_id: str) -> Dict[str, Any]:
    return get_success_data(env.api.get_organ(organ_id, env.alloc))


def read_case(env: Env, case_id: str) -> Dict[str, Any]:
    return get_success_data(env.api.get_donor_case(case_id, env.donor))


def read_run(env: Env, run_id: str) -> Dict[str, Any]:
    return get_success_data(env.api.get_match_run(run_id, env.alloc))


def read_team(env: Env, team_id: str) -> Dict[str, Any]:
    return get_success_data(env.api.get_recovery_team(team_id, env.logistics))


def read_asset(env: Env, asset_id: str) -> Dict[str, Any]:
    return get_success_data(env.api.get_transport_asset(asset_id, env.logistics))


def read_authorization(env: Env, authorization_id: str) -> Dict[str, Any]:
    return get_success_data(
        env.api.get_authorization(authorization_id, env.auth_one)
    )


def read_screening(env: Env, screening_id: str) -> Dict[str, Any]:
    return get_success_data(env.api.get_screening(screening_id, env.coordinator))


def read_referral(env: Env, referral_id: str) -> Dict[str, Any]:
    return get_success_data(env.api.get_death_referral(referral_id, env.coordinator))


def read_operation(env: Env, operation_id: str) -> Dict[str, Any]:
    return get_success_data(
        env.api.get_recovery_operation(operation_id, env.logistics)
    )


def read_hospital(env: Env, hospital_id: str) -> Dict[str, Any]:
    return get_success_data(env.api.get_hospital_partner(hospital_id, env.admin))


def read_performance(env: Env, hospital_id: str, **params: Any) -> Dict[str, Any]:
    """The computed recertification read, which persists nothing."""
    return get_success_data(
        env.api.get_hospital_performance(hospital_id, env.admin, params or None)
    )


def list_offers(env: Env, run_id: str) -> List[Dict[str, Any]]:
    return get_success_data(env.api.list_offers(run_id, env.alloc))


def list_observations(env: Env, case_id: str, **params: Any) -> List[Dict[str, Any]]:
    return get_success_data(
        env.api.list_observations(case_id, env.donor, params or None)
    )


def list_serology(env: Env, screening_id: str, **params: Any) -> List[Dict[str, Any]]:
    return get_success_data(
        env.api.list_serology_results(screening_id, env.lab, params or None)
    )


def list_nok_contacts(
    env: Env, authorization_id: str, **params: Any
) -> List[Dict[str, Any]]:
    return get_success_data(
        env.api.list_nok_contacts(authorization_id, env.auth_one, params or None)
    )


def list_screenings(env: Env, referral_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        env.api.list_screenings_for_referral(referral_id, env.coordinator)
    )


def list_authorizations(env: Env, referral_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        env.api.list_authorizations_for_referral(referral_id, env.auth_one)
    )


def list_runs(env: Env, organ_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        env.api.list_match_runs_for_organ(organ_id, env.alloc)
    )


def advance_run(env: Env, run_id: str) -> Dict[str, Any]:
    return get_success_data(env.api.advance_match_run(run_id, env.alloc))


def open_match_run(
    env: Env,
    organ_id: str,
    candidates: Optional[List[Dict[str, Any]]] = None,
    primary_offer_slots: Optional[int] = None,
    expected_organ_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = (
        expected_organ_version
        if expected_organ_version is not None
        else read_organ(env, organ_id)["version"]
    )
    payload = f.match_run_payload(
        version, candidates or candidate_sequence(1, 240)
    )
    if primary_offer_slots is not None:
        payload["primary_offer_slots"] = primary_offer_slots
    return get_success_data(env.api.create_match_run(organ_id, payload, env.alloc))


def respond_to_offer(
    env: Env,
    run_id: str,
    offer_id: str,
    decision: str,
    as_user: str = ALLOCATION_USER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        env.api.respond_to_offer(
            run_id,
            offer_id,
            f.offer_response_payload(decision, **overrides),
            make_allocation_specialist_headers(as_user),
        )
    )


def book_operation(
    env: Env, case_id: str, team_id: str, or_start_at: str, or_end_at: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        env.api.create_recovery_operation(
            case_id,
            f.recovery_operation_payload(team_id, or_start_at, or_end_at, **overrides),
            env.logistics,
        )
    )


def cross_clamp(env: Env, operation_id: str) -> Dict[str, Any]:
    return get_success_data(
        env.api.record_cross_clamp(operation_id, env.logistics)
    )


def cancel_operation(env: Env, operation_id: str) -> Dict[str, Any]:
    return get_success_data(
        env.api.cancel_recovery_operation(operation_id, env.logistics)
    )


def dispatch_transport(
    env: Env,
    organ_id: str,
    asset_id: str,
    depart_at: str,
    arrive_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        env.api.dispatch_transport(
            organ_id,
            f.transport_payload(asset_id, depart_at, arrive_at, **overrides),
            env.logistics,
        )
    )


def record_disposition(
    env: Env, organ_id: str, disposition: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        env.api.record_disposition(
            organ_id, f.disposition_payload(disposition, **overrides), env.director
        )
    )


# ===========================================================================
# Tier 2 -- entity-hierarchy builders
# ===========================================================================
@dataclass
class Bundle:
    """Every identifier produced while walking the pipeline."""

    env: Env
    hospital: Dict[str, Any]
    referral: Optional[Dict[str, Any]] = None
    screening: Optional[Dict[str, Any]] = None
    authorization: Optional[Dict[str, Any]] = None
    case: Optional[Dict[str, Any]] = None
    organs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    run: Optional[Dict[str, Any]] = None
    offers: List[Dict[str, Any]] = field(default_factory=list)
    team: Optional[Dict[str, Any]] = None
    operation: Optional[Dict[str, Any]] = None
    asset: Optional[Dict[str, Any]] = None

    # -- convenient identifier accessors ---------------------------------
    @property
    def hospital_id(self) -> str:
        return self.hospital["id"]

    @property
    def referral_id(self) -> str:
        return self.referral["id"]

    @property
    def screening_id(self) -> str:
        return self.screening["id"]

    @property
    def authorization_id(self) -> str:
        return self.authorization["id"]

    @property
    def case_id(self) -> str:
        return self.case["id"]

    @property
    def run_id(self) -> str:
        return self.run["id"]

    def organ(self, organ_type: str) -> Dict[str, Any]:
        return self.organs[organ_type]

    def organ_id(self, organ_type: str) -> str:
        return self.organs[organ_type]["id"]

    @property
    def only_organ(self) -> Dict[str, Any]:
        assert len(self.organs) == 1, "bundle carries more than one organ"
        return next(iter(self.organs.values()))

    @property
    def only_organ_id(self) -> str:
        return self.only_organ["id"]

    # -- refreshers ------------------------------------------------------
    def refresh_case(self) -> Dict[str, Any]:
        self.case = read_case(self.env, self.case_id)
        return self.case

    def refresh_organ(self, organ_type: str) -> Dict[str, Any]:
        organ = read_organ(self.env, self.organ_id(organ_type))
        self.organs[organ_type] = organ
        return organ

    def refresh_run(self) -> Dict[str, Any]:
        self.run = read_run(self.env, self.run_id)
        return self.run

    def refresh_offers(self) -> List[Dict[str, Any]]:
        self.offers = list_offers(self.env, self.run_id)
        return self.offers


def hospital_only(env: Env, clock: str, **overrides: Any) -> Bundle:
    """A registered hospital partner and nothing else."""
    env.set_clock(clock)
    return Bundle(env=env, hospital=create_hospital(env, **overrides))


def received_referral(
    env: Env,
    clock: str = "2026-09-01T08:00:00Z",
    lag_minutes: int = 30,
    hospital: Optional[Dict[str, Any]] = None,
    **referral_overrides: Any,
) -> Bundle:
    """A hospital plus one referral whose clinical-trigger lag is ``lag_minutes``."""
    if hospital is None:
        bundle = hospital_only(env, clock)
    else:
        env.set_clock(clock)
        bundle = Bundle(env=env, hospital=hospital)
    trigger_at = shift_minutes(clock, -lag_minutes)
    bundle.referral = create_referral(
        env, bundle.hospital_id, trigger_at, **referral_overrides
    )
    return bundle


def screened_referral(
    env: Env,
    clock: str = "2026-09-01T08:00:00Z",
    lag_minutes: int = 30,
    risk_factors: Optional[List[str]] = None,
    informant_reliability: str = "PRIMARY_NEXT_OF_KIN",
    assessor: Optional[str] = None,
    **referral_overrides: Any,
) -> Bundle:
    """Referral with a PENDING screening that already carries a risk score."""
    bundle = received_referral(
        env, clock, lag_minutes, **referral_overrides
    )
    bundle.screening = open_screening(env, bundle.referral_id)
    bundle.screening = submit_assessment(
        env,
        bundle.screening_id,
        bundle.screening["version"],
        risk_factors,
        informant_reliability,
        as_user=assessor,
    )
    return bundle


def cleared_referral(
    env: Env,
    clock: str = "2026-09-01T08:00:00Z",
    lag_minutes: int = 30,
    risk_factors: Optional[List[str]] = None,
    informant_reliability: str = "PRIMARY_NEXT_OF_KIN",
    **referral_overrides: Any,
) -> Bundle:
    """Referral in SCREEN_CLEARED, ruled by a director who did not assess."""
    bundle = screened_referral(
        env, clock, lag_minutes, risk_factors, informant_reliability, **referral_overrides
    )
    bundle.screening = rule_screening(
        env, bundle.screening_id, "CLEARED", as_user=DIRECTOR_USER
    )
    return bundle


def authorized_referral(
    env: Env,
    clock: str = "2026-09-01T08:00:00Z",
    lag_minutes: int = 30,
    risk_factors: Optional[List[str]] = None,
    informant_reliability: str = "PRIMARY_NEXT_OF_KIN",
    **referral_overrides: Any,
) -> Bundle:
    """Registry-branch packet finalized by a second specialist."""
    bundle = cleared_referral(
        env, clock, lag_minutes, risk_factors, informant_reliability, **referral_overrides
    )
    bundle.authorization = open_registry_authorization(env, bundle.referral_id)
    bundle.authorization = finalize_authorization(
        env, bundle.authorization_id, as_user=AUTH_USER_2
    )
    return bundle


def nok_consented_referral(
    env: Env,
    clock: str = "2026-09-01T08:00:00Z",
    relationship: str = "SPOUSE",
    consent_recorder: str = AUTH_USER_1,
    with_documents: bool = True,
    witness_name: Optional[str] = "Jane Roe",
) -> Bundle:
    """Next-of-kin branch walked to NOK_CONSENTED, optionally document-complete."""
    bundle = cleared_referral(env, clock)
    bundle.authorization = open_nok_authorization(
        env, bundle.referral_id, as_user=consent_recorder
    )
    record_nok_contact(
        env,
        bundle.authorization_id,
        relationship,
        "CONSENT",
        as_user=consent_recorder,
        contact_note="Consent by phone",
    )
    bundle.authorization = read_authorization(env, bundle.authorization_id)
    if with_documents:
        upload_document(
            env,
            bundle.authorization_id,
            "SIGNED_CONSENT_FORM",
            as_user=consent_recorder,
        )
        extra: Dict[str, Any] = {}
        if witness_name is not None:
            extra["witness_name"] = witness_name
        bundle.authorization = upload_document(
            env,
            bundle.authorization_id,
            "WITNESS_ATTESTATION",
            as_user=consent_recorder,
            **extra,
        )
    return bundle


def nok_authorized_referral(
    env: Env,
    clock: str = "2026-09-01T08:00:00Z",
    relationship: str = "SPOUSE",
    consent_recorder: str = AUTH_USER_1,
    finalizer: str = AUTH_USER_2,
) -> Bundle:
    """Next-of-kin branch carried all the way to AUTHORIZED."""
    bundle = nok_consented_referral(
        env, clock, relationship, consent_recorder, with_documents=True
    )
    bundle.authorization = finalize_authorization(
        env, bundle.authorization_id, as_user=finalizer
    )
    return bundle


# ===========================================================================
# Tier 3 -- full-lifecycle shortcuts
# ===========================================================================
def converted_case(
    env: Env,
    clock: str = "2026-09-01T08:00:00Z",
    lag_minutes: int = 30,
    organ_types: Sequence[str] = (),
    risk_factors: Optional[List[str]] = None,
    informant_reliability: str = "PRIMARY_NEXT_OF_KIN",
    nok_branch: bool = False,
    **referral_overrides: Any,
) -> Bundle:
    """An AUTHORIZED referral converted into a donor case, with organs registered."""
    if nok_branch:
        bundle = nok_authorized_referral(env, clock)
    else:
        bundle = authorized_referral(
            env,
            clock,
            lag_minutes,
            risk_factors,
            informant_reliability,
            **referral_overrides,
        )
    bundle.case = create_case(env, bundle.referral_id, bundle.authorization_id)
    for organ_type in organ_types:
        bundle.organs[organ_type] = register_organ(env, bundle.case_id, organ_type)
    return bundle


def allocatable_organ(
    env: Env,
    organ_type: str = "KIDNEY_LEFT",
    clock: str = "2026-09-01T08:00:00Z",
    extra_organ_types: Sequence[str] = (),
    risk_factors: Optional[List[str]] = None,
    informant_reliability: str = "PRIMARY_NEXT_OF_KIN",
) -> Bundle:
    """A donor case whose named organ has been declared ALLOCATABLE."""
    bundle = converted_case(
        env,
        clock,
        organ_types=[organ_type, *extra_organ_types],
        risk_factors=risk_factors,
        informant_reliability=informant_reliability,
    )
    bundle.organs[organ_type] = evaluate_organ(
        env, bundle.organ_id(organ_type), "ALLOCATABLE"
    )
    return bundle


def offering_organ(
    env: Env,
    organ_type: str = "KIDNEY_LEFT",
    clock: str = "2026-09-01T08:00:00Z",
    candidate_count: int = 1,
    primary_offer_slots: Optional[int] = 1,
    acceptance_clock_minutes: Optional[int] = 240,
    extra_organ_types: Sequence[str] = (),
    risk_factors: Optional[List[str]] = None,
    informant_reliability: str = "PRIMARY_NEXT_OF_KIN",
) -> Bundle:
    """An OFFERING organ behind an OPEN run whose primary slots are filled."""
    bundle = allocatable_organ(
        env,
        organ_type,
        clock,
        extra_organ_types,
        risk_factors,
        informant_reliability,
    )
    bundle.run = open_match_run(
        env,
        bundle.organ_id(organ_type),
        candidate_sequence(candidate_count, acceptance_clock_minutes),
        primary_offer_slots,
    )
    bundle.refresh_offers()
    return bundle


def accepted_organ(
    env: Env,
    organ_type: str = "KIDNEY_LEFT",
    clock: str = "2026-09-01T08:00:00Z",
    candidate_count: int = 1,
    primary_offer_slots: Optional[int] = 1,
    increased_risk_ack: Optional[bool] = None,
    extra_organ_types: Sequence[str] = (),
    risk_factors: Optional[List[str]] = None,
    informant_reliability: str = "PRIMARY_NEXT_OF_KIN",
) -> Bundle:
    """The rank-one offer accepted, so the organ sits in ACCEPTED."""
    bundle = offering_organ(
        env,
        organ_type,
        clock,
        candidate_count,
        primary_offer_slots,
        240,
        extra_organ_types,
        risk_factors,
        informant_reliability,
    )
    overrides: Dict[str, Any] = {}
    if increased_risk_ack is not None:
        overrides["increased_risk_ack"] = increased_risk_ack
    respond_to_offer(
        env, bundle.run_id, bundle.offers[0]["id"], "ACCEPT", **overrides
    )
    bundle.refresh_organ(organ_type)
    bundle.refresh_run()
    bundle.refresh_offers()
    return bundle


def recovered_organ(
    env: Env,
    organ_type: str = "KIDNEY_LEFT",
    clock: str = "2026-09-01T08:00:00Z",
    specialty: str = "MULTIORGAN",
    or_start_offset_minutes: int = 120,
    or_duration_minutes: int = 120,
    clamp_at_offset_minutes: int = 180,
    increased_risk_ack: Optional[bool] = None,
) -> Bundle:
    """Cross-clamp recorded, so the organ sits in RECOVERED with a clamp instant."""
    bundle = accepted_organ(
        env, organ_type, clock, increased_risk_ack=increased_risk_ack
    )
    bundle.team = create_team(env, specialty=specialty)
    or_start = shift_minutes(clock, or_start_offset_minutes)
    or_end = shift_minutes(or_start, or_duration_minutes)
    bundle.operation = book_operation(
        env, bundle.case_id, bundle.team["id"], or_start, or_end
    )
    env.set_clock(shift_minutes(clock, clamp_at_offset_minutes))
    bundle.operation = cross_clamp(env, bundle.operation["id"])
    bundle.refresh_organ(organ_type)
    return bundle


def dispatched_organ(
    env: Env,
    organ_type: str = "KIDNEY_LEFT",
    clock: str = "2026-09-01T08:00:00Z",
    transit_minutes: int = 150,
    depart_offset_minutes: int = 60,
    asset_overrides: Optional[Dict[str, Any]] = None,
) -> Bundle:
    """A recovered organ dispatched on a transport asset with a pinned projection."""
    bundle = recovered_organ(env, organ_type, clock)
    bundle.asset = create_asset(env, **(asset_overrides or {}))
    clamp_at = bundle.organ(organ_type)["cross_clamp_at"]
    depart = shift_minutes(clamp_at, depart_offset_minutes)
    arrive = shift_minutes(depart, transit_minutes)
    bundle.organs[organ_type] = dispatch_transport(
        env, bundle.organ_id(organ_type), bundle.asset["id"], depart, arrive
    )
    return bundle


# ===========================================================================
# Tier 4 -- accumulation and threshold targeting
# ===========================================================================
def hospital_with_referral_flags(
    env: Env,
    clock: str,
    timely_count: int,
    untimely_count: int,
    window_minutes: int = 60,
    ventilated: bool = True,
) -> Bundle:
    """A hospital carrying an exact mix of TIMELY and UNTIMELY referrals.

    The lifetime denominator counts every referral the hospital has ever
    placed, so this is the lever for the posture bands and for the windowed
    recertification denominator alike.
    """
    bundle = hospital_only(env, clock, timely_referral_window_minutes=window_minutes)
    for _ in range(timely_count):
        create_referral(
            env,
            bundle.hospital_id,
            shift_minutes(clock, -(window_minutes - 1)),
            ventilated=ventilated,
        )
    for _ in range(untimely_count):
        create_referral(
            env,
            bundle.hospital_id,
            shift_minutes(clock, -(window_minutes + 1)),
            ventilated=ventilated,
        )
    bundle.hospital = get_success_data(
        env.api.get_hospital_partner(bundle.hospital_id, env.admin)
    )
    return bundle


def screening_at_info_request_budget(
    env: Env, clock: str = "2026-09-01T08:00:00Z", loops: int = 2
) -> Bundle:
    """A screening bounced back ``loops`` times, each loop closed by a reassessment."""
    bundle = screened_referral(env, clock)
    for _ in range(loops):
        get_success_data(
            env.api.request_info(bundle.screening_id, env.director)
        )
        current = read_screening(env, bundle.screening_id)
        bundle.screening = submit_assessment(
            env, bundle.screening_id, current["version"]
        )
    return bundle


def increased_risk_offering_organ(
    env: Env,
    organ_type: str = "KIDNEY_LEFT",
    clock: str = "2026-09-01T08:00:00Z",
) -> Bundle:
    """An OFFERING organ on a donor case pinned INCREASED_RISK.

    Three heavy factors under the primary-next-of-kin multiplier of 1.00 sum to
    15.75, which clears the 12.00 tier threshold.
    """
    return offering_organ(
        env,
        organ_type,
        clock,
        candidate_count=1,
        primary_offer_slots=1,
        risk_factors=[
            "IV_DRUG_USE_12MO",
            "UNKNOWN_MEDICAL_SOCIAL_HISTORY",
            "HEMODIALYSIS_12MO",
            "BLOOD_TRANSFUSION_12MO",
        ],
    )


def offering_organ_with_expiring_offer(
    env: Env,
    organ_type: str = "LIVER",
    clock: str = "2026-09-01T09:00:00Z",
    acceptance_clock_minutes: int = 60,
) -> Bundle:
    """One PENDING offer whose acceptance clock is about to elapse."""
    return offering_organ(
        env,
        organ_type,
        clock,
        candidate_count=1,
        primary_offer_slots=1,
        acceptance_clock_minutes=acceptance_clock_minutes,
    )


def team_with_booked_window(
    env: Env,
    clock: str = "2026-09-01T08:00:00Z",
    organ_type: str = "KIDNEY_LEFT",
    or_start_at: Optional[str] = None,
    or_end_at: Optional[str] = None,
    turnaround_buffer_minutes: Optional[int] = None,
    specialty: str = "MULTIORGAN",
) -> Bundle:
    """An ACCEPTED organ whose team already holds one SCHEDULED window."""
    bundle = accepted_organ(env, organ_type, clock)
    overrides: Dict[str, Any] = {"specialty": specialty}
    if turnaround_buffer_minutes is not None:
        overrides["turnaround_buffer_minutes"] = turnaround_buffer_minutes
    bundle.team = create_team(env, **overrides)
    start = or_start_at or shift_minutes(clock, 120)
    end = or_end_at or shift_minutes(start, 120)
    bundle.operation = book_operation(
        env, bundle.case_id, bundle.team["id"], start, end
    )
    bundle.team = read_team(env, bundle.team["id"])
    return bundle


def asset_with_one_leg(
    env: Env,
    clock: str = "2026-09-01T08:00:00Z",
    organ_type: str = "KIDNEY_LEFT",
    capacity: Optional[int] = None,
    transit_minutes: int = 150,
) -> Bundle:
    """A transport asset already carrying one leg, for the capacity boundary."""
    overrides: Dict[str, Any] = {}
    if capacity is not None:
        overrides["concurrent_leg_capacity"] = capacity
    return dispatched_organ(
        env,
        organ_type,
        clock,
        transit_minutes=transit_minutes,
        asset_overrides=overrides,
    )


# ===========================================================================
# Tier 5 -- finalization and terminal postures
# ===========================================================================
def restricted_case(
    env: Env,
    thoracic_type: str = "HEART",
    abdominal_type: str = "KIDNEY_RIGHT",
    clock: str = "2026-09-01T09:00:00Z",
    evaluate_thoracic: bool = True,
) -> Bundle:
    """A case driven OPTIMIZED then DECOMPENSATING, so its posture is RESTRICTED.

    The first observation scores 70 (OPTIMIZED); the second scores 35, which
    drops the case to DECOMPENSATING and therefore to a RESTRICTED posture.
    """
    bundle = converted_case(
        env, clock, organ_types=[thoracic_type, abdominal_type]
    )
    if evaluate_thoracic:
        bundle.organs[thoracic_type] = evaluate_organ(
            env, bundle.organ_id(thoracic_type), "ALLOCATABLE"
        )
    first_at = shift_minutes(clock, 60)
    env.set_clock(first_at)
    chart_observation(env, bundle.case_id, f.optimized_observation_payload(first_at))
    second_at = shift_minutes(clock, 90)
    env.set_clock(second_at)
    chart_observation(
        env, bundle.case_id, f.decompensating_observation_payload(second_at)
    )
    bundle.refresh_case()
    for organ_type in list(bundle.organs):
        bundle.refresh_organ(organ_type)
    return bundle


def frozen_case_by_donor_loss(
    env: Env,
    organ_type: str = "LIVER",
    clock: str = "2026-09-01T09:00:00Z",
    evaluate: bool = True,
) -> Bundle:
    """A cardiac-arrest observation drives the case to LOST and FROZEN."""
    bundle = converted_case(env, clock, organ_types=[organ_type])
    if evaluate:
        bundle.organs[organ_type] = evaluate_organ(
            env, bundle.organ_id(organ_type), "ALLOCATABLE"
        )
    arrest_at = shift_minutes(clock, 60)
    env.set_clock(arrest_at)
    chart_observation(
        env, bundle.case_id, f.cardiac_arrest_observation_payload(arrest_at)
    )
    bundle.refresh_case()
    bundle.refresh_organ(organ_type)
    return bundle


def rescinded_authorization_case(
    env: Env,
    organ_type: str = "LIVER",
    clock: str = "2026-09-01T08:00:00Z",
) -> Bundle:
    """A next-of-kin authorized case ready for a higher-rank objection.

    Consent is taken at rank 2 after the spouse is unreachable, so a later
    spouse objection outranks the consenting relative.
    """
    bundle = cleared_referral(env, clock)
    bundle.authorization = open_nok_authorization(env, bundle.referral_id)
    record_nok_contact(env, bundle.authorization_id, "SPOUSE", "UNREACHABLE")
    record_nok_contact(env, bundle.authorization_id, "ADULT_CHILD", "CONSENT")
    upload_document(env, bundle.authorization_id, "SIGNED_CONSENT_FORM")
    upload_document(
        env, bundle.authorization_id, "WITNESS_ATTESTATION", witness_name="Jane Roe"
    )
    bundle.authorization = finalize_authorization(
        env, bundle.authorization_id, as_user=AUTH_USER_2
    )
    bundle.case = create_case(env, bundle.referral_id, bundle.authorization_id)
    bundle.organs[organ_type] = register_organ(env, bundle.case_id, organ_type)
    bundle.organs[organ_type] = evaluate_organ(
        env, bundle.organ_id(organ_type), "ALLOCATABLE"
    )
    return bundle


def nontransplantable_organ(
    env: Env,
    organ_type: str = "LIVER",
    clock: str = "2026-09-01T08:00:00Z",
    reason: Optional[str] = "ANATOMIC_ANOMALY",
    extra_organ_types: Sequence[str] = (),
) -> Bundle:
    """A case whose named organ was ruled NON_TRANSPLANTABLE at evaluation."""
    bundle = converted_case(
        env, clock, organ_types=[organ_type, *extra_organ_types]
    )
    overrides: Dict[str, Any] = {}
    if reason is not None:
        overrides["nontransplantable_reason"] = reason
    bundle.organs[organ_type] = evaluate_organ(
        env, bundle.organ_id(organ_type), "NON_TRANSPLANTABLE", **overrides
    )
    return bundle


def cit_limit_for(organ_type: str) -> int:
    return CIT_LIMIT_MINUTES[organ_type]


# ===========================================================================
# pytest fixtures
# ===========================================================================
@pytest.fixture(scope="session", autouse=True)
def _register_error_statuses():
    """Publish the declared HTTP status of every error identifier once."""
    register_error_status_map()


@pytest.fixture
def api() -> OpoApiClient:
    return OpoApiClient()


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    return make_opo_admin_headers()


@pytest.fixture
def coordinator_headers() -> Dict[str, str]:
    return make_referral_coordinator_headers()


@pytest.fixture
def lab_headers() -> Dict[str, str]:
    return make_serology_lab_headers()


@pytest.fixture
def director_headers() -> Dict[str, str]:
    return make_medical_director_headers(DIRECTOR_USER)


@pytest.fixture
def second_director_headers() -> Dict[str, str]:
    return make_medical_director_headers(DIRECTOR_USER_2)


@pytest.fixture
def auth_specialist_headers() -> Dict[str, str]:
    return make_authorization_specialist_headers(AUTH_USER_1)


@pytest.fixture
def second_auth_specialist_headers() -> Dict[str, str]:
    return make_authorization_specialist_headers(AUTH_USER_2)


@pytest.fixture
def donor_coordinator_headers() -> Dict[str, str]:
    return make_donor_coordinator_headers()


@pytest.fixture
def allocation_headers() -> Dict[str, str]:
    return make_allocation_specialist_headers()


@pytest.fixture
def logistics_headers() -> Dict[str, str]:
    return make_recovery_logistics_headers()


@pytest.fixture
def anonymous_headers() -> Dict[str, str]:
    return make_anonymous_headers()


@pytest.fixture
def env(api: OpoApiClient) -> Env:
    """The acting environment every builder in this module takes."""
    return Env(
        api=api,
        admin=make_opo_admin_headers(),
        coordinator=make_referral_coordinator_headers(),
        lab=make_serology_lab_headers(),
        director=make_medical_director_headers(DIRECTOR_USER),
        director_two=make_medical_director_headers(DIRECTOR_USER_2),
        auth_one=make_authorization_specialist_headers(AUTH_USER_1),
        auth_two=make_authorization_specialist_headers(AUTH_USER_2),
        donor=make_donor_coordinator_headers(),
        alloc=make_allocation_specialist_headers(),
        logistics=make_recovery_logistics_headers(),
        anonymous=make_anonymous_headers(),
    )
