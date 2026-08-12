"""Difficulty: boundary_precision_check — amps, review rounds, slot vehicles at the boundary."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_application,
    advance_festival,
    api_client,
    book_reservation,
    create_assignment,
    create_booth,
    create_slot,
    create_vendor,
    decide_application,
    get_application,
    get_slot,
    get_zone,
    make_vendor_headers,
    make_vendor_spec,
    request_changes,
    setup_curated_multi,
    setup_open_festival,
    setup_submitted_application,
    start_review,
    submit_application,
    validate_error,
    validate_success,
)

VM = TEST_USERS["vendor_manager_headers"]
OPS = TEST_USERS["ops_headers"]


def _setup_amp_festival():
    """Zone 100A; ACCEPTED applications A FOOD_HOT (60A), B FOOD_COLD (40A),
    C MERCHANDISE (1A); festival CURATED; three booths (outlet 60 each)."""
    scen = setup_open_festival(name="Amp Fest", zone_power=100, zone_water=2)
    fest_id = scen["festival"]["id"]
    vendors, apps = [], []
    for name, cat, amps, fee in (("Amp A", "FOOD_HOT", 60, 50000),
                                 ("Amp B", "FOOD_COLD", 40, 40000),
                                 ("Amp C", "MERCHANDISE", 1, 30000)):
        v = create_vendor(legal_name=name, contact_email=f"{name.replace(' ', '')}@amp.com")
        app = submit_application(v, fest_id, category=cat, power_needed_amps=amps,
                                 proposed_flat_fee_cents=fee)
        start_review(app["id"])
        app = accept_application(app["id"], "FLAT_FEE", flat_fee_cents=fee)
        vendors.append(v)
        apps.append(app)
    advance_festival(fest_id, "CURATED")
    booths = [create_booth(scen["zone"]["id"], label=f"N-0{i + 1}") for i in range(3)]
    scen.update({"vendors": vendors, "apps": apps, "booths": booths})
    return scen


class TestZonePowerBoundary:
    def test_landing_exactly_on_capacity_is_admitted(self, api):
        """PRD §3.3: "Zone utility admission is inclusive at the boundary. The
        create is rejected with `ERR_POWER_CAPACITY_EXCEEDED` only when the
        zone's `reserved_power_amps` plus the new `power_draw_amps` would exceed
        `power_capacity_amps` — landing exactly on capacity is allowed".

        Design: Difficulty/boundary_precision_check/zone_power_exact_capacity_admitted
        """
        scen = _setup_amp_festival()
        asg_a = create_assignment(scen["apps"][0]["id"], scen["booths"][0]["id"], power_draw_amps=60)
        asg_b = create_assignment(scen["apps"][1]["id"], scen["booths"][1]["id"], power_draw_amps=40)
        assert asg_a["status"] == "RESERVED" and asg_b["status"] == "RESERVED"
        assert get_zone(scen["zone"]["id"])["reserved_power_amps"] == 100, "60 + 40 == 100 == capacity"

    def test_one_amp_over_capacity_is_rejected_and_changes_nothing(self, api):
        """PRD §3.3: "The create is rejected with `ERR_POWER_CAPACITY_EXCEEDED`
        only when the zone's `reserved_power_amps` plus the new `power_draw_amps`
        would exceed `power_capacity_amps`".

        Design: Difficulty/boundary_precision_check/zone_power_exact_capacity_admitted
        """
        scen = _setup_amp_festival()
        create_assignment(scen["apps"][0]["id"], scen["booths"][0]["id"], power_draw_amps=60)
        create_assignment(scen["apps"][1]["id"], scen["booths"][1]["id"], power_draw_amps=40)
        resp = api.create_assignment(
            {"application_id": scen["apps"][2]["id"], "booth_id": scen["booths"][2]["id"],
             "power_draw_amps": 1, "requires_water": False},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_POWER_CAPACITY_EXCEEDED)  # 101 > 100 crosses
        assert get_zone(scen["zone"]["id"])["reserved_power_amps"] == 100, "failed reservation changed nothing"


def _drive_three_revision_loops():
    """Application cycled through three full revision loops; the fourth
    submission sits UNDER_REVIEW with review_round == 3."""
    scen = setup_submitted_application(name="Rounds Fest")
    current = scen["app"]
    for _ in range(3):
        start_review(current["id"])
        request_changes(current["id"])
        resp = api_client.create_application(
            {"vendor_id": scen["vendor"]["id"], "festival_id": scen["festival"]["id"],
             "category": "FOOD_HOT", "fee_model": "FLAT_FEE", "proposed_flat_fee_cents": 50000,
             "power_needed_amps": 20, "requires_water": False,
             "supersedes_application_id": current["id"]},
            make_vendor_headers(scen["vendor"]["id"]),
        )
        current = validate_success(resp, expected_status=201)
    current = start_review(current["id"])
    scen["app"] = current
    return scen


class TestReviewRoundCap:
    def test_three_resubmissions_land_at_round_three(self, api):
        """PRD §3.2: "on success the source moves to `SUPERSEDED` and the new
        application enters `SUBMITTED` with `review_round` set to the source's
        round plus one."

        Design: Difficulty/boundary_precision_check/review_round_cap_at_three
        """
        scen = _drive_three_revision_loops()
        assert scen["app"]["review_round"] == 3, "three resubmissions landed"
        assert scen["app"]["status"] == "UNDER_REVIEW"

    def test_request_changes_at_round_three_is_rejected(self, api):
        """PRD §3.2: "this loop is bounded — requesting changes when
        `review_round` has already reached 3 is rejected with
        `ERR_REVIEW_ROUND_LIMIT`."

        Design: Difficulty/boundary_precision_check/review_round_cap_at_three
        """
        scen = _drive_three_revision_loops()
        resp = api.request_changes(scen["app"]["id"], {}, VM)
        validate_error(resp, ApiErrorId.ERR_REVIEW_ROUND_LIMIT)  # 3 < 3 is false
        assert get_application(scen["app"]["id"])["status"] == "UNDER_REVIEW", (
            "rejected request changed nothing"
        )


class TestSlotVehicleBoundary:
    def _setup_slot_fest(self):
        specs = [
            make_vendor_spec("Slot A", "FOOD_HOT"),
            make_vendor_spec("Slot B", "FOOD_COLD"),
            make_vendor_spec("Slot C", "DESSERT"),
        ]
        scen = setup_curated_multi(specs, name="Slot Fest", zone_power=300, zone_water=3)
        slot = create_slot(scen["festival"]["id"], max_vehicles=3)
        return scen, slot

    def test_slot_aggregate_capacity_inclusive_boundary(self, api):
        """PRD §3.5: "Capacity admission is inclusive at the boundary: the
        booking is rejected with `ERR_SLOT_CAPACITY_EXCEEDED` only when the
        slot's reserved count plus the new `vehicle_count` would exceed
        `max_vehicles`."

        Design: Difficulty/boundary_precision_check/slot_vehicle_exact_capacity_admitted
        """
        scen, slot = self._setup_slot_fest()
        asg_a, asg_b, _ = scen["assignments"]
        ra = book_reservation(asg_a["id"], slot["id"], vehicle_count=2)
        rb = book_reservation(asg_b["id"], slot["id"], vehicle_count=1)
        assert ra["status"] == "BOOKED" and rb["status"] == "BOOKED", "2 + 1 == 3 == max admitted"
        assert get_slot(slot["id"])["reserved_vehicle_count"] == 3

    def test_one_vehicle_over_capacity_is_rejected_and_changes_nothing(self, api):
        """PRD §3.5: "the booking is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`
        only when the slot's reserved count plus the new `vehicle_count` would
        exceed `max_vehicles`."

        Design: Difficulty/boundary_precision_check/slot_vehicle_exact_capacity_admitted
        """
        scen, slot = self._setup_slot_fest()
        asg_a, asg_b, asg_c = scen["assignments"]
        book_reservation(asg_a["id"], slot["id"], vehicle_count=2)
        book_reservation(asg_b["id"], slot["id"], vehicle_count=1)
        resp = api.create_reservation(
            {"assignment_id": asg_c["id"], "slot_id": slot["id"], "vehicle_count": 1}, OPS
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED)  # the 4th vehicle crosses
        assert get_slot(slot["id"])["reserved_vehicle_count"] == 3, "failed booking changed nothing"
