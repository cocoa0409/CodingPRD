"""Renewal fees, dual registration, optimistic concurrency, and list/estimate
endpoint tests (PRD Sections 2.3, 2.8, 2.10, 3.7, 3.8)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_renewal_invoice,
    create_active_registration,
    create_active_registration_with_invoice,
    create_applicant,
    create_firm,
    create_firm_applicant_request,
    create_registration_request,
    get_affiliation,
    get_invoice,
    issue_renewal_invoice,
    make_applicant_payload,
    make_firm_payload,
    make_registration_request_payload,
    make_user_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRenewalFeeRankVariant:
    def _setup_two_active_registrations(self):
        """One firm with two IA registrations: RA approved 2026-06-02 (ACTIVE
        2026-06-03), RB approved 2026-06-04 (ACTIVE 2026-06-05)."""
        ctx_a = create_active_registration(
            category="IA",
            jurisdictions=("CA",),
            approve_date="2026-06-02",
            window_start="2026-06-01T00:00:00Z",
            window_end="2026-06-03T00:00:00Z",
            submitter_user_id="rp-fee-a",
            reviewer_user_id="co-fee-a",
        )
        ctx_b = create_active_registration(
            category="IA",
            jurisdictions=("CA",),
            approve_date="2026-06-04",
            window_start="2026-06-03T00:00:00Z",
            window_end="2026-06-05T00:00:00Z",
            submitter_user_id="rp-fee-b",
            reviewer_user_id="co-fee-b",
            firm_overrides={
                "crd_number": ctx_a["firm"]["crd_number"],
                "legal_name": ctx_a["firm"]["legal_name"],
            },
        )
        return ctx_a, ctx_b

    def test_renewal_fee_first_registration_base(self, api):
        """PRD Section 3.7: "The `base_fee_cents` component depends on the
        firm's rank for this registration: count the firm's other registration
        requests that are `ACTIVE` with an `approved_at` earlier than this
        request's (ties broken by `created_at` ascending); if there are none
        this is the firm's first registration of the cycle and the base is
        10000 cents". PRD Section 3.7: "The `jurisdiction_fee_cents` component
        is the sum of `annual_fee_cents` over the request's jurisdiction
        selections in `APPROVED` status". PRD Section 3.2: "a `STATE`
        selection costs 5000 cents per year".

        Design: Difficulty/dual_variant_calc/renewal_fee_first_vs_additional_registration_variant
        """
        firm = create_firm()
        app_a = create_applicant()
        req_a = create_registration_request(app_a["id"], firm["id"],
                                            registration_category="IA")
        from test_helpers import (
            add_jurisdiction_selection,
            create_fingerprint_submission,
            list_exam_requirements,
            pass_exam_requirement,
            process_fingerprint,
            submit_request,
        )
        add_jurisdiction_selection(req_a["id"], "CA", "STATE")
        fp = create_fingerprint_submission(req_a["id"])
        process_fingerprint(fp["id"], "CLEARED")
        submit_request(req_a["id"], "rp-fee-a")
        exams_a = {r["exam_code"]: r for r in list_exam_requirements(req_a["id"])}
        for code in ("SIE", "S66"):
            pass_exam_requirement(
                exams_a[code]["id"],
                "2026-06-01T00:00:00Z", "2026-06-03T00:00:00Z",
                pass_clock="2026-06-01T00:00:00Z",
            )
        set_clock("2026-06-02T00:00:00Z")
        validate_success(
            api.approve_registration_request(
                req_a["id"], make_user_headers("co-fee-a", "ComplianceOfficer")
            )
        )
        set_clock("2026-06-03T00:00:00Z")  # RA rolls ACTIVE

        # Second registration at the same firm, approved two days later.
        app_b = create_applicant()
        req_b = create_registration_request(app_b["id"], firm["id"],
                                            registration_category="IA")
        add_jurisdiction_selection(req_b["id"], "CA", "STATE")
        fp_b = create_fingerprint_submission(req_b["id"])
        process_fingerprint(fp_b["id"], "CLEARED")
        submit_request(req_b["id"], "rp-fee-b")
        exams_b = {r["exam_code"]: r for r in list_exam_requirements(req_b["id"])}
        for code in ("SIE", "S66"):
            pass_exam_requirement(
                exams_b[code]["id"],
                "2026-06-03T00:00:00Z", "2026-06-05T00:00:00Z",
                pass_clock="2026-06-03T00:00:00Z",
            )
        set_clock("2026-06-04T00:00:00Z")
        validate_success(
            api.approve_registration_request(
                req_b["id"], make_user_headers("co-fee-b", "ComplianceOfficer")
            )
        )
        set_clock("2026-06-05T00:00:00Z")  # RB rolls ACTIVE

        set_clock("2026-12-01T00:00:00Z")  # before 2027-01-01: zero days late
        inv_a = issue_renewal_invoice(req_a["id"], 2027)
        assert_renewal_invoice(inv_a)
        # Rank 0 (earliest approved_at): base 10000; CA approved: 5000.
        assert inv_a["base_fee_cents"] == 10000
        assert inv_a["jurisdiction_fee_cents"] == 5000
        assert inv_a["late_surcharge_cents"] == 0
        assert inv_a["total_cents"] == 15000

    def test_renewal_fee_additional_registration_base(self, api):
        """PRD Section 3.7: "count the firm's other registration requests that
        are `ACTIVE` with an `approved_at` earlier than this request's (ties
        broken by `created_at` ascending); if there are none this is the
        firm's first registration of the cycle and the base is 10000 cents,
        otherwise each additional registration pays 5000 cents."

        Design: Difficulty/dual_variant_calc/renewal_fee_first_vs_additional_registration_variant
        """
        firm = create_firm()
        from test_helpers import (
            add_jurisdiction_selection,
            create_fingerprint_submission,
            list_exam_requirements,
            pass_exam_requirement,
            process_fingerprint,
            submit_request,
        )

        def _activate(applicant_crd_suffix, approve_date, submitter, reviewer,
                      win_start, win_end):
            app = create_applicant()
            req = create_registration_request(app["id"], firm["id"],
                                              registration_category="IA")
            add_jurisdiction_selection(req["id"], "CA", "STATE")
            fp = create_fingerprint_submission(req["id"])
            process_fingerprint(fp["id"], "CLEARED")
            submit_request(req["id"], submitter)
            exams = {r["exam_code"]: r
                     for r in list_exam_requirements(req["id"])}
            for code in ("SIE", "S66"):
                pass_exam_requirement(
                    exams[code]["id"], win_start, win_end, pass_clock=win_start,
                )
            set_clock(f"{approve_date}T00:00:00Z")
            validate_success(
                api.approve_registration_request(
                    req["id"], make_user_headers(reviewer, "ComplianceOfficer")
                )
            )
            from datetime import date, timedelta
            y, m, d = (int(p) for p in approve_date.split("-"))
            nxt = (date(y, m, d) + timedelta(days=1)).isoformat()
            set_clock(f"{nxt}T00:00:00Z")
            return req

        req_a = _activate("a", "2026-06-02", "rp-fee-a", "co-fee-a",
                          "2026-06-01T00:00:00Z", "2026-06-03T00:00:00Z")
        req_b = _activate("b", "2026-06-04", "rp-fee-b", "co-fee-b",
                          "2026-06-03T00:00:00Z", "2026-06-05T00:00:00Z")

        set_clock("2026-12-01T00:00:00Z")
        inv_b = issue_renewal_invoice(req_b["id"], 2027)
        assert_renewal_invoice(inv_b)
        # Rank 1 (one earlier-activated registration on the firm): base 5000.
        assert inv_b["base_fee_cents"] == 5000
        assert inv_b["jurisdiction_fee_cents"] == 5000
        assert inv_b["late_surcharge_cents"] == 0
        assert inv_b["total_cents"] == 10000


class TestRenewalFeeLateBlocks:
    def test_renewal_fee_late_block_tiering_exactly_one_block(self, api):
        """PRD Section 3.7: "measure the whole days from January 1 of
        `cycle_year` to the current server date (never less than zero), take
        the number of full 14-day blocks that fit in that span, and charge 25%
        of `base_fee_cents` per block, capped at 100%". PRD Section 2.7: "the
        component is rounded to whole cents using round-half-up before any
        summation takes place".

        Design: Difficulty/combinatorial_formula/renewal_fee_late_block_tiering_mode_a
        """
        ctx = create_active_registration(
            category="IA",
            jurisdictions=("CA", "NY", "TX"),
            approve_date="2026-06-02",
            submitter_user_id="rp-tier",
            reviewer_user_id="co-tier",
        )
        # 2027-01-15 is exactly 14 whole days after 2027-01-01: one block.
        set_clock("2027-01-15T00:00:00Z")
        invoice = issue_renewal_invoice(ctx["request"]["id"], 2027)
        assert_renewal_invoice(invoice)
        assert invoice["jurisdiction_fee_cents"] == 15000  # 3 APPROVED STATE
        assert invoice["base_fee_cents"] == 10000          # rank 0
        assert invoice["late_surcharge_cents"] == 2500     # 1 block => 25%
        assert invoice["total_cents"] == 27500

    def test_renewal_fee_late_block_tiering_thirteen_days_no_block(self, api):
        """PRD Section 3.7: "take the number of full 14-day blocks that fit in
        that span, and charge 25% of `base_fee_cents` per block". Thirteen
        whole days fit zero full blocks, so the surcharge component is zero.

        Design: Difficulty/combinatorial_formula/renewal_fee_late_block_tiering_mode_a
        """
        ctx = create_active_registration(
            category="IA",
            jurisdictions=("CA", "NY", "TX"),
            approve_date="2026-06-02",
            submitter_user_id="rp-tier13",
            reviewer_user_id="co-tier13",
        )
        # 2027-01-14 is 13 whole days after 2027-01-01: floor(13/14) == 0.
        set_clock("2027-01-14T00:00:00Z")
        invoice = issue_renewal_invoice(ctx["request"]["id"], 2027)
        assert_renewal_invoice(invoice)
        assert invoice["jurisdiction_fee_cents"] == 15000
        assert invoice["base_fee_cents"] == 10000
        assert invoice["late_surcharge_cents"] == 0
        assert invoice["total_cents"] == 25000

    def test_renewal_fee_surcharge_cap_at_100_percent(self, api):
        """PRD Section 3.7: "charge 25% of `base_fee_cents` per block, capped
        at 100% — four or more blocks therefore cost the full base again".

        Design: Corner/calculations/renewal_fee_surcharge_cap_at_100_percent
        """
        ctx = create_active_registration(
            category="IA",
            jurisdictions=("CA",),
            approve_date="2026-06-02",
            submitter_user_id="rp-cap",
            reviewer_user_id="co-cap",
        )
        # 2027-03-12 is 70 whole days after 2027-01-01: 5 blocks => 125%,
        # capped at 100% of the 10000-cent base.
        set_clock("2027-03-12T00:00:00Z")
        invoice = issue_renewal_invoice(ctx["request"]["id"], 2027)
        assert_renewal_invoice(invoice)
        assert invoice["late_surcharge_cents"] == 10000
        assert invoice["total_cents"] == 25000  # 5000 + 10000 + 10000


class TestRenewalEstimate:
    def test_input_set_filtering_excludes_non_approved_selections(
        self, api, finance_clerk_headers
    ):
        """PRD Section 3.7: "The `jurisdiction_fee_cents` component is the sum
        of `annual_fee_cents` over the request's jurisdiction selections in
        `APPROVED` status — selections in `SELECTED`, `REJECTED`, or
        `RELINQUISHED` contribute nothing". PRD Section 3.7: "The estimate
        runs the identical formula".

        Design: Corner/calculations/input_set_filtering_excludes_non_approved_selections
        """
        from test_helpers import create_submitted_request
        ctx = create_submitted_request(
            category="RR",
            jurisdictions=("CA", "FINRA"),
            submitter_user_id="rp-fl",
        )
        # Request is SUBMITTED: both selections are still SELECTED.
        estimate = validate_success(
            api.get_renewal_estimate(ctx["request"]["id"], 2027,
                                     finance_clerk_headers)
        )
        assert estimate["jurisdiction_fee_cents"] == 0

    def test_renewal_estimate_is_provisional_not_persisted(
        self, api, finance_clerk_headers
    ):
        """PRD Section 4: "Provisional renewal fee estimate for a cycle year
        (not persisted)". PRD Section 3.7: "it returns `estimated_total_cents`
        alongside its `jurisdiction_fee_cents`, `base_fee_cents`, and
        `late_surcharge_cents` components, and it is never persisted."

        Design: Corner/endpoints/renewal_estimate_is_provisional_not_persisted
        """
        from test_helpers import create_firm_applicant_request
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        estimate = validate_success(
            api.get_renewal_estimate(request["id"], 2027, finance_clerk_headers)
        )
        for field in (
            "estimated_total_cents", "jurisdiction_fee_cents",
            "base_fee_cents", "late_surcharge_cents",
        ):
            assert isinstance(estimate[field], int), (
                f"estimate must carry integer component {field}"
            )

        invoices, _meta = validate_paginated(
            api.list_renewal_invoices(
                finance_clerk_headers,
                params={"registration_request_id": request["id"]},
            )
        )
        assert invoices == [], "the estimate must not persist any invoice row"


class TestRenewalInvoiceUniqueness:
    def test_duplicate_invoice_same_cycle_rejected(self, api, finance_clerk_headers):
        """PRD Section 3.7: "at most one invoice may exist per registration
        request and cycle year — a second issue for the same pair is rejected
        `ERR_DUPLICATE`".

        Design: Corner/errors/duplicate_invoice_same_cycle_rejected
        """
        ctx = create_active_registration_with_invoice(
            cycle_year=2027,
            invoice_clock="2026-12-01T00:00:00Z",
            submitter_user_id="rp-di",
            reviewer_user_id="co-di",
        )
        resp = api.create_renewal_invoice(
            {
                "registration_request_id": ctx["request"]["id"],
                "cycle_year": 2027,
            },
            finance_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

        # A different cycle year for the same registration is a new pair.
        inv_2028 = validate_success(
            api.create_renewal_invoice(
                {
                    "registration_request_id": ctx["request"]["id"],
                    "cycle_year": 2028,
                },
                finance_clerk_headers,
            ),
            expected_status=201,
        )
        assert inv_2028["cycle_year"] == 2028


class TestInvoicePaymentOcc:
    def test_occ_stale_version_on_invoice_pay(self, api, finance_clerk_headers):
        """PRD Section 2.8: "Paying a renewal invoice requires the request to
        carry `expected_renewal_invoice_version`, holding the invoice
        `version` the client last observed." PRD Section 2.10: step 5 "State
        legality ... otherwise `ERR_INVALID_STATE` (409)" is ordered ahead of
        step 6 "Optimistic concurrency ... otherwise `ERR_STALE_VERSION`
        (412)" — so a replayed pay against an already-PAID invoice surfaces
        the state error.

        Design: Corner/cross_cutting_layers/occ_stale_version_on_invoice_pay
        """
        ctx = create_active_registration_with_invoice(
            cycle_year=2027,
            invoice_clock="2026-12-01T00:00:00Z",
            submitter_user_id="rp-oc",
            reviewer_user_id="co-oc",
        )
        invoice = ctx["invoice"]
        captured_version = invoice["version"]

        paid = validate_success(
            api.pay_renewal_invoice(
                invoice["id"],
                {"expected_renewal_invoice_version": captured_version},
                finance_clerk_headers,
            )
        )
        assert paid["status"] == "PAID"
        assert paid["version"] > captured_version

        # Replaying the stale version hits the state check (already PAID),
        # which the declared validation order evaluates before OCC.
        resp = api.pay_renewal_invoice(
            invoice["id"],
            {"expected_renewal_invoice_version": captured_version},
            finance_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_occ_stale_version_on_registration_patch(
        self, api, registration_principal_headers
    ):
        """PRD Section 2.8: "Patching a registration request requires the
        request body to carry `expected_registration_request_version`,
        holding the request `version` the client last observed. If the
        request's current `version` has advanced — because a system
        transition or another writer mutated it in the meantime — the patch
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_registration_patch
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        captured_version = request["version"]

        patched = validate_success(
            api.patch_registration_request(
                request["id"],
                {
                    "registration_category": "IA",
                    "expected_registration_request_version": captured_version,
                },
                registration_principal_headers,
            )
        )
        assert patched["registration_category"] == "IA"
        assert patched["version"] > captured_version

        # Replaying the stale version is rejected by the OCC check.
        resp = api.patch_registration_request(
            request["id"],
            {
                "registration_category": "PRINCIPAL",
                "expected_registration_request_version": captured_version,
            },
            registration_principal_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestJurisdictionFeeConservation:
    def test_jurisdiction_fee_conservation_on_relinquish_components(self, api):
        """PRD Section 3.2: "Once a registration is `ACTIVE`, a
        `RegistrationPrincipal` may give up a jurisdiction by relinquishing an
        `APPROVED` selection, moving it to `RELINQUISHED`." PRD Section 3.7:
        "The `jurisdiction_fee_cents` component is the sum of
        `annual_fee_cents` over the request's jurisdiction selections in
        `APPROVED` status — selections in `SELECTED`, `REJECTED`, or
        `RELINQUISHED` contribute nothing". PRD Section 3.2: "Relinquishment
        has a fiscal echo: the `jurisdiction_fee_cents` of every
        still-`ISSUED` renewal invoice for that registration request is
        recomputed to reflect the smaller approved-jurisdiction set (§3.7)."

        Design: Difficulty/compensating_invariant/jurisdiction_fee_conservation_on_relinquish
        """
        ctx = create_active_registration_with_invoice(
            cycle_year=2027,
            invoice_clock="2026-12-01T00:00:00Z",
            category="IA",
            jurisdictions=("CA", "NY"),
            submitter_user_id="rp-inv",
            reviewer_user_id="co-inv",
        )
        invoice = ctx["invoice"]
        # Two APPROVED STATE selections: 5000 + 5000.
        assert invoice["jurisdiction_fee_cents"] == 10000
        assert invoice["base_fee_cents"] == 10000
        assert invoice["total_cents"] == 20000

        relinquished = validate_success(
            api.relinquish_jurisdiction_selection(
                ctx["selections"]["CA"]["id"],
                make_user_headers("rp-inv", "RegistrationPrincipal"),
            )
        )
        assert relinquished["status"] == "RELINQUISHED"

        after = get_invoice(invoice["id"])
        assert after["jurisdiction_fee_cents"] == 5000
        assert after["total_cents"] == 15000

    def test_jurisdiction_fee_conservation_only_issued_invoice_recomputed(self, api):
        """PRD Section 3.2: "Relinquishment has a fiscal echo: the
        `jurisdiction_fee_cents` of every still-`ISSUED` renewal invoice for
        that registration request is recomputed to reflect the smaller
        approved-jurisdiction set (§3.7)." PRD Section 3.7: "selections in
        `SELECTED`, `REJECTED`, or `RELINQUISHED` contribute nothing, and a
        request with no approved selections pays zero here."

        Design: Difficulty/compensating_invariant/jurisdiction_fee_conservation_on_relinquish
        """
        ctx = create_active_registration_with_invoice(
            cycle_year=2027,
            invoice_clock="2026-12-01T00:00:00Z",
            category="IA",
            jurisdictions=("CA", "NY"),
            submitter_user_id="rp-inv2",
            reviewer_user_id="co-inv2",
        )
        invoice = ctx["invoice"]

        # Relinquish NY first: invoice drops from 10000 to 5000.
        validate_success(
            api.relinquish_jurisdiction_selection(
                ctx["selections"]["NY"]["id"],
                make_user_headers("rp-inv2", "RegistrationPrincipal"),
            )
        )
        mid = get_invoice(invoice["id"])
        assert mid["jurisdiction_fee_cents"] == 5000
        assert mid["total_cents"] == 15000

        # Relinquish CA too: with no APPROVED selections left the component
        # falls to zero and the total drops by the same amount again.
        validate_success(
            api.relinquish_jurisdiction_selection(
                ctx["selections"]["CA"]["id"],
                make_user_headers("rp-inv2", "RegistrationPrincipal"),
            )
        )
        end = get_invoice(invoice["id"])
        assert end["jurisdiction_fee_cents"] == 0
        assert end["base_fee_cents"] == 10000
        assert end["total_cents"] == 10000


class TestAffiliationApprovalGate:
    def _setup_pending_affiliation_while_approved(self):
        """First registration approved 2026-06-02 but clock parked the same
        day (still APPROVED); affiliation created against second firm."""
        firm1 = create_firm(legal_name="Cross Firm 1")
        firm2 = create_firm(legal_name="Cross Firm 2")
        applicant = create_applicant()
        from test_helpers import (
            add_jurisdiction_selection,
            create_fingerprint_submission,
            list_exam_requirements,
            pass_exam_requirement,
            process_fingerprint,
            submit_request,
        )
        req = create_registration_request(applicant["id"], firm1["id"],
                                          registration_category="IA")
        add_jurisdiction_selection(req["id"], "CA", "STATE")
        fp = create_fingerprint_submission(req["id"])
        process_fingerprint(fp["id"], "CLEARED")
        submit_request(req["id"], "rp-cross")
        exams = {r["exam_code"]: r for r in list_exam_requirements(req["id"])}
        for code in ("SIE", "S66"):
            pass_exam_requirement(
                exams[code]["id"],
                "2026-06-01T00:00:00Z", "2026-06-03T00:00:00Z",
                pass_clock="2026-06-01T00:00:00Z",
            )
        set_clock("2026-06-02T00:00:00Z")
        validate_success(
            api_client.approve_registration_request(
                req["id"], make_user_headers("co-cross", "ComplianceOfficer")
            )
        )
        # Park the clock on the approval day: rollover has not yet fired.
        set_clock("2026-06-02T12:00:00Z")
        affiliation = validate_success(
            api_client.create_affiliation_request(
                {
                    "applicant_id": applicant["id"],
                    "second_firm_id": firm2["id"],
                    "first_registration_request_id": req["id"],
                },
                make_user_headers("rp-cross", "RegistrationPrincipal"),
            ),
            expected_status=201,
        )
        return firm1, firm2, applicant, req, affiliation

    def test_affiliation_approval_gated_by_first_registration_active_rejected(self, api):
        """PRD Section 3.8: "Approval requires the affiliation to be
        `PENDING`, the first registration to be `ACTIVE` at decision time".
        While the first registration is merely `APPROVED` (the deferred
        activation of PRD Section 3.5 has not fired), the approve fails the
        state-legality check (PRD Section 2.10 step 5).

        Design: Difficulty/cross_entity_state_dependency/affiliation_approval_gated_by_first_registration_active
        """
        _f1, _f2, _app, req, affiliation = (
            self._setup_pending_affiliation_while_approved()
        )
        # Confirm the first registration is still APPROVED, not ACTIVE.
        from test_helpers import get_request
        assert get_request(req["id"])["status"] == "APPROVED"

        resp = api.approve_affiliation_request(
            affiliation["id"], make_user_headers("co-cross-2", "ComplianceOfficer")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_affiliation_approval_gated_by_first_registration_active_succeeds(self, api):
        """PRD Section 3.8: "Approval requires the affiliation to be
        `PENDING`, the first registration to be `ACTIVE` at decision time ...
        approval moves `PENDING → APPROVED`." PRD Section 3.5: "The request
        moves `APPROVED → ACTIVE` as a system transition evaluated when the
        server clock is set: ... when the clock's current date is strictly
        after the date of `approved_at`".

        Design: Difficulty/cross_entity_state_dependency/affiliation_approval_gated_by_first_registration_active
        """
        _f1, _f2, _app, req, affiliation = (
            self._setup_pending_affiliation_while_approved()
        )
        # Advance past the approval day so the rollover fires.
        set_clock("2026-06-03T00:00:00Z")
        from test_helpers import get_request
        assert get_request(req["id"])["status"] == "ACTIVE"

        approved = validate_success(
            api.approve_affiliation_request(
                affiliation["id"],
                make_user_headers("co-cross-2", "ComplianceOfficer"),
            )
        )
        assert approved["status"] == "APPROVED"


class TestAffiliationSlotOccupation:
    def test_affiliation_status_occupation_blocks_duplicate(self, api,
                                                            registration_principal_headers,
                                                            compliance_officer_headers):
        """PRD Section 3.8: "the applicant may hold at most one affiliation
        request in `PENDING` or `APPROVED` status for a given second firm,
        with repeats rejected `ERR_DUPLICATE`".

        Design: Difficulty/resource_temporal_overlap/affiliation_status_occupation_blocks_and_releases
        """
        firm1 = create_firm(legal_name="Overlap Firm 2A")
        firm2 = create_firm(legal_name="Overlap Firm 2B")
        applicant = create_applicant()
        req = create_registration_request(applicant["id"], firm1["id"],
                                          registration_category="IA")

        first = validate_success(
            api.create_affiliation_request(
                {
                    "applicant_id": applicant["id"],
                    "second_firm_id": firm2["id"],
                    "first_registration_request_id": req["id"],
                },
                registration_principal_headers,
            ),
            expected_status=201,
        )
        assert first["status"] == "PENDING"

        # While the first is PENDING the identical request is a duplicate.
        resp = api.create_affiliation_request(
            {
                "applicant_id": applicant["id"],
                "second_firm_id": firm2["id"],
                "first_registration_request_id": req["id"],
            },
            registration_principal_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

    def test_affiliation_status_occupation_released_by_denial(self, api,
                                                              registration_principal_headers,
                                                              compliance_officer_headers):
        """PRD Section 3.8: "the applicant may hold at most one affiliation
        request in `PENDING` or `APPROVED` status for a given second firm,
        with repeats rejected `ERR_DUPLICATE`." PRD Section 3.8: "Denial needs
        only the `PENDING` precondition and records the supplied
        `denial_reason` on the row, moving it to `DENIED`." A DENIED row is
        outside the PENDING-or-APPROVED set, so the slot is released.

        Design: Difficulty/resource_temporal_overlap/affiliation_status_occupation_blocks_and_releases
        """
        firm1 = create_firm(legal_name="Overlap Firm 2A")
        firm2 = create_firm(legal_name="Overlap Firm 2B")
        applicant = create_applicant()
        req = create_registration_request(applicant["id"], firm1["id"],
                                          registration_category="IA")

        first = validate_success(
            api.create_affiliation_request(
                {
                    "applicant_id": applicant["id"],
                    "second_firm_id": firm2["id"],
                    "first_registration_request_id": req["id"],
                },
                registration_principal_headers,
            ),
            expected_status=201,
        )
        denied = validate_success(
            api.deny_affiliation_request(
                first["id"],
                {"denial_reason": "Conflicting business line at second firm."},
                compliance_officer_headers,
            )
        )
        assert denied["status"] == "DENIED"

        second = validate_success(
            api.create_affiliation_request(
                {
                    "applicant_id": applicant["id"],
                    "second_firm_id": firm2["id"],
                    "first_registration_request_id": req["id"],
                },
                registration_principal_headers,
            ),
            expected_status=201,
        )
        assert second["status"] == "PENDING"
        assert second["id"] != first["id"]


class TestListEndpoints:
    def test_list_pagination_envelope_fields(self, api, system_operator_headers):
        """PRD Section 2.3: "List responses carry four pagination fields in
        the `meta` object of the envelope: `limit`, `offset`, `total_count`,
        and `has_more`." PRD Section 2.3: "The `limit` parameter caps the
        number of items returned; it defaults to 10". PRD Section 2.2: the
        envelope carries `meta.api_request_id`, `meta.api_request_timestamp`,
        and a `response_type` of "array" for a list of resources.

        Design: Corner/endpoints/list_pagination_envelope_fields
        """
        create_firm(crd_number="3401", legal_name="Pg Firm A")
        create_firm(crd_number="3402", legal_name="Pg Firm B")

        response = api.list_firms(
            system_operator_headers, params={"limit": 1, "offset": 0}
        )
        body = response.json()
        assert "api_request_id" in body.get("meta", {})
        assert "api_request_timestamp" in body.get("meta", {})
        assert body.get("response_type") == "array"

        data, meta = validate_paginated(response)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0

    def test_filtered_list_by_foreign_key(self, api, system_operator_headers):
        """PRD Section 4 declares the endpoint "List jurisdiction selections
        with optional filters", and the request's selections are keyed by
        `registration_request_id` (PRD Section 3.2: "Each selection is created
        against a `registration_request_id`"), so the filtered list returns
        only the named request's selections.

        Design: Corner/endpoints/filtered_list_by_foreign_key
        """
        firm = create_firm(crd_number="3403", legal_name="Flt Firm")
        app_a = create_applicant(
            crd_number="3404", full_name="Flt Rep A", date_of_birth="1998-11-23"
        )
        app_b = create_applicant(
            crd_number="3405", full_name="Flt Rep B", date_of_birth="1999-12-24"
        )
        from test_helpers import add_jurisdiction_selection
        req_a = create_registration_request(app_a["id"], firm["id"],
                                            registration_category="RR")
        req_b = create_registration_request(app_b["id"], firm["id"],
                                            registration_category="RR")
        add_jurisdiction_selection(req_a["id"], "CA", "STATE")
        add_jurisdiction_selection(req_b["id"], "NY", "STATE")

        data, _meta = validate_paginated(
            api.list_jurisdiction_selections(
                system_operator_headers,
                params={"registration_request_id": req_a["id"]},
            )
        )
        assert len(data) == 1
        assert data[0]["jurisdiction_code"] == "CA"
        assert data[0]["registration_request_id"] == req_a["id"]
