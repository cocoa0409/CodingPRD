"""Order pipeline: confirmation, cancellation cascade, placement and lot rules (PRD §2.8, §3.1, §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_booked_dates,
    book_transport,
    canonical_community_scenario,
    confirm_order,
    create_community,
    create_customer,
    create_lot,
    create_model,
    create_unit,
    get_success_data,
    new_order_scenario,
    progress_to_funded,
    progress_to_financing_approved,
    reserve_lot,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CONSULTANT = TEST_USERS["consultant_headers"]


def test_confirm_already_confirmed_rejected(api, consultant_headers):
    """PRD §2.8: "(all action endpoints): the target resource is in a state from
    which the requested transition exists — this covers idempotent re-fires and
    terminal lockdown — else `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.4: "Confirmation records the deposit, moves `deal_status` from `DRAFT`
    to `PENDING_SITE_EVAL`, moves `payment_status` from `UNPAID` to
    `DEPOSIT_PAID`, and increments the order's `version`."

    Design: Corner/state_machines/confirm_already_confirmed_rejected
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    confirm_order(scn, 212_100)

    resp = api.confirm_sales_order(scn["order"]["id"], {"deposit_cents": 212_100}, consultant_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["deposit_cents"] == 212_100, "a rejected re-fire must not record a second deposit"
    assert order["deal_status"] == "PENDING_SITE_EVAL"


def test_cancel_while_financed_rejected(api, consultant_headers):
    """PRD §3.4: "A `SalesConsultant` may cancel from `DRAFT`, `PENDING_SITE_EVAL`,
    `SITE_APPROVED`, `PENDING_FINANCING`, `FINANCING_APPROVED`, or
    `AWAITING_DELIVERY`, but never from `TITLED`, `CLOSED`, or `CANCELLED`, and
    never while `payment_status` is `FINANCED`; a forbidden cancel is rejected
    with `ERR_ORDER_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_while_financed_returns_not_cancellable
    """
    scn = canonical_community_scenario()
    progress_to_funded(scn)
    assert scn["order"]["deal_status"] == "AWAITING_DELIVERY"
    assert scn["order"]["payment_status"] == "FINANCED"

    resp = api.cancel_sales_order(scn["order"]["id"], consultant_headers)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)

    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["deal_status"] == "AWAITING_DELIVERY" and order["payment_status"] == "FINANCED"
    unit = get_success_data(api.get_home_unit(scn["unit"]["id"], ADMIN))
    assert unit["status"] == "RESERVED", "no compensation fires on a forbidden cancel"


def test_parallel_dimensions_advance_on_confirm(api, consultant_headers):
    """PRD §2.9: "The `payment_status` dimension runs `UNPAID` → `DEPOSIT_PAID` →
    `FINANCED`, with `DEPOSIT_PAID` → `REFUNDED` as the cancellation
    compensation; `REFUNDED` is terminal."
    PRD §2.9: "The two dimensions intersect at exactly three moments:
    confirmation moves payment from `UNPAID` to `DEPOSIT_PAID`, funding moves
    payment to `FINANCED` while the deal advances to `AWAITING_DELIVERY`, and
    cancellation refunds a paid deposit."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_dimensions
    """
    scn = new_order_scenario(placement_type="COMMUNITY_LOT", agreed_home_price_cents=4_200_000)
    assert scn["order"]["deal_status"] == "DRAFT" and scn["order"]["payment_status"] == "UNPAID"

    order = confirm_order(scn, 212_100)
    assert order["deal_status"] == "PENDING_SITE_EVAL", f"deal advances DRAFT -> PENDING_SITE_EVAL, got {order['deal_status']}"
    assert order["payment_status"] == "DEPOSIT_PAID", f"payment advances UNPAID -> DEPOSIT_PAID, got {order['payment_status']}"


def test_parallel_dimensions_cancel_refund_compensation(api, consultant_headers):
    """PRD §2.9: "The `payment_status` dimension runs `UNPAID` → `DEPOSIT_PAID` →
    `FINANCED`, with `DEPOSIT_PAID` → `REFUNDED` as the cancellation
    compensation; `REFUNDED` is terminal."
    PRD §3.4: "the held unit returns `RESERVED` → `AT_DEALER` with its
    `sales_order_id` cleared; a community-placement lot returns `RESERVED` →
    `AVAILABLE`".

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_dimensions
    """
    scn = new_order_scenario(placement_type="COMMUNITY_LOT", agreed_home_price_cents=4_200_000)
    confirm_order(scn, 212_100)

    order = validate_success(api.cancel_sales_order(scn["order"]["id"], consultant_headers))
    assert order["deal_status"] == "CANCELLED" and order["payment_status"] == "REFUNDED"

    unit = get_success_data(api.get_home_unit(scn["unit"]["id"], ADMIN))
    assert unit["status"] == "AT_DEALER", f"unit released by compensation, got {unit['status']}"
    lot = get_success_data(api.get_lot(scn["lot"]["id"], CONSULTANT))
    assert lot["status"] == "AVAILABLE", f"lot released by compensation, got {lot['status']}"


def test_real_property_on_community_lot_rejected(api, consultant_headers):
    """PRD §3.3: "`REAL_PROPERTY` financing — a mortgage — is incompatible with
    leased community land, so a `REAL_PROPERTY` order with `COMMUNITY_LOT`
    placement is rejected with `ERR_FINANCING_TYPE_INCOMPATIBLE`."

    Design: Corner/validations/real_property_on_community_lot_rejected
    """
    model = create_model()
    community = create_community()
    lot = create_lot(community["id"])
    reserve_lot(lot["id"])
    customer = create_customer()
    unit = create_unit(model["id"])

    resp = api.create_sales_order(
        {
            "customer_id": customer["id"],
            "home_unit_id": unit["id"],
            "placement_type": "COMMUNITY_LOT",
            "lot_id": lot["id"],
            "financing_type": "REAL_PROPERTY",
            "agreed_home_price_cents": 4_200_000,
        },
        consultant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FINANCING_TYPE_INCOMPATIBLE)
    unit_after = get_success_data(api.get_home_unit(unit["id"], ADMIN))
    assert unit_after["status"] == "AT_DEALER", "no reservation side effect on rejection"


def test_deposit_one_cent_insufficient(api, consultant_headers):
    """PRD §3.4: "A `SalesConsultant` confirms a `DRAFT` order by supplying
    `deposit_cents`, which must be at least five percent of `total_price_cents`
    rounded half-up to whole cents — a shortfall is rejected with
    `ERR_DEPOSIT_INSUFFICIENT`."

    Design: Corner/validations/deposit_one_cent_insufficient
    """
    scn = canonical_community_scenario()
    assert scn["order"]["total_price_cents"] == 9_471_997
    # round_half_up(5% x 9,471,997) = 473,600.
    resp = api.confirm_sales_order(scn["order"]["id"], {"deposit_cents": 473_599}, consultant_headers)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT)

    order = validate_success(api.confirm_sales_order(scn["order"]["id"], {"deposit_cents": 473_600}, consultant_headers))
    assert order["deal_status"] == "PENDING_SITE_EVAL", "exactly the 5% boundary deposit must pass"


def test_placement_mismatch_both_directions(api, consultant_headers):
    """PRD §3.3: "Placement coherence is strict: `COMMUNITY_LOT` requires a
    `lot_id` naming an already-`RESERVED` lot (otherwise `ERR_PLACEMENT_MISMATCH`
    or `ERR_LOT_NOT_AVAILABLE`), `PRIVATE_LAND` forbids a `lot_id` entirely".

    Design: Corner/validations/placement_mismatch_both_directions
    """
    model = create_model()
    community = create_community()
    lot = create_lot(community["id"])
    reserve_lot(lot["id"])
    customer_a = create_customer()
    customer_b = create_customer()
    unit_a = create_unit(model["id"])
    unit_b = create_unit(model["id"])

    resp_a = api.create_sales_order(
        {
            "customer_id": customer_a["id"],
            "home_unit_id": unit_a["id"],
            "placement_type": "COMMUNITY_LOT",
            "financing_type": "CHATTEL",
            "agreed_home_price_cents": 4_200_000,
        },
        consultant_headers,
    )
    validate_error(resp_a, ApiErrorId.ERR_PLACEMENT_MISMATCH)

    resp_b = api.create_sales_order(
        {
            "customer_id": customer_b["id"],
            "home_unit_id": unit_b["id"],
            "placement_type": "PRIVATE_LAND",
            "lot_id": lot["id"],
            "financing_type": "CHATTEL",
            "agreed_home_price_cents": 4_200_000,
        },
        consultant_headers,
    )
    validate_error(resp_b, ApiErrorId.ERR_PLACEMENT_MISMATCH)


def test_order_on_unreserved_lot_rejected(api, consultant_headers):
    """PRD §2.8: "order creation requires a `RESERVED` lot; lot reservation
    requires an `AVAILABLE` lot, else `ERR_LOT_NOT_AVAILABLE` (HTTP 409)."

    Design: Corner/validations/order_on_unreserved_lot_rejected
    """
    model = create_model()
    community = create_community()
    lot = create_lot(community["id"])  # stays AVAILABLE
    customer = create_customer()
    unit = create_unit(model["id"])

    resp = api.create_sales_order(
        {
            "customer_id": customer["id"],
            "home_unit_id": unit["id"],
            "placement_type": "COMMUNITY_LOT",
            "lot_id": lot["id"],
            "financing_type": "CHATTEL",
            "agreed_home_price_cents": 4_200_000,
        },
        consultant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_AVAILABLE)


def test_second_order_on_held_unit_rejected(api, consultant_headers):
    """PRD §3.3: "The unit must be `AT_DEALER` or `RETAIL_READY` and not
    referenced by any other order whose `deal_status` is neither `CLOSED` nor
    `CANCELLED`, or creation fails with `ERR_HOME_UNIT_UNAVAILABLE`."
    PRD §3.4: "the held unit returns `RESERVED` → `AT_DEALER` with its
    `sales_order_id` cleared".

    Design: Corner/validations/second_order_on_held_unit_rejected
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    customer_b = create_customer()

    resp = api.create_sales_order(
        {
            "customer_id": customer_b["id"],
            "home_unit_id": scn["unit"]["id"],
            "placement_type": "PRIVATE_LAND",
            "financing_type": "CHATTEL",
            "agreed_home_price_cents": 4_200_000,
        },
        consultant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_HOME_UNIT_UNAVAILABLE)

    validate_success(api.cancel_sales_order(scn["order"]["id"], consultant_headers))
    order_b = validate_success(
        api.create_sales_order(
            {
                "customer_id": customer_b["id"],
                "home_unit_id": scn["unit"]["id"],
                "placement_type": "PRIVATE_LAND",
                "financing_type": "CHATTEL",
                "agreed_home_price_cents": 4_200_000,
            },
            consultant_headers,
        ),
        expected_status=201,
    )
    assert order_b["home_unit_id"] == scn["unit"]["id"], "unit released by cancellation can anchor a new order"


