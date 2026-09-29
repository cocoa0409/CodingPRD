"""Endpoint shapes: a partial update, a two-branch action, a computed read, an optional link."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import UNKNOWN_JOB_FAMILY_ID, UNKNOWN_POSTING_ID, UNKNOWN_PROGRAM_ID
from test_helpers.test_users import (
    BRAND_LEAD_USER_ID,
    brand_lead_headers,
    community_manager_headers,
    media_buyer_headers,
)


def test_updating_two_program_fields_leaves_the_other_funding_figures_alone(api):
    """PRD §3.1: "Later on, a lead may adjust the program's funding, its attribution model or its
    send quota; each such adjustment recomputes `available_budget_cents` from the standing definition
    in §2.6, refreshes `updated_at` and advances `version` by 1."
    PRD §2.6: "`committed_budget_cents` is the sum of `delta_cents` over every ledger entry of that
    program, and `available_budget_cents` is the sum of `pool_job_board_cents`, `pool_social_cents`,
    `pool_programmatic_cents`, `flex_reserve_cents` and the `dedicated_budget_cents` of every
    `JobFamily` belonging to that program, less `committed_budget_cents`."
    PRD §2.9: "6. Every path identifier must resolve, left to right, with the per-kind codes of §2.8
    (404)."

    Design: Corner/endpoints/patch_program_updates_only_the_supplied_fields_and_bumps_the_version
    """
    program = fx.create_program(api, pool_job_board_cents=300000, send_quota_total=40)

    response = api.update_program(
        program["id"],
        {"attribution_model": "POSITION_BASED", "pool_social_cents": 150000},
        brand_lead_headers(),
    )
    on_unknown_program = api.update_program(
        UNKNOWN_PROGRAM_ID, {"flex_reserve_cents": 1}, brand_lead_headers()
    )

    patched = validate_success(response, 200)
    assert patched["attribution_model"] == "POSITION_BASED", patched
    a.assert_cents(patched["pool_social_cents"], 150000, "pool_social_cents")
    a.assert_cents(patched["pool_job_board_cents"], 300000, "pool_job_board_cents")
    a.assert_cents(patched["pool_programmatic_cents"], 0, "pool_programmatic_cents")
    a.assert_cents(patched["flex_reserve_cents"], 0, "flex_reserve_cents")
    assert patched["send_quota_total"] == 40, patched
    assert patched["name"] == program["name"], patched
    assert patched["created_at"] == program["created_at"], patched
    assert patched["version"] == 2, patched
    a.assert_program_budget(
        patched, committed_budget_cents=0, available_budget_cents=450000
    )
    validate_error(on_unknown_program, ApiErrorId.PROGRAM_NOT_FOUND, 404)
    listed, meta = validate_paginated(api.list_programs(brand_lead_headers()))
    assert meta["total_count"] == 1, meta
    assert [row["id"] for row in listed] == [program["id"]], listed


def test_the_review_endpoint_can_send_a_persona_back_and_then_approve_the_resubmission(api):
    """PRD §3.3: "Both branches set `reviewed_by_user_id` to the acting `X-User-ID`, store the
    supplied note in `last_review_note`, refresh `updated_at` and advance `version` by 1."
    PRD §3.3: "`REQUEST_REVISION` carries no such mix requirement, moves the persona
    `IN_REVIEW → DRAFT`, and additionally increments `revision_count` by 1."
    PRD §3.3: "Either decision requires the persona to be in `IN_REVIEW`, refusing otherwise with
    `ERR_PERSONA_NOT_IN_REVIEW`, and either decision requires the acting `X-User-ID` to differ from
    `drafted_by_user_id`, refusing otherwise with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.3: "`mix_confidence_pct` is the total `sample_size` across all in-window signals divided
    by 10 and rounded down, then held to a ceiling of 100 — so ten respondents buy one percentage
    point of confidence, and a thousand respondents saturate the scale."

    Design: Corner/endpoints/persona_review_action_endpoint_can_request_a_revision_and_re_approve
    """
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    channel = fx.create_channel(api, program["id"])
    persona = fx.create_persona(api, family["id"])
    fx.add_signal(api, persona["id"], channel["id"], sample_size=400)
    fx.submit_persona(api, persona["id"])

    sent_back = validate_success(
        api.review_candidate_persona(
            persona["id"],
            f.persona_review_payload("REQUEST_REVISION", "add a second channel"),
            brand_lead_headers(),
        ),
        200,
    )
    resubmitted = fx.submit_persona(api, persona["id"])
    approved = validate_success(
        api.review_candidate_persona(
            persona["id"], f.persona_review_payload("APPROVE", "good now"), brand_lead_headers()
        ),
        200,
    )
    replayed = api.review_candidate_persona(
        persona["id"], f.persona_review_payload("APPROVE", "again"), brand_lead_headers()
    )

    assert sent_back["state"] == "DRAFT", sent_back
    assert sent_back["revision_count"] == 1, sent_back
    assert sent_back["reviewed_by_user_id"] == BRAND_LEAD_USER_ID, sent_back
    assert sent_back["last_review_note"] == "add a second channel", sent_back
    assert resubmitted["state"] == "IN_REVIEW", resubmitted
    assert resubmitted["mix_confidence_pct"] == 40, resubmitted
    assert approved["state"] == "APPROVED", approved
    assert approved["revision_count"] == 1, approved
    assert approved["last_review_note"] == "good now", approved
    validate_error(replayed, ApiErrorId.PERSONA_NOT_IN_REVIEW, 409)
    assert fx.read_persona(api, persona["id"])["state"] == "APPROVED"


def test_the_conversion_read_is_null_and_side_effect_free_on_a_posting_with_no_applications(api):
    """PRD §3.4: "`conversion_rate_bp` is null while `apply_start_count` is 0, and otherwise is ten
    thousand multiplied by `submitted_count`, divided by `apply_start_count`, and rounded down to a
    whole basis point."
    PRD §3.4: "On creation the service derives `title_word_count` as the number of
    whitespace-delimited tokens in `title`, and initialises `content_status` to `DRAFT`,
    `compliance_status` to `UNREVIEWED`, `optimization_score` to 0, `apply_start_count`,
    `submitted_count` and `qualified_count` to 0, `conversion_rate_bp` to null, and
    `optimized_by_user_id`, `cleared_by_user_id` and `suspended_reason` all to null."
    PRD §2.9: "6. Every path identifier must resolve, left to right, with the per-kind codes of §2.8
    (404)."

    Design: Corner/endpoints/conversion_computed_read_reports_null_before_any_application_exists
    """
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    posting = fx.create_posting(api, family["id"])

    response = api.get_job_posting_conversion(posting["id"], media_buyer_headers())
    on_unknown_posting = api.get_job_posting_conversion(
        UNKNOWN_POSTING_ID, media_buyer_headers()
    )

    metrics = validate_success(response, 200)
    assert metrics["apply_start_count"] == 0, metrics
    assert metrics["submitted_count"] == 0, metrics
    assert metrics["qualified_count"] == 0, metrics
    assert metrics["conversion_rate_bp"] is None, metrics
    unchanged = fx.read_posting(api, posting["id"])
    assert unchanged["version"] == 1, unchanged
    assert unchanged["updated_at"] == posting["updated_at"], unchanged
    assert unchanged["content_status"] == "DRAFT", unchanged
    assert unchanged["compliance_status"] == "UNREVIEWED", unchanged
    validate_error(on_unknown_posting, ApiErrorId.POSTING_NOT_FOUND, 404)


def test_an_optional_interest_family_is_still_validated_and_then_filterable(api):
    """PRD §2.9: "7. Every foreign key supplied in a request body must resolve to an existing row of
    its declared parent entity, in the order the fields appear in the endpoint's input list, with the
    same per-kind codes (404)."
    PRD §2.8: "Each entity kind reports its own not-found code, and the code is chosen by the *kind
    of thing that failed to resolve*, whether it failed as a path segment or as a body foreign key."
    PRD §3.7: "The registration names the program whose community is being joined, an `email` of 1 to
    200 characters in RFC 5322 shape that must be unique inside that program, and optionally an
    `interest_job_family_id` naming the family the member cares about — null when they expressed no
    preference."
    PRD §4: "List members by program, interest family, consent status or email, in
    dispatch-evaluation order."

    Design: Corner/endpoints/member_join_with_an_unknown_interest_family_returns_not_found
    """
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])

    ghost_link = api.create_talent_community_member(
        f.member_payload(
            program["id"],
            "ghostlink@example.com",
            interest_job_family_id=UNKNOWN_JOB_FAMILY_ID,
        ),
        community_manager_headers(),
    )
    after_the_refusal, refusal_meta = validate_paginated(
        api.list_talent_community_members(
            community_manager_headers(), {"program_id": program["id"]}
        )
    )
    linked = fx.join_community(
        api, program["id"], "linked@example.com", interest_job_family_id=family["id"]
    )
    unlinked = fx.join_community(api, program["id"], "nopreference@example.com")
    filtered, filtered_meta = validate_paginated(
        api.list_talent_community_members(
            community_manager_headers(),
            {"program_id": program["id"], "interest_job_family_id": family["id"]},
        )
    )
    by_program, by_program_meta = validate_paginated(
        api.list_talent_community_members(
            community_manager_headers(), {"program_id": program["id"]}
        )
    )

    validate_error(ghost_link, ApiErrorId.JOB_FAMILY_NOT_FOUND, 404)
    assert after_the_refusal == [], after_the_refusal
    assert refusal_meta["total_count"] == 0, refusal_meta
    assert linked["interest_job_family_id"] == family["id"], linked
    assert unlinked["interest_job_family_id"] is None, unlinked
    assert [row["id"] for row in filtered] == [linked["id"]], filtered
    assert filtered_meta["total_count"] == 1, filtered_meta
    assert [row["id"] for row in by_program] == [linked["id"], unlinked["id"]], by_program
    assert by_program_meta["total_count"] == 2, by_program_meta
