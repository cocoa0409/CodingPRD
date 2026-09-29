"""Endpoint contracts: panel-status updates, recovery links, preview and posture."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLAIMS_EXAMINER_HEADERS,
    ERR_CAPITATION_POSTURE_RESTRICTED,
    IPA_ADMIN_HEADERS,
    NETWORK_MANAGER_HEADERS,
    assert_fields,
    assign_enrollee,
    build_final_scorecard,
    build_paid_claim,
    build_posted_file,
    build_single_member_funded_pool,
    close_incurral,
    create_active_agreement,
    create_active_physician,
    create_enrollee,
    create_pool,
    create_recovery,
    expected_recovery_figures,
    expected_settlement_waterfall,
    list_pool_distributions,
    propose_settlement,
    read_agreement,
    read_physician,
    read_pool,
    read_recovery,
    reserve_pool,
    set_clock,
    state_payload,
)


def _active_physician_on_an_open_panel(api):
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(api, max_panel_size=5)
    physician = create_active_physician(api, agreement["id"])
    return agreement, physician


def _patch_panel(api, physician_id, panel_status, headers=None):
    return api.set_panel_status(
        physician_id,
        {"panel_status": panel_status},
        headers or NETWORK_MANAGER_HEADERS,
    )


class TestPanelStatusPatchAndReadback:
    def test_closing_a_panel_returns_the_new_panel_status(self, api):
        """PRD §3.2: "On the panel dimension, closing a panel — `OPEN → CLOSED_TO_NEW` — may be done by a `NetworkManager` or by the `PhysicianUser` on their own record, and requires only that `panel_status` is `OPEN`."

        Design: Corner/endpoints/panel_status_patch_updates_and_readback_matches
        """
        _agreement, physician = _active_physician_on_an_open_panel(api)
        assert physician["panel_status"] == "OPEN"

        closed = validate_success(
            _patch_panel(api, physician["id"], "CLOSED_TO_NEW"), 200
        )
        assert_fields(
            closed, {"panel_status": "CLOSED_TO_NEW", "credential_status": "ACTIVE"}
        )

    def test_the_individual_read_matches_the_patch_response(self, api):
        """PRD §3.2: "A physician record read individually exposes both state dimensions, `panel_size`, `quality_composite_bps` and `continuity_of_care_until`; the agreement's physician roster may be listed with optional `credential_status` and `panel_status` filters."

        Design: Corner/endpoints/panel_status_patch_updates_and_readback_matches
        """
        _agreement, physician = _active_physician_on_an_open_panel(api)
        closed = validate_success(
            _patch_panel(api, physician["id"], "CLOSED_TO_NEW"), 200
        )

        readback = read_physician(api, physician["id"])
        assert_fields(
            readback,
            {
                "panel_status": closed["panel_status"],
                "credential_status": closed["credential_status"],
                "panel_size": closed["panel_size"],
                "version": closed["version"],
                "updated_at": closed["updated_at"],
            },
        )

    def test_each_panel_direction_advances_the_physician_version_by_one(self, api):
        """PRD §3.2: "Both directions advance the physician's `version` by 1."

        Design: Corner/endpoints/panel_status_patch_updates_and_readback_matches
        """
        _agreement, physician = _active_physician_on_an_open_panel(api)

        closed = validate_success(
            _patch_panel(api, physician["id"], "CLOSED_TO_NEW"), 200
        )
        assert closed["version"] == physician["version"] + 1

        reopened = validate_success(_patch_panel(api, physician["id"], "OPEN"), 200)
        assert reopened["version"] == closed["version"] + 1
        assert reopened["panel_status"] == "OPEN"

    def test_the_roster_filter_follows_the_patched_panel_status(self, api):
        """PRD §3.2: "Reopening — `CLOSED_TO_NEW → OPEN` — is reserved to a `NetworkManager` and carries three preconditions: `panel_status` must be `CLOSED_TO_NEW`, `credential_status` must be `ACTIVE`, and the agreement's `capitation_posture` must read `CURRENT`."

        Design: Corner/endpoints/panel_status_patch_updates_and_readback_matches
        """
        agreement, physician = _active_physician_on_an_open_panel(api)
        _patch_panel(api, physician["id"], "CLOSED_TO_NEW")

        closed_rows, closed_meta = validate_paginated(
            api.list_agreement_physicians(
                agreement["id"],
                NETWORK_MANAGER_HEADERS,
                {"panel_status": "CLOSED_TO_NEW", "limit": 10, "offset": 0},
            )
        )
        assert closed_meta["total_count"] == 1
        assert closed_rows[0]["id"] == physician["id"]

        _patch_panel(api, physician["id"], "OPEN")
        open_rows, open_meta = validate_paginated(
            api.list_agreement_physicians(
                agreement["id"],
                NETWORK_MANAGER_HEADERS,
                {"panel_status": "OPEN", "limit": 10, "offset": 0},
            )
        )
        assert open_meta["total_count"] == 1
        assert open_rows[0]["id"] == physician["id"]


def _two_members_with_paid_claims_over_a_low_attachment(api):
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        stop_loss_attachment_cents=1000,
        reinsurance_recovery_bps=9000,
        professional_pool_share_bps=10000,
        institutional_pool_share_bps=0,
        quality_withhold_bps=0,
        max_panel_size=5,
    )
    physician = create_active_physician(api, agreement["id"])
    pool = create_pool(api, agreement["id"], pool_type="PROFESSIONAL")

    first = create_enrollee(api, agreement["id"], external_member_id="SL-0001")
    assign_enrollee(api, first["id"], physician["id"])
    second = create_enrollee(api, agreement["id"], external_member_id="SL-0002")
    assign_enrollee(api, second["id"], physician["id"])

    set_clock(api, "2026-08-01T00:00:00Z")
    build_posted_file(
        api,
        agreement["id"],
        [
            {
                "external_member_id": first["external_member_id"],
                "physician_npi": physician["npi"],
                "claimed_capitation_cents": 20000,
            },
            {
                "external_member_id": second["external_member_id"],
                "physician_npi": physician["npi"],
                "claimed_capitation_cents": 20000,
            },
        ],
    )
    build_paid_claim(
        api,
        agreement["id"],
        first["id"],
        physician["id"],
        6000,
        service_date="2026-07-10T00:00:00Z",
    )
    build_paid_claim(
        api,
        agreement["id"],
        second["id"],
        physician["id"],
        3000,
        service_date="2026-07-12T00:00:00Z",
    )
    return agreement, physician, pool, first, second


class TestStopLossRecoveryLinksPoolAndEnrollee:
    def test_the_recovery_snapshots_the_agreement_attachment_point(self, api):
        """PRD §3.7: "`attachment_cents` is snapshotted from the agreement's `stop_loss_attachment_cents` so a later contract amendment cannot retroactively move an already-filed recovery's attachment point."

        Design: Corner/endpoints/stop_loss_recovery_links_pool_and_enrollee_with_snapshot_fields
        """
        agreement, _physician, pool, first, _second = (
            _two_members_with_paid_claims_over_a_low_attachment(api)
        )

        recovery = create_recovery(api, pool["id"], first["id"])
        assert_fields(
            recovery,
            expected_recovery_figures(
                6000,
                agreement["stop_loss_attachment_cents"],
                agreement["reinsurance_recovery_bps"],
            ),
        )
        assert recovery["attachment_cents"] == 1000
        assert recovery["recovery_cents"] == 4500

    def test_the_recovery_opens_in_draft_with_no_user_ids_recorded(self, api):
        """PRD §3.7: "The record begins in `status` `DRAFT` with `submitted_by_user_id`, `adjudicated_by_user_id` and `denial_reason` all null."

        Design: Corner/endpoints/stop_loss_recovery_links_pool_and_enrollee_with_snapshot_fields
        """
        _agreement, _physician, pool, first, _second = (
            _two_members_with_paid_claims_over_a_low_attachment(api)
        )

        recovery = create_recovery(api, pool["id"], first["id"])
        assert_fields(
            recovery,
            {
                "status": "DRAFT",
                "submitted_by_user_id": None,
                "adjudicated_by_user_id": None,
                "denial_reason": None,
            },
        )
        assert read_pool(api, pool["id"])["stop_loss_recovery_cents"] == 0

    def test_the_recovery_points_at_one_pool_and_one_member_of_that_agreement(self, api):
        """PRD §2.7: "Every cross-reference in this system must stay inside a single `DelegationAgreement`."

        Design: Corner/endpoints/stop_loss_recovery_links_pool_and_enrollee_with_snapshot_fields
        """
        _agreement, _physician, pool, first, second = (
            _two_members_with_paid_claims_over_a_low_attachment(api)
        )

        recovery = create_recovery(api, pool["id"], first["id"])
        assert_fields(
            read_recovery(api, recovery["id"]),
            {"pool_id": pool["id"], "enrollee_id": first["id"]},
        )

        rows, meta = validate_paginated(
            api.list_recoveries(
                CLAIMS_EXAMINER_HEADERS,
                {
                    "pool_id": pool["id"],
                    "enrollee_id": first["id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == recovery["id"]
        assert rows[0]["enrollee_id"] != second["id"]


def _reserved_pool_whose_physician_holds_a_final_scorecard(api):
    built = build_single_member_funded_pool(
        api, base_pmpm_cents=20000, reconciliation_method="ROSTER_SNAPSHOT"
    )
    build_final_scorecard(
        api,
        built["physician"]["id"],
        measurement_period="2026",
        hedis_composite_bps=7000,
        access_score_bps=7000,
        patient_experience_bps=7000,
    )

    set_clock(api, "2027-01-01T00:00:00Z")
    close_incurral(api, built["pool"]["id"])
    reserved = reserve_pool(api, built["pool"]["id"])
    return built, reserved


class TestSettlementPreviewMatchesTheProposal:
    def test_the_preview_reports_the_pre_fee_tier_without_moving_the_pool(self, api):
        """PRD §3.7: "Before committing to a settlement, an `IpaAdmin` or the agreement's `PayerRepresentative` may ask for a settlement preview — a computed, read-only projection that re-runs the settlement waterfall against the pool's current ledger without changing any state, so that the pre-fee tier decision is observable before a proposal is made."

        Design: Corner/endpoints/settlement_preview_matches_the_proposal_it_predicts
        """
        built, reserved = _reserved_pool_whose_physician_holds_a_final_scorecard(api)
        assert_fields(
            reserved,
            {"funded_cents": 20000, "paid_claims_cents": 0, "ibnr_reserve_cents": 0},
        )

        preview = validate_success(
            api.get_settlement_preview(built["pool"]["id"], IPA_ADMIN_HEADERS), 200
        )
        assert_fields(preview, expected_settlement_waterfall(20000, 0, 0, 0))
        assert_fields(preview, {"surplus_tier": "TIER_3", "admin_fee_bps": 1000})

        unchanged = read_pool(api, built["pool"]["id"])
        assert_fields(
            unchanged,
            {
                "status": "RESERVED",
                "version": reserved["version"],
                "surplus_tier": None,
                "admin_fee_cents": 0,
                "shared_savings_pool_cents": 0,
            },
        )

    def test_the_proposal_persists_exactly_the_previewed_figures(self, api):
        """PRD §3.8: "Exactly two rounding steps occur, at step seven and step nine, and the ratio at step five is truncated."

        Design: Corner/endpoints/settlement_preview_matches_the_proposal_it_predicts
        """
        built, _reserved = _reserved_pool_whose_physician_holds_a_final_scorecard(api)
        preview = validate_success(
            api.get_settlement_preview(built["pool"]["id"], IPA_ADMIN_HEADERS), 200
        )

        proposed = propose_settlement(api, built["pool"]["id"])
        assert proposed["status"] == "SETTLEMENT_PROPOSED"
        # `surplus_ratio_bps` is a settlement-preview output field; PRD §3.7
        # does not declare it among the risk pool's own ledger fields, so it is
        # not compared against the persisted pool here.
        for field in (
            "raw_surplus_cents",
            "surplus_tier",
            "admin_fee_cents",
            "distributable_surplus_cents",
            "shared_savings_pool_cents",
        ):
            assert proposed[field] == preview[field], field
        assert proposed["shared_savings_pool_cents"] == 10800

    def test_the_previewed_shared_savings_pool_is_what_the_distribution_pays(self, api):
        """PRD §3.8: "`net_distribution_cents` is `withhold_release_cents` plus `shared_savings_cents`."

        Design: Corner/endpoints/settlement_preview_matches_the_proposal_it_predicts
        """
        built, _reserved = _reserved_pool_whose_physician_holds_a_final_scorecard(api)
        preview = validate_success(
            api.get_settlement_preview(built["pool"]["id"], IPA_ADMIN_HEADERS), 200
        )
        propose_settlement(api, built["pool"]["id"])

        distributions = list_pool_distributions(api, built["pool"]["id"])
        assert len(distributions) == 1
        assert_fields(
            distributions[0],
            {
                "physician_id": built["physician"]["id"],
                "status": "PROPOSED",
                "withhold_share_cents": 0,
                "withhold_release_cents": 0,
                "shared_savings_cents": preview["shared_savings_pool_cents"],
                "net_distribution_cents": preview["shared_savings_pool_cents"],
            },
        )


def _closed_panel_under_a_pool_driven_into_deficit(api):
    built = build_single_member_funded_pool(
        api, base_pmpm_cents=20000, reconciliation_method="ROSTER_SNAPSHOT"
    )
    _patch_panel(api, built["physician"]["id"], "CLOSED_TO_NEW")
    claim = build_paid_claim(
        api,
        built["agreement"]["id"],
        built["enrollee"]["id"],
        built["physician"]["id"],
        20000,
        service_date="2026-07-10T00:00:00Z",
    )
    return built, claim


class TestPanelReopenUnderReviewPosture:
    def test_paying_the_whole_funding_flags_the_pool_and_moves_the_posture(self, api):
        """PRD §3.6: "Fourth, because `loss_ratio_bps` changed, `deficit_flag` is re-evaluated as strictly greater than 9500 basis points, and when it becomes true the agreement's `capitation_posture` is re-derived to `UNDER_REVIEW` — which, per §2.9, closes every `OPEN` panel of that agreement."

        Design: Corner/endpoints/panel_reopen_under_review_posture_rejected_then_allowed_after_void
        """
        built, _claim = _closed_panel_under_a_pool_driven_into_deficit(api)

        assert_fields(
            read_pool(api, built["pool"]["id"]),
            {"paid_claims_cents": 20000, "loss_ratio_bps": 10000, "deficit_flag": True},
        )
        assert (
            read_agreement(api, built["agreement"]["id"])["capitation_posture"]
            == "UNDER_REVIEW"
        )

    def test_reopening_under_that_posture_is_refused_and_leaves_the_panel_closed(
        self, api
    ):
        """PRD §3.1: "The posture matters operationally because a panel may be reopened only while it reads `CURRENT`; an attempt while it reads `UNDER_REVIEW` or `WITHHELD` is refused with `ERR_CAPITATION_POSTURE_RESTRICTED`."

        Design: Corner/endpoints/panel_reopen_under_review_posture_rejected_then_allowed_after_void
        """
        built, _claim = _closed_panel_under_a_pool_driven_into_deficit(api)
        before = read_physician(api, built["physician"]["id"])

        validate_error(
            _patch_panel(api, built["physician"]["id"], "OPEN"),
            ERR_CAPITATION_POSTURE_RESTRICTED,
            409,
        )
        assert_fields(
            read_physician(api, built["physician"]["id"]),
            {"panel_status": "CLOSED_TO_NEW", "version": before["version"]},
        )

    def test_voiding_the_claim_clears_the_deficit_and_the_reopen_then_succeeds(
        self, api
    ):
        """PRD §3.6: "The pool's `loss_ratio_bps`, `deficit_flag` and `stop_loss_eligible_enrollee_count` are all recomputed, and the agreement's `capitation_posture` is re-derived."

        Design: Corner/endpoints/panel_reopen_under_review_posture_rejected_then_allowed_after_void
        """
        built, claim = _closed_panel_under_a_pool_driven_into_deficit(api)
        validate_error(
            _patch_panel(api, built["physician"]["id"], "OPEN"),
            ERR_CAPITATION_POSTURE_RESTRICTED,
            409,
        )

        validate_success(
            api.set_claim_state(
                claim["id"], state_payload("VOIDED"), CLAIMS_EXAMINER_HEADERS
            ),
            200,
        )
        assert_fields(
            read_pool(api, built["pool"]["id"]),
            {"paid_claims_cents": 0, "loss_ratio_bps": 0, "deficit_flag": False},
        )
        assert (
            read_agreement(api, built["agreement"]["id"])["capitation_posture"]
            == "CURRENT"
        )

        reopened = validate_success(
            _patch_panel(api, built["physician"]["id"], "OPEN"), 200
        )
        assert reopened["panel_status"] == "OPEN"
