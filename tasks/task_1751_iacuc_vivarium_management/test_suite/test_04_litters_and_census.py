"""Breeding litters and the daily census: weaning-age boundary, pup
reassignment, nursing-pup capacity exemption flip, census system-count
filtering, and the census gate on provisional billing (PRD §3.4, §3.5,
§3.6, §3.7).
"""
from test_helpers import (
    BILLING,
    FACILITY,
    STAFF,
    VET,
    ApiErrorId,
    api_client,
    assert_census_record,
    assert_litter,
    file_census,
    get_success_data,
    set_clock,
    setup_breeding_cage,
    setup_occupied_cage,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import compute_provisional_ok, create_billing_run


class TestWeanAgeBoundary:
    def test_wean_one_second_early_rejected_then_boundary_succeeds(self, api):
        """PRD §3.5: "Weaning becomes available once the logical clock reaches
        `born_on` plus 21 days; an earlier attempt is rejected with
        `ERR_LITTER_TOO_YOUNG` (HTTP 422), and a litter no longer `NURSING`
        rejects the attempt with `ERR_INVALID_STATE`."

        Design: Difficulty/boundary_precision_check/wean_age_exact_21_day_boundary
        """
        scenario = setup_breeding_cage(pup_count=4, capacity_adults=2,
                                       target_capacity=5)
        litter = scenario["litter"]
        assert litter["state"] == "NURSING"

        set_clock("2026-08-21T23:59:59Z")
        resp = api_client.wean_litter(
            litter["id"], {"target_cage_ids": [scenario["wean_cage"]["id"]]}, STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_LITTER_TOO_YOUNG)

        set_clock("2026-08-22T00:00:00Z")
        weaned = validate_success(api_client.wean_litter(
            litter["id"], {"target_cage_ids": [scenario["wean_cage"]["id"]]}, STAFF,
        ))
        assert_litter(weaned)
        assert weaned["state"] == "WEANED", (
            "weaning at exactly born_on + 21 days is allowed"
        )
        assert weaned["weaned_count"] == 4, (
            "weaning sets weaned_count to the full pup_count"
        )

    def test_wean_reassigns_pups_to_target_cages(self, api):
        """PRD §3.5: "Weaning moves the litter from `NURSING` to `WEANED` and
        sets `weaned_count` to the full `pup_count`; every pup's `cage_id` is
        reassigned to the standard cages named in the request's
        `target_cage_ids`, each target cage must absorb its newcomers within
        `capacity_adults` (else `ERR_CAGE_OVER_CAPACITY`), and the source and
        target cages are all recomputed."

        Design: Difficulty/boundary_precision_check/wean_age_exact_21_day_boundary
        """
        scenario = setup_breeding_cage(pup_count=4, capacity_adults=2,
                                       target_capacity=5)
        litter = scenario["litter"]
        # At born_on + 22 days the pups count toward capacity (PRD §3.4: "A
        # nursing pup ... begins counting on day twenty-two"), so the target
        # cage's effective occupancy is 4 and it must read OCCUPIED.
        set_clock("2026-08-23T00:00:00Z")
        validate_success(api_client.wean_litter(
            litter["id"], {"target_cage_ids": [scenario["wean_cage"]["id"]]}, STAFF,
        ))

        pups = get_success_data(
            api_client.list_litter_animals(litter["id"], STAFF)
        )
        assert len(pups) == 4
        for pup in pups:
            assert pup["cage_id"] == scenario["wean_cage"]["id"], (
                "every pup is reassigned to the target standard cage"
            )
            assert pup["status"] == "ALIVE"

        target = get_success_data(
            api_client.get_cage(scenario["wean_cage"]["id"], FACILITY)
        )
        assert target["status"] == "OCCUPIED"


class TestNursingPupCapacityExemption:
    def test_pup_cap_exemption_flips_on_day_22(self, api):
        """PRD §3.4: "A nursing pup is exempt from the count through its
        twenty-first day of age and begins counting on day twenty-two." and
        "Whenever effective occupancy exceeds `capacity_adults` the cage
        becomes `OVER_CAPACITY` and accepts no further animal additions;
        whenever effective occupancy falls to zero the cage becomes `EMPTY`;
        otherwise a cage holding animals reads `OCCUPIED`".

        Design: Corner/calculations/pup_cap_exemption_day22_flip
        """
        scenario = setup_breeding_cage(pup_count=8, capacity_adults=5,
                                       target_capacity=5)
        cage_id = scenario["cage"]["id"]

        set_clock("2026-08-22T00:00:00Z")
        cage = get_success_data(api_client.get_cage(cage_id, STAFF))
        assert cage["status"] == "OCCUPIED", (
            "at pup age 21 the 8 pups are still exempt: 2 adults <= 5"
        )

        set_clock("2026-08-23T00:00:00Z")
        cage = get_success_data(api_client.get_cage(cage_id, STAFF))
        assert cage["status"] == "OVER_CAPACITY", (
            "on day 22 the pups count: effective occupancy 10 > 5"
        )


class TestCensusSystemCount:
    def test_system_count_excludes_non_alive_animals(self, api):
        """PRD §3.6: "The server computes `system_count` — the number of
        animals whose `cage_id` is this cage and whose `status` is `ALIVE` on
        that census date — and `discrepancy`, the physical count minus the
        system count."

        Design: Corner/calculations/census_system_count_excludes_non_alive
        """
        scenario = setup_occupied_cage(num_animals=3, capacity_adults=5)
        cage_id = scenario["cage"]["id"]
        get_success_data(
            api_client.euthanize_animal(scenario["animals"][0]["id"], VET)
        )

        record = file_census(cage_id, "2026-08-10T00:00:00Z", 2)
        assert_census_record(record)
        assert record["system_count"] == 2, (
            "the euthanized animal is excluded from system_count"
        )
        assert record["discrepancy"] == 0

        record2 = file_census(cage_id, "2026-08-11T00:00:00Z", 3)
        assert record2["system_count"] == 2
        assert record2["discrepancy"] == 1, (
            "discrepancy is physical_count minus system_count"
        )


class TestCensusGateOnBilling:
    def test_discrepant_census_blocks_provisional_computation(self, api):
        """PRD §3.7: "If any census record in the run's period carries a
        nonzero `discrepancy`, the attempt is rejected with
        `ERR_CENSUS_DISCREPANCY` (HTTP 422), the reason is recorded in the
        run's `hold_reason`, and the run remains `DRAFT`."

        Design: Difficulty/cross_entity_state_dependency/billing_finalize_gated_by_census_clean
        """
        scenario = setup_occupied_cage(num_animals=1)
        cage_id = scenario["cage"]["id"]

        record = file_census(cage_id, "2026-08-10T00:00:00Z", 2)
        assert record["discrepancy"] == 1, "physical 2 vs system 1"

        run = create_billing_run("2026-08-01T00:00:00Z", "2026-08-22T00:00:00Z")
        resp = api_client.compute_provisional(run["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_CENSUS_DISCREPANCY)

        current = get_success_data(api_client.get_billing_run(run["id"], BILLING))
        assert current["state"] == "DRAFT"
        assert isinstance(current.get("hold_reason"), str) and current["hold_reason"], (
            "the reason is recorded in the run's hold_reason"
        )

    def test_clean_census_allows_provisional_computation(self, api):
        """PRD §3.7: "Otherwise the run advances to `PROVISIONAL` and the
        system creates one per-diem charge of `variant` `PROVISIONAL` for
        every cage occupied during the period, each charge linked by
        `billing_run_id`, `cage_id`, `protocol_id`, and the `grant_id` to be
        debited at posting."

        Design: Difficulty/cross_entity_state_dependency/billing_finalize_gated_by_census_clean
        """
        scenario = setup_occupied_cage(num_animals=1)
        cage_id = scenario["cage"]["id"]
        file_census(cage_id, "2026-08-01T00:00:00Z", 1)

        run = create_billing_run("2026-08-01T00:00:00Z", "2026-08-22T00:00:00Z")
        run = compute_provisional_ok(run["id"])
        assert run["state"] == "PROVISIONAL"

        charges = get_success_data(
            api_client.list_billing_run_charges(run["id"], BILLING)
        )
        assert len(charges) == 1
        charge = charges[0]
        assert charge["variant"] == "PROVISIONAL"
        assert charge["cage_id"] == cage_id
        assert charge["protocol_id"] == scenario["protocol"]["id"]
        assert charge["grant_id"] == scenario["grant"]["id"]

