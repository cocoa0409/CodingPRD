"""Talent money: the two usage-fee variants, the payment mirror on the casting
deal, settlement — plus delivery and recall of the finished order."""

import pytest

from test_helpers import (
    ADMIN,
    CASTING,
    MIXER,
    PC,
    REVIEWER_2,
    ApiErrorId,
    accrue_payment,
    assert_order_money_conserved,
    assert_same_instant,
    assert_talent_payment,
    book_session,
    create_talent_payment_payload,
    make_native_reviewer_headers,
    run_session_to_completed,
    setup_after_qc_failure,
    setup_canon,
    setup_order_in_qc,
    start_review_round,
    validate_error,
    validate_paginated,
    validate_success,
)

QC_REVIEWER = make_native_reviewer_headers(REVIEWER_2)


# --------------------------------------------------------------------------
# The two usage-fee variants on identical session data
# --------------------------------------------------------------------------
def test_a_buyout_deal_pays_a_flat_multiple_of_the_base_fee(api):
    """PRD §3.10: "For each of the assignment's own sessions that is `COMPLETED` and
    whose `is_retake` is false, the service multiplies the assignment's
    `agreed_rate_cents_per_hour` by that session's `duration_minutes`, divides by
    sixty, and rounds half up to a whole cent."
    PRD §3.10: "Under `BUYOUT`, a single flat multiplier buys every territory at once:
    `usage_fee_cents` is `base_fee_cents` multiplied by one and seventy-five
    hundredths, rounded half up to a whole cent."
    PRD §3.10: "`total_fee_cents` is simply `base_fee_cents` plus `usage_fee_cents`,
    both already whole cents."

    Design: Difficulty/dual_variant_calc/talent_payment_buyout_vs_residual_diverge
    """
    ctx = setup_canon(36)
    data = validate_success(
        api.create_talent_payment(
            create_talent_payment_payload(ctx["ca1_id"], ["US", "DE", "JP"]), ADMIN
        ),
        201,
    )
    assert_talent_payment(data)
    assert data["variant"] == "BUYOUT"
    assert data["base_fee_cents"] == 72000
    assert data["usage_fee_cents"] == 126000
    assert data["total_fee_cents"] == 198000


def test_a_residual_deal_pays_the_banded_total_on_the_same_territory_scope(api):
    """PRD §3.10: "Walking the sorted list from its first position, the first
    territory contributes forty-five hundredths, the second contributes thirty
    hundredths, the third contributes eighteen hundredths, and every territory from
    the fourth position onward contributes seven hundredths each."
    PRD §3.10: "A three-territory residual scope therefore pays ninety-three
    hundredths of the base while a buyout on the same data pays one and seventy-five
    hundredths of it."
    PRD §3.10: "`total_fee_cents` is simply `base_fee_cents` plus `usage_fee_cents`,
    both already whole cents."

    Design: Difficulty/dual_variant_calc/talent_payment_buyout_vs_residual_diverge
    """
    ctx = setup_canon(36)
    data = validate_success(
        api.create_talent_payment(
            create_talent_payment_payload(ctx["ca2_id"], ["US", "DE", "JP"]), ADMIN
        ),
        201,
    )
    assert_talent_payment(data)
    assert data["variant"] == "RESIDUAL"
    assert data["base_fee_cents"] == 34000
    assert data["usage_fee_cents"] == 31620
    assert data["total_fee_cents"] == 65620


