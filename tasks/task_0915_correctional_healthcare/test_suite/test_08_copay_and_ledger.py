"""The inmate trust account: the exemption short circuit, the funded/indigent fork, the
strict indigency threshold and the running ledger balance."""

from test_helpers import (
    assert_copay_charge,
    assert_ledger_entry,
    assert_money_invariant,
    fixtures as fx,
    validate_paginated,
    validate_success,
)


class TestFundedVersusIndigentVariant:
    def test_funded_patient_pays_the_full_schedule_as_a_charge_entry(self, api, admin_headers):
        """PRD §3.7: "4. **The funded variant** applies when `indigency_snapshot` is false:
        `amount_cents` equals `scheduled_amount_cents` in full, `charge_variant` is `FUNDED`,
        the charge's `status` is `POSTED`, and one ledger entry of type `CHARGE` is appended
        whose `amount_cents` is the negation of the charge amount."
        PRD §3.7: "2. Otherwise `scheduled_amount_cents` is looked up from the co-pay
        schedule: 500 cents for `SICK_CALL`, 300 cents for `NURSE_TRIAGE`, 800 cents for
        `PROVIDER_VISIT`, 1000 cents for `DENTAL`, and 1500 cents for `SPECIALTY_OFFSITE`."

        Design: Difficulty/dual_variant_calc/copay_funded_vs_indigent_lien_variant
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1001", full_name="Alex Rivera", booked_at="2026-05-01T00:00:00Z"
        )
        fx.deposit(inmate["id"], 1000)

        resp = api.create_copay_charge(
            inmate["id"], {"encounter_type": "SICK_CALL"}, admin_headers
        )
        charge = validate_success(resp, 201)
        assert_copay_charge(charge)
        assert charge["charge_variant"] == "FUNDED"
        assert charge["amount_cents"] == 500
        assert charge["status"] == "POSTED"
        assert charge["indigency_snapshot"] is False
        assert fx.read_inmate(inmate["id"])["account_balance_cents"] == 500

    def test_indigent_patient_is_liened_half_the_schedule_and_may_go_negative(
        self, api, admin_headers
    ):
        """PRD §3.7: "5. **The indigent variant** applies when `indigency_snapshot` is true:
        `amount_cents` is 50 percent of `scheduled_amount_cents`, rounded half up to a whole
        number of cents; `charge_variant` is `INDIGENT`; the charge's `status` is `DEBT_LIEN`;
        and one ledger entry of type `LIEN` is appended, again with the negated amount. The
        lien is explicitly allowed to drive the balance negative — care is never refused for
        insufficient funds, the debt simply follows the patient."

        Design: Difficulty/dual_variant_calc/copay_funded_vs_indigent_lien_variant
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1002", full_name="Blair Cortez", booked_at="2026-05-01T00:00:00Z"
        )

        resp = api.create_copay_charge(
            inmate["id"], {"encounter_type": "SICK_CALL"}, admin_headers
        )
        charge = validate_success(resp, 201)
        assert charge["charge_variant"] == "INDIGENT"
        assert charge["amount_cents"] == 250
        assert charge["status"] == "DEBT_LIEN"
        assert charge["indigency_snapshot"] is True

        refreshed = fx.read_inmate(inmate["id"])
        assert refreshed["account_balance_cents"] == -250
        entries = fx.ledger_entries_for(inmate["id"])
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "LIEN"
        assert entries[0]["amount_cents"] == -250
        assert_money_invariant(entries, refreshed)


