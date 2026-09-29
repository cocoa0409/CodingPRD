"""Composite scenario builders for the pulmonary function laboratory API.

Every scenario in this suite begins from an empty database, so each precondition
is built here by calling the same published endpoints a real laboratory would
use: set the logical clock, register the roster, publish a reference equation
set, program a device through its daily quality checks, register a patient,
raise and submit an order, then schedule and run a session.

The builders return the identifiers and headers a test needs and nothing else;
assertions belong in the tests, not here.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import MORNING_CLOCK
from .test_users import (
    COMPLIANCE_AUDITOR,
    LAB_MANAGER,
    make_interpreting_physician_headers,
    make_ordering_physician_headers,
    make_technologist_headers,
)

Json = Dict[str, Any]


# --------------------------------------------------------------------- context
@dataclass
class Roster:
    """The staff a scenario has registered, with their identity headers."""

    tech1_id: str
    tech1: Dict[str, str]
    doc1_id: str
    doc1: Dict[str, str]
    bcs_id: Optional[str] = None
    tech2_id: Optional[str] = None
    tech2: Optional[Dict[str, str]] = None
    interpreter_ids: List[str] = field(default_factory=list)
    interpreters: List[Dict[str, str]] = field(default_factory=list)

    @property
    def rad1_id(self) -> str:
        return self.interpreter_ids[0]

    @property
    def rad1(self) -> Dict[str, str]:
        return self.interpreters[0]

    @property
    def rad2_id(self) -> str:
        return self.interpreter_ids[1]

    @property
    def rad2(self) -> Dict[str, str]:
        return self.interpreters[1]


@dataclass
class Lab:
    """A laboratory that is ready to schedule work."""

    roster: Roster
    equation_id: str
    device_id: str
    patient_id: str
    device_ids: List[str] = field(default_factory=list)

    # Convenience passthroughs so a test body stays short.
    @property
    def tech1(self) -> Dict[str, str]:
        return self.roster.tech1

    @property
    def tech1_id(self) -> str:
        return self.roster.tech1_id

    @property
    def doc1(self) -> Dict[str, str]:
        return self.roster.doc1

    @property
    def doc1_id(self) -> str:
        return self.roster.doc1_id

    @property
    def bcs_id(self) -> str:
        assert self.roster.bcs_id is not None, "no biologic control subject registered"
        return self.roster.bcs_id


# ------------------------------------------------------------- primitive steps
def _created(response, expected_status: int = 201) -> Json:
    return get_success_data(response, expected_status=expected_status)


def _ok(response) -> Json:
    return get_success_data(response, expected_status=200)


def set_clock(api: ApiClient, to_iso8601: str) -> Json:
    """Move the server's logical clock, the only time source the API reads."""
    return _ok(api.set_logical_clock(to_iso8601, LAB_MANAGER))


def register_staff(api: ApiClient, payload: Json) -> Json:
    return _created(api.create_staff(payload, LAB_MANAGER))


def register_technologist(api: ApiClient, **kwargs: Any) -> Json:
    return register_staff(api, f.technologist_payload(**kwargs))


def register_biologic_control_subject(api: ApiClient, **kwargs: Any) -> Json:
    return register_staff(api, f.biologic_control_subject_payload(**kwargs))


def register_ordering_physician(api: ApiClient, **kwargs: Any) -> Json:
    return register_staff(api, f.ordering_physician_payload(**kwargs))


def register_interpreting_physician(api: ApiClient, **kwargs: Any) -> Json:
    return register_staff(api, f.interpreting_physician_payload(**kwargs))


def publish_reference_equation(api: ApiClient, **kwargs: Any) -> Json:
    return _created(api.create_reference_equation(f.reference_equation_payload(**kwargs), LAB_MANAGER))


def register_device(
    api: ApiClient, device_code: str = "SPIRO-1", modality: str = "SPIROMETRY"
) -> Json:
    return _created(api.create_device(f.device_payload(device_code, modality), LAB_MANAGER))


def register_patient(api: ApiClient, **kwargs: Any) -> Json:
    return _created(api.create_patient(f.patient_payload(**kwargs), LAB_MANAGER))


def receive_rescue_lot(api: ApiClient, **kwargs: Any) -> Json:
    return _created(api.create_rescue_lot(f.rescue_lot_payload(**kwargs), LAB_MANAGER))


def append_quality_event(
    api: ApiClient, device_id: str, payload: Json, tech_headers: Dict[str, str]
) -> Json:
    return _created(api.create_quality_event(device_id, payload, tech_headers))


