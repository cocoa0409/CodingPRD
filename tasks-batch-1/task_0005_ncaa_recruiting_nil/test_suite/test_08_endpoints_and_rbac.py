"""Endpoint and RBAC claims: utilization variant default, listing filter
by status, sub-resource listing of Periods, coach-program mismatch on
withdraw, and authentication/authorization (PRD §2.1, §2.3, §3.1, §3.4,
§4).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_program, create_student_athlete, setup_certified_athlete,
    create_draft_offer, send_offer, create_period,
    set_clock, certify_athlete,
    make_coach_headers,
    create_program_payload,
    create_scholarship_offer_payload, send_scholarship_offer_payload,
    create_recruiting_contact_payload,
    TEST_USERS,
)


# ─── Corner: endpoints ─────────────────────────────────


def test_list_scholarship_offers_filtered_by_status_returns_only_sent(api):
    """PRD §3.4: "List endpoints for offers are filterable by `program_id`,
    `student_athlete_id`, and `status`."

    Design: Corner/endpoints/list_offers_filtered_by_status
    """
    program = create_program(sport_code="MBB", school_name="Filter U", scholarship_slot_cap=13)
    athlete_a = setup_certified_athlete(sport_code="MBB", full_name="AA")
    athlete_b = setup_certified_athlete(sport_code="MBB", full_name="BB", gpa=3.400)

    # Athlete A: SENT offer
    oa = create_draft_offer(program["id"], athlete_a["id"], annual_value_cents=3_000_000)
    send_offer(oa["id"], program["version"])

    # Athlete B: DRAFT offer
    create_draft_offer(program["id"], athlete_b["id"], annual_value_cents=3_000_000)

    res = api.list_scholarship_offers(
        TEST_USERS["compliance_officer_headers"],
        params={"status": "SENT", "program_id": program["id"]},
    )
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert all(o["status"] == "SENT" for o in data)


def test_utilization_endpoint_default_variant_is_base(api):
    """PRD §3.4: "The `base` variant — which is the default if `variant`
    is omitted — produces `slots_committed`"
    PRD §3.4: "The utilization read returns `program_id`, `variant`,
    `slot_count`, and `scholarship_slot_cap`."

    Design: Corner/endpoints/utilization_endpoint_default_variant_is_base
    """
    program = create_program(sport_code="FOOTBALL", school_name="Default U",
                             scholarship_slot_cap=85)
    res = api.get_program_utilization(
        program["id"], TEST_USERS["coach_headers"],
        params=None,
    )
    data = validate_success(res, 200)
    assert data["variant"] == "base"
    assert data["slot_count"] == 0
    assert data["scholarship_slot_cap"] == 85
    assert data["program_id"] == program["id"]


def test_list_periods_for_program(api):
    """PRD §3.1: "A coach may inspect the existing calendar before
    logging a contact, and the system exposes per-program list and read
    endpoints for periods filterable by `period_type`."

    Design: Corner/endpoints/period_list_for_program_sub_resource
    """
    program = create_program(sport_code="BASEBALL", school_name="Cal U", scholarship_slot_cap=11)
    create_period(program["id"], period_type="CONTACT",
                  starts_at="2026-12-01T00:00:00Z", ends_at="2026-12-05T00:00:00Z")
    create_period(program["id"], period_type="QUIET",
                  starts_at="2026-12-05T00:00:00Z", ends_at="2026-12-10T00:00:00Z")

    res = api.list_periods(program["id"], TEST_USERS["compliance_officer_headers"])
    data, meta = validate_paginated(res)
    assert len(data) == 2
    assert meta["total_count"] == 2


# ─── Corner: errors / RBAC ─────────────────────────────


def test_coach_program_mismatch_on_withdraw(api):
    """PRD §2.1: "later coach-driven transitions on that offer require
    the acting `X-User-ID` to match the `X-User-ID` that stamped the
    offer (i.e. the coach must belong to `offer.program_id`), and a
    mismatch is rejected with `ERR_COACH_PROGRAM_MISMATCH`."

    Design: Corner/errors/error_coach_program_mismatch_on_withdraw
    """
    # Create program, a CONTACT period spanning the action window, and the
    # offer is created by coach_x; coach_y attempts to withdraw.
    program = create_program(sport_code="FOOTBALL", school_name="Mismatch U",
                             scholarship_slot_cap=85)
    create_period(program["id"], period_type="CONTACT",
                  starts_at="2026-05-01T00:00:00Z", ends_at="2026-05-31T00:00:00Z")
    set_clock("2026-05-10T00:00:00Z")
    athlete = setup_certified_athlete(sport_code="FOOTBALL", full_name="K")

    # Log a contact under coach_x.
    validate_success(api.create_recruiting_contact(
        create_recruiting_contact_payload(
            program_id=program["id"],
            student_athlete_id=athlete["id"],
            coach_user_id="coach_x",
            contact_at="2026-05-10T12:00:00Z",
            channel="IN_PERSON",
        ),
        make_coach_headers("coach_x"),
    ), 201)

    # coach_x creates and sends an offer.
    offer = validate_success(api.create_scholarship_offer(
        create_scholarship_offer_payload(
            program_id=program["id"],
            student_athlete_id=athlete["id"],
            annual_value_cents=4_000_000,
        ),
        make_coach_headers("coach_x"),
    ), 201)
    validate_success(api.send_scholarship_offer(
        offer["id"],
        send_scholarship_offer_payload(expected_program_version=program["version"]),
        make_coach_headers("coach_x"),
    ), 200)

    # coach_y attempts to withdraw.
    res = api.withdraw_scholarship_offer(
        offer["id"], make_coach_headers("coach_y"),
    )
    validate_error(res, ApiErrorId.ERR_COACH_PROGRAM_MISMATCH.value)


def test_coach_cannot_create_program(api):
    """PRD §2.1: "A request whose role is not on the authorization list
    for the targeted endpoint is rejected with `ERR_UNAUTHORIZED` (403)."
    PRD §4: "POST `/ncaa/programs` ... Authorized Role(s):
    ComplianceOfficer"

    Design: Corner/rbac/rbac_coach_cannot_create_program
    """
    res = api.create_program(
        create_program_payload(
            sport_code="FOOTBALL", school_name="Denied U", scholarship_slot_cap=85,
        ),
        make_coach_headers("coach_y"),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    which identifies the acting user, and `X-User-Role`, which declares
    the operational capacity under which they are acting. A request
    missing either header is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/rbac_unauthenticated_request_rejected
    """
    # Pass an empty header dict — neither X-User-ID nor X-User-Role is set.
    res = api.list_programs({})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_eligibility_center_cannot_send_scholarship_offer(api):
    """PRD §2.1: "A request whose role is not on the authorization list
    for the targeted endpoint is rejected with `ERR_UNAUTHORIZED` (403)."
    PRD §4: "POST `/ncaa/scholarship-offers/{id}/send` ... Authorized
    Role(s): Coach"

    Design: Corner/rbac/rbac_eligibilitycenter_cannot_send_offer
    """
    program = create_program(sport_code="FOOTBALL", school_name="RBAC U",
                             scholarship_slot_cap=85)
    athlete = create_student_athlete(sport_code="FOOTBALL", full_name="M")
    offer = create_draft_offer(
        program["id"], athlete["id"], annual_value_cents=4_000_000,
    )

    res = api.send_scholarship_offer(
        offer["id"],
        send_scholarship_offer_payload(expected_program_version=program["version"]),
        TEST_USERS["eligibility_center_headers"],
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)
