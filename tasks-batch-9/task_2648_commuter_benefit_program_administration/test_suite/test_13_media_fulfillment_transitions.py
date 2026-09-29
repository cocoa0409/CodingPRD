"""Media fulfillment: the MediaOrder transition guards, the election
fulfillment roll-up ladder, and the batch reconciliation bubble-up.

Every test builds its own employer, catalogue product, election and batch
through the documented endpoints, because the service is restarted against an
empty database before each test runs.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import PROGRAM_ADMIN, constants, fixtures
from test_helpers import make_order_desk_headers
from test_helpers.api_errors import ERR_INVALID_STATE_TRANSITION


def test_01_shipping_a_still_pending_media_line_is_refused_and_records_no_tracking(api):
    """PRD §2.7: "Transition existence: the target row's current state must have a declared outgoing transition for the requested action, otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
    PRD §3.6: "It requires the media line's `status` to be `SUBMITTED`, the catalogue product's `requires_physical_fulfillment` to be true — a digitally provisioned product is never shipped — and the owning batch's `status` to be `RELEASED` or `RECONCILED`."

    Design: Corner/state_machines/media_order_ship_from_pending_returns_invalid_state_transition
    """
    chain = fixtures.make_procurement_chain(
        api,
        region_code=constants.REGION_AUS,
        media_quantity=1,
        pretax_amount_cents=6000,
        unit_price_cents=6000,
        seal_user_id="desk-ops",
        stop_after="ordered",
        coverage_start_at="2026-08-01T00:00:00Z",
        coverage_end_at="2026-08-15T00:00:00Z",
    )
    order = chain["order"]
    assert order["status"] == "PENDING", order["status"]
    assert order["version"] == 1, order["version"]
    assert chain["batch"]["status"] == "OPEN", chain["batch"]["status"]

    refused = api.ship_media_order(
        order["id"], {"tracking_ref": "TRK-EARLY-1"}, make_order_desk_headers("desk-ops")
    )
    assert refused.status_code == 409, (
        f"a ship against a PENDING line must be a 409 conflict, got {refused.status_code}"
    )
    validate_error(refused, ERR_INVALID_STATE_TRANSITION)

    after = fixtures.read_media_order(api, order["id"])
    assert after["status"] == "PENDING", (
        f"the line must stay PENDING, it is {after['status']}"
    )
    assert after["tracking_ref"] is None, (
        f"a refused ship must not store a tracking reference, got {after['tracking_ref']!r}"
    )
    assert after["version"] == 1, (
        f"the refused ship must perform no write, version is {after['version']}"
    )

    election = fixtures.read_election(api, chain["election"]["id"])
    assert election["fulfillment_status"] == "ORDERED", election["fulfillment_status"]
    assert election["funding_status"] == "PENDING", election["funding_status"]


def test_02_confirming_the_last_line_bubbles_the_released_batch_to_reconciled(api):
    """PRD §3.6: "The line moves `SHIPPED → DELIVERED`, the parent election's `fulfillment_status` is re-derived, the owning batch's `RELEASED → RECONCILED` bubble-up is re-evaluated, and the `version` of the line, its election and — where the bubble-up fires — its batch advances by 1."
    PRD §3.5: "The batch's own final posture, `RECONCILED`, is a bubble-up rather than a request: whenever a media line in a `RELEASED` batch changes status, the batch is re-evaluated, and once every media order in the batch sits in `DELIVERED` or `CANCELLED` — with `line_count` at least 1 — the batch moves `RELEASED → RECONCILED` and its `version` advances by 1."

    Design: Corner/state_machines/last_delivered_order_bubbles_batch_released_to_reconciled
    """
    chain = fixtures.make_procurement_chain(
        api,
        region_code=constants.REGION_AUS,
        media_quantity=1,
        pretax_amount_cents=6000,
        unit_price_cents=6000,
        seal_user_id="desk-a",
        release_user_id="desk-b",
        stop_after="released",
        coverage_start_at="2026-08-01T00:00:00Z",
        coverage_end_at="2026-08-15T00:00:00Z",
    )
    order_id = chain["order"]["id"]
    desk_a = make_order_desk_headers("desk-a")
    assert chain["batch"]["status"] == "RELEASED", chain["batch"]["status"]
    assert chain["order"]["status"] == "SUBMITTED", chain["order"]["status"]

    shipped = validate_success(
        api.ship_media_order(order_id, {"tracking_ref": "TRK-BUB-1"}, desk_a)
    )
    assert shipped["status"] == "SHIPPED", shipped["status"]
    in_transit = fixtures.read_election(api, chain["election"]["id"])
    assert in_transit["fulfillment_status"] == "IN_TRANSIT", (
        in_transit["fulfillment_status"]
    )

    batch_before = fixtures.read_batch(api, chain["batch"]["id"], desk_a)
    assert batch_before["status"] == "RELEASED", batch_before["status"]
    election_before = in_transit

    delivered = validate_success(api.confirm_media_order_delivery(order_id, desk_a))

    assert delivered["status"] == "DELIVERED", delivered["status"]
    assert delivered["tracking_ref"] == "TRK-BUB-1", (
        "delivery confirmation must leave the carrier reference in place"
    )
    assert delivered["version"] == shipped["version"] + 1, (
        f"the line version must advance by 1: {shipped['version']} -> "
        f"{delivered['version']}"
    )

    election_after = fixtures.read_election(api, chain["election"]["id"])
    assert election_after["fulfillment_status"] == "DELIVERED", (
        f"the election fulfillment axis must reach DELIVERED, it is "
        f"{election_after['fulfillment_status']}"
    )
    assert election_after["funding_status"] == "PENDING", (
        "the money axis is untouched by a delivery confirmation"
    )
    assert election_after["version"] == election_before["version"] + 1, (
        f"the election version must advance by 1: {election_before['version']} -> "
        f"{election_after['version']}"
    )

    batch_after = fixtures.read_batch(api, chain["batch"]["id"], desk_a)
    assert batch_after["status"] == "RECONCILED", (
        "the batch must bubble up to RECONCILED with no batch-level request, it is "
        f"{batch_after['status']}"
    )
    assert batch_after["line_count"] == 1, batch_after["line_count"]
    assert batch_after["version"] == batch_before["version"] + 1, (
        f"the batch version must advance by 1: {batch_before['version']} -> "
        f"{batch_after['version']}"
    )


def test_03_shipping_a_digitally_provisioned_product_is_refused(api):
    """PRD §3.6: "It requires the media line's `status` to be `SUBMITTED`, the catalogue product's `requires_physical_fulfillment` to be true — a digitally provisioned product is never shipped — and the owning batch's `status` to be `RELEASED` or `RECONCILED`."
    PRD §2.7: "Transition existence: the target row's current state must have a declared outgoing transition for the requested action, otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/ship_blocked_when_transit_media_is_not_physically_fulfilled
    """
    chain = fixtures.make_procurement_chain(
        api,
        region_code=constants.REGION_SEA,
        media_quantity=1,
        pretax_amount_cents=4000,
        unit_price_cents=4000,
        seal_user_id="desk-a",
        release_user_id="desk-b",
        stop_after="released",
        employer_overrides={"parking_group_limit_cents": 31500},
        category_overrides={
            "category_type": "PARKING",
            "monthly_exclusion_limit_cents": 31500,
        },
        media_overrides={
            "media_type": "DEBIT_CARD",
            "requires_physical_fulfillment": False,
        },
    )
    assert chain["media"]["requires_physical_fulfillment"] is False, (
        "the catalogue product must be the digitally provisioned one"
    )
    assert chain["batch"]["status"] == "RELEASED", chain["batch"]["status"]
    order_before = fixtures.read_media_order(api, chain["order"]["id"])
    assert order_before["status"] == "SUBMITTED", order_before["status"]

    refused = api.ship_media_order(
        chain["order"]["id"],
        {"tracking_ref": "TRK-GS-1"},
        make_order_desk_headers("desk-a"),
    )
    assert refused.status_code == 409, (
        f"the guard must answer with a 409 conflict, got {refused.status_code}"
    )
    validate_error(refused, ERR_INVALID_STATE_TRANSITION)

    order_after = fixtures.read_media_order(api, chain["order"]["id"])
    assert order_after["status"] == "SUBMITTED", (
        f"the line must not be left half-transitioned, it is {order_after['status']}"
    )
    assert order_after["tracking_ref"] is None, (
        f"a refused ship must store no tracking reference, got {order_after['tracking_ref']!r}"
    )
    assert order_after["version"] == order_before["version"], (
        f"the refused ship must perform no write, version moved to {order_after['version']}"
    )

    election = fixtures.read_election(api, chain["election"]["id"])
    assert election["fulfillment_status"] == "ORDERED", (
        f"the election must stay in ORDERED, it is {election['fulfillment_status']}"
    )


def test_04_a_single_delivered_unit_against_three_entitled_units_stays_ordered(api):
    """PRD §3.6: "Otherwise, if every candidate order has `status` `DELIVERED` **and** the sum of their `quantity` values is at least the election's `entitled_media_units`, the result is `DELIVERED`."
    PRD §3.6: "This precedence is what makes the outcome deterministic; a partially-delivered election whose remaining lines are still `SUBMITTED` sits in `ORDERED`, not in `DELIVERED`."

    Design: Corner/state_machines/fulfillment_stays_ordered_when_delivered_quantity_is_short_of_entitlement
    """
    base = fixtures.make_program_with_participant(
        api,
        region_code=constants.REGION_AUS,
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
    )
    media = fixtures.make_transit_media(
        api,
        region_code=constants.REGION_AUS,
        eligible_category_type="TRANSIT_PASS",
        unit_price_cents=6000,
    )
    election = fixtures.make_election(
        api,
        base["employee"]["id"],
        base["window"]["id"],
        base["category"]["id"],
        base["account"]["id"],
        PROGRAM_ADMIN,
        pretax_amount_cents=18000,
        posttax_amount_cents=0,
        transit_media_id=media["id"],
        media_quantity=3,
    )
    assert election["entitled_media_units"] == 3, election["entitled_media_units"]
    assert election["fulfillment_status"] == "AWAITING_ORDER", (
        election["fulfillment_status"]
    )

    desk_a = make_order_desk_headers("desk-a")
    batch = fixtures.make_open_batch(
        api, base["window"]["id"], constants.REGION_AUS, "desk-a"
    )
    order = fixtures.make_media_order(
        api,
        election["id"],
        media["id"],
        batch["id"],
        "desk-a",
        quantity=1,
        coverage_start_at="2026-08-01T00:00:00Z",
        coverage_end_at="2026-08-31T00:00:00Z",
    )
    assert order["quantity"] == 1, (
        "the single line covers only one of the three entitled units"
    )
    validate_success(api.seal_order_batch(batch["id"], desk_a))
    validate_success(
        api.release_order_batch(batch["id"], make_order_desk_headers("desk-b"))
    )
    shipped = validate_success(
        api.ship_media_order(order["id"], {"tracking_ref": "TRK-CR-1"}, desk_a)
    )
    assert shipped["status"] == "SHIPPED", shipped["status"]
    mid = fixtures.read_election(api, election["id"])
    assert mid["fulfillment_status"] == "IN_TRANSIT", mid["fulfillment_status"]

    delivered = validate_success(api.confirm_media_order_delivery(order["id"], desk_a))

    assert delivered["status"] == "DELIVERED", delivered["status"]
    after = fixtures.read_election(api, election["id"])
    assert after["fulfillment_status"] == "ORDERED", (
        "one delivered unit does not cover three entitled units, so the roll-up must "
        f"fall through to ORDERED, got {after['fulfillment_status']}"
    )
    assert after["entitled_media_units"] == 3, after["entitled_media_units"]
    assert after["funding_status"] == "PENDING", after["funding_status"]

    batch_after = fixtures.read_batch(api, batch["id"], desk_a)
    assert batch_after["status"] == "RECONCILED", (
        "every line of the batch is DELIVERED, so the batch itself reconciles even "
        f"though the election does not, got {batch_after['status']}"
    )
    assert batch_after["line_count"] == 1, batch_after["line_count"]


def test_05_cancelling_an_election_cancels_the_pending_line_and_spares_the_shipped_one(api):
    """PRD §3.3: "Both source postures produce the identical effect set: `funding_status` becomes `CANCELLED`, `excluded_amount_cents`, `posttax_spill_cents`, `posttax_effective_cents` and `total_amount_cents` are zeroed, every media order of the election whose `status` is `PENDING` or `SUBMITTED` is moved to `CANCELLED`, `fulfillment_status` is set to `CANCELLED`, the window's `election_count` and the category's `active_election_count` are recomputed, and `Election.version` advances by 1 alongside the `version` of every media order the cascade cancelled."
    PRD §3.6: "If the election's `funding_status` is `CANCELLED`, the result is `CANCELLED`."

    Design: Corner/state_machines/election_cancel_cancels_only_pending_media_order_not_shipped_one
    """
    base = fixtures.make_program_with_participant(
        api,
        region_code=constants.REGION_AUS,
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
    )
    media = fixtures.make_transit_media(
        api,
        region_code=constants.REGION_AUS,
        eligible_category_type="TRANSIT_PASS",
        unit_price_cents=6000,
    )
    election = fixtures.make_election(
        api,
        base["employee"]["id"],
        base["window"]["id"],
        base["category"]["id"],
        base["account"]["id"],
        PROGRAM_ADMIN,
        pretax_amount_cents=12000,
        posttax_amount_cents=0,
        transit_media_id=media["id"],
        media_quantity=2,
    )
    desk_a = make_order_desk_headers("desk-a")

    batch_one = fixtures.make_open_batch(
        api, base["window"]["id"], constants.REGION_AUS, "desk-a"
    )
    order_one = fixtures.make_media_order(
        api,
        election["id"],
        media["id"],
        batch_one["id"],
        "desk-a",
        quantity=1,
        coverage_start_at="2026-08-01T00:00:00Z",
        coverage_end_at="2026-08-15T00:00:00Z",
    )
    validate_success(api.seal_order_batch(batch_one["id"], desk_a))
    validate_success(
        api.release_order_batch(batch_one["id"], make_order_desk_headers("desk-b"))
    )
    shipped = validate_success(
        api.ship_media_order(order_one["id"], {"tracking_ref": "TRK-CC-1"}, desk_a)
    )
    assert shipped["status"] == "SHIPPED", shipped["status"]

    batch_two = fixtures.make_open_batch(
        api, base["window"]["id"], constants.REGION_AUS, "desk-a"
    )
    order_two = fixtures.make_media_order(
        api,
        election["id"],
        media["id"],
        batch_two["id"],
        "desk-a",
        quantity=1,
        coverage_start_at="2026-08-16T00:00:00Z",
        coverage_end_at="2026-08-31T00:00:00Z",
    )
    assert order_two["status"] == "PENDING", order_two["status"]
    assert order_two["superseded_media_order_id"] is None, (
        "a SHIPPED line is not superseded by a later line"
    )

    election_before = fixtures.read_election(api, election["id"])
    assert election_before["fulfillment_status"] == "IN_TRANSIT", (
        election_before["fulfillment_status"]
    )
    assert election_before["funding_status"] == "PENDING", (
        election_before["funding_status"]
    )
    assert election_before["total_amount_cents"] == 12000, (
        election_before["total_amount_cents"]
    )
    account_before = fixtures.read_account(api, base["account"]["id"])

    cancelled = validate_success(api.cancel_election(election["id"], PROGRAM_ADMIN))

    assert cancelled["funding_status"] == "CANCELLED", cancelled["funding_status"]
    assert cancelled["fulfillment_status"] == "CANCELLED", (
        cancelled["fulfillment_status"]
    )
    assert cancelled["total_amount_cents"] == 0, cancelled["total_amount_cents"]
    assert cancelled["excluded_amount_cents"] == 0, cancelled["excluded_amount_cents"]
    assert cancelled["posttax_spill_cents"] == 0, cancelled["posttax_spill_cents"]
    assert cancelled["posttax_effective_cents"] == 0, (
        cancelled["posttax_effective_cents"]
    )
    assert cancelled["version"] == election_before["version"] + 1, (
        f"the election version must advance by 1: {election_before['version']} -> "
        f"{cancelled['version']}"
    )

    shipped_after = fixtures.read_media_order(api, order_one["id"], desk_a)
    assert shipped_after["status"] == "SHIPPED", (
        f"media already in the mail cannot be un-mailed, got {shipped_after['status']}"
    )
    assert shipped_after["tracking_ref"] == "TRK-CC-1", (
        "the shipped line keeps its carrier reference"
    )
    assert shipped_after["version"] == shipped["version"], (
        f"the shipped line must not be written: {shipped['version']} -> "
        f"{shipped_after['version']}"
    )

    pending_after = fixtures.read_media_order(api, order_two["id"], desk_a)
    assert pending_after["status"] == "CANCELLED", (
        f"the PENDING line must be cancelled by the cascade, got {pending_after['status']}"
    )
    assert pending_after["version"] == order_two["version"] + 1, (
        f"the cancelled line version must advance by 1: {order_two['version']} -> "
        f"{pending_after['version']}"
    )

    window_after = fixtures.read_window(api, base["window"]["id"])
    assert window_after["election_count"] == 0, (
        "the window counter must be recomputed to exclude the cancelled election, got "
        f"{window_after['election_count']}"
    )
    category_after = validate_success(
        api.get_benefit_category(base["category"]["id"], PROGRAM_ADMIN)
    )
    assert category_after["active_election_count"] == 0, (
        "the category counter must be recomputed to exclude the cancelled election, got "
        f"{category_after['active_election_count']}"
    )

    account_after = fixtures.read_account(api, base["account"]["id"])
    assert account_after["version"] == account_before["version"], (
        "cancelling a PENDING election moves no money"
    )
    assert account_after["available_balance_cents"] == (
        account_before["available_balance_cents"]
    ), account_after["available_balance_cents"]

    batch_one_after = fixtures.read_batch(api, batch_one["id"], desk_a)
    assert batch_one_after["status"] == "RELEASED", (
        "the released batch still holds a SHIPPED line, so it cannot reconcile, got "
        f"{batch_one_after['status']}"
    )
    batch_two_after = fixtures.read_batch(api, batch_two["id"], desk_a)
    assert batch_two_after["status"] == "OPEN", (
        f"the never-sealed batch stays OPEN, got {batch_two_after['status']}"
    )
