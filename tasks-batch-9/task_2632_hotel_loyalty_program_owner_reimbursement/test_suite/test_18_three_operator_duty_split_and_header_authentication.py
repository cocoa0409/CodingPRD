"""The three separate operators money must pass through on its way out of the programme, and the identity headers a request needs before any of that is even considered.

The batch here carries a soft-demand award stay, so its net payable is the
per-night floor rather than the property's own rate — a small, exact figure
that makes it easy to see that the two refused hand-offs moved no cash at all.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    NO_IDENTITY_HEADERS,
    assert_batch,
    assert_fund,
    assert_hotel,
    assert_member,
    assert_redemption,
    factories as fac,
    fixtures as fx,
    make_admin_headers,
    make_role_without_user_id_headers,
    make_unknown_role_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _dutysplit_inn_with_a_released_batch(api):
    """A property whose one accrued award night has been selected into a released batch.

    Occupancy sits at 0.60, below the soft-demand threshold, so each night
    reimburses at the 3,000-cent floor rather than at half the property's
    4,000-cent average daily rate. Two nights make a 6,000-cent net payable,
    and the release is stamped with the first of three operators.
    """
    bundle = fx.create_active_hotel(
        api,
        name="Dutysplit Inn",
        brand_code="DSI",
        market_tier="SELECT",
        program_fee_pct=0.05,
        rooms_count=40,
        trailing_12m_occupancy_pct=0.60,
        trailing_12m_adr_cents=4_000,
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
        api,
        email="dt1@example.com",
        full_name="Ingrid Solberg",
        enrollment_date="2026-02-09",
    )
    fx.settled_purchase(api, member["id"], 40_000, channel="DIRECT_PURCHASE")
    redemption = fx.accrued_award(api, member["id"], hotel_id, "2026-06-05", "2026-06-07")
    batch = fx.open_batch(api, hotel_id, "2026-06")
    released = fx.release_batch(api, batch["id"], releaser_id="op-sod-a")
    return {
        "hotel_id": hotel_id,
        "member_id": member["id"],
        "redemption_id": redemption["id"],
        "batch_id": batch["id"],
        "released": released,
    }


def _one_enrolled_member_and_nothing_else(api):
    """A single member, so the authentication tests have both a real id and a missing one."""
    member = fx.enroll_member(
        api,
        email="au1@example.com",
        full_name="Elif Yildiz",
        enrollment_date="2026-02-12",
    )
    return {"member_id": member["id"]}


class TestReleasingApprovingAndPayingNeedsThreeDistinctOperators:
    """One batch, three hand-offs, and no operator allowed to make two of them."""

    def test_the_release_stamps_its_operator_and_prices_the_soft_demand_night(self, api):
        """Release selects the accrued night, prices it at the per-night floor and records who did it.

        PRD: "When occupancy is below 0.80 — soft demand, the room might well have gone empty — the rate per night is fifty percent of the average daily rate rounded half up, but never less than 3,000 cents."

        Design: Corner/rbac/releasing_approving_and_paying_a_batch_needs_three_distinct_operators
        """
        bundle = _dutysplit_inn_with_a_released_batch(api)
        assert_batch(
            bundle["released"],
            status="RELEASED",
            item_count=1,
            gross_cents=6_000,
            fee_offset_base_cents=0,
            surcharge_cents=0,
            total_fee_offset_cents=0,
            net_payable_cents=6_000,
            occupancy_at_release=0.60,
            adr_at_release=4_000,
            released_by="op-sod-a",
        )
        assert (
            bundle["released"]["approved_by_user_id"] is None
        ), "no approver may be recorded on a merely released batch"
        assert_redemption(
            fx.read_redemption(api, bundle["redemption_id"]),
            fulfillment_status="STAYED",
            reimbursement_status="BATCHED",
            points_charged=40_000,
            estimated_cents=6_000,
            settled_cents=6_000,
            nights=2,
        )

    def test_approving_as_the_releaser_is_refused(self, api):
        """The operator who chose what to pay may not also approve paying it.

        PRD: "the caller must not be the operator recorded in `released_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`"

        Design: Corner/rbac/releasing_approving_and_paying_a_batch_needs_three_distinct_operators
        """
        bundle = _dutysplit_inn_with_a_released_batch(api)
        validate_error(
            api.approve_batch(bundle["batch_id"], make_admin_headers("op-sod-a")),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )
        assert_batch(
            fx.read_batch(api, bundle["batch_id"]),
            status="RELEASED",
            net_payable_cents=6_000,
            released_by="op-sod-a",
        )
        assert (
            fx.read_batch(api, bundle["batch_id"])["approved_by_user_id"] is None
        ), "a refused approval must not stamp an approver"

    def test_a_second_operator_approves_and_is_recorded(self, api):
        """The approval is not forbidden in itself: a different operator carries it, and no money moves.

        PRD: "Approval moves `RELEASED → APPROVED`, records `approved_by_user_id` from the caller's operator header, increments the `version` and moves no monetary field whatsoever."

        Design: Corner/rbac/releasing_approving_and_paying_a_batch_needs_three_distinct_operators
        """
        bundle = _dutysplit_inn_with_a_released_batch(api)
        approved = validate_success(
            api.approve_batch(bundle["batch_id"], make_admin_headers("op-sod-b"))
        )
        assert_batch(
            approved,
            status="APPROVED",
            item_count=1,
            gross_cents=6_000,
            net_payable_cents=6_000,
            released_by="op-sod-a",
            approved_by="op-sod-b",
        )
        assert_fund(fx.read_fund(api), cash_cents=47_500)

    def test_paying_as_the_releaser_is_refused(self, api):
        """The payer must differ from the releaser as well as from the approver.

        PRD: "The caller must differ from **both** `released_by_user_id` and `approved_by_user_id`, else `ERR_PAYER_CONFLICT` — three distinct operators are required to carry money from selection to cash-out."

        Design: Corner/rbac/releasing_approving_and_paying_a_batch_needs_three_distinct_operators
        """
        bundle = _dutysplit_inn_with_a_released_batch(api)
        fx.approve_batch(api, bundle["batch_id"], approver_id="op-sod-b")
        validate_error(
            api.pay_batch(bundle["batch_id"], make_admin_headers("op-sod-a")),
            ApiErrorId.ERR_PAYER_CONFLICT,
        )
        assert_batch(
            fx.read_batch(api, bundle["batch_id"]),
            status="APPROVED",
            net_payable_cents=6_000,
        )
        assert_fund(fx.read_fund(api), cash_cents=47_500)

    def test_paying_as_the_approver_is_refused_and_nothing_moves(self, api):
        """The approver is the second of the two names the payer must not match.

        PRD: "**Paying an approved batch** is administrator-only, requires the batch to be `APPROVED`, else `ERR_BATCH_INVALID_STATE`, and is the tightest-controlled operation in the programme."

        Design: Corner/rbac/releasing_approving_and_paying_a_batch_needs_three_distinct_operators
        """
        bundle = _dutysplit_inn_with_a_released_batch(api)
        fx.approve_batch(api, bundle["batch_id"], approver_id="op-sod-b")
        validate_error(
            api.pay_batch(bundle["batch_id"], make_admin_headers("op-sod-b")),
            ApiErrorId.ERR_PAYER_CONFLICT,
        )
        assert_redemption(
            fx.read_redemption(api, bundle["redemption_id"]),
            reimbursement_status="BATCHED",
            settled_cents=6_000,
        )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel_id"]),
            status="ACTIVE",
            reimbursement_owed_cents=6_000,
        )
        assert_fund(fx.read_fund(api), cash_cents=47_500)

    def test_a_third_operator_pays_and_the_cash_finally_moves(self, api):
        """With three distinct operators the disbursement completes and programme cash falls by the net payable.

        PRD: "the fund's `cash_balance_cents` falls by `net_payable_cents`, so a negative net payable *increases* programme cash; the property's `reimbursement_owed_cents` is recomputed and drops those bookings, since `PAID` sits outside the owed set"

        Design: Corner/rbac/releasing_approving_and_paying_a_batch_needs_three_distinct_operators
        """
        bundle = _dutysplit_inn_with_a_released_batch(api)
        fx.approve_batch(api, bundle["batch_id"], approver_id="op-sod-b")
        paid = validate_success(
            api.pay_batch(bundle["batch_id"], make_admin_headers("op-sod-c"))
        )
        assert_batch(
            paid,
            status="PAID",
            item_count=1,
            net_payable_cents=6_000,
            released_by="op-sod-a",
            approved_by="op-sod-b",
        )
        assert_fund(fx.read_fund(api), cash_cents=41_500)
        assert_redemption(
            fx.read_redemption(api, bundle["redemption_id"]),
            reimbursement_status="PAID",
            settled_cents=6_000,
        )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel_id"]),
            status="ACTIVE",
            reimbursement_owed_cents=0,
        )


class TestMissingOrUnknownIdentityHeadersAreRejectedFirst:
    """Authentication runs ahead of authorisation, ownership and even existence."""

    def test_a_request_with_no_headers_at_all_is_unauthenticated_not_missing(self, api):
        """The identifier in the path does not exist, but the absent headers are reported first.

        PRD: "If either header is absent, or if `X-User-Role` carries a value outside the five roles the programme recognises, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The five roles are `ProgramAdministrator`, `HotelOwner`, `Member`, `MemberCareAgent`, and `ProgramAuditor`."

        Design: Corner/rbac/missing_or_unknown_identity_headers_are_rejected_before_anything_else
        """
        _one_enrolled_member_and_nothing_else(api)
        validate_error(
            api.get_member(NON_EXISTENT_UUID, NO_IDENTITY_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )

    def test_a_role_outside_the_five_the_programme_recognises_is_unauthenticated(self, api):
        """A confident-looking role that the programme does not know is not merely unauthorised.

        PRD: "**Header authentication** — missing headers or an unrecognised role yield `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_or_unknown_identity_headers_are_rejected_before_anything_else
        """
        _one_enrolled_member_and_nothing_else(api)
        validate_error(
            api.create_hotel(
                fac.create_hotel_payload(
                    name="Ghost Hotel",
                    brand_code="GHT",
                    market_tier="URBAN",
                    program_fee_pct=0.05,
                    rooms_count=10,
                    trailing_12m_occupancy_pct=0.5,
                    trailing_12m_adr_cents=9_000,
                ),
                make_unknown_role_headers("op-ghost-1", role="SuperAdmin"),
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )

    def test_a_recognised_role_without_an_acting_principal_is_unauthenticated(self, api):
        """Both headers are required, so naming a valid role without naming who is acting is not enough.

        PRD: "Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it acts."

        Design: Corner/rbac/missing_or_unknown_identity_headers_are_rejected_before_anything_else
        """
        bundle = _one_enrolled_member_and_nothing_else(api)
        validate_error(
            api.get_member(
                bundle["member_id"], make_role_without_user_id_headers("ProgramAdministrator")
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )
        readable = validate_success(
            api.get_member(bundle["member_id"], make_admin_headers())
        )
        assert_member(
            readable,
            elite_tier="BASE",
            point_balance=0,
            lifetime_points_earned=0,
            version=1,
        )

    def test_every_unauthenticated_refusal_carries_the_bare_error_envelope_and_writes_nothing(
        self, api
    ):
        """Three refusals, three identical two-field bodies, and no property registered by any of them.

        PRD: "**Header authentication** — missing headers or an unrecognised role yield `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_or_unknown_identity_headers_are_rejected_before_anything_else
        """
        bundle = _one_enrolled_member_and_nothing_else(api)
        responses = (
            api.get_member(NON_EXISTENT_UUID, NO_IDENTITY_HEADERS),
            api.create_hotel(
                fac.create_hotel_payload(name="Ghost Hotel", brand_code="GHT"),
                make_unknown_role_headers("op-ghost-1", role="SuperAdmin"),
            ),
            api.get_member(
                bundle["member_id"], make_role_without_user_id_headers("ProgramAdministrator")
            ),
        )
        for response in responses:
            assert response.status_code == 401, (
                "every authentication refusal must answer HTTP 401, got "
                f"{response.status_code}"
            )
            body = response.json()
            assert (
                body["response_type"] == "error"
            ), "an authentication refusal must declare itself an error response"
            assert set(body["data"].keys()) == {"error_id", "message"}, (
                "the error payload must carry exactly the error id and the message, got "
                f"{sorted(body['data'].keys())}"
            )
        _, hotel_meta = validate_paginated(api.list_hotels(make_admin_headers()))
        assert (
            hotel_meta["total_count"] == 0
        ), "no unauthenticated request may have registered a property"
