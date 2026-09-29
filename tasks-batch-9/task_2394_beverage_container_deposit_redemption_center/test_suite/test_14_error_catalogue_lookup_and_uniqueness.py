"""Lookups, page windows, lot arithmetic, natural keys and site coherence.

The early rungs of the ladder answer with per-entity codes rather than one
generic failure, and the uniqueness rungs answer before any capacity or
distance question is asked.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_center_pool,
    assert_stamped_at,
    make_distributor_headers,
    make_retailer_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as h

INSTANT = "2026-08-05T09:00:00Z"


class TestUnknownIdsOnEveryReadPath:
    """Eight aggregates, eight different not-found codes."""

    def test_each_read_path_answers_with_its_own_not_found(self, api):
        """Nothing is stored, so every single-resource read reports its own 404.

        PRD: "Every identifier in the path resolves to a stored row, validated left to
        right → otherwise the 404 that names the first unresolved segment:
        `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_CENTER_NOT_FOUND`,
        `ERR_MACHINE_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
        `ERR_BAG_DROP_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND` or
        `ERR_PERIOD_NOT_FOUND`."

        PRD: "All error API responses (4xx status codes) follow this standard envelope
        format:"

        Design: Corner/errors/unknown_ids_on_every_read_path_return_not_found
        """
        h.set_clock(api, INSTANT)

        missing = "00000000-0000-4000-8000-00000000000{}"
        probes = [
            (api.get_distributor, 1, ApiErrorId.ERR_DISTRIBUTOR_NOT_FOUND),
            (api.get_redemption_center, 2, ApiErrorId.ERR_CENTER_NOT_FOUND),
            (api.get_machine, 3, ApiErrorId.ERR_MACHINE_NOT_FOUND),
            (api.get_redeemer_account, 4, ApiErrorId.ERR_ACCOUNT_NOT_FOUND),
            (api.get_redemption_visit, 5, ApiErrorId.ERR_VISIT_NOT_FOUND),
            (api.get_bag_drop, 6, ApiErrorId.ERR_BAG_DROP_NOT_FOUND),
            (api.get_commodity_batch, 7, ApiErrorId.ERR_BATCH_NOT_FOUND),
            (api.get_program_period, 8, ApiErrorId.ERR_PERIOD_NOT_FOUND),
        ]

        for read, suffix, expected in probes:
            response = read(missing.format(suffix), ADMIN_HEADERS)
            body = validate_error(response, expected.value, expected_status=404)
            assert body["message"].strip()


class TestPaginationWindow:
    """The accepted window is exactly 1..100 with a non-negative offset."""

    def test_zero_hundred_one_and_a_negative_offset_are_refused(self, api):
        """limit 0, limit 101 and offset -1 fail; limit 1 and limit 100 do not.

        PRD: "A `limit` outside the inclusive range of 1 to 100, a non-integer `limit` or
        `offset`, or a negative `offset` is refused with `ERR_INVALID_PAGINATION` (HTTP 400)."

        PRD: "`limit` caps the number of rows returned; it defaults to 10 when omitted, may
        not be lower than 1 and may not exceed 100."

        Design: Corner/errors/pagination_outside_one_to_hundred_is_rejected
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        h.create_draft_product(api, distributor["id"])

        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            validate_error(
                api.list_beverage_products(ADMIN_HEADERS, params=params),
                ApiErrorId.ERR_INVALID_PAGINATION.value,
                expected_status=400,
            )

        _, narrow = validate_paginated(
            api.list_beverage_products(ADMIN_HEADERS, params={"limit": 1, "offset": 0})
        )
        assert narrow["limit"] == 1
        assert narrow["total_count"] == 1

        _, wide = validate_paginated(
            api.list_beverage_products(ADMIN_HEADERS, params={"limit": 100, "offset": 0})
        )
        assert wide["limit"] == 100
        assert wide["offset"] == 0
        assert wide["total_count"] == 1
        assert wide["has_more"] is False


class TestLotQuantityConsistency:
    """Impossible arithmetic dies before screening; possible arithmetic is screened."""

    def test_six_and_five_against_ten_is_refused_while_six_and_four_screen_to_nothing(
        self, api
    ):
        """11 flagged containers out of 10 is refused; exactly 10 becomes a MIXED rejection.

        PRD: "On a container lot, `out_of_state_marked_quantity` plus
        `contaminated_quantity` is at most `presented_quantity` → otherwise
        `ERR_LOT_QUANTITY_INCONSISTENT` (HTTP 422)."

        PRD: "Otherwise `accepted_quantity` is the presented quantity less the out-of-state
        marked quantity less the contaminated quantity, and `reject_reason` names the dominant
        cause of whatever was refused: `MIXED` when both the out-of-state marked quantity and
        the contaminated quantity are greater than 0, `OUT_OF_STATE` when only the out-of-state
        marked quantity is greater than 0, `CONTAMINATED` when only the contaminated quantity
        is greater than 0, and null when neither is — in which case nothing was rejected at
        all."

        Design: Corner/errors/lot_quantity_flags_that_exceed_the_presented_count_are_rejected
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center = fleet["center"]
        headers = h.make_center_headers(center["id"])
        visit = h.open_center_hand_visit(api, center["id"])

        validate_error(
            api.create_container_lot(
                visit["id"],
                f.create_lot_payload(
                    product["id"],
                    10,
                    visit["version"],
                    out_of_state_marked_quantity=6,
                    contaminated_quantity=5,
                ),
                headers,
            ),
            ApiErrorId.ERR_LOT_QUANTITY_INCONSISTENT.value,
            expected_status=422,
        )

        untouched = h.read_visit(api, visit["id"], headers)
        assert untouched["count_status"] == "OPEN"
        assert untouched["version"] == visit["version"]

        lot = h.add_lot(
            api,
            visit["id"],
            product["id"],
            10,
            headers,
            out_of_state_marked_quantity=6,
            contaminated_quantity=4,
            expected_visit_version=visit["version"],
        )
        assert lot["accepted_quantity"] == 0
        assert lot["reject_reason"] == "MIXED"
        assert lot["rejected_quantity"] == 10
        assert lot["deposit_value_cents"] == 0

        counting = h.read_visit(api, visit["id"], headers)
        assert counting["presented_total"] == 10
        assert counting["out_of_state_marked_total"] == 6
        assert counting["raw_accepted_count"] == 0


class TestDuplicateBusinessKeys:
    """Four registries, four natural keys, four distinct 409s."""

    def test_each_reused_key_answers_with_its_own_duplicate_code(self, api):
        """A permit, a UPC, an asset tag and an account code all refuse the second row.

        PRD: "The submitted natural key is unused → otherwise the matching duplicate
        error: `ERR_DUPLICATE_PERMIT_NUMBER` for `permit_number`, `ERR_DUPLICATE_UPC` for
        `upc`, `ERR_DUPLICATE_ASSET_TAG` for `asset_tag`, `ERR_DUPLICATE_ACCOUNT_CODE` for
        `account_code`, `ERR_DUPLICATE_TAG_CODE` for `tag_code`, `ERR_DUPLICATE_BATCH_CODE`
        for `batch_code`, `ERR_DUPLICATE_QUARTER_CODE` for `quarter_code` (all HTTP 409)."

        PRD: "A centre's `machine_count` is the number of its machines whose `status` is
        anything other than `RETIRED`, and `out_of_service_machine_count` is the number whose
        `status` is exactly `OUT_OF_SERVICE`; both are recomputed whenever a machine event
        changes a machine's status."

        Design: Corner/errors/duplicate_business_keys_on_four_registries_are_rejected
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        distributor_headers = make_distributor_headers(distributor["id"])
        product = h.create_draft_product(api, distributor["id"])
        center = h.create_center(api, site_name="Bend Redemption Center")
        machine = h.install_machine(api, center["id"])
        h.create_account(api)

        validate_error(
            api.create_distributor(
                f.create_distributor_payload(legal_name="Another Bottling LLC"),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_PERMIT_NUMBER.value,
            expected_status=409,
        )
        validate_error(
            api.create_beverage_product(
                f.create_beverage_product_payload(
                    distributor["id"],
                    brand_name="Cascade Sparkling",
                    container_material="ALUMINUM",
                    fill_volume_ml=355,
                ),
                distributor_headers,
            ),
            ApiErrorId.ERR_DUPLICATE_UPC.value,
            expected_status=409,
        )
        validate_error(
            api.create_machine(
                center["id"],
                f.create_machine_payload(accepted_material="ALUMINUM"),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_ASSET_TAG.value,
            expected_status=409,
        )
        validate_error(
            api.create_redeemer_account(
                f.create_redeemer_account_payload(holder_name="Other Holder"),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_ACCOUNT_CODE.value,
            expected_status=409,
        )

        labels, label_meta = validate_paginated(
            api.list_beverage_products(
                ADMIN_HEADERS, params={"upc": "011110000001"}
            )
        )
        assert label_meta["total_count"] == 1
        assert [row["id"] for row in labels] == [product["id"]]

        machines, machine_meta = validate_paginated(
            api.list_center_machines(center["id"], ADMIN_HEADERS)
        )
        assert machine_meta["total_count"] == 1
        assert [row["id"] for row in machines] == [machine["id"]]

        assert h.read_center(api, center["id"], ADMIN_HEADERS)["machine_count"] == 1
        assert (
            validate_success(
                api.get_distributor(distributor["id"], distributor_headers)
            )["legal_name"]
            == "Cascade Bottling LLC"
        )


class TestDuplicateBatchCodeBeatsThePool:
    """The uniqueness rung runs before the capacity rung."""

    def test_a_reused_code_is_refused_even_though_the_pool_is_deep_enough(self, api):
        """100 containers are still unbatched, yet the repeated code fails first.

        PRD: "The submitted natural key is unused → otherwise the matching duplicate
        error: `ERR_DUPLICATE_PERMIT_NUMBER` for `permit_number`, `ERR_DUPLICATE_UPC` for
        `upc`, `ERR_DUPLICATE_ASSET_TAG` for `asset_tag`, `ERR_DUPLICATE_ACCOUNT_CODE` for
        `account_code`, `ERR_DUPLICATE_TAG_CODE` for `tag_code`, `ERR_DUPLICATE_BATCH_CODE`
        for `batch_code`, `ERR_DUPLICATE_QUARTER_CODE` for `quarter_code` (all HTTP 409)."

        PRD: "The requested batch `container_count` is at most the centre's
        `unbatched_container_count` → otherwise `ERR_INSUFFICIENT_UNBATCHED_CONTAINERS` (HTTP
        422)."

        Design: Corner/errors/duplicate_batch_code_is_rejected_before_the_pool_is_touched
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        headers = h.make_center_headers(center["id"])

        h.create_counted_center_visit(
            api, center["id"], machine["id"], product["id"], [200]
        )
        batch = h.create_batch(api, center["id"], 100)

        validate_error(
            api.create_commodity_batch(
                f.create_commodity_batch_payload(
                    center["id"], 50, material="ALUMINUM", batch_code="BATCH-1001"
                ),
                headers,
            ),
            ApiErrorId.ERR_DUPLICATE_BATCH_CODE.value,
            expected_status=409,
        )

        batches, meta = validate_paginated(
            api.list_commodity_batches(headers, params={"center_id": center["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in batches] == [batch["id"]]

        assert_center_pool(
            h.read_center(api, center["id"], headers),
            accepted_container_count=200,
            batched_container_count=100,
            unbatched_container_count=100,
        )


class TestExemptStoreCannotOpenARetailerVisit:
    """Redemption at the store stops the moment the exemption is granted."""

    def test_the_same_visit_body_succeeds_before_the_exemption_and_fails_after(self, api):
        """One store, one body, two answers either side of CLAIM_EXEMPTION.

        PRD: "The store named by `retailer_id` has `obligation_status` `OBLIGATED` →
        otherwise `ERR_RETAILER_EXEMPT` (HTTP 409). Applies to opening a `RETAILER` visit."

        PRD: "On success the server writes `nearest_center_id` and
        `nearest_center_distance_miles` from the selected centre and stamps
        `exemption_granted_at` with the current logical instant."

        Design: Corner/errors/exempt_store_cannot_open_a_retailer_visit
        """
        h.set_clock(api, INSTANT)
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center = fleet["center"]
        retailer = h.create_retailer(api)
        headers = make_retailer_headers(retailer["id"])

        visit = h.open_retailer_visit(api, retailer["id"])
        closed = h.close_count(api, visit["id"], headers)
        assert closed["count_status"] == "COUNTED"

        exempt = h.exemption_action(api, retailer["id"], "CLAIM_EXEMPTION", headers)
        assert exempt["obligation_status"] == "EXEMPT"
        assert exempt["nearest_center_id"] == center["id"]
        assert exempt["nearest_center_distance_miles"] == 1.00
        assert_stamped_at(exempt["exemption_granted_at"], INSTANT)

        validate_error(
            api.create_redemption_visit(
                f.retailer_visit_payload(retailer["id"]), headers
            ),
            ApiErrorId.ERR_RETAILER_EXEMPT.value,
            expected_status=409,
        )

        _, meta = validate_paginated(
            api.list_redemption_visits(headers, params={"retailer_id": retailer["id"]})
        )
        assert meta["total_count"] == 1


class TestMachineAndVisitMustShareACenter:
    """The coherence rung reads in both directions."""

    def test_a_foreign_machine_and_a_foreign_visit_are_both_refused(self, api):
        """Centre A cannot borrow centre B's machine, nor can B's machine serve A's visit.

        PRD: "Machine/centre coherence: the machine's `center_id` equals the visit's
        `center_id`, and the visit named by `visit_id` in a machine event is the visit
        occupying that machine → otherwise `ERR_MACHINE_CENTER_MISMATCH` (HTTP 422)."

        PRD: "A successful open stamps `session_started_at` with the current logical instant
        and sets `open_session_count` to 1."

        Design: Corner/errors/machines_and_visits_must_belong_to_the_same_center
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        first = h.create_operational_center(
            api, {"site_name": "Center A"}, {"asset_tag": "RVM-A001"}
        )
        second = h.create_operational_center(
            api,
            {"site_name": "Center B", "x_miles": 20.0, "y_miles": 20.0},
            {"asset_tag": "RVM-B001"},
        )
        center_a, machine_a = first["center"], first["machine"]
        center_b, machine_b = second["center"], second["machine"]

        validate_error(
            api.create_redemption_visit(
                f.center_machine_visit_payload(center_a["id"], machine_b["id"]),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_MACHINE_CENTER_MISMATCH.value,
            expected_status=422,
        )
        _, meta = validate_paginated(api.list_redemption_visits(ADMIN_HEADERS))
        assert meta["total_count"] == 0

        visit_a = validate_success(
            api.create_redemption_visit(
                f.center_machine_visit_payload(center_a["id"], machine_a["id"]),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        h.add_lot(
            api,
            visit_a["id"],
            product["id"],
            10,
            ADMIN_HEADERS,
            expected_visit_version=visit_a["version"],
        )
        visit_b = validate_success(
            api.create_redemption_visit(
                f.center_machine_visit_payload(center_b["id"], machine_b["id"]),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        h.add_lot(
            api,
            visit_b["id"],
            product["id"],
            10,
            ADMIN_HEADERS,
            expected_visit_version=visit_b["version"],
        )

        occupied = h.open_session(api, machine_b["id"], visit_b["id"], ADMIN_HEADERS)
        assert occupied["status"] == "COUNTING"
        assert occupied["open_session_count"] == 1

        validate_error(
            api.post_machine_event(
                machine_b["id"],
                f.machine_event_payload("JAM_REPORTED", visit_id=visit_a["id"]),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_MACHINE_CENTER_MISMATCH.value,
            expected_status=422,
        )

        still_counting = h.read_machine(api, machine_b["id"], ADMIN_HEADERS)
        assert still_counting["status"] == "COUNTING"
        assert still_counting["jam_count_today"] == 0

        untouched = h.read_visit(api, visit_a["id"], ADMIN_HEADERS)
        assert untouched["count_status"] == "COUNTING"
        assert untouched["requires_manual_recount"] is False


class TestExemptionNeedsAnOperationalAllMaterialsCenter:
    """The candidate-set rung runs before the distance rung."""

    def test_a_near_pet_only_center_never_counts_as_a_candidate(self, api):
        """1.00 mile away is irrelevant while no operational all-materials centre exists.

        PRD: "Second, at least one candidate centre must exist — candidates are exactly
        those centres whose `status` is `OPERATIONAL` and whose `accepts_all_materials` is
        true. If that candidate set is empty the claim is refused with
        `ERR_NO_ELIGIBLE_CENTER`."

        PRD: "The candidates are then ranked by rounded distance ascending, with ties broken
        by `created_at` ascending and never by identifier, and the first candidate is selected."

        Design: Corner/errors/exemption_requires_an_operational_all_materials_center_to_exist
        """
        h.set_clock(api, INSTANT)
        h.create_operational_center(
            api,
            {
                "site_name": "PET Only Center",
                "accepted_materials": ["PET_PLASTIC"],
                "accepts_all_materials": False,
                "opening_cash_cents": 50000,
            },
        )
        retailer = h.create_retailer(api)
        headers = make_retailer_headers(retailer["id"])

        validate_error(
            api.post_exemption_action(
                retailer["id"], f.exemption_action_payload("CLAIM_EXEMPTION"), headers
            ),
            ApiErrorId.ERR_NO_ELIGIBLE_CENTER.value,
            expected_status=422,
        )

        eligible = h.create_center(
            api,
            site_name="All Materials Center",
            x_miles=2.0,
            y_miles=0.0,
            opening_cash_cents=50000,
        )
        h.install_machine(
            api, eligible["id"], asset_tag="RVM-2001", accepted_material="ALUMINUM"
        )

        validate_error(
            api.post_exemption_action(
                retailer["id"], f.exemption_action_payload("CLAIM_EXEMPTION"), headers
            ),
            ApiErrorId.ERR_NO_ELIGIBLE_CENTER.value,
            expected_status=422,
        )

        h.activate_center(api, eligible["id"])

        granted = h.exemption_action(api, retailer["id"], "CLAIM_EXEMPTION", headers)
        assert granted["obligation_status"] == "EXEMPT"
        assert granted["nearest_center_id"] == eligible["id"]
        assert granted["nearest_center_distance_miles"] == 1.00
