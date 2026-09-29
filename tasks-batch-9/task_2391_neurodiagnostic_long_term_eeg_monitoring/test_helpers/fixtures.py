"""
Composite setup builders.

Every test starts against an empty database, so any precondition deeper than a
single create has to be walked through the public endpoints. These builders do
that walking. They are plain functions taking the client, so a pytest fixture
and a test body can call the same builder, and they return the parsed record so
a caller can read ids and versions straight out of the result.

The builders are layered:

* single-record creates and the state progressions that reach a usable state;
* the entity hierarchy composite that reaches an admitted stay with coverage;
* lifecycle shortcuts that drive a study or a report to a later state;
* accumulation builders that drive a figure to a threshold (storage lock,
  coverage constraint, capture target met);
* finalization builders that reach a terminal record (final report, delivered
  package, decided conference case).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    ALERT_SOURCE_ALGORITHM,
    CLASSIFICATION_CLINICAL,
    DISPOSITION_ROUTINE,
    EVENT_CLINICAL_SEIZURE,
    OUTCOME_APPROVE,
    RISK_MODERATE,
    SETTING_INPATIENT,
    SPECIALTY_EPILEPTOLOGY,
    SPECIALTY_NEUROSURGERY,
    T_ADMIT,
    VOTE_CANDIDATE,
)
from .test_users import (
    COORDINATOR,
    EPILEPTOLOGIST,
    EPILEPTOLOGIST_ID,
    EPILEPTOLOGIST_ID_2,
    NURSE_ID,
    PAYER_REVIEWER,
    TECHNOLOGIST,
    TECHNOLOGIST_ID,
    as_epileptologist,
    as_nurse,
)

SHIFT_END_DEFAULT = "2026-08-10T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1 — the clock and single-record progressions
# ---------------------------------------------------------------------------


def set_clock(api, to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical clock, which every role may drive."""
    return get_success_data(api.set_clock(to_iso8601, COORDINATOR))


def create_unit(
    api,
    *,
    name: str = "EMU A",
    bed_count: int = 2,
    storage_quota_gb: float = 500.00,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_unit(
            f.unit_payload(
                name=name, bed_count=bed_count, storage_quota_gb=storage_quota_gb
            ),
            COORDINATOR,
        )
    )


