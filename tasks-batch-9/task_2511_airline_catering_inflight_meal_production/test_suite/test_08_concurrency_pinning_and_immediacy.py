"""Optimistic concurrency on the three guarded creates, version monotonicity, snapshot pinning and cascade immediacy."""

from test_helpers import (
    CART_CODE_CHILL,
    CLOCK_CART,
    CLOCK_MANIFEST,
    CLOCK_UPLIFT,
    COMPLIANCE,
    FEED,
    LM_ALICE,
    LM_BOB,
    SEAL_PRIMARY,
    SEAL_SECONDARY,
    ApiErrorId,
    advance_to_departed,
    advance_to_issued,
    assert_decimal_equals,
    assert_instant_equals,
    assert_total_count,
    factories as f,
    get_success_data,
    load_item,
    open_manifest,
    read_cart,
    read_flight,
    reconcile,
    register_cart,
    set_clock,
    sign_off_build,
    validate_error,
    validate_paginated,
    validate_success,
)

FRESH_SEAL = "SEAL-AN411-99"


class TestTheThreeVersionGuardedCreates:
    """Each guarded create refused on a superseded parent, then retried on a fresh read."""

    def test_a_manifest_create_holding_a_superseded_flight_version_is_refused(
        self, sealed_env
    ):
        """The delay between the read and the write moves the flight one version on.

        PRD §2.7: "Opening a draft loading manifest, `POST /flights/{id}/loading-manifests`, requires `expected_flight_version` carrying the client's last observed `version` of the target `Flight`. If that value does not equal the flight's current `version`, the create is rejected with `ERR_STALE_FLIGHT_VERSION` (HTTP 412). The guard exists because a newly opened manifest legitimately voids any manifest of the same flight still in `DRAFT`; a writer holding a stale view of the flight would silently discard a draft it never saw."

        Design: Corner/cross-cutting complexity layers/a_manifest_create_with_a_superseded_flight_version_is_refused_then_retried
        """
        env = sealed_env
        api = env.api
        set_clock(api, CLOCK_MANIFEST)
        held_version = read_flight(api, env.flight_id)["version"]

        validate_success(
            api.record_delay(
                env.flight_id, f.delay_payload(10, reason="ATC_SLOT"), FEED
            ),
            200,
        )

        validate_error(
            api.open_loading_manifest(
                env.flight_id, f.manifest_payload(held_version), LM_BOB
            ),
            ApiErrorId.ERR_STALE_FLIGHT_VERSION.value,
            412,
        )
        _, meta = validate_paginated(
            api.list_loading_manifests(LM_BOB, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 0)

        moved = read_flight(api, env.flight_id)
        assert moved["version"] == held_version + 1
        assert moved["delay_minutes"] == 10
        # Ten minutes is far below the hour-and-a-half slot threshold. No
        # manifest exists yet, so an unfiltered listing is the whole run set:
        # PRD §4 makes `GET /delivery-runs` filterable by `loading_manifest_id`,
        # `truck_id`, `stand_id`, `recovery_of_run_id` and `status` only.
        _, run_meta = validate_paginated(api.list_delivery_runs(LM_BOB))
        assert_total_count(run_meta, 0)

        manifest = open_manifest(api, env.flight_id, headers=LM_BOB)
        assert manifest["status"] == "DRAFT"
        assert manifest["flight_id"] == env.flight_id

    def test_an_uplift_create_holding_a_pre_departure_flight_version_is_refused(
        self, sealed_env
    ):
        """A version captured before the issue is two behind by reconciliation time.

        PRD §2.7: "Reconciling the uplift, `POST /flights/{id}/uplift-records`, likewise requires `expected_flight_version` carrying the client's last observed `version` of the target `Flight`, and a value that does not equal the flight's current `version` is rejected with `ERR_STALE_FLIGHT_VERSION` (HTTP 412). A new reconciliation supersedes any earlier `DRAFT` reconciliation of the same flight, so without the guard a stale writer would overwrite counts derived from cart state it never observed."

        Design: Corner/cross-cutting complexity layers/an_uplift_create_holding_a_pre_departure_flight_version_is_refused_then_retried
        """
        env = sealed_env
        api = env.api
        pre_issue_version = read_flight(api, env.flight_id)["version"]
        advance_to_issued(env)
        advance_to_departed(env)
        set_clock(api, CLOCK_UPLIFT)

        lines = [f.uplift_line(env.specs["Y"]["id"], 170, 10)]
        validate_error(
            api.create_uplift_record(
                env.flight_id,
                f.uplift_payload(pre_issue_version, lines),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_STALE_FLIGHT_VERSION.value,
            412,
        )
        refused = read_flight(api, env.flight_id)
        assert refused["status"] == "DEPARTED"
        _, meta = validate_paginated(
            api.list_uplift_records(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 0)
        # The issue and the departure each bumped the flight.
        assert refused["version"] > pre_issue_version

        record = reconcile(api, env.flight_id, lines)
        assert record["status"] == "DRAFT"
        # 180 uplifted trays at 1450 cents, uplifted by the 12 percent handling fee.
        assert record["gross_cost_cents"] == 292320
        assert read_flight(api, env.flight_id)["status"] == "RECONCILED"

    def test_a_seal_write_holding_a_pre_build_cart_version_is_refused(
        self, released_env
    ):
        """Signing off the build bumps the cart, so the pre-build version is stale.

        PRD §2.7: "Fitting a security seal, `POST /carts/{id}/seals`, requires `expected_cart_version` carrying the client's last observed `version` of the target `Cart`, and a value that does not equal the cart's current `version` is rejected with `ERR_STALE_CART_VERSION` (HTTP 412). A new seal legitimately supersedes the prior one, so a writer working from a stale view would replace a seal number that is already pinned into a manifest snapshot it never observed."

        Design: Corner/cross-cutting complexity layers/a_seal_write_holding_a_pre_build_cart_version_is_refused_then_retried
        """
        env = released_env
        api = env.api
        set_clock(api, CLOCK_CART)
        cart = register_cart(api, env.flight_id, cart_code=CART_CODE_CHILL)
        load_item(api, cart["id"], env.batch["id"], 180)
        pre_build_version = read_cart(api, cart["id"])["version"]
        sign_off_build(api, cart["id"])

        # The cart IS `BUILT` at this moment, so only the version can be at fault.
        built = read_cart(api, cart["id"])
        assert built["build_status"] == "BUILT"
        assert built["version"] == pre_build_version + 1

        validate_error(
            api.seal_cart(
                cart["id"], f.seal_payload(pre_build_version, SEAL_PRIMARY), LM_ALICE
            ),
            ApiErrorId.ERR_STALE_CART_VERSION.value,
            412,
        )
        unsealed = read_cart(api, cart["id"])
        assert unsealed["seal_status"] == "UNSEALED"
        assert unsealed["seal_number"] is None
        assert unsealed["seal_count"] == 0

        # The refused write consumed nothing, so the same number still seals.
        sealed = get_success_data(
            api.seal_cart(
                cart["id"],
                f.seal_payload(unsealed["version"], SEAL_PRIMARY),
                LM_ALICE,
            )
        )
        assert sealed["seal_status"] == "SEALED"
        assert sealed["seal_number"] == SEAL_PRIMARY
        assert sealed["sealed_by_user_id"] == "lm_alice"


class TestVersionMonotonicity:
    """Every accepted write advances its row, and a refused one advances nothing."""

    def test_a_cascade_advances_the_cascaded_row_and_a_refusal_advances_nothing(
        self, released_env
    ):
        """One load bumps two rows; the over-capacity load bumps neither.

        PRD §2.9: "Many operations in this service mutate more than one row. When they do, every affected row is treated as a real mutation: its `version` increments and its `updated_at` refreshes, exactly as if it had been written directly."

        PRD §2.5: "A resource is created with `version` equal to 1; every mutation that changes the row increments `version` by exactly 1 and refreshes `updated_at`."

        PRD §2.4: "Because the clock is explicit, instants recorded by the service are exactly the clock's value at the moment the recording request was processed, not an approximation of it."

        Design: Corner/cross-cutting complexity layers/every_accepted_write_advances_the_version_including_cascaded_rows
        """
        env = released_env
        api = env.api
        set_clock(api, CLOCK_CART)
        cart = register_cart(api, env.flight_id, cart_code=CART_CODE_CHILL)

        flight_before = read_flight(api, env.flight_id)
        cart_before = read_cart(api, cart["id"])

        # The refresh of `updated_at` is only observable across a clock move:
        # PRD §2.4 makes every instant the service writes the logical clock's own
        # reading, so two writes at one frozen instant record the same string.
        # 06:20 is still hours inside the 08:30 release deadline.
        load_instant = "2026-09-15T06:20:00Z"
        set_clock(api, load_instant)

        item = load_item(api, cart["id"], env.batch["id"], 180)
        assert item["version"] == 1

        cart_after = read_cart(api, cart["id"])
        flight_after = read_flight(api, env.flight_id)
        # The direct write bumped the cart.
        assert cart_after["version"] == cart_before["version"] + 1
        # The roll-up into `units_loaded` bumped the flight too.
        assert flight_after["version"] == flight_before["version"] + 1
        assert cart_after["updated_at"] != cart_before["updated_at"]
        assert flight_after["updated_at"] != flight_before["updated_at"]
        assert_instant_equals(cart_after["updated_at"], load_instant)
        assert_instant_equals(flight_after["updated_at"], load_instant)
        assert cart_after["created_at"] == cart_before["created_at"]
        assert flight_after["created_at"] == flight_before["created_at"]

        validate_error(
            api.load_cart_item(
                cart["id"], f.cart_item_payload(env.batch["id"], 999), LM_ALICE
            ),
            ApiErrorId.ERR_CART_CAPACITY_EXCEEDED.value,
            422,
        )
        cart_final = read_cart(api, cart["id"])
        assert cart_final["version"] == cart_after["version"]
        assert cart_final["updated_at"] == cart_after["updated_at"]
        assert read_flight(api, env.flight_id)["version"] == flight_after["version"]


class TestSnapshotPinningAndImmediacy:
    """The frozen seal list, and the fact that no read ever has to wait."""

    def test_the_snapshot_is_pinned_at_issue_and_only_a_re_issue_re_pins_it(
        self, issued_env
    ):
        """A reseal amends the manifest without moving the snapshot the reseal contradicts.

        PRD §3.6: "From that moment the snapshot is a frozen claim about reality: any later void, reseal or slot movement that contradicts it drives the manifest to `AMENDED`, increments `amendment_count`, and pulls the flight back to `PLANNED` — which is exactly what `AMENDED` means, that the pinned snapshot no longer matches reality."

        PRD §3.6: "It applies to a manifest in `DRAFT` or in `AMENDED`, moving it `DRAFT → ISSUED` or `AMENDED → ISSUED` — the `AMENDED → ISSUED` edge closes the amendment cycle and re-pins the snapshot against current cart state — and requires the flight to be in `PLANNED`."

        PRD §3.9: "`seal_mismatch_count` is the number of entries in the manifest's pinned `cart_seal_snapshot` whose `seal_number` does not appear in `observed_seals`, and is 0 whenever `observed_seals` was omitted."

        Design: Corner/cross-cutting complexity layers/the_manifest_snapshot_is_pinned_at_issue_and_only_a_re_issue_re_pins_it
        """
        env = issued_env
        api = env.api
        manifest_id = env.manifest["id"]
        cart_id = env.cart["id"]

        set_clock(api, "2026-09-15T07:05:00Z")
        resealed = get_success_data(
            api.seal_cart(
                cart_id,
                f.seal_payload(read_cart(api, cart_id)["version"], SEAL_SECONDARY),
                LM_ALICE,
            )
        )
        assert resealed["seal_status"] == "RESEALED"
        assert resealed["seal_number"] == SEAL_SECONDARY
        assert resealed["seal_count"] == 2
        # Sealing moves only the seal axis.
        assert resealed["build_status"] == "BUILT"

        amended = validate_success(api.get_loading_manifest(manifest_id, LM_BOB), 200)
        assert amended["status"] == "AMENDED"
        assert amended["amendment_count"] == 1
        pinned = [entry["seal_number"] for entry in amended["cart_seal_snapshot"]]
        # The pinned snapshot did not follow the cart.
        assert pinned == [SEAL_PRIMARY]
        assert read_flight(api, env.flight_id)["status"] == "PLANNED"

        set_clock(api, "2026-09-15T07:10:00Z")
        reissued = validate_success(
            api.issue_loading_manifest(manifest_id, {}, LM_BOB), 200
        )
        assert reissued["status"] == "ISSUED"
        assert [
            entry["seal_number"] for entry in reissued["cart_seal_snapshot"]
        ] == [SEAL_SECONDARY]
        # Re-issuing closes the cycle without counting a second amendment.
        assert reissued["amendment_count"] == 1
        assert_instant_equals(reissued["issued_at"], "2026-09-15T07:10:00Z")
        assert read_flight(api, env.flight_id)["status"] == "LOADED"

        env.manifest = reissued
        advance_to_departed(env)
        set_clock(api, CLOCK_UPLIFT)
        record = reconcile(
            api,
            env.flight_id,
            [f.uplift_line(env.specs["Y"]["id"], 170, 10)],
            observed_seals=[FRESH_SEAL],
        )
        assert record["seal_mismatch_count"] == 1
        assert_decimal_equals(record["spec_deviation_pct"], "0.00")

        findings, meta = validate_paginated(
            api.list_audit_findings(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 1)
        only = findings[0]
        assert only["finding_type"] == "SEAL_MISMATCH"
        assert only["severity"] == "MAJOR"
        assert only["source"] == "SYSTEM"
        # 200,000 cents of base penalty at the MAJOR multiplier of 2.5.
        assert only["penalty_cents"] == 500000

    def test_one_void_shows_every_cascaded_row_already_settled(self, issued_env):
        """The mutating body and three immediate reads agree with no clock movement.

        PRD §2.9: "Cascades are immediate and fully applied before the response is emitted — there is no deferred or eventual settlement anywhere in the service, so a read issued immediately after a cascading write observes every consequence of it."

        PRD §3.6: "The owning cart, if `BUILT`, falls back `BUILT → BUILDING`, and its seal axis moves from `SEALED` or `RESEALED` to `BROKEN` on the same row — the break clears `sealed_by_user_id` but deliberately leaves `seal_number` in place for audit."

        Design: Corner/consistency model/every_cascaded_field_is_already_visible_in_the_same_response
        """
        env = issued_env
        api = env.api

        voided = validate_success(
            api.void_cart_item(env.cart["id"], env.item["id"], LM_ALICE), 200
        )
        # The mutating response itself already carries the terminal item state.
        assert voided["status"] == "VOID"
        assert_instant_equals(voided["voided_at"], CLOCK_MANIFEST)

        # No clock movement and no other traffic between the write and these reads.
        cart = validate_success(api.get_cart(env.cart["id"], LM_ALICE), 200)
        assert cart["build_status"] == "BUILDING"
        assert cart["seal_status"] == "BROKEN"
        assert cart["loaded_units"] == 0
        assert cart["seal_number"] == SEAL_PRIMARY

        manifest = validate_success(
            api.get_loading_manifest(env.manifest["id"], LM_BOB), 200
        )
        assert manifest["status"] == "AMENDED"
        assert manifest["amendment_count"] == 1

        flight = validate_success(api.get_flight(env.flight_id, COMPLIANCE), 200)
        assert flight["status"] == "PLANNED"
        assert flight["units_loaded"] == 0
        assert flight["unit_balance"] == 180
        assert flight["cost_per_pax_cents"] == 0
