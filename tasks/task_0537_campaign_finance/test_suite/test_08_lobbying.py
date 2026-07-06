"""Lobbying registrants, clients, activities: committed vs certified spend, client-active
gate, conservation on void, and activity overlap."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_activity_payload,
    TEST_USERS, make_registrant_headers,
    set_clock, create_registrant, add_client, create_lobbying_period,
    add_activity, get_registrant, setup_registrant_with_client_and_period,
)

REGULATOR = TEST_USERS["regulator_headers"]
PUBLIC = TEST_USERS["public_headers"]


# --------------------------------------------------------------------------- #
# Committed vs certified spend
# --------------------------------------------------------------------------- #
def _registrant_two_period_spend(api, name):
    """registrant + client; LP1 OPEN with 30000 activity; LP2 with 20000 activity then CLOSED."""
    set_clock(api, "2026-06-01T00:00:00Z")
    registrant = create_registrant(api, name=name)
    rgid = registrant["id"]
    client = add_client(api, rgid, client_name="ClientCo")
    lp1 = create_lobbying_period(api, period_label="LP1", period_start="2026-01-01T00:00:00Z",
                                 period_end="2026-03-31T00:00:00Z", filing_deadline="2026-04-15T00:00:00Z")
    lp2 = create_lobbying_period(api, period_label="LP2", period_start="2026-04-02T00:00:00Z",
                                 period_end="2026-06-30T00:00:00Z", filing_deadline="2026-07-15T00:00:00Z")
    add_activity(api, rgid, client["id"], lp1["id"], subject="S1", amount_cents=30000, activity_date="2026-02-01T00:00:00Z")
    add_activity(api, rgid, client["id"], lp2["id"], subject="S2", amount_cents=20000, activity_date="2026-05-01T00:00:00Z")
    validate_success(api.close_lobbying_period(lp2["id"], REGULATOR))
    return rgid


def test_committed_spend_counts_all_recorded_activities(api):
    """PRD §3.7: "total_committed_spend_cents is the sum of amount_cents over the registrant's
    RECORDED activities across all periods regardless of period status — the provisional view."

    Design: Difficulty/dual_variant_calc/registrant_committed_vs_certified_spend
    """
    rgid = _registrant_two_period_spend(api, "Lobby LLC A")
    registrant = get_registrant(api, rgid)
    assert registrant["total_committed_spend_cents"] == 50000, "30000 (OPEN LP1) + 20000 (CLOSED LP2)"


def test_certified_spend_counts_only_closed_period_activities(api):
    """PRD §3.7: "total_certified_spend_cents is the sum of amount_cents over the registrant's
    RECORDED activities whose lobbying period is CLOSED — the certified view; because it
    restricts to closed periods, the certified total is always less than or equal to the
    committed total."

    Design: Difficulty/dual_variant_calc/registrant_committed_vs_certified_spend
    """
    rgid = _registrant_two_period_spend(api, "Lobby LLC B")
    registrant = get_registrant(api, rgid)
    assert registrant["total_certified_spend_cents"] == 20000, "only the CLOSED LP2 activity is certified"
    assert registrant["total_committed_spend_cents"] != registrant["total_certified_spend_cents"]


# --------------------------------------------------------------------------- #
# Client-active gate on activity create
# --------------------------------------------------------------------------- #
def test_activity_for_deactivated_client_rejected(api):
    """PRD §3.7: "Recording an activity requires both the client and the registrant to be
    ACTIVE; a non-active client is rejected with ERR_CLIENT_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/activity_requires_client_active
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    registrant = create_registrant(api, name="LamL")
    rgid = registrant["id"]
    client = add_client(api, rgid, client_name="ClientCo")
    validate_success(api.deactivate_client(client["id"], make_registrant_headers(rgid)))
    period = create_lobbying_period(api)
    resp = api.create_activity(
        rgid, create_activity_payload(client["id"], period["id"], amount_cents=5000), make_registrant_headers(rgid)
    )
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_ACTIVE.value)


