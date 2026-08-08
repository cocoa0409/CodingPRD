"""Treatment-plan lifecycle: the revision cycle, activation state guard, and the
optimistic-concurrency / supersession rule.

Queue A: non_linear_state_machine (revision cycle).
Queue B: plan state machine, cross_cutting OCC.
"""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx


# ---------------------------------------------------- revision cycle (queue A)
def test_plan_reactivation_returns_to_active(api):
    """PRD §3.2: "Re-activating then returns it `UNDER_REVISION → ACTIVE`, and the
    plan may cycle between these two states any number of times."

    Design: Difficulty/non_linear_state_machine/treatment_plan_revision_cycle
    """
    ctx = fx.setup_active_plan(api, payer="INSURANCE")
    api.revise_plan(ctx["plan_id"], {"revision_note": "Adjust goals"}, TEST_USERS["clinical_headers"])
    resp = api.activate_plan(ctx["plan_id"], TEST_USERS["clinical_headers"])
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "ACTIVE", "plan returns to ACTIVE after the second activate"


def test_plan_revision_increments_count(api):
    """PRD §3.2: "an `ACTIVE` plan may be opened for revision, moving it
    `ACTIVE → UNDER_REVISION`, incrementing `revision_count` by 1, and recording the
    optional `revision_note`".

    Design: Difficulty/non_linear_state_machine/treatment_plan_revision_cycle
    """
    ctx = fx.setup_active_plan(api, payer="INSURANCE")
    api.revise_plan(ctx["plan_id"], {"revision_note": "Adjust goals"}, TEST_USERS["clinical_headers"])
    resp = api.activate_plan(ctx["plan_id"], TEST_USERS["clinical_headers"])
    data = validate_success(resp, expected_status=200)
    assert data["revision_count"] == 1, "revision_count is 1 after one revise"


# ---------------------------------------------------- activation guard (queue B)
def test_activate_already_active_plan_rejected(api):
    """PRD §3.2: "A plan may only be activated from `DRAFT` or from `UNDER_REVISION`;
    attempting it from any other state yields `ERR_PLAN_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_plan_rejected
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")  # plan already ACTIVE
    resp = api.activate_plan(ctx["plan_id"], TEST_USERS["clinical_headers"])
    validate_error(resp, ApiErrorId.ERR_PLAN_INVALID_STATE.value)


# ------------------------------------------------- optimistic concurrency (B)
def test_occ_stale_client_version_rejected(api):
    """PRD §2.8: "If `expected_client_version` does not equal the client's current
    `version`, the create is rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_client_version_rejected
    """
    ther = fx.new_therapist(api)
    client = fx.new_self_pay_client(api)
    cv0 = client["version"]
    ref1 = fx.new_referral(api, client["id"])
    fx.assess(api, ref1["id"], ther["id"])
    ref2 = fx.new_referral(api, client["id"], reason="y")
    fx.assess(api, ref2["id"], ther["id"], baseline_score=42)
    fx.new_plan(api, client["id"], ref1["id"], cv0)  # first create advances client.version
    resp = api.create_treatment_plan(
        client["id"],
        {"referral_id": ref2["id"], "discipline": "MUSIC", "weekly_frequency": 1,
         "expected_client_version": cv0},
        TEST_USERS["clinical_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_CLIENT_VERSION.value)


def test_occ_fresh_client_version_supersedes_prior_plan(api):
    """PRD §3.2: "any plan the client already holds in `DRAFT` or `ACTIVE` status is
    superseded — it transitions to `SUPERSEDED`." PRD §2.8: "creating a new plan
    supersedes the client's prior plan and advances the client's `version`".

    Design: Corner/cross_cutting_complexity_layers/occ_fresh_client_version_supersedes_prior_plan
    """
    ther = fx.new_therapist(api)
    client = fx.new_self_pay_client(api)
    cv0 = client["version"]
    ref1 = fx.new_referral(api, client["id"])
    fx.assess(api, ref1["id"], ther["id"])
    ref2 = fx.new_referral(api, client["id"], reason="y")
    fx.assess(api, ref2["id"], ther["id"], baseline_score=42)
    plan1 = fx.new_plan(api, client["id"], ref1["id"], cv0)
    fx.activate_plan(api, plan1["id"])
    cv_fresh = fx.get_client_version(api, client["id"])
    resp = api.create_treatment_plan(
        client["id"],
        {"referral_id": ref2["id"], "discipline": "MUSIC", "weekly_frequency": 1,
         "expected_client_version": cv_fresh},
        TEST_USERS["clinical_headers"])
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    plan1_after = validate_success(
        api.get_treatment_plan(plan1["id"], TEST_USERS["clinical_headers"]), expected_status=200)
    assert plan1_after["status"] == "SUPERSEDED", "prior ACTIVE plan is superseded"
