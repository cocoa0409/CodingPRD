"""Exhibition agreements: amendment floor, amendment OCC, and termination
gating on live slots (PRD §2.7, §3.7)."""
from test_helpers import (
    ApiErrorId,
    fx_programmed,
    validate_error, validate_success,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]
OPS = TEST_USERS["ops_headers"]


class TestAmend:
    def test_amend_guards_license_floor_and_stale_occ(self, api, admin_headers):
        """PRD §3.7: "The license may never be cut beneath usage already
        consumed — a `licensed_screening_count` below the agreement's
        `used_screening_count` is rejected with `ERR_LICENSED_BELOW_USED`. A
        successful amend leaves the agreement in `ACTIVE`, refreshes
        `submission_version_at_signing` to the submission's current version,
        and increments the agreement's own `version`"; §2.7: the amend
        carries `expected_agreement_version` and a stale value is rejected
        with `ERR_STALE_VERSION` (HTTP 412).

        Design: Corner/validations/amend_guards_license_floor_and_stale_occ
        """
        ctx = fx_programmed(films=1, capacity_slots=1)  # one CONFIRMED slot
        # Re-read: the first confirmation flipped the agreement to ACTIVE and
        # bumped its version since the signing snapshot.
        agreement = validate_success(
            api.get_exhibition_agreement(ctx["agreements"][0]["id"], DIRECTOR)
        )
        assert agreement["status"] == "ACTIVE"  # flipped at first confirm
        assert agreement["used_screening_count"] == 1
        observed_version = agreement["version"]

        below_floor = api.amend_agreement(
            agreement["id"],
            {"expected_agreement_version": observed_version,
             "licensed_screening_count": 0},
            DIRECTOR,
        )
        validate_error(below_floor, ApiErrorId.ERR_LICENSED_BELOW_USED.value)

        amended = validate_success(api.amend_agreement(
            agreement["id"],
            {"expected_agreement_version": observed_version,
             "licensed_screening_count": 5},
            DIRECTOR,
        ))
        assert amended["licensed_screening_count"] == 5
        assert amended["status"] == "ACTIVE"
        assert amended["version"] > observed_version

        film = validate_success(
            api.get_submission(ctx["films"][0]["film"]["id"], admin_headers)
        )
        assert amended["submission_version_at_signing"] == film["version"]

        replay = api.amend_agreement(
            agreement["id"],
            {"expected_agreement_version": observed_version,
             "revenue_share_pct": 5.0},
            DIRECTOR,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value)


class TestTerminate:
    def test_terminate_blocked_until_slots_released(self, api):
        """PRD §3.7: termination moves "a `SIGNED` or `ACTIVE` agreement to
        terminal `TERMINATED`, but it is forbidden while any slot in `HELD`
        or `CONFIRMED` references the entry, failing with
        `ERR_ACTIVE_SLOTS_EXIST`."

        Design: Corner/validations/terminate_blocked_until_slots_released
        """
        ctx = fx_programmed(films=1, capacity_slots=1)  # CONFIRMED premiere
        agreement = ctx["agreements"][0]
        slot = ctx["slots"][0]

        blocked = api.terminate_agreement(agreement["id"], DIRECTOR)
        validate_error(blocked, ApiErrorId.ERR_ACTIVE_SLOTS_EXIST.value)

        cancelled = validate_success(api.cancel_slot(slot["id"], OPS))
        assert cancelled["status"] == "CANCELLED"

        terminated = validate_success(
            api.terminate_agreement(agreement["id"], DIRECTOR)
        )
        assert terminated["status"] == "TERMINATED"
