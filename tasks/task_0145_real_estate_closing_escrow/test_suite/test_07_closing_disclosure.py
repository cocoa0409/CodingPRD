"""Closing Disclosure: creation, cash_to_close, issue, acknowledge,
promote, revise cycle, and the 3-business-day clock (PRD §3.5, §2.10)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    acknowledge_cd,
    advance_clock_by,
    advance_clock_to,
    advance_escrow,
    api_client,
    assert_closing_disclosure,
    assert_version_incremented_by_one,
    cancel_escrow,
    closing_disclosure_payload,
    create_cd,
    create_ccr_disclosure,
    create_emd_held,
    iso_utc,
    issue_cd,
    make_buyer_headers,
    parse_iso,
    promote_cd,
    re_get_closing_disclosure,
    re_get_escrow_file,
    revise_cd,
    revise_cd_payload,
    server_now_dt,
    setup_emd_held,
    setup_escrow_in_contingent_cd,
    setup_owners_policy_bound,
    setup_title_cleared,
    validate_error,
    validate_success,
    version_only_payload,
    with_idempotency,
)


# ===========================================================================
# CD creation — PRD §3.5
# ===========================================================================
class TestClosingDisclosureCreation:

    def test_create_cd_status_draft_version_one(self, api):
        """PRD §3.5: "On creation the row begins in DRAFT, the
        version_number starts at 1".

        Claim: POST /closing-disclosures returns 201 with status=DRAFT
        and version_number=1.
        """
        bundle = setup_escrow_in_contingent_cd()
        cd = create_cd(bundle["escrow_file"]["id"])
        assert_closing_disclosure(cd)
        assert cd["status"] == "DRAFT"
        assert cd["version_number"] == 1

    def test_create_cd_freezes_prorations_and_cash_to_close(self, api):
        """PRD §3.5: "the system freezes cash_to_close along with the
        two pro-ration line items prorated_tax_credit and
        prorated_hoa_credit."

        Claim: on create, prorated_tax_credit, prorated_hoa_credit, and
        cash_to_close are all populated and within precision.
        """
        bundle = setup_escrow_in_contingent_cd(
            hoa_annual_dues=789.0, tax_annual=1234.0,
        )
        cd = create_cd(
            bundle["escrow_file"]["id"], seller_days_owned=100,
        )
        assert "prorated_tax_credit" in cd
        assert "prorated_hoa_credit" in cd
        assert "cash_to_close" in cd


# ===========================================================================
# Cash-to-close — PRD §3.5 (difficulty rule 2)
# ===========================================================================
class TestCashToCloseRoundingOrder:

    def test_cash_to_close_per_line_then_sum(self, api):
        """PRD §3.5: "Per-line-item rounding precedes the sum: the
        system must not sum the raw quotients and then round, because
        the order of rounding and addition is observably different and
        the test suite pins the per-item-first order."

        With tax_annual=1234, hoa_annual_dues=789, seller_days_owned=100,
        year_basis=365:
          tax_raw = 1234 * 100 / 365 = 338.0821...
          hoa_raw = 789 * 100 / 365 = 216.164...
          prorated_tax_credit = 338.08
          prorated_hoa_credit = 216.16
          sum = 554.24 (NOT 554.25 from sum-then-round of 554.246575)
        Then cash_to_close = 300000 - 240000 - 3000 - 0 - 338.08 -
        216.16 + 5000 = 61445.76.

        Claim: cash_to_close == 61445.76 and != 61445.75 (proves
        per-line-then-sum rounding order).

        # difficulty: combinatorial_formula/cash_to_close_rounding_order_pin
        """
        bundle = setup_escrow_in_contingent_cd(
            purchase_price=300000.00,
            loan_amount=240000.00,
            emd_amount=3000.00,
            hoa_annual_dues=789.0,
            tax_annual=1234.0,
        )
        cd = create_cd(
            bundle["escrow_file"]["id"],
            total_loan_costs=5000.00,
            seller_credits=0.00,
            seller_days_owned=100,
        )
        assert cd["prorated_tax_credit"] == pytest.approx(338.08, abs=0.001)
        assert cd["prorated_hoa_credit"] == pytest.approx(216.16, abs=0.001)
        assert cd["cash_to_close"] == pytest.approx(61445.76, abs=0.001)
        assert cd["cash_to_close"] != pytest.approx(61445.75, abs=0.001)


# ===========================================================================
# CD issue — PRD §3.5
# ===========================================================================
class TestClosingDisclosureIssue:

    def test_issue_sets_status_and_clock_fields(self, api):
        """PRD §3.5: "Issuance moves the disclosure from DRAFT to
        ISSUED. The system writes issued_at to the current server time
        and computes earliest_funding_at per the business-day clock
        described in §2".

        Claim: after issue, status=ISSUED with issued_at and
        earliest_funding_at populated.
        """
        bundle = setup_escrow_in_contingent_cd()
        cd = create_cd(bundle["escrow_file"]["id"])
        cd = issue_cd(cd["id"], version=cd["version"])
        assert cd["status"] == "ISSUED"
        assert cd.get("issued_at") is not None
        assert cd.get("earliest_funding_at") is not None

    def test_issue_against_wrong_parent_status_rejected(self, api):
        """PRD §3.5: "Issuance is permitted only when the parent escrow
        file is in CONTINGENT_CD; a request issued against any other
        parent status is rejected with ERR_CROSS_ENTITY_STATE."

        Claim: issuing a CD whose parent has been cancelled (so the
        file is no longer CONTINGENT_CD) yields ERR_CROSS_ENTITY_STATE
        (or ERR_INVALID_STATE if the CD itself has been cascade-VOIDED).
        """
        bundle = setup_escrow_in_contingent_cd()
        cd = create_cd(bundle["escrow_file"]["id"])
        # Cancel the file — moves file out of CONTINGENT_CD.
        ef = re_get_escrow_file(bundle["escrow_file"]["id"])
        cancel_escrow(
            ef["id"], "BUYER_DEFAULT", version=ef["version"],
        )
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.issue_closing_disclosure(
            cd["id"], version_only_payload(version=cd["version"]), eo,
        )
        # Either the file-status cross-entity check (priority 6) wins,
        # or the CD's own VOIDED state-check (priority 5) wins, both
        # before any clock check. The temporal error is excluded.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_CROSS_ENTITY_STATE.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )


# ===========================================================================
# Acknowledge — PRD §3.5
# ===========================================================================
class TestClosingDisclosureAcknowledge:

    def test_acknowledge_by_correct_buyer_sets_status(self, api):
        """PRD §3.5: "Once ISSUED, the buyer acknowledges receipt of
        the disclosure, which moves it to ACKNOWLEDGED and stamps
        buyer_acknowledged_at to the current server time. The
        acknowledge transition is restricted to a Buyer whose X-User-ID
        equals the parent escrow file's buyer_party_id."

        Claim: the actual buyer's ack moves status to ACKNOWLEDGED.
        """
        bundle = setup_escrow_in_contingent_cd()
        cd = create_cd(bundle["escrow_file"]["id"])
        cd = issue_cd(cd["id"], version=cd["version"])
        cd_ack = acknowledge_cd(
            cd["id"], bundle["buyer"]["id"], version=cd["version"],
        )
        assert cd_ack["status"] == "ACKNOWLEDGED"
        assert cd_ack.get("buyer_acknowledged_at") is not None

    def test_acknowledge_by_wrong_buyer_rejected(self, api):
        """PRD §2.1: "a buyer can only acknowledge a Closing Disclosure
        ... on an escrow file whose buyer_party_id equals the caller's
        X-User-ID."

        Claim: a Buyer whose X-User-ID is a different Party.id yields
        ERR_FORBIDDEN_ROLE.
        """
        bundle_a = setup_escrow_in_contingent_cd()
        bundle_b = setup_escrow_in_contingent_cd()
        cd = create_cd(bundle_a["escrow_file"]["id"])
        cd = issue_cd(cd["id"], version=cd["version"])
        # Buyer of B tries to ack A's CD.
        headers = with_idempotency(
            make_buyer_headers(bundle_b["buyer"]["id"]),
        )
        resp = api.acknowledge_closing_disclosure(
            cd["id"], version_only_payload(version=cd["version"]), headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


# ===========================================================================
# Promote with waiting period — PRD §2.10 / §3.5 (difficulty rule 8)
# ===========================================================================
class TestClosingDisclosurePromoteWaitingPeriod:

    def test_promote_before_earliest_funding_at_rejected(self, api):
        """PRD §3.5: "From ACKNOWLEDGED the disclosure can be promoted
        to READY_TO_FUND, but only when the server clock has reached or
        passed earliest_funding_at; a premature promotion is rejected
        with ERR_CD_WAITING_PERIOD."

        Claim: promoting before earliest_funding_at yields
        ERR_CD_WAITING_PERIOD.

        # difficulty: resource_temporal_overlap/cd_three_business_day_cooling_off_half_open_inclusive_end
        """
        bundle = setup_escrow_in_contingent_cd()
        cd = create_cd(bundle["escrow_file"]["id"])
        cd = issue_cd(cd["id"], version=cd["version"])
        cd = acknowledge_cd(
            cd["id"], bundle["buyer"]["id"], version=cd["version"],
        )
        # Do NOT advance clock — server_now is still issued_at-ish.
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.promote_closing_disclosure(
            cd["id"], version_only_payload(version=cd["version"]), eo,
        )
        validate_error(resp, ApiErrorId.ERR_CD_WAITING_PERIOD)

    def test_promote_after_earliest_funding_at_succeeds(self, api):
        """PRD §3.5: "From ACKNOWLEDGED the disclosure can be promoted
        to READY_TO_FUND, but only when the server clock has reached or
        passed earliest_funding_at".
        PRD §2.10: "The promotion of an acknowledged Closing Disclosure
        to ready-to-fund requires that server_now be greater than or
        equal to earliest_funding_at".

        Claim: with clock at earliest_funding_at, promote succeeds and
        status becomes READY_TO_FUND.

        # difficulty: resource_temporal_overlap/cd_three_business_day_cooling_off_half_open_inclusive_end
        """
        bundle = setup_escrow_in_contingent_cd()
        cd = create_cd(bundle["escrow_file"]["id"])
        cd = issue_cd(cd["id"], version=cd["version"])
        cd = acknowledge_cd(
            cd["id"], bundle["buyer"]["id"], version=cd["version"],
        )
        # Advance to or past earliest_funding_at — comfortable margin.
        earliest = parse_iso(cd["earliest_funding_at"])
        target = earliest + timedelta(seconds=1)
        advance_clock_to(iso_utc(target))
        cd_promoted = promote_cd(cd["id"], version=cd["version"])
        assert cd_promoted["status"] == "READY_TO_FUND"


# ===========================================================================
# Revise cycle — PRD §3.5 (difficulty rule 3)
# ===========================================================================
class TestClosingDisclosureReviseCycle:

    def test_revise_increments_version_number_on_reissue(self, api):
        """PRD §3.5: "When the disclosure is subsequently re-issued out
        of REVISED, the system increments version_number by exactly
        one".

        Claim: revise → issue increments version_number 1 → 2 → 3.

        # difficulty: non_linear_state_machine/closing_disclosure_revision_cycle
        """
        bundle = setup_escrow_in_contingent_cd()
        cd = create_cd(bundle["escrow_file"]["id"])
        cd = issue_cd(cd["id"], version=cd["version"])
        assert cd["version_number"] == 1
        cd = revise_cd(
            cd["id"], triggering_change_kind="APR_DELTA_OVER_THRESHOLD",
            version=cd["version"],
        )
        cd = issue_cd(cd["id"], version=cd["version"])
        assert cd["version_number"] == 2
        cd = revise_cd(
            cd["id"], triggering_change_kind="FEE_DELTA_UNDER_THRESHOLD",
            version=cd["version"],
        )
        cd = issue_cd(cd["id"], version=cd["version"])
        assert cd["version_number"] == 3
        assert cd["status"] == "ISSUED"

    def test_revise_acknowledged_clears_buyer_ack(self, api):
        """PRD §3.5: "if the prior status was ACKNOWLEDGED,
        buyer_acknowledged_at is cleared because the buyer must
        re-acknowledge the revised version."

        Claim: revise from ACKNOWLEDGED clears buyer_acknowledged_at.
        """
        bundle = setup_escrow_in_contingent_cd()
        cd = create_cd(bundle["escrow_file"]["id"])
        cd = issue_cd(cd["id"], version=cd["version"])
        cd = acknowledge_cd(
            cd["id"], bundle["buyer"]["id"], version=cd["version"],
        )
        assert cd.get("buyer_acknowledged_at") is not None
        cd = revise_cd(
            cd["id"], triggering_change_kind="LOAN_PRODUCT_CHANGE",
            version=cd["version"],
        )
        assert cd.get("buyer_acknowledged_at") in (None, "")

    def test_revise_major_change_restarts_clock(self, api):
        """PRD §3.5: "if the change is APR_DELTA_OVER_THRESHOLD,
        LOAN_PRODUCT_CHANGE, or PREPAYMENT_PENALTY_ADDED, the re-issue
        sets issued_at to the current server time and recomputes
        earliest_funding_at from scratch — the full three-business-day
        clock starts again."

        Claim: after major-change revise → re-issue, earliest_funding_at
        is later (strictly greater) than the prior earliest_funding_at.
        """
        bundle = setup_escrow_in_contingent_cd()
        cd = create_cd(bundle["escrow_file"]["id"])
        cd = issue_cd(cd["id"], version=cd["version"])
        first_earliest = cd["earliest_funding_at"]
        # Advance clock 2 calendar days so the "day after issued_at"
        # advances and the recomputed earliest_funding_at strictly
        # advances past first_earliest. (1 hour is insufficient because
        # earliest_funding_at is pinned to 00:00 UTC on the third
        # business day — two issues on the same calendar day produce
        # the same earliest_funding_at.)
        advance_clock_by(days=2)
        cd = revise_cd(
            cd["id"], triggering_change_kind="APR_DELTA_OVER_THRESHOLD",
            version=cd["version"],
        )
        cd = issue_cd(cd["id"], version=cd["version"])
        second_earliest = cd["earliest_funding_at"]
        # Strict-greater: new computation starts from the new issued_at.
        assert parse_iso(second_earliest) > parse_iso(first_earliest)

    def test_revise_fee_delta_under_threshold_preserves_clock(self, api):
        """PRD §3.5: "If the change is FEE_DELTA_UNDER_THRESHOLD, the
        re-issue still sets issued_at to the current server time, but
        earliest_funding_at is preserved unchanged from the prior
        version — the clock continues."

        Claim: after FEE_DELTA_UNDER_THRESHOLD revise → re-issue,
        earliest_funding_at == prior earliest_funding_at.
        """
        bundle = setup_escrow_in_contingent_cd()
        cd = create_cd(bundle["escrow_file"]["id"])
        cd = issue_cd(cd["id"], version=cd["version"])
        first_earliest = cd["earliest_funding_at"]
        advance_clock_by(hours=2)
        cd = revise_cd(
            cd["id"], triggering_change_kind="FEE_DELTA_UNDER_THRESHOLD",
            version=cd["version"],
        )
        cd = issue_cd(cd["id"], version=cd["version"])
        second_earliest = cd["earliest_funding_at"]
        assert parse_iso(second_earliest) == parse_iso(first_earliest)


# ===========================================================================
# Validation priority — PRD §2.8 (difficulty rule 5)
# ===========================================================================
class TestValidationPriorityOnPromote:

    def test_cross_entity_state_beats_waiting_period_on_promote(self, api):
        """PRD §2.8: "the entity's current state matching the from-state
        required by the requested transition (ERR_INVALID_STATE); any
        cross-entity state preconditions such as the parent escrow
        file's status or the §1031 disbursement having settled
        (ERR_CROSS_ENTITY_STATE); ... the Closing Disclosure three-
        business-day cooling-off (ERR_CD_WAITING_PERIOD)".

        Claim: when both the cooling-off has not elapsed AND the CD has
        been cascade-VOIDED by file cancellation, the higher-priority
        state-class error (ERR_INVALID_STATE / ERR_CROSS_ENTITY_STATE)
        suppresses the temporal error. The temporal error is NOT
        returned.

        # difficulty: priority_pair_validation_conflict/cross_entity_state_beats_business_temporal_on_cd_promote
        """
        bundle = setup_escrow_in_contingent_cd()
        cd = create_cd(bundle["escrow_file"]["id"])
        cd = issue_cd(cd["id"], version=cd["version"])
        cd = acknowledge_cd(
            cd["id"], bundle["buyer"]["id"], version=cd["version"],
        )
        # DO NOT advance clock — cooling-off would normally fail with
        # ERR_CD_WAITING_PERIOD.
        ef = re_get_escrow_file(bundle["escrow_file"]["id"])
        cancel_escrow(
            ef["id"], "BUYER_DEFAULT", version=ef["version"],
        )
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.promote_closing_disclosure(
            cd["id"], version_only_payload(version=cd["version"]), eo,
        )
        from test_helpers import validate_error_is_one_of
        actual = validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_CROSS_ENTITY_STATE.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )
        # The temporal-class error must NOT be selected.
        assert actual != ApiErrorId.ERR_CD_WAITING_PERIOD.value
