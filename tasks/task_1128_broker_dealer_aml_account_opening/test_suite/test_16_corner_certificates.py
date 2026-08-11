"""Corner queue: certificate deposit pipeline, holds, duplicates, decision OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_deposit,
    api_client,
    create_deposit,
    get_deposit,
    run_daily_sweep,
    set_clock,
    setup_deposit_in_clearance_hold,
    setup_open_account,
    setup_ready_deposit,
    validate_error,
    validate_success,
)


class TestCertHoldLowPricedVsRegularReleaseTiming:
    def test_low_priced_holds_10_regular_holds_5_inclusive_release(self, api):
        """PRD §3.8: "Entering `CLEARANCE_HOLD` stamps `hold_release_date`: the hold
        lasts ten calendar days for a low-priced certificate and five otherwise".
        PRD §2.5: "any deposit in `CLEARANCE_HOLD` whose `hold_release_date` is on or
        before the clock date becomes `READY_TO_ACCEPT` — release is inclusive, so a
        clock date equal to the release date releases the hold."
        Both deposits enter CLEARANCE_HOLD on 2026-05-01: the regular cert releases at
        the 2026-05-06 sweep while the low-priced cert stays held until 2026-05-11.

        Design: Corner/calculations/cert_hold_low_priced_vs_regular_release_timing
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_open_account()
        account_id = ctx["account"]["id"]
        dep_l = create_deposit(
            account_id, certificate_number="CN-C03L", cusip="CUSIPL3",
            security_name="C3 Low", quantity=100, unit_price=2.00,
        )
        dep_r = create_deposit(
            account_id, certificate_number="CN-C03R", cusip="CUSIPR3",
            security_name="C3 Reg", quantity=10, unit_price=40.00,
        )
        for dep in (dep_l, dep_r):
            advance_deposit(dep["id"])
            advance_deposit(dep["id"])
        held_l = advance_deposit(dep_l["id"])
        held_r = advance_deposit(dep_r["id"])
        assert held_l["hold_release_date"] == "2026-05-11", (
            f"low-priced hold is 10 days, got {held_l['hold_release_date']}"
        )
        assert held_r["hold_release_date"] == "2026-05-06", (
            f"regular hold is 5 days, got {held_r['hold_release_date']}"
        )

        set_clock("2026-05-06T00:00:00Z")
        sweep = run_daily_sweep()
        assert sweep["holds_released"] == 1, (
            f"only the regular cert releases on 2026-05-06, got {sweep['holds_released']}"
        )
        assert get_deposit(dep_l["id"])["status"] == "CLEARANCE_HOLD"
        assert get_deposit(dep_r["id"])["status"] == "READY_TO_ACCEPT"


class TestRestrictiveLegendExtendsHold:
    def test_legend_adds_five_days_and_release_is_inclusive(self, api):
        """PRD §3.8: "the hold lasts ten calendar days for a low-priced certificate and
        five otherwise, plus five additional days when `has_restrictive_legend` is
        set".
        PRD §2.5: "release is inclusive, so a clock date equal to the release date
        releases the hold."
        A regular-priced legend cert entering CLEARANCE_HOLD 2026-05-01 releases
        2026-05-11: still held on 2026-05-10, released by the sweep on 2026-05-11.

        Design: Corner/calculations/restrictive_legend_extends_hold
        """
        ctx = setup_deposit_in_clearance_hold(
            certificate_number="CN-C04", cusip="CUSIPC4", security_name="C4 Corp",
            quantity=10, unit_price=40.00, has_restrictive_legend=True,
        )
        deposit = ctx["deposit"]
        assert deposit["hold_release_date"] == "2026-05-11", (
            f"5 regular + 5 legend = 10 days from 2026-05-01, "
            f"got {deposit['hold_release_date']}"
        )

        set_clock("2026-05-10T00:00:00Z")
        sweep = run_daily_sweep()
        assert sweep["holds_released"] == 0, "day 9 of the hold: still held"

        set_clock("2026-05-11T00:00:00Z")
        sweep = run_daily_sweep()
        assert sweep["holds_released"] == 1, "inclusive release on the release date"
        assert get_deposit(deposit["id"])["status"] == "READY_TO_ACCEPT"


