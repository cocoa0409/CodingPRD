"""The policy version lifecycle: drafting, back-testing, revision and activation."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_rate_equals,
)
from test_helpers.constants import CLOCK_T0
from test_helpers.factories import (
    create_detection_signal_payload,
    revise_policy_version_payload,
)
from test_helpers.fixtures import (
    build_decided_case,
    build_legal_case,
    build_policy_baseline,
    build_workforce_baseline,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    POLICY_ACTIVATOR_HEADERS,
    POLICY_AUTHOR_HEADERS,
    POLICY_MANAGER_ACTIVATOR_ID,
)


def test_policy_version_revise_returns_backtesting_to_draft(api, world):
    """A revision rewrites the thresholds and voids every stored back-test field.

    PRD 3.2: "A revision may overwrite any of `auto_action_threshold`,
    `review_floor`, `review_sla_minutes`, `appeal_window_hours` and
    `requires_recertification`, and it voids the stale evidence:
    `backtest_divergence_rate` and `backtest_completed_at` return to null and
    `backtest_sample_size` returns to 0, so the draft must be back-tested again
    before it can be activated."

    Design: Corner/state_machines/policy_version_revise_returns_backtesting_to_draft
    """
    base = build_policy_baseline(world)
    second = world.create_draft_version(base.category_id, version_label="v2")
    back_tested = world.back_test(second["id"])
    assert back_tested["status"] == "BACKTESTING"
    assert back_tested["backtest_completed_at"] is not None

    revised = validate_success(
        api.revise_policy_version(
            second["id"],
            payload=revise_policy_version_payload(
                auto_action_threshold=0.8, review_floor=0.3, review_sla_minutes=120
            ),
            headers=POLICY_AUTHOR_HEADERS,
        )
    )
    assert revised["status"] == "DRAFT"
    assert_rate_equals(revised["auto_action_threshold"], 0.8, "auto_action_threshold")
    assert_rate_equals(revised["review_floor"], 0.3, "review_floor")
    assert revised["review_sla_minutes"] == 120
    assert revised["backtest_divergence_rate"] is None
    assert revised["backtest_sample_size"] == 0
    assert revised["backtest_completed_at"] is None

    category = validate_success(
        api.get_policy_category(base.category_id, headers=ADMIN_HEADERS)
    )
    assert category["active_version_id"] == base.version_id
    first = validate_success(api.get_policy_version(base.version_id, headers=ADMIN_HEADERS))
    assert first["status"] == "ACTIVE"


def test_policy_category_bubbles_up_to_active_on_first_version_activation(api, world, clock_at_t0):
    """The category flips to ACTIVE only when its first child version activates.

    PRD 3.2: "Fourth, the parent category's `active_version_id` is repointed to
    the newly activated version and its `status` becomes `ACTIVE` if it was still
    `DRAFT` — after which detection signals citing that category's `code` stop
    failing with `ERR_NO_ACTIVE_POLICY_VERSION`."

    Design: Corner/state_machines/policy_category_bubbles_up_to_active_on_first_version_activation
    """
    category = world.create_category()
    world.create_queue(category["id"])
    account = world.create_account()
    item = world.create_content(account["id"])
    draft = world.create_draft_version(category["id"])
    world.back_test(draft["id"])

    before = validate_success(api.get_policy_category(category["id"], headers=POLICY_AUTHOR_HEADERS))
    assert before["status"] == "DRAFT"
    assert before["active_version_id"] is None
    validate_error(
        api.create_detection_signal(
            create_detection_signal_payload(item["id"]), headers=ADMIN_HEADERS
        ),
        ApiErrorId.NO_ACTIVE_POLICY_VERSION.value,
    )

    activated = validate_success(
        api.activate_policy_version(draft["id"], headers=POLICY_ACTIVATOR_HEADERS)
    )
    assert_fields(
        activated,
        {
            "status": "ACTIVE",
            "supersedes_version_id": None,
            "activated_by_user_id": POLICY_MANAGER_ACTIVATOR_ID,
        },
        "policy version",
    )

    after = validate_success(api.get_policy_category(category["id"], headers=POLICY_AUTHOR_HEADERS))
    assert after["status"] == "ACTIVE"
    assert after["active_version_id"] == draft["id"]

    signal = validate_success(
        api.create_detection_signal(
            create_detection_signal_payload(item["id"]), headers=ADMIN_HEADERS
        ),
        201,
    )
    assert signal["pinned_policy_version_label"] == "v1"


def test_activate_before_backtest_rejected_as_not_backtested(api, world, clock_at_t0):
    """An unmeasured draft cannot activate, whoever asks for it.

    PRD 3.2: "It is refused unless the version is `BACKTESTING` with a non-null
    `backtest_divergence_rate` (`ERR_POLICY_VERSION_NOT_BACKTESTED`, HTTP 409);
    unless the activating manager's `X-User-ID` differs from
    `authored_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403); and unless the
    recorded divergence is at most one quarter — a `backtest_divergence_rate`
    strictly greater than `0.2500` is rejected with
    `ERR_BACKTEST_DIVERGENCE_EXCEEDED` (HTTP 422), while exactly `0.2500`
    activates."

    Design: Corner/endpoints/activate_before_backtest_rejected_as_not_backtested
    """
    category = world.create_category()
    draft = world.create_draft_version(category["id"])

    refused = api.activate_policy_version(draft["id"], headers=POLICY_ACTIVATOR_HEADERS)
    assert refused.status_code == 409
    validate_error(refused, ApiErrorId.POLICY_VERSION_NOT_BACKTESTED.value)

    unchanged = validate_success(api.get_policy_version(draft["id"], headers=ADMIN_HEADERS))
    assert_fields(
        unchanged,
        {
            "status": "DRAFT",
            "activated_by_user_id": None,
            "activated_at": None,
            "backtest_divergence_rate": None,
        },
        "policy version",
    )
    category_row = validate_success(
        api.get_policy_category(category["id"], headers=ADMIN_HEADERS)
    )
    assert category_row["status"] == "DRAFT"
    assert category_row["active_version_id"] is None

    world.back_test(draft["id"])
    activated = validate_success(
        api.activate_policy_version(draft["id"], headers=POLICY_ACTIVATOR_HEADERS)
    )
    assert activated["status"] == "ACTIVE"


def test_author_activating_own_policy_version_rejected(api, world, clock_at_t0):
    """Authoring and activating a policy version must be two different managers.

    PRD 2.8: "**Segregation of duties**, `ERR_SEGREGATION_OF_DUTIES`, on exactly
    three operations: activating a policy version (the activator's `X-User-ID`
    must differ from `authored_by_user_id`), drawing an audit sample (the auditor
    may not be the case's `decided_by_reviewer_id`), and routing an appeal to an
    independent reviewer (who may not be the case's `decided_by_reviewer_id`)."

    Design: Corner/errors/author_activating_own_policy_version_rejected
    """
    category = world.create_category()
    draft = world.create_draft_version(category["id"])
    world.back_test(draft["id"])

    refused = api.activate_policy_version(draft["id"], headers=POLICY_AUTHOR_HEADERS)
    assert refused.status_code == 403
    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES.value)

    unchanged = validate_success(api.get_policy_version(draft["id"], headers=ADMIN_HEADERS))
    assert unchanged["status"] == "BACKTESTING"
    assert unchanged["activated_by_user_id"] is None
    category_row = validate_success(
        api.get_policy_category(category["id"], headers=ADMIN_HEADERS)
    )
    assert category_row["status"] == "DRAFT"
    assert category_row["active_version_id"] is None

    activated = validate_success(
        api.activate_policy_version(draft["id"], headers=POLICY_ACTIVATOR_HEADERS)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["activated_by_user_id"] == POLICY_MANAGER_ACTIVATOR_ID


def test_second_backtest_rejected_as_not_draft(api, world):
    """Back-testing is a DRAFT-only move, and so is revision from BACKTESTING.

    PRD 3.2: "Before a draft may govern anything it must be **back-tested**
    against history, which advances it `DRAFT → BACKTESTING`; attempting a
    back-test on a version that is not `DRAFT` is rejected with
    `ERR_POLICY_VERSION_NOT_DRAFT` (HTTP 409)."

    Design: Corner/errors/second_backtest_rejected_as_not_draft
    """
    base = build_policy_baseline(world)
    second = world.create_draft_version(base.category_id, version_label="v2")
    first_pass = world.back_test(second["id"])
    completed_at = first_pass["backtest_completed_at"]

    refused = api.back_test_policy_version(second["id"], headers=POLICY_AUTHOR_HEADERS)
    assert refused.status_code == 409
    validate_error(refused, ApiErrorId.POLICY_VERSION_NOT_DRAFT.value)
    unchanged = validate_success(api.get_policy_version(second["id"], headers=ADMIN_HEADERS))
    assert unchanged["status"] == "BACKTESTING"
    assert_instant_equals(
        unchanged["backtest_completed_at"], completed_at, "backtest_completed_at"
    )

    revised = world.revise(second["id"])
    assert revised["status"] == "DRAFT"
    validate_error(
        api.revise_policy_version(
            second["id"],
            payload=revise_policy_version_payload(),
            headers=POLICY_AUTHOR_HEADERS,
        ),
        ApiErrorId.POLICY_VERSION_NOT_DRAFT.value,
    )
    again = world.back_test(second["id"])
    assert again["status"] == "BACKTESTING"


def test_activation_above_max_backtest_divergence_rejected(api, world):
    """A candidate that would have auto-actioned a human-reviewed case cannot activate.

    PRD 3.2: "`backtest_sample_size` records how many cases were replayed, and
    `backtest_divergence_rate` is the count of cases whose predicted class differs
    from their historical class divided by that sample size, rounded half up to
    four decimal places."

    Design: Corner/errors/activation_above_max_backtest_divergence_rejected
    """
    base = build_workforce_baseline(world)
    build_decided_case(base, outcome="NO_ACTION")

    candidate = world.create_draft_version(
        base.category_id, version_label="v2", auto_action_threshold=0.5, review_floor=0.4
    )
    measured = world.back_test(candidate["id"])
    assert measured["backtest_sample_size"] == 1
    assert_rate_equals(measured["backtest_divergence_rate"], 1.0, "backtest_divergence_rate")

    refused = api.activate_policy_version(candidate["id"], headers=POLICY_ACTIVATOR_HEADERS)
    assert refused.status_code == 422
    validate_error(refused, ApiErrorId.BACKTEST_DIVERGENCE_EXCEEDED.value)

    blocked = validate_success(api.get_policy_version(candidate["id"], headers=ADMIN_HEADERS))
    assert blocked["status"] == "BACKTESTING"
    assert blocked["activated_at"] is None
    incumbent = validate_success(api.get_policy_version(base.version_id, headers=ADMIN_HEADERS))
    assert incumbent["status"] == "ACTIVE"
    category = validate_success(
        api.get_policy_category(base.category_id, headers=ADMIN_HEADERS)
    )
    assert category["active_version_id"] == base.version_id

    world.revise(candidate["id"], auto_action_threshold=0.9, review_floor=0.4)
    remeasured = world.back_test(candidate["id"])
    assert_rate_equals(remeasured["backtest_divergence_rate"], 0.0, "backtest_divergence_rate")
    activated = world.activate(candidate["id"])
    assert activated["status"] == "ACTIVE"


def test_backtest_excludes_legal_origin_cases_from_the_sample(api, world):
    """Only decided classifier-origin cases are replayed, so the legal case is skipped.

    PRD 3.2: "The sample is every `ModerationCase` whose pinned
    `policy_version_id` is that currently active version, whose status is
    `DECIDED`, and whose `detection_signal_id` is not null — legal-request and
    manual-report cases carry no classifier confidence and are excluded entirely
    — taken in ascending `created_at` order."

    Design: Corner/calculations/backtest_excludes_legal_origin_cases_from_the_sample
    """
    base = build_workforce_baseline(world)
    build_decided_case(base, outcome="NO_ACTION")
    legal = build_legal_case(base)
    legal_decided = world.decide_as_legal(legal.case_id, outcome="NO_ACTION")
    assert legal_decided["status"] == "DECIDED"
    assert legal_decided["decision_source"] == "LEGAL"
    assert legal_decided["decided_by_reviewer_id"] is None
    assert legal_decided["detection_signal_id"] is None

    candidate = world.create_draft_version(
        base.category_id, version_label="v2", auto_action_threshold=0.95, review_floor=0.4
    )
    measured = validate_success(
        api.back_test_policy_version(candidate["id"], headers=POLICY_AUTHOR_HEADERS)
    )
    assert measured["status"] == "BACKTESTING"
    assert measured["backtest_sample_size"] == 1
    assert_rate_equals(measured["backtest_divergence_rate"], 0.0, "backtest_divergence_rate")
    assert_instant_equals(measured["backtest_completed_at"], CLOCK_T0, "backtest_completed_at")

    activated = validate_success(
        api.activate_policy_version(candidate["id"], headers=POLICY_ACTIVATOR_HEADERS)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["supersedes_version_id"] == base.version_id
