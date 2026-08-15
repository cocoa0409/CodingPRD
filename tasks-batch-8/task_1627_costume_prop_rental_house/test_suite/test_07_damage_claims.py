"""Damage and loss claims: valuation variants, lifecycle, segregation of duties."""
from test_helpers import (
    ApiErrorId,
    acquire_unit,
    apply_credit_note,
    check_in_line,
    create_active_renter,
    create_catalog_item,
    create_confirmed_production,
    create_confirmed_reservation,
    create_pull_list_for,
    dispatch_pull_list,
    generate_invoice,
    get_assessment_for_line,
    get_claim,
    get_item,
    get_line,
    get_pull_list,
    get_unit,
    make_accountant_headers,
    make_renter_contact_headers,
    make_wardrobe_staff_headers,
    pick_all_lines,
    post_claim,
    publish_rate_card,
    set_logical_clock,
    setup_damaged_line_with_claim,
    setup_dispatched_scenario,
    submit_and_get_lines,
    validate_error,
    validate_success,
)

DISPATCH_CLOCK = "2026-08-31T00:00:00Z"
ON_DUE_CLOCK = "2026-09-10T00:00:00Z"


class TestDamageValuationDualVariant:
    def _setup_two_renters(self, api):
        """Identical unit economics for two renters; only their insurance posture differs:
        renter A is covered at/above the item's replacement value, renter B below it."""
        publish_rate_card(api)
        item = create_catalog_item(api, name="Victorian tailcoat")
        acquire_unit(api, item["id"], barcode="BC-001",
                     acquisition_date="2024-08-01", acquisition_cost_cents=60000)
        acquire_unit(api, item["id"], barcode="BC-002",
                     acquisition_date="2024-08-01", acquisition_cost_cents=60000)
        renter_a = create_active_renter(api, name="Renter A", renter_type="THEATRE",
                                        coverage_cents=600000)["renter"]
        renter_b = create_active_renter(api, name="Renter B", renter_type="INDIVIDUAL",
                                        coverage_cents=50000)["renter"]

        claims = {}
        for key, renter in (("a", renter_a), ("b", renter_b)):
            production = create_confirmed_production(
                api, renter, title=f"Prod {key.upper()}", closing_date="2026-09-20",
            )
            create_confirmed_reservation(
                api, production["id"], renter, item["id"], quantity=1,
                window_start_date="2026-09-01", window_end_date="2026-09-10",
            )
            pull_list = create_pull_list_for(api, production["id"], renter)
            _, lines = submit_and_get_lines(api, pull_list["id"])
            pick_all_lines(api, lines)
            dispatch_pull_list(api, pull_list["id"], at=DISPATCH_CLOCK)
            claims[key] = {"line_id": lines[0]["id"], "production": production}

        # Both lines come back on their due date with the same grade drop B -> C.
        set_logical_clock(api, ON_DUE_CLOCK)
        for key in ("a", "b"):
            line = check_in_line(
                api, claims[key]["line_id"],
                condition_grade_after="C", damage_severity="MINOR", staff_id="ws-1",
            )
            assert line["status"] == "DAMAGED"
            assessment = get_assessment_for_line(api, line["id"])
            resp = api.create_claim(
                {"pull_list_line_id": line["id"], "claim_type": "DAMAGE",
                 "return_assessment_id": assessment["id"]},
                make_wardrobe_staff_headers("ws-1"),
            )
            claims[key]["claim"] = validate_success(resp, 201)
        return claims

    def test_agreed_value_when_coverage_meets_replacement(self, api):
        """PRD §3.7: "For `DAMAGE` claims the method is `AGREED_VALUE` when the renter holds
        at least one certificate in `VERIFIED` status whose `coverage_cents` is at least the
        item's `replacement_value_cents` (equal coverage qualifies) and whose `expiry_date`
        is on or after the assessment date" and "`AGREED_VALUE`: the item's
        `replacement_value_cents` times a valuation grade multiplier — 1.00 for grade `A`,
        0.80 for `B`, 0.60 for `C`, 0.40 for `D` — rounded half up."

        Design: Difficulty/dual_variant_calc/damage_valuation_agreed_vs_depreciated
        """
        claims = self._setup_two_renters(api)
        claim_a = claims["a"]["claim"]
        assert claim_a["valuation_method"] == "AGREED_VALUE"
        # 100000 * 0.60 (grade C after) = 60000, independent of cost and age.
        assert claim_a["assessed_value_cents"] == 60000

    def test_depreciated_replacement_when_coverage_below_replacement(self, api):
        """PRD §3.7: "For `DAMAGE` claims the method is `AGREED_VALUE` when the renter holds
        at least one certificate in `VERIFIED` status whose `coverage_cents` is at least the
        item's `replacement_value_cents` (equal coverage qualifies) and whose `expiry_date`
        is on or after the assessment date; otherwise it is `DEPRECIATED_REPLACEMENT`." and
        "`DEPRECIATED_REPLACEMENT`: straight-line depreciation from the unit's
        `acquisition_cost_cents` over a five-year useful life." and "A salvage floor of ten
        percent of the item's `replacement_value_cents` applies: the larger of the raw value
        and the floor is taken, then multiplied by the same valuation grade multiplier, and
        the result is rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/damage_valuation_agreed_vs_depreciated
        """
        claims = self._setup_two_renters(api)
        claim_b = claims["b"]["claim"]
        assert claim_b["valuation_method"] == "DEPRECIATED_REPLACEMENT"
        # Age floor(771/365)=2 years; raw 60000*(1-2/5)=36000 > floor 10000;
        # 36000 * 0.60 = 21600.
        assert claim_b["assessed_value_cents"] == 21600
        # Identical unit economics diverge purely by renter insurance posture.
        assert claims["a"]["claim"]["assessed_value_cents"] != claim_b["assessed_value_cents"]


