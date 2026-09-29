"""The refusal a settled obligation earns and the stay-shaped refusal that hides it, the
disbursement that waits for cash it can actually spend, and the identical two-field body
that five different refusal classes hand back."""

from test_helpers import (
    ApiErrorId,
    assert_batch,
    assert_delivery,
    assert_fund,
    assert_hotel,
    assert_member,
    assert_purchase,
    assert_redemption,
    assert_stay,
    factories as fac,
    fixtures as fx,
    make_admin_headers,
    make_auditor_headers,
    make_hotel_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

_UNKNOWN_MEMBER_ID = "00000000-0000-4000-8000-000000000000"


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _deliverstate_house_with_two_open_obligations(api):
    """A silver guest with two short stays behind the qualifying one, each carrying a single
    outstanding upgrade the property has yet to answer for."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Deliverstate Hotel",
        brand_code="DSH",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=110,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    rate_plan_id = bundle["rate_plan"]["id"]
    member = fx.enroll_member(
        api, email="ds1@example.com", full_name="Kasper Lind", enrollment_date="2026-01-22"
    )
    member_id = member["id"]
    qualifying = fx.posted_stay(
        api, hotel_id, member_id, rate_plan_id, "2026-04-01", "2026-04-11", 100_000
    )
    stay_b = fx.posted_stay(
        api, hotel_id, member_id, rate_plan_id, "2026-05-01", "2026-05-03", 40_000
    )
    stay_c = fx.posted_stay(
        api, hotel_id, member_id, rate_plan_id, "2026-06-01", "2026-06-03", 40_000
    )

    bundle["member"] = member
    bundle["member_id"] = member_id
    bundle["qualifying_stay"] = qualifying
    bundle["stay_b"] = stay_b
    bundle["stay_c"] = stay_c
    bundle["obligation_b"] = fx.obligation_of_type(api, stay_b["id"], "UPGRADE")
    bundle["obligation_c"] = fx.obligation_of_type(api, stay_c["id"], "UPGRADE")
    return bundle


def _cashfloor_resort_with_an_approved_batch_the_fund_cannot_cover(api):
    """A compression-market resort owed 160,000 cents against a fund holding only the
    47,500 cents one guest paid for points, with the batch already approved."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Cashfloor Resort",
        brand_code="CFR",
        market_tier="RESORT",
        program_fee_pct=0.05,
        rooms_count=120,
        trailing_12m_occupancy_pct=0.96,
        trailing_12m_adr_cents=80_000,
    )
    hotel_id = bundle["hotel"]["id"]
    fx.publish_pricing(
        api,
        hotel_id,
        season="STANDARD",
        window_start_date="2026-06-01",
        window_end_date="2026-06-30",
        points_per_night=20_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=2,
    )
    member = fx.enroll_member(
        api, email="cf1@example.com", full_name="Selma Vidal", enrollment_date="2026-01-25"
    )
    member_id = member["id"]
    first_purchase = fx.settled_purchase(
        api, member_id, 40_000, channel="DIRECT_PURCHASE"
    )
    accrued = fx.accrued_award(api, member_id, hotel_id, "2026-06-05", "2026-06-07")
    batch = fx.open_batch(api, hotel_id, "2026-06")
    released = fx.release_batch(api, batch["id"], "op-release-cf")
    approved = fx.approve_batch(api, batch["id"], "op-approve-cf")

    bundle["member"] = member
    bundle["member_id"] = member_id
    bundle["first_purchase"] = first_purchase
    bundle["accrued"] = accrued
    bundle["batch_id"] = batch["id"]
    bundle["opened_batch"] = batch
    bundle["released_batch"] = released
    bundle["approved_batch"] = approved
    return bundle


def _top_the_fund_up_to_the_exact_disbursement(api, member_id):
    """Two further settled sales, 110,000 cents and 2,500 cents, bringing programme cash to
    exactly the 160,000 the batch will disburse."""
    big = fx.settled_purchase(api, member_id, 100_000, channel="DIRECT_PURCHASE")
    small = fx.settled_purchase(api, member_id, 2_000, channel="DIRECT_PURCHASE")
    return {"big": big, "small": small}


