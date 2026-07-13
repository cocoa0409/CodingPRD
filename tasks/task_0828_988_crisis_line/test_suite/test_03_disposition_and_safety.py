"""Contact disposition gating, the SCREENED->EMERGENCY branch, and safety-plan preconditions."""
from test_helpers import (
    api_client as api,
    validate_success, validate_error, validate_paginated,
    TEST_USERS,
    create_screened_contact, create_de_escalation_contact,
)

COUNSELOR = TEST_USERS["counselor_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── priority_pair_validation_conflict / state_beats_disposition_safety ────────

def test_dispatch_pending_from_de_escalation_yields_invalid_state():
    """PRD §2.8: "the target resource being in a legal from-state for the requested transition, yielding `ERR_INVALID_STATE`"
    PRD §2.8: "Earlier checks strictly precede later ones"
    PRD §3.3: "Each disposition is available only from `SCREENED`; attempting it from any other state fails the from-state check with `ERR_INVALID_STATE`."

    A DE_ESCALATION MODERATE contact requesting DISPATCH_PENDING fails both the from-state
    check (5) and the band safety check (7); the earlier state check wins.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_disposition_safety_on_contact_state
    """
    contact = create_de_escalation_contact("pc-a-01")
    res = api.contact_state(contact["id"], {"to_status": "DISPATCH_PENDING"}, DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_disposition_safety_fires_alone_when_state_is_valid():
    """PRD §3.3: "A dispatcher may route a `SCREENED` contact toward mobile dispatch, moving it to `DISPATCH_PENDING`; this is permitted only when the `risk_band` is exactly `HIGH`, and any other band is rejected with `ERR_DISPOSITION_NOT_ALLOWED`."

    Isolation control for the precedence pair: with the from-state legal (SCREENED), only
    the band safety check (7) can fail, surfacing ERR_DISPOSITION_NOT_ALLOWED — proving the
    check exists and is what the state error pre-empts in the conflict case above.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_disposition_safety_on_contact_state
    """
    contact = create_screened_contact("pc-a-02", band="MODERATE")
    res = api.contact_state(contact["id"], {"to_status": "DISPATCH_PENDING"}, DISPATCHER)
    validate_error(res, "ERR_DISPOSITION_NOT_ALLOWED", expected_status=409)


# ─── non_linear_state_machine / contact_screened_branches_to_emergency ─────────

def test_screened_imminent_branches_to_emergency_sets_status():
    """PRD §3.3: "The emergency route sets `disposition` to `EMERGENCY`, stamps `disposition_at`, sets `emergency_status` to `INITIATED`, and creates the 911 hand-off record described in §3.7."

    Design: Difficulty/non_linear_state_machine/contact_screened_branches_to_emergency_with_divergent_side_effects
    """
    contact = create_screened_contact("br-emg-01", band="IMMINENT", channel="TEXT")
    res = api.contact_state(contact["id"], {"to_status": "EMERGENCY_911"}, DISPATCHER)
    updated = validate_success(res, 200)
    assert updated["status"] == "EMERGENCY_911", f"expected EMERGENCY_911, got {updated['status']}"
    assert updated["emergency_status"] == "INITIATED", (
        f"expected INITIATED, got {updated['emergency_status']}"
    )


def test_screened_imminent_branch_creates_emergency_coordination():
    """PRD §3.7: "Whenever a contact enters `EMERGENCY_911`, the system sets the contact's `emergency_status` to `INITIATED` and creates an `EmergencyCoordination` record carrying the `contact_id`, a `psap_reference` token for the 911 (PSAP) hand-off, a `risk_band_at_escalation` snapshot of the contact's `risk_band` at that instant, and the `initiated_by_role` naming the role that triggered the hand-off."

    Design: Difficulty/non_linear_state_machine/contact_screened_branches_to_emergency_with_divergent_side_effects
    """
    contact = create_screened_contact("br-emg-02", band="IMMINENT", channel="TEXT")
    validate_success(api.contact_state(contact["id"], {"to_status": "EMERGENCY_911"}, DISPATCHER), 200)

    rows, meta = validate_paginated(
        api.list_emergency_coordinations(DISPATCHER, params={"contact_id": contact["id"]})
    )
    assert meta["total_count"] == 1, f"expected exactly 1 coordination record, got {meta['total_count']}"
    assert rows[0]["risk_band_at_escalation"] == "IMMINENT", (
        f"expected IMMINENT snapshot, got {rows[0]['risk_band_at_escalation']}"
    )


# ─── Corner / disposition_de_escalation_on_high_band_returns_not_allowed ───────

def test_de_escalation_on_high_band_rejected():
    """PRD §3.3: "A counselor may route a `SCREENED` contact toward de-escalation, moving it to `DE_ESCALATION`; this is permitted only when the contact's `risk_band` is `LOW` or `MODERATE`, and any other band is rejected with `ERR_DISPOSITION_NOT_ALLOWED`."

    Design: Corner/validations/disposition_de_escalation_on_high_band_returns_not_allowed
    """
    contact = create_screened_contact("vd-a-01", band="HIGH")
    res = api.contact_state(contact["id"], {"to_status": "DE_ESCALATION"}, COUNSELOR)
    validate_error(res, "ERR_DISPOSITION_NOT_ALLOWED", expected_status=409)


# ─── Corner / resolve_de_escalation_without_active_safety_plan_returns_error ───

def test_resolve_de_escalation_without_active_safety_plan_rejected():
    """PRD §3.4: "A counselor resolves a `DE_ESCALATION` contact by moving it to `RESOLVED`, but this is permitted only when the contact's `has_active_safety_plan` is true; if the contact has no active safety plan the resolution is rejected with `ERR_NO_ACTIVE_SAFETY_PLAN`."

    Design: Corner/validations/resolve_de_escalation_without_active_safety_plan_returns_error
    """
    contact = create_de_escalation_contact("vd-b-01")
    res = api.contact_state(contact["id"], {"to_status": "RESOLVED"}, COUNSELOR)
    validate_error(res, "ERR_NO_ACTIVE_SAFETY_PLAN", expected_status=409)
