"""Composite setup helpers.

Every test starts against an empty database, so all state must be built from
scratch through the API. These helpers are layered:

* tier 1 — single-row creators (``create_center``, ``create_chair`` ...)
* tier 2 — the standing estate (``setup_suite``)
* tier 3 — a booked visit (``setup_booked_visit``)
* tier 4 — a visit advanced along the schedule dimension
  (``setup_confirmed_visit``, ``setup_checked_in_visit``, ``setup_infusing_visit``,
  ``setup_observing_visit``, ``setup_completed_visit``)
* tier 5 — inventory and history side-chains (``setup_prepared_dose``,
  ``inject_history``, ``run_sweep``)

Setup calls use the lenient ``get_success_data`` validator so a broken setup step
reports the failing call rather than a confusing downstream assertion.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    DEFAULT_APPROVED_UNITS,
    DEFAULT_PAYER_NAME,
    FIXTURE_CLOCK,
)
from .factories import (
    make_adverse_event_payload,
    make_appointment_payload,
    make_approval_decision_payload,
    make_authorization_payload,
    make_biosimilar_payload,
    make_center_payload,
    make_chair_payload,
    make_clock_payload,
    make_drug_lot_payload,
    make_drug_payload,
    make_floored_drug_payload,
    make_history_payload,
    make_lab_result_payload,
    make_nurse_payload,
    make_patient_payload,
    make_preparation_payload,
    make_reminder_payload,
    make_sweep_payload,
    make_template_payload,
    make_treatment_plan_payload,
    make_ungated_drug_payload,
)
from .test_users import (
    AUTH_SPECIALIST,
    MEDICAL_DIRECTOR,
    PHARMACIST,
    SCHEDULER,
    make_nurse_headers,
    make_patient_headers,
)
from .types import DoseTier


def previous_day(service_date: str) -> str:
    """The calendar day before ``service_date``, as a bare ISO date."""
    return (date.fromisoformat(service_date) - timedelta(days=1)).isoformat()


# ---------------------------------------------------------------------------
# Tier 1 — single-row creators
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, current_utc: str, headers: Dict[str, str] = None) -> dict:
    """Move the logical clock and return the ``current_utc`` / ``previous_utc`` pair."""
    return get_success_data(
        api.set_clock(make_clock_payload(current_utc), headers or SCHEDULER)
    )


def create_center(api: ApiClient, **overrides) -> dict:
    return get_success_data(api.create_center(make_center_payload(**overrides), SCHEDULER))


def create_chair(api: ApiClient, center_id: str, label: str = "A1", **overrides) -> dict:
    return get_success_data(
        api.create_chair(make_chair_payload(center_id, label, **overrides), SCHEDULER)
    )


def create_nurse(api: ApiClient, center_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_nurse(make_nurse_payload(center_id, **overrides), SCHEDULER)
    )


def create_drug(api: ApiClient, **overrides) -> dict:
    """Register the standing lab-gated product."""
    return get_success_data(api.create_drug(make_drug_payload(**overrides), PHARMACIST))


def create_ungated_drug(api: ApiClient, **overrides) -> dict:
    return get_success_data(
        api.create_drug(make_ungated_drug_payload(**overrides), PHARMACIST)
    )


def create_floored_drug(api: ApiClient, **overrides) -> dict:
    return get_success_data(
        api.create_drug(make_floored_drug_payload(**overrides), PHARMACIST)
    )


def create_biosimilar(api: ApiClient, reference_drug_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_drug(make_biosimilar_payload(reference_drug_id, **overrides), PHARMACIST)
    )


def create_lot(
    api: ApiClient,
    drug_id: str,
    lot_number: str = "LOT-0001",
    units_received: int = 10,
    expires_on: str = "2026-12-01T00:00:00Z",
    **overrides,
) -> dict:
    return get_success_data(
        api.create_drug_lot(
            make_drug_lot_payload(
                drug_id, lot_number, units_received, expires_on, **overrides
            ),
            PHARMACIST,
        )
    )


def create_patient(
    api: ApiClient, mrn: str = "MRN-0001", full_name: str = "Pat One", **overrides
) -> dict:
    return get_success_data(
        api.create_patient(make_patient_payload(mrn, full_name, **overrides), SCHEDULER)
    )


def create_plan(api: ApiClient, patient_id: str, drug_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_treatment_plan(
            make_treatment_plan_payload(patient_id, drug_id, **overrides), SCHEDULER
        )
    )


def create_template(
    api: ApiClient, center_id: str, drug_id: str, dose_tier: str = DoseTier.MID, **overrides
) -> dict:
    return get_success_data(
        api.create_template(
            make_template_payload(center_id, drug_id, dose_tier, **overrides), SCHEDULER
        )
    )


def book_appointment(
    api: ApiClient,
    center_id: str,
    patient_id: str,
    treatment_plan_id: str,
    template_id: str,
    **overrides,
) -> dict:
    return get_success_data(
        api.create_appointment(
            make_appointment_payload(
                center_id, patient_id, treatment_plan_id, template_id, **overrides
            ),
            SCHEDULER,
        )
    )


def file_lab_result(
    api: ApiClient,
    patient_id: str,
    collected_at: str = "2026-08-05T06:00:00Z",
    anc_value: float = 2.0,
    platelet_value: float = 200,
    headers: Dict[str, str] = None,
    **overrides,
) -> dict:
    """File a laboratory draw; supplying both values files a RESULTED draw."""
    return get_success_data(
        api.create_lab_result(
            make_lab_result_payload(
                patient_id, collected_at, anc_value, platelet_value, **overrides
            ),
            headers or PHARMACIST,
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — the standing estate
# ---------------------------------------------------------------------------
@dataclass
class Suite:
    """The rows a booking needs, keyed for readable access inside tests."""

    center: dict
    chairs: Dict[str, dict] = field(default_factory=dict)
    nurses: List[dict] = field(default_factory=list)
    drug: Optional[dict] = None
    template: Optional[dict] = None
    patient: Optional[dict] = None
    plan: Optional[dict] = None

    # -- convenience accessors ------------------------------------------
    @property
    def center_id(self) -> str:
        return self.center["id"]

    @property
    def nurse(self) -> dict:
        return self.nurses[0]

    @property
    def nurse_id(self) -> str:
        return self.nurses[0]["id"]

    @property
    def nurse_headers(self) -> Dict[str, str]:
        return make_nurse_headers(self.nurses[0]["id"])

    @property
    def patient_headers(self) -> Dict[str, str]:
        return make_patient_headers(self.patient["id"])

    @property
    def patient_id(self) -> str:
        return self.patient["id"]

    @property
    def plan_id(self) -> str:
        return self.plan["id"]

    @property
    def template_id(self) -> str:
        return self.template["id"]

    @property
    def drug_id(self) -> str:
        return self.drug["id"]

    def chair(self, label: str) -> dict:
        return self.chairs[label]

    def chair_id(self, label: str) -> str:
        return self.chairs[label]["id"]

    def headers_for_nurse(self, index: int = 0) -> Dict[str, str]:
        return make_nurse_headers(self.nurses[index]["id"])


def setup_suite(
    api: ApiClient,
    clock: Optional[str] = FIXTURE_CLOCK,
    chair_labels: tuple = ("A1",),
    nurse_specs: Optional[List[dict]] = None,
    center_overrides: Optional[dict] = None,
    drug_overrides: Optional[dict] = None,
    drug_kind: str = "gate",
    dose_tier: str = DoseTier.MID,
    patient_overrides: Optional[dict] = None,
    plan_overrides: Optional[dict] = None,
    with_patient: bool = True,
    with_plan: bool = True,
    with_template: bool = True,
) -> Suite:
    """Stand up a centre, its chairs and roster, a product, a template, a patient
    and an ACTIVE regimen — the preamble nearly every scenario needs.

    ``drug_kind`` selects among the three standing products: ``"gate"`` (the
    lab-gated 120/90/30 product), ``"ungated"`` (short and ungated) and
    ``"floored"`` (administration floor above the escalated base).
    """
    if clock is not None:
        set_clock(api, clock)

    center = create_center(api, **(center_overrides or {}))
    suite = Suite(center=center)

    for label in chair_labels:
        suite.chairs[label] = create_chair(api, center["id"], label)

    for spec in nurse_specs if nurse_specs is not None else [{}]:
        suite.nurses.append(create_nurse(api, center["id"], **spec))

    creator = {
        "gate": create_drug,
        "ungated": create_ungated_drug,
        "floored": create_floored_drug,
    }[drug_kind]
    suite.drug = creator(api, **(drug_overrides or {}))

    if with_template:
        suite.template = create_template(api, center["id"], suite.drug["id"], dose_tier)
    if with_patient:
        suite.patient = create_patient(api, **(patient_overrides or {}))
    if with_plan and suite.patient is not None:
        suite.plan = create_plan(
            api, suite.patient["id"], suite.drug["id"], **(plan_overrides or {})
        )
    return suite


def add_patient_with_plan(
    api: ApiClient,
    suite: Suite,
    mrn: str,
    full_name: str = "Pat Two",
    patient_overrides: Optional[dict] = None,
    plan_overrides: Optional[dict] = None,
) -> tuple:
    """Register a further patient on the suite's product and return (patient, plan)."""
    patient = create_patient(api, mrn, full_name, **(patient_overrides or {}))
    plan = create_plan(api, patient["id"], suite.drug["id"], **(plan_overrides or {}))
    return patient, plan


