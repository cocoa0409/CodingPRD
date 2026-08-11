"""Three conserved quantities and the compensating actions that must leave
them exactly where they started: entitlement units, seat-pool capacity and the
number of derived alert rows."""
from test_helpers import (
    validate_success, validate_paginated, assert_same_instant,
    assert_statement_arithmetic, assert_seat_conservation, assert_ledger_entry,
    fixtures as fx,
)


# ==========================================================================
# Conserved quantity 1 — REMOVAL entitlement units
# ==========================================================================

def test_removal_unit_conservation_across_a_draft_and_void_round_trip(api):
    """PRD §2.10: "For each resource type, the account's granted total is the sum of
    `amount` over `GRANT` entries, its consumed total the sum over `CONSUME` entries and
    its released total the sum over `RELEASE` entries, in every case restricted to entries
    booked against the account's single `OPEN` billing cycle. Remaining is granted minus
    consumed plus released."

    Design: Difficulty/compensating_invariant/removal_unit_conservation_across_draft_and_void
    """
    world = fx.setup_household_with_exposure(
        broker_overrides={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                          "jurisdiction": "OTHER", "response_window_days": 30})
    household = world["household"]

    before = fx.entitlement_statement(household)
    assert (before["removal_granted"], before["removal_consumed"],
            before["removal_released"], before["removal_remaining"]) == (60, 0, 0, 60)
    assert_statement_arithmetic(before)

    request = fx.draft_removal(world["exposure"]["id"])
    mid = fx.entitlement_statement(household)
    assert (mid["removal_granted"], mid["removal_consumed"],
            mid["removal_released"], mid["removal_remaining"]) == (60, 1, 0, 59)
    assert_statement_arithmetic(mid)

    validate_success(api.void_removal_request(request["id"], fx.AGENT))
    after = fx.entitlement_statement(household)
    assert (after["removal_granted"], after["removal_consumed"],
            after["removal_released"], after["removal_remaining"]) == (60, 1, 1, 60)
    assert_statement_arithmetic(after)


def test_voiding_a_draft_writes_a_compensating_ledger_pair(api):
    """PRD §2.10: "A derived `signed_amount` is exposed on each entry — it equals `amount`
    for `GRANT` and `RELEASE` entries and the negation of `amount` for `CONSUME` entries."
    PRD §3.1: "A member row exposes `removal_units_consumed_this_cycle`, which is that
    member's net draw on the shared removal pool: the sum of `REMOVAL` `CONSUME` amounts
    carrying their `member_id` in the account's open cycle, minus the sum of the matching
    `RELEASE` amounts."

    Design: Difficulty/compensating_invariant/removal_unit_conservation_across_draft_and_void
    """
    world = fx.setup_household_with_exposure(
        broker_overrides={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                          "jurisdiction": "OTHER", "response_window_days": 30})
    household = world["household"]
    request = fx.draft_removal(world["exposure"]["id"])
    validate_success(api.void_removal_request(request["id"], fx.AGENT))

    rows, meta = fx.ledger_entries(household["account_id"], resource_type="REMOVAL")
    assert meta["total_count"] == 3, "one grant, one consume and one release"
    for row in rows:
        assert_ledger_entry(row)
    by_type = {row["entry_type"]: row for row in rows}
    assert by_type["GRANT"]["signed_amount"] == 60
    assert by_type["CONSUME"]["signed_amount"] == -1
    assert by_type["RELEASE"]["signed_amount"] == 1
    assert by_type["RELEASE"]["reason_code"] == "REMOVAL_VOIDED"
    # The three signed amounts net back to the original grant.
    assert sum(row["signed_amount"] for row in rows) == 60

    member = validate_success(api.get_member(household["owner_id"], fx.ADMIN))
    assert member["removal_units_consumed_this_cycle"] == 0

    row = fx.read_removal(request["id"])
    assert row["entitlement_units_consumed"] == 1
    assert row["entitlement_units_released"] == 1


