"""The pagination envelope around a filtered collection, and a pure link write.

The two listing rules that matter here are arithmetic rather than membership:
`total_count` counts the filtered set and `has_more` compares the window against
that count. The spare reservation is then the system's one pure association
write, navigable from either end and indifferent to the contract's own state.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_CONTRACT_NOT_FOUND,
    ERR_MODULE_NOT_FOUND,
    ERR_VALIDATION_FAILED,
)
from test_helpers.assertions import (
    assert_contract_fields,
    assert_module_fields,
    assert_no_pagination_meta,
    assert_ordered_by_created_at,
    assert_page_meta,
    assert_version,
    ids_of,
)
from test_helpers.constants import (
    CONTRACT_PENDING,
    MODULE_CALIBRATED,
    MODULE_MANUFACTURED,
    MODULE_PIXEL_TESTED,
)
from test_helpers.factories import spare_reservation_payload

#: Twelve modules of one family: two calibrated, two only pixel-tested, eight as
#: registered.
STOCK_SIZE = 12
DEFAULT_LIMIT = 10
CALIBRATED_STOCK = 2
PIXEL_TESTED_STOCK = 2

#: The two ends of the accepted page-size range.
BELOW_MINIMUM_LIMIT = 0
ABOVE_MAXIMUM_LIMIT = 101

#: A 300 basis point holding on a single-module wall obliges one spare.
SINGLE_MODULE_SPARE_REQUIRED_COUNT = 1


def _twelve_modules_in_three_states(plant):
    """One family and twelve modules, registered in serial order."""
    model = plant.register_model()
    modules = [
        plant.register_module(model["id"], f"M-{index:02d}")
        for index in range(1, STOCK_SIZE + 1)
    ]
    for module in modules[:4]:
        plant.pixel_test(module["id"])
    for module in modules[:2]:
        plant.calibrate(module["id"])
    return model, modules


class TestListEnvelopeArithmetic:
    """The envelope is computed from the filtered count, not from the page."""

    def test_the_default_window_is_ten_rows_and_the_tail_is_the_remainder(self, plant):
        """Every list endpoint accepts two optional query parameters. `limit`
        controls page size: it defaults to 10 when omitted, may not be below 1, and
        may not exceed 100. Every list response carries the four pagination fields
        inside `meta`: `limit` and `offset` echo the effective values used for the
        page, `total_count` reports how many records matched the filters before the
        page window was applied, and `has_more` is true exactly when records remain
        beyond the current window.

        Design: Corner/endpoints/list_pagination_envelope_composes_with_filters
        """
        model, modules = _twelve_modules_in_three_states(plant)

        first_page, first_meta = validate_paginated(
            plant.api.list_modules(plant.qa, {"display_model_id": model["id"]})
        )
        tail, tail_meta = validate_paginated(
            plant.api.list_modules(
                plant.qa,
                {"display_model_id": model["id"], "limit": 5, "offset": DEFAULT_LIMIT},
            )
        )

        assert ids_of(first_page) == ids_of(modules[:DEFAULT_LIMIT])
        assert_ordered_by_created_at(first_page)
        assert_page_meta(
            first_meta,
            limit=DEFAULT_LIMIT,
            offset=0,
            total_count=STOCK_SIZE,
            has_more=True,
        )
        assert ids_of(tail) == ids_of(modules[DEFAULT_LIMIT:])
        assert_page_meta(
            tail_meta, limit=5, offset=DEFAULT_LIMIT, total_count=STOCK_SIZE, has_more=False
        )

        models, models_meta = validate_paginated(plant.api.list_display_models(plant.qa))
        assert ids_of(models) == [model["id"]]
        assert_page_meta(models_meta, total_count=1, has_more=False)

    def test_the_count_follows_the_filter_and_the_range_is_never_clamped(self, plant):
        """A `limit` outside the 1-to-100 range, or a negative `offset`, is a
        malformed request and is rejected with `ERR_VALIDATION_FAILED` (HTTP 400).
        Single-resource reads carry neither of the four.

        Design: Corner/endpoints/list_pagination_envelope_composes_with_filters
        """
        model, modules = _twelve_modules_in_three_states(plant)

        tested, tested_meta = validate_paginated(
            plant.api.list_modules(
                plant.qa,
                {"display_model_id": model["id"], "module_state": MODULE_PIXEL_TESTED},
            )
        )
        second_calibrated, calibrated_meta = validate_paginated(
            plant.api.list_modules(
                plant.qa,
                {
                    "display_model_id": model["id"],
                    "module_state": MODULE_CALIBRATED,
                    "limit": 1,
                    "offset": 1,
                },
            )
        )

        assert ids_of(tested) == ids_of(modules[2:4])
        assert_page_meta(tested_meta, total_count=PIXEL_TESTED_STOCK, has_more=False)
        assert ids_of(second_calibrated) == [modules[1]["id"]]
        assert_page_meta(
            calibrated_meta,
            limit=1,
            offset=1,
            total_count=CALIBRATED_STOCK,
            has_more=False,
        )

        too_small = plant.api.list_modules(
            plant.qa, {"display_model_id": model["id"], "limit": BELOW_MINIMUM_LIMIT}
        )
        too_large = plant.api.list_modules(
            plant.qa, {"display_model_id": model["id"], "limit": ABOVE_MAXIMUM_LIMIT}
        )

        validate_error(too_small, ERR_VALIDATION_FAILED, 400)
        validate_error(too_large, ERR_VALIDATION_FAILED, 400)

        single = plant.api.get_module(modules[-1]["id"], plant.qa)
        last = validate_success(single, 200)
        assert_no_pagination_meta(single.json()["meta"])
        assert_module_fields(
            last,
            module_state=MODULE_MANUFACTURED,
            color_bin=None,
            color_bin_rank=None,
            cabinet_id=None,
            slot_index=None,
        )


class TestSpareReservationLink:
    """Both ends must resolve, and neither end changes state."""

    def test_neither_missing_end_touches_the_other(self, plant):
        """A referenced `module_id`, in path or body, resolves — otherwise
        `ERR_MODULE_NOT_FOUND`. A referenced `service_contract_id`, in path or body,
        resolves — otherwise `ERR_CONTRACT_NOT_FOUND`.

        Design: Corner/endpoints/spare_reservation_links_a_module_to_a_contract_both_ways
        """
        model = plant.register_model()
        project = plant.create_project(model["id"])
        contract = plant.sell_contract(project["id"])
        spare = plant.calibrated_module(model["id"], serial_no="M-SPARE-1")

        unknown_module = plant.api.reserve_spare(
            contract["id"],
            spare_reservation_payload(contract["version"], NON_EXISTENT_UUID),
            plant.service,
        )
        unknown_contract = plant.api.reserve_spare(
            NON_EXISTENT_UUID,
            spare_reservation_payload(contract["version"], spare["id"]),
            plant.service,
        )

        validate_error(unknown_module, ERR_MODULE_NOT_FOUND, 404)
        validate_error(unknown_contract, ERR_CONTRACT_NOT_FOUND, 404)
        held = plant.contract(contract["id"])
        assert_contract_fields(held, spare_reserved_count=0)
        assert_version(held, contract["version"], "contract")
        assert_module_fields(
            plant.module(spare["id"]),
            module_state=MODULE_CALIBRATED,
            reserved_service_contract_id=None,
        )

    def test_the_link_is_navigable_from_the_module_side_and_activates_nothing(self, plant):
        """A reservation writes the contract's id into the module's
        `reserved_service_contract_id` and raises `spare_reserved_count`, which is
        always the count of modules whose `reserved_service_contract_id` is this
        contract **and** whose `module_state` is `CALIBRATED`. It becomes `ACTIVE`
        only through commissioning sign-off (§3.7), which is also what stamps
        `warranty_start_at` — the zero point of the brightness-degradation warranty.

        Design: Corner/endpoints/spare_reservation_links_a_module_to_a_contract_both_ways
        """
        model = plant.register_model()
        project = plant.create_project(model["id"])
        contract = plant.sell_contract(project["id"])
        first_spare = plant.calibrated_module(model["id"], serial_no="M-SPARE-1")
        second_spare = plant.calibrated_module(model["id"], serial_no="M-SPARE-2")

        first_response = plant.api.reserve_spare(
            contract["id"],
            spare_reservation_payload(contract["version"], first_spare["id"]),
            plant.service,
        )
        first_held = validate_success(first_response, 201)
        second_held = validate_success(
            plant.api.reserve_spare(
                contract["id"],
                spare_reservation_payload(
                    plant.contract_version(contract["id"]), second_spare["id"]
                ),
                plant.service,
            ),
            201,
        )

        assert first_held["id"] == first_spare["id"]
        assert_module_fields(
            first_held,
            module_state=MODULE_CALIBRATED,
            reserved_service_contract_id=contract["id"],
            cabinet_id=None,
        )
        assert_module_fields(
            second_held,
            module_state=MODULE_CALIBRATED,
            reserved_service_contract_id=contract["id"],
        )
        assert_version(first_held, first_spare["version"] + 1, "module")

        stocked = plant.contract(contract["id"])
        assert_contract_fields(
            stocked,
            contract_state=CONTRACT_PENDING,
            spare_reserved_count=2,
            spare_required_count=SINGLE_MODULE_SPARE_REQUIRED_COUNT,
        )
        assert_version(stocked, contract["version"] + 2, "contract")
        assert stocked["warranty_start_at"] is None

        rows, meta = validate_paginated(
            plant.api.list_modules(
                plant.qa, {"reserved_service_contract_id": contract["id"]}
            )
        )
        assert ids_of(rows) == [first_spare["id"], second_spare["id"]]
        assert_page_meta(meta, total_count=2, has_more=False)
