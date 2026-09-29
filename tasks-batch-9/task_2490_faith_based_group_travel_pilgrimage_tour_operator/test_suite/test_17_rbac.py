"""Who may act: the 401 that precedes every authorisation question, four roles
reaching for operations that are not theirs, a leader working inside and outside
their own agreement, and the two segregation-of-duties pairs."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    air_block_payload,
    api_client,
    assign_room,
    active_agreement,
    deposited_traveler,
    enrol_traveler,
    offer_agreement,
    open_departure,
    pay,
    pilgrim_payload,
    program_with_departure,
    quote_protection,
    read_agreement,
    read_departure,
    read_protection,
    read_traveler,
    review_protection,
    validate_error,
    validate_paginated,
    validate_success,
    make_group_leader_headers,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]
AIR_DESK = TEST_USERS["air_desk_agent"]
LAND = TEST_USERS["land_contractor"]
FINANCE = TEST_USERS["finance_controller"]
PROTECTION_REVIEWER = TEST_USERS["protection_reviewer"]


def test_a_read_with_no_role_header_is_unauthenticated_not_unauthorized(api):
    """PRD §2.9: "1. **Authentication** — a missing, empty or unrecognised
    `X-User-Role` yields `ERR_UNAUTHENTICATED` (401). This applies to every
    endpoint without exception, including read endpoints and the clock-control
    capability." That band sits above the next one: "2. **Authorization** — a
    recognised role that is not listed on the addressed operation, or a
    `GroupLeader` reaching outside their own agreement, yields
    `ERR_UNAUTHORIZED` (403). This too applies to every endpoint."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    # An identifier alone, with no role claimed: nothing to authorise yet.
    response = api_client.list_departures({"X-User-ID": "u-program-manager-1"})

    validate_error(response, ApiErrorId.UNAUTHENTICATED.value)


def test_the_air_desk_may_not_confirm_a_traveler_for_travel(api):
    """PRD §4 lists confirmation as `POST` `/pilgrims/{pilgrimId}/confirm`,
    "Confirm a deposited traveler for travel; gated on the departure's risk
    posture, on senior protection, and on there being no unratified itinerary
    modification.", permitted to `ProgramManager`. PRD §2.9: "2.
    **Authorization** — a recognised role that is not listed on the addressed
    operation, or a `GroupLeader` reaching outside their own agreement, yields
    `ERR_UNAUTHORIZED` (403). This too applies to every endpoint." Confirmation
    is the only writer of the frozen price, per §3.5: "Confirmation freezes
    `price_locked_cents` at the departure's current
    `provisional_per_pax_price_cents`, recomputes `invoice_total_cents`,
    recomputes the departure's `paying_pax_count` and provisional tier fields,
    and recomputes the recruiting agreement's snapshot accrual."

    Design: Corner/rbac/air_desk_agent_cannot_confirm_a_traveler
    """
    stage = open_departure()
    traveler = deposited_traveler(
        stage["departure"]["id"],
        full_name="Deposited Traveler",
        date_of_birth="1975-01-10",
    )
    assert traveler["booking_status"] == "DEPOSITED"

    response = api_client.confirm_pilgrim(traveler["id"], AIR_DESK)
    validate_error(response, ApiErrorId.UNAUTHORIZED.value)

    refused = read_traveler(traveler["id"])
    assert refused["booking_status"] == "DEPOSITED"
    # Never confirmed, so the price was never frozen.
    assert refused["price_locked_cents"] is None


