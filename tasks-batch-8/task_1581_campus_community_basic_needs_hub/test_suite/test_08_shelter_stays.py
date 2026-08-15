"""Shelter coordination: PET sanitation buffer, client night intersection,
window-vs-overlap ordering, no-show strikes, and operational error codes."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_bed,
    create_coordinator,
    create_reserved_stay,
    create_shelter_coordinator,
    create_shelter_eligible_client,
    create_shelter_stay_payload,
    create_active_client,
    run_sweeps,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["hub_admin_headers"]


def _two_eligible_clients(coord):
    c1, _, _ = create_shelter_eligible_client(coord, alias="jay")
    c2, _, _ = create_shelter_eligible_client(
        coord, alias="kai", monthly_income_cents=5000, food_insecurity_score=5,
    )
    return c1, c2


class TestPetFriendlyBedBuffer:
    def _setup_beds_and_stays(self):
        """Plain bed N1 and PET_FRIENDLY bed P1 each hold a stay
        [2026-08-10, +2 nights) — checkout 2026-08-12; the PET bed's buffer
        runs to 2026-08-13."""
        _, coord = create_coordinator()
        _, shelter = create_shelter_coordinator()
        c1, c2 = _two_eligible_clients(coord)
        bed_n = create_bed(shelter, site="Haven", label="N1")
        bed_p = create_bed(shelter, site="Haven", label="P1",
                           features=["PET_FRIENDLY"])
        s_n = create_reserved_stay(c1["id"], bed_n["id"], shelter)
        s_p = create_reserved_stay(c2["id"], bed_p["id"], shelter)
        return coord, shelter, c1, c2, bed_n, bed_p, s_n, s_p

    def test_plain_bed_allows_back_to_back_turnover(self, api):
        """PRD §3.6: "Back-to-back turnover — the new check-in landing exactly
        on the existing stay's checkout date — is allowed on an ordinary bed,
        because the buffer equals the checkout date ..."

        Design: Difficulty/resource_temporal_overlap/pet_friendly_bed_sanitation_buffer_blocks_turnover_day
        """
        _, shelter, c1, _, bed_n, _, _, _ = self._setup_beds_and_stays()
        turnover = create_reserved_stay(
            c1["id"], bed_n["id"], shelter,
            check_in_date="2026-08-12", planned_nights=1,
        )
        assert turnover["status"] == "RESERVED", (
            "check-in on the prior stay's checkout day is free on a plain bed"
        )

    def test_pet_bed_buffer_blocks_turnover_day_and_expires_next_day(self, api):
        """PRD §3.6: "`buffer_until_exclusive`, one day beyond checkout for a
        `PET_FRIENDLY` bed and equal to checkout otherwise."
        PRD §3.6: "on a `PET_FRIENDLY` bed the next check-in must be at least
        one day after checkout, the sanitation buffer."
        PRD §3.6: "The bed must be free for the requested interval under the
        bed rule below (else `ERR_BED_NOT_AVAILABLE`)."

        Design: Difficulty/resource_temporal_overlap/pet_friendly_bed_sanitation_buffer_blocks_turnover_day
        """
        _, shelter, _, c2, _, bed_p, _, s_p = self._setup_beds_and_stays()
        assert s_p["check_out_exclusive"] == "2026-08-12"
        assert s_p["buffer_until_exclusive"] == "2026-08-13"

        res = api.create_shelter_stay(
            c2["id"],
            create_shelter_stay_payload(
                bed_p["id"], check_in_date="2026-08-12", planned_nights=1
            ),
            shelter,
        )
        validate_error(res, ApiErrorId.ERR_BED_NOT_AVAILABLE, expected_status=409)

        after_buffer = create_reserved_stay(
            c2["id"], bed_p["id"], shelter,
            check_in_date="2026-08-13", planned_nights=1,
        )
        assert after_buffer["status"] == "RESERVED", (
            "the half-open edge at buffer_until is free"
        )


class TestClientNightIntersection:
    def _setup_client_with_stay(self):
        _, coord = create_coordinator()
        _, shelter = create_shelter_coordinator()
        client, _, _ = create_shelter_eligible_client(
            coord, alias="noa", housing_status="UNSTABLE",
            food_insecurity_score=5,
        )
        bed_a = create_bed(shelter, site="Haven", label="A1")
        bed_b = create_bed(shelter, site="Haven", label="B1")
        s1 = create_reserved_stay(client["id"], bed_a["id"], shelter)
        return shelter, client, bed_a, bed_b, s1

    def test_shared_night_rejected_as_client_overlap(self, api):
        """PRD §3.6: "a client's nights are the closed set from `check_in_date`
        through the day before `check_out_exclusive`, and a new stay for the
        same client conflicts with an existing `RESERVED` or `OCCUPIED` stay
        when their night sets intersect."
        PRD §3.6: "The client must have no intersecting nights under the
        client rule below (else `ERR_CLIENT_STAY_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/client_double_booking_night_intersection_with_turnover_allowed
        """
        shelter, client, _, bed_b, s1 = self._setup_client_with_stay()
        res = api.create_shelter_stay(
            client["id"],
            create_shelter_stay_payload(
                bed_b["id"], check_in_date="2026-08-11", planned_nights=1
            ),
            shelter,
        )
        validate_error(res, ApiErrorId.ERR_CLIENT_STAY_OVERLAP, expected_status=409)

    def test_checkout_day_turnover_allowed_for_client(self, api):
        """PRD §3.6: "Same-day turnover — checking in on the day the previous
        stay checks out — is therefore allowed for the client, whose nights do
        not intersect ..."

        Design: Difficulty/resource_temporal_overlap/client_double_booking_night_intersection_with_turnover_allowed
        """
        shelter, client, _, bed_b, s1 = self._setup_client_with_stay()
        s2 = create_reserved_stay(
            client["id"], bed_b["id"], shelter,
            check_in_date="2026-08-12", planned_nights=1,
        )
        assert s2["status"] == "RESERVED", (
            "night sets {08-10, 08-11} and {08-12} are disjoint"
        )
        stays = validate_success(
            api.list_shelter_stays(shelter, params={"client_id": client["id"]}), 200
        )
        assert {s["status"] for s in stays} == {"RESERVED"}
        assert len(stays) == 2


class TestWindowBeatsOverlap:
    def _setup(self):
        """Bed B1 holds a RESERVED stay [2026-08-14, +2 nights); the clock is
        at the 2026-08-01 default, so 2026-08-14 is the horizon edge."""
        _, coord = create_coordinator()
        _, shelter = create_shelter_coordinator()
        c1, c2 = _two_eligible_clients(coord)
        bed = create_bed(shelter, site="Haven House", label="B1")
        create_reserved_stay(c2["id"], bed["id"], shelter,
                             check_in_date="2026-08-14", planned_nights=2)
        return shelter, c1, bed

    def test_booking_horizon_violation_reports_window_not_overlap(self, api):
        """PRD §3.6: "The stay window must be sane: `check_in_date` within the
        booking horizon from the logical today through 13 days ahead
        inclusive, and `planned_nights` between 1 and 14 inclusive, with
        violations rejected as `ERR_STAY_WINDOW_INVALID`. Placement then
        checks the bed and the client."

        Design: Difficulty/priority_pair_validation_conflict/stay_create_temporal_window_beats_bed_overlap
        """
        shelter, c1, bed = self._setup()
        # 2026-08-15 is 14 days beyond logical today — and also collides with
        # the existing [2026-08-14, +2) stay. The window rule is checked first.
        res = api.create_shelter_stay(
            c1["id"],
            create_shelter_stay_payload(
                bed["id"], check_in_date="2026-08-15", planned_nights=2
            ),
            shelter,
        )
        validate_error(res, ApiErrorId.ERR_STAY_WINDOW_INVALID, expected_status=422)

    def test_window_valid_overlap_reports_bed_unavailable(self, api):
        """PRD §3.6: "The bed must be free for the requested interval under
        the bed rule below (else `ERR_BED_NOT_AVAILABLE`)."
        PRD §3.6: "`check_in_date` within the booking horizon from the logical
        today through 13 days ahead inclusive".

        Design: Difficulty/priority_pair_validation_conflict/stay_create_temporal_window_beats_bed_overlap
        """
        shelter, c1, bed = self._setup()
        # 2026-08-14 is exactly 13 days out — inside the horizon — so the bed
        # rule is what fires.
        res = api.create_shelter_stay(
            c1["id"],
            create_shelter_stay_payload(
                bed["id"], check_in_date="2026-08-14", planned_nights=1
            ),
            shelter,
        )
        validate_error(res, ApiErrorId.ERR_BED_NOT_AVAILABLE, expected_status=409)


def test_two_no_show_strikes_restrict_third_booking(api):
    """PRD §3.6: "A stay still `RESERVED` once the logical date has moved past
    the day after its `check_in_date` flips to `NO_SHOW` with
    `no_show_marked_at` stamped at the logical now. Each no-show recomputes
    the client's `shelter_no_show_count_90d`; when that count reaches 2, the
    client's `shelter_restricted` becomes true, and subsequent stay creation
    is rejected with `ERR_SHELTER_RESTRICTED`."

    Design: Corner/state_machines/two_no_show_strikes_restrict_third_booking
    """
    _, coord = create_coordinator()
    _, shelter = create_shelter_coordinator()
    client, _, _ = create_shelter_eligible_client(coord, alias="ns")
    bed = create_bed(shelter, site="Haven", label="B1")

    create_reserved_stay(client["id"], bed["id"], shelter,
                         check_in_date="2026-08-02", planned_nights=1)
    set_clock("2026-08-04T00:00:00Z")
    sweep1 = run_sweeps()
    assert sweep1["stays_marked_no_show"] == 1

    create_reserved_stay(client["id"], bed["id"], shelter,
                         check_in_date="2026-08-05", planned_nights=1)
    set_clock("2026-08-07T00:00:00Z")
    sweep2 = run_sweeps()
    assert sweep2["stays_marked_no_show"] == 1

    client_after = validate_success(api.get_client(client["id"], shelter), 200)
    assert client_after["shelter_no_show_count_90d"] == 2
    assert client_after["shelter_restricted"] is True

    res = api.create_shelter_stay(
        client["id"],
        create_shelter_stay_payload(bed["id"], check_in_date="2026-08-10",
                                    planned_nights=1),
        shelter,
    )
    validate_error(res, ApiErrorId.ERR_SHELTER_RESTRICTED, expected_status=409)


def test_stay_checkin_outside_arrival_window(api):
    """PRD §3.6: "the logical date must be the `check_in_date` or the day
    immediately after it (else `ERR_STAY_WINDOW_INVALID`)".
    PRD §2.4: "Advancing the clock does not by itself fire any automatic
    transition; time-driven transitions are evaluated only when the second
    capability, the **sweep checkpoint**, is invoked."

    Design: Corner/validations/stay_checkin_outside_arrival_window
    """
    _, coord = create_coordinator()
    _, shelter = create_shelter_coordinator()
    client, _, _ = create_shelter_eligible_client(coord, alias="win")
    bed = create_bed(shelter, site="Haven", label="W1")
    stay = create_reserved_stay(client["id"], bed["id"], shelter,
                                check_in_date="2026-08-01", planned_nights=3)

    set_clock("2026-08-03T08:00:00Z")
    res = api.shelter_stay_check_in(stay["id"], shelter)
    validate_error(res, ApiErrorId.ERR_STAY_WINDOW_INVALID, expected_status=422)

    stay_after = validate_success(api.get_shelter_stay(stay["id"], shelter), 200)
    assert stay_after["status"] == "RESERVED", (
        "no sweep ran — no implicit NO_SHOW"
    )


def test_shelter_operational_errors_batch(api):
    """PRD §3.6: "The bed must be `AVAILABLE` (else `ERR_BED_OUT_OF_SERVICE`)."
    PRD §3.6: "the verified assessment's `housing_status` must be `UNSTABLE`
    or `HOMELESS`; a `STABLE` or `COST_BURDENED` household is not
    shelter-eligible and is rejected with `ERR_NOT_HOUSING_INSECURE`."
    PRD §3.6: "marking a bed `OUT_OF_SERVICE` while a stay is `OCCUPIED` on it
    is rejected with `ERR_BED_OCCUPIED`."
    PRD §3.6: "Departure is marked by checking out: the stay must be
    `OCCUPIED` (else `ERR_STAY_NOT_ACTIONABLE`) ..."

    Design: Corner/errors/shelter_operational_errors_batch
    """
    _, coord = create_coordinator()
    _, shelter = create_shelter_coordinator()
    client_h, _, _ = create_shelter_eligible_client(coord, alias="h")
    client_s, _, _ = create_active_client(
        coord, client_overrides={"alias_name": "s"}
    )
    bed_x = create_bed(shelter, site="Haven", label="X1")
    bed_y = create_bed(shelter, site="Haven", label="Y1")

    stay_x = create_reserved_stay(client_h["id"], bed_x["id"], shelter,
                                  check_in_date="2026-08-01", planned_nights=2)
    occupied = validate_success(api.shelter_stay_check_in(stay_x["id"], shelter), 200)
    assert occupied["status"] == "OCCUPIED"

    stay_y = create_reserved_stay(client_h["id"], bed_y["id"], shelter,
                                  check_in_date="2026-08-10", planned_nights=1)
    validate_success(
        api.patch_shelter_bed(bed_y["id"], {"status": "OUT_OF_SERVICE"}, shelter), 200
    )

    res = api.create_shelter_stay(
        client_h["id"],
        create_shelter_stay_payload(bed_y["id"], check_in_date="2026-08-12",
                                    planned_nights=1),
        shelter,
    )
    validate_error(res, ApiErrorId.ERR_BED_OUT_OF_SERVICE, expected_status=409)

    res = api.create_shelter_stay(
        client_s["id"],
        create_shelter_stay_payload(bed_x["id"], check_in_date="2026-08-10",
                                    planned_nights=1),
        shelter,
    )
    validate_error(res, ApiErrorId.ERR_NOT_HOUSING_INSECURE, expected_status=422)

    res = api.patch_shelter_bed(bed_x["id"], {"status": "OUT_OF_SERVICE"}, shelter)
    validate_error(res, ApiErrorId.ERR_BED_OCCUPIED, expected_status=409)

    res = api.shelter_stay_check_out(stay_y["id"], shelter)
    validate_error(res, ApiErrorId.ERR_STAY_NOT_ACTIONABLE, expected_status=409)
