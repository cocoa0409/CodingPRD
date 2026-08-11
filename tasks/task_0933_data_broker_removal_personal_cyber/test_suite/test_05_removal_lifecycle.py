"""Drafting, submitting, completing, rejecting and expiring opt-out removal
requests, and the entitlement draw behind them."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_removal_request, assert_same_instant, fixtures as fx,
)


def _acknowledged_request_world():
    world = fx.setup_household_with_exposure(
        broker_overrides={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                          "jurisdiction": "OTHER", "response_window_days": 30})
    world["request"] = fx.acknowledged_removal(world["exposure"]["id"],
                                               broker_reference="QL-9")
    return world


def test_the_submitting_agent_may_not_record_the_completion(api):
    """PRD §3.5: "Completion moves `ACKNOWLEDGED → COMPLETED` and is the system's
    segregation-of-duties point: the calling `X-User-ID` must **differ** from the
    `submitted_by_agent_id` recorded at submission, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.5: "Hop 3, caused by hop 2, re-derives that exposure's profile counters
    `open_exposure_count` (down by one) and `suppressed_exposure_count` (up by one)."

    Design: Corner/state_machines/removal_complete_by_the_submitting_agent_is_rejected
    """
    world = _acknowledged_request_world()
    request_id = world["request"]["id"]

    response = api.complete_removal_request(request_id, fx.AGENT)

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert fx.read_removal(request_id)["status"] == "ACKNOWLEDGED"
    assert fx.read_exposure(world["exposure"]["id"])["status"] == "FOUND", \
        "the refused completion fires no side effect"

    data = validate_success(api.complete_removal_request(request_id, fx.AGENT_BETA))
    assert data["status"] == "COMPLETED"
    assert data["completed_by_agent_id"] == fx.AGENT_BETA_ID

    exposure = fx.read_exposure(world["exposure"]["id"])
    assert exposure["status"] == "SUPPRESSED"
    assert exposure["suppression_count"] == 1
    profile = fx.read_profile(world["profile"]["id"])
    assert profile["open_exposure_count"] == 0
    assert profile["suppressed_exposure_count"] == 1


def test_expiry_is_refused_before_the_deadline_and_admitted_at_it(api):
    """PRD §3.5: "Eligibility is a single inclusive comparison — the current instant must be
    at or after the request's `sla_deadline_at`. At the exact deadline instant expiry is
    permitted; one millisecond earlier it is rejected with `ERR_SLA_NOT_ELAPSED`."
    PRD §3.5: "Expiry is available to a `PrivacyAgent` or `PlatformAdmin` from either
    `SUBMITTED → EXPIRED` or `ACKNOWLEDGED → EXPIRED`, with identical side effects from
    both origins: `closed_at` is stamped and the broker re-derives `expired_request_count`
    and its compliance score."

    Design: Corner/calculations/sla_expiry_inclusive_boundary_at_the_deadline_instant
    """
    world = fx.setup_household_with_exposure(
        broker_overrides={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                          "jurisdiction": "OTHER", "response_window_days": 30})
    request = fx.draft_removal(world["exposure"]["id"])
    submitted = fx.submit_removal(request["id"])
    # 30 declared window + 0 WEB_FORM buffer = 30; max(30, 21 OTHER floor) = 30.
    assert submitted["effective_window_days"] == 30
    # 2026-05-01 + 30 whole days = 2026-05-31.
    assert_same_instant(submitted["sla_deadline_at"], "2026-05-31T00:00:00Z",
                        "sla_deadline_at")

    fx.set_clock("2026-05-30T23:59:59Z")
    validate_error(api.expire_removal_request(request["id"], fx.AGENT),
                   ApiErrorId.ERR_SLA_NOT_ELAPSED.value, 409)
    assert fx.read_removal(request["id"])["status"] == "SUBMITTED"

    fx.set_clock("2026-05-31T00:00:00Z")
    data = validate_success(api.expire_removal_request(request["id"], fx.AGENT))
    assert data["status"] == "EXPIRED"
    assert_same_instant(data["closed_at"], "2026-05-31T00:00:00Z", "closed_at")

    report = validate_success(api.get_compliance_report(
        world["broker"]["id"], fx.AGENT, params={"scope": "LIFETIME"}))
    assert report["expired_request_count"] == 1
    # 100 - 12 * 1 = 88.
    assert report["compliance_score"] == 88


def test_completing_at_the_exact_deadline_counts_as_on_time(api):
    """PRD §3.5: "A request's `on_time` is derived and tri-valued: it is null in every
    status other than `COMPLETED`; it is true when the status is `COMPLETED` and
    `closed_at` is at or before `sla_deadline_at`; and it is false when the status is
    `COMPLETED` and `closed_at` is strictly after `sla_deadline_at`. The boundary is
    inclusive — completing at exactly the deadline instant counts as on time."
    PRD §3.9: "The score starts from a base of 100, subtracts 8 points per reappearance,
    subtracts 12 points per expired request, subtracts 5 points per rejected request, adds
    3 points per on-time completion, and is then clamped into the inclusive range 0 to 100
    — the floor is 0 and the ceiling is 100."

    Design: Corner/calculations/removal_on_time_true_when_completed_at_the_exact_deadline
    """
    world = fx.setup_household_with_exposure(
        broker_overrides={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                          "jurisdiction": "OTHER", "response_window_days": 30})
    request = fx.acknowledged_removal(world["exposure"]["id"], broker_reference="QL-7")
    fx.set_clock("2026-05-31T00:00:00Z")

    data = validate_success(api.complete_removal_request(request["id"], fx.AGENT_BETA))

    assert_removal_request(data)
    assert data["status"] == "COMPLETED"
    assert_same_instant(data["closed_at"], "2026-05-31T00:00:00Z", "closed_at")
    assert_same_instant(data["sla_deadline_at"], "2026-05-31T00:00:00Z", "sla_deadline_at")
    assert data["on_time"] is True

    report = validate_success(api.get_compliance_report(
        world["broker"]["id"], fx.AGENT, params={"scope": "LIFETIME"}))
    assert report["on_time_completion_count"] == 1
    # 100 + 3 = 103, clamped down to the ceiling of 100.
    assert report["compliance_score"] == 100

    exposure = fx.read_exposure(world["exposure"]["id"])
    assert exposure["status"] == "SUPPRESSED"
    assert exposure["suppression_count"] == 1


def test_the_member_subcap_is_only_reached_once_the_pool_check_passes(api):
    """PRD §3.5: "Step three: otherwise, if the member's remaining sub-cap — the plan's
    `per_member_removal_subcap` minus that member's net consumption this cycle — is below
    1, the draft fails with `ERR_MEMBER_SUBCAP_EXCEEDED`."
    PRD §3.5: "The shared pool is checked strictly before the personal sub-cap, so a draft
    that would breach both reports the pool error."

    Design: Corner/calculations/member_subcap_is_checked_after_the_shared_pool
    """
    household = fx.open_household(tier="FAMILY", name="Family Capped",
                                  removal_quota_per_cycle=10,
                                  per_member_removal_subcap=2)
    brokers = [fx.create_broker(name=name, opt_out_method="WEB_FORM",
                                jurisdiction="OTHER", response_window_days=30)
               for name in ("BrokerOne", "BrokerTwo", "BrokerThree")]
    profile = fx.setup_active_profile(household)
    _, exposures = fx.run_scan(profile["id"], [b["id"] for b in brokers],
                               kind="INITIAL", complete=True)
    first = fx.draft_removal(exposures[0]["id"])
    fx.draft_removal(exposures[1]["id"])

    response = api.create_removal_request(exposures[2]["id"], fx.AGENT)

    validate_error(response, ApiErrorId.ERR_MEMBER_SUBCAP_EXCEEDED.value, 409)
    account = fx.read_account(household)
    # 10 granted - 2 consumed = 8 remaining, so rung 45 was satisfied and only the
    # per-member rung could have fired.
    assert account["removal_units_remaining"] == 8
    member = validate_success(api.get_member(household["owner_id"], fx.ADMIN))
    assert member["removal_units_consumed_this_cycle"] == 2
    _, meta = validate_paginated(api.list_removal_requests(
        fx.ADMIN, params={"exposure_id": exposures[2]["id"]}))
    assert meta["total_count"] == 0

    # Voiding one draft returns a sub-cap slot and the same call then lands.
    validate_success(api.void_removal_request(first["id"], fx.AGENT))
    validate_success(api.create_removal_request(exposures[2]["id"], fx.AGENT), 201)


def test_a_draft_against_a_reappeared_exposure_draws_no_unit(api):
    """PRD §3.5: "Step one: if the exposure is fee-exempt — that is, if its status is
    `REAPPEARED` — the request draws zero units, no ledger entry is written,
    `entitlement_units_consumed` is set to 0, and the draw stops there; neither quota check
    below is performed at all."
    PRD §3.4: "One derived flag ties the two axes together: an exposure's `fee_exempt` is
    true exactly while its status is `REAPPEARED`, and a removal request drafted against a
    fee-exempt exposure draws no entitlement unit at all."

    Design: Corner/calculations/reappeared_exposure_makes_the_next_request_fee_exempt
    """
    world = fx.setup_household_with_exposure(
        broker_overrides={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                          "jurisdiction": "OTHER", "response_window_days": 30})
    household, broker, profile = world["household"], world["broker"], world["profile"]
    exposure_id = world["exposure"]["id"]
    fx.suppress_exposure(exposure_id, broker_reference="QL-11")

    # 44 whole days later the re-finding is a REAPPEARANCE.
    fx.set_clock("2026-06-14T00:00:00Z")
    rescan = fx.queue_scan(profile["id"], kind="RECURRING")
    fx.start_scan(rescan["id"])
    fx.record_finding(rescan["id"], broker["id"])

    before = fx.read_exposure(exposure_id)
    assert before["status"] == "REAPPEARED"
    assert before["fee_exempt"] is True
    account_before = fx.read_account(household)
    assert account_before["removal_units_consumed"] == 1
    assert account_before["removal_units_remaining"] == 59

    data = validate_success(api.create_removal_request(exposure_id, fx.AGENT), 201)

    assert data["entitlement_units_consumed"] == 0
    account_after = fx.read_account(household)
    assert account_after["removal_units_consumed"] == 1
    assert account_after["removal_units_remaining"] == 59
    member = validate_success(api.get_member(household["owner_id"], fx.ADMIN))
    assert member["removal_units_consumed_this_cycle"] == 1

    _, meta = fx.ledger_entries(household["account_id"], resource_type="REMOVAL")
    assert meta["total_count"] == 2, "one grant and one consume — the fee-exempt draft wrote nothing"

    scan_row = validate_success(api.get_scan_run(rescan["id"], fx.ADMIN))
    assert scan_row["reappearance_hit_count"] == 1
    assert scan_row["new_exposure_count"] == 0


def test_the_two_compliance_scopes_disagree_on_identical_stored_data(api):
    """PRD §3.9: "Under `CURRENT_WINDOW`, a cutoff is taken at the current instant minus 30
    days, inclusive, and the four figures become: the **number of exposure rows** at this
    broker currently sitting in `REAPPEARED` whose `last_seen_at` is at or after the cutoff
    — so the same exposure contributes at most one penalty no matter how many times it has
    looped; the count of `EXPIRED` requests whose `closed_at` is at or after the cutoff; the
    count of `REJECTED` requests whose `closed_at` is at or after the cutoff; and the count
    of `COMPLETED` requests with `on_time` true whose `closed_at` is at or after the cutoff."
    PRD §3.9: "The **broker compliance report** scores one broker out of 100 and accepts an
    optional `scope` of `LIFETIME` or `CURRENT_WINDOW`, defaulting to `LIFETIME`."

    Design: Corner/calculations/broker_compliance_lifetime_versus_current_window_scope
    """
    world = fx.setup_household_with_exposure(
        broker_overrides={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                          "jurisdiction": "OTHER", "response_window_days": 30})
    request = fx.acknowledged_removal(world["exposure"]["id"], broker_reference="QL-5")
    fx.reject_removal(request["id"], "NO_MATCH")
    fx.set_clock("2026-07-01T00:00:00Z")
    broker_id = world["broker"]["id"]

    lifetime = validate_success(api.get_compliance_report(
        broker_id, fx.AGENT, params={"scope": "LIFETIME"}))
    assert lifetime["rejected_request_count"] == 1
    assert lifetime["expired_request_count"] == 0
    assert lifetime["on_time_completion_count"] == 0
    assert lifetime["reappearance_count"] == 0
    # 100 - 5 * 1 = 95.
    assert lifetime["compliance_score"] == 95
    assert lifetime["top_offending_profiles"] == []

    window = validate_success(api.get_compliance_report(
        broker_id, fx.AGENT, params={"scope": "CURRENT_WINDOW"}))
    # The cutoff is 2026-07-01 minus 30 days = 2026-06-01; the rejection closed on
    # 2026-05-01, before it, so it drops out and the score returns to the base.
    assert window["rejected_request_count"] == 0
    assert window["compliance_score"] == 100
    assert window["top_offending_profiles"] == []

    default_scope = validate_success(api.get_compliance_report(broker_id, fx.AGENT))
    assert default_scope["rejected_request_count"] == 1
    assert default_scope["compliance_score"] == 95


def test_the_shared_pool_error_is_reported_while_the_subcap_has_room(api):
    """PRD §3.5: "Step two: otherwise, if the account's `removal_units_remaining` is below
    1, the draft fails with `ERR_REMOVAL_QUOTA_EXCEEDED`."
    PRD §2.6: "45. The account's `removal_units_remaining` is at least 1, otherwise
    `ERR_REMOVAL_QUOTA_EXCEEDED` (409). Applies to removal drafting, and is skipped
    entirely when the target exposure is fee-exempt."

    PRD §2.2 constrains the plan shape itself: "The sub-cap may never exceed the pool it
    draws from." The pool is therefore drained by *two* members rather than by raising the
    sub-cap above the pool, so the drafting member still has sub-cap room when the pool
    rung fires and only that rung can explain the error.

    Design: Corner/validations/second_removal_draft_rejected_by_the_shared_pool
    """
    household = fx.open_household(tier="FAMILY", name="Family Micro",
                                  monthly_fee_cents=900, max_members=2,
                                  profile_quota_per_cycle=2, scan_quota_per_cycle=4,
                                  removal_quota_per_cycle=2,
                                  per_member_removal_subcap=2)
    sibling = fx.invite_and_activate_member(household, email="robin@example.com",
                                            full_name="Robin Kid",
                                            role_in_family="ADULT")
    brokers = [fx.create_broker(name=name, opt_out_method="WEB_FORM",
                                jurisdiction="OTHER", response_window_days=30)
               for name in ("BrokerOne", "BrokerTwo", "BrokerThree")]
    profile = fx.setup_active_profile(household)
    _, exposures = fx.run_scan(profile["id"], [brokers[0]["id"], brokers[1]["id"]],
                               kind="INITIAL", complete=True)
    sibling_profile = fx.setup_active_profile(household, member_id=sibling["id"],
                                              identifier_value="robin@example.com")
    _, sibling_exposures = fx.run_scan(sibling_profile["id"], [brokers[2]["id"]],
                                       kind="INITIAL", complete=True)
    # One unit drawn by each member drains the pool of 2 while each member's
    # personal sub-cap of 2 still has one unit of room.
    fx.draft_removal(exposures[0]["id"])
    fx.draft_removal(sibling_exposures[0]["id"])

    response = api.create_removal_request(exposures[1]["id"], fx.AGENT)

    validate_error(response, ApiErrorId.ERR_REMOVAL_QUOTA_EXCEEDED.value, 409)
    assert fx.read_account(household)["removal_units_remaining"] == 0
    member = validate_success(api.get_member(household["owner_id"], fx.ADMIN))
    # 1 consumed against a sub-cap of 2, so only the pool rung could have fired.
    assert member["removal_units_consumed_this_cycle"] == 1
    _, meta = validate_paginated(api.list_removal_requests(
        fx.ADMIN, params={"exposure_id": exposures[1]["id"]}))
    assert meta["total_count"] == 0


def test_drafting_on_behalf_of_a_revoked_member_is_refused(api):
    """PRD §2.6: "16. The member on whose behalf the operation is performed has
    `authorization_status` `GRANTED`, otherwise `ERR_AUTHORIZATION_REVOKED` (409). Applies
    to exactly four operations: profile drafting, scan queuing, removal drafting and
    removal submission."
    PRD §3.2: "Re-granting authorization moves `REVOKED → GRANTED`, clears
    `authorization_revoked_at` to null, and does **not** resurrect the voided requests —
    new ones must be drafted."

    Design: Corner/validations/revoked_authorization_rejects_a_new_removal_request
    """
    world = fx.setup_household_with_exposure(
        broker_overrides={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                          "jurisdiction": "OTHER", "response_window_days": 30})
    household = world["household"]
    validate_success(api.set_member_authorization(household["owner_id"], "REVOKE",
                                                  household["owner"]))

    response = api.create_removal_request(world["exposure"]["id"], fx.AGENT)

    validate_error(response, ApiErrorId.ERR_AUTHORIZATION_REVOKED.value, 409)
    assert fx.read_account(household)["removal_units_remaining"] == 60

    regranted = validate_success(api.set_member_authorization(
        household["owner_id"], "GRANT", household["owner"]))
    assert regranted["authorization_status"] == "GRANTED"
    assert regranted["authorization_revoked_at"] is None
    validate_success(api.create_removal_request(world["exposure"]["id"], fx.AGENT), 201)
