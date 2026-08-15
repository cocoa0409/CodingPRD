"""Food-contact compliance letters, shipment, ship-time OCC, and the
quote-versus-invoice dual pricing variant."""
from test_helpers import (
    EST,
    QM,
    api_client,
    assert_compliance_letter,
    current_job_version,
    get_job,
    issue_letter,
    job_chain,
    ship_job,
    validate_error,
    validate_paginated,
)


class TestComplianceLetters:

    def test_compliance_letter_has_no_version_field(self):
        """PRD §2.4: "One entity is deliberately lighter: a
        **ComplianceLetter** is an immutable artifact and carries only `id` and
        `created_at`. It has no `updated_at` and no `version`, because it is
        never modified after issuance."
        PRD §3.7: "The letter takes a `letter_type` (only `FOOD_CONTACT`
        exists) and a free-text `body` asserting substrate and recipe
        conformity; the server stamps `issued_at` and links the letter to its
        job via `job_id`."

        Design: Corner/entities/compliance_letter_has_no_version_field
        """
        chain = job_chain(stop_at="PRINTED", account_name="Letter Immut",
                          artwork_code="AW-L1", substrate_code="FC-1",
                          recipe_code="INK-F1", die_code="D-L1",
                          press_code="P-L1", quantity_ordered=1000,
                          food_contact=True)
        letter = issue_letter(chain["job"]["id"])
        assert_compliance_letter(letter)
        assert letter["letter_type"] == "FOOD_CONTACT"

        data, _ = validate_paginated(
            api_client.list_compliance_letters(chain["job"]["id"], QM))
        row = next(r for r in data if r["id"] == letter["id"])
        assert "version" not in row, "letter rows carry no version"
        assert "updated_at" not in row, "letter rows carry no updated_at"
        assert row["created_at"]
        assert row["issued_at"]

    def test_letter_while_on_press_rejected(self):
        """PRD §3.7: "For food-contact work, a `QualityManager` issues the
        compliance letter once the job is `PRINTED` or `REWOUND`; in any other
        state the request is rejected with `ERR_JOB_NOT_READY_FOR_LETTER`."

        Design: Corner/state_machines/letter_while_on_press_rejected
        """
        chain = job_chain(stop_at="ON_PRESS", account_name="Early Letter Co",
                          artwork_code="AW-EL", substrate_code="FC-5",
                          recipe_code="INK-F5", die_code="D-EL",
                          press_code="P-EL", quantity_ordered=1000,
                          food_contact=True)
        resp = api_client.issue_compliance_letter(
            chain["job"]["id"],
            {"letter_type": "FOOD_CONTACT", "body": "Too early."}, QM)
        validate_error(resp, "ERR_JOB_NOT_READY_FOR_LETTER",
                       expected_status=409)

    def test_duplicate_letter_rejected(self):
        """PRD §3.7: "One such letter per job: a second `FOOD_CONTACT` letter
        is rejected with `ERR_DUPLICATE_LETTER`."

        Design: Corner/state_machines/duplicate_letter_rejected
        """
        chain = job_chain(stop_at="PRINTED", account_name="Dup Co",
                          artwork_code="AW-D", substrate_code="FC-4",
                          recipe_code="INK-F4", die_code="D-D",
                          press_code="P-D", quantity_ordered=1000,
                          food_contact=True)
        job_id = chain["job"]["id"]
        issue_letter(job_id, body="First letter.")

        resp = api_client.issue_compliance_letter(
            job_id, {"letter_type": "FOOD_CONTACT",
                     "body": "Second letter attempt."}, QM)
        validate_error(resp, "ERR_DUPLICATE_LETTER", expected_status=409)

    def test_ship_without_letter_rejected_when_required(self):
        """PRD §3.7: "Shipment is the final act, performed by a
        `QualityManager`. The job must be `REWOUND` (`ERR_JOB_NOT_REWOUND`); a
        job flagged `requires_food_contact_letter` cannot ship until its
        `FOOD_CONTACT` letter exists (`ERR_COMPLIANCE_LETTER_MISSING`); and the
        request must carry `expected_job_version` matching the job's current
        `version`, rejected as `ERR_STALE_VERSION` on mismatch per §2.8."

        Design: Corner/state_machines/ship_without_letter_rejected_when_required
        """
        chain = job_chain(stop_at="REWOUND", account_name="NoLetter Co",
                          artwork_code="AW-NL", substrate_code="FC-2",
                          recipe_code="INK-F2", die_code="D-NL",
                          press_code="P-NL", quantity_ordered=1000,
                          food_contact=True)
        job_id = chain["job"]["id"]
        resp = api_client.ship_job(
            job_id, {"expected_job_version": current_job_version(job_id)}, QM)
        validate_error(resp, "ERR_COMPLIANCE_LETTER_MISSING",
                       expected_status=422)
        assert get_job(job_id)["status"] == "REWOUND"

    def test_letter_issued_then_ship_succeeds(self):
        """PRD §3.7: "For food-contact work, a `QualityManager` issues the
        compliance letter once the job is `PRINTED` or `REWOUND`; in any other
        state the request is rejected with `ERR_JOB_NOT_READY_FOR_LETTER`."
        PRD §3.7: "The job must be `REWOUND` (`ERR_JOB_NOT_REWOUND`); a job
        flagged `requires_food_contact_letter` cannot ship until its
        `FOOD_CONTACT` letter exists (`ERR_COMPLIANCE_LETTER_MISSING`); and the
        request must carry `expected_job_version` matching the job's current
        `version`, rejected as `ERR_STALE_VERSION` on mismatch per §2.8."
        PRD §3.7: "The job moves `REWOUND` → `SHIPPED`, a terminal state."

        Design: Corner/state_machines/letter_issued_then_ship_succeeds
        """
        chain = job_chain(stop_at="REWOUND", account_name="Letter Co",
                          artwork_code="AW-L2", substrate_code="FC-3",
                          recipe_code="INK-F3", die_code="D-L2",
                          press_code="P-L2", quantity_ordered=1000,
                          food_contact=True)
        job_id = chain["job"]["id"]
        letter = issue_letter(job_id)
        assert letter["letter_type"] == "FOOD_CONTACT"

        shipped = ship_job(job_id, current_job_version(job_id))
        assert shipped["status"] == "SHIPPED"
        # good 1000: base 4500 + material 10640 + ink 68 + plates 120000
        assert shipped["invoiced_price_cents"] == 135208


