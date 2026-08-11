"""Package acceptance: billable weight, the handling fee, oversize and the notification clock."""

import pytest

from test_helpers import (
    CMRA_OPERATOR,
    ApiErrorId,
    assert_mail_item,
    assert_same_instant,
    create_carrier_rule,
    log_and_match_package,
    read_mail_item,
    set_clock,
    setup_accepted_package,
    setup_releasable_box,
    validate_error,
    validate_success,
)


# ==========================================================================
# Billable weight: the two branches of the max()
# ==========================================================================
def _setup_two_parcels():
    ctx = setup_releasable_box(
        "A-101",
        "Ann Holder",
        holder_email="ann@example.com",
        box_overrides={"security_deposit_cents": 5000, "prepaid_balance_cents": 12000},
        recipient_overrides={"signature_authorization_on_file": True},
    )
    rule = create_carrier_rule(
        carrier_code="UPS",
        dim_divisor=139,
        max_length_plus_girth_in=130.0,
        max_actual_weight_lb=70.0,
        accepts_signature_required=True,
        acceptance_fee_cents=300,
        base_rate_cents_per_lb=40,
    )
    bulky = log_and_match_package(
        ctx, rule["id"], actual_weight_lb=2.0, length_in=20.0, width_in=16.0, height_in=12.0
    )
    compact = log_and_match_package(
        ctx, rule["id"], actual_weight_lb=30.0, length_in=10.0, width_in=8.0, height_in=6.0
    )
    ctx["carrier_rule"] = rule
    ctx["bulky_id"] = bulky["id"]
    ctx["compact_id"] = compact["id"]
    return ctx


def test_a_light_bulky_parcel_prices_on_its_dimensional_weight(api):
    """PRD §3.5: "Dimensional weight is the product of `length_in`, `width_in` and
    `height_in` divided by the carrier rule's `dim_divisor` and then **rounded up to the
    next whole pound**."
    PRD §3.5: "When the scale weight is greater than or equal to the dimensional weight,
    `billable_weight_lb` is simply the scale weight and the cubic dimensions never enter
    the price; when the dimensional weight is strictly greater, `billable_weight_lb` is
    the dimensional weight and a light bulky parcel prices above what it weighs."
    PRD §3.5: "For every other class it is the carrier rule's `acceptance_fee_cents`
    plus the product of `billable_weight_lb` and the rule's `base_rate_cents_per_lb`,
    with that whole sum rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/package_dimensional_vs_actual_weight_diverge
    """
    ctx = _setup_two_parcels()

    accepted = validate_success(api.accept_package(ctx["bulky_id"], CMRA_OPERATOR))
    assert_mail_item(accepted)
    assert accepted["billable_weight_lb"] == pytest.approx(28, abs=0.01)
    assert accepted["package_acceptance_fee_cents"] == 1420
    assert accepted["billable_weight_lb"] != accepted["actual_weight_lb"]


def test_a_heavy_compact_parcel_prices_on_its_scale_weight(api):
    """PRD §3.5: "`billable_weight_lb` is then the greater of `actual_weight_lb` and
    that dimensional weight, carried to one decimal place."
    PRD §3.5: "For every other class it is the carrier rule's `acceptance_fee_cents`
    plus the product of `billable_weight_lb` and the rule's `base_rate_cents_per_lb`,
    with that whole sum rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/package_dimensional_vs_actual_weight_diverge
    """
    ctx = _setup_two_parcels()

    accepted = validate_success(api.accept_package(ctx["compact_id"], CMRA_OPERATOR))
    assert accepted["billable_weight_lb"] == pytest.approx(30.0, abs=0.01)
    assert accepted["package_acceptance_fee_cents"] == 1500
    assert accepted["billable_weight_lb"] == pytest.approx(
        accepted["actual_weight_lb"], abs=0.01
    )


# ==========================================================================
# The oversize threshold
# ==========================================================================
def test_length_plus_girth_exactly_on_the_threshold_is_accepted_and_one_tenth_above_is_not(api):
    """PRD §3.5: "The piece is oversize when length-plus-girth is **strictly greater
    than** the rule's `max_length_plus_girth_in`, or when `actual_weight_lb` is
    **strictly greater than** the rule's `max_actual_weight_lb`."
    PRD §3.5: "Both comparisons are strict, so a piece sitting exactly on either
    threshold is accepted and a piece one tenth above it is `ERR_PACKAGE_OVERSIZE`."
    PRD §3.5: "Finally the oversize check: girth is twice the sum of `width_in` and
    `height_in`, and length-plus-girth is `length_in` added to that girth."

    The first parcel lands exactly ON the inclusive-accept edge (130.0 in), the second
    one tenth of an inch above it (130.2 in).

    Design: Corner/calculations/oversize_refusal_threshold_is_strictly_greater
    """
    ctx = setup_releasable_box("Z-2001", "Sue Size", holder_email="sue@example.com")
    rule = create_carrier_rule(
        carrier_code="UPS",
        dim_divisor=139,
        max_length_plus_girth_in=130.0,
        max_actual_weight_lb=70.0,
        acceptance_fee_cents=300,
        base_rate_cents_per_lb=40,
    )
    on_edge = log_and_match_package(
        ctx, rule["id"], actual_weight_lb=10.0, length_in=50.0, width_in=20.0, height_in=20.0
    )
    over_edge = log_and_match_package(
        ctx, rule["id"], actual_weight_lb=10.0, length_in=50.2, width_in=20.0, height_in=20.0
    )

    accepted = validate_success(api.accept_package(on_edge["id"], CMRA_OPERATOR))
    assert accepted["billable_weight_lb"] == pytest.approx(144, abs=0.01)
    assert accepted["package_acceptance_fee_cents"] == 6060

    refused = api.accept_package(over_edge["id"], CMRA_OPERATOR)
    validate_error(refused, ApiErrorId.ERR_PACKAGE_OVERSIZE.value)

    untouched = read_mail_item(over_edge["id"])
    assert untouched["accepted_at"] is None
    assert untouched["notification_status"] == "NOT_REQUIRED"


