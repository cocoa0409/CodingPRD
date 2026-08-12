"""Queuing, running and retrying scans; the broker catalogue's input rules;
and the exposure inventory those scans write."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_broker, assert_exposure_record, assert_same_instant, fixtures as fx,
)


def test_the_third_retry_on_one_scan_is_refused_at_the_cap(api):
    """PRD §3.4: "The loop is capped: retries are admitted only while `retry_count` is
    strictly below 2, so a scan may be retried twice and the third attempt is rejected with
    `ERR_SCAN_RETRY_CAP_REACHED`; at most three running attempts therefore exist per scan."

    Design: Corner/state_machines/scan_retry_cap_reached_on_third_attempt
    """
    household = fx.open_household()
    profile = fx.setup_active_profile(household)
    scan = fx.queue_scan(profile["id"], kind="INITIAL")
    for attempt in range(1, 4):
        fx.start_scan(scan["id"])
        validate_success(api.fail_scan(scan["id"], f"timeout {attempt}", fx.AGENT))
        if attempt < 3:
            validate_success(api.retry_scan(scan["id"], fx.AGENT))

    response = api.retry_scan(scan["id"], fx.AGENT)

    validate_error(response, ApiErrorId.ERR_SCAN_RETRY_CAP_REACHED.value, 409)
    row = validate_success(api.get_scan_run(scan["id"], fx.ADMIN))
    assert row["retry_count"] == 2
    assert row["status"] == "FAILED"
    assert fx.read_account(household)["scan_units_consumed"] == 1, \
        "retries never draw a second scan unit"

    validate_success(api.cancel_scan(scan["id"], fx.AGENT))
    rows, meta = fx.ledger_entries(household["account_id"],
                                   resource_type="SCAN", entry_type="RELEASE")
    assert meta["total_count"] == 1
    assert rows[0]["reason_code"] == "SCAN_ABANDONED"
    assert fx.read_account(household)["scan_units_remaining"] == 12


def test_a_recurring_scan_is_admitted_at_exactly_seven_elapsed_days(api):
    """PRD §3.4: "A `RECURRING` scan is eligible when `last_completed_scan_at` is null, or
    when the whole number of days obtained by dividing the elapsed seconds since
    `last_completed_scan_at` by 86400 and taking the floor is **at least** 7."
    PRD §3.4: "That boundary is inclusive: a recurring scan is permitted at exactly 7 whole
    elapsed days and rejected at 6, with `ERR_RESCAN_TOO_SOON`."

    Design: Corner/calculations/rescan_interval_inclusive_boundary_at_seven_days
    """
    household = fx.open_household()
    profile = fx.setup_active_profile(household)
    fx.run_scan(profile["id"], [], kind="INITIAL", complete=True)

    # 2026-05-01 to 2026-05-07 is 6 whole days.
    fx.set_clock("2026-05-07T00:00:00Z")
    response = api.create_scan_run({"profile_id": profile["id"], "kind": "RECURRING"},
                                   fx.AGENT)
    validate_error(response, ApiErrorId.ERR_RESCAN_TOO_SOON.value, 409)
    assert fx.read_account(household)["scan_units_consumed"] == 1, \
        "a rejected create draws nothing"

    # 2026-05-01 to 2026-05-08 is exactly 7 whole days.
    fx.set_clock("2026-05-08T00:00:00Z")
    data = validate_success(api.create_scan_run(
        {"profile_id": profile["id"], "kind": "RECURRING"}, fx.AGENT), 201)
    assert data["status"] == "QUEUED"
    assert data["kind"] == "RECURRING"
    account = fx.read_account(household)
    assert account["scan_units_consumed"] == 2
    assert account["scan_units_remaining"] == 10


def test_a_second_initial_scan_after_completion_is_refused(api):
    """PRD §3.4: "An `INITIAL` scan is eligible only while the profile's
    `last_completed_scan_at` is still null; once a scan has completed, a second initial
    scan is rejected with `ERR_INITIAL_SCAN_ALREADY_DONE`."
    PRD §3.4: "Completing a running scan stamps `completed_at` and, crucially, writes the
    profile's `last_completed_scan_at` with the current instant — that single write is what
    the seven-day recurring interval is measured from."

    Design: Corner/validations/second_initial_scan_after_completion_is_rejected
    """
    household = fx.open_household()
    profile = fx.setup_active_profile(household)
    fx.run_scan(profile["id"], [], kind="INITIAL", complete=True)
    fx.set_clock("2026-06-01T00:00:00Z")

    response = api.create_scan_run({"profile_id": profile["id"], "kind": "INITIAL"},
                                   fx.AGENT)

    validate_error(response, ApiErrorId.ERR_INITIAL_SCAN_ALREADY_DONE.value, 409)
    validate_success(api.create_scan_run(
        {"profile_id": profile["id"], "kind": "RECURRING"}, fx.AGENT), 201)
    assert_same_instant(fx.read_profile(profile["id"])["last_completed_scan_at"],
                        "2026-05-01T00:00:00Z", "last_completed_scan_at")


def test_an_auditor_may_read_scans_but_not_queue_one(api):
    """PRD §2.1: "`Auditor` is a read-only compliance reviewer holding no mutating
    capability anywhere in the API."
    PRD §2.6: "3. The endpoint's authorized-roles list contains the supplied `X-User-Role`
    — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

    Design: Corner/validations/auditor_cannot_create_a_scan_run
    """
    household = fx.open_household()
    profile = fx.setup_active_profile(household)

    response = api.create_scan_run({"profile_id": profile["id"], "kind": "INITIAL"},
                                   fx.AUDITOR)

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    _, meta = validate_paginated(api.list_scan_runs(fx.AUDITOR,
                                                    params={"profile_id": profile["id"]}))
    assert meta["total_count"] == 0, "reads are permitted, writes are not"


def test_a_resighting_of_a_found_exposure_only_moves_last_seen_at(api):
    """PRD §3.4: "With a candidate in `FOUND` or `REAPPEARED`, the classification is
    `RESIGHTING`."
    PRD §3.4: "`RESIGHTING` refreshes `last_seen_at` on the existing `FOUND` or
    `REAPPEARED` row and changes nothing else."

    Design: Corner/calculations/resighting_of_a_found_exposure_creates_no_new_row
    """
    world = fx.setup_household_with_exposure(
        broker_overrides={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                          "jurisdiction": "OTHER", "response_window_days": 30})
    household, broker, profile = world["household"], world["broker"], world["profile"]
    exposure_id, first_scan = world["exposure"]["id"], world["scan"]

    fx.set_clock("2026-05-20T00:00:00Z")
    rescan = fx.queue_scan(profile["id"], kind="RECURRING")
    fx.start_scan(rescan["id"])

    data = validate_success(api.record_finding(
        rescan["id"],
        {"broker_id": broker["id"], "exposure_kind": "PEOPLE_SEARCH",
         "source_url": "https://quicklookup.example/dana"},
        fx.AGENT))

    assert_exposure_record(data)
    assert data["id"] == exposure_id
    assert data["status"] == "FOUND"
    assert data["reappearance_count"] == 0
    assert data["suppression_count"] == 0
    assert data["fee_exempt"] is False
    assert_same_instant(data["first_found_at"], "2026-05-01T00:00:00Z", "first_found_at")
    assert_same_instant(data["last_seen_at"], "2026-05-20T00:00:00Z", "last_seen_at")
    assert data["discovered_by_scan_id"] == first_scan["id"]

    _, meta = validate_paginated(api.list_exposures(
        household["owner"], params={"profile_id": profile["id"],
                                    "broker_id": broker["id"]}))
    assert meta["total_count"] == 1

    scan_row = validate_success(api.get_scan_run(rescan["id"], fx.ADMIN))
    assert scan_row["findings_count"] == 1
    assert scan_row["new_exposure_count"] == 0
    assert scan_row["reappearance_hit_count"] == 0


def test_the_exposure_listing_composes_its_filters(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered by
    `created_at` ascending."
    PRD §3.5: "Hop 2, caused by hop 1, transitions the linked exposure `FOUND → SUPPRESSED`
    or `REAPPEARED → RE_SUPPRESSED`, incrementing its `suppression_count` by 1 and stamping
    `last_suppressed_at` at the current instant."

    Design: Corner/endpoints/exposure_list_filters_by_status_and_broker
    """
    world = fx.setup_household_with_two_exposures(
        broker_a={"name": "BrokerOne", "opt_out_method": "WEB_FORM",
                  "jurisdiction": "OTHER", "response_window_days": 30},
        broker_b={"name": "BrokerTwo", "opt_out_method": "WEB_FORM",
                  "jurisdiction": "OTHER", "response_window_days": 30})
    owner = world["household"]["owner"]
    profile_id = world["profile"]["id"]
    exposure_a, exposure_b = world["exposure_a"]["id"], world["exposure_b"]["id"]
    fx.suppress_exposure(exposure_a, broker_reference="B1-1")

    rows, meta = validate_paginated(api.list_exposures(owner,
                                                       params={"profile_id": profile_id}))
    assert meta["total_count"] == 2
    assert rows[0]["id"] == exposure_a, "ordering is created_at ascending"

    found, found_meta = validate_paginated(api.list_exposures(
        owner, params={"profile_id": profile_id, "status": "FOUND"}))
    assert found_meta["total_count"] == 1
    assert found[0]["id"] == exposure_b

    suppressed, suppressed_meta = validate_paginated(api.list_exposures(
        owner, params={"profile_id": profile_id, "status": "SUPPRESSED"}))
    assert suppressed_meta["total_count"] == 1
    assert suppressed[0]["id"] == exposure_a

    by_broker, broker_meta = validate_paginated(api.list_exposures(
        owner, params={"profile_id": profile_id, "broker_id": world["broker_a"]["id"]}))
    assert broker_meta["total_count"] == 1
    assert by_broker[0]["id"] == exposure_a

    _, scan_meta = validate_paginated(api.list_exposures(
        owner, params={"discovered_by_scan_id": world["scan"]["id"]}))
    assert scan_meta["total_count"] == 2


