"""Security and RBAC: missing auth, unauthorized role, OCC stale-version on
finalize-seating."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_wedding_payload,
    create_guest_payload,
    create_meal_option_payload,
    create_seating_assignment_payload,
    create_table_payload,
    make_couple_headers,
    make_platform_integration_headers,
    make_guest_self_headers,
    set_clock,
    bootstrap_wedding_in_rsvp_open,
)


# ─────────────────────────────────────────────────────────────────────────────
# Corner / rbac / platform_integration_cannot_create_wedding
# ─────────────────────────────────────────────────────────────────────────────

def test_platform_integration_cannot_create_wedding(api):
    """PRD §2.1: "When the caller's role is well-formed but the role itself
    is not authorized for the target endpoint per the role matrix in §4,
    the rejection is `ERR_FORBIDDEN` (HTTP 403)".
    PRD §4 endpoint table: `POST /weddings` lists only `Couple` as the
    authorized role.

    Design: Corner/rbac/platform_integration_cannot_create_wedding
    """
    payload = create_wedding_payload(
        couple_user_id="couple_x", title="X Wedding",
        ceremony_at="2027-06-01T18:00:00Z",
        rsvp_deadline_at="2027-05-15T23:59:59Z",
    )
    headers = make_platform_integration_headers()
    res = api.create_wedding(payload, headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_guest_self_cannot_create_other_guest(api):
    """PRD §2.1: "When the caller's role is well-formed but the role itself
    is not authorized for the target endpoint per the role matrix in §4,
    the rejection is `ERR_FORBIDDEN` (HTTP 403)".
    PRD §4 endpoint table: `POST /weddings/{id}/guests` lists only `Couple`.

    Design: Corner/rbac/guest_self_cannot_create_other_guest
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding, _meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_gs")
    couple = make_couple_headers("couple_gs")
    g_authn = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Authn", email="authn@example.com"),
        couple,
    ), expected_status=201)

    self_headers = make_guest_self_headers(g_authn["id"], g_authn["invitation_token"])
    res = api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Sneaky", email="sneaky@example.com"),
        self_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two mandatory HTTP
    headers identifying the caller: `X-User-ID` to identify the acting
    principal and `X-User-Role` to specify their operational capacity.
    Requests missing either header, or carrying values that fail
    well-formedness checks, are rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."
    PRD §2.1: "In addition, `GuestSelf` requests must carry an
    `X-Invitation-Token` header whose value matches the
    `Guest.invitation_token` minted by the server when the guest was first
    added; a missing or mismatched token is itself `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_au")
    couple = make_couple_headers("couple_au")
    g = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Auth", email="auth@example.com"),
        couple,
    ), expected_status=201)

    # GuestSelf headers without an invitation token → ERR_UNAUTHENTICATED.
    bad_headers = {"X-User-ID": g["id"], "X-User-Role": "GuestSelf"}
    res = api.guest_rsvp(
        g["id"], {"attending": True, "meal_option_id": meal["id"]}, bad_headers,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


# ─────────────────────────────────────────────────────────────────────────────
# OCC on finalize-seating: exercise the stale-version path by deterministically
# bumping wedding.version (auto-seat commit, which PRD §3.3 says bumps version)
# and then submitting finalize-seating with the pre-bump version.
# ─────────────────────────────────────────────────────────────────────────────

def test_finalize_seating_with_stale_wedding_version_returns_412(api):
    """PRD §2.8: "Finalizing a wedding's seating plan requires a non-optional
    `expected_wedding_version` field in the request body. The server compares
    it to the target `Wedding`'s current `version`; on mismatch the request
    is rejected with `ERR_STALE_VERSION`."
    PRD §3.3: "the committing variant — a write-style call — requires the
    wedding's `status` to be either `RSVP_CLOSED` or `SEATED` ... on commit,
    the wedding's `version` advances by 1 and `seating_dirty` is left set
    to true so the couple still has to explicitly finalize."

    Design: Corner/state_machines/error_stale_version_on_finalize_seating
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_st")
    couple = make_couple_headers("couple_st")

    # Build minimal seating so finalize would otherwise pass: 1 ATTENDING guest,
    # 1 Table, manual SeatingAssignment.
    table = validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=1, capacity=2),
        couple,
    ), expected_status=201)
    g = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(full_name="Stay", email="stay@example.com"),
        couple,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        g["id"], {"attending": True, "meal_option_id": meal["id"]}, couple,
    ), expected_status=200)
    closed = validate_success(api.close_rsvp(wedding["id"], couple), expected_status=200)
    validate_success(api.create_seating_assignment(
        create_seating_assignment_payload(
            wedding["id"], table["id"], "GUEST", g["id"],
        ),
        couple,
    ), expected_status=201)

    pre = validate_success(api.get_wedding(wedding["id"], couple), expected_status=200)
    stale_version = pre["version"]
    # auto-seat commit deterministically bumps wedding.version per PRD §3.3.
    validate_success(api.auto_seat_commit(wedding["id"], couple), expected_status=200)

    res = api.finalize_seating(wedding["id"], stale_version, couple)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    after = validate_success(api.get_wedding(wedding["id"], couple), expected_status=200)
    assert after["status"] == "RSVP_CLOSED", "wedding must remain RSVP_CLOSED"
