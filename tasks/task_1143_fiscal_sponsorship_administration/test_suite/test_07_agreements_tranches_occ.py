"""Agreements, grant tranches, model gates, and optimistic concurrency
(PRD §2.4, §2.7, §2.10, §3.2)."""
from test_helpers import (
    ApiErrorId,
    amend_agreement_payload,
    close_tranche,
    countersign,
    create_active_bundle,
    create_approved_bundle,
    create_grant_tranche_payload,
    create_tranche,
    fund_adjustment_payload,
    get_agreement,
    get_fund,
    get_project,
    make_applicant_headers,
    make_finance_officer_headers,
    make_sponsor_admin_headers,
    set_clock,
    validate_error,
    validate_success,
)


class TestCountersignCascade:
    def test_countersign_side_effects(self, api):
        """PRD §3.2: "Countersignature fires a three-way activation: the agreement
        moves to `ACTIVE`, the project moves from `PROPOSED` to `ACTIVE`, and the fund
        moves from `PENDING` to `ACTIVE`."

        Design: Corner/state_machines/sm_countersign_side_effects
        """
        bundle = create_approved_bundle("user_c_cs", project_name="CS", contact_email="cs@x.org")
        activated = countersign(bundle["agreement_id"], bundle["applicant_id"])
        assert activated["status"] == "ACTIVE"
        assert get_project(bundle["project_id"])["status"] == "ACTIVE"
        assert get_fund(bundle["fund_account_id"])["status"] == "ACTIVE"


