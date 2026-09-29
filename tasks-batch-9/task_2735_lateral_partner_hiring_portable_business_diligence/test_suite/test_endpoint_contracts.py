"""Endpoint-shape contracts: the soft-delete visibility flag, the acceptance freeze, the
cross-aggregate link check, the derived-date read and the conditional activation."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assert_money_equals,
    create_client_book_entry_payload,
    create_offer_payload,
    freeze_practice_group_payload,
    read_assessment,
    read_candidate,
    read_client_book_entry,
    read_integration_plan,
    read_practice_group,
    read_questionnaire,
    setup_assessed_candidate,
    setup_book,
    setup_hired_candidate,
    setup_plan_in_draft,
    setup_questionnaire_in_draft,
    setup_second_assessed_candidate,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]
CHAIR = TEST_USERS["committee_chair_headers"]

LATE_ADDITION = {
    "client_name": "Late Addition LLC",
    "relationship_role": "SERVICE_PARTNER",
    "claimed_annual_billings_usd": 90000.00,
    "claimed_portability_pct": 0.5000,
    "claimed_realization_rate": 0.9000,
    "matter_types": ["TAX"],
}


def test_withdrawn_book_rows_stay_out_of_the_listing_until_the_flag_asks_for_them():
    """Only one entity in this system is soft-deleted rather than removed: a
    `ClientBookEntry` whose `status` has become `WITHDRAWN`. Such a row remains readable by
    its own identifier and remains referenceable by rows that already point at it, but it is
    excluded from every aggregation the system performs and it is hidden from list responses
    unless the caller passes `include_withdrawn` as true.

    Design: Corner/endpoints/client_book_entry_list_hides_soft_deleted_rows_until_the_flag_is_set
    """
    ctx = setup_questionnaire_in_draft()
    setup_book(ctx, "AB")
    entry_a_id = ctx["entries"]["Northwind Holdings"]["id"]
    entry_b_id = ctx["entries"]["Calder Manufacturing"]["id"]

    validate_success(
        api_client.delete_client_book_entry(entry_b_id, ctx["candidate_headers"])
    )

    rows, meta = validate_paginated(
        api_client.list_client_book_entries(
            COORDINATOR,
            params={"questionnaire_id": ctx["questionnaire"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["id"] == entry_a_id

    _all_rows, all_meta = validate_paginated(
        api_client.list_client_book_entries(
            COORDINATOR,
            params={
                "questionnaire_id": ctx["questionnaire"]["id"],
                "include_withdrawn": True,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert all_meta["total_count"] == 2

    gone_rows, gone_meta = validate_paginated(
        api_client.list_client_book_entries(
            COORDINATOR,
            params={
                "questionnaire_id": ctx["questionnaire"]["id"],
                "status": "WITHDRAWN",
                "include_withdrawn": True,
            },
        )
    )
    assert gone_meta["total_count"] == 1
    assert gone_rows[0]["id"] == entry_b_id

    withdrawn = read_client_book_entry(entry_b_id)
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["client_name"] == "Calder Manufacturing"

    questionnaire = read_questionnaire(ctx["questionnaire"]["id"])
    assert questionnaire["entry_count"] == 1
    assert questionnaire["status"] == "DRAFT"


def test_acceptance_seals_the_book_against_both_additions_and_withdrawals():
    """Alternatively the coordinator accepts the LPQ as the diligence of record, moving
    `UNDER_REVIEW → ACCEPTED`, which requires that at least one portability assessment on
    this questionnaire is in `CURRENT` status. Acceptance freezes the client book: once the
    LPQ is `ACCEPTED`, creating an entry and soft-deleting an entry are both refused with
    `ERR_QUESTIONNAIRE_INVALID_STATE`.

    Design: Corner/endpoints/questionnaire_accept_freezes_the_client_book
    """
    ctx = setup_assessed_candidate("SLIM")
    entry_a_id = ctx["entries"]["Northwind Holdings"]["id"]

    accepted = validate_success(
        api_client.accept_questionnaire(ctx["questionnaire"]["id"], COORDINATOR)
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["entry_count"] == 1

    late = api_client.create_client_book_entry(
        ctx["questionnaire"]["id"],
        create_client_book_entry_payload(**LATE_ADDITION),
        ctx["candidate_headers"],
    )
    validate_error(late, ApiErrorId.ERR_QUESTIONNAIRE_INVALID_STATE.value)

    removal = api_client.delete_client_book_entry(entry_a_id, ctx["candidate_headers"])
    validate_error(removal, ApiErrorId.ERR_QUESTIONNAIRE_INVALID_STATE.value)

    entry = read_client_book_entry(entry_a_id)
    assert entry["status"] == "ACTIVE"
    assert entry["portable_status"] == "VALIDATED"
    assert read_assessment(ctx["assessment"]["id"])["status"] == "CURRENT"
    assert read_candidate(ctx["candidate"]["id"])["pipeline_status"] == "DILIGENCE"


def test_an_offer_may_only_price_against_its_own_candidates_assessment():
    """The referenced assessment's questionnaire must belong to that same candidate, or the
    request is refused with `ERR_ASSESSMENT_CANDIDATE_MISMATCH`.
    Creation also writes the offer's identifier into the candidate's `open_offer_id` and
    increments the candidate's `version` by 1 — which is exactly why the next writer's
    `expected_candidate_version` must be refreshed.

    Design: Corner/endpoints/offer_create_links_only_to_an_assessment_of_its_own_candidate
    """
    ctx = setup_assessed_candidate("SLIM")
    other = setup_second_assessed_candidate(ctx)
    second_id = other["candidate"]["id"]
    second_version = read_candidate(second_id)["version"]

    borrowed = api_client.create_offer(
        second_id,
        create_offer_payload(
            ctx["assessment"]["id"],
            second_version,
            guaranteed_comp_usd=400000.00,
            signing_bonus_usd=40000.00,
        ),
        CHAIR,
    )
    validate_error(borrowed, ApiErrorId.ERR_ASSESSMENT_CANDIDATE_MISMATCH.value)

    own = validate_success(
        api_client.create_offer(
            second_id,
            create_offer_payload(
                other["assessment"]["id"],
                second_version,
                guaranteed_comp_usd=400000.00,
                signing_bonus_usd=40000.00,
            ),
            CHAIR,
        ),
        expected_status=201,
    )
    assert own["candidate_id"] == second_id
    assert own["portability_assessment_id"] == other["assessment"]["id"]
    assert own["status"] == "DRAFTED"
    assert own["round_number"] == 1

    assert read_candidate(second_id)["open_offer_id"] == own["id"]
    assert read_candidate(ctx["candidate"]["id"])["open_offer_id"] is None
    assert_money_equals(
        read_practice_group(ctx["practice_group"]["id"])["reserved_guarantee_budget_usd"],
        0.00,
        "reserved_guarantee_budget_usd",
    )


def test_the_candidate_read_carries_the_derived_dates_and_both_status_dimensions():
    """**Hop 2**: the candidate moves `OFFER_OUT → HIRED`, with `resignation_date` and
    `hire_date` both set to the current logical clock and `earliest_start_date` computed as
    that instant advanced by `notice_period_days` days. **Hop 3**, caused by hop 2: the
    sourcing engagement's fee crystallises — `fee_basis` and `fee_amount_usd` are computed by
    the search-fee rule above using the candidate's `hire_date` as the hire instant, and
    `fee_status` is set to `FEE_DUE`.

    Design: Corner/endpoints/candidate_read_exposes_the_derived_dates_and_the_clearance_dimension
    """
    ctx = setup_hired_candidate("SLIM")

    read = validate_success(
        api_client.get_candidate(ctx["candidate"]["id"], ctx["leader_headers"])
    )
    assert_instant_equals(
        read["resignation_date"], "2026-08-01T00:00:00.000Z", "resignation_date"
    )
    assert_instant_equals(read["hire_date"], "2026-08-01T00:00:00.000Z", "hire_date")
    assert_instant_equals(
        read["earliest_start_date"], "2026-09-15T00:00:00.000Z", "earliest_start_date"
    )
    assert read["clearance_status"] == "CLEARED"
    assert read["pipeline_status"] == "HIRED"
    assert read["open_offer_id"] == ctx["offer"]["id"]

    rows, meta = validate_paginated(
        api_client.list_candidates(
            ctx["leader_headers"],
            params={
                "pipeline_status": "HIRED",
                "clearance_status": "CLEARED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["candidate"]["id"]

    engagement = validate_success(
        api_client.get_search_firm_engagement(ctx["engagement"]["id"], COORDINATOR)
    )
    assert engagement["fee_status"] == "FEE_DUE"
    assert engagement["fee_basis"] == "DIRECT_PLACEMENT"
    assert_money_equals(engagement["fee_amount_usd"], 137500.00, "fee_amount_usd")


def test_activation_waits_for_the_group_to_be_reopened_before_it_takes_a_slot():
    """A freeze does not disturb anything already in flight — offers already drafted against
    candidates targeting the group are left exactly as they are — but three later operations
    will be refused while the group is frozen: opening a new candidate, submitting an offer to
    committee, and activating an integration plan.
    **Onboarding slots are scarce.** Activating a plan moves it `DRAFT → ACTIVE` and consumes
    one unit of the group's onboarding capacity: the group's `active_onboarding_count` is
    incremented by 1 and the group's `version` advances.

    Design: Corner/endpoints/plan_activate_is_conditional_on_an_open_practice_group
    """
    ctx = setup_plan_in_draft("SLIM")
    group_id = ctx["practice_group"]["id"]
    plan_id = ctx["plan"]["id"]

    validate_success(
        api_client.freeze_practice_group(
            group_id,
            freeze_practice_group_payload(
                reason="Partner comp cycle: no new onboarding until the new fiscal year."
            ),
            ADMIN,
        )
    )

    blocked = api_client.activate_integration_plan(plan_id, ctx["leader_headers"])
    validate_error(blocked, ApiErrorId.ERR_PRACTICE_GROUP_FROZEN.value)

    frozen = validate_success(api_client.get_practice_group(group_id, CHAIR))
    assert frozen["status"] == "HIRING_FROZEN"
    assert frozen["active_onboarding_count"] == 0

    validate_success(api_client.unfreeze_practice_group(group_id, ADMIN))

    activated = validate_success(
        api_client.activate_integration_plan(plan_id, ctx["leader_headers"])
    )
    assert activated["status"] == "ACTIVE"
    assert activated["introduction_count"] == 0
    assert read_integration_plan(plan_id)["status"] == "ACTIVE"

    group = read_practice_group(group_id)
    assert group["status"] == "OPEN"
    assert group["active_onboarding_count"] == 1
    assert group["onboarding_capacity"] == 2
