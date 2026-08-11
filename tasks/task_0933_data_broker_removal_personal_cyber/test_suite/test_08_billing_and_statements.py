"""Billing cycles, plan changes, the entitlement statement and the logical
clock."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_billing_cycle, assert_cycle_money_arithmetic, assert_statement_arithmetic,
    assert_same_instant, breakdown_member_id, fixtures as fx,
)


def test_closing_a_cycle_freezes_it_and_mints_a_freshly_granted_successor(api):
    """PRD §3.9: "Closing stamps `closed_at`, freezes `pre_discount_total_cents`,
    `loyalty_discount_cents` and `total_charged_cents`, and moves the cycle
    `OPEN → CLOSED`, which is terminal."
    PRD §3.9: "**When and only when the owning account's status is `ACTIVE`**, closing also
    mints the successor: a new cycle with `cycle_seq` one higher, `starts_at` at the current
    instant, `ends_at` 30 days later, `status` `OPEN`, and `base_charge_cents` taken from
    the account's current plan's `monthly_fee_cents`; and — caused by minting that successor
    — three fresh `GRANT` ledger entries, one per resource type, are appended against the
    new cycle with amounts taken from that plan's three quotas and `reason_code`
    `CYCLE_GRANT`."
    PRD §2.10: "Entries booked to closed cycles never contribute and there is no carry-over."

    Design: Corner/state_machines/billing_cycle_close_mints_successor_with_fresh_grants
    """
    household = fx.open_household()
    fx.setup_active_profile(household)
    first = fx.first_cycle(household)
    fx.set_clock("2026-05-31T00:00:00Z")

    data = validate_success(api.close_billing_cycle(first["id"], fx.ADMIN))

    assert_billing_cycle(data)
    assert data["status"] == "CLOSED"
    assert_same_instant(data["closed_at"], "2026-05-31T00:00:00Z", "closed_at")
    # 2200 base with no prorations; 2200 >= 1500 selects the 2 per cent tier;
    # round_half_up(2200 * 0.02) = 44; 2200 - 44 = 2156.
    assert data["pre_discount_total_cents"] == 2200
    assert data["loyalty_discount_cents"] == 44
    assert data["total_charged_cents"] == 2156
    assert_cycle_money_arithmetic(data)

    cycles, meta = validate_paginated(api.list_billing_cycles(household["account_id"],
                                                              fx.ADMIN))
    assert meta["total_count"] == 2
    successor = cycles[1]
    assert successor["cycle_seq"] == 2
    assert successor["status"] == "OPEN"
    assert_same_instant(successor["starts_at"], "2026-05-31T00:00:00Z", "starts_at")
    # 2026-05-31 + 30 days = 2026-06-30.
    assert_same_instant(successor["ends_at"], "2026-06-30T00:00:00Z", "ends_at")
    assert successor["base_charge_cents"] == 2200

    statement = fx.entitlement_statement(household)
    assert statement["cycle_seq"] == 2
    assert statement["profile_granted"] == 4
    assert statement["profile_consumed"] == 0, "cycle-1 consumption does not carry over"
    assert statement["profile_remaining"] == 4

    _, grant_meta = fx.ledger_entries(household["account_id"], entry_type="GRANT")
    assert grant_meta["total_count"] == 6, "three grants per cycle"


def test_the_member_breakdown_ranks_by_draw_then_by_creation_order(api):
    """PRD §3.9: "That array is eligible over the account's members whose status is
    `INVITED` or `ACTIVE`, ranked by `removal_units_consumed_this_cycle` descending with
    ties broken by the member's `created_at` ascending, and falls back to an empty array
    when no member qualifies, which is never an error."

    Design: Corner/calculations/entitlement_statement_member_breakdown_ordering_and_tiebreak
    """
    household = fx.open_household()
    first_kid = fx.invite_member(household, email="kid1@example.com",
                                 full_name="Robin Kid", role_in_family="MINOR")
    second_kid = fx.invite_member(household, email="kid2@example.com",
                                  full_name="Sam Kid", role_in_family="MINOR")
    brokers = [fx.create_broker(name=name, opt_out_method="WEB_FORM",
                                jurisdiction="OTHER", response_window_days=30)
               for name in ("BrokerOne", "BrokerTwo")]
    profile = fx.setup_active_profile(household)
    scan = fx.queue_scan(profile["id"], kind="INITIAL")
    fx.start_scan(scan["id"])
    exposures = [fx.record_finding(scan["id"], broker["id"]) for broker in brokers]
    for exposure in exposures:
        fx.draft_removal(exposure["id"])

    data = validate_success(api.get_entitlement_statement(household["account_id"],
                                                          household["owner"]))

    assert data["cycle_seq"] == 1
    assert (data["profile_granted"], data["profile_consumed"],
            data["profile_remaining"]) == (4, 1, 3)
    assert (data["scan_granted"], data["scan_consumed"], data["scan_remaining"]) == (12, 1, 11)
    assert (data["removal_granted"], data["removal_consumed"],
            data["removal_released"], data["removal_remaining"]) == (60, 2, 0, 58)
    assert_statement_arithmetic(data)

    breakdown = data["member_breakdown"]
    assert len(breakdown) == 3
    ordered = [breakdown_member_id(entry) for entry in breakdown]
    # The owner drew 2 units and ranks first; the two zero-draw invitees tie and
    # are ordered by created_at ascending, which is their invitation order.
    assert ordered == [household["owner_id"], first_kid["id"], second_kid["id"]]


def test_the_logical_clock_starts_at_the_declared_instant(api):
    """PRD §2.4: "The clock's startup value is exactly `2026-05-01T00:00:00Z`; until an
    administrator moves it, every timestamp the server stamps derives from that value."
    PRD §2.4: "A `PlatformAdmin`-only test-driving capability sets the clock to a supplied
    `to_iso8601` instant and answers with the new `current_utc` alongside the
    `previous_utc` it replaced."

    Design: Corner/endpoints/logical_clock_defaults_to_the_declared_startup_instant
    """
    household = fx.open_household()

    data = validate_success(api.set_clock("2026-06-10T12:30:00Z", fx.ADMIN))

    assert_same_instant(data["previous_utc"], "2026-05-01T00:00:00Z", "previous_utc")
    assert_same_instant(data["current_utc"], "2026-06-10T12:30:00Z", "current_utc")

    account = fx.read_account(household)
    assert_same_instant(account["created_at"], "2026-05-01T00:00:00Z", "created_at")
    cycle = fx.first_cycle(household)
    assert_same_instant(cycle["starts_at"], "2026-05-01T00:00:00Z", "starts_at")
    assert_same_instant(cycle["ends_at"], "2026-05-31T00:00:00Z", "ends_at")


def test_the_statement_and_the_account_row_never_disagree(api):
    """PRD §3.9: "The **entitlement statement** for an account emits, against the account's
    single open cycle, the `account_id`, the `cycle_id` and `cycle_seq`, and then granted,
    consumed, released and remaining for each pool — `profile_granted`, `profile_consumed`,
    `profile_released`, `profile_remaining`, `scan_granted`, `scan_consumed`,
    `scan_released`, `scan_remaining`, `removal_granted`, `removal_consumed`,
    `removal_released` and `removal_remaining` — followed by a `member_breakdown` array."

    Design: Corner/endpoints/entitlement_statement_agrees_with_the_account_row
    """
    household = fx.open_household()
    profile = fx.setup_active_profile(household)
    scan = fx.queue_scan(profile["id"], kind="INITIAL")
    validate_success(api.cancel_scan(scan["id"], fx.AGENT))

    statement = validate_success(api.get_entitlement_statement(household["account_id"],
                                                               fx.AUDITOR))
    account = validate_success(api.get_account(household["account_id"], fx.ADMIN))

    # 12 granted, 1 consumed by the queue, 1 released by the cancellation.
    assert (statement["scan_granted"], statement["scan_consumed"],
            statement["scan_released"], statement["scan_remaining"]) == (12, 1, 1, 12)
    assert (account["scan_units_granted"], account["scan_units_consumed"],
            account["scan_units_released"], account["scan_units_remaining"]) == (12, 1, 1, 12)
    assert statement["profile_consumed"] == account["profile_units_consumed"] == 1
    assert statement["profile_remaining"] == account["profile_units_remaining"] == 3
    assert (statement["removal_granted"], statement["removal_consumed"],
            statement["removal_remaining"]) == (60, 0, 60)
    assert_statement_arithmetic(statement)

    assert statement["account_id"] == household["account_id"]
    assert statement["cycle_id"] == fx.open_cycle(household)["id"]

    scan_row = validate_success(api.get_scan_run(scan["id"], fx.ADMIN))
    assert scan_row["status"] == "CANCELLED"
    assert scan_row["entitlement_units_held"] == 0


def test_a_downgrade_below_the_occupied_roster_is_refused(api):
    """PRD §3.9: "Before any money moves, the downgrade guard runs: the target plan's
    `max_members` must be at least the account's occupied seat count — the number of members
    in `INVITED` or `ACTIVE` — **and** its `profile_quota_per_cycle` must be at least the
    account's `profile_units_consumed`, or the change is refused with
    `ERR_PLAN_DOWNGRADE_BELOW_USAGE`."
    PRD §3.9: "Note that this boundary is **inclusive** (the new ceiling may exactly equal
    current usage), whereas the invitation boundary of §3.1 is **strict**; the two
    comparisons deliberately differ."

    Design: Corner/validations/plan_downgrade_below_member_usage_is_rejected
    """
    family = fx.create_family_plan()
    solo = fx.create_solo_plan()
    household = fx.open_household(plan=family)
    kid = fx.invite_member(household, email="kid@example.com", full_name="Robin Kid",
                           role_in_family="MINOR")
    version = fx.account_version(household)

    response = api.change_plan(household["account_id"],
                               {"new_plan_id": solo["id"], "change_kind": "DOWNGRADE",
                                "expected_account_version": version},
                               household["owner"])

    validate_error(response, ApiErrorId.ERR_PLAN_DOWNGRADE_BELOW_USAGE.value, 409)
    account = fx.read_account(household)
    assert account["plan_id"] == family["id"]
    assert account["version"] == version
    assert fx.first_cycle(household)["proration_credit_cents"] == 0

    # Removing the invitee drops the roster to one seat, which SOLO's ceiling of 1
    # admits on the inclusive boundary.
    validate_success(api.remove_member(kid["id"], household["owner"]))
    validate_success(api.change_plan(
        household["account_id"],
        {"new_plan_id": solo["id"], "change_kind": "DOWNGRADE",
         "expected_account_version": fx.account_version(household)},
        household["owner"]))


def test_a_plan_change_with_no_open_cycle_reports_cycle_closed(api):
    """PRD §2.6: "24. The account has a billing cycle in `OPEN` to book money into,
    otherwise `ERR_CYCLE_CLOSED` (409). Applies to plan changes and add-on purchase."
    PRD §3.9: "An account closed while `SUSPENDED` gets no successor, which is exactly the
    situation rung 24 exists to report."

    Design: Corner/validations/plan_change_with_no_open_cycle_returns_cycle_closed
    """
    family = fx.create_family_plan()
    plus = fx.create_family_plus_plan()
    household = fx.open_household(plan=family)
    cycle = fx.first_cycle(household)

    validate_success(api.suspend_account(household["account_id"], fx.ADMIN))
    validate_success(api.close_billing_cycle(cycle["id"], fx.ADMIN))
    resumed = validate_success(api.resume_account(household["account_id"], fx.ADMIN))
    assert resumed["status"] == "ACTIVE"

    cycles, meta = validate_paginated(api.list_billing_cycles(household["account_id"],
                                                              fx.ADMIN))
    assert meta["total_count"] == 1, "no successor is minted for a suspended account"
    assert cycles[0]["status"] == "CLOSED"

    response = api.change_plan(household["account_id"],
                               {"new_plan_id": plus["id"], "change_kind": "UPGRADE",
                                "expected_account_version": resumed["version"]},
                               fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_CYCLE_CLOSED.value, 409)
    assert fx.read_account(household)["plan_id"] == family["id"]
