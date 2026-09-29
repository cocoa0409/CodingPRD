"""The cross-cutting layers: optimistic concurrency on both pinned parents, derived-counter
reconciliation, the soft-delete's surviving history, list paging, and immediate consistency."""

from test_helpers import (
    ApiErrorId,
    EXPECTED_AB_BOOK,
    EXPECTED_SLIM_BOOK,
    TEST_USERS,
    api_client,
    append_collection_record,
    assert_instant_equals,
    assert_money_equals,
    assert_ratio_equals,
    create_assessment_payload,
    create_offer_payload,
    make_committee_chair_headers,
    read_assessment,
    read_candidate,
    read_client_book_entry,
    read_practice_group,
    read_questionnaire,
    request_revision_payload,
    setup_approved_offer,
    setup_assessed_candidate,
    setup_book,
    setup_questionnaire_in_draft,
    setup_questionnaire_under_review,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]
CHAIR = make_committee_chair_headers("user-chair-1")

UNVERIFIED_RECORD = {
    "record_type": "HISTORICAL",
    "period_end_date": "2026-06-30T00:00:00.000Z",
    "amount_usd": 700000.00,
    "status": "UNVERIFIED",
}


def test_each_pinned_parent_advances_by_one_and_refuses_the_version_it_just_burned():
    """A new assessment supersedes every prior assessment on the same questionnaire and
    rewrites `latest_assessment_id`, so a caller holding an outdated version is valuing a client
    book it has not fully read.
    Creating an assessment writes it with `status` `CURRENT`, turns every earlier assessment on
    the same questionnaire whose `status` is `CURRENT` or `STALE` to `SUPERSEDED`, writes the new
    assessment's identifier into the questionnaire's `latest_assessment_id`, and increments the
    questionnaire's `version` by 1.
    Creation also writes the offer's identifier into the candidate's `open_offer_id` and
    increments the candidate's `version` by 1 — which is exactly why the next writer's
    `expected_candidate_version` must be refreshed.

    Design: Corner/cross_cutting_complexity_layers/both_occ_guards_bump_their_parent_version_by_exactly_one
    """
    ctx = setup_questionnaire_under_review("SLIM")
    questionnaire_id = ctx["questionnaire"]["id"]
    candidate_id = ctx["candidate"]["id"]

    lpq_v1 = read_questionnaire(questionnaire_id)["version"]
    candidate_v1 = read_candidate(candidate_id)["version"]

    first = validate_success(
        api_client.create_portability_assessment(
            questionnaire_id, create_assessment_payload(lpq_v1), COORDINATOR
        ),
        expected_status=201,
    )

    replayed_assessment = api_client.create_portability_assessment(
        questionnaire_id, create_assessment_payload(lpq_v1), COORDINATOR
    )
    questionnaire_error = validate_error(
        replayed_assessment, ApiErrorId.ERR_STALE_QUESTIONNAIRE_VERSION.value, 412
    )

    lpq_v2 = read_questionnaire(questionnaire_id)["version"]
    assert lpq_v2 == lpq_v1 + 1

    second = validate_success(
        api_client.create_portability_assessment(
            questionnaire_id, create_assessment_payload(lpq_v2), COORDINATOR
        ),
        expected_status=201,
    )

    validate_success(
        api_client.create_offer(
            candidate_id,
            create_offer_payload(
                second["id"],
                candidate_v1,
                guaranteed_comp_usd=400000.00,
                signing_bonus_usd=40000.00,
            ),
            CHAIR,
        ),
        expected_status=201,
    )

    replayed_offer = api_client.create_offer(
        candidate_id,
        create_offer_payload(
            second["id"],
            candidate_v1,
            guaranteed_comp_usd=400000.00,
            signing_bonus_usd=40000.00,
        ),
        CHAIR,
    )
    candidate_error = validate_error(
        replayed_offer, ApiErrorId.ERR_STALE_CANDIDATE_VERSION.value, 412
    )
    assert questionnaire_error["error_id"] != candidate_error["error_id"]

    candidate_v2 = read_candidate(candidate_id)["version"]
    assert candidate_v2 == candidate_v1 + 1

    later_offer = validate_success(
        api_client.create_offer(
            candidate_id,
            create_offer_payload(
                second["id"],
                candidate_v2,
                guaranteed_comp_usd=400000.00,
                signing_bonus_usd=40000.00,
            ),
            CHAIR,
        ),
        expected_status=201,
    )

    assert read_assessment(first["id"])["status"] == "SUPERSEDED"
    assert read_assessment(second["id"])["status"] == "CURRENT"
    assert_money_equals(
        second["adjusted_portable_total_usd"],
        EXPECTED_SLIM_BOOK["adjusted_portable_total_usd"],
        "adjusted_portable_total_usd",
    )
    assert read_questionnaire(questionnaire_id)["latest_assessment_id"] == second["id"]

    assert later_offer["status"] == "DRAFTED"
    assert_money_equals(
        later_offer["adjusted_portable_total_snapshot_usd"],
        EXPECTED_SLIM_BOOK["adjusted_portable_total_usd"],
        "adjusted_portable_total_snapshot_usd",
    )
    assert_money_equals(
        later_offer["net_first_year_economics_usd"],
        401381.27,
        "net_first_year_economics_usd",
    )
    assert read_candidate(candidate_id)["open_offer_id"] == later_offer["id"]
    assert_money_equals(
        read_practice_group(ctx["practice_group"]["id"])["reserved_guarantee_budget_usd"],
        0.00,
        "reserved_guarantee_budget_usd",
    )


