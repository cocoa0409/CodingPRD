"""Batch and recipe lifecycle guards (PRD §2.10, §3.1, §3.3, §3.6)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    create_recipe_payload,
    create_crop_with_active_recipe, create_crop, create_loop_rack, create_growing_batch,
    create_batch, seed_batch, set_clock, schedule_cycle, start_cycle,
    SEED_CLOCK,
)

FM = TEST_USERS["farm_manager_headers"]
GR = TEST_USERS["grower_headers"]


def _grower_recipe(crop):
    recipe = validate_success(api_client.create_recipe(create_recipe_payload(crop["id"]), GR),
                              expected_status=201)
    return recipe


class TestBatchStateGuards:
    def test_batch_seed_twice_rejected(self, api):
        """PRD §3.3: "When a `Grower` seeds a `PLANNED` batch". PRD §2.10 tier 5:
        "The target resource's own state machine permits the transition
        (`ERR_INVALID_STATE_TRANSITION` ...)."

        Design: Corner/state_machines/batch_seed_twice_rejected
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        set_clock(SEED_CLOCK)
        batch = create_batch(crop["id"], [towers[0]["id"]])
        seed_batch(batch["id"])

        resp = api.seed_batch(batch["id"], GR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(api.get_batch(batch["id"], GR))
        assert after["production_status"] == "SEEDED"

    def test_harvest_from_terminal_failed_rejected(self, api):
        """PRD §3.3: "The harvest itself, performed by a `Grower` on a `HARVEST_READY`
        batch" and "Failing a batch ... moves `production_status` to `FAILED`". A FAILED
        batch admits no further production trigger; the lifecycle gate is
        `ERR_INVALID_STATE_TRANSITION` (PRD §2.10 tier 5).

        Design: Corner/state_machines/harvest_from_terminal_failed_rejected
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        set_clock(SEED_CLOCK)
        batch = create_batch(crop["id"], [towers[0]["id"]])
        seed_batch(batch["id"])
        validate_success(api.fail_batch(batch["id"], {"cause_category": "EQUIPMENT"}, GR))

        resp = api.harvest_batch(batch["id"],
                                 {"grade_a_lb": 10.0, "grade_b_lb": 0.0, "cull_lb": 0.0}, GR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(api.get_batch(batch["id"], GR))
        assert after["production_status"] == "FAILED"
        assert after["harvested_at"] is None, "no harvest fields may be written"

    def test_cull_creates_no_failure_report_but_fail_does(self, api):
        """PRD §3.3: "Failing a batch ... spawns a `FailureReport` in `REPORTED`" while
        culling "follows the identical state set and the same release cascade but
        produces no failure report, ending the batch at `CULLED`."

        Design: Corner/state_machines/cull_creates_no_failure_report_but_fail_does
        """
        crop, _ = create_crop_with_active_recipe()
        _, rack, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=2)
        b1 = create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)
        b2 = create_growing_batch(crop["id"], [towers[1]["id"]], seed_clock=SEED_CLOCK)

        resp_cull = api.cull_batch(b1["id"], GR)
        assert validate_success(resp_cull)["production_status"] == "CULLED"
        resp_fail = api.fail_batch(b2["id"], {"cause_category": "CLIMATE"}, GR)
        assert validate_success(resp_fail)["production_status"] == "FAILED"

        fr_culled, meta_culled = validate_paginated(api.list_batch_failure_reports(b1["id"], GR))
        assert meta_culled["total_count"] == 0, "cull must not create a FailureReport"
        fr_failed, meta_failed = validate_paginated(api.list_batch_failure_reports(b2["id"], GR))
        assert meta_failed["total_count"] == 1
        assert fr_failed[0]["report_status"] == "REPORTED"

        rack_after = validate_success(api.get_rack(rack["id"], FM))
        assert rack_after["occupied_towers"] == 0, "both endings release their towers"


class TestRecipeStateGuards:
    def test_recipe_activate_from_retired_rejected(self, api):
        """PRD §3.1: "A `Grower` activates a `DRAFT` recipe" — a retired recipe is no
        longer DRAFT, so the lifecycle gate rejects with `ERR_INVALID_STATE_TRANSITION`
        (PRD §2.10 tier 5).

        Design: Corner/state_machines/recipe_activate_from_retired_rejected
        """
        crop = create_crop(crop_code="KALE-01")
        recipe = _grower_recipe(crop)
        validate_success(api.retire_recipe(recipe["id"], GR))

        resp = api.activate_recipe(recipe["id"], {"expected_crop_version": crop["version"]}, GR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(api.get_recipe(recipe["id"], GR))
        assert after["recipe_status"] == "RETIRED"

    def test_recipe_retire_in_use_rejected(self, api):
        """PRD §3.1: "a manual retire is refused with `ERR_RECIPE_IN_USE` while any
        batch referencing that `recipe_id` remains in `PLANNED`, `SEEDED`, `GROWING`,
        `AT_RISK`, `HARVEST_READY`, or `HARVESTED`."

        Design: Corner/state_machines/recipe_retire_in_use_rejected
        """
        crop, recipe = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)

        resp = api.retire_recipe(recipe["id"], GR)
        validate_error(resp, ApiErrorId.ERR_RECIPE_IN_USE)
        after = validate_success(api.get_recipe(recipe["id"], GR))
        assert after["recipe_status"] == "ACTIVE"


class TestCropRetirement:
    def test_crop_in_use_blocks_retire(self, api):
        """PRD §3.1: "A `FarmManager` may retire a crop only when no grow batch
        references it in any of `PLANNED`, `SEEDED`, `GROWING`, `AT_RISK`,
        `HARVEST_READY`, or `HARVESTED`, and no retail contract for the crop is `ACTIVE`
        or `SUSPENDED`; either blockage surfaces as `ERR_CROP_IN_USE`."

        Design: Corner/errors/crop_in_use_blocks_retire
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        batch = create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)

        resp = api.retire_crop(crop["id"], FM)
        validate_error(resp, ApiErrorId.ERR_CROP_IN_USE)

        validate_success(api.cull_batch(batch["id"], GR))
        after = validate_success(api.retire_crop(crop["id"], FM))
        assert after["crop_status"] == "RETIRED"


