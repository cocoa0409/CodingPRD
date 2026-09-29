"""Appeal filing conditions, independent review ownership and the upheld arm."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_fields, assert_instant_equals, assert_rate_equals
from test_helpers.factories import create_appeal_payload, resolve_appeal_payload
from test_helpers.fixtures import (
    build_appeal_under_independent_review,
    build_decided_case,
    build_pending_case,
    build_resolved_appeal,
    build_submitted_appeal,
    build_workforce_baseline,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_account_holder_headers,
    make_reviewer_headers,
)


def test_appeal_on_missing_case_returns_not_found_before_the_state_check(api, world):
    """An unresolvable body reference is answered before ownership or lifecycle.

    PRD 2.8: "**Body-referenced identifiers and natural keys**, resolved in the
    order the operation's input list declares them: `account_id`, then
    `content_item_id`, then `policy_category_id`, then `policy_category_code`,
    then `policy_version_id`, then `case_id`, then `target_reviewer_id`, then
    each member of `exclude_reviewer_ids`."

    Design: Corner/validations/appeal_on_missing_case_returns_not_found_before_the_state_check
    """
    base = build_workforce_baseline(world)

    refused = api.create_appeal(
        create_appeal_payload(NON_EXISTENT_UUID, grounds_text="Nothing to see here"),
        headers=make_account_holder_headers(base.account_id),
    )
    assert refused.status_code == 404
    validate_error(refused, ApiErrorId.CASE_NOT_FOUND.value)

    stranger = world.create_account(external_handle="acct_stranger")
    also_refused = api.create_appeal(
        create_appeal_payload(NON_EXISTENT_UUID, grounds_text="Nothing to see here"),
        headers=make_account_holder_headers(stranger["id"]),
    )
    assert also_refused.status_code == 404
    validate_error(also_refused, ApiErrorId.CASE_NOT_FOUND.value)

    pending = build_pending_case(base, content_overrides={"graphic_weight": 2})
    undecided = api.create_appeal(
        create_appeal_payload(pending.case_id, grounds_text="Too early"),
        headers=make_account_holder_headers(base.account_id),
    )
    assert undecided.status_code == 409
    validate_error(undecided, ApiErrorId.CASE_NOT_DECIDED.value)

    assert world.get_account(base.account_id)["appeal_credits_remaining"] == 3
    rows, meta = validate_paginated(api.list_appeals(headers=ADMIN_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []


def test_second_appeal_on_same_case_rejected(api, world):
    """One case admits one appeal, and the duplicate spends no second credit.

    PRD 3.7: "no appeal may already exist for that `case_id`, since each case
    admits at most one, or `ERR_APPEAL_ALREADY_EXISTS` (HTTP 409)"

    Design: Corner/errors/second_appeal_on_same_case_rejected
    """
    base = build_workforce_baseline(world)
    filed = build_submitted_appeal(base, outcome="REMOVE")
    assert world.get_account(base.account_id)["appeal_credits_remaining"] == 2

    refused = api.create_appeal(
        create_appeal_payload(filed.case_scenario.case_id, grounds_text="Second filing"),
        headers=make_account_holder_headers(base.account_id),
    )
    assert refused.status_code == 409
    validate_error(refused, ApiErrorId.APPEAL_ALREADY_EXISTS.value)

    rows, meta = validate_paginated(
        api.list_appeals(headers=ADMIN_HEADERS, case_id=filed.case_scenario.case_id)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [filed.appeal_id]
    assert world.get_account(base.account_id)["appeal_credits_remaining"] == 2
    assert world.get_content(filed.case_scenario.content_id)["review_status"] == "APPEALED"


def test_appeal_resolution_by_a_different_reviewer_rejected(api, world):
    """Only the appointed independent reviewer may close the appeal.

    PRD 2.8: "the reviewer resolving an appeal must be that appeal's
    `independent_reviewer_id`, else `ERR_NOT_APPEAL_REVIEWER`"

    Design: Corner/errors/appeal_resolution_by_a_different_reviewer_rejected
    """
    base = build_workforce_baseline(world)
    routed = build_appeal_under_independent_review(base, outcome="REMOVE")
    assert routed.appeal["independent_reviewer_id"] == base.senior_id
    assert routed.appeal["status"] == "INDEPENDENT_REVIEW"

    refused = api.resolve_appeal(
        routed.appeal_id,
        resolve_appeal_payload(resolution="UPHELD"),
        headers=make_reviewer_headers(base.frontline_id),
    )
    assert refused.status_code == 403
    validate_error(refused, ApiErrorId.NOT_APPEAL_REVIEWER.value)

    unchanged = world.get_appeal(routed.appeal_id)
    assert_fields(
        unchanged,
        {
            "status": "INDEPENDENT_REVIEW",
            "independent_reviewer_id": base.senior_id,
            "resolved_at": None,
            "reinstated_content": False,
        },
        "appeal after the refused resolve",
    )
    decider = world.get_reviewer(base.frontline_id)
    assert decider["appealed_count"] == 0
    assert decider["accuracy_score_blended"] is None

    accepted = validate_success(
        api.resolve_appeal(
            routed.appeal_id,
            resolve_appeal_payload(resolution="UPHELD"),
            headers=make_reviewer_headers(base.senior_id),
        )
    )
    assert accepted["status"] == "UPHELD"


def test_account_holder_cannot_read_another_accounts_appeal(api, world):
    """Appeal reads are scoped to the appellant, on the item and on the list.

    PRD 2.8: "An `AccountHolder` may only file an appeal on content authored by
    their own account and may only read appeals whose `account_id` equals
    `X-User-ID`, else `ERR_APPEAL_NOT_OWNED`."

    Design: Corner/rbac/account_holder_cannot_read_another_accounts_appeal
    """
    base = build_workforce_baseline(world)
    filed = build_submitted_appeal(base, outcome="REMOVE")
    other = world.create_account(external_handle="acct_bystander")

    refused_item = api.get_appeal(
        filed.appeal_id, headers=make_account_holder_headers(other["id"])
    )
    assert refused_item.status_code == 403
    validate_error(refused_item, ApiErrorId.APPEAL_NOT_OWNED.value)

    refused_list = api.list_appeals(
        headers=make_account_holder_headers(other["id"]), account_id=base.account_id
    )
    assert refused_list.status_code == 403
    validate_error(refused_list, ApiErrorId.APPEAL_NOT_OWNED.value)

    owned = validate_success(
        api.get_appeal(filed.appeal_id, headers=make_account_holder_headers(base.account_id))
    )
    assert owned["account_id"] == base.account_id
    assert owned["id"] == filed.appeal_id

    own_rows, own_meta = validate_paginated(
        api.list_appeals(
            headers=make_account_holder_headers(other["id"]), account_id=other["id"]
        )
    )
    assert own_meta["total_count"] == 0
    assert own_rows == []


def test_expired_appeal_window_beats_an_exhausted_credit_balance(api, world):
    """Both fiscal and temporal defects are present, and the temporal one answers.

    PRD 3.7: "the logical clock must be at or before the case's
    `appeal_deadline_at`, or `ERR_APPEAL_WINDOW_CLOSED` (HTTP 422) — filing
    exactly at the deadline instant is still in time; and the account's
    `appeal_credits_remaining` must be at least 1, or
    `ERR_APPEAL_CREDITS_EXHAUSTED` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/appeal_window_temporal_beats_credit_exhaustion_fiscal
    """
    base = build_workforce_baseline(world, account_overrides={"appeal_credits_remaining": 0})
    scenario = build_decided_case(base, outcome="REMOVE", content_overrides={"graphic_weight": 2})
    assert_instant_equals(
        scenario.case["appeal_deadline_at"], "2026-08-04T09:00:00Z", "appeal_deadline_at"
    )
    assert world.get_account(base.account_id)["appeal_credits_remaining"] == 0

    world.set_clock("2026-08-05T09:00:00Z")
    refused = api.create_appeal(
        create_appeal_payload(scenario.case_id, grounds_text="Late but sincere"),
        headers=make_account_holder_headers(base.account_id),
    )
    assert refused.status_code == 422
    validate_error(refused, ApiErrorId.APPEAL_WINDOW_CLOSED.value)
    assert refused.json()["data"]["error_id"] != ApiErrorId.APPEAL_CREDITS_EXHAUSTED.value


def test_exhausted_credit_balance_answers_only_while_the_window_is_open(api, world):
    """The fiscal rule is live in its own right and yields to the deadline rule.

    PRD 3.7: "and the account's `appeal_credits_remaining` must be at least 1,
    or `ERR_APPEAL_CREDITS_EXHAUSTED` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/appeal_window_temporal_beats_credit_exhaustion_fiscal
    """
    base = build_workforce_baseline(world, account_overrides={"appeal_credits_remaining": 0})
    scenario = build_decided_case(base, outcome="REMOVE", content_overrides={"graphic_weight": 2})

    in_window = api.create_appeal(
        create_appeal_payload(scenario.case_id, grounds_text="Sincere and prompt"),
        headers=make_account_holder_headers(base.account_id),
    )
    assert in_window.status_code == 402
    validate_error(in_window, ApiErrorId.APPEAL_CREDITS_EXHAUSTED.value)

    world.set_clock("2026-08-05T09:00:00Z")
    out_of_window = api.create_appeal(
        create_appeal_payload(scenario.case_id, grounds_text="Late but sincere"),
        headers=make_account_holder_headers(base.account_id),
    )
    assert out_of_window.status_code == 422
    validate_error(out_of_window, ApiErrorId.APPEAL_WINDOW_CLOSED.value)

    assert world.get_account(base.account_id)["appeal_credits_remaining"] == 0
    rows, meta = validate_paginated(
        api.list_appeals(headers=ADMIN_HEADERS, case_id=scenario.case_id)
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert world.get_content(scenario.content_id)["review_status"] == "ACTIONED"


def test_filing_an_appeal_moves_only_the_review_dimension(api, world):
    """Review status walks CLEAR to APPEALED while visibility stays where enforcement left it.

    PRD 3.7: "On the content item, `review_status` moves from `ACTIONED` to
    `APPEALED` while `visibility_status` is left exactly as the decision left it
    — a removed item stays `REMOVED` for the duration of the appeal."

    Design: Difficulty/non_linear_state_machine/content_item_parallel_dimensions_independent
    """
    base = build_workforce_baseline(world)
    item = world.create_content(
        base.account_id,
        language=base.queue["language"],
        media_kind="TEXT",
        graphic_weight=2,
    )
    assert item["review_status"] == "CLEAR"
    assert item["visibility_status"] == "LIVE"

    signal = world.submit_signal(
        item["id"], policy_category_code=base.category_code, classifier_confidence=0.7
    )
    case = world.get_case(signal["resulting_case_id"])
    under_review = world.get_content(item["id"])
    assert under_review["review_status"] == "UNDER_REVIEW"
    assert under_review["visibility_status"] == "LIVE"

    world.assign(case["id"], target_reviewer_id=base.frontline_id)
    world.decide(case["id"], base.frontline_id, outcome="REMOVE")
    after_decide = world.get_content(item["id"])
    assert after_decide["review_status"] == "ACTIONED"
    assert after_decide["visibility_status"] == "REMOVED"

    appeal = world.file_appeal(case["id"], base.account_id)
    assert_fields(
        appeal,
        {
            "status": "SUBMITTED",
            "account_id": base.account_id,
            "case_id": case["id"],
            "independent_reviewer_id": None,
            "resolved_at": None,
            "resolution_note": None,
            "reinstated_content": False,
        },
        "filed appeal",
    )
    assert_instant_equals(appeal["filed_at"], "2026-08-01T09:00:00Z", "filed_at")
    after_appeal = world.get_content(item["id"])
    assert after_appeal["review_status"] == "APPEALED"
    assert after_appeal["visibility_status"] == "REMOVED"
    assert after_appeal["reinstated_at"] is None
    assert world.get_account(base.account_id)["appeal_credits_remaining"] == 2


def test_upheld_resolution_restores_review_status_without_touching_visibility(api, world):
    """The losing appeal costs a credit and leaves the enforcement in place.

    PRD 3.7: "The content item returns to `review_status` `ACTIONED` with
    `visibility_status` unchanged, and the account's `appeal_credits_remaining`
    is **not** refunded — a losing appeal costs a credit."

    Design: Difficulty/non_linear_state_machine/content_item_parallel_dimensions_independent
    """
    base = build_workforce_baseline(world)
    routed = build_appeal_under_independent_review(base, outcome="REMOVE")
    appealed = world.get_content(routed.case_scenario.content_id)
    assert appealed["review_status"] == "APPEALED"
    assert appealed["visibility_status"] == "REMOVED"

    resolved = world.resolve_appeal(
        routed.appeal_id,
        base.senior_id,
        resolution="UPHELD",
        resolution_note="Original call was correct",
    )
    assert_fields(
        resolved,
        {
            "status": "UPHELD",
            "reinstated_content": False,
            "resolution_note": "Original call was correct",
        },
        "upheld appeal",
    )
    assert_instant_equals(resolved["resolved_at"], "2026-08-01T09:00:00Z", "resolved_at")

    item = world.get_content(routed.case_scenario.content_id)
    assert item["review_status"] == "ACTIONED"
    assert item["visibility_status"] == "REMOVED"
    assert item["reinstated_at"] is None

    account = world.get_account(base.account_id)
    assert_fields(
        account,
        {"strike_points": 4, "standing": "LIMITED", "appeal_credits_remaining": 2},
        "account after the upheld appeal",
    )
    assert world.get_case(routed.case_scenario.case_id)["is_overturned"] is False

    decider = world.get_reviewer(base.frontline_id)
    assert decider["appealed_count"] == 1
    assert decider["upheld_appeal_count"] == 1
    assert_rate_equals(decider["accuracy_score_blended"], 1.0, "accuracy_score_blended")
    assert decider["accuracy_score_audit_only"] is None
    assert decider["status"] == "ACTIVE"


def test_appeal_resolved_twice_rejected_as_not_under_review(api, world):
    """An upheld appeal is terminal even for the reviewer who upheld it.

    PRD 3.7: "Only that reviewer may do so — `X-User-ID` must equal
    `independent_reviewer_id`, else `ERR_NOT_APPEAL_REVIEWER` (HTTP 403) — and
    only from `INDEPENDENT_REVIEW`, else `ERR_APPEAL_NOT_UNDER_REVIEW`."

    Design: Corner/state_machines/appeal_resolved_twice_rejected_as_not_under_review
    """
    base = build_workforce_baseline(world)
    resolved = build_resolved_appeal(base, resolution="UPHELD", outcome="REMOVE")
    assert resolved.appeal["status"] == "UPHELD"

    refused = api.resolve_appeal(
        resolved.appeal_id,
        resolve_appeal_payload(resolution="OVERTURNED", resolution_note="Second thoughts"),
        headers=make_reviewer_headers(base.senior_id),
    )
    assert refused.status_code == 409
    validate_error(refused, ApiErrorId.APPEAL_NOT_UNDER_REVIEW.value)

    unchanged = world.get_appeal(resolved.appeal_id)
    assert_fields(
        unchanged,
        {
            "status": "UPHELD",
            "reinstated_content": False,
            "resolution_note": "Original call stands.",
        },
        "appeal after the refused second resolve",
    )
    item = world.get_content(resolved.case_scenario.content_id)
    assert item["visibility_status"] == "REMOVED"
    assert item["review_status"] == "ACTIONED"
    assert world.get_case(resolved.case_scenario.case_id)["is_overturned"] is False

    account = world.get_account(base.account_id)
    assert_fields(
        account,
        {"appeal_credits_remaining": 2, "strike_points": 4, "standing": "LIMITED"},
        "account after the refused second resolve",
    )
    decider = world.get_reviewer(base.frontline_id)
    assert decider["appealed_count"] == 1
    assert decider["upheld_appeal_count"] == 1
    assert_rate_equals(decider["accuracy_score_blended"], 1.0, "accuracy_score_blended")
    assert decider["status"] == "ACTIVE"
