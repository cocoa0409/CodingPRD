"""Entity shapes: creation defaults, computed fields, journals and lookups.

These tests read the stored shape of a row rather than exercise a workflow —
what a fresh row contains, which fields the server writes for itself, and what
the two append-only journals expose.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    ApiErrorId,
    assert_stamped_at,
    make_distributor_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as h

INSTANT = "2026-08-05T09:00:00Z"


class TestDistributorCreation:
    """A fresh distributor is active with both lifetime counters at zero."""

    def test_creation_returns_201_with_zeroed_counters(self, api):
        """The new row is ACTIVE at version 1 with nothing yet initiated.

        PRD: "Both lifetime counters — `deposits_initiated_cents`, the running sum of
        deposit value this distributor has put into commerce, and
        `containers_initiated_count`, the running sum of containers behind that value —
        start at 0."

        Design: Corner/entities/distributor_creation_returns_201_with_zeroed_counters
        """
        h.set_clock(api, INSTANT)

        response = api.create_distributor(
            f.create_distributor_payload(), ADMIN_HEADERS
        )
        created = validate_success(response, expected_status=201)

        envelope = response.json()
        assert envelope["response_type"] == "object"
        assert envelope["meta"]["api_request_id"].startswith("req_")

        assert is_valid_uuid(created["id"])
        assert created["status"] == "ACTIVE"
        assert created["deposits_initiated_cents"] == 0
        assert created["containers_initiated_count"] == 0
        assert created["version"] == 1
        assert is_iso8601_timestamp(created["created_at"])
        assert_stamped_at(created["created_at"], INSTANT)

        stored = validate_success(api.get_distributor(created["id"], ADMIN_HEADERS))
        assert stored["legal_name"] == "Cascade Bottling LLC"
        assert stored["state_code"] == "OR"
        assert stored["permit_number"] == "PERMIT-1001"


class TestDraftLabelRetrieval:
    """Coverage is decided by submission, not by creation."""

    def test_draft_label_reads_back_without_a_coverage_determination(self, api):
        """A never-submitted label carries null coverage and a zero deposit.

        PRD: "A newly created label sits in `registration_state` `DRAFT` with
        `deposit_cents` at 0 and no coverage determination yet made; `coverage_status` and
        `coverage_reason` are only written when the label is first submitted."

        Design: Corner/entities/beverage_product_retrieval_returns_stored_label_before_submission
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_draft_product(
            api, distributor["id"], brand_name="Cascade Spring"
        )

        response = api.get_beverage_product(
            product["id"], make_distributor_headers(distributor["id"])
        )
        stored = validate_success(response)

        assert stored["brand_name"] == "Cascade Spring"
        assert stored["registration_state"] == "DRAFT"
        assert stored["coverage_status"] is None
        assert stored["coverage_reason"] is None
        assert stored["deposit_cents"] == 0
        assert stored["registered_at"] is None
        assert stored["version"] == 1


