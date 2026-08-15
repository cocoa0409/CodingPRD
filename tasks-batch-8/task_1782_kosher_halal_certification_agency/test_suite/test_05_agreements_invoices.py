"""Agreements (OCC, term computation, fee snapshot) and invoices."""
from test_helpers import (
    ApiErrorId,
    create_active_agreement,
    create_agreement_payload,
    create_annual_invoice,
    create_applicant_client,
    create_certifiable_product,
    create_draft_agreement,
    create_facility_for,
    find_invoices,
    get_client,
    get_client_version,
    get_success_data,
    make_client_contact_headers,
    make_supervisor_headers,
    raise_finding,
    schedule_visit,
    set_clock,
    setup_certified_client,
    validate_error,
    validate_success,
)


class TestAgreementTermComputation:
    def test_agreement_term_end_date_anniversary_vs_calendar_year(self, api):
        """PRD section 3.8: "an anniversary agreement ends the day before the
        twelve-month anniversary of its start, while a calendar-year agreement
        ends on December 31 of the start year."

        Design: Corner/calculations/agreement_term_end_date_anniversary_vs_calendar_year
        """
        anniv_client = create_applicant_client(legal_name="T1 Co")
        anniv = create_draft_agreement(anniv_client["id"],
                                       billing_cycle="ANNIVERSARY",
                                       term_start_date="2026-04-01")
        assert anniv["term_end_date"] == "2027-03-31", (
            "ANNIVERSARY: term_start + 12 months - 1 day")

        cal_client = create_applicant_client(legal_name="T2 Co",
                                             contact_email="t2@x.com")
        cal = create_draft_agreement(cal_client["id"],
                                     billing_cycle="CALENDAR_YEAR",
                                     term_start_date="2026-04-01")
        assert cal["term_end_date"] == "2026-12-31", (
            "CALENDAR_YEAR: Dec 31 of the start year")


class TestAgreementOcc:
    def test_occ_stale_client_version_on_agreement_create(
            self, api, account_manager_headers):
        """PRD section 2.7: "If that value no longer matches the client's
        current `version` — because another writer has advanced the client
        record since the caller read it — the create is rejected with
        `ERR_STALE_CLIENT_VERSION` (HTTP 412), before any business logic runs."

        Design: Corner/validations/occ_stale_client_version_on_agreement_create
        """
        client = create_applicant_client(legal_name="OCC Co")
        cid = client["id"]
        stale_version = client["version"]

        first = validate_success(api.create_agreement(
            create_agreement_payload(cid, stale_version),
            account_manager_headers), 201)
        fresh_version = get_client_version(cid)
        assert fresh_version == stale_version + 1, (
            "a successful agreement create increments the client's version")
        second = validate_success(api.create_agreement(
            create_agreement_payload(cid, fresh_version,
                                     billing_cycle="CALENDAR_YEAR",
                                     term_start_date="2026-05-01",
                                     per_product_fee_cents=80000),
            account_manager_headers), 201)

        resp = api.create_agreement(
            create_agreement_payload(cid, stale_version,
                                     term_start_date="2026-06-01",
                                     per_product_fee_cents=90000),
            account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_CLIENT_VERSION, 412)

        assert validate_success(api.get_agreement(
            first["id"], account_manager_headers))["status"] == "DRAFT"
        assert validate_success(api.get_agreement(
            second["id"], account_manager_headers))["status"] == "DRAFT", (
                "create-with-supersede only retires an ACTIVE agreement")


