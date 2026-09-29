"""Composite setup helpers, arranged in five tiers.

The harness restarts the server before each test, so every test begins with an
empty database and the logical clock reading its startup instant. These helpers
build the recurring case files the specification's scenarios need, in ascending
order of composition:

1. Clock control — pin the logical clock, run the compliance sweep.
2. Roster and physical plant — clinicians, a unit and its beds.
3. Patients and evaluations — a patient plus a signed evaluation with a chosen
   clinical picture, so the acuity tier and recommendation are known up front.
4. Legal track — a hold in a chosen status, petitions and scheduled hearings.
5. Admission track — admissions searched, placed, restrained, planned and
   discharged.

Every helper reads the created resource back out of the response it just made,
so callers always hold the server's own view (including the ``version`` they
will need for an optimistic-concurrency field).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .constants import shift
from .test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    make_attending_psychiatrist_headers,
    make_charge_nurse_headers,
    make_intake_clinician_headers,
    make_patient_rights_advocate_headers,
)
from .types import (
    BedType,
    GenderCareCategory,
    GenderMixingPolicy,
    HoldType,
    LegalStatus,
    SearchType,
    StaffRole,
)

#: A weekday instant inside the court and business windows, used as the common
#: starting point for scenarios that need deadlines to fall on known dates.
#: Thursday 3 September 2026 at 08:00 UTC.
PINNED_CLOCK = "2026-09-03T08:00:00Z"

#: A Thursday afternoon anchor whose raw seventy-two-hour expiry lands on a
#: Sunday, so the calendar and judicial deadlines visibly diverge (PRD 3.3).
DIVERGENT_ANCHOR = "2026-09-03T14:30:00Z"


# ---------------------------------------------------------------------------
# Tier 1: clock and sweep
# ---------------------------------------------------------------------------


def set_clock(api, to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> str:
    """Move the logical clock and return the ``current_utc`` it reports."""
    response = api.set_clock(
        headers or COMPLIANCE_OFFICER_HEADERS, factories.clock_payload(to_iso8601)
    )
    return get_success_data(response, 200)["current_utc"]


def run_sweep(api, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Run the compliance sweep and return its four counters."""
    response = api.run_sweep(headers or COMPLIANCE_OFFICER_HEADERS)
    return get_success_data(response, 200)


def pin_clock(api, to_iso8601: str = PINNED_CLOCK) -> str:
    """Pin the clock to the common weekday starting point."""
    return set_clock(api, to_iso8601)


# ---------------------------------------------------------------------------
# Tier 2: roster and physical plant
# ---------------------------------------------------------------------------


@dataclass
class Roster:
    """The five staff members most scenarios need, plus their headers."""

    intake: Dict[str, Any]
    psychiatrist: Dict[str, Any]
    second_psychiatrist: Dict[str, Any]
    charge_nurse: Dict[str, Any]
    advocate: Dict[str, Any]

    @property
    def intake_headers(self) -> Dict[str, str]:
        return make_intake_clinician_headers(self.intake["id"])

    @property
    def psychiatrist_headers(self) -> Dict[str, str]:
        return make_attending_psychiatrist_headers(self.psychiatrist["id"])

    @property
    def second_psychiatrist_headers(self) -> Dict[str, str]:
        return make_attending_psychiatrist_headers(self.second_psychiatrist["id"])

    @property
    def charge_nurse_headers(self) -> Dict[str, str]:
        return make_charge_nurse_headers(self.charge_nurse["id"])

    @property
    def advocate_headers(self) -> Dict[str, str]:
        return make_patient_rights_advocate_headers(self.advocate["id"])

    #: The intake clinician doubles as a search witness distinct from the nurse.
    @property
    def witness_id(self) -> str:
        return self.intake["id"]