class TestIndigencyThreshold:
    def test_a_balance_of_exactly_two_hundred_cents_is_not_indigent(self, api, admin_headers):
        """PRD §3.7: "The patient is indigent when their current `account_balance_cents` is
        **strictly less than** 200 cents **and** the peak is likewise strictly less than 200
        cents. A balance of exactly 200 cents is not indigent; 199 cents is."

        Design: Difficulty/boundary_precision_check/indigency_threshold_exactly_200_cents_is_not_indigent
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1150", full_name="Ray Sung", booked_at="2026-05-01T00:00:00Z"
        )
        fx.deposit(inmate["id"], 200, memo="deposit at the threshold")

        charge = validate_success(
            api.create_copay_charge(inmate["id"], {"encounter_type": "SICK_CALL"}, admin_headers),
            201,
        )
        assert charge["charge_variant"] == "FUNDED"
        assert charge["amount_cents"] == 500
        assert fx.read_inmate(inmate["id"])["account_balance_cents"] == -300

    def test_a_balance_of_one_hundred_ninety_nine_cents_is_indigent(self, api, admin_headers):
        """PRD §3.7: "The patient is indigent when their current `account_balance_cents` is
        **strictly less than** 200 cents **and** the peak is likewise strictly less than 200
        cents. A balance of exactly 200 cents is not indigent; 199 cents is."

        Design: Difficulty/boundary_precision_check/indigency_threshold_exactly_200_cents_is_not_indigent
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1151", full_name="Sam Tran", booked_at="2026-05-01T00:00:00Z"
        )
        fx.deposit(inmate["id"], 199, memo="deposit one cent below")

        charge = validate_success(
            api.create_copay_charge(inmate["id"], {"encounter_type": "SICK_CALL"}, admin_headers),
            201,
        )
        assert charge["charge_variant"] == "INDIGENT"
        assert charge["amount_cents"] == 250
        assert fx.read_inmate(inmate["id"])["account_balance_cents"] == -51


class TestPreChargeIndigencyEvaluation:
    def test_indigency_is_evaluated_on_the_ledger_as_it_stands_before_the_charge(
        self, api, admin_headers
    ):
        """PRD §3.7: "Posting a co-pay follows a pinned six-step order, and the order matters
        because the amount depends on indigency, indigency depends on the balance, and the
        charge itself changes the balance. The cycle is cut by evaluating indigency against
        the ledger **as it stands before this charge posts** — never after."
        PRD §3.7: "3. `indigency_snapshot` is then set from the indigency determination
        above, evaluated on the pre-charge ledger."

        Design: Difficulty/combinatorial_formula/copay_indigency_evaluated_on_pre_charge_ledger
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1040", full_name="Frankie Gill", booked_at="2026-05-01T00:00:00Z"
        )
        fx.deposit(inmate["id"], 250, memo="family deposit")
        fx.set_clock("2026-06-05T00:00:00Z")

        charge = validate_success(
            api.create_copay_charge(inmate["id"], {"encounter_type": "SICK_CALL"}, admin_headers),
            201,
        )
        assert charge["indigency_snapshot"] is False
        assert charge["charge_variant"] == "FUNDED"
        assert charge["amount_cents"] == 500, (
            "A post-charge indigency evaluation would have produced 250"
        )
        assert charge["status"] == "POSTED"

    def test_the_thirty_day_lookback_window_excludes_older_entries(self, api, admin_headers):
        """PRD §3.7: "Take the window that begins 30 days before the current clock instant
        and ends at the current clock instant, **closed at both ends**, so an entry created
        exactly 30 days before the clock is still inside it. Collect the `balance_after_cents`
        values of every ledger entry of this inmate created inside that window, again with no
        filter on `entry_type`. The **peak** is the largest of those values; when the window
        contains no entries at all, the inmate's current `account_balance_cents` stands in as
        the peak."

        Design: Difficulty/combinatorial_formula/copay_indigency_evaluated_on_pre_charge_ledger
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1041", full_name="Frankie Gill", booked_at="2026-05-01T00:00:00Z"
        )
        fx.deposit(inmate["id"], 250, memo="family deposit")
        fx.set_clock("2026-06-05T00:00:00Z")
        validate_success(
            api.create_copay_charge(inmate["id"], {"encounter_type": "SICK_CALL"}, admin_headers),
            201,
        )

        refreshed = fx.read_inmate(inmate["id"])
        assert refreshed["account_balance_cents"] == -250
        assert refreshed["indigent_flag"] is True
        assert_money_invariant(fx.ledger_entries_for(inmate["id"]), refreshed)


