"""Closed-interval season overlap, optimistic concurrency, terminal lockdown."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    ApiErrorId, TEST_USERS,
    create_amendment_payload, create_true_up_payload, create_contract_site_payload,
    setup_client, setup_site, setup_contract, link_site, activate_contract,
    setup_active_per_push, setup_active_seasonal, setup_storm_event, set_clock,
    setup_billable_visit, setup_issued_event_invoice, expire_contract_at,
    schedule_visit, upload_photo,
    make_crew_headers,
)

DISPATCH = TEST_USERS["ops_dispatcher_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
CREW = TEST_USERS["crew_lead_headers"]

_OBS = [("NOAA", "2026-12-10T07:30:00Z", 2.0), ("DTN", "2026-12-10T08:00:00Z", 2.1)]


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / contract_season_overlap_closed_interval
# ---------------------------------------------------------------------------

def _setup_season_overlap_scenario(api):
    """Site sI covered by ACTIVE kI1 [2026-11-01, 2027-03-31T23:59:59Z]; two DRAFT
    successors: kI2 touching at the endpoint, kI3 starting one second past."""
    client = setup_client(name="Seasonal Holdings")
    site = setup_site(client["id"], name="Perimeter Lot", address="14 Boundary Rd",
                      pavement_area_sqft=22_000)
    k1 = setup_contract(client["id"], contract_type="PER_PUSH",
                        per_push_rate_cents=40_000, require_photo_verification=False)
    link_site(k1["id"], site["id"])
    activate_contract(k1["id"])
    k2 = setup_contract(client["id"], contract_type="PER_PUSH",
                        season_start="2027-03-31T23:59:59Z",
                        season_end="2027-11-30T23:59:59Z",
                        per_push_rate_cents=41_000, require_photo_verification=False)
    k3 = setup_contract(client["id"], contract_type="PER_PUSH",
                        season_start="2027-04-01T00:00:00Z",
                        season_end="2027-11-30T23:59:59Z",
                        per_push_rate_cents=41_000, require_photo_verification=False)
    return client, site, k1, k2, k3


def test_season_overlap_touching_closed_intervals_conflict(api):
    """PRD §3.1: "two contracts in `ACTIVE` or `SUSPENDED` status may not cover the same site over intersecting closed season intervals, and because the intervals are closed, seasons that merely touch at an endpoint still conflict — a violation is rejected with `ERR_SEASON_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/contract_season_overlap_closed_interval
    """
    _, site, _, k2, _ = _setup_season_overlap_scenario(api)
    # kI2's season_start touches the incumbent's season_end exactly: closed
    # intervals include both endpoints, so the seasons intersect.
    validate_error(api.create_contract_site(
        create_contract_site_payload(k2["id"], site["id"], priority_sequence=1,
                                     completion_target_minutes=360),
        DISPATCH), ApiErrorId.ERR_SEASON_WINDOW_OVERLAP)


def test_season_overlap_one_second_past_end_links_cleanly(api):
    """PRD §3.1: "two contracts in `ACTIVE` or `SUSPENDED` status may not cover the same site over intersecting closed season intervals, and because the intervals are closed, seasons that merely touch at an endpoint still conflict — a violation is rejected with `ERR_SEASON_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/contract_season_overlap_closed_interval
    """
    _, site, _, _, k3 = _setup_season_overlap_scenario(api)
    # kI3 starts one second past the incumbent's closed season end.
    link = validate_success(api.create_contract_site(
        create_contract_site_payload(k3["id"], site["id"], priority_sequence=1,
                                     completion_target_minutes=360),
        DISPATCH), 201)
    assert link["contract_id"] == k3["id"]


# ---------------------------------------------------------------------------
# Corner: optimistic concurrency on contract-scoped creation
# ---------------------------------------------------------------------------

def test_amendment_create_stale_version_returns_412(api):
    """PRD §2.7: "A request to create a ContractAmendment must carry `expected_contract_version`, holding the contract `version` the client last observed; if that value does not equal the contract's current `version`, the request is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). This guard matters because a successful amendment creation supersedes the previously PENDING amendment — a stale writer would otherwise discard an amendment it never observed."

    Design: Corner/cross_cutting_layers/amendment_create_stale_version_returns_412
    """
    ctx = setup_active_per_push(client_name="OCC Co", require_photo_verification=False)
    contract_id = ctx["contract"]["id"]
    observed_version = ctx["contract"]["version"]  # 2 after activation

    am1 = validate_success(api.create_amendment(
        create_amendment_payload(contract_id, observed_version,
                                 "2027-01-01T00:00:00Z", trigger_depth_inches=2.5),
        DISPATCH), 201)
    assert am1["status"] == "PENDING"

    # Replaying the pre-am1 version is stale now (creation bumped it to 3).
    validate_error(api.create_amendment(
        create_amendment_payload(contract_id, observed_version,
                                 "2027-01-15T00:00:00Z", per_push_rate_cents=50_000),
        DISPATCH), ApiErrorId.ERR_STALE_CONTRACT_VERSION)

    amendments, _ = validate_paginated(api.list_contract_amendments(contract_id, DISPATCH))
    by_id = {a["id"]: a for a in amendments}
    assert by_id[am1["id"]]["status"] == "PENDING", (
        "a rejected create supersedes nothing")

    contract = validate_success(api.get_contract(contract_id, DISPATCH), 200)
    assert contract["version"] == 3, "the failed create must not bump the version"


def test_trueup_create_stale_version_returns_412(api):
    """PRD §2.7: "The same rule governs SeasonalTrueUp creation: the request must carry `expected_contract_version` matching the contract's current `version`, and a mismatch is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), because a successful true-up creation supersedes the previously DRAFT true-up."

    Design: Corner/cross_cutting_layers/trueup_create_stale_version_returns_412
    """
    ctx = setup_active_seasonal(client_name="OCC True Co")
    expired = expire_contract_at(ctx["contract"]["id"])
    observed_version = expired["version"]

    tu1 = validate_success(api.create_true_up(
        create_true_up_payload(ctx["contract"]["id"], observed_version),
        DISPATCH), 201)
    assert tu1["status"] == "DRAFT"
    assert tu1["balance_due_cents"] == 0, "no pushes all season -> nothing due"

    validate_error(api.create_true_up(
        create_true_up_payload(ctx["contract"]["id"], observed_version),
        DISPATCH), ApiErrorId.ERR_STALE_CONTRACT_VERSION)

    tu1_after = validate_success(api.get_true_up(tu1["id"], DISPATCH), 200)
    assert tu1_after["status"] == "DRAFT", (
        "the existing DRAFT true-up is not superseded by the rejected request")


# ---------------------------------------------------------------------------
# Corner: terminal lockdown
# ---------------------------------------------------------------------------

def test_terminal_lockdown_paid_invoice_and_rejected_photo(api):
    """PRD §3.6: "accepting moves `UPLOADED` to `ACCEPTED`, rejecting moves it to `REJECTED`, both record `reviewed_by_user_id`, and both outcomes are terminal."
    PRD §2.8: "a resource already in a terminal state rejects every transition with `ERR_ALREADY_TERMINAL`"
    PRD §3.7: "Voiding an `ISSUED`, `PARTIALLY_PAID`, or `PARTIALLY_CREDITED` invoice — three sibling branches with identical guards" — a PAID invoice has no void transition, so the tier-5 state rule owns the rejection.

    Design: Corner/state_machines/terminal_lockdown_paid_invoice_and_rejected_photo
    """
    ctx = setup_active_per_push(client_name="Terminal Co", trigger_depth_inches=1.0)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    setup_billable_visit(ctx, event, _OBS)
    invoice = setup_issued_event_invoice(ctx, event)
    paid = validate_success(
        api.pay_invoice(invoice["id"], {"amount_cents": 45_000}, DISPATCH), 200)
    assert paid["status"] == "PAID"

    # A PAID invoice has no further transitions; the tier-5 state rule rejects
    # the void before any fiscal guard runs.
    error_id = validate_error_is_one_of(
        api.void_invoice(invoice["id"], DISPATCH),
        [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE])
    assert error_id != ApiErrorId.ERR_INVOICE_HAS_PAYMENTS

    # Photo half: REJECTED is explicitly terminal.
    ctx2 = setup_active_per_push(client_name="Terminal Co Photos",
                                 require_photo_verification=False)
    set_clock("2026-12-10T07:00:00Z")
    event2 = setup_storm_event(window_start="2026-12-12T00:00:00Z",
                               window_end="2026-12-12T06:00:00Z")
    visit2 = schedule_visit(event2["id"], ctx2["contract_site"]["id"],
                            scheduled_start="2026-12-12T09:00:00Z",
                            scheduled_end="2026-12-12T10:00:00Z")
    set_clock("2026-12-12T09:05:00Z")
    get_success_data(api.start_visit(visit2["id"], CREW))
    photo = upload_photo(visit2["id"], "BEFORE", "s3://proof/before.jpg")
    rejected = validate_success(api.reject_photo(photo["id"], DISPATCH), 200)
    assert rejected["review_status"] == "REJECTED"

    validate_error(api.accept_photo(photo["id"], DISPATCH),
                   ApiErrorId.ERR_ALREADY_TERMINAL)
