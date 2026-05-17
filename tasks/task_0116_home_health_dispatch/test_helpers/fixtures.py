"""Composite setup helpers — multi-step preambles tests can reuse.

The home-health-dispatch workflow is long: create patient -> create
OASIS (DRAFT) -> lock OASIS -> open Episode -> schedule one or more
Visits -> complete each Visit (requires clock advance) -> optionally
record Mileage on completed Visits -> advance clock past end_date ->
close Episode (BillingSpecialist) -> read PDGMClaim. Or, in the
abandonment branch: advance clock past end_date + 7 -> expire-sweep
(PlatformAdmin) -> read EXPIRED Episode and FINALIZED PDGMClaim.

IDENTITY THREADING — PRD §2.1:

- FieldClinician is ENTITY-BACKED. Every FieldClinician-driven call
  (POST /visits/{visitId}/complete, POST /visits/{visitId}/mileage)
  MUST mint headers via make_field_clinician_headers(clinician["id"]).
  The fixtures here remember the acting Clinician.id for each Visit
  and thread it through completion + mileage calls.

- IntakeCoordinator, BillingSpecialist, and PlatformAdmin are OPAQUE.
  Their shared TEST_USERS headers are canonical for every call.

Setup helpers use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    EPISODE_END_OFFSET_DAYS,
    EPISODE_EXPIRE_GRACE_DAYS,
    TEST_DEFAULTS,
)
from .factories import (
    clock_advance_payload,
    create_clinician_payload,
    create_episode_payload,
    create_mileage_payload,
    create_oasis_payload,
    create_patient_payload,
    create_visit_payload,
    date_offset,
    patch_clinician_payload,
    patch_patient_payload,
)
from .test_users import (
    TEST_USERS,
    make_field_clinician_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.7 / §4 (PlatformAdmin only)
# ===========================================================================
def advance_clock_to(target_date: str,
                     *,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /_clock/advance to a YYYY-MM-DD target. PRD §2.7:
    PlatformAdmin only."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(target_date=target_date), headers,
    )
    return get_success_data(resp)


def get_clock(*, headers: Optional[Dict[str, str]] = None
              ) -> Dict[str, Any]:
    """GET /_clock."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_clock(headers)
    return get_success_data(resp)


def anchor_clock(target_date: Optional[str] = None) -> Dict[str, Any]:
    """Pin the clock to a known anchor date so all downstream date
    arithmetic is deterministic. Defaults to the difficulty-design
    January 2026 anchor.

    Idempotent: PRD §2.7 forbids moving the clock backward
    (ERR_CLOCK_BACKWARDS). If the clock has already advanced past
    `target_date` (e.g., a prior sub-fixture in the same test moved it
    forward), leave it where it is and return the current ClockState.
    The anchor is a *floor* for downstream date arithmetic, not a hard
    pin.
    """
    target_date = target_date or TEST_DEFAULTS["CLOCK_ANCHOR_DATE"]
    current = get_clock()
    if current.get("current_date", "") >= target_date:
        return current
    return advance_clock_to(target_date)


