"""Chargebacks: dual-variant amounts, cap/coverage nesting, per-line rounding,
assessment gates, dispute window, billing/payment, and the lease ledger."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_billing_clerk_headers,
    make_compliance_officer_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    MANAGER,
    assess_chargeback,
    complete_positive_inspection,
    create_lease,
    create_resident,
    create_unit,
    dispute_chargeback,
    resident_headers_for,
    set_clock,
    setup_community,
    setup_prep_acknowledged_treatment,
    schedule_treatment,
)


class TestDisposalProvisionalVsFinal:
    def _setup_disposal_case(self, api, verified_count=1, rejected_count=0):
        ctx = setup_community(contract_overrides={
            "scope_pest_types": ["BED_BUGS", "ROACHES"],
            "coverage_per_incident_cents": 20000,
        })
        unit, tech = ctx["unit"], ctx["technician"]
        _, case = complete_positive_inspection(unit["id"], tech)
        disposals = []
        for i in range(verified_count):
            d = get_success_data(api.create_furniture_disposal(
                case["id"], {"item_description": f"verified-{i}", "quantity": 1}, MANAGER))
            get_success_data(api.verify_furniture_disposal(d["id"], {"verified": True}, MANAGER))
            disposals.append(d)
        for i in range(rejected_count):
            d = get_success_data(api.create_furniture_disposal(
                case["id"], {"item_description": f"rejected-{i}", "quantity": 1}, MANAGER))
            get_success_data(api.verify_furniture_disposal(d["id"], {"verified": False}, MANAGER))
            disposals.append(d)
        return ctx, case

    def test_disposal_provisional_uses_planned_count(self, api):
        """PRD §3.7: "For `FURNITURE_DISPOSAL`, the provisional variant uses
        `planned_item_count` lines of 7995 each, while the final variant uses
        one line of 7995 per `VERIFIED` disposal of the linked case, excluding
        `PENDING` and `REJECTED` items."
        PRD §2.8: "Furniture disposal is billed per item at 7995 cents."
        PRD §2.8: "Every chargeback amount carries a 7.5 percent administrative
        surcharge applied line by line."

        Design: Difficulty/dual_variant_calc/chargeback_provisional_vs_final_disposal
        """
        ctx, case = self._setup_disposal_case(api, verified_count=1, rejected_count=1)
        cb = assess_chargeback(ctx["lease"]["id"], kind="FURNITURE_DISPOSAL",
                               planned_item_count=2, bed_bug_case_id=case["id"])
        assert cb["provisional_amount_cents"] == 17190, (
            "2 planned lines x round_half_up(7995 * 1.075) = 2 x 8595"
        )
        assert cb["status"] == "ASSESSED"

    def test_disposal_final_counts_verified_only_and_shifts_balance(self, api):
        """PRD §3.7: "For `FURNITURE_DISPOSAL`, the provisional variant uses
        `planned_item_count` lines of 7995 each, while the final variant uses
        one line of 7995 per `VERIFIED` disposal of the linked case, excluding
        `PENDING` and `REJECTED` items. The final variant alone appends an
        overage line — the excess of `actual_minutes` over `planned_minutes`,
        floored at zero, multiplied by 175 cents — when a
        `source_treatment_id` is set and that treatment is `COMPLETED`; the
        provisional variant never includes an overage line."
        PRD §3.7: "Billing — from `ASSESSED` or `UPHELD`, by a `BillingClerk` —
        computes `final_amount_cents` under the final variant, stamps
        `billed_at`, and replaces the provisional contribution with the final
        one in the lease balance."

        Design: Difficulty/dual_variant_calc/chargeback_provisional_vs_final_disposal
        """
        ctx, case = self._setup_disposal_case(api, verified_count=1, rejected_count=1)
        lease = ctx["lease"]
        cb = assess_chargeback(lease["id"], kind="FURNITURE_DISPOSAL",
                               planned_item_count=2, bed_bug_case_id=case["id"])
        billed = validate_success(api.bill_chargeback(cb["id"], CLERK))
        assert billed["status"] == "BILLED"
        assert billed["final_amount_cents"] == 8595, (
            "1 VERIFIED item only; the REJECTED sofa is excluded; no overage line"
        )
        assert billed["final_amount_cents"] != cb["provisional_amount_cents"]
        lease_after = validate_success(api.get_lease(lease["id"], CLERK))
        assert lease_after["outstanding_balance_cents"] == 8595


class TestCapCoverageNesting:
    def _setup_two_caps(self, api):
        ctx = setup_community(num_units=2, with_lease=False, with_resident=False,
                              contract_overrides={
                                  "scope_pest_types": ["ROACHES"],
                                  "coverage_per_incident_cents": 20000,
                              })
        u1, u2 = ctx["units"]
        lease1 = create_lease(u1["id"], chargeback_cap_cents=1000)
        lease2 = create_lease(u2["id"], chargeback_cap_cents=2150)
        return ctx, lease1, lease2

    def test_cap_clamps_below_pre_cap_amount(self, api):
        """PRD §3.7: "Each line's base is computed first; the vendor coverage
        credit — the smaller of the contract's `coverage_per_incident_cents`
        and 22000 — applies to the `REPEAT_INFESTATION` line base only; every
        line is then multiplied by 1.075 and rounded half-up to whole cents
        individually; the rounded lines are summed; and the total is clamped to
        at most the lease's `chargeback_cap_cents` and never below zero."

        Design: Difficulty/combinatorial_formula/chargeback_cap_coverage_nesting
        """
        ctx, lease1, _ = self._setup_two_caps(api)
        cb1 = assess_chargeback(lease1["id"], kind="REPEAT_INFESTATION")
        assert cb1["provisional_amount_cents"] == 1000, (
            "pre-cap round_half_up(max(0, 22000 - min(20000, 22000)) * 1.075) = 2150 "
            "clamped by cap 1000"
        )
        lease1_after = validate_success(api.get_lease(lease1["id"], CLERK))
        assert lease1_after["outstanding_balance_cents"] == 1000

    def test_cap_equal_to_pre_cap_amount_not_clamped(self, api):
        """PRD §3.7: "Each line's base is computed first; the vendor coverage
        credit — the smaller of the contract's `coverage_per_incident_cents`
        and 22000 — applies to the `REPEAT_INFESTATION` line base only; every
        line is then multiplied by 1.075 and rounded half-up to whole cents
        individually; the rounded lines are summed; and the total is clamped to
        at most the lease's `chargeback_cap_cents` and never below zero."

        Design: Difficulty/combinatorial_formula/chargeback_cap_coverage_nesting
        """
        ctx, _, lease2 = self._setup_two_caps(api)
        cb2 = assess_chargeback(lease2["id"], kind="REPEAT_INFESTATION")
        assert cb2["provisional_amount_cents"] == 2150, (
            "pre-cap 2150 equals cap 2150 exactly; the clamp is at-most, so the "
            "inclusive boundary does not reduce the amount"
        )
        lease2_after = validate_success(api.get_lease(lease2["id"], CLERK))
        assert lease2_after["outstanding_balance_cents"] == 2150


class TestPerLineRoundingOrder:
    def test_disposal_per_line_rounding_order(self, api):
        """PRD §3.7: "Per-line rounding before summation is mandatory — three
        disposal lines illustrate why: 7995 cents with the surcharge is
        8594.625 per line, rounding each line first yields three lines of 8595
        summing to 25785, whereas summing first and rounding once would yield
        25784; the pinned behavior is 25785."

        Design: Difficulty/combinatorial_formula/disposal_per_line_rounding_order
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        unit, tech, lease = ctx["unit"], ctx["technician"], ctx["lease"]
        _, case = complete_positive_inspection(unit["id"], tech)
        for name in ("mattress", "sofa", "bed frame"):
            d = get_success_data(api.create_furniture_disposal(
                case["id"], {"item_description": name, "quantity": 1}, MANAGER))
            get_success_data(api.verify_furniture_disposal(d["id"], {"verified": True}, MANAGER))

        cb = assess_chargeback(lease["id"], kind="FURNITURE_DISPOSAL",
                               planned_item_count=3, bed_bug_case_id=case["id"])
        billed = validate_success(api.bill_chargeback(cb["id"], CLERK))
        assert billed["final_amount_cents"] == 25785, (
            "3 x round_half_up(7995 * 1.075) = 3 x 8595; the sum-then-round "
            "value 25784 is the forbidden order"
        )

    def test_disposal_final_excludes_pending_and_rejected(self, api):
        """PRD §3.7: "the final variant uses one line of 7995 per `VERIFIED`
        disposal of the linked case, excluding `PENDING` and `REJECTED`
        items."
        PRD §2.8: "Furniture disposal is billed per item at 7995 cents."

        Design: Difficulty/combinatorial_formula/disposal_per_line_rounding_order
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        unit, tech, lease = ctx["unit"], ctx["technician"], ctx["lease"]
        _, case = complete_positive_inspection(unit["id"], tech)
        # 2 VERIFIED, 1 REJECTED, 1 PENDING
        for i in range(2):
            d = get_success_data(api.create_furniture_disposal(
                case["id"], {"item_description": f"v{i}", "quantity": 1}, MANAGER))
            get_success_data(api.verify_furniture_disposal(d["id"], {"verified": True}, MANAGER))
        d = get_success_data(api.create_furniture_disposal(
            case["id"], {"item_description": "rej", "quantity": 1}, MANAGER))
        get_success_data(api.verify_furniture_disposal(d["id"], {"verified": False}, MANAGER))
        get_success_data(api.create_furniture_disposal(
            case["id"], {"item_description": "pend", "quantity": 1}, MANAGER))

        cb = assess_chargeback(lease["id"], kind="FURNITURE_DISPOSAL",
                               planned_item_count=4, bed_bug_case_id=case["id"])
        billed = validate_success(api.bill_chargeback(cb["id"], CLERK))
        assert billed["final_amount_cents"] == 17190, (
            "2 VERIFIED items x round_half_up(7995 * 1.075) = 2 x 8595"
        )


class TestAssessmentGates:
    def test_unsigned_addendum_blocks_chargeback_assessment(self, api):
        """PRD §3.7: "Assessment requires the lease to be `ACTIVE`, else
        `ERR_LEASE_NOT_ACTIVE` (HTTP 409), and requires `pest_addendum_signed`
        true, else `ERR_LEASE_CLAUSE_MISSING` (HTTP 422)."

        Design: Corner/validations/unsigned_addendum_blocks_chargeback_assessment
        """
        ctx = setup_community(with_lease=False, with_resident=False)
        lease = create_lease(ctx["unit"]["id"], pest_addendum_signed=False)
        resp = api.create_chargeback(lease["id"], {"kind": "NON_COMPLIANCE_FEE"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_LEASE_CLAUSE_MISSING)

    def test_manual_late_fee_kind_rejected(self, api):
        """PRD §3.2: "A `LATE_FEE` may never be assessed manually; an attempt
        returns `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/manual_late_fee_kind_rejected
        """
        ctx = setup_community(with_resident=False)
        resp = api.create_chargeback(ctx["lease"]["id"], {"kind": "LATE_FEE"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_heat_surcharge_rejected_when_contract_includes_heat(self, api):
        """PRD §3.7: "a `HEAT_SURCHARGE` is assessable only when the contract's
        `heat_treatment_included` is false; a manual `LATE_FEE` is never
        permitted. Shape violations return `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/heat_surcharge_rejected_when_contract_includes_heat
        """
        ctx = setup_community(with_resident=False,
                              contract_overrides={"scope_pest_types": ["BED_BUGS"],
                                                  "heat_treatment_included": True})
        resp = api.create_chargeback(ctx["lease"]["id"], {"kind": "HEAT_SURCHARGE"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_ended_lease_rejects_assessment(self, api):
        """PRD §3.7: "Assessment requires the lease to be `ACTIVE`, else
        `ERR_LEASE_NOT_ACTIVE` (HTTP 409), and requires `pest_addendum_signed`
        true, else `ERR_LEASE_CLAUSE_MISSING` (HTTP 422)."
        PRD §3.2: "A lease begins `ACTIVE` and flips lazily to `ENDED` once the
        current logical date passes its `end_date`."

        Design: Corner/validations/ended_lease_rejects_assessment
        """
        ctx = setup_community(with_resident=False)
        set_clock("2027-08-01T00:00:00Z")
        resp = api.create_chargeback(ctx["lease"]["id"], {"kind": "NON_COMPLIANCE_FEE"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_LEASE_NOT_ACTIVE)


class TestDisputeWindow:
    def test_dispute_window_boundary_14_days(self, api):
        """PRD §3.7: "The resident of the lease may dispute an `ASSESSED`
        chargeback, supplying a `reason`, within 14 days of `assessed_at`
        inclusive; a later attempt returns `ERR_DISPUTE_WINDOW_EXPIRED`
        (HTTP 422)."
        PRD §2.4: "At startup, before any clock call, the logical clock reads
        exactly 2026-08-01T00:00:00Z."

        Design: Corner/validations/dispute_window_boundary_14_days
        """
        ctx = setup_community(num_units=2, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        u1, u2 = ctx["units"]
        lease1 = create_lease(u1["id"])
        lease2 = create_lease(u2["id"])
        res1 = create_resident(u1["id"], lease1["id"], email="r1@x.com")
        res2 = create_resident(u2["id"], lease2["id"], full_name="R Two", email="r2@x.com")
        cb1 = assess_chargeback(lease1["id"])
        cb2 = assess_chargeback(lease2["id"])

        set_clock("2026-08-15T00:00:00Z")
        disputed = validate_success(
            api.dispute_chargeback(cb1["id"], {"reason": "exactly 14 days"},
                                   resident_headers_for(res1))
        )
        assert disputed["status"] == "DISPUTED"

        set_clock("2026-08-16T00:00:00Z")
        resp = api.dispute_chargeback(cb2["id"], {"reason": "15 days later"},
                                      resident_headers_for(res2))
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED)


class TestDisputeStateGate:
    def test_dispute_from_billed_returns_invalid_state(self, api):
        """PRD §3.7: "The resident of the lease may dispute an `ASSESSED`
        chargeback, supplying a `reason`, within 14 days of `assessed_at`
        inclusive; a later attempt returns `ERR_DISPUTE_WINDOW_EXPIRED`
        (HTTP 422)."
        PRD §2.4: "a transition that is simply not defined from the entity's
        current non-terminal state is rejected with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/chargeback_dispute_from_billed_returns_invalid_state
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["ROACHES"]})
        cb = assess_chargeback(ctx["lease"]["id"])
        validate_success(api.bill_chargeback(cb["id"], CLERK))
        resp = api.dispute_chargeback(cb["id"], {"reason": "too late to dispute a bill"},
                                      resident_headers_for(ctx["resident"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPaymentAmount:
    def test_payment_amount_must_equal_final(self, api):
        """PRD §3.7: "Recording payment requires the submitted `amount_cents`
        to equal `final_amount_cents` exactly; a mismatch returns
        `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). A matching payment moves the
        chargeback to `PAID`, stamps `paid_at`, and zeroes its contribution to
        the balance."

        Design: Corner/validations/payment_amount_must_equal_final
        """
        ctx = setup_community(with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        cb = assess_chargeback(ctx["lease"]["id"])
        billed = validate_success(api.bill_chargeback(cb["id"], CLERK))
        assert billed["final_amount_cents"] == 16125

        resp = api.record_payment(cb["id"], {"amount_cents": 16124}, CLERK)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

        paid = validate_success(api.record_payment(cb["id"], {"amount_cents": 16125}, CLERK))
        assert paid["status"] == "PAID"


class TestSegregationAndOcc:
    def test_segregation_of_duties_same_operator_rejected(self, api):
        """PRD §3.7: "A `ComplianceOfficer` then resolves the dispute with a
        `resolution` of `UPHELD` or `WAIVED`, under the OCC guard of §2.6 via
        `expected_chargeback_version`, and under segregation of duties: the
        resolver's `X-User-ID` must differ from the chargeback's `assessed_by`,
        else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_same_operator_rejected
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["ROACHES"]})
        cb = assess_chargeback(ctx["lease"]["id"], clerk_user_id="clerk-1")
        disputed = dispute_chargeback(cb["id"], ctx["resident"])
        # The assessing clerk's id holds the ComplianceOfficer role here: the
        # role gate passes, the segregation-of-duties check must reject.
        resp = api.resolve_dispute(
            cb["id"],
            {"resolution": "UPHELD", "expected_chargeback_version": disputed["version"]},
            make_compliance_officer_headers("clerk-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_occ_stale_resolve_returns_412(self, api):
        """PRD §2.6: "Resolving a chargeback dispute requires the request to
        carry `expected_chargeback_version`, holding the chargeback `version`
        the deciding officer last observed. A mismatch with the chargeback's
        current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412); the
        officer's view of the dispute is stale and must be refreshed."

        Design: Corner/cross_cutting_layers/occ_stale_resolve_returns_412
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["ROACHES"]})
        cb = assess_chargeback(ctx["lease"]["id"])
        disputed = dispute_chargeback(cb["id"], ctx["resident"])
        officer = make_compliance_officer_headers("officer-9")

        resp = api.resolve_dispute(
            cb["id"],
            {"resolution": "UPHELD", "expected_chargeback_version": disputed["version"] - 1},
            officer,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        resolved = validate_success(
            api.resolve_dispute(
                cb["id"],
                {"resolution": "UPHELD", "expected_chargeback_version": disputed["version"]},
                officer,
            )
        )
        assert resolved["status"] == "UPHELD"


class TestLeaseBalanceInvariant:
    def test_lease_balance_assess_waive_invariant(self, api):
        """PRD §3.2: "`outstanding_balance_cents` is the sum of
        `provisional_amount_cents` over the lease's chargebacks in `ASSESSED`
        or `DISPUTED`, plus the sum of `final_amount_cents` over chargebacks in
        `UPHELD` or `BILLED`; chargebacks that are `WAIVED` or `PAID`
        contribute zero."
        PRD §3.7: "Resolution stamps `resolved_by` and `resolution`; `UPHELD`
        contributes zero to the lease balance until billed, while `WAIVED`
        contributes zero outright and restores the balance."

        Design: Difficulty/compensating_invariant/lease_balance_assess_waive_invariant
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["ROACHES"]})
        lease, resident = ctx["lease"], ctx["resident"]
        bal0 = validate_success(api.get_lease(lease["id"], CLERK))
        assert bal0["outstanding_balance_cents"] == 0

        cb = assess_chargeback(lease["id"], kind="NON_COMPLIANCE_FEE")
        assert cb["provisional_amount_cents"] == 16125
        bal1 = validate_success(api.get_lease(lease["id"], CLERK))
        assert bal1["outstanding_balance_cents"] == 16125

        disputed = dispute_chargeback(cb["id"], resident, reason="prep was done")
        resolved = validate_success(api.resolve_dispute(
            cb["id"],
            {"resolution": "WAIVED", "expected_chargeback_version": disputed["version"]},
            make_compliance_officer_headers("officer-9"),
        ))
        assert resolved["status"] == "WAIVED"
        bal2 = validate_success(api.get_lease(lease["id"], CLERK))
        assert bal2["outstanding_balance_cents"] == 0
        assert bal2["delinquent"] is False

    def test_waive_restores_balance_to_exactly_prior_value(self, api):
        """PRD §3.2: "`outstanding_balance_cents` is the sum of
        `provisional_amount_cents` over the lease's chargebacks in `ASSESSED`
        or `DISPUTED`, plus the sum of `final_amount_cents` over chargebacks in
        `UPHELD` or `BILLED`; chargebacks that are `WAIVED` or `PAID`
        contribute zero."
        PRD §3.7: "Resolution stamps `resolved_by` and `resolution`; `UPHELD`
        contributes zero to the lease balance until billed, while `WAIVED`
        contributes zero outright and restores the balance."

        Design: Difficulty/compensating_invariant/lease_balance_assess_waive_invariant
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["ROACHES"]})
        lease, resident = ctx["lease"], ctx["resident"]
        # A surviving chargeback keeps the balance non-zero through the cycle,
        # so the exact-restoration assertion is not trivially zero-to-zero.
        keep = assess_chargeback(lease["id"])
        target = assess_chargeback(lease["id"])
        before = validate_success(api.get_lease(lease["id"], CLERK))
        assert before["outstanding_balance_cents"] == 32250

        disputed = dispute_chargeback(target["id"], resident, reason="prep was done")
        validate_success(api.resolve_dispute(
            target["id"],
            {"resolution": "WAIVED", "expected_chargeback_version": disputed["version"]},
            make_compliance_officer_headers("officer-9"),
        ))
        after = validate_success(api.get_lease(lease["id"], CLERK))
        assert after["outstanding_balance_cents"] == 16125, (
            "the waived chargeback's contribution is fully unwound; only the "
            "surviving 16125 assessment remains"
        )

    def test_lease_balance_mixed_status_composition(self, api):
        """PRD §3.2: "`outstanding_balance_cents` is the sum of
        `provisional_amount_cents` over the lease's chargebacks in `ASSESSED`
        or `DISPUTED`, plus the sum of `final_amount_cents` over chargebacks in
        `UPHELD` or `BILLED`; chargebacks that are `WAIVED` or `PAID`
        contribute zero. The lease's `delinquent` flag is true exactly when the
        outstanding balance is greater than zero."

        Design: Corner/calculations/lease_balance_mixed_status_composition
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["ROACHES"]})
        lease, resident = ctx["lease"], ctx["resident"]
        clerk = make_billing_clerk_headers("clerk-1")

        cb1 = assess_chargeback(lease["id"])  # stays ASSESSED
        cb2 = assess_chargeback(lease["id"])  # -> PAID
        validate_success(api.bill_chargeback(cb2["id"], clerk))
        validate_success(api.record_payment(cb2["id"], {"amount_cents": 16125}, clerk))
        cb3 = assess_chargeback(lease["id"])  # -> WAIVED
        disputed3 = dispute_chargeback(cb3["id"], resident)
        validate_success(api.resolve_dispute(
            cb3["id"],
            {"resolution": "WAIVED", "expected_chargeback_version": disputed3["version"]},
            make_compliance_officer_headers("officer-9"),
        ))
        cb4 = assess_chargeback(lease["id"])  # -> BILLED
        validate_success(api.bill_chargeback(cb4["id"], clerk))

        bal = validate_success(api.get_lease(lease["id"], CLERK))
        assert bal["outstanding_balance_cents"] == 32250, (
            "cb1 ASSESSED provisional 16125 + cb4 BILLED final 16125; "
            "cb2 PAID and cb3 WAIVED contribute 0"
        )
        assert bal["delinquent"] is True
        cbs = get_success_data(api.list_lease_chargebacks(lease["id"], CLERK))
        assert not any(c["kind"] == "LATE_FEE" for c in cbs), "32250 < 50000"


class TestLateFeeCascadeFromPrepFailure:
    def test_prep_failure_fires_chargeback_and_late_fee(self, api):
        """PRD §3.4: "A non-compliant verification moves it to `NON_COMPLIANT`
        and fires a second cascade. Link one: if the unit has an `ACTIVE` lease
        with `pest_addendum_signed` true, the system auto-creates a
        `NON_COMPLIANCE_FEE` chargeback in `ASSESSED` whose
        `source_treatment_id` points at this treatment. Link two: the new
        chargeback recomputes the lease's `outstanding_balance_cents` and
        `delinquent`. Link three: if that recompute crosses the 50000-cent
        late-fee threshold upward under the guard of §3.2, a `LATE_FEE`
        chargeback in `ASSESSED` follows and the balance recomputes again."
        PRD §3.2: "A late-fee trigger runs after every upward recompute of the
        balance: when the outstanding balance reaches at least 50000 cents and
        the lease has no `LATE_FEE` chargeback in `ASSESSED`, `DISPUTED`,
        `UPHELD`, or `BILLED`, the system creates a `LATE_FEE` chargeback in
        `ASSESSED` — base 5000 cents before surcharge — and recomputes the
        balance once more."

        Design: Difficulty/transitive_cascade/cascade_prep_failure_to_late_fee
        """
        ctx = setup_community(contract_overrides={
            "scope_pest_types": ["ROACHES"],
            "coverage_per_incident_cents": 20000,
            "heat_treatment_included": False,
        })
        tech = ctx["technician"]
        # Second unit with a lease capped at 40000 so the heat surcharge clamps
        # to 40000 (below the 50000 late-fee threshold, so no late fee yet).
        u2 = create_unit(ctx["property"]["id"], unit_number="102", floor=1, stack_index=2)
        lease2 = create_lease(u2["id"], chargeback_cap_cents=40000)
        res2 = create_resident(u2["id"], lease2["id"], full_name="R Two", email="r2@x.com")
        cb_heat = assess_chargeback(lease2["id"], kind="HEAT_SURCHARGE")
        assert cb_heat["provisional_amount_cents"] == 40000, (
            "cap clamps round_half_up(65000 * 1.075) = 69875; no late fee at 40000 < 50000"
        )

        tr = setup_prep_acknowledged_treatment(u2["id"], res2, tech["id"])
        failed = validate_success(api.verify_prep(tr["id"], {"compliant": False}, MANAGER))
        assert failed["status"] == "NON_COMPLIANT"

        cbs = get_success_data(api.list_lease_chargebacks(lease2["id"], CLERK))
        nc = [c for c in cbs if c["kind"] == "NON_COMPLIANCE_FEE"]
        lf = [c for c in cbs if c["kind"] == "LATE_FEE"]
        assert len(nc) == 1 and nc[0]["provisional_amount_cents"] == 16125
        assert nc[0]["source_treatment_id"] == tr["id"]
        assert len(lf) == 1 and lf[0]["provisional_amount_cents"] == 5375, (
            "LATE_FEE created only because the balance crossed 50000 upward"
        )
        bal = validate_success(api.get_lease(lease2["id"], CLERK))
        assert bal["outstanding_balance_cents"] == 61500, "40000 + 16125 + 5375"
        assert bal["delinquent"] is True

    def test_late_fee_guard_allows_at_most_one_live_late_fee(self, api):
        """PRD §3.2: "A late-fee trigger runs after every upward recompute of
        the balance: when the outstanding balance reaches at least 50000 cents
        and the lease has no `LATE_FEE` chargeback in `ASSESSED`, `DISPUTED`,
        `UPHELD`, or `BILLED`, the system creates a `LATE_FEE` chargeback in
        `ASSESSED` — base 5000 cents before surcharge — and recomputes the
        balance once more. The threshold crossing is inclusive, and the
        trigger's guard means at most one live late fee per lease."

        Design: Difficulty/transitive_cascade/cascade_prep_failure_to_late_fee
        """
        ctx = setup_community(contract_overrides={
            "scope_pest_types": ["ROACHES"],
            "heat_treatment_included": False,
        })
        u = create_unit(ctx["property"]["id"], unit_number="102", floor=1, stack_index=2)
        lease = create_lease(u["id"], chargeback_cap_cents=100000)
        # Three HEAT_SURCHARGEs of 69875 each: the first crosses 50000 (one
        # late fee), later ones must not add another live LATE_FEE.
        assess_chargeback(lease["id"], kind="HEAT_SURCHARGE")
        assess_chargeback(lease["id"], kind="HEAT_SURCHARGE")
        assess_chargeback(lease["id"], kind="HEAT_SURCHARGE")
        cbs = get_success_data(api.list_lease_chargebacks(lease["id"], CLERK))
        late_fees = [c for c in cbs if c["kind"] == "LATE_FEE"]
        assert len(late_fees) == 1, "at most one live late fee per lease"
        assert late_fees[0]["provisional_amount_cents"] == 5375
        bal = validate_success(api.get_lease(lease["id"], CLERK))
        assert bal["outstanding_balance_cents"] == 3 * 69875 + 5375
