"""Scale intake: accounts, grain lots, moisture tests, recertification, OCC."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_customer,
    assert_grain_lot,
    assert_moisture_test,
    certify_test,
    create_customer,
    create_customer_payload,
    create_grain_lot_payload,
    create_lot,
    create_moisture_test,
    create_moisture_test_payload,
    get_lot,
    make_grower_headers,
    make_technician_headers,
    set_clock,
    setup_base,
    validate_error,
    validate_paginated,
    validate_success,
)

class TestCustomerCreationDefaults:
    def test_customer_creation_defaults(self, api, manager_headers):
        """PRD §3.1: "Two optional fields complete the account: an opening
        `prepaid_balance_cents` (the grower's credit on account, defaulting to 0)
        and a `priority_class` — `STANDARD` by default, or `PRIORITY_CONTRACT` for
        growers whose contracts buy queue protection (§3.4). Every account begins
        with `account_status` `ACTIVE`."

        Design: Corner/entities/customer_creation_defaults
        """
        res = api.create_customer(
            create_customer_payload(name="C1", credit_limit_cents=500000),
            manager_headers,
        )
        cust = validate_success(res, 201)
        assert_customer(cust)
        assert cust["priority_class"] == "STANDARD"
        assert cust["prepaid_balance_cents"] == 0
        assert cust["account_status"] == "ACTIVE"


class TestGrainLotIntake:
    def test_grain_lot_computed_and_system_fields(self, api, manager_headers):
        """PRD §3.2: "The system derives `wet_net_weight_lbs` as the gross weight
        minus the tare weight. A new lot's `status` is `RECEIVED`, its `ownership`
        is `GROWER_HELD`, and its `current_owner_id` equals the `customer_id`."
        PRD §3.2: "Intake grading may supply `foreign_material_pct`, defaulting
        to 0.0;"

        Design: Corner/entities/grain_lot_computed_and_system_fields
        """
        cust = create_customer()
        res = api.create_grain_lot(
            create_grain_lot_payload(
                cust["id"], commodity="CORN", gross_weight_lbs=44000,
                tare_weight_lbs=34000, target_moisture_pct=15.0,
            ),
            make_technician_headers("tech-1"),
        )
        lot = validate_success(res, 201)
        assert_grain_lot(lot)
        assert lot["wet_net_weight_lbs"] == 10000
        assert lot["foreign_material_pct"] == 0.0
        assert lot["status"] == "RECEIVED"
        assert lot["ownership"] == "GROWER_HELD"
        assert lot["current_owner_id"] == cust["id"]

    def test_grain_lot_get_not_found_returns_404(self, api, manager_headers):
        """PRD §2.9: "Each unresolvable reference yields its own 404:
        `ERR_CUSTOMER_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_TEST_NOT_FOUND`,
        `ERR_SCHEDULE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
        `ERR_RUN_NOT_FOUND`, `ERR_BLEND_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, or
        `ERR_PAYMENT_NOT_FOUND`."

        Design: Corner/entities/grain_lot_get_not_found_returns_404
        """
        res = api.get_grain_lot(NON_EXISTENT_UUID, manager_headers)
        validate_error(res, ApiErrorId.ERR_LOT_NOT_FOUND, expected_status=404)

    def test_grain_lot_list_pagination_and_status_filter(self, api, manager_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."
        PRD §3.2: "The lot list filters by `customer_id`, `current_owner_id`,
        `certified_test_id`, `status`, and `commodity`."

        Design: Corner/entities/grain_lot_list_pagination_and_status_filter
        """
        cust = create_customer()
        for commodity, target in (("CORN", 15.0), ("SOYBEAN", 13.0), ("WHEAT", 13.5)):
            create_lot(cust["id"], commodity=commodity, target_moisture_pct=target)

        page1, meta1 = validate_paginated(api.list_grain_lots(
            manager_headers, params={"customer_id": cust["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_grain_lots(
            manager_headers, params={"customer_id": cust["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        filtered, meta3 = validate_paginated(api.list_grain_lots(
            manager_headers, params={"customer_id": cust["id"], "status": "RECEIVED"}))
        assert meta3["total_count"] == 3
        assert all(lot["status"] == "RECEIVED" for lot in filtered)

    def test_grain_lot_invalid_enum_commodity(self, api, manager_headers):
        """PRD §3.2: "The payload names the delivering account (`customer_id`),
        the `commodity` — one of `CORN`, `SOYBEAN`, or `WHEAT` — the two scale
        weights `gross_weight_lbs` (truck plus grain) and `tare_weight_lbs`
        (empty truck), and the contractual dry-down `target_moisture_pct`"
        PRD §2.9: "Violations yield `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/grain_lot_invalid_enum_commodity
        """
        cust = create_customer()
        res = api.create_grain_lot(
            create_grain_lot_payload(
                cust["id"], commodity="RICE", gross_weight_lbs=44000,
                tare_weight_lbs=34000, target_moisture_pct=15.0,
            ),
            make_technician_headers("tech-1"),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_grain_lot_gross_not_above_tare_rejected(self, api, manager_headers):
        """PRD §2.9: "Request shape — required fields present, types valid, enum
        values legal, `gross_weight_lbs` greater than `tare_weight_lbs` with
        `tare_weight_lbs` positive, monetary amounts positive,
        `sample_moisture_pct` strictly between 0 and 60, and a lot's
        `target_moisture_pct` between 10.0 and 20.0 inclusive."

        Design: Corner/entities/grain_lot_gross_not_above_tare_rejected
        """
        cust = create_customer()
        res = api.create_grain_lot(
            create_grain_lot_payload(
                cust["id"], commodity="CORN", gross_weight_lbs=34000,
                tare_weight_lbs=34000, target_moisture_pct=15.0,
            ),
            make_technician_headers("tech-1"),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestMoistureTestLifecycle:
    def test_certified_test_supersede_recomputes_lot_baseline(self, api, manager_headers):
        """PRD §3.2: "In both cases the same cascade runs: any prior `CERTIFIED`
        or `DISPUTED` test of the same lot becomes `SUPERSEDED`; the lot's
        `intake_moisture_pct` and `current_moisture_pct` take the new test's
        `sample_moisture_pct`; the lot's `certified_test_id` points at the newly
        certified test; the test records `certified_by_user_id` and a
        logical-clock `certified_at`; the lot's provisional baseline is
        recomputed as below; and the lot's version increments."
        PRD §3.2: "The water-shrink percentage is the lot's intake moisture minus
        its target moisture, divided by one hundred minus the target moisture,
        the quotient multiplied by one hundred."
        PRD §3.2: "The `provisional_dry_weight_lbs` is the wet net weight
        multiplied by one minus the provisional shrink percentage divided by one
        hundred, rounded half up to whole pounds."

        Design: Corner/entities/certified_test_supersede_recomputes_lot_baseline
        """
        ctx = setup_base(with_unit=False)
        cust = ctx["cust"]
        lot = create_lot(cust["id"], commodity="CORN", gross_weight_lbs=44000,
                         tare_weight_lbs=34000, target_moisture_pct=15.0,
                         foreign_material_pct=2.0)
        test1 = create_moisture_test(lot["id"], 22.5,
                                     expected_grain_lot_version=lot["version"],
                                     tech_id="tech-1")
        certify_test(test1["id"], tech_id="tech-1")
        before = get_lot(lot["id"])
        # (22.5-15)/85*100 + 0.5 = 9.323529...; 10000*(1-0.09323529) = 9067.647 -> 9068
        assert before["provisional_dry_weight_lbs"] == 9068

        dispute = api.dispute_moisture_test(test1["id"], make_grower_headers(cust["id"]))
        assert validate_success(dispute, 200)["status"] == "DISPUTED"

        test2 = create_moisture_test(lot["id"], 21.0, tech_id="tech-2",
                                     supersedes_test_id=test1["id"])
        certify_test(test2["id"], tech_id="tech-2")

        old = validate_success(api.get_moisture_test(test1["id"], manager_headers), 200)
        assert old["status"] == "SUPERSEDED"
        after = get_lot(lot["id"])
        assert after["intake_moisture_pct"] == pytest.approx(21.0)
        assert after["certified_test_id"] == test2["id"]
        # (21-15)/85*100 + 0.5 = 7.558824%; 10000*(1-0.07558824) = 9244.12 -> 9244
        assert after["provisional_dry_weight_lbs"] == 9244

    def test_moisture_test_certify_twice_rejected(self, api, manager_headers):
        """PRD §3.2: "An `IntakeTechnician` certifies a `PRELIMINARY` test while
        its lot is `RECEIVED` or `TESTED`; against any other lot state the
        attempt is rejected with `ERR_INVALID_STATE`."
        PRD §2.9: "Other state mismatches yield `ERR_INVALID_STATE` (all HTTP
        409)."

        Design: Corner/state_machines/moisture_test_certify_twice_rejected
        """
        ctx = setup_base(with_unit=False)
        lot = create_lot(ctx["cust"]["id"])
        test = create_moisture_test(lot["id"], 20.0,
                                    expected_grain_lot_version=lot["version"],
                                    tech_id="tech-1")
        certify_test(test["id"], tech_id="tech-1")

        res = api.certify_moisture_test(test["id"], make_technician_headers("tech-1"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api.get_moisture_test(test["id"], manager_headers), 200)
        assert after["status"] == "CERTIFIED"

    def test_retest_same_technician_sod_violation(self, api, manager_headers):
        """PRD §2.8: "Moisture disputes: when a lot's current certified test
        stands DISPUTED, the technician who certifies the retest must differ from
        the technician who certified the disputed test. Violations are rejected
        with `ERR_RETEST_SO_DUTY_VIOLATION`."

        Design: Corner/validations/retest_same_technician_sod_violation
        """
        ctx = setup_base(with_unit=False)
        cust = ctx["cust"]
        lot = create_lot(cust["id"])
        test1 = create_moisture_test(lot["id"], 22.5,
                                     expected_grain_lot_version=lot["version"],
                                     tech_id="tech-1")
        certify_test(test1["id"], tech_id="tech-1")
        api.dispute_moisture_test(test1["id"], make_grower_headers(cust["id"]))
        test2 = create_moisture_test(lot["id"], 21.0, tech_id="tech-2",
                                     supersedes_test_id=test1["id"])

        # Same certifier as the disputed test -> segregation violation.
        res = api.certify_moisture_test(test2["id"], make_technician_headers("tech-1"))
        validate_error(res, ApiErrorId.ERR_RETEST_SO_DUTY_VIOLATION, expected_status=403)

        # A different technician certifies the retest successfully.
        certified = validate_success(
            api.certify_moisture_test(test2["id"], make_technician_headers("tech-2")), 200)
        assert certified["status"] == "CERTIFIED"
        old = validate_success(api.get_moisture_test(test1["id"], manager_headers), 200)
        assert old["status"] == "SUPERSEDED"
        assert get_lot(lot["id"])["intake_moisture_pct"] == pytest.approx(21.0)


class TestMoistureTestOcc:
    def test_occ_moisture_test_stale_lot_version(self, api, manager_headers):
        """PRD §2.7: "Creating a moisture test requires the request to carry
        `expected_grain_lot_version`, the client's last observed `version` of the
        target grain lot. If the lot's current version has moved past the
        declared value, the create is rejected with `ERR_STALE_LOT_VERSION`
        (HTTP 412)."
        PRD §2.7: "Note that creating a moisture test itself increments the
        lot's version by one, so two tests opened against the same observed
        version cannot both succeed."

        Design: Corner/cross_cutting_layers/occ_moisture_test_stale_lot_version
        """
        ctx = setup_base(with_unit=False)
        lot = create_lot(ctx["cust"]["id"])
        observed_version = lot["version"]

        first = api.create_moisture_test(
            create_moisture_test_payload(lot["id"], observed_version,
                                         sample_moisture_pct=20.0),
            make_technician_headers("tech-1"),
        )
        validate_success(first, 201)

        stale = api.create_moisture_test(
            create_moisture_test_payload(lot["id"], observed_version,
                                         sample_moisture_pct=20.5),
            make_technician_headers("tech-1"),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_LOT_VERSION, expected_status=412)

        # The single successful create bumped the lot's version exactly once.
        assert get_lot(lot["id"])["version"] == observed_version + 1


class TestExistenceBeforeShape:
    def test_missing_required_and_bad_fk_returns_not_found(self, api, technician_headers):
        """PRD §2.9: "Requests are validated in a fixed order, and a failure at
        an earlier gate masks every later one — a request never reports a
        business-rule violation it would also have failed on authentication."
        PRD §2.9: "Reference existence — path identifiers resolve first, in
        left-to-right order as they appear in the URL, then foreign-key
        identifiers in the request body (`customer_id`, `lot_id`, `unit_id`,
        `queue_ticket_id`, schedule references, and so on)."

        Design: Corner/validations/missing_required_and_bad_fk_returns_not_found
        """
        # Non-existent lot_id AND missing required fields: existence (gate 4)
        # fires before request shape (gate 5).
        res = api.create_moisture_test({"lot_id": NON_EXISTENT_UUID}, technician_headers)
        validate_error(res, ApiErrorId.ERR_LOT_NOT_FOUND, expected_status=404)
