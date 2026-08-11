"""Dual-variant calculations: the registration fee and the renewal compliance
score each have a PROVISIONAL and a FINALIZED/AUDITED variant (PRD §3.5, §3.6).
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_permit_holder_headers,
    create_community, create_eligible_holder, create_full_equipment_lsv,
    create_draft_registration, finalize_inspection_for_registration,
    create_insurance, deposit, get_holder, set_clock,
    COMMUNITY_ADMIN, OFFICER,
    create_violation_payload,
    assert_instant_equal,
)


def _setup_dv1():
    """Community with fleet program on; ELIGIBLE holder; full-equipment 6-seat
    LSV; DRAFT 2026 registration finalized with an all-90 PASSED inspection."""
    community = create_community(name="C-DV1", fleet_program_enabled=True)
    holder = create_eligible_holder(community["id"], full_name="H DV1",
                                    birth_date="2010-05-01")
    vehicle = create_full_equipment_lsv(holder["id"])
    registration = create_draft_registration(vehicle["id"], holder["id"],
                                             registration_year=2026)
    finalize_inspection_for_registration(registration["id"], score=90)
    registration = get_success_data(
        api_client.get_registration(registration["id"], COMMUNITY_ADMIN))
    return community, holder, vehicle, registration


class TestRegistrationFeeProvisionalVsFinalized:
    def test_provisional_fee_assumes_fleet_discount(self):
        """PRD §3.5: "The PROVISIONAL variant — used at registration creation and
        at a renewal opened while the registration is still `ACTIVE` — assumes the
        discount whenever the community's `fleet_program_enabled` is true, with no
        usage-history check."

        Design: Difficulty/dual_variant_calc/registration_fee_provisional_vs_finalized_fleet_discount
        """
        _, _, _, registration = _setup_dv1()
        # 15000 * min(1 + 0.02*8, 1.20) = 17400; + max(0,6-4)*500 = 18400;
        # * 0.9 = 16560 (fleet discount assumed); >= base 15000.
        assert registration["provisional_fee_cents"] == 16560, (
            f"provisional fee {registration['provisional_fee_cents']} != 16560")

    def test_finalized_fee_withholds_discount_without_returned_dispatch(self):
        """PRD §3.5: "The FINALIZED variant — used when an inspection passes, when a
        late renewal is opened from `EXPIRED`, and at renewal finalization — grants
        the discount only when the holder has at least one fleet dispatch in
        `RETURNED` status whose `returned_at` falls within the trailing 365 days of
        the calculation instant."

        Design: Difficulty/dual_variant_calc/registration_fee_provisional_vs_finalized_fleet_discount
        """
        _, _, _, registration = _setup_dv1()
        # 15000 * min(1 + 0.025*8, 1.20) = 18000; + 1000 seats = 19000;
        # no RETURNED dispatch -> no discount; total_due = min(19000+0, 2*19000).
        assert registration["finalized_fee_cents"] == 19000, (
            f"finalized fee {registration['finalized_fee_cents']} != 19000")
        assert registration["total_due_cents"] == 19000
        assert registration["provisional_fee_cents"] != registration["finalized_fee_cents"]


def _setup_dv2():
    """ACTIVE LSV registration (finalized 19000) with a funded wallet (81000 after
    activation) and two violations staged for the renewal-score variants."""
    community = create_community(name="C-DV2", fleet_program_enabled=True)
    holder = create_eligible_holder(community["id"], full_name="H DV2",
                                    birth_date="2010-05-01")
    holder = deposit(holder["id"], 100000, holder["version"])
    vehicle = create_full_equipment_lsv(holder["id"])
    registration = create_draft_registration(vehicle["id"], holder["id"],
                                             registration_year=2026)
    finalize_inspection_for_registration(registration["id"], score=90)
    create_insurance(holder["id"], vehicle["id"], policy_number="N-DV2")
    hh = make_permit_holder_headers(holder["id"])
    get_success_data(api_client.activate_registration(registration["id"], hh))
    # 200 days before the renew instant -> recency weight 0.5
    set_clock("2027-03-10T00:00:00Z")
    vio1 = get_success_data(api_client.create_violation(
        create_violation_payload(holder["id"], violation_code="OFF_ROUTE",
                                 points_assessed=6, fine_cents=5000,
                                 occurred_at="2026-08-27T00:00:00Z"), OFFICER))
    get_success_data(api_client.uphold_violation(vio1["id"], OFFICER))
    # FILED; 40 days before renew, 45 days at finalize -> aged > 30 by then
    vio2 = get_success_data(api_client.create_violation(
        create_violation_payload(holder["id"], violation_code="PARKING_VIOLATION",
                                 points_assessed=10, fine_cents=8000,
                                 occurred_at="2027-02-03T00:00:00Z"), OFFICER))
    set_clock("2027-03-15T00:00:00Z")
    return community, holder, vehicle, registration


class TestRenewalScoreProvisionalVsAudited:
    def test_provisional_score_excludes_filed_violations(self):
        """PRD §3.6: "The PROVISIONAL variant, computed at the renew instant,
        includes only violations in `UPHELD` status at a status weight of 1.0;
        `FILED` violations are excluded entirely."

        Design: Difficulty/dual_variant_calc/renewal_compliance_score_provisional_vs_audited
        """
        _, holder, _, registration = _setup_dv2()
        hh = make_permit_holder_headers(holder["id"])
        renewed = validate_success(
            api_client.renew_registration(registration["id"], hh), 200)
        # 100 - 6 * 0.5 (UPHELD, 200 days old) = 97; FILED V2 excluded entirely.
        assert renewed["renewal_score_provisional"] == pytest.approx(97, abs=0.01), (
            f"provisional score {renewed['renewal_score_provisional']} != 97")

    def test_audited_score_includes_aged_filed_at_half_weight(self):
        """PRD §3.6: "The AUDITED variant, computed at the finalization instant,
        includes `UPHELD` violations at weight 1.0 and additionally includes `FILED`
        violations whose `occurred_at` is more than 30 days before the as-of
        instant, at a status weight of 0.5."
        PRD §3.6: "When the audited score is at least 70, the registration moves
        `RENEWAL_PENDING` → `ACTIVE`: the wallet is debited the recomputed total
        due (a shortfall is rejected with `ERR_INSUFFICIENT_FUNDS`), `paid_cents`
        accumulates the debit, `expiry_date` extends by 365 days from the previous
        expiry, and both the registration's and the holder's `version` increment."

        Design: Difficulty/dual_variant_calc/renewal_compliance_score_provisional_vs_audited
        """
        _, holder, _, registration = _setup_dv2()
        hh = make_permit_holder_headers(holder["id"])
        renewed = validate_success(
            api_client.renew_registration(registration["id"], hh), 200)
        set_clock("2027-03-20T00:00:00Z")
        finalized = validate_success(
            api_client.finalize_renewal(registration["id"], COMMUNITY_ADMIN), 200)
        # 100 - 6*0.5 - 10*1.0*0.5 = 92 (aged FILED included at half weight).
        assert finalized["renewal_score_audited"] == pytest.approx(92, abs=0.01), (
            f"audited score {finalized['renewal_score_audited']} != 92")
        assert renewed["renewal_score_provisional"] != finalized["renewal_score_audited"]
        assert finalized["status"] == "ACTIVE"  # 92 >= 70
        # PRD §3.6: "expiry_date extends by 365 days from the previous expiry".
        # Previous expiry 2027-05-01 + 365 days = 2028-04-30 (2028-02-29 falls
        # inside the span). Instant comparison: PRD pins the instant, not the
        # serialization.
        assert_instant_equal(finalized["expiry_date"], "2028-04-30T00:00:00Z")
        wallet_after = get_holder(holder["id"])["wallet_balance_cents"]
        # 100000 - 19000 (activation) - 19000 (renewal, no RETURNED dispatch) = 62000
        assert wallet_after == 62000, f"wallet {wallet_after} != 62000"
