"""Hull completion: creation gate on the order's state, HIN assignment, the
creator stamp, one-hull-per-order, and certification gates (PRD §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_hull,
    book_order_no_options,
    certify_hull,
    confirm_order,
    create_dealer,
    create_hull,
    create_hull_payload,
    create_model,
    create_run,
    create_slot,
    get_hull,
    get_order,
    make_compliance_officer_headers,
    make_dealer_principal_headers,
    make_production_planner_headers,
    set_clock,
    setup_bookable_world,
    setup_certified_hull,
    setup_committed_hull,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ANY = TEST_USERS["any_headers"]


class TestHullCreationGate:
    def test_hull_creation_rejected_on_allocated_order(self, api):
        """PRD §3.6: "The order must be `COMMITTED` — any other state, including
        one whose run has since closed, is refused with
        `ERR_INVALID_ORDER_STATE`"

        Design: Difficulty/cross_entity_state_dependency/hull_creation_gated_on_dealer_order_state
        """
        world = setup_bookable_world(api, with_options=False)
        order = book_order_no_options(
            api, world["dealer"], world["model"], slot_id=world["slot"]["id"]
        )
        assert order["status"] == "ALLOCATED"  # booked but never confirmed
        resp = api.create_hull(
            create_hull_payload(order["id"]),
            make_production_planner_headers("planner-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE)
        # No hull was persisted for the order, and the order is untouched.
        data, meta = validate_paginated(
            api.list_hulls(ANY, params={"order_id": order["id"]})
        )
        assert meta["total_count"] == 0
        assert get_order(api, order["id"])["status"] == "ALLOCATED"

    def test_hull_creation_rejected_on_waitlisted_order(self, api):
        """PRD §3.6: "The order must be `COMMITTED` — any other state, including
        one whose run has since closed, is refused with
        `ERR_INVALID_ORDER_STATE`"

        A WAITLISTED order never entered production and rejects completion.

        Design: Difficulty/cross_entity_state_dependency/hull_creation_gated_on_dealer_order_state
        """
        model = create_model(api)
        dealer = create_dealer(api)
        order = book_order_no_options(api, dealer, model)
        assert order["status"] == "WAITLISTED"
        resp = api.create_hull(
            create_hull_payload(order["id"]),
            make_production_planner_headers("planner-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE)

    def test_second_hull_for_order_rejected(self, api):
        """PRD §3.6: "The order must be `COMMITTED` — any other state, including
        one whose run has since closed, is refused with
        `ERR_INVALID_ORDER_STATE` (the pinned exception: completion does not
        require the run to remain `OPEN`) — and exactly one hull may exist per
        order, a second attempt drawing `ERR_HULL_ALREADY_EXISTS`."

        After the first completion the order is IN_PRODUCTION, so the duplicate
        attempt is blocked by exactly one of the two family-7 state guards.

        Design: Corner/state_machines/hull_already_exists_for_order_rejected
        """
        world = setup_committed_hull(api, with_options=False)
        resp = api.create_hull(
            create_hull_payload(world["order"]["id"]),
            make_production_planner_headers("planner-1"),
        )
        actual = validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_HULL_ALREADY_EXISTS, ApiErrorId.ERR_INVALID_ORDER_STATE],
        )
        assert actual in (
            ApiErrorId.ERR_HULL_ALREADY_EXISTS,
            ApiErrorId.ERR_INVALID_ORDER_STATE,
        )


class TestHullFields:
    def test_hull_created_by_user_id_stamped(self, api):
        """PRD §3.6: "The hull copies `slot_id` and `model_id` from its order,
        stamps `completed_at` from the clock, and records the planner's
        `X-User-ID` as `created_by_user_id`."
        PRD §3.6: "The hull is born `UNCERTIFIED` on its certification dimension
        and `AT_PLANT` on its delivery dimension"

        Design: Corner/entities/hull_fields_created_by_user_id_stamped
        """
        world = setup_bookable_world(api, with_options=False)
        order = book_order_no_options(
            api, world["dealer"], world["model"], slot_id=world["slot"]["id"]
        )
        order = confirm_order(api, order, world["dealer"])
        hull = create_hull(api, order["id"], planner_user_id="planner-42")
        assert_hull(hull)
        assert hull["created_by_user_id"] == "planner-42"
        assert hull["certification_status"] == "UNCERTIFIED"
        assert hull["delivery_status"] == "AT_PLANT"
        assert hull["slot_id"] == world["slot"]["id"]
        assert hull["model_id"] == world["model"]["id"]


class TestHinAssignment:
    def test_hin_serial_sequence_per_model_year(self, api):
        """PRD §3.6: "`serial_no` is a per-model-and-model-year sequence: the
        first hull of a given model and `model_year` takes 1, and each
        subsequent hull takes one more than the highest existing serial for
        that pair."
        PRD §3.6: "The `hin` is a twelve-character composition: the manufacturer
        code `BRW`, then the serial zero-padded to five digits, then a single
        letter for the completion month — A for January through L for December,
        with I skipped by construction of the twelve-letter map — then the last
        digit of the completion year, then the model year modulo 100
        zero-padded to two digits. The first hull of model year 2027 completed
        in August 2026 is therefore `BRW00001H627`"

        Design: Corner/calculations/hin_assignment_serial_sequence_per_model_year
        """
        world = setup_bookable_world(api, with_options=False)
        dealer, model, slot = world["dealer"], world["model"], world["slot"]
        o1 = book_order_no_options(api, dealer, model, slot_id=slot["id"])
        o1 = confirm_order(api, o1, dealer)
        o2 = book_order_no_options(api, dealer, model, slot_id=slot["id"])
        o2 = confirm_order(api, o2, dealer)
        # Both completions stamp the startup clock 2026-08-01 (August 2026).
        h1 = create_hull(api, o1["id"])
        h2 = create_hull(api, o2["id"])
        assert h1["serial_no"] == 1
        assert h1["hin"] == "BRW00001H627", (
            f"first hull of MY2027 completed Aug 2026 must be BRW00001H627, "
            f"got {h1['hin']}"
        )
        assert h2["serial_no"] == 2
        assert h2["hin"] == "BRW00002H627"

    def test_hin_month_letter_december_is_L(self, api):
        """PRD §3.6: "The `hin` is a twelve-character composition: the
        manufacturer code `BRW`, then the serial zero-padded to five digits,
        then a single letter for the completion month — A for January through L
        for December, with I skipped by construction of the twelve-letter map —
        then the last digit of the completion year, then the model year modulo
        100 zero-padded to two digits."

        December 2026 completion of a MY2027 model: letter L, year digit 6.

        Design: Corner/calculations/hin_month_letter_skips_I_december_L
        """
        world = setup_bookable_world(api, with_options=False)
        order = book_order_no_options(
            api, world["dealer"], world["model"], slot_id=world["slot"]["id"]
        )
        order = confirm_order(api, order, world["dealer"])
        set_clock(api, "2026-12-15T00:00:00Z")
        hull = create_hull(api, order["id"])
        assert hull["hin"] == "BRW00001L627", (
            f"December completion must use letter L, got {hull['hin']}"
        )


class TestCertification:
    def test_second_certify_rejected(self, api):
        """PRD §3.6: "Certification is a `ComplianceOfficer` act gated by
        segregation of duties: the hull must be `UNCERTIFIED` (else
        `ERR_INVALID_HULL_STATE`)"

        Design: Corner/state_machines/hull_certify_idempotency_second_certify_rejected
        """
        world = setup_certified_hull(api, with_options=False)
        resp = api.certify_hull(
            world["hull"]["id"], make_compliance_officer_headers("officer-7")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_HULL_STATE)

    def test_segregation_of_duty_blocks_certifier_creator_match(self, api):
        """PRD §3.6: "the certifier's `X-User-ID` must differ from the hull's
        `created_by_user_id` — the planner who reported completion may not
        certify it, and a matching identity fails with
        `ERR_SEGREGATION_OF_DUTY`."

        Design: Corner/validations/segregation_of_duty_blocks_certifier_creator_match
        """
        world = setup_committed_hull(api, with_options=False,
                                     planner_user_id="planner-1")
        resp = api.certify_hull(
            world["hull"]["id"], make_compliance_officer_headers("planner-1")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTY)


class TestHullListFilter:
    def test_hulls_list_filter_by_model_id(self, api):
        """PRD §3.6: "Hulls can be listed with `order_id`, `slot_id`, or
        `model_id` filters"

        Design: Corner/endpoints/hulls_list_filter_by_model_id
        """
        world = setup_bookable_world(api, with_options=False)
        dealer, slot = world["dealer"], world["slot"]
        m1 = world["model"]
        m2 = create_model(api, model_code="SP210", base_price_cents=3000000,
                          production_hours=50)
        o1 = book_order_no_options(api, dealer, m1, slot_id=slot["id"])
        o1 = confirm_order(api, o1, dealer)
        o2 = book_order_no_options(api, dealer, m2, slot_id=slot["id"],
                                   deposit_paid_cents=309000)
        o2 = confirm_order(api, o2, dealer)
        h1 = create_hull(api, o1["id"])
        create_hull(api, o2["id"])
        data, meta = validate_paginated(
            api.list_hulls(ANY, params={"model_id": m1["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == h1["id"]
        assert data[0]["model_id"] == m1["id"]
