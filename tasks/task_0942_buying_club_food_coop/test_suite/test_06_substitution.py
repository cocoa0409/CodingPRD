"""Supplier substitutes: tolerance, automatic resolution and the offer state
machine."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_instant_equals_offset,
    assert_substitution_offer,
    canonical_world,
    find_offer_for_line,
    make_member_headers,
    substitution_world,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["club_admin_headers"]


def test_substitute_price_at_exactly_the_tolerance_ceiling_auto_approves(api):
    """PRD §3.6: "It also records `within_tolerance`, which is true when
    `offered_unit_price_cents` is at most `original_unit_price_cents` multiplied by
    1.10 and rounded half up to the whole cent, and a `respond_by` instant set to
    the offer's `created_at` plus 24 hours."
    PRD §3.6: "If the preference is `ANY_SUBSTITUTE`, or it is `APPROVAL_REQUIRED`
    and `within_tolerance` is true, the offer resolves `PENDING → AUTO_APPROVED`
    inside the very request that created it, and the line moves
    `CONFIRMED → SUBSTITUTED` at the offered price."
    PRD §3.6: "An offer records the `order_line_id` it applies to, the
    `receipt_line_id` that introduced the substitute, the `substitute_item_id`, the
    `offered_units` of the substitute allocated to that line, the line's
    `original_unit_price_cents` as bound before substitution, and an
    `offered_unit_price_cents` derived from `substitute_case_price_cents` by exactly
    the same base-then-split-fee rule that priced the original line."

    Design: Difficulty/boundary_precision_check/substitute_price_at_exactly_the_tolerance_ceiling_auto_approves
    """
    w = substitution_world(api, substitute_case_price_cents=11000)

    offer_mara = find_offer_for_line(api, w, w.lines["mara_cheese"])
    assert_substitution_offer(offer_mara)
    assert offer_mara["original_unit_price_cents"] == 3734
    assert offer_mara["offered_unit_price_cents"] == 4107
    assert offer_mara["within_tolerance"] is True
    assert offer_mara["status"] == "AUTO_APPROVED"
    assert offer_mara["offered_units"] == 4
    assert_instant_equals_offset(
        offer_mara["respond_by"], offer_mara["created_at"], hours=24, label="respond_by"
    )

    offer_ben = find_offer_for_line(api, w, w.lines["ben_cheese"])
    assert offer_ben["original_unit_price_cents"] == 3334
    assert offer_ben["offered_unit_price_cents"] == 3667
    assert offer_ben["within_tolerance"] is True
    assert offer_ben["status"] == "AUTO_APPROVED"

    mara_line = validate_success(api.get_order_line(w.lines["mara_cheese"], ADMIN))
    assert mara_line["status"] == "SUBSTITUTED"
    assert mara_line["unit_price_cents"] == 4107

    ben_line = validate_success(api.get_order_line(w.lines["ben_cheese"], ADMIN))
    assert ben_line["unit_price_cents"] == 3667


def test_one_cent_above_the_tolerance_ceiling_leaves_the_offer_pending(api):
    """PRD §2.7: "**Substitution tolerance.** A substitute is within tolerance
    when its `offered_unit_price_cents` is less than or equal to the
    `original_unit_price_cents` multiplied by 1.10 and rounded half up to the whole
    cent. Inclusive."
    PRD §3.6: "Only an `APPROVAL_REQUIRED` line facing an out-of-tolerance price
    leaves an offer sitting in `PENDING` for the member to answer."

    Design: Difficulty/boundary_precision_check/substitute_price_at_exactly_the_tolerance_ceiling_auto_approves
    """
    w = substitution_world(api, substitute_case_price_cents=11010)

    offer_mara = find_offer_for_line(api, w, w.lines["mara_cheese"])
    assert offer_mara["original_unit_price_cents"] == 3734
    assert offer_mara["offered_unit_price_cents"] == 4110
    assert offer_mara["within_tolerance"] is False
    assert offer_mara["status"] == "PENDING"

    line = validate_success(api.get_order_line(w.lines["mara_cheese"], ADMIN))
    assert line["status"] == "CONFIRMED"
    assert line["unit_price_cents"] == 3734


def test_approving_an_auto_approved_offer_returns_invalid_offer_state(api):
    """PRD §3.6: "an offer that is not `PENDING` is refused with
    `ERR_INVALID_OFFER_STATE`."
    PRD §2.9: "**Rung 20** — the substitution offer has status `PENDING`. Applies
    to approving and declining an offer. Failure: `ERR_INVALID_OFFER_STATE`, HTTP
    409."

    Design: Corner/state_machines/approving_an_auto_approved_offer_returns_invalid_offer_state
    """
    w = substitution_world(api, substitute_case_price_cents=11000)
    offer = find_offer_for_line(api, w, w.lines["mara_cheese"])

    body = validate_error(
        api.approve_substitution_offer(offer["id"], make_member_headers(w.mara_id)),
        ApiErrorId.ERR_INVALID_OFFER_STATE.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_EXCEPTION_WINDOW_CLOSED.value

    assert (
        validate_success(api.get_substitution_offer(offer["id"], ADMIN))["status"]
        == "AUTO_APPROVED"
    )
    assert validate_success(api.get_cycle(w.cycle_id, ADMIN))["exception_state"] == "OPEN"


def test_an_unknown_substitution_offer_id_returns_offer_not_found(api):
    """PRD §2.8: "`substitution_offer_id` yields
    `ERR_SUBSTITUTION_OFFER_NOT_FOUND`"

    Design: Corner/errors/an_unknown_substitution_offer_id_returns_offer_not_found
    """
    w = canonical_world(api, "volunteer_verified")

    validate_error(
        api.get_substitution_offer(NON_EXISTENT_UUID, make_member_headers(w.mara_id)),
        ApiErrorId.ERR_SUBSTITUTION_OFFER_NOT_FOUND.value,
    )