# ---------------------------------------------------------------------------
# Tier 3 — a booked visit
# ---------------------------------------------------------------------------
def setup_booked_visit(
    api: ApiClient,
    clock: Optional[str] = FIXTURE_CLOCK,
    service_date: str = "2026-08-10",
    requested_start_minute: int = 540,
    chair_labels: tuple = ("A1",),
    appointment_overrides: Optional[dict] = None,
    booking_clock: Optional[str] = None,
    **suite_kwargs,
) -> tuple:
    """Stand up a suite and book one visit on it. Returns (suite, appointment).

    ``booking_clock`` lets the estate be built and the visit booked at an earlier
    instant than ``clock``, which is what a ``ROUTINE`` booking needs whenever the
    scenario wants the clock to already sit on the service day; the clock is moved
    on to ``clock`` once the booking is in.
    """
    book_at = booking_clock if booking_clock is not None else clock
    suite = setup_suite(api, clock=book_at, chair_labels=chair_labels, **suite_kwargs)
    appointment = book_appointment(
        api,
        suite.center_id,
        suite.patient_id,
        suite.plan_id,
        suite.template_id,
        service_date=service_date,
        requested_start_minute=requested_start_minute,
        **(appointment_overrides or {}),
    )
    if clock is not None and book_at != clock:
        set_clock(api, clock)
    return suite, appointment


