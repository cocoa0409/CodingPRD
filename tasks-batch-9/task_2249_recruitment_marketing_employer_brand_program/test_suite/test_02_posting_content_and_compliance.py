"""Career-site content: optimization revisions, compliance clearance and the publish gates."""
from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    BRAND_LEAD_USER_ID,
    brand_lead_headers,
    persona_researcher_headers,
)


def _family_with_channel(api):
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    channel = fx.create_channel(api, program["id"])
    return program, family, channel


def test_reoptimizing_a_cleared_posting_retracts_its_compliance_clearance(api):
    """PRD §3.3: "It also has a compliance consequence that is easy to miss: if the posting's
    `compliance_status` was `CLEARED`, it is reset to `UNREVIEWED` and `cleared_by_user_id` is
    set back to null, because the text a reviewer cleared has just been superseded."
    PRD §3.3: "note that the `OPTIMIZED → OPTIMIZED` self-transition is entirely legal, each
    call being a new revision that supersedes the prior one."
    PRD §3.3: "And `compliance_status` must be `CLEARED`, or publication is refused with
    `ERR_POSTING_COMPLIANCE_NOT_CLEARED`."

    Design: Difficulty/non_linear_state_machine/posting_optimize_self_transition_retracts_compliance_clearance
    """
    _, family, channel = _family_with_channel(api)
    fx.approved_persona(api, family["id"], channel["id"])
    posting = fx.create_posting(api, family["id"])
    optimized = fx.optimize_posting(api, posting["id"], posting["version"])
    assert optimized["optimization_score"] == 100, optimized
    cleared = fx.clear_posting(api, posting["id"])
    assert cleared["compliance_status"] == "CLEARED", cleared

    revised = fx.optimize_posting(api, posting["id"], cleared["version"], benefit_count=2)

    assert revised["optimization_score"] == 85, revised
    assert revised["content_status"] == "OPTIMIZED", revised
    assert revised["compliance_status"] == "UNREVIEWED", revised
    assert revised["cleared_by_user_id"] is None, revised
    assert revised["optimized_by_user_id"] == BRAND_LEAD_USER_ID, revised

    refused = api.publish_job_posting(posting["id"], brand_lead_headers())
    validate_error(refused, ApiErrorId.POSTING_COMPLIANCE_NOT_CLEARED, 409)
    assert fx.read_posting(api, posting["id"])["content_status"] == "OPTIMIZED"


def test_a_reoptimized_posting_publishes_again_once_it_is_cleared_a_second_time(api):
    """PRD §3.3: "A `CLEAR` decision requires `compliance_status` to be `UNREVIEWED` or
    `FLAGGED`, refusing an already-cleared posting with `ERR_POSTING_ALREADY_CLEARED`."
    PRD §3.3: "Publication from `OPTIMIZED` and publication from `SUSPENDED` are the same
    operation with the same gates, and both set `content_status` to `PUBLISHED`, clear
    `suspended_reason` back to null, refresh `updated_at` and advance `version` by 1."
    PRD §2.4: "Thereafter, every mutation that the service accepts refreshes `updated_at` and
    increments `version` by exactly 1, including mutations that a cascade performed rather than
    the caller requesting directly."

    Design: Difficulty/non_linear_state_machine/posting_optimize_self_transition_retracts_compliance_clearance
    """
    _, family, channel = _family_with_channel(api)
    fx.approved_persona(api, family["id"], channel["id"])
    posting = fx.create_posting(api, family["id"])
    optimized = fx.optimize_posting(api, posting["id"], posting["version"])
    cleared = fx.clear_posting(api, posting["id"])
    revised = fx.optimize_posting(api, posting["id"], cleared["version"], benefit_count=2)

    recleared = fx.clear_posting(api, posting["id"], note="second pass is clean")
    published = fx.publish_posting(api, posting["id"])

    assert recleared["compliance_status"] == "CLEARED", recleared
    assert published["content_status"] == "PUBLISHED", published
    assert published["compliance_status"] == "CLEARED", published
    assert published["optimization_score"] == 85, published
    assert published["suspended_reason"] is None, published
    versions = [
        posting["version"],
        optimized["version"],
        cleared["version"],
        revised["version"],
        recleared["version"],
        published["version"],
    ]
    assert versions == sorted(set(versions)), f"versions must strictly increase: {versions}"


