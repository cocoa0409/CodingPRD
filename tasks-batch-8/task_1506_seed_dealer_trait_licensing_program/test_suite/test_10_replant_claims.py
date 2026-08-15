"""Replant claims: filing rules, segregation of duties, the approval cascade
that spawns replacement orders, and withdrawal/denial paths."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_seed_order,
    create_field_for,
    create_grower,
    create_replant_claim_payload,
    get_success_data,
    make_adjuster_headers,
    make_salesrep_headers,
    set_clock,
    setup_confirmed_order,
    setup_delivered_order,
    setup_filed_claim,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SALESREP = TEST_USERS["salesrep_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


class TestClaimFilingRules:
    def test_replant_claim_window_inclusive_boundary_then_closed(self, api):
        """PRD §3.8: "the claim must be filed no later than
        `replant_claim_window_days` days after the event — the boundary day
        itself remains fileable — otherwise `ERR_REPLANT_WINDOW_CLOSED`."

        Design: Corner/validations/replant_claim_window_inclusive_boundary_then_closed
        """
        ctx = setup_delivered_order(units=10, with_field=True)

        set_clock("2027-05-22T00:00:00Z")  # exactly event_date + 21 days
        claim = validate_success(
            api.create_replant_claim(
                create_replant_claim_payload(
                    ctx["order"]["id"], ctx["line"]["id"], ctx["field"]["id"],
                    event_date="2027-05-01T00:00:00Z", acres_affected=10,
                ),
                SALESREP,
            ),
            expected_status=201,
        )
        assert claim["status"] == "FILED"

        set_clock("2027-05-23T00:00:00Z")  # one day past the boundary
        resp = api.create_replant_claim(
            create_replant_claim_payload(
                ctx["order"]["id"], ctx["line"]["id"], ctx["field"]["id"],
                event_date="2027-05-01T00:00:00Z", acres_affected=5,
            ),
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_REPLANT_WINDOW_CLOSED)

    def test_claim_on_undelivered_line_rejected(self, api):
        """PRD §3.8: "And there must be something to replant: the claimed line
        must hold delivered, unreturned units, otherwise
        `ERR_NO_DELIVERED_UNITS`."

        Design: Corner/validations/claim_on_undelivered_line_rejected
        """
        ctx = setup_confirmed_order(units=10, with_field=True)
        set_clock("2027-05-02T09:00:00Z")
        resp = api.create_replant_claim(
            create_replant_claim_payload(
                ctx["order"]["id"], ctx["line"]["id"], ctx["field"]["id"]
            ),
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_NO_DELIVERED_UNITS)

    def test_claim_with_field_of_different_grower_rejected(self, api):
        """PRD §3.8: "the `field_id` where the stand failed (which must belong
        to the order's grower, otherwise `ERR_FIELD_GROWER_MISMATCH`)".

        Design: Corner/validations/claim_with_field_of_different_grower_rejected
        """
        ctx = setup_delivered_order(units=10)
        other_grower = create_grower(account_name="Jones Ag", external_ref="EXT-002")
        other_field = create_field_for(
            other_grower, name="Jones East", acres=60, soil_type="CLAY",
            drainage="POOR", irrigated=False, prev_crop="CORN", maturity_zone=10,
        )
        set_clock("2027-05-02T09:00:00Z")
        resp = api.create_replant_claim(
            create_replant_claim_payload(
                ctx["order"]["id"], ctx["line"]["id"], other_field["id"]
            ),
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_FIELD_GROWER_MISMATCH)


class TestSegregationOfDuties:
    def test_adjuster_cannot_review_or_decide_own_claim(self, api):
        """PRD §3.8: "starting review (`FILED → UNDER_REVIEW`), requesting more
        information (`UNDER_REVIEW → INFO_REQUESTED`), approving, and denying
        all require that the acting adjuster's `X-User-ID` differ from the
        claim's `filed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/adjuster_cannot_review_or_decide_own_claim
        """
        ctx = setup_delivered_order(units=10, with_field=True)
        set_clock("2027-05-02T09:00:00Z")
        claim = get_success_data(
            api.create_replant_claim(
                create_replant_claim_payload(
                    ctx["order"]["id"], ctx["line"]["id"], ctx["field"]["id"],
                    event_type="DROUGHT",
                ),
                make_adjuster_headers("adj-9"),
            )
        )
        assert claim["filed_by_user_id"] == "adj-9"

        resp = api.start_claim_review(claim["id"], make_adjuster_headers("adj-9"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        get_success_data(api.start_claim_review(claim["id"], make_adjuster_headers("adj-1")))
        resp = api.approve_claim(claim["id"], make_adjuster_headers("adj-9"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        claim_after = validate_success(api.get_replant_claim(claim["id"], ADJUSTER))
        assert claim_after["status"] == "UNDER_REVIEW"


class TestApprovalCascade:
    def _approved_claim_ctx(self, api, acres_affected=25, units=80):
        """Delivered order of `units` on a 100-acre field, plus a claim filed by
        rep-1 and moved to UNDER_REVIEW by adjuster adj-1."""
        ctx = setup_delivered_order(
            units=units, with_field=True,
            lot_overrides={"received_units": 10000},
        )
        ctx = setup_filed_claim(
            ctx=ctx, filer_id="rep-1", acres_affected=acres_affected,
            event_type="FLOOD",
        )
        get_success_data(
            api.start_claim_review(ctx["claim"]["id"], make_adjuster_headers("adj-1"))
        )
        return ctx

    def test_approve_creates_confirmed_free_replacement_order(self, api):
        """PRD §3.8: "a replacement `SeedOrder` is created with `grower_id` and
        `program_id` copied from the original order, `is_replacement` set true,
        and `status` placed directly into `CONFIRMED`, bypassing `DRAFT`".
        PRD §3.8: "the replacement's `payment_status` lands directly on
        `SETTLED` when its `net_amount_cents` is zero, otherwise on `UNPAID`."

        Design: Difficulty/transitive_cascade/replant_approve_cascades_replacement_order_and_lot_reservation
        """
        ctx = self._approved_claim_ctx(api, acres_affected=25, units=80)
        claim = validate_success(
            api.approve_claim(ctx["claim"]["id"], make_adjuster_headers("adj-1"))
        )
        assert claim["status"] == "APPROVED"
        assert claim["replacement_order_id"]

        replacement = validate_success(
            api.get_order(claim["replacement_order_id"], SALESREP)
        )
        assert_seed_order(replacement)
        assert replacement["is_replacement"] is True
        assert replacement["status"] == "CONFIRMED"
        assert replacement["grower_id"] == ctx["grower"]["id"]
        assert replacement["program_id"] == ctx["program"]["id"]
        # min(ceil(25 x 80 / 100), 80) = 20 units; 10000bps replacement discount
        assert replacement["total_units"] == 20
        assert replacement["net_amount_cents"] == 0
        assert replacement["payment_status"] == "SETTLED"

    def test_approve_reserves_replacement_units_on_lot(self, api):
        """PRD §3.8: "the replacement order's confirmation reserves inventory
        through the same selector, setting each line's `inventory_lot_id` and
        `reserved_units` and growing the lot's `reserved_units`".

        Design: Difficulty/transitive_cascade/replant_approve_cascades_replacement_order_and_lot_reservation
        """
        ctx = self._approved_claim_ctx(api, acres_affected=25, units=80)
        lot_before = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
        assert lot_before["reserved_units"] == 0, (
            "the original order's reservation was consumed by its full delivery"
        )

        claim = validate_success(
            api.approve_claim(ctx["claim"]["id"], make_adjuster_headers("adj-1"))
        )
        assert claim["status"] == "APPROVED"
        lot_after = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
        assert lot_after["reserved_units"] == 20


class TestReplacementUnitCeiling:
    def test_replant_replacement_units_ceiling_rounding(self, api):
        """PRD §3.8: "the replacement carries one line per claimed line with the
        same variety, no treatment, and units sized as the smaller of two bounds
        — the claimed `acres_affected` times the original line's `units` divided
        by the field's `acres`, rounded up to a whole unit, and the line's
        delivered-not-returned remainder (`delivered_units` minus
        `returned_units`)".
        PRD §2.6: "the one fractional intermediate — replacement-unit sizing in
        §3.8 — resolves upward via a ceiling, the smallest integer greater than
        or equal to the raw quotient."

        Design: Corner/calculations/replant_replacement_units_ceiling_rounding
        """
        ctx = setup_delivered_order(units=80, with_field=True,
                                    lot_overrides={"received_units": 10000})
        ctx = setup_filed_claim(ctx=ctx, filer_id="rep-1", acres_affected=33,
                                event_type="HAIL")
        get_success_data(
            api.start_claim_review(ctx["claim"]["id"], make_adjuster_headers("adj-1"))
        )
        claim = validate_success(
            api.approve_claim(ctx["claim"]["id"], make_adjuster_headers("adj-1"))
        )
        replacement = validate_success(
            api.get_order(claim["replacement_order_id"], SALESREP)
        )
        # ceil(33 x 80 / 100) = ceil(26.4) = 27
        assert replacement["total_units"] == 27


class TestWithdrawal:
    def test_claim_withdraw_then_approve_rejected(self, api):
        """PRD §3.8: "Withdrawal is the filer side's exit — a sales rep, or the
        grower for their own orders' claims — moving a claim from `FILED`,
        `UNDER_REVIEW`, or `INFO_REQUESTED` to `WITHDRAWN`."
        PRD §2.8: "The target resource must be in a state from which the
        requested transition exists (otherwise `ERR_INVALID_STATE_TRANSITION`,
        HTTP 409)".

        Design: Corner/state_machines/claim_withdraw_then_approve_rejected
        """
        ctx = setup_filed_claim(filer_id="rep-1", units=10)
        withdrawn = validate_success(
            api.withdraw_claim(ctx["claim"]["id"], make_salesrep_headers("rep-1"))
        )
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.approve_claim(ctx["claim"]["id"], make_adjuster_headers("adj-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
