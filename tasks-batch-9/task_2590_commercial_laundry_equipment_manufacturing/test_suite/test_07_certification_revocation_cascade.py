"""The certification-revocation cascade fired by revoking one floor technician.

Revoking the technician who logged every station operation on a shipped unit
raises the unit's integrity hold without re-opening its terminal state, blocks
the open warranty claim filed against it, and recomputes the claiming
distributor's open-claim counter — all inside the revoking request.
"""

from datetime import datetime

from prd_bench_local_runner.testing import validate_success
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.test_users import (
    CHANNEL_MANAGER,
    PLANT_MANAGER,
    PRODUCT_ENGINEER,
    TRAINING_ADMIN,
    WARRANTY_ANALYST,
)


def _instant(value: str) -> datetime:
    """Read an ISO 8601 UTC stamp back as an instant, whatever its precision."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _revoke_floor_technician(api, env):
    """Revoke the certification of the technician who worked every station."""
    return validate_success(
        api.create_certification_action(
            env["technician"]["id"],
            f.revoke_payload(reason="CALIBRATION_AUDIT_FAILURE"),
            TRAINING_ADMIN,
        ),
        expected_status=200,
    )


def _read_technician(api, technician_id):
    return validate_success(
        api.get_technician(technician_id, TRAINING_ADMIN), expected_status=200
    )


def _read_build(api, build_order_id):
    return validate_success(
        api.get_build_order(build_order_id, PLANT_MANAGER), expected_status=200
    )


def _read_model(api, model_id):
    return validate_success(
        api.get_machine_model(model_id, PRODUCT_ENGINEER), expected_status=200
    )


def _read_claim(api, claim_id):
    return validate_success(
        api.get_warranty_claim(claim_id, WARRANTY_ANALYST), expected_status=200
    )


def _read_distributor(api, distributor_id):
    return validate_success(
        api.get_distributor(distributor_id, CHANNEL_MANAGER), expected_status=200
    )


def _read_part(api, part_id):
    return validate_success(
        api.get_service_part(part_id, WARRANTY_ANALYST), expected_status=200
    )


class TestRevocationStripsTheTechnician:
    def test_01_the_technician_moves_from_active_to_revoked(self, api, submitted_claim):
        """The revoked badge leaves the technician in REVOKED.

        PRD: "A revocation moves the technician from `ACTIVE` to `REVOKED` and runs a four-hop cascade inside the same request."
        Design: Difficulty/transitive_cascade/cert_revoke_quality_hold_blocks_claim_and_decrements_open_count
        """
        env = submitted_claim
        assert env["technician"]["cert_state"] == "ACTIVE"

        _revoke_floor_technician(api, env)

        technician = _read_technician(api, env["technician"]["id"])
        assert technician["cert_state"] == "REVOKED"

    def test_02_the_scopes_are_emptied_and_the_revocation_is_counted(
        self, api, submitted_claim
    ):
        """The first hop empties the scope set and increments the revocation count.

        PRD: "The first hop touches the technician: `cert_scopes` is emptied, `revocation_count` increases by 1, `last_cert_action_at` is stamped with the current instant, and the technician's `version` advances by 1."
        Design: Difficulty/transitive_cascade/cert_revoke_quality_hold_blocks_claim_and_decrements_open_count
        """
        env = submitted_claim

        _revoke_floor_technician(api, env)

        technician = _read_technician(api, env["technician"]["id"])
        assert technician["cert_scopes"] == []
        assert technician["revocation_count"] == 1

    def test_03_the_revocation_is_stamped_on_the_logical_clock(
        self, api, submitted_claim
    ):
        """The action instant is the server's logical clock, never wall-clock time.

        PRD: "The server starts with the logical clock at exactly `2026-08-01T00:00:00Z` and never falls back to real time for any comparison, stamp or expiry decision."
        Design: Difficulty/transitive_cascade/cert_revoke_quality_hold_blocks_claim_and_decrements_open_count
        """
        env = submitted_claim

        _revoke_floor_technician(api, env)

        technician = _read_technician(api, env["technician"]["id"])
        assert _instant(technician["last_cert_action_at"]) == _instant(
            c.DEFAULT_CLOCK_UTC
        )


class TestTheAcceptedUnitKeepsItsTerminalState:
    def test_01_a_shipped_unit_is_never_re_opened(self, api, submitted_claim):
        """The accepted unit stays ACCEPTED instead of moving to quality hold.

        PRD: "Two invariants hold across all three. First, **terminal states are never re-opened**: a unit that has reached `ACCEPTED` or `SCRAPPED` never returns to an in-production state, so a cascade that would otherwise move a unit to `QUALITY_HOLD` instead only records the integrity flag on an accepted unit, and leaves a scrapped unit entirely untouched."
        Design: Difficulty/transitive_cascade/cert_revoke_quality_hold_blocks_claim_and_decrements_open_count
        """
        env = submitted_claim
        a.assert_build_state(env["build"], "ACCEPTED")

        _revoke_floor_technician(api, env)

        build = _read_build(api, env["build"]["id"])
        a.assert_build_state(build, "ACCEPTED")

    def test_02_the_accepted_unit_takes_the_integrity_hold_flag(
        self, api, submitted_claim
    ):
        """The second hop raises integrity_hold on the unit the technician built.

        PRD: "The second hop finds every build order carrying at least one station log written by this technician and, walking them in `created_at` ascending order, puts each one under an integrity hold: a unit in `ON_FLOOR`, `DRUM_DONE`, `BEARINGS_DONE` or `QA_HOLD` moves to `QUALITY_HOLD` with `integrity_hold` set to true; a unit already in `ACCEPTED` keeps its terminal state and takes only `integrity_hold` set to true, because a shipped unit is never re-opened; a unit in `SCRAPPED` is left entirely untouched."
        Design: Difficulty/transitive_cascade/cert_revoke_quality_hold_blocks_claim_and_decrements_open_count
        """
        env = submitted_claim
        assert env["build"]["integrity_hold"] is False

        _revoke_floor_technician(api, env)

        build = _read_build(api, env["build"]["id"])
        assert build["integrity_hold"] is True

    def test_03_no_unit_of_the_model_is_counted_on_quality_hold(
        self, api, submitted_claim
    ):
        """With nothing in QUALITY_HOLD the model's hold counter stays at zero.

        PRD: "Each affected unit's `version` advances by 1, and the owning model's `quality_hold_unit_count` is recomputed from the units now sitting in `QUALITY_HOLD`."
        Design: Difficulty/transitive_cascade/cert_revoke_quality_hold_blocks_claim_and_decrements_open_count
        """
        env = submitted_claim

        _revoke_floor_technician(api, env)

        model = _read_model(api, env["model"]["id"])
        assert model["quality_hold_unit_count"] == 0


class TestTheOpenClaimIsBlocked:
    def test_01_the_submitted_claim_leaves_submitted_for_fulfillment_blocked(
        self, api, submitted_claim
    ):
        """The claim against the held unit is blocked by the third hop.

        PRD: "The third hop finds every warranty claim in `SUBMITTED` filed against any of those units and, walking them in `created_at` ascending order, moves each to `FULFILLMENT_BLOCKED` with `block_reason` set to `BUILD_INTEGRITY_HOLD` and its `version` advanced by 1."
        Design: Difficulty/transitive_cascade/cert_revoke_quality_hold_blocks_claim_and_decrements_open_count
        """
        env = submitted_claim
        a.assert_claim_state(env["claim"], "SUBMITTED")

        _revoke_floor_technician(api, env)

        claim = _read_claim(api, env["claim"]["id"])
        a.assert_claim_state(claim, "FULFILLMENT_BLOCKED")

    def test_02_the_block_reason_names_the_build_integrity_hold(
        self, api, submitted_claim
    ):
        """The block is attributed to the unit's integrity standing, not to stock.

        PRD: "Only the certification-revocation cascade of §3.4 sets `integrity_hold` to true, and only that flag drives claims into `FULFILLMENT_BLOCKED` with `block_reason` of `BUILD_INTEGRITY_HOLD`."
        Design: Difficulty/transitive_cascade/cert_revoke_quality_hold_blocks_claim_and_decrements_open_count
        """
        env = submitted_claim
        assert env["claim"]["block_reason"] == "NONE"

        _revoke_floor_technician(api, env)

        claim = _read_claim(api, env["claim"]["id"])
        assert claim["block_reason"] == "BUILD_INTEGRITY_HOLD"

    def test_03_a_blocked_claim_settles_nothing(self, api, submitted_claim):
        """Blocking is not adjudication, so no money is covered.

        PRD: "A new claim begins in `claim_state` `SUBMITTED` with `block_reason` at `NONE`, `coverage_variant` at `NONE`, `covered_amount_cents` at 0, `denial_reason` at `NONE`, `adjudicated_by_user_id` null and `voided_at` null, and the filing recomputes the claiming distributor's `open_claim_count`."
        Design: Difficulty/transitive_cascade/cert_revoke_quality_hold_blocks_claim_and_decrements_open_count
        """
        env = submitted_claim

        _revoke_floor_technician(api, env)

        claim = _read_claim(api, env["claim"]["id"])
        a.assert_cents(claim["covered_amount_cents"], 0)


class TestTheDistributorCountersAreRecomputed:
    def test_01_the_open_claim_count_falls_back_to_zero(self, api, submitted_claim):
        """The distributor's open-claim tally follows the claim out of SUBMITTED.

        PRD: "`open_claim_count` is the number of that distributor's warranty claims currently sitting in `SUBMITTED`, and it is recomputed on every event that could change it."
        Design: Difficulty/transitive_cascade/cert_revoke_quality_hold_blocks_claim_and_decrements_open_count
        """
        env = submitted_claim
        before = _read_distributor(api, env["distributor"]["id"])
        assert before["open_claim_count"] == 1

        _revoke_floor_technician(api, env)

        after = _read_distributor(api, env["distributor"]["id"])
        assert after["open_claim_count"] == 0

    def test_02_the_channel_standing_is_untouched_by_the_cascade(
        self, api, submitted_claim
    ):
        """The distributor stays AUTHORIZED; only its counter moved.

        PRD: "The fourth hop recomputes `open_claim_count` on every distributor that owned one of those claims."
        Design: Difficulty/transitive_cascade/cert_revoke_quality_hold_blocks_claim_and_decrements_open_count
        """
        env = submitted_claim

        _revoke_floor_technician(api, env)

        distributor = _read_distributor(api, env["distributor"]["id"])
        assert distributor["distributor_state"] == "AUTHORIZED"

    def test_03_the_claimed_part_stock_position_does_not_move(
        self, api, submitted_claim
    ):
        """Blocking a claim reserves nothing: the shelf keeps its three units.

        PRD: "Neither `on_hand_qty` nor `reserved_qty` is ever set directly by a client; §3.9 explains the only three movements that change them."
        Design: Difficulty/transitive_cascade/cert_revoke_quality_hold_blocks_claim_and_decrements_open_count
        """
        env = submitted_claim

        _revoke_floor_technician(api, env)

        part = _read_part(api, env["part"]["id"])
        assert part["on_hand_qty"] == 3
        assert part["reserved_qty"] == 0
