"""Entity-level corners of the Adoption Review Press contract.

These tests pin the record shapes the PRD declares before any workflow runs: the
seed values a freshly created edition, state profile, cycle or correlation entry
carries, the uniqueness and enum constraints on their fields, the identifiers
returned when a named record does not exist, and the pagination envelope a list
endpoint reports.
"""

import pytest

from test_helpers import (
    ADOPTION_MODEL_ADOPTION_LIST,
    ADOPTION_MODEL_OPEN_TERRITORY,
    ACCESSIBILITY_WCAG_2_1_AA,
    DEPTH_PRACTICE,
    NON_EXISTENT_UUID,
    PRICING_STATUS_UNPRICED,
    REVIEW_STATUS_DRAFT,
    ROSTERING_ONEROSTER_1_2,
    TITLE_STATUS_DRAFT,
    VERDICT_PENDING,
    ApiErrorId,
    assert_ascending_by_created_at,
    assert_decimal_equals,
    assert_mutable_record,
    assert_page_budget_conserved,
    assert_print_unit_ledger_balances,
    factories,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import seed_cycle, seed_standard, seed_state, seed_title


def test_new_edition_starts_with_an_empty_print_unit_ledger_and_seed_defaults(
    api, publisher_editor_headers
):
    """PRD 3.2: "A `PlatformAdmin` or a `PublisherEditor` creates it with an `isbn_base` of exactly 13 characters, unique across the platform, a `subject` from the same four-member set the frameworks use, a grade band of `grade_low` and `grade_high` obeying the same 0-to-12 rules as a standard, a `copyright_year` between 2015 and 2100 inclusive, an `edition_number` that defaults to 1 and must be at least 1, a `page_count` of at least 1, a `signature_page_capacity` that must be at least the creation `page_count`, a `list_price_cents` of at least 1, and an optional array of `content_tags` — uppercase snake_case tags, at most 40 of them — describing the topics and content actually present in the edition."

    PRD 3.2: "On creation, `page_budget_remaining` is set to `signature_page_capacity` minus `page_count`, `content_revision` is set to 1, every inventory counter is set to 0, and `status` is `DRAFT`."
    PRD 3.2: "The `adopted_state_codes` array records the `state_code` of every state where a submission of this edition reached an adopted status, and it is written only by the committee tally of Section 3.8."
    PRD 2.4: "Most resources additionally carry `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the record — and `version`, an integer that starts at 1 on creation and increments by 1 on every mutation."
    PRD 2.10: "The **print-unit ledger** of a title states that `total_received_units` always equals the sum of `on_hand_units`, `committed_units`, `sample_reserved_units`, `fulfilled_units` and `written_off_units`."
    PRD 2.10: "The **signature page budget** of a title states that `page_count` plus `page_budget_remaining` always equals `signature_page_capacity`, the immutable press signature capacity fixed when the edition was created."
    PRD 4: "Operations that mint a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or read data return `200 OK`."

    Design: Corner/entities/title_create_seeds_ledger_and_page_budget_defaults
    """
    # Neither edition_number nor content_tags is supplied: both must take their
    # declared creation values.
    payload = factories.title_payload(
        subject="MATH",
        grade_low=6,
        grade_high=8,
        page_count=400,
        signature_page_capacity=480,
        list_price_cents=9400,
        content_tags=None,
    )

    title = validate_success(
        api.create_title(payload, publisher_editor_headers), expected_status=201
    )

    assert title["edition_number"] == 1
    assert title["content_tags"] == []
    assert title["status"] == TITLE_STATUS_DRAFT
    assert title["content_revision"] == 1
    assert title["adopted_state_codes"] == []

    assert title["page_count"] == 400
    assert title["signature_page_capacity"] == 480
    assert title["page_budget_remaining"] == 80
    assert_page_budget_conserved(title)

    for bucket in (
        "total_received_units",
        "on_hand_units",
        "committed_units",
        "sample_reserved_units",
        "fulfilled_units",
        "written_off_units",
    ):
        assert title[bucket] == 0, f"{bucket} must start at 0, got {title[bucket]!r}"
    assert_print_unit_ledger_balances(title)

    assert_mutable_record(title)
    assert title["version"] == 1


def test_state_profile_omitting_its_policy_fields_takes_every_declared_default(
    api, platform_admin_headers
):
    """PRD 3.1: "The rest of the profile describes what the state demands of publishers, and each field has a default that applies when the field is omitted."

    PRD 3.1: "`sampling_copies_required` is the number of print sample copies that must reach the state before a submission may be filed; it defaults to 0 and must be between 0 and 50 inclusive."
    PRD 3.1: "`comment_response_days` is the number of calendar days the publisher has to answer a public comment before it escalates; it defaults to 10 and must be between 1 and 60 inclusive."
    PRD 3.1: "`required_topics` and `prohibited_content_tags` are arrays of uppercase snake_case codes, each defaulting to empty and each capped at 20 entries — the first names topics that must be present in submitted content, the second names tags the state forbids in adopted instructional materials."
    PRD 3.1: "`multi_year_max_years` caps the contract term a price filing may commit to; it defaults to 6 and must be between 1 and 10 inclusive."
    PRD 3.1: "`price_cap_cents` is the maximum net state price the state accepts per copy across a whole term; it defaults to null, meaning uncapped, and when supplied must be at least 1."
    PRD 3.1: "`min_verified_coverage_pct` is the minimum correlation coverage percentage; it defaults to 85.00, must lie between 0.00 and 100.00, and is carried at two decimals."
    PRD 2.11: "Each `StateProfile` declares an `accessibility_standard` — either `WCAG_2_1_AA` or `WCAG_2_2_AA`, defaulting to `WCAG_2_1_AA` — a `rostering_standard` chosen from `ONEROSTER_1_1`, `ONEROSTER_1_2` and `CSV_MANUAL`, defaulting to `ONEROSTER_1_2`, and a boolean `data_privacy_addendum_required` that defaults to true."

    Design: Corner/entities/state_profile_policy_defaults_applied_when_omitted
    """
    payload = factories.state_profile_payload(
        "AL",
        adoption_model=ADOPTION_MODEL_ADOPTION_LIST,
        sampling_copies_required=None,
        min_verified_coverage_pct=None,
    )
    assert set(payload) == {"state_code", "adoption_model"}

    state = validate_success(
        api.create_state_profile(payload, platform_admin_headers), expected_status=201
    )

    assert state["state_code"] == "AL"
    assert state["adoption_model"] == ADOPTION_MODEL_ADOPTION_LIST
    assert state["sampling_copies_required"] == 0
    assert state["comment_response_days"] == 10
    assert state["required_topics"] == []
    assert state["prohibited_content_tags"] == []
    assert state["multi_year_max_years"] == 6
    assert state["price_cap_cents"] is None
    assert_decimal_equals(
        state["min_verified_coverage_pct"], "85.00", "min_verified_coverage_pct"
    )
    assert state["accessibility_standard"] == ACCESSIBILITY_WCAG_2_1_AA
    assert state["rostering_standard"] == ROSTERING_ONEROSTER_1_2
    assert state["data_privacy_addendum_required"] is True


def test_a_second_profile_for_the_same_state_code_is_refused_as_a_duplicate(
    api, platform_admin_headers
):
    """PRD 3.1: "A `PlatformAdmin` registers an adopting state by supplying its `state_code` — exactly two uppercase letters, unique across the whole platform — and its `adoption_model`, which is either `ADOPTION_LIST` for a state that publishes an adopted list districts must buy from, or `OPEN_TERRITORY` for a state whose districts buy directly."

    PRD 3.1: "A duplicate `state_code` is refused with `ERR_DUPLICATE_RESOURCE`."
    PRD 2.6: "Request shape — required fields present, types correct, enum members recognized, numeric ranges honoured, ISO 8601 datetimes parseable, `limit` between 1 and 100 inclusive, `offset` at least 0, else `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

    Design: Corner/entities/state_code_uniqueness_rejects_second_profile
    """
    first = validate_success(
        api.create_state_profile(
            factories.state_profile_payload(
                "AK", adoption_model=ADOPTION_MODEL_OPEN_TERRITORY
            ),
            platform_admin_headers,
        ),
        expected_status=201,
    )

    duplicate = api.create_state_profile(
        factories.state_profile_payload(
            "AK", adoption_model=ADOPTION_MODEL_ADOPTION_LIST
        ),
        platform_admin_headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_RESOURCE, expected_status=409)

    # A state code is exactly two uppercase letters, so the lowercase form never
    # reaches the uniqueness check at all.
    lowercase = api.create_state_profile(
        factories.state_profile_payload(
            "ak", adoption_model=ADOPTION_MODEL_ADOPTION_LIST
        ),
        platform_admin_headers,
    )
    validate_error(lowercase, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    surviving = validate_success(
        api.get_state_profile(first["id"], platform_admin_headers)
    )
    assert surviving["id"] == first["id"]
    assert surviving["state_code"] == "AK"
    assert surviving["adoption_model"] == ADOPTION_MODEL_OPEN_TERRITORY


def test_opening_a_cycle_without_naming_its_subject_is_rejected_on_shape(api):
    """PRD 3.1: "The cycle names its `subject` and its `cycle_year`, an adoption year label between 2020 and 2100 inclusive, together with six phase timestamps that must be supplied in non-decreasing order with two strict steps: `submission_deadline_at` must be strictly after `submission_open_at`; `committee_review_at` must be at or after `submission_deadline_at`; `public_comment_start_at` must be at or after `committee_review_at`; `public_comment_end_at` must be strictly after `public_comment_start_at`; and `adoption_decision_at` must be at or after `public_comment_end_at`."

    PRD 2.6: "Request shape — required fields present, types correct, enum members recognized, numeric ranges honoured, ISO 8601 datetimes parseable, `limit` between 1 and 100 inclusive, `offset` at least 0, else `ERR_INVALID_REQUEST` (400). Applies to every endpoint."
    PRD 2.6: "More broadly, when several checks could reject one request, they are evaluated in a fixed order and the **first** failing check supplies the response."

    Design: Corner/entities/adoption_cycle_create_missing_required_field_rejected
    """
    world = seed_state(api, "HI", adoption_model=ADOPTION_MODEL_OPEN_TERRITORY)

    payload = factories.adoption_cycle_payload(world.state_id, cycle_year=2027)
    payload.pop("subject")

    response = api.create_adoption_cycle(payload, world.officer)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    cycles, meta = validate_paginated(
        api.list_adoption_cycles(world.officer, {"state_id": world.state_id})
    )
    assert meta["total_count"] == 0, "A rejected request must not create a cycle"
    assert cycles == []


def test_a_correlation_entry_claiming_an_unknown_depth_level_is_rejected(
    api, publisher_editor_headers
):
    """PRD 3.4: "While the submission is `DRAFT`, its `PublisherEditor` adds correlation entries one at a time, each naming a `standard_code` of 1 to 40 characters, a `depth_level` of `MENTION`, `PRACTICE` or `MASTERY` claiming how deeply the content treats the standard, a `page_reference` of 1 to 40 characters locating the treatment in the edition, and an `evidence_citation` of at least 20 and at most 500 characters quoting the material verbatim."

    PRD 2.6: "Request shape — required fields present, types correct, enum members recognized, numeric ranges honoured, ISO 8601 datetimes parseable, `limit` between 1 and 100 inclusive, `offset` at least 0, else `ERR_INVALID_REQUEST` (400). Applies to every endpoint."
    PRD 3.4: "If there are no candidates, the standard contributes nothing."
    PRD 3.4: "The coverage percentage is then 100 multiplied by the numerator, divided by the denominator, rounded half up to 2 decimal places, and finally capped at 100.00."

    Design: Corner/entities/correlation_invalid_depth_level_enum_rejected
    """
    world = seed_state(api, "DE", adoption_model=ADOPTION_MODEL_OPEN_TERRITORY)
    seed_standard(
        api, world, "DE.M.5.1", subject="MATH", grade_low=5, grade_high=5, weight=2
    )
    seed_cycle(api, world, subject="MATH", cycle_year=2027)
    seed_title(api, world, subject="MATH", grade_low=5, grade_high=5)

    submission = get_success_data(
        api.create_submission(
            factories.submission_payload(world.cycle_id, world.title_id),
            publisher_editor_headers,
        )
    )

    response = api.create_correlation(
        submission["id"],
        factories.correlation_payload("DE.M.5.1", depth_level="SURVEY"),
        publisher_editor_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    entries, meta = validate_paginated(
        api.list_correlations(submission["id"], publisher_editor_headers)
    )
    assert meta["total_count"] == 0, "A rejected citation must not be stored"
    assert entries == []

    after = validate_success(
        api.get_submission(submission["id"], publisher_editor_headers)
    )
    assert_decimal_equals(
        after["self_reported_coverage_pct"], "0.00", "self_reported_coverage_pct"
    )


def test_reading_a_submission_that_does_not_exist_reports_it_as_not_found(
    api, publisher_editor_headers
):
    """PRD 2.6: "A `/submissions` path identifier resolves to a `Submission`, else `ERR_SUBMISSION_NOT_FOUND` (404) — on reading a submission and on every one of its sub-resource operations."

    Design: Corner/entities/get_submission_with_unknown_id_returns_not_found
    """
    response = api.get_submission(NON_EXISTENT_UUID, publisher_editor_headers)

    validate_error(
        response, ApiErrorId.ERR_SUBMISSION_NOT_FOUND, expected_status=404
    )
    assert response.json()["response_type"] == "error"


def test_starting_a_submission_against_an_absent_edition_reports_the_reference_missing(
    api, publisher_editor_headers
):
    """PRD 2.6: "Every foreign key supplied in a request body — `state_id`, `cycle_id`, `title_id`, `submission_id`, `bundle_id`, `pricing_proposal_id` — resolves to an existing record, else `ERR_REFERENCED_RESOURCE_NOT_FOUND` (404). Applies to creating a cycle, a content edit, a submission, a panel, a slot, a pricing proposal and a district order."

    PRD 3.1: "New cycles are born `SCHEDULED` with `phase_epoch` at 0 and every submission counter at 0."
    PRD 3.1: "`submission_count` is the number of the cycle's submissions whose `review_status` is `FILED`, `SCHEDULED` or `PRESENTED`."

    Design: Corner/entities/create_submission_referencing_absent_title_returns_not_found
    """
    world = seed_state(api, "ND", adoption_model=ADOPTION_MODEL_OPEN_TERRITORY)
    cycle_id = seed_cycle(api, world, subject="MATH", cycle_year=2027)

    response = api.create_submission(
        factories.submission_payload(cycle_id, NON_EXISTENT_UUID),
        publisher_editor_headers,
    )
    validate_error(
        response, ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND, expected_status=404
    )

    cycle = validate_success(api.get_adoption_cycle(cycle_id, world.officer))
    assert cycle["submission_count"] == 0


def test_the_submission_list_pages_one_cycle_with_a_total_count_and_has_more(
    api, publisher_editor_headers
):
    """PRD 2.3: "`offset` is the number of records to skip before the first returned record; it defaults to 0 and its minimum accepted value is 0."

    PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`. `total_count` is the number of records matching the request's filters before pagination is applied, and `has_more` is true when records matching the filters remain beyond the returned page."
    PRD 2.3: "Unless a specific endpoint says otherwise, every list endpoint returns its records sorted by `created_at` in ascending order."
    PRD 3.4: "Submissions can be listed and filtered by `cycle_id`, `title_id`, `review_status`, `pricing_status` and `adoption_blocked`."
    PRD 3.4: "The new record is born with `review_status` `DRAFT` and `pricing_status` `UNPRICED` — the two dimensions of the submission lifecycle advance independently of each other, and neither gates the other's transitions."

    Design: Corner/entities/submission_list_paginates_with_total_count_and_has_more
    """
    world = seed_state(api, "IA", adoption_model=ADOPTION_MODEL_OPEN_TERRITORY)
    cycle_id = seed_cycle(api, world, subject="SCIENCE", cycle_year=2027)

    submission_ids = []
    for page_count in (300, 305, 310):
        title_id = seed_title(
            api,
            world,
            subject="SCIENCE",
            grade_low=7,
            grade_high=7,
            page_count=page_count,
            content_tags=["LAB_SAFETY"],
        )
        submission = get_success_data(
            api.create_submission(
                factories.submission_payload(cycle_id, title_id),
                publisher_editor_headers,
            )
        )
        submission_ids.append(submission["id"])

    first_rows, first_meta = validate_paginated(
        api.list_submissions(
            publisher_editor_headers,
            {"cycle_id": cycle_id, "limit": 2, "offset": 0},
        )
    )
    assert len(first_rows) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert_ascending_by_created_at(first_rows)

    second_rows, second_meta = validate_paginated(
        api.list_submissions(
            publisher_editor_headers,
            {"cycle_id": cycle_id, "limit": 2, "offset": 2},
        )
    )
    assert len(second_rows) == 1
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    paged = first_rows + second_rows
    assert sorted(row["id"] for row in paged) == sorted(submission_ids)
    for row in paged:
        assert row["cycle_id"] == cycle_id
        assert row["review_status"] == REVIEW_STATUS_DRAFT
        assert row["pricing_status"] == PRICING_STATUS_UNPRICED


def test_a_practice_citation_weighs_the_standard_by_its_depth_multiplier(
    api, publisher_editor_headers
):
    """PRD 3.4: "Each entry also stores an `effective_weight`, the cited standard's `weight` multiplied by the depth multiplier of the claimed `depth_level`, rounded half up to 2 decimal places."

    PRD 3.4: "The depth multipliers are 0.40 for `MENTION`, 0.70 for `PRACTICE` and 1.00 for `MASTERY`."
    PRD 3.4: "The entry's `submission_id` is taken from the path and its `reviewer_verdict` starts at `PENDING`."
    PRD 3.4: "The denominator is the sum of `weight` over that set."
    PRD 3.4: "The coverage percentage is then 100 multiplied by the numerator, divided by the denominator, rounded half up to 2 decimal places, and finally capped at 100.00."
    PRD 3.4: "The **self-reported** variant accepts entries whose `reviewer_verdict` is `PENDING` or `ACCEPTED` — the publisher's own claim, which counts evidence the committee has not yet looked at — and is stored in `self_reported_coverage_pct`; it is the gate at filing time."
    PRD 3.4: "The **committee-verified** variant accepts only entries whose `reviewer_verdict` is `ACCEPTED`, discarding both `PENDING` and `INSUFFICIENT` evidence, and is stored in `verified_coverage_pct`; it is the gate at adoption time."
    PRD 4: "Operations that mint a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or read data return `200 OK`."

    Design: Corner/entities/correlation_entry_effective_weight_is_computed_from_standard_weight
    """
    world = seed_state(api, "RI", adoption_model=ADOPTION_MODEL_OPEN_TERRITORY)
    seed_standard(
        api, world, "RI.E.4.1", subject="ELA", grade_low=4, grade_high=4, weight=3
    )
    seed_cycle(api, world, subject="ELA", cycle_year=2027)
    seed_title(
        api,
        world,
        subject="ELA",
        grade_low=4,
        grade_high=4,
        page_count=290,
        content_tags=["CLOSE_READING"],
    )

    submission = get_success_data(
        api.create_submission(
            factories.submission_payload(world.cycle_id, world.title_id),
            publisher_editor_headers,
        )
    )

    entry = validate_success(
        api.create_correlation(
            submission["id"],
            factories.correlation_payload("RI.E.4.1", depth_level=DEPTH_PRACTICE),
            publisher_editor_headers,
        ),
        expected_status=201,
    )

    # Weight 3 at the PRACTICE multiplier of 0.70.
    assert entry["submission_id"] == submission["id"]
    assert entry["depth_level"] == DEPTH_PRACTICE
    assert_decimal_equals(entry["effective_weight"], "2.10", "effective_weight")
    assert entry["reviewer_verdict"] == VERDICT_PENDING

    # The lone standard of the framework carries the whole denominator of 3, so
    # the self-reported claim is 100 * 2.10 / 3, while nothing is yet accepted.
    after = validate_success(
        api.get_submission(submission["id"], publisher_editor_headers)
    )
    assert_decimal_equals(
        after["self_reported_coverage_pct"], "70.00", "self_reported_coverage_pct"
    )
    assert_decimal_equals(
        after["verified_coverage_pct"], "0.00", "verified_coverage_pct"
    )
