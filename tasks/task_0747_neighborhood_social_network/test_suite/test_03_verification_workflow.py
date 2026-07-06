"""VerificationRequest lifecycle, membership, resubmission cycle, expiry."""
import pytest

from test_helpers import (
    get_success_data, validate_error,
    make_resident_headers, make_moderator_headers,
    setup_neighborhood_with_moderator, create_resident, fetch_pending_verification,
    approve_verification, promote_to_moderator,
    set_clock, api_client, ADMIN,
)


class TestVerificationRequestCycle:
    """Difficulty rule 3 — cyclic state machine on VerificationRequest."""

    def test_cycle_in_review_and_resubmission_required_reenters_in_review(self, api):
        """PRD §3.1: "Requesting resubmission advances the state to
        `RESUBMISSION_REQUIRED` and is the sole cyclic path in the flow: from
        `RESUBMISSION_REQUIRED`, the resident named on the request (their id
        must equal the request's `resident_id`) may resubmit with a fresh
        `proof_reference` (optionally changing `proof_type`) so long as the
        clock is still before `expires_at`, and the request re-enters
        `IN_REVIEW`; a request can cycle `IN_REVIEW → RESUBMISSION_REQUIRED →
        IN_REVIEW` as many times as the review demands until the window closes."

        Design: Difficulty/non_linear_state_machine/verification_request_cycles_in_review_and_resubmission_required
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod = setup_neighborhood_with_moderator()
        r5 = create_resident(n["id"], email="r5@x.com", display_name="R5",
                             home_address_line="9 A St")
        vr5 = fetch_pending_verification(r5["id"])
        mod_headers = make_moderator_headers(mod["id"])
        get_success_data(api_client.claim_verification_request(vr5["id"], mod_headers))
        get_success_data(api_client.request_resubmission(vr5["id"], mod_headers))
        # Now resubmit as the resident.
        result = get_success_data(api_client.resubmit_verification(
            vr5["id"], {"proof_reference": "proof-v2"},
            make_resident_headers(r5["id"]),
        ))
        assert result["state"] == "IN_REVIEW", \
            f"Expected IN_REVIEW after resubmit, got {result['state']}"
        assert result["proof_reference"] == "proof-v2"

    def test_resubmit_from_resubmission_required_updates_proof_reference(self, api):
        """PRD §3.1: "from `RESUBMISSION_REQUIRED`, the resident named on the
        request (their id must equal the request's `resident_id`) may resubmit
        with a fresh `proof_reference` (optionally changing `proof_type`) so
        long as the clock is still before `expires_at`, and the request
        re-enters `IN_REVIEW`."

        Design: Difficulty/non_linear_state_machine/verification_request_cycles_in_review_and_resubmission_required
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod = setup_neighborhood_with_moderator()
        r = create_resident(n["id"], email="rc@x.com", display_name="RC",
                            home_address_line="10 A St")
        vr = fetch_pending_verification(r["id"])
        mod_headers = make_moderator_headers(mod["id"])
        get_success_data(api_client.claim_verification_request(vr["id"], mod_headers))
        get_success_data(api_client.request_resubmission(vr["id"], mod_headers))
        # Second cycle: request-resubmission again.
        result = get_success_data(api_client.resubmit_verification(
            vr["id"], {"proof_reference": "proof-v2"},
            make_resident_headers(r["id"]),
        ))
        assert result["state"] == "IN_REVIEW"
        # Cycle again: request another resubmission.
        get_success_data(api_client.request_resubmission(vr["id"], mod_headers))
        result3 = get_success_data(api_client.resubmit_verification(
            vr["id"], {"proof_reference": "proof-v3"},
            make_resident_headers(r["id"]),
        ))
        assert result3["state"] == "IN_REVIEW", "Second cycle must return to IN_REVIEW"
        assert result3["proof_reference"] == "proof-v3"


class TestVerificationExpiryAutoTransition:
    """Corner: clock advance past expires_at auto-transitions SUBMITTED->EXPIRED."""

    def test_clock_past_expires_at_fires_submitted_to_expired(self, api):
        """PRD §3.1: "if the logical clock reaches or passes `expires_at`
        while the request is still `SUBMITTED`, the system auto-transitions
        the request to `EXPIRED` and sets the resident's `verification_status`
        to `REJECTED` — the terminal states of the machine are `APPROVED`,
        `REJECTED`, and `EXPIRED`."

        Design: Corner/state_machines/verification_expiry_auto_transition_on_clock_advance
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod = setup_neighborhood_with_moderator()
        r = create_resident(n["id"], email="rx@x.com", display_name="RX",
                            home_address_line="11 A St")
        vr = fetch_pending_verification(r["id"])
        # Advance well past submitted_at + 14 days.
        set_clock("2026-06-20T00:00:00Z")
        vr_now = get_success_data(api_client.get_verification_request(vr["id"], ADMIN))
        assert vr_now["state"] == "EXPIRED", \
            f"Expected EXPIRED after clock advance, got {vr_now['state']}"
        r_now = get_success_data(api_client.get_resident(r["id"], ADMIN))
        assert r_now["verification_status"] == "REJECTED", \
            f"Expected verification_status=REJECTED, got {r_now['verification_status']}"


class TestResubmitAfterExpiryReturnsInvalidState:
    """Corner: resubmit on EXPIRED VerificationRequest returns ERR_INVALID_STATE."""

    def test_resubmit_on_expired_returns_invalid_state(self, api):
        """PRD §2.6: "State checks come next on any endpoint that drives a
        state machine: the target entity's current state must be a valid
        origin state (a valid `from` in the state machine) for the requested
        transition, or the request is rejected with `ERR_INVALID_STATE` (HTTP
        409)."

        Design: Corner/errors/resubmit_after_expiry_returns_invalid_state
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod = setup_neighborhood_with_moderator()
        r = create_resident(n["id"], email="re@x.com", display_name="RE",
                            home_address_line="12 A St")
        vr = fetch_pending_verification(r["id"])
        mod_headers = make_moderator_headers(mod["id"])
        # Claim + request-resubmission to reach RESUBMISSION_REQUIRED, then let
        # the clock pass expires_at.
        get_success_data(api_client.claim_verification_request(vr["id"], mod_headers))
        get_success_data(api_client.request_resubmission(vr["id"], mod_headers))
        set_clock("2026-06-20T00:00:00Z")
        # Now resubmit -> from state is no longer RESUBMISSION_REQUIRED, so
        # the invalid-state error fires. (Or the auto-EXPIRED path applied.)
        resp = api_client.resubmit_verification(
            vr["id"], {"proof_reference": "late"},
            make_resident_headers(r["id"]),
        )
        validate_error(resp, "ERR_INVALID_STATE")


class TestNonModeratorCannotClaimVerification:
    """Corner: /claim is Moderator-exclusive; Resident role -> 403."""

    def test_resident_role_cannot_claim_verification_request(self, api):
        """PRD §2.1: "If either header is missing, malformed, or its value is
        not one of the six declared role names, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, a role that is
        not permitted for the specific endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/non_moderator_cannot_claim_verification_request_forbidden
        """
        set_clock("2026-06-01T00:00:00Z")
        # Fresh neighborhood + resident (no moderator promotion).
        n = get_success_data(api_client.create_neighborhood(
            {"name": "N1", "state_code": "CA", "center_lat": 37.75,
             "center_lng": -122.42, "radius_meters": 2000}, ADMIN))
        r = create_resident(n["id"], email="rr@x.com", display_name="RR",
                            home_address_line="13 A St")
        vr = fetch_pending_verification(r["id"])
        # Call /claim as the resident (Resident role, live id).
        resp = api_client.claim_verification_request(
            vr["id"], make_resident_headers(r["id"]))
        validate_error(resp, "ERR_FORBIDDEN")


class TestReverseMembershipReachability:
    """Corner: GET /residents/{id}/memberships returns rows for that resident."""

    def test_get_residents_memberships_returns_verified_row(self, api):
        """PRD §3.1: "The `ResidentMembership` collection is reachable in
        three directions: by resident (returning all memberships attached to
        a given resident), by neighborhood (returning all memberships attached
        to a given neighborhood), and by the originating verification request
        (returning the membership rows produced by that specific approval)."

        Design: Corner/endpoints/reverse_reachability_get_residents_memberships_returns_list
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod = setup_neighborhood_with_moderator()
        r = create_resident(n["id"], email="rm@x.com", display_name="RM",
                            home_address_line="14 A St")
        vr = fetch_pending_verification(r["id"])
        approve_verification(vr["id"], mod["id"])
        resp = api_client.list_resident_memberships(r["id"],
                                                    make_resident_headers(r["id"]))
        data = get_success_data(resp)
        rows = data if isinstance(data, list) else data.get("data", data)
        if isinstance(rows, dict):
            rows = rows.get("data", [])
        assert len(rows) >= 1, "Expected at least one ResidentMembership row"
        verified_rows = [row for row in rows if row.get("neighborhood_id") == n["id"]
                         and row.get("status") == "VERIFIED"]
        assert verified_rows, \
            f"Expected a VERIFIED membership in n1, got rows={rows}"


class TestNeighborhoodVerifiedResidentCount:
    """Corner: verified_resident_count increments on APPROVED verification."""

    def test_verified_resident_count_increments_on_approve(self, api):
        """PRD §3.1: "Approving from `IN_REVIEW` moves the state to `APPROVED`
        and cascades three side effects in one response: the pair
        `(resident_id, neighborhood_id)` gains (or updates to) a
        `ResidentMembership` row with `status=VERIFIED`, `verified_at` set to
        the current logical clock, and `source_verification_id` pointing at
        the approving request; the underlying `Resident`'s
        `verification_status` becomes `VERIFIED`; and the target
        `Neighborhood`'s `verified_resident_count` is incremented by 1."

        Design: Corner/endpoints/neighborhood_get_returns_computed_verified_resident_count
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod = setup_neighborhood_with_moderator()
        # Moderator was approved during setup so the count is already 1.
        n_after_mod = get_success_data(api_client.get_neighborhood(n["id"], ADMIN))
        base = n_after_mod["verified_resident_count"]
        # Approve one more resident -> count += 1.
        r = create_resident(n["id"], email="rc@x.com", display_name="RC",
                            home_address_line="20 A St")
        vr = fetch_pending_verification(r["id"])
        approve_verification(vr["id"], mod["id"])
        n_final = get_success_data(api_client.get_neighborhood(n["id"], ADMIN))
        assert n_final["verified_resident_count"] == base + 1, \
            f"Expected verified_resident_count={base+1}, got {n_final['verified_resident_count']}"