def test_publication_is_refused_while_only_another_families_persona_is_approved(api):
    """PRD §3.3: "At least one persona of the posting's job family must be in state `APPROVED`,
    or publication is refused with `ERR_NO_APPROVED_PERSONA`."

    Design: Difficulty/cross_entity_state_dependency/posting_publish_requires_approved_persona_of_its_own_job_family
    """
    program, engineering, channel = _family_with_channel(api)
    sales = fx.create_job_family(
        api, program["id"], name="Sales", code="SALES", priority_rank=2
    )
    fx.approved_persona(api, sales["id"], channel["id"], name="Enterprise AE")
    engineering_persona = fx.create_persona(api, engineering["id"])
    fx.add_signal(api, engineering_persona["id"], channel["id"])
    submitted = fx.submit_persona(api, engineering_persona["id"])
    assert submitted["state"] == "IN_REVIEW", submitted
    posting = fx.create_posting(api, engineering["id"])
    fx.optimize_posting(api, posting["id"], posting["version"])
    cleared = fx.clear_posting(api, posting["id"])

    refused = api.publish_job_posting(posting["id"], brand_lead_headers())

    validate_error(refused, ApiErrorId.NO_APPROVED_PERSONA, 409)
    unchanged = fx.read_posting(api, posting["id"])
    assert unchanged["content_status"] == "OPTIMIZED", unchanged
    assert unchanged["version"] == cleared["version"], unchanged


def test_approving_the_own_family_persona_unlocks_publication_and_locks_retirement(api):
    """PRD §3.2: "`APPROVE` additionally requires `channel_mix` to be a non-empty array — a
    persona whose mix collapsed to nothing is refused with `ERR_NO_RESEARCH_SIGNALS` — and
    moves the persona `IN_REVIEW → APPROVED`."
    PRD §3.2: "One referential guard applies: if no *other* persona of the same job family is
    in `APPROVED` and at least one job posting of that family has a `content_status` of
    `PUBLISHED` or `SUSPENDED`, the retirement is refused with `ERR_PERSONA_IN_USE`."

    Design: Difficulty/cross_entity_state_dependency/posting_publish_requires_approved_persona_of_its_own_job_family
    """
    program, engineering, channel = _family_with_channel(api)
    sales = fx.create_job_family(
        api, program["id"], name="Sales", code="SALES", priority_rank=2
    )
    fx.approved_persona(api, sales["id"], channel["id"], name="Enterprise AE")
    engineering_persona = fx.create_persona(api, engineering["id"])
    fx.add_signal(api, engineering_persona["id"], channel["id"])
    fx.submit_persona(api, engineering_persona["id"])
    posting = fx.create_posting(api, engineering["id"])
    fx.optimize_posting(api, posting["id"], posting["version"])
    fx.clear_posting(api, posting["id"])

    approved = fx.approve_persona(api, engineering_persona["id"])
    published = fx.publish_posting(api, posting["id"])

    assert approved["state"] == "APPROVED", approved
    assert approved["reviewed_by_user_id"] == BRAND_LEAD_USER_ID, approved
    assert published["content_status"] == "PUBLISHED", published
    assert published["compliance_status"] == "CLEARED", published
    assert published["suspended_reason"] is None, published

    retirement = api.retire_candidate_persona(
        engineering_persona["id"], persona_researcher_headers()
    )
    validate_error(retirement, ApiErrorId.PERSONA_IN_USE, 409)
    assert fx.read_persona(api, engineering_persona["id"])["state"] == "APPROVED"
