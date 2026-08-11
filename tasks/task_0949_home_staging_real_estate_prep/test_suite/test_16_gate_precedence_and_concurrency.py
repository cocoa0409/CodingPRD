"""The total order over the ten write gates, and the optimistic-concurrency guards."""

from test_helpers import (
    ADMIN,
    CLERK,
    COORD,
    TIER_SIGNATURE,
    WAREHOUSE,
    ApiErrorId,
    assert_same_instant,
    lease_version,
    new_tier,
    setup_consultation_held_one_room,
    setup_occupied_pay_at_closing_authorized,
    setup_vacant_project_staged,
    setup_vacant_pull_submitted,
    validate_error,
    validate_success,
)

UNKNOWN_TIER = "6b0f9d31-2c44-4a08-9b7e-33a1c4e5d600"


def test_an_unpermitted_role_is_answered_before_the_missing_project(api):
    """PRD §2.7: "Every mutating endpoint in this system evaluates the same **total order of
    ten gates** and returns the error of the *first* gate that objects."
    PRD §2.7: "Rung 4: the acting role appears in the endpoint's permitted-role list as
    published in §4; otherwise `ERR_UNAUTHORIZED`, HTTP 403."

    Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_beats_missing_project_returns_unauthorized
    """
    validate_success(api.set_clock("2026-06-01T00:00:00Z", ADMIN))

    resp = api.authorize_project("9f1e0c2b-4a5d-4e61-8c9b-11e7b6a0f1d2", WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_a_permitted_role_on_the_same_missing_project_gets_the_not_found(api):
    """PRD §2.7: "Rung 5: every identifier in the path resolves to a stored row, validated
    left to right, returning the entity-specific not-found code of the leftmost unresolved
    segment with HTTP 404."
    PRD §2.7: "2. **G2 — Authorization** (rung 4): the acting role appears in the endpoint's
    permitted-role list."

    Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_beats_missing_project_returns_unauthorized
    """
    validate_success(api.set_clock("2026-06-01T00:00:00Z", ADMIN))

    resp = api.authorize_project(
        "9f1e0c2b-4a5d-4e61-8c9b-11e7b6a0f1d2",
        {"X-User-ID": "someone", "X-User-Role": "Seller",
         "Content-Type": "application/json"})

    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND.value, 404)


def test_an_unresolvable_body_tier_is_answered_before_the_scope_check(api):
    """PRD §2.7: "Rung 9: every foreign key supplied in the body resolves to a stored row of
    the declared parent entity, returning that entity's not-found code with HTTP 404."
    PRD §2.7: "3. **G3 — Existence and shape** (rungs 5–9): path resources resolve left to
    right, the body is an object, required fields are present, enums are members, types and
    ranges hold, and body foreign keys resolve."

    Design: Difficulty/priority_pair_validation_conflict/missing_tier_beats_unapproved_scope_returns_tier_not_found
    """
    ctx = setup_consultation_held_one_room()

    resp = api.create_project(
        {"property_id": ctx["prop_id"], "consultation_id": ctx["cons_id"],
         "listing_id": ctx["listing_id"], "package_tier_id": UNKNOWN_TIER,
         "payer_client_id": ctx["seller_id"], "payer_type": "SELLER"}, COORD)

    validate_error(resp, ApiErrorId.ERR_TIER_NOT_FOUND.value, 404)
    consultation = validate_success(api.get_consultation(ctx["cons_id"], COORD))
    assert consultation["state"] == "SCOPE_DRAFTED"


def test_with_the_tier_resolved_the_unapproved_scope_is_what_objects(api):
    """PRD §2.7: "Rung 38: the referenced consultation is in state `SCOPE_APPROVED` before a
    project may be created against it; otherwise `ERR_SCOPE_NOT_APPROVED`, HTTP 409."
    PRD §2.7: "8. **G8 — Safety and authority** (rungs 38–52): scope approval, authorization
    caps, seller consent, vendor lead time and minimum term, lease minimums, extension
    increments and totals, tier-change direction, and photography linkage."

    Design: Difficulty/priority_pair_validation_conflict/missing_tier_beats_unapproved_scope_returns_tier_not_found
    """
    ctx = setup_consultation_held_one_room()
    tier = new_tier(TIER_SIGNATURE)

    resp = api.create_project(
        {"property_id": ctx["prop_id"], "consultation_id": ctx["cons_id"],
         "listing_id": ctx["listing_id"], "package_tier_id": tier["id"],
         "payer_client_id": ctx["seller_id"], "payer_type": "SELLER"}, COORD)

    validate_error(resp, ApiErrorId.ERR_SCOPE_NOT_APPROVED.value, 409)
    consultation = validate_success(api.get_consultation(ctx["cons_id"], COORD))
    assert consultation["state"] == "SCOPE_DRAFTED"


def test_a_stale_lease_version_is_answered_before_the_zero_cycle_request(api):
    """PRD §2.9: "In all three cases the version check happens at gate G7 — after the
    target's own state precondition has been satisfied, and before any authority, capacity or
    fiscal arithmetic runs."
    PRD §2.9: "Requesting a lease extension requires `expected_lease_version` carrying the
    client's last observed `version` of the parent `Lease`. A mismatch is rejected with
    `ERR_STALE_LEASE_VERSION` (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/stale_lease_version_beats_zero_cycle_request_returns_stale_version
    """
    ctx = setup_vacant_project_staged()
    observed = lease_version(ctx["lease_id"])

    resp = api.request_extension(ctx["lease_id"], 0, observed - 1, COORD)

    validate_error(resp, ApiErrorId.ERR_STALE_LEASE_VERSION.value, 412)
    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert lease["billed_cycles"] == 4


