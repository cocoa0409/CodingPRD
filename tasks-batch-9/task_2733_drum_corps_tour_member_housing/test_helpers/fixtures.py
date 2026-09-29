"""Composite setup helpers.

Every precondition is built from scratch through the endpoints the PRD declares,
because each test runs against a freshly launched server with an empty store.
Setup calls use get_success_data(), so a broken precondition fails loudly with
the error identifier the server returned rather than silently later.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK_ISO
from .test_users import (
    BUSINESS_MANAGER_HEADERS,
    CORPS_DIRECTOR_HEADERS,
    MEMBERSHIP_COORDINATOR_HEADERS,
    SECOND_BUSINESS_MANAGER_HEADERS,
    TOUR_MANAGER_HEADERS,
    VOLUNTEER_SCREENER_HEADERS,
    make_member_headers,
    make_volunteer_headers,
)
from .types import (
    AuditionDecision,
    Duty,
    PaymentMethod,
    ScreeningDecision,
    StopType,
    UsageType,
    VolunteerRoleType,
)

JsonDict = Dict[str, Any]


# ============================================================ tier 0: the clock
def set_clock(api: ApiClient, to_iso8601: str) -> None:
    """Move the logical clock to an explicit instant."""
    get_success_data(api.set_clock(to_iso8601, CORPS_DIRECTOR_HEADERS))


def reset_clock(api: ApiClient) -> None:
    set_clock(api, DEFAULT_CLOCK_ISO)


# ======================================================= tier 1: atomic reads
def get_season(api: ApiClient, season_id: str, headers=None) -> JsonDict:
    return get_success_data(api.get_season(season_id, headers or CORPS_DIRECTOR_HEADERS))


def get_member(api: ApiClient, member_id: str, headers=None) -> JsonDict:
    return get_success_data(
        api.get_member(member_id, headers or MEMBERSHIP_COORDINATOR_HEADERS)
    )


def get_contract(api: ApiClient, contract_id: str, headers=None) -> JsonDict:
    return get_success_data(
        api.get_member_contract(contract_id, headers or MEMBERSHIP_COORDINATOR_HEADERS)
    )


def get_plan(api: ApiClient, plan_id: str, headers=None) -> JsonDict:
    return get_success_data(
        api.get_payment_plan(plan_id, headers or BUSINESS_MANAGER_HEADERS)
    )


def get_payment(api: ApiClient, payment_id: str, headers=None) -> JsonDict:
    return get_success_data(
        api.get_tuition_payment(payment_id, headers or BUSINESS_MANAGER_HEADERS)
    )


def get_school(api: ApiClient, school_id: str, headers=None) -> JsonDict:
    return get_success_data(
        api.get_host_school(school_id, headers or TOUR_MANAGER_HEADERS)
    )


def get_agreement(api: ApiClient, agreement_id: str, headers=None) -> JsonDict:
    return get_success_data(
        api.get_facility_agreement(agreement_id, headers or TOUR_MANAGER_HEADERS)
    )


def get_housing(api: ApiClient, assignment_id: str, headers=None) -> JsonDict:
    return get_success_data(
        api.get_housing_assignment(
            assignment_id, headers or MEMBERSHIP_COORDINATOR_HEADERS
        )
    )


def get_stop(api: ApiClient, stop_id: str, headers=None) -> JsonDict:
    return get_success_data(api.get_tour_stop(stop_id, headers or TOUR_MANAGER_HEADERS))


def get_booking(api: ApiClient, booking_id: str, headers=None) -> JsonDict:
    return get_success_data(
        api.get_site_booking(booking_id, headers or TOUR_MANAGER_HEADERS)
    )


def get_volunteer(api: ApiClient, volunteer_id: str, headers=None) -> JsonDict:
    return get_success_data(
        api.get_volunteer(volunteer_id, headers or VOLUNTEER_SCREENER_HEADERS)
    )


def get_shift(api: ApiClient, assignment_id: str, headers=None) -> JsonDict:
    return get_success_data(
        api.get_staff_assignment(assignment_id, headers or TOUR_MANAGER_HEADERS)
    )


def get_settlement(api: ApiClient, settlement_id: str, headers=None) -> JsonDict:
    return get_success_data(
        api.get_show_settlement(settlement_id, headers or BUSINESS_MANAGER_HEADERS)
    )


# ==================================================== tier 2: atomic creators
def create_season(api: ApiClient, **overrides) -> JsonDict:
    return get_success_data(
        api.create_season(f.season_payload(**overrides), CORPS_DIRECTOR_HEADERS)
    )


def create_member(api: ApiClient, season_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.create_member(
            f.member_payload(season_id, **overrides), MEMBERSHIP_COORDINATOR_HEADERS
        )
    )


def create_school(api: ApiClient, **overrides) -> JsonDict:
    return get_success_data(
        api.create_host_school(f.host_school_payload(**overrides), TOUR_MANAGER_HEADERS)
    )


def create_volunteer(
    api: ApiClient, role_type: str = VolunteerRoleType.CHAPERONE, **overrides
) -> JsonDict:
    return get_success_data(
        api.create_volunteer(
            f.volunteer_payload(role_type, **overrides), VOLUNTEER_SCREENER_HEADERS
        )
    )


def create_stop(api: ApiClient, season_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.create_tour_stop(
            f.tour_stop_payload(season_id, **overrides), TOUR_MANAGER_HEADERS
        )
    )


def create_rehearsal_stop(api: ApiClient, season_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.create_tour_stop(
            f.rehearsal_stop_payload(season_id, **overrides), TOUR_MANAGER_HEADERS
        )
    )


def run_sweep(api: ApiClient, season_id: str) -> JsonDict:
    """One billing sweep over the season; returns the season it hands back."""
    return get_success_data(api.run_billing_cycle(season_id, BUSINESS_MANAGER_HEADERS))


# ================================================== tier 3: state advancers
def offer_member(api: ApiClient, member_id: str, audition_score: int = 92) -> JsonDict:
    return get_success_data(
        api.record_audition_decision(
            member_id,
            f.audition_decision_payload(
                decision=AuditionDecision.OFFER, audition_score=audition_score
            ),
            MEMBERSHIP_COORDINATOR_HEADERS,
        )
    )


def decline_member(api: ApiClient, member_id: str, audition_score: int = 40) -> JsonDict:
    return get_success_data(
        api.record_audition_decision(
            member_id,
            f.audition_decision_payload(
                decision=AuditionDecision.DECLINE, audition_score=audition_score
            ),
            MEMBERSHIP_COORDINATOR_HEADERS,
        )
    )


def set_medical(api: ApiClient, member_id: str, to_medical_status: str, note: str = "note") -> JsonDict:
    return get_success_data(
        api.set_medical_status(
            member_id,
            f.medical_status_payload(to_medical_status, note=note),
            MEMBERSHIP_COORDINATOR_HEADERS,
        )
    )


def withdraw_member(api: ApiClient, member_id: str, withdrawal_date: str, **overrides) -> JsonDict:
    return get_success_data(
        api.withdraw_member(
            member_id,
            f.withdraw_payload(withdrawal_date, **overrides),
            MEMBERSHIP_COORDINATOR_HEADERS,
        )
    )


def issue_contract(api: ApiClient, member_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.create_member_contract(
            f.member_contract_payload(member_id, **overrides),
            MEMBERSHIP_COORDINATOR_HEADERS,
        )
    )


def request_revision(api: ApiClient, contract_id: str, member_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.request_contract_revision(
            contract_id,
            f.revision_request_payload(**overrides),
            make_member_headers(member_id),
        )
    )


def reissue_contract(api: ApiClient, contract_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.reissue_member_contract(
            contract_id, f.reissue_payload(**overrides), MEMBERSHIP_COORDINATOR_HEADERS
        )
    )


def sign_contract(
    api: ApiClient, contract_id: str, member_id: str, signature_name: str = "Signed Member"
) -> JsonDict:
    return get_success_data(
        api.sign_member_contract(
            contract_id,
            f.signature_payload(signature_name),
            make_member_headers(member_id),
        )
    )


def execute_contract(api: ApiClient, contract_id: str) -> JsonDict:
    return get_success_data(
        api.execute_member_contract(contract_id, CORPS_DIRECTOR_HEADERS)
    )


def create_plan(
    api: ApiClient,
    member_id: str,
    contract_id: str,
    first_due_date: str,
    expected_member_version: Optional[int] = None,
) -> JsonDict:
    if expected_member_version is None:
        expected_member_version = get_member(api, member_id)["version"]
    return get_success_data(
        api.create_payment_plan(
            f.payment_plan_payload(
                member_id, contract_id, first_due_date, expected_member_version
            ),
            BUSINESS_MANAGER_HEADERS,
        )
    )


def post_payment(
    api: ApiClient,
    plan_id: str,
    amount_cents: int,
    received_on: str,
    method: str = PaymentMethod.CHECK,
) -> JsonDict:
    return get_success_data(
        api.create_tuition_payment(
            f.tuition_payment_payload(plan_id, amount_cents, received_on, method=method),
            BUSINESS_MANAGER_HEADERS,
        )
    )


def reverse_payment(api: ApiClient, payment_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.reverse_tuition_payment(
            payment_id, f.reversal_payload(**overrides), BUSINESS_MANAGER_HEADERS
        )
    )


def draft_agreement(api: ApiClient, school_id: str, season_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.create_facility_agreement(
            f.facility_agreement_payload(school_id, season_id, **overrides),
            TOUR_MANAGER_HEADERS,
        )
    )


def submit_agreement(api: ApiClient, agreement_id: str) -> JsonDict:
    return get_success_data(
        api.submit_facility_agreement(agreement_id, TOUR_MANAGER_HEADERS)
    )


def counter_agreement(api: ApiClient, agreement_id: str, countered_nightly_rate_cents: int) -> JsonDict:
    return get_success_data(
        api.counter_facility_agreement(
            agreement_id,
            f.counter_payload(countered_nightly_rate_cents),
            TOUR_MANAGER_HEADERS,
        )
    )


def sign_agreement(api: ApiClient, agreement_id: str) -> JsonDict:
    return get_success_data(
        api.sign_facility_agreement(agreement_id, CORPS_DIRECTOR_HEADERS)
    )


def cancel_agreement(api: ApiClient, agreement_id: str, reason: str = "School withdrew") -> JsonDict:
    return get_success_data(
        api.cancel_facility_agreement(
            agreement_id, f.cancel_payload(reason), CORPS_DIRECTOR_HEADERS
        )
    )


def house_member(
    api: ApiClient,
    agreement_id: str,
    member_id: str,
    space_index: int,
    check_in_date: str,
    check_out_date: str,
    expected_facility_agreement_version: Optional[int] = None,
) -> JsonDict:
    if expected_facility_agreement_version is None:
        expected_facility_agreement_version = get_agreement(api, agreement_id)["version"]
    return get_success_data(
        api.create_housing_assignment(
            f.housing_assignment_payload(
                agreement_id,
                member_id,
                space_index,
                check_in_date,
                check_out_date,
                expected_facility_agreement_version,
            ),
            MEMBERSHIP_COORDINATOR_HEADERS,
        )
    )


def release_housing(api: ApiClient, assignment_id: str) -> JsonDict:
    return get_success_data(
        api.release_housing_assignment(assignment_id, MEMBERSHIP_COORDINATOR_HEADERS)
    )


def confirm_stop(api: ApiClient, stop_id: str) -> JsonDict:
    return get_success_data(api.confirm_tour_stop(stop_id, TOUR_MANAGER_HEADERS))


def complete_stop(api: ApiClient, stop_id: str) -> JsonDict:
    return get_success_data(api.complete_tour_stop(stop_id, TOUR_MANAGER_HEADERS))


def cancel_stop(api: ApiClient, stop_id: str, reason: str = "Venue flooded") -> JsonDict:
    return get_success_data(
        api.cancel_tour_stop(stop_id, f.cancel_payload(reason), CORPS_DIRECTOR_HEADERS)
    )


def create_booking(
    api: ApiClient,
    stop_id: str,
    school_id: str,
    agreement_id: str,
    block_start_at: str,
    block_end_at: str,
    **overrides,
) -> JsonDict:
    return get_success_data(
        api.create_site_booking(
            f.site_booking_payload(
                stop_id, school_id, agreement_id, block_start_at, block_end_at, **overrides
            ),
            TOUR_MANAGER_HEADERS,
        )
    )


def release_booking(api: ApiClient, booking_id: str) -> JsonDict:
    return get_success_data(api.release_site_booking(booking_id, TOUR_MANAGER_HEADERS))


def clear_volunteer(
    api: ApiClient, volunteer_id: str, decided_on: str, headers=None
) -> JsonDict:
    return get_success_data(
        api.record_screening_decision(
            volunteer_id,
            f.screening_decision_payload(decided_on, ScreeningDecision.CLEAR),
            headers or VOLUNTEER_SCREENER_HEADERS,
        )
    )


def reject_volunteer(
    api: ApiClient, volunteer_id: str, decided_on: str, headers=None
) -> JsonDict:
    return get_success_data(
        api.record_screening_decision(
            volunteer_id,
            f.screening_decision_payload(decided_on, ScreeningDecision.REJECT),
            headers or VOLUNTEER_SCREENER_HEADERS,
        )
    )


def propose_shift(
    api: ApiClient,
    volunteer_id: str,
    stop_id: str,
    duty: str,
    shift_start_at: str,
    shift_end_at: str,
) -> JsonDict:
    return get_success_data(
        api.create_staff_assignment(
            f.staff_assignment_payload(
                volunteer_id, stop_id, duty, shift_start_at, shift_end_at
            ),
            TOUR_MANAGER_HEADERS,
        )
    )


def accept_shift(api: ApiClient, assignment_id: str, volunteer_id: str) -> JsonDict:
    return get_success_data(
        api.accept_staff_assignment(assignment_id, make_volunteer_headers(volunteer_id))
    )


def approve_shift(api: ApiClient, assignment_id: str, headers=None) -> JsonDict:
    return get_success_data(
        api.approve_staff_assignment(assignment_id, headers or TOUR_MANAGER_HEADERS)
    )


def open_settlement(
    api: ApiClient,
    stop_id: str,
    appearance_fee_cents: int,
    prize_pool_cents: int,
    projected_placement: int,
    headers=None,
) -> JsonDict:
    return get_success_data(
        api.create_show_settlement(
            f.show_settlement_payload(
                stop_id, appearance_fee_cents, prize_pool_cents, projected_placement
            ),
            headers or BUSINESS_MANAGER_HEADERS,
        )
    )


def finalize_settlement(
    api: ApiClient,
    settlement_id: str,
    final_placement: int,
    remittance_lines: Optional[List[JsonDict]] = None,
    headers=None,
) -> JsonDict:
    return get_success_data(
        api.finalize_show_settlement(
            settlement_id,
            f.finalize_payload(final_placement, remittance_lines),
            headers or SECOND_BUSINESS_MANAGER_HEADERS,
        )
    )


# ============================================== tier 4: composite chains
def offered_member(api: ApiClient, season_id: str, audition_score: int = 92, **member_overrides) -> JsonDict:
    """A member who has been registered and offered a place."""
    member = create_member(api, season_id, **member_overrides)
    return offer_member(api, member["id"], audition_score)


def contracted_member(
    api: ApiClient,
    season_id: str,
    tuition_amount_cents: int = f.SEASON_TUITION_BASE_CENTS,
    payment_plan_type: str = "STANDARD_3",
    signature_name: str = "Signed Member",
    **member_overrides,
) -> JsonDict:
    """Register, offer, issue, sign and execute — a member on the roster.

    Returns {"member": ..., "contract": ...} with both records freshly read.
    """
    member = create_member(api, season_id, **member_overrides)
    offer_member(api, member["id"])
    contract = issue_contract(
        api,
        member["id"],
        tuition_amount_cents=tuition_amount_cents,
        payment_plan_type=payment_plan_type,
    )
    sign_contract(api, contract["id"], member["id"], signature_name)
    contract = execute_contract(api, contract["id"])
    return {"member": get_member(api, member["id"]), "contract": contract}


def financed_member(
    api: ApiClient,
    season_id: str,
    first_due_date: str,
    tuition_amount_cents: int = f.SEASON_TUITION_BASE_CENTS,
    payment_plan_type: str = "STANDARD_3",
    **member_overrides,
) -> JsonDict:
    """A contracted member with the installment plan that finances them.

    Returns {"member": ..., "contract": ..., "plan": ...}.
    """
    built = contracted_member(
        api,
        season_id,
        tuition_amount_cents=tuition_amount_cents,
        payment_plan_type=payment_plan_type,
        **member_overrides,
    )
    plan = create_plan(
        api,
        built["member"]["id"],
        built["contract"]["id"],
        first_due_date,
        built["member"]["version"],
    )
    return {
        "member": get_member(api, built["member"]["id"]),
        "contract": built["contract"],
        "plan": plan,
    }


def signed_agreement_with_school(
    api: ApiClient,
    season_id: str,
    usage_type: str = UsageType.SPRING_TRAINING,
    school: Optional[JsonDict] = None,
    school_overrides: Optional[JsonDict] = None,
    counters: Optional[List[int]] = None,
    **agreement_overrides,
) -> JsonDict:
    """Draft, submit, optionally counter, and sign a facility agreement.

    Returns {"school": ..., "agreement": ...} with both records freshly read.
    """
    if school is None:
        school = create_school(api, **(school_overrides or {}))
    agreement = draft_agreement(
        api, school["id"], season_id, usage_type=usage_type, **agreement_overrides
    )
    submit_agreement(api, agreement["id"])
    for rate in counters or []:
        counter_agreement(api, agreement["id"], rate)
        submit_agreement(api, agreement["id"])
    agreement = sign_agreement(api, agreement["id"])
    return {"school": get_school(api, school["id"]), "agreement": agreement}


def housed_member(
    api: ApiClient,
    season_id: str,
    check_in_date: str,
    check_out_date: str,
    space_index: int = 1,
    agreement: Optional[JsonDict] = None,
    school: Optional[JsonDict] = None,
    member: Optional[JsonDict] = None,
    **agreement_overrides,
) -> JsonDict:
    """A contracted member bedded down under a signed spring-training agreement.

    Returns {"school": ..., "agreement": ..., "member": ..., "assignment": ...}.
    """
    if agreement is None:
        built = signed_agreement_with_school(
            api, season_id, UsageType.SPRING_TRAINING, school=school, **agreement_overrides
        )
        school, agreement = built["school"], built["agreement"]
    if member is None:
        member = contracted_member(api, season_id)["member"]
    assignment = house_member(
        api,
        agreement["id"],
        member["id"],
        space_index,
        check_in_date,
        check_out_date,
        agreement["version"],
    )
    return {
        "school": get_school(api, school["id"]),
        "agreement": get_agreement(api, agreement["id"]),
        "member": get_member(api, member["id"]),
        "assignment": assignment,
    }


def confirmed_stop(api: ApiClient, season_id: str, **overrides) -> JsonDict:
    """A stop planned and confirmed. Coverage gates must already be satisfied."""
    stop = create_stop(api, season_id, **overrides)
    return confirm_stop(api, stop["id"])


def completed_show_stop(api: ApiClient, season_id: str, **overrides) -> JsonDict:
    """A SHOW stop driven all the way to COMPLETED.

    Plans the stop, confirms it, advances the logical clock to its depart_at and
    completes it. The clock is left at the stop's depart_at, so a caller that
    cares about the clock afterwards should set it explicitly.
    """
    stop = create_stop(api, season_id, stop_type=StopType.SHOW, **overrides)
    confirm_stop(api, stop["id"])
    set_clock(api, stop["depart_at"])
    return complete_stop(api, stop["id"])


def draft_settlement_on_show(
    api: ApiClient,
    season_id: str,
    appearance_fee_cents: int,
    prize_pool_cents: int,
    projected_placement: int,
    preparer_headers=None,
    **stop_overrides,
) -> JsonDict:
    """A completed SHOW stop carrying a DRAFT settlement.

    Returns {"stop": ..., "settlement": ...}.
    """
    stop = completed_show_stop(api, season_id, **stop_overrides)
    settlement = open_settlement(
        api,
        stop["id"],
        appearance_fee_cents,
        prize_pool_cents,
        projected_placement,
        headers=preparer_headers,
    )
    return {"stop": get_stop(api, stop["id"]), "settlement": settlement}


def screened_volunteer(
    api: ApiClient,
    role_type: str,
    decided_on: str,
    screener_headers=None,
    **volunteer_overrides,
) -> JsonDict:
    """A volunteer registered and cleared on the given date."""
    volunteer = create_volunteer(api, role_type, **volunteer_overrides)
    return clear_volunteer(api, volunteer["id"], decided_on, headers=screener_headers)


def approved_shift(
    api: ApiClient,
    volunteer_id: str,
    stop_id: str,
    duty: str,
    shift_start_at: str,
    shift_end_at: str,
    approver_headers=None,
) -> JsonDict:
    """Propose, accept and approve one shift in a single call."""
    shift = propose_shift(api, volunteer_id, stop_id, duty, shift_start_at, shift_end_at)
    accept_shift(api, shift["id"], volunteer_id)
    return approve_shift(api, shift["id"], headers=approver_headers)


def staffed_stop(
    api: ApiClient,
    season_id: str,
    duties: List[str],
    decided_on: str,
    shift_start_at: str,
    shift_end_at: str,
    approver_headers=None,
    **stop_overrides,
) -> JsonDict:
    """A planned stop carrying one approved shift per requested duty.

    Returns {"stop": ..., "volunteers": [...], "shifts": [...]}.
    """
    role_type_for_duty = {
        Duty.DRIVE: VolunteerRoleType.DRIVER,
        Duty.COOK: VolunteerRoleType.COOK,
        Duty.CHAPERONE: VolunteerRoleType.CHAPERONE,
        Duty.TRAINER: VolunteerRoleType.ATHLETIC_TRAINER,
    }
    stop = create_stop(api, season_id, **stop_overrides)
    volunteers: List[JsonDict] = []
    shifts: List[JsonDict] = []
    for duty in duties:
        volunteer = screened_volunteer(
            api, role_type_for_duty[duty], decided_on
        )
        shift = approved_shift(
            api,
            volunteer["id"],
            stop["id"],
            duty,
            shift_start_at,
            shift_end_at,
            approver_headers=approver_headers,
        )
        volunteers.append(get_volunteer(api, volunteer["id"]))
        shifts.append(shift)
    return {"stop": get_stop(api, stop["id"]), "volunteers": volunteers, "shifts": shifts}


def on_tour_member(
    api: ApiClient,
    season_id: str,
    first_due_date: str = "2027-06-20",
    tuition_amount_cents: int = f.SEASON_TUITION_BASE_CENTS,
    **member_overrides,
) -> JsonDict:
    """A contracted member promoted onto the touring roster by a sweep.

    The caller must already have moved the logical clock to or past the season's
    tour_departure_date, since that is the threshold the sweep compares against.
    """
    built = contracted_member(
        api, season_id, tuition_amount_cents=tuition_amount_cents, **member_overrides
    )
    run_sweep(api, season_id)
    return get_member(api, built["member"]["id"])