def test_a_land_contractor_may_not_open_an_air_block(api):
    """PRD §4 lists `POST` `/air-blocks`, "Open an air block negotiation with a
    carrier for a departure, in DRAFT.", permitted to `AirDeskAgent`. PRD §2.9:
    "2. **Authorization** — a recognised role that is not listed on the addressed
    operation, or a `GroupLeader` reaching outside their own agreement, yields
    `ERR_UNAUTHORIZED` (403). This too applies to every endpoint."

    Design: Corner/rbac/land_contractor_cannot_open_an_air_block
    """
    _program, departure = program_with_departure()

    response = api_client.create_air_block(air_block_payload(departure["id"]), LAND)
    validate_error(response, ApiErrorId.UNAUTHORIZED.value)

    # The refusal wrote nothing: the departure has no block to negotiate.
    rows, meta = validate_paginated(
        api_client.list_air_blocks(AIR_DESK, {"departure_id": departure["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_finance_may_not_countersign_a_leader_agreement(api):
    """PRD §3.4: "Only the leader themself may accept. Countersigning moves
    `PENDING_COUNTERSIGN` to `ACTIVE` and is performed under the `GroupLeader`
    role, whose `X-User-ID` must equal the agreement's own `id`; countersigning
    from any other state is `ERR_AGREEMENT_INVALID_STATE`." PRD §4 lists `POST`
    `/group-leader-agreements/{agreementId}/countersign`, "Leader accepts the
    agreement, activating recruitment credit.", permitted to `GroupLeader`, and
    §2.9 puts that band above every state rule: "2. **Authorization** — a
    recognised role that is not listed on the addressed operation, or a
    `GroupLeader` reaching outside their own agreement, yields
    `ERR_UNAUTHORIZED` (403). This too applies to every endpoint."

    Design: Corner/rbac/finance_controller_cannot_countersign_a_leader_agreement
    """
    _program, departure = program_with_departure()
    agreement = offer_agreement(
        departure["id"],
        leader_name="Fr. Alonso Reyes",
        leader_user_id="u-leader-alonso",
        commission_mode="PER_PAX_CASH",
    )
    assert agreement["status"] == "PENDING_COUNTERSIGN"

    response = api_client.countersign_agreement(agreement["id"], FINANCE)
    validate_error(response, ApiErrorId.UNAUTHORIZED.value)

    assert read_agreement(agreement["id"])["status"] == "PENDING_COUNTERSIGN"


def test_a_leader_may_not_read_a_traveler_recruited_by_another_leader(api):
    """PRD §2.1: "When `X-User-Role` is `GroupLeader`, `X-User-ID` is the `id` of
    the acting `GroupLeaderAgreement`; ownership checks on any resource that
    references a group leader agreement compare the resource's agreement
    reference to `X-User-ID`. Concretely, a `GroupLeader` may countersign only
    the agreement whose `id` equals their `X-User-ID`, may read only that
    agreement, and may read or create only travelers whose
    `recruited_by_agreement_id` equals their `X-User-ID`. A `GroupLeader` who
    addresses another leader's agreement or another leader's traveler is rejected
    with `ERR_UNAUTHORIZED`, exactly as if the role were not listed on the
    endpoint at all; the same code answers a `GroupLeader` whose `X-User-ID` does
    not identify any stored agreement."

    Design: Corner/rbac/group_leader_cannot_read_another_leaders_traveler
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    # Two distinct leaders on one departure: different `leader_user_id`, so
    # neither agreement supersedes the other.
    agreement_a = active_agreement(
        departure_id, leader_name="Fr. Alonso Reyes", leader_user_id="u-leader-alonso"
    )
    agreement_b = active_agreement(
        departure_id, leader_name="Fr. Bruno Neri", leader_user_id="u-leader-bruno"
    )
    recruit = enrol_traveler(
        departure_id,
        full_name="Alonso Recruit",
        date_of_birth="1975-01-10",
        recruited_by_agreement_id=agreement_a["id"],
    )
    # The owning leader reads their own recruit without difficulty.
    own = validate_success(
        api_client.get_pilgrim(recruit["id"], make_group_leader_headers(agreement_a["id"]))
    )
    assert own["recruited_by_agreement_id"] == agreement_a["id"]

    response = api_client.get_pilgrim(
        recruit["id"], make_group_leader_headers(agreement_b["id"])
    )
    validate_error(response, ApiErrorId.UNAUTHORIZED.value)

    assert read_agreement(agreement_a["id"])["status"] == "ACTIVE"
    assert read_agreement(agreement_b["id"])["status"] == "ACTIVE"


def test_a_leader_books_a_recruit_under_their_own_agreement(api):
    """PRD §2.1: "Concretely, a `GroupLeader` may countersign only the agreement
    whose `id` equals their `X-User-ID`, may read only that agreement, and may
    read or create only travelers whose `recruited_by_agreement_id` equals their
    `X-User-ID`." PRD §3.5: "Enrolment is performed by a `ProgramManager` or by
    the recruiting `GroupLeader`, and carries the `departure_id` being booked, a
    `full_name` of 1 to 120 characters as it will appear on documents, a
    `date_of_birth` in `YYYY-MM-DD` form that must be a valid ISO date strictly
    before the departure's `departure_date`, a `room_type_requested` of `SINGLE`,
    `DOUBLE` or `TWIN`, optionally a `recruited_by_agreement_id` naming the
    recruiting leader agreement (absent for a direct booking), optionally a
    `mobility_code` of `NONE`, `CANE`, `WALKER` or `WHEELCHAIR` defaulting to
    `NONE`, optionally `is_free_seat_grant` defaulting to false to mark the
    booking as a leader's free-travel seat rather than a paying booking, and
    optionally `risk_acknowledged` defaulting to false to record that the
    traveler signed the elevated-risk acknowledgement." And: "A successful
    enrolment writes `booking_status` `INQUIRY`, `payment_status` `UNPAID` and
    `protection_status` `NONE`; sets `is_paying` to the logical negation of
    `is_free_seat_grant`; computes `age_at_departure` as the number of complete
    years between `date_of_birth` and the departure's `departure_date`, floored,
    so a traveler whose birthday falls the day after departure is one year
    younger for every purpose in this system; increments the recruiting
    agreement's `free_seats_granted_count` when the booking is a free seat; and
    recomputes both the departure's provisional tier snapshot and the recruiting
    agreement's snapshot accrual."

    Design: Corner/rbac/group_leader_enrols_a_traveler_under_their_own_agreement
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    agreement = active_agreement(
        departure_id, leader_name="Fr. Alonso Reyes", leader_user_id="u-leader-alonso"
    )

    created = validate_success(
        api_client.create_pilgrim(
            pilgrim_payload(
                departure_id,
                full_name="Leader Recruit",
                date_of_birth="1975-01-10",
                room_type_requested="DOUBLE",
                recruited_by_agreement_id=agreement["id"],
            ),
            make_group_leader_headers(agreement["id"]),
        ),
        201,
    )

    assert created["recruited_by_agreement_id"] == agreement["id"]
    assert created["booking_status"] == "INQUIRY"
    assert created["is_paying"] is True
    assert created["is_free_seat_grant"] is False
    # An inquiry is not yet a paying head, so no accrual and no tier movement.
    assert read_agreement(agreement["id"])["recruited_paying_count"] == 0
    assert read_departure(departure_id)["paying_pax_count"] == 0


def test_the_officer_who_proposed_a_modification_may_not_ratify_it(api):
    """PRD §3.9: "Proposing sets `pending_modification_required` true, copies the
    reason into `pending_modification_reason`, stamps
    `pending_modification_proposed_by_user_id` with the acting `X-User-ID`,
    copies the delta into `pending_modification_cost_delta_cents`, and increments
    the departure's `version`." And: "Ratification requires
    `pending_modification_required` to be true, failing which — nothing was
    proposed, or the previous proposal was already ratified — the answer is
    `ERR_NO_PENDING_MODIFICATION` (HTTP 409); and it requires the acting
    `X-User-ID` to differ from `pending_modification_proposed_by_user_id`,
    failing which the answer is `ERR_SEGREGATION_OF_DUTIES`." And: "Ratification
    adds `pending_modification_cost_delta_cents` to the departure's cumulative
    `itinerary_cost_delta_cents`, increments `ratified_modification_count` by 1,
    clears `pending_modification_required` to false with
    `pending_modification_reason` and `pending_modification_proposed_by_user_id`
    returned to unset and `pending_modification_cost_delta_cents` returned to 0,
    recomputes the departure's `land_cost_total_cents`, and increments the
    departure's `version`."

    Design: Corner/rbac/ratifying_your_own_itinerary_modification_rejected
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    proposed = validate_success(
        api_client.propose_itinerary_modification(
            departure_id,
            {
                "modification_reason": "Coach swap after the operator withdrew a lift-equipped vehicle",
                "cost_delta_cents": 180_000,
            },
            PLANNER,
        )
    )
    assert proposed["pending_modification_required"] is True
    assert proposed["pending_modification_proposed_by_user_id"] == "u-program-manager-1"

    # The very same `X-User-ID` comes back to ratify their own proposal.
    response = api_client.ratify_itinerary_modification(departure_id, PLANNER)
    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value)

    live = read_departure(departure_id)
    assert live["pending_modification_required"] is True
    assert live["pending_modification_cost_delta_cents"] == 180_000
    assert live["ratified_modification_count"] == 0
    assert live["itinerary_cost_delta_cents"] == 0


def test_the_administrator_who_recorded_the_review_may_not_decide_the_waiver(api):
    """PRD §3.8: "The call writes `questionnaire_complete` and
    `stable_period_days`, stamps `medical_review_by_user_id` with the acting
    `X-User-ID`, re-derives `waiver_eligible` and re-quotes the premium." And:
    "The waiver decision carries a `decision` of `APPROVE` or `DECLINE`, requires
    the record to be in `MEDICAL_REVIEWED`, and requires the acting `X-User-ID`
    to differ from the stored `medical_review_by_user_id`, failing which the
    answer is `ERR_SEGREGATION_OF_DUTIES`." Eligibility is derived from the
    deposit anchor: "Otherwise it is true only when all three of the following
    hold: `questionnaire_complete` is true; `stable_period_days` is 60 or
    greater; and the whole-day difference between the logical clock's calendar
    date and `deposit_reference_date` is 21 days or fewer."

    Design: Corner/rbac/deciding_a_waiver_you_medically_reviewed_rejected
    """
    stage = open_departure()
    traveler = enrol_traveler(
        stage["departure"]["id"],
        full_name="Waiver Applicant",
        date_of_birth="1948-06-20",
        room_type_requested="DOUBLE",
    )
    assign_room(
        traveler["id"],
        room_type_assigned="DOUBLE",
        room_label="IL-223",
        ground_floor=True,
    )
    protection = quote_protection(
        traveler["id"],
        plan_code="PREMIER",
        medical_limit_cents=1_000_000,
        pre_existing_waiver_requested=True,
    )
    # The deposit-crossing receipt is what stamps the anchor the waiver needs.
    pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
    reviewed = review_protection(
        protection["id"],
        headers=PROTECTION_REVIEWER,
        questionnaire_complete=True,
        stable_period_days=90,
    )
    assert reviewed["status"] == "MEDICAL_REVIEWED"
    assert reviewed["medical_review_by_user_id"] == "u-prot-reviewer"
    assert reviewed["waiver_eligible"] is True

    response = api_client.decide_waiver(
        protection["id"], {"decision": "APPROVE"}, PROTECTION_REVIEWER
    )
    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value)

    still_open = read_protection(protection["id"])
    assert still_open["status"] == "MEDICAL_REVIEWED"
    assert still_open["medical_review_by_user_id"] == "u-prot-reviewer"
    assert still_open["waiver_eligible"] is True