class TestAgreementStateAndUniqueness:
    def test_agreement_double_activate_rejected(self, api,
                                                account_manager_headers):
        """PRD section 3.8: "Activation (`DRAFT` → `ACTIVE`) requires the client
        to be `APPLICANT` or `CERTIFIED` (`ERR_CLIENT_INVALID_STATE`), the
        agreement still `DRAFT` (`ERR_AGREEMENT_INVALID_STATE`)".

        Design: Corner/state_machines/agreement_double_activate_rejected
        """
        client = create_applicant_client(legal_name="DA Co")
        agreement = create_active_agreement(client["id"])
        assert agreement["status"] == "ACTIVE"
        resp = api.activate_agreement(agreement["id"], account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_INVALID_STATE)

    def test_second_active_agreement_rejected(self, api,
                                              account_manager_headers):
        """PRD section 3.8: "Activation (`DRAFT` → `ACTIVE`) requires the client
        to be `APPLICANT` or `CERTIFIED` (`ERR_CLIENT_INVALID_STATE`), the
        agreement still `DRAFT` (`ERR_AGREEMENT_INVALID_STATE`), and no other
        `ACTIVE` agreement for the client (`ERR_ACTIVE_AGREEMENT_EXISTS`)."

        Design: Corner/validations/second_active_agreement_rejected
        """
        client = create_applicant_client(legal_name="SA Co")
        first = create_draft_agreement(client["id"])
        second = create_draft_agreement(client["id"],
                                        billing_cycle="CALENDAR_YEAR",
                                        term_start_date="2026-05-01",
                                        per_product_fee_cents=80000)
        validate_success(api.activate_agreement(first["id"],
                                                account_manager_headers))
        resp = api.activate_agreement(second["id"], account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_AGREEMENT_EXISTS)

    def test_halal_agreement_for_kosher_client_scheme_mismatch(
            self, api, account_manager_headers):
        """PRD section 3.8: "The scheme must be covered by the client's
        `certification_scheme` (`ERR_SCHEME_MISMATCH`)."

        Design: Corner/validations/halal_agreement_for_kosher_client_scheme_mismatch
        """
        client = create_applicant_client(legal_name="Sch Co",
                                         certification_scheme="KOSHER")
        resp = api.create_agreement(
            create_agreement_payload(client["id"], get_client_version(client["id"]),
                                     scheme="HALAL"),
            account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_SCHEME_MISMATCH)