def test_cancel_cascade_releases_job_and_restores_crew(api, consultant_headers):
    """PRD §3.4: "An allowed cancel fires one compensating cascade in the same
    request: the held unit returns `RESERVED` → `AT_DEALER` with its
    `sales_order_id` cleared; a community-placement lot returns `RESERVED` →
    `AVAILABLE`; every transport job of the order still in `SCHEDULED` or
    `DELAYED` is cancelled, and each such cancellation restores the assigned
    crew's window capacity by recomputing `booked_dates` with the cancelled
    job's sections removed from every covered date".

    Design: Difficulty/transitive_cascade/order_cancel_depth3_cascade
    """
    scn = canonical_community_scenario()
    progress_to_financing_approved(scn)
    crew, job = book_transport(scn)

    crew_view = get_success_data(api.get_transport_crew(crew["id"], ADMIN))
    assert_booked_dates(crew_view, ["2026-08-20", "2026-08-21"])

    order = validate_success(api.cancel_sales_order(scn["order"]["id"], consultant_headers))
    assert order["deal_status"] == "CANCELLED" and order["payment_status"] == "REFUNDED"

    job_view = get_success_data(api.get_transport_job(job["id"], TEST_USERS["coordinator_headers"]))
    assert job_view["status"] == "CANCELLED", f"hop 1: job cancelled by the order cascade, got {job_view['status']}"
    crew_after = get_success_data(api.get_transport_crew(crew["id"], ADMIN))
    assert_booked_dates(crew_after, [])


