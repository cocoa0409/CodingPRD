"""Entity creation: defaults and server-minted system fields."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_guest_payload,
    create_plus_one_payload,
    make_couple_headers,
    set_clock,
    bootstrap_wedding_in_draft,
)


# ─────────────────────────────────────────────────────────────────────────────
# Corner / entities / guest_create_default_plus_one_allowed_false
# ─────────────────────────────────────────────────────────────────────────────

def test_guest_create_default_plus_one_allowed_false(api):
    """PRD §3.1: "Guests are added one at a time with `full_name`, `email`
    (case-insensitively unique within the wedding), an `is_child` flag
    (defaulting to false), and a `plus_one_allowed` flag (defaulting to
    false)".
    PRD §3.2: "The system enforces a one-shot rule via the priority-ordered
    checks of §2.9: the parent guest's `plus_one_allowed` must currently be
    true, and the guest must not already have a `PlusOne`; either violation
    is rejected with `ERR_PLUS_ONE_NOT_ALLOWED` (HTTP 422)."

    Design: Corner/entities/guest_create_default_plus_one_allowed_false
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding = bootstrap_wedding_in_draft(couple_user_id="couple_def")
    couple = make_couple_headers("couple_def")
    guest = validate_success(api.create_guest(
        wedding["id"],
        {"full_name": "Default", "email": "default@example.com"},
        couple,
    ), expected_status=201)
    assert guest["plus_one_allowed"] is False

    res = api.create_plus_one(
        guest["id"], create_plus_one_payload(full_name="Should Fail"), couple,
    )
    validate_error(res, ApiErrorId.ERR_PLUS_ONE_NOT_ALLOWED, expected_status=422)


# ─────────────────────────────────────────────────────────────────────────────
# Corner / entities / guest_invitation_token_server_minted
# ─────────────────────────────────────────────────────────────────────────────

def test_guest_invitation_token_server_minted(api):
    """PRD §3.1: "on create the guest is assigned `rsvp_status` of `INVITED`,
    the server mints an opaque `invitation_token` used later for `GuestSelf`
    authentication, and `meal_option_id` is left null."

    Design: Corner/entities/guest_invitation_token_server_minted
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding = bootstrap_wedding_in_draft(couple_user_id="couple_tok")
    couple = make_couple_headers("couple_tok")
    guest = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Tok", email="tok@example.com"),
        couple,
    ), expected_status=201)
    token = guest.get("invitation_token")
    assert isinstance(token, str) and len(token) > 0, (
        f"invitation_token must be a non-empty server-minted string, got {token!r}"
    )
