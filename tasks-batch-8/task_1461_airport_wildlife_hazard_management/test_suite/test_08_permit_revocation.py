"""Permit revocation cascade to LOGGED dispersals and take_consumed
conservation across the revocation."""
import pytest

from test_helpers import (
    validate_success,
    setup_permit_scenario,
    create_logged_dispersal,
    review_dispersal,
    close_dispersal,
    ApiErrorId,
)


class TestPermitRevocationCascade:
    """Revoking an ACTIVE permit flags every still-LOGGED dispersal that
    references it."""

    def test_revoke_flags_logged_dispersals(self, api):
        """PRD §3.4: "A regulator may also revoke an `ACTIVE` permit;
        revocation is restricted to a regulator whose `agency` matches the
        issuing agency, and on revocation every still-`LOGGED` dispersal
        referencing the permit is cascaded to `FLAGGED` so the field team
        knows the authorization underpinning it is gone."

        Design: Difficulty/transitive_cascade/permit_revocation_cascade_to_flagged_dispersals
        """
        ctx = setup_permit_scenario(icao_code="KHHH", authorized_take_total=10,
                                    permit_number="MB0002-00")
        d1 = create_logged_dispersal(
            ctx["airport"]["id"], ctx["performer"], ctx["species"]["id"],
            performed_at="2026-07-15T10:00:00Z", animals_taken_lethal=2,
            take_permit_id=ctx["permit"]["id"],
        )
        d2 = create_logged_dispersal(
            ctx["airport"]["id"], ctx["performer"], ctx["species"]["id"],
            performed_at="2026-07-16T10:00:00Z", animals_dispersed=3,
            animals_taken_lethal=1, take_permit_id=ctx["permit"]["id"],
        )

        revoked = validate_success(
            api.revoke_take_permit(ctx["permit"]["id"], ctx["regulator_headers"]),
            200,
        )
        assert revoked["status"] == "REVOKED"

        for d in (d1, d2):
            d_after = validate_success(
                api.get_dispersal_activity(d["id"], ctx["senior_headers"]), 200,
            )
            assert d_after["status"] == "FLAGGED", (
                f"LOGGED dispersal {d['id']} must cascade to FLAGGED, got "
                f"{d_after['status']}"
            )

    def test_revoke_leaves_reviewed_dispersal_untouched(self, api):
        """PRD §3.4: "on revocation every still-`LOGGED` dispersal referencing
        the permit is cascaded to `FLAGGED`" — a dispersal already in
        `REVIEWED` is not still-LOGGED and is not cascaded.

        Design: Difficulty/transitive_cascade/permit_revocation_cascade_to_flagged_dispersals
        """
        ctx = setup_permit_scenario(icao_code="KHHI", authorized_take_total=10,
                                    permit_number="MB0002-01")
        d_logged = create_logged_dispersal(
            ctx["airport"]["id"], ctx["performer"], ctx["species"]["id"],
            performed_at="2026-07-15T10:00:00Z", animals_taken_lethal=1,
            take_permit_id=ctx["permit"]["id"],
        )
        d_reviewed = create_logged_dispersal(
            ctx["airport"]["id"], ctx["performer"], ctx["species"]["id"],
            performed_at="2026-07-16T10:00:00Z", animals_dispersed=3,
            animals_taken_lethal=1, take_permit_id=ctx["permit"]["id"],
        )
        review_dispersal(d_reviewed["id"], ctx["senior"])

        validate_success(
            api.revoke_take_permit(ctx["permit"]["id"], ctx["regulator_headers"]),
            200,
        )

        logged_after = validate_success(
            api.get_dispersal_activity(d_logged["id"], ctx["senior_headers"]), 200,
        )
        assert logged_after["status"] == "FLAGGED"
        reviewed_after = validate_success(
            api.get_dispersal_activity(d_reviewed["id"], ctx["senior_headers"]), 200,
        )
        assert reviewed_after["status"] == "REVIEWED", (
            f"REVIEWED dispersal must not be cascaded, got "
            f"{reviewed_after['status']}"
        )


