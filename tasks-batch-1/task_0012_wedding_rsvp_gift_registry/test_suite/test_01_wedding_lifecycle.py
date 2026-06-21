"""Wedding lifecycle: creation defaults, state transitions, archive lockdown,
total_capacity recomputation."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_wedding_payload,
    create_meal_option_payload,
    create_table_payload,
    create_guest_payload,
    make_couple_headers,
    set_clock,
    bootstrap_wedding_in_draft,
    bootstrap_wedding_in_rsvp_open,
    bootstrap_archived_wedding,
    assert_wedding,
)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / non_linear_state_machine / registry_item_cyclic_open_fulfilled
# (handled in test_04)
#
# Corner: wedding lifecycle and archive guards live here.
# ─────────────────────────────────────────────────────────────────────────────


def test_wedding_create_minimum_fields_returns_201(api):
    """PRD §3.1: "On create the guest is assigned ..." preceded by:
    "The system records the operator's `couple_user_id` from the request body
    ... The system seeds three derived fields on create: `status` is set to
    `DRAFT`, `seating_dirty` is set to false, and `total_capacity` is set to 0
    (no tables yet)."
    PRD §2.4: "`version` (integer): a counter that starts at 1 on create
    and increments by exactly 1 on every mutation".

    Design: Corner/entities/wedding_create_minimum_fields_returns_201
    """
    set_clock("2027-01-01T00:00:00Z")
    payload = create_wedding_payload(
        couple_user_id="couple_min",
        title="Min Wedding",
        ceremony_at="2027-06-01T18:00:00Z",
        rsvp_deadline_at="2027-05-15T23:59:59Z",
    )
    res = api.create_wedding(payload, make_couple_headers("couple_min"))
    wedding = validate_success(res, expected_status=201)
    assert_wedding(wedding)
    assert wedding["status"] == "DRAFT"
    assert wedding["seating_dirty"] is False
    assert wedding["total_capacity"] == 0
    assert wedding["version"] == 1


def test_wedding_create_missing_title_returns_invalid_request(api):
    """PRD §2.9: "The shape-level `ERR_INVALID_REQUEST` (HTTP 400) — missing
    required field, malformed enum, integer out of range, empty
    `drafted_body` — fires last."

    Design: Corner/entities/wedding_create_missing_title_returns_invalid_request
    """
    payload = {
        "couple_user_id": "couple_nm",
        # title intentionally omitted (PRD §3.1 names it as required input)
        "ceremony_at": "2027-06-01T18:00:00Z",
        "rsvp_deadline_at": "2027-05-15T23:59:59Z",
    }
    res = api.create_wedding(payload, make_couple_headers("couple_nm"))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_open_rsvp_from_rsvp_open_returns_invalid_state(api):
    """PRD §3.1: "Opening RSVPs — transitioning `status` from `DRAFT` to
    `RSVP_OPEN`" — only DRAFT may open. Repeating the open transition violates
    state-machine precondition.
    PRD §2.9: "then state-machine preconditions on the target entity
    (`ERR_INVALID_STATE` at 409)."

    Design: Corner/state_machines/open_rsvp_from_rsvp_open_returns_invalid_state
    """
    wedding, _meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_op")
    res = api.open_rsvp(wedding["id"], make_couple_headers("couple_op"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_archived_wedding_rejects_all_mutations(api):
    """PRD §2.6: "Once a wedding's `status` reaches `ARCHIVED`, every mutation
    against the wedding itself or against any of its descendants is rejected
    with `ERR_WEDDING_ARCHIVED` (HTTP 409): no new RSVPs, no new purchases,
    no new thank-you-note transitions, no new seating edits."

    Design: Corner/state_machines/archived_wedding_rejects_all_mutations
    """
    archived = bootstrap_archived_wedding(
        couple_user_id="couple_ar",
        clock_iso_before="2027-01-01T00:00:00Z",
        clock_iso_after_ceremony="2027-06-02T00:00:00Z",
        ceremony_at="2027-06-01T18:00:00Z",
        rsvp_deadline_at="2027-05-15T23:59:59Z",
    )
    assert archived["status"] == "ARCHIVED"
    res = api.create_guest(
        archived["id"],
        create_guest_payload(full_name="Late", email="late@example.com"),
        make_couple_headers("couple_ar"),
    )
    validate_error(res, ApiErrorId.ERR_WEDDING_ARCHIVED, expected_status=409)


def test_close_rsvp_auto_declines_invited_guests(api):
    """PRD §3.1: "The automatic and the explicit close share an identical
    cascade: every `Guest` still in `INVITED` is auto-transitioned to
    `DECLINED` with their `meal_option_id` cleared to null".

    Design: Corner/state_machines/close_rsvp_auto_declines_invited_guests
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_cls")
    headers = make_couple_headers("couple_cls")

    g_inv = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(full_name="Inv", email="inv@example.com"),
        headers,
    ), expected_status=201)
    g_att = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(full_name="Att", email="att@example.com"),
        headers,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        g_att["id"], {"attending": True, "meal_option_id": meal["id"]}, headers,
    ), expected_status=200)

    validate_success(api.close_rsvp(wedding["id"], headers), expected_status=200)

    inv_after = validate_success(api.get_guest(g_inv["id"], headers), expected_status=200)
    att_after = validate_success(api.get_guest(g_att["id"], headers), expected_status=200)
    assert inv_after["rsvp_status"] == "DECLINED"
    assert inv_after.get("meal_option_id") is None
    assert att_after["rsvp_status"] == "ATTENDING"


def test_derived_field_total_capacity_recomputed(api):
    """PRD §3.1: "Adding a table refreshes `total_capacity` to the sum of every
    table's `capacity` and advances the wedding's `version` by 1."

    Design: Corner/cross_cutting/derived_field_total_capacity_recomputed
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding = bootstrap_wedding_in_draft(couple_user_id="couple_tc")
    headers = make_couple_headers("couple_tc")
    assert wedding["total_capacity"] == 0

    validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=1, capacity=4), headers,
    ), expected_status=201)
    validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=2, capacity=6), headers,
    ), expected_status=201)

    after = validate_success(api.get_wedding(wedding["id"], headers), expected_status=200)
    assert after["total_capacity"] == 10
