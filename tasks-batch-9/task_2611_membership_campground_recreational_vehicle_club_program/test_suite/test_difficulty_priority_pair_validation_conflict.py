"""Requests that break two rungs at once report the higher rung."""

from test_helpers import (
    ADMIN,
    assert_entitlement_counters,
    assert_membership_axes,
    book_member_stay,
    completed_stay,
    create_classic_tier,
    create_open_park,
    make_reinstatement_payload,
    make_reservation_payload,
    pay_invoice_in_full,
    read_membership,
    reset_clock,
    sell_membership_to_new_member,
    set_clock,
    suspend_membership,
    validate_error,
    validate_paginated,
    validate_success,
)


def _exhausted_and_suspended_classic(api):
    """A CLASSIC contract with its ten CLASS_B nights spent and then suspended."""
    reset_clock(api)
    tier = create_classic_tier(api)
    holder = sell_membership_to_new_member(api, tier["id"], upfront_paid_cents=795000)
    park = create_open_park(
        api,
        name="Agave Ridge RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    completed_stay(
        api,
        holder["headers"],
        park["id"],
        holder["membership_id"],
        "2026-08-05",
        "2026-08-15",
    )
    set_clock(api, "2026-08-16")
    suspend_membership(api, holder["membership_id"], "ADMIN_ACTION")
    return holder, park


def test_suspended_contract_outranks_an_exhausted_entitlement(api):
    """The contract-state rung answers first even though the fiscal rung also fails.

    PRD §2.8: "Membership contract state — `ERR_MEMBERSHIP_NOT_ACTIVE` (HTTP 409),
    on member booking, extension and transfer submission: the acting membership's
    `membership_status` must be `ACTIVE`, so `SUSPENDED`, `TRANSFER_PENDING` and
    `TERMINATED` memberships can neither book, extend nor transfer."

    Design: Difficulty/priority_pair_validation_conflict/membership_not_active_state_error_outranks_entitlement_exhausted_fiscal_error
    """
    holder, park = _exhausted_and_suspended_classic(api)
    assert_entitlement_counters(read_membership(api, holder["membership_id"]), class_b=10, annual=10)

    response = api.create_reservation(
        make_reservation_payload(
            park["id"], holder["membership_id"], "2026-08-20", "2026-08-25"
        ),
        holder["headers"],
    )
    validate_error(response, "ERR_MEMBERSHIP_NOT_ACTIVE", 409)

    rows, _meta = validate_paginated(
        api.list_reservations(ADMIN, {"membership_id": holder["membership_id"]})
    )
    assert len(rows) == 1, "the rejected booking created no reservation row"
    assert_entitlement_counters(read_membership(api, holder["membership_id"]), class_b=10, annual=10)


def test_reinstatement_exposes_the_lower_entitlement_rung(api):
    """With the contract axis repaired, the identical request reports the fiscal rung.

    PRD §3.3: "Landing exactly on either limit is permitted; exceeding either is
    refused with `ERR_ENTITLEMENT_NIGHTS_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/membership_not_active_state_error_outranks_entitlement_exhausted_fiscal_error
    """
    holder, park = _exhausted_and_suspended_classic(api)

    pay_invoice_in_full(api, holder["invoice_id"], holder["headers"])
    reinstated = validate_success(
        api.reinstate_membership(
            holder["membership_id"],
            make_reinstatement_payload(reinstatement_fee_paid_cents=15000),
            ADMIN,
        ),
        200,
    )
    assert_membership_axes(reinstated, "ACTIVE", "CURRENT")

    response = api.create_reservation(
        make_reservation_payload(
            park["id"], holder["membership_id"], "2026-08-20", "2026-08-25"
        ),
        holder["headers"],
    )
    validate_error(response, "ERR_ENTITLEMENT_NIGHTS_EXHAUSTED", 422)
    assert_entitlement_counters(read_membership(api, holder["membership_id"]), class_b=10, annual=10)


def _classic_holder_with_a_confirmed_late_september_stay(api):
    """A CLASSIC contract whose next arrival is one night after its own departure."""
    reset_clock(api)
    tier = create_classic_tier(api)
    holder = sell_membership_to_new_member(api, tier["id"], upfront_paid_cents=795000)
    park = create_open_park(
        api,
        name="Storm Lake RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    existing = book_member_stay(
        api, holder["headers"], park["id"], holder["membership_id"], "2026-09-28", "2026-10-02"
    )
    return holder, park, existing


def test_advance_window_outranks_the_out_and_back_gap(api):
    """At 63 days out the temporal rung answers before the constraint rung.

    PRD §2.8: "Note likewise that on a booking, all of the temporal and length
    rules (rungs 31 through 36) are evaluated before the fiscal rules (rungs 42
    through 45), so a stay that is both too far in advance and beyond its
    entitlement reports the advance window."

    Design: Difficulty/priority_pair_validation_conflict/advance_window_temporal_error_outranks_out_and_back_constraint_error
    """
    holder, park, _existing = _classic_holder_with_a_confirmed_late_september_stay(api)

    response = api.create_reservation(
        make_reservation_payload(
            park["id"], holder["membership_id"], "2026-10-03", "2026-10-06"
        ),
        holder["headers"],
    )
    validate_error(response, "ERR_ADVANCE_WINDOW_EXCEEDED", 422)
    assert_entitlement_counters(read_membership(api, holder["membership_id"]), class_b=4, annual=4)


def test_out_and_back_gap_answers_once_the_window_is_satisfied(api):
    """Exactly 60 days out clears the window and the one-night gap is refused.

    PRD §3.3: "Otherwise the gap is the requested `arrival_date` minus that
    previous stay's `departure_date`, in whole nights, and the rule passes when
    the gap is at least the tier's `min_out_nights_between_stays`."

    Design: Difficulty/priority_pair_validation_conflict/advance_window_temporal_error_outranks_out_and_back_constraint_error
    """
    holder, park, existing = _classic_holder_with_a_confirmed_late_september_stay(api)

    set_clock(api, "2026-08-04")
    response = api.create_reservation(
        make_reservation_payload(
            park["id"], holder["membership_id"], "2026-10-03", "2026-10-06"
        ),
        holder["headers"],
    )
    validate_error(response, "ERR_OUT_AND_BACK_VIOLATION", 422)

    still_there = validate_success(api.get_reservation(existing["id"], ADMIN), 200)
    assert still_there["status"] == "CONFIRMED", "the earlier stay is untouched"
    assert_entitlement_counters(read_membership(api, holder["membership_id"]), class_b=4, annual=4)