class TestTakeConsumedConservation:
    """take_consumed is the sum over CLOSED dispersals; revocation does not
    decrement it."""

    def test_revoke_preserves_take_consumed(self, api):
        """PRD §3.4: "the permit's `take_consumed` must equal the sum of
        `animals_taken_lethal` across every `CLOSED` dispersal referencing the
        permit."
        PRD §3.4: "A regulator may also revoke an `ACTIVE` permit" (no
        provision decrements the already-consumed take).

        Design: Difficulty/compensating_invariant/permit_take_consumed_invariant_after_close_and_revoke
        """
        ctx = setup_permit_scenario(icao_code="KQQQ", authorized_take_total=10,
                                    permit_number="MB0005-00")
        d1 = create_logged_dispersal(
            ctx["airport"]["id"], ctx["performer"], ctx["species"]["id"],
            performed_at="2026-07-15T10:00:00Z", animals_taken_lethal=3,
            take_permit_id=ctx["permit"]["id"],
        )
        review_dispersal(d1["id"], ctx["senior"])
        close_dispersal(d1["id"], ctx["senior"])
        d2 = create_logged_dispersal(
            ctx["airport"]["id"], ctx["performer"], ctx["species"]["id"],
            performed_at="2026-07-16T10:00:00Z", animals_dispersed=3,
            animals_taken_lethal=2, take_permit_id=ctx["permit"]["id"],
        )

        validate_success(
            api.revoke_take_permit(ctx["permit"]["id"], ctx["regulator_headers"]),
            200,
        )

        permit = validate_success(
            api.get_take_permit(ctx["permit"]["id"], ctx["regulator_headers"]), 200,
        )
        assert permit["status"] == "REVOKED"
        assert permit["take_consumed"] == 3, (
            f"revocation must not decrement the conserved quantity, got "
            f"{permit['take_consumed']}"
        )
        d2_after = validate_success(
            api.get_dispersal_activity(d2["id"], ctx["senior_headers"]), 200,
        )
        assert d2_after["status"] == "FLAGGED"

    def test_logged_dispersal_not_counted_in_take_consumed(self, api):
        """PRD §3.4: "the permit's `take_consumed` must equal the sum of
        `animals_taken_lethal` across every `CLOSED` dispersal referencing the
        permit." A LOGGED dispersal is not CLOSED and contributes nothing.

        Design: Difficulty/compensating_invariant/permit_take_consumed_invariant_after_close_and_revoke
        """
        ctx = setup_permit_scenario(icao_code="KQQR", authorized_take_total=10,
                                    permit_number="MB0005-02")
        d1 = create_logged_dispersal(
            ctx["airport"]["id"], ctx["performer"], ctx["species"]["id"],
            performed_at="2026-07-15T10:00:00Z", animals_taken_lethal=3,
            take_permit_id=ctx["permit"]["id"],
        )
        review_dispersal(d1["id"], ctx["senior"])
        close_dispersal(d1["id"], ctx["senior"])
        d2 = create_logged_dispersal(
            ctx["airport"]["id"], ctx["performer"], ctx["species"]["id"],
            performed_at="2026-07-16T10:00:00Z", animals_dispersed=3,
            animals_taken_lethal=2, take_permit_id=ctx["permit"]["id"],
        )

        permit = validate_success(
            api.get_take_permit(ctx["permit"]["id"], ctx["regulator_headers"]), 200,
        )
        assert permit["take_consumed"] == 3, (
            f"LOGGED dispersal (take 2) must not be counted, got "
            f"{permit['take_consumed']}"
        )
        d2_after = validate_success(
            api.get_dispersal_activity(d2["id"], ctx["senior_headers"]), 200,
        )
        assert d2_after["status"] == "LOGGED"
