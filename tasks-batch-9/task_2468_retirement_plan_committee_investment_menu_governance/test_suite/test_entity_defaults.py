"""Creation-time state of the governance skeleton: the plan, its committee seats,
the appointments that fill them, the fiduciary training records that qualify
them, and the derived surface a plan read exposes once the charter and the policy
statement are in place.

Every expectation here comes from PRD 3.1 (plan registration and charter
adoption), PRD 3.2 (seats, appointments, training and documented acceptance),
PRD 2.4 (identity and audit stamps) and PRD 2.9 (the menu-posture ladder).
"""

from test_helpers.api_client import paginate_params
from test_helpers.assertions import (
    assert_capacity_triple,
    assert_common_fields,
    assert_contains_ids,
    assert_fields,
    assert_ratio,
    assert_version_bumped,
    is_iso8601_timestamp,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    Paths,
    member_payload,
    plan_payload,
    seat_payload,
    training_payload,
    without,
)
from test_helpers.fixtures import (
    activate_member,
    adopt_charter,
    appoint_member,
    assign_training,
    complete_training,
    create_seat,
    read_meeting,
    read_member,
    read_motion,
    read_plan,
    register_plan,
    sign_acceptance,
)
from test_helpers.test_users import auditor_headers, sponsor_headers
from test_helpers.types import (
    CharterStatus,
    FeeDisclosureStatus,
    FiduciaryTrainingStatus,
    IpsStatus,
    MeetingStatus,
    MemberStatus,
    MenuPosture,
    MotionStatus,
    ScoringVariant,
    SeatStatus,
    TrainingModule,
    TrainingStatus,
)


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


def test_plan_registration_starts_draft_frozen_with_the_whole_capacity_available(api):
    """Registering a plan returns a DRAFT charter, a FROZEN posture and the full
    slot capacity sitting in the available partition.

    Design: Corner/entities/plan_create_starts_draft_charter_frozen_posture_and_full_capacity
    """
    response = api.post(
        Paths.PLANS, plan_payload(menu_slot_capacity=6), sponsor_headers()
    )
    plan = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object", body["response_type"]
    assert body["meta"]["api_request_id"].startswith("req_"), body["meta"]
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), body["meta"]

    assert_common_fields(plan)
    assert_fields(
        plan,
        charter_status=CharterStatus.DRAFT,
        charter_adopted_quarter_index=None,
        menu_posture=MenuPosture.FROZEN,
        fiscal_quarter_index=0,
        fee_disclosure_status=FeeDisclosureStatus.COMPLIANT,
        menu_slot_capacity=6,
        occupied_menu_slots=0,
        reserved_menu_slots=0,
        available_menu_slots=6,
        draft_proposal_count=0,
        documented_acceptance_count=0,
        total_plan_assets_cents=0,
        revenue_credit_accrued_cents=0,
        revenue_credit_allocated_cents=0,
        revenue_credit_balance_cents=0,
        version=1,
    )
    assert_ratio(plan["at_risk_slot_ratio"], "0.0000", "at_risk_slot_ratio")
    # PRD 2.10: available_menu_slots starts equal to menu_slot_capacity.
    assert_capacity_triple(plan, occupied=0, reserved=0, available=6)


# --------------------------------------------------------------------------
# Seats and appointments
# --------------------------------------------------------------------------


def test_seat_creation_starts_vacant_on_a_plan_whose_charter_is_still_draft(api):
    """A committee seat is created VACANT with no vacant quarters behind it, even
    though the plan's charter has not been adopted yet.

    Design: Corner/entities/committee_seat_create_starts_vacant_with_zero_vacant_quarters
    """
    plan = register_plan(api)

    response = api.post(
        Paths.SEATS,
        seat_payload(plan["id"], seat_code="S-CHAIR", voting=True, seat_index=1),
        sponsor_headers(),
    )
    seat = validate_success(response, 201)

    assert_common_fields(seat)
    assert_fields(
        seat,
        plan_id=plan["id"],
        seat_code="S-CHAIR",
        status=SeatStatus.VACANT,
        consecutive_vacant_quarters=0,
        voting=True,
        seat_index=1,
        version=1,
    )
    # Seat creation is legal while the charter is still DRAFT (PRD 3.1 requires
    # the seats to exist *before* adoption).
    assert read_plan(api, plan["id"])["charter_status"] == CharterStatus.DRAFT

    rows, meta = validate_paginated(
        api.get(
            Paths.SEATS,
            sponsor_headers(),
            paginate_params(plan_id=plan["id"], status=SeatStatus.VACANT),
        )
    )
    assert meta["total_count"] == 1, meta
    assert_contains_ids(rows, seat["id"])