def test_cancel_cascade_fanout_compensations(api, consultant_headers):
    """PRD §3.4: "An allowed cancel fires one compensating cascade in the same
    request: the held unit returns `RESERVED` → `AT_DEALER` with its
    `sales_order_id` cleared; a community-placement lot returns `RESERVED` →
    `AVAILABLE`; every transport job of the order still in `SCHEDULED` or
    `DELAYED` is cancelled, and each such cancellation restores the assigned
    crew's window capacity by recomputing `booked_dates` with the cancelled
    job's sections removed from every covered date; every evaluation in
    `SCHEDULED` or `FINDINGS_RECORDED` becomes `SUPERSEDED`; every financing
    application in `DRAFT`, `SUBMITTED`, `CONDITIONALLY_APPROVED`, or `APPROVED`
    becomes `SUPERSEDED`; and when a deposit was recorded, `payment_status` moves
    `DEPOSIT_PAID` → `REFUNDED`."

    Design: Difficulty/transitive_cascade/order_cancel_depth3_cascade
    """
    scn = canonical_community_scenario()
    progress_to_financing_approved(scn)
    book_transport(scn)
    evaluation = scn["evaluation"]
    application = scn["application"]

    validate_success(api.cancel_sales_order(scn["order"]["id"], consultant_headers))

    unit = get_success_data(api.get_home_unit(scn["unit"]["id"], ADMIN))
    assert unit["status"] == "AT_DEALER" and unit["sales_order_id"] is None
    lot = get_success_data(api.get_lot(scn["lot"]["id"], CONSULTANT))
    assert lot["status"] == "AVAILABLE"
    app_view = get_success_data(api.get_financing_application(application["id"], CONSULTANT))
    assert app_view["status"] == "SUPERSEDED", f"application superseded by the cascade, got {app_view['status']}"
    ev_view = get_success_data(api.get_site_evaluation(evaluation["id"], CONSULTANT))
    assert ev_view["status"] == "APPROVED", "terminal evaluations are untouched by the cascade"


