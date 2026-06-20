"""Business validations, cross-entity state gates, duplicate-resource guards, OCC,
and RBAC. Translates queue A (Difficulty) rules `cross_entity_state_dependency`,
`resource_temporal_overlap`, the surviving `priority_pair_validation_conflict`
instance, and queue B (Corner) `validations` / `errors` / `rbac` /
`cross_cutting_complexity_layers` instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    build_user_headers,
    ApiErrorId,
    TEST_USERS,
    make_subscriber_headers,
    factories as f,
    fixtures as fx,
)

GO = TEST_USERS["grid_operator_headers"]
PA = TEST_USERS["program_admin_headers"]


# ─── Queue A: cross_entity_state_dependency ───────────────────────────

def test_period_close_blocked_by_disputed_reconciliation(api):
    """PRD §3.12: "Finally a `GridOperator` closes a `TRUED_UP` period, moving it
    `TRUED_UP → CLOSED`, but only if every reconciliation of that period has a dispute
    dimension of either `NONE` or `RESOLVED`; an attempt to close while any
    reconciliation is still `DISPUTED` is rejected with `ERR_OPEN_DISPUTE_BLOCKS_CLOSE`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/period_close_blocked_by_disputed_reconciliation
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-08", forecast_production_kwh=1000, metered_production_kwh=1000,
        project_overrides={"name": "Garden M", "program_fee_rate": 0.10},
    )
    recon = fx.first_reconciliation(reconciled["id"])
    fx.dispute_reconciliation(recon["id"], subscriber["id"])
    get_success_data(api.true_up_period(reconciled["id"], GO))
    resp = api.close_period(reconciled["id"], GO)
    validate_error(resp, ApiErrorId.ERR_OPEN_DISPUTE_BLOCKS_CLOSE.value, 409)
    after = fx.get_period(reconciled["id"])
    assert after["status"] == "TRUED_UP", "period stays TRUED_UP"


