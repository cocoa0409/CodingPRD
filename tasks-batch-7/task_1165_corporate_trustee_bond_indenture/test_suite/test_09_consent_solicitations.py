"""Consent solicitations: tabulation bases, record-date snapshots, window
occupation (closed intervals), expiry discipline, duplicate ballots, target
validation (PRD §3.6)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    CLOCK_START, set_clock,
    create_active_indenture_with_tranche, setup_indenture_with_positions,
    register_account,
    create_redemption_run, fund_run, execute_run,
    create_solicitation, open_solicitation, create_open_solicitation,
    cast_ballot, close_solicitation, get_solicitation, get_tranche,
    create_consent_solicitation_payload, create_ballot_payload,
    make_issuer_headers, make_noteholder_headers, make_trust_officer_headers,
)

OFFICER = make_trust_officer_headers("officer-1")


class TestTabulationBasisDivergence:
    def _setup_dual_basis_scenario(self, api):
        """Positions A 400M / B 350M / C 250M. S1 RECORD_DATE (record_date
        2026-06-01) with A+B CONSENT cast at 2026-06-05; a 99999999
        redemption executes at 2026-06-10; S1 closes PASSED. S2
        CURRENT_OUTSTANDING with identical ballots cast after the
        redemption."""
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000, 350000000, 250000000),
            holder_prefixes=("H-A", "H-B", "H-C"),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 1000000000,
                               "notice_period_days": 30},
            reset_clock=False)
        indenture, tranche = ctx["indenture"], ctx["tranche"]
        account_a, account_b, _ = ctx["accounts"]

        sol1 = create_solicitation(
            indenture["id"], issuer_ref="issuer-1", subject_type="AMEND_TERMS",
            amendment_payload={"annual_admin_fee_cents": 2600000},
            consent_threshold_bps=8000, tabulation_basis="RECORD_DATE",
            record_date="2026-06-01", expiry_date="2026-07-01")
        open_solicitation(sol1["id"])
        set_clock("2026-06-05T00:00:00Z")
        cast_ballot(sol1["id"], account_a["id"], "CONSENT")
        cast_ballot(sol1["id"], account_b["id"], "CONSENT")

        set_clock("2026-06-10T00:00:00Z")
        redemption = create_redemption_run(tranche["id"], 99999999,
                                           scheduled_payment_date="2026-07-15")
        fund_run(redemption["id"], 99999999, issuer_ref="issuer-1")
        execute_run(redemption["id"])

        sol1 = close_solicitation(sol1["id"])

        sol2 = create_solicitation(
            indenture["id"], issuer_ref="issuer-1", subject_type="AMEND_TERMS",
            amendment_payload={"annual_admin_fee_cents": 2600000},
            consent_threshold_bps=8000, tabulation_basis="CURRENT_OUTSTANDING",
            record_date="2026-06-01", expiry_date="2026-07-01")
        open_solicitation(sol2["id"])
        cast_ballot(sol2["id"], account_a["id"], "CONSENT")
        cast_ballot(sol2["id"], account_b["id"], "CONSENT")
        ctx.update({"sol1": sol1, "sol2": sol2})
        return ctx

    def test_record_date_solicitation_passes_despite_interim_redemption(self, api):
        """PRD §3.6: "under `RECORD_DATE`, each ballot's weight is frozen at
        the holder's aggregate principal as of the end of `record_date` (the
        latest `principal_history` entry per position whose `effective_from`
        is at or before 23:59:59.999 UTC on the record date governs, and a
        position whose first history entry postdates the record date
        contributes zero), so redemptions executed between the record date
        and close do not change weights"
        PRD §3.6: "The solicitation becomes `PASSED` when the consenting
        weight multiplied by ten thousand is at least `consent_threshold_bps`
        multiplied by the eligible principal — integer cross-multiplication
        with no floating-point division"

        Record-date weights A+B = 750000000; eligible at close 900000001:
        750000000*10000 >= 8000*900000001.

        Design: Difficulty/dual_variant_calc/consent_record_date_vs_current_outstanding
        """
        ctx = self._setup_dual_basis_scenario(api)
        sol1 = ctx["sol1"]
        assert sol1["status"] == "PASSED"
        assert sol1["consenting_principal_cents"] == 750000000, (
            "weights frozen at the record date")

    def test_current_outstanding_solicitation_fails_after_interim_redemption(self, api):
        """PRD §3.6: "under `CURRENT_OUTSTANDING` weights are recomputed at
        close, so interim redemptions reduce them and identical ballots yield
        a smaller tally."

        Current weights A+B = 360000001+315000000 = 675000001;
        675000001*10000 < 8000*900000001.

        Design: Difficulty/dual_variant_calc/consent_record_date_vs_current_outstanding
        """
        ctx = self._setup_dual_basis_scenario(api)
        sol2 = close_solicitation(ctx["sol2"]["id"])
        assert sol2["status"] == "FAILED", (
            "identical ballots fail under CURRENT_OUTSTANDING after the "
            "interim redemption")
        assert sol2["consenting_principal_cents"] == 675000001

        tranche = get_tranche(ctx["tranche"]["id"])
        assert tranche["outstanding_principal_cents"] == 900000001


class TestZeroBallotClose:
    def _setup_zero_ballot_solicitation(self, api):
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        solicitation = create_open_solicitation(
            ctx["indenture"]["id"], issuer_ref="issuer-1",
            subject_type="AMEND_TERMS",
            amendment_payload={"annual_admin_fee_cents": 2600000},
            consent_threshold_bps=5000, tabulation_basis="CURRENT_OUTSTANDING",
            record_date="2026-06-01", expiry_date="2026-07-01")
        ctx["solicitation"] = solicitation
        return ctx

    def test_close_with_zero_ballots_fails(self, api):
        """PRD §3.6: "and `FAILED` otherwise, with zero ballots failing any
        positive threshold because the consenting weight is zero."

        Clock 2026-06-15, on or before expiry 2026-07-01: the outcome is
        FAILED, not EXPIRED.

        Design: Difficulty/boundary_precision_check/zero_ballot_close_fails_with_zero_tally
        """
        ctx = self._setup_zero_ballot_solicitation(api)
        set_clock("2026-06-15T00:00:00Z")
        closed = close_solicitation(ctx["solicitation"]["id"])
        assert closed["status"] == "FAILED"
        assert closed["consenting_principal_cents"] == 0
        assert closed["ballots"] == []

    def test_close_at_expiry_date_still_tabulates(self, api):
        """PRD §3.6: "When the clock's date is on or before `expiry_date`,
        eligible principal is the sum of `principal_amount_cents` over
        `ACTIVE` positions of the indenture's tranches in `ACTIVE` or
        `ACCELERATED` status"
        PRD §3.6: "When the clock's date is past `expiry_date` at close, the
        solicitation becomes `EXPIRED` regardless of the tally — expiry wins
        over tabulation."

        At exactly the expiry date the close tabulates (and with zero ballots
        fails the threshold) rather than lapsing to EXPIRED.

        Design: Difficulty/boundary_precision_check/zero_ballot_close_fails_with_zero_tally
        """
        ctx = self._setup_zero_ballot_solicitation(api)
        set_clock("2026-07-01T00:00:00Z")  # exactly the expiry date
        closed = close_solicitation(ctx["solicitation"]["id"])
        assert closed["status"] == "FAILED", (
            "on the expiry date itself the close tabulates; zero ballots fail")
        assert closed["consenting_principal_cents"] == 0


class TestRecordDateSnapshot:
    def test_record_date_ballot_weight_snapshot(self, api):
        """PRD §3.6: "under `RECORD_DATE`, each ballot's weight is frozen at
        the holder's aggregate principal as of the end of `record_date` (the
        latest `principal_history` entry per position whose `effective_from`
        is at or before 23:59:59.999 UTC on the record date governs, and a
        position whose first history entry postdates the record date
        contributes zero)"
        PRD §3.6: "Each accepted ballot appends to the solicitation's
        `ballots` array an entry recording the account, the `vote`, the
        `principal_voted_cents` weight computed per the tabulation basis, and
        the `cast_at` instant"

        Design: Corner/calculations/record_date_ballot_weight_uses_principal_history
        """
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(250000000, 750000000),
            holder_prefixes=("H-C", "H-R"),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 1000000000,
                               "notice_period_days": 30},
            reset_clock=False)
        account_c = ctx["accounts"][0]
        solicitation = create_open_solicitation(
            ctx["indenture"]["id"], issuer_ref="issuer-1",
            subject_type="AMEND_TERMS",
            amendment_payload={"annual_admin_fee_cents": 2600000},
            consent_threshold_bps=5000, tabulation_basis="RECORD_DATE",
            record_date="2026-06-01", expiry_date="2026-07-01")

        # Redemption executes after the record date, before the ballot.
        set_clock("2026-06-10T00:00:00Z")
        redemption = create_redemption_run(ctx["tranche"]["id"], 99999999,
                                           scheduled_payment_date="2026-07-15")
        fund_run(redemption["id"], 99999999, issuer_ref="issuer-1")
        execute_run(redemption["id"])

        cast_ballot(solicitation["id"], account_c["id"], "CONSENT")
        solicitation = get_solicitation(solicitation["id"])
        ballot = next(b for b in solicitation["ballots"]
                      if b["noteholder_account_id"] == account_c["id"])
        assert ballot["principal_voted_cents"] == 250000000, (
            "record-date snapshot governs even though the ballot postdates "
            "the redemption")

        from test_helpers import get_position
        position = get_position(ctx["positions"][0]["id"])
        assert position["principal_amount_cents"] == 225000000, (
            "current principal diverges from the record-date snapshot")


class TestSolicitationWindowOccupation:
    def _setup_first_solicitation(self, api):
        set_clock(CLOCK_START)
        indenture, tranche = create_active_indenture_with_tranche(reset_clock=False)
        sol1 = create_solicitation(
            indenture["id"], issuer_ref="issuer-1", subject_type="AMEND_TERMS",
            amendment_payload={"annual_admin_fee_cents": 2600000},
            consent_threshold_bps=5000, tabulation_basis="CURRENT_OUTSTANDING",
            record_date="2026-06-01", expiry_date="2026-07-01")
        return indenture, sol1

    def test_solicitation_shared_boundary_date_collides(self, api):
        """PRD §3.6: "Solicitation windows are the **closed** interval from
        `record_date` through `expiry_date`, and the windows of one
        indenture's solicitations must not overlap another solicitation in
        `DRAFT` or `OPEN` — a shared boundary date already counts as a
        collision, and an overlapping creation is rejected with
        `ERR_SOLICITATION_WINDOW_OVERLAP`."

        [2026-07-01, 2026-08-01] shares the closed boundary 2026-07-01 with
        [2026-06-01, 2026-07-01].

        Design: Difficulty/resource_temporal_overlap/solicitation_window_closed_interval_adjacency_collides
        """
        indenture, sol1 = self._setup_first_solicitation(api)
        payload = create_consent_solicitation_payload(
            indenture["id"], amendment_payload={"annual_admin_fee_cents": 2700000},
            record_date="2026-07-01", expiry_date="2026-08-01")
        resp = api.create_consent_solicitation(payload, make_issuer_headers("issuer-1"))
        validate_error(resp, ApiErrorId.ERR_SOLICITATION_WINDOW_OVERLAP)

    def test_solicitation_window_starting_next_day_accepted(self, api):
        """PRD §3.6: "Solicitation windows are the **closed** interval from
        `record_date` through `expiry_date`, and the windows of one
        indenture's solicitations must not overlap another solicitation in
        `DRAFT` or `OPEN` — a shared boundary date already counts as a
        collision"

        [2026-07-02, 2026-08-01] shares no date with [2026-06-01, 2026-07-01].

        Design: Difficulty/resource_temporal_overlap/solicitation_window_closed_interval_adjacency_collides
        """
        indenture, sol1 = self._setup_first_solicitation(api)
        payload = create_consent_solicitation_payload(
            indenture["id"], amendment_payload={"annual_admin_fee_cents": 2700000},
            record_date="2026-07-02", expiry_date="2026-08-01")
        resp = api.create_consent_solicitation(payload, make_issuer_headers("issuer-1"))
        sol2 = validate_success(resp, 201)
        assert sol2["status"] == "DRAFT"


class TestExpiredBallotPriority:
    def _setup_expired_solicitation(self, api, with_holder_d=False):
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        solicitation = create_open_solicitation(
            ctx["indenture"]["id"], issuer_ref="issuer-1",
            subject_type="AMEND_TERMS",
            amendment_payload={"annual_admin_fee_cents": 2600000},
            consent_threshold_bps=5000, tabulation_basis="CURRENT_OUTSTANDING",
            record_date="2026-06-01", expiry_date="2026-06-30")
        account_d = register_account("H-D", "Holder D", "d@x.com") if with_holder_d else None
        set_clock("2026-07-01T00:00:00Z")  # past expiry
        ctx["solicitation"] = solicitation
        ctx["account_d"] = account_d
        return ctx

    def test_expired_ballot_reports_expiry_not_eligibility(self, api):
        """PRD §2.8: "when several rules are violated at once the rejection
        carries the error of the **earliest** rule in the stack."
        PRD §2.8: "17. Solicitation expiry — `ERR_SOLICITATION_EXPIRED`."
        PRD §2.8: "23. Holder-of-record eligibility and substitution-field
        freshness — `ERR_NO_ELIGIBLE_POSITION`."

        Holder D has no positions (rule 23 violated) and the ballot is cast
        after expiry (rule 17 violated): the earlier rule wins.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_expired_ballot
        """
        ctx = self._setup_expired_solicitation(api, with_holder_d=True)
        account_d = ctx["account_d"]
        resp = api.cast_ballot(
            ctx["solicitation"]["id"],
            create_ballot_payload(account_d["id"], "CONSENT"),
            make_noteholder_headers(account_d["id"]))
        error = validate_error(resp, ApiErrorId.ERR_SOLICITATION_EXPIRED)
        assert error["error_id"] != "ERR_NO_ELIGIBLE_POSITION", (
            "temporal rule (priority 17) precedes eligibility (priority 23)")

    def test_expired_ballot_by_eligible_holder_also_expired(self, api):
        """PRD §3.6: "balloting after `expiry_date` is rejected with
        `ERR_SOLICITATION_EXPIRED`"

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_expired_ballot
        """
        ctx = self._setup_expired_solicitation(api)
        account_a = ctx["accounts"][0]  # holds 400000000 — eligibility clean
        resp = api.cast_ballot(
            ctx["solicitation"]["id"],
            create_ballot_payload(account_a["id"], "CONSENT"),
            make_noteholder_headers(account_a["id"]))
        validate_error(resp, ApiErrorId.ERR_SOLICITATION_EXPIRED)

        solicitation = get_solicitation(ctx["solicitation"]["id"])
        assert solicitation["status"] == "OPEN", "failed ballot changes nothing"
        assert solicitation["ballots"] == []


class TestBallotAndTargetConstraints:
    def test_duplicate_ballot_rejected(self, api):
        """PRD §3.6: "At most one ballot exists per solicitation and account
        (a repeat is `ERR_DUPLICATE_CONSTRAINT`)"

        Design: Corner/validations/duplicate_ballot_rejected
        """
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        solicitation = create_open_solicitation(
            ctx["indenture"]["id"], issuer_ref="issuer-1",
            record_date="2026-06-01", expiry_date="2026-07-01")
        account_a = ctx["accounts"][0]
        cast_ballot(solicitation["id"], account_a["id"], "CONSENT")

        resp = api.cast_ballot(
            solicitation["id"], create_ballot_payload(account_a["id"], "WITHHOLD"),
            make_noteholder_headers(account_a["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CONSTRAINT)

        solicitation = get_solicitation(solicitation["id"])
        assert len(solicitation["ballots"]) == 1, "the first vote stands"
        assert solicitation["ballots"][0]["vote"] == "CONSENT"

    def test_waive_covenant_target_validation(self, api):
        """PRD §3.6: "A `WAIVE_COVENANT` solicitation requires
        `target_obligation_id` referencing a covenant obligation **of the same
        indenture** — a missing or cross-indenture target is rejected with
        `ERR_TARGET_OBLIGATION_MISMATCH`."

        Design: Corner/validations/waive_covenant_without_target_rejected
        """
        from test_helpers import create_obligation
        indenture1, _ = create_active_indenture_with_tranche(
            indenture_overrides={"name": "I1"})
        indenture2, _ = create_active_indenture_with_tranche(
            indenture_overrides={"name": "I2"}, reset_clock=False)
        obligation2 = create_obligation(
            indenture2["id"], covenant_type="INSURANCE_CERT",
            frequency="ANNUAL", period_anchor_date="2026-12-31")

        issuer = make_issuer_headers("issuer-1")
        # Missing target_obligation_id entirely.
        payload = create_consent_solicitation_payload(
            indenture1["id"], subject_type="WAIVE_COVENANT",
            amendment_payload=None)
        payload.pop("amendment_payload", None)
        resp = api.create_consent_solicitation(payload, issuer)
        validate_error(resp, ApiErrorId.ERR_TARGET_OBLIGATION_MISMATCH)

        # Cross-indenture target: the obligation belongs to I2.
        payload["target_obligation_id"] = obligation2["id"]
        resp = api.create_consent_solicitation(payload, issuer)
        validate_error(resp, ApiErrorId.ERR_TARGET_OBLIGATION_MISMATCH)