def test_a_seven_territory_residual_scope_is_clipped_by_the_cap(api):
    """PRD §3.10: "Those contributions are summed into a single band total, that total
    is capped at one and twenty hundredths — a seven-territory scope would otherwise
    reach one and twenty-one hundredths and is therefore clipped — and
    `usage_fee_cents` is `base_fee_cents` multiplied by the capped total, rounded half
    up to a whole cent exactly once."
    PRD §3.10: "The supplied `territory_scope` is first sorted ascending by each
    territory's position in the canonical order `US`, `CA`, `UK`, `DE`, `FR`, `JP`,
    `BR`, `AU`, `ROW` — the ordering is by that canonical position only, never by the
    order the client listed them and never by row identifier."

    Design: Corner/calculations/residual_band_total_is_clipped_by_the_cap
    """
    scope = ["US", "CA", "UK", "DE", "FR", "JP", "BR"]
    ctx = setup_canon(
        21,
        talent1={"full_name": "Anna Vogel", "licensed_territories": scope},
        ca1={"usage_variant": "RESIDUAL"},
    )
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")
    run_session_to_completed(ctx, "s1_id", "2026-09-10T09:00:00Z")

    data = validate_success(
        api.create_talent_payment(create_talent_payment_payload(ctx["ca1_id"], scope), ADMIN),
        201,
    )
    assert data["variant"] == "RESIDUAL"
    assert data["base_fee_cents"] == 72000
    assert data["usage_fee_cents"] == 86400
    assert data["total_fee_cents"] == 158400
    assert validate_success(
        api.get_casting_assignment(ctx["ca1_id"], CASTING)
    )["payment_status"] == "ACCRUED"


# --------------------------------------------------------------------------
# The two independent state dimensions of a casting deal
# --------------------------------------------------------------------------
def test_the_booking_dimension_reaches_recorded_while_payment_is_still_unbilled(api):
    """PRD §3.5: "The payment dimension is `payment_status`, and it is genuinely
    independent of the booking dimension: a `CONFIRMED` assignment can be `UNBILLED`,
    and a `RECORDED` assignment can be `UNBILLED`, `ACCRUED`, `SETTLED` or `VOIDED`."
    PRD §3.5: "It starts at `UNBILLED`."
    PRD §3.5: "When one of the assignment's sessions whose `is_retake` is false
    reaches `COMPLETED`, the assignment advances `CONFIRMED → RECORDED`, its
    `recorded_minutes` is recomputed, and its `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/casting_assignment_two_dimensions_advance_independently
    """
    ctx = setup_canon(36)
    data = validate_success(api.get_casting_assignment(ctx["ca1_id"], CASTING))
    assert data["casting_status"] == "RECORDED"
    assert data["payment_status"] == "UNBILLED"
    assert data["recorded_minutes"] == 120


def test_accruing_a_payment_moves_only_the_payment_dimension(api):
    """PRD §3.5: "Accruing a payment against the assignment moves it
    `UNBILLED → ACCRUED`, and the same edge exists as `VOIDED → ACCRUED` for a
    replacement payment raised after a retake round; both require the assignment's
    `casting_status` to be `RECORDED` at the moment of accrual."
    PRD §3.5: "The two dimensions never share a trigger except that single retake
    cascade, which moves each dimension along its own edge independently."

    Design: Difficulty/non_linear_state_machine/casting_assignment_two_dimensions_advance_independently
    """
    ctx = setup_canon(36)
    payment = validate_success(
        api.create_talent_payment(
            create_talent_payment_payload(ctx["ca1_id"], ["US", "DE", "JP"]), ADMIN
        ),
        201,
    )
    assert payment["status"] == "ACCRUED"
    assert payment["total_fee_cents"] == 198000

    data = validate_success(api.get_casting_assignment(ctx["ca1_id"], CASTING))
    assert data["casting_status"] == "RECORDED", (
        "the accrual must not disturb the booking dimension"
    )
    assert data["payment_status"] == "ACCRUED"


# --------------------------------------------------------------------------
# Accrual guards
# --------------------------------------------------------------------------
def test_a_second_accrual_on_one_deal_is_refused(api):
    """PRD §3.10: "The assignment must be in `casting_status` of `RECORDED`, and it
    must not already carry a payment in `ACCRUED` — a second concurrent accrual on the
    same deal is refused with `ERR_PAYMENT_ALREADY_ACCRUED`."
    PRD §3.10: "Payments may be listed filtered by `casting_assignment_id`, by
    `talent_id` and by `status`."

    Design: Corner/validations/second_accrual_on_one_assignment_is_rejected
    """
    ctx = setup_canon(21)
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")
    run_session_to_completed(ctx, "s1_id", "2026-09-10T09:00:00Z")
    accrue_payment(ctx, "tp1_id", "ca1_id", ["US", "DE", "JP"])

    resp = api.create_talent_payment(
        create_talent_payment_payload(ctx["ca1_id"], ["DE"]), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_ALREADY_ACCRUED.value)
    assert resp.status_code == 409
    rows, _ = validate_paginated(
        api.list_talent_payments(ADMIN, {"casting_assignment_id": ctx["ca1_id"]})
    )
    assert len(rows) == 1
    assert validate_success(api.get_talent_payment(ctx["tp1_id"], ADMIN))["status"] == "ACCRUED"