def test_transfer_blocked_by_subscriber_jurisdiction_mismatch(api):
    """PRD §3.5: "The target subscriber must exist, and the target's `state_code` must
    match the project's `state_code`; a jurisdiction mismatch is rejected with
    `ERR_TRANSFER_JURISDICTION_MISMATCH` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/transfer_blocked_by_subscriber_jurisdiction_mismatch
    """
    project = fx.create_project(name="Garden N", state_code="NY", nameplate_capacity_kw=100)
    owner = fx.create_subscriber(full_name="NY Holder", utility_account_no="ACC-16", state_code="NY")
    target = fx.create_subscriber(full_name="CA Target", utility_account_no="ACC-17", state_code="CA")
    subscription = fx.create_active_subscription(project["id"], owner["id"], 5.0)
    proj = fx.get_project(project["id"])
    resp = api.transfer_subscription(
        subscription["id"], f.transfer_payload(target["id"], proj["version"]),
        make_subscriber_headers(owner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TRANSFER_JURISDICTION_MISMATCH.value, 409)
    after = fx.get_subscription(subscription["id"])
    assert after["status"] == "ACTIVE", "subscription stays ACTIVE; no successor"


def test_period_closes_after_dispute_resolved(api):
    """PRD §3.12: "Finally a `GridOperator` closes a `TRUED_UP` period, moving it
    `TRUED_UP → CLOSED`, but only if every reconciliation of that period has a dispute
    dimension of either `NONE` or `RESOLVED`; an attempt to close while any
    reconciliation is still `DISPUTED` is rejected with `ERR_OPEN_DISPUTE_BLOCKS_CLOSE`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/period_close_blocked_by_disputed_reconciliation
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-08", forecast_production_kwh=1000, metered_production_kwh=1000,
        project_overrides={"name": "Garden M2", "program_fee_rate": 0.10},
    )
    recon = fx.first_reconciliation(reconciled["id"])
    fx.dispute_reconciliation(recon["id"], subscriber["id"])
    get_success_data(api.resolve_dispute(recon["id"], PA))
    get_success_data(api.true_up_period(reconciled["id"], GO))
    closed = get_success_data(api.close_period(reconciled["id"], GO))
    assert closed["status"] == "CLOSED", "close allowed once dispute is RESOLVED"


def test_transfer_to_matching_jurisdiction_succeeds(api):
    """PRD §3.5: "The target subscriber must exist, and the target's `state_code` must
    match the project's `state_code`; a jurisdiction mismatch is rejected with
    `ERR_TRANSFER_JURISDICTION_MISMATCH` (HTTP 409)."
    PRD §3.5: "On success the service creates a successor subscription in status
    `ACTIVE` owned by the target, copying the same `share_kw`, setting
    `transferred_from_subscription_id` to the original subscription's id, and setting
    the successor's `is_carve_out` from the target subscriber's `is_low_income`."

    Design: Difficulty/cross_entity_state_dependency/transfer_blocked_by_subscriber_jurisdiction_mismatch
    """
    project = fx.create_project(name="Garden N2", state_code="NY", nameplate_capacity_kw=100)
    owner = fx.create_subscriber(full_name="NY Holder 2", utility_account_no="ACC-16b", state_code="NY")
    target = fx.create_subscriber(full_name="NY Target 2", utility_account_no="ACC-17b", state_code="NY")
    subscription = fx.create_active_subscription(project["id"], owner["id"], 5.0)
    proj = fx.get_project(project["id"])
    successor = get_success_data(
        api.transfer_subscription(
            subscription["id"], f.transfer_payload(target["id"], proj["version"]),
            make_subscriber_headers(owner["id"]),
        )
    )
    assert successor["status"] == "ACTIVE"
    assert successor["transferred_from_subscription_id"] == subscription["id"]


# ─── Queue A: priority_pair_validation_conflict (surviving instance) ──

def test_state_invalid_beats_carve_out_on_activate(api):
    """PRD §2.9: "Eighth, state validity — the target resource must be in a state from
    which the requested transition is defined, else `ERR_INVALID_STATE`."
    PRD §2.9: "Only after all of these pass are the operation-specific business rules —
    carve-out, jurisdiction, usage cap, capacity, project-full, dispute, and the various
    REC and meter guards described throughout §3 — evaluated."

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_beats_carve_out_business_safety_on_activate
    """
    project = fx.create_project(name="Garden J", nameplate_capacity_kw=100,
                                carve_out_pct=0.40)
    subscriber = fx.create_subscriber(full_name="LI Big", utility_account_no="ACC-12",
                                      is_low_income=True)
    # Enrollment left in DRAFT (never submitted/approved); also over carve-out (41 > 40).
    enr = fx.create_draft_enrollment(project["id"], subscriber["id"], 41.0)
    resp = api.activate_enrollment(enr["id"], PA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_state_invalid_beats_carve_out_activate_preserves_draft(api):
    """PRD §2.9: "Eighth, state validity — the target resource must be in a state from
    which the requested transition is defined, else `ERR_INVALID_STATE`."
    PRD §2.9: "Only after all of these pass are the operation-specific business rules —
    carve-out, jurisdiction, usage cap, capacity, project-full, dispute, and the various
    REC and meter guards described throughout §3 — evaluated."

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_beats_carve_out_business_safety_on_activate
    """
    project = fx.create_project(name="Garden J2", nameplate_capacity_kw=100,
                                carve_out_pct=0.40)
    subscriber = fx.create_subscriber(full_name="LI Big 2", utility_account_no="ACC-12b",
                                      is_low_income=True)
    enr = fx.create_draft_enrollment(project["id"], subscriber["id"], 41.0)
    resp = api.activate_enrollment(enr["id"], PA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = get_success_data(api.get_enrollment(enr["id"], PA))
    assert after["status"] == "DRAFT", "enrollment unchanged; activation rejected on state"


# ─── Queue A: resource_temporal_overlap ───────────────────────────────

def test_duplicate_period_month_same_project_rejected(api):
    """PRD §3.7: "The `period_month` must be unique within the project; a duplicate is
    rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/duplicate_period_month_same_project_rejected
    """
    project = fx.create_project(name="Garden O")
    fx.create_open_period(project["id"], "2026-09", 1000)
    resp = api.create_period(
        f.create_period_payload(project["id"], "2026-09", forecast_production_kwh=2000), GO
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)


def test_duplicate_utility_account_no_across_subscribers_rejected(api):
    """PRD §3.2: "The `utility_account_no` must be unique across all subscribers; a
    collision is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/duplicate_utility_account_no_across_subscribers_rejected
    """
    fx.create_subscriber(full_name="First", utility_account_no="ACC-DUP")
    resp = api.create_subscriber(
        f.create_subscriber_payload(full_name="Second", utility_account_no="ACC-DUP"), PA
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)


def test_distinct_period_months_same_project_both_created(api):
    """PRD §3.7: "The `period_month` must be unique within the project; a duplicate is
    rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/duplicate_period_month_same_project_rejected
    """
    project = fx.create_project(name="Garden O2")
    fx.create_open_period(project["id"], "2026-09", 1000)
    # A different month on the same project is NOT a collision.
    resp = api.create_period(
        f.create_period_payload(project["id"], "2026-10", forecast_production_kwh=2000), GO
    )
    validate_success(resp, 201)


def test_distinct_utility_account_no_second_subscriber_created(api):
    """PRD §3.2: "The `utility_account_no` must be unique across all subscribers; a
    collision is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/duplicate_utility_account_no_across_subscribers_rejected
    """
    fx.create_subscriber(full_name="First Distinct", utility_account_no="ACC-DUP-A")
    # A distinct account number registers successfully.
    resp = api.create_subscriber(
        f.create_subscriber_payload(full_name="Second Distinct", utility_account_no="ACC-DUP-B"), PA
    )
    validate_success(resp, 201)


# ─── Queue B: validations section ─────────────────────────────────────

def test_usage_cap_exact_boundary_passes_submit(api):
    """PRD §3.3: "And the requested share must fit the subscriber's self-reported
    consumption under the **annual-usage cap**: the `requested_share_kw` multiplied by 1000
    must be no greater than the subscriber's `annual_usage_kwh`, else
    `ERR_USAGE_CAP_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/usage_cap_exact_boundary_passes_submit
    """
    project = fx.create_project(name="P19")
    subscriber = fx.create_subscriber(full_name="Cap Edge", utility_account_no="ACC-C18",
                                      annual_usage_kwh=5000)
    enr = fx.create_draft_enrollment(project["id"], subscriber["id"], 5.0)
    resp = api.submit_enrollment(enr["id"], make_subscriber_headers(subscriber["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "SUBMITTED"  # 5.0*1000 == 5000 <= 5000


def test_usage_cap_exceeded_returns_error(api):
    """PRD §3.3: "And the requested share must fit the subscriber's self-reported
    consumption under the **annual-usage cap**: the `requested_share_kw` multiplied by 1000
    must be no greater than the subscriber's `annual_usage_kwh`, else
    `ERR_USAGE_CAP_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/usage_cap_exceeded_returns_error
    """
    project = fx.create_project(name="P20")
    subscriber = fx.create_subscriber(full_name="Cap Over", utility_account_no="ACC-C19",
                                      annual_usage_kwh=5000)
    enr = fx.create_draft_enrollment(project["id"], subscriber["id"], 6.0)
    resp = api.submit_enrollment(enr["id"], make_subscriber_headers(subscriber["id"]))
    validate_error(resp, ApiErrorId.ERR_USAGE_CAP_EXCEEDED.value, 409)
    after = get_success_data(api.get_enrollment(enr["id"], PA))
    assert after["status"] == "DRAFT", "enrollment stays DRAFT"


def test_carve_out_exceeded_on_approve_returns_error(api):
    """PRD §3.3: "If the subscriber is low-income, approval additionally requires that
    the `requested_share_kw` fit within the project's `carve_out_available_kw`;
    otherwise approval is rejected with `ERR_CARVE_OUT_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/carve_out_exceeded_on_approve_returns_error
    """
    project = fx.create_project(name="P21", nameplate_capacity_kw=100, carve_out_pct=0.40)
    subscriber = fx.create_subscriber(full_name="LI Over", utility_account_no="ACC-C20",
                                      is_low_income=True)
    enr = fx.create_draft_enrollment(project["id"], subscriber["id"], 41.0)
    fx.submit_enrollment(enr["id"], subscriber["id"])
    resp = api.approve_enrollment(enr["id"], PA)
    validate_error(resp, ApiErrorId.ERR_CARVE_OUT_EXCEEDED.value, 409)


def test_pagination_limit_out_of_bounds_returns_error(api):
    """PRD §2.3: "A `limit` below 1 or above 100, or an `offset` below 0, is rejected
    with `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/validations/pagination_limit_out_of_bounds_returns_error
    """
    project = fx.create_project(name="P22")
    resp = api.list_periods(GO, params={"project_id": project["id"], "limit": 0})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value, 400)


# ─── Queue B: errors section ──────────────────────────────────────────

def test_meter_missing_reading_returns_meter_reading_required(api):
    """PRD §3.9: "The request must supply `metered_production_kwh` (present and at least
    zero, else `ERR_METER_READING_REQUIRED`, HTTP 400) and the optimistic-concurrency
    `expected_period_version` matching the period's current `version` (else
    `ERR_STALE_PERIOD_VERSION`, HTTP 412)."

    Design: Corner/errors/meter_missing_reading_returns_meter_reading_required
    """
    project = fx.create_project(name="P26")
    period = fx.create_open_period(project["id"], "2026-10", 1000)
    resp = api.meter_period(period["id"], {"expected_period_version": period["version"]}, GO)
    validate_error(resp, ApiErrorId.ERR_METER_READING_REQUIRED.value, 400)
    after = fx.get_period(period["id"])
    assert after["status"] == "OPEN", "period stays OPEN"


def test_rec_retire_missing_beneficiary_returns_error(api):
    """PRD §3.13: "Retiring it requires a `retirement_beneficiary` (else
    `ERR_REC_BENEFICIARY_REQUIRED`, HTTP 400) and moves it `ALLOCATED → RETIRED`, which
    increases the project's `rec_retired_total` by the batch's `rec_count` so the
    project's `rec_available_balance` falls."

    Design: Corner/endpoints/rec_retire_missing_beneficiary_returns_error
    """
    project, subscriber, subscription, reconciled, allocated = fx.setup_allocated_rec_batch(
        period_month="2026-09", metered_production_kwh=10000, requested_share_kw=5.0
    )
    resp = api.retire_rec_batch(allocated["id"], {}, PA)
    validate_error(resp, ApiErrorId.ERR_REC_BENEFICIARY_REQUIRED.value, 400)
    after = get_success_data(api.get_rec_batch(allocated["id"], PA))
    assert after["status"] == "ALLOCATED", "batch stays ALLOCATED"


def test_rec_transfer_missing_counterparty_returns_error(api):
    """PRD §3.13: "Transferring it requires a `transfer_counterparty` (else
    `ERR_REC_COUNTERPARTY_REQUIRED`, HTTP 400) and moves it `ALLOCATED → TRANSFERRED`,
    which decreases the project's `rec_available_balance` by the batch's `rec_count`
    while leaving `rec_retired_total` unchanged — a side effect deliberately divergent
    from retirement."

    Design: Corner/errors/rec_transfer_missing_counterparty_returns_error
    """
    project, subscriber, subscription, reconciled, allocated = fx.setup_allocated_rec_batch(
        period_month="2026-11", metered_production_kwh=10000, requested_share_kw=5.0
    )
    resp = api.transfer_rec_batch(allocated["id"], {}, PA)
    validate_error(resp, ApiErrorId.ERR_REC_COUNTERPARTY_REQUIRED.value, 400)
    after = get_success_data(api.get_rec_batch(allocated["id"], PA))
    assert after["status"] == "ALLOCATED", "batch stays ALLOCATED"


def test_dispute_blocks_apply_returns_error(api):
    """PRD §3.11: "The same operator then applies an `ISSUED` reconciliation, moving the
    credit dimension `ISSUED → APPLIED`; application requires that the dispute dimension
    is not currently `DISPUTED`, else `ERR_DISPUTE_BLOCKS_APPLY` (HTTP 409)."

    Design: Corner/errors/dispute_blocks_apply_returns_error
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-12", forecast_production_kwh=1000, metered_production_kwh=1000,
        project_overrides={"name": "P28", "program_fee_rate": 0.10},
    )
    recon = fx.first_reconciliation(reconciled["id"])
    fx.issue_reconciliation(recon["id"])
    fx.dispute_reconciliation(recon["id"], subscriber["id"])
    resp = api.apply_reconciliation(recon["id"], GO)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_BLOCKS_APPLY.value, 409)
    after = get_success_data(api.get_reconciliation(recon["id"], GO))
    assert after["credit_status"] == "ISSUED", "credit_status stays ISSUED"