def test_lot_length_exact_fit_allowed(api, consultant_headers):
    """PRD §3.1: "When an order targets community placement, the home must
    physically fit the pad: the model's `section_count` must be at most the
    lot's `max_sections` and the model's `length_ft` at most the lot's
    `max_length_ft`, with equality allowed on both dimensions."

    Design: Difficulty/boundary_precision_check/lot_length_exact_fit
    """
    model = create_model(length_ft=70)
    community = create_community()
    lot = create_lot(community["id"], max_sections=1, max_length_ft=70)
    reserve_lot(lot["id"])
    customer = create_customer()
    unit = create_unit(model["id"])

    order = validate_success(
        api.create_sales_order(
            {
                "customer_id": customer["id"],
                "home_unit_id": unit["id"],
                "placement_type": "COMMUNITY_LOT",
                "lot_id": lot["id"],
                "financing_type": "CHATTEL",
                "agreed_home_price_cents": 5_500_000,
            },
            consultant_headers,
        ),
        expected_status=201,
    )
    assert order["lot_id"] == lot["id"], "length exactly equal to max_length_ft must fit (<= inclusive)"


def test_lot_length_one_tenth_over_rejected(api, consultant_headers):
    """PRD §3.1: "A home that does not fit rejects the order with
    `ERR_LOT_DIMENSION_INSUFFICIENT`."

    Design: Difficulty/boundary_precision_check/lot_length_exact_fit
    """
    model = create_model(length_ft=70.1)
    community = create_community()
    lot = create_lot(community["id"], max_sections=1, max_length_ft=70)
    reserve_lot(lot["id"])
    customer = create_customer()
    unit = create_unit(model["id"])

    resp = api.create_sales_order(
        {
            "customer_id": customer["id"],
            "home_unit_id": unit["id"],
            "placement_type": "COMMUNITY_LOT",
            "lot_id": lot["id"],
            "financing_type": "CHATTEL",
            "agreed_home_price_cents": 5_500_000,
        },
        consultant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_LOT_DIMENSION_INSUFFICIENT)

    lot_after = get_success_data(api.get_lot(lot["id"], CONSULTANT))
    assert lot_after["status"] == "RESERVED", "a rejected order must not consume the lot"
