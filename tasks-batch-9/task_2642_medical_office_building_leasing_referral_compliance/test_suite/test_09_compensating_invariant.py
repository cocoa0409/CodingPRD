"""Two conserved pools: the building's rentable area and its parking stalls."""
from test_helpers import assert_mix_figures, assert_parking_counters, validate_paginated
from test_helpers import fixtures as fx
from test_helpers.test_users import PROPERTY_MANAGER


def _certified_independent_lease(api):
    """One 5000 sf exam suite let to an independent practice, certified and unexecuted."""
    return fx.certified_lease(
        api,
        tenant_overrides={"legal_name": "Northgate Medical Group PC",
                          "affiliation": "INDEPENDENT_PRACTICE",
                          "primary_specialty": "GASTROENTEROLOGY"},
        lease_overrides={"term_start": "2026-09-01", "term_end": "2029-08-31",
                         "base_rent_psf_annual": 30.00},
    )


def test_execution_and_commencement_move_area_between_the_two_conserved_partners(api):
    """The 5000 sf leaves the vacant side and joins the leased side without changing the total.

    PRD: "`leased_rentable_sf` is the sum of those two figures, and `vacant_rentable_sf` is the
    building's `total_rentable_sf` less `leased_rentable_sf` — the two are conserved partners and
    must always add back to `total_rentable_sf`."

    PRD: "A building's `leased_rentable_sf` plus its `vacant_rentable_sf` equals
    `total_rentable_sf`."

    PRD: "Leases in `DRAFT`, `PENDING_FMV_REVIEW`, `SUSPENDED_MIX_REVIEW`, `FMV_CERTIFIED`,
    `TERMINATED` and `WITHDRAWN` are all excluded as well — a certified lease holds no area until
    it is executed."

    Design: Difficulty/compensating_invariant/rentable_square_footage_conserved_across_execute_and_terminate
    """
    ctx = _certified_independent_lease(api)
    lease_id = ctx["lease"]["id"]

    before = fx.read_building(api, ctx["building"]["id"])
    assert before["total_rentable_sf"] == 100000
    assert_mix_figures(before, anchor_sf=0, independent_sf=0, leased_sf=0, vacant_sf=100000,
                       anchor_share_pct=0.0000, posture="BALANCED")
    assert before["leased_rentable_sf"] + before["vacant_rentable_sf"] == 100000

    fx.execute(api, lease_id, "Independent practice signed")
    executed_view = fx.read_building(api, ctx["building"]["id"])
    assert_mix_figures(executed_view, anchor_sf=0, independent_sf=5000, leased_sf=5000,
                       vacant_sf=95000, anchor_share_pct=0.0000, posture="BALANCED")
    assert executed_view["leased_rentable_sf"] + executed_view["vacant_rentable_sf"] == 100000
    assert fx.read_suite(api, ctx["suite"]["id"])["occupancy_status"] == "RESERVED"

    fx.set_clock_date(api, "2026-09-01")
    fx.commence(api, lease_id, "Practice takes occupancy")
    active_view = fx.read_building(api, ctx["building"]["id"])
    assert_mix_figures(active_view, anchor_sf=0, independent_sf=5000, leased_sf=5000,
                       vacant_sf=95000, anchor_share_pct=0.0000, posture="BALANCED")
    assert active_view["leased_rentable_sf"] + active_view["vacant_rentable_sf"] == 100000
    assert fx.read_suite(api, ctx["suite"]["id"])["occupancy_status"] == "OCCUPIED"


def test_termination_restores_the_exact_figures_the_building_held_before_execution(api):
    """The round trip is exactly compensating: every one of the six figures comes back.

    PRD: "**Hop 1** stamps `terminated_on` with the clock date, moves the demised suite to
    `VACANT`, sets that suite's `last_vacated_on` to the clock date and advances the suite's
    `version`."

    PRD: "`leased_rentable_sf` is the sum of those two figures, and `vacant_rentable_sf` is the
    building's `total_rentable_sf` less `leased_rentable_sf` — the two are conserved partners and
    must always add back to `total_rentable_sf`."

    Design: Difficulty/compensating_invariant/rentable_square_footage_conserved_across_execute_and_terminate
    """
    ctx = _certified_independent_lease(api)
    lease_id = ctx["lease"]["id"]
    pristine = fx.read_building(api, ctx["building"]["id"])

    fx.execute(api, lease_id, "Independent practice signed")
    fx.set_clock_date(api, "2026-09-01")
    fx.commence(api, lease_id, "Practice takes occupancy")

    terminated = fx.terminate(api, lease_id, "MUTUAL",
                              termination_note="Practice relocated by agreement")
    assert terminated["status"] == "TERMINATED"
    assert terminated["terminated_on"] == "2026-09-01"

    suite = fx.read_suite(api, ctx["suite"]["id"])
    assert suite["occupancy_status"] == "VACANT"
    assert suite["last_vacated_on"] == "2026-09-01"

    after = fx.read_building(api, ctx["building"]["id"])
    assert_mix_figures(after, anchor_sf=0, independent_sf=0, leased_sf=0, vacant_sf=100000,
                       anchor_share_pct=0.0000, posture="BALANCED")
    assert after["leased_rentable_sf"] + after["vacant_rentable_sf"] == 100000
    for figure in ("anchor_rentable_sf", "independent_rentable_sf", "leased_rentable_sf",
                   "vacant_rentable_sf", "tenant_mix_posture"):
        assert after[figure] == pristine[figure], (
            "{} did not return to its pre-execution value".format(figure))