# ==========================================================================
# Conserved quantity 2 — seat-pool capacity
# ==========================================================================

def test_seat_pool_capacity_is_conserved_across_bind_and_release(api):
    """PRD §2.10: "For every add-on, `seats_bound` is the count of its seats in `BOUND` and
    `seats_available` is `seats_total` minus `seats_bound`. Released and voided seats hold
    no capacity."

    Design: Difficulty/compensating_invariant/seat_pool_conservation_across_bind_and_release
    """
    household = fx.open_household()
    addon = fx.buy_addon(household, addon_type="DEVICE_PROTECTION", seats_total=3,
                         per_seat_fee_cents=250)
    assert addon["seats_bound"] == 0
    assert addon["seats_available"] == 3
    assert_seat_conservation(addon)

    seat = fx.bind_seat(household, addon["id"], device_label="Dana Laptop")
    mid = fx.read_addon(addon["id"])
    assert mid["seats_bound"] == 1
    assert mid["seats_available"] == 2
    assert_seat_conservation(mid)

    validate_success(api.release_seat(seat["id"], household["owner"]))
    after = fx.read_addon(addon["id"])
    assert after["seats_bound"] == 0
    assert after["seats_available"] == 3
    assert_seat_conservation(after)


def test_releasing_a_seat_is_not_a_rebind_and_mints_no_phantom_row(api):
    """PRD §3.8: "A released seat carries a derived `rebind_eligible_at`, which is its
    `released_at` advanced by 72 hours and is null while `released_at` is null."
    PRD §3.8: "A new seat is created in `BOUND` with `bind_count` 1, and the add-on's
    `seats_bound` rises, `seats_available` falls, and `version` increments."

    Design: Difficulty/compensating_invariant/seat_pool_conservation_across_bind_and_release
    """
    household = fx.open_household()
    addon = fx.buy_addon(household, addon_type="DEVICE_PROTECTION", seats_total=3,
                         per_seat_fee_cents=250)
    seat = fx.bind_seat(household, addon["id"], device_label="Dana Laptop")

    data = validate_success(api.release_seat(seat["id"], household["owner"]))

    assert data["status"] == "RELEASED"
    assert data["bind_count"] == 1, "a release is not a re-bind"
    # released_at 2026-05-01T00:00:00Z + 72 hours = 2026-05-04T00:00:00Z.
    assert_same_instant(data["rebind_eligible_at"], "2026-05-04T00:00:00Z",
                        "rebind_eligible_at")

    _, meta = validate_paginated(api.list_device_seats(
        household["owner"], params={"addon_id": addon["id"]}))
    assert meta["total_count"] == 1, "the round trip must create no extra seat row"


# ==========================================================================
# Conserved quantity 3 — the number of derived alert rows
# ==========================================================================

def _breach_world():
    """One ACTIVE profile carrying one EMAIL identifier, plus a breach event whose
    record types give record points max(10, 30) = 30."""
    household = fx.open_household()
    profile = fx.draft_profile(household)
    identifier = fx.add_identifier(profile["id"], household["owner"],
                                   identifier_type="EMAIL",
                                   identifier_value="dana@example.com")
    validate_success(fx.api.activate_profile(profile["id"], household["owner"]))
    event = fx.create_breach_event(name="MailVault 2026",
                                   breach_date="2026-04-01T00:00:00Z",
                                   disclosed_at="2026-04-15T00:00:00Z",
                                   record_types=["EMAIL_ADDRESS", "PASSWORD_HASH"],
                                   base_severity_points=15)
    return household, profile, identifier, event


