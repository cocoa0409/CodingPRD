"""The consultation lifecycle: the fork at hold, the scope loop and cancellation."""

from test_helpers import (
    ADMIN,
    COORD,
    ApiErrorId,
    assert_consultation,
    make_listing_agent_headers,
    setup_consultation_two_scope_items,
    setup_listing_active,
    validate_error,
    validate_success,
)


def test_holding_a_consultation_before_its_instant_is_too_early(api):
    """PRD §2.7: "Rung 34: the logical clock has reached the scheduled instant of the event
    being reported — the consultation's, install's, visit's, pickup's or shoot's
    `scheduled_at` — where "reached" means the clock is on or after that instant; otherwise
    `ERR_EVENT_TOO_EARLY`, HTTP 422."
    PRD §3.1: "The `SCHEDULED → HELD` transition requires the logical clock to have reached
    `scheduled_at`, stamps `held_at` with the logical clock, and copies the property's
    `occupancy` into the consultation's `pipeline` — `OCCUPIED` becoming `OCCUPIED_PREP`
    and `VACANT` becoming `VACANT_STAGING`."

    Design: Corner/state_machines/consultation_hold_before_scheduled_instant_returns_too_early
    """
    ctx = setup_listing_active()

    resp = api.hold_consultation(ctx["cons_id"], COORD)

    validate_error(resp, ApiErrorId.ERR_EVENT_TOO_EARLY.value, 422)
    data = validate_success(api.get_consultation(ctx["cons_id"], COORD))
    assert_consultation(data)
    assert data["state"] == "SCHEDULED"
    assert data["held_at"] is None


def test_submitting_the_scope_twice_is_an_invalid_consultation_state(api):
    """PRD §2.7: "Rung 18: the consultation's `state` is a legal origin for the requested
    transition; otherwise `ERR_CONSULTATION_INVALID_STATE`, HTTP 409."
    PRD §3.1: "Submitting the scope moves it `SCOPE_DRAFTED → SCOPE_SUBMITTED`, requires at
    least one scoped room and a non-null `recommended_tier_code` of `ESSENTIAL`,
    `SIGNATURE` or `LUXE`, and stores that recommendation along with the consultant's
    `estimated_hours`."

    Design: Corner/state_machines/consultation_submit_scope_twice_rejected_as_invalid_state
    """
    ctx = setup_consultation_two_scope_items()
    validate_success(api.submit_scope(
        ctx["cons_id"], {"recommended_tier_code": "SIGNATURE"}, COORD))

    resp = api.submit_scope(ctx["cons_id"], {"recommended_tier_code": "LUXE"}, COORD)

    validate_error(resp, ApiErrorId.ERR_CONSULTATION_INVALID_STATE.value, 409)
    data = validate_success(api.get_consultation(ctx["cons_id"], COORD))
    assert data["state"] == "SCOPE_SUBMITTED"
    assert data["recommended_tier_code"] == "SIGNATURE"
    assert data["revision_count"] == 0


def test_edit_action_on_a_vacant_consultation_is_a_pipeline_mismatch(api):
    """PRD §3.1: "The legal actions split by pipeline: `EDIT`, `DECLUTTER` and `REFRESH` are
    `OCCUPIED_PREP`-only, `PACKAGE_ROOM` is `VACANT_STAGING`-only, and `ACCESSORY_ONLY` is
    legal on both."
    PRD §2.10: "The same code answers a scope item whose `action` is illegal for its
    consultation's pipeline."

    Design: Corner/state_machines/edit_scope_action_rejected_on_a_vacant_pipeline_consultation
    """
    ctx = setup_consultation_two_scope_items()

    resp = api.add_scope_item(
        ctx["cons_id"],
        {"room_label": "Den", "action": "EDIT", "estimated_hours": 3.0,
         "accessory_set_count": 0}, COORD)

    validate_error(resp, ApiErrorId.ERR_PIPELINE_MISMATCH.value, 409)
    data = validate_success(api.get_consultation(ctx["cons_id"], COORD))
    assert data["scoped_room_count"] == 2


def test_cancelled_consultation_freezes_further_scope_writes(api):
    """PRD §2.7: "Rung 17: the ancestor consultation is not in state `CANCELLED`; otherwise
    `ERR_CONSULTATION_INVALID_STATE`, HTTP 409."
    PRD §3.1: "Abandoning a consultation from `SCHEDULED`, `HELD`, `SCOPE_DRAFTED` or
    `SCOPE_REJECTED` moves it to `CANCELLED` and, when no other live consultation remains
    on that property, returns the property to `NEW`."

    Design: Corner/state_machines/cancelled_consultation_is_terminal_and_blocks_scope_writes
    """
    ctx = setup_consultation_two_scope_items()
    validate_success(api.cancel_consultation(ctx["cons_id"], COORD))

    resp = api.add_scope_item(
        ctx["cons_id"],
        {"room_label": "Den", "action": "PACKAGE_ROOM", "requires_rental": True,
         "accessory_set_count": 0}, COORD)

    validate_error(resp, ApiErrorId.ERR_CONSULTATION_INVALID_STATE.value, 409)
    data = validate_success(api.get_consultation(ctx["cons_id"], COORD))
    assert data["state"] == "CANCELLED"
    prop = validate_success(api.get_property(ctx["prop_id"], COORD))
    assert prop["prep_state"] == "NEW"


