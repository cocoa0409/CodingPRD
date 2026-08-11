"""Affiliation agreement lifecycle and cascades (corner: state_machines;
difficulty: transitive_cascade)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_avail_allocation_payload,
    create_program_payload,
    get_success_data,
    make_nar_headers,
    make_platform_admin_headers,
    setup_basic_scenario,
    setup_clock,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import (
    create_avail_allocation,
    create_territory,
    create_program,
    confirm_avail_allocation,
)


class TestAgreementInvalidTransition:
    def test_activate_terminated_agreement_returns_invalid_state(self, api):
        """PRD §3.2: "`TERMINATED` is a terminal state."
        PRD §2.10 step 4: "the target resource is in a state that permits the
        requested transition per its state machine (else `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/agreement_invalid_from_terminated_to_active
        """
        scenario = setup_basic_scenario()
        nar = scenario["nar_headers"]
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        aid = scenario["agreement"]["id"]
        # Drive to TERMINATED.
        get_success_data(api.terminate_agreement(nid, sid, aid, nar))
        # Attempt to activate the TERMINATED agreement.
        resp = api.activate_agreement(nid, sid, aid, nar)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTerminationCascade:
    def test_termination_revokes_claimed_and_confirmed_allocs(self, api):
        """PRD §3.2: "Terminating from `ACTIVE` additionally cascades to every
        avail allocation in `CLAIMED` or `CONFIRMED` on this station, flipping
        each to `REVOKED`."
        PRD §3.2: "the territory's `exclusivity_holder_station_id` is cleared
        back to null".

        Design: Difficulty/transitive_cascade/termination_cascade_to_avail_revocation
        """
        scenario = setup_basic_scenario()
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        # Build program + two avail allocations, one CLAIMED and one CONFIRMED.
        program = create_program(
            nid,
            avail_minutes_total=20,
            avail_minutes_local_allocatable=10,
            is_syndicated=False,
        )
        aa1 = create_avail_allocation(nid, sid, program["id"], sgo,
                                      local_minutes_claimed=4)
        aa2 = create_avail_allocation(nid, sid, program["id"], sgo,
                                      local_minutes_claimed=5)
        confirm_avail_allocation(nid, sid, aa2["id"], nar)

        # Trigger termination.
        get_success_data(
            api.terminate_agreement(nid, sid, scenario["agreement"]["id"], nar)
        )
        aa1_after = validate_success(
            api.get_avail_allocation(nid, sid, aa1["id"], nar), expected_status=200
        )
        aa2_after = validate_success(
            api.get_avail_allocation(nid, sid, aa2["id"], nar), expected_status=200
        )
        terr_after = validate_success(
            api.get_territory(nid, scenario["territory"]["id"], nar), expected_status=200
        )
        assert aa1_after["status"] == "REVOKED", (
            f"CLAIMED allocation must flip to REVOKED on termination; got "
            f"{aa1_after['status']!r}"
        )
        assert aa2_after["status"] == "REVOKED", (
            f"CONFIRMED allocation must flip to REVOKED on termination; got "
            f"{aa2_after['status']!r}"
        )
        assert terr_after["exclusivity_holder_station_id"] is None, (
            "Territory exclusivity holder must be cleared to null on termination; "
            f"got {terr_after['exclusivity_holder_station_id']!r}"
        )

    def test_termination_clears_territory_exclusivity_holder(self, api):
        """PRD §3.2: "the territory's `exclusivity_holder_station_id` is
        cleared back to null".

        Design: Difficulty/transitive_cascade/termination_cascade_to_avail_revocation
        """
        scenario = setup_basic_scenario()
        nid = scenario["network"]["id"]
        nar = scenario["nar_headers"]
        # Sanity: territory held by this station while ACTIVE.
        terr_before = validate_success(
            api.get_territory(nid, scenario["territory"]["id"], nar)
        )
        assert terr_before["exclusivity_holder_station_id"] == scenario["station"]["id"]
        # Terminate.
        get_success_data(
            api.terminate_agreement(
                nid, scenario["station"]["id"], scenario["agreement"]["id"], nar
            )
        )
        terr_after = validate_success(
            api.get_territory(nid, scenario["territory"]["id"], nar)
        )
        assert terr_after["exclusivity_holder_station_id"] is None, (
            "Termination must clear the exclusivity holder to null; got "
            f"{terr_after['exclusivity_holder_station_id']!r}"
        )

    def test_termination_cascade_skips_already_revoked(self, api):
        """PRD §3.2: "Terminating from `ACTIVE` additionally cascades to every
        avail allocation in `CLAIMED` or `CONFIRMED` on this station, flipping
        each to `REVOKED`." (Implicitly: allocations already in `REVOKED` are
        outside the cascade's target set.)
        PRD §3.8: "`REVOKED` and `EXPIRED` are the terminal states of an avail
        allocation."

        Design: Corner/state_machines/avail_allocation_revoke_cascade_only_affects_non_terminal
        """
        scenario = setup_basic_scenario()
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        program = create_program(
            nid,
            avail_minutes_total=20,
            avail_minutes_local_allocatable=10,
            is_syndicated=False,
        )
        aa1 = create_avail_allocation(nid, sid, program["id"], sgo,
                                      local_minutes_claimed=2)
        aa2 = create_avail_allocation(nid, sid, program["id"], sgo,
                                      local_minutes_claimed=3)
        # Confirm aa1, revoke aa2 explicitly so aa2 is already terminal.
        confirm_avail_allocation(nid, sid, aa1["id"], nar)
        get_success_data(api.revoke_avail_allocation(nid, sid, aa2["id"], nar))

        get_success_data(
            api.terminate_agreement(nid, sid, scenario["agreement"]["id"], nar)
        )
        aa1_after = validate_success(api.get_avail_allocation(nid, sid, aa1["id"], nar))
        aa2_after = validate_success(api.get_avail_allocation(nid, sid, aa2["id"], nar))
        assert aa1_after["status"] == "REVOKED"
        assert aa2_after["status"] == "REVOKED", (
            "Already-REVOKED allocation must remain REVOKED (terminal states "
            "are not re-mutated by the cascade)"
        )