# ---------------------------------------------------------------------------
# Authorization side-chain
# ---------------------------------------------------------------------------
def file_authorization(
    api: ApiClient,
    appointment_id: str,
    payer_name: str = DEFAULT_PAYER_NAME,
    headers: Dict[str, str] = None,
) -> dict:
    return get_success_data(
        api.create_authorization_request(
            appointment_id, make_authorization_payload(payer_name), headers or AUTH_SPECIALIST
        )
    )


def submit_authorization(api: ApiClient, auth_id: str) -> dict:
    return get_success_data(api.submit_authorization(auth_id, AUTH_SPECIALIST))


def approve_authorization(
    api: ApiClient, auth_id: str, approved_units: int = DEFAULT_APPROVED_UNITS
) -> dict:
    return get_success_data(
        api.decide_authorization(
            auth_id, make_approval_decision_payload(approved_units), AUTH_SPECIALIST
        )
    )


def setup_approved_authorization(
    api: ApiClient,
    appointment_id: str,
    payer_name: str = DEFAULT_PAYER_NAME,
    approved_units: int = DEFAULT_APPROVED_UNITS,
) -> dict:
    """File, submit and approve payer coverage for one visit in one call."""
    auth = file_authorization(api, appointment_id, payer_name)
    submit_authorization(api, auth["id"])
    return approve_authorization(api, auth["id"], approved_units)


# ---------------------------------------------------------------------------
# Tier 4 — advancing the schedule dimension
# ---------------------------------------------------------------------------
def confirm_visit(api: ApiClient, appointment_id: str) -> dict:
    return get_success_data(api.confirm_appointment(appointment_id, SCHEDULER))


def check_in_visit(
    api: ApiClient, appointment_id: str, headers: Dict[str, str] = None
) -> dict:
    return get_success_data(api.check_in_appointment(appointment_id, headers or SCHEDULER))


def start_infusion(api: ApiClient, appointment_id: str, nurse_id: str) -> dict:
    return get_success_data(
        api.start_infusion(appointment_id, make_nurse_headers(nurse_id))
    )


def complete_infusion(api: ApiClient, appointment_id: str, nurse_id: str) -> dict:
    return get_success_data(
        api.complete_infusion(appointment_id, make_nurse_headers(nurse_id))
    )


def discharge_visit(api: ApiClient, appointment_id: str, nurse_id: str) -> dict:
    return get_success_data(
        api.discharge_appointment(appointment_id, make_nurse_headers(nurse_id))
    )


