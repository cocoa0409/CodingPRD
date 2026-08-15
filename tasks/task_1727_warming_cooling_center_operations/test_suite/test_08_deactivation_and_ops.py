"""Episode deactivation cascade (three levels), the conditional OPENING-site
close branch, and the ops sweep (PRD §3.2, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_bed_conservation,
    get_dispatch,
    get_episode,
    get_site_activation,
    get_stay,
    list_stays,
    setup_active_episode_open_plus_opening_site,
    setup_deactivation_cascade_scene,
    setup_draining_site_with_checked_in_guest,
    setup_run_ops_scene,
    validate_error,
    validate_success,
    get_success_data,
    EOC_HEADERS,
    INTAKE_HEADERS,
)


class TestDeactivationCascade:
    def test_deactivation_drains_site_and_cancels_reserved_stays(self, api):
        """PRD §3.8: "An `EOCManager` action moves the episode from `ACTIVE`
        to `DEACTIVATING`, stamps `deactivated_at` from the logical clock, and
        fires a three-level cascade. At the first level, each of the episode's
        site activations in `OPEN` moves to `DRAINING`, processed in
        `created_at` ascending order, while each activation still in `OPENING`
        moves directly to `CLOSED` with its own close side effects. At the
        second level, every activation that just drained cancels each of its
        stays still in `RESERVED` — again in `created_at` ascending order —
        releasing bed, pet and locker usage; guests already `CHECKED_IN` are
        not disturbed by the drain."

        Design: Difficulty/transitive_cascade/deactivation_cascade_episode_site_stay_dispatch
        """
        ws = setup_deactivation_cascade_scene()
        resp = api.deactivate_episode(ws["episode"]["id"], EOC_HEADERS)
        assert validate_success(resp, 200)["status"] == "DEACTIVATING"

        sa = get_site_activation(ws["site_activation"]["id"])
        assert sa["status"] == "DRAINING"

        cancelled = list_stays(
            {"transport_dispatch_id": ws["dispatch"]["id"]})
        assert len(cancelled) == 2
        assert all(s["status"] == "CANCELLED" for s in cancelled)

    def test_deactivation_cascade_cancels_drained_dispatch(self, api):
        """PRD §3.8: "At the third level, each of those cancelled stays that
        was born of a transport reservation decrements its linked dispatch's
        `reserved_bed_count` by one, and when that decrement drops the count
        to zero on a dispatch still `ASSIGNED`, the dispatch itself moves to
        `CANCELLED`." and "guests already `CHECKED_IN` are not disturbed by
        the drain."

        Design: Difficulty/transitive_cascade/deactivation_cascade_episode_site_stay_dispatch
        """
        ws = setup_deactivation_cascade_scene()
        validate_success(api.deactivate_episode(ws["episode"]["id"], EOC_HEADERS),
                         200)

        dispatch = get_dispatch(ws["dispatch"]["id"])
        assert dispatch["status"] == "CANCELLED"
        assert dispatch["reserved_bed_count"] == 0

        # The walk-in guest already CHECKED_IN is not disturbed by the drain.
        assert get_stay(ws["stay_walkin"]["id"])["status"] == "CHECKED_IN"

        sa = get_site_activation(ws["site_activation"]["id"])
        assert sa["occupied_beds"] == 1
        assert sa["reserved_beds"] == 0
        assert sa["beds_free"] == 3
        assert_bed_conservation(sa)

    def test_deactivation_closes_never_opened_site_and_cancels_its_shifts(
            self, api):
        """PRD §3.8: "At the first level, each of the episode's site
        activations in `OPEN` moves to `DRAINING`, processed in `created_at`
        ascending order, while each activation still in `OPENING` moves
        directly to `CLOSED` with its own close side effects."
        PRD §3.2: "A successful close moves the activation to `CLOSED` and
        cancels every one of its shifts still `PLANNED` or `CONFIRMED`."

        Design: Corner/state_machines/deactivation_closes_never_opened_site_and_cancels_its_shifts
        """
        ws = setup_active_episode_open_plus_opening_site()
        validate_success(api.deactivate_episode(ws["episode"]["id"], EOC_HEADERS),
                         200)

        sa_a = get_site_activation(ws["sa_a"]["id"])
        sa_b = get_site_activation(ws["sa_b"]["id"])
        assert sa_a["status"] == "DRAINING"
        assert sa_b["status"] == "CLOSED"

        # The drained (previously OPEN) site keeps its confirmed shift; the
        # never-opened site closed, cancelling its confirmed shift.
        shift_a = get_success_data(api.get_shift(ws["shift_a"]["id"], EOC_HEADERS))
        shift_b = get_success_data(api.get_shift(ws["shift_b"]["id"], EOC_HEADERS))
        assert shift_a["status"] == "CONFIRMED"
        assert shift_b["status"] == "CANCELLED"


class TestOpsSweep:
    def test_run_ops_completes_past_shifts_and_expires_reserved_no_shows(
            self, api):
        """PRD §3.8: "Each run increments the episode's `ops_run_index` by
        one, advances the episode's `version` by one, and executes three steps
        in a pinned order. First, every `CONFIRMED` shift of the episode whose
        `end_at` has been reached by the logical clock moves to `COMPLETED`,
        processed in `created_at` ascending order, recomputing coverage as it
        goes. Second, every `RESERVED` stay of the episode whose linked
        dispatch has `ARRIVED` and for which the logical clock has reached
        sixty minutes past the dispatch's `arrived_at` moves to `NO_SHOW` in
        `created_at` ascending order, each releasing its bed, pet and locker
        usage and decrementing its dispatch's `reserved_bed_count`."

        Design: Corner/state_machines/run_ops_completes_past_shifts_and_expires_reserved_no_shows
        """
        ws = setup_run_ops_scene()
        resp = api.run_ops(ws["episode"]["id"], EOC_HEADERS)
        episode = validate_success(resp, 200)
        assert episode["ops_run_index"] == 1

        # The short 09:00-10:00 shift has ended by 14:30; the overnight lead
        # shift ends tomorrow at 06:00 and is untouched.
        shift_w = get_success_data(api.get_shift(ws["shift_worker"]["id"],
                                                 EOC_HEADERS))
        shift_lead = get_success_data(api.get_shift(ws["lead_shift"]["id"],
                                                    EOC_HEADERS))
        assert shift_w["status"] == "COMPLETED"
        assert shift_lead["status"] == "CONFIRMED"

        # Arrived 13:00, now 14:30 — the 60-minute grace has elapsed.
        stay = get_stay(ws["stay"]["id"])
        assert stay["status"] == "NO_SHOW"

        dispatch = get_dispatch(ws["dispatch"]["id"])
        assert dispatch["reserved_bed_count"] == 0

        sa = get_site_activation(ws["site_activation"]["id"])
        assert sa["reserved_beds"] == 0
        assert sa["beds_free"] == 4
        assert_bed_conservation(sa)


class TestSiteCloseGate:
    def test_site_close_blocked_until_last_stay_checked_out_then_episode_deactivates(
            self, api):
        """PRD §3.2: "Closing is a `SiteLead` action available from `OPENING`
        or `DRAINING`, and only when no stay of the activation remains in
        `RESERVED` or `CHECKED_IN` — otherwise the close is rejected with
        `ERR_STAYS_STILL_ACTIVE`. A successful close moves the activation to
        `CLOSED` and cancels every one of its shifts still `PLANNED` or
        `CONFIRMED`. When the episode is `DEACTIVATING` and this close removes
        the last non-closed activation, the episode itself settles to
        `DEACTIVATED` immediately, without waiting for an ops sweep."

        Design: Corner/state_machines/site_close_blocked_until_last_stay_checked_out_then_episode_deactivates
        """
        ws = setup_draining_site_with_checked_in_guest()
        sa_id = ws["site_activation"]["id"]

        blocked = api.close_site_activation(sa_id, ws["lead1_headers"])
        validate_error(blocked, ApiErrorId.ERR_STAYS_STILL_ACTIVE,
                       expected_status=409)

        validate_success(api.check_out_stay(ws["stay"]["id"], INTAKE_HEADERS),
                         200)
        closed = api.close_site_activation(sa_id, ws["lead1_headers"])
        assert validate_success(closed, 200)["status"] == "CLOSED"

        # The last non-closed activation closed: the episode settles at once.
        assert get_episode(ws["episode"]["id"])["status"] == "DEACTIVATED"