class TestAnnualFeeSnapshot:
    def test_annual_fee_tiered_copacker_multiplier_surcharge(
            self, api, account_manager_headers):
        """PRD section 3.8: "The tiered base charges 120000 cents for the first
        facility, 90000 cents for each of the second through fifth facilities
        (the count of facilities from 2 up to at most 5), and 70000 cents for
        each facility beyond the fifth. A co-packer surcharge of 25000 cents is
        added per facility whose `facility_role` is `CO_PACKER`. The scheme
        multiplier is 1.0 for `KOSHER` or `HALAL` and 1.8 for `DUAL`, applied to
        the base and rounded half-up to integer cents. Finally a risk surcharge
        keyed on the client's `risk_tier` at the calculation instant — zero
        percent for `LOW`, five percent for `MEDIUM`, fifteen percent for `HIGH`
        — is applied to the rounded subtotal, itself rounded half-up, and added."

        Design: Difficulty/combinatorial_formula/annual_fee_tiered_copacker_multiplier_surcharge
        """
        client = create_applicant_client(legal_name="Fee Co",
                                         certification_scheme="DUAL")
        cid = client["id"]
        cc = make_client_contact_headers(cid)
        facilities = []
        for idx in range(5):
            facilities.append(get_success_data(api.create_facility(
                {"client_id": cid, "name": f"F{idx + 1}", "address": str(idx + 1),
                 "facility_role": "OWNED"}, cc)))
        for idx in range(2):
            facilities.append(get_success_data(api.create_facility(
                {"client_id": cid, "name": f"F{idx + 6}", "address": str(idx + 6),
                 "facility_role": "CO_PACKER"}, cc)))

        visit = schedule_visit(facilities[0]["id"], visit_type="ROUTINE",
                               inspector_user_id="sup-2",
                               scheduled_start="2026-08-03T09:00:00Z",
                               scheduled_end="2026-08-03T12:00:00Z")
        set_clock("2026-08-03T10:00:00Z")
        sup = make_supervisor_headers("sup-2")
        validate_success(api.start_visit(visit["id"], sup))
        raise_finding(visit["id"], "sup-2", severity="MAJOR",
                      description="traceability gap")
        validate_success(api.complete_visit(visit["id"], sup))

        scored = get_client(cid)
        assert scored["open_nc_score"] == 3
        assert scored["risk_tier"] == "MEDIUM", (
            "one OPEN MAJOR (weight 3) puts the client in the 5% branch")

        agreement = create_draft_agreement(cid, scheme="DUAL",
                                           billing_cycle="ANNIVERSARY",
                                           term_start_date="2026-04-01")
        activated = validate_success(api.activate_agreement(agreement["id"],
                                                            account_manager_headers))
        assert activated["annual_fee_snapshot_cents"] == 1266300, (
            "tier_sum 620000 + copacker 50000 = 670000; x1.8 = 1206000; "
            "+5% = 60300; total 1266300")

    def test_annual_fee_snapshot_frozen_against_later_changes(
            self, api, account_manager_headers, reviewer_headers):
        """PRD section 3.8: "Activation freezes the annual fee onto
        `annual_fee_snapshot_cents` using the activation-snapshot variant of the
        fee calculation: later facility registrations or risk-tier movements
        never mutate the snapshot."

        Design: Difficulty/combinatorial_formula/annual_fee_tiered_copacker_multiplier_surcharge
        """
        client = create_applicant_client(legal_name="Fee Co 2",
                                         certification_scheme="DUAL")
        cid = client["id"]
        cc = make_client_contact_headers(cid)
        facilities = []
        for idx in range(5):
            facilities.append(get_success_data(api.create_facility(
                {"client_id": cid, "name": f"F{idx + 1}", "address": str(idx + 1),
                 "facility_role": "OWNED"}, cc)))
        for idx in range(2):
            facilities.append(get_success_data(api.create_facility(
                {"client_id": cid, "name": f"F{idx + 6}", "address": str(idx + 6),
                 "facility_role": "CO_PACKER"}, cc)))
        visit = schedule_visit(facilities[0]["id"], visit_type="ROUTINE",
                               inspector_user_id="sup-2",
                               scheduled_start="2026-08-03T09:00:00Z",
                               scheduled_end="2026-08-03T12:00:00Z")
        set_clock("2026-08-03T10:00:00Z")
        sup = make_supervisor_headers("sup-2")
        validate_success(api.start_visit(visit["id"], sup))
        raise_finding(visit["id"], "sup-2", severity="MAJOR",
                      description="traceability gap")
        validate_success(api.complete_visit(visit["id"], sup))

        agreement = create_draft_agreement(cid, scheme="DUAL",
                                           billing_cycle="ANNIVERSARY",
                                           term_start_date="2026-04-01")
        activated = validate_success(api.activate_agreement(agreement["id"],
                                                            account_manager_headers))
        assert activated["annual_fee_snapshot_cents"] == 1266300

        # Later facility registration and a risk-tier movement to HIGH.
        get_success_data(api.create_facility(
            {"client_id": cid, "name": "F8", "address": "8",
             "facility_role": "OWNED"}, cc))
        visit2 = schedule_visit(facilities[1]["id"], visit_type="ROUTINE",
                                inspector_user_id="sup-3",
                                scheduled_start="2026-08-04T09:00:00Z",
                                scheduled_end="2026-08-04T12:00:00Z")
        set_clock("2026-08-04T10:00:00Z")
        sup3 = make_supervisor_headers("sup-3")
        validate_success(api.start_visit(visit2["id"], sup3))
        raise_finding(visit2["id"], "sup-3", severity="CRITICAL",
                      description="severe")
        validate_success(api.complete_visit(visit2["id"], sup3))
        assert get_client(cid)["risk_tier"] == "HIGH"

        reread = validate_success(api.get_agreement(agreement["id"],
                                                    account_manager_headers))
        assert reread["annual_fee_snapshot_cents"] == 1266300, (
            "the snapshot is frozen at activation")

    def test_high_risk_surcharge_in_annual_fee_snapshot(
            self, api, account_manager_headers):
        """PRD section 3.8: "Finally a risk surcharge keyed on the client's
        `risk_tier` at the calculation instant — zero percent for `LOW`, five
        percent for `MEDIUM`, fifteen percent for `HIGH` — is applied to the
        rounded subtotal, itself rounded half-up, and added."

        Design: Corner/calculations/high_risk_surcharge_in_annual_fee_snapshot
        """
        client = create_applicant_client(legal_name="High Co")
        cid = client["id"]
        facility = create_facility_for(cid, name="FH")
        visit = schedule_visit(facility["id"], visit_type="ROUTINE",
                               inspector_user_id="sup-1",
                               scheduled_start="2026-08-02T09:00:00Z",
                               scheduled_end="2026-08-02T12:00:00Z")
        set_clock("2026-08-02T10:00:00Z")
        sup = make_supervisor_headers("sup-1")
        validate_success(api.start_visit(visit["id"], sup))
        raise_finding(visit["id"], "sup-1", severity="CRITICAL",
                      description="cr")
        validate_success(api.complete_visit(visit["id"], sup))
        scored = get_client(cid)
        assert scored["open_nc_score"] == 8 and scored["risk_tier"] == "HIGH"

        agreement = create_draft_agreement(cid)
        activated = validate_success(api.activate_agreement(agreement["id"],
                                                            account_manager_headers))
        assert activated["annual_fee_snapshot_cents"] == 138000, (
            "120000 base, KOSHER x1.0, +15% HIGH surcharge = 138000")