def test_appointment_creates_an_appointed_member_with_pending_training(api):
    """An appointment lands in APPOINTED with no acceptance on file, training
    PENDING and no votes cast.

    Design: Corner/entities/member_appointment_fills_its_seat_and_starts_appointed
    """
    plan = register_plan(api)
    seat = create_seat(api, plan["id"])

    response = api.post(
        Paths.MEMBERS,
        member_payload(seat["id"], member_name="Dana Okonjo"),
        sponsor_headers(),
    )
    member = validate_success(response, 201)

    assert_common_fields(member)
    assert_fields(
        member,
        seat_id=seat["id"],
        # PRD 3.2: the request field member_name is stored as person_name.
        person_name="Dana Okonjo",
        status=MemberStatus.APPOINTED,
        acceptance_signed_at=None,
        fiduciary_training_status=FiduciaryTrainingStatus.PENDING,
        independence_flag=True,
        votes_cast_count=0,
        version=1,
    )


def test_appointment_flips_its_parent_seat_from_vacant_to_filled(api):
    """Filling a seat is what moves it out of VACANT: the parent seat reads
    FILLED in the same request that creates the member.

    Design: Corner/entities/member_appointment_fills_its_seat_and_starts_appointed
    """
    plan = register_plan(api)
    seat = create_seat(api, plan["id"])
    assert seat["status"] == SeatStatus.VACANT

    member = appoint_member(api, seat["id"])

    seat_after = validate_success(api.get(Paths.seat(seat["id"]), sponsor_headers()))
    assert_fields(
        seat_after,
        status=SeatStatus.FILLED,
        consecutive_vacant_quarters=0,
    )

    rows, meta = validate_paginated(
        api.get(Paths.MEMBERS, sponsor_headers(), paginate_params(seat_id=seat["id"]))
    )
    assert meta["total_count"] == 1, meta
    assert_contains_ids(rows, member["id"])


# --------------------------------------------------------------------------
# Fiduciary training records
# --------------------------------------------------------------------------


def test_training_assignment_applies_the_declared_defaults(api):
    """An assigned training record is ASSIGNED, carries the declared eight-quarter
    validity and is stamped with the plan's current fiscal quarter, with nothing
    recorded about completion yet.

    Design: Corner/entities/training_record_assign_applies_declared_defaults_and_moves_member_to_training_assigned
    """
    plan = register_plan(api)
    seat = create_seat(api, plan["id"])
    member = appoint_member(api, seat["id"])

    # validity_quarters is omitted so the declared default is exercised.
    payload = without(
        training_payload(member["id"], module_code=TrainingModule.FIDUCIARY_DUTIES),
        "validity_quarters",
    )
    response = api.post(Paths.TRAINING_RECORDS, payload, sponsor_headers())
    record = validate_success(response, 201)

    assert_common_fields(record)
    assert_fields(
        record,
        member_id=member["id"],
        module_code=TrainingModule.FIDUCIARY_DUTIES,
        status=TrainingStatus.ASSIGNED,
        validity_quarters=8,
        # PRD 3.2: assigned_quarter_index copies the plan's fiscal_quarter_index,
        # which registration set to 0.
        assigned_quarter_index=0,
        completed_quarter_index=None,
        score_pct=None,
        version=1,
    )


def test_training_assignment_moves_the_member_to_training_assigned_only(api):
    """Assigning training moves an APPOINTED member to TRAINING_ASSIGNED, leaves
    training currency PENDING because the second required module is still
    missing, and does not touch the plan's documented acceptance count.

    Design: Corner/entities/training_record_assign_applies_declared_defaults_and_moves_member_to_training_assigned
    """
    plan = register_plan(api)
    seat = create_seat(api, plan["id"])
    member = appoint_member(api, seat["id"])
    assert member["status"] == MemberStatus.APPOINTED

    assign_training(api, member["id"], module_code=TrainingModule.FIDUCIARY_DUTIES)

    member_after = read_member(api, member["id"])
    assert_fields(
        member_after,
        status=MemberStatus.TRAINING_ASSIGNED,
        fiduciary_training_status=FiduciaryTrainingStatus.PENDING,
        acceptance_signed_at=None,
    )
    # PRD 3.2: the assignment branch deliberately leaves documented_acceptance_count alone.
    assert read_plan(api, plan["id"])["documented_acceptance_count"] == 0


# --------------------------------------------------------------------------
# documented_acceptance_count
# --------------------------------------------------------------------------