def test_re_ingesting_the_same_breach_never_mints_a_second_alert(api):
    """PRD §2.10: "For a given breach event, the number of breach-alert rows equals the
    number of **distinct** monitored identifiers ever matched by any ingest of that event,
    no matter how many times the same payload is re-ingested and no matter how many
    duplicate values appear inside a single payload."
    PRD §3.6: "Duplicate values inside a single `matched_identifier_values` array collapse
    to a single match per identifier row."

    Design: Difficulty/compensating_invariant/breach_alert_row_count_conserved_across_reingest
    """
    household, profile, identifier, event = _breach_world()

    first = fx.ingest_breach(event["id"], ["dana@example.com"])
    assert first["created_alert_count"] == 1
    assert first["escalated_alert_count"] == 0
    assert first["unchanged_alert_count"] == 0
    assert first["matched_identifier_count"] == 1

    second = fx.ingest_breach(event["id"], ["dana@example.com", "dana@example.com"])
    assert second["created_alert_count"] == 0
    assert second["unchanged_alert_count"] == 1
    assert second["matched_identifier_count"] == 1, "duplicates collapse to one match"

    fx.ingest_breach(event["id"], ["dana@example.com"])
    fx.ingest_breach(event["id"], ["dana@example.com"])

    rows, meta = fx.alerts_for_event(event["id"], household["owner"])
    assert meta["total_count"] == 1
    assert rows[0]["identifier_id"] == identifier["id"]
    assert rows[0]["member_id"] == household["owner_id"]


def test_alert_severity_ratchets_upward_and_never_falls_back(api):
    """PRD §3.6: "The stored severity is replaced only when the ordinal of the recomputed
    band is **strictly greater** than the ordinal of the stored band; in that case
    `severity` and `severity_points` are both replaced and `escalation_count` increments
    by 1."
    PRD §3.6: "When the recomputed ordinal is lower than or equal to the stored one,
    `severity`, `severity_points`, `escalation_count`, `updated_at` and `version` are
    **all** left untouched."

    Design: Difficulty/compensating_invariant/breach_alert_row_count_conserved_across_reingest
    """
    household, profile, identifier, event = _breach_world()

    fx.ingest_breach(event["id"], ["dana@example.com"])
    rows, _ = fx.alerts_for_event(event["id"], household["owner"])
    alert_id = rows[0]["id"]
    # 15 base + 30 record (max of EMAIL_ADDRESS 10 and PASSWORD_HASH 30)
    # + 5 identifier bonus (EMAIL is not SSN_LAST4) + 0 hygiene = 50 -> HIGH (>= 45).
    assert rows[0]["severity_points"] == 50
    assert rows[0]["severity"] == "HIGH"

    finding = fx.add_credential_finding(profile["id"], "BREACHED_PASSWORD",
                                        detail="mail vault")
    escalating = fx.ingest_breach(event["id"], ["dana@example.com"])
    assert escalating["created_alert_count"] == 0
    assert escalating["escalated_alert_count"] == 1
    escalated = fx.read_alert(alert_id, household["owner"])
    # 50 + 10 hygiene escalation = 60 -> CRITICAL (>= 60); ordinal 4 > 3.
    assert escalated["severity_points"] == 60
    assert escalated["severity"] == "CRITICAL"
    assert escalated["escalation_count"] == 1

    validate_success(api.remediate_finding(finding["id"], household["owner"]))
    quiet = fx.ingest_breach(event["id"], ["dana@example.com"])
    assert quiet["created_alert_count"] == 0
    assert quiet["escalated_alert_count"] == 0
    assert quiet["unchanged_alert_count"] == 1

    final = fx.read_alert(alert_id, household["owner"])
    # The recomputed total falls back to 50 / HIGH (ordinal 3), which is lower than
    # the stored CRITICAL (ordinal 4), so nothing moves.
    assert final["severity"] == "CRITICAL"
    assert final["severity_points"] == 60
    assert final["escalation_count"] == 1
    assert final["version"] == escalated["version"]
    assert_same_instant(final["updated_at"], escalated["updated_at"], "updated_at")

    event_row = validate_success(api.list_breach_alerts(fx.ADMIN,
                                                        params={"breach_event_id": event["id"]}))
    assert len(event_row) == 1
