"""Stay lifecycle forks (reservation check-in, transfer) and the bed-night
dual variants (PRD §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    arrive_dispatch,
    assert_guest_stay,
    get_site_activation,
    get_stay,
    setup_guest_checked_in_window,
    setup_two_active_episodes_with_open_sites,
    setup_two_open_sites_scene,
    transfer_stay_payload,
    validate_error,
    validate_success,
    INTAKE_HEADERS,
)


class TestBedNightDualVariants:
    def test_bed_nights_provisional_credits_in_progress_night(self, api):
        """PRD §3.4: "The provisional variant, `bed_nights_provisional`, is
        live on every read: it counts the midnight boundaries from
        `checked_in_at` up to the logical-clock now and adds one extra night
        for the in-progress night while the stay is still `CHECKED_IN`, so the
        provisional figure is always at least the final figure for the same
        stay." and "it remains null while the stay is still checked in".

        Design: Difficulty/dual_variant_calc/bed_nights_provisional_exceeds_final_for_in_progress_stay
        """
        # Checked in 2026-08-10T20:00:00Z; observed at 2026-08-11T21:00:00Z:
        # one midnight boundary crossed (2026-08-11T00:00:00Z) plus the
        # in-progress night.
        ws = setup_guest_checked_in_window()
        stay = get_stay(ws["stay"]["id"])
        assert_guest_stay(stay)
        assert stay["status"] == "CHECKED_IN"
        assert stay["bed_nights_provisional"] == 2
        assert stay["bed_nights_final"] is None

    def test_bed_nights_final_counts_only_crossed_midnights_after_checkout(
            self, api):
        """PRD §3.4: "The final variant, `bed_nights_final`, counts the
        midnight instants that are strictly after `checked_in_at` and at or
        before `checked_out_at`; it is computed the moment a stay leaves
        `CHECKED_IN` — by check-out, by behavioral ejection, or by transfer —
        and it remains null while the stay is still checked in, as it does for
        reserved stays that never reach check-in."

        Design: Difficulty/dual_variant_calc/bed_nights_provisional_exceeds_final_for_in_progress_stay
        """
        ws = setup_guest_checked_in_window()
        resp = api.check_out_stay(ws["stay"]["id"], INTAKE_HEADERS)
        stay = validate_success(resp, 200)
        assert stay["status"] == "CHECKED_OUT"
        # 20:00 -> next-day 21:00 crosses exactly one 00:00Z boundary; the
        # provisional figure no longer credits an in-progress night.
        assert stay["bed_nights_final"] == 1
        assert stay["bed_nights_provisional"] == 1


class TestStayBranchingForks:
    def test_reserved_stay_checks_in_after_dispatch_arrival(self, api):
        """PRD §3.5: "On success the dispatch moves from `REQUESTED` to
        `ASSIGNED`, `vehicle_id` is set, `reserved_bed_count` becomes the
        rider count, and one `RESERVED` stay per rider is created at the
        destination ..."
        PRD §3.4: "Check-in moves a `RESERVED` stay to `CHECKED_IN`. The
        linked dispatch must have arrived, else `ERR_DISPATCH_NOT_ARRIVED`,
        and the medical-hold gate applies again."

        Design: Difficulty/non_linear_state_machine/guest_stay_branching_forks_reserved_checkin_and_transfer
        """
        ws = setup_two_open_sites_scene()
        stay1 = ws["stay_reserved"]
        assert stay1["status"] == "RESERVED"  # dispatch-born, not walk-in

        arrive_dispatch(ws["dispatch"]["id"])
        resp = api.check_in_stay(stay1["id"], INTAKE_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "CHECKED_IN"

        sa_a = get_site_activation(ws["sa_a"]["id"])
        assert sa_a["occupied_beds"] == 2   # rider + walk-in
        assert sa_a["reserved_beds"] == 0

    def test_transfer_moves_stay_and_creates_successor(self, api):
        """PRD §3.4: "A successful transfer moves the source stay to
        `TRANSFERRED_OUT` with `checked_out_at` stamped and its final bed
        nights computed, releases the source pools, and creates a successor
        stay at the target already in `CHECKED_IN`, carrying the same
        `guest_id`, the same pinned `pet_slots_used` and `lockers_used`, a
        null `transport_dispatch_id`, a `transfer_sequence` one higher than
        the source's, and a fresh `checked_in_at`."

        Design: Difficulty/non_linear_state_machine/guest_stay_branching_forks_reserved_checkin_and_transfer
        """
        ws = setup_two_open_sites_scene()
        # Check the dispatch rider in first so site A holds both guests.
        arrive_dispatch(ws["dispatch"]["id"])
        checked = validate_success(
            api.check_in_stay(ws["stay_reserved"]["id"], INTAKE_HEADERS), 200)
        assert checked["status"] == "CHECKED_IN"

        source = ws["stay_walkin"]
        resp = api.transfer_stay(
            source["id"], transfer_stay_payload(ws["sa_b"]["id"]),
            INTAKE_HEADERS)
        successor = validate_success(resp, 200)
        assert_guest_stay(successor)
        assert successor["status"] == "CHECKED_IN"
        assert successor["site_activation_id"] == ws["sa_b"]["id"]
        assert successor["guest_id"] == source["guest_id"]
        assert successor["transfer_sequence"] == 1
        assert successor["transport_dispatch_id"] is None

        source_after = get_stay(source["id"])
        assert source_after["status"] == "TRANSFERRED_OUT"

        sa_a = get_site_activation(ws["sa_a"]["id"])
        sa_b = get_site_activation(ws["sa_b"]["id"])
        assert sa_a["occupied_beds"] == 1   # only the dispatch rider remains
        assert sa_b["occupied_beds"] == 1

    def test_transfer_to_site_in_other_episode_rejected(self, api):
        """PRD §3.4: "The request names a `target_site_activation_id`. The
        target must belong to the same episode as the source, else
        `ERR_CROSS_EPISODE_TRANSFER`; it must be `OPEN`, else
        `ERR_SITE_NOT_OPEN`; ..."

        Design: Corner/validations/transfer_to_site_in_other_episode_rejected
        """
        ws = setup_two_active_episodes_with_open_sites()
        resp = api.transfer_stay(
            ws["stay"]["id"], transfer_stay_payload(ws["sa_b"]["id"]),
            INTAKE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_CROSS_EPISODE_TRANSFER,
                       expected_status=409)
        stay = get_stay(ws["stay"]["id"])
        assert stay["status"] == "CHECKED_IN"
        assert stay["site_activation_id"] == ws["sa_a"]["id"]