def test_the_entry_count_and_the_portable_book_identity_both_follow_the_withdrawal():
    """Soft-deleting an entry sets its `status` to `WITHDRAWN`, decrements the questionnaire's
    `entry_count` by 1, and likewise turns any `CURRENT` assessment on that questionnaire
    `STALE`.
    The **portable book identity** holds on every `PortabilityAssessment`:
    `validated_portable_total_usd` plus `declined_portable_total_usd` always equals
    `gross_baseline_total_usd`, exactly, to the cent.

    Design: Corner/cross_cutting_complexity_layers/derived_counters_and_ledger_totals_reconcile_after_a_soft_delete
    """
    ctx = setup_questionnaire_in_draft()
    setup_book(ctx, "AB")
    questionnaire_id = ctx["questionnaire"]["id"]
    entry_a_id = ctx["entries"]["Northwind Holdings"]["id"]
    entry_b_id = ctx["entries"]["Calder Manufacturing"]["id"]

    assert read_questionnaire(questionnaire_id)["entry_count"] == 2

    validate_success(
        api_client.delete_client_book_entry(entry_b_id, ctx["candidate_headers"])
    )
    assert read_questionnaire(questionnaire_id)["entry_count"] == 1
    assert read_client_book_entry(entry_a_id)["verified_record_count"] == 3

    validate_success(
        api_client.submit_questionnaire(questionnaire_id, ctx["candidate_headers"])
    )
    under_review = validate_success(
        api_client.start_review_questionnaire(questionnaire_id, COORDINATOR)
    )

    assessment = validate_success(
        api_client.create_portability_assessment(
            questionnaire_id,
            create_assessment_payload(under_review["version"]),
            COORDINATOR,
        ),
        expected_status=201,
    )

    read_back = read_assessment(assessment["id"])
    assert_money_equals(
        read_back["gross_baseline_total_usd"], 1269000.00, "gross_baseline_total_usd"
    )
    assert_money_equals(
        read_back["validated_portable_total_usd"],
        1269000.00,
        "validated_portable_total_usd",
    )
    assert_money_equals(
        read_back["declined_portable_total_usd"], 0.00, "declined_portable_total_usd"
    )
    assert_money_equals(
        round(
            float(read_back["validated_portable_total_usd"])
            + float(read_back["declined_portable_total_usd"]),
            2,
        ),
        float(read_back["gross_baseline_total_usd"]),
        "portable book identity",
    )
    assert read_back["entry_count_in_scope"] == 1
    assert_money_equals(
        read_back["adjusted_portable_total_usd"], 1078650.00, "adjusted_portable_total_usd"
    )
    assert_ratio_equals(read_back["top_client_share"], 1.0000, "top_client_share")
    assert read_back["status"] == "CURRENT"

    questionnaire = read_questionnaire(questionnaire_id)
    assert questionnaire["entry_count"] == 1
    assert questionnaire["latest_assessment_id"] == assessment["id"]
    assert read_client_book_entry(entry_b_id)["status"] == "WITHDRAWN"


