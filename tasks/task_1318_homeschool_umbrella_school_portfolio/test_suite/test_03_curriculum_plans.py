"""Curriculum plans: review/revision cycle, amendment OCC, uniqueness, core subjects."""
from test_helpers import (
    ApiErrorId,
    assert_curriculum_plan,
    assert_version_incremented,
    create_curriculum_plan_payload,
    create_open_year,
    get_success_data,
    setup_registered_enrollment,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

REVIEWER = TEST_USERS["reviewer_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]

CORE = ["READING", "WRITING", "MATH", "SCIENCE", "SOCIAL_STUDIES"]


def _setup_plan(api, subjects=None):
    year = create_open_year()
    ctx = setup_registered_enrollment(year["id"], 6, family_name="Fam Cyc",
                                      district_code="D-05")
    plan = get_success_data(
        api.create_curriculum_plan(
            ctx["enrollment"]["id"], create_curriculum_plan_payload(subjects=subjects),
            ctx["parent_headers"],
        )
    )
    return ctx, plan


def test_plan_revision_cycle_increments_revision_count(api):
    """PRD §3.3: "The family resubmits a revised plan (`REVISION_REQUESTED` →
    `SUBMITTED`), which increments `revision_count`, and the review cycle repeats."
    PRD §3.3: "a revision request moves `SUBMITTED` → `REVISION_REQUESTED`, and
    either way the reviewer is recorded as `reviewer_id` and the notes stored as
    `review_notes`."

    Design: Difficulty/non_linear_state_machine/curriculum_plan_revision_cycle
    """
    ctx, plan = _setup_plan(api)
    parent = ctx["parent_headers"]

    submitted = validate_success(api.submit_curriculum_plan(plan["id"], parent))
    assert submitted["status"] == "SUBMITTED"

    revision = validate_success(
        api.review_curriculum_plan(
            plan["id"], {"decision": "REQUEST_REVISION", "notes": "add PE detail"}, REVIEWER
        )
    )
    assert revision["status"] == "REVISION_REQUESTED"
    assert revision["reviewer_id"] == "rev-1"
    assert revision["review_notes"] == "add PE detail"

    resubmitted = validate_success(api.submit_curriculum_plan(plan["id"], parent))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1, "resubmission increments revision_count"

    approved = validate_success(
        api.review_curriculum_plan(plan["id"], {"decision": "APPROVE"}, REVIEWER)
    )
    assert approved["status"] == "APPROVED"


def test_plan_amendment_cycle_revisits_approved(api):
    """PRD §3.3: "A valid amendment moves the plan to `AMENDMENT_REVIEW` with the
    new subjects in place."
    PRD §3.3: "A reviewer then brings it back: `AMENDMENT_REVIEW` → `APPROVED` on
    approval or `AMENDMENT_REVIEW` → `REVISION_REQUESTED` on a revision request,
    recording `reviewer_id` either way, after which the resubmission cycle
    applies as before."
    PRD §2.5: "`version` (integer): a system-managed integer that increments with
    every mutation of the resource."

    Design: Difficulty/non_linear_state_machine/curriculum_plan_revision_cycle
    """
    ctx, plan = _setup_plan(api)
    parent = ctx["parent_headers"]
    get_success_data(api.submit_curriculum_plan(plan["id"], parent))
    approved = get_success_data(
        api.review_curriculum_plan(plan["id"], {"decision": "APPROVE"}, REVIEWER)
    )

    amended = validate_success(
        api.amend_curriculum_plan(
            plan["id"],
            {"subjects": CORE + ["MUSIC"],
             "expected_curriculum_plan_version": approved["version"]},
            parent,
        )
    )
    assert amended["status"] == "AMENDMENT_REVIEW"
    assert_version_incremented(amended["version"], approved["version"])

    reapproved = validate_success(
        api.review_curriculum_plan(plan["id"], {"decision": "APPROVE"}, REVIEWER)
    )
    assert reapproved["status"] == "APPROVED"
    assert_version_incremented(reapproved["version"], amended["version"])
    assert "MUSIC" in reapproved["subjects"], "amendment content survives the cycle"


def test_occ_stale_version_curriculum_amend(api):
    """PRD §2.7: "Amending an approved curriculum plan requires the request body
    to carry `expected_curriculum_plan_version`, the client-side observation of
    the plan's current `version`. An amendment supersedes the currently approved
    subject list, so amending from a stale view would silently overwrite a newer
    approved revision; a mismatch with the plan's current `version` is likewise
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_curriculum_amend
    """
    ctx, plan = _setup_plan(api)
    parent = ctx["parent_headers"]
    get_success_data(api.submit_curriculum_plan(plan["id"], parent))
    approved = get_success_data(
        api.review_curriculum_plan(plan["id"], {"decision": "APPROVE"}, REVIEWER)
    )
    stale_version = approved["version"]

    amended = get_success_data(
        api.amend_curriculum_plan(
            plan["id"],
            {"subjects": CORE + ["MUSIC"], "expected_curriculum_plan_version": stale_version},
            parent,
        )
    )
    assert amended["status"] == "AMENDMENT_REVIEW"
    reapproved = get_success_data(
        api.review_curriculum_plan(plan["id"], {"decision": "APPROVE"}, REVIEWER)
    )
    assert reapproved["status"] == "APPROVED"

    # Replaying the pre-amendment version against the now-APPROVED plan is stale.
    resp = api.amend_curriculum_plan(
        plan["id"],
        {"subjects": CORE + ["ART"], "expected_curriculum_plan_version": stale_version},
        parent,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    current = get_success_data(api.get_curriculum_plan(plan["id"], REGISTRAR))
    assert current["version"] == reapproved["version"]
    assert current["subjects"] == CORE + ["MUSIC"], "second amendment was not applied"


def test_second_plan_rejected(api):
    """PRD §3.3: "Exactly one plan may exist per enrollment — a second attempt
    is refused with `ERR_PLAN_ALREADY_EXISTS` — and it is created as `DRAFT` from
    the parent's proposed `subjects` list."

    Design: Corner/errors/second_plan_rejected
    """
    ctx, _plan = _setup_plan(api)
    resp = api.create_curriculum_plan(
        ctx["enrollment"]["id"], create_curriculum_plan_payload(), ctx["parent_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_ALREADY_EXISTS)


def test_plan_submit_missing_core_subjects(api):
    """PRD §3.3: "Submission, a parent action, requires the plan to cover all
    five core subjects — `READING`, `WRITING`, `MATH`, `SCIENCE`, and
    `SOCIAL_STUDIES` — and a submission missing any of them fails with
    `ERR_PLAN_MISSING_CORE_SUBJECT`; success moves `DRAFT` → `SUBMITTED`."

    Design: Corner/validations/plan_submit_missing_core_subjects
    """
    ctx, plan = _setup_plan(api, subjects=["MATH", "SCIENCE"])
    assert plan["status"] == "DRAFT", "create itself accepts the partial list"
    resp = api.submit_curriculum_plan(plan["id"], ctx["parent_headers"])
    validate_error(resp, ApiErrorId.ERR_PLAN_MISSING_CORE_SUBJECT)
    current = get_success_data(api.get_curriculum_plan(plan["id"], REGISTRAR))
    assert current["status"] == "DRAFT"