def create_bed(api, unit_id: str, *, label: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(api.create_bed(f.bed_payload(unit_id, label), COORDINATOR))


def create_patient(
    api,
    *,
    mrn: Optional[str] = None,
    display_name: str = "Pat Monitored",
    risk_tier: str = RISK_MODERATE,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_patient(
            f.patient_payload(mrn=mrn, display_name=display_name, risk_tier=risk_tier),
            COORDINATOR,
        )
    )


def draft_authorization(
    api,
    patient_id: str,
    *,
    requested_setting: str = SETTING_INPATIENT,
    requested_days: int = 5,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_authorization(
            f.authorization_payload(
                patient_id,
                requested_setting=requested_setting,
                requested_days=requested_days,
            ),
            COORDINATOR,
        )
    )


def submitted_authorization(api, patient_id: str, **kwargs: Any) -> Dict[str, Any]:
    authorization = draft_authorization(api, patient_id, **kwargs)
    return get_success_data(
        api.submit_authorization(authorization["id"], COORDINATOR)
    )


def approved_authorization(
    api,
    patient_id: str,
    *,
    requested_setting: str = SETTING_INPATIENT,
    requested_days: int = 5,
    authorized_days: Optional[int] = None,
    authorized_setting: Optional[str] = None,
    payer_note: str = "approved",
) -> Dict[str, Any]:
    """Draft, submit and approve funding in one step."""
    authorization = submitted_authorization(
        api,
        patient_id,
        requested_setting=requested_setting,
        requested_days=requested_days,
    )
    return get_success_data(
        api.record_payer_decision(
            authorization["id"],
            f.payer_decision_payload(
                outcome=OUTCOME_APPROVE,
                authorized_days=(
                    authorized_days if authorized_days is not None else requested_days
                ),
                authorized_setting=authorized_setting or requested_setting,
                payer_note=payer_note,
            ),
            PAYER_REVIEWER,
        )
    )


def create_shift(
    api,
    unit_id: str,
    *,
    technologist_user_id: str = TECHNOLOGIST_ID,
    starts_at: str = T_ADMIT,
    ends_at: str = SHIFT_END_DEFAULT,
    max_concurrent_studies: int = 2,
    activate: bool = True,
) -> Dict[str, Any]:
    shift = get_success_data(
        api.create_shift(
            f.shift_payload(
                unit_id,
                technologist_user_id=technologist_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                max_concurrent_studies=max_concurrent_studies,
            ),
            COORDINATOR,
        )
    )
    if activate:
        shift = get_success_data(api.activate_shift(shift["id"], COORDINATOR))
    return shift


def schedule_admission(
    api,
    *,
    patient_id: str,
    authorization_id: str,
    unit_id: str,
    setting: str = SETTING_INPATIENT,
    scheduled_admit_at: str = T_ADMIT,
    target_event_count: int = 4,
    planned_days: int = 5,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_admission(
            f.admission_payload(
                patient_id,
                authorization_id,
                unit_id,
                setting=setting,
                scheduled_admit_at=scheduled_admit_at,
                target_event_count=target_event_count,
                planned_days=planned_days,
            ),
            COORDINATOR,
        )
    )


def admit(
    api,
    admission_id: str,
    *,
    bed_id: Optional[str] = None,
    at: Optional[str] = None,
) -> Dict[str, Any]:
    if at is not None:
        set_clock(api, at)
    return get_success_data(
        api.admit(admission_id, f.admit_payload(bed_id), COORDINATOR)
    )


def create_study(
    api,
    admission_id: str,
    *,
    channel_count: int = 32,
    modality: str = SETTING_INPATIENT,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_study(
            f.study_payload(admission_id, channel_count=channel_count, modality=modality),
            TECHNOLOGIST,
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — the entity hierarchy composite
# ---------------------------------------------------------------------------


@dataclass
class Baseline:
    """An admitted inpatient stay with coverage rostered and a study created."""

    unit: Dict[str, Any]
    patient: Dict[str, Any]
    authorization: Dict[str, Any]
    admission: Dict[str, Any]
    bed: Optional[Dict[str, Any]] = None
    beds: List[Dict[str, Any]] = field(default_factory=list)
    shift: Optional[Dict[str, Any]] = None
    study: Optional[Dict[str, Any]] = None

    @property
    def unit_id(self) -> str:
        return self.unit["id"]

    @property
    def patient_id(self) -> str:
        return self.patient["id"]

    @property
    def authorization_id(self) -> str:
        return self.authorization["id"]

    @property
    def admission_id(self) -> str:
        return self.admission["id"]

    @property
    def bed_id(self) -> Optional[str]:
        return self.bed["id"] if self.bed else None

    @property
    def shift_id(self) -> Optional[str]:
        return self.shift["id"] if self.shift else None

    @property
    def study_id(self) -> Optional[str]:
        return self.study["id"] if self.study else None


def build_admitted_stay(
    api,
    *,
    unit_name: str = "EMU A",
    bed_count: int = 2,
    storage_quota_gb: float = 500.00,
    bed_labels: Optional[List[str]] = None,
    mrn: Optional[str] = None,
    display_name: str = "Pat Monitored",
    risk_tier: str = RISK_MODERATE,
    setting: str = SETTING_INPATIENT,
    requested_days: int = 5,
    authorized_days: Optional[int] = None,
    planned_days: int = 5,
    target_event_count: int = 4,
    scheduled_admit_at: str = T_ADMIT,
    admitted_at: Optional[str] = T_ADMIT,
    with_shift: bool = True,
    shift_starts_at: str = T_ADMIT,
    shift_ends_at: str = SHIFT_END_DEFAULT,
    max_concurrent_studies: int = 2,
    technologist_user_id: str = TECHNOLOGIST_ID,
    activate_shift: bool = True,
    with_study: bool = True,
    channel_count: int = 32,
) -> Baseline:
    """Walk unit, bed, patient, funding, schedule, admit, coverage and study."""
    unit = create_unit(
        api, name=unit_name, bed_count=bed_count, storage_quota_gb=storage_quota_gb
    )
    labels = bed_labels if bed_labels is not None else ["EMU-1"]
    beds = [create_bed(api, unit["id"], label=label) for label in labels]
    patient = create_patient(
        api, mrn=mrn, display_name=display_name, risk_tier=risk_tier
    )
    authorization = approved_authorization(
        api,
        patient["id"],
        requested_setting=setting,
        requested_days=requested_days,
        authorized_days=authorized_days,
    )
    admission = schedule_admission(
        api,
        patient_id=patient["id"],
        authorization_id=authorization["id"],
        unit_id=unit["id"],
        setting=setting,
        scheduled_admit_at=scheduled_admit_at,
        target_event_count=target_event_count,
        planned_days=planned_days,
    )
    bed = beds[0] if beds else None
    if admitted_at is not None:
        admission = admit(
            api,
            admission["id"],
            bed_id=bed["id"] if (bed and setting == SETTING_INPATIENT) else None,
            at=admitted_at,
        )
    shift = None
    if with_shift:
        shift = create_shift(
            api,
            unit["id"],
            technologist_user_id=technologist_user_id,
            starts_at=shift_starts_at,
            ends_at=shift_ends_at,
            max_concurrent_studies=max_concurrent_studies,
            activate=activate_shift,
        )
    study = None
    if with_study:
        study = create_study(
            api,
            admission["id"],
            channel_count=channel_count,
            modality=setting,
        )
    return Baseline(
        unit=unit,
        patient=patient,
        authorization=authorization,
        admission=admission,
        bed=bed,
        beds=beds,
        shift=shift,
        study=study,
    )


def build_acquiring_stay(api, *, started_at: Optional[str] = None, **kwargs: Any) -> Baseline:
    """The admitted-stay composite with its study already acquiring."""
    baseline = build_admitted_stay(api, **kwargs)
    assert baseline.study is not None and baseline.shift is not None
    baseline.study = start_study(
        api, baseline.study_id, baseline.shift_id, at=started_at
    )
    return baseline


# ---------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# ---------------------------------------------------------------------------


def start_study(
    api, study_id: str, shift_id: str, *, at: Optional[str] = None
) -> Dict[str, Any]:
    if at is not None:
        set_clock(api, at)
    return get_success_data(
        api.start_study(study_id, f.start_payload(shift_id), TECHNOLOGIST)
    )


def pause_study(
    api,
    study_id: str,
    *,
    at: Optional[str] = None,
    reason: str = "ROUTINE_SEGMENT_CLOSE",
    maintenance_kind: Optional[str] = None,
    impedance_kohm: Optional[float] = None,
) -> Dict[str, Any]:
    if at is not None:
        set_clock(api, at)
    return get_success_data(
        api.pause_study(
            study_id,
            f.pause_payload(
                reason=reason,
                maintenance_kind=maintenance_kind,
                impedance_kohm=impedance_kohm,
            ),
            TECHNOLOGIST,
        )
    )


def resume_study(api, study_id: str, *, at: Optional[str] = None) -> Dict[str, Any]:
    if at is not None:
        set_clock(api, at)
    return get_success_data(api.resume_study(study_id, TECHNOLOGIST))


def complete_study(api, study_id: str, *, at: Optional[str] = None) -> Dict[str, Any]:
    if at is not None:
        set_clock(api, at)
    return get_success_data(api.complete_study(study_id, TECHNOLOGIST))


def discharge(
    api,
    admission_id: str,
    *,
    disposition: str = DISPOSITION_ROUTINE,
    at: Optional[str] = None,
) -> Dict[str, Any]:
    if at is not None:
        set_clock(api, at)
    return get_success_data(
        api.discharge(admission_id, f.discharge_payload(disposition), COORDINATOR)
    )


def create_taper_plan(
    api,
    admission_id: str,
    *,
    total_steps: int = 3,
    steps_advanced: int = 0,
) -> Dict[str, Any]:
    plan = get_success_data(
        api.create_taper_plan(
            f.taper_plan_payload(admission_id, total_steps=total_steps), EPILEPTOLOGIST
        )
    )
    for _ in range(steps_advanced):
        plan = get_success_data(api.advance_taper_step(plan["id"], EPILEPTOLOGIST))
    return plan


def raise_alert(
    api,
    study_id: str,
    *,
    source: str = ALERT_SOURCE_ALGORITHM,
    at: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    if at is not None:
        set_clock(api, at)
    return get_success_data(
        api.raise_alert(study_id, f.alert_payload(source), headers or TECHNOLOGIST)
    )


def record_intervention(
    api,
    alert_id: str,
    *,
    interventions: Optional[List[str]] = None,
    injury_observed: bool = False,
    rescue_med_given: bool = False,
    nurse_user_id: str = NURSE_ID,
    at: Optional[str] = None,
) -> Dict[str, Any]:
    if at is not None:
        set_clock(api, at)
    return get_success_data(
        api.record_intervention(
            alert_id,
            f.intervention_payload(
                interventions=interventions,
                injury_observed=injury_observed,
                rescue_med_given=rescue_med_given,
            ),
            as_nurse(nurse_user_id),
        )
    )


def adjudicate_alert(
    api,
    alert_id: str,
    classification: str = CLASSIFICATION_CLINICAL,
    *,
    at: Optional[str] = None,
    user_id: str = EPILEPTOLOGIST_ID,
) -> Dict[str, Any]:
    if at is not None:
        set_clock(api, at)
    return get_success_data(
        api.adjudicate_alert(
            alert_id, f.adjudicate_alert_payload(classification), as_epileptologist(user_id)
        )
    )


def close_alert(api, alert_id: str) -> Dict[str, Any]:
    return get_success_data(api.close_alert(alert_id, EPILEPTOLOGIST))


def create_marking(
    api,
    study_id: str,
    onset_at: str,
    *,
    event_class: str = EVENT_CLINICAL_SEIZURE,
    duration_seconds: Optional[int] = None,
    alert_id: Optional[str] = None,
    adjudicate: bool = False,
) -> Dict[str, Any]:
    marking = get_success_data(
        api.create_marking(
            f.marking_payload(
                study_id,
                onset_at,
                event_class=event_class,
                duration_seconds=duration_seconds,
                alert_id=alert_id,
            ),
            EPILEPTOLOGIST,
        )
    )
    if adjudicate:
        marking = get_success_data(
            api.adjudicate_marking(marking["id"], EPILEPTOLOGIST)
        )
    return marking


def report_of_study(api, study_id: str) -> Dict[str, Any]:
    """The single review report a completed study synthesizes, found by listing."""
    body = get_success_data(api.list_study_reports(study_id, EPILEPTOLOGIST))
    reports = body if isinstance(body, list) else body["data"]
    assert reports, f"study {study_id} has no review report to read"
    return reports[0]


def issue_prelim(
    api,
    report_id: str,
    *,
    localization: str = "LEFT_TEMPORAL",
    author_user_id: str = EPILEPTOLOGIST_ID,
    at: Optional[str] = None,
) -> Dict[str, Any]:
    if at is not None:
        set_clock(api, at)
    return get_success_data(
        api.issue_prelim(
            report_id,
            f.issue_prelim_payload(localization),
            as_epileptologist(author_user_id),
        )
    )


def issue_final(
    api,
    report_id: str,
    *,
    localization: str = "LEFT_TEMPORAL",
    author_user_id: str = EPILEPTOLOGIST_ID_2,
    at: Optional[str] = None,
) -> Dict[str, Any]:
    if at is not None:
        set_clock(api, at)
    return get_success_data(
        api.issue_final(
            report_id,
            f.issue_final_payload(localization),
            as_epileptologist(author_user_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# ---------------------------------------------------------------------------


def acquire_segment(
    api,
    study_id: str,
    *,
    from_iso: str,
    to_iso: str,
    shift_id: Optional[str] = None,
    reason: str = "ROUTINE_SEGMENT_CLOSE",
    maintenance_kind: Optional[str] = None,
    impedance_kohm: Optional[float] = None,
) -> Dict[str, Any]:
    """Record one closed acquisition segment spanning the two instants."""
    if shift_id is not None:
        start_study(api, study_id, shift_id, at=from_iso)
    else:
        resume_study(api, study_id, at=from_iso)
    return pause_study(
        api,
        study_id,
        at=to_iso,
        reason=reason,
        maintenance_kind=maintenance_kind,
        impedance_kohm=impedance_kohm,
    )


def acquire_and_complete(
    api,
    study_id: str,
    shift_id: str,
    *,
    from_iso: str,
    to_iso: str,
) -> Dict[str, Any]:
    """One open segment closed by completion, which also creates the report."""
    start_study(api, study_id, shift_id, at=from_iso)
    return complete_study(api, study_id, at=to_iso)


def adjudicated_alert_with_marking(
    api,
    study_id: str,
    *,
    detected_at: str,
    onset_at: str,
    event_class: str = EVENT_CLINICAL_SEIZURE,
    duration_seconds: Optional[int] = None,
    classification: str = CLASSIFICATION_CLINICAL,
    source: str = ALERT_SOURCE_ALGORITHM,
    nurse_user_id: str = NURSE_ID,
    with_intervention: bool = True,
    close: bool = False,
) -> Dict[str, Any]:
    """An alert, its bedside response, its marking and its adjudication."""
    alert = raise_alert(api, study_id, source=source, at=detected_at)
    if with_intervention:
        record_intervention(api, alert["id"], nurse_user_id=nurse_user_id)
    marking = create_marking(
        api,
        study_id,
        onset_at,
        event_class=event_class,
        duration_seconds=duration_seconds,
        alert_id=alert["id"],
    )
    alert = adjudicate_alert(api, alert["id"], classification)
    if close:
        alert = close_alert(api, alert["id"])
    return {"alert": alert, "marking": marking}


# ---------------------------------------------------------------------------
# Tier 5 — finalization and terminal states
# ---------------------------------------------------------------------------


def finalized_report(
    api,
    study_id: str,
    *,
    prelim_author_user_id: str = EPILEPTOLOGIST_ID,
    final_author_user_id: str = EPILEPTOLOGIST_ID_2,
    localization: str = "LEFT_TEMPORAL",
    prelim_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive the report of a completed study all the way to FINAL_ISSUED."""
    report = report_of_study(api, study_id)
    issue_prelim(
        api,
        report["id"],
        localization=localization,
        author_user_id=prelim_author_user_id,
        at=prelim_at,
    )
    return issue_final(
        api,
        report["id"],
        localization=localization,
        author_user_id=final_author_user_id,
    )


def queue_export(
    api,
    study_id: str,
    *,
    include_video: bool = False,
    supersedes_export_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Queue a package, reading the study's current version first as required."""
    study = get_success_data(api.get_study(study_id, COORDINATOR))
    return get_success_data(
        api.create_export(
            f.export_payload(
                study_id,
                study["version"],
                include_video=include_video,
                supersedes_export_id=supersedes_export_id,
            ),
            COORDINATOR,
        )
    )


def built_export(api, study_id: str, *, include_video: bool = False) -> Dict[str, Any]:
    package = queue_export(api, study_id, include_video=include_video)
    return get_success_data(api.build_export(package["id"], COORDINATOR))


def delivered_export(
    api,
    study_id: str,
    *,
    include_video: bool = False,
    recipient_center: str = "Regional Surgical Center",
) -> Dict[str, Any]:
    package = built_export(api, study_id, include_video=include_video)
    return get_success_data(
        api.deliver_export(
            package["id"], f.deliver_payload(recipient_center), COORDINATOR
        )
    )


def presented_case(
    api,
    *,
    admission_id: str,
    export_id: str,
    presenter_user_id: str = EPILEPTOLOGIST_ID,
) -> Dict[str, Any]:
    case = get_success_data(
        api.create_conference_case(
            f.conference_case_payload(admission_id, export_id), EPILEPTOLOGIST
        )
    )
    return get_success_data(
        api.present_case(case["id"], as_epileptologist(presenter_user_id))
    )


def cast_ballot(
    api,
    case_id: str,
    *,
    voter_user_id: str,
    specialty: str = SPECIALTY_EPILEPTOLOGY,
    vote: str = VOTE_CANDIDATE,
    rationale: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.cast_vote(
            case_id,
            f.vote_payload(specialty=specialty, vote=vote, rationale=rationale),
            as_epileptologist(voter_user_id),
        )
    )


def cast_ballots(api, case_id: str, ballots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cast a sequence of ballots described as {voter_user_id, specialty, vote}."""
    return [cast_ballot(api, case_id, **ballot) for ballot in ballots]


def case_with_quorum(
    api,
    *,
    admission_id: str,
    export_id: str,
    presenter_user_id: str = EPILEPTOLOGIST_ID,
    votes: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """A presented case carrying three counted ballots across two specialties."""
    case = presented_case(
        api,
        admission_id=admission_id,
        export_id=export_id,
        presenter_user_id=presenter_user_id,
    )
    ballots = votes if votes is not None else [
        {
            "voter_user_id": "epi-voter-1",
            "specialty": SPECIALTY_EPILEPTOLOGY,
            "vote": VOTE_CANDIDATE,
        },
        {
            "voter_user_id": "epi-voter-2",
            "specialty": SPECIALTY_NEUROSURGERY,
            "vote": VOTE_CANDIDATE,
        },
        {
            "voter_user_id": "epi-voter-3",
            "specialty": SPECIALTY_NEUROSURGERY,
            "vote": VOTE_CANDIDATE,
        },
    ]
    cast_ballots(api, case["id"], ballots)
    return get_success_data(api.get_conference_case(case["id"], EPILEPTOLOGIST))