def test_with_a_fresh_lease_version_the_zero_cycle_request_is_what_objects(api):
    """PRD §2.7: "Rung 45: the extension's `requested_cycles` is a whole positive multiple of
    the one-cycle extension increment, so fractional requests and zero are both rejected;
    otherwise `ERR_PARTIAL_CYCLE_EXTENSION`, HTTP 422."
    PRD §2.7: "**G7 sits between state preconditions and business authority**: a request that
    is already illegal for the target's current state is rejected before its version is even
    looked at, but a writer holding a stale version is turned away before any cap or capacity
    arithmetic runs."

    Design: Difficulty/priority_pair_validation_conflict/stale_lease_version_beats_zero_cycle_request_returns_stale_version
    """
    ctx = setup_vacant_project_staged()

    resp = api.request_extension(ctx["lease_id"], 0, lease_version(ctx["lease_id"]), COORD)

    validate_error(resp, ApiErrorId.ERR_PARTIAL_CYCLE_EXTENSION.value, 422)
    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert lease["billed_cycles"] == 4


def test_the_expired_service_window_is_answered_before_the_uncollected_deposit(api):
    """PRD §2.7: "Rung 63: the proposed or reported visit instant is on or before the
    project's `service_window_end_date`; otherwise `ERR_SERVICE_WINDOW_EXPIRED`, HTTP 409."
    PRD §2.7: "**G10 is last on purpose**: a caller whose request is both structurally broken
    and fiscally blocked is told about the structural problem first, so that fixing the money
    never surfaces a second, unrelated rejection."

    Design: Difficulty/priority_pair_validation_conflict/expired_service_window_beats_uncollected_deposit_returns_window_expired
    """
    ctx = setup_occupied_pay_at_closing_authorized()

    resp = api.schedule_visit(ctx["proj_id"], "2026-08-01T09:00:00Z", COORD)

    validate_error(resp, ApiErrorId.ERR_SERVICE_WINDOW_EXPIRED.value, 409)
    deposit = validate_success(api.get_deposit(ctx["dep_id"], CLERK))
    assert deposit["state"] == "REQUIRED"
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert_same_instant(project["service_window_end_date"], "2026-07-16T00:00:00Z",
                        "project.service_window_end_date")


def test_inside_the_window_the_uncollected_deposit_is_what_objects(api):
    """PRD §2.7: "Rung 66: the project's deposit is in state `HELD` before execution work may
    begin; otherwise `ERR_DEPOSIT_NOT_HELD`, HTTP 402."
    PRD §2.7: "10. **G10 — Fiscal** (rungs 66–73): deposit held, deposit minimum, exact
    payment, already-paid, deferral expiry, fiscal hold, the MLS delivery payment gate, and
    the refund gate."

    Design: Difficulty/priority_pair_validation_conflict/expired_service_window_beats_uncollected_deposit_returns_window_expired
    """
    ctx = setup_occupied_pay_at_closing_authorized()

    resp = api.schedule_visit(ctx["proj_id"], "2026-06-05T09:00:00Z", COORD)

    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_HELD.value, 402)
    deposit = validate_success(api.get_deposit(ctx["dep_id"], CLERK))
    assert deposit["state"] == "REQUIRED"


def test_a_commit_carrying_a_stale_project_version_is_refused(api):
    """PRD §2.9: "Committing an inventory pull requires `expected_project_version` carrying
    the client's last observed `version` of the pull's parent `Project`. If any writer has
    advanced that project's version since the client read it, the commit is rejected with
    `ERR_STALE_PROJECT_VERSION` (HTTP 412)."
    PRD §3.4: "Committing the pull is permitted from `SUBMITTED` or from `PARTIAL`, requires a
    `fill_rate` of at least 0.70 — exactly 0.7000 commits — and is optimistic-concurrency
    guarded on the parent project as described in §2.9."

    Design: Corner/cross_cutting_complexity_layers/stale_project_version_on_pull_commit_returns_412
    """
    ctx = setup_vacant_pull_submitted()

    resp = api.commit_pull(ctx["pull_id"], ctx["proj_v"] - 1, WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION.value, 412)
    pull = validate_success(api.get_pull(ctx["pull_id"], WAREHOUSE))
    assert pull["state"] == "SUBMITTED"
    assert pull["committed_at"] is None


def test_the_matching_project_version_commits_and_advances_that_version(api):
    """PRD §3.4: "A commit stamps `committed_at` with the logical clock, drops every
    still-`UNFILLED` line to `DROPPED`, and bumps both the pull's and the project's
    `version`."
    PRD §2.4: "`version` is an integer that begins at 1 when the row is created and increments
    by exactly 1 on every mutation of that row."

    Design: Corner/cross_cutting_complexity_layers/correct_project_version_on_pull_commit_succeeds_and_bumps_version
    """
    ctx = setup_vacant_pull_submitted()

    validate_success(api.commit_pull(ctx["pull_id"], ctx["proj_v"], WAREHOUSE))

    pull = validate_success(api.get_pull(ctx["pull_id"], WAREHOUSE))
    assert pull["state"] == "COMMITTED"
    assert float(pull["fill_rate"]) == 1.0
    project = validate_success(api.get_project(ctx["proj_id"], WAREHOUSE))
    assert project["version"] == ctx["proj_v"] + 1
