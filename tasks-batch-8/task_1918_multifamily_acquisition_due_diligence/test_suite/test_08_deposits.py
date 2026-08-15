"""Security deposit reconciliation: accrual variants, anniversary boundary, disputes."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_audited_lease,
    add_lease,
    add_rent_roll_entry,
    add_unit,
    create_deposit_payload,
    create_kicked_off_acquisition,
    get_acquisition,
    get_success_data,
    setup_verified_unit,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
EO1 = TEST_USERS["escrow_officer_headers"]


def _audited_unit_with_deposit(api, *, interest_accrual_method, lease_start,
                                lease_end, stated, move_in=None):
    """Kicked-off acquisition (given accrual method) + audited lease +
    RECORDED deposit. Returns (acq, lease, deposit)."""
    acq = create_kicked_off_acquisition(
        property_name="Deposit Deal",
        interest_accrual_method=interest_accrual_method)
    unit = add_unit(acq["id"])
    lease = add_lease(unit["id"], lease_start_date=lease_start,
                      lease_end_date=lease_end)
    add_rent_roll_entry(unit["id"],
                        move_in_date=move_in or lease_start,
                        reported_deposit_cents=stated)
    get_success_data(api.audit_lease_file(lease["id"], ANALYST))
    dep = get_success_data(api.create_deposit(
        create_deposit_payload(lease["id"], seller_stated_amount_cents=stated),
        ANALYST), 201)
    return acq, lease, dep


class TestDepositInterestMethodsDiverge:
    def test_daily_accrual_vs_simple_annual_on_identical_inputs(self, api):
        """PRD §3.10: "Under the acquisition's default `DAILY_ACCRUAL` method,
        the accrual is `verified_amount_cents` times `annual_interest_rate`
        times the day count divided by 365, rounded half up — interest accrues
        from day one. Under `SIMPLE_ANNUAL`, only whole elapsed anniversary
        years accrue: the whole-year count is the day count divided by 365
        rounded down, and the accrual is `verified_amount_cents` times
        `annual_interest_rate` times that whole-year count, rounded half up —
        so a 364-day-old deposit accrues nothing while a 365-day-old deposit
        accrues one full year."
        PRD §3.10: "The entry's `variance_cents` is `verified_amount_cents`
        plus `accrued_interest_cents` minus `seller_stated_amount_cents`. A
        zero variance lands the entry `RECONCILED`... A nonzero variance lands
        the entry `DISPUTED` instead..."

        Design: Difficulty/dual_variant_calc/deposit_interest_methods_diverge
        """
        # 376 elapsed days (2025-09-01 .. 2026-09-12): DAILY accrues
        # round(150000 x 0.02 x 376/365) = 3090; SIMPLE accrues one year = 3000.
        acq_a, lease_a, dep_a = _audited_unit_with_deposit(
            api, interest_accrual_method="DAILY_ACCRUAL",
            lease_start="2025-09-01T00:00:00Z", lease_end="2027-08-31T00:00:00Z",
            stated=150_000)
        acq_b, lease_b, dep_b = _audited_unit_with_deposit(
            api, interest_accrual_method="SIMPLE_ANNUAL",
            lease_start="2025-09-01T00:00:00Z", lease_end="2027-08-31T00:00:00Z",
            stated=150_000)

        rec_a = validate_success(api.reconcile_deposit(dep_a["id"], ANALYST))
        rec_b = validate_success(api.reconcile_deposit(dep_b["id"], ANALYST))
        assert rec_a["accrued_interest_cents"] == 3_090
        assert rec_a["variance_cents"] == 3_090
        assert rec_a["status"] == "DISPUTED"
        assert rec_b["accrued_interest_cents"] == 3_000, (
            "floor(376/365) = 1 whole anniversary year"
        )
        assert rec_b["variance_cents"] == 3_000
        assert rec_b["status"] == "DISPUTED"
        assert rec_a["accrued_interest_cents"] - rec_b["accrued_interest_cents"] == 90

    def test_accrual_methods_diverge_by_exactly_90_cents(self, api):
        """PRD §3.10: "Accrued interest runs from the lease's
        `lease_start_date` to the acquisition's `closing_date`, the day count
        being the calendar days between those dates with the closing date
        exclusive of the start."
        PRD §3.10: "When `interest_required` is false, `accrued_interest_cents`
        is zero."

        Design: Difficulty/dual_variant_calc/deposit_interest_methods_diverge
        """
        acq_a, _, dep_a = _audited_unit_with_deposit(
            api, interest_accrual_method="DAILY_ACCRUAL",
            lease_start="2025-09-01T00:00:00Z", lease_end="2027-08-31T00:00:00Z",
            stated=150_000)
        acq_b, _, dep_b = _audited_unit_with_deposit(
            api, interest_accrual_method="SIMPLE_ANNUAL",
            lease_start="2025-09-01T00:00:00Z", lease_end="2027-08-31T00:00:00Z",
            stated=150_000)
        rec_a = get_success_data(api.reconcile_deposit(dep_a["id"], ANALYST))
        rec_b = get_success_data(api.reconcile_deposit(dep_b["id"], ANALYST))
        # Identical lease/deposit inputs diverge by exactly 90 cents.
        assert (rec_a["accrued_interest_cents"], rec_b["accrued_interest_cents"]) == (3_090, 3_000)
        assert rec_a["verified_amount_cents"] == 150_000
        assert rec_b["verified_amount_cents"] == 150_000


class TestDepositInterestExactAnniversaryBoundary:
    def test_365_day_lease_accrues_one_year_364_accrues_zero(self, api):
        """PRD §3.10: "Under `SIMPLE_ANNUAL`, only whole elapsed anniversary
        years accrue: the whole-year count is the day count divided by 365
        rounded down, and the accrual is `verified_amount_cents` times
        `annual_interest_rate` times that whole-year count, rounded half up —
        so a 364-day-old deposit accrues nothing while a 365-day-old deposit
        accrues one full year."

        Design: Difficulty/boundary_precision_check/deposit_interest_exact_anniversary_boundary
        """
        acq, lease1, dep1 = _audited_unit_with_deposit(
            api, interest_accrual_method="SIMPLE_ANNUAL",
            lease_start="2025-09-12T00:00:00Z", lease_end="2027-09-11T00:00:00Z",
            stated=153_000, move_in="2025-09-12T00:00:00Z")
        # Second unit on the same acquisition: 364 elapsed days at closing.
        unit2 = add_unit(acq["id"], unit_number="2B", floor_plan="2BR",
                         sqft=900, market_rent_cents=180000)
        lease2 = add_lease(unit2["id"], resident_name="R Two",
                           lease_start_date="2025-09-13T00:00:00Z",
                           lease_end_date="2027-09-12T00:00:00Z")
        add_rent_roll_entry(unit2["id"], reported_resident_name="R Two",
                            reported_deposit_cents=150_000,
                            move_in_date="2025-09-13T00:00:00Z")
        get_success_data(api.audit_lease_file(lease2["id"], ANALYST))
        dep2 = get_success_data(api.create_deposit(
            create_deposit_payload(lease2["id"],
                                   seller_stated_amount_cents=150_000),
            ANALYST), 201)

        rec1 = validate_success(api.reconcile_deposit(dep1["id"], ANALYST))
        rec2 = validate_success(api.reconcile_deposit(dep2["id"], ANALYST))
        assert rec1["accrued_interest_cents"] == 3_000, (
            "365 days: floor(365/365) = 1 whole year; the anniversary counts"
        )
        assert rec1["status"] == "RECONCILED"
        assert rec2["accrued_interest_cents"] == 0, "364 days: floor(364/365) = 0"
        assert rec2["status"] == "RECONCILED"

    def test_anniversary_day_itself_counts(self, api):
        """PRD §3.10: "the day count being the calendar days between those
        dates with the closing date exclusive of the start."
        PRD §3.10: "so a 364-day-old deposit accrues nothing while a
        365-day-old deposit accrues one full year."

        Design: Difficulty/boundary_precision_check/deposit_interest_exact_anniversary_boundary
        """
        acq, _, dep1 = _audited_unit_with_deposit(
            api, interest_accrual_method="SIMPLE_ANNUAL",
            lease_start="2025-09-12T00:00:00Z", lease_end="2027-09-11T00:00:00Z",
            stated=153_000, move_in="2025-09-12T00:00:00Z")
        unit2 = add_unit(acq["id"], unit_number="2B", floor_plan="2BR",
                         sqft=900, market_rent_cents=180000)
        lease2 = add_lease(unit2["id"], resident_name="R Two",
                           lease_start_date="2025-09-13T00:00:00Z",
                           lease_end_date="2027-09-12T00:00:00Z")
        add_rent_roll_entry(unit2["id"], reported_resident_name="R Two",
                            reported_deposit_cents=150_000,
                            move_in_date="2025-09-13T00:00:00Z")
        get_success_data(api.audit_lease_file(lease2["id"], ANALYST))
        dep2 = get_success_data(api.create_deposit(
            create_deposit_payload(lease2["id"],
                                   seller_stated_amount_cents=150_000),
            ANALYST), 201)

        rec1 = get_success_data(api.reconcile_deposit(dep1["id"], ANALYST))
        rec2 = get_success_data(api.reconcile_deposit(dep2["id"], ANALYST))
        assert rec1["accrued_interest_cents"] == 3_000
        assert rec2["accrued_interest_cents"] == 0
        # Both seller statements matched principal + accrued interest: variance 0.
        assert rec1["variance_cents"] == 0
        assert rec2["variance_cents"] == 0


class TestDepositReconcileGates:
    def test_reconcile_requires_audited_lease(self, api):
        """PRD §3.10: "Reconciliation by an analyst first requires the lease to
        have completed audit — status `AUDITED`, `RESOLVED`, or `WAIVED`, else
        `ERR_LEASE_NOT_AUDITED`."

        Design: Corner/validations/reconcile_requires_audited_lease
        """
        acq = create_kicked_off_acquisition(property_name="Rec Gate")
        unit = add_unit(acq["id"])
        lease = add_lease(unit["id"])  # UPLOADED, never audited
        dep = get_success_data(api.create_deposit(
            create_deposit_payload(lease["id"]), ANALYST), 201)

        resp = api.reconcile_deposit(dep["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_LEASE_NOT_AUDITED, 409)

    def test_queue_escrow_requires_pre_closing(self, api):
        """PRD §3.10: "Once the acquisition reaches `PRE_CLOSING` — queueing
        earlier is rejected with `ERR_ACQUISITION_NOT_PRE_CLOSING` — an
        `EscrowOfficer` queues each reconciled entry for escrow, moving it to
        `ESCROW_QUEUED`."

        Design: Corner/validations/queue_escrow_requires_pre_closing
        """
        ctx = setup_verified_unit(property_name="Escrow Gate")
        resp = api.queue_deposit_escrow(ctx["deposit"]["id"], EO1)
        validate_error(resp, ApiErrorId.ERR_ACQUISITION_NOT_PRE_CLOSING, 409)


class TestDepositDisputeResolution:
    def test_deposit_dispute_resolve_must_zero_variance(self, api):
        """PRD §3.10: "Resolving a dispute supplies an
        `adjusted_verified_amount_cents` and an optional `note`; the entry's
        `verified_amount_cents` is replaced with the adjusted value, the
        variance is recomputed under the same formula, and the resolution
        succeeds only when the recomputed variance is exactly zero — otherwise
        it is rejected with `ERR_DEPOSIT_VARIANCE_UNRESOLVED`. A successful
        resolution moves the entry from `DISPUTED` to `RECONCILED` and
        recomputes the unit flag and both acquisition rollups."
        PRD §3.10: "The acquisition's `deposit_variance_cents` is the sum of
        `variance_cents` over entries in `DISPUTED` status."
        PRD §3.9: "any deposit ledger entry stands `DISPUTED`" forces BLOCKED.

        Design: Corner/validations/deposit_dispute_resolve_must_zero_variance
        """
        acq = create_kicked_off_acquisition(property_name="Var Deal")
        unit = add_unit(acq["id"])
        lease = add_audited_lease(unit["id"], reported_deposit_cents=153_091)
        dep = get_success_data(api.create_deposit(
            create_deposit_payload(lease["id"],
                                   seller_stated_amount_cents=153_091),
            ANALYST), 201)

        disputed = get_success_data(api.reconcile_deposit(dep["id"], ANALYST))
        assert disputed["status"] == "DISPUTED"
        assert disputed["variance_cents"] == -1, (
            "150000 verified + 3090 interest - 153091 stated"
        )
        acq_now = get_acquisition(acq["id"])
        assert acq_now["deposit_variance_cents"] == -1
        assert acq_now["readiness_posture"] == "BLOCKED"

        resp = api.resolve_deposit_dispute(
            dep["id"], {"adjusted_verified_amount_cents": 150_000,
                        "note": "no change"}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_VARIANCE_UNRESOLVED, 409)

        resolved = validate_success(api.resolve_deposit_dispute(
            dep["id"], {"adjusted_verified_amount_cents": 150_001,
                        "note": "seller found 1 cent"}, ANALYST))
        assert resolved["status"] == "RECONCILED"
        assert resolved["variance_cents"] == 0
        acq_now = get_acquisition(acq["id"])
        assert acq_now["deposit_variance_cents"] == 0
        assert acq_now["readiness_posture"] == "ON_TRACK"