class TestInvoices:
    def test_invoice_void_on_paid_rejected(self, api, account_manager_headers):
        """PRD section 3.8: "payment or void against a `PAID` or `VOID` invoice
        yields `ERR_INVOICE_INVALID_STATE`."

        Design: Corner/state_machines/invoice_void_on_paid_rejected
        """
        client = create_applicant_client(legal_name="SM6 Co")
        create_facility_for(client["id"], name="F6")
        agreement = create_active_agreement(client["id"])
        invoice = create_annual_invoice(client["id"], agreement["id"])
        paid = validate_success(api.record_payment(invoice["id"],
                                                   account_manager_headers))
        assert paid["status"] == "PAID"

        resp = api.void_invoice(invoice["id"], account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVOICE_INVALID_STATE)
        client_after = get_client(client["id"])
        assert client_after["total_billed_cents"] == 120000, (
            "a rejected void leaves the billed ledger unchanged")

    def test_duplicate_annual_invoice_rejected(self, api,
                                               account_manager_headers):
        """PRD section 3.8: "at most one non-`VOID` annual invoice may exist per
        agreement (a second attempt yields `ERR_DUPLICATE_ANNUAL_INVOICE`)."

        Design: Corner/validations/duplicate_annual_invoice_rejected
        """
        client = create_applicant_client(legal_name="DI Co")
        agreement = create_active_agreement(client["id"])
        create_annual_invoice(client["id"], agreement["id"])
        resp = api.create_invoice(
            {"client_id": client["id"], "invoice_type": "ANNUAL_CERTIFICATION",
             "agreement_id": agreement["id"]}, account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ANNUAL_INVOICE)

    def test_reinstatement_invoice_requires_suspended_client(
            self, api, account_manager_headers):
        """PRD section 3.8: "`REINSTATEMENT` invoices are also manager-created,
        carry no `agreement_id`, are allowed only while the client is
        `SUSPENDED` (`ERR_CLIENT_INVALID_STATE` otherwise), and charge a flat
        50000 cents."

        Design: Corner/validations/reinstatement_invoice_requires_suspended_client
        """
        client = create_applicant_client(legal_name="RI Co")
        resp = api.create_invoice(
            {"client_id": client["id"], "invoice_type": "REINSTATEMENT"},
            account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CLIENT_INVALID_STATE)

    def test_annual_invoice_without_active_agreement_rejected(
            self, api, account_manager_headers):
        """PRD section 3.8: "`ANNUAL_CERTIFICATION` invoices are created by an
        `AccountManager` against an `agreement_id` naming an `ACTIVE`
        agreement". PRD section 3.7: "An `ACTIVE` agreement must exist for the
        client (`ERR_NO_ACTIVE_AGREEMENT`)".

        Design: Corner/validations/annual_invoice_without_active_agreement_rejected
        """
        client = create_applicant_client(legal_name="NA Co")
        draft = create_draft_agreement(client["id"])
        assert draft["status"] == "DRAFT"
        resp = api.create_invoice(
            {"client_id": client["id"], "invoice_type": "ANNUAL_CERTIFICATION",
             "agreement_id": draft["id"]}, account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_AGREEMENT)


