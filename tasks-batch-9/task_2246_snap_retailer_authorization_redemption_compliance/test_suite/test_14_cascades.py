"""Two multi-level cascades fired from two different roots.

Enforcement propagates from the sanction case down through the store, its
deployment, its terminal and the depot counters, and sideways onto the owner. A
monitoring close propagates from the period through the store's sanction
dimension into the release of its reservations.
"""
from test_helpers import (
    ADMIN,
    active_equipment,
    advance_clock,
    api_client,
    assert_depot_conservation,
    assert_fields,
    authorized_store,
    close_period,
    enforce_case,
    file_reply,
    finalize_case,
    issue_charge_letter,
    issue_determination,
    open_case,
    open_flagged_period,
    refresh_deployment,
    refresh_depot,
    refresh_owner,
    refresh_store,
    refresh_terminal,
    reserved_equipment,
    rows,
    substantiated_trafficking_investigation,
)


def _enforced_permanent_disqualification():
    """An authorized store with one ACTIVE deployment, permanently disqualified
    and enforced on the effective date."""
    context = authorized_store()
    equipment = active_equipment(context.store)
    investigation = substantiated_trafficking_investigation(context.store_id)
    case = open_case(investigation["id"], "TRAFFICKING")
    case = issue_charge_letter(case["id"])
    file_reply(case["id"], context.owner)
    issue_determination(case["id"], "PERMANENT_DISQUALIFICATION")
    advance_clock("2026-08-12T00:00:00Z")
    finalize_case(case["id"])
    advance_clock("2026-09-11T00:00:00Z")
    return context, equipment, enforce_case(case["id"])


def test_enforcement_disqualifies_the_store_and_rolls_up_onto_the_owner():
    """One enforce call terminally disqualifies the store and posts the permanent
    disqualification onto the owner, who is not yet barred.

    The specification lets enforcement run only "on or after the effective date",
    at which point it "cascad[es] through the store, its deployments, its
    terminals, the depot counters and the owner rollup". A permanent
    disqualification leaves no reinstatement date, and the owner's status only
    turns BARRED on a second permanent disqualification.

    Design: Difficulty/transitive_cascade/enforcement_cascade_case_store_deployment_terminal_depot_owner_five_levels
    """
    context, _equipment, case = _enforced_permanent_disqualification()

    assert_fields(
        case,
        {
            "status": "ENFORCED",
            "effective_date": "2026-09-11T00:00:00Z",
            "enforced_at": "2026-09-11T00:00:00Z",
        },
        "enforced case",
    )
    store = refresh_store(context.store_id)
    assert_fields(
        store,
        {
            "authorization_status": "DISQUALIFIED",
            "permanently_disqualified": True,
            "disqualified_until": None,
            "active_terminal_count": 0,
        },
        "disqualified store",
    )
    owner = refresh_owner(context.owner_id)
    assert_fields(
        owner,
        {
            "permanent_disqualification_count": 1,
            "sanction_flag": "PERMANENTLY_DISQUALIFIED",
            "status": "ACTIVE",
        },
        "owner rollup",
    )


def test_enforcement_recalls_the_hardware_and_re_derives_the_depot_counters():
    """The same enforce call marks the deployment for recall with an
    authorization-lost reason, puts the terminal in pending-return and moves the
    unit between two depot counters without changing the total.

    The specification requires the depot's five counters to stay in balance --
    "`units_in_stock` plus `units_reserved` plus `units_deployed` plus
    `units_pending_return` plus `units_retired` equals `total_units_owned`." -- so
    the enforced unit leaves `units_deployed` for `units_pending_return`.

    Design: Difficulty/transitive_cascade/enforcement_cascade_case_store_deployment_terminal_depot_owner_five_levels
    """
    _context, equipment, _case = _enforced_permanent_disqualification()

    deployment = refresh_deployment(equipment.deployment_id)
    assert_fields(
        deployment,
        {"status": "RECALL_PENDING", "close_reason_code": "AUTHORIZATION_LOST"},
        "recalled deployment",
    )
    assert refresh_terminal(equipment.terminal_id)["status"] == "PENDING_RETURN"

    assert_depot_conservation(
        refresh_depot(equipment.depot_id),
        {
            "units_deployed": 0,
            "units_pending_return": 1,
            "units_in_stock": 4,
            "units_reserved": 0,
            "units_retired": 0,
        },
    )


def _flag_l3_close_over_a_reservation():
    """An authorized store holding a RESERVED, never-activated deployment, whose
    only monitoring period closes at FLAG_L3."""
    context = authorized_store()
    equipment = reserved_equipment(context.store)
    period = open_flagged_period(context.store_id)
    return context, equipment, period, close_period(period["id"])


def test_flag_l3_close_opens_a_system_investigation_without_touching_authorization():
    """The monitoring close scores the period, flags the store, opens one
    investigation carrying the triggering period, and leaves the store trading.

    The cascade runs entirely inside the sanction dimension: the specification
    keeps the store AUTHORIZED through investigation, and a system-opened
    investigation starts OPEN with no evidence, so its confidence score is zero.

    Design: Difficulty/transitive_cascade/period_close_cascade_flag_investigation_sanction_status_and_reserved_release
    """
    context, _equipment, period, closed = _flag_l3_close_over_a_reservation()

    assert_fields(
        closed,
        {"status": "CLOSED", "anomaly_score": 92, "flag_level": "FLAG_L3"},
        "closed period",
    )
    store = refresh_store(context.store_id)
    assert_fields(
        store,
        {
            "redemption_flag_level": "FLAG_L3",
            "sanction_status": "UNDER_INVESTIGATION",
            "authorization_status": "AUTHORIZED",
        },
        "flagged store",
    )

    investigations = rows(
        api_client.list_investigations(ADMIN, {"store_id": context.store_id})
    )
    assert len(investigations) == 1, (
        f"expected exactly one system investigation, got {investigations}"
    )
    assert_fields(
        investigations[0],
        {
            "opened_reason": "ANOMALY_FLAG_L3",
            "trigger_period_id": period["id"],
            "status": "OPEN",
            "trafficking_confidence_score": 0,
        },
        "system investigation",
    )


def test_flag_l3_close_releases_the_reservation_back_into_depot_stock():
    """The reserved deployment the store never activated is released by the same
    close, the terminal returns to stock and the depot is whole again.

    This is the branch enforcement never reaches: only RESERVED commitments are
    released when an investigation opens, and a released unit goes straight back
    to `units_in_stock` rather than through pending return, keeping the five
    counters summing to `total_units_owned`.

    Design: Difficulty/transitive_cascade/period_close_cascade_flag_investigation_sanction_status_and_reserved_release
    """
    context, equipment, _period, _closed = _flag_l3_close_over_a_reservation()

    deployment = refresh_deployment(equipment.deployment_id)
    assert_fields(
        deployment,
        {"status": "RELEASED", "closed_at": "2026-08-01T00:00:00Z"},
        "released deployment",
    )
    assert refresh_terminal(equipment.terminal_id)["status"] == "IN_STOCK"

    assert_depot_conservation(
        refresh_depot(equipment.depot_id),
        {"units_reserved": 0, "units_in_stock": 5},
    )
    assert refresh_store(context.store_id)["active_terminal_count"] == 0