class TestBatchCreationGates:
    def test_batch_create_with_retired_crop_rejected(self, api):
        """PRD §3.3: "the crop must not be `RETIRED` (`ERR_CROP_RETIRED`)".

        Design: Corner/errors/batch_create_with_retired_crop_rejected
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        validate_success(api.retire_crop(crop["id"], FM))

        resp = api.create_batch({"crop_id": crop["id"], "tower_ids": [towers[0]["id"]]}, GR)
        validate_error(resp, ApiErrorId.ERR_CROP_RETIRED)

    def test_batch_create_without_active_recipe_rejected(self, api):
        """PRD §3.3: "the crop ... must have an `ACTIVE` recipe (`ERR_NO_ACTIVE_RECIPE`)".

        Design: Corner/errors/batch_create_without_active_recipe_rejected
        """
        crop = create_crop(crop_code="KALE-01")
        _grower_recipe(crop)  # stays DRAFT, never activated
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)

        resp = api.create_batch({"crop_id": crop["id"], "tower_ids": [towers[0]["id"]]}, GR)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_RECIPE)

    def test_rack_not_operating_blocks_batch_create(self, api):
        """PRD §3.2: "Allocating onto a tower whose rack is not `OPERATING` fails with
        `ERR_RACK_NOT_OPERATING`."

        Design: Corner/validations/rack_not_operating_blocks_batch_create
        """
        crop, _ = create_crop_with_active_recipe()
        loop, rack, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        set_clock("2026-08-08T00:00:00Z")
        cycle = schedule_cycle(loop["id"], "2026-08-08T01:00:00Z", "2026-08-08T03:00:00Z")
        start_cycle(cycle["id"], "2026-08-08T01:00:00Z")

        resp = api.create_batch({"crop_id": crop["id"], "tower_ids": [towers[0]["id"]]}, GR)
        validate_error(resp, ApiErrorId.ERR_RACK_NOT_OPERATING)
        _, meta = validate_paginated(api.list_batches(GR))
        assert meta["total_count"] == 0, "no batch may be created on a held rack"


class TestRecipeActivationOcc:
    def test_occ_recipe_activate_stale_crop_version(self, api):
        """PRD §2.9: "If the supplied value does not equal the parent entity's current
        `version` — because an earlier activation, shipment creation, settlement,
        publish, or assignment has already advanced it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)". PRD §3.1: "Activation supersedes: any other
        recipe of the same crop currently `ACTIVE` is automatically moved to `RETIRED`,
        and the parent crop's `version` is incremented by one — so two sequential
        activations against the same crop cannot both succeed on one observed version."

        Design: Corner/cross_cutting_layers/occ_recipe_activate_stale_crop_version
        """
        crop = create_crop(crop_code="KALE-01")
        r1 = _grower_recipe(crop)
        r2 = validate_success(
            api.create_recipe(create_recipe_payload(crop["id"], light_hours_per_day=18), GR),
            expected_status=201,
        )
        v1 = crop["version"]

        r1_after = validate_success(
            api.activate_recipe(r1["id"], {"expected_crop_version": v1}, GR))
        assert r1_after["recipe_status"] == "ACTIVE"

        stale = api.activate_recipe(r2["id"], {"expected_crop_version": v1}, GR)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        crop_now = validate_success(api.get_crop(crop["id"], FM))
        assert crop_now["version"] == v1 + 1, "activation increments the crop version by one"
        r2_after = validate_success(
            api.activate_recipe(r2["id"], {"expected_crop_version": crop_now["version"]}, GR))
        assert r2_after["recipe_status"] == "ACTIVE"
        r1_final = validate_success(api.get_recipe(r1["id"], GR))
        assert r1_final["recipe_status"] == "RETIRED", "activation supersedes the prior ACTIVE recipe"
        crop_final = validate_success(api.get_crop(crop["id"], FM))
        assert crop_final["version"] == v1 + 2