def test_an_unknown_opt_out_method_routes_to_the_enum_error(api):
    """PRD §2.6: "8. Every supplied enum-typed field carries a declared member of that enum
    — otherwise `ERR_INVALID_ENUM` (422). This rung applies to an exhaustive, closed list of
    fields and to no others: a plan's `tier`; a member's `role_in_family`; a broker's
    `opt_out_method` and `jurisdiction`; an identity document's `document_type`; a scan's
    `kind`; an exposure's `exposure_kind`; a credential finding's `finding_type`; an
    identifier's `identifier_type`; an add-on's `addon_type`; each element of a breach
    event's `record_types`; the plan-change `change_kind` field; the legal-hold `hold_state`
    field; the member-authorization `action` field; the compliance-report `scope` field; and
    every `status`, `severity`, `resource_type` or `entry_type` value supplied as a list
    filter."

    Design: Corner/entities/broker_invalid_enum_opt_out_method_is_rejected
    """
    response = api.create_broker(
        {"name": "Bad Broker", "opt_out_method": "FAX", "jurisdiction": "US_CA",
         "response_window_days": 30, "requires_identity_verification": False},
        fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value, 422)


def test_a_response_window_above_ninety_days_is_out_of_range(api):
    """PRD §2.6: "9. Numeric fields satisfy their range constraints — otherwise
    `ERR_VALUE_OUT_OF_RANGE` (422)."
    PRD §3.5: "Registering a broker declares its trade `name`, an `opt_out_method` of
    `WEB_FORM`, `EMAIL`, `POSTAL` or `PHONE`, a `jurisdiction` of `US_CA`, `US_VA`, `EU` or
    `OTHER`, a self-declared `response_window_days` of at least 5 and at most 90, and an
    optional `requires_identity_verification` flag defaulting to false."

    Design: Corner/entities/broker_response_window_out_of_range_returns_value_out_of_range
    """
    response = api.create_broker(
        {"name": "Slow Broker", "opt_out_method": "EMAIL", "jurisdiction": "EU",
         "response_window_days": 91, "requires_identity_verification": False},
        fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value, 422)

    # 90 is the inclusive ceiling.
    data = validate_success(api.create_broker(
        {"name": "Slow Broker", "opt_out_method": "EMAIL", "jurisdiction": "EU",
         "response_window_days": 90, "requires_identity_verification": False},
        fx.ADMIN), 201)
    assert_broker(data)
    assert data["response_window_days"] == 90