def run_expire_sweep(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Any:
    """POST /_sweep/expire-episodes. PRD §3.4 / §4: PlatformAdmin only.
    Returns the list of episodes the sweep affected."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.sweep_expire_episodes(headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 0: reference data — Patient and Clinician creation helpers.
# ===========================================================================
def create_patient(
    *,
    full_name: Optional[str] = None,
    medicare_id: Optional[str] = None,
    home_zip: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /patients — IntakeCoordinator or PlatformAdmin."""
    headers = headers or TEST_USERS["intake_coordinator_headers"]
    resp = api_client.create_patient(
        create_patient_payload(
            full_name=full_name,
            medicare_id=medicare_id,
            home_zip=home_zip,
        ),
        headers,
    )
    return get_success_data(resp)


def patch_patient(
    *,
    patient: Dict[str, Any],
    full_name: Optional[str] = None,
    home_zip: Optional[str] = None,
    include_version: bool = True,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PATCH /patients/{patientId}. include_version controls whether
    optimistic-concurrency version is sent (PRD §2.8 says it is
    optional)."""
    headers = headers or TEST_USERS["intake_coordinator_headers"]
    version = patient["version"] if include_version else None
    resp = api_client.patch_patient(
        patient["id"],
        patch_patient_payload(
            full_name=full_name, home_zip=home_zip, version=version,
        ),
        headers,
    )
    return get_success_data(resp)


def create_clinician(
    *,
    full_name: Optional[str] = None,
    discipline: str = "SN",
    license_expiration_date: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /clinicians — PlatformAdmin only."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.create_clinician(
        create_clinician_payload(
            full_name=full_name,
            discipline=discipline,
            license_expiration_date=license_expiration_date,
        ),
        headers,
    )
    return get_success_data(resp)


def patch_clinician(
    *,
    clinician: Dict[str, Any],
    status: Optional[str] = None,
    license_expiration_date: Optional[str] = None,
    include_version: bool = True,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PATCH /clinicians/{clinicianId} — PlatformAdmin only."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    version = clinician["version"] if include_version else None
    resp = api_client.patch_clinician(
        clinician["id"],
        patch_clinician_payload(
            status=status,
            license_expiration_date=license_expiration_date,
            version=version,
        ),
        headers,
    )
    return get_success_data(resp)


def suspend_clinician(clinician: Dict[str, Any]) -> Dict[str, Any]:
    """Move a clinician to SUSPENDED via PATCH."""
    return patch_clinician(clinician=clinician, status="SUSPENDED")


# ===========================================================================
# Tier 1: OASIS create + lock.
# ===========================================================================
def create_oasis(
    *,
    patient: Dict[str, Any],
    assessment_reason: str = "START_OF_CARE",
    assessment_date: Optional[str] = None,
    clinical_grouping: str = "MMTA_OTHER",
    functional_impairment_level: str = "MEDIUM",
    admission_source: str = "COMMUNITY",
    hha_companion_hours_ordered: Optional[float] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /patients/{patientId}/oasis — IntakeCoordinator."""
    headers = headers or TEST_USERS["intake_coordinator_headers"]
    resp = api_client.create_oasis(
        patient["id"],
        create_oasis_payload(
            assessment_reason=assessment_reason,
            assessment_date=assessment_date,
            clinical_grouping=clinical_grouping,
            functional_impairment_level=functional_impairment_level,
            admission_source=admission_source,
            hha_companion_hours_ordered=hha_companion_hours_ordered,
        ),
        headers,
    )
    return get_success_data(resp)


def lock_oasis(
    *,
    patient: Dict[str, Any],
    oasis: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /patients/{patientId}/oasis/{oasisId}/lock —
    IntakeCoordinator."""
    headers = headers or TEST_USERS["intake_coordinator_headers"]
    resp = api_client.lock_oasis(patient["id"], oasis["id"], headers)
    return get_success_data(resp)


def create_and_lock_oasis(
    *,
    patient: Dict[str, Any],
    assessment_reason: str = "START_OF_CARE",
    assessment_date: Optional[str] = None,
    clinical_grouping: str = "MMTA_OTHER",
    functional_impairment_level: str = "MEDIUM",
    admission_source: str = "COMMUNITY",
    hha_companion_hours_ordered: Optional[float] = None,
) -> Dict[str, Any]:
    """Create a DRAFT OASIS and immediately lock it."""
    oasis = create_oasis(
        patient=patient,
        assessment_reason=assessment_reason,
        assessment_date=assessment_date,
        clinical_grouping=clinical_grouping,
        functional_impairment_level=functional_impairment_level,
        admission_source=admission_source,
        hha_companion_hours_ordered=hha_companion_hours_ordered,
    )
    return lock_oasis(patient=patient, oasis=oasis)


# ===========================================================================
# Tier 2: Episode open.
# ===========================================================================
def open_episode(
    *,
    patient: Dict[str, Any],
    oasis: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /patients/{patientId}/episodes — IntakeCoordinator.
    PRD §3.4 requires source OASIS to be LOCKED."""
    headers = headers or TEST_USERS["intake_coordinator_headers"]
    resp = api_client.create_episode(
        patient["id"],
        create_episode_payload(source_oasis_id=oasis["id"]),
        headers,
    )
    return get_success_data(resp)


def setup_open_episode(
    *,
    assessment_reason: str = "START_OF_CARE",
    assessment_date: Optional[str] = None,
    clinical_grouping: str = "MMTA_OTHER",
    functional_impairment_level: str = "MEDIUM",
    admission_source: str = "COMMUNITY",
    hha_companion_hours_ordered: Optional[float] = None,
    home_zip: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Patient -> OASIS -> lock -> Episode. Returns (patient, oasis,
    episode) all in their post-mutation projections."""
    assessment_date = assessment_date or TEST_DEFAULTS["CLOCK_ANCHOR_DATE"]
    patient = create_patient(home_zip=home_zip)
    oasis = create_and_lock_oasis(
        patient=patient,
        assessment_reason=assessment_reason,
        assessment_date=assessment_date,
        clinical_grouping=clinical_grouping,
        functional_impairment_level=functional_impairment_level,
        admission_source=admission_source,
        hha_companion_hours_ordered=hha_companion_hours_ordered,
    )
    episode = open_episode(patient=patient, oasis=oasis)
    return patient, oasis, episode


# ===========================================================================
# Tier 3: Visit schedule / complete / cancel.
# ===========================================================================
def schedule_visit(
    *,
    episode: Dict[str, Any],
    clinician: Dict[str, Any],
    visit_type: Optional[str] = None,
    visit_date: Optional[str] = None,
    start_minute: int = 480,
    end_minute: int = 540,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /episodes/{episodeId}/visits — IntakeCoordinator."""
    headers = headers or TEST_USERS["intake_coordinator_headers"]
    visit_type = visit_type or clinician.get("discipline", "SN")
    # Default visit_date to the episode's start_date for safety.
    visit_date = visit_date or episode["start_date"]
    resp = api_client.create_visit(
        episode["id"],
        create_visit_payload(
            clinician_id=clinician["id"],
            visit_type=visit_type,
            visit_date=visit_date,
            start_minute=start_minute,
            end_minute=end_minute,
        ),
        headers,
    )
    return get_success_data(resp)


def complete_visit(
    *,
    visit: Dict[str, Any],
    clinician: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /visits/{visitId}/complete — FieldClinician.

    PRD §3.5: "The completion action requires that X-User-ID equal the
    visit's clinician_id". The headers are minted from the owning
    Clinician.id by default — pass `headers=` only when intentionally
    testing the ownership rule."""
    headers = headers or make_field_clinician_headers(clinician["id"])
    resp = api_client.complete_visit(visit["id"], headers)
    return get_success_data(resp)


def cancel_visit(
    *,
    visit: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /visits/{visitId}/cancel — IntakeCoordinator."""
    headers = headers or TEST_USERS["intake_coordinator_headers"]
    resp = api_client.cancel_visit(visit["id"], headers)
    return get_success_data(resp)


def schedule_and_complete_visit(
    *,
    episode: Dict[str, Any],
    clinician: Dict[str, Any],
    visit_type: Optional[str] = None,
    visit_date: Optional[str] = None,
    start_minute: int = 480,
    end_minute: int = 540,
) -> Dict[str, Any]:
    """Schedule a Visit, advance the clock to visit_date if needed, and
    then complete it via the owning Clinician's headers.

    PRD §3.5: "The completion action requires that … current_date be on
    or after visit_date".
    """
    visit = schedule_visit(
        episode=episode,
        clinician=clinician,
        visit_type=visit_type,
        visit_date=visit_date,
        start_minute=start_minute,
        end_minute=end_minute,
    )
    # Make sure the clock has reached visit_date before completion.
    advance_clock_to(visit["visit_date"])
    return complete_visit(visit=visit, clinician=clinician)


# ===========================================================================
# Tier 4: Mileage capture (FieldClinician ownership-gated).
# ===========================================================================
def record_mileage(
    *,
    visit: Dict[str, Any],
    clinician: Dict[str, Any],
    miles_driven: float,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /visits/{visitId}/mileage — FieldClinician.

    The FieldClinician role is entity-backed: PRD §2.1 binds X-User-ID
    to the acting Clinician.id. The headers default uses
    make_field_clinician_headers(clinician["id"])."""
    headers = headers or make_field_clinician_headers(clinician["id"])
    resp = api_client.create_mileage(
        visit["id"],
        create_mileage_payload(miles_driven=miles_driven),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 5: Episode close / expire-sweep.
# ===========================================================================
def close_episode(
    *,
    episode: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /episodes/{episodeId}/close — BillingSpecialist.

    PRD §3.4 requires current_date >= episode.end_date and zero
    SCHEDULED visits. The caller is responsible for advancing the clock
    before invoking this fixture."""
    headers = headers or TEST_USERS["billing_specialist_headers"]
    resp = api_client.close_episode(episode["id"], headers)
    return get_success_data(resp)


def advance_clock_past_end_date(episode: Dict[str, Any],
                                *,
                                extra_days: int = 1) -> Dict[str, Any]:
    """Advance the server clock to episode.end_date + extra_days."""
    target = date_offset(episode["end_date"], days=extra_days)
    return advance_clock_to(target)


def advance_clock_past_expire_grace(episode: Dict[str, Any],
                                    *,
                                    extra_days: int = 1
                                    ) -> Dict[str, Any]:
    """Advance the clock to end_date + grace + extra_days. PRD §3.4:
    "current_date > end_date + 7" triggers expire-sweep eligibility."""
    target = date_offset(
        episode["end_date"],
        days=EPISODE_EXPIRE_GRACE_DAYS + extra_days,
    )
    return advance_clock_to(target)


# ===========================================================================
# Re-fetch helpers.
# ===========================================================================
def re_get_patient(patient_id: str,
                   *,
                   headers: Optional[Dict[str, str]] = None
                   ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["intake_coordinator_headers"]
    return get_success_data(api_client.get_patient(patient_id, headers))


def re_get_clinician(clinician_id: str,
                     *,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(
        api_client.get_clinician(clinician_id, headers),
    )


def re_get_oasis(patient_id: str, oasis_id: str,
                 *,
                 headers: Optional[Dict[str, str]] = None
                 ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["intake_coordinator_headers"]
    return get_success_data(
        api_client.get_oasis(patient_id, oasis_id, headers),
    )


def re_get_episode(episode_id: str,
                   *,
                   headers: Optional[Dict[str, str]] = None
                   ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["intake_coordinator_headers"]
    return get_success_data(api_client.get_episode(episode_id, headers))


def re_get_visit(visit_id: str,
                 *,
                 headers: Optional[Dict[str, str]] = None
                 ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["intake_coordinator_headers"]
    return get_success_data(api_client.get_visit(visit_id, headers))


def re_get_claim(episode_id: str,
                 *,
                 headers: Optional[Dict[str, str]] = None
                 ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["billing_specialist_headers"]
    return get_success_data(api_client.get_claim(episode_id, headers))


# ===========================================================================
# Composite scenario fixtures driven by the difficulty-design recipes.
# ===========================================================================

def setup_three_clinicians_for_distinct_visits(
    *,
    license_expiration_date: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create one SN, one PT, and one OT Clinician, each with a long
    license. Returns (sn, pt, ot)."""
    sn = create_clinician(
        discipline="SN",
        license_expiration_date=license_expiration_date,
    )
    pt = create_clinician(
        discipline="PT",
        license_expiration_date=license_expiration_date,
    )
    ot = create_clinician(
        discipline="OT",
        license_expiration_date=license_expiration_date,
    )
    return sn, pt, ot


def setup_episode_with_three_completed_visits(
    *,
    clinical_grouping: str = "NEURO",
    functional_impairment_level: str = "MEDIUM",
    admission_source: str = "COMMUNITY",
    home_zip: Optional[str] = None,
    start_date: Optional[str] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    List[Dict[str, Any]], List[Dict[str, Any]],
]:
    """Anchor clock; open an Episode (EARLY/NEURO/MEDIUM/COMMUNITY by
    default); schedule + complete THREE visits (SN, PT, OT on three
    different dates inside the window).

    This is the LUPA-path setup (3 < 5 = LUPA_THRESHOLD) used by
    difficulty-design instances:
      - dual_variant_calc/pdgm_payment_provisional_vs_final_lupa_divergence
      - combinatorial_formula/lupa_per_visit_round_then_sum

    Returns (patient, oasis, episode, clinicians[sn,pt,ot], visits).
    """
    anchor_date = start_date or TEST_DEFAULTS["CLOCK_ANCHOR_DATE"]
    anchor_clock(anchor_date)
    sn, pt, ot = setup_three_clinicians_for_distinct_visits()

    patient, oasis, episode = setup_open_episode(
        clinical_grouping=clinical_grouping,
        functional_impairment_level=functional_impairment_level,
        admission_source=admission_source,
        assessment_date=anchor_date,
        home_zip=home_zip,
    )

    # Schedule three visits on the first three days of the episode.
    v_sn = schedule_visit(
        episode=episode, clinician=sn, visit_type="SN",
        visit_date=date_offset(episode["start_date"], days=4),
        start_minute=480, end_minute=540,
    )
    v_pt = schedule_visit(
        episode=episode, clinician=pt, visit_type="PT",
        visit_date=date_offset(episode["start_date"], days=5),
        start_minute=480, end_minute=540,
    )
    v_ot = schedule_visit(
        episode=episode, clinician=ot, visit_type="OT",
        visit_date=date_offset(episode["start_date"], days=6),
        start_minute=480, end_minute=540,
    )

    # Advance clock past each visit_date and complete each visit using
    # the OWNING clinician's headers (FieldClinician is entity-backed).
    advance_clock_to(v_ot["visit_date"])  # >= all three dates
    completed_visits = [
        complete_visit(visit=v_sn, clinician=sn),
        complete_visit(visit=v_pt, clinician=pt),
        complete_visit(visit=v_ot, clinician=ot),
    ]
    return (
        patient, oasis, episode, [sn, pt, ot], completed_visits,
    )


def setup_episode_with_five_completed_visits(
    *,
    clinical_grouping: str = "NEURO",
    functional_impairment_level: str = "MEDIUM",
    admission_source: str = "COMMUNITY",
    home_zip: Optional[str] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    List[Dict[str, Any]], List[Dict[str, Any]],
]:
    """Open Episode; schedule and complete EXACTLY 5 visits across 5
    distinct dates and 5 distinct clinicians.

    This is the LUPA-boundary setup (count == 5 ≥ LUPA_THRESHOLD, so
    LUPA must NOT trigger) used by difficulty-design:
      - boundary_precision_check/lupa_threshold_strict_less_than_boundary

    Returns (patient, oasis, episode, clinicians (5 of them), visits).
    """
    anchor_date = TEST_DEFAULTS["CLOCK_ANCHOR_DATE"]
    anchor_clock(anchor_date)
    # Use 5 SN clinicians for simplicity.
    clinicians = [
        create_clinician(discipline="SN") for _ in range(5)
    ]
    patient, oasis, episode = setup_open_episode(
        clinical_grouping=clinical_grouping,
        functional_impairment_level=functional_impairment_level,
        admission_source=admission_source,
        assessment_date=anchor_date,
        home_zip=home_zip,
    )
    visits = []
    for i, c in enumerate(clinicians):
        v = schedule_visit(
            episode=episode, clinician=c, visit_type="SN",
            visit_date=date_offset(episode["start_date"], days=4 + i),
            start_minute=480, end_minute=540,
        )
        visits.append(v)
    # Advance clock past the last visit_date.
    advance_clock_to(visits[-1]["visit_date"])
    completed = [
        complete_visit(visit=v, clinician=c)
        for v, c in zip(visits, clinicians)
    ]
    return patient, oasis, episode, clinicians, completed


def setup_episode_with_one_completed_visit(
    *,
    clinical_grouping: str = "NEURO",
    functional_impairment_level: str = "MEDIUM",
    admission_source: str = "COMMUNITY",
    home_zip: Optional[str] = None,
    discipline: str = "SN",
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any],
]:
    """Minimal setup that completes ONE visit on the Episode. Used for
    mileage tests where we need a COMPLETED visit to record mileage
    against. Returns (patient, oasis, episode, clinician, visit)."""
    anchor_date = TEST_DEFAULTS["CLOCK_ANCHOR_DATE"]
    anchor_clock(anchor_date)
    clinician = create_clinician(discipline=discipline)
    patient, oasis, episode = setup_open_episode(
        clinical_grouping=clinical_grouping,
        functional_impairment_level=functional_impairment_level,
        admission_source=admission_source,
        assessment_date=anchor_date,
        home_zip=home_zip,
    )
    visit = schedule_visit(
        episode=episode, clinician=clinician, visit_type=discipline,
        visit_date=date_offset(episode["start_date"], days=4),
        start_minute=480, end_minute=540,
    )
    advance_clock_to(visit["visit_date"])
    completed = complete_visit(visit=visit, clinician=clinician)
    return patient, oasis, episode, clinician, completed


def setup_episode_with_two_completed_sn_visits_for_mileage(
    *,
    home_zip: Optional[str] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    List[Dict[str, Any]], List[Dict[str, Any]],
]:
    """Setup for the mileage round-then-sum vs sum-then-round
    divergence: 2 SN clinicians, 2 completed SN visits on consecutive
    days. Used by difficulty-design:
      - dual_variant_calc/mileage_round_then_sum_vs_sum_then_round_divergence

    Returns (patient, oasis, episode, [sn1, sn2], [v1, v2]).
    """
    anchor_date = TEST_DEFAULTS["CLOCK_ANCHOR_DATE"]
    anchor_clock(anchor_date)
    sn1 = create_clinician(discipline="SN")
    sn2 = create_clinician(discipline="SN")
    patient, oasis, episode = setup_open_episode(
        clinical_grouping="NEURO",
        functional_impairment_level="MEDIUM",
        admission_source="COMMUNITY",
        assessment_date=anchor_date,
        home_zip=home_zip,
    )
    v1 = schedule_visit(
        episode=episode, clinician=sn1, visit_type="SN",
        visit_date=date_offset(episode["start_date"], days=4),
        start_minute=480, end_minute=540,
    )
    v2 = schedule_visit(
        episode=episode, clinician=sn2, visit_type="SN",
        visit_date=date_offset(episode["start_date"], days=5),
        start_minute=480, end_minute=540,
    )
    advance_clock_to(v2["visit_date"])
    c1 = complete_visit(visit=v1, clinician=sn1)
    c2 = complete_visit(visit=v2, clinician=sn2)
    return patient, oasis, episode, [sn1, sn2], [c1, c2]


def close_episode_at_end_date(episode: Dict[str, Any]
                              ) -> Dict[str, Any]:
    """Advance clock past episode.end_date and close. Returns the
    closed Episode response."""
    advance_clock_past_end_date(episode, extra_days=1)
    return close_episode(episode=episode)


def setup_open_episode_for_expire_sweep(
    *,
    clinical_grouping: str = "NEURO",
    functional_impairment_level: str = "MEDIUM",
    admission_source: str = "COMMUNITY",
    home_zip: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Anchor clock; open Episode (EARLY/NEURO/MEDIUM/COMMUNITY by
    default). No visits. Used to drive the expire-sweep cascade.

    Returns (patient, oasis, episode)."""
    anchor_date = TEST_DEFAULTS["CLOCK_ANCHOR_DATE"]
    anchor_clock(anchor_date)
    patient, oasis, episode = setup_open_episode(
        clinical_grouping=clinical_grouping,
        functional_impairment_level=functional_impairment_level,
        admission_source=admission_source,
        assessment_date=anchor_date,
        home_zip=home_zip,
    )
    return patient, oasis, episode


def setup_open_episode_with_one_scheduled_visit_for_expire_sweep(
    *,
    home_zip: Optional[str] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any],
]:
    """Open Episode + one SCHEDULED visit that is never completed.
    Used by difficulty-design:
      - transitive_cascade/sweep_expire_to_visit_cancel_to_claim_finalize_chain

    Returns (patient, oasis, episode, clinician, scheduled_visit).
    """
    anchor_date = TEST_DEFAULTS["CLOCK_ANCHOR_DATE"]
    anchor_clock(anchor_date)
    clinician = create_clinician(discipline="SN")
    patient, oasis, episode = setup_open_episode(
        clinical_grouping="NEURO",
        functional_impairment_level="MEDIUM",
        admission_source="COMMUNITY",
        assessment_date=anchor_date,
        home_zip=home_zip,
    )
    # Schedule a visit somewhere inside the episode window but DO NOT
    # complete it.
    visit = schedule_visit(
        episode=episode, clinician=clinician, visit_type="SN",
        visit_date=date_offset(episode["start_date"], days=30),
        start_minute=480, end_minute=540,
    )
    return patient, oasis, episode, clinician, visit


# ===========================================================================
# Closed-episode tooling — for state_vs_safety priority-pair test.
# ===========================================================================
def setup_closed_episode(
    *,
    home_zip: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Open and immediately close an Episode (no visits). Returns
    (patient, oasis, closed_episode)."""
    patient, oasis, episode = setup_open_episode_for_expire_sweep(
        home_zip=home_zip,
    )
    closed = close_episode_at_end_date(episode)
    return patient, oasis, closed


# ===========================================================================
# Setup helpers exclusively for the HHA-hours difficulty instances.
# ===========================================================================
def setup_episode_with_hha_cap(
    *,
    hha_companion_hours_ordered: float,
    home_zip: Optional[str] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Open an Episode with a specified hha_companion_hours_ordered
    cap and a single HHA clinician. Returns (patient, oasis, episode,
    hha_clinician)."""
    anchor_date = TEST_DEFAULTS["CLOCK_ANCHOR_DATE"]
    anchor_clock(anchor_date)
    hha = create_clinician(discipline="HHA")
    patient, oasis, episode = setup_open_episode(
        clinical_grouping="NEURO",
        functional_impairment_level="MEDIUM",
        admission_source="COMMUNITY",
        assessment_date=anchor_date,
        hha_companion_hours_ordered=hha_companion_hours_ordered,
        home_zip=home_zip,
    )
    return patient, oasis, episode, hha


__all__ = [
    # Clock
    "advance_clock_to",
    "get_clock",
    "anchor_clock",
    "run_expire_sweep",
    "advance_clock_past_end_date",
    "advance_clock_past_expire_grace",
    # Reference data
    "create_patient",
    "patch_patient",
    "create_clinician",
    "patch_clinician",
    "suspend_clinician",
    # OASIS + Episode
    "create_oasis",
    "lock_oasis",
    "create_and_lock_oasis",
    "open_episode",
    "setup_open_episode",
    # Visit / Mileage
    "schedule_visit",
    "complete_visit",
    "cancel_visit",
    "schedule_and_complete_visit",
    "record_mileage",
    # Episode close
    "close_episode",
    "close_episode_at_end_date",
    # Re-fetch helpers
    "re_get_patient",
    "re_get_clinician",
    "re_get_oasis",
    "re_get_episode",
    "re_get_visit",
    "re_get_claim",
    # Difficulty-design composites
    "setup_three_clinicians_for_distinct_visits",
    "setup_episode_with_three_completed_visits",
    "setup_episode_with_five_completed_visits",
    "setup_episode_with_one_completed_visit",
    "setup_episode_with_two_completed_sn_visits_for_mileage",
    "setup_open_episode_for_expire_sweep",
    "setup_open_episode_with_one_scheduled_visit_for_expire_sweep",
    "setup_closed_episode",
    "setup_episode_with_hha_cap",
]