def test_documented_acceptance_count_counts_a_signature_once_not_again_on_activation(api):
    """The plan's documented acceptance count rises by exactly one when a member
    signs, and activating that same member does not add a second unit.

    Design: Corner/entities/plan_documented_acceptance_count_is_a_count_not_a_counter
    """
    plan = register_plan(api)
    seat = create_seat(api, plan["id"])
    member = appoint_member(api, seat["id"])
    assert read_plan(api, plan["id"])["documented_acceptance_count"] == 0

    for module in TrainingModule.REQUIRED:
        record = assign_training(api, member["id"], module_code=module)
        complete_training(api, record["id"], member["id"], 95.00)
    assert read_plan(api, plan["id"])["documented_acceptance_count"] == 0

    signed = sign_acceptance(api, member["id"])
    assert signed["acceptance_signed_at"] is not None
    assert read_plan(api, plan["id"])["documented_acceptance_count"] == 1

    activated = activate_member(api, member["id"])
    assert activated["status"] == MemberStatus.ACTIVE
    # PRD 3.2: activation recomputes posture; it does not re-count the acceptance.
    assert read_plan(api, plan["id"])["documented_acceptance_count"] == 1


def test_documented_acceptance_count_is_three_for_three_accepted_members(api, committee):
    """Three members who each signed and then activated leave the count at three,
    and charter adoption reports that same three.

    Design: Corner/entities/plan_documented_acceptance_count_is_a_count_not_a_counter
    """
    ctx = committee
    before = read_plan(api, ctx.plan_id)
    assert before["documented_acceptance_count"] == 3, before
    assert before["charter_status"] == CharterStatus.DRAFT

    adopted = adopt_charter(api, ctx.plan_id)

    assert_fields(
        adopted,
        charter_status=CharterStatus.ADOPTED,
        charter_adopted_quarter_index=0,
        documented_acceptance_count=3,
    )
    assert_version_bumped(before, adopted)

    for key in ("chair", "finance", "hr"):
        member = read_member(api, ctx.members[key]["id"])
        assert_fields(
            member,
            status=MemberStatus.ACTIVE,
            fiduciary_training_status=FiduciaryTrainingStatus.CURRENT,
        )
    # PRD 3.2: independence_flag is true exactly when affiliated_provider_role is NONE.
    assert read_member(api, ctx.members["hr"]["id"])["independence_flag"] is False
    assert read_member(api, ctx.members["chair"]["id"])["independence_flag"] is True


# --------------------------------------------------------------------------
# The derived plan surface
# --------------------------------------------------------------------------


def test_plan_read_reports_an_open_posture_and_an_untouched_capacity_triple(api, adopted_ips):
    """Once the charter is adopted, a policy statement is in force and three
    voting members are active, the plan reads OPEN with its whole capacity still
    available and no assets on the menu.

    Design: Corner/entities/plan_read_reports_open_posture_and_capacity_triple_after_ips_adoption
    """
    ctx = adopted_ips

    response = api.get(Paths.plan(ctx.plan_id), auditor_headers())
    plan = validate_success(response, 200)
    assert response.json()["response_type"] == "object", response.json()["response_type"]

    assert_fields(
        plan,
        charter_status=CharterStatus.ADOPTED,
        menu_posture=MenuPosture.OPEN,
        fee_disclosure_status=FeeDisclosureStatus.COMPLIANT,
        occupied_menu_slots=0,
        reserved_menu_slots=0,
        available_menu_slots=6,
        draft_proposal_count=0,
        total_plan_assets_cents=0,
        revenue_credit_balance_cents=0,
    )
    # PRD 2.11: the ratio is 0.0000 while no slot counts toward the denominator.
    assert_ratio(plan["at_risk_slot_ratio"], "0.0000", "at_risk_slot_ratio")
    assert_capacity_triple(plan, occupied=0, reserved=0, available=6)

    ips = validate_success(api.get(Paths.ips(ctx.ips_id), auditor_headers()))
    motion = read_motion(api, ctx.motions["ips"]["id"])
    assert_fields(
        ips,
        status=IpsStatus.ADOPTED,
        scoring_variant=ScoringVariant.TRAILING_PERIOD,
        approving_motion_id=motion["id"],
        adopted_quarter_index=0,
    )

    assert_fields(motion, status=MotionStatus.CARRIED, for_count=3)
    assert_ratio(motion["support_pct"], "100.0000", "support_pct")

    meeting = read_meeting(api, ctx.meetings["ips_meeting"]["id"])
    assert_fields(
        meeting, status=MeetingStatus.MINUTES_APPROVED, quorum_met=True
    )