def test_a_territory_scope_outside_the_performer_rights_is_refused(api):
    """PRD §3.10: "The scope must be a subset of the performer's
    `licensed_territories` and must itself contain the owning order's `territory`; a
    scope that escapes the performer's rights or omits the order's own territory is
    refused with `ERR_TERRITORY_NOT_LICENSED`."

    Design: Corner/validations/payment_scope_outside_talent_rights_is_rejected
    """
    ctx = setup_canon(21)
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")
    run_session_to_completed(ctx, "s1_id", "2026-09-10T09:00:00Z")

    resp = api.create_talent_payment(
        create_talent_payment_payload(ctx["ca1_id"], ["DE", "FR"]), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_TERRITORY_NOT_LICENSED.value)
    assert resp.status_code == 422
    assert validate_success(
        api.get_casting_assignment(ctx["ca1_id"], CASTING)
    )["payment_status"] == "UNBILLED"
    rows, _ = validate_paginated(
        api.list_talent_payments(ADMIN, {"casting_assignment_id": ctx["ca1_id"]})
    )
    assert rows == []


def test_settling_an_already_settled_payment_is_refused(api):
    """PRD §3.10: "Settlement is the terminal act. A `PlatformAdmin` settles a payment
    that is currently `ACCRUED`; a payment already `SETTLED` or `VOIDED` earns
    `ERR_PAYMENT_ALREADY_SETTLED`."
    PRD §3.10: "A surviving settlement moves the payment `ACCRUED → SETTLED`, stamps
    `settled_at` with the current logical-clock instant, advances the assignment's
    payment dimension `ACCRUED → SETTLED`, and increments the payment's `version` by
    1."

    Design: Corner/errors/settling_a_payment_twice_returns_already_settled
    """
    ctx = setup_canon(43)
    validate_success(
        api.decide_quality_review(
            ctx["qr_id"], {"decision": "PASS", "defect_count": 20}, QC_REVIEWER
        )
    )
    settled = validate_success(api.settle_talent_payment(ctx["tp1_id"], ADMIN))
    assert settled["status"] == "SETTLED"
    assert_same_instant(settled["settled_at"], "2026-09-10T12:00:00Z", "settled_at")
    assert validate_success(
        api.get_casting_assignment(ctx["ca1_id"], CASTING)
    )["payment_status"] == "SETTLED"

    resp = api.settle_talent_payment(ctx["tp1_id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_ALREADY_SETTLED.value)
    assert resp.status_code == 409


def test_the_payment_mirror_flips_back_to_accrued_on_a_replacement_payment(api):
    """PRD §3.10: "A deal whose previous payment was voided by a retake round is
    explicitly re-accruable, which is how a re-recorded performance gets paid again."
    PRD §3.10: "Creating it advances the assignment's payment dimension
    `UNBILLED → ACCRUED`, or `VOIDED → ACCRUED` when this is a replacement after a
    retake round."
    PRD §3.10: "Sessions in any other status contribute nothing, and retake sessions
    never enter the base at all, which is precisely why a retake is a cost to the
    vendor rather than a second payday for the performer."

    Design: Corner/cross_cutting_layers/payment_status_mirror_reconciles_on_void_and_reaccrual
    """
    ctx = setup_after_qc_failure()
    book_session(ctx, "s3_id", "ca1_id", "2026-09-11T09:00:00Z", "2026-09-11T11:00:00Z",
                 is_retake=True)
    run_session_to_completed(ctx, "s3_id", "2026-09-11T09:00:00Z")

    assert validate_success(
        api.get_casting_assignment(ctx["ca1_id"], CASTING)
    )["payment_status"] == "VOIDED"

    replacement = validate_success(
        api.create_talent_payment(
            create_talent_payment_payload(ctx["ca1_id"], ["US", "DE", "JP"]), ADMIN
        ),
        201,
    )
    assert validate_success(
        api.get_casting_assignment(ctx["ca1_id"], CASTING)
    )["payment_status"] == "ACCRUED"
    assert validate_success(api.get_talent_payment(ctx["tp1_id"], ADMIN))["status"] == "VOIDED"
    assert replacement["status"] == "ACCRUED"
    assert replacement["base_fee_cents"] == 72000
    assert replacement["usage_fee_cents"] == 126000
    rows, _ = validate_paginated(
        api.list_talent_payments(ADMIN, {"casting_assignment_id": ctx["ca1_id"]})
    )
    assert len(rows) == 2


# --------------------------------------------------------------------------
# Delivery and recall
# --------------------------------------------------------------------------
def _order_with_a_passed_review(api):
    ctx = setup_order_in_qc()
    start_review_round(ctx, reviewer_user=REVIEWER_2, sampled_loop_count=200)
    validate_success(
        api.decide_quality_review(
            ctx["qr_id"], {"decision": "PASS", "defect_count": 20}, QC_REVIEWER
        )
    )
    return ctx


def test_delivery_requires_every_metadata_key_the_specification_names(api):
    """PRD §3.11: "Three preconditions apply: the order must be in `QC`; the order's
    newest quality review must be in `PASSED`, and an order whose newest review has
    not passed is refused with `ERR_INVALID_STATE`; and every key listed in the
    platform specification's `metadata_fields_required` must be present in the
    supplied map with a non-empty value, a shortfall being refused with
    `ERR_METADATA_INCOMPLETE`."
    PRD §3.11: "Delivery stores the supplied map in `metadata_locale_fields`, stamps
    `delivered_at` with the current logical-clock instant, and increments the order's
    `version` by 1."

    Design: Corner/validations/delivery_without_every_required_metadata_key_is_rejected
    """
    ctx = _order_with_a_passed_review(api)
    resp = api.deliver_order(
        ctx["o_id"], {"metadata_locale_fields": {"title_local": "Der Titel"}}, PC
    )
    validate_error(resp, ApiErrorId.ERR_METADATA_INCOMPLETE.value)
    assert resp.status_code == 422

    delivered = validate_success(
        api.deliver_order(
            ctx["o_id"],
            {"metadata_locale_fields": {"title_local": "Der Titel",
                                        "synopsis_local": "Die Inhaltsangabe"}},
            PC,
        )
    )
    assert delivered["status"] == "DELIVERED"
    assert_same_instant(delivered["delivered_at"], "2026-09-10T12:00:00Z", "delivered_at")


def test_recall_supersedes_the_conformed_mix_and_releases_the_committed_money(api):
    """PRD §3.11: "A `ProductionCoordinator` may supply an optional free-text
    `reason`; the order moves `DELIVERED → RECALLED` and three things happen alongside.
    The whole of the order's `committed_cents` is moved into its `released_cents`,
    leaving `gross_accrued_cents` untouched so that the conservation invariant of §2.9
    still holds. The order's newest mix job moves `CONFORMED → SUPERSEDED`. And the
    order's `version` increments by 1."

    Design: Corner/state_machines/recall_supersedes_conformed_mix_and_releases_money
    """
    ctx = _order_with_a_passed_review(api)
    validate_success(
        api.deliver_order(
            ctx["o_id"],
            {"metadata_locale_fields": {"title_local": "Der Titel",
                                        "synopsis_local": "Die Inhaltsangabe"}},
            PC,
        )
    )
    recalled = validate_success(
        api.recall_order(ctx["o_id"], {"reason": "Loudness complaint"}, PC)
    )
    assert recalled["status"] == "RECALLED"
    assert validate_success(api.get_mix_job(ctx["mj_id"], MIXER))["status"] == "SUPERSEDED"
    assert recalled["committed_cents"] == 0
    assert recalled["released_cents"] == 190000
    assert recalled["gross_accrued_cents"] == 190000
    assert_order_money_conserved(recalled)
    assert validate_success(api.get_quality_review(ctx["qr_id"], PC))["status"] == "PASSED"
