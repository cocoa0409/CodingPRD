"""Role boundaries: the refusals the profile declares, and the one path every role shares."""
from test_helpers import (
    add_staff_member,
    create_donor,
    create_donor_cost_claim_payload,
    create_finalized_flagged_review,
    create_psychosocial_evaluation_payload,
    create_recipient,
    determine_evaluation,
    file_improvement_plan,
    get_donor,
    make_advocate_headers,
    refresh_program,
    setup_donated_donor,
    setup_program_with_staff,
    submit_medical_evaluation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId


def test_finance_admin_cannot_file_the_claim_it_would_later_decide():
    """PRD §2.1: "Write endpoints are narrowly scoped: `ProgramAdmin` alone configures
    programs, staff, rooms, advocate assignments, follow-up waivers, improvement-plan
    decisions and the logical clock; `TransplantCoordinator` alone drives candidacy, donor
    referral, chain construction, offers, theatre bookings, follow-up submissions and
    cost-claim filing; `DonorAdvocate` alone runs consent disclosure and the advocacy
    determination; `EvaluationReviewer` alone submits, determines and resubmits donor
    evaluations; `QualityOfficer` alone creates and finalizes outcome reviews and files
    improvement plans; `FinanceAdmin` alone adjudicates and reverses cost claims."
    PRD §2.1: "The prohibitions are as load-bearing as the permissions: `ProgramAdmin`
    cannot file the improvement plan it decides on, `QualityOfficer` cannot decide the plan
    it filed, `TransplantCoordinator` cannot adjudicate the claim it filed, and
    `FinanceAdmin` cannot touch any clinical state."
    PRD §2.10: "`X-User-Role` names a declared role that the endpoint authorizes, and for
    an entity-backed role `X-User-ID` is an active staff member with the matching
    `staff_role` — `ERR_UNAUTHORIZED`, 403."
    PRD §3.9: "Claims are listed through their donor, filtered on `claim_type` and
    `status`, with `limit` and `offset`, and the listing exposes each claim's
    estimated-versus-adjudicated split."
    PRD §2.9: "A program's `donor_fund_committed_cents` is the sum of `fund_part_cents`
    over every donor cost claim whose donor belongs to that program and whose `status` is
    `ADJUDICATED`."

    Design: Corner/rbac/finance_admin_cannot_file_a_donor_cost_claim
    """
    env = setup_donated_donor()
    donor_id = env["donor_one"]["id"]

    response = api_client.create_donor_cost_claim(
        create_donor_cost_claim_payload(
            donor_id,
            claim_type="MEDICAL",
            coverage_source="PROGRAM_FUND",
            submitted_amount_cents=450000,
            service_from_on="2026-08-10",
            service_to_on="2026-08-11",
        ),
        env["finance_headers"],
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    _rows, meta = validate_paginated(
        api_client.list_donor_cost_claims(donor_id, env["coordinator_headers"])
    )
    assert meta["total_count"] == 0, "the adjudicator filed nothing"
    assert refresh_program(env)["donor_fund_committed_cents"] == 0


def test_quality_officer_cannot_decide_the_plan_it_filed():
    """PRD §2.1: "The prohibitions are as load-bearing as the permissions: `ProgramAdmin`
    cannot file the improvement plan it decides on, `QualityOfficer` cannot decide the plan
    it filed, `TransplantCoordinator` cannot adjudicate the claim it filed, and
    `FinanceAdmin` cannot touch any clinical state."
    PRD §3.8: "A `ProgramAdmin` acts on a plan by supplying an `action` and, for a
    decision, a `decision_reason_code`."
    PRD §3.8: "Creation puts the new plan in `SUBMITTED` with `decision_reason_code`,
    `decided_at` and `closed_at` all null, moves any existing plan of the same review whose
    status is `SUBMITTED` or `REJECTED` to `SUPERSEDED` — which the system will only do
    while no plan of that review has already reached `ACCEPTED` or `CLOSED` — and
    increments the parent review's `version` so that a competing writer holding the old
    value is now stale."
    PRD §2.8: "Then: if an unanswered flagged review exists, the posture is `FROZEN`."

    Design: Corner/rbac/quality_officer_cannot_decide_the_plan_it_filed
    """
    env = setup_program_with_staff()
    review = create_finalized_flagged_review(env)
    assert review["flag_level"] == "FLAGGED"
    plan = file_improvement_plan(env, review["id"])
    assert plan["status"] == "SUBMITTED"
    assert refresh_program(env)["compliance_posture"] == "FROZEN"

    response = api_client.transition_improvement_plan(
        plan["id"],
        {"action": "ACCEPT", "decision_reason_code": "PLAN_ADEQUATE"},
        env["quality_headers"],
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    rows, meta = validate_paginated(
        api_client.list_review_improvement_plans(review["id"], env["quality_headers"])
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == plan["id"]
    assert rows[0]["status"] == "SUBMITTED", "the filer did not answer its own review"
    assert rows[0]["decided_at"] is None
    assert rows[0]["decision_reason_code"] is None
    assert refresh_program(env)["compliance_posture"] == "FROZEN"


def test_a_coordinator_cannot_move_the_logical_clock():
    """PRD §2.1: "Write endpoints are narrowly scoped: `ProgramAdmin` alone configures
    programs, staff, rooms, advocate assignments, follow-up waivers, improvement-plan
    decisions and the logical clock; `TransplantCoordinator` alone drives candidacy, donor
    referral, chain construction, offers, theatre bookings, follow-up submissions and
    cost-claim filing; `DonorAdvocate` alone runs consent disclosure and the advocacy
    determination; `EvaluationReviewer` alone submits, determines and resubmits donor
    evaluations; `QualityOfficer` alone creates and finalizes outcome reviews and files
    improvement plans; `FinanceAdmin` alone adjudicates and reverses cost claims."
    PRD §2.1: "If the header names a role that is not one of the six declared roles, or
    names a role that the target endpoint does not authorize, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.4: "The logical UTC clock reads exactly `2026-08-01T00:00:00Z` before any
    test-driving call adjusts it, and it never falls back to wall-clock time."
    PRD §2.4: "Every persisted resource exposes an `id` that is a server-minted UUID with
    no type prefix, and a `created_at` timestamp in ISO 8601 UTC format with three
    fractional digits."

    Design: Corner/rbac/coordinator_cannot_set_the_logical_clock
    """
    env = setup_program_with_staff()
    assert env["clock"] == "2026-08-01T00:00:00Z"

    response = api_client.set_clock(
        {"current_utc": "2026-09-01T00:00:00Z"}, env["coordinator_headers"]
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    recipient = create_recipient(env, mrn="R-001")
    assert recipient["created_at"].startswith("2026-08-01T00:00:00"), (
        "the refused call left the clock at the epoch"
    )


def test_every_role_shares_every_read_endpoint():
    """PRD §2.1: "Read endpoints are open to all six roles."
    PRD §2.4: "Almost every resource additionally exposes an `updated_at` timestamp in the
    same format and an integer `version` that starts at 1 on creation and increases by
    exactly 1 on every mutation that changes the row."
    PRD §3.3: "The referral records `referred_by_staff_id` from the referring
    coordinator's `X-User-ID` for provenance."
    PRD §3.3: "A new donor starts with `overall_status` `REFERRED`, `advocacy_status`
    `UNASSIGNED`, both `medical_status` and `psychosocial_status` at `PENDING`,
    `disclosure_sequence` 0, `deferral_count` 0, `medical_risk_points` and
    `psychosocial_risk_points` 0, and `screening_risk_index` 0; `advocate_staff_id`,
    `disclosure_at`, `cooling_off_ends_at`, `attestation_at`, `objection_reason_code`,
    `final_risk_index` and `donated_at` are all null."
    PRD §3.3: "Donor candidates are listed with optional `program_id`,
    `intended_recipient_id`, `referred_by_staff_id`, `advocate_staff_id` and
    `overall_status` filters plus `limit` and `offset`; reading one exposes all four state
    dimensions, both risk indices and `cooling_off_ends_at`."

    Design: Corner/rbac/every_role_shares_every_read_endpoint
    """
    env = setup_program_with_staff()
    donor = create_donor(env, assign_advocate=False, mrn="D-001", age_years=41)
    donor_id = donor["id"]
    program_version = validate_success(
        api_client.get_program(env["program_id"], env["admin_headers"])
    )["version"]

    for headers in (
        env["admin_headers"],
        env["coordinator_headers"],
        env["advocate_headers"],
        env["reviewer_med_headers"],
        env["quality_headers"],
    ):
        validate_success(api_client.get_program(env["program_id"], headers))
        validate_success(api_client.get_donor_candidate(donor_id, headers))
    quality_read = validate_success(
        api_client.get_donor_candidate(donor_id, env["quality_headers"])
    )

    finance_read = validate_success(
        api_client.get_donor_candidate(donor_id, env["finance_headers"])
    )

    assert finance_read["overall_status"] == "REFERRED"
    assert finance_read["referred_by_staff_id"] == env["coordinator"]["id"]
    assert finance_read == quality_read, "the payload does not depend on the reader"
    assert finance_read["version"] == 1, "no read mutated the donor"
    assert finance_read["advocacy_status"] == "UNASSIGNED"
    assert finance_read["medical_status"] == "PENDING"
    assert finance_read["psychosocial_status"] == "PENDING"
    assert finance_read["cooling_off_ends_at"] is None
    assert (
        validate_success(api_client.get_program(env["program_id"], env["admin_headers"]))[
            "version"
        ]
        == program_version
    ), "no read mutated the program"


def test_a_second_advocate_with_the_same_role_cannot_disclose_consent():
    """PRD §2.1: "In addition, for any operation on a donor candidate the header value
    must equal that donor's `advocate_staff_id`; if it names a different staff member the
    request fails with `ERR_NOT_ASSIGNED_ADVOCATE` (HTTP 403)."
    PRD §2.10: "Resource-scoped actor binding: `X-User-ID` equals the donor's
    `advocate_staff_id` for consent disclosure and the advocacy determination, and equals
    the evaluation's `reviewer_staff_id` for an evaluation determination and resubmission —
    `ERR_NOT_ASSIGNED_ADVOCATE` or `ERR_NOT_ASSIGNED_REVIEWER`, 403."
    PRD §3.3: "Only the assigned advocate may record an informed-consent disclosure
    session, and the operation takes no body fields at all."
    PRD §3.3: "It advances `disclosure_sequence` by 1, sets `disclosure_at` to the current
    logical clock, and re-derives `cooling_off_ends_at`."
    PRD §3.3: "A `ProgramAdmin` assigns the advocate by supplying an `advocate_staff_id`,
    moving `advocacy_status` from `UNASSIGNED` to `ASSIGNED` and recording the staff member
    on the donor."

    Design: Corner/rbac/unassigned_advocate_cannot_disclose_consent
    """
    env = setup_program_with_staff()
    recipient = create_recipient(env, mrn="R-001")
    donor = create_donor(
        env, intended_recipient_id=recipient["id"], mrn="D-001", age_years=41
    )
    assert donor["advocacy_status"] == "ASSIGNED"
    assert donor["advocate_staff_id"] == env["advocate"]["id"]
    second_advocate = add_staff_member(
        env["program_id"], "LIVING_DONOR_ADVOCATE", "1000000008", "Advocate Two"
    )

    response = api_client.record_consent_disclosure(
        donor["id"], make_advocate_headers(second_advocate["id"])
    )

    validate_error(
        response, ApiErrorId.ERR_NOT_ASSIGNED_ADVOCATE.value, expected_status=403
    )

    after = get_donor(env, donor["id"])
    assert after["advocacy_status"] == "ASSIGNED"
    assert after["disclosure_sequence"] == 0
    assert after["disclosure_at"] is None
    assert after["cooling_off_ends_at"] is None

    disclosed = validate_success(
        api_client.record_consent_disclosure(donor["id"], env["advocate_headers"])
    )
    assert disclosed["advocacy_status"] == "DISCLOSED", (
        "the assigned advocate makes the identical call succeed"
    )
    assert disclosed["disclosure_sequence"] == 1


def test_the_medical_reviewer_cannot_also_author_the_psychosocial_evaluation():
    """PRD §3.4: "The reviewer of a donor's psychosocial evaluation may not be the
    reviewer of that same donor's medical evaluation — a single person may not certify both
    halves of one donor's fitness — and a violation is `ERR_REVIEWER_SOD_CONFLICT`."
    PRD §3.4: "Submitting an evaluation requires the `donor_candidate_id` and the
    `domain`, and records the authoring reviewer's `X-User-ID` as `reviewer_staff_id`."
    PRD §3.4: "A `CLEARED` determination sets that donor dimension to `CLEARED`, copies
    the evaluation's `risk_points` into the donor's `medical_risk_points` or
    `psychosocial_risk_points` as the domain dictates, recomputes the donor's
    `screening_risk_index` and re-derives `overall_status`."
    PRD §3.4: "Evaluations are listed with optional `donor_candidate_id`,
    `reviewer_staff_id`, `domain` and `status` filters plus `limit` and `offset`, and read
    individually to expose `exclusion_codes`, `hard_exclusion_count`, `risk_points` and
    `submission_count`."

    Design: Corner/rbac/medical_reviewer_cannot_also_author_the_psychosocial_evaluation
    """
    env = setup_program_with_staff()
    recipient = create_recipient(env, mrn="R-001")
    donor = create_donor(
        env, intended_recipient_id=recipient["id"], mrn="D-001", age_years=41
    )
    medical = submit_medical_evaluation(env, donor["id"])
    assert medical["reviewer_staff_id"] == env["reviewer_med"]["id"]
    determine_evaluation(env, medical["id"], "CLEARED", env["reviewer_med_headers"])
    body = create_psychosocial_evaluation_payload(
        donor["id"], financial_hardship_score=1, social_support_score=9
    )

    response = api_client.create_donor_evaluation(body, env["reviewer_med_headers"])

    validate_error(
        response, ApiErrorId.ERR_REVIEWER_SOD_CONFLICT.value, expected_status=422
    )

    _rows, meta = validate_paginated(
        api_client.list_donor_evaluations(
            env["coordinator_headers"], params={"donor_candidate_id": donor["id"]}
        )
    )
    assert meta["total_count"] == 1, "the conflicted submission created no row"

    after = get_donor(env, donor["id"])
    assert after["psychosocial_status"] == "PENDING"
    assert after["medical_status"] == "CLEARED"

    accepted = validate_success(
        api_client.create_donor_evaluation(body, env["reviewer_psy_headers"]),
        expected_status=201,
    )
    assert accepted["reviewer_staff_id"] == env["reviewer_psy"]["id"], (
        "the identical body is accepted from the other reviewer"
    )
    assert accepted["status"] == "SUBMITTED"
