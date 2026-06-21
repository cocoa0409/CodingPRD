"""Resource creation, retrieval, defaults, computed/system fields, and integrity.

Translates queue B (Corner) instances from the `entities` section, plus a couple of
`errors`/`rbac`/`consistency_model` breadth instances that are pure single-resource claims.
"""
import pytest

from test_helpers import (
    api_client as _ac,  # noqa: F401  (kept for symmetry; tests use the `api` fixture)
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_grid_operator_headers,
    make_program_admin_headers,
    make_subscriber_headers,
    factories as f,
    fixtures as fx,
)

GO = TEST_USERS["grid_operator_headers"]
PA = TEST_USERS["program_admin_headers"]


# ─── Creation / derived defaults ──────────────────────────────────────

def test_create_project_returns_201_with_derived_ledger_defaults(api):
    """PRD §3.1: "At creation the project starts `OPEN`, its `committed_kw` and all
    REC balances are zero, and its `available_kw` equals the full `nameplate_capacity_kw`."

    Design: Corner/entities/create_project_returns_201_with_derived_ledger_defaults
    """
    resp = api.create_project(
        f.create_project_payload(name="P1", state_code="NY",
                                 nameplate_capacity_kw=100, credit_rate_cents_per_kwh=10),
        GO,
    )
    data = validate_success(resp, 201)
    assert data["committed_kw"] == 0
    assert data["available_kw"] == 100
    assert data["status"] == "OPEN"
    assert data["rec_minted_total"] == 0
    assert data["rec_available_balance"] == 0


def test_get_subscriber_returns_stored_data(api):
    """PRD §3.2: "A `ProgramAdmin` registers a utility subscriber with a `full_name`,
    a `utility_account_no`, a `state_code` naming the jurisdiction of that utility
    account, an optional `is_low_income` flag (defaulting to false), and a
    self-reported `annual_usage_kwh` of at least zero."

    Design: Corner/entities/get_subscriber_returns_stored_data
    """
    created = get_success_data(
        api.create_subscriber(
            f.create_subscriber_payload(full_name="Jane Q", utility_account_no="ACC-C1",
                                        state_code="NY", annual_usage_kwh=50000),
            PA,
        )
    )
    resp = api.get_subscriber(created["id"], PA)
    data = validate_success(resp, 200)
    assert data["full_name"] == "Jane Q"
    assert data["utility_account_no"] == "ACC-C1"


def test_create_project_omitting_carve_out_pct_applies_default(api):
    """PRD §2.6: "The carve-out percentage defaults to 0.40 and must lie between 0
    and 1 inclusive; the program fee rate defaults to 0.10 and must be at least 0
    and strictly less than 1."

    Design: Corner/entities/create_project_omitting_carve_out_pct_applies_default
    """
    resp = api.create_project(
        f.create_project_payload(name="P4", nameplate_capacity_kw=100,
                                 credit_rate_cents_per_kwh=10),
        GO,
    )
    data = validate_success(resp, 201)
    assert data["carve_out_pct"] == 0.40
    assert data["program_fee_rate"] == 0.10


def test_project_available_kw_computed_input_ignored(api):
    """PRD §2.5: "`available_kw` is the project's `nameplate_capacity_kw` minus
    `committed_kw`, never allowed to fall below zero."

    Design: Corner/entities/project_available_kw_computed_input_ignored
    """
    resp = api.create_project(
        f.create_project_payload(name="P5", nameplate_capacity_kw=80,
                                 credit_rate_cents_per_kwh=10),
        GO,
    )
    data = validate_success(resp, 201)
    assert data["available_kw"] == 80


def test_subscriber_system_fields_generated(api):
    """PRD §3.2: "On registration the subscriber's `lifetime_savings_cents` starts
    at zero and its `churn_risk_score` is initialized."
    PRD §3.2: "it starts at zero, adds 40 if the subscriber has any subscription
    currently in `SUSPENDED`, adds 35 if the subscriber has any reconciliation whose
    dispute dimension is currently `DISPUTED`, and adds 10 if the subscriber's
    `is_low_income` is true; the running total is then capped so it never exceeds 100."

    Design: Corner/entities/subscriber_system_fields_generated
    """
    resp = api.create_subscriber(
        f.create_subscriber_payload(full_name="Sys Gen", utility_account_no="ACC-C3",
                                    state_code="NY", annual_usage_kwh=0),
        PA,
    )
    data = validate_success(resp, 201)
    assert data["lifetime_savings_cents"] == 0
    assert data["version"] == 1
    # Not SUSPENDED, no dispute, not low-income → 0.
    assert data["churn_risk_score"] == 0


# ─── Validation / type constraints ────────────────────────────────────