def setup_confirmed_visit(
    api: ApiClient,
    clock: Optional[str] = FIXTURE_CLOCK,
    service_date: str = "2026-08-10",
    requested_start_minute: int = 540,
    with_lab: bool = True,
    lab_collected_at: Optional[str] = None,
    booking_clock: Optional[str] = None,
    **kwargs,
) -> tuple:
    """A visit sitting in CONFIRMED under live payer coverage.

    Returns (suite, appointment). When the product carries a lab gate a passing
    draw is filed first unless ``with_lab`` is turned off. When ``clock`` already
    sits on the service day the booking is placed the previous morning, since a
    ``ROUTINE`` visit may not be booked on the clock's own date.
    """
    if booking_clock is None and clock is not None and clock[:10] == service_date:
        booking_clock = f"{previous_day(service_date)}T07:00:00Z"
    suite, appointment = setup_booked_visit(
        api,
        clock=clock,
        service_date=service_date,
        requested_start_minute=requested_start_minute,
        booking_clock=booking_clock,
        **kwargs,
    )
    if with_lab and suite.drug.get("requires_lab_gate"):
        file_lab_result(
            api,
            suite.patient_id,
            collected_at=lab_collected_at or (clock or FIXTURE_CLOCK),
        )
    setup_approved_authorization(api, appointment["id"])
    confirmed = confirm_visit(api, appointment["id"])
    return suite, confirmed


def setup_checked_in_visit(
    api: ApiClient,
    clock: Optional[str] = "2026-08-10T08:00:00Z",
    service_date: str = "2026-08-10",
    requested_start_minute: int = 540,
    **kwargs,
) -> tuple:
    """A visit sitting in CHECKED_IN on its own service day."""
    suite, appointment = setup_confirmed_visit(
        api,
        clock=clock,
        service_date=service_date,
        requested_start_minute=requested_start_minute,
        **kwargs,
    )
    checked_in = check_in_visit(api, appointment["id"])
    return suite, checked_in


def setup_infusing_visit(
    api: ApiClient,
    clock: Optional[str] = "2026-08-10T08:00:00Z",
    service_date: str = "2026-08-10",
    requested_start_minute: int = 540,
    units_requested: int = 2,
    lot_units: int = 10,
    lot_expires_on: str = "2026-12-01T00:00:00Z",
    **kwargs,
) -> tuple:
    """A visit sitting in INFUSING with a compounded dose standing by.

    Returns (suite, appointment, preparation).
    """
    suite, appointment = setup_confirmed_visit(
        api,
        clock=clock,
        service_date=service_date,
        requested_start_minute=requested_start_minute,
        **kwargs,
    )
    create_lot(
        api, suite.drug_id, units_received=lot_units, expires_on=lot_expires_on
    )
    check_in_visit(api, appointment["id"])
    prep = request_dose(api, appointment["id"], units_requested)
    prep = compound_dose(api, prep["id"])
    infusing = start_infusion(api, appointment["id"], suite.nurse_id)
    return suite, infusing, prep


def setup_observing_visit(api: ApiClient, **kwargs) -> tuple:
    """A visit sitting in OBSERVING with its dose already mixed."""
    suite, appointment, prep = setup_infusing_visit(api, **kwargs)
    observing = complete_infusion(api, appointment["id"], suite.nurse_id)
    return suite, observing, prep


def setup_completed_visit(api: ApiClient, **kwargs) -> tuple:
    """A visit discharged all the way to COMPLETED."""
    suite, appointment, prep = setup_observing_visit(api, **kwargs)
    completed = discharge_visit(api, appointment["id"], suite.nurse_id)
    return suite, completed, prep


# ---------------------------------------------------------------------------
# Tier 5 — inventory, reactions, history, sweep
# ---------------------------------------------------------------------------
def request_dose(
    api: ApiClient, appointment_id: str, units_requested: int = 2
) -> dict:
    return get_success_data(
        api.create_drug_preparation(
            appointment_id, make_preparation_payload(units_requested), PHARMACIST
        )
    )


def compound_dose(api: ApiClient, preparation_id: str) -> dict:
    return get_success_data(api.prepare_dose(preparation_id, PHARMACIST))


def setup_prepared_dose(
    api: ApiClient,
    appointment_id: str,
    drug_id: str,
    units_requested: int = 2,
    lot_units: int = 10,
    lot_number: str = "LOT-0001",
    lot_expires_on: str = "2026-12-01T00:00:00Z",
    create_backing_lot: bool = True,
) -> dict:
    """Book a lot if needed, request the dose and mix it. Returns the PREPARED dose."""
    if create_backing_lot:
        create_lot(
            api,
            drug_id,
            lot_number=lot_number,
            units_received=lot_units,
            expires_on=lot_expires_on,
        )
    prep = request_dose(api, appointment_id, units_requested)
    return compound_dose(api, prep["id"])


