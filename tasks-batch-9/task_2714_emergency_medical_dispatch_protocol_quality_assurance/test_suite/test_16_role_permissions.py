"""Role-based access control on the EMD dispatch QA API.

Covers the six declared roles' exclusive writes, the per-endpoint authorization
refusal, the dispatcher's case-ownership check on a rebuttal, the
segregation-of-duties comparand at finalization, the one write two roles share,
and the authentication gate that runs ahead of every other check.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.assertions import approx1, assert_instant_equals

CLOCK = "2026-08-20T00:00:00Z"
CALL_RECEIVED_AT = "2026-08-05T09:00:00Z"

# Four sections at 23 of 25 give 92.00 per section, a 92.0 composite under both
# the unweighted and the default weighted view.
SECTIONS_92 = {
    "case_entry": (23, 25),
    "key_questions": (23, 25),
    "pre_arrival": (23, 25),
    "final_coding": (23, 25),
}
SECTIONS_PERFECT = {
    "case_entry": (25, 25),
    "key_questions": (25, 25),
    "pre_arrival": (25, 25),
    "final_coding": (25, 25),
}

CURRICULUM_WEIGHTS = {
    "case_entry_weight": 0.2500,
    "key_questions_weight": 0.2500,
    "pre_arrival_weight": 0.2500,
    "final_coding_weight": 0.2500,
}


def _program_with_two_families(api):
    """A programme with an APPROVED MPDS card set and a second DRAFT card set."""
    program = fx.new_program(api)
    version = fx.new_approved_version(api, program["id"], version_label="MPDS-13.0")
    curriculum = fx.new_version(
        api,
        program["id"],
        protocol_family="LOCAL_CARDSET",
        version_label="LOCAL-1.0",
        **CURRICULUM_WEIGHTS,
    )
    return program, version, curriculum


def test_each_role_exercises_its_own_exclusive_write(api):
    """PRD §3.5: "Scoring is the `QaReviewer`'s work and nobody else's."
    PRD §3.5: "Every sheet records `submitted_by_user_id` from the submitting
    reviewer's `X-User-ID`, which is the comparand the segregation-of-duties rule
    uses at finalization, and each sheet is linked to its parent by `review_id`."
    PRD §3.7: "Finalization is a `QaSupervisor` action, optionally carrying a
    `finalization_note`, and it is the moment a review stops being an opinion and
    becomes a number in a ledger."
    PRD §3.2: "Approving a draft moves it `DRAFT → APPROVED`, stamps
    `approved_by_user_id` with the director's `X-User-ID`, and may carry an
    optional `approval_note`."
    PRD §2.4: "A `ProgramAdmin` may move the clock to any instant by supplying
    `to_iso8601`; the response reports the new value as `current_utc`."
    PRD §3.9: "Accreditation reporting is the `AccreditationOfficer`'s exclusive
    province."
    PRD §3.9: "Filing takes the report `DRAFT → SUBMITTED`, records the recipient
    and stamps `submitted_at` from the logical clock, and then Cascade C runs."

    Design: Corner/rbac/each_role_exercises_its_own_exclusive_write
    """
    program, version, curriculum = _program_with_two_families(api)
    dispatcher = fx.new_dispatcher(api, program["id"])
    fx.set_clock(api, CLOCK)
    call = fx.ingest_call(api, dispatcher["id"], received_at=CALL_RECEIVED_AT)
    period = fx.new_period(api, program["id"], target_sample_count=1)
    review = fx.target(api, period["id"], call["id"], "COMPLAINT")

    # The reviewer scores.
    sheet = validate_success(
        api.submit_scores(
            review["id"],
            f.section_score_payload(review["version"], SECTIONS_92, "10-C-4"),
            u.REVIEWER,
        ),
        201,
    )
    assert sheet["submitted_by_user_id"] == u.REVIEWER_USER_ID, (
        "the sheet must record the submitting reviewer's X-User-ID"
    )

    # The supervisor finalizes.
    finalized = validate_success(
        api.finalize_review(review["id"], {"finalization_note": "accepted"}, u.SUPERVISOR),
        200,
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["final_composite_score"] == approx1(92.0)

    # The medical director approves protocol content.
    approved = validate_success(
        api.approve_protocol_version(
            curriculum["id"], {"approval_note": "curriculum adopted"}, u.DIRECTOR
        ),
        200,
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == u.DIRECTOR_USER_ID

    # The programme administrator owns the logical clock.
    clock = validate_success(
        api.set_clock({"to_iso8601": "2026-09-02T00:00:00Z"}, u.ADMIN), 200
    )
    assert_instant_equals(clock["current_utc"], "2026-09-02T00:00:00Z")

    # The accreditation officer builds and files the report.
    report = validate_success(
        api.create_accreditation_report(
            program["id"], f.accreditation_report_payload(), u.OFFICER
        ),
        201,
    )
    assert report["status"] == "DRAFT"
    filed = validate_success(
        api.submit_accreditation_report(
            report["id"], {"submitted_to": "OVERSIGHT_COMMITTEE"}, u.OFFICER
        ),
        200,
    )
    assert filed["status"] == "SUBMITTED"
    assert filed["submitted_to"] == "OVERSIGHT_COMMITTEE"
    assert_instant_equals(filed["submitted_at"], "2026-09-02T00:00:00Z")

    program_after = validate_success(api.get_audit_program(program["id"], u.ADMIN), 200)
    assert program_after["submitted_report_count"] == 1
    assert program_after["accreditation_status"] == "ACCREDITED"


def _scored_review_env(api):
    """A SCORED review at 92.0 in an OPEN MIXED period, plus a DRAFT card set."""
    program, version, curriculum = _program_with_two_families(api)
    dispatcher = fx.new_dispatcher(api, program["id"])
    fx.set_clock(api, CLOCK)
    call = fx.ingest_call(api, dispatcher["id"], received_at=CALL_RECEIVED_AT)
    period = fx.new_period(
        api, program["id"], sampling_mode="MIXED", target_sample_count=2
    )
    review = fx.target(api, period["id"], call["id"], "COMPLAINT")
    observed_version = review["version"]
    fx.score(
        api,
        review["id"],
        sections=SECTIONS_92,
        expected_review_version=observed_version,
    )
    return {
        "program_id": program["id"],
        "curriculum_id": curriculum["id"],
        "dispatcher_id": dispatcher["id"],
        "period_id": period["id"],
        "review_id": review["id"],
        "observed_version": observed_version,
    }


_UNAUTHORIZED_WRITES = {
    "reviewer_cannot_finalize": lambda api, env: api.finalize_review(
        env["review_id"], {"finalization_note": "reviewer tries to close"}, u.REVIEWER
    ),
    "supervisor_cannot_score": lambda api, env: api.submit_scores(
        env["review_id"],
        f.section_score_payload(env["observed_version"], SECTIONS_PERFECT, "10-C-4"),
        u.SUPERVISOR,
    ),
    "admin_cannot_approve_a_version": lambda api, env: api.approve_protocol_version(
        env["curriculum_id"], {"approval_note": "admin tries to approve"}, u.ADMIN
    ),
    "officer_cannot_void_a_review": lambda api, env: api.void_review(
        env["review_id"], {"void_reason": "AUDIO_UNAVAILABLE"}, u.OFFICER
    ),
    "director_cannot_draw_a_sample": lambda api, env: api.draw_random_sample(
        env["period_id"], {"requested_count": 1}, u.DIRECTOR
    ),
}


@pytest.mark.parametrize("attempt", list(_UNAUTHORIZED_WRITES))
def test_roles_outside_an_endpoints_list_cannot_invoke_it(api, attempt):
    """PRD §2.1: "If the headers are well formed but the named role is not among
    those authorized for the endpoint being called, the request is rejected with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.9: "The practical consequence worth internalising: a state violation
    always outranks a scope, safety, overlap, temporal, uniqueness or quota
    violation, and an authorization failure outranks everything except a missing
    header."

    Design: Corner/rbac/roles_outside_an_endpoints_list_cannot_invoke_it_returns_403
    """
    env = _scored_review_env(api)

    validate_error(_UNAUTHORIZED_WRITES[attempt](api, env), err.ERR_ROLE_NOT_PERMITTED)

    review = validate_success(api.get_review(env["review_id"], u.SUPERVISOR), 200)
    assert review["status"] == "SCORED", "a refused write must not move the review"
    assert review["provisional_composite_score"] == approx1(92.0)
    assert review["finalized_at"] is None
    assert review["voided_at"] is None

    sheets, meta = validate_paginated(
        api.list_score_sheets(env["review_id"], u.SUPERVISOR, {"limit": 100})
    )
    assert meta["total_count"] == 1, "no refused submission may append a sheet"
    assert len(sheets) == 1

    curriculum = validate_success(
        api.get_protocol_version(env["curriculum_id"], u.ADMIN), 200
    )
    assert curriculum["status"] == "DRAFT"
    assert curriculum["approved_by_user_id"] is None


def test_a_dispatcher_cannot_rebut_another_dispatchers_review(api):
    """PRD §2.1: "When `X-User-Role` is `Dispatcher`, by contrast, `X-User-ID` is
    the `id` of the acting dispatcher row, and ownership checks compare the
    resource's dispatcher foreign key to it directly: a dispatcher filing a
    rebuttal must be the dispatcher whose work is under review, and a mismatch is
    rejected with `ERR_NOT_CASE_OWNER` (HTTP 403)."
    PRD §3.7: "A dispatcher who believes a score is wrong may say so, and the
    right to do it is theirs alone — only the `Dispatcher` role may file, and only
    against a review whose `dispatcher_id` is their own `X-User-ID`, with any
    other dispatcher's attempt refused with `ERR_NOT_CASE_OWNER`."
    PRD §3.7: "An accepted filing creates a rebuttal in `status` `SUBMITTED`,
    linked by `review_id`, with `round_index` one greater than the review's
    `rebuttal_round_count` at the time of filing and `submitted_by_user_id`
    recording the filing dispatcher — always the same identifier as the review's
    `dispatcher_id`."
    PRD §3.7: "The review's `rebuttal_round_count` is set to that same round
    index, the review moves `SCORED → DISPUTED`, and its `version` is
    incremented."

    Design: Corner/rbac/a_dispatcher_cannot_rebut_another_dispatchers_review
    """
    env = fx.scored_review_env(api)
    owner_id = env["dispatcher_id"]
    peer = fx.new_dispatcher(api, env["program_id"])

    body = f.rebuttal_payload(narrative="the pre-arrival deduction is not mine")

    validate_error(
        api.create_rebuttal(
            env["review_id"], body, u.make_dispatcher_headers(peer["id"])
        ),
        err.ERR_NOT_CASE_OWNER,
    )

    rebuttal = validate_success(
        api.create_rebuttal(
            env["review_id"], body, u.make_dispatcher_headers(owner_id)
        ),
        201,
    )
    assert rebuttal["status"] == "SUBMITTED"
    assert rebuttal["round_index"] == 1
    assert rebuttal["review_id"] == env["review_id"]
    assert rebuttal["submitted_by_user_id"] == owner_id

    rows, meta = validate_paginated(
        api.list_rebuttals(env["review_id"], u.SUPERVISOR, {"limit": 100})
    )
    assert meta["total_count"] == 1, "the refused peer attempt must not create a row"
    assert [row["id"] for row in rows] == [rebuttal["id"]]

    review = validate_success(api.get_review(env["review_id"], u.SUPERVISOR), 200)
    assert review["status"] == "DISPUTED"
    assert review["rebuttal_round_count"] == 1


def test_the_scoring_reviewer_cannot_finalize_their_own_sheet(api):
    """PRD §2.1: "The `X-User-ID` finalizing a review must differ from the
    `submitted_by_user_id` recorded on that review's current score sheet; a
    reviewer who has already been granted `QaSupervisor` capacity may not sign off
    their own scoring work, and an attempt to do so is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.7: "The finalizing `X-User-ID` must differ from the current sheet's
    `submitted_by_user_id`, or the request is refused for segregation of duties."

    Design: Corner/rbac/the_scoring_reviewer_cannot_finalize_their_own_sheet_returns_403
    """
    dual_reviewer = u.make_headers("dual-1", u.ROLE_QA_REVIEWER)
    dual_supervisor = u.make_headers("dual-1", u.ROLE_QA_SUPERVISOR)

    program = fx.new_program(api)
    fx.new_approved_version(api, program["id"], version_label="MPDS-13.0")
    dispatcher = fx.new_dispatcher(api, program["id"])
    fx.set_clock(api, CLOCK)
    call = fx.ingest_call(api, dispatcher["id"], received_at=CALL_RECEIVED_AT)
    period = fx.new_period(api, program["id"], target_sample_count=1)
    review = fx.target(api, period["id"], call["id"], "COMPLAINT")
    sheet = validate_success(
        api.submit_scores(
            review["id"],
            f.section_score_payload(review["version"], SECTIONS_92, "10-C-4"),
            dual_reviewer,
        ),
        201,
    )
    assert sheet["submitted_by_user_id"] == "dual-1"

    validate_error(
        api.finalize_review(
            review["id"], {"finalization_note": "self-closing"}, dual_supervisor
        ),
        err.ERR_SEGREGATION_OF_DUTIES,
    )
    still_scored = validate_success(api.get_review(review["id"], u.SUPERVISOR), 200)
    assert still_scored["status"] == "SCORED"
    assert still_scored["finalized_at"] is None

    finalized = validate_success(
        api.finalize_review(
            review["id"], {"finalization_note": "independent close"}, u.SUPERVISOR
        ),
        200,
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["final_composite_score"] == approx1(92.0)

    ledger = validate_success(api.get_dispatcher(dispatcher["id"], u.ADMIN), 200)
    assert ledger["reviewed_case_count"] == 1, "the ledger moved only on the permitted finalize"


def test_both_the_supervisor_and_the_reviewer_can_target_a_review(api):
    """PRD §3.4: "Targeted selection, available to a `QaSupervisor` and also to a
    `QaReviewer`, pulls one nominated case in."
    PRD §3.4: "A successful targeted selection creates one review with
    `selection_mode` of `TARGETED`, moves the call to `SELECTED`, and increments
    the period's `selected_review_count` by one."

    Design: Corner/rbac/both_the_supervisor_and_the_reviewer_can_target_a_review
    """
    program = fx.new_program(api)
    fx.new_approved_version(api, program["id"], version_label="MPDS-13.0")
    dispatcher = fx.new_dispatcher(api, program["id"])
    fx.set_clock(api, CLOCK)
    call_one = fx.ingest_call(api, dispatcher["id"], received_at="2026-08-05T09:00:00Z")
    call_two = fx.ingest_call(
        api,
        dispatcher["id"],
        received_at="2026-08-06T09:00:00Z",
        dispatched_determinant_code="10-D-2",
    )
    period = fx.new_period(
        api, program["id"], sampling_mode="MIXED", target_sample_count=2
    )

    by_supervisor = validate_success(
        api.target_review(
            period["id"], f.target_review_payload(call_one["id"]), u.SUPERVISOR
        ),
        201,
    )
    assert by_supervisor["selection_mode"] == "TARGETED"
    assert by_supervisor["selection_reason"] == "COMPLAINT"
    assert by_supervisor["status"] == "SELECTED"

    by_reviewer = validate_success(
        api.target_review(
            period["id"],
            f.target_review_payload(call_two["id"], selection_reason="SENTINEL_FLAG"),
            u.REVIEWER,
        ),
        201,
    )
    assert by_reviewer["selection_mode"] == "TARGETED"
    assert by_reviewer["selection_reason"] == "SENTINEL_FLAG"
    assert by_reviewer["status"] == "SELECTED"

    periods, _ = validate_paginated(
        api.list_sampling_periods(
            program["id"], u.OFFICER, {"status": "OPEN", "limit": 10, "offset": 0}
        )
    )
    assert len(periods) == 1
    assert periods[0]["selected_review_count"] == 2
    assert periods[0]["status"] == "OPEN", (
        "meeting the quota does not close the period; closing is its own action"
    )

    reviews, meta = validate_paginated(
        api.list_reviews(
            u.SUPERVISOR, {"sampling_period_id": period["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["id"] for row in reviews) == sorted(
        [by_supervisor["id"], by_reviewer["id"]]
    )
    assert {row["status"] for row in reviews} == {"SELECTED"}


_UNAUTHENTICATED_CALLS = {
    "missing_role_header": lambda api, env: api.create_audit_program(
        f.audit_program_payload(name="Headerless"), u.headers_without_role()
    ),
    "missing_user_id_header": lambda api, env: api.create_audit_program(
        f.audit_program_payload(name="No Identity"), u.headers_without_user_id()
    ),
    "undeclared_role_name": lambda api, env: api.create_audit_program(
        f.audit_program_payload(name="Unknown Role"), u.headers_with_unknown_role()
    ),
    "unknown_review_id_is_still_401": lambda api, env: api.finalize_review(
        NON_EXISTENT_UUID, {"finalization_note": "no headers at all"},
        u.headers_without_role(),
    ),
    "reads_are_covered_too": lambda api, env: api.get_audit_program(
        env["program_id"], u.headers_without_user_id()
    ),
}


@pytest.mark.parametrize("attempt", list(_UNAUTHENTICATED_CALLS))
def test_calls_without_a_valid_role_header_are_unauthenticated(api, attempt):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying
    the acting operator, and `X-User-Role`, naming the capacity in which they act.
    If either header is absent, or if `X-User-Role` is not one of the six declared
    roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.9: "1. **Authentication** — headers present and the role recognized,
    else `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/writes_without_a_valid_role_header_are_unauthenticated
    """
    program = fx.new_program(api)
    env = {"program_id": program["id"]}

    validate_error(_UNAUTHENTICATED_CALLS[attempt](api, env), err.ERR_UNAUTHENTICATED)

    readable = validate_success(api.get_audit_program(program["id"], u.ADMIN), 200)
    assert readable["id"] == program["id"], (
        "a refused unauthenticated call must leave the programme readable"
    )
