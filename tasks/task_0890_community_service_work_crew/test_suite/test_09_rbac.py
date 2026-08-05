"""Role-based access control: authentication, peer-role authorization, and entity-backed
ownership on waivers and check-in.

Covers Corner queue instances under section `rbac`.
"""
from test_helpers import (
    validate_error,
    make_participant_headers, make_supervisor_headers,
    create_participant_payload,
    TEST_USERS,
)
from test_helpers import fixtures as fx

CLERK = TEST_USERS["clerk_headers"]


def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the caller, and
    `X-User-Role`, naming the caller's role. If either header is missing, or if
    `X-User-Role` is not one of the four roles defined below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    res = api.create_participant(create_participant_payload(full_name="No Auth"), headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", 401)


def test_courtclerk_cannot_create_site_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the role (or, where applicable, the specific identity)
    is not permitted to perform the operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 (POST /sites): authorized role is ProgramCoordinator only.

    Design: Corner/rbac/courtclerk_cannot_create_site_unauthorized
    """
    from test_helpers import create_site_payload
    res = api.create_site(create_site_payload(name="Bad"), CLERK)
    validate_error(res, "ERR_UNAUTHORIZED", 403)


def test_participant_cannot_sign_other_participants_waiver(api):
    """PRD §3.3: "Signing is reserved to the `Participant` who owns the placement's referral".
    PRD §2.1: "ownership checks compare the `participant_id` of the referral behind a placement or
    conversion to `X-User-ID`."

    Design: Corner/rbac/participant_cannot_sign_other_participants_waiver
    """
    site = fx.new_site()
    sup = fx.new_supervisor(site["id"])
    p1 = fx.new_participant(full_name="P One", email="p1@example.org")
    p2 = fx.new_participant(full_name="P Two", email="p2@example.org")
    ref = fx.new_referral(p1["id"], court_case_number="CR-D15")
    plc = fx.new_placement(ref["id"], site["id"], sup["id"])
    res = api.sign_waiver(plc["id"], {"signature_name": "Wrong Person"},
                          make_participant_headers(p2["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", 403)


def test_unassigned_supervisor_cannot_checkin(api):
    """PRD §3.5: "check-in, check-out, and verify all require the acting `SiteSupervisor`'s `X-User-ID` to
    equal the placement's `supervisor_id`, else `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/unassigned_supervisor_cannot_checkin
    """
    base = fx.accepting_site_with_supervisor()
    site_id = base["site"]["id"]
    sup1 = base["supervisor"]["id"]
    sup2 = fx.new_supervisor(site_id, full_name="S Two")
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], court_case_number="CR-D16")
    plc = fx.new_placement(ref["id"], site_id, sup1)
    fx.sign_waiver(plc["id"], part["id"])
    fx.activate_placement(plc["id"])
    ws = fx.new_session(plc["id"], "2026-06-05T09:00:00Z", "2026-06-05T11:00:00Z")
    res = api.check_in(ws["id"], make_supervisor_headers(sup2["id"]),
                       {"check_in_at": "2026-06-05T09:00:00Z"})
    validate_error(res, "ERR_UNAUTHORIZED", 403)