class TestTrancheGuards:
    def test_tranche_period_invalid(self, api):
        """PRD §3.2: "A `period_end` earlier than its `period_start` is rejected with
        `ERR_TRANCHE_PERIOD_INVALID`."

        Design: Corner/validations/v_tranche_period_invalid
        """
        bundle = create_active_bundle("user_c_v11", model="PRE_APPROVED_GRANT",
                                      project_name="TP", contact_email="tp@x.org")
        resp = api.create_grant_tranche(
            bundle["agreement_id"],
            create_grant_tranche_payload(amount_cents=100000, period_start="2026-06-01",
                                         period_end="2026-01-01", purpose="backwards"),
            make_sponsor_admin_headers())
        validate_error(resp, ApiErrorId.ERR_TRANCHE_PERIOD_INVALID)

    def test_tranche_on_comprehensive_model_mismatch(self, api):
        """PRD §3.2: "Issuance against a comprehensive agreement is rejected with
        `ERR_MODEL_MISMATCH`."

        Design: Corner/validations/v_tranche_on_comprehensive_model_mismatch
        """
        bundle = create_active_bundle("user_c_v14", model="COMPREHENSIVE",
                                      project_name="MM", contact_email="mm@x.org")
        resp = api.create_grant_tranche(
            bundle["agreement_id"],
            create_grant_tranche_payload(amount_cents=100000, period_start="2026-01-01",
                                         period_end="2026-03-31", purpose="wrong model"),
            make_sponsor_admin_headers())
        validate_error(resp, ApiErrorId.ERR_MODEL_MISMATCH)

    def test_tranche_close_before_period_end_rejected(self, api):
        """PRD §3.2: "Once the logical clock's calendar date is strictly later than a
        tranche's `period_end`, a `SponsorAdmin` closes it with a mandatory
        `report_note`; closing earlier, or closing an already `CLOSED` tranche, is
        rejected with `ERR_TRANCHE_STATE_INVALID`."
        PRD §2.4: "it runs on a logical clock whose startup value is exactly
        `2026-05-01T00:00:00Z`."

        Design: Corner/state_machines/sm_tranche_close_before_period_end_rejected
        """
        bundle = create_active_bundle("user_c_tc", model="PRE_APPROVED_GRANT",
                                      project_name="TC", contact_email="tc@x.org")
        tranche = create_tranche(bundle["agreement_id"], amount_cents=100000,
                                 period_start="2026-01-01", period_end="2026-06-30",
                                 purpose="h1")
        # Startup clock 2026-05-01 is on/before period_end 2026-06-30 -> too early.
        resp = api.close_grant_tranche(tranche["id"], {"report_note": "early"},
                                       make_sponsor_admin_headers())
        validate_error(resp, ApiErrorId.ERR_TRANCHE_STATE_INVALID)

        set_clock("2026-07-01T00:00:00Z")
        closed = close_tranche(tranche["id"], report_note="final report")
        assert closed["status"] == "CLOSED"

    def test_tranche_day_adjacency_legal(self, api):
        """PRD §3.2: "Two tranches on the same agreement may not share a single
        calendar day: any overlap of their closed intervals is rejected with
        `ERR_TRANCHE_PERIOD_OVERLAP` (HTTP 409), while pure adjacency — one tranche's
        `period_start` exactly one day after another's `period_end` — is legal."
        T1 [2026-01-01, 2026-03-31]; T2 starting 2026-04-01 shares no calendar day.

        Design: Difficulty/resource_temporal_overlap/tranche_closed_interval_overlap
        """
        bundle = create_active_bundle("user_app_u", model="PRE_APPROVED_GRANT",
                                      project_name="Phi", contact_email="ph@x.org")
        create_tranche(bundle["agreement_id"], amount_cents=500000,
                       period_start="2026-01-01", period_end="2026-03-31",
                       purpose="Q1 programs")
        t2 = create_tranche(bundle["agreement_id"], amount_cents=300000,
                            period_start="2026-04-01", period_end="2026-06-30",
                            purpose="Q2 programs")
        assert t2["status"] == "ISSUED", "end+1-day adjacency is legal under closed intervals"

    def test_tranche_shared_single_day_rejected(self, api):
        """PRD §3.2: "Two tranches on the same agreement may not share a single
        calendar day: any overlap of their closed intervals is rejected with
        `ERR_TRANCHE_PERIOD_OVERLAP` (HTTP 409)"
        T3 [2026-03-31, 2026-05-31] shares exactly the calendar day 2026-03-31 with
        T1 [2026-01-01, 2026-03-31] — adjacency that half-open semantics would allow
        but closed-interval semantics forbids.

        Design: Difficulty/resource_temporal_overlap/tranche_closed_interval_overlap
        """
        bundle = create_active_bundle("user_app_u2", model="PRE_APPROVED_GRANT",
                                      project_name="Phi2", contact_email="ph2@x.org")
        create_tranche(bundle["agreement_id"], amount_cents=500000,
                       period_start="2026-01-01", period_end="2026-03-31",
                       purpose="Q1 programs")
        resp = api.create_grant_tranche(
            bundle["agreement_id"],
            create_grant_tranche_payload(amount_cents=100000, period_start="2026-03-31",
                                         period_end="2026-05-31", purpose="overlap probe"),
            make_sponsor_admin_headers())
        validate_error(resp, ApiErrorId.ERR_TRANCHE_PERIOD_OVERLAP)