def test_the_scan_pool_closes_at_zero_and_reopens_on_a_cancellation(api):
    """PRD §2.6: "44. The account's `scan_units_remaining` is at least 1, otherwise
    `ERR_SCAN_QUOTA_EXCEEDED` (409). Applies to scan queuing."
    PRD §3.4: "The two cancellation edges, `QUEUED → CANCELLED` and `FAILED → CANCELLED`,
    both set `entitlement_units_held` to 0, append a `SCAN` `RELEASE` entry of `amount` 1,
    and raise `scan_units_released` and `scan_units_remaining` by one — but they differ in
    one field: `QUEUED → CANCELLED` carries `reason_code` `SCAN_CANCELLED`, while
    `FAILED → CANCELLED` carries `reason_code` `SCAN_ABANDONED`."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_scan_quota_boundary_at_the_last_unit
    """
    household = fx.open_household(tier="SOLO", name="Solo Two Scans",
                                  monthly_fee_cents=900, max_members=1,
                                  profile_quota_per_cycle=1, scan_quota_per_cycle=2,
                                  removal_quota_per_cycle=5,
                                  per_member_removal_subcap=5)
    profile = fx.setup_active_profile(household)
    first = fx.queue_scan(profile["id"], kind="INITIAL")

    # The second scan is admitted while remaining is exactly 1, leaving 0.
    validate_success(api.create_scan_run(
        {"profile_id": profile["id"], "kind": "RECURRING"}, fx.AGENT), 201)
    assert fx.read_account(household)["scan_units_remaining"] == 0

    validate_error(api.create_scan_run(
        {"profile_id": profile["id"], "kind": "RECURRING"}, fx.AGENT),
        ApiErrorId.ERR_SCAN_QUOTA_EXCEEDED.value, 409)

    validate_success(api.cancel_scan(first["id"], fx.AGENT))
    freed = fx.read_account(household)
    assert freed["scan_units_released"] == 1
    assert freed["scan_units_remaining"] == 1

    third = validate_success(api.create_scan_run(
        {"profile_id": profile["id"], "kind": "RECURRING"}, fx.AGENT), 201)
    assert third["status"] == "QUEUED"
    final = fx.read_account(household)
    assert final["scan_units_granted"] == 2
    assert final["scan_units_consumed"] == 3
    assert final["scan_units_remaining"] == 0