def test_rejected_activity_leaves_registrant_spend_unchanged(api):
    """PRD §3.7: "A newly recorded activity is created in RECORDED status, and its creation
    recomputes the registrant's spend totals and increments the registrant's version." (a
    rejected create records nothing, so the totals are untouched)

    Design: Difficulty/cross_entity_state_dependency/activity_requires_client_active
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    registrant = create_registrant(api, name="LamL2")
    rgid = registrant["id"]
    client = add_client(api, rgid, client_name="ClientCo")
    validate_success(api.deactivate_client(client["id"], make_registrant_headers(rgid)))
    period = create_lobbying_period(api)
    api.create_activity(
        rgid, create_activity_payload(client["id"], period["id"], amount_cents=5000), make_registrant_headers(rgid)
    )
    registrant_after = get_registrant(api, rgid)
    assert registrant_after["total_committed_spend_cents"] == 0, "a rejected activity records no spend"


# --------------------------------------------------------------------------- #
# Conservation on activity create + void
# --------------------------------------------------------------------------- #
def test_committed_spend_reflects_new_activity(api):
    """PRD §3.7: "A newly recorded activity is created in RECORDED status, and its creation
    recomputes the registrant's spend totals and increments the registrant's version."

    Design: Difficulty/compensating_invariant/activity_create_void_conserves_registrant_spend
    """
    registrant, client, period = setup_registrant_with_client_and_period(api, registrant_overrides={"name": "MuL"})
    rgid = registrant["id"]
    assert get_registrant(api, rgid)["total_committed_spend_cents"] == 0
    add_activity(api, rgid, client["id"], period["id"], amount_cents=25000)
    assert get_registrant(api, rgid)["total_committed_spend_cents"] == 25000


def test_committed_spend_conserved_after_create_then_void(api):
    """PRD §3.7: "Voiding an activity recomputes the registrant's total_committed_spend_cents
    downward, and also recomputes total_certified_spend_cents downward when the voided
    activity's period was CLOSED, then increments the registrant's version."

    Design: Difficulty/compensating_invariant/activity_create_void_conserves_registrant_spend
    """
    registrant, client, period = setup_registrant_with_client_and_period(api, registrant_overrides={"name": "MuL2"})
    rgid = registrant["id"]
    before = get_registrant(api, rgid)["total_committed_spend_cents"]
    activity = add_activity(api, rgid, client["id"], period["id"], amount_cents=25000)
    validate_success(api.void_activity(activity["id"], make_registrant_headers(rgid)))
    after = get_registrant(api, rgid)["total_committed_spend_cents"]
    assert before == 0 and after == 0, "voided activity must restore committed spend to the pre-create value"


# --------------------------------------------------------------------------- #
# Activity state / overlap (corner)
# --------------------------------------------------------------------------- #
def test_void_already_voided_activity_rejected(api):
    """PRD §3.7: "The owning registrant may void a recorded activity, moving it from RECORDED
    to the terminal VOIDED; this requires the activity to be RECORDED and is otherwise
    rejected with ERR_ACTIVITY_NOT_VOIDABLE."

    Design: Corner/state_machines/activity_void_twice_rejected
    """
    registrant, client, period = setup_registrant_with_client_and_period(api, registrant_overrides={"name": "VoidL"})
    rgid = registrant["id"]
    activity = add_activity(api, rgid, client["id"], period["id"], amount_cents=5000)
    validate_success(api.void_activity(activity["id"], make_registrant_headers(rgid)))
    validate_error(api.void_activity(activity["id"], make_registrant_headers(rgid)),
                   ApiErrorId.ERR_ACTIVITY_NOT_VOIDABLE.value)


def test_activity_under_terminated_registrant_rejected(api):
    """PRD §3.7: "Recording an activity requires both the client and the registrant to be
    ACTIVE ... a non-active registrant [is rejected] with ERR_REGISTRANT_NOT_ACTIVE."

    Design: Corner/validations/activity_registrant_terminated_rejected
    """
    registrant = create_registrant(api, name="TermL")
    rgid = registrant["id"]
    client = add_client(api, rgid, client_name="C")
    period = create_lobbying_period(api)
    validate_success(api.terminate_registrant(rgid, make_registrant_headers(rgid)))
    resp = api.create_activity(
        rgid, create_activity_payload(client["id"], period["id"], amount_cents=5000), make_registrant_headers(rgid)
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRANT_NOT_ACTIVE.value)


def test_activity_same_client_same_day_overlap_rejected(api):
    """PRD §3.7: "an activity on a day already occupied by another recorded activity for that
    same pair is rejected with ERR_ACTIVITY_OVERLAP."

    Design: Corner/validations/activity_same_client_day_overlap_rejected
    """
    registrant, client, period = setup_registrant_with_client_and_period(api, registrant_overrides={"name": "OvL"})
    rgid = registrant["id"]
    add_activity(api, rgid, client["id"], period["id"], subject="S1", amount_cents=5000, activity_date="2026-02-01T00:00:00Z")
    resp = api.create_activity(
        rgid, create_activity_payload(client["id"], period["id"], subject="S2", amount_cents=6000,
                                      activity_date="2026-02-01T00:00:00Z"),
        make_registrant_headers(rgid),
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVITY_OVERLAP.value)


def test_registrant_activities_reverse_list(api):
    """PRD §3.8: "a registrant's clients (filterable by status) and activities (filterable by
    client_id, period_id, and status) can be listed."

    Design: Corner/endpoints/registrant_activities_reverse_list
    """
    registrant, client, period = setup_registrant_with_client_and_period(api, registrant_overrides={"name": "RevL"})
    rgid = registrant["id"]
    activity = add_activity(api, rgid, client["id"], period["id"], amount_cents=5000)
    data, _meta = validate_paginated(api.list_registrant_activities(rgid, PUBLIC))
    assert activity["id"] in [a["id"] for a in data], "created activity must appear in the registrant's activities"
