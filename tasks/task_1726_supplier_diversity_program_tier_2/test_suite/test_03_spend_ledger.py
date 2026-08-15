"""Spend import ledger: voids, lifetime counters, attribution exclusion,
pagination defaults, and nested certification listing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_net_posted_invariant,
    create_business_unit,
    create_supplier,
    create_supplier_with_verified_cert,
    generate_scorecard,
    get_success_data,
    import_spend,
    submit_certification,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN1 = TEST_USERS["admin_1_headers"]
ANALYST1 = TEST_USERS["analyst_1_headers"]


class TestVoid:
    def test_spend_record_double_void_rejected(self, api):
        """PRD §3.3: "voiding a `POSTED` record moves it to `VOIDED`, adds to
        the voided counter, and bumps the business unit's `version`."
        PRD §2.8: "Fourth, whether the target resource is in a state from
        which the requested transition is defined."

        Design: Corner/state_machines/spend_record_double_void_rejected
        """
        bu = create_business_unit()
        supplier = create_supplier(legal_name="Void Co", tax_id="T-VOID")
        record = import_spend(supplier["id"], bu["id"], 70000,
                              transaction_date="2026-02-01",
                              payment_date="2026-02-10")
        voided = validate_success(api.void_spend_record(record["id"], ANALYST1))
        assert voided["status"] == "VOIDED"
        resp = api.void_spend_record(record["id"], ANALYST1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        bu_after = validate_success(api.get_business_unit(bu["id"], ADMIN1))
        assert bu_after["lifetime_voided_spend_cents"] == 70000, (
            "The voided counter moves exactly once"
        )

    def test_spend_voided_records_excluded_from_attribution(self, api):
        """PRD §3.6: "The input set is the unit's spend records that are
        currently `POSTED` and whose basis date falls inside that range;
        `VOIDED` records are excluded."

        Design: Corner/calculations/spend_voided_records_excluded_from_attribution
        """
        bu = create_business_unit()
        supplier, _cert = create_supplier_with_verified_cert(
            legal_name="Diverse Parts Co", tax_id="T-DP",
            certificate_number="M-DP")
        r1 = import_spend(supplier["id"], bu["id"], 70000,
                          transaction_date="2026-02-01",
                          payment_date="2026-02-01")
        import_spend(supplier["id"], bu["id"], 30000,
                     transaction_date="2026-02-02", payment_date="2026-02-02")
        get_success_data(api.void_spend_record(r1["id"], ANALYST1))
        scorecard = generate_scorecard(bu["id"], reporting_period="2026-Q1",
                                       attribution_basis="ACCRUAL")
        assert scorecard["total_spend_cents"] == 30000, (
            "The VOIDED 70000 record drops out of total_spend_cents"
        )
        assert scorecard["direct_diverse_spend_cents"] == 30000, (
            "The VOIDED record drops out of direct_diverse_spend_cents too"
        )


class TestLifetimeCounterInvariant:
    def test_spend_void_reimport_lifetime_counters(self, api):
        """PRD §3.3: "`lifetime_imported_spend_cents` accumulates
        `amount_cents` over every spend record ever imported for the unit and
        is never decremented. `lifetime_voided_spend_cents` accumulates
        `amount_cents` over every spend record voided for the unit and is
        likewise never decremented."

        Design: Difficulty/compensating_invariant/spend_void_reimport_conserves_net_posted
        """
        bu = create_business_unit()
        supplier = create_supplier(legal_name="Ledger Co", tax_id="T-LED")
        r1 = import_spend(supplier["id"], bu["id"], 100000,
                          transaction_date="2026-02-01",
                          payment_date="2026-02-10")
        voided = validate_success(api.void_spend_record(r1["id"], ANALYST1))
        assert voided["status"] == "VOIDED"
        import_spend(supplier["id"], bu["id"], 100000,
                     transaction_date="2026-02-01", payment_date="2026-02-10")
        bu_after = validate_success(api.get_business_unit(bu["id"], ADMIN1))
        assert bu_after["lifetime_imported_spend_cents"] == 200000, (
            "Both imports counted; the void never decrements the imported "
            "counter"
        )
        assert bu_after["lifetime_voided_spend_cents"] == 100000

    def test_spend_net_posted_invariant_after_void_reimport(self, api):
        """PRD §3.3: "Together they conserve posted spend: the sum of
        `amount_cents` over records currently `POSTED` always equals
        `lifetime_imported_spend_cents` minus `lifetime_voided_spend_cents`."
        PRD §3.3: "Importing a record adds to the imported counter and bumps
        the business unit's `version`; voiding a `POSTED` record moves it to
        `VOIDED`, adds to the voided counter, and bumps the business unit's
        `version`."

        Design: Difficulty/compensating_invariant/spend_void_reimport_conserves_net_posted
        """
        bu = create_business_unit()
        supplier = create_supplier(legal_name="Ledger Co", tax_id="T-LED")
        r1 = import_spend(supplier["id"], bu["id"], 100000,
                          transaction_date="2026-02-01",
                          payment_date="2026-02-10")
        get_success_data(api.void_spend_record(r1["id"], ANALYST1))
        import_spend(supplier["id"], bu["id"], 100000,
                     transaction_date="2026-02-01", payment_date="2026-02-10")
        records, _meta = validate_paginated(api.list_spend_records(ANALYST1))
        posted_sum = sum(r["amount_cents"] for r in records
                         if r["status"] == "POSTED")
        bu_after = validate_success(api.get_business_unit(bu["id"], ADMIN1))
        assert_net_posted_invariant(bu_after, posted_sum)
        assert posted_sum == 100000, (
            "Net posted spend after the void/re-import pair is identical to "
            "the value before it"
        )
        assert bu_after["version"] == 4, (
            "create + import + void + import each mutate the business unit"
        )


class TestListing:
    def test_spend_records_pagination_defaults(self, api):
        """PRD §2.3: "`limit` defaults to 10, must be at least 1, and may not
        exceed 100. `offset` defaults to 0."
        PRD §2.3: "The `meta` block of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/spend_records_pagination_defaults
        """
        bu = create_business_unit()
        supplier = create_supplier(legal_name="Page Co", tax_id="T-PAGE")
        for i in range(6):
            import_spend(supplier["id"], bu["id"], 1001 + i,
                         transaction_date=f"2026-02-0{i + 1}",
                         payment_date=f"2026-02-0{i + 1}")

        rows, meta = validate_paginated(api.list_spend_records(ANALYST1))
        assert meta["total_count"] == 6
        assert meta["limit"] == 10, "Default limit is 10"
        assert len(rows) == 6
        assert meta["has_more"] is False

        rows, meta = validate_paginated(
            api.list_spend_records(ANALYST1, params={"limit": 5}))
        assert len(rows) == 5
        assert meta["total_count"] == 6
        assert meta["has_more"] is True

        rows, meta = validate_paginated(
            api.list_spend_records(ANALYST1, params={"limit": 5, "offset": 5}))
        assert len(rows) == 1, "The second page carries the 1-row remainder"
        assert meta["total_count"] == 6
        assert meta["has_more"] is False

    def test_certifications_list_scoped_to_owning_supplier(self, api):
        """PRD §4: "List certifications of a supplier" — the nested collection
        returns the path supplier's certifications.
        PRD §2.9: "When a URL nests one resource under another — a supplier's
        certifications, a business unit's goals or scorecards, a sourcing
        event's invitations — path identifiers are validated left-to-right"

        Design: Corner/endpoints/certifications_list_scoped_to_owning_supplier
        """
        supplier_a = create_supplier(legal_name="Scoped A", tax_id="T-SCA")
        supplier_b = create_supplier(legal_name="Scoped B", tax_id="T-SCB")
        submit_certification(supplier_a["id"], cert_type="MBE",
                             certificate_number="M-SCA")
        submit_certification(supplier_a["id"], cert_type="WBE",
                             certificate_number="W-SCA")
        submit_certification(supplier_b["id"], cert_type="VET",
                             certificate_number="V-SCB")
        certs, meta = validate_paginated(
            api.list_certifications(supplier_a["id"], ADMIN1))
        assert meta["total_count"] == 2
        assert all(c["supplier_id"] == supplier_a["id"] for c in certs), (
            "The sub-resource list never returns a sibling supplier's "
            "certifications"
        )
