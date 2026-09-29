"""
The access-side rungs of the rejection order: authentication of the two
headers, identity scope for the three entity-backed roles, the family-specific
404s on path and body identifiers, the family-specific duplicate conflicts, and
the two tag-batch gates that guard encoding and read-quality verification.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ADJUSTMENT_NOT_FOUND,
    ERR_CATEGORY_NOT_FOUND,
    ERR_COUNTER_FIRM_NOT_FOUND,
    ERR_COUNT_LINE_NOT_FOUND,
    ERR_COUNT_SCHEDULE_NOT_FOUND,
    ERR_COUNT_TASK_NOT_FOUND,
    ERR_COUNT_WINDOW_NOT_DUE,
    ERR_DUPLICATE_CATEGORY_CODE,
    ERR_DUPLICATE_COUNTER_FIRM_CODE,
    ERR_DUPLICATE_SKU,
    ERR_DUPLICATE_STORE_CODE,
    ERR_DUPLICATE_VENDOR_CODE,
    ERR_IDENTITY_SCOPE_VIOLATION,
    ERR_INVALID_VERIFICATION_COUNTS,
    ERR_INVESTIGATION_NOT_FOUND,
    ERR_ITEM_NOT_FOUND,
    ERR_PHYSICAL_INVENTORY_LINE_NOT_FOUND,
    ERR_PHYSICAL_INVENTORY_NOT_FOUND,
    ERR_SAMPLE_BELOW_REQUIRED,
    ERR_SHRINK_PERIOD_NOT_FOUND,
    ERR_STOCK_POSITION_NOT_FOUND,
    ERR_STORE_NOT_FOUND,
    ERR_TAG_BATCH_NOT_FOUND,
    ERR_TAG_SCHEME_MISMATCH,
    ERR_UNAUTHENTICATED,
    ERR_VENDOR_NOT_FOUND,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    NO_AUTH_HEADERS,
    ROLE_INVENTORY_ANALYST,
    USER_ANALYST_1,
    headers_for,
    headers_without_role,
    make_counter_headers,
    make_store_ops_headers,
    make_vendor_rep_headers,
)

EARLY_WINDOW = {
    "window_start": "2026-07-01T00:00:00Z",
    "window_end": "2026-07-01T00:00:00Z",
}


def _schedule_due_in_august(api):
    """An APPAREL category, store S100 and an ACTIVE handheld schedule."""
    category = fx.create_category(api, f.apparel_category_payload())
    store = fx.create_store(api, f.store_payload())
    schedule = fx.create_schedule(
        api, store["id"], category["id"], first_due_date="2026-08-01"
    )
    assert schedule["status"] == "ACTIVE"
    assert schedule["next_due_date"] == "2026-08-01"
    return schedule


class TestAuthenticationIsTheFirstRung:
    def test_a_missing_role_header_is_reported_before_the_window_rules(self, api):
        """
        A request with no role header never reaches the temporal checks.

        "Every request must carry two headers: `X-User-ID`, identifying the acting
        user, and `X-User-Role`, declaring the capacity in which they act. If either
        header is missing, empty, or if `X-User-Role` names anything outside the seven
        roles defined below, the request is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/count_task_create_missing_x_user_role_header_returns_unauthenticated
        """
        schedule = _schedule_due_in_august(api)
        payload = f.count_task_payload(schedule["id"], **EARLY_WINDOW)

        response = api.create_count_task(payload, headers_without_role())
        validate_error(response, ERR_UNAUTHENTICATED, 401)

        body = response.json()
        assert body["response_type"] == "error"
        assert set(body["data"].keys()) == {"error_id", "message"}

        validate_error(
            api.create_count_task(payload, ANALYST), ERR_COUNT_WINDOW_NOT_DUE, 422
        )

        rows, meta = validate_paginated(
            api.list_count_tasks(ANALYST, {"count_schedule_id": schedule["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_role_outside_the_seven_is_not_authenticated(self, api):
        """
        An undeclared role name authenticates no better than a missing one.

        "If either header is missing, empty, or if `X-User-Role` names anything
        outside the seven roles defined below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/count_task_create_missing_x_user_role_header_returns_unauthenticated
        """
        schedule = _schedule_due_in_august(api)
        payload = f.count_task_payload(schedule["id"], **EARLY_WINDOW)

        validate_error(
            api.create_count_task(payload, headers_for("Auditor", USER_ANALYST_1)),
            ERR_UNAUTHENTICATED,
            401,
        )

        rows, meta = validate_paginated(
            api.list_count_tasks(ANALYST, {"count_schedule_id": schedule["id"]})
        )
        assert meta["total_count"] == 0

    def test_an_empty_user_id_and_no_headers_at_all_are_both_unauthenticated(self, api):
        """
        An empty identity is as absent as no identity.

        "If either header is missing, empty, or if `X-User-Role` names anything
        outside the seven roles defined below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/count_task_create_missing_x_user_role_header_returns_unauthenticated
        """
        schedule = _schedule_due_in_august(api)
        payload = f.count_task_payload(schedule["id"], **EARLY_WINDOW)

        validate_error(
            api.create_count_task(payload, headers_for(ROLE_INVENTORY_ANALYST, "")),
            ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.create_count_task(payload, NO_AUTH_HEADERS), ERR_UNAUTHENTICATED, 401
        )

        rows, meta = validate_paginated(
            api.list_count_tasks(ANALYST, {"count_schedule_id": schedule["id"]})
        )
        assert meta["total_count"] == 0


class TestIdentityScopeOnTheEntityBackedRoles:
    def test_receiving_a_batch_destined_for_another_store_is_refused(self, api):
        """
        `StoreOps` may only receive the batches addressed to its own store.

        "When `X-User-Role` is `StoreOps`, `X-User-ID` is the `id` of the acting
        `Store`; ownership checks on any resource that references a `Store` compare
        the resource's store-bearing field to `X-User-ID` — specifically a tag batch's
        `destination_store_id` and a count task's `store_id`."

        Design: Corner/errors/tag_batch_receive_by_a_different_store_ops_returns_forbidden
        """
        world = fx.apparel_reference_world(api, baseline=100)
        other_store = fx.create_store(api, f.handheld_only_store_payload())
        vendor_headers = make_vendor_rep_headers(world["vendor_id"])

        batch = validate_success(
            api.create_tag_batch(
                f.tag_batch_payload(
                    world["vendor_id"], world["item_id"], world["store_id"]
                ),
                vendor_headers,
            ),
            201,
        )
        encoded = validate_success(
            api.encode_tag_batch(batch["id"], f.encode_payload(), vendor_headers)
        )
        assert encoded["status"] == "ENCODED"

        validate_error(
            api.receive_tag_batch(
                batch["id"], make_store_ops_headers(other_store["id"])
            ),
            ERR_IDENTITY_SCOPE_VIOLATION,
            403,
        )

        stalled = fx.read_tag_batch(api, batch["id"])
        assert stalled["status"] == "ENCODED"
        assert stalled["version"] == 2

        received = validate_success(
            api.receive_tag_batch(
                batch["id"], make_store_ops_headers(world["store_id"])
            )
        )
        assert received["status"] == "RECEIVED"

    def test_a_vendor_rep_may_not_draft_a_batch_for_another_vendor(self, api):
        """
        The batch's own `vendor_id` is what the scope check compares against.

        "When `X-User-Role` is `VendorRep`, `X-User-ID` is the `id` of the acting
        `Vendor`; ownership checks compare a tag batch's `vendor_id`, or the vendor
        identifier named in the request path, to `X-User-ID`."

        Design: Corner/errors/tag_batch_receive_by_a_different_store_ops_returns_forbidden
        """
        world = fx.apparel_reference_world(api, baseline=100)
        other_vendor = fx.create_vendor(api, f.vendor_payload(code="VEND2", name="Two"))

        validate_error(
            api.create_tag_batch(
                f.tag_batch_payload(
                    world["vendor_id"], world["item_id"], world["store_id"]
                ),
                make_vendor_rep_headers(other_vendor["id"]),
            ),
            ERR_IDENTITY_SCOPE_VIOLATION,
            403,
        )

        rows, meta = validate_paginated(api.list_tag_batches(ADMIN))
        assert meta["total_count"] == 0

        accepted = validate_success(
            api.create_tag_batch(
                f.tag_batch_payload(
                    world["vendor_id"], world["item_id"], world["store_id"]
                ),
                make_vendor_rep_headers(world["vendor_id"]),
            ),
            201,
        )
        assert accepted["vendor_id"] == world["vendor_id"]

    def test_a_counter_firm_may_not_start_another_firms_inventory(self, api):
        """
        A counting firm is scoped to the inventories booked with it.

        "When `X-User-Role` is `ThirdPartyCounter`, `X-User-ID` is the `id` of the
        acting `CounterFirm`; ownership checks compare a physical inventory's
        `counter_firm_id` to `X-User-ID`. A write attempted by one of these three
        roles against a resource scoped to a different entity is rejected with
        `ERR_IDENTITY_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/errors/tag_batch_receive_by_a_different_store_ops_returns_forbidden
        """
        world = fx.physical_inventory_world(api)
        other_firm = fx.create_counter_firm(
            api, f.counter_firm_payload(code="CF2", name="Counting Firm Two")
        )

        validate_error(
            api.start_physical_inventory(
                world["physical_inventory_id"], make_counter_headers(other_firm["id"])
            ),
            ERR_IDENTITY_SCOPE_VIOLATION,
            403,
        )
        assert (
            fx.read_physical_inventory(api, world["physical_inventory_id"])["status"]
            == "PLANNED"
        )

        started = validate_success(
            api.start_physical_inventory(
                world["physical_inventory_id"], world["counter_headers"]
            )
        )
        assert started["status"] == "COUNTING"


class TestUnknownIdentifiersReportTheirOwnFamily:
    def test_every_path_family_reports_its_own_not_found(self, api):
        """
        Each identifier type owns a distinct 404 identifier.

        "Path identifiers are resolved strictly left to right, and the first
        identifier that resolves to nothing terminates the request with the 404
        belonging to that identifier's type: `ERR_CATEGORY_NOT_FOUND`,
        `ERR_STORE_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_COUNTER_FIRM_NOT_FOUND`,
        `ERR_ITEM_NOT_FOUND`, `ERR_STOCK_POSITION_NOT_FOUND`,
        `ERR_TAG_BATCH_NOT_FOUND`, `ERR_COUNT_SCHEDULE_NOT_FOUND`,
        `ERR_COUNT_TASK_NOT_FOUND`, `ERR_COUNT_LINE_NOT_FOUND`,
        `ERR_INVESTIGATION_NOT_FOUND`, `ERR_ADJUSTMENT_NOT_FOUND`,
        `ERR_SHRINK_PERIOD_NOT_FOUND`, `ERR_PHYSICAL_INVENTORY_NOT_FOUND` or
        `ERR_PHYSICAL_INVENTORY_LINE_NOT_FOUND`."

        Design: Corner/errors/unknown_path_ids_return_family_specific_not_found
        """
        families = [
            (api.get_category, ERR_CATEGORY_NOT_FOUND),
            (api.get_store, ERR_STORE_NOT_FOUND),
            (api.get_vendor, ERR_VENDOR_NOT_FOUND),
            (api.get_counter_firm, ERR_COUNTER_FIRM_NOT_FOUND),
            (api.get_item, ERR_ITEM_NOT_FOUND),
            (api.get_stock_position, ERR_STOCK_POSITION_NOT_FOUND),
            (api.get_tag_batch, ERR_TAG_BATCH_NOT_FOUND),
            (api.get_count_schedule, ERR_COUNT_SCHEDULE_NOT_FOUND),
            (api.get_count_task, ERR_COUNT_TASK_NOT_FOUND),
            (api.get_count_line, ERR_COUNT_LINE_NOT_FOUND),
            (api.get_investigation, ERR_INVESTIGATION_NOT_FOUND),
            (api.get_adjustment, ERR_ADJUSTMENT_NOT_FOUND),
            (api.get_shrink_period, ERR_SHRINK_PERIOD_NOT_FOUND),
            (api.get_physical_inventory, ERR_PHYSICAL_INVENTORY_NOT_FOUND),
            (api.get_physical_inventory_line, ERR_PHYSICAL_INVENTORY_LINE_NOT_FOUND),
        ]
        for accessor, error_id in families:
            validate_error(accessor(NON_EXISTENT_UUID, ADMIN), error_id, 404)

    def test_body_foreign_keys_are_resolved_in_the_declared_input_order(self, api):
        """
        An unresolvable body key raises the 404 of the type it names.

        "Foreign keys supplied in a request body are resolved after path identifiers,
        in the order the endpoint's input list declares them, and an unresolvable body
        foreign key raises the same 404 for the type it names — a body `store_id` or
        `destination_store_id` that matches no store raises `ERR_STORE_NOT_FOUND`, a
        body `primary_vendor_id` or `vendor_id` that matches no vendor raises
        `ERR_VENDOR_NOT_FOUND`, a body `category_id` raises `ERR_CATEGORY_NOT_FOUND`,
        a body `item_id` raises `ERR_ITEM_NOT_FOUND`, a body `counter_firm_id` raises
        `ERR_COUNTER_FIRM_NOT_FOUND`, a body `count_schedule_id` raises
        `ERR_COUNT_SCHEDULE_NOT_FOUND`, a body `shrink_period_id` raises
        `ERR_SHRINK_PERIOD_NOT_FOUND`, and a body `investigation_id` raises
        `ERR_INVESTIGATION_NOT_FOUND`."

        Design: Corner/errors/unknown_path_ids_return_family_specific_not_found
        """
        category = fx.create_category(api, f.apparel_category_payload())
        vendor = fx.create_vendor(api)

        validate_error(
            api.create_item(f.item_payload(NON_EXISTENT_UUID, vendor["id"]), ADMIN),
            ERR_CATEGORY_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_item(f.item_payload(category["id"], NON_EXISTENT_UUID), ADMIN),
            ERR_VENDOR_NOT_FOUND,
            404,
        )

        item = fx.create_item(api, f.item_payload(category["id"], vendor["id"]))
        validate_error(
            api.create_stock_position(
                f.stock_position_payload(NON_EXISTENT_UUID, item["id"]), ADMIN
            ),
            ERR_STORE_NOT_FOUND,
            404,
        )

        rows, meta = validate_paginated(api.list_items(ANALYST))
        assert meta["total_count"] == 1


class TestDuplicateNaturalKeys:
    def test_every_reference_family_reports_its_own_conflict(self, api):
        """
        Natural-key uniqueness is checked per family, with its own identifier.

        "Request shape: required fields present, declared types honoured, numeric and
        length ranges satisfied (`ERR_INVALID_REQUEST`), then enum membership
        (`ERR_INVALID_ENUM_VALUE`), then pagination bounds on list reads
        (`ERR_INVALID_PAGINATION`), then natural-key uniqueness on reference-data
        creation (`ERR_DUPLICATE_CATEGORY_CODE`, `ERR_DUPLICATE_STORE_CODE`,
        `ERR_DUPLICATE_VENDOR_CODE`, `ERR_DUPLICATE_COUNTER_FIRM_CODE`,
        `ERR_DUPLICATE_SKU`)."

        Design: Corner/errors/duplicate_natural_keys_return_family_specific_conflicts
        """
        category = fx.create_category(api, f.apparel_category_payload())
        fx.create_store(api, f.store_payload())
        vendor = fx.create_vendor(api)
        fx.create_counter_firm(api)
        fx.create_item(api, f.item_payload(category["id"], vendor["id"]))

        validate_error(
            api.create_category(
                f.apparel_category_payload(
                    name="Apparel Duplicate", count_cadence_days=60
                ),
                ADMIN,
            ),
            ERR_DUPLICATE_CATEGORY_CODE,
            409,
        )
        validate_error(
            api.create_store(f.store_payload(name="Store 100 Again"), ADMIN),
            ERR_DUPLICATE_STORE_CODE,
            409,
        )
        validate_error(
            api.create_vendor(f.vendor_payload(name="Vendor One Again"), ADMIN),
            ERR_DUPLICATE_VENDOR_CODE,
            409,
        )
        validate_error(
            api.create_counter_firm(
                f.counter_firm_payload(name="Counting Firm One Again"), ADMIN
            ),
            ERR_DUPLICATE_COUNTER_FIRM_CODE,
            409,
        )
        validate_error(
            api.create_item(
                f.item_payload(category["id"], vendor["id"], description="Crew tee v2"),
                ADMIN,
            ),
            ERR_DUPLICATE_SKU,
            409,
        )

        rows, meta = validate_paginated(api.list_categories(ANALYST))
        assert meta["total_count"] == 1
        assert rows[0]["count_cadence_days"] == 30

    def test_the_constraint_binds_the_exact_code_and_not_the_table(self, api):
        """
        A second category with a different code is ordinary reference data.

        "A **merchandise category** is registered with a `code` of 1 to 32 characters
        drawn from uppercase alphanumerics and the hyphen and unique across all
        categories, together with a human-readable `name` of 1 to 120 characters. A
        second category submitted with a `code` already on file is rejected with
        `ERR_DUPLICATE_CATEGORY_CODE`."

        Design: Corner/errors/duplicate_natural_keys_return_family_specific_conflicts
        """
        fx.create_category(api, f.apparel_category_payload())

        validate_error(
            api.create_category(f.apparel_category_payload(), ADMIN),
            ERR_DUPLICATE_CATEGORY_CODE,
            409,
        )

        home = validate_success(
            api.create_category(f.home_category_payload(), ADMIN), 201
        )
        assert home["code"] == "HOME"

        rows, meta = validate_paginated(api.list_categories(ANALYST))
        assert meta["total_count"] == 2
        assert sorted(row["code"] for row in rows) == ["APPAREL", "HOME"]


class TestEncodingMustAgreeWithTheSku:
    @staticmethod
    def _draft_batch(api):
        """A DRAFT batch of 1000 units for a SGTIN_96 SKU with prefix length 7."""
        world = fx.apparel_reference_world(api, baseline=100)
        assert world["item"]["tag_encoding_scheme"] == "SGTIN_96"
        assert world["item"]["epc_prefix_length"] == 7
        vendor_headers = make_vendor_rep_headers(world["vendor_id"])
        batch = validate_success(
            api.create_tag_batch(
                f.tag_batch_payload(
                    world["vendor_id"],
                    world["item_id"],
                    world["store_id"],
                    quantity_encoded=1000,
                ),
                vendor_headers,
            ),
            201,
        )
        assert batch["status"] == "DRAFT"
        return batch, vendor_headers

    def test_the_wrong_scheme_leaves_the_batch_unencoded(self, api):
        """
        The scheme axis is checked against the SKU's own declaration.

        "The payload declares the `encoding_scheme` actually used, which must be either
        `SGTIN_96` or `SGTIN_198`, and the `epc_prefix` printed on the tags, which must
        consist of digits only. Two things must line up with the SKU: the submitted
        `encoding_scheme` must equal the SKU's `tag_encoding_scheme`, and the number of
        digits in `epc_prefix` must equal the SKU's `epc_prefix_length`. A failure of
        either check is rejected with `ERR_TAG_SCHEME_MISMATCH` (HTTP 422)."

        Design: Corner/errors/tag_batch_encode_with_mismatched_scheme_or_prefix_length_rejected
        """
        batch, vendor_headers = self._draft_batch(api)

        validate_error(
            api.encode_tag_batch(
                batch["id"],
                f.encode_payload(encoding_scheme="SGTIN_198"),
                vendor_headers,
            ),
            ERR_TAG_SCHEME_MISMATCH,
            422,
        )

        stalled = fx.read_tag_batch(api, batch["id"])
        assert stalled["status"] == "DRAFT"
        assert stalled["verification_outcome"] is None
        assert stalled["read_rate_bps"] == 0

    def test_a_right_scheme_with_a_short_prefix_is_rejected_just_as_firmly(self, api):
        """
        The prefix-length axis is independent of the scheme axis.

        "Two things must line up with the SKU: the submitted `encoding_scheme` must
        equal the SKU's `tag_encoding_scheme`, and the number of digits in `epc_prefix`
        must equal the SKU's `epc_prefix_length`. A failure of either check is rejected
        with `ERR_TAG_SCHEME_MISMATCH` (HTTP 422)."

        Design: Corner/errors/tag_batch_encode_with_mismatched_scheme_or_prefix_length_rejected
        """
        batch, vendor_headers = self._draft_batch(api)

        validate_error(
            api.encode_tag_batch(
                batch["id"], f.encode_payload(epc_prefix="061414"), vendor_headers
            ),
            ERR_TAG_SCHEME_MISMATCH,
            422,
        )
        assert fx.read_tag_batch(api, batch["id"])["status"] == "DRAFT"

        encoded = validate_success(
            api.encode_tag_batch(batch["id"], f.encode_payload(), vendor_headers)
        )
        assert encoded["status"] == "ENCODED"
        assert encoded["encoding_scheme"] == "SGTIN_96"
        assert encoded["epc_prefix"] == "0614141"
        assert encoded["required_sample_units"] == 50


class TestVerificationGatesRunInOrder:
    def test_a_short_sample_outranks_arithmetically_impossible_counts(self, api):
        """
        The sample floor is reported even when the counts are also incoherent.

        "Three gates apply in order. The batch must be in `RECEIVED`. `sampled_units`
        must be at least the `required_sample_units` frozen at encoding, otherwise the
        submission is rejected with `ERR_SAMPLE_BELOW_REQUIRED` (HTTP 422). And the
        counts must be internally coherent: `readable_units` may not exceed
        `sampled_units`, `unencoded_units` may not exceed `sampled_units`, and the sum
        of `readable_units` and `unencoded_units` may not exceed `sampled_units`; a
        violation of any of the three is rejected with
        `ERR_INVALID_VERIFICATION_COUNTS` (HTTP 422)."

        Design: Corner/errors/tag_verify_with_sample_below_required_or_impossible_counts_rejected
        """
        world = fx.encoded_tag_batch_world(api, quantity=1000, baseline=100)
        assert world["encoded_batch"]["required_sample_units"] == 50

        validate_error(
            api.verify_tag_batch(
                world["batch_id"],
                f.verify_payload(sampled_units=40, readable_units=45),
                world["store_headers"],
            ),
            ERR_SAMPLE_BELOW_REQUIRED,
            422,
        )

        stalled = fx.read_tag_batch(api, world["batch_id"])
        assert stalled["status"] == "RECEIVED"
        assert stalled["verification_outcome"] is None
        assert stalled["sampled_units"] == 0
        assert stalled["readable_units"] == 0
        assert fx.read_vendor(api, world["vendor_id"])["tag_compliance_score_bps"] == 10000

    def test_incoherent_counts_are_rejected_and_a_coherent_sample_passes(self, api):
        """
        Each of the three coherence clauses reports the same identifier.

        "And the counts must be internally coherent: `readable_units` may not exceed
        `sampled_units`, `unencoded_units` may not exceed `sampled_units`, and the sum
        of `readable_units` and `unencoded_units` may not exceed `sampled_units`; a
        violation of any of the three is rejected with
        `ERR_INVALID_VERIFICATION_COUNTS` (HTTP 422)."

        Design: Corner/errors/tag_verify_with_sample_below_required_or_impossible_counts_rejected
        """
        world = fx.encoded_tag_batch_world(api, quantity=1000, baseline=100)

        validate_error(
            api.verify_tag_batch(
                world["batch_id"],
                f.verify_payload(sampled_units=50, readable_units=51),
                world["store_headers"],
            ),
            ERR_INVALID_VERIFICATION_COUNTS,
            422,
        )
        validate_error(
            api.verify_tag_batch(
                world["batch_id"],
                f.verify_payload(
                    sampled_units=50, readable_units=30, unencoded_units=25
                ),
                world["store_headers"],
            ),
            ERR_INVALID_VERIFICATION_COUNTS,
            422,
        )
        assert fx.read_tag_batch(api, world["batch_id"])["status"] == "RECEIVED"

        passed = validate_success(
            api.verify_tag_batch(
                world["batch_id"],
                f.verify_payload(sampled_units=50, readable_units=50),
                world["store_headers"],
            )
        )
        assert passed["read_rate_bps"] == 10000
        assert passed["verification_outcome"] == "PASS"
        assert passed["status"] == "VERIFIED_PASS"