def test_a_signature_parcel_from_a_non_signing_carrier_cannot_be_taken(api):
    """PRD §3.5: "A piece whose `signature_required` is true arriving from a carrier
    whose rule has `accepts_signature_required` false cannot be taken at all, and is
    `ERR_CARRIER_NOT_ACCEPTED`."
    PRD §3.5: "A piece whose `signature_required` is true requires its matched member's
    `signature_authorization_on_file` to be true, failing which the request is
    `ERR_SIGNATURE_AUTHORIZATION_MISSING`."

    Design: Corner/calculations/signature_required_parcel_from_a_non_signing_carrier_is_refused
    """
    ctx = setup_releasable_box(
        "Z-2009",
        "Ann Sign",
        holder_email="annsign@example.com",
        recipient_overrides={"signature_authorization_on_file": True},
    )
    rule = create_carrier_rule(
        carrier_code="DHL",
        dim_divisor=139,
        max_length_plus_girth_in=130.0,
        max_actual_weight_lb=70.0,
        accepts_signature_required=False,
        acceptance_fee_cents=300,
        base_rate_cents_per_lb=40,
    )
    parcel = log_and_match_package(
        ctx,
        rule["id"],
        signature_required=True,
        actual_weight_lb=5.0,
        length_in=10.0,
        width_in=8.0,
        height_in=6.0,
    )

    response = api.accept_package(parcel["id"], CMRA_OPERATOR)
    validate_error(response, ApiErrorId.ERR_CARRIER_NOT_ACCEPTED.value)

    assert read_mail_item(parcel["id"])["accepted_at"] is None
    member = validate_success(api.get_recipient(ctx["recipient_id"], CMRA_OPERATOR))
    assert member["signature_authorization_on_file"] is True


# ==========================================================================
# The notification clock
# ==========================================================================
def test_notification_breaches_only_strictly_after_the_due_instant(api):
    """PRD §3.5: "Whenever the logical clock advances past that deadline — strictly
    greater than `notification_due_at`, while `notified_at` is still null —
    `notification_status` moves `PENDING → BREACHED`."
    PRD §3.5: "Acceptance also starts the notification obligation.
    `notification_status` moves from `NOT_REQUIRED` to `PENDING` and
    `notification_due_at` is computed from `accepted_at`: for a service-of-process piece
    on a mailbox carrying an add-on with `active` true, the deadline is `accepted_at`
    plus **4 hours**, the same-business-day statutory clock; for every other case — an
    ordinary package, or a service-of-process piece with no active add-on — the deadline
    is `accepted_at` plus **24 hours**."

    The clock lands exactly ON the due instant first (still PENDING, the comparison is
    strict) and one second beyond it second.

    Design: Corner/calculations/notification_breaches_when_the_clock_passes_the_due_instant
    """
    ctx = setup_accepted_package(
        "Z-2003",
        "Uri Late",
        carrier_overrides={"carrier_code": "UPS"},
        package_overrides={
            "actual_weight_lb": 5.0,
            "length_in": 10.0,
            "width_in": 8.0,
            "height_in": 6.0,
        },
    )
    assert_same_instant(
        ctx["item"]["notification_due_at"], "2026-05-02T00:00:00.000Z", "notification_due_at"
    )

    set_clock("2026-05-02T00:00:00Z")
    assert read_mail_item(ctx["item_id"])["notification_status"] == "PENDING"

    set_clock("2026-05-02T00:00:01Z")
    breached = read_mail_item(ctx["item_id"])
    assert breached["notification_status"] == "BREACHED"
    assert breached["notified_at"] is None


def test_a_breached_piece_cannot_be_retro_notified(api):
    """PRD §3.5: "A piece that has already breached cannot be retro-notified:
    attempting to move `BREACHED → SENT` is refused with `ERR_INVALID_STATE`."
    PRD §3.5: "It moves `notification_status` `PENDING → SENT` and stamps `notified_at`
    from the clock, bumping `MailItem.version` by one."

    Design: Corner/calculations/notifying_a_breached_piece_is_rejected
    """
    ctx = setup_accepted_package(
        "Z-2004",
        "Vic Miss",
        carrier_overrides={"carrier_code": "UPS"},
        package_overrides={
            "actual_weight_lb": 5.0,
            "length_in": 10.0,
            "width_in": 8.0,
            "height_in": 6.0,
        },
    )
    set_clock("2026-05-03T00:00:00Z")

    response = api.notify_mail_item(ctx["item_id"], CMRA_OPERATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    item = read_mail_item(ctx["item_id"])
    assert item["notification_status"] == "BREACHED"
    assert item["notified_at"] is None