class TestShippedTerminalAndOcc:

    def test_cancel_shipped_job_rejected(self):
        """PRD §3.8: "Until a job goes on press, an `Estimator` may cancel it:
        cancellation is permitted from `QUOTED`, `APPROVED` or `RELEASED`, and
        from any other state it is rejected with `ERR_JOB_NOT_CANCELLABLE`."
        PRD §3.8: "`CANCELLED` is terminal, alongside `SHIPPED`."

        Design: Corner/state_machines/cancel_shipped_job_rejected
        """
        chain = job_chain(stop_at="SHIPPED", account_name="Shipped Co",
                          artwork_code="AW-SH", substrate_code="SH-1",
                          recipe_code="INK-SH", die_code="D-SH",
                          press_code="P-SH", quantity_ordered=1000)
        job_id = chain["job"]["id"]
        resp = api_client.cancel_job(job_id, EST)
        validate_error(resp, "ERR_JOB_NOT_CANCELLABLE", expected_status=409)

        job = get_job(job_id)
        assert job["status"] == "SHIPPED"
        assert job["invoiced_price_cents"] == 135208, \
            "the frozen invoice survives the rejected cancellation"

    def test_ship_with_stale_job_version_returns_412(self):
        """PRD §2.8: "**Shipping a job** requires the request body to carry
        `expected_job_version`, holding the job's `version` as the shipper last
        observed it. If the job's current `version` has advanced since — for
        example because a late rewind-roll judgment or a compliance-letter
        issuance has legitimately mutated the job — the shipment is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/ship_with_stale_job_version_returns_412
        """
        chain = job_chain(stop_at="REWOUND", account_name="OCC Ship Co",
                          artwork_code="AW-OC", substrate_code="OC-1",
                          recipe_code="INK-OC", die_code="D-OC",
                          press_code="P-OC", quantity_ordered=1000)
        job_id = chain["job"]["id"]
        observed = current_job_version(job_id)

        stale = api_client.ship_job(
            job_id, {"expected_job_version": observed - 1}, QM)
        validate_error(stale, "ERR_STALE_VERSION", expected_status=412)

        shipped = ship_job(job_id, observed)
        assert shipped["status"] == "SHIPPED", \
            "retry with the observed current version succeeds"