def _building_with_an_active_lease(api):
    """A 400-stall building whose pool is untouched, with one ACTIVE lease to allocate against."""
    ctx = fx.active_lease(api)
    building = fx.read_building(api, ctx["building"]["id"])
    assert building["total_parking_stalls"] == 400
    assert_parking_counters(building, staff=0, patient=0, unallocated=400)
    return ctx


def test_two_allocations_draw_the_pool_down_without_changing_the_stall_total(api):
    """Staff and patient allocations each move stalls out of the unallocated bucket only.

    PRD: "A `PropertyManager` allocates stalls by supplying `expected_building_version` together
    with the `building_id`, the `lease_id` receiving the stalls, a `category` of `STAFF` or
    `PATIENT`, and a `stall_count` of at least 1; the allocation is created in `ACTIVE`."

    PRD: "The building's three derived counters are then recomputed: `staff_allocated_stalls` is
    the summed `stall_count` of active staff allocations, `patient_allocated_stalls` the summed
    `stall_count` of active patient allocations, and `unallocated_stalls` is
    `total_parking_stalls` less those two sums."

    PRD: "A building's `staff_allocated_stalls` plus `patient_allocated_stalls` plus
    `unallocated_stalls` equals `total_parking_stalls`, and that holds after every allocation,
    every revocation and every lease-termination cascade."

    Design: Difficulty/compensating_invariant/parking_stall_pool_conserved_across_allocate_and_revoke
    """
    ctx = _building_with_an_active_lease(api)
    building_id = ctx["building"]["id"]
    lease_id = ctx["lease"]["id"]

    staff = fx.allocate_stalls(api, building_id, lease_id, "STAFF", 20)
    assert staff["status"] == "ACTIVE"
    assert staff["category"] == "STAFF"
    assert staff["stall_count"] == 20
    assert staff["revoked_on"] is None
    assert_parking_counters(fx.read_building(api, building_id), staff=20, patient=0,
                            unallocated=380)

    patient = fx.allocate_stalls(api, building_id, lease_id, "PATIENT", 30)
    assert patient["status"] == "ACTIVE"
    assert patient["stall_count"] == 30
    assert_parking_counters(fx.read_building(api, building_id), staff=20, patient=30,
                            unallocated=350)

    rows, meta = validate_paginated(
        api.list_parking_allocations(PROPERTY_MANAGER,
                                     params={"building_id": building_id, "status": "ACTIVE"}))
    assert meta["total_count"] == 2
    assert sorted(row["id"] for row in rows) == sorted([staff["id"], patient["id"]])


def test_revoking_both_allocations_returns_every_stall_to_the_pool(api):
    """The revocations exactly compensate the allocations, category by category.

    PRD: "A `PropertyManager` may revoke an allocation with an optional `revocation_note`, which
    moves it to `REVOKED`, stamps `revoked_on` with the clock date, returns the stalls to the pool
    by recomputing the three counters, and advances the building's `version`."

    PRD: "Only active allocations count, so revoked stalls are genuinely back in the pool, and the
    identity that the three counters sum to `total_parking_stalls` holds after every allocation,
    every revocation and every lease-termination cascade."

    Design: Difficulty/compensating_invariant/parking_stall_pool_conserved_across_allocate_and_revoke
    """
    ctx = _building_with_an_active_lease(api)
    building_id = ctx["building"]["id"]
    lease_id = ctx["lease"]["id"]

    staff = fx.allocate_stalls(api, building_id, lease_id, "STAFF", 20)
    patient = fx.allocate_stalls(api, building_id, lease_id, "PATIENT", 30)
    before_revocation = fx.read_building(api, building_id)

    revoked_staff = fx.revoke_allocation(api, staff["id"], "Staff parking surrendered")
    assert revoked_staff["status"] == "REVOKED"
    assert revoked_staff["revoked_on"] == "2026-09-01"
    assert_parking_counters(fx.read_building(api, building_id), staff=0, patient=30,
                            unallocated=370)

    revoked_patient = fx.revoke_allocation(api, patient["id"], "Patient parking surrendered")
    assert revoked_patient["status"] == "REVOKED"
    assert revoked_patient["revoked_on"] == "2026-09-01"

    after = fx.read_building(api, building_id)
    assert_parking_counters(after, staff=0, patient=0, unallocated=400)
    assert after["version"] > before_revocation["version"]

    rows, meta = validate_paginated(
        api.list_parking_allocations(PROPERTY_MANAGER,
                                     params={"building_id": building_id, "status": "ACTIVE"}))
    assert meta["total_count"] == 0
    assert rows == []