def test_create_project_carve_out_pct_out_of_range_returns_validation(api):
    """PRD §2.6: "Field values outside their allowed ranges — a carve-out percentage
    outside the 0-to-1 interval, or a negative share or usage figure — are rejected
    with `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/create_project_carve_out_pct_out_of_range_returns_validation
    """
    resp = api.create_project(
        f.create_project_payload(name="P6", nameplate_capacity_kw=100,
                                 carve_out_pct=1.5, credit_rate_cents_per_kwh=10),
        GO,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_create_enrollment_missing_requested_share_kw_returns_invalid_request(api):
    """PRD §2.9: "Fifth, required-field presence and typing — required body fields
    must be present and well-typed (for example `requested_share_kw`,
    `metered_production_kwh`, or `period_month`), else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_enrollment_missing_requested_share_kw_returns_invalid_request
    """
    project = fx.create_project(name="P3")
    subscriber = fx.create_subscriber(full_name="Miss Field", utility_account_no="ACC-C2")
    resp = api.create_enrollment(
        {"project_id": project["id"], "subscriber_id": subscriber["id"]},
        make_subscriber_headers(subscriber["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_get_project_nonexistent_id_returns_not_found(api):
    """PRD §2.9: "Third, path existence — every resource id named in the URL path
    must exist, validated left to right, else `ERR_NOT_FOUND`."

    Design: Corner/entities/get_project_nonexistent_id_returns_not_found
    """
    resp = api.get_project(NON_EXISTENT_UUID, GO)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_fk_integrity_enrollment_unknown_project_returns_reference_not_found(api):
    """PRD §2.9: "Fourth, referential existence — every foreign key in the request
    body (such as `project_id`, `subscriber_id`, or `target_subscriber_id`) must
    reference an existing resource, else `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/fk_integrity_enrollment_unknown_project_returns_reference_not_found
    """
    subscriber = fx.create_subscriber(full_name="Orphan", utility_account_no="ACC-C4")
    resp = api.create_enrollment(
        {"project_id": NON_EXISTENT_UUID, "subscriber_id": subscriber["id"],
         "requested_share_kw": 5.0},
        make_subscriber_headers(subscriber["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, 404)


# ─── Append-only immutability ─────────────────────────────────────────

def test_carve_out_adjustment_immutable_append_only_resource(api):
    """PRD §2.4: "The carve-out adjustment is an append-only audit record: it carries
    only `id` and `created_at`. It has no `updated_at` and no `version`, because it is
    never mutated after creation."
    PRD §3.1: "The service captures the prior fraction into `previous_carve_out_pct`,
    writes `new_carve_out_pct` onto the project's `carve_out_pct`, recomputes
    `carve_out_available_kw` from the new fraction, and increments the project's
    `version` by one."

    Design: Corner/entities/carve_out_adjustment_immutable_append_only_resource
    """
    project = fx.create_project(name="P7", carve_out_pct=0.40)
    resp = api.create_carve_out_adjustment(
        project["id"], f.carve_out_adjustment_payload(0.50, "expand carve-out"), PA
    )
    data = validate_success(resp, 201)
    assert data["previous_carve_out_pct"] == 0.40
    assert data["new_carve_out_pct"] == 0.50
    assert "version" not in data, "append-only record carries no version"


# ─── Listing / pagination envelope ────────────────────────────────────

def test_list_periods_paginated_envelope(api):
    """PRD §2.3: "Each list response surfaces, inside its `meta` object, the `limit`
    and `offset` in effect together with `total_count` (the total number of matching
    records before pagination) and `has_more` (a boolean that is true when records
    remain beyond the current page)."

    Design: Corner/entities/list_periods_paginated_envelope
    """
    project = fx.create_project(name="P2")
    fx.create_open_period(project["id"], "2026-01", 1000)
    resp = api.list_periods(GO, params={"project_id": project["id"]})
    data, meta = validate_paginated(resp)
    body = resp.json()
    assert body["response_type"] == "array"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_get_subscriptions_filtered_by_project_reverse_reachability(api):
    """PRD §3.5: "Subscriptions are listable and filterable in reverse by `project_id`,
    `subscriber_id`, `enrollment_id`, `transferred_from_subscription_id`, and
    `cancellation_effective_period_id`."

    Design: Corner/endpoints/get_subscriptions_filtered_by_project_reverse_reachability
    """
    project, subscriber, subscription = fx.setup_project_with_active_subscription()
    resp = api.list_subscriptions(GO, params={"project_id": project["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["id"] == subscription["id"]


# ─── Consistency model (immediate) ────────────────────────────────────

def test_activate_response_immediately_reflects_committed_capacity(api):
    """PRD §2.5: "each is recomputed by the service whenever a triggering event
    occurs, and every such recomputation is part of the same atomic request that
    caused it — there is no deferred or eventual settlement."
    PRD §3.4: "The project ledger is then resynced: `committed_kw` increases by the
    committed `share_kw`, and `available_kw`, `carve_out_committed_kw`, and
    `carve_out_available_kw` are all recomputed."

    Design: Corner/consistency_model/activate_response_immediately_reflects_committed_capacity
    """
    project = fx.create_project(name="P35")
    subscriber = fx.create_subscriber(full_name="Imm Sub", utility_account_no="ACC-C31")
    enr = fx.create_draft_enrollment(project["id"], subscriber["id"], 5.0)
    fx.submit_enrollment(enr["id"], subscriber["id"])
    fx.approve_enrollment(enr["id"])
    fx.activate_enrollment(enr["id"])
    data = get_success_data(api.get_project(project["id"], GO))
    assert data["committed_kw"] == 5