class TestDepositDecisionBeforeReadyRejected:
    def test_decision_from_authenticity_review_rejected(self, api):
        """PRD §3.8: "Deciding a deposit belongs to a `ComplianceOfficer` and is
        possible only from `READY_TO_ACCEPT` (`ERR_DEPOSIT_NOT_DECIDABLE` otherwise)."
        The correct OCC version does not rescue a decision attempted from
        AUTHENTICITY_REVIEW.

        Design: Corner/state_machines/deposit_decision_before_ready_rejected
        """
        ctx = setup_open_account()
        deposit = create_deposit(
            ctx["account"]["id"], certificate_number="CN-S13", cusip="CUSIPS13",
            security_name="S13 Corp", quantity=5, unit_price=20.00,
        )
        advance_deposit(deposit["id"])
        in_review = advance_deposit(deposit["id"])
        assert in_review["status"] == "AUTHENTICITY_REVIEW"

        resp = api_client.decide_deposit(
            deposit["id"],
            {"expected_deposit_version": in_review["version"], "outcome": "ACCEPT"},
            TEST_USERS["officer_headers"],
        )
        error = validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_DECIDABLE)
        assert error["error_id"] == "ERR_DEPOSIT_NOT_DECIDABLE"
        assert resp.status_code == 409


class TestDuplicateCertificateNumberPureConstraint:
    def test_second_in_flight_deposit_same_number_rejected(self, api):
        """PRD §3.8: "the number must be unique among deposits not in `REJECTED` or
        `REJECTED_SUSPICIOUS`, else `ERR_DUPLICATE_CERTIFICATE_NUMBER`."
        The certificate number is NOT on the lost/stolen registry, so the pure
        uniqueness constraint fires with 409.

        Design: Corner/validations/duplicate_certificate_number_pure_constraint
        """
        ctx = setup_open_account()
        account_id = ctx["account"]["id"]
        create_deposit(
            account_id, certificate_number="CN-V05", cusip="CUSIPV5",
            security_name="V5 Corp", quantity=5, unit_price=20.00,
        )
        resp = api_client.create_deposit(
            account_id,
            {
                "certificate_number": "CN-V05",
                "cusip": "CUSIPV5",
                "security_name": "V5 Corp",
                "quantity": 6,
                "unit_price": 20.00,
            },
            TEST_USERS["ops_headers"],
        )
        error = validate_error(resp, ApiErrorId.ERR_DUPLICATE_CERTIFICATE_NUMBER)
        assert error["error_id"] == "ERR_DUPLICATE_CERTIFICATE_NUMBER"
        assert resp.status_code == 409


class TestOccCertDecisionStaleAfterSupplement:
    def test_stale_decision_rejected_after_supplement_fresh_decision_accepted(self, api):
        """PRD §2.6: "**Certificate deposit decisions** require
        `expected_deposit_version`, the client's last observed `version` of the
        deposit. Because attaching a supplement legitimately advances the deposit's
        version while it sits decidable, a reviewer whose observation predates that
        bump is refused with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.8: "**Accept** moves `READY_TO_ACCEPT` → `ACCEPTED` and clears the
        linked deposit transaction from `FLAGGED` to `CLEARED`."

        Design: Corner/cross_cutting_layers/occ_cert_decision_stale_after_supplement
        """
        ctx = setup_ready_deposit(
            certificate_number="CN-X02", cusip="CUSIPX2", security_name="X2 Corp",
            quantity=5, unit_price=20.00,
        )
        deposit = ctx["deposit"]
        observed = deposit["version"]

        resp = api_client.supplement_deposit(
            deposit["id"], {"note": "transfer agent confirmed"}, TEST_USERS["ops_headers"]
        )
        supplemented = validate_success(resp)
        assert supplemented["version"] == observed + 1, (
            "a supplement changes no state but increments the deposit's version"
        )

        resp = api_client.decide_deposit(
            deposit["id"],
            {"expected_deposit_version": observed, "outcome": "ACCEPT"},
            TEST_USERS["officer_headers"],
        )
        error = validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert error["error_id"] == "ERR_STALE_VERSION"
        assert resp.status_code == 412

        fresh = get_deposit(deposit["id"])
        resp = api_client.decide_deposit(
            deposit["id"],
            {"expected_deposit_version": fresh["version"], "outcome": "ACCEPT"},
            TEST_USERS["officer_headers"],
        )
        accepted = validate_success(resp)
        assert accepted["status"] == "ACCEPTED"

        resp = api_client.get_transaction(
            deposit["transaction_id"], TEST_USERS["ops_headers"]
        )
        txn = validate_success(resp)
        assert txn["status"] == "CLEARED", (
            f"accept must clear the linked deposit transaction, got {txn['status']}"
        )
