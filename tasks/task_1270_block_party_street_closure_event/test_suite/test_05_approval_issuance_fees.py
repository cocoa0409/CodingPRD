"""Approval gates, issuance fan-out, and the two fee schedules (PRD §3.3, §3.5)."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_application_record,
    create_deposit_record,
    create_insurance_record,
    create_reservation_record,
    create_stock_record,
    create_tcp_record,
    get_application_record,
    make_organizer_headers,
    review_insurance_record,
    review_tcp_record,
    setup_approvable_application,
    setup_draft_application,
    setup_issued_application,
    setup_under_review_application,
    submit_application_record,
    submit_tcp_record,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["permit_officer_headers"]


class TestProvisionalVsFinalFee:
    def _issued_ctx(self, api):
        return setup_issued_application(
            application_overrides={
                "expected_attendance": 100,
                "amplified_sound": True,
                "alcohol_served": False,
            },
            segment_overrides={"length_m": 48},
            tcp_overrides={"barricade_count": 4, "cone_count": 20, "sign_count": 2},
            tcp_before_submit=True,
            sound_overrides={"speaker_count": 4, "max_db_at_property_line": 60,
                             "planned_sound_end": "21:30"},
            stocks=[
                {"equipment_kind": "BARRICADE", "total_units": 10},
                {"equipment_kind": "CONE", "total_units": 30},
                {"equipment_kind": "SIGN", "total_units": 5},
            ],
            reservations=[
                {"equipment_kind": "BARRICADE", "units": 4},
                {"equipment_kind": "CONE", "units": 20},
                {"equipment_kind": "SIGN", "units": 2},
            ],
        )

    def test_provisional_fee_frozen_at_submit(self, api):
        """PRD §3.3: "The fee subtotal starts from a base of 5000 cents ($50.00), adds an
        attendance tier — nothing when `expected_attendance` is 50 or fewer, 4000 cents when
        it falls between 51 and 150 inclusive, and 9000 cents when it exceeds 150 — adds 7500
        cents when `alcohol_served` is true, adds 2500 cents when `amplified_sound` is true,
        and adds 10000 cents when the segment's `jurisdiction` is `STATE_ROUTE`."
        PRD §3.3: "if a traffic control plan exists for the application — in any status —
        its current counts at submit time are priced at 250 cents per barricade, 25 cents per
        cone, and 100 cents per sign; with no plan, the allowance is zero."
        PRD §3.3: "The provisional figure is deliberately plain: it never includes tax, never
        includes the large-event discount, and never includes the administrative surcharge."

        Design: Difficulty/dual_variant_calc/permit_fee_provisional_vs_final_diverge
        """
        # TCP drafted while the application is DRAFT so the estimate sees its counts.
        ctx = setup_draft_application(
            application_overrides={"expected_attendance": 100, "amplified_sound": True},
            segment_overrides={"length_m": 48},
        )
        app, organizer = ctx["application"], ctx["organizer"]
        create_tcp_record(app, organizer, barricade_count=4, cone_count=20, sign_count=2)
        submitted = submit_application_record(app, organizer)
        # fee_subtotal 5000 + 4000 (tier 51-150) + 2500 (sound) = 11500;
        # plan estimate 4*250 + 20*25 + 2*100 = 1700.
        assert submitted["provisional_fee_cents"] == 13200

    def test_final_fee_diverges_at_issue(self, api):
        """PRD §3.5: "Third, the large-event test: if the fee subtotal plus that deposit
        requirement exceeds 20000 cents — evaluated strictly, on the pre-discount subtotal —
        the fee is discounted by ten percent, the product rounded half up to whole cents;
        otherwise the fee stands undiscounted. Fourth, an administrative surcharge of three
        percent of the discounted fee, rounded half up, is added — the surcharge applies to
        the fee alone, never to equipment or the deposit."
        PRD §3.3: "The provisional figure is deliberately plain: it never includes tax, never
        includes the large-event discount, and never includes the administrative surcharge."

        Design: Difficulty/dual_variant_calc/permit_fee_provisional_vs_final_diverge
        """
        ctx = self._issued_ctx(api)
        app = ctx["application"]
        assert app["status"] == "ISSUED"
        assert app["provisional_fee_cents"] == 13200
        # Discount: 11500 + 10000 > 20000 -> 10350; surcharge round_half_up(310.5) = 311;
        # equipment 1083 + 541 + 217 = 1841 (per-line tax).
        assert app["equipment_total_cents"] == 1841
        assert app["final_fee_cents"] == 12502
        assert app["provisional_fee_cents"] != app["final_fee_cents"]


class TestTieredFeeDiscountAndSurchargeOrder:
    def _issued_ctx(self, api):
        return setup_issued_application(
            segment_overrides={
                "jurisdiction": "STATE_ROUTE",
                "segment_kind": "MIXED_USE",
                "household_count": 2,
                "business_count": 2,
                "length_m": 12,
            },
            signatures=[
                {"household_address": "7 State Rd", "signer_name": "U One", "signer_email": "u1@example.com"},
                {"household_address": "7 State Rd", "signer_name": "U Two", "signer_email": "u2@example.com"},
                {"household_address": "9 State Rd", "signer_name": "U Three",
                 "signer_email": "u3@example.com", "is_business": True},
            ],
            application_overrides={
                "event_start_at": "2026-07-20T14:00:00Z",
                "event_end_at": "2026-07-20T22:00:00Z",
                "expected_attendance": 200,
                "amplified_sound": False,
                "alcohol_served": True,
                "food_vendors": True,
            },
            tcp_overrides={"barricade_count": 1, "cone_count": 0, "sign_count": 0},
            tcp_before_submit=True,
            insurance_overrides={"coverage_amount_cents": 150000000, "expires_on": "2027-01-01"},
            stocks=[{"equipment_kind": "BARRICADE", "total_units": 5}],
            reservations=[{"equipment_kind": "BARRICADE", "units": 1}],
        )

    def test_provisional_threshold_and_deposit_inputs(self, api):
        """PRD §3.2: "on a `RESIDENTIAL` segment the threshold is 60 percent of the segment's
        `household_count` rounded up to a whole number, while on a `MIXED_USE` segment it is
        60 percent of `household_count` plus 50 percent of `business_count`, the sum rounded
        up to a whole number."
        PRD §3.7: "Its `required_cents` are computed at creation from the application's
        fields: a base of 10000 cents, plus 15000 cents when `expected_attendance` exceeds
        150, plus 20000 cents when `alcohol_served` is true."

        Design: Difficulty/combinatorial_formula/tiered_fee_discount_and_surcharge_order
        """
        ctx = self._issued_ctx(api)
        petition = ctx["petition"]
        # ceil(0.6*2 + 0.5*2) = ceil(2.2) = 3; SIGNATURE_COUNT let the two same-address
        # signatures count twice, so the petition verified with only 2 distinct addresses.
        assert petition["required_signatures"] == 3
        assert petition["support_mode"] == "SIGNATURE_COUNT"
        assert petition["status"] == "LOCKED", "petition locks at issuance"
        assert ctx["application"]["provisional_fee_cents"] == 31750, (
            "5000 + 9000 tier3 + 7500 alcohol + 10000 STATE_ROUTE + 250 plan estimate"
        )
        assert ctx["deposit"]["required_cents"] == 45000, "10000 + 15000 crowd + 20000 alcohol"

    def test_final_fee_pinned_evaluation_order(self, api):
        """PRD §3.5: "Third, the large-event test: if the fee subtotal plus that deposit
        requirement exceeds 20000 cents — evaluated strictly, on the pre-discount subtotal —
        the fee is discounted by ten percent, the product rounded half up to whole cents;
        otherwise the fee stands undiscounted. Fourth, an administrative surcharge of three
        percent of the discounted fee, rounded half up, is added — the surcharge applies to
        the fee alone, never to equipment or the deposit."

        Design: Difficulty/combinatorial_formula/tiered_fee_discount_and_surcharge_order
        """
        ctx = self._issued_ctx(api)
        app = ctx["application"]
        # 31500 + 45000 > 20000 -> discount 28350; surcharge round_half_up(850.5) = 851;
        # equipment line 250 + round_half_up(20.625)=21 -> 271.
        assert app["equipment_total_cents"] == 271
        assert app["final_fee_cents"] == 29472


class TestPerLineTaxRounding:
    def _issued_ctx(self, api):
        return setup_issued_application(
            application_overrides={"expected_attendance": 30},
            segment_overrides={"length_m": 12},
            tcp_overrides={"barricade_count": 1, "cone_count": 13, "sign_count": 0},
            stocks=[
                {"equipment_kind": "BARRICADE", "total_units": 5},
                {"equipment_kind": "CONE", "total_units": 20},
            ],
            reservations=[
                {"equipment_kind": "BARRICADE", "units": 1},
                {"equipment_kind": "CONE", "units": 9},
                {"equipment_kind": "CONE", "units": 4},
            ],
        )

    def test_per_line_invoices_and_equipment_total(self, api):
        """PRD §3.5: "for each reservation line the pretax amount is `units` multiplied by
        the kind's unit rate (250 cents per barricade, 25 per cone, 100 per sign), the line's
        tax is that pretax amount multiplied by 8.25 percent and rounded half up to whole
        cents, and `invoice_cents` is pretax plus tax."
        PRD §3.5: "Tax is rounded per line and only then summed — the alternative order of
        summing pretax across lines and taxing the total once is expressly rejected, because
        the two orders diverge by cents on common unit mixes."

        Design: Difficulty/combinatorial_formula/per_line_tax_rounding_beats_sum_first
        """
        ctx = self._issued_ctx(api)
        organizer = ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        invoices = []
        for reservation in ctx["reservations"]:
            current = validate_success(api.get_equipment_reservation(reservation["id"], headers), 200)
            assert current["reservation_status"] == "CONFIRMED"
            assert current["billing_status"] == "INVOICED"
            invoices.append(current["invoice_cents"])
        # BARRICADE 1: 250 + 21 = 271; CONE 9: 225 + 19 = 244; CONE 4: 100 + 8 = 108.
        assert sorted(invoices) == [108, 244, 271]
        assert ctx["application"]["equipment_total_cents"] == 623, (
            "per-line order yields 623; the rejected sum-first order would yield 622"
        )

    def test_final_fee_uses_equipment_total_without_discount(self, api):
        """PRD §3.5: "Third, the large-event test: if the fee subtotal plus that deposit
        requirement exceeds 20000 cents — evaluated strictly, on the pre-discount subtotal —
        the fee is discounted by ten percent, the product rounded half up to whole cents;
        otherwise the fee stands undiscounted."
        PRD §3.5: "Sixth and finally, `final_fee_cents` is the discounted fee plus the
        surcharge plus `equipment_total_cents`."

        Design: Difficulty/combinatorial_formula/per_line_tax_rounding_beats_sum_first
        """
        ctx = self._issued_ctx(api)
        # 5000 + 10000 <= 20000 -> no discount; surcharge round_half_up(5000*0.03) = 150.
        assert ctx["application"]["final_fee_cents"] == 5773


class TestApproveGates:
    def test_approve_blocked_without_deposit(self, api):
        """PRD §3.5: "and a deposit must exist in `HELD` (else `ERR_DEPOSIT_REQUIRED`)."

        Design: Difficulty/cross_entity_state_dependency/approve_gated_by_deposit_state
        """
        # Recipe setup: 1 BARRICADE reservation covering the plan — but NO deposit.
        ctx = setup_approvable_application(
            with_deposit=False,
            stocks=[{"equipment_kind": "BARRICADE", "total_units": 5}],
            reservations=[{"equipment_kind": "BARRICADE", "units": 1}],
        )
        app = ctx["application"]
        res = api.approve_permit_application(app["id"], OFFICER)
        validate_error(res, "ERR_DEPOSIT_REQUIRED")
        current = get_application_record(app["id"], ctx["organizer"])
        assert current["status"] == "UNDER_REVIEW"

    def test_approve_succeeds_once_deposit_held(self, api):
        """PRD §3.5: "and a deposit must exist in `HELD` (else `ERR_DEPOSIT_REQUIRED`).
        All six green moves the application to `APPROVED`."
        PRD §3.7: "Its `required_cents` are computed at creation from the application's
        fields: a base of 10000 cents, plus 15000 cents when `expected_attendance` exceeds
        150, plus 20000 cents when `alcohol_served` is true."

        Design: Difficulty/cross_entity_state_dependency/approve_gated_by_deposit_state
        """
        ctx = setup_approvable_application(
            with_deposit=False,
            stocks=[{"equipment_kind": "BARRICADE", "total_units": 5}],
            reservations=[{"equipment_kind": "BARRICADE", "units": 1}],
        )
        app, organizer = ctx["application"], ctx["organizer"]
        deposit = create_deposit_record(app, organizer)
        assert deposit["status"] == "HELD"
        assert deposit["required_cents"] == 10000, "attendance 40, no alcohol -> base only"
        approved = validate_success(api.approve_permit_application(app["id"], OFFICER), 200)
        assert approved["status"] == "APPROVED"

    def test_referential_error_beats_fiscal_on_approve(self, api):
        """PRD §2.6: "the platform evaluates validation classes in a fixed priority order,
        and the earliest failing class determines the error returned."
        PRD §3.5: "The petition is confirmed `VERIFIED` (else `ERR_PETITION_NOT_VERIFIED`);
        the traffic plan must exist in `TCP_APPROVED` (else `ERR_TCP_NOT_APPROVED`)".
        PRD §3.5: "and a deposit must exist in `HELD` (else `ERR_DEPOSIT_REQUIRED`)."

        Design: Difficulty/priority_pair_validation_conflict/referential_error_beats_fiscal_on_approve
        """
        ctx = setup_under_review_application(segment_overrides={"length_m": 12})
        app, organizer = ctx["application"], ctx["organizer"]
        tcp = create_tcp_record(app, organizer, barricade_count=1)
        submit_tcp_record(tcp["id"], organizer)  # SUBMITTED but never reviewed; no deposit.
        res = api.approve_permit_application(app["id"], OFFICER)
        validate_error(res, "ERR_TCP_NOT_APPROVED")
        current = get_application_record(app["id"], organizer)
        assert current["status"] == "UNDER_REVIEW"

    def test_fiscal_gate_fires_once_referential_passes(self, api):
        """PRD §3.5: "The petition is confirmed `VERIFIED` (else `ERR_PETITION_NOT_VERIFIED`);
        the traffic plan must exist in `TCP_APPROVED` (else `ERR_TCP_NOT_APPROVED`); when
        `amplified_sound` is true the sound plan must exist in `SOUND_APPROVED` (else
        `ERR_SOUND_PLAN_NOT_APPROVED`); insurance must be satisfied by a non-superseded
        record in `VERIFIED` or `WAIVER_GRANTED` (else `ERR_INSURANCE_NOT_SATISFIED`);
        equipment coverage must hold — for each kind `BARRICADE`, `CONE`, and `SIGN`, the sum
        of `units` across this application's reservations in `HELD` or `CONFIRMED` must reach
        the traffic plan's planned count for that kind (else `ERR_EQUIPMENT_NOT_RESERVED`);
        and a deposit must exist in `HELD` (else `ERR_DEPOSIT_REQUIRED`)."

        Design: Difficulty/priority_pair_validation_conflict/referential_error_beats_fiscal_on_approve
        """
        ctx = setup_approvable_application(
            with_deposit=False,
            stocks=[{"equipment_kind": "BARRICADE", "total_units": 5}],
            reservations=[{"equipment_kind": "BARRICADE", "units": 1}],
        )
        app = ctx["application"]
        res = api.approve_permit_application(app["id"], OFFICER)
        validate_error(res, "ERR_DEPOSIT_REQUIRED")

    def test_sound_and_insurance_gates_on_approve(self, api):
        """PRD §3.5: "when `amplified_sound` is true the sound plan must exist in
        `SOUND_APPROVED` (else `ERR_SOUND_PLAN_NOT_APPROVED`); insurance must be satisfied by
        a non-superseded record in `VERIFIED` or `WAIVER_GRANTED` (else
        `ERR_INSURANCE_NOT_SATISFIED`)".

        Design: Corner/validations/sound_gate_and_insurance_gate_on_approve
        """
        ctx = setup_under_review_application(
            application_overrides={"amplified_sound": True}
        )
        petition, organizer = ctx["petition"], ctx["organizer"]
        # App A: amplified, TCP approved, no sound plan at all.
        tcp_a = create_tcp_record(ctx["application"], organizer, barricade_count=1)
        submit_tcp_record(tcp_a["id"], organizer)
        review_tcp_record(tcp_a["id"], "APPROVE")
        # App B: non-amplified, TCP approved, no insurance record.
        app_b = create_application_record(
            petition, organizer,
            event_start_at="2026-06-27T14:00:00Z", event_end_at="2026-06-27T22:00:00Z",
        )
        app_b = submit_application_record(app_b, organizer)
        tcp_b = create_tcp_record(app_b, organizer, barricade_count=1)
        submit_tcp_record(tcp_b["id"], organizer)
        review_tcp_record(tcp_b["id"], "APPROVE")

        res = api.approve_permit_application(ctx["application"]["id"], OFFICER)
        validate_error(res, "ERR_SOUND_PLAN_NOT_APPROVED")
        res = api.approve_permit_application(app_b["id"], OFFICER)
        validate_error(res, "ERR_INSURANCE_NOT_SATISFIED")

    def test_equipment_coverage_gap_rejected(self, api):
        """PRD §3.5: "equipment coverage must hold — for each kind `BARRICADE`, `CONE`, and
        `SIGN`, the sum of `units` across this application's reservations in `HELD` or
        `CONFIRMED` must reach the traffic plan's planned count for that kind (else
        `ERR_EQUIPMENT_NOT_RESERVED`)".

        Design: Corner/validations/equipment_coverage_gap_returns_409
        """
        ctx = setup_approvable_application(
            segment_overrides={"length_m": 48},
            tcp_overrides={"barricade_count": 4},
            stocks=[{"equipment_kind": "BARRICADE", "total_units": 10}],
            reservations=[{"equipment_kind": "BARRICADE", "units": 2}],
        )
        res = api.approve_permit_application(ctx["application"]["id"], OFFICER)
        validate_error(res, "ERR_EQUIPMENT_NOT_RESERVED")
        current = get_application_record(ctx["application"]["id"], ctx["organizer"])
        assert current["status"] == "UNDER_REVIEW"


class TestDepositTierAndVersionPinning:
    def test_deposit_required_tier_boundary_150_vs_151(self, api):
        """PRD §3.7: "Its `required_cents` are computed at creation from the application's
        fields: a base of 10000 cents, plus 15000 cents when `expected_attendance` exceeds
        150, plus 20000 cents when `alcohol_served` is true."

        Design: Corner/calculations/deposit_required_tier_boundary_150_vs_151
        """
        ctx = setup_under_review_application(application_overrides={"expected_attendance": 150})
        petition, organizer = ctx["petition"], ctx["organizer"]
        app_b = create_application_record(
            petition, organizer,
            event_start_at="2026-06-27T14:00:00Z", event_end_at="2026-06-27T22:00:00Z",
            expected_attendance=151, alcohol_served=True,
        )
        app_b = submit_application_record(app_b, organizer)
        dep_a = create_deposit_record(ctx["application"], organizer)
        dep_b = create_deposit_record(app_b, organizer)
        assert dep_a["required_cents"] == 10000, "150 does not exceed 150 -> base only"
        assert dep_b["required_cents"] == 45000, "10000 + 15000 crowd + 20000 alcohol"

    def test_plan_version_pinned_and_locked_at_issue(self, api):
        """PRD §3.4: "At permit issuance an approved plan locks: `TCP_APPROVED` becomes
        terminal `LOCKED`, and `locked_at_version` pins the plan's `version` at that instant
        — a field that stays empty until then."
        PRD §3.4: "While the plan is `DRAFT` or `CHANGES_REQUESTED` the organizer may revise
        any of those six fields, each revision incrementing the plan's `version`."

        Design: Corner/cross_cutting_layers/version_pinning_on_issue
        """
        ctx = setup_under_review_application(segment_overrides={"length_m": 12})
        app, organizer = ctx["application"], ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        tcp = create_tcp_record(app, organizer, barricade_count=1)
        validate_success(api.patch_traffic_control_plan(tcp["id"], {"cone_count": 2}, headers), 200)
        submit_tcp_record(tcp["id"], organizer)
        approved_tcp = review_tcp_record(tcp["id"], "APPROVE")

        current = get_application_record(app["id"], organizer)
        insurance = create_insurance_record(app["id"], organizer, current["version"])
        review_insurance_record(insurance["id"], "APPROVE")
        create_stock_record(equipment_kind="BARRICADE", total_units=5)
        create_stock_record(equipment_kind="CONE", total_units=5)
        create_reservation_record(app, organizer, "BARRICADE", 1)
        create_reservation_record(app, organizer, "CONE", 2)
        create_deposit_record(app, organizer)
        validate_success(api.approve_permit_application(app["id"], OFFICER), 200)
        validate_success(api.issue_permit_application(app["id"], OFFICER), 200)

        locked = validate_success(api.get_traffic_control_plan(tcp["id"], headers), 200)
        assert locked["status"] == "LOCKED"
        assert locked["locked_at_version"] == approved_tcp["version"], (
            "locked_at_version pins the version the plan carried when it locked"
        )
        res = api.patch_traffic_control_plan(tcp["id"], {"cone_count": 9}, headers)
        validate_error(res, "ERR_INVALID_STATE")
        locked = validate_success(api.get_traffic_control_plan(tcp["id"], headers), 200)
        assert locked["cone_count"] == 2
