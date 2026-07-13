"""Transitive cascades (escalate / divert), conserved ledgers, terminal-state lockdown."""
from test_helpers import (
    api_client as api,
    validate_success, validate_error,
    create_safety_plan_payload, TEST_USERS,
    create_contact, create_screened_contact,
    setup_dispatch, setup_held_referral, drive_dispatch_to_completed,
)

SUP = TEST_USERS["supervisor_headers"]
COUNSELOR = TEST_USERS["counselor_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── transitive_cascade / escalate_cancels_dispatch_voids_referral_decrements_center ─

def test_escalate_cancels_dispatch():
    """PRD §3.7: "Escalating from `DISPATCH_PENDING` or `REFERRAL_PENDING` first cancels the contact's active mobile dispatch (any dispatch in `REQUESTED`, `EN_ROUTE`, or `ON_SCENE`) to `CANCELLED`, if one exists"

    Design: Difficulty/transitive_cascade/escalate_cancels_dispatch_voids_referral_decrements_center
    """
    contact, center, referral, dispatch = setup_held_referral("casc-01", dispatch_link=True)
    validate_success(api.contact_state(contact["id"], {"to_status": "EMERGENCY_911"}, DISPATCHER), 200)

    got_contact = validate_success(api.get_contact(contact["id"], DISPATCHER), 200)
    assert got_contact["status"] == "EMERGENCY_911", f"got {got_contact['status']}"
    got_dispatch = validate_success(api.get_dispatch(dispatch["id"], DISPATCHER), 200)
    assert got_dispatch["status"] == "CANCELLED", (
        f"escalate must cancel the active dispatch, got {got_dispatch['status']}"
    )


def test_escalate_cascade_voids_referral_and_decrements_center():
    """PRD §3.7: "from `REFERRAL_PENDING` this begins the escalate cascade, since cancelling the dispatch voids the linked `HELD` bed referral, whose `VOIDED` transition decrements the center's `held_beds` — and note that because this contact is being escalated in the same request, the void does not revert the contact back to `DISPATCH_PENDING`."

    Design: Difficulty/transitive_cascade/escalate_cancels_dispatch_voids_referral_decrements_center
    """
    contact, center, referral, dispatch = setup_held_referral("casc-02", dispatch_link=True)
    validate_success(api.contact_state(contact["id"], {"to_status": "EMERGENCY_911"}, DISPATCHER), 200)

    got_referral = validate_success(api.get_bed_referral(referral["id"], DISPATCHER), 200)
    assert got_referral["status"] == "VOIDED", (
        f"cancel cascade must void the linked HELD referral, got {got_referral['status']}"
    )
    got_center = validate_success(api.get_center(center["id"], DISPATCHER), 200)
    assert got_center["held_beds"] == 0, (
        f"held_beds must decrement to 0 after cascade void, got {got_center['held_beds']}"
    )


# ─── transitive_cascade / center_divert_voids_referral_reverts_contact ─────────

def test_center_divert_voids_held_referral():
    """PRD §3.6: "Diverting a center moves it from `ONLINE` to `DIVERTED`: as a cascade, every one of that center's referrals still in `HELD` is transitioned `HELD` to `VOIDED`, and each such void decrements `held_beds` and reverts its contact from `REFERRAL_PENDING` to `DISPATCH_PENDING`; the center's `version` is then incremented."

    Design: Difficulty/transitive_cascade/center_divert_voids_referral_reverts_contact
    """
    contact, center, referral, _ = setup_held_referral("divert-01")
    got_center = validate_success(api.center_state(center["id"], {"to_status": "DIVERTED"}, DISPATCHER), 200)
    assert got_center["status"] == "DIVERTED", f"got {got_center['status']}"
    got_referral = validate_success(api.get_bed_referral(referral["id"], DISPATCHER), 200)
    assert got_referral["status"] == "VOIDED", (
        f"divert must void the HELD referral, got {got_referral['status']}"
    )


def test_center_divert_reverts_contact_and_decrements_beds():
    """PRD §3.6: "Diverting a center moves it from `ONLINE` to `DIVERTED`: as a cascade, every one of that center's referrals still in `HELD` is transitioned `HELD` to `VOIDED`, and each such void decrements `held_beds` and reverts its contact from `REFERRAL_PENDING` to `DISPATCH_PENDING`; the center's `version` is then incremented."

    Design: Difficulty/transitive_cascade/center_divert_voids_referral_reverts_contact
    """
    contact, center, referral, _ = setup_held_referral("divert-02")
    validate_success(api.center_state(center["id"], {"to_status": "DIVERTED"}, DISPATCHER), 200)
    got_contact = validate_success(api.get_contact(contact["id"], DISPATCHER), 200)
    assert got_contact["status"] == "DISPATCH_PENDING", (
        f"void must revert contact to DISPATCH_PENDING, got {got_contact['status']}"
    )
    got_center = validate_success(api.get_center(center["id"], DISPATCHER), 200)
    assert got_center["held_beds"] == 0, f"expected held_beds 0, got {got_center['held_beds']}"


# ─── compensating_invariant / team_slot_conserved_on_dispatch_cancel ───────────

def test_dispatch_create_increments_team_active_count():
    """PRD §3.5: "The dispatch is created in `REQUESTED`; the owning team's `active_dispatch_count` is incremented and its `version` is incremented; and the dispatch's `priority_score_estimated` is pinned at creation."
    PRD §2.9: "For a mobile crisis team, `active_dispatch_count` is the count of that team's dispatches currently in `REQUESTED`, `EN_ROUTE`, or `ON_SCENE`."

    Design: Difficulty/compensating_invariant/team_slot_conserved_on_dispatch_cancel
    """
    _, team, _ = setup_dispatch("ci-a-01")  # capacity-1 team, one REQUESTED dispatch
    got_team = validate_success(api.get_team(team["id"], DISPATCHER), 200)
    assert got_team["active_dispatch_count"] == 1, (
        f"expected active_dispatch_count 1 after create, got {got_team['active_dispatch_count']}"
    )
    assert got_team["capacity"] == 1, f"expected capacity 1, got {got_team['capacity']}"


def test_dispatch_cancel_conserves_team_slot():
    """PRD §3.5: "A dispatch may be cancelled to `CANCELLED` from any of `REQUESTED`, `EN_ROUTE`, or `ON_SCENE`; every cancellation decrements the team's `active_dispatch_count` and increments the team's `version`"
    PRD §2.9: "The team's remaining capacity is its `capacity` minus `active_dispatch_count`, and the invariant that remaining capacity plus `active_dispatch_count` equals `capacity` holds at every moment."

    Design: Difficulty/compensating_invariant/team_slot_conserved_on_dispatch_cancel
    """
    _, team, dispatch = setup_dispatch("ci-a-02")
    got_dispatch = validate_success(
        api.dispatch_state(dispatch["id"], {"to_status": "CANCELLED"}, DISPATCHER), 200)
    assert got_dispatch["status"] == "CANCELLED", f"got {got_dispatch['status']}"
    got_team = validate_success(api.get_team(team["id"], DISPATCHER), 200)
    assert got_team["active_dispatch_count"] == 0, (
        f"cancel must restore active_dispatch_count to 0, got {got_team['active_dispatch_count']}"
    )
    assert got_team["capacity"] == 1, f"capacity must stay 1, got {got_team['capacity']}"


# ─── compensating_invariant / center_bed_conserved_on_referral_void ────────────

def test_bed_referral_create_holds_a_bed():
    """PRD §3.6: "A successful referral is created in `HELD`; the center's `held_beds` is incremented and its `version` is incremented; and the contact is driven from `DISPATCH_PENDING` to `REFERRAL_PENDING`."
    PRD §2.9: "The center's `available_beds` is its `bed_capacity` minus `held_beds` minus `occupied_beds`."

    Design: Difficulty/compensating_invariant/center_bed_conserved_on_referral_void
    """
    _, center, _, _ = setup_held_referral("ci-b-01")  # capacity-1 center, one HELD referral
    got_center = validate_success(api.get_center(center["id"], DISPATCHER), 200)
    assert got_center["held_beds"] == 1, f"expected held_beds 1, got {got_center['held_beds']}"
    assert got_center["available_beds"] == 0, (
        f"expected available_beds 0 on capacity-1 center with 1 hold, got {got_center['available_beds']}"
    )


def test_bed_referral_void_conserves_center_beds():
    """PRD §3.6: "Voiding a referral moves it from `HELD` to `VOIDED`; voiding decrements the center's `held_beds`, and if the linked contact is in `REFERRAL_PENDING` — and that contact is not being escalated to `EMERGENCY_911` in the very same request — it reverts the contact from `REFERRAL_PENDING` back to `DISPATCH_PENDING`."
    PRD §2.9: "The invariant `available_beds + held_beds + occupied_beds == bed_capacity` holds at every moment."

    Design: Difficulty/compensating_invariant/center_bed_conserved_on_referral_void
    """
    _, center, referral, _ = setup_held_referral("ci-b-02")
    got_referral = validate_success(
        api.bed_referral_state(referral["id"], {"to_status": "VOIDED"}, DISPATCHER), 200)
    assert got_referral["status"] == "VOIDED", f"got {got_referral['status']}"
    got_center = validate_success(api.get_center(center["id"], DISPATCHER), 200)
    assert got_center["held_beds"] == 0, f"void must restore held_beds to 0, got {got_center['held_beds']}"
    assert got_center["available_beds"] == 1, (
        f"expected available_beds 1 after void, got {got_center['available_beds']}"
    )


# ─── Corner / cancel_dispatch_from_completed_returns_invalid_state ─────────────

def test_cancel_completed_dispatch_returns_invalid_state():
    """PRD §3.5: "Each transition is legal only from its named from-state; any other origin is rejected with `ERR_INVALID_STATE`. `COMPLETED` and `CANCELLED` are terminal."

    Design: Corner/state_machines/cancel_dispatch_from_completed_returns_invalid_state
    """
    _, _, dispatch = setup_dispatch("sm-a-01")
    drive_dispatch_to_completed(dispatch["id"])
    res = api.dispatch_state(dispatch["id"], {"to_status": "CANCELLED"}, DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner / safety_plan_activate_from_archived_returns_invalid_state ─────────

def test_activate_archived_safety_plan_returns_invalid_state():
    """PRD §3.4: "A counselor activates a plan by moving it from `DRAFT` to `ACTIVE`, which is legal only from `DRAFT`."
    PRD §2.8: "the target resource being in a legal from-state for the requested transition, yielding `ERR_INVALID_STATE`"

    Design: Corner/state_machines/safety_plan_activate_from_archived_returns_invalid_state
    """
    contact = create_screened_contact("sm-b-01", band="MODERATE")
    plan = validate_success(
        api.create_safety_plan(create_safety_plan_payload(contact["id"]), COUNSELOR), 201)
    validate_success(api.safety_plan_state(plan["id"], {"to_status": "ARCHIVED"}, COUNSELOR), 200)
    res = api.safety_plan_state(plan["id"], {"to_status": "ACTIVE"}, COUNSELOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner / close_contact_from_intake_returns_invalid_state ──────────────────

def test_close_intake_contact_returns_invalid_state():
    """PRD §3.8: "the case is administratively closed by a supervisor driving it from `RESOLVED` to `CLOSED`; this close is reserved exclusively to the `ClinicalSupervisor` role, is legal only while the contact is in `RESOLVED`, and carries no further side effects."
    PRD §2.8: "the target resource being in a legal from-state for the requested transition, yielding `ERR_INVALID_STATE`"

    Design: Corner/state_machines/close_contact_from_intake_returns_invalid_state
    """
    contact = create_contact("sm-c-01", channel="PHONE")
    res = api.contact_state(contact["id"], {"to_status": "CLOSED"}, SUP)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
