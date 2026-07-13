"""Admission preferences: verify/deny/revoke and the denormalized total_points."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    fixtures,
)
from test_helpers.fixtures import (
    create_applicant, create_waitlist, enroll, claim_preference, verify_claim,
)

IC = TEST_USERS["intake_clerk_headers"]


def _entry_total_points(api, waitlist_id, entry_id):
    data, _meta = validate_paginated(api.list_entries(waitlist_id, IC))
    match = [e for e in data if e["id"] == entry_id]
    assert match, f"entry {entry_id} not found on waitlist {waitlist_id}"
    return match[0]["total_points"]


def test_verify_veteran_claim_adds_50_points(api):
    """PRD §3.2: "a VETERAN preference is worth 50 points". PRD §3.2: "The
    total_points on every one of that applicant's waitlist entries is the sum of
    points_awarded over the applicant's VERIFIED claims ... and this figure is
    recomputed on the applicant's waitlist entries at the moment the claim is verified."

    Design: Difficulty/compensating_invariant/preference_verify_revoke_conserves_points
    """
    app = create_applicant(api, "Cons2")
    wl = create_waitlist(api, bedroom_size=2)
    entry = enroll(api, wl["id"], app["id"])
    claim = claim_preference(api, app["id"], "VETERAN")
    verify_claim(api, claim["id"], "VERIFY")
    assert _entry_total_points(api, wl["id"], entry["id"]) == 50, \
        "verifying a VETERAN claim must add 50 to the entry total_points"


def test_revoke_veteran_claim_conserves_points_to_zero(api):
    """PRD §3.2: "revoking returns a VERIFIED claim to CLAIMED, resets its
    points_awarded back to 0, and recomputes total_points on each of the
    applicant's waitlist entries so the removed points are subtracted."

    Design: Difficulty/compensating_invariant/preference_verify_revoke_conserves_points
    """
    app = create_applicant(api, "Cons2b")
    wl = create_waitlist(api, bedroom_size=2)
    entry = enroll(api, wl["id"], app["id"])
    claim = claim_preference(api, app["id"], "VETERAN")
    verify_claim(api, claim["id"], "VERIFY")
    assert _entry_total_points(api, wl["id"], entry["id"]) == 50

    revoked = get_success_data(api.revoke_preference_claim(claim["id"], IC))
    assert revoked["status"] == "CLAIMED", f"revoke returns claim to CLAIMED, got {revoked['status']}"
    assert revoked["points_awarded"] == 0, "revoke resets points_awarded to 0"
    assert _entry_total_points(api, wl["id"], entry["id"]) == 0, \
        "after revoke the entry total_points must return to 0 with no drift"


def test_denied_claim_contributes_zero_points(api):
    """PRD §3.2: "A decision to deny moves a CLAIMED claim to DENIED and leaves
    points_awarded at 0." PRD §3.2: "claims in CLAIMED or DENIED contribute nothing".

    Design: Corner/calculations/total_points_excludes_denied_claim
    """
    app = create_applicant(api, "Calc1")
    wl = create_waitlist(api, bedroom_size=2)
    entry = enroll(api, wl["id"], app["id"])
    claim = claim_preference(api, app["id"], "VETERAN")
    denied = get_success_data(api.verify_preference_claim(claim["id"], {"decision": "DENY"}, IC))
    assert denied["status"] == "DENIED"
    assert denied["points_awarded"] == 0
    assert _entry_total_points(api, wl["id"], entry["id"]) == 0, \
        "a DENIED claim must not contribute points"


def test_verify_already_verified_claim_rejected(api):
    """PRD §3.2: "Only a claim currently in CLAIMED may be verified or denied;
    acting on a claim in any other state is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/verify_already_verified_claim_rejected
    """
    app = create_applicant(api, "SM1")
    claim = claim_preference(api, app["id"], "VETERAN")
    verify_claim(api, claim["id"], "VERIFY")
    resp = api.verify_preference_claim(claim["id"], {"decision": "VERIFY"}, IC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