class TestExemptEncounters:
    def test_exempt_encounter_is_waived_at_zero_and_appends_no_ledger_entry(
        self, api, admin_headers
    ):
        """PRD §3.7: "1. **The exemption test runs first, before any balance is read at
        all.** Six encounter classifications are exempt on public-health and constitutional
        grounds: `MENTAL_HEALTH`, `EMERGENCY`, `COMMUNICABLE_DISEASE`, `CHRONIC_FOLLOWUP`,
        `INTAKE_SCREENING` and `STAFF_INITIATED`. For any of these, `scheduled_amount_cents`
        and `amount_cents` are both 0, `charge_variant` is `EXEMPT`, the charge's `status` is
        created directly as `WAIVED`, `indigency_snapshot` is recorded as false because
        indigency was never evaluated, and **no ledger entry is appended**. Processing stops
        here."
        PRD §3.7: "The same six steps run, the same ledger entry is or is not appended, and
        the inmate's `version` increments by 1 when an entry was appended and is left
        untouched when the charge came out exempt."

        Design: Corner/calculations/copay_exempt_encounter_waived_without_ledger_entry
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2260", full_name="Sia Uddin", booked_at="2026-05-01T00:00:00Z"
        )
        fx.deposit(inmate["id"], 1000)
        assert fx.read_inmate(inmate["id"])["version"] == 2

        charge = validate_success(
            api.create_copay_charge(
                inmate["id"], {"encounter_type": "MENTAL_HEALTH"}, admin_headers
            ),
            201,
        )
        assert charge["charge_variant"] == "EXEMPT"
        assert charge["amount_cents"] == 0
        assert charge["scheduled_amount_cents"] == 0
        assert charge["status"] == "WAIVED"
        assert charge["indigency_snapshot"] is False

        entries = fx.ledger_entries_for(inmate["id"])
        assert len(entries) == 1
        refreshed = fx.read_inmate(inmate["id"])
        assert refreshed["account_balance_cents"] == 1000
        assert refreshed["version"] == 2


class TestLedgerRunningBalance:
    def test_balance_after_cents_is_the_chronological_running_total(self, api, admin_headers):
        """PRD §3.7: "Take every ledger entry for the inmate — with no filter on type, no
        filter on status and no time window whatsoever — sorted by `created_at` ascending,
        breaking ties between entries that share a `created_at` by the order in which the
        server appended them inside the request, earliest append first. Walk that list from a
        running total of zero, adding each entry's `amount_cents` to the running total and
        writing the running total into that entry's `balance_after_cents`. The inmate's
        `account_balance_cents` is the final running total."

        Design: Corner/calculations/ledger_running_balance_after_each_entry
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2280", full_name="Uri Wexler", booked_at="2026-05-01T00:00:00Z"
        )
        first_entry = fx.deposit(inmate["id"], 1000)
        assert_ledger_entry(first_entry)

        charge = validate_success(
            api.create_copay_charge(inmate["id"], {"encounter_type": "SICK_CALL"}, admin_headers),
            201,
        )

        rows, meta = validate_paginated(
            api.list_ledger_entries(admin_headers, params={"inmate_id": inmate["id"]})
        )
        assert meta["total_count"] == 2
        assert rows[0]["id"] == first_entry["id"]
        assert rows[0]["balance_after_cents"] == 1000
        assert rows[1]["entry_type"] == "CHARGE"
        assert rows[1]["amount_cents"] == -500
        assert rows[1]["balance_after_cents"] == 500
        assert rows[1]["source_copay_charge_id"] == charge["id"]

        refreshed = fx.read_inmate(inmate["id"])
        assert refreshed["account_balance_cents"] == 500
        assert_money_invariant(rows, refreshed)
