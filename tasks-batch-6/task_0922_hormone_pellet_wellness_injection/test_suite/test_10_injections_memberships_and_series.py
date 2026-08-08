"""Wellness injections, the payment waterfall, memberships and prepaid series."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    administer_visit,
    assert_membership,
    assert_same_instant,
    assert_series_entitlement_conservation,
    assert_series_pack,
    book_injection_visit,
    make_physician_headers,
    new_membership,
    new_patient,
    new_physician,
    new_series_pack,
    new_standing_order,
    read_injection_visit,
    read_membership,
    read_series_pack,
    set_clock,
    setup_injection_visit,
    validate_error,
    validate_paginated,
    validate_success,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]


def test_administering_against_an_expired_pack_is_refused(api):
    """PRD §2.9: "**Rung 32** — now is no later than the pack's `expires_at`, on
    `POST /clinic/injection-visits/{id}/administer`. Otherwise `ERR_SERIES_EXPIRED` (409),
    with the forfeiture behaviour described in §2.11."
    PRD §3.7: "`purchased_visits` and `remaining_visits` are both set to 8 while
    `redeemed_visits`, `refunded_visits`, `forfeited_visits` and `refunded_cents` all start at
    0; `purchased_at` is stamped from the logical clock, `expires_at` is set 365 days later,
    and `status` starts `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/injection_administer_blocked_by_expired_series_pack
    """
    ctx = setup_injection_visit(
        api, injection_type="B12", with_series_pack=True, room_code="RM15",
        scheduled_start="2027-05-02T09:00:00Z", administer_at="2027-05-02T00:00:00Z",
        patient_name="Pat TwentyTwo", patient_email="p22@example.com",
        standing_order_kwargs={"valid_until": "2027-05-01T00:00:00Z"},
    )
    assert ctx["pack"]["price_cents"] == 26300
    assert ctx["pack"]["per_visit_value_cents"] == 3287
    assert_same_instant(ctx["pack"]["expires_at"], "2027-05-01T00:00:00Z", "expires_at")

    response = api.administer_injection_visit(
        ctx["visit_id"], make_physician_headers(ctx["physician_id"])
    )
    validate_error(response, ApiErrorId.ERR_SERIES_EXPIRED.value)
    assert response.status_code == 409

    visit = read_injection_visit(api, ctx["visit_id"])
    assert visit["status"] == "SCHEDULED"
    assert visit["series_debit_cents"] == 0


def test_expiry_forfeiture_commits_before_the_request_is_rejected(api):
    """PRD §2.11: "Finally, one rule commits a write and then fails the request anyway. When
    an administration is attempted against a series pack whose validity has expired while the
    pack still reads `ACTIVE`, the forfeiture bookkeeping commits first — the remaining
    entitlements move into `forfeited_visits`, `remaining_visits` drops to zero and the pack's
    `version` increments — and only then is the request rejected with `ERR_SERIES_EXPIRED`."
    PRD §2.10: "**Entitlements in a series pool.** For every `SeriesPack`, `purchased_visits`
    always equals the sum of `remaining_visits`, `redeemed_visits`, `refunded_visits` and
    `forfeited_visits`."

    Design: Difficulty/cross_entity_state_dependency/injection_administer_blocked_by_expired_series_pack
    """
    ctx = setup_injection_visit(
        api, injection_type="B12", with_series_pack=True, room_code="RM15",
        scheduled_start="2027-05-02T09:00:00Z", administer_at="2027-05-02T00:00:00Z",
        patient_name="Pat TwentyTwo", patient_email="p22@example.com",
        standing_order_kwargs={"valid_until": "2027-05-01T00:00:00Z"},
    )

    response = api.administer_injection_visit(
        ctx["visit_id"], make_physician_headers(ctx["physician_id"])
    )
    validate_error(response, ApiErrorId.ERR_SERIES_EXPIRED.value)

    pack = read_series_pack(api, ctx["pack"]["id"])
    assert pack["status"] == "EXPIRED"
    assert pack["remaining_visits"] == 0
    assert pack["forfeited_visits"] == 8
    assert pack["redeemed_visits"] == 0
    assert pack["refunded_visits"] == 0
    assert_series_entitlement_conservation(pack)


def test_series_administration_draws_one_entitlement_and_debits_book_value(api):
    """PRD §3.7: "For `SERIES`, `charge_cents` is 0 and the value comes out of the pack
    instead: `series_debit_cents` is normally the pack's floored `per_visit_value_cents`, but
    on the **final** genuine redemption it is the pack's whole remaining book value, namely
    `price_cents` minus `per_visit_value_cents` multiplied by one fewer than
    `purchased_visits`."
    PRD §3.7: "The pack's `remaining_visits` decrements, `redeemed_visits` increments, and its
    `version` increments; when the draw takes the last entitlement the pack moves
    `ACTIVE → EXHAUSTED`."

    Design: Difficulty/compensating_invariant/administer_then_void_restores_series_entitlement_conservation
    """
    ctx = setup_injection_visit(
        api, injection_type="B12", with_series_pack=True, room_code="RM23",
        scheduled_start="2026-05-15T09:00:00Z", administer_at="2026-05-15T09:00:00Z",
        patient_name="Pat TwentyNine", patient_email="p29@example.com",
    )

    administered = administer_visit(api, ctx["visit_id"], ctx["physician_id"])
    assert administered["payment_source"] == "SERIES"
    assert administered["charge_cents"] == 0
    assert administered["series_debit_cents"] == 3287
    assert administered["status"] == "ADMINISTERED"

    pack = read_series_pack(api, ctx["pack"]["id"])
    assert pack["remaining_visits"] == 7
    assert pack["redeemed_visits"] == 1
    assert pack["status"] == "ACTIVE"
    assert_series_pack(pack)


def test_voiding_the_visit_returns_the_entitlement_to_the_pack(api):
    """PRD §2.10: "The compensating pair here is administering against the pack (moving one
    entitlement from remaining to redeemed) and voiding that visit (moving it back); the round
    trip restores `remaining_visits` exactly and leaves `refunded_visits` and
    `forfeited_visits` untouched."
    PRD §3.7: "An administered visit can be voided by a `Physician` with a required `reason`,
    moving it `ADMINISTERED → VOIDED`, and this is the compensating action for the entitlement
    identity: a `SERIES` visit gives the pack its entitlement back, decrementing
    `redeemed_visits` and incrementing `remaining_visits` and returning the pack
    `EXHAUSTED → ACTIVE` when this very visit was what exhausted it; a `MEMBERSHIP_INCLUDED`
    visit decrements `included_visits_used` and increments the membership's `version`; a
    `SELF_PAY` visit simply resets `charge_cents` to 0."

    Design: Difficulty/compensating_invariant/administer_then_void_restores_series_entitlement_conservation
    """
    ctx = setup_injection_visit(
        api, injection_type="B12", with_series_pack=True, room_code="RM23",
        scheduled_start="2026-05-15T09:00:00Z", administer_at="2026-05-15T09:00:00Z",
        patient_name="Pat TwentyNine", patient_email="p29@example.com",
    )
    administer_visit(api, ctx["visit_id"], ctx["physician_id"])

    voided = validate_success(
        api.void_injection_visit(
            ctx["visit_id"], {"reason": "Charted against the wrong pack"},
            make_physician_headers(ctx["physician_id"]),
        ),
        200,
    )
    assert voided["status"] == "VOIDED"
    assert voided["payment_source"] == "SERIES"
    assert voided["charge_cents"] == 0

    pack = read_series_pack(api, ctx["pack"]["id"])
    assert pack["purchased_visits"] == 8
    assert pack["remaining_visits"] == 8
    assert pack["redeemed_visits"] == 0
    assert pack["refunded_visits"] == 0
    assert pack["forfeited_visits"] == 0
    assert pack["status"] == "ACTIVE"


def test_membership_allowance_is_burned_before_the_visit_falls_through_to_self_pay(api):
    """PRD §3.7: "Step two: if `membership_id` is non-null and that membership's `status` is
    `ACTIVE` and its `included_visits_used` is strictly less than its
    `included_visits_allowance`, the source is `MEMBERSHIP_INCLUDED`. Step three: otherwise
    the source is `SELF_PAY`."
    PRD §3.7: "For `MEMBERSHIP_INCLUDED`, `charge_cents` is 0, `series_debit_cents` stays 0,
    the membership's `included_visits_used` increments and its `version` increments by 1. For
    `SELF_PAY`, `series_debit_cents` stays 0 and `charge_cents` is the injection's list price
    multiplied by one minus the applicable discount rate, rounded half up once — where the
    list prices are 3500 cents for `B12`, 4500 for `LIPOTROPIC`, 5500 for `VITAMIN_D` and 8500
    for `GLUTATHIONE`, and the discount rate is the membership's `discount_pct` when a
    `membership_id` is named and that membership is `ACTIVE`, and zero otherwise."

    Design: Corner/calculations/injection_payment_waterfall_burns_membership_allowance_then_self_pays
    """
    physician = new_physician(api)
    patient = new_patient(api, "Corner Eighteen", "c18@example.com", sex_at_birth="FEMALE")
    membership = new_membership(api, patient["id"], "ELITE")
    order = new_standing_order(api, physician["id"])

    visits = [
        book_injection_visit(
            api, patient["id"], physician["id"], order["id"],
            injection_type="GLUTATHIONE", room_code="RM43",
            scheduled_start=f"2026-05-06T{9 + offset:02d}:00:00Z",
            membership_id=membership["id"],
        )
        for offset in range(5)
    ]
    set_clock(api, "2026-05-06T09:00:00Z")

    administered = [administer_visit(api, visit["id"], physician["id"]) for visit in visits]

    assert administered[0]["payment_source"] == "MEMBERSHIP_INCLUDED"
    assert administered[0]["charge_cents"] == 0
    assert administered[3]["payment_source"] == "MEMBERSHIP_INCLUDED"
    assert administered[4]["payment_source"] == "SELF_PAY"
    assert administered[4]["charge_cents"] == 6800
    assert administered[4]["series_debit_cents"] == 0

    membership_after = read_membership(api, membership["id"])
    assert membership_after["included_visits_used"] == 4
    assert membership_after["included_visits_allowance"] == 4


def test_a_usable_pack_always_wins_over_an_unused_membership_allowance(api):
    """PRD §3.7: "How the visit is paid for is decided by a fixed three-step precedence,
    evaluated top to bottom with the first match winning, and written to `payment_source`.
    Step one: if `series_pack_id` is non-null, the source is `SERIES`."
    PRD §3.7: "The precedence is absolute — a patient holding both a usable pack and an unused
    included-visit allowance always burns the pack."

    Design: Corner/calculations/series_takes_precedence_over_membership_included_allowance
    """
    physician = new_physician(api)
    patient = new_patient(api, "Corner Nineteen", "c19@example.com", sex_at_birth="FEMALE")
    membership = new_membership(api, patient["id"], "ELITE")
    pack = new_series_pack(api, patient["id"], "B12")
    order = new_standing_order(api, physician["id"])
    visit = book_injection_visit(
        api, patient["id"], physician["id"], order["id"], injection_type="B12",
        room_code="RM44", scheduled_start="2026-05-07T09:00:00Z",
        series_pack_id=pack["id"], membership_id=membership["id"],
    )
    set_clock(api, "2026-05-07T09:00:00Z")

    administered = administer_visit(api, visit["id"], physician["id"])

    assert administered["payment_source"] == "SERIES"
    assert administered["series_debit_cents"] == 3287
    assert administered["charge_cents"] == 0

    pack_after = read_series_pack(api, pack["id"])
    assert pack_after["remaining_visits"] == 7
    assert pack_after["redeemed_visits"] == 1
    assert read_membership(api, membership["id"])["included_visits_used"] == 0


def test_eighth_redemption_takes_the_residual_and_exhausts_the_pack(api):
    """PRD §3.7: "For `SERIES`, `charge_cents` is 0 and the value comes out of the pack
    instead: `series_debit_cents` is normally the pack's floored `per_visit_value_cents`, but
    on the **final** genuine redemption it is the pack's whole remaining book value, namely
    `price_cents` minus `per_visit_value_cents` multiplied by one fewer than
    `purchased_visits`. That final-residual rule applies if and only if, immediately before
    this draw, `redeemed_visits` equals `purchased_visits` minus one — that is, every other
    entitlement was actually redeemed."
    PRD §3.7: "On a `B12` pack the ordinary debit is 3287 cents and the final-residual debit
    is 3291 cents, four cents more on the identical pack."

    Design: Corner/state_machines/series_pack_exhausts_on_eighth_redemption_with_residual_debit
    """
    physician = new_physician(api)
    patient = new_patient(api, "Corner Fourteen", "c14@example.com", sex_at_birth="FEMALE")
    order = new_standing_order(api, physician["id"])
    pack = new_series_pack(api, patient["id"], "B12")
    assert pack["price_cents"] == 26300
    assert pack["per_visit_value_cents"] == 3287

    visits = [
        book_injection_visit(
            api, patient["id"], physician["id"], order["id"], injection_type="B12",
            room_code="RM40", scheduled_start=f"2026-05-05T{9 + offset:02d}:00:00Z",
            series_pack_id=pack["id"],
        )
        for offset in range(8)
    ]
    set_clock(api, "2026-05-05T09:00:00Z")

    debits = [
        administer_visit(api, visit["id"], physician["id"])["series_debit_cents"]
        for visit in visits
    ]

    assert debits[0] == 3287
    assert debits[6] == 3287
    assert debits[7] == 3291, "The final genuine redemption carries the whole residual"
    assert sum(debits) == 26300

    pack_after = read_series_pack(api, pack["id"])
    assert pack_after["status"] == "EXHAUSTED"
    assert pack_after["remaining_visits"] == 0
    assert pack_after["redeemed_visits"] == 8
    assert pack_after["forfeited_visits"] == 0
    assert pack_after["refunded_visits"] == 0


def test_pack_refund_pays_the_floored_per_visit_value_and_keeps_the_residual(api):
    """PRD §3.7: "It can be refunded by `FrontDesk` with an optional `reason`, which moves it
    `ACTIVE → REFUNDED`: `refunded_visits` absorbs whatever `remaining_visits` held,
    `remaining_visits` drops to 0, and `refunded_cents` is set to the number of entitlements
    bought back multiplied by the floored `per_visit_value_cents` — deliberately with no
    residual adjustment, so a `B12` pack refunded before any redemption returns eight times
    3287, which is 26296 against a price of 26300, and the clinic keeps the four cents."

    Design: Corner/calculations/series_refund_pays_floored_per_visit_value_and_keeps_the_residual
    """
    patient = new_patient(api, "Corner TwentyOne", "c21@example.com", sex_at_birth="FEMALE")
    pack = new_series_pack(api, patient["id"], "B12")

    refunded = validate_success(
        api.refund_series_pack(pack["id"], {"reason": "Patient moving away"}, FRONT_DESK), 200
    )

    assert refunded["status"] == "REFUNDED"
    assert refunded["refunded_cents"] == 26296
    assert refunded["refunded_visits"] == 8
    assert refunded["remaining_visits"] == 0
    assert refunded["redeemed_visits"] == 0
    assert refunded["forfeited_visits"] == 0
    assert_series_pack(refunded)


def test_pause_credit_multiplies_the_unrounded_daily_rate_before_rounding_once(api):
    """PRD §3.7: "Pausing, available to `FrontDesk` or the `Patient`, moves the membership
    `ACTIVE → PAUSED` and banks a prorated credit computed in seven strictly ordered steps.
    First, elapsed days are the days between `period_start` and now. Second, the period length
    in days is the days between `period_start` and `period_end`. Third, unused days are the
    period length minus the elapsed days, floored at zero so a pause after the period has run
    out banks nothing. Fourth, the daily rate is `monthly_fee_cents` divided by the period
    length, kept as an exact unrounded rational. Fifth — and this is the only rounding step —
    the credit is the daily rate multiplied by the unused days, rounded half up to whole cents.
    Sixth, the credit is capped at `monthly_fee_cents`. Seventh, that credit is added to the
    membership's `pause_credit_cents`."
    PRD §3.7: "The order matters: an `ELITE` membership of 19900 cents over 30 days paused on
    elapsed day 7 has 23 unused days and a daily rate of 663.3333…, giving a correct credit of
    15257, whereas rounding the daily rate to 663 first and then multiplying gives 15249,
    which is wrong."

    Design: Corner/calculations/pause_credit_multiplies_unrounded_daily_rate_then_rounds_once
    """
    patient = new_patient(api, "Corner Sixteen", "c16@example.com", sex_at_birth="FEMALE")
    membership = new_membership(api, patient["id"], "ELITE")
    assert membership["monthly_fee_cents"] == 19900
    assert_same_instant(membership["period_start"], "2026-05-01T00:00:00Z", "period_start")
    assert_same_instant(membership["period_end"], "2026-05-31T00:00:00Z", "period_end")

    set_clock(api, "2026-05-08T00:00:00Z")
    paused = validate_success(api.pause_membership(membership["id"], FRONT_DESK), 200)

    assert paused["status"] == "PAUSED"
    assert_same_instant(paused["paused_at"], "2026-05-08T00:00:00Z", "paused_at")
    assert paused["pause_credit_cents"] == 15257
    assert paused["pause_credit_cents"] != 15249, (
        "Rounding the daily rate before multiplying would bank 15249"
    )
    assert_membership(paused)


def test_resume_beyond_the_annual_pause_allowance_is_rejected_without_mutation(api):
    """PRD §3.7: "Resuming moves it `PAUSED → ACTIVE` and is checked before it is applied:
    `pause_days_used` plus the days elapsed since `paused_at` must be no greater than 90, with
    equality passing, and a rejected resume answers `ERR_PAUSE_LIMIT_EXCEEDED` while leaving
    the membership entirely untouched. On success `pause_days_used` rises by the days elapsed
    since `paused_at`, `period_end` is pushed out by that same number of days,
    `pause_credit_cents` is reduced by the smaller of itself and `monthly_fee_cents`,
    `paused_at` returns to null, and the `version` increments."

    Design: Corner/validations/resume_beyond_the_annual_pause_allowance_is_rejected_without_mutation
    """
    patient = new_patient(api, "Corner ThirtyThree", "c33@example.com", sex_at_birth="FEMALE")
    membership = new_membership(api, patient["id"], "PLUS")

    set_clock(api, "2026-05-02T00:00:00Z")
    validate_success(api.pause_membership(membership["id"], FRONT_DESK), 200)
    set_clock(api, "2026-07-01T00:00:00Z")
    resumed = validate_success(api.resume_membership(membership["id"], FRONT_DESK), 200)
    assert resumed["pause_days_used"] == 60
    set_clock(api, "2026-07-02T00:00:00Z")
    validate_success(api.pause_membership(membership["id"], FRONT_DESK), 200)

    set_clock(api, "2026-08-12T00:00:00Z")
    response = api.resume_membership(membership["id"], FRONT_DESK)
    validate_error(response, ApiErrorId.ERR_PAUSE_LIMIT_EXCEEDED.value)
    assert response.status_code == 422

    untouched = read_membership(api, membership["id"])
    assert untouched["status"] == "PAUSED"
    assert untouched["pause_days_used"] == 60
    assert_same_instant(untouched["paused_at"], "2026-07-02T00:00:00Z", "paused_at")
    assert_same_instant(untouched["period_end"], "2026-07-30T00:00:00Z", "period_end")


def test_resuming_an_active_membership_reports_invalid_state(api):
    """PRD §3.7: "Resuming moves it `PAUSED → ACTIVE` and is checked before it is applied:
    `pause_days_used` plus the days elapsed since `paused_at` must be no greater than 90, with
    equality passing, and a rejected resume answers `ERR_PAUSE_LIMIT_EXCEEDED` while leaving
    the membership entirely untouched."
    PRD §2.9: "**Rung 10** — the target row is in a state from which the requested transition
    is declared on the relevant axis, on every action endpoint. Otherwise `ERR_INVALID_STATE`
    (409)."
    PRD §3.7: "Everything else is derived: `monthly_fee_cents` is 4900 for `BASIC`, 9900 for
    `PLUS` and 19900 for `ELITE`; `discount_pct` is 0.00, 0.10 and 0.20 across the same three
    tiers and applies both to procedure subtotals and to cancellation fees;
    `included_visits_allowance` is 0, 2 and 4 injection visits per period."

    Design: Corner/state_machines/membership_resume_while_active_returns_invalid_state
    """
    patient = new_patient(api, "Corner Ten", "c10@example.com", sex_at_birth="FEMALE")
    membership = new_membership(api, patient["id"], "PLUS")

    response = api.resume_membership(membership["id"], FRONT_DESK)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert response.status_code == 409

    after = read_membership(api, membership["id"])
    assert after["status"] == "ACTIVE"
    assert after["pause_days_used"] == 0
    assert after["monthly_fee_cents"] == 9900
    assert after["discount_pct"] == 0.10
    assert after["included_visits_allowance"] == 2


def test_second_live_membership_for_one_patient_is_refused(api):
    """PRD §3.7: "A patient may hold only one live membership: enrolling while another
    membership of theirs is `ACTIVE` or `PAUSED` is refused with
    `ERR_DUPLICATE_ACTIVE_MEMBERSHIP`."
    PRD §2.9: "**Rung 34** — the patient holds no other membership in status `ACTIVE` or
    `PAUSED`, on `POST /clinic/memberships`. Otherwise `ERR_DUPLICATE_ACTIVE_MEMBERSHIP` (409)."

    Design: Corner/validations/second_active_membership_for_one_patient_is_rejected
    """
    patient = new_patient(api, "Corner Thirty", "c30@example.com")
    first = new_membership(api, patient["id"], "BASIC")

    response = api.create_membership({"patient_id": patient["id"], "tier": "ELITE"}, FRONT_DESK)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ACTIVE_MEMBERSHIP.value)
    assert response.status_code == 409

    kept = read_membership(api, first["id"])
    assert kept["tier"] == "BASIC"
    assert kept["monthly_fee_cents"] == 4900
    assert kept["discount_pct"] == 0.00
    assert kept["included_visits_allowance"] == 0

    rows, meta = validate_paginated(
        api.list_memberships(FRONT_DESK, {"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 1


def test_a_pack_cannot_be_attached_to_another_patients_visit(api):
    """PRD §3.7: "Injection bookings run the same provider-conflict and room-conflict geometry
    as insertions — twenty minutes of buffer on the provider, none on the room — and a pack
    named for a different patient is refused at once with `ERR_SERIES_NOT_TRANSFERABLE`."
    PRD §2.9: "**Rung 31** — the series pack's `patient_id` equals the injection visit's
    `patient_id`, on `POST /clinic/injection-visits` and
    `POST /clinic/injection-visits/{id}/administer`. Packs are never transferable between
    patients. Otherwise `ERR_SERIES_NOT_TRANSFERABLE` (403)."

    Design: Corner/validations/series_pack_cannot_be_applied_to_another_patients_visit
    """
    physician = new_physician(api)
    owner = new_patient(api, "Corner ThirtyFour A", "c34a@example.com", sex_at_birth="FEMALE")
    stranger = new_patient(
        api, "Corner ThirtyFour B", "c34b@example.com", sex_at_birth="FEMALE",
        date_of_birth="1980-01-02",
    )
    order = new_standing_order(api, physician["id"])
    pack = new_series_pack(api, owner["id"], "B12")

    response = api.create_injection_visit(
        {
            "patient_id": stranger["id"],
            "provider_id": physician["id"],
            "standing_order_id": order["id"],
            "injection_type": "B12",
            "room_code": "RM56",
            "scheduled_start": "2026-05-26T09:00:00Z",
            "series_pack_id": pack["id"],
        },
        FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_SERIES_NOT_TRANSFERABLE.value)
    assert response.status_code == 403

    assert read_series_pack(api, pack["id"])["remaining_visits"] == 8
    rows, meta = validate_paginated(
        api.list_injection_visits(FRONT_DESK, {"patient_id": stranger["id"]})
    )
    assert meta["total_count"] == 0


def test_administering_against_a_refunded_pack_reports_exhausted_not_expired(api):
    """PRD §2.9: "**Rung 33** — the pack's `remaining_visits` is at least 1, on
    `POST /clinic/injection-visits/{id}/administer`. Otherwise `ERR_SERIES_EXHAUSTED` (409)."
    PRD §3.7: "A pack with no entitlements left but still inside its validity window is
    refused with `ERR_SERIES_EXHAUSTED` instead — and because the expiry check sits above the
    exhaustion check, a pack that is both expired and exhausted reports the expiry."

    Design: Corner/validations/administering_against_a_refunded_pack_reports_exhausted
    """
    ctx = setup_injection_visit(
        api, injection_type="B12", with_series_pack=True, room_code="RM57",
        scheduled_start="2026-05-27T09:00:00Z",
        patient_name="Corner ThirtyFive", patient_email="c35@example.com",
    )
    validate_success(
        api.refund_series_pack(ctx["pack"]["id"], {"reason": "Changed her mind"}, FRONT_DESK), 200
    )
    set_clock(api, "2026-05-27T09:00:00Z")

    response = api.administer_injection_visit(
        ctx["visit_id"], make_physician_headers(ctx["physician_id"])
    )
    validate_error(response, ApiErrorId.ERR_SERIES_EXHAUSTED.value)
    assert response.status_code == 409

    pack = read_series_pack(api, ctx["pack"]["id"])
    assert pack["status"] == "REFUNDED"
    assert pack["remaining_visits"] == 0
    assert pack["refunded_visits"] == 8
    assert pack["forfeited_visits"] == 0
    assert read_injection_visit(api, ctx["visit_id"])["status"] == "SCHEDULED"


def test_voiding_a_still_scheduled_visit_reports_invalid_state(api):
    """PRD §3.7: "An administered visit can be voided by a `Physician` with a required
    `reason`, moving it `ADMINISTERED → VOIDED`, and this is the compensating action for the
    entitlement identity: a `SERIES` visit gives the pack its entitlement back, decrementing
    `redeemed_visits` and incrementing `remaining_visits` and returning the pack
    `EXHAUSTED → ACTIVE` when this very visit was what exhausted it; a `MEMBERSHIP_INCLUDED`
    visit decrements `included_visits_used` and increments the membership's `version`; a
    `SELF_PAY` visit simply resets `charge_cents` to 0."
    PRD §3.7: "The four packs price out as follows: `B12` at 26300 cents with a per-visit
    value of 3287; `LIPOTROPIC` at 33100 with 4137; `VITAMIN_D` at 39900 with 4987;
    `GLUTATHIONE` at 60300 with 7537 — each leaving a four-cent residual."

    Design: Corner/state_machines/injection_visit_void_from_scheduled_returns_invalid_state
    """
    ctx = setup_injection_visit(
        api, injection_type="LIPOTROPIC", with_series_pack=True, room_code="RM41",
        scheduled_start="2026-05-25T09:00:00Z",
        patient_name="Corner Fifteen", patient_email="c15@example.com",
    )

    response = api.void_injection_visit(
        ctx["visit_id"], {"reason": "Booked in error"},
        make_physician_headers(ctx["physician_id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert response.status_code == 409

    assert read_injection_visit(api, ctx["visit_id"])["status"] == "SCHEDULED"
    pack = read_series_pack(api, ctx["pack"]["id"])
    assert pack["price_cents"] == 33100
    assert pack["per_visit_value_cents"] == 4137
    assert pack["remaining_visits"] == 8
    assert pack["status"] == "ACTIVE"
