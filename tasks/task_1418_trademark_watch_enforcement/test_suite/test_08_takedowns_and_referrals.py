"""Takedown filings, the confirmed-counterfeit ledger, the threshold referral
cascade, damages rounding, appeal caps, and referral lifecycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_removed_counterfeit_filing,
    assert_counterfeit_referral,
    assert_takedown_filing,
    create_alert,
    create_referral,
    create_recordation,
    create_takedown,
    file_takedown,
    get_alert,
    make_associate_headers,
    make_partner_headers,
    platform_response,
    setup_alert_with_confirmed_counterfeits,
    setup_counterfeit_alert,
    setup_registered_record,
    triage_alert,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestThresholdReferralCascade:
    def test_fifth_removal_auto_creates_referral_and_marks_alert(self, api,
                                                                 paralegal_headers):
        """PRD §3.7: "A `FILED` or `APPEALED` filing marked `REMOVED` succeeds; when
        its `basis` is `COUNTERFEIT`, the alert's `confirmed_counterfeit_count`
        increments by one, and if that count has reached at least 5 while
        `referral_auto_created` is still false, the threshold cascade auto-creates a
        counterfeit referral in `DRAFT` status with `auto_created` true,
        `referral_channel` `LAW_ENFORCEMENT`, an empty `seizure_lines` array, and
        flips `referral_auto_created` to true."

        Design: Difficulty/transitive_cascade/takedown_removal_threshold_referral_cascade
        """
        client, record, alert, _ = setup_alert_with_confirmed_counterfeits(4)
        assert alert["confirmed_counterfeit_count"] == 4
        _, meta_before = validate_paginated(
            api.list_counterfeit_referrals(paralegal_headers,
                                           params={"watch_alert_id": alert["id"]}))
        assert meta_before["total_count"] == 0

        fifth = create_takedown(alert["id"], platform="META", basis="COUNTERFEIT",
                                listing_url="https://meta.example/shop/5")
        file_takedown(fifth["id"])
        platform_response(fifth["id"], "REMOVED")

        alert_after = get_alert(alert["id"])
        assert alert_after["confirmed_counterfeit_count"] == 5
        assert alert_after["referral_auto_created"] is True

    def test_auto_referral_contents_after_threshold(self, api, paralegal_headers):
        """PRD §3.7: "if that count has reached at least 5 while
        `referral_auto_created` is still false, the threshold cascade auto-creates a
        counterfeit referral in `DRAFT` status with `auto_created` true,
        `referral_channel` `LAW_ENFORCEMENT`, an empty `seizure_lines` array, and
        flips `referral_auto_created` to true."

        Design: Difficulty/transitive_cascade/takedown_removal_threshold_referral_cascade
        """
        _, _, alert, _ = setup_alert_with_confirmed_counterfeits(5)
        data, meta = validate_paginated(
            api.list_counterfeit_referrals(paralegal_headers,
                                           params={"watch_alert_id": alert["id"]}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        referral = data[0]
        assert_counterfeit_referral(referral)
        assert referral["auto_created"] is True
        assert referral["status"] == "DRAFT"
        assert referral["referral_channel"] == "LAW_ENFORCEMENT"


class TestCounterfeitLedgerConservation:
    def test_confirmed_count_matches_removed_filings_forward(self, api,
                                                             paralegal_headers):
        """PRD §3.7: "A `FILED` or `APPEALED` filing marked `REMOVED` succeeds; when
        its `basis` is `COUNTERFEIT`, the alert's `confirmed_counterfeit_count`
        increments by one"

        Design: Difficulty/compensating_invariant/counterfeit_ledger_conservation_across_reinstate
        """
        _, _, alert, _ = setup_alert_with_confirmed_counterfeits(3)
        assert get_alert(alert["id"])["confirmed_counterfeit_count"] == 3
        data, meta = validate_paginated(
            api.list_takedown_filings(paralegal_headers,
                                      params={"watch_alert_id": alert["id"],
                                              "status": "REMOVED"}))
        assert meta["total_count"] == 3
        assert get_alert(alert["id"])["confirmed_counterfeit_count"] == meta["total_count"]

    def test_reinstate_decrements_confirmed_count_with_floor(self, api,
                                                             paralegal_headers):
        """PRD §3.7: "Reinstatement applies only from `REMOVED` and moves the filing
        to its terminal `REINSTATED` state, decrementing the alert's
        `confirmed_counterfeit_count` by one for `COUNTERFEIT` filings, with a floor
        of zero."

        Design: Difficulty/compensating_invariant/counterfeit_ledger_conservation_across_reinstate
        """
        _, _, alert, filing_ids = setup_alert_with_confirmed_counterfeits(3)
        target = filing_ids[1]
        reinstated = platform_response(target, "REINSTATED")
        assert reinstated["status"] == "REINSTATED"

        assert get_alert(alert["id"])["confirmed_counterfeit_count"] == 2
        _, meta = validate_paginated(
            api.list_takedown_filings(paralegal_headers,
                                      params={"watch_alert_id": alert["id"],
                                              "status": "REMOVED"}))
        assert meta["total_count"] == 2
        assert get_alert(alert["id"])["confirmed_counterfeit_count"] == meta["total_count"]


class TestCounterfeitDamagesRounding:
    def test_per_line_rounding_then_sum(self, api, paralegal_headers):
        """PRD §3.7: "Estimated statutory damages are computed per line: each line's
        units times unit value times one and a half, rounded half-up to whole cents
        first, and only then summed into `estimated_damages_cents` — summing raw
        values and rounding once is deliberately not the rule."
        PRD §3.7: "A manually created referral has `auto_created` false, starts in
        `DRAFT`"

        Design: Difficulty/combinatorial_formula/counterfeit_damages_per_line_rounding
        """
        _, _, alert, _ = setup_alert_with_confirmed_counterfeits(3)
        res = api.create_counterfeit_referral(
            alert["id"],
            {
                "referral_channel": "LAW_ENFORCEMENT",
                "seizure_lines": [
                    {"units": 3, "unit_value_cents": 333},
                    {"units": 1, "unit_value_cents": 335},
                ],
            },
            make_associate_headers("assoc_1"),
        )
        referral = validate_success(res, 201)
        assert_counterfeit_referral(referral)
        # Line 1: round_half_up(3*333*1.5) == 1499; line 2: round_half_up(1*335*1.5)
        # == 503; total 2002 (sum-then-round would give 2001).
        assert referral["estimated_damages_cents"] == 2002
        assert referral["auto_created"] is False
        assert referral["status"] == "DRAFT"

    def test_half_cent_line_rounds_half_up(self, api):
        """PRD §3.7: "Estimated statutory damages are computed per line: each line's
        units times unit value times one and a half, rounded half-up to whole cents
        first, and only then summed into `estimated_damages_cents`"

        Design: Difficulty/combinatorial_formula/counterfeit_damages_per_line_rounding
        """
        _, _, alert, _ = setup_alert_with_confirmed_counterfeits(3)
        referral = create_referral(
            alert["id"], referral_channel="LAW_ENFORCEMENT",
            seizure_lines=[{"units": 1, "unit_value_cents": 335}])
        # round_half_up(1 * 335 * 1.5) == round_half_up(502.5) == 503.
        assert referral["estimated_damages_cents"] == 503


class TestAppealCycleAndLifecycle:
    def test_takedown_appeal_cycle_and_cap(self, api, paralegal_headers):
        """PRD §3.7: "From `REJECTED`, a `Paralegal` may appeal, incrementing
        `appeal_count`; the appeal cap is 2 and a third attempt is rejected with
        `ERR_APPEAL_CAP_REACHED`."

        Design: Corner/state_machines/takedown_appeal_cycle_and_cap
        """
        _, _, alert = setup_counterfeit_alert(budget=500000)
        filing = create_takedown(alert["id"], platform="AMAZON", basis="TRADEMARK",
                                 listing_url="https://amazon.example/item/1")
        file_takedown(filing["id"])

        rejected = platform_response(filing["id"], "REJECTED")
        assert rejected["status"] == "REJECTED"

        appealed1 = validate_success(api.appeal_takedown(filing["id"],
                                                         paralegal_headers), 200)
        assert appealed1["status"] == "APPEALED"
        assert appealed1["appeal_count"] == 1
        platform_response(filing["id"], "REJECTED")

        appealed2 = validate_success(api.appeal_takedown(filing["id"],
                                                         paralegal_headers), 200)
        assert appealed2["appeal_count"] == 2
        platform_response(filing["id"], "REJECTED")

        res = api.appeal_takedown(filing["id"], paralegal_headers)
        validate_error(res, ApiErrorId.ERR_APPEAL_CAP_REACHED, expected_status=422)
        after = validate_success(api.get_takedown_filing(filing["id"],
                                                         paralegal_headers), 200)
        assert_takedown_filing(after)
        assert after["appeal_count"] == 2
        assert after["status"] == "REJECTED"

    def test_referral_lifecycle_and_terminal_lockdown(self, api, partner_headers):
        """PRD §3.7: "A `PartnerAttorney` refers a draft, moving it to `REFERRED`; a
        `CUSTOMS_SEIZE` referral additionally requires an `ACTIVE` customs
        recordation on the alert's record, else `ERR_CUSTOMS_RECORDATION_REQUIRED`.
        Acknowledgement moves a referred referral to its terminal `ACKNOWLEDGED`
        state."
        PRD §2.10: "State — the target entity is in a state from which the requested
        transition is declared, including terminal-state lockdown, else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/referral_lifecycle_and_terminal_lockdown
        """
        _, _, alert, _ = setup_alert_with_confirmed_counterfeits(3)
        referral = create_referral(
            alert["id"], referral_channel="LAW_ENFORCEMENT",
            seizure_lines=[{"units": 2, "unit_value_cents": 5000}])

        referred = validate_success(api.refer_referral(referral["id"],
                                                       partner_headers), 200)
        assert referred["status"] == "REFERRED"
        acknowledged = validate_success(api.acknowledge_referral(referral["id"],
                                                                 partner_headers), 200)
        assert acknowledged["status"] == "ACKNOWLEDGED"

        res = api.acknowledge_referral(referral["id"], partner_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        refreshed = validate_success(api.get_counterfeit_referral(referral["id"],
                                                                  partner_headers), 200)
        assert refreshed["status"] == "ACKNOWLEDGED"


class TestReferralPreconditions:
    def test_manual_referral_threshold_boundary(self, api):
        """PRD §3.7: "Manual counterfeit referrals are created by an
        `AssociateAttorney` against an alert whose `confirmed_counterfeit_count` is
        at least 3 — below that threshold the create is rejected with
        `ERR_REFERRAL_THRESHOLD_NOT_MET`."
        PRD §3.7: "A manually created referral has `auto_created` false, starts in
        `DRAFT`"

        Design: Corner/validations/manual_referral_threshold_boundary
        """
        _, _, alert, _ = setup_alert_with_confirmed_counterfeits(2)
        res = api.create_counterfeit_referral(
            alert["id"],
            {"referral_channel": "LAW_ENFORCEMENT",
             "seizure_lines": [{"units": 2, "unit_value_cents": 5000}]},
            make_associate_headers("assoc_1"),
        )
        validate_error(res, ApiErrorId.ERR_REFERRAL_THRESHOLD_NOT_MET,
                       expected_status=422)

        add_removed_counterfeit_filing(alert["id"], 3)
        referral = create_referral(
            alert["id"], referral_channel="LAW_ENFORCEMENT",
            seizure_lines=[{"units": 2, "unit_value_cents": 5000}])
        assert referral["status"] == "DRAFT"
        assert referral["auto_created"] is False
        # round_half_up(2 * 5000 * 1.5) == 15000.
        assert referral["estimated_damages_cents"] == 15000

    def test_customs_seize_referral_requires_active_recordation(self, api,
                                                                partner_headers):
        """PRD §3.7: "A `PartnerAttorney` refers a draft, moving it to `REFERRED`; a
        `CUSTOMS_SEIZE` referral additionally requires an `ACTIVE` customs
        recordation on the alert's record, else `ERR_CUSTOMS_RECORDATION_REQUIRED`."

        Design: Corner/validations/customs_seize_referral_requires_active_recordation
        """
        client, record = setup_registered_record(budget=500000, classes=(25,))
        alert = create_alert(record["id"], 95, 92, 80, source="MARKETPLACE_SWEEP",
                             conflicting_classes=(25,), conflicting_owner="FakeShop")
        alert = triage_alert(alert["id"])
        for i in range(3):
            add_removed_counterfeit_filing(alert["id"], i + 1)

        referral = create_referral(
            alert["id"], referral_channel="CUSTOMS_SEIZE",
            seizure_lines=[{"units": 2, "unit_value_cents": 5000}])
        res = api.refer_referral(referral["id"], partner_headers)
        validate_error(res, ApiErrorId.ERR_CUSTOMS_RECORDATION_REQUIRED,
                       expected_status=422)
        refreshed = validate_success(api.get_counterfeit_referral(referral["id"],
                                                                  partner_headers), 200)
        assert refreshed["status"] == "DRAFT"

        create_recordation(record["id"], recordation_number="CBP-1",
                           term_start="2026-08-15T00:00:00Z",
                           term_end="2027-08-15T00:00:00Z")
        referred = validate_success(api.refer_referral(referral["id"],
                                                       partner_headers), 200)
        assert referred["status"] == "REFERRED"