class TestBilledCentsConservation:
    def test_billed_cents_conserved_under_add_product_and_void(
            self, api, account_manager_headers, officer_headers):
        """PRD section 3.8: "The client's `total_billed_cents` is the sum of
        `total_cents` over all of the client's invoices in `ISSUED`, `OVERDUE`,
        or `PAID` — `VOID` is excluded — recomputed whenever an invoice is
        created or voided."

        Design: Difficulty/compensating_invariant/billed_cents_conserved_under_add_product_and_void
        """
        ctx = setup_certified_client(legal_name="Inv Co")
        cid = ctx["client"]["id"]
        assert get_client(cid)["total_billed_cents"] == 120000

        set_clock("2026-07-01T00:00:00Z")
        extra = create_certifiable_product(
            cid, [ctx["ingredients"][0]["id"]], name="PIV2")
        validate_success(api.add_certificate_products(
            ctx["certificate"]["id"], [extra["id"]], officer_headers), 201)
        after_add = get_client(cid)
        assert after_add["total_billed_cents"] == 174600, (
            "120000 annual + 54600 prorated addition (73000 x 273/365)")

        addition = find_invoices(invoice_type="PRODUCT_ADDITION",
                                 related_certificate_id=ctx["certificate"]["id"])
        assert len(addition) == 1
        validate_success(api.void_invoice(addition[0]["id"],
                                          account_manager_headers))
        after_void = get_client(cid)
        assert after_void["total_billed_cents"] == 120000, (
            "create + void conserve the billed ledger exactly")

        cert = validate_success(api.get_certificate(ctx["certificate"]["id"],
                                                    officer_headers))
        assert cert["active_product_count"] == 2, (
            "voiding the invoice does not remove the listed product")

    def test_billed_cents_drop_to_zero_when_annual_invoice_voided(
            self, api, account_manager_headers):
        """PRD section 3.8: "Voiding an `ISSUED` or `OVERDUE` invoice
        compensates the ledger." PRD section 3.8: "The client's
        `total_billed_cents` is the sum of `total_cents` over all of the
        client's invoices in `ISSUED`, `OVERDUE`, or `PAID` — `VOID` is
        excluded".

        Design: Difficulty/compensating_invariant/billed_cents_conserved_under_add_product_and_void
        """
        client = create_applicant_client(legal_name="Inv Co 2")
        create_facility_for(client["id"], name="F")
        agreement = create_active_agreement(client["id"])
        invoice = create_annual_invoice(client["id"], agreement["id"])
        assert invoice["status"] == "ISSUED"
        assert get_client(client["id"])["total_billed_cents"] == 120000

        voided = validate_success(api.void_invoice(invoice["id"],
                                                   account_manager_headers))
        assert voided["status"] == "VOID"
        assert get_client(client["id"])["total_billed_cents"] == 0, (
            "the voided invoice leaves the billed set")
