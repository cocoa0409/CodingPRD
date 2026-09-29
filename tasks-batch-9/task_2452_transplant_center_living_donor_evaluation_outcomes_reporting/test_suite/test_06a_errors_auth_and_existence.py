"""The catalogue's authentication, shape and existence codes, one request each."""
from test_helpers import (
    NON_EXISTENT_UUID,
    add_operating_room,
    add_segment,
    create_chain,
    create_donor,
    create_offer_payload,
    create_program,
    create_recipient,
    follow_up_fields,
    get_donor,
    make_program_admin_headers,
    refresh_program,
    setup_paired_loop_participants,
    setup_program_with_staff,
    submit_medical_evaluation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId


def _chain_with_one_segment(env):
    chain = create_chain(env, "PAIRED_LOOP")
    segment = add_segment(
        env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"]
    )
    return chain, segment


def test_err_missing_auth_header_returns_401():
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting
    principal, and `X-User-Role`, naming the role that principal is acting in."
    PRD §2.1: "If either header is absent or empty, the request is rejected with
    `ERR_MISSING_AUTH_HEADER` (HTTP 401) before anything else is examined."
    PRD §2.10: "Both `X-User-ID` and `X-User-Role` are present and non-empty —
    `ERR_MISSING_AUTH_HEADER`, 401."
    PRD §3.1: "Adding a person to the center requires the owning `program_id`, a
    `full_name`, a `staff_role` drawn from the five credentialed duties, and an `npi`
    national provider identifier; `is_active` is optional and defaults to true."

    Design: Corner/errors/err_missing_auth_header_returns_401
    """
    program = create_program(name="Northlake Transplant Center", center_code="NLT-01")
    body = {
        "program_id": program["id"],
        "full_name": "Coordinator One",
        "staff_role": "TRANSPLANT_COORDINATOR",
        "npi": "1000000001",
    }

    response = api_client.create_staff_member(body, {})

    validate_error(
        response, ApiErrorId.ERR_MISSING_AUTH_HEADER.value, expected_status=401
    )

    rows, meta = validate_paginated(
        api_client.list_program_staff_members(
            program["id"], make_program_admin_headers()
        )
    )
    assert rows == []
    assert meta["total_count"] == 0, "an otherwise valid body still created nothing"


def test_err_unauthorized_returns_403():
    """PRD §2.1: "If the header names a role that is not one of the six declared roles, or
    names a role that the target endpoint does not authorize, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.10: "`X-User-Role` names a declared role that the endpoint authorizes, and for
    an entity-backed role `X-User-ID` is an active staff member with the matching
    `staff_role` — `ERR_UNAUTHORIZED`, 403."
    PRD §2.1: "Write endpoints are narrowly scoped: `ProgramAdmin` alone configures
    programs, staff, rooms, advocate assignments, follow-up waivers, improvement-plan
    decisions and the logical clock; `TransplantCoordinator` alone drives candidacy, donor
    referral, chain construction, offers, theatre bookings, follow-up submissions and
    cost-claim filing; `DonorAdvocate` alone runs consent disclosure and the advocacy
    determination; `EvaluationReviewer` alone submits, determines and resubmits donor
    evaluations; `QualityOfficer` alone creates and finalizes outcome reviews and files
    improvement plans; `FinanceAdmin` alone adjudicates and reverses cost claims."

    Design: Corner/errors/err_unauthorized_returns_403
    """
    env = setup_program_with_staff()

    response = api_client.create_staff_member(
        {
            "program_id": env["program_id"],
            "full_name": "Coordinator Two",
            "staff_role": "TRANSPLANT_COORDINATOR",
            "npi": "1000000010",
        },
        env["coordinator_headers"],
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    _rows, meta = validate_paginated(
        api_client.list_program_staff_members(
            env["program_id"],
            env["admin_headers"],
            params={"staff_role": "TRANSPLANT_COORDINATOR"},
        )
    )
    assert meta["total_count"] == 1, "the coordinator could not clone itself"


def test_err_not_assigned_advocate_returns_403():
    """PRD §2.1: "In addition, for any operation on a donor candidate the header value must
    equal that donor's `advocate_staff_id`; if it names a different staff member the request
    fails with `ERR_NOT_ASSIGNED_ADVOCATE` (HTTP 403)."
    PRD §2.10: "Resource-scoped actor binding: `X-User-ID` equals the donor's
    `advocate_staff_id` for consent disclosure and the advocacy determination, and equals
    the evaluation's `reviewer_staff_id` for an evaluation determination and resubmission —
    `ERR_NOT_ASSIGNED_ADVOCATE` or `ERR_NOT_ASSIGNED_REVIEWER`, 403."
    PRD §3.3: "It advances `disclosure_sequence` by 1, sets `disclosure_at` to the current
    logical clock, and re-derives `cooling_off_ends_at`."

    Design: Corner/errors/err_not_assigned_advocate_returns_403
    """
    from test_helpers import add_staff_member, make_advocate_headers

    env = setup_program_with_staff()
    donor = create_donor(env, mrn="D-001", age_years=41)
    other = add_staff_member(
        env["program_id"], "LIVING_DONOR_ADVOCATE", "1000000011", "Advocate Two"
    )

    response = api_client.record_consent_disclosure(
        donor["id"], make_advocate_headers(other["id"])
    )

    validate_error(
        response, ApiErrorId.ERR_NOT_ASSIGNED_ADVOCATE.value, expected_status=403
    )

    after = get_donor(env, donor["id"])
    assert after["advocacy_status"] == "ASSIGNED"
    assert after["disclosure_at"] is None
    assert after["disclosure_sequence"] == 0


def test_err_not_assigned_reviewer_returns_403():
    """PRD §2.1: "For any operation on an existing evaluation the header value must equal
    that evaluation's `reviewer_staff_id`; if it names a different staff member the request
    fails with `ERR_NOT_ASSIGNED_REVIEWER` (HTTP 403)."
    PRD §2.10: "Resource-scoped actor binding: `X-User-ID` equals the donor's
    `advocate_staff_id` for consent disclosure and the advocacy determination, and equals
    the evaluation's `reviewer_staff_id` for an evaluation determination and resubmission —
    `ERR_NOT_ASSIGNED_ADVOCATE` or `ERR_NOT_ASSIGNED_REVIEWER`, 403."
    PRD §3.4: "Every determination stamps `determined_at` with the current logical clock
    and increments the evaluation's `version` by 1."

    Design: Corner/errors/err_not_assigned_reviewer_returns_403
    """
    env = setup_program_with_staff()
    donor = create_donor(env, mrn="D-001", age_years=41)
    evaluation = submit_medical_evaluation(env, donor["id"])
    assert evaluation["reviewer_staff_id"] == env["reviewer_med"]["id"]

    response = api_client.record_evaluation_determination(
        evaluation["id"], {"outcome": "CLEARED"}, env["reviewer_psy_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_NOT_ASSIGNED_REVIEWER.value, expected_status=403
    )

    reread = validate_success(
        api_client.get_donor_evaluation(evaluation["id"], env["reviewer_med_headers"])
    )
    assert reread["status"] == "SUBMITTED"
    assert reread["determined_at"] is None
    assert get_donor(env, donor["id"])["medical_status"] == "PENDING"


def test_err_validation_returns_400():
    """PRD §2.10: "Request shape, as specified in §2.6 — `ERR_VALIDATION`, 400."
    PRD §2.6: "Request-shape validation, reported as `ERR_VALIDATION` (HTTP 400), covers a
    fixed list of conditions: every input field that has no default must be present; every
    enum-typed field must hold a declared member; integers and numbers must be of the right
    type and inside their declared range; cents-denominated fields must be non-negative
    integers; datetimes must be ISO 8601 UTC; `end_at` must be later than `start_at`,
    `period_end_on` must not precede `period_start_on`, and `service_to_on` must not
    precede `service_from_on`; `lost_wage_days` must be present and at least 1 exactly when
    `claim_type` is `LOST_WAGES` and must be absent otherwise; a reason code that a
    transition requires must be present — this covers `objection_reason_code`,
    `decline_reason_code`, `break_reason_code`, `waiver_reason_code`,
    `decision_reason_code` and `reversal_reason_code`; `limit` must lie in the inclusive
    range 1 to 100 and `offset` must be at least 0; and `observed_survivor_count` must not
    exceed `cohort_size`."
    PRD §3.2: "A coordinator opens a recipient workup by supplying the owning `program_id`,
    the patient's `mrn`, an `abo_blood_type` of `O`, `A`, `B` or `AB`, an `age_years` value
    of at least 0, and a `cpra` calculated panel reactive antibody fraction between 0 and 1
    inclusive."

    Design: Corner/errors/err_validation_returns_400
    """
    env = setup_program_with_staff()

    response = api_client.create_recipient_candidate(
        {
            "program_id": env["program_id"],
            "mrn": "R-001",
            "abo_blood_type": "A",
            "age_years": 44,
            "cpra": 1.5,
        },
        env["coordinator_headers"],
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, expected_status=400)

    _rows, meta = validate_paginated(
        api_client.list_recipient_candidates(
            env["coordinator_headers"], params={"program_id": env["program_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_err_program_not_found_returns_404():
    """PRD §2.5: "The same codes cover foreign keys supplied in a request body rather than
    in the path."
    PRD §2.5: "Every reference — `program_id`, `intended_recipient_id`,
    `referred_by_staff_id`, `advocate_staff_id`, `donor_candidate_id`,
    `recipient_candidate_id`, `reviewer_staff_id`, `exchange_chain_id`,
    `predecessor_segment_id`, `operating_room_id`, `chain_segment_id`, `surgeon_staff_id`
    and `program_outcome_review_id` — must resolve to an existing row, and the failure
    reports the not-found code of the entity type that reference points at."
    PRD §2.10: "Every foreign key supplied in the request body exists — the matching
    not-found code, 404."

    Design: Corner/errors/err_program_not_found_returns_404
    """
    env = setup_program_with_staff()

    response = api_client.create_recipient_candidate(
        {
            "program_id": NON_EXISTENT_UUID,
            "mrn": "R-001",
            "abo_blood_type": "A",
            "age_years": 44,
            "cpra": 0.1,
        },
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value, expected_status=404
    )

    _rows, meta = validate_paginated(
        api_client.list_recipient_candidates(
            env["coordinator_headers"], params={"program_id": env["program_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_err_staff_not_found_returns_404():
    """PRD §2.5: "The thirteen not-found codes are `ERR_PROGRAM_NOT_FOUND`,
    `ERR_STAFF_NOT_FOUND`, `ERR_RECIPIENT_NOT_FOUND`, `ERR_DONOR_NOT_FOUND`,
    `ERR_EVALUATION_NOT_FOUND`, `ERR_CHAIN_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`,
    `ERR_ROOM_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_FOLLOW_UP_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_PLAN_NOT_FOUND` and `ERR_CLAIM_NOT_FOUND`, each returned
    with HTTP 404."
    PRD §2.10: "Every foreign key supplied in the request body exists — the matching
    not-found code, 404."
    PRD §3.3: "A `ProgramAdmin` assigns the advocate by supplying an `advocate_staff_id`,
    moving `advocacy_status` from `UNASSIGNED` to `ASSIGNED` and recording the staff member
    on the donor."

    Design: Corner/errors/err_staff_not_found_returns_404
    """
    env = setup_program_with_staff()
    donor = create_donor(env, assign_advocate=False, mrn="D-001", age_years=41)
    assert donor["advocacy_status"] == "UNASSIGNED"

    response = api_client.assign_advocate(
        donor["id"], {"advocate_staff_id": NON_EXISTENT_UUID}, env["admin_headers"]
    )

    validate_error(response, ApiErrorId.ERR_STAFF_NOT_FOUND.value, expected_status=404)

    after = get_donor(env, donor["id"])
    assert after["advocacy_status"] == "UNASSIGNED"
    assert after["advocate_staff_id"] is None


def test_err_recipient_not_found_returns_404():
    """PRD §2.5: "Path identifiers are resolved strictly left to right, in this order:
    program, then staff member, then recipient, then donor, then evaluation, then chain,
    then segment, then room, then booking, then follow-up, then review, then plan, then
    claim."
    PRD §2.10: "Every identifier in the path exists, resolved left to right — the matching
    not-found code, 404."
    PRD §3.2: "Candidates are listed with optional `program_id`, `listing_status` and
    `candidacy_approved_by_staff_id` filters plus `limit` and `offset`, and read
    individually to expose `active_days_total`, `waitlist_priority_score` and
    `offer_decline_count`."

    Design: Corner/errors/err_recipient_not_found_returns_404
    """
    env = setup_program_with_staff()

    response = api_client.get_recipient_candidate(
        NON_EXISTENT_UUID, env["coordinator_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_RECIPIENT_NOT_FOUND.value, expected_status=404
    )

    rows, meta = validate_paginated(
        api_client.list_recipient_candidates(
            env["coordinator_headers"], params={"program_id": env["program_id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_err_donor_not_found_returns_404():
    """PRD §2.5: "The first identifier that resolves to nothing determines the error, so a
    request naming a real program and a fictional chain reports the chain failure and not
    the other way round."
    PRD §2.10: "Every identifier in the path exists, resolved left to right — the matching
    not-found code, 404."
    PRD §3.3: "Donor candidates are listed with optional `program_id`,
    `intended_recipient_id`, `referred_by_staff_id`, `advocate_staff_id` and
    `overall_status` filters plus `limit` and `offset`; reading one exposes all four state
    dimensions, both risk indices and `cooling_off_ends_at`."

    Design: Corner/errors/err_donor_not_found_returns_404
    """
    env = setup_program_with_staff()

    response = api_client.get_donor_candidate(
        NON_EXISTENT_UUID, env["coordinator_headers"]
    )

    validate_error(response, ApiErrorId.ERR_DONOR_NOT_FOUND.value, expected_status=404)

    rows, meta = validate_paginated(
        api_client.list_donor_candidates(
            env["coordinator_headers"], params={"program_id": env["program_id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_err_evaluation_not_found_returns_404():
    """PRD §2.5: "The thirteen not-found codes are `ERR_PROGRAM_NOT_FOUND`,
    `ERR_STAFF_NOT_FOUND`, `ERR_RECIPIENT_NOT_FOUND`, `ERR_DONOR_NOT_FOUND`,
    `ERR_EVALUATION_NOT_FOUND`, `ERR_CHAIN_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`,
    `ERR_ROOM_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_FOLLOW_UP_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_PLAN_NOT_FOUND` and `ERR_CLAIM_NOT_FOUND`, each returned
    with HTTP 404."
    PRD §2.10: "Every identifier in the path exists, resolved left to right — the matching
    not-found code, 404."
    PRD §3.4: "Evaluations are listed with optional `donor_candidate_id`,
    `reviewer_staff_id`, `domain` and `status` filters plus `limit` and `offset`, and read
    individually to expose `exclusion_codes`, `hard_exclusion_count`, `risk_points` and
    `submission_count`."

    Design: Corner/errors/err_evaluation_not_found_returns_404
    """
    env = setup_program_with_staff()

    response = api_client.record_evaluation_determination(
        NON_EXISTENT_UUID, {"outcome": "CLEARED"}, env["reviewer_med_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_EVALUATION_NOT_FOUND.value, expected_status=404
    )

    _rows, meta = validate_paginated(
        api_client.list_donor_evaluations(
            env["reviewer_med_headers"],
            params={"reviewer_staff_id": env["reviewer_med"]["id"]},
        )
    )
    assert meta["total_count"] == 0


def test_err_chain_not_found_returns_404():
    """PRD §2.5: "Path identifiers are resolved strictly left to right, in this order:
    program, then staff member, then recipient, then donor, then evaluation, then chain,
    then segment, then room, then booking, then follow-up, then review, then plan, then
    claim."
    PRD §2.10: "Every identifier in the path exists, resolved left to right — the matching
    not-found code, 404."
    PRD §3.5: "Chains are listed with optional `program_id`, `chain_type` and `status`
    filters plus `limit` and `offset`, and read individually to expose `version`,
    `segment_count`, `is_closed_loop`, `total_planned_cit_minutes` and
    `committed_donor_count`."

    Design: Corner/errors/err_chain_not_found_returns_404
    """
    env = setup_program_with_staff()

    response = api_client.validate_chain(NON_EXISTENT_UUID, env["coordinator_headers"])

    validate_error(response, ApiErrorId.ERR_CHAIN_NOT_FOUND.value, expected_status=404)

    rows, meta = validate_paginated(
        api_client.list_exchange_chains(
            env["coordinator_headers"], params={"program_id": env["program_id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_err_segment_not_found_returns_404():
    """PRD §2.5: "The thirteen not-found codes are `ERR_PROGRAM_NOT_FOUND`,
    `ERR_STAFF_NOT_FOUND`, `ERR_RECIPIENT_NOT_FOUND`, `ERR_DONOR_NOT_FOUND`,
    `ERR_EVALUATION_NOT_FOUND`, `ERR_CHAIN_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`,
    `ERR_ROOM_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_FOLLOW_UP_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_PLAN_NOT_FOUND` and `ERR_CLAIM_NOT_FOUND`, each returned
    with HTTP 404."
    PRD §2.10: "Every identifier in the path exists, resolved left to right — the matching
    not-found code, 404."
    PRD §3.5: "Segments are listed with optional `exchange_chain_id`,
    `donor_candidate_id`, `recipient_candidate_id`, `predecessor_segment_id` and `status`
    filters plus `limit` and `offset`, and read individually to expose their planned and
    actual cold-ischemia figures and `cit_breach`."

    Design: Corner/errors/err_segment_not_found_returns_404
    """
    env = setup_program_with_staff()

    response = api_client.send_segment_offer(
        NON_EXISTENT_UUID,
        create_offer_payload("2026-08-09T07:00:00Z", "2026-08-09T13:00:00Z"),
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_SEGMENT_NOT_FOUND.value, expected_status=404
    )

    rows, meta = validate_paginated(
        api_client.list_chain_segments(
            env["coordinator_headers"], params={"status": "PLANNED"}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_err_room_not_found_returns_404():
    """PRD §2.5: "Every reference — `program_id`, `intended_recipient_id`,
    `referred_by_staff_id`, `advocate_staff_id`, `donor_candidate_id`,
    `recipient_candidate_id`, `reviewer_staff_id`, `exchange_chain_id`,
    `predecessor_segment_id`, `operating_room_id`, `chain_segment_id`, `surgeon_staff_id`
    and `program_outcome_review_id` — must resolve to an existing row, and the failure
    reports the not-found code of the entity type that reference points at."
    PRD §2.10: "Every foreign key supplied in the request body exists — the matching
    not-found code, 404."
    PRD §3.1: "Registering a theatre requires `program_id` and a `room_code` that is
    unique within the program — a repeat is `ERR_DUPLICATE_ROOM_CODE` — plus an optional
    `turnover_buffer_minutes` that defaults to 45 and may not be negative; the room's
    `reserved_minutes_total` starts at 0."

    Design: Corner/errors/err_room_not_found_returns_404
    """
    env = setup_paired_loop_participants()
    _chain, segment = _chain_with_one_segment(env)
    room = add_operating_room(env, "OR-1")

    response = api_client.create_procedure_booking(
        {
            "operating_room_id": NON_EXISTENT_UUID,
            "chain_segment_id": segment["id"],
            "surgeon_staff_id": env["surgeon"]["id"],
            "booking_role": "DONOR_RECOVERY",
            "start_at": "2026-08-09T06:00:00Z",
            "end_at": "2026-08-09T10:00:00Z",
        },
        env["coordinator_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ROOM_NOT_FOUND.value, expected_status=404)

    _rows, meta = validate_paginated(
        api_client.list_procedure_bookings(
            env["coordinator_headers"], params={"chain_segment_id": segment["id"]}
        )
    )
    assert meta["total_count"] == 0
    rooms = validate_success(
        api_client.list_program_operating_rooms(env["program_id"], env["admin_headers"])
    )
    assert [row for row in rooms if row["id"] == room["id"]][0][
        "reserved_minutes_total"
    ] == 0


def test_err_booking_not_found_returns_404():
    """PRD §2.5: "The thirteen not-found codes are `ERR_PROGRAM_NOT_FOUND`,
    `ERR_STAFF_NOT_FOUND`, `ERR_RECIPIENT_NOT_FOUND`, `ERR_DONOR_NOT_FOUND`,
    `ERR_EVALUATION_NOT_FOUND`, `ERR_CHAIN_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`,
    `ERR_ROOM_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_FOLLOW_UP_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_PLAN_NOT_FOUND` and `ERR_CLAIM_NOT_FOUND`, each returned
    with HTTP 404."
    PRD §2.10: "Every identifier in the path exists, resolved left to right — the matching
    not-found code, 404."
    PRD §3.6: "Bookings are listed with optional `operating_room_id`, `chain_segment_id`,
    `surgeon_staff_id`, `booking_role` and `status` filters plus `limit` and `offset`, and
    read individually to expose `duration_minutes` and `cancel_reason_code`."

    Design: Corner/errors/err_booking_not_found_returns_404
    """
    env = setup_paired_loop_participants()
    _chain, segment = _chain_with_one_segment(env)
    add_operating_room(env, "OR-1")
    add_operating_room(env, "OR-2")

    response = api_client.cancel_procedure_booking(
        NON_EXISTENT_UUID,
        {"cancel_reason_code": "SCHEDULE_CHANGE"},
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_BOOKING_NOT_FOUND.value, expected_status=404
    )

    rows, meta = validate_paginated(
        api_client.list_procedure_bookings(
            env["coordinator_headers"], params={"chain_segment_id": segment["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_err_follow_up_not_found_returns_404():
    """PRD §2.5: "The thirteen not-found codes are `ERR_PROGRAM_NOT_FOUND`,
    `ERR_STAFF_NOT_FOUND`, `ERR_RECIPIENT_NOT_FOUND`, `ERR_DONOR_NOT_FOUND`,
    `ERR_EVALUATION_NOT_FOUND`, `ERR_CHAIN_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`,
    `ERR_ROOM_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_FOLLOW_UP_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_PLAN_NOT_FOUND` and `ERR_CLAIM_NOT_FOUND`, each returned
    with HTTP 404."
    PRD §2.10: "Every identifier in the path exists, resolved left to right — the matching
    not-found code, 404."
    PRD §3.7: "When the denominator is zero the figure is 100.00 — a brand-new program
    with three future-dated rows reports the vacuous 100.00 rather than 0.00."

    Design: Corner/errors/err_follow_up_not_found_returns_404
    """
    env = setup_program_with_staff()

    response = api_client.submit_follow_up(
        NON_EXISTENT_UUID,
        {"submitted_fields": follow_up_fields(12)},
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_FOLLOW_UP_NOT_FOUND.value, expected_status=404
    )

    assert refresh_program(env)["follow_up_compliance_pct"] == 100.0


def test_err_review_not_found_returns_404():
    """PRD §2.5: "The thirteen not-found codes are `ERR_PROGRAM_NOT_FOUND`,
    `ERR_STAFF_NOT_FOUND`, `ERR_RECIPIENT_NOT_FOUND`, `ERR_DONOR_NOT_FOUND`,
    `ERR_EVALUATION_NOT_FOUND`, `ERR_CHAIN_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`,
    `ERR_ROOM_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_FOLLOW_UP_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_PLAN_NOT_FOUND` and `ERR_CLAIM_NOT_FOUND`, each returned
    with HTTP 404."
    PRD §2.10: "Every identifier in the path exists, resolved left to right — the matching
    not-found code, 404."
    PRD §2.8: "Then: if an unanswered flagged review exists, the posture is `FROZEN`.
    Otherwise, if `follow_up_compliance_pct` is strictly below the program's
    `follow_up_compliance_threshold_pct`, or an open watch exists, or `cit_breach_count` is
    at least 2, the posture is `RESTRICTED`. Otherwise the posture is `OPEN`."

    Design: Corner/errors/err_review_not_found_returns_404
    """
    env = setup_program_with_staff()

    response = api_client.finalize_outcome_review(
        NON_EXISTENT_UUID, env["quality_headers"]
    )

    validate_error(response, ApiErrorId.ERR_REVIEW_NOT_FOUND.value, expected_status=404)

    assert refresh_program(env)["compliance_posture"] == "OPEN"


def test_err_plan_not_found_returns_404():
    """PRD §2.5: "The thirteen not-found codes are `ERR_PROGRAM_NOT_FOUND`,
    `ERR_STAFF_NOT_FOUND`, `ERR_RECIPIENT_NOT_FOUND`, `ERR_DONOR_NOT_FOUND`,
    `ERR_EVALUATION_NOT_FOUND`, `ERR_CHAIN_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`,
    `ERR_ROOM_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_FOLLOW_UP_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_PLAN_NOT_FOUND` and `ERR_CLAIM_NOT_FOUND`, each returned
    with HTTP 404."
    PRD §2.10: "Every identifier in the path exists, resolved left to right — the matching
    not-found code, 404."
    PRD §2.8: "Then: if an unanswered flagged review exists, the posture is `FROZEN`.
    Otherwise, if `follow_up_compliance_pct` is strictly below the program's
    `follow_up_compliance_threshold_pct`, or an open watch exists, or `cit_breach_count` is
    at least 2, the posture is `RESTRICTED`. Otherwise the posture is `OPEN`."

    Design: Corner/errors/err_plan_not_found_returns_404
    """
    env = setup_program_with_staff()

    response = api_client.transition_improvement_plan(
        NON_EXISTENT_UUID, {"action": "ACCEPT"}, env["admin_headers"]
    )

    validate_error(response, ApiErrorId.ERR_PLAN_NOT_FOUND.value, expected_status=404)

    assert refresh_program(env)["compliance_posture"] == "OPEN"


def test_err_claim_not_found_returns_404():
    """PRD §2.5: "The thirteen not-found codes are `ERR_PROGRAM_NOT_FOUND`,
    `ERR_STAFF_NOT_FOUND`, `ERR_RECIPIENT_NOT_FOUND`, `ERR_DONOR_NOT_FOUND`,
    `ERR_EVALUATION_NOT_FOUND`, `ERR_CHAIN_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`,
    `ERR_ROOM_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_FOLLOW_UP_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_PLAN_NOT_FOUND` and `ERR_CLAIM_NOT_FOUND`, each returned
    with HTTP 404."
    PRD §2.10: "Every identifier in the path exists, resolved left to right — the matching
    not-found code, 404."
    PRD §3.1: "Registration also fixes the program's starting derived state:
    `compliance_posture` begins at `OPEN`, `follow_up_compliance_pct` begins at 100 because
    no follow-up interval is due yet, `cit_breach_count` begins at 0,
    `donor_fund_committed_cents` begins at 0 and `donor_fund_remaining_cents` begins equal
    to `donor_fund_pool_cents`."

    Design: Corner/errors/err_claim_not_found_returns_404
    """
    env = setup_program_with_staff()

    response = api_client.adjudicate_claim(
        NON_EXISTENT_UUID, {"decision": "APPROVE"}, env["finance_headers"]
    )

    validate_error(response, ApiErrorId.ERR_CLAIM_NOT_FOUND.value, expected_status=404)

    program = refresh_program(env)
    assert program["donor_fund_committed_cents"] == 0
    assert program["donor_fund_remaining_cents"] == 5000000
