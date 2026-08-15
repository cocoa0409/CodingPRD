"""Rights grants: windows, exclusive overlap geometry, and the computed posture."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_asset, create_rights_grant, get_asset, set_clock,
    TEST_USERS,
)

ARCHIVIST = TEST_USERS["archivist_lead_headers"]
RIGHTS = TEST_USERS["rights_manager_headers"]


def test_rights_posture_precedence_and_end_exclusive_expiry(api):
    """PRD §3.3: "Otherwise, if at least one effective grant carries an empty
    `restriction_flags` list, the posture is `CLEARED` — `CLEARED` beats `RESTRICTED`
    whenever even one unrestricted effective grant exists. Only when every effective
    grant carries at least one restriction flag is the posture `RESTRICTED`."
    PRD §3.3: "If the effective set is empty, the posture is `EXPIRED`."
    PRD §3.3: "`REVOKED` grants are excluded, and a grant whose `window_end` equals now
    is already outside its window."

    Design: Corner/calculations/rights_posture_precedence_and_end_exclusive_expiry
    """
    asset = create_asset()
    g1 = create_rights_grant(asset["id"], window_start="2026-01-01T00:00:00Z",
                             window_end="2026-09-01T00:00:00Z")
    create_rights_grant(asset["id"], grant_type="STREAMING",
                        window_start="2026-01-01T00:00:00Z",
                        window_end="2026-09-01T00:00:00Z",
                        restriction_flags=["NO_RERUN"])

    p1 = get_asset(asset["id"])["rights_posture"]
    assert p1 == "CLEARED", "one unrestricted effective grant must win over a restricted one"

    validate_success(api.revoke_rights_grant(g1["id"], RIGHTS), 200)
    p2 = get_asset(asset["id"])["rights_posture"]
    assert p2 == "RESTRICTED", "only a restriction-flagged grant remains effective"

    set_clock("2026-09-01T00:00:00Z")
    p3 = get_asset(asset["id"])["rights_posture"]
    assert p3 == "EXPIRED", "window_end == now is outside the window (end-exclusive)"


def test_grant_window_in_past_rejected(api):
    """PRD §3.3: "it must reach into the future: a grant whose `window_end` is at or
    before the current logical time is rejected with `ERR_RIGHTS_WINDOW_PAST` (HTTP 422)."

    Design: Corner/errors/grant_window_in_past_rejected
    """
    asset = create_asset()
    res = api.create_rights_grant(
        {"asset_id": asset["id"], "grant_type": "BROADCAST", "territory": "DOMESTIC",
         "window_start": "2025-01-01T00:00:00Z", "window_end": "2026-01-01T00:00:00Z"},
        RIGHTS)
    validate_error(res, ApiErrorId.ERR_RIGHTS_WINDOW_PAST)


def test_exclusive_grant_overlap_rejected_adjacency_allowed(api):
    """PRD §3.3: "When `exclusive` is true, creation is rejected with
    `ERR_EXCLUSIVE_GRANT_OVERLAP` (HTTP 422) if any other `ACTIVE` exclusive grant
    exists for the same asset with the same `grant_type` and `territory` whose window
    intersects the new one."
    PRD §3.3: "the windows conflict only when the new window starts strictly before the
    existing window's end and the existing window starts strictly before the new
    window's end, so a new window beginning exactly at the existing window's end is
    adjacency, not conflict, and is allowed."

    Design: Difficulty/resource_temporal_overlap/exclusive_rights_grant_half_open_overlap
    """
    asset = create_asset()
    create_rights_grant(asset["id"], window_start="2026-01-01T00:00:00Z",
                        window_end="2027-01-01T00:00:00Z", exclusive=True)

    res = api.create_rights_grant(
        {"asset_id": asset["id"], "grant_type": "BROADCAST", "territory": "DOMESTIC",
         "window_start": "2026-06-01T00:00:00Z", "window_end": "2026-12-01T00:00:00Z",
         "exclusive": True}, RIGHTS)
    validate_error(res, ApiErrorId.ERR_EXCLUSIVE_GRANT_OVERLAP)

    adjacent = validate_success(api.create_rights_grant(
        {"asset_id": asset["id"], "grant_type": "BROADCAST", "territory": "DOMESTIC",
         "window_start": "2027-01-01T00:00:00Z", "window_end": "2028-01-01T00:00:00Z",
         "exclusive": True}, RIGHTS), 201)
    assert adjacent["status"] == "ACTIVE"


def test_exclusive_grant_overlap_after_revoke_allowed(api):
    """PRD §3.3: "When `exclusive` is true, creation is rejected with
    `ERR_EXCLUSIVE_GRANT_OVERLAP` (HTTP 422) if any other `ACTIVE` exclusive grant
    exists for the same asset with the same `grant_type` and `territory` whose window
    intersects the new one."
    PRD §3.3: "Revocation moves a grant from `ACTIVE` to the terminal `REVOKED`".

    Design: Difficulty/resource_temporal_overlap/exclusive_rights_grant_half_open_overlap
    """
    asset = create_asset()
    g1 = create_rights_grant(asset["id"], window_start="2026-01-01T00:00:00Z",
                             window_end="2027-01-01T00:00:00Z", exclusive=True)
    validate_success(api.revoke_rights_grant(g1["id"], RIGHTS), 200)

    g2 = validate_success(api.create_rights_grant(
        {"asset_id": asset["id"], "grant_type": "BROADCAST", "territory": "DOMESTIC",
         "window_start": "2026-06-01T00:00:00Z", "window_end": "2026-12-01T00:00:00Z",
         "exclusive": True}, RIGHTS), 201)
    assert g2["status"] == "ACTIVE", (
        "a REVOKED grant is not ACTIVE and must not trigger the overlap rule")


def test_exclusive_overlap_scoped_to_type_and_territory(api):
    """PRD §3.3: "if any other `ACTIVE` exclusive grant exists for the same asset with
    the same `grant_type` and `territory` whose window intersects the new one".

    Design: Corner/errors/exclusive_overlap_scoped_to_type_and_territory
    """
    asset = create_asset()
    create_rights_grant(asset["id"], window_start="2026-01-01T00:00:00Z",
                        window_end="2027-01-01T00:00:00Z", exclusive=True)

    g = validate_success(api.create_rights_grant(
        {"asset_id": asset["id"], "grant_type": "STREAMING", "territory": "DOMESTIC",
         "window_start": "2026-06-01T00:00:00Z", "window_end": "2026-12-01T00:00:00Z",
         "exclusive": True}, RIGHTS), 201)
    assert g["status"] == "ACTIVE", "different grant_type is outside the overlap scope"
