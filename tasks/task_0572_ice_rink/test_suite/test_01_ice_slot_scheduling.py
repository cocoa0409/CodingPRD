"""Ice-slot lifecycle: publish/unpublish cycle, resurface-buffer overlap,
cancel of empty slots, and the state/precondition guards on the transitions."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_rink, create_slot, create_published_slot, publish_slot, get_slot,
    setup_public_slot, admit, create_funded_skater,
)

RM = TEST_USERS["rink_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/ice_slot_draft_scheduled_cycle
# ---------------------------------------------------------------------------
def test_ice_slot_publish_unpublish_publish_ends_scheduled(api):
    """PRD §3.1: "Unpublishing reverses a slot from `SCHEDULED` back to `DRAFT`
    — the schedule is deliberately cyclic between these two states."
    PRD §3.1: "A successful publish sets `status` to `SCHEDULED` and increments
    `version`."

    Design: Difficulty/non_linear_state_machine/ice_slot_draft_scheduled_cycle
    """
    rink = create_rink(api)
    slot = create_slot(api, rink["id"], "PUBLIC_SKATE",
                       "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    validate_success(api.publish_ice_slot(slot["id"], RM))
    validate_success(api.unpublish_ice_slot(slot["id"], RM))
    data = validate_success(api.publish_ice_slot(slot["id"], RM))
    assert data["status"] == "SCHEDULED", f"expected SCHEDULED, got {data['status']}"


def test_ice_slot_cycle_increments_version_each_transition(api):
    """PRD §2.5: "`version` — an integer that starts at creation and increments by
    one on every mutation of the resource."
    PRD §3.1: "A successful publish sets `status` to `SCHEDULED` and increments
    `version`."

    Design: Difficulty/non_linear_state_machine/ice_slot_draft_scheduled_cycle
    """
    rink = create_rink(api)
    slot = create_slot(api, rink["id"], "PUBLIC_SKATE",
                       "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    base_version = slot["version"]
    validate_success(api.publish_ice_slot(slot["id"], RM))
    validate_success(api.unpublish_ice_slot(slot["id"], RM))
    data = validate_success(api.publish_ice_slot(slot["id"], RM))
    # three mutations (publish, unpublish, publish) => +3 over the created version
    assert data["version"] == base_version + 3, (
        f"expected version {base_version + 3} after 3 transitions, got {data['version']}")


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/ice_slot_resurface_buffer_overlap
# ---------------------------------------------------------------------------
def test_publish_within_resurface_buffer_rejected(api):
    """PRD §3.1: "take that slot's window and widen it by `resurface_buffer_minutes`
    on each side; the candidate slot's own `[start_utc, end_utc)` window must not
    overlap any such widened window."
    PRD §3.1: "Any tighter spacing is a collision, rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/ice_slot_resurface_buffer_overlap
    """
    rink = create_rink(api, resurface_buffer_minutes=15)
    create_published_slot(api, rink["id"], "PUBLIC_SKATE",
                          "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    # Second slot starts 10 min after the first ends (< 15 min buffer) -> collision.
    near = create_slot(api, rink["id"], "PUBLIC_SKATE",
                       "2026-06-10T09:10:00Z", "2026-06-10T10:10:00Z")
    validate_error(api.publish_ice_slot(near["id"], RM), ApiErrorId.ERR_SLOT_OVERLAP.value)


def test_publish_adjacent_at_exact_buffer_allowed(api):
    """PRD §3.1: "A gap exactly equal to the buffer is permitted: adjacency where
    the untouched slots are separated by precisely the buffer does not overlap and
    is allowed."

    Design: Difficulty/resource_temporal_overlap/ice_slot_resurface_buffer_overlap
    """
    rink = create_rink(api, resurface_buffer_minutes=15)
    create_published_slot(api, rink["id"], "PUBLIC_SKATE",
                          "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    # Second slot starts exactly 15 min after the first ends (gap == buffer) -> allowed.
    adj = create_slot(api, rink["id"], "PUBLIC_SKATE",
                      "2026-06-10T09:15:00Z", "2026-06-10T10:15:00Z")
    data = validate_success(api.publish_ice_slot(adj["id"], RM))
    assert data["status"] == "SCHEDULED", f"adjacency should publish, got {data['status']}"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/cancel_slot_with_empty_children_no_op
# ---------------------------------------------------------------------------
def test_cancel_scheduled_slot_with_no_children_succeeds(api):
    """PRD §3.1: "Cancellation carries no precondition — a scheduled slot may
    always be cancelled."

    Design: Difficulty/boundary_precision_check/cancel_slot_with_empty_children_no_op
    """
    setup = setup_public_slot(api, published=True, public_skate_capacity=2,
                              public_skate_fee_cents=1500, rental_skate_count=5)
    data = validate_success(api.cancel_ice_slot(setup["slot"]["id"], RM))
    assert data["status"] == "CANCELLED", f"expected CANCELLED, got {data['status']}"


def test_cancel_empty_public_slot_leaves_rental_inventory_intact(api):
    """PRD §3.2: "the rink's `available_rental_skates` equals `rental_skate_count`
    minus the number of `ADMITTED` admissions across all of the rink's slots that
    carry `rental_skate` set to true."

    Design: Difficulty/boundary_precision_check/cancel_slot_with_empty_children_no_op
    """
    setup = setup_public_slot(api, published=True, public_skate_capacity=2,
                              public_skate_fee_cents=1500, rental_skate_count=5)
    validate_success(api.cancel_ice_slot(setup["slot"]["id"], RM))
    rink = validate_success(api.get_rink(setup["rink"]["id"], RM))
    assert rink["available_rental_skates"] == 5, (
        f"no admissions existed; expected 5 free skates, got {rink['available_rental_skates']}")


# ---------------------------------------------------------------------------
# Corner/state_machines/publish_already_scheduled_returns_invalid_state
# ---------------------------------------------------------------------------
def test_publish_already_scheduled_slot_rejected(api):
    """PRD §3.1: "Publishing a slot advances it from `DRAFT` to `SCHEDULED`".
    PRD §2.9: "State — the target resource is in a state that permits the requested
    transition, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/publish_already_scheduled_returns_invalid_state
    """
    setup = setup_public_slot(api, published=True)
    validate_error(api.publish_ice_slot(setup["slot"]["id"], RM),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/cancel_terminal_slot_returns_invalid_state
# ---------------------------------------------------------------------------
def test_cancel_already_cancelled_slot_rejected(api):
    """PRD §2.9: "State — the target resource is in a state that permits the
    requested transition, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/cancel_terminal_slot_returns_invalid_state
    """
    setup = setup_public_slot(api, published=True)
    validate_success(api.cancel_ice_slot(setup["slot"]["id"], RM))
    validate_error(api.cancel_ice_slot(setup["slot"]["id"], RM),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/unpublish_with_active_admission_returns_invalid_state
# ---------------------------------------------------------------------------
def test_unpublish_slot_with_admitted_skater_rejected(api):
    """PRD §3.1: "there must be zero `PublicSkateAdmission` in `ADMITTED` status,
    zero non-terminal `LearnToSkateClass`, and zero `SlotBooking` in `BOOKED`
    status referencing this slot. If any such child exists, the transition is
    rejected with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/unpublish_with_active_admission_returns_invalid_state
    """
    setup = setup_public_slot(api, published=True, public_skate_capacity=5,
                              public_skate_fee_cents=0)
    sk = create_funded_skater(api, "unpub@x.com", 0)
    admit(api, setup["slot"]["id"], sk["id"])
    validate_error(api.unpublish_ice_slot(setup["slot"]["id"], RM),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/complete_slot_before_end_time_returns_invalid_state
# ---------------------------------------------------------------------------
def test_complete_slot_before_end_time_rejected(api):
    """PRD §3.1: "Completing a slot moves it from `SCHEDULED` to `COMPLETED`, and
    is gated on time: the logical clock must have reached or passed the slot's
    `end_utc`, else the request is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complete_slot_before_end_time_returns_invalid_state
    """
    # Clock left at the startup default 2026-05-01, which precedes the slot end.
    setup = setup_public_slot(api, published=True)
    validate_error(api.complete_ice_slot(setup["slot"]["id"], RM),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner/entities/ice_slot_missing_required_purpose_returns_invalid_request
# ---------------------------------------------------------------------------
def test_create_ice_slot_missing_purpose_rejected(api):
    """PRD §2.9: "Field-level validity — required fields present, enums valid, end
    after start, non-negative amounts, and pagination within range, else
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/ice_slot_missing_required_purpose_returns_invalid_request
    """
    rink = create_rink(api)
    resp = api.create_ice_slot(
        {"rink_id": rink["id"], "start_utc": "2026-06-10T08:00:00Z",
         "end_utc": "2026-06-10T09:00:00Z"}, RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner/entities/ice_slot_end_before_start_returns_invalid_request
# ---------------------------------------------------------------------------
def test_create_ice_slot_end_before_start_rejected(api):
    """PRD §3.1: "`start_utc` (inclusive) and `end_utc` (exclusive) bound the
    block of ice; `end_utc` must be strictly after `start_utc` or the create is
    malformed."

    Design: Corner/entities/ice_slot_end_before_start_returns_invalid_request
    """
    rink = create_rink(api)
    resp = api.create_ice_slot(
        {"rink_id": rink["id"], "purpose": "PUBLIC_SKATE",
         "start_utc": "2026-06-10T09:00:00Z", "end_utc": "2026-06-10T08:00:00Z"}, RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