class TestLossClaims:
    def test_loss_claim_full_replacement_and_grace_fee(self, api):
        """PRD §3.7: "For `LOSS` claims the method short-circuits: the value is always the
        item's full `replacement_value_cents` — a total loss, no grade multiplier."
        PRD §3.6: "Either way the line becomes `LOST`, the unit moves `OUT` → `DISPOSED`,
        `serviceable_unit_count` is recomputed, and the late fee is computed with `late_days`
        fixed at seven — a fixed grace, not an open-ended accrual."

        Design: Corner/calculations/loss_claim_full_replacement_and_grace_fee
        """
        ctx = setup_dispatched_scenario(api, quantity=1, num_units=1)
        set_logical_clock(api, "2026-09-05T00:00:00Z")  # mid-window: no real lateness yet
        line = validate_success(
            api.report_lost(ctx["lines"][0]["id"], make_wardrobe_staff_headers())
        )
        assert line["status"] == "LOST"
        # Fixed 7-day grace fee: 7 * 1000 * 1.00 * 0.10 = 700.
        assert line["late_fee_cents"] == 700

        claim = validate_success(
            api.create_claim(
                {"pull_list_line_id": line["id"], "claim_type": "LOSS"},
                make_wardrobe_staff_headers("ws-1"),
            ),
            201,
        )
        assert claim["assessed_value_cents"] == 100000
        assert get_unit(api, ctx["units"][0]["id"])["status"] == "DISPOSED"
        assert get_item(api, ctx["item"]["id"])["serviceable_unit_count"] == 0

    def test_error_claim_type_mismatch_on_lost_line(self, api):
        """PRD §3.7: "a `DAMAGE` claim requires the line in `DAMAGED` status together with
        its assessment, and a `LOSS` claim requires the line in `LOST` status with
        `return_assessment_id` null; a mismatch is `ERR_CLAIM_TYPE_MISMATCH`."

        Design: Corner/errors/error_claim_type_mismatch_on_lost_line
        """
        ctx = setup_dispatched_scenario(api, quantity=1, num_units=1)
        line = validate_success(
            api.report_lost(ctx["lines"][0]["id"], make_wardrobe_staff_headers())
        )
        assert line["status"] == "LOST"

        resp = api.create_claim(
            {"pull_list_line_id": line["id"], "claim_type": "DAMAGE"},
            make_wardrobe_staff_headers("ws-1"),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_TYPE_MISMATCH, 409)