def test_project_creation_against_a_submitted_but_unapproved_scope_is_refused(api):
    """PRD §2.7: "Rung 38: the referenced consultation is in state `SCOPE_APPROVED` before a
    project may be created against it; otherwise `ERR_SCOPE_NOT_APPROVED`, HTTP 409."
    PRD §3.2: "Creation is refused with `ERR_SCOPE_NOT_APPROVED` unless the named
    consultation is in `SCOPE_APPROVED`, and refused with `ERR_DUPLICATE_ACTIVE_PROJECT` if
    any other project on that same property sits in a `workflow_state` other than `CLOSED`."

    Design: Corner/validations/project_creation_against_unapproved_scope_rejected
    """
    ctx = setup_consultation_two_scope_items()
    validate_success(api.submit_scope(
        ctx["cons_id"], {"recommended_tier_code": "SIGNATURE"}, COORD))

    resp = api.create_project(
        {"property_id": ctx["prop_id"], "consultation_id": ctx["cons_id"],
         "listing_id": ctx["listing_id"], "package_tier_id": ctx["tier_sig"],
         "payer_client_id": ctx["seller_id"], "payer_type": "SELLER"}, COORD)

    validate_error(resp, ApiErrorId.ERR_SCOPE_NOT_APPROVED.value, 409)
    data = validate_success(api.get_consultation(ctx["cons_id"], COORD))
    assert data["state"] == "SCOPE_SUBMITTED"
    listed = validate_success(api.list_projects(COORD))
    assert listed == [], "a refused creation must leave no project row behind"


def test_scope_revision_loop_returns_to_drafted_and_counts_the_revision(api):
    """PRD §3.1: "From `SCOPE_REJECTED`, adding another scope item walks the consultation
    back to `SCOPE_DRAFTED` and increments `revision_count`; the loop `SCOPE_DRAFTED →
    SCOPE_SUBMITTED → SCOPE_REJECTED → SCOPE_DRAFTED` may repeat without limit, and
    `revision_count` records how deep it has gone."
    PRD §3.1: "Rejection moves `SCOPE_SUBMITTED → SCOPE_REJECTED` and may carry a
    `rejection_note`."

    Design: Difficulty/non_linear_state_machine/consultation_revision_loop_increments_revision_count
    """
    ctx = setup_consultation_two_scope_items()
    agent = make_listing_agent_headers(ctx["agent_id"])
    validate_success(api.submit_scope(
        ctx["cons_id"], {"recommended_tier_code": "SIGNATURE"}, COORD))
    validate_success(api.reject_scope(
        ctx["cons_id"], {"rejection_note": "Swap the sofa"}, agent))

    resp = api.add_scope_item(
        ctx["cons_id"],
        {"room_label": "Dining", "action": "PACKAGE_ROOM", "requires_rental": True,
         "accessory_set_count": 0}, COORD)

    validate_success(resp, 201)
    data = validate_success(api.get_consultation(ctx["cons_id"], COORD))
    assert data["state"] == "SCOPE_DRAFTED"
    assert data["revision_count"] == 1
    assert data["scoped_room_count"] == 3


def test_second_pass_of_the_scope_loop_reaches_approval_and_scopes_the_property(api):
    """PRD §3.1: "From `SCOPE_REJECTED`, adding another scope item walks the consultation
    back to `SCOPE_DRAFTED` and increments `revision_count`; the loop `SCOPE_DRAFTED →
    SCOPE_SUBMITTED → SCOPE_REJECTED → SCOPE_DRAFTED` may repeat without limit, and
    `revision_count` records how deep it has gone."
    PRD §3.1: "Approval moves `SCOPE_SUBMITTED → SCOPE_APPROVED` and, as its cross-entity
    effect, drives the property to `SCOPED`; the approver must be either the listing agent
    of a listing on that property or the property's own owner."

    Design: Difficulty/non_linear_state_machine/consultation_revision_loop_increments_revision_count
    """
    ctx = setup_consultation_two_scope_items()
    agent = make_listing_agent_headers(ctx["agent_id"])
    validate_success(api.submit_scope(
        ctx["cons_id"], {"recommended_tier_code": "SIGNATURE"}, COORD))
    validate_success(api.reject_scope(
        ctx["cons_id"], {"rejection_note": "Swap the sofa"}, agent))
    validate_success(api.add_scope_item(
        ctx["cons_id"],
        {"room_label": "Dining", "action": "PACKAGE_ROOM", "requires_rental": True,
         "accessory_set_count": 0}, COORD), 201)
    validate_success(api.submit_scope(
        ctx["cons_id"], {"recommended_tier_code": "SIGNATURE"}, COORD))

    resp = api.approve_scope(ctx["cons_id"], agent)

    data = validate_success(resp)
    assert data["state"] == "SCOPE_APPROVED"
    assert data["revision_count"] == 1
    assert data["scoped_room_count"] == 3
    prop = validate_success(api.get_property(ctx["prop_id"], COORD))
    assert prop["prep_state"] == "SCOPED"


def test_cancelling_a_consultation_from_scheduled_returns_the_property_to_new(api):
    """PRD §3.1: "Abandoning a consultation from `SCHEDULED`, `HELD`, `SCOPE_DRAFTED` or
    `SCOPE_REJECTED` moves it to `CANCELLED` and, when no other live consultation remains
    on that property, returns the property to `NEW`."

    Design: Corner/state_machines/cancelled_consultation_is_terminal_and_blocks_scope_writes
    """
    ctx = setup_listing_active()

    resp = api.cancel_consultation(ctx["cons_id"], ADMIN)

    data = validate_success(resp)
    assert data["state"] == "CANCELLED"
    prop = validate_success(api.get_property(ctx["prop_id"], COORD))
    assert prop["prep_state"] == "NEW"