class TestQuoteVersusInvoice:

    def _reference_chain(self, account_name: str):
        """qty 4000 ordered / 6000 good; shelf die; one accepted roll."""
        return job_chain(
            stop_at="REWOUND", account_name=account_name,
            artwork_code="AW-1", color_count=2, plate_set_cost_cents=120000,
            substrate_code="BOPP-30", width_mm=1000, cost_per_msq_cents=40,
            recipe_code="INK-1", cost_per_lb_cents=300,
            die_mode="shelf", die_code="D-1",
            press_code="P-1", station_count=4, setup_waste_ft=300,
            run_waste_pct_numerator=5,
            quantity_ordered=4000, repeat_length_mm=76,
            good_quantity_produced=6000,
            rewind_max_rolls=3, max_splices_per_roll=2,
            rolls=[{"label_count": 6000, "splice_count": 1}])

    def test_provisional_quote_keys_on_quantity_ordered(self):
        """PRD §3.4: "The first component is the base print charge, priced by
        an average-rate tier table keyed on the full `quantity_ordered` — the
        single applicable rate covers the entire quantity rather than
        accumulating marginally across brackets."
        PRD §3.4: "The provisional `quoted_price_cents` is the sum of base,
        material, ink and plates; the new-die tooling charge is deliberately
        absent from the quote, because only at release does the system know
        whether this job is the die's first use."
        PRD §3.5: "At release the system computes and freezes the job's
        `material_ft` in three steps."

        Design: Difficulty/dual_variant_calc/quote_provisional_vs_invoice_final_pricing
        """
        chain = self._reference_chain("Acme Quote")
        job = chain["job"]
        # provisional variant: qty 4000 -> rate_a base 18000; worst-case
        # footage 1348 (setup waste included) -> material 25475 + ink 162
        assert job["quoted_price_cents"] == 163637
        # release-time material calc: running 998 < 5000 -> setup 300 billed
        assert job["material_ft"] == 1348

    def test_final_invoice_keys_on_good_quantity_produced(self):
        """PRD §3.7: "Shipment prices the invoice on what the customer actually
        receives. The same average-rate tier table as the quote applies —
        4,500, 3,800 or 3,200 cents per thousand across the same brackets —
        but keyed on `good_quantity_produced`, so a run that ships short can
        fall into a lower bracket and re-price at the higher per-thousand rate:
        the invoice is not the quote."
        PRD §3.7: "The final `invoiced_price_cents` is the sum of the base
        charge, the material charge, the ink charge, the artwork's
        `plate_set_cost_cents`, and any `die_charge_applied_cents` billed at
        release; it replaces the provisional quote, and the difference between
        the two figures is the invoice variance. The job moves `REWOUND` →
        `SHIPPED`, a terminal state."

        Design: Difficulty/dual_variant_calc/quote_provisional_vs_invoice_final_pricing
        """
        chain = self._reference_chain("Acme Invoice")
        job_id = chain["job"]["id"]
        shipped = ship_job(job_id, current_job_version(job_id))
        assert shipped["status"] == "SHIPPED"
        # final variant: good 6000 -> rate_b base 22800; released footage 1348
        # -> material 25475 + ink 162 + plates 120000 + die 0
        assert shipped["invoiced_price_cents"] == 168437
        assert shipped["quoted_price_cents"] == 163637, \
            "the provisional quote is preserved, not overwritten"
        assert shipped["invoiced_price_cents"] != shipped["quoted_price_cents"]