def create_clinician(
    api,
    full_name: str,
    staff_role: str,
    license_number: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Register one clinician on the roster."""
    response = api.create_clinician(
        headers or COMPLIANCE_OFFICER_HEADERS,
        factories.clinician_payload(
            full_name=full_name,
            staff_role=staff_role,
            license_number=license_number,
        ),
    )
    return get_success_data(response, 201)


def build_roster(api) -> Roster:
    """Register the recurring cast of five clinicians."""
    return Roster(
        intake=create_clinician(
            api, "Iris Nolan", StaffRole.INTAKE_CLINICIAN.value, "LIC-INT-2367-1"
        ),
        psychiatrist=create_clinician(
            api, "Dr Alma Reyes", StaffRole.PSYCHIATRIST.value, "LIC-PSY-2367-1"
        ),
        second_psychiatrist=create_clinician(
            api, "Dr Bo Fenn", StaffRole.PSYCHIATRIST.value, "LIC-PSY-2367-2"
        ),
        charge_nurse=create_clinician(
            api, "Rosa Kim", StaffRole.CHARGE_NURSE.value, "LIC-RN-2367-1"
        ),
        advocate=create_clinician(
            api, "Vera Cho", StaffRole.RIGHTS_ADVOCATE.value, "LIC-ADV-2367-1"
        ),
    )


@dataclass
class Ward:
    """A unit together with the beds created inside it."""

    unit: Dict[str, Any]
    beds: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.unit["id"]

    def bed(self, bed_label: str) -> Dict[str, Any]:
        for bed in self.beds:
            if bed["bed_label"] == bed_label:
                return bed
        raise KeyError(f"no bed labelled {bed_label!r} in this unit")


def create_unit(
    api,
    name: str = "Ward 4 North",
    gender_mixing_policy: str = GenderMixingPolicy.SEPARATE_BY_ROOM.value,
    seclusion_room_count: int = 1,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open one unit."""
    response = api.create_unit(
        headers or COMPLIANCE_OFFICER_HEADERS,
        factories.unit_payload(
            name=name,
            gender_mixing_policy=gender_mixing_policy,
            seclusion_room_count=seclusion_room_count,
        ),
    )
    return get_success_data(response, 201)


def create_bed(
    api,
    unit_id: str,
    room_number: str,
    wing_code: str,
    bed_label: str,
    bed_type: str = BedType.STANDARD.value,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Add one bed to a unit."""
    response = api.create_bed(
        headers or COMPLIANCE_OFFICER_HEADERS,
        factories.bed_payload(
            unit_id=unit_id,
            room_number=room_number,
            wing_code=wing_code,
            bed_label=bed_label,
            bed_type=bed_type,
        ),
    )
    return get_success_data(response, 201)


def build_ward(
    api,
    name: str = "Ward 4 North",
    gender_mixing_policy: str = GenderMixingPolicy.SEPARATE_BY_ROOM.value,
    seclusion_room_count: int = 1,
    bed_specs: Optional[Sequence[Dict[str, Any]]] = None,
) -> Ward:
    """Open a unit and stock it with beds.

    ``bed_specs`` entries take ``room_number``, ``wing_code``, ``bed_label`` and
    an optional ``bed_type``; the default is the three-standard-bed ward the
    placement scenarios use.
    """
    if bed_specs is None:
        bed_specs = (
            {"room_number": "401", "wing_code": "A", "bed_label": "401-A"},
            {"room_number": "402", "wing_code": "A", "bed_label": "402-A"},
            {"room_number": "403", "wing_code": "B", "bed_label": "403-B"},
        )
    unit = create_unit(api, name, gender_mixing_policy, seclusion_room_count)
    ward = Ward(unit=unit)
    for spec in bed_specs:
        ward.beds.append(
            create_bed(
                api,
                unit_id=unit["id"],
                room_number=spec["room_number"],
                wing_code=spec["wing_code"],
                bed_label=spec["bed_label"],
                bed_type=spec.get("bed_type", BedType.STANDARD.value),
            )
        )
    ward.unit = read_unit(api, unit["id"])
    return ward


def set_bed_status(
    api, bed_id: str, status: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Move one bed to a new status, which re-derives the unit's posture."""
    response = api.update_bed_status(
        headers or COMPLIANCE_OFFICER_HEADERS, bed_id, status=status
    )
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Read-back helpers
# ---------------------------------------------------------------------------


def read_unit(api, unit_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Fetch a unit, which is how a caller learns its current version."""
    return get_success_data(
        api.get_unit(headers or COMPLIANCE_OFFICER_HEADERS, unit_id), 200
    )


def unit_version(api, unit_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    """The unit's current version, for the mandatory placement guard."""
    return read_unit(api, unit_id, headers)["version"]


def read_admission(
    api, admission_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.get_admission(headers or COMPLIANCE_OFFICER_HEADERS, admission_id), 200
    )


def admission_version(
    api, admission_id: str, headers: Optional[Dict[str, str]] = None
) -> int:
    """The admission's current version, for the capacity-determination guard."""
    return read_admission(api, admission_id, headers)["version"]


def read_bed(api, bed_id: str, unit_id: str, headers: Optional[Dict[str, str]] = None):
    """Locate a bed through its unit's bed listing."""
    response = api.list_unit_beds(
        headers or COMPLIANCE_OFFICER_HEADERS, unit_id, limit=100
    )
    for bed in get_success_data(response, 200):
        if bed["id"] == bed_id:
            return bed
    raise AssertionError(f"bed {bed_id} not listed under unit {unit_id}")


def read_patient(api, patient_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(
        api.get_patient(headers or COMPLIANCE_OFFICER_HEADERS, patient_id), 200
    )


def read_clinician(api, clinician_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(
        api.get_clinician(headers or COMPLIANCE_OFFICER_HEADERS, clinician_id), 200
    )


def read_hold(api, hold_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(
        api.get_hold(headers or COMPLIANCE_OFFICER_HEADERS, hold_id), 200
    )


def read_petition(api, petition_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(
        api.get_petition(headers or COMPLIANCE_OFFICER_HEADERS, petition_id), 200
    )


def read_hearing(api, hearing_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(
        api.get_hearing(headers or COMPLIANCE_OFFICER_HEADERS, hearing_id), 200
    )


def read_restraint(api, restraint_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(
        api.get_restraint(headers or COMPLIANCE_OFFICER_HEADERS, restraint_id), 200
    )


def read_evaluation(api, evaluation_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(
        api.get_evaluation(headers or COMPLIANCE_OFFICER_HEADERS, evaluation_id), 200
    )


def read_discharge_request(api, request_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(
        api.get_discharge_request(COMPLIANCE_OFFICER_HEADERS if headers is None else headers, request_id),
        200,
    )


def read_capacity_determination(
    api, determination_id: str, headers: Optional[Dict[str, str]] = None
):
    return get_success_data(
        api.get_capacity_determination(
            headers or COMPLIANCE_OFFICER_HEADERS, determination_id
        ),
        200,
    )


def read_medication_consent(api, consent_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(
        api.get_medication_consent(headers or COMPLIANCE_OFFICER_HEADERS, consent_id),
        200,
    )


# ---------------------------------------------------------------------------
# Tier 3: patients and evaluations
# ---------------------------------------------------------------------------


def create_patient(
    api,
    mrn: Optional[str] = None,
    legal_name: str = "Dana Whitlock",
    age_years: int = 34,
    gender_care_category: str = GenderCareCategory.FEMALE.value,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Register one patient."""
    response = api.create_patient(
        headers or COMPLIANCE_OFFICER_HEADERS,
        factories.patient_payload(
            mrn=mrn,
            legal_name=legal_name,
            age_years=age_years,
            gender_care_category=gender_care_category,
        ),
    )
    return get_success_data(response, 201)


def create_evaluation(
    api,
    headers: Dict[str, str],
    patient_id: str,
    danger_to_self: bool = True,
    danger_to_others: bool = False,
    grave_disability: bool = False,
    capacity_present: bool = False,
    clinical_summary: str = "Acute suicidal ideation with a stated plan.",
) -> Dict[str, Any]:
    """Start an evaluation, which lands in DRAFT."""
    response = api.create_evaluation(
        headers,
        factories.evaluation_payload(
            patient_id=patient_id,
            danger_to_self=danger_to_self,
            danger_to_others=danger_to_others,
            grave_disability=grave_disability,
            capacity_present=capacity_present,
            clinical_summary=clinical_summary,
        ),
    )
    return get_success_data(response, 201)


def signed_evaluation(
    api,
    headers: Dict[str, str],
    patient_id: str,
    *,
    danger_to_self: bool = True,
    danger_to_others: bool = False,
    grave_disability: bool = False,
    capacity_present: bool = False,
    clinical_summary: str = "Acute suicidal ideation with a stated plan.",
    signed_at_clock: Optional[str] = None,
) -> Dict[str, Any]:
    """Start and sign an evaluation, optionally pinning the signing instant.

    ``signed_at_clock`` matters because a hold anchors on the evaluation's
    ``signed_at``, not on when the hold row was written.
    """
    evaluation = create_evaluation(
        api,
        headers,
        patient_id,
        danger_to_self=danger_to_self,
        danger_to_others=danger_to_others,
        grave_disability=grave_disability,
        capacity_present=capacity_present,
        clinical_summary=clinical_summary,
    )
    if signed_at_clock is not None:
        set_clock(api, signed_at_clock)
    return get_success_data(api.sign_evaluation(headers, evaluation["id"]), 200)


def involuntary_case(
    api,
    roster: Roster,
    *,
    mrn: Optional[str] = None,
    legal_name: str = "Dana Whitlock",
    age_years: int = 34,
    gender_care_category: str = GenderCareCategory.FEMALE.value,
    danger_to_self: bool = True,
    danger_to_others: bool = False,
    grave_disability: bool = False,
    signed_at_clock: Optional[str] = None,
) -> Dict[str, Any]:
    """A patient plus a signed evaluation recommending an involuntary hold.

    Absent capacity together with at least one danger criterion is what makes the
    recommendation ``INVOLUNTARY_HOLD``.
    """
    patient = create_patient(
        api,
        mrn=mrn,
        legal_name=legal_name,
        age_years=age_years,
        gender_care_category=gender_care_category,
    )
    evaluation = signed_evaluation(
        api,
        roster.intake_headers,
        patient["id"],
        danger_to_self=danger_to_self,
        danger_to_others=danger_to_others,
        grave_disability=grave_disability,
        capacity_present=False,
        signed_at_clock=signed_at_clock,
    )
    return {"patient": patient, "evaluation": evaluation}


def voluntary_case(
    api,
    roster: Roster,
    *,
    mrn: Optional[str] = None,
    legal_name: str = "Perry Vale",
    age_years: int = 41,
    gender_care_category: str = GenderCareCategory.MALE.value,
    danger_to_self: bool = True,
    danger_to_others: bool = False,
    grave_disability: bool = False,
) -> Dict[str, Any]:
    """A patient plus a signed evaluation recommending a voluntary admission."""
    patient = create_patient(
        api,
        mrn=mrn,
        legal_name=legal_name,
        age_years=age_years,
        gender_care_category=gender_care_category,
    )
    evaluation = signed_evaluation(
        api,
        roster.intake_headers,
        patient["id"],
        danger_to_self=danger_to_self,
        danger_to_others=danger_to_others,
        grave_disability=grave_disability,
        capacity_present=True,
    )
    return {"patient": patient, "evaluation": evaluation}


# ---------------------------------------------------------------------------
# Tier 4: the legal track
# ---------------------------------------------------------------------------


def create_hold(
    api,
    headers: Dict[str, str],
    patient_id: str,
    evaluation_id: str,
    hold_type: str = HoldType.EMERGENCY_72H.value,
) -> Dict[str, Any]:
    """File a hold, which lands in PENDING_CERTIFICATION."""
    response = api.create_hold(
        headers,
        factories.hold_payload(
            patient_id=patient_id, evaluation_id=evaluation_id, hold_type=hold_type
        ),
    )
    return get_success_data(response, 201)


def certified_hold(
    api,
    roster: Roster,
    patient_id: str,
    evaluation_id: str,
    *,
    initiator_headers: Optional[Dict[str, str]] = None,
    certifier_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """A hold carried through to ACTIVE by a second clinician.

    The certifier must differ from the initiator, so the intake clinician files
    and the attending psychiatrist certifies.
    """
    hold = create_hold(
        api,
        initiator_headers or roster.intake_headers,
        patient_id,
        evaluation_id,
    )
    return get_success_data(
        api.certify_hold(
            certifier_headers or roster.psychiatrist_headers,
            hold["id"],
            factories.certification_payload(),
        ),
        200,
    )


def active_hold_case(
    api,
    roster: Roster,
    *,
    mrn: Optional[str] = None,
    legal_name: str = "Dana Whitlock",
    age_years: int = 34,
    gender_care_category: str = GenderCareCategory.FEMALE.value,
    danger_to_self: bool = True,
    danger_to_others: bool = False,
    grave_disability: bool = False,
    signed_at_clock: Optional[str] = None,
) -> Dict[str, Any]:
    """A patient with a signed evaluation and an ACTIVE emergency hold."""
    case = involuntary_case(
        api,
        roster,
        mrn=mrn,
        legal_name=legal_name,
        age_years=age_years,
        gender_care_category=gender_care_category,
        danger_to_self=danger_to_self,
        danger_to_others=danger_to_others,
        grave_disability=grave_disability,
        signed_at_clock=signed_at_clock,
    )
    case["hold"] = certified_hold(
        api, roster, case["patient"]["id"], case["evaluation"]["id"]
    )
    return case


def create_petition(
    api,
    headers: Dict[str, str],
    hold_id: str,
    petition_grounds: str = "Continued grave disability without treatment.",
) -> Dict[str, Any]:
    """File a petition for a fourteen-day extension."""
    response = api.create_petition(
        headers,
        factories.petition_payload(hold_id=hold_id, petition_grounds=petition_grounds),
    )
    return get_success_data(response, 201)


def scheduled_hearing(
    api,
    headers: Dict[str, str],
    petition_id: str,
    advocate_clinician_id: str,
    scheduled_start_at: str,
    duration_minutes: int = 60,
) -> Dict[str, Any]:
    """Book a hearing slot on an advocate's docket."""
    response = api.create_hearing(
        headers,
        factories.hearing_payload(
            petition_id=petition_id,
            advocate_clinician_id=advocate_clinician_id,
            scheduled_start_at=scheduled_start_at,
            duration_minutes=duration_minutes,
        ),
    )
    return get_success_data(response, 201)


def petition_with_hearing(
    api,
    roster: Roster,
    hold_id: str,
    scheduled_start_at: str,
    duration_minutes: int = 60,
) -> Dict[str, Any]:
    """A filed petition already carried to HEARING_SCHEDULED."""
    petition = create_petition(api, roster.psychiatrist_headers, hold_id)
    hearing = scheduled_hearing(
        api,
        roster.advocate_headers,
        petition["id"],
        roster.advocate["id"],
        scheduled_start_at,
        duration_minutes,
    )
    return {"petition": read_petition(api, petition["id"]), "hearing": hearing}


def record_outcome(
    api, outcome: str, hearing_id: str, findings_note: str = "Findings entered on the record."
) -> Dict[str, Any]:
    """Record a hearing outcome, which only the compliance office may do."""
    response = api.record_hearing_outcome(
        COMPLIANCE_OFFICER_HEADERS,
        hearing_id,
        factories.hearing_outcome_payload(outcome, findings_note),
    )
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Tier 5: the admission track
# ---------------------------------------------------------------------------


def create_admission(
    api,
    roster: Roster,
    patient_id: str,
    evaluation_id: str,
    unit_id: str,
    requested_legal_status: str = LegalStatus.INVOLUNTARY.value,
) -> Dict[str, Any]:
    """Open an admission, which only an intake clinician may do."""
    response = api.create_admission(
        roster.intake_headers,
        factories.admission_payload(
            patient_id=patient_id,
            evaluation_id=evaluation_id,
            unit_id=unit_id,
            requested_legal_status=requested_legal_status,
        ),
    )
    return get_success_data(response, 201)


def complete_safety_search(
    api,
    roster: Roster,
    admission_id: str,
    *,
    search_type: str = SearchType.WANDED.value,
    witness_clinician_id: Optional[str] = None,
    items_secured: int = 2,
    contraband_found: bool = False,
    performer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Record a completed safety search, the precondition for placement."""
    response = api.record_safety_search(
        performer_headers or roster.charge_nurse_headers,
        admission_id,
        factories.safety_search_payload(
            search_witness_clinician_id=witness_clinician_id or roster.witness_id,
            search_type=search_type,
            outcome="COMPLETED",
            search_items_secured_count=items_secured,
            contraband_found=contraband_found,
        ),
    )
    return get_success_data(response, 200)


def searched_admission(
    api,
    roster: Roster,
    patient_id: str,
    evaluation_id: str,
    unit_id: str,
    requested_legal_status: str = LegalStatus.INVOLUNTARY.value,
) -> Dict[str, Any]:
    """An admission whose safety search is COMPLETED but which is not yet placed."""
    admission = create_admission(
        api, roster, patient_id, evaluation_id, unit_id, requested_legal_status
    )
    return complete_safety_search(api, roster, admission["id"])


def place_admission(
    api,
    roster: Roster,
    admission_id: str,
    unit_id: str,
    *,
    bed_id: Optional[str] = None,
    posture_override_reason: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Place an admission, re-reading the unit for its current version first."""
    response = api.place_admission(
        headers or roster.charge_nurse_headers,
        admission_id,
        factories.placement_payload(
            unit_id=unit_id,
            expected_unit_version=unit_version(api, unit_id),
            bed_id=bed_id,
            posture_override_reason=posture_override_reason,
        ),
    )
    return get_success_data(response, 200)


def placed_admission(
    api,
    roster: Roster,
    ward: Ward,
    case: Dict[str, Any],
    *,
    requested_legal_status: str = LegalStatus.INVOLUNTARY.value,
    bed_id: Optional[str] = None,
) -> Dict[str, Any]:
    """An admission carried all the way to PLACED in an occupied bed."""
    admission = searched_admission(
        api,
        roster,
        case["patient"]["id"],
        case["evaluation"]["id"],
        ward.id,
        requested_legal_status,
    )
    return place_admission(api, roster, admission["id"], ward.id, bed_id=bed_id)


def voluntary_placed_admission(
    api,
    roster: Roster,
    ward: Ward,
    *,
    mrn: Optional[str] = None,
    legal_name: str = "Perry Vale",
    age_years: int = 41,
    gender_care_category: str = GenderCareCategory.MALE.value,
    bed_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A voluntary patient placed in a bed, with no hold anywhere in play."""
    case = voluntary_case(
        api,
        roster,
        mrn=mrn,
        legal_name=legal_name,
        age_years=age_years,
        gender_care_category=gender_care_category,
    )
    case["admission"] = placed_admission(
        api,
        roster,
        ward,
        case,
        requested_legal_status=LegalStatus.VOLUNTARY.value,
        bed_id=bed_id,
    )
    return case


def involuntary_placed_admission(
    api,
    roster: Roster,
    ward: Ward,
    *,
    mrn: Optional[str] = None,
    legal_name: str = "Dana Whitlock",
    age_years: int = 34,
    gender_care_category: str = GenderCareCategory.FEMALE.value,
    danger_to_self: bool = True,
    danger_to_others: bool = False,
    grave_disability: bool = False,
    bed_id: Optional[str] = None,
    signed_at_clock: Optional[str] = None,
) -> Dict[str, Any]:
    """A patient on an ACTIVE hold, admitted involuntarily and placed."""
    case = active_hold_case(
        api,
        roster,
        mrn=mrn,
        legal_name=legal_name,
        age_years=age_years,
        gender_care_category=gender_care_category,
        danger_to_self=danger_to_self,
        danger_to_others=danger_to_others,
        grave_disability=grave_disability,
        signed_at_clock=signed_at_clock,
    )
    case["admission"] = placed_admission(
        api,
        roster,
        ward,
        case,
        requested_legal_status=LegalStatus.INVOLUNTARY.value,
        bed_id=bed_id,
    )
    return case


# ---------------------------------------------------------------------------
# Tier 5: restraints
# ---------------------------------------------------------------------------


def order_restraint(
    api,
    roster: Roster,
    admission_id: str,
    intervention_type: str,
    ordered_duration_minutes: int,
    clinical_justification: str = "Imminent risk of serious self-injury.",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Order a restraint episode, which lands in ORDERED."""
    response = api.create_restraint(
        headers or roster.psychiatrist_headers,
        factories.restraint_payload(
            admission_id=admission_id,
            intervention_type=intervention_type,
            ordered_duration_minutes=ordered_duration_minutes,
            clinical_justification=clinical_justification,
        ),
    )
    return get_success_data(response, 201)


def active_restraint(
    api,
    roster: Roster,
    admission_id: str,
    intervention_type: str,
    ordered_duration_minutes: int,
    *,
    orderer_headers: Optional[Dict[str, str]] = None,
    reviewer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """An episode carried to ACTIVE by a face-to-face review.

    For a mechanical restraint or a seclusion the reviewer must differ from the
    orderer, so the second psychiatrist reviews by default.
    """
    episode = order_restraint(
        api,
        roster,
        admission_id,
        intervention_type,
        ordered_duration_minutes,
        headers=orderer_headers,
    )
    return get_success_data(
        api.record_face_to_face(
            reviewer_headers or roster.second_psychiatrist_headers,
            episode["id"],
            factories.face_to_face_payload(),
        ),
        200,
    )


def log_monitoring_checks(
    api,
    roster: Roster,
    restraint_id: str,
    check_clocks: Sequence[str],
    check_type: str = "CIRCULATION",
) -> List[Dict[str, Any]]:
    """Log one monitoring check at each supplied instant, moving the clock."""
    results: List[Dict[str, Any]] = []
    for moment in check_clocks:
        set_clock(api, moment)
        results.append(
            get_success_data(
                api.add_monitoring_check(
                    roster.charge_nurse_headers,
                    restraint_id,
                    factories.monitoring_check_payload(check_type=check_type),
                ),
                200,
            )
        )
    return results


def release_restraint(
    api,
    roster: Roster,
    restraint_id: str,
    release_clock: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Release an ACTIVE episode, optionally moving the clock first."""
    if release_clock is not None:
        set_clock(api, release_clock)
    response = api.release_restraint(
        headers or roster.charge_nurse_headers,
        restraint_id,
        factories.release_payload(),
    )
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Tier 5: capacity, consent and discharge
# ---------------------------------------------------------------------------


def determine_capacity(
    api,
    roster: Roster,
    admission_id: str,
    capacity_present: bool,
    *,
    surrogate_name: Optional[str] = None,
    surrogate_relationship: Optional[str] = None,
    surrogate_authority_scope: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Record a capacity determination, re-reading the admission version first."""
    response = api.create_capacity_determination(
        headers or roster.psychiatrist_headers,
        factories.capacity_determination_payload(
            admission_id=admission_id,
            expected_admission_version=admission_version(api, admission_id),
            capacity_present=capacity_present,
            surrogate_name=surrogate_name,
            surrogate_relationship=surrogate_relationship,
            surrogate_authority_scope=surrogate_authority_scope,
        ),
    )
    return get_success_data(response, 201)


def request_discharge(
    api,
    roster: Roster,
    admission_id: str,
    requested_by: str = "PATIENT",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Record a patient-initiated discharge request, which lands PENDING."""
    response = api.create_discharge_request(
        headers or roster.charge_nurse_headers,
        factories.discharge_request_payload(
            admission_id=admission_id, requested_by=requested_by
        ),
    )
    return get_success_data(response, 201)


def secure_discharge_plan(
    api,
    roster: Roster,
    admission_id: str,
    follow_up_appointment_at: Optional[str] = None,
    *,
    follow_up_provider_name: str = "Eastside Community Mental Health",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Submit a follow-up appointment, moving the plan to APPOINTMENT_SECURED.

    With no explicit appointment the helper books one a week out, which is
    comfortably inside the shortest guarantee window the tables allow.
    """
    if follow_up_appointment_at is None:
        follow_up_appointment_at = shift(PINNED_CLOCK, days=4)
    response = api.submit_discharge_plan(
        headers or roster.psychiatrist_headers,
        admission_id,
        factories.discharge_plan_payload(
            follow_up_appointment_at=follow_up_appointment_at,
            follow_up_provider_name=follow_up_provider_name,
        ),
    )
    return get_success_data(response, 200)


def discharge(
    api,
    roster: Roster,
    admission_id: str,
    discharge_summary: str = "Stabilized, safety plan reviewed, medications reconciled.",
) -> Dict[str, Any]:
    """Physically discharge an admission."""
    response = api.discharge_admission(
        roster.psychiatrist_headers,
        admission_id,
        factories.discharge_payload(discharge_summary),
    )
    return get_success_data(response, 200)