class TestClaimLifecycle:
    def test_error_claim_already_exists_second_claim_rejected(self, api):
        """PRD §3.7: "Only one claim may exist per line — a second is rejected with
        `ERR_CLAIM_ALREADY_EXISTS`."

        Design: Corner/errors/error_claim_already_exists_second_claim_rejected
        """
        ctx = setup_damaged_line_with_claim(api)
        assert ctx["claim"]["status"] == "DRAFT"

        resp = api.create_claim(
            {"pull_list_line_id": ctx["line"]["id"], "claim_type": "DAMAGE",
             "return_assessment_id": ctx["assessment"]["id"]},
            make_wardrobe_staff_headers("ws-2"),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_EXISTS, 409)

    def test_error_sod_violation_on_self_post(self, api):
        """PRD §3.7: "the posting request is rejected with `ERR_SOD_VIOLATION` (HTTP 403)
        when the poster's `X-User-ID` equals the claim's `created_by_user_id` — the wardrobe
        staff member who assessed the damage may not post its charge."

        Design: Corner/errors/error_sod_violation_on_self_post
        """
        ctx = setup_damaged_line_with_claim(api, staff_id="ws-1")
        claim = ctx["claim"]
        assert claim["created_by_user_id"] == "ws-1"

        resp = api.post_claim(claim["id"], make_accountant_headers("ws-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 403)
        assert get_claim(api, claim["id"])["status"] == "DRAFT"

        posted = post_claim(api, claim["id"], accountant_id="acct-1")
        assert posted["status"] == "POSTED"
        assert posted["posted_by_user_id"] == "acct-1"

    def test_claim_dispute_cycle_and_billed_lock(self, api):
        """PRD §3.7: "The renter may push back: a `RenterContact` disputes a `POSTED` claim
        of their own, moving it to `DISPUTED` — but only while the claim's `invoice_id` is
        still null, because a claim already swept into an invoice cannot be disputed
        (`ERR_CLAIM_ALREADY_BILLED`). From `DISPUTED` the loop continues: an `Accountant`
        may re-post the claim (re-affirming it, with the same segregation-of-duties check)
        or waive it."

        Design: Corner/state_machines/claim_dispute_cycle_and_billed_lock
        """
        ctx = setup_damaged_line_with_claim(api)
        claim = post_claim(api, ctx["claim"]["id"], accountant_id="acct-1")
        assert claim["status"] == "POSTED"

        disputed = validate_success(
            api.dispute_claim(
                claim["id"], make_renter_contact_headers(ctx["renter"]["id"]),
            )
        )
        assert disputed["status"] == "DISPUTED"
        reposted = post_claim(api, claim["id"], accountant_id="acct-1")
        assert reposted["status"] == "POSTED"

        invoice = generate_invoice(api, ctx["production"]["id"])
        # AGREED_VALUE: coverage 600000 >= replacement 100000; grade C multiplier 0.60.
        assert invoice["damage_charges_cents"] == 60000

        resp = api.dispute_claim(
            claim["id"], make_renter_contact_headers(ctx["renter"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_BILLED, 409)
        assert get_claim(api, claim["id"])["invoice_id"] == invoice["id"]

    def test_claim_waived_allows_autoclose_and_invoice_void_on_open(self, api):
        """PRD §3.5: "A dispatched list closes automatically: when every line has reached a
        terminal state (`RETURNED`, `DAMAGED`, or `LOST`), every approved fitting on its
        lines has been restored, and every `DAMAGED` or `LOST` line has a damage claim in
        `POSTED` or `WAIVED` status, the list moves to `CLOSED`".
        PRD §3.8: "A full-total credit note on an `OPEN` invoice is the administrative void
        of an unissued invoice: the invoice becomes `VOID`, and every record swept into it
        becomes unbilled again — `rental_invoiced` and `late_fee_invoiced` back to false on
        lines, `invoiced` back to false on tickets, and `invoice_id` back to null on claims."

        Design: Corner/state_machines/claim_waived_allows_autoclose_and_invoice_void_on_open
        """
        ctx = setup_damaged_line_with_claim(api)
        # The DRAFT claim does not satisfy the auto-close gate.
        assert get_pull_list(api, ctx["pull_list"]["id"])["status"] == "DISPATCHED"

        invoice = generate_invoice(api, ctx["production"]["id"])
        # rental 8000 + late 0 + cleaning 1500; the DRAFT claim is not swept.
        assert invoice["total_cents"] == 9500
        assert invoice["damage_charges_cents"] == 0
        assert invoice["status"] == "OPEN"

        waived = validate_success(
            api.waive_claim(ctx["claim"]["id"], make_accountant_headers())
        )
        assert waived["status"] == "WAIVED"
        # Waiving satisfies the gate; the list closes with no explicit close call.
        assert get_pull_list(api, ctx["pull_list"]["id"])["status"] == "CLOSED"

        voided = apply_credit_note(api, invoice["id"], 9500, reason="goodwill")
        assert voided["status"] == "VOID"
        line_after = get_line(api, ctx["line"]["id"])
        assert line_after["rental_invoiced"] is False
        assert line_after["late_fee_invoiced"] is False