def test_reopen_after_applied_returns_recon_already_applied(api):
    """PRD §3.12: "A `RECONCILED` period that should not have been finalized can be
    reopened by a `GridOperator`, moving it `RECONCILED → METERED`, provided no
    reconciliation of that period has yet reached credit `APPLIED`; a reopen attempted
    after any reconciliation was applied is rejected with `ERR_RECON_ALREADY_APPLIED`
    (HTTP 409)."

    Design: Corner/errors/reopen_after_applied_returns_recon_already_applied
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2027-01", forecast_production_kwh=1000, metered_production_kwh=1000,
        project_overrides={"name": "P29", "program_fee_rate": 0.10},
    )
    recon = fx.first_reconciliation(reconciled["id"])
    fx.issue_reconciliation(recon["id"])
    fx.apply_reconciliation(recon["id"])
    resp = api.reopen_period(reconciled["id"], GO)
    validate_error(resp, ApiErrorId.ERR_RECON_ALREADY_APPLIED.value, 409)
    after = fx.get_period(reconciled["id"])
    assert after["status"] == "RECONCILED", "period stays RECONCILED"


def test_withdraw_non_queued_waitlist_entry_returns_error(api):
    """PRD §3.6: "The owner may withdraw a `QUEUED` entry, moving it
    `QUEUED → WITHDRAWN`; a withdraw attempted on an entry that is not `QUEUED` is
    rejected with `ERR_WAITLIST_NOT_QUEUED` (HTTP 409)."

    Design: Corner/endpoints/withdraw_non_queued_waitlist_entry_returns_error
    """
    project, holder, holder_sub, waiter, waitlist_entry = fx.setup_full_project_with_waitlist(
        nameplate_capacity_kw=10, holder_share=10.0, waiter_share=5.0
    )
    waiter_headers = make_subscriber_headers(waiter["id"])
    get_success_data(api.withdraw_waitlist_entry(waitlist_entry["id"], waiter_headers))
    resp = api.withdraw_waitlist_entry(waitlist_entry["id"], waiter_headers)
    validate_error(resp, ApiErrorId.ERR_WAITLIST_NOT_QUEUED.value, 409)
    after = get_success_data(api.get_waitlist_entry(waitlist_entry["id"], PA))
    assert after["status"] == "WITHDRAWN", "entry stays WITHDRAWN"


# ─── Queue B: rbac section ────────────────────────────────────────────

def test_subscriber_cannot_create_project_returns_forbidden(api):
    """PRD §2.1: "The grid operator is the only role that may create a project, open a
    billing period, set a meter reading, reconcile a period, sweep its true-up, reopen
    it, close it, issue an on-bill credit, and apply that credit to lifetime savings."

    Design: Corner/rbac/subscriber_cannot_create_project_returns_forbidden
    """
    subscriber = fx.create_subscriber(full_name="No Op", utility_account_no="ACC-C28",
                                      annual_usage_kwh=50000)
    resp = api.create_project(
        f.create_project_payload(name="X", nameplate_capacity_kw=100, credit_rate_cents_per_kwh=10),
        make_subscriber_headers(subscriber["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)


def test_grid_operator_cannot_approve_enrollment_returns_forbidden(api):
    """PRD §2.1: "The program administrator is the only role that may register a
    subscriber, change a project's carve-out percentage, approve, reject, or activate an
    enrollment, suspend or resume a subscription, resolve a dispute, and earmark, retire,
    or transfer a REC batch."

    Design: Corner/rbac/grid_operator_cannot_approve_enrollment_returns_forbidden
    """
    project = fx.create_project(name="P30")
    subscriber = fx.create_subscriber(full_name="RBAC Sub", utility_account_no="ACC-C29")
    enr = fx.create_draft_enrollment(project["id"], subscriber["id"], 5.0)
    fx.submit_enrollment(enr["id"], subscriber["id"])
    resp = api.approve_enrollment(enr["id"], GO)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)
    after = get_success_data(api.get_enrollment(enr["id"], PA))
    assert after["status"] == "SUBMITTED", "enrollment stays SUBMITTED"


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "A request missing the role header, or carrying a value that is not one
    of these three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    project = fx.create_project(name="P31")
    bad_headers = build_user_headers("nobody", "Anonymous")
    resp = api.get_project(project["id"], bad_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
