"""Delinquency escalation, default declaration, and the charge-off cascade.

Covers difficulty instances (transitive_cascade, compensating_invariant) and corner instances
(state_machines side-effects, segregation_of_duties, optimistic_concurrency).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    create_active_line_with_draw,
    schedule_remittance,
    settle_remittance,
    set_clock,
    setup_delinquent_line,
    setup_line_at_default_threshold,
    setup_defaulted_line,
    setup_charged_off_line,
    get_line,
    sum_ledger_amounts,
    declare_default_payload,
    charge_off_payload,
    SV1,
    CO1,
    CO_DEFAULT,
    CO_CHARGEOFF,
)


def _scheduled_remittances(api, line_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_remittances(line_id, SV1, params={"status": "SCHEDULED"}))


def _ledger_by_type(api, line_id, entry_type):
    from test_helpers import validate_paginated
    return validate_paginated(
        api.list_ledger_entries_for_line(line_id, SV1, params={"entry_type": entry_type})
    )


class TestNsfDelinquencyCascade:
    def test_third_strike_tips_active_line_into_delinquent(self, api):
        """The third NSF strike auto-transitions an ACTIVE line to DELINQUENT.

        PRD §3.5: "if after the strike increment the line's nsf_strike_count has reached the
        delinquency threshold of 3 and the line is currently ACTIVE, the line auto-transitions
        from ACTIVE to DELINQUENT and its version is bumped."

        Design: Difficulty/transitive_cascade/nsf_settle_delinquency_cascade_depth2
        """
        set_clock("2026-05-13T00:00:00Z")
        line, _ = create_active_line_with_draw(
            200_000, cadence="DAILY", feed_overrides={"pulled_at": "2026-05-12T00:00:00Z"}
        )
        remit = schedule_remittance(line["id"], "2026-05-15T00:00:00Z")
        # First two NSF strikes via the auto-spawned retry chain.
        set_clock("2026-05-15T00:00:00Z")
        f1 = settle_remittance(remit["id"], "NSF")
        r2 = validate_success(api.get_remittance(f1["next_retry_remittance_id"], SV1), 200)
        set_clock("2026-05-17T00:00:00Z")
        f2 = settle_remittance(r2["id"], "NSF")
        r3 = validate_success(api.get_remittance(f2["next_retry_remittance_id"], SV1), 200)
        # Third NSF tips the line into DELINQUENT.
        set_clock("2026-05-19T00:00:00Z")
        f3 = settle_remittance(r3["id"], "NSF")
        assert f3["status"] == "FAILED"
        line_after = get_line(line["id"])
        assert line_after["nsf_strike_count"] == 3
        assert line_after["status"] == "DELINQUENT"


class TestChargeOffCascade:
    def test_charge_off_writes_off_draw_and_appends_ledger_entry(self, api):
        """Charge-off flips OUTSTANDING draws to WRITTEN_OFF, appends a WRITE_OFF ledger entry,
        and recomputes outstanding principal to zero.

        PRD §3.6: "every OUTSTANDING draw on the line transitions to WRITTEN_OFF (hop one); each
        written-off draw appends a WRITE_OFF ledger entry for its unrepaid principal — that
        draw's principal minus its principal already repaid (hop two); and the line's
        outstanding principal is recomputed, which now lands at zero because no outstanding
        draws remain (hop three)."

        Design: Difficulty/transitive_cascade/chargeoff_writeoff_ledger_cascade_depth3
        """
        line, draw, line_after = setup_charged_off_line(principal_cents=200_000)
        assert line_after["status"] == "CHARGED_OFF"
        assert line_after["outstanding_principal_cents"] == 0
        drawn = validate_success(api.get_draw(draw["id"], SV1), 200)
        assert drawn["status"] == "WRITTEN_OFF"
        entries, meta = _ledger_by_type(api, line["id"], "WRITE_OFF")
        assert meta["total_count"] == 1
        # PRD §2.8: amount_cents is a signed movement — "a credit is negative (reducing
        # it)". A WRITE_OFF reduces outstanding to zero, so its magnitude is the draw's
        # unrepaid principal (200000) recorded as a reducing (negative) movement.
        assert sum_ledger_amounts(entries, "WRITE_OFF") == -200_000

    def test_principal_accounting_conserved_through_chargeoff(self, api):
        """Total principal is conserved: DRAW_PRINCIPAL == repayments + write-off + outstanding.

        PRD §2.8: "Every movement of money against a line is recorded as an immutable
        LedgerEntry row, and the outstanding balance is always reconstructible from these rows."
        PRD §3.6: "each written-off draw appends a WRITE_OFF ledger entry for its unrepaid
        principal — that draw's principal minus its principal already repaid (hop two)"

        Design: Difficulty/compensating_invariant/principal_accounting_conserved_through_chargeoff
        """
        line, draw, line_after = setup_charged_off_line(principal_cents=200_000)
        drawn = validate_success(api.get_draw(draw["id"], SV1), 200)
        assert drawn["status"] == "WRITTEN_OFF"
        assert line_after["outstanding_principal_cents"] == 0
        dp, _ = _ledger_by_type(api, line["id"], "DRAW_PRINCIPAL")
        pr, _ = _ledger_by_type(api, line["id"], "PRINCIPAL_REPAYMENT")
        wo, _ = _ledger_by_type(api, line["id"], "WRITE_OFF")
        total_draw = sum_ledger_amounts(dp, "DRAW_PRINCIPAL")
        total_repaid = sum_ledger_amounts(pr, "PRINCIPAL_REPAYMENT")
        total_writeoff = sum_ledger_amounts(wo, "WRITE_OFF")
        # PRD §2.8: amount_cents is a signed movement — debit positive (DRAW_PRINCIPAL),
        # credit negative (PRINCIPAL_REPAYMENT, WRITE_OFF both reduce outstanding).
        assert total_draw == 200_000
        assert total_repaid == 0
        assert total_writeoff == -200_000
        # Signed conservation: the running balance is reconstructible from the rows
        # (PRD §2.8) — the sum of all signed principal movements equals outstanding.
        assert total_draw + total_repaid + total_writeoff == line_after["outstanding_principal_cents"]


class TestDeclareDefaultSideEffects:
    def test_declare_default_cancels_scheduled_remittances(self, api):
        """Declaring default stamps defaulted_by_user_id and cancels SCHEDULED remittances.

        PRD §3.6: "the system records the declaring officer's X-User-ID as defaulted_by_user_id,
        cancels every SCHEDULED remittance on the line by moving each to CANCELLED, moves the
        line to DEFAULTED, and bumps the line's version."

        Design: Corner/state_machines/declare_default_cancels_scheduled_remittances_cascade
        """
        line, draw, last = setup_line_at_default_threshold(principal_cents=200_000)
        retry_id = last["next_retry_remittance_id"]
        ver = get_line(line["id"])["version"]
        defaulted = validate_success(
            api.declare_default(line["id"], declare_default_payload(ver), CO_DEFAULT), 200
        )
        assert defaulted["status"] == "DEFAULTED"
        assert defaulted["defaulted_by_user_id"] == "co_default"
        if retry_id:
            retry = validate_success(api.get_remittance(retry_id, SV1), 200)
            assert retry["status"] == "CANCELLED"
        _, meta = _scheduled_remittances(api, line["id"])
        assert meta["total_count"] == 0


class TestSegregationOfDuties:
    def test_charge_off_by_same_officer_as_default_rejected(self, api):
        """The officer who declared default may not charge off the same line.

        PRD §3.6: "by segregation of duties, the acting X-User-ID must differ from the line's
        recorded defaulted_by_user_id, or the request is rejected with
        ERR_SEGREGATION_OF_DUTIES."

        Design: Corner/rbac/charge_off_same_officer_as_default_segregation
        """
        line, draw, line_after_default = setup_defaulted_line(principal_cents=200_000)
        ver = line_after_default["version"]
        res = api.charge_off(line["id"], charge_off_payload(ver), CO_DEFAULT)
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
        after = get_line(line["id"])
        assert after["status"] == "DEFAULTED"


class TestOccChargeOff:
    def test_charge_off_with_stale_pre_default_version_rejected(self, api):
        """Charging off with the pre-default version (stale by one) returns ERR_STALE_VERSION.

        PRD §3.6: "Charge-off also requires expected_credit_line_version to match the line's
        current version, rejecting a mismatch with ERR_STALE_VERSION."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_charge_off
        """
        line, draw, _ = setup_line_at_default_threshold(principal_cents=200_000)
        pre_default_ver = get_line(line["id"])["version"]
        validate_success(
            api.declare_default(line["id"], declare_default_payload(pre_default_ver), CO_DEFAULT), 200
        )
        # Reuse the now-stale pre-default version for charge-off OCC.
        res = api.charge_off(line["id"], charge_off_payload(pre_default_ver), CO_CHARGEOFF)
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)
        after = get_line(line["id"])
        assert after["status"] == "DEFAULTED"
