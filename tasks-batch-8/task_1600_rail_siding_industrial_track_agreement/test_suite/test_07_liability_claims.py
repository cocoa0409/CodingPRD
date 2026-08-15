"""LiabilityClaim apportionment, the indemnity cap aggregate, the dispute loop,
and the renewal-offer coupling (PRD §3.1, §3.7).
"""
from test_helpers import (
    RCM,
    ApiErrorId,
    assert_liability_claim,
    get_agreement,
    get_liability_claim,
    make_active_agreement,
    make_liability_claim,
    make_shipper_headers,
    validate_error,
    validate_success,
)
from test_helpers import constants as C


class TestApportionment:
    def test_apportion_omitted_pct_uses_agreement_default(self, api):
        """PRD §3.7: "The request may carry `shipper_fault_pct` between 0 and
        100; when omitted, the agreement's `shipper_indemnity_default_pct`
        applies."
        PRD §3.7: "The raw shipper share is `claim_amount_cents` multiplied by
        the fault percentage and divided by 100, rounded half-up to whole
        cents."

        Design: Corner/calculations/liability_apportion_default_pct_applied
        """
        agreement = make_active_agreement()
        claim = make_liability_claim(agreement["id"], claim_amount_cents=60000)
        res = api.apportion_claim(claim["id"], {}, RCM)
        apportioned = validate_success(res)
        assert_liability_claim(apportioned)
        assert apportioned["shipper_fault_pct"] == 50
        # round_half_up(60000 * 50 / 100, 0)
        assert apportioned["shipper_liability_cents"] == 30000
        assert apportioned["railroad_liability_cents"] == 30000
        assert apportioned["status"] == "APPORTIONED"

    def test_cap_binds_allocation_to_remaining_headroom(self, api):
        """PRD §3.7: "the remaining headroom is `liability_cap_cents` minus the
        sum of `shipper_liability_cents` over this agreement's claims in
        `ACCEPTED` status only — claims still `FILED`, `APPORTIONED`, or
        `DISPUTED` are excluded from that sum, which means a claim being
        re-apportioned does not count its own prior amount against the cap."
        PRD §3.7: "The allocated `shipper_liability_cents` is the smaller of
        the raw share and the remaining headroom, and
        `railroad_liability_cents` is the remainder of the claim amount."

        Design: Corner/calculations/liability_cap_min_allocation
        """
        agreement = make_active_agreement()
        first = make_liability_claim(agreement["id"], claim_amount_cents=60000)
        validate_success(
            api.apportion_claim(first["id"], {"shipper_fault_pct": 50}, RCM)
        )
        accepted = validate_success(
            api.accept_claim(
                first["id"], make_shipper_headers(C.SHIPPER_USER_ID)
            )
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["shipper_liability_cents"] == 30000
        second = make_liability_claim(
            agreement["id"], claim_amount_cents=150000, claimant_name="R. Roe",
            incident_date="2026-08-03",
        )
        res = api.apportion_claim(second["id"], {"shipper_fault_pct": 50}, RCM)
        apportioned = validate_success(res)
        # Raw share 75000 vs headroom 100000 - 30000 = 70000: the cap binds.
        assert apportioned["shipper_liability_cents"] == 70000
        assert apportioned["railroad_liability_cents"] == 80000


class TestDisputeCycle:
    def test_dispute_and_reapportion_cycle(self, api):
        """PRD §3.7: "Dispute, optionally carrying a `dispute_reason`, returns
        the claim to `DISPUTED`, from which the railroad may apportion again;
        the loop continues until the shipper accepts."
        PRD §3.7: "claims still `FILED`, `APPORTIONED`, or `DISPUTED` are
        excluded from that sum, which means a claim being re-apportioned does
        not count its own prior amount against the cap."
        PRD §3.7: "The raw shipper share is `claim_amount_cents` multiplied by
        the fault percentage and divided by 100, rounded half-up to whole
        cents."

        Design: Corner/state_machines/claim_dispute_and_reapportion_cycle
        """
        agreement = make_active_agreement()
        claim = make_liability_claim(agreement["id"], claim_amount_cents=60000)
        assert claim["status"] == "FILED"
        first = validate_success(
            api.apportion_claim(claim["id"], {"shipper_fault_pct": 50}, RCM)
        )
        assert first["shipper_liability_cents"] == 30000
        disputed = validate_success(
            api.dispute_claim(
                claim["id"],
                make_shipper_headers(C.SHIPPER_USER_ID),
                payload={"dispute_reason": "Fault percentage contested"},
            )
        )
        assert disputed["status"] == "DISPUTED"
        second = validate_success(
            api.apportion_claim(claim["id"], {"shipper_fault_pct": 40}, RCM)
        )
        # Recomputed from scratch: the prior APPORTIONED amount is excluded
        # from the ACCEPTED-only cap sum, so no self-consumption.
        assert second["shipper_liability_cents"] == 24000
        assert second["railroad_liability_cents"] == 36000
        assert second["status"] == "APPORTIONED"
        accepted = validate_success(
            api.accept_claim(
                claim["id"], make_shipper_headers(C.SHIPPER_USER_ID)
            )
        )
        assert accepted["status"] == "ACCEPTED"


class TestRenewalBlockedByOpenClaims:
    def test_renewal_offer_blocked_by_filed_claim(self, api):
        """PRD §3.1: "A `RailroadContractsManager` may offer renewal only while
        the agreement is `ACTIVE`, only while no liability claim of the
        agreement sits in `FILED`, `APPORTIONED`, or `DISPUTED` status (an open
        claim rejects the offer with `ERR_OPEN_CLAIMS_BLOCK_RENEWAL`), and only
        while the current logical date is on or before the date
        `renewal_notice_days` days before `term_end_date` — past that closing
        date the offer is rejected with `ERR_RENEWAL_WINDOW_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/renewal_offer_blocked_by_open_claim
        """
        agreement = make_active_agreement()
        make_liability_claim(agreement["id"], claim_amount_cents=60000)
        res = api.offer_renewal(agreement["id"], RCM)
        validate_error(res, ApiErrorId.ERR_OPEN_CLAIMS_BLOCK_RENEWAL, 409)
        assert get_agreement(agreement["id"])["status"] == "ACTIVE"

    def test_renewal_offer_allowed_once_claim_accepted(self, api):
        """PRD §3.1: "A `RailroadContractsManager` may offer renewal only while
        the agreement is `ACTIVE`, only while no liability claim of the
        agreement sits in `FILED`, `APPORTIONED`, or `DISPUTED` status (an open
        claim rejects the offer with `ERR_OPEN_CLAIMS_BLOCK_RENEWAL`), and only
        while the current logical date is on or before the date
        `renewal_notice_days` days before `term_end_date` — past that closing
        date the offer is rejected with `ERR_RENEWAL_WINDOW_CLOSED`."
        PRD §3.7: "Acceptance moves the claim to `ACCEPTED` — its terminal
        state — and locks `shipper_liability_cents`, which from then on counts
        toward the agreement's cap aggregate."

        Design: Difficulty/cross_entity_state_dependency/renewal_offer_blocked_by_open_claim
        """
        agreement = make_active_agreement()
        claim = make_liability_claim(agreement["id"], claim_amount_cents=60000)
        validate_success(
            api.apportion_claim(claim["id"], {"shipper_fault_pct": 50}, RCM)
        )
        # APPORTIONED is still an open status for the renewal gate.
        blocked = api.offer_renewal(agreement["id"], RCM)
        validate_error(blocked, ApiErrorId.ERR_OPEN_CLAIMS_BLOCK_RENEWAL, 409)
        accepted = validate_success(
            api.accept_claim(
                claim["id"], make_shipper_headers(C.SHIPPER_USER_ID)
            )
        )
        assert accepted["status"] == "ACCEPTED"
        assert get_liability_claim(claim["id"])["shipper_liability_cents"] == 30000
        offered = validate_success(api.offer_renewal(agreement["id"], RCM))
        assert offered["status"] == "RENEWAL_OFFERED"
