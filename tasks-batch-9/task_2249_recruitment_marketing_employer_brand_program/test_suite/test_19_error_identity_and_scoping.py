"""Which error id fires, and how wide the uniqueness and not-found scopes really are."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    UNKNOWN_LEDGER_ENTRY_ID,
    UNKNOWN_NURTURE_SEND_ID,
    UNKNOWN_POSTING_ID,
    UNKNOWN_TOUCHPOINT_ID,
)
from test_helpers.test_users import (
    brand_lead_headers,
    community_manager_headers,
    media_buyer_headers,
    recruiting_ops_headers,
)


def test_a_family_code_may_repeat_in_a_second_program_but_never_inside_one(api):
    """PRD §2.11: "A `JobFamily`'s `code` must be unique within its program, and a collision is
    rejected with `ERR_DUPLICATE_FAMILY_CODE`."
    PRD §2.11: "Note the scoping carefully: the same family code in two different programs is legal,
    as is the same external reference on two different review platforms."
    PRD §2.9: "10. Scoped uniqueness on job-family creation, talent-community registration and
    employer-review ingestion, with the three codes of §2.11 (409)."

    Design: Corner/errors/duplicate_family_code_is_scoped_to_one_program
    """
    program_a = fx.create_program(api, name="Program A")
    program_b = fx.create_program(api, name="Program B")
    family_a = fx.create_job_family(api, program_a["id"])

    collision = api.create_job_family(
        f.job_family_payload(
            program_a["id"],
            name="Software Engineering Duplicate",
            code="SWE",
            cpqa_target_cents=16000,
            priority_rank=2,
        ),
        brand_lead_headers(),
    )
    accepted = api.create_job_family(
        f.job_family_payload(program_b["id"]), brand_lead_headers()
    )

    validate_error(collision, ApiErrorId.DUPLICATE_FAMILY_CODE, 409)
    family_b = validate_success(accepted, 201)
    assert family_b["code"] == "SWE", family_b
    assert family_b["program_id"] == program_b["id"], family_b
    rows, meta = validate_paginated(
        api.list_job_families(brand_lead_headers(), {"code": "SWE"})
    )
    assert meta["total_count"] == 2, meta
    assert sorted(row["id"] for row in rows) == sorted([family_a["id"], family_b["id"]]), rows
    assert sorted(row["program_id"] for row in rows) == sorted(
        [program_a["id"], program_b["id"]]
    ), rows


def test_member_email_is_scoped_to_a_program_while_a_review_reference_is_scoped_to_a_platform(api):
    """PRD §2.11: "A `TalentCommunityMember`'s `email` must be unique within its program, and a
    collision is rejected with `ERR_DUPLICATE_MEMBER_EMAIL`."
    PRD §2.11: "An `EmployerReview`'s `external_ref` must be unique within its `platform`, and a
    collision is rejected with `ERR_DUPLICATE_REVIEW_REF`."
    PRD §2.11: "Three uniqueness constraints are scoped rather than global."

    Design: Corner/errors/duplicate_member_email_and_duplicate_review_reference_use_different_scopes
    """
    program = fx.create_program(api)
    other_program = fx.create_program(api, name="Second Program")
    member = fx.join_community(api, program["id"], "dup@example.com")
    review = fx.ingest_review(
        api,
        program["id"],
        platform="GLASSDOOR",
        external_ref="ref-1",
        rating=4,
        posted_at="2026-07-30T00:00:00Z",
    )

    same_email_same_program = api.create_talent_community_member(
        f.member_payload(program["id"], "dup@example.com"), community_manager_headers()
    )
    same_email_other_program = api.create_talent_community_member(
        f.member_payload(other_program["id"], "dup@example.com"), community_manager_headers()
    )
    same_ref_same_platform = api.create_employer_review(
        f.review_payload(
            program["id"],
            platform="GLASSDOOR",
            external_ref="ref-1",
            rating=2,
            posted_at="2026-07-31T00:00:00Z",
        ),
        community_manager_headers(),
    )
    same_ref_other_platform = api.create_employer_review(
        f.review_payload(
            program["id"],
            platform="INDEED",
            external_ref="ref-1",
            rating=2,
            posted_at="2026-07-31T00:00:00Z",
        ),
        community_manager_headers(),
    )

    validate_error(same_email_same_program, ApiErrorId.DUPLICATE_MEMBER_EMAIL, 409)
    second_member = validate_success(same_email_other_program, 201)
    assert second_member["email"] == member["email"], second_member
    assert second_member["program_id"] == other_program["id"], second_member
    validate_error(same_ref_same_platform, ApiErrorId.DUPLICATE_REVIEW_REF, 409)
    indeed_review = validate_success(same_ref_other_platform, 201)
    assert indeed_review["external_ref"] == review["external_ref"], indeed_review
    assert indeed_review["platform"] == "INDEED", indeed_review
    assert indeed_review["id"] != review["id"], indeed_review


def test_the_four_event_collections_share_one_generic_not_found_code(api):
    """PRD §2.8: "The four immutable event collections — channel-preference signals, touchpoints,
    nurture send-evaluation rows and budget ledger entries — share a single code,
    `ERR_RECORD_NOT_FOUND`, when the addressed row does not exist."
    PRD §2.8: "Each entity kind reports its own not-found code, and the code is chosen by the *kind
    of thing that failed to resolve*, whether it failed as a path segment or as a body foreign key."
    PRD §2.8: "All eleven of these codes carry HTTP 404."

    Design: Corner/errors/unknown_touchpoint_id_returns_record_not_found
    """
    unknown_touchpoint = api.get_touchpoint(UNKNOWN_TOUCHPOINT_ID, recruiting_ops_headers())
    unknown_send = api.get_nurture_send(UNKNOWN_NURTURE_SEND_ID, community_manager_headers())
    unknown_entry = api.get_budget_ledger_entry(UNKNOWN_LEDGER_ENTRY_ID, brand_lead_headers())
    unknown_posting = api.get_job_posting(UNKNOWN_LEDGER_ENTRY_ID, brand_lead_headers())

    for response in (unknown_touchpoint, unknown_send, unknown_entry):
        validate_error(response, ApiErrorId.RECORD_NOT_FOUND, 404)
    validate_error(unknown_posting, ApiErrorId.POSTING_NOT_FOUND, 404)


def test_an_organic_channel_cannot_carry_paid_media_but_still_carries_touchpoints(api):
    """PRD §2.9: "30. A paid flight's channel must have a `channel_type` of `JOB_BOARD`, `SOCIAL` or
    `PROGRAMMATIC`, else `ERR_CHANNEL_NOT_PAYABLE` (409)."
    PRD §3.5: "The channel's `channel_type` must be `JOB_BOARD`, `SOCIAL` or `PROGRAMMATIC`; a
    career-site, event or email channel cannot carry paid media and the request is refused with
    `ERR_CHANNEL_NOT_PAYABLE`."
    PRD §3.2: "Only the first three of those may ever carry paid media; the other three exist so that
    organic, event and email touches can be attributed to a real channel record."

    Design: Corner/errors/flight_on_a_career_site_channel_returns_channel_not_payable
    """
    program = fx.create_program(api, pool_job_board_cents=1000000)
    family = fx.create_job_family(api, program["id"])
    organic = fx.create_channel(
        api, program["id"], name="Careers Site", channel_type="CAREER_SITE"
    )
    posting = fx.published_posting(api, family["id"], organic["id"])
    program_version = fx.program_version(api, program["id"])

    refused = api.create_media_flight(
        f.flight_payload(
            organic["id"],
            family["id"],
            posting["id"],
            program_version,
            start_date="2026-08-05",
            end_date="2026-08-10",
            daily_cap_cents=50000,
        ),
        media_buyer_headers(),
    )
    application = fx.start_application(api, posting["id"], "organic@example.com")
    touch = fx.add_touchpoint(
        api,
        application["id"],
        organic["id"],
        "2026-08-01T09:00:00Z",
        touch_type="ORGANIC_VISIT",
    )

    validate_error(refused, ApiErrorId.CHANNEL_NOT_PAYABLE, 409)
    assert fx.list_flights(api, channel_id=organic["id"]) == []
    assert fx.list_ledger_entries(api, program_id=program["id"]) == []
    assert fx.program_version(api, program["id"]) == program_version
    assert touch["channel_id"] == organic["id"], touch
    assert touch["touch_type"] == "ORGANIC_VISIT", touch
    assert touch["media_flight_id"] is None, touch
    assert touch["credit_bp"] == 0, touch


def test_pagination_bounds_are_a_closed_interval_rejected_only_from_outside(api):
    """PRD §2.3: "A `limit` that is not an integer inside the inclusive range of 1 through 100, or an
    `offset` that is not an integer of zero or greater, is rejected with `ERR_INVALID_PAGINATION`
    (HTTP 400)."
    PRD §2.3: "`limit` controls page size: it defaults to 10, its minimum accepted value is 1, and
    its maximum accepted value is 100."
    PRD §2.9: "5. On every list endpoint, `limit` must be an integer from 1 through 100 and `offset`
    an integer of zero or more, else `ERR_INVALID_PAGINATION` (400)."

    Design: Corner/errors/list_endpoints_reject_limit_zero_and_negative_offset_with_invalid_pagination
    """
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])

    limit_zero = api.list_job_families(
        brand_lead_headers(), {"program_id": program["id"], "limit": 0}
    )
    limit_over = api.list_job_families(
        brand_lead_headers(), {"program_id": program["id"], "limit": 101}
    )
    negative_offset = api.list_job_families(
        brand_lead_headers(), {"program_id": program["id"], "offset": -1}
    )
    upper_bound = api.list_job_families(
        brand_lead_headers(), {"program_id": program["id"], "limit": 100, "offset": 0}
    )
    lower_bound = api.list_job_families(
        brand_lead_headers(), {"program_id": program["id"], "limit": 1}
    )
    ledger_limit_zero = api.list_budget_ledger_entries(
        brand_lead_headers(), {"program_id": program["id"], "limit": 0}
    )

    for response in (limit_zero, limit_over, negative_offset, ledger_limit_zero):
        validate_error(response, ApiErrorId.INVALID_PAGINATION, 400)
    widest, widest_meta = validate_paginated(upper_bound)
    assert [row["id"] for row in widest] == [family["id"]], widest
    assert widest_meta["limit"] == 100, widest_meta
    assert widest_meta["has_more"] is False, widest_meta
    narrowest, narrowest_meta = validate_paginated(lower_bound)
    assert [row["id"] for row in narrowest] == [family["id"]], narrowest
    assert narrowest_meta["limit"] == 1, narrowest_meta
    assert narrowest_meta["total_count"] == 1, narrowest_meta
