"""The seventy percent rule: a floored sell-through ratio, the attestation feeding it, and the
state error that outranks it."""

from test_helpers import (
    constants as k,
    factories as f,
    fixtures as fx,
    make_consultant_headers,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["commission_analyst_headers"]


def _inventory_order_payload(env, consultant, quantity, order_type="PERSONAL_INVENTORY"):
    return f.product_order_payload(
        consultant["id"],
        fx.lines_for(env, ("SAMPLE", quantity)),
        order_type=order_type,
        posted_period_code=k.PERIOD_2026_08["period_code"],
        ship_to_state_code="TX",
    )


def _july_sell_through_profiles(api, profiles):
    """Root consultants with a closed July whose sell-through was stamped at lock.

    `profiles` maps a label to (email, full name, inventory units, retail units). August is
    created OPEN afterwards with the clock inside it.
    """
    fx.set_clock(api, "2026-07-10T00:00:00Z")
    env = fx.setup_environment(api, periods=(k.PERIOD_2026_07,))
    july = env["periods"]["2026-07"]
    people = {}
    for label, (email, name, inventory_units, retail_units) in profiles.items():
        consultant = fx.enroll_consultant(api, env, email, name)
        fx.place_and_pay_order(
            api,
            env,
            consultant,
            [("SAMPLE", inventory_units)],
            order_type="PERSONAL_INVENTORY",
            period_code="2026-07",
            reference=f"INV-{label}",
        )
        fx.place_and_pay_order(
            api,
            env,
            consultant,
            [("SAMPLE", retail_units)],
            order_type="RETAIL_CUSTOMER",
            period_code="2026-07",
            reference=f"RET-{label}",
        )
        people[label] = consultant
    fx.close_period(api, fx.lock_period(api, july))
    fx.set_clock(api, "2026-08-05T00:00:00Z")
    august = fx.create_period(api, env["plan"]["id"], k.PERIOD_2026_08)
    return env, july, august, people


def test_sell_through_of_exactly_seventy_percent_admits_the_next_inventory_order(api):
    """14,000 credited of 20,000 purchased points floors to exactly 7,000 basis points, and the
    admission test is at-or-above, so the next personal-inventory order is accepted.

    PRD: "the order is admitted only when that row's `sell_through_bp` is at or above the plan's
    `seventy_rule_bp`".

    Design: Difficulty/boundary_precision_check/sell_through_boundary_at_seventy_rule_bp_gates_the_next_inventory_order
    """
    env, july, august, people = _july_sell_through_profiles(
        api, {"F": ("fiona@example.com", "Fiona Root", 20000, 14000)}
    )
    fiona = people["F"]

    row = fx.qualification_of(api, fiona["id"], july["id"])
    assert row["inventory_volume_points"] == 20000, "twenty thousand purchased points"
    assert row["retail_volume_points"] == 14000, "fourteen thousand retail points"
    assert row["sell_through_bp"] == 7000, (
        "14,000 of 20,000 floors to exactly the 7,000 basis point threshold"
    )

    admitted = validate_success(
        api.create_product_order(
            _inventory_order_payload(env, fiona, 10), make_consultant_headers(fiona["id"])
        ),
        201,
    )
    assert admitted["total_volume_points"] == 10, "ten SAMPLE units at one point each"
    assert admitted["total_due_cents"] == 2160, (
        "1,000 merchandise plus 165 tax plus 995 shipping"
    )
    assert admitted["posted_period_code"] == "2026-08", "the order posts to the open period"


def test_sell_through_one_point_short_refuses_inventory_but_not_retail(api):
    """13,999 credited of 20,000 purchased points floors to 6,999 rather than rounding to 7,000,
    so the personal-inventory order is refused while a retail order still succeeds.

    PRD: "Otherwise `sell_through_bp` is the credited points multiplied by 10,000, divided by the
    purchased points, and **truncated toward zero**".

    Design: Difficulty/boundary_precision_check/sell_through_boundary_at_seventy_rule_bp_gates_the_next_inventory_order
    """
    env, july, august, people = _july_sell_through_profiles(
        api, {"G": ("gabe@example.com", "Gabe Root", 20000, 13999)}
    )
    gabe = people["G"]

    row = fx.qualification_of(api, gabe["id"], july["id"])
    assert row["inventory_volume_points"] == 20000, "twenty thousand purchased points"
    assert row["retail_volume_points"] == 13999, "one credited point fewer than the boundary case"
    assert row["sell_through_bp"] == 6999, (
        "13,999 of 20,000 is 6,999.5 basis points, truncated to 6,999 rather than rounded to 7,000"
    )

    validate_error(
        api.create_product_order(
            _inventory_order_payload(env, gabe, 10), make_consultant_headers(gabe["id"])
        ),
        "ERR_INVENTORY_LOADING_VIOLATION",
        422,
    )

    retail = validate_success(
        api.create_product_order(
            _inventory_order_payload(env, gabe, 10, order_type="RETAIL_CUSTOMER"),
            make_consultant_headers(gabe["id"]),
        ),
        201,
    )
    assert retail["total_volume_points"] == 10, (
        "the seventy percent gate applies only to PERSONAL_INVENTORY, so retail selling continues"
    )


def _suspended_with_failing_sell_through(api):
    """Consultant F with a 6,900 basis point July sell-through and a SUSPENSION in force."""
    env, july, august, people = _july_sell_through_profiles(
        api, {"F": ("fiona@example.com", "Fiona Root", 100, 69)}
    )
    fiona = people["F"]
    case = fx.sanction_consultant(
        api,
        fiona,
        sanction_level="SUSPENSION",
        effective_from="2026-08-05T00:00:00Z",
        effective_until="2026-08-25T00:00:00Z",
        claim_type="PRICING_VIOLATION",
    )
    return env, july, august, fiona, case


def test_a_suspended_consultant_sees_the_state_error_not_the_inventory_loading_error(api):
    """One request violates both the consultant-status rule and the seventy percent rule, and the
    state error is the one returned.

    PRD: "On order placement, the consultant's own status is a state concern and outranks the
    anti-inventory-loading rule."

    Design: Difficulty/priority_pair_validation_conflict/suspended_consultant_state_error_precedes_inventory_loading_fiscal_error
    """
    env, july, august, fiona, case = _suspended_with_failing_sell_through(api)

    row = fx.qualification_of(api, fiona["id"], july["id"])
    assert row["inventory_volume_points"] == 100, "one hundred purchased points"
    assert row["retail_volume_points"] == 69, "sixty-nine retail points"
    assert row["sell_through_bp"] == 6900, "69 of 100 floors to 6,900 basis points"
    assert case["status"] == "SANCTIONED", "the sanction was imposed"
    assert fx.read_consultant(api, fiona["id"])["status"] == "SUSPENDED", (
        "the SUSPENSION drove the consultant to SUSPENDED"
    )

    validate_error(
        api.create_product_order(
            _inventory_order_payload(env, fiona, 50), make_consultant_headers(fiona["id"])
        ),
        "ERR_CONSULTANT_NOT_ORDER_ELIGIBLE",
        409,
    )


def test_dismissing_the_sanction_uncovers_the_inventory_loading_error_on_the_same_request(api):
    """With the sell-through untouched at 6,900 basis points, dismissing the sanction turns the
    identical request's state error into the fiscal error, and neither attempt writes an order.

    PRD: "A `SUSPENDED` consultant who is also in breach of the seventy percent rule is rejected
    with `ERR_CONSULTANT_NOT_ORDER_ELIGIBLE`, never with `ERR_INVENTORY_LOADING_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_consultant_state_error_precedes_inventory_loading_fiscal_error
    """
    env, july, august, fiona, case = _suspended_with_failing_sell_through(api)

    validate_error(
        api.create_product_order(
            _inventory_order_payload(env, fiona, 50), make_consultant_headers(fiona["id"])
        ),
        "ERR_CONSULTANT_NOT_ORDER_ELIGIBLE",
        409,
    )

    fx.appeal_case(api, fiona, case, "the price list quoted was the current one")
    fx.review_case(api, case)
    dismissed = fx.dismiss_case(api, case, decision_reason="appeal upheld")
    assert dismissed["status"] == "DISMISSED", "the appeal was upheld"
    assert fx.read_consultant(api, fiona["id"])["status"] == "ACTIVE", (
        "dismissing a case that imposed SUSPENSION returns the consultant to ACTIVE"
    )

    validate_error(
        api.create_product_order(
            _inventory_order_payload(env, fiona, 50), make_consultant_headers(fiona["id"])
        ),
        "ERR_INVENTORY_LOADING_VIOLATION",
        422,
    )

    assert fx.qualification_of(api, fiona["id"], july["id"])["sell_through_bp"] == 6900, (
        "the sell-through ratio was never touched by either attempt"
    )
    rows, meta = validate_paginated(
        api.list_product_orders(
            ADMIN, params={"consultant_id": fiona["id"], "posted_period_code": "2026-08"}
        )
    )
    assert rows == [], "neither refused attempt created an order row"
    assert meta["total_count"] == 0, "the period holds no order for this consultant"


def test_personal_use_attestation_is_capped_by_inventory_and_closes_with_the_period(api):
    """The attestation is bounded above by the inventory actually purchased, inclusive at the
    bound, is refused once the period is locked, and feeds the sell-through ratio.

    PRD: "the attested figure may not exceed the row's `inventory_volume_points`, because a
    consultant cannot attest to consuming more than they purchased".

    Design: Corner/validations/personal_use_attestation_is_capped_by_inventory_volume_and_closes_with_the_period
    """
    env = fx.setup_environment(api)
    alice = fx.enroll_root(api, env)
    period = env["periods"]["2026-08"]
    order = fx.place_and_pay_order(
        api, env, alice, [("SAMPLE", 100)], order_type="PERSONAL_INVENTORY"
    )
    assert order["total_due_cents"] == 12645, "one hundred SAMPLE in TX cost 12,645 cents"

    row = fx.qualification_of(api, alice["id"], period["id"])
    assert row["inventory_volume_points"] == 100, "one hundred purchased points"
    assert row["retail_volume_points"] == 0, "nothing was sold at retail"

    headers = make_consultant_headers(alice["id"])
    validate_error(
        api.attest_personal_use(row["id"], f.personal_use_attestation_payload(101), headers),
        "ERR_ATTESTATION_EXCEEDS_INVENTORY",
        422,
    )
    attested = validate_success(
        api.attest_personal_use(row["id"], f.personal_use_attestation_payload(100), headers)
    )
    assert attested["attested_personal_use_points"] == 100, (
        "the bound is inclusive, so attesting the entire inventory is legal"
    )

    fx.lock_period(api, period)
    validate_error(
        api.attest_personal_use(row["id"], f.personal_use_attestation_payload(50), headers),
        "ERR_PERIOD_NOT_ACCEPTING_VOLUME",
        409,
    )

    final = validate_success(api.get_period_qualification(row["id"], ANALYST))
    assert final["attested_personal_use_points"] == 100, "the locked figure stands"
    assert final["sell_through_bp"] == 10000, (
        "credited points are the smaller of purchased and retail plus attested, so 100 of 100"
    )