def _envelope_arms_with_an_impaired_fund(api):
    """One posted ten-night stay leaves ten thousand points outstanding against no cash at
    all, which drives the fund's posture to impaired."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Envelope Arms",
        brand_code="EVA",
        market_tier="SELECT",
        program_fee_pct=0.05,
        rooms_count=60,
        trailing_12m_occupancy_pct=0.70,
        trailing_12m_adr_cents=12_000,
    )
    hotel_id = bundle["hotel"]["id"]
    member = fx.enroll_member(
        api,
        email="ev1@example.com",
        full_name="Odile Bertrand",
        enrollment_date="2026-01-27",
    )
    member_id = member["id"]
    stay = fx.posted_stay(
        api,
        hotel_id,
        member_id,
        bundle["rate_plan"]["id"],
        "2026-04-01",
        "2026-04-11",
        100_000,
    )

    bundle["member"] = member
    bundle["member_id"] = member_id
    bundle["stay"] = stay
    return bundle


# ----------------------------------------------------------------------
# A settled obligation refuses both verbs, unless its stay refuses first.
# ----------------------------------------------------------------------
class TestDeliveryInvalidStateFiresOnASettledRowAndIsItselfMaskedByTheStay:
    def test_honouring_an_outstanding_upgrade_recovers_a_capped_share_of_the_rate(
        self, api
    ):
        """Fifteen percent of a 30,000-cent average daily rate is 4,500, comfortably under
        the ceiling, and it lands on the obligation as the property's recovery.

        PRD: "An `UPGRADE` recovers fifteen percent of the property's
        `trailing_12m_adr_cents` as read at delivery time, rounded half up to the cent and
        then capped at 9,000 cents"

        Design: Corner/errors/delivery_invalid_state_fires_on_a_settled_row_and_is_itself_masked_by_the_stay
        """
        bundle = _deliverstate_house_with_two_open_obligations(api)
        owner = make_hotel_owner_headers(bundle["hotel"]["id"])

        delivered = fx.deliver_obligation(
            api, bundle["obligation_b"]["id"], headers=owner
        )

        assert_delivery(
            delivered,
            status="DELIVERED",
            benefit_type="UPGRADE",
            cost_recovery_cents=4_500,
        )

    def test_honouring_the_same_row_twice_is_refused_rather_than_repeated(self, api):
        """A settled obligation is not idempotent: the second attempt is told the row is no
        longer in a state that admits the verb.

        PRD: "Two checks run and their order is fixed: first the obligation's originating
        stay must still be in `POSTED_QUALIFYING`, else `ERR_STAY_INVALID_STATE` — a benefit
        cannot be recorded against a stay that has since been disputed, adjusted or voided;
        then the obligation itself must be in `OBLIGATED`, else
        `ERR_DELIVERY_INVALID_STATE`."

        Design: Corner/errors/delivery_invalid_state_fires_on_a_settled_row_and_is_itself_masked_by_the_stay
        """
        bundle = _deliverstate_house_with_two_open_obligations(api)
        owner = make_hotel_owner_headers(bundle["hotel"]["id"])
        delivery_id = bundle["obligation_b"]["id"]
        fx.deliver_obligation(api, delivery_id, headers=owner)

        validate_error(
            api.deliver_benefit(delivery_id, owner),
            ApiErrorId.ERR_DELIVERY_INVALID_STATE,
        )

    def test_denying_a_row_the_property_already_honoured_hits_the_same_refusal(
        self, api
    ):
        """Delivery and denial are alternatives out of one state, so once one has been taken
        the other is closed off with the same error.

        PRD: "Denial runs three checks in order: the originating stay must still be
        `POSTED_QUALIFYING`, else `ERR_STAY_INVALID_STATE`; the obligation must be
        `OBLIGATED`, else `ERR_DELIVERY_INVALID_STATE`"

        Design: Corner/errors/delivery_invalid_state_fires_on_a_settled_row_and_is_itself_masked_by_the_stay
        """
        bundle = _deliverstate_house_with_two_open_obligations(api)
        owner = make_hotel_owner_headers(bundle["hotel"]["id"])
        delivery_id = bundle["obligation_b"]["id"]
        fx.deliver_obligation(api, delivery_id, headers=owner)

        validate_error(
            api.deny_benefit(
                delivery_id,
                fac.deny_benefit_payload(
                    denial_reason="Changed our minds after the fact."
                ),
                owner,
            ),
            ApiErrorId.ERR_DELIVERY_INVALID_STATE,
        )

    def test_voiding_the_stay_waives_the_obligation_it_created(self, api):
        """The obligation cannot outlive its stay, so the unwind carries the outstanding
        upgrade with it.

        PRD: "every elite benefit obligation whose `stay_id` names this very stay and whose
        `status` is `OBLIGATED` or `ESCALATED` moves to `WAIVED`, because an obligation
        cannot outlive the stay that created it"

        Design: Corner/errors/delivery_invalid_state_fires_on_a_settled_row_and_is_itself_masked_by_the_stay
        """
        bundle = _deliverstate_house_with_two_open_obligations(api)

        voided = fx.void_stay(
            api, bundle["stay_c"]["id"], reason="Charge reversed by the acquirer."
        )

        assert_stay(voided, status="VOID")
        assert_delivery(
            fx.obligation_of_type(api, bundle["stay_c"]["id"], "UPGRADE"),
            status="WAIVED",
            cost_recovery_cents=0,
        )

    def test_the_waived_row_answers_with_its_stays_refusal_and_not_its_own(self, api):
        """Both gates are now closed, and the one that runs first is the stay's, so the same
        shaped request produces a different error identifier.

        PRD: "Two checks run and their order is fixed: first the obligation's originating
        stay must still be in `POSTED_QUALIFYING`, else `ERR_STAY_INVALID_STATE` — a benefit
        cannot be recorded against a stay that has since been disputed, adjusted or voided;
        then the obligation itself must be in `OBLIGATED`, else
        `ERR_DELIVERY_INVALID_STATE`."

        Design: Corner/errors/delivery_invalid_state_fires_on_a_settled_row_and_is_itself_masked_by_the_stay
        """
        bundle = _deliverstate_house_with_two_open_obligations(api)
        owner = make_hotel_owner_headers(bundle["hotel"]["id"])
        fx.void_stay(
            api, bundle["stay_c"]["id"], reason="Charge reversed by the acquirer."
        )

        validate_error(
            api.deliver_benefit(bundle["obligation_c"]["id"], owner),
            ApiErrorId.ERR_STAY_INVALID_STATE,
        )

    def test_the_refusals_leave_the_settled_row_and_the_denial_count_alone(self, api):
        """Two rejected requests wrote nothing: the honoured obligation still carries its
        recovery and no denial was ever recorded against the property.

        PRD: "`DENIED`, `ESCALATED` and `DENIED_FINAL` are all inside the counted set, while
        `DELIVERED`, `WAIVED` and `OBLIGATED` are outside it."

        Design: Corner/errors/delivery_invalid_state_fires_on_a_settled_row_and_is_itself_masked_by_the_stay
        """
        bundle = _deliverstate_house_with_two_open_obligations(api)
        owner = make_hotel_owner_headers(bundle["hotel"]["id"])
        delivery_id = bundle["obligation_b"]["id"]
        fx.deliver_obligation(api, delivery_id, headers=owner)
        api.deliver_benefit(delivery_id, owner)
        api.deny_benefit(
            delivery_id,
            fac.deny_benefit_payload(denial_reason="Changed our minds after the fact."),
            owner,
        )

        settled = fx.obligation_of_type(api, bundle["stay_b"]["id"], "UPGRADE")

        assert_delivery(
            settled, status="DELIVERED", cost_recovery_cents=4_500, denial_reason=None
        )
        assert settled["denial_reason"] is None, (
            "an honoured obligation carries no denial reason after a refused denial"
        )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            benefit_denial_count=0,
            benefit_recovery_owed_cents=4_500,
        )


# ----------------------------------------------------------------------
# The fund is a cash constraint, and the comparison is inclusive.
# ----------------------------------------------------------------------
class TestPayingABatchTheFundCannotCoverIsRefusedUntilCashExactlyMatches:
    def test_a_compression_market_award_accrues_the_undiscounted_nightly_rate(
        self, api
    ):
        """Occupancy of 0.96 is at or above the compression threshold, so two nights accrue
        the full 80,000-cent rate apiece.

        PRD: "When occupancy is at or above 0.95 — compression, the property could certainly
        have sold the room — the rate per night is the full average daily rate, undiscounted."

        Design: Corner/errors/paying_a_batch_the_fund_cannot_cover_is_refused_until_cash_exactly_matches
        """
        bundle = _cashfloor_resort_with_an_approved_batch_the_fund_cannot_cover(api)

        assert_purchase(
            bundle["first_purchase"], status="SETTLED", cash_due_cents=47_500
        )
        assert_redemption(
            bundle["accrued"],
            fulfillment_status="STAYED",
            reimbursement_status="ACCRUED",
            estimated_cents=160_000,
            points_charged=40_000,
            nights=2,
        )

    def test_an_empty_fee_ledger_leaves_the_whole_gross_payable(self, api):
        """One item, nothing owed back in fees, and therefore no surcharge to net off
        whichever band the working figure selects.

        PRD: "Step two: `fee_offset_base_cents` is the property's `fee_ledger_balance_cents`
        as read at release"

        Design: Corner/errors/paying_a_batch_the_fund_cannot_cover_is_refused_until_cash_exactly_matches
        """
        bundle = _cashfloor_resort_with_an_approved_batch_the_fund_cannot_cover(api)

        assert bundle["opened_batch"]["status"] == "OPEN", (
            f"a new batch opens in OPEN, got {bundle['opened_batch']['status']}"
        )
        assert_batch(
            bundle["released_batch"],
            item_count=1,
            gross_cents=160_000,
            fee_offset_base_cents=0,
            surcharge_cents=0,
            total_fee_offset_cents=0,
            net_payable_cents=160_000,
            adr_at_release=80_000,
        )
        assert_batch(
            bundle["approved_batch"], status="APPROVED", net_payable_cents=160_000
        )

    def test_a_disbursement_larger_than_programme_cash_is_refused(self, api):
        """The fund holds only what one guest paid for points, which is a long way short of
        the 160,000 the property is owed.

        PRD: "The fund must be able to cover the disbursement: its `cash_balance_cents` must
        be at least `net_payable_cents`, else `ERR_FUND_INSUFFICIENT_CASH`"

        Design: Corner/errors/paying_a_batch_the_fund_cannot_cover_is_refused_until_cash_exactly_matches
        """
        bundle = _cashfloor_resort_with_an_approved_batch_the_fund_cannot_cover(api)

        validate_error(
            api.pay_batch(bundle["batch_id"], make_admin_headers("op-pay-cf")),
            ApiErrorId.ERR_FUND_INSUFFICIENT_CASH,
        )

    def test_the_refused_disbursement_moves_no_money_and_leaves_the_batch_approved(
        self, api
    ):
        """A refused payment is not a partial payment: the batch is still waiting and the
        fund still holds every cent it held before.

        PRD: "the batch moves `APPROVED → PAID` and its `version` increments. **Hop two:**
        because the batch went paid, every booking whose `batch_id` names it advances
        `reimbursement_status` `BATCHED → PAID`; the fund's `cash_balance_cents` falls by
        `net_payable_cents`"

        Design: Corner/errors/paying_a_batch_the_fund_cannot_cover_is_refused_until_cash_exactly_matches
        """
        bundle = _cashfloor_resort_with_an_approved_batch_the_fund_cannot_cover(api)
        api.pay_batch(bundle["batch_id"], make_admin_headers("op-pay-cf"))

        assert_batch(
            fx.read_batch(api, bundle["batch_id"]),
            status="APPROVED",
            net_payable_cents=160_000,
        )
        assert_fund(fx.read_fund(api), cash_cents=47_500)
        assert_redemption(
            fx.read_redemption(api, bundle["accrued"]["id"]),
            reimbursement_status="BATCHED",
        )

    def test_cash_exactly_equal_to_the_disbursement_is_enough(self, api):
        """Two further sales price at their volume tiers and bring the fund to precisely the
        figure the batch will spend, and the same payment then goes through.

        PRD: "The volume discount is tiered on `points_quantity` alone: twelve percent at
        100,000 points or more, five percent at 25,000 points or more, and nothing below
        that."

        Design: Corner/errors/paying_a_batch_the_fund_cannot_cover_is_refused_until_cash_exactly_matches
        """
        bundle = _cashfloor_resort_with_an_approved_batch_the_fund_cannot_cover(api)
        api.pay_batch(bundle["batch_id"], make_admin_headers("op-pay-cf"))
        topped = _top_the_fund_up_to_the_exact_disbursement(api, bundle["member_id"])

        assert_purchase(topped["big"], status="SETTLED", cash_due_cents=110_000)
        assert_purchase(topped["small"], status="SETTLED", cash_due_cents=2_500)
        assert_fund(fx.read_fund(api), cash_cents=160_000)

        paid = fx.pay_batch(api, bundle["batch_id"], "op-pay-cf")

        assert_batch(paid, status="PAID", net_payable_cents=160_000)

    def test_the_disbursement_drains_the_fund_and_settles_the_booking(self, api):
        """Paying takes the fund to exactly zero, and the booking that justified the
        disbursement reaches the terminal end of its reimbursement dimension.

        PRD: "every booking whose `batch_id` names it advances `reimbursement_status`
        `BATCHED → PAID`; the fund's `cash_balance_cents` falls by `net_payable_cents`"

        Design: Corner/errors/paying_a_batch_the_fund_cannot_cover_is_refused_until_cash_exactly_matches
        """
        bundle = _cashfloor_resort_with_an_approved_batch_the_fund_cannot_cover(api)
        _top_the_fund_up_to_the_exact_disbursement(api, bundle["member_id"])
        fx.pay_batch(api, bundle["batch_id"], "op-pay-cf")

        assert_fund(fx.read_fund(api), cash_cents=0)
        assert_redemption(
            fx.read_redemption(api, bundle["accrued"]["id"]),
            reimbursement_status="PAID",
            settled_cents=160_000,
        )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]), reimbursement_owed_cents=0
        )


# ----------------------------------------------------------------------
# Five refusal classes, one envelope.
# ----------------------------------------------------------------------
def _one_refusal_of_every_class(api, bundle):
    """Five raw responses: a malformed body, an unknown identifier, a repeated activation, a
    reversed date range and a grant the impaired fund will not allow."""
    admin = make_admin_headers()
    hotel_id = bundle["hotel"]["id"]
    member_id = bundle["member_id"]
    untiered = fac.create_hotel_payload(
        name="No Tier Hotel",
        brand_code="NTH",
        program_fee_pct=0.05,
        rooms_count=10,
        trailing_12m_occupancy_pct=0.5,
        trailing_12m_adr_cents=9_000,
    )
    untiered.pop("market_tier", None)

    return {
        "malformed": api.create_hotel(untiered, admin),
        "unknown": api.get_member(_UNKNOWN_MEMBER_ID, admin),
        "repeated": api.activate_hotel(hotel_id, admin),
        "reversed": api.create_stay(
            fac.create_stay_payload(
                member_id,
                hotel_id,
                bundle["rate_plan"]["id"],
                checkin_date="2026-05-10",
                checkout_date="2026-05-04",
                room_revenue_cents=40_000,
            ),
            admin,
        ),
        "unaffordable": api.create_point_adjustment(
            fac.point_adjustment_payload(
                member_id,
                500,
                fx.member_version(api, member_id),
                adjustment_reason="Gesture of goodwill.",
            ),
            admin,
        ),
    }


class TestEveryRefusalClassReturnsTheSameTwoFieldErrorEnvelope:
    def test_ten_thousand_unbacked_points_leave_the_fund_impaired(self, api):
        """The only ledger entry in the programme is an earning, and no cash has ever come
        in, so the ratio is zero and the posture is impaired.

        PRD: "A ratio below 0.7500 yields `IMPAIRED`, and two gates close programme-wide:
        goodwill point grants are refused with `ERR_FUND_IMPAIRED` (HTTP 402)"

        Design: Corner/errors/every_refusal_class_returns_the_same_two_field_error_envelope
        """
        _envelope_arms_with_an_impaired_fund(api)

        fund = validate_success(api.get_program_fund(make_auditor_headers("aud-ev-01")))

        assert_fund(
            fund,
            cash_cents=0,
            outstanding_points=10_000,
            liability_cents=4_800,
            solvency_ratio=0.0,
            status="IMPAIRED",
        )

    def test_each_refusal_class_answers_with_its_own_identifier(self, api):
        """A missing enum, an unknown identifier, a repeated activation, a reversed date range
        and an unaffordable grant are five distinct refusals, not one generic one.

        PRD: "The `error_id` is a unique, machine-readable string that identifies the specific
        error."

        Design: Corner/errors/every_refusal_class_returns_the_same_two_field_error_envelope
        """
        bundle = _envelope_arms_with_an_impaired_fund(api)

        refusals = _one_refusal_of_every_class(api, bundle)

        validate_error(refusals["malformed"], ApiErrorId.ERR_INVALID_REQUEST)
        validate_error(refusals["unknown"], ApiErrorId.ERR_MEMBER_NOT_FOUND)
        validate_error(refusals["repeated"], ApiErrorId.ERR_HOTEL_NOT_ACTIVE)
        validate_error(refusals["reversed"], ApiErrorId.ERR_INVALID_DATE_RANGE)
        validate_error(refusals["unaffordable"], ApiErrorId.ERR_FUND_IMPAIRED)

    def test_the_five_status_codes_are_the_declared_ones(self, api):
        """The same envelope arrives under five different transport statuses, one per refusal
        family.

        PRD: "A violation yields `ERR_INVALID_DATE_RANGE` (HTTP 422) and applies to paid-stay
        capture, award booking, blackout drafting and award price publication."

        Design: Corner/errors/every_refusal_class_returns_the_same_two_field_error_envelope
        """
        bundle = _envelope_arms_with_an_impaired_fund(api)

        refusals = _one_refusal_of_every_class(api, bundle)

        expected = {
            "malformed": 400,
            "unaffordable": 402,
            "unknown": 404,
            "repeated": 409,
            "reversed": 422,
        }
        for key, status in expected.items():
            assert refusals[key].status_code == status, (
                f"the {key} request should refuse with HTTP {status}, got "
                f"{refusals[key].status_code}"
            )

    def test_every_refusal_body_carries_exactly_an_identifier_and_a_message(self, api):
        """No refusal leaks a field list, a partial entity or an identifier of the row it
        would have written.

        PRD: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/errors/every_refusal_class_returns_the_same_two_field_error_envelope
        """
        bundle = _envelope_arms_with_an_impaired_fund(api)

        refusals = _one_refusal_of_every_class(api, bundle)

        for key, response in refusals.items():
            body = response.json()
            assert body["response_type"] == "error", (
                f"the {key} refusal reports response_type {body['response_type']}"
            )
            assert set(body["data"].keys()) == {"error_id", "message"}, (
                f"the {key} refusal carries {sorted(body['data'].keys())} in its data "
                "object, expected exactly error_id and message"
            )

    def test_no_refusal_message_leaks_a_trace_or_an_internal_path(self, api):
        """Each message is a readable sentence rather than a stack frame, a query fragment or
        an internal field path.

        PRD: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/errors/every_refusal_class_returns_the_same_two_field_error_envelope
        """
        bundle = _envelope_arms_with_an_impaired_fund(api)

        refusals = _one_refusal_of_every_class(api, bundle)

        for key, response in refusals.items():
            message = response.json()["data"]["message"]
            assert isinstance(message, str) and message.strip(), (
                f"the {key} refusal carries an empty message"
            )
            for leak in ("Traceback", "SELECT ", "sqlite", "site-packages", 'File "'):
                assert leak not in message, (
                    f"the {key} refusal message leaks {leak!r}: {message}"
                )

    def test_none_of_the_five_refusals_wrote_anything(self, api):
        """One property, one stay and ten thousand points before the refusals, and exactly
        the same afterwards.

        PRD: "and it is refused with `ERR_FUND_IMPAIRED` while the programme fund's `status`
        is `IMPAIRED` — the programme does not hand out points it cannot value."

        Design: Corner/errors/every_refusal_class_returns_the_same_two_field_error_envelope
        """
        bundle = _envelope_arms_with_an_impaired_fund(api)
        _one_refusal_of_every_class(api, bundle)

        _, hotel_meta = validate_paginated(api.list_hotels(make_admin_headers()))
        _, stay_meta = validate_paginated(api.list_stays(make_admin_headers()))

        assert hotel_meta["total_count"] == 1, (
            f"the refused enrolment should not have created a property, total is "
            f"{hotel_meta['total_count']}"
        )
        assert stay_meta["total_count"] == 1, (
            f"the refused capture should not have created a stay, total is "
            f"{stay_meta['total_count']}"
        )
        assert_member(
            fx.read_member(api, bundle["member_id"]),
            point_balance=10_000,
            elite_tier="SILVER",
        )
        assert_stay(
            fx.read_stay(api, bundle["stay"]["id"]),
            status="POSTED_QUALIFYING",
            base_points=10_000,
        )
