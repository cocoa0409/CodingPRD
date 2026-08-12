"""Contract lifecycle: initial states, suspension, amendments, expiry, renewal."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    create_storm_event_payload, create_amendment_payload, create_true_up_payload,
    setup_client, setup_site, setup_contract, link_site, activate_contract,
    setup_active_per_push, setup_active_seasonal, setup_storm_event,
    schedule_visit, set_clock, setup_subcontractor,
    setup_completed_visit, setup_billable_visit, expire_contract_at,
    create_visit_payload, create_subcontractor_payload,
)

DISPATCH = TEST_USERS["ops_dispatcher_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_initial_states_on_creation(api):
    """PRD §3.1: "A new contract is born in `DRAFT` with `version` 1 and every season accumulator at zero"
    PRD §3.3: "The event is born `REPORTED`"
    PRD §3.4: "The record is born `PENDING` with `assignments_released_count`, `assignments_failed_count`, and `active_assignment_count` all at zero."
    PRD §3.5: "starts the visit with `execution_status` `SCHEDULED` and `billing_status` `PENDING`"
    PRD §3.5: "computes `sla_deadline_at` as the storm's `window_end` plus the link's `completion_target_minutes`"

    Design: Corner/state_machines/initial_states_on_creation
    """
    client = setup_client(name="Init States Co")
    site = setup_site(client["id"], name="Init Lot")
    contract = setup_contract(client["id"], contract_type="PER_PUSH",
                              per_push_rate_cents=45_000,
                              require_photo_verification=False)
    assert contract["status"] == "DRAFT"
    assert contract["version"] == 1
    assert contract["season_billable_push_count"] == 0
    assert contract["season_billed_cents"] == 0
    assert contract["overage_active"] is False

    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    assert event["status"] == "REPORTED"

    sub = get_success_data(api.create_subcontractor(
        create_subcontractor_payload(legal_name="Init Sub",
                                     contact_email="i@sub.example"),
        DISPATCH))
    assert sub["status"] == "PENDING"
    assert sub["assignments_released_count"] == 0
    assert sub["assignments_failed_count"] == 0
    assert sub["active_assignment_count"] == 0
    assert sub["reliability_score"] == 0

    contract_site = link_site(contract["id"], site["id"],
                              priority_sequence=1, completion_target_minutes=360)
    activate_contract(contract["id"])
    visit = schedule_visit(event["id"], contract_site["id"],
                           scheduled_start="2026-12-10T09:00:00Z",
                           scheduled_end="2026-12-10T10:00:00Z")
    assert visit["execution_status"] == "SCHEDULED"
    assert visit["billing_status"] == "PENDING"
    assert visit["sla_deadline_at"] == "2026-12-10T14:00:00.000Z", (
        "window_end 08:00 + 360 completion minutes = 14:00")


def test_suspend_blocks_visit_creation_and_resume_restores(api):
    """PRD §3.2: "Suspension takes `ACTIVE` to `SUSPENDED` and blocks new visit creation for the contract while it lasts (rejected with `ERR_CONTRACT_NOT_ACTIVE`); resumption takes `SUSPENDED` back to `ACTIVE`."

    Design: Corner/state_machines/contract_suspend_resume_cycle_gates_visit_creation
    """
    ctx = setup_active_per_push(client_name="Suspend Co", require_photo_verification=False)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()

    suspended = validate_success(
        api.suspend_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert suspended["status"] == "SUSPENDED"

    payload = create_visit_payload(event["id"], ctx["contract_site"]["id"])
    validate_error(api.create_visit(payload, DISPATCH),
                   ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    resumed = validate_success(
        api.resume_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert resumed["status"] == "ACTIVE"

    visit = validate_success(api.create_visit(payload, DISPATCH), 201)
    assert visit["execution_status"] == "SCHEDULED"


def test_amendment_supersede_and_approve_applies_changes(api):
    """PRD §3.2: "Exactly one amendment per contract may be `PENDING` at any time: a successful creation moves any previously `PENDING` amendment of the same contract to `SUPERSEDED`, and the creation itself increments the contract's `version` by one."
    PRD §3.2: "applies each non-null change field onto the contract, increments the contract's `version` again"
    PRD §3.2: "`APPROVED`, `REJECTED`, and `SUPERSEDED` are all terminal."
    PRD §2.8: "a resource already in a terminal state rejects every transition with `ERR_ALREADY_TERMINAL`"

    Design: Corner/state_machines/amendment_supersede_and_approve_applies_changes
    """
    ctx = setup_active_per_push(client_name="Amend Co", trigger_depth_inches=2.0,
                                per_push_rate_cents=45_000,
                                require_photo_verification=False)
    contract_id = ctx["contract"]["id"]
    version_after_activate = ctx["contract"]["version"]  # 2 (create=1, activate=2)
    assert version_after_activate == 2

    am1 = validate_success(api.create_amendment(
        create_amendment_payload(contract_id, version_after_activate,
                                 "2027-01-01T00:00:00Z", trigger_depth_inches=2.5),
        DISPATCH), 201)
    assert am1["status"] == "PENDING"
    contract_v3 = validate_success(api.get_contract(contract_id, DISPATCH), 200)
    assert contract_v3["version"] == 3

    am2 = validate_success(api.create_amendment(
        create_amendment_payload(contract_id, 3, "2027-01-15T00:00:00Z",
                                 trigger_depth_inches=3.0, per_push_rate_cents=50_000),
        DISPATCH), 201)
    assert am2["status"] == "PENDING"

    amendments, _ = validate_paginated(
        api.list_contract_amendments(contract_id, DISPATCH))
    by_id = {a["id"]: a for a in amendments}
    assert by_id[am1["id"]]["status"] == "SUPERSEDED"

    approved = validate_success(api.approve_amendment(am2["id"], DISPATCH), 200)
    assert approved["status"] == "APPROVED"

    validate_error(api.approve_amendment(am1["id"], DISPATCH),
                   ApiErrorId.ERR_ALREADY_TERMINAL)

    contract = validate_success(api.get_contract(contract_id, DISPATCH), 200)
    assert contract["trigger_depth_inches"] == 3.0
    assert contract["per_push_rate_cents"] == 50_000
    assert contract["version"] == 5, (
        "version advances once per mutation: 2 (activate) -> 3 (amendment 1) "
        "-> 4 (amendment 2) -> 5 (approve)")


def test_amendment_effective_from_outside_season_rejected(api):
    """PRD §3.2: "records an `effective_from` marker that must fall strictly after `season_start` and no later than `season_end`, failing as `ERR_AMENDMENT_WINDOW_INVALID` otherwise."

    Design: Corner/validations/amendment_effective_from_outside_season_rejected
    """
    ctx = setup_active_per_push(client_name="Amend Window Co")
    version = ctx["contract"]["version"]
    validate_error(api.create_amendment(
        create_amendment_payload(ctx["contract"]["id"], version,
                                 "2027-04-15T00:00:00Z", trigger_depth_inches=3.0),
        DISPATCH), ApiErrorId.ERR_AMENDMENT_WINDOW_INVALID)


def test_activate_contract_without_sites_returns_error(api):
    """PRD §3.2: "Activation — performed by an `OpsDispatcher` — requires at least one ContractSite linked to the contract, failing as `ERR_CONTRACT_HAS_NO_SITES` when none exists"

    Design: Corner/validations/activate_contract_without_sites_returns_error
    """
    client = setup_client(name="No Sites Co")
    contract = setup_contract(client["id"], contract_type="PER_PUSH",
                              require_photo_verification=False)
    validate_error(api.activate_contract(contract["id"], DISPATCH),
                   ApiErrorId.ERR_CONTRACT_HAS_NO_SITES)
    contract_after = validate_success(api.get_contract(contract["id"], DISPATCH), 200)
    assert contract_after["status"] == "DRAFT"


def test_expire_blocked_by_open_work(api):
    """PRD §3.2: "It requires the logical clock to be strictly later than `season_end` — expiring at or before season end fails as `ERR_INVALID_STATE` — and no visit of the contract may remain in `SCHEDULED`, `IN_PROGRESS`, or `AWAITING_BACKUP`, failing as `ERR_CONTRACT_HAS_OPEN_WORK`."
    PRD §3.5: "A dispatcher may cancel a `SCHEDULED` visit to `CANCELLED` outright."

    Design: Corner/validations/expire_blocked_by_open_work
    """
    ctx = setup_active_per_push(client_name="Open Work Co",
                                season_end="2026-12-31T23:59:59Z")
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    visit = schedule_visit(event["id"], ctx["contract_site"]["id"])
    set_clock("2027-01-05T00:00:00Z")

    validate_error(api.expire_contract(ctx["contract"]["id"], DISPATCH),
                   ApiErrorId.ERR_CONTRACT_HAS_OPEN_WORK)

    cancelled = validate_success(api.cancel_visit(visit["id"], DISPATCH), 200)
    assert cancelled["execution_status"] == "CANCELLED"

    expired = validate_success(api.expire_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert expired["status"] == "EXPIRED"


def test_renewal_blocked_by_open_trueup_and_non_expired_source(api):
    """PRD §3.2: "Renewing an expired contract spawns a brand-new contract in `DRAFT` carrying the same `client_id`, `contract_type`, and rate terms unless the renewal payload overrides them"
    PRD §3.2: "Renewal is refused while any true-up of the contract is still `DRAFT` or `ISSUED` — rejected with `ERR_RENEWAL_BLOCKED` — and the new `season_start` must be strictly later than the source contract's `season_end`."
    PRD §3.2: "The new contract's `prior_contract_id` points at the source; the source's `renewed_to_contract_id` is set to the new id and its `version` increments by one, while the source itself remains `EXPIRED` forever."
    PRD §3.9: "success stamps `settled_at` and makes the parent contract eligible for the renewal flow of §3.2."

    Design: Corner/validations/renewal_blocked_by_open_trueup_and_non_expired_source
    """
    ctx = setup_active_seasonal(client_name="Renew Co", seasonal_push_cap=2,
                                completion_target_minutes=480)
    contract_id = ctx["contract"]["id"]
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    setup_billable_visit(ctx, event, [
        ("NOAA", "2026-12-10T07:30:00Z", 2.0),
        ("DTN", "2026-12-10T08:00:00Z", 2.1),
    ])

    renew_payload = {"season_start": "2027-11-01T00:00:00Z",
                     "season_end": "2028-03-31T23:59:59Z"}

    # Renew while still ACTIVE: renewal is defined only for an expired contract.
    validate_error(api.renew_contract(contract_id, renew_payload, DISPATCH),
                   ApiErrorId.ERR_INVALID_STATE)

    expired = expire_contract_at(contract_id)
    true_up = validate_success(api.create_true_up(
        create_true_up_payload(contract_id, expired["version"]), DISPATCH), 201)
    assert true_up["balance_due_cents"] == 0, (
        "one push under cap 2, no materials, no misses -> nothing due")
    get_success_data(api.issue_true_up(true_up["id"], DISPATCH))

    # Renew while the true-up is ISSUED (still open).
    validate_error(api.renew_contract(contract_id, renew_payload, DISPATCH),
                   ApiErrorId.ERR_RENEWAL_BLOCKED)

    settled = validate_success(api.settle_true_up(
        true_up["id"], {"settled_amount_cents": 0}, DISPATCH), 200)
    assert settled["status"] == "SETTLED"

    renewal = validate_success(
        api.renew_contract(contract_id, renew_payload, DISPATCH), 201)
    assert renewal["status"] == "DRAFT"
    assert renewal["contract_type"] == "SEASONAL"
    assert renewal["prior_contract_id"] == contract_id

    source = validate_success(api.get_contract(contract_id, DISPATCH), 200)
    assert source["renewed_to_contract_id"] == renewal["id"]
    assert source["status"] == "EXPIRED"


def test_subcontractor_reapprove_cycle(api):
    """PRD §3.4: "A `PlatformAdmin` approves `PENDING` to `APPROVED`, may suspend an `APPROVED` subcontractor to `SUSPENDED`, and may re-approve a `SUSPENDED` one back to `APPROVED`."

    Design: Corner/state_machines/subcontractor_reapprove_cycle
    """
    sub = setup_subcontractor(legal_name="Reapprove LLC",
                              contact_email="r@sub.example", approve=False)
    assert sub["status"] == "PENDING"
    approved = validate_success(api.approve_subcontractor(sub["id"], ADMIN), 200)
    assert approved["status"] == "APPROVED"
    suspended = validate_success(api.suspend_subcontractor(sub["id"], ADMIN), 200)
    assert suspended["status"] == "SUSPENDED"
    reapproved = validate_success(api.approve_subcontractor(sub["id"], ADMIN), 200)
    assert reapproved["status"] == "APPROVED"


def test_duplicate_priority_sequence_within_contract_rejected(api):
    """PRD §3.1: "The `priority_sequence` is unique within a contract — a duplicate is rejected with `ERR_PRIORITY_SEQUENCE_CONFLICT` — and lower values are serviced first."

    Design: Corner/validations/duplicate_priority_sequence_within_contract_rejected
    """
    from test_helpers import create_contract_site_payload
    client = setup_client(name="Prio Co")
    site1 = setup_site(client["id"], name="Lot One", address="1 Prio St")
    site2 = setup_site(client["id"], name="Lot Two", address="2 Prio St")
    contract = setup_contract(client["id"], contract_type="PER_PUSH",
                              require_photo_verification=False)
    link_site(contract["id"], site1["id"], priority_sequence=1,
              completion_target_minutes=360)

    validate_error(api.create_contract_site(
        create_contract_site_payload(contract["id"], site2["id"],
                                     priority_sequence=1,
                                     completion_target_minutes=300),
        DISPATCH), ApiErrorId.ERR_PRIORITY_SEQUENCE_CONFLICT)