def record_reaction(
    api: ApiClient,
    appointment_id: str,
    nurse_id: str,
    grade: int = 2,
    action: str = "HOLD",
    **overrides,
) -> dict:
    return get_success_data(
        api.create_adverse_event(
            appointment_id,
            make_adverse_event_payload(grade, action, **overrides),
            make_nurse_headers(nurse_id),
        )
    )


def record_reminder(
    api: ApiClient, appointment_id: str, channel: str = "SMS", **overrides
) -> dict:
    return get_success_data(
        api.create_reminder(
            appointment_id, make_reminder_payload(channel, **overrides), SCHEDULER
        )
    )


def inject_history(
    api: ApiClient,
    center_id: str,
    patient_id: str,
    treatment_plan_id: str,
    template_id: str,
    service_date: str,
    schedule_status: str,
    chair_minutes: int = 240,
    **overrides,
) -> dict:
    """Write a visit already in a terminal schedule status straight into the record."""
    return get_success_data(
        api.inject_appointment_history(
            make_history_payload(
                center_id,
                patient_id,
                treatment_plan_id,
                template_id,
                service_date,
                schedule_status,
                chair_minutes,
                **overrides,
            ),
            SCHEDULER,
        )
    )


def run_sweep(api: ApiClient, center_id: str, service_date: str) -> dict:
    return get_success_data(
        api.run_daily_sweep(center_id, make_sweep_payload(service_date), SCHEDULER)
    )


def open_review(api: ApiClient, event_id: str) -> dict:
    return get_success_data(
        api.start_adverse_event_review(event_id, MEDICAL_DIRECTOR)
    )


def close_review(
    api: ApiClient, event_id: str, review_outcome: str = "RESUME_SAME_DRUG"
) -> dict:
    return get_success_data(
        api.close_adverse_event(
            event_id, {"review_outcome": review_outcome}, MEDICAL_DIRECTOR
        )
    )


# ---------------------------------------------------------------------------
# Read-back helpers
# ---------------------------------------------------------------------------
def read_appointment(api: ApiClient, appointment_id: str) -> dict:
    return get_success_data(api.get_appointment(appointment_id, SCHEDULER))


def read_chair(api: ApiClient, chair_id: str) -> dict:
    return get_success_data(api.get_chair(chair_id, SCHEDULER))


def read_nurse(api: ApiClient, nurse_id: str) -> dict:
    return get_success_data(api.get_nurse(nurse_id, SCHEDULER))


def read_patient(api: ApiClient, patient_id: str) -> dict:
    return get_success_data(api.get_patient(patient_id, SCHEDULER))


def read_plan(api: ApiClient, plan_id: str) -> dict:
    return get_success_data(api.get_treatment_plan(plan_id, SCHEDULER))


def read_template(api: ApiClient, template_id: str) -> dict:
    return get_success_data(api.get_template(template_id, SCHEDULER))


def read_center(api: ApiClient, center_id: str) -> dict:
    return get_success_data(api.get_center(center_id, SCHEDULER))


def read_lot(api: ApiClient, lot_id: str) -> dict:
    return get_success_data(api.get_drug_lot(lot_id, PHARMACIST))


def read_preparation(api: ApiClient, preparation_id: str) -> dict:
    return get_success_data(api.get_drug_preparation(preparation_id, PHARMACIST))


def read_lab_result(api: ApiClient, lab_id: str) -> dict:
    return get_success_data(api.get_lab_result(lab_id, PHARMACIST))


def read_authorization(api: ApiClient, auth_id: str) -> dict:
    return get_success_data(api.get_authorization_request(auth_id, AUTH_SPECIALIST))


def read_adverse_event(api: ApiClient, event_id: str) -> dict:
    return get_success_data(api.get_adverse_event(event_id, MEDICAL_DIRECTOR))


def read_reminder(api: ApiClient, reminder_id: str) -> dict:
    return get_success_data(api.get_reminder_contact(reminder_id, SCHEDULER))


def read_utilization(
    api: ApiClient, center_id: str, service_date: str, variant: Optional[str] = None
) -> dict:
    params: Dict[str, Any] = {"service_date": service_date}
    if variant is not None:
        params["variant"] = variant
    return get_success_data(api.get_utilization(center_id, SCHEDULER, params))


def read_chair_billing(api: ApiClient, center_id: str, service_date: str) -> dict:
    return get_success_data(
        api.get_chair_billing_summary(center_id, SCHEDULER, {"service_date": service_date})
    )


def read_no_show_risk(
    api: ApiClient, patient_id: str, variant: Optional[str] = None
) -> dict:
    params = {"variant": variant} if variant is not None else None
    return get_success_data(api.get_no_show_risk(patient_id, SCHEDULER, params))
