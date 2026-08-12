"""Mentorship and first-year check-ins: supersede cascade, ordered unique
markers, mentor rule ordering, completion gating, immutable check-in shape,
OCC on assignment creation, and mentor ownership."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_physician, create_case, get_case,
    create_active_mentor, create_mentorship, record_check_in,
    create_mentorship_payload, create_check_in_payload, setup_mentorship,
    make_mentor_headers, assert_check_in,
)

DIRECTOR = TEST_USERS["onboarding_director_headers"]


def _get_assignment(assignment_id):
    return get_success_data(api_client.get_mentorship_assignment(assignment_id, DIRECTOR))


def test_mentorship_supersede_leaves_single_active(api):
    """PRD §3.9: "At most one assignment is `ACTIVE` per case: creating a new one supersedes the previous `ACTIVE` assignment, moving it to `SUPERSEDED`."

    Design: Corner/state_machines/mentorship_supersede_leaves_single_active
    """
    physician = create_physician(full_name="Dr. Nan")
    case = create_case(physician["id"])
    mentor1 = create_active_mentor(full_name="Dr. Mentor1", email="m1@x.com")
    mentor2 = create_active_mentor(full_name="Dr. Mentor2", email="m2@x.com")

    ma1 = create_mentorship(case["id"], mentor1["id"])
    ma2 = create_mentorship(case["id"], mentor2["id"])
    assert ma2["status"] == "ACTIVE"
    assert _get_assignment(ma1["id"])["status"] == "SUPERSEDED", (
        "the prior assignment is superseded by cascade, not by an explicit action"
    )

    data = get_success_data(
        api_client.list_mentorship_assignments(
            DIRECTOR, params={"onboarding_case_id": case["id"], "status": "ACTIVE"}
        )
    )
    assert len(data) == 1
    assert data[0]["id"] == ma2["id"]


def test_mentorship_complete_after_five_ordered_checkins(api):
    """PRD §3.9: "Once all five markers are recorded, an `OnboardingDirector` may complete the assignment — it must be `ACTIVE` (else `ERR_MENTORSHIP_NOT_ACTIVE`), and completing before all five check-ins exist is rejected with `ERR_CHECKINS_INCOMPLETE` (HTTP 422) — moving it to `COMPLETED`."

    Design: Corner/state_machines/mentorship_complete_after_five_ordered_checkins
    """
    ctx = setup_mentorship(mentee_name="Dr. Ode")
    ma_id = ctx["assignment"]["id"]
    mentor_id = ctx["mentor"]["id"]
    record_check_in(ma_id, mentor_id, "D30", "POSITIVE")
    record_check_in(ma_id, mentor_id, "D90", "NEUTRAL")

    resp = api_client.complete_mentorship_assignment(ma_id, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_CHECKINS_INCOMPLETE)

    record_check_in(ma_id, mentor_id, "D180", "NEUTRAL")
    record_check_in(ma_id, mentor_id, "D270", "POSITIVE")
    record_check_in(ma_id, mentor_id, "D365", "POSITIVE")
    data = validate_success(api_client.complete_mentorship_assignment(ma_id, DIRECTOR), 200)
    assert data["status"] == "COMPLETED"
    assert data["checkins_recorded"] == 5


def test_checkin_duplicate_before_order_rule(api):
    """PRD §3.9: "Markers must be recorded strictly in ascending order and at most once each, and the two ordering failures are distinct and checked in a fixed sequence: a `day_marker` already present on the assignment is rejected with `ERR_CHECKIN_ALREADY_RECORDED` (HTTP 409), and only if the marker is new does the server check that it is the immediate next marker in the `D30`-through-`D365` sequence, rejecting a skip with `ERR_CHECKIN_OUT_OF_ORDER` (HTTP 422)."

    Design: Corner/validations/checkin_duplicate_before_order_rule
    """
    ctx = setup_mentorship(mentee_name="Dr. Xiu")
    ma_id = ctx["assignment"]["id"]
    mentor_id = ctx["mentor"]["id"]
    record_check_in(ma_id, mentor_id, "D30", "POSITIVE")
    headers = make_mentor_headers(mentor_id)

    resp = api_client.record_check_in(ma_id, create_check_in_payload("D180", "NEUTRAL"), headers)
    validate_error(resp, ApiErrorId.ERR_CHECKIN_OUT_OF_ORDER)

    resp = api_client.record_check_in(ma_id, create_check_in_payload("D30", "NEUTRAL"), headers)
    validate_error(resp, ApiErrorId.ERR_CHECKIN_ALREADY_RECORDED)

    validate_success(
        api_client.record_check_in(ma_id, create_check_in_payload("D90", "NEUTRAL"), headers), 201
    )
    assert _get_assignment(ma_id)["checkins_recorded"] == 2


def test_mentor_validation_order_trio(api):
    """PRD §3.9: "The mentor rules are pinned in a fixed evaluation order: first, the mentor may not be the mentee, else `ERR_MENTOR_IS_MENTEE` (HTTP 422); second, the `mentor_physician_id` must reference an `ACTIVE` physician — the pool the mark-active action of §3.1 feeds — else `ERR_MENTOR_NOT_ACTIVE_PHYSICIAN`; third, the mentor's specialty must match the mentee's, else `ERR_MENTOR_SPECIALTY_MISMATCH`."

    Design: Corner/validations/mentor_validation_order_trio
    """
    mentee = create_physician(full_name="Dr. Yao")
    case = create_case(mentee["id"])
    cand_idle = create_physician(
        full_name="Dr. Zed", hire_type="LEADERSHIP", email="zed2@x.com"
    )
    cand_card = create_physician(
        full_name="Dr. Card", specialty="CARDIOLOGY", hire_type="LEADERSHIP", email="card@x.com"
    )
    validate_success(api_client.mark_physician_active(cand_card["id"], DIRECTOR), 200)

    version = get_case(case["id"])["version"]

    resp = api_client.create_mentorship_assignment(
        create_mentorship_payload(case["id"], mentee["id"], version), DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_MENTOR_IS_MENTEE)

    resp = api_client.create_mentorship_assignment(
        create_mentorship_payload(case["id"], cand_idle["id"], version), DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_MENTOR_NOT_ACTIVE_PHYSICIAN)

    resp = api_client.create_mentorship_assignment(
        create_mentorship_payload(case["id"], cand_card["id"], version), DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_MENTOR_SPECIALTY_MISMATCH)

    data = get_success_data(
        api_client.list_mentorship_assignments(
            DIRECTOR, params={"onboarding_case_id": case["id"]}
        )
    )
    assert data == [], "rejected creates must not persist any assignment"


def test_checkin_immutable_shape_has_no_version(api):
    """PRD §2.5: "A CheckIn and a RetentionRiskSnapshot are point-in-time records: each carries only `id` and `created_at`, and both `updated_at` and `version` are absent from them."
    PRD §3.9: "the server stamps `occurred_on` from the logical clock at recording time."

    Design: Corner/entities/checkin_immutable_shape_has_no_version
    """
    ctx = setup_mentorship(mentee_name="Dr. Di")
    ma_id = ctx["assignment"]["id"]
    record_check_in(ma_id, ctx["mentor"]["id"], "D30", "POSITIVE")

    data = get_success_data(api_client.list_check_ins(ma_id, DIRECTOR))
    assert len(data) == 1
    check_in = data[0]
    assert check_in["day_marker"] == "D30"
    assert check_in["sentiment"] == "POSITIVE"
    assert check_in["mentorship_id"] == ma_id
    assert "occurred_on" in check_in
    assert_check_in(check_in)


def test_mentorship_create_stale_version_412(api):
    """PRD §2.8: "The mentorship-assignment creation endpoint (`POST /onboarding/mentorship-assignments`) applies the identical rule: the request must carry `expected_onboarding_case_version` matching the case's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.9: "At most one assignment is `ACTIVE` per case: creating a new one supersedes the previous `ACTIVE` assignment, moving it to `SUPERSEDED`."

    Design: Corner/cross_cutting_layers/mentorship_create_stale_version_412
    """
    physician = create_physician(full_name="Dr. Mia")
    case = create_case(physician["id"])
    m1 = create_active_mentor(full_name="Dr. M1", email="m1@x.com")
    m2 = create_active_mentor(full_name="Dr. M2", email="m2@x.com")

    stale_version = get_case(case["id"])["version"]
    ma1 = create_mentorship(case["id"], m1["id"])  # bumps the case version

    resp = api_client.create_mentorship_assignment(
        create_mentorship_payload(case["id"], m2["id"], stale_version), DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    fresh_version = get_case(case["id"])["version"]
    data = validate_success(
        api_client.create_mentorship_assignment(
            create_mentorship_payload(case["id"], m2["id"], fresh_version), DIRECTOR
        ),
        201,
    )
    assert data["status"] == "ACTIVE"
    assert _get_assignment(ma1["id"])["status"] == "SUPERSEDED"


def test_mentor_cannot_checkin_on_others_assignment(api):
    """PRD §2.1: "the caller may record check-ins only on mentorship assignments whose `mentor_physician_id` equals `X-User-ID`; a mentor touching another mentor's assignment is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/mentor_cannot_checkin_on_others_assignment
    """
    physician = create_physician(full_name="Dr. Kay")
    case = create_case(physician["id"])
    m1 = create_active_mentor(full_name="Dr. M1", email="m1@x.com")
    m2 = create_active_mentor(full_name="Dr. M2", email="m2@x.com")
    assignment = create_mentorship(case["id"], m1["id"])

    resp = api_client.record_check_in(
        assignment["id"],
        create_check_in_payload("D30", "POSITIVE"),
        make_mentor_headers(m2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert _get_assignment(assignment["id"])["checkins_recorded"] == 0
