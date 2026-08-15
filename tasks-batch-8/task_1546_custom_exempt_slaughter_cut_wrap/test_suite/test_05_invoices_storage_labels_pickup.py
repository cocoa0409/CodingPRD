"""Invoice settlement, storage accrual, label compliance, and pickup.

Covers the PROVISIONAL vs FINAL invoice variants, tiered processing with
storage and deposit credit, per-share deposit-credit rounding order, the
200-lb tier boundary, the 7-day free storage window, the custom-exempt resale
label gate, the label/invoice pickup gates, the pickup cascade, the
manager-only storage waiver, and half-open freezer-unit occupancy.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_share,
    assert_invoice,
    assert_invoice_invariants,
    assert_label_record,
    assert_storage_record,
    book_and_confirm,
    create_and_submit_cut_sheet,
    create_capacity_day,
    create_customer,
    finalize_split,
    get_share,
    get_share_invoice,
    get_share_label,
    get_share_storage_record,
    get_success_data,
    make_customer_headers,
    payment_payload,
    process_animal_to_hanging,
    set_logical_clock,
    setup_finalized_single_share,
    setup_ready_share,
    validate_error,
    validate_success,
)

OP = TEST_USERS["operator_headers"]
MGR = TEST_USERS["manager_headers"]


class TestProvisionalVsFinal:
    def _setup_beef_split(self):
        """BEEF animal: live 1200.0, hanging 700.0; two 0.5 shares (c1, c2);
        deposit 15000 paid. Invoice for c1's share: provisional runs on the
        estimated weight 372.0 lb, final on the actual 350.0 lb."""
        c1 = create_customer("Ann Orr", "555-0101", "ann@x.com")
        c2 = create_customer("Bob Venn", "555-0102", "bob@x.com")
        day = create_capacity_day("2026-08-20", 2)
        _appointment, animals = book_and_confirm(c1["id"], day["id"], "BEEF", 1)
        animal = process_animal_to_hanging(animals[0]["id"], "TAG-A1", 1200.0, 700.0)
        s1 = add_share(animal["id"], c1["id"], 0.5, as_customer_id=c1["id"])
        add_share(animal["id"], c2["id"], 0.5, as_customer_id=c1["id"])
        finalize_split(animal["id"])
        return c1, c2, animal, s1

    def test_invoice_provisional_total_uses_estimated_weight(self, api):
        """PRD §3.6: "The quoted figure, `provisional_total_cents`, is computed
        once at creation and never recomputed: it runs the tiered processing
        schedule against the share's `estimated_share_weight_lbs` rather than
        the actual hanging weight, adds the same `slaughter_share_cents`,
        assumes zero storage and zero surcharge, and subtracts the share's
        `deposit_credit_cents`."

        BEEF share 0.5: estimated 1200 * 0.62 * 0.5 = 372.0 lb -> tiered
        200*95 + 172*85 = 33620; slaughter 12000 * 0.5 = 6000; deposit pool
        15000 split evenly -> credit 7500; provisional = 33620 + 6000 - 7500.

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_settlement
        """
        _c1, _c2, _animal, s1 = self._setup_beef_split()
        invoice = get_share_invoice(s1["id"])
        assert_invoice(invoice)
        assert invoice["slaughter_share_cents"] == 6000
        assert invoice["deposit_credit_cents"] == 7500
        assert invoice["provisional_total_cents"] == 32120

    def test_invoice_final_total_uses_actual_hanging_weight(self, api):
        """PRD §3.6: "The live figure, `total_cents`, is the final-variant
        sum: `processing_fee_cents` computed from the share's actual
        `share_hanging_weight_lbs`, plus `slaughter_share_cents`, plus the
        storage component ... plus `surcharge_cents`, minus
        `deposit_credit_cents`."
        PRD §3.6: "Whenever the actual hanging weight differs from the
        estimate, the provisional and final totals diverge."

        BEEF share 0.5 at actual 350.0 lb: tiered 200*95 + 150*85 = 31750;
        total = 31750 + 6000 - 7500 = 30250, diverging from the 32120 quote.

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_settlement
        """
        _c1, _c2, _animal, s1 = self._setup_beef_split()
        invoice = get_share_invoice(s1["id"])
        assert invoice["processing_fee_cents"] == 31750
        assert invoice["total_cents"] == 30250
        assert invoice["provisional_total_cents"] != invoice["total_cents"]
        assert_invoice_invariants(invoice)


class TestTieredProcessingWithStorageAndCredit:
    def _setup_hog_ready_0804(self):
        """HOG 1.0 share, live 600.0 / hanging 500.0, ready 2026-08-04."""
        return setup_ready_share(
            species="HOG", live_weight_lbs=600.0, hanging_weight_lbs=500.0,
            tag_id="TAG-H500",
        )

    def test_invoice_combines_tiered_processing_storage_and_credit(self, api):
        """PRD §3.6: "above the boundary the fee is exactly 200 pounds at the
        first-tier rate plus the excess weight multiplied by the second-tier
        rate, that excess portion rounded half-up to a whole cent."
        PRD §3.5: "The first seven days are free; every day beyond the seventh
        bills at 500 cents."
        PRD §3.6: "the invoice's `storage_cents` accrued as of the current
        instant".

        HOG 500.0 lb: processing 200*85 + 300*75 = 39500; slaughter 6000;
        credit 7500; at 2026-08-15 (11 days stored) storage = 4 * 500 = 2000;
        total = 39500 + 6000 + 2000 - 7500 = 40000.

        Design: Difficulty/combinatorial_formula/invoice_tiered_processing_with_storage_and_credit
        """
        scenario = self._setup_hog_ready_0804()
        set_logical_clock("2026-08-15T00:00:00Z")
        # A payment observes the current instant, recomputing storage first.
        invoice = scenario["invoice"]
        paid = validate_success(
            api.pay_invoice(invoice["id"], payment_payload(40000),
                            make_customer_headers(scenario["customer"]["id"]))
        )
        assert paid["processing_fee_cents"] == 39500
        assert paid["slaughter_share_cents"] == 6000
        assert paid["storage_cents"] == 2000
        assert paid["deposit_credit_cents"] == 7500
        assert paid["total_cents"] == 40000
        # Provisional: estimated 600 * 0.75 * 1.0 = 450.0 lb ->
        # tiered 17000 + 250*75 = 35750; 35750 + 6000 - 7500 = 34250.
        assert paid["provisional_total_cents"] == 34250

    def test_payment_recomputes_storage_and_settles_to_paid(self, api):
        """PRD §3.6: "Before the payment is applied, the invoice's
        `storage_cents` is recomputed as of the current instant under the
        final variant ... `total_cents` and `amount_due_cents` are recomputed
        with it. A payment smaller than the amount due moves the invoice to
        `PARTIALLY_PAID`; a payment covering the full amount due moves it to
        `PAID`".

        Design: Difficulty/combinatorial_formula/invoice_tiered_processing_with_storage_and_credit
        """
        scenario = self._setup_hog_ready_0804()
        set_logical_clock("2026-08-15T00:00:00Z")
        invoice = scenario["invoice"]
        paid = validate_success(
            api.pay_invoice(invoice["id"], payment_payload(40000),
                            make_customer_headers(scenario["customer"]["id"]))
        )
        assert paid["status"] == "PAID"
        assert paid["amount_paid_cents"] == 40000
        assert_invoice_invariants(paid)


class TestDepositCreditRounding:
    def _setup_three_way_split(self):
        """HOG hanging 200.0, deposit 7500 paid, shares 0.333 / 0.333 / 0.334
        in creation order."""
        c1 = create_customer("Ann Orr", "555-0101", "ann@x.com")
        c2 = create_customer("Bob Venn", "555-0102", "bob@x.com")
        c3 = create_customer("Cid Wynn", "555-0103", "cid@x.com")
        day = create_capacity_day("2026-08-20", 1)
        _appointment, animals = book_and_confirm(c1["id"], day["id"], "HOG", 1)
        animal = process_animal_to_hanging(animals[0]["id"], "TAG-H1", 280.0, 200.0)
        s1 = add_share(animal["id"], c1["id"], 0.333, as_customer_id=c1["id"])
        s2 = add_share(animal["id"], c2["id"], 0.333, as_customer_id=c1["id"])
        s3 = add_share(animal["id"], c3["id"], 0.334, as_customer_id=c1["id"])
        finalize_split(animal["id"])
        return s1, s2, s3

    def test_deposit_credit_rounded_per_share_first(self, api):
        """PRD §3.4: "the pool then flows to the animal's shares in creation
        order, each share's `deposit_credit_cents` being the pool multiplied
        by its `share_fraction` rounded half-up to a whole cent per share
        first, and any leftover difference — a cent or two in either
        direction — reconciled afterward onto the largest-fraction share,
        again breaking ties by earliest creation".

        Pool 7500: 0.333 -> 2498, 0.333 -> 2498, 0.334 -> 2505; the +1
        residual is reconciled onto the largest-fraction share -> 2504.

        Design: Difficulty/combinatorial_formula/deposit_credit_per_share_rounding_then_residual
        """
        s1, s2, s3 = self._setup_three_way_split()
        assert get_share_invoice(s1["id"])["deposit_credit_cents"] == 2498
        assert get_share_invoice(s2["id"])["deposit_credit_cents"] == 2498
        assert get_share_invoice(s3["id"])["deposit_credit_cents"] == 2504

    def test_deposit_credit_sums_to_paid_deposit(self, api):
        """PRD §3.4: "so the credits across an animal's shares sum to the pool
        exactly." The animal's pool is the appointment's `deposit_paid_cents`
        divided by `head_count` — here 7500 over one animal.

        Design: Difficulty/combinatorial_formula/deposit_credit_per_share_rounding_then_residual
        """
        s1, s2, s3 = self._setup_three_way_split()
        credits = [
            get_share_invoice(s["id"])["deposit_credit_cents"] for s in (s1, s2, s3)
        ]
        assert sum(credits) == 7500


class TestTierBoundary:
    def test_tier_boundary_above_200lb_uses_marginal_rate(self, api):
        """PRD §3.6: "weight up to and including 200 pounds bills at the
        species' first-tier rate, and any weight above 200 pounds bills at the
        second-tier rate on the excess only."

        HOG: at 200.0 lb the fee is 200 * 85 = 17000; at 201.0 lb it is
        17000 + 1.0 * 75 = 17075 — the marginal rate applies only above 200.

        Design: Corner/calculations/tier_boundary_above_200lb_uses_marginal_rate
        """
        c_a = create_customer("Ann Orr", "555-0101", "ann@x.com")
        c_b = create_customer("Bob Venn", "555-0102", "bob@x.com")
        day = create_capacity_day("2026-08-20", 2)
        _appt_a, animals_a = book_and_confirm(c_a["id"], day["id"], "HOG", 1)
        animal_a = process_animal_to_hanging(animals_a[0]["id"], "TAG-A", 280.0, 200.0)
        s_a = add_share(animal_a["id"], c_a["id"], 1.0, as_customer_id=c_a["id"])
        finalize_split(animal_a["id"])
        _appt_b, animals_b = book_and_confirm(c_b["id"], day["id"], "HOG", 1)
        animal_b = process_animal_to_hanging(animals_b[0]["id"], "TAG-B", 280.0, 201.0)
        s_b = add_share(animal_b["id"], c_b["id"], 1.0, as_customer_id=c_b["id"])
        finalize_split(animal_b["id"])
        assert get_share_invoice(s_a["id"])["processing_fee_cents"] == 17000
        assert get_share_invoice(s_b["id"])["processing_fee_cents"] == 17075


class TestStorageFreeWindow:
    def test_storage_day_seven_is_free(self, api):
        """PRD §3.5: "The first seven days are free; every day beyond the
        seventh bills at 500 cents."

        Ready 2026-08-04; payment observed at 2026-08-11 (days_stored 7):
        storage 0, total 15500 (17000 processing + 6000 slaughter - 7500
        credit), invoice PAID by a 15500 payment.

        Design: Difficulty/boundary_precision_check/storage_free_window_last_free_day_vs_first_billable_day
        """
        scenario = setup_ready_share()
        set_logical_clock("2026-08-11T00:00:00Z")
        invoice = scenario["invoice"]
        paid = validate_success(
            api.pay_invoice(invoice["id"], payment_payload(15500),
                            make_customer_headers(scenario["customer"]["id"]))
        )
        assert paid["storage_cents"] == 0
        assert paid["total_cents"] == 15500
        assert paid["status"] == "PAID"
        assert_invoice_invariants(paid)

    def test_storage_day_eight_first_billable_day(self, api):
        """PRD §3.5: "The first seven days are free; every day beyond the
        seventh bills at 500 cents."

        Ready 2026-08-04; payment observed at 2026-08-12 (days_stored 8):
        storage 500, total 16000, invoice PAID by a 16000 payment.

        Design: Difficulty/boundary_precision_check/storage_free_window_last_free_day_vs_first_billable_day
        """
        scenario = setup_ready_share()
        set_logical_clock("2026-08-12T00:00:00Z")
        invoice = scenario["invoice"]
        paid = validate_success(
            api.pay_invoice(invoice["id"], payment_payload(16000),
                            make_customer_headers(scenario["customer"]["id"]))
        )
        assert paid["storage_cents"] == 500
        assert paid["total_cents"] == 16000
        assert paid["status"] == "PAID"


class TestLabelCompliance:
    def test_resale_label_approve_rejected(self, api):
        """PRD §3.7: "Staff approve the label only when the share's
        `intended_use` is `OWNER_USE` — product labeled not for sale may never
        be resold, and approval for a `RESALE` share is rejected with
        `ERR_RESALE_LABEL_FORBIDDEN`."
        PRD §3.7: "`label_text` computed to begin with the exact string
        `NOT FOR SALE` followed by the owner name and a description of the
        share".

        Design: Corner/validations/resale_label_approve_rejected
        """
        scenario = setup_finalized_single_share(intended_use="RESALE")
        label = scenario["label"]
        assert_label_record(label)
        assert label["label_text"].startswith("NOT FOR SALE")
        resp = api.approve_label(label["id"], OP)
        validate_error(resp, ApiErrorId.ERR_RESALE_LABEL_FORBIDDEN,
                       expected_status=422)
        assert api.get_label(label["id"], OP).json()["data"]["status"] == "PENDING"

    def test_label_double_approve_rejected(self, api):
        """PRD §3.7: "Approval moves the record from `PENDING` to `APPROVED`".
        PRD §2.8: "then state-transition legality including terminal-state
        lockdown (`ERR_INVALID_STATE`, HTTP 409)".

        Design: Corner/state_machines/label_double_approve_rejected
        """
        scenario = setup_finalized_single_share()
        label = scenario["label"]
        first = validate_success(api.approve_label(label["id"], OP))
        assert first["status"] == "APPROVED"
        resp = api.approve_label(label["id"], OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = api.get_label(label["id"], OP).json()["data"]
        assert after["status"] == "APPROVED"
        assert after["version"] == first["version"], (
            "rejected re-approval must not increment the version again"
        )


class TestPickupGates:
    def test_pickup_blocked_until_label_approved(self, api):
        """PRD §3.7: "the share's label must be `APPROVED`, else
        `ERR_LABEL_NOT_APPROVED`".

        Invoice fully paid on the ready day (storage 0), label still PENDING.

        Design: Corner/validations/pickup_blocked_until_label_approved
        """
        scenario = setup_ready_share()
        customer = scenario["customer"]
        paid = validate_success(
            api.pay_invoice(scenario["invoice"]["id"], payment_payload(15500),
                            make_customer_headers(customer["id"]))
        )
        assert paid["status"] == "PAID"
        record = scenario["storage_record"]
        resp = api.pickup_storage_record(record["id"], OP)
        validate_error(resp, ApiErrorId.ERR_LABEL_NOT_APPROVED, expected_status=409)
        assert get_share_storage_record(scenario["share"]["id"])["status"] == "STORED"

    def test_pickup_blocked_until_invoice_paid(self, api):
        """PRD §3.7: "the share's invoice must stand `PAID` after its storage
        has been recomputed as of the pickup instant — unpaid accrual since
        the last payment still blocks the door, surfacing as
        `ERR_INVOICE_NOT_PAID`."

        Label APPROVED, invoice unpaid.

        Design: Corner/validations/pickup_blocked_until_invoice_paid
        """
        scenario = setup_ready_share()
        get_success_data(api.approve_label(scenario["label"]["id"], OP))
        record = scenario["storage_record"]
        resp = api.pickup_storage_record(record["id"], OP)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAID, expected_status=402)
        assert get_share_storage_record(scenario["share"]["id"])["status"] == "STORED"

    def test_pickup_share_cascades_and_double_pickup_rejected(self, api):
        """PRD §3.7: "When both gates pass, the record moves from `STORED` to
        `PICKED_UP`, `picked_up_at` is stamped ... The share cascades from
        `READY` to `PICKED_UP` ... and when every share of the animal has
        reached a terminal state the animal bubbles up from `READY` to
        `COMPLETE`."
        PRD §2.8: "then state-transition legality including terminal-state
        lockdown (`ERR_INVALID_STATE`, HTTP 409)".

        Design: Corner/state_machines/pickup_share_cascades_and_double_pickup_rejected
        """
        scenario = setup_ready_share()
        customer = scenario["customer"]
        get_success_data(api.approve_label(scenario["label"]["id"], OP))
        paid = validate_success(
            api.pay_invoice(scenario["invoice"]["id"], payment_payload(15500),
                            make_customer_headers(customer["id"]))
        )
        assert paid["status"] == "PAID"
        record = scenario["storage_record"]
        picked = validate_success(api.pickup_storage_record(record["id"], OP))
        assert_storage_record(picked)
        assert picked["status"] == "PICKED_UP"
        assert picked["picked_up_at"] is not None
        assert get_share(scenario["share"]["id"])["status"] == "PICKED_UP"
        animal = get_success_data(api.get_animal(scenario["animal"]["id"], OP))
        assert animal["status"] == "COMPLETE", (
            "all shares terminal, so the animal bubbles up to COMPLETE"
        )
        resp = api.pickup_storage_record(record["id"], OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestStorageWaiver:
    def test_operator_cannot_waive_storage_manager_can(self, api):
        """PRD §4: `POST /locker/invoices/{id}/waive-storage` — Authorized
        Role(s): PlantManager.
        PRD §2.1: "A request whose role is not permitted on the targeted
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.6: "waiving sets `storage_waived` to true, and the total and
        amount due are recomputed with the storage component forced to zero."

        Ready 2026-08-04; at 2026-08-13 the record has 9 days stored, 2
        billable -> 1000 accrued. Waiving removes that component:
        17000 + 6000 + 0 - 7500 = 15500.

        Design: Corner/rbac/operator_cannot_waive_storage_manager_can
        """
        scenario = setup_ready_share()
        set_logical_clock("2026-08-13T00:00:00Z")
        invoice = scenario["invoice"]
        resp = api.waive_storage(invoice["id"], OP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        waived = validate_success(api.waive_storage(invoice["id"], MGR))
        assert waived["storage_waived"] is True
        assert waived["total_cents"] == 15500, (
            "the 1000-cent accrued storage component drops out of the total"
        )


class TestFreezerOccupancy:
    def _setup_freezer_full_scenario(self, api):
        """Two BEEF animals (head_count 2, deposit 30000): a1 hanging 400.0
        with four 0.25 shares (owners c1, c2, c1, c2); a2 hanging 200.0 with
        one 1.0 share (owner c3). All sheets submitted; clock at 2026-08-04
        (hang met); a1's fabrication completed, filling all four freezer
        units."""
        c1 = create_customer("Ann Orr", "555-0101", "ann@x.com")
        c2 = create_customer("Bob Venn", "555-0102", "bob@x.com")
        c3 = create_customer("Cid Wynn", "555-0103", "cid@x.com")
        day = create_capacity_day("2026-08-20", 2)
        _appointment, animals = book_and_confirm(c1["id"], day["id"], "BEEF", 2)
        an1, an2 = animals[0]["id"], animals[1]["id"]
        process_animal_to_hanging(an1, "TAG-F1", 1200.0, 400.0)
        shares = [
            add_share(an1, c1["id"], 0.25, as_customer_id=c1["id"]),
            add_share(an1, c2["id"], 0.25, as_customer_id=c1["id"]),
            add_share(an1, c1["id"], 0.25, as_customer_id=c1["id"]),
            add_share(an1, c2["id"], 0.25, as_customer_id=c1["id"]),
        ]
        finalize_split(an1)
        for share in shares:
            create_and_submit_cut_sheet(share["id"], share["owner_customer_id"])
        process_animal_to_hanging(an2, "TAG-F2", 1200.0, 200.0)
        share_b = add_share(an2, c3["id"], 1.0, as_customer_id=c1["id"])
        finalize_split(an2)
        create_and_submit_cut_sheet(share_b["id"], c3["id"])
        set_logical_clock("2026-08-04T00:00:00Z")
        get_success_data(api.start_fabrication(an1, OP))
        get_success_data(api.complete_fabrication(an1, OP))
        get_success_data(api.start_fabrication(an2, OP))
        return {
            "c1": c1, "c2": c2, "c3": c3,
            "an1": an1, "an2": an2,
            "shares": shares, "share_b": share_b,
        }

    def test_complete_fab_rejected_when_freezer_full(self, api):
        """PRD §3.5: "The plant's freezer holds four units; each share
        occupies exactly one unit ... the count of storage records currently
        `STORED` plus the number of this animal's `CONFIRMED` shares must not
        exceed four, else the completion is rejected with
        `ERR_FREEZER_FULL`."

        Four shares already STORED; completing the one-share animal would
        push occupancy to five.

        Design: Difficulty/resource_temporal_overlap/freezer_units_half_open_window_occupancy
        """
        scenario = self._setup_freezer_full_scenario(api)
        resp = api.complete_fabrication(scenario["an2"], OP)
        validate_error(resp, ApiErrorId.ERR_FREEZER_FULL, expected_status=409)
        animal = get_success_data(api.get_animal(scenario["an2"], OP))
        assert animal["status"] == "CUTTING", (
            "rejected completion leaves the animal in CUTTING"
        )

    def test_pickup_frees_unit_for_same_instant_completion(self, api):
        """PRD §3.5: "Occupancy windows are half-open: a record occupies its
        unit from its `ready_at` instant up to but not including its
        `picked_up_at` instant, so a pickup recorded at a given instant frees
        the unit for a share that becomes ready at that same instant."

        s1's invoice: share weight 100.0 lb -> processing 9500; slaughter
        12000 * 0.25 = 3000; pool 30000 / 2 animals = 15000, credit 3750;
        total 8750 at zero storage days. After s1 is paid and picked up at
        2026-08-04, the second animal's completion succeeds at that instant.

        Design: Difficulty/resource_temporal_overlap/freezer_units_half_open_window_occupancy
        """
        scenario = self._setup_freezer_full_scenario(api)
        # First confirm the freezer is full.
        resp = api.complete_fabrication(scenario["an2"], OP)
        validate_error(resp, ApiErrorId.ERR_FREEZER_FULL, expected_status=409)
        s1 = scenario["shares"][0]
        label1 = get_share_label(s1["id"])
        get_success_data(api.approve_label(label1["id"], OP))
        invoice1 = get_share_invoice(s1["id"])
        paid = validate_success(
            api.pay_invoice(invoice1["id"], payment_payload(8750),
                            make_customer_headers(scenario["c1"]["id"]))
        )
        assert paid["total_cents"] == 8750
        assert paid["status"] == "PAID"
        record1 = get_share_storage_record(s1["id"])
        get_success_data(api.pickup_storage_record(record1["id"], OP))
        # The freed unit is immediately available at the same logical instant.
        completed = validate_success(api.complete_fabrication(scenario["an2"], OP))
        assert completed["status"] == "READY"
        record_b = get_share_storage_record(scenario["share_b"]["id"])
        assert record_b["status"] == "STORED"