def run_daily_quality_program(
    api: ApiClient,
    device_id: str,
    tech_headers: Dict[str, str],
    bcs_id: str,
    filter_serial: str = "F-1001",
    leak_check: bool = False,
) -> Dict[str, Json]:
    """Calibrate, control, refit the filter and disinfect a device for the day.

    ``leak_check`` adds the closed-circuit leak check a DLCO or plethysmography
    device also needs before it may be booked.
    """
    events: Dict[str, Json] = {}
    events["calibration"] = append_quality_event(
        api, device_id, f.calibration_event_payload(), tech_headers
    )
    if leak_check:
        events["leak_check"] = append_quality_event(
            api, device_id, f.leak_check_event_payload(), tech_headers
        )
    events["biologic_control"] = append_quality_event(
        api, device_id, f.biologic_control_event_payload(bcs_id), tech_headers
    )
    events["filter_replacement"] = append_quality_event(
        api, device_id, f.filter_replacement_event_payload(filter_serial), tech_headers
    )
    events["disinfection"] = append_quality_event(
        api, device_id, f.disinfection_event_payload(), tech_headers
    )
    return events


def draft_order(api: ApiClient, patient_id: str, doc_headers: Dict[str, str], **kwargs: Any) -> Json:
    return _created(api.create_test_order(f.test_order_payload(patient_id, **kwargs), doc_headers))


def submit_order(api: ApiClient, order_id: str, doc_headers: Dict[str, str]) -> Json:
    return _ok(api.submit_test_order(order_id, doc_headers, {}))


def draft_and_submit_order(
    api: ApiClient, patient_id: str, doc_headers: Dict[str, str], **kwargs: Any
) -> Json:
    """Raise an order and submit it, answering with the submitted row."""
    order = draft_order(api, patient_id, doc_headers, **kwargs)
    return submit_order(api, order["id"], doc_headers)


def schedule_session(
    api: ApiClient,
    order_id: str,
    device_id: str,
    tech_headers: Dict[str, str],
    scheduled_start_at: str,
    scheduled_end_at: str,
) -> Json:
    return _created(
        api.create_test_session(
            f.test_session_payload(order_id, device_id, scheduled_start_at, scheduled_end_at),
            tech_headers,
        )
    )


def append_maneuver(
    api: ApiClient, session_id: str, payload: Json, tech_headers: Dict[str, str]
) -> Json:
    return _created(api.create_maneuver(session_id, payload, tech_headers))


def append_maneuver_series(
    api: ApiClient,
    session_id: str,
    tech_headers: Dict[str, str],
    payloads: Optional[Sequence[Json]] = None,
) -> List[Json]:
    """Record a run of efforts, defaulting to the standard grade-A trio."""
    series = list(payloads) if payloads is not None else f.STANDARD_MANEUVER_SERIES
    return [append_maneuver(api, session_id, payload, tech_headers) for payload in series]


def finalize_quality(
    api: ApiClient, session_id: str, tech_headers: Dict[str, str], comment: Optional[str] = None
) -> Json:
    payload = f.finalize_quality_payload() if comment is None else f.finalize_quality_payload(comment)
    return _ok(api.finalize_session_quality(session_id, payload, tech_headers))


def append_custody_event(
    api: ApiClient, session_id: str, payload: Json, headers: Dict[str, str]
) -> Json:
    return _created(api.create_custody_event(session_id, payload, headers))


def verify_identity(
    api: ApiClient,
    session_id: str,
    tech_headers: Dict[str, str],
    id_document_type: str = "PHOTO_ID",
) -> Json:
    return append_custody_event(api, session_id, f.id_verified_payload(id_document_type), tech_headers)


def apply_seal(
    api: ApiClient, session_id: str, tech_headers: Dict[str, str], seal_serial: str = "SEAL-9001"
) -> Json:
    return append_custody_event(api, session_id, f.seal_applied_payload(seal_serial), tech_headers)


def witness_session(api: ApiClient, session_id: str, note: Optional[str] = None) -> Json:
    """The compliance auditor's witness attestation on a custody chain."""
    return append_custody_event(api, session_id, f.witness_signed_payload(note), COMPLIANCE_AUDITOR)


def arm_challenge_run(
    api: ApiClient,
    session_id: str,
    rescue_lot_id: str,
    tech_headers: Dict[str, str],
    agent: str = "METHACHOLINE",
) -> Json:
    return _created(
        api.create_challenge_run(session_id, f.challenge_run_payload(rescue_lot_id, agent), tech_headers)
    )


def record_challenge_step(
    api: ApiClient,
    run_id: str,
    dose_units: float,
    post_step_fev1_l: float,
    tech_headers: Dict[str, str],
) -> Json:
    # PRD 4: "recording a challenge step answers 200 with the updated
    # `ChallengeRun` rather than 201, because a step is an accumulator update on
    # the run rather than a resource of its own".
    return _ok(
        api.create_challenge_step(
            run_id, f.challenge_step_payload(dose_units, post_step_fev1_l), tech_headers
        )
    )


def assign_report(
    api: ApiClient, session_id: str, expected_session_version: int
) -> Json:
    return _created(
        api.create_interpretation_report(
            session_id, f.report_assignment_payload(expected_session_version), LAB_MANAGER
        )
    )


