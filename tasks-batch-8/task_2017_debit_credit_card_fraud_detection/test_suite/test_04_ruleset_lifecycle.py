"""RuleSet lifecycle: draft, activate, retire, OCC tuning, segregation of duties,
threshold ordering, activation state guard."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_rule_set_payload,
    get_success_data,
    make_analyst_headers,
    make_manager_headers,
)

MANAGER = TEST_USERS["manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def test_ruleset_threshold_order_enforced(api):
    """PRD §3.2: "The threshold ordering is strict: `review_threshold` must be
    strictly less than `decline_threshold`, and equality is rejected along with
    inversion as `ERR_THRESHOLD_ORDER_INVALID` (HTTP 422)."

    Design: Corner/validations/ruleset_threshold_order_enforced
    """
    bad = create_rule_set_payload(review_threshold=100, decline_threshold=100)
    resp = api.create_rule_set(bad, ANALYST)
    validate_error(resp, ApiErrorId.ERR_THRESHOLD_ORDER_INVALID, expected_status=422)

    ok = create_rule_set_payload(review_threshold=99, decline_threshold=100)
    created = validate_success(api.create_rule_set(ok, ANALYST), expected_status=201)
    assert created["ruleset_status"] == "DRAFT"


def test_ruleset_activation_by_creator_rejected(api):
    """PRD §3.2: "the activator's `X-User-ID` must differ from `created_by_user_id`,
    else `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/ruleset_activation_by_creator_rejected
    """
    rs = get_success_data(
        api.create_rule_set(create_rule_set_payload(), make_manager_headers("mgr-9")),
        expected_status=201,
    )
    assert rs["created_by_user_id"] == "mgr-9"
    resp = api.activate_rule_set(rs["id"], make_manager_headers("mgr-9"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    activated = validate_success(
        api.activate_rule_set(rs["id"], make_manager_headers("mgr-1"))
    )
    assert activated["ruleset_status"] == "ACTIVE"
    assert activated["activated_by_user_id"] == "mgr-1"


def test_ruleset_activate_from_active_rejected(api):
    """PRD §3.2: "Activating a `DRAFT` ruleset moves it to `ACTIVE`"; the transition
    is defined only from `DRAFT`, so activating an already-`ACTIVE` ruleset fails
    the state-machine precondition (priority 7, `ERR_INVALID_STATE` per §2.6).

    Design: Corner/state_machines/ruleset_activate_from_active_rejected
    """
    rs = get_success_data(
        api.create_rule_set(create_rule_set_payload(), make_analyst_headers("analyst-1")),
        expected_status=201,
    )
    get_success_data(api.activate_rule_set(rs["id"], make_manager_headers("mgr-1")))
    resp = api.activate_rule_set(rs["id"], make_manager_headers("mgr-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    current = validate_success(api.get_rule_set(rs["id"], MANAGER))
    assert current["ruleset_status"] == "ACTIVE"


class TestRulesetUpdateStaleVersion:
    def _make_draft(self, api):
        return get_success_data(
            api.create_rule_set(create_rule_set_payload(), make_analyst_headers("analyst-1")),
            expected_status=201,
        )

    def test_first_update_increments_version(self, api):
        """PRD §3.2: "the request must present `expected_ruleset_version` equal to
        the ruleset's current `version`, and any subset of the tunable fields ...
        may be adjusted in one call; a successful update increments `version` by
        exactly 1".

        Design: Corner/complexity_layers/ruleset_update_stale_version_rejected
        """
        rs = self._make_draft(api)
        assert rs["version"] == 1
        updated = validate_success(
            api.update_rule_set(
                rs["id"],
                {"expected_ruleset_version": rs["version"], "decline_threshold": 90},
                make_analyst_headers("analyst-1"),
            )
        )
        assert updated["version"] == 2
        assert updated["decline_threshold"] == 90

    def test_stale_version_rejected_and_leaves_no_residue(self, api):
        """PRD §2.9: "If the value does not equal the ruleset's current `version` —
        because another update has already advanced it — the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from silently
        overwriting tuning it has not observed."

        Design: Corner/complexity_layers/ruleset_update_stale_version_rejected
        """
        rs = self._make_draft(api)
        updated = validate_success(
            api.update_rule_set(
                rs["id"],
                {"expected_ruleset_version": rs["version"], "decline_threshold": 90},
                make_analyst_headers("analyst-1"),
            )
        )
        assert updated["version"] == 2
        stale = api.update_rule_set(
            rs["id"],
            {"expected_ruleset_version": rs["version"], "decline_threshold": 85},
            make_analyst_headers("analyst-1"),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        current = validate_success(api.get_rule_set(rs["id"], MANAGER))
        assert current["decline_threshold"] == 90, "the stale update must leave no residue"
        assert current["version"] == 2