class TestLabelListingPagination:
    """The envelope's pagination fields describe the whole match, not the page."""

    def test_two_pages_cover_three_labels_without_repetition(self, api):
        """limit 2 splits three labels into a full page and a remainder.

        PRD: "`total_count` is the number of rows matching the filter before pagination is
        applied, and `has_more` is true when rows remain beyond the current window."

        Design: Corner/entities/beverage_products_listing_paginates_with_total_count_and_has_more
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        h.create_draft_product(
            api, distributor["id"], brand_name="Cascade Spring", upc="011110000001"
        )
        h.create_draft_product(
            api,
            distributor["id"],
            brand_name="Cascade Cola",
            beverage_type="CARBONATED_SOFT_DRINK",
            container_material="ALUMINUM",
            fill_volume_ml=355,
            upc="011110000002",
        )
        h.create_draft_product(
            api,
            distributor["id"],
            brand_name="Cascade Cider",
            beverage_type="HARD_CIDER",
            container_material="GLASS",
            upc="011110000003",
        )

        first_rows, first_meta = validate_paginated(
            api.list_beverage_products(ADMIN_HEADERS, params={"limit": 2, "offset": 0})
        )
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert len(first_rows) == 2

        second_rows, second_meta = validate_paginated(
            api.list_beverage_products(ADMIN_HEADERS, params={"limit": 2, "offset": 2})
        )
        assert second_meta["limit"] == 2
        assert second_meta["offset"] == 2
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert len(second_rows) == 1

        seen = [row["upc"] for row in first_rows + second_rows]
        assert sorted(seen) == ["011110000001", "011110000002", "011110000003"]

        _, default_meta = validate_paginated(api.list_beverage_products(ADMIN_HEADERS))
        assert default_meta["limit"] == 10
        assert default_meta["offset"] == 0
        assert default_meta["total_count"] == 3
        assert default_meta["has_more"] is False


class TestUnknownRetailerLookup:
    """An unstored identifier is an error envelope, not an empty success."""

    def test_unknown_retailer_id_returns_the_error_envelope(self, api):
        """The read reports the store-specific 404 with a populated message.

        PRD: "Every identifier in the path resolves to a stored row, validated left to
        right → otherwise the 404 that names the first unresolved segment:
        `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_CENTER_NOT_FOUND`,
        `ERR_MACHINE_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
        `ERR_BAG_DROP_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND` or
        `ERR_PERIOD_NOT_FOUND`."

        Design: Corner/entities/retailer_lookup_with_unknown_id_returns_not_found
        """
        h.set_clock(api, INSTANT)

        response = api.get_retailer(NON_EXISTENT_UUID, ADMIN_HEADERS)
        error = validate_error(
            response, ApiErrorId.ERR_RETAILER_NOT_FOUND.value, expected_status=404
        )

        envelope = response.json()
        assert envelope["response_type"] == "error"
        assert error["message"].strip() != ""
        assert envelope["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(envelope["meta"]["api_request_timestamp"])

        _, meta = validate_paginated(api.list_retailers(ADMIN_HEADERS))
        assert meta["total_count"] == 0


class TestCentreRequiredFields:
    """The accepted-materials list has no default, so it cannot be omitted."""

    def test_centre_without_accepted_materials_is_refused(self, api):
        """Omitting the required list is a request-shape failure and stores nothing.

        PRD: "Request shape: every required body field is present, every enum value is a
        declared member, every integer lies inside its declared range, every state code is
        exactly two uppercase letters, dates are well formed, and the site/channel pairing
        rules hold — `center_id` required and `retailer_id` absent when `site_type` is
        `CENTER`; `retailer_id` required and `center_id` absent when `site_type` is
        `RETAILER`; `machine_id` required when `channel` is `MACHINE_COUNT` and absent when
        `channel` is `HAND_COUNT`; and `channel` forced to `HAND_COUNT` whenever `site_type`
        is `RETAILER`."

        PRD: "Any violation is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/center_creation_without_accepted_materials_returns_invalid_request
        """
        h.set_clock(api, INSTANT)

        response = api.create_redemption_center(
            {"site_name": "Bend Redemption Center", "x_miles": 0.0, "y_miles": 0.0},
            ADMIN_HEADERS,
        )
        validate_error(
            response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
        )

        _, meta = validate_paginated(api.list_redemption_centers(ADMIN_HEADERS))
        assert meta["total_count"] == 0


class TestNetworkDefaults:
    """Omitting the optional inputs yields the declared defaults, not nulls."""

    def test_centre_and_machine_apply_their_declared_defaults(self, api):
        """The centre takes 350/0/true and the machine a 2000-container bin.

        PRD: "`accepts_all_materials`, which defaults to true and marks a centre that takes
        every covered material — only such a centre can satisfy a retailer exemption;
        `daily_account_cap_containers`, the per-account daily payable container allowance
        the centre enforces, defaulting to 350; and `opening_cash_cents`, the cash loaded
        into the payout drawer, defaulting to 0."

        Design: Corner/entities/center_and_machine_creation_apply_declared_defaults
        """
        h.set_clock(api, INSTANT)

        center = validate_success(
            api.create_redemption_center(
                f.create_redemption_center_payload(site_name="Salem Redemption Center"),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert center["accepts_all_materials"] is True
        assert center["daily_account_cap_containers"] == 350
        assert center["opening_cash_cents"] == 0
        assert center["cash_drawer_balance_cents"] == 0
        assert center["status"] == "PROVISIONAL"

        machine = validate_success(
            api.create_machine(
                center["id"],
                f.create_machine_payload(
                    asset_tag="RVM-2001", accepted_material="ALUMINUM"
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert machine["bin_capacity_containers"] == 2000
        assert machine["status"] == "IDLE"
        assert machine["bin_filled_count"] == 0
        assert machine["jam_count_today"] == 0
        assert machine["jam_day"] is None
        assert machine["open_session_count"] == 0

        assert h.read_center(api, center["id"], ADMIN_HEADERS)["machine_count"] == 1


class TestCentreDrawerIsComputed:
    """The drawer balance is a projection that activation seeds."""

    def test_drawer_is_zero_until_activation_copies_the_opening_cash(self, api):
        """A PROVISIONAL centre holds no cash however much was loaded on paper.

        PRD: "A new centre opens in `status` `PROVISIONAL` with
        `cash_drawer_balance_cents` at 0 and every derived counter at 0."

        Design: Corner/entities/center_cash_drawer_is_computed_and_extra_field_input_ignored
        """
        h.set_clock(api, INSTANT)

        center = validate_success(
            api.create_redemption_center(
                f.create_redemption_center_payload(
                    site_name="Bend Redemption Center", opening_cash_cents=50000
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert center["cash_drawer_balance_cents"] == 0
        assert center["opening_cash_cents"] == 50000

        h.install_machine(api, center["id"])
        activated = h.activate_center(api, center["id"])

        assert activated["cash_drawer_balance_cents"] == 50000
        assert activated["status"] == "OPERATIONAL"
        assert activated["suspension_reason"] is None


class TestVisitSystemFields:
    """The visit's date and both state dimensions are server-written."""

    def test_visit_date_and_both_dimensions_come_from_the_server(self, api, world):
        """Opening a visit stamps the logical date and starts OPEN and PENDING.

        PRD: "The server stamps `visit_date` from the logical clock as the calendar date on
        which the visit opened, and opens the visit with `count_status` `OPEN` and
        `payout_status` `PENDING`."

        Design: Corner/entities/visit_system_fields_generated_and_client_state_input_ignored
        """
        response = api.create_redemption_visit(
            f.center_machine_visit_payload(
                world.center_id, world.machine_id, world.account_id
            ),
            world.center_headers,
        )
        visit = validate_success(response, expected_status=201)

        assert visit["visit_date"] == "2026-08-05"
        assert visit["count_status"] == "OPEN"
        assert visit["payout_status"] == "PENDING"
        assert visit["presented_total"] == 0
        assert visit["payout_cents"] == 0
        assert visit["counted_at"] is None
        assert_stamped_at(visit["created_at"], INSTANT)
        assert visit["version"] == 1


class TestLabelTypeConstraints:
    """Enum membership, integer ranges and state-code shape are all rung 7."""

    def test_bad_enum_zero_volume_and_long_state_code_are_all_refused(self, api):
        """Three separately malformed labels each fail, and none is stored.

        PRD: "every enum value is a declared member, every integer lies inside its declared
        range, every state code is exactly two uppercase letters, dates are well formed"

        Design: Corner/entities/product_creation_with_bad_enum_and_volume_returns_invalid_request
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        headers = make_distributor_headers(distributor["id"])

        bad_enum = api.create_beverage_product(
            f.create_beverage_product_payload(
                distributor["id"],
                brand_name="Cascade Sparkle",
                beverage_type="SPARKLING_JUICE",
            ),
            headers,
        )
        validate_error(
            bad_enum, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
        )

        bad_volume = api.create_beverage_product(
            f.create_beverage_product_payload(
                distributor["id"], fill_volume_ml=0, upc="011110000002"
            ),
            headers,
        )
        validate_error(
            bad_volume, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
        )

        bad_state = api.create_beverage_product(
            f.create_beverage_product_payload(
                distributor["id"], label_state_code="ORE", upc="011110000003"
            ),
            headers,
        )
        validate_error(
            bad_state, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
        )

        _, meta = validate_paginated(api.list_beverage_products(ADMIN_HEADERS))
        assert meta["total_count"] == 0


class TestDepositLedgerImmutability:
    """A deposit ledger line carries no version and no updated_at."""

    def test_initiation_line_has_only_id_and_created_at(self, api):
        """The single ledger row exposes the journal shape and the running liability.

        PRD: "A `DepositLedgerEntry` is the same — `id` and `created_at` only, no
        `updated_at`, no `version`. Corrections to either journal are made by appending a
        compensating line, never by editing a line in place."

        Design: Corner/entities/deposit_ledger_entry_is_immutable_and_carries_no_version
        """
        h.set_clock(api, INSTANT)
        period = h.create_period(api, operating_cost_cents=1000)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        h.initiate_deposits(api, distributor["id"], product["id"], 300, period["id"])

        rows, meta = validate_paginated(
            api.list_ledger_entries(period["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

        line = rows[0]
        assert line["entry_type"] == "DEPOSIT_INITIATED"
        assert line["amount_cents"] == 3000
        assert line["container_count"] == 300
        assert line["liability_after_cents"] == 3000
        assert line["source_kind"] == "DISTRIBUTOR"
        assert line["source_ref_id"] == distributor["id"]
        assert line["period_id"] == period["id"]
        assert is_valid_uuid(line["id"])
        assert_stamped_at(line["created_at"], INSTANT)
        assert "version" not in line
        assert "updated_at" not in line

        assert h.read_period(api, period["id"])["outstanding_liability_cents"] == 3000


class TestCreditJournalImmutability:
    """A credit line records the balance it produced and is never edited."""

    def test_manual_grant_line_reports_the_running_balance(self, api):
        """The grant line carries balance_after_cents while the balance lives on the account.

        PRD: "An `AccountCreditEntry` carries only `id` and `created_at`: it has no
        `updated_at` and no `version`, and there is no endpoint that modifies one once
        written."

        Design: Corner/entities/account_credit_entry_is_immutable_and_reports_running_balance
        """
        h.set_clock(api, INSTANT)
        account = h.create_account(api, bag_drop_enrolled=True)

        validate_success(
            api.post_credit_action(
                account["id"],
                f.credit_action_payload(
                    "MANUAL_GRANT",
                    1000,
                    account["version"],
                    memo="goodwill credit",
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        rows, meta = validate_paginated(
            api.list_credit_entries(account["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1

        line = rows[0]
        assert line["entry_type"] == "MANUAL_GRANT"
        assert line["amount_cents"] == 1000
        assert line["balance_after_cents"] == 1000
        assert line["source_kind"] == "PROGRAM_ACTION"
        assert line["source_ref_id"] == ADMIN_USER_ID
        assert line["memo"] == "goodwill credit"
        assert "version" not in line
        assert "updated_at" not in line

        holder = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert holder["credit_balance_cents"] == 1000
        assert holder["version"] == 2


class TestLotParentResolution:
    """A body foreign key resolves before any business rule runs."""

    def test_unknown_product_id_on_a_lot_is_a_not_found(self, api):
        """The lot request reports the label 404 and leaves the visit untouched.

        PRD: "Every foreign key supplied in the request body resolves to a stored row →
        otherwise the corresponding 404 from that same set (`ERR_DISTRIBUTOR_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_CENTER_NOT_FOUND`, `ERR_MACHINE_NOT_FOUND`,
        `ERR_ACCOUNT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`,
        `ERR_PERIOD_NOT_FOUND`)."

        Design: Corner/entities/lot_creation_with_unknown_product_id_returns_not_found
        """
        h.set_clock(api, INSTANT)
        fleet = h.create_operational_center(
            api, {"site_name": "Bend Redemption Center"}
        )
        center, machine = fleet["center"], fleet["machine"]
        visit = h.open_center_machine_visit(api, center["id"], machine["id"])
        center_headers = h.make_center_headers(center["id"])

        response = api.create_container_lot(
            visit["id"],
            f.create_lot_payload(NON_EXISTENT_UUID, 10, visit["version"]),
            center_headers,
        )
        validate_error(
            response, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value, expected_status=404
        )

        stored = h.read_visit(api, visit["id"], center_headers)
        assert stored["count_status"] == "OPEN"
        assert stored["presented_total"] == 0
        assert stored["version"] == 1

        _, meta = validate_paginated(api.list_visit_lots(visit["id"], center_headers))
        assert meta["total_count"] == 0