def sign_report(
    api: ApiClient, report_id: str, interpreter_headers: Dict[str, str], clinical_comment: Optional[str] = None
) -> Json:
    payload = (
        f.sign_report_payload() if clinical_comment is None else f.sign_report_payload(clinical_comment)
    )
    return _ok(api.sign_interpretation_report(report_id, payload, interpreter_headers))


# ------------------------------------------------------------ composite builds
def build_roster(
    api: ApiClient,
    with_biologic_control: bool = True,
    second_technologist: bool = False,
    interpreters: int = 0,
    interpreter_max_concurrent_reports: int = 1,
) -> Roster:
    """Register the staff members a testing day needs."""
    tech1 = register_technologist(api)
    doc1 = register_ordering_physician(api)
    roster = Roster(
        tech1_id=tech1["id"],
        tech1=make_technologist_headers(tech1["id"]),
        doc1_id=doc1["id"],
        doc1=make_ordering_physician_headers(doc1["id"]),
    )
    if with_biologic_control:
        roster.bcs_id = register_biologic_control_subject(api)["id"]
    if second_technologist:
        tech2 = register_technologist(api, employee_code="T-002", full_name="Bo Reyes")
        roster.tech2_id = tech2["id"]
        roster.tech2 = make_technologist_headers(tech2["id"])
    for index in range(interpreters):
        code, name = (("R-001", "Rhea Lund"), ("R-002", "Ravi Menon"))[index]
        row = register_interpreting_physician(
            api,
            employee_code=code,
            full_name=name,
            max_concurrent_reports=interpreter_max_concurrent_reports,
        )
        roster.interpreter_ids.append(row["id"])
        roster.interpreters.append(make_interpreting_physician_headers(row["id"]))
    return roster


def build_lab(
    api: ApiClient,
    clock: str = MORNING_CLOCK,
    device_codes: Sequence[str] = ("SPIRO-1",),
    modality: str = "SPIROMETRY",
    leak_check: bool = False,
    interpreters: int = 0,
    interpreter_max_concurrent_reports: int = 1,
    second_technologist: bool = False,
) -> Lab:
    """A laboratory with its clock set, its roster hired and its devices programmed."""
    set_clock(api, clock)
    roster = build_roster(
        api,
        second_technologist=second_technologist,
        interpreters=interpreters,
        interpreter_max_concurrent_reports=interpreter_max_concurrent_reports,
    )
    equation = publish_reference_equation(api)
    device_ids: List[str] = []
    for index, code in enumerate(device_codes, start=1):
        device_ids.append(register_device(api, code, modality)["id"])
        run_daily_quality_program(
            api,
            device_ids[-1],
            roster.tech1,
            roster.bcs_id or "",
            filter_serial=f"F-100{index}",
            leak_check=leak_check,
        )
    patient = register_patient(api)
    return Lab(
        roster=roster,
        equation_id=equation["id"],
        device_id=device_ids[0],
        patient_id=patient["id"],
        device_ids=device_ids,
    )


def build_ready_order(api: ApiClient, lab: Lab, **kwargs: Any) -> Json:
    """An order that has cleared indication validation and may be scheduled."""
    return draft_and_submit_order(api, lab.patient_id, lab.doc1, **kwargs)


def build_scheduled_session(
    api: ApiClient,
    lab: Lab,
    scheduled_start_at: str = "2026-08-03T09:00:00Z",
    scheduled_end_at: str = "2026-08-03T09:30:00Z",
    device_id: Optional[str] = None,
    order: Optional[Json] = None,
    **order_kwargs: Any,
) -> Json:
    order = order if order is not None else build_ready_order(api, lab, **order_kwargs)
    return schedule_session(
        api,
        order["id"],
        device_id or lab.device_id,
        lab.tech1,
        scheduled_start_at,
        scheduled_end_at,
    )


def build_session_with_maneuvers(
    api: ApiClient,
    lab: Lab,
    payloads: Optional[Sequence[Json]] = None,
    **session_kwargs: Any,
) -> Json:
    """A session that is IN_PROGRESS with a run of recorded efforts."""
    session = build_scheduled_session(api, lab, **session_kwargs)
    append_maneuver_series(api, session["id"], lab.tech1, payloads)
    return session


def build_accepted_session(
    api: ApiClient,
    lab: Lab,
    payloads: Optional[Sequence[Json]] = None,
    **session_kwargs: Any,
) -> Json:
    """A session whose quality has been finalized; answers with the closed row."""
    session = build_session_with_maneuvers(api, lab, payloads, **session_kwargs)
    return finalize_quality(api, session["id"], lab.tech1)


def build_assigned_report(
    api: ApiClient,
    lab: Lab,
    payloads: Optional[Sequence[Json]] = None,
    **session_kwargs: Any,
) -> Json:
    """An accepted session handed to an interpreting physician."""
    session = build_accepted_session(api, lab, payloads, **session_kwargs)
    return assign_report(api, session["id"], session["version"])