def test_a_withdrawn_row_still_resolves_with_its_evidence_but_leaves_the_next_valuation():
    """Such a row remains readable by its own identifier and remains referenceable by rows
    that already point at it, but it is excluded from every aggregation the system performs and
    it is hidden from list responses unless the caller passes `include_withdrawn` as true.
    Entries whose `status` is `WITHDRAWN` are excluded from the scope entirely and are not
    tested for evidence.

    Design: Corner/cross_cutting_complexity_layers/soft_deleted_book_rows_keep_their_history_but_leave_the_valuation
    """
    ctx = setup_assessed_candidate("AB")
    questionnaire_id = ctx["questionnaire"]["id"]
    first_assessment_id = ctx["assessment"]["id"]
    entry_b_id = ctx["entries"]["Calder Manufacturing"]["id"]

    assert_money_equals(
        ctx["assessment"]["gross_baseline_total_usd"],
        EXPECTED_AB_BOOK["gross_baseline_total_usd"],
        "gross_baseline_total_usd",
    )

    # PRD makes the client book mutable again only once the LPQ has been sent back, so
    # the soft-delete runs from REVISION_REQUESTED; the loop then closes back through
    # SUBMITTED -> UNDER_REVIEW, which is what the second assessment requires.
    validate_success(
        api_client.request_revision_questionnaire(
            questionnaire_id, request_revision_payload(), COORDINATOR
        )
    )

    validate_success(
        api_client.delete_client_book_entry(entry_b_id, ctx["candidate_headers"])
    )

    validate_success(
        api_client.submit_questionnaire(questionnaire_id, ctx["candidate_headers"])
    )
    validate_success(
        api_client.start_review_questionnaire(questionnaire_id, COORDINATOR)
    )

    survivor = validate_success(
        api_client.get_client_book_entry(entry_b_id, COORDINATOR)
    )
    assert survivor["status"] == "WITHDRAWN"
    assert_money_equals(
        survivor["validated_portable_amount_usd"],
        EXPECTED_AB_BOOK["entry_b_baseline"],
        "validated_portable_amount_usd",
    )
    assert survivor["verified_record_count"] == 3

    _rows, meta = validate_paginated(
        api_client.list_collection_records(
            COORDINATOR,
            params={
                "client_book_entry_id": entry_b_id,
                "record_type": "HISTORICAL",
                "status": "VERIFIED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 3

    second = validate_success(
        api_client.create_portability_assessment(
            questionnaire_id,
            create_assessment_payload(read_questionnaire(questionnaire_id)["version"]),
            COORDINATOR,
        ),
        expected_status=201,
    )

    stale_one = read_assessment(first_assessment_id)
    assert stale_one["status"] == "SUPERSEDED"
    assert_money_equals(
        stale_one["gross_baseline_total_usd"],
        EXPECTED_AB_BOOK["gross_baseline_total_usd"],
        "gross_baseline_total_usd",
    )

    assert second["status"] == "CURRENT"
    assert second["entry_count_in_scope"] == 1
    assert_money_equals(
        second["gross_baseline_total_usd"], 1269000.00, "gross_baseline_total_usd"
    )
    assert_money_equals(
        second["validated_portable_total_usd"],
        1269000.00,
        "validated_portable_total_usd",
    )
    assert_money_equals(
        second["adjusted_portable_total_usd"], 1078650.00, "adjusted_portable_total_usd"
    )

    assert read_questionnaire(questionnaire_id)["entry_count"] == 1


def test_paging_and_filtering_narrow_the_record_listing_without_disturbing_each_other():
    """The `meta` object of every list response carries `limit`, `offset`, `total_count` — the
    number of records matching the filters across all pages, not merely the number returned on
    this page — and `has_more`, a boolean that is true exactly when records matching the filters
    remain beyond the current page.
    collection records by `candidate_id`, `client_book_entry_id`, `record_type`, or `status`;

    Design: Corner/cross_cutting_complexity_layers/collection_record_listing_pages_and_filters_independently
    """
    ctx = setup_questionnaire_in_draft()
    setup_book(ctx, "AB")
    candidate_id = ctx["candidate"]["id"]
    entry_a_id = ctx["entries"]["Northwind Holdings"]["id"]
    entry_b_id = ctx["entries"]["Calder Manufacturing"]["id"]

    unverified = append_collection_record(
        candidate_id, entry_a_id, **UNVERIFIED_RECORD
    )

    _page_one, first_meta = validate_paginated(
        api_client.list_collection_records(
            COORDINATOR, params={"candidate_id": candidate_id, "limit": 4, "offset": 0}
        )
    )
    assert first_meta["total_count"] == 7
    assert first_meta["has_more"] is True

    _page_two, second_meta = validate_paginated(
        api_client.list_collection_records(
            COORDINATOR, params={"candidate_id": candidate_id, "limit": 4, "offset": 4}
        )
    )
    assert second_meta["total_count"] == 7
    assert second_meta["has_more"] is False

    _verified, verified_meta = validate_paginated(
        api_client.list_collection_records(
            COORDINATOR,
            params={
                "candidate_id": candidate_id,
                "record_type": "HISTORICAL",
                "status": "VERIFIED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert verified_meta["total_count"] == 6
    assert verified_meta["has_more"] is False

    unverified_rows, unverified_meta = validate_paginated(
        api_client.list_collection_records(
            COORDINATOR,
            params={
                "client_book_entry_id": entry_a_id,
                "status": "UNVERIFIED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert unverified_meta["total_count"] == 1
    assert unverified_rows[0]["id"] == unverified["id"]

    _tail, tail_meta = validate_paginated(
        api_client.list_collection_records(
            COORDINATOR,
            params={"client_book_entry_id": entry_b_id, "limit": 2, "offset": 2},
        )
    )
    assert tail_meta["total_count"] == 3
    assert tail_meta["has_more"] is False

    assert read_client_book_entry(entry_a_id)["verified_record_count"] == 3
    assert read_client_book_entry(entry_b_id)["verified_record_count"] == 3
    assert read_questionnaire(ctx["questionnaire"]["id"])["entry_count"] == 2


def test_the_whole_accept_cascade_is_visible_on_the_first_read_of_every_touched_row():
    """The consistency model is immediate. Every cascade, every ledger adjustment and every
    derived-field recomputation described in this document lands inside the request that
    triggered it, before that request returns. There is no background worker, no eventual
    reconciliation, and no window in which a parent and its children disagree.
    The money then converts rather than releases: the group's `reserved_guarantee_budget_usd`
    is reduced by `guaranteed_comp_usd`, its `committed_guarantee_total_usd` is increased by the
    same amount, and `available_guarantee_budget_usd` is **unchanged** — the reservation becomes
    a commitment.

    Design: Corner/consistency_model/the_accept_cascade_is_readable_on_the_first_read_after_the_write
    """
    ctx = setup_approved_offer("SLIM")
    offer_id = ctx["offer"]["id"]
    group_id = ctx["practice_group"]["id"]

    before = read_practice_group(group_id)
    assert_money_equals(
        before["reserved_guarantee_budget_usd"], 500000.00, "reserved before the accept"
    )
    assert_money_equals(
        before["available_guarantee_budget_usd"], 4500000.00, "available before the accept"
    )
    assert_money_equals(
        before["committed_guarantee_total_usd"], 0.00, "committed before the accept"
    )

    accepted = validate_success(
        api_client.accept_offer(offer_id, ctx["candidate_headers"])
    )
    assert accepted["status"] == "ACCEPTED"

    offer_read = validate_success(api_client.get_offer(offer_id, CHAIR))
    assert offer_read["status"] == "ACCEPTED"
    assert_instant_equals(
        offer_read["accepted_at"], "2026-08-01T00:00:00.000Z", "accepted_at"
    )

    candidate_read = validate_success(
        api_client.get_candidate(ctx["candidate"]["id"], ctx["leader_headers"])
    )
    assert candidate_read["pipeline_status"] == "HIRED"
    assert_instant_equals(
        candidate_read["hire_date"], "2026-08-01T00:00:00.000Z", "hire_date"
    )
    assert_instant_equals(
        candidate_read["resignation_date"], "2026-08-01T00:00:00.000Z", "resignation_date"
    )
    assert_instant_equals(
        candidate_read["earliest_start_date"],
        "2026-09-15T00:00:00.000Z",
        "earliest_start_date",
    )

    engagement_read = validate_success(
        api_client.get_search_firm_engagement(ctx["engagement"]["id"], COORDINATOR)
    )
    assert engagement_read["fee_status"] == "FEE_DUE"
    assert engagement_read["fee_basis"] == "DIRECT_PLACEMENT"
    assert_money_equals(engagement_read["fee_amount_usd"], 137500.00, "fee_amount_usd")

    after = validate_success(api_client.get_practice_group(group_id, CHAIR))
    assert_money_equals(
        after["reserved_guarantee_budget_usd"], 0.00, "reserved after the accept"
    )
    assert_money_equals(
        after["committed_guarantee_total_usd"], 500000.00, "committed after the accept"
    )
    assert_money_equals(
        after["available_guarantee_budget_usd"], 4500000.00, "available after the accept"
    )

    again = validate_success(api_client.get_practice_group(group_id, CHAIR))
    assert_money_equals(
        again["reserved_guarantee_budget_usd"],
        after["reserved_guarantee_budget_usd"],
        "reserved on the repeat read",
    )
    assert_money_equals(
        again["committed_guarantee_total_usd"],
        after["committed_guarantee_total_usd"],
        "committed on the repeat read",
    )
    assert_money_equals(
        again["available_guarantee_budget_usd"],
        after["available_guarantee_budget_usd"],
        "available on the repeat read",
    )
