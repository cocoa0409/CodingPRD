"""Corner: temporal, resource-constraint, fiscal, vendor-standing, and SoD violations."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_application,
    advance_festival,
    api_client,
    create_application_payload,
    create_assignment,
    create_booth,
    create_festival,
    create_vendor,
    create_zone,
    get_application,
    get_vendor,
    issue_fine,
    make_vendor_headers,
    move_to_settlement_phase,
    pay_fine,
    reconcile_settlement,
    report_sale,
    create_settlement,
    respond_fine,
    setup_accepted_application,
    setup_active_assignment,
    setup_confirmed_assignment,
    setup_curated_with_booth,
    setup_open_festival,
    setup_reconciled_settlement,
    setup_reserved_assignment,
    setup_submitted_application,
    start_review,
    submit_application,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
DIRECTOR2 = TEST_USERS["director2_headers"]
VM = TEST_USERS["vendor_manager_headers"]
OPS = TEST_USERS["ops_headers"]
FIN1 = TEST_USERS["finance_headers"]
FIN2 = TEST_USERS["finance2_headers"]


class TestTemporalViolations:
    def test_transaction_outside_event_window_rejected(self, api):
        """PRD §3.6: "and `occurred_at` must lie within the festival window from
        `event_start` through `event_end`, inclusive at both ends, otherwise
        `ERR_TRANSACTION_OUT_OF_WINDOW` (HTTP 400)."

        Design: Corner/validations/transaction_outside_event_window_rejected
        """
        scen = setup_active_assignment(name="Window Fest")
        resp = api.create_transaction(
            {"assignment_id": scen["assignment"]["id"], "amount_cents": 1000,
             "occurred_at": "2026-07-13T00:00:00Z", "idempotency_key": "ow1"},
            make_vendor_headers(scen["vendor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSACTION_OUT_OF_WINDOW)

    def test_slot_window_inverted_rejected(self, api):
        """PRD §3.5: "the half-open window bounds `window_start` and `window_end` —
        the close must be strictly after the open, otherwise `ERR_INVALID_WINDOW`
        (HTTP 400)".

        Design: Corner/validations/slot_window_inverted_rejected
        """
        festival = create_festival(name="Invert Fest")
        resp = api.create_slot(
            {"festival_id": festival["id"], "gate": "GATE_A",
             "window_start": "2026-07-10T08:00:00Z", "window_end": "2026-07-10T08:00:00Z",
             "max_vehicles": 10},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


class TestResourceConstraints:
    def test_draw_above_outlet_rejected(self, api):
        """PRD §3.3: "The draw may not exceed the booth's `power_outlet_max_amps`
        (`ERR_POWER_DRAW_EXCEEDS_OUTLET`, HTTP 400)".

        Design: Corner/validations/draw_above_outlet_rejected
        """
        scen = setup_open_festival(name="Outlet Fest", zone_power=500)
        vendor = create_vendor(legal_name="Outlet LLC")
        app = submit_application(vendor, scen["festival"]["id"], power_needed_amps=70)
        start_review(app["id"])
        accept_application(app["id"], "FLAT_FEE", flat_fee_cents=50000)
        advance_festival(scen["festival"]["id"], "CURATED")
        booth = create_booth(scen["zone"]["id"], power_outlet_max_amps=60)
        resp = api.create_assignment(
            {"application_id": app["id"], "booth_id": booth["id"],
             "power_draw_amps": 70, "requires_water": False},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_POWER_DRAW_EXCEEDS_OUTLET)

    def test_water_hookup_missing_rejected(self, api):
        """PRD §3.3: "and a water-requiring assignment may not land on a booth
        without a hookup (`ERR_WATER_HOOKUP_UNAVAILABLE`, HTTP 400)".

        Design: Corner/validations/water_hookup_missing_rejected
        """
        scen = setup_open_festival(name="Dry Fest", zone_water=2)
        vendor = create_vendor(legal_name="Dry LLC")
        app = submit_application(vendor, scen["festival"]["id"], requires_water=True)
        start_review(app["id"])
        accept_application(app["id"], "FLAT_FEE", flat_fee_cents=50000)
        advance_festival(scen["festival"]["id"], "CURATED")
        booth = create_booth(scen["zone"]["id"], has_water_hookup=False)
        resp = api.create_assignment(
            {"application_id": app["id"], "booth_id": booth["id"],
             "power_draw_amps": 20, "requires_water": True},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_WATER_HOOKUP_UNAVAILABLE)

    def test_category_exclusivity_conflict_rejected(self, api):
        """PRD §3.3: "Category exclusivity applies within a zone: if any
        assignment in `RESERVED`, `CONFIRMED`, or `ACTIVE` already exists in the
        zone with the application's category, the create is rejected with
        `ERR_CATEGORY_EXCLUSIVITY_CONFLICT`."

        Design: Corner/validations/category_exclusivity_conflict_rejected
        """
        scen = setup_open_festival(name="Exclusive Fest", zone_power=200, zone_water=2)
        fest_id = scen["festival"]["id"]
        va = create_vendor(legal_name="Excl A", contact_email="a@excl.com")
        vb = create_vendor(legal_name="Excl B", contact_email="b@excl.com")
        appa = submit_application(va, fest_id, category="FOOD_HOT")
        appb = submit_application(vb, fest_id, category="FOOD_HOT")
        start_review(appa["id"])
        accept_application(appa["id"], "FLAT_FEE", flat_fee_cents=50000)
        start_review(appb["id"])
        accept_application(appb["id"], "FLAT_FEE", flat_fee_cents=50000)
        advance_festival(fest_id, "CURATED")
        b1 = create_booth(scen["zone"]["id"], label="N-01")
        b2 = create_booth(scen["zone"]["id"], label="N-02")
        create_assignment(appa["id"], b1["id"], power_draw_amps=20)
        resp = api.create_assignment(
            {"application_id": appb["id"], "booth_id": b2["id"],
             "power_draw_amps": 20, "requires_water": False},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_CATEGORY_EXCLUSIVITY_CONFLICT)


class TestFiscalViolations:
    def test_accept_with_incomplete_hybrid_terms_rejected(self, api):
        """PRD §3.2: "acceptance is rejected with `ERR_FEE_TERMS_INCOMPLETE` (HTTP
        400) when the set is incomplete — `FLAT_FEE` requires
        `curated_flat_fee_cents`; `REVENUE_SHARE` requires
        `curated_revenue_share_pct_bp` together with `curated_tier_mode` of
        `MARGINAL` or `WHOLE_TIER`; `HYBRID` requires `curated_flat_fee_cents`,
        `curated_revenue_share_pct_bp`, `curated_minimum_guarantee_cents`, and
        `curated_free_allowance_cents`."

        Design: Corner/validations/accept_with_incomplete_hybrid_terms_rejected
        """
        scen = setup_open_festival(name="Terms Fest")
        vendor = create_vendor(legal_name="Terms LLC")
        app = submit_application(vendor, scen["festival"]["id"], fee_model="HYBRID",
                                 proposed_flat_fee_cents=80000, proposed_revenue_share_pct_bp=1200)
        start_review(app["id"])
        resp = api.decide_application(
            app["id"],
            {"decision": "ACCEPTED", "curated_fee_model": "HYBRID",
             "curated_flat_fee_cents": 80000, "curated_revenue_share_pct_bp": 1200},
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_FEE_TERMS_INCOMPLETE)
        assert get_application(app["id"])["status"] == "UNDER_REVIEW"

    def test_zero_amount_transaction_rejected(self, api):
        """PRD §3.6: "the gross `amount_cents` (at least 1, otherwise
        `ERR_INVALID_AMOUNT`, HTTP 400)".

        Design: Corner/validations/zero_amount_transaction_rejected
        """
        scen = setup_active_assignment(name="Zero Fest")
        resp = api.create_transaction(
            {"assignment_id": scen["assignment"]["id"], "amount_cents": 0,
             "occurred_at": "2026-07-10T14:00:00Z", "idempotency_key": "zero1"},
            make_vendor_headers(scen["vendor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT)


class TestVendorStanding:
    def test_suspended_vendor_submit_rejected(self, api):
        """PRD §3.7: "When a vendor's strike count reaches 3 — exactly three
        suspends; the threshold is inclusive — the vendor moves to `SUSPENDED`".
        PRD §3.2: "submitting as a `SUSPENDED` vendor is rejected with
        `ERR_VENDOR_SUSPENDED`".

        Design: Corner/validations/suspended_vendor_submit_rejected
        """
        scen = setup_reserved_assignment(name="Susp F1")
        asg_id = scen["assignment"]["id"]
        vendor = scen["vendor"]
        for i, ftype in enumerate(["WASTE_SORTING", "GREASE_DISPOSAL", "COMPOST_CONTAMINATION"]):
            fine = issue_fine(asg_id, type=ftype, amount_cents=5000)
            respond_fine(fine["id"], vendor, "ACKNOWLEDGED")
            pay_fine(fine["id"])
        assert get_vendor(vendor["id"])["status"] == "SUSPENDED", "three paid strikes suspend"

        f2 = create_festival(name="Susp F2", event_start="2026-08-01T12:00:00Z",
                             event_end="2026-08-02T23:00:00Z")
        create_zone(f2["id"], name="South")
        advance_festival(f2["id"], "APPLICATIONS_OPEN")
        payload = create_application_payload(vendor["id"], f2["id"], category="DESSERT",
                                             proposed_flat_fee_cents=30000, power_needed_amps=10)
        resp = api.create_application(payload, make_vendor_headers(vendor["id"]))
        validate_error(resp, ApiErrorId.ERR_VENDOR_SUSPENDED)


class TestSegregationOfDuties:
    def test_sod_fine_self_waiver_forbidden(self, api):
        """PRD §2.9: "Waiving a compliance fine requires that the acting
        `FestivalDirector`'s `X-User-ID` differ from the fine's
        `created_by_user_id`, unless the issuer is the literal `system` —
        auto-issued fines may be waived by any director. A self-waiver attempt is
        rejected with `ERR_SOD_FINE_WAIVER` (HTTP 403)."

        Design: Corner/validations/sod_fine_self_waiver_forbidden
        """
        scen = setup_reserved_assignment(name="SoD Fine Fest")
        fine = issue_fine(scen["assignment"]["id"], type="WASTE_SORTING",
                          amount_cents=8000, headers=DIRECTOR)
        assert fine["created_by_user_id"] == "dir-1"

        resp = api.waive_fine(fine["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_SOD_FINE_WAIVER)
        waived = validate_success(api.waive_fine(fine["id"], DIRECTOR2))
        assert waived["status"] == "WAIVED", "a different director may waive"

    def test_sod_settlement_self_finalize_forbidden(self, api):
        """PRD §2.9: "Finalizing a settlement requires that the acting
        `FinanceLead`'s `X-User-ID` differ from the settlement's recorded
        `reconciled_by_user_id`; the same person may not reconcile and finalize
        the same settlement, and a violation is rejected with
        `ERR_SOD_SETTLEMENT_FINALIZE` (HTTP 403)."

        Design: Corner/validations/sod_settlement_self_finalize_forbidden
        """
        scen = setup_reconciled_settlement(sale_amounts=[60000], name="SoD Settle Fest")
        assert scen["settlement"]["reconciled_by_user_id"] == "fin-1"
        move_to_settlement_phase(scen)
        resp = api.finalize_settlement(scen["settlement"]["id"], FIN1)
        validate_error(resp, ApiErrorId.ERR_SOD_SETTLEMENT_FINALIZE)
        finalized = validate_success(api.finalize_settlement(scen["settlement"]["id"], FIN2))
        assert finalized["status"] == "FINALIZED", "a different finance lead may finalize"