class TestAmendModelGateAndRbac:
    def test_forward_basis_on_grant_model_mismatch(self, api):
        """PRD §2.7: "an agreement's `spending_basis` may be `FORWARD_LOOKING` only
        under `COMPREHENSIVE`; the value `SETTLED` is the default and is the only legal
        value under `PRE_APPROVED_GRANT`, and an amendment that would set
        `FORWARD_LOOKING` on a grant-model agreement is rejected with
        `ERR_MODEL_MISMATCH`."
        The request carries the agreement's current version, so the §2.10 OCC check
        passes and only the model gate can fire.

        Design: Corner/validations/v_forward_basis_on_grant_model_mismatch
        """
        bundle = create_active_bundle("user_c_v15", model="PRE_APPROVED_GRANT",
                                      project_name="MB", contact_email="mb@x.org")
        agreement = get_agreement(bundle["agreement_id"])
        resp = api.amend_agreement(
            bundle["agreement_id"],
            amend_agreement_payload(agreement["version"], spending_basis="FORWARD_LOOKING"),
            make_sponsor_admin_headers())
        validate_error(resp, ApiErrorId.ERR_MODEL_MISMATCH)

    def test_applicant_cannot_amend_agreement(self, api):
        """PRD §2.1: "A request whose role is not on the target endpoint's authorized
        list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /fsa/agreements/{id}/amend is authorized for SponsorAdmin only.

        Design: Corner/rbac/rbac_applicant_cannot_amend_agreement
        """
        bundle = create_active_bundle("user_c_b8", project_name="RB8", contact_email="rb8@x.org")
        agreement = get_agreement(bundle["agreement_id"])
        resp = api.amend_agreement(
            bundle["agreement_id"],
            amend_agreement_payload(agreement["version"], note="applicant attempt"),
            make_applicant_headers(bundle["applicant_id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestOptimisticConcurrency:
    def test_occ_fund_adjustment_stale_version_rejected(self, api):
        """PRD §2.10: "Posting a manual adjustment against a fund requires
        `expected_fund_account_version` in the request body, carrying the `FundAccount`
        `version` the client last observed; if another write has advanced the fund's
        version since, the adjustment is rejected with `ERR_STALE_FUND_VERSION`
        (HTTP 412)"
        PRD §2.5: "The `version` is an integer that starts at 1 and increments by
        exactly 1 on every mutation"

        Design: Corner/cross_cutting_complexity_layers/occ_fund_adjustment_stale_version_rejected
        """
        bundle = create_active_bundle("user_c_o1", project_name="OC1", contact_email="oc1@x.org")
        fid = bundle["fund_account_id"]
        observed = get_fund(fid)["version"]

        first = validate_success(api.post_fund_adjustment(
            fid, fund_adjustment_payload(observed, 5000, memo="correction in"),
            make_finance_officer_headers()))
        assert first["version"] == observed + 1, "successful adjustment bumps version by 1"

        stale = api.post_fund_adjustment(
            fid, fund_adjustment_payload(observed, -5000, memo="stale writer"),
            make_finance_officer_headers("user_fo_2"))
        validate_error(stale, ApiErrorId.ERR_STALE_FUND_VERSION)
        assert get_fund(fid)["total_adjustments_cents"] == 5000, (
            "the stale writer folds nothing into the signed adjustment total")

    def test_occ_agreement_amend_stale_version_rejected(self, api):
        """PRD §2.10: "Amending an agreement requires `expected_agreement_version`
        against the `SponsorshipAgreement` `version`; a mismatch is rejected with
        `ERR_STALE_AGREEMENT_VERSION` (HTTP 412), because an amendment supersedes the
        prior terms as a whole and must be based on their current state."
        PRD §3.2: "A successful amendment increments the agreement's `version` by one
        and updates the terms: `spending_basis` (`SETTLED` or, for `COMPREHENSIVE`
        agreements only, `FORWARD_LOOKING` — otherwise `ERR_MODEL_MISMATCH`),
        `effective_date`, and `amendment_note`, the last taken from the request's
        `note` field."

        Design: Corner/cross_cutting_complexity_layers/occ_agreement_amend_stale_version_rejected
        """
        bundle = create_active_bundle("user_c_o2", project_name="OC2", contact_email="oc2@x.org")
        agid = bundle["agreement_id"]
        observed = get_agreement(agid)["version"]

        first = validate_success(api.amend_agreement(
            agid, amend_agreement_payload(observed, note="first"),
            make_sponsor_admin_headers()))
        assert first["version"] == observed + 1

        stale = api.amend_agreement(
            agid, amend_agreement_payload(observed, note="stale second"),
            make_sponsor_admin_headers("user_sa_2"))
        validate_error(stale, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)
        assert get_agreement(agid)["amendment_note"] == "first", (
            "the rejected stale amendment leaves the recorded terms untouched")
