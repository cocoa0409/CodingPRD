"""Request-payload factories.

Every monetary field is emitted as a JSON integer of cents, never as a decimal
and never as a numeric string. Passing OMIT for any key deletes it from the
payload, which is how tests exercise required-field and conditional-field rules.
"""

import itertools
from typing import Any, Dict

from .types import (
    AuditionDecision,
    DietaryFlag,
    Duty,
    PaymentMethod,
    PaymentPlanType,
    RemittanceKind,
    ScreeningDecision,
    Section,
    StopType,
    UsageType,
    VolunteerRoleType,
)


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "OMIT"


OMIT = _Omit()

_counter = itertools.count(1)


def unique_email(prefix: str = "person") -> str:
    """An email address no other record in this process has used."""
    return f"{prefix}.{next(_counter)}@corpsmail.test"


def unique_name(prefix: str = "Name") -> str:
    return f"{prefix} {next(_counter)}"


def _build(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if isinstance(value, _Omit):
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# --------------------------------------------------------------------- Seasons
SEASON_NAME = "2027 Tour"
SEASON_YEAR = 2027
SEASON_TUITION_BASE_CENTS = 399900
SPRING_START = "2027-05-10"
SPRING_END = "2027-06-05"
DEPARTURE = "2027-06-12"


def season_payload(**overrides) -> Dict[str, Any]:
    return _build(
        {
            "name": SEASON_NAME,
            "year": SEASON_YEAR,
            "tuition_base_cents": SEASON_TUITION_BASE_CENTS,
            "spring_training_start_date": SPRING_START,
            "spring_training_end_date": SPRING_END,
            "tour_departure_date": DEPARTURE,
        },
        overrides,
    )


# --------------------------------------------------------------------- Members
ADULT_DOB = "2005-03-15"
MINOR_DOB = "2010-09-01"
EIGHTEEN_ON_DEPARTURE_DOB = "2009-06-12"


def member_payload(season_id: str, **overrides) -> Dict[str, Any]:
    return _build(
        {
            "season_id": season_id,
            "full_name": unique_name("Member"),
            "email": unique_email("member"),
            "date_of_birth": ADULT_DOB,
            "section": Section.BRASS,
            "dietary_flag": DietaryFlag.NONE,
        },
        overrides,
    )


def audition_decision_payload(**overrides) -> Dict[str, Any]:
    return _build(
        {"decision": AuditionDecision.OFFER, "audition_score": 92}, overrides
    )


def medical_status_payload(to_medical_status: str, **overrides) -> Dict[str, Any]:
    return _build({"to_medical_status": to_medical_status}, overrides)


def withdraw_payload(withdrawal_date: str, **overrides) -> Dict[str, Any]:
    return _build(
        {"withdrawal_date": withdrawal_date, "reason": "Left the corps"}, overrides
    )


# ----------------------------------------------------------- Member contracts
def member_contract_payload(member_id: str, **overrides) -> Dict[str, Any]:
    return _build(
        {
            "member_id": member_id,
            "tuition_amount_cents": SEASON_TUITION_BASE_CENTS,
            "payment_plan_type": PaymentPlanType.STANDARD_3,
        },
        overrides,
    )


def revision_request_payload(**overrides) -> Dict[str, Any]:
    return _build({"revision_note": "Please reduce the tuition."}, overrides)


def reissue_payload(**overrides) -> Dict[str, Any]:
    return _build({}, overrides)


def signature_payload(signature_name: str = "Signed Member", **overrides) -> Dict[str, Any]:
    return _build({"signature_name": signature_name}, overrides)


# --------------------------------------------------------------- Payment plans
def payment_plan_payload(
    member_id: str,
    member_contract_id: str,
    first_due_date: str,
    expected_member_version: int,
    **overrides,
) -> Dict[str, Any]:
    return _build(
        {
            "member_id": member_id,
            "member_contract_id": member_contract_id,
            "first_due_date": first_due_date,
            "expected_member_version": expected_member_version,
        },
        overrides,
    )


def tuition_payment_payload(
    payment_plan_id: str, amount_cents: int, received_on: str, **overrides
) -> Dict[str, Any]:
    return _build(
        {
            "payment_plan_id": payment_plan_id,
            "amount_cents": amount_cents,
            "received_on": received_on,
            "method": PaymentMethod.CHECK,
        },
        overrides,
    )


def reversal_payload(**overrides) -> Dict[str, Any]:
    return _build({"reversal_reason": "Cheque returned unpaid"}, overrides)


# ---------------------------------------------------------------- Host schools
def host_school_payload(**overrides) -> Dict[str, Any]:
    return _build(
        {
            "name": unique_name("Host School"),
            "city": "Muncie",
            "state_code": "IN",
            "sleeping_space_count": 30,
            "capacity_per_space": 12,
            "rehearsal_field_count": 2,
            "has_air_conditioning": True,
        },
        overrides,
    )


# ---------------------------------------------------------- Facility agreements
def facility_agreement_payload(
    host_school_id: str, season_id: str, **overrides
) -> Dict[str, Any]:
    return _build(
        {
            "host_school_id": host_school_id,
            "season_id": season_id,
            "usage_type": UsageType.SPRING_TRAINING,
            "start_date": SPRING_START,
            "end_date": SPRING_END,
            "nightly_rate_cents": 450,
            "minimum_billable_beds": 0,
        },
        overrides,
    )


def counter_payload(countered_nightly_rate_cents: int, **overrides) -> Dict[str, Any]:
    return _build(
        {"countered_nightly_rate_cents": countered_nightly_rate_cents}, overrides
    )


def cancel_payload(reason: str = "No longer needed", **overrides) -> Dict[str, Any]:
    return _build({"cancel_reason": reason}, overrides)


# ---------------------------------------------------------- Housing assignments
def housing_assignment_payload(
    facility_agreement_id: str,
    member_id: str,
    space_index: int,
    check_in_date: str,
    check_out_date: str,
    expected_facility_agreement_version: int,
    **overrides,
) -> Dict[str, Any]:
    return _build(
        {
            "facility_agreement_id": facility_agreement_id,
            "member_id": member_id,
            "space_index": space_index,
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
            "expected_facility_agreement_version": expected_facility_agreement_version,
        },
        overrides,
    )


# ------------------------------------------------------------------ Tour stops
def tour_stop_payload(season_id: str, **overrides) -> Dict[str, Any]:
    return _build(
        {
            "season_id": season_id,
            "stop_type": StopType.SHOW,
            "venue_name": unique_name("Stadium"),
            "city": "Allentown",
            "state_code": "PA",
            "arrive_at": "2027-06-20T10:00:00Z",
            "depart_at": "2027-06-20T23:00:00Z",
            "show_start_at": "2027-06-20T20:00:00Z",
            "travel_miles_from_previous": 0,
            "uniform_trunks": 0,
            "instrument_cases": 0,
            "prop_units": 0,
            "truck_count": 4,
            "rehearsal_minutes": 0,
            "heat_index_f": 80,
        },
        overrides,
    )


def rehearsal_stop_payload(season_id: str, **overrides) -> Dict[str, Any]:
    base = tour_stop_payload(
        season_id, stop_type=StopType.REHEARSAL_ONLY, show_start_at=OMIT
    )
    return _build(base, overrides)


# ---------------------------------------------------------------- Site bookings
def site_booking_payload(
    tour_stop_id: str,
    host_school_id: str,
    facility_agreement_id: str,
    block_start_at: str,
    block_end_at: str,
    **overrides,
) -> Dict[str, Any]:
    return _build(
        {
            "tour_stop_id": tour_stop_id,
            "host_school_id": host_school_id,
            "facility_agreement_id": facility_agreement_id,
            "block_start_at": block_start_at,
            "block_end_at": block_end_at,
            "indoor": True,
        },
        overrides,
    )


# ------------------------------------------------------------------ Volunteers
def volunteer_payload(role_type: str = VolunteerRoleType.CHAPERONE, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": unique_name("Volunteer"),
        "email": unique_email("volunteer"),
        "role_type": role_type,
    }
    if role_type == VolunteerRoleType.DRIVER:
        payload["cdl_number"] = "CDL-" + str(next(_counter))
    if role_type == VolunteerRoleType.ATHLETIC_TRAINER:
        payload["credential_id"] = "ATC-" + str(next(_counter))
    return _build(payload, overrides)


def screening_decision_payload(
    decided_on: str, decision: str = ScreeningDecision.CLEAR, **overrides
) -> Dict[str, Any]:
    return _build({"decision": decision, "decided_on": decided_on}, overrides)


# ------------------------------------------------------------ Staff assignments
def staff_assignment_payload(
    volunteer_id: str,
    tour_stop_id: str,
    duty: str,
    shift_start_at: str,
    shift_end_at: str,
    **overrides,
) -> Dict[str, Any]:
    return _build(
        {
            "volunteer_id": volunteer_id,
            "tour_stop_id": tour_stop_id,
            "duty": duty,
            "shift_start_at": shift_start_at,
            "shift_end_at": shift_end_at,
        },
        overrides,
    )


# ------------------------------------------------------------ Show settlements
def show_settlement_payload(
    tour_stop_id: str,
    appearance_fee_cents: int,
    prize_pool_cents: int,
    projected_placement: int,
    **overrides,
) -> Dict[str, Any]:
    return _build(
        {
            "tour_stop_id": tour_stop_id,
            "appearance_fee_cents": appearance_fee_cents,
            "prize_pool_cents": prize_pool_cents,
            "projected_placement": projected_placement,
        },
        overrides,
    )


def remittance_line(kind: str, amount_cents: int, recorded_at: str) -> Dict[str, Any]:
    return {"kind": kind, "amount_cents": amount_cents, "recorded_at": recorded_at}


def sanction_line(amount_cents: int, recorded_at: str) -> Dict[str, Any]:
    return remittance_line(RemittanceKind.SANCTION_FEE, amount_cents, recorded_at)


def rebate_line(amount_cents: int, recorded_at: str) -> Dict[str, Any]:
    return remittance_line(RemittanceKind.FEE_REBATE, amount_cents, recorded_at)


def prize_adjustment_line(amount_cents: int, recorded_at: str) -> Dict[str, Any]:
    return remittance_line(RemittanceKind.PRIZE_ADJUSTMENT, amount_cents, recorded_at)


def finalize_payload(final_placement: int, remittance_lines=None, **overrides) -> Dict[str, Any]:
    return _build(
        {
            "final_placement": final_placement,
            "remittance_lines": list(remittance_lines or []),
        },
        overrides,
    )


DUTY_BY_ROLE_TYPE = {
    VolunteerRoleType.DRIVER: Duty.DRIVE,
    VolunteerRoleType.COOK: Duty.COOK,
    VolunteerRoleType.CHAPERONE: Duty.CHAPERONE,
    VolunteerRoleType.ATHLETIC_TRAINER: Duty.TRAINER,
}
