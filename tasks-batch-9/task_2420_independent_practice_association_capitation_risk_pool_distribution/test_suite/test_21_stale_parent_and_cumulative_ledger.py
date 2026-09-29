"""Stale-parent guards on the two versioned creates, and the cumulative paid ledger."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLAIMS_EXAMINER_HEADERS,
    ERR_STALE_ENROLLEE_VERSION,
    ERR_STALE_PHYSICIAN_VERSION,
    ERR_STOP_LOSS_NOT_ATTACHED,
    IPA_ADMIN_HEADERS,
    NETWORK_MANAGER_HEADERS,
    assert_fields,
    assign_enrollee,
    assignment_payload,
    build_paid_claim,
    create_active_agreement,
    create_active_physician,
    create_enrollee,
    create_physician,
    create_pool,
    credential_physician,
    expected_recovery_figures,
    physician_version,
    read_agreement,
    read_assignment,
    read_enrollee,
    read_physician,
    read_pool,
    read_scorecard,
    recovery_payload,
    scorecard_payload,
    set_clock,
    state_payload,
)

_SUPERSEDE_INSTANT = "2026-08-01T00:00:00Z"


def _member_placed_on_the_first_panel(api):
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(api, max_panel_size=5)
    first = create_active_physician(api, agreement["id"], full_name="Ada Okafor")
    second = create_active_physician(api, agreement["id"], full_name="Bo Lindgren")
    enrollee = create_enrollee(api, agreement["id"], external_member_id="SV-0001")
    assert enrollee["version"] == 1

    original = assign_enrollee(
        api, enrollee["id"], first["id"], effective_date="2026-01-01T00:00:00Z"
    )
    set_clock(api, _SUPERSEDE_INSTANT)
    return agreement, first, second, enrollee, original


def _supersede_with_version(api, enrollee_id, physician_id, expected_version):
    return api.create_assignment(
        assignment_payload(
            enrollee_id,
            physician_id,
            expected_version,
            effective_date=_SUPERSEDE_INSTANT,
            supersede_prior=True,
        ),
        NETWORK_MANAGER_HEADERS,
    )


class TestStaleEnrolleeVersionBlocksTheSupersede:
    def test_the_first_placement_advances_the_enrollee_version(self, api):
        """PRD §3.4: "The parent enrollee's `version` advances by 1 because its `assigned_physician_id` moved."

        Design: Corner/cross_cutting_layers/stale_expected_enrollee_version_blocks_the_superseding_assignment
        """
        _agreement, first, _second, enrollee, original = (
            _member_placed_on_the_first_panel(api)
        )
        assert_fields(
            original,
            {
                "status": "ACTIVE",
                "physician_id": first["id"],
                "term_date": None,
                "superseded_by_assignment_id": None,
            },
        )
        assert_fields(
            read_enrollee(api, enrollee["id"]),
            {"assigned_physician_id": first["id"], "version": enrollee["version"] + 1},
        )

    def test_replaying_the_first_observed_version_is_rejected_as_stale(self, api):
        """PRD §2.8: "If that value does not equal the enrollee's current `version`, the create is rejected with `ERR_STALE_ENROLLEE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/stale_expected_enrollee_version_blocks_the_superseding_assignment
        """
        _agreement, _first, second, enrollee, _original = (
            _member_placed_on_the_first_panel(api)
        )

        validate_error(
            _supersede_with_version(api, enrollee["id"], second["id"], 1),
            ERR_STALE_ENROLLEE_VERSION,
            412,
        )

    def test_the_rejected_supersede_moves_nothing_at_all(self, api):
        """PRD §2.8: "The guard exists because an earlier create carrying `supersede_prior` set to true may already have re-pointed `assigned_physician_id` on that enrollee — behaviour the product intentionally permits — which means a writer working from an older read holds a stale picture of where the member currently sits on a panel."

        Design: Corner/cross_cutting_layers/stale_expected_enrollee_version_blocks_the_superseding_assignment
        """
        agreement, first, second, enrollee, original = (
            _member_placed_on_the_first_panel(api)
        )
        validate_error(
            _supersede_with_version(api, enrollee["id"], second["id"], 1),
            ERR_STALE_ENROLLEE_VERSION,
            412,
        )

        assert_fields(
            read_enrollee(api, enrollee["id"]),
            {"assigned_physician_id": first["id"], "version": 2},
        )
        assert_fields(
            read_assignment(api, original["id"]),
            {"status": "ACTIVE", "term_date": None},
        )
        assert read_physician(api, first["id"])["panel_size"] == 1
        assert read_physician(api, second["id"])["panel_size"] == 0
        assert read_agreement(api, agreement["id"])["total_assigned_members"] == 1

        rows, meta = validate_paginated(
            api.list_assignments(
                NETWORK_MANAGER_HEADERS,
                {"enrollee_id": enrollee["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == original["id"]

    def test_the_refreshed_version_supersedes_the_prior_row(self, api):
        """PRD §3.4: "When `supersede_prior` is supplied as true, the member's existing `ACTIVE` assignment is not treated as a conflict; instead the system moves that prior row `ACTIVE → TERMINATED` at the new assignment's `effective_date`, setting its `status` to `TERMINATED`, its `term_date` to that instant, its `superseded_by_assignment_id` to the identifier of the new row, recomputing the prior physician's `panel_size` downward by one, and advancing the prior row's `version` by 1."

        Design: Corner/cross_cutting_layers/stale_expected_enrollee_version_blocks_the_superseding_assignment
        """
        _agreement, _first, second, enrollee, original = (
            _member_placed_on_the_first_panel(api)
        )
        validate_error(
            _supersede_with_version(api, enrollee["id"], second["id"], 1),
            ERR_STALE_ENROLLEE_VERSION,
            412,
        )

        successor = validate_success(
            _supersede_with_version(api, enrollee["id"], second["id"], 2), 201
        )
        assert_fields(
            successor,
            {
                "status": "ACTIVE",
                "physician_id": second["id"],
                "effective_date": _SUPERSEDE_INSTANT,
            },
        )
        assert_fields(
            read_assignment(api, original["id"]),
            {
                "status": "TERMINATED",
                "term_date": _SUPERSEDE_INSTANT,
                "superseded_by_assignment_id": successor["id"],
            },
        )

    def test_the_derived_counters_follow_the_single_live_assignment(self, api):
        """PRD §2.9: "`Enrollee.assigned_physician_id` is the `physician_id` of that enrollee's single `ACTIVE` assignment, and is null when the enrollee has none."

        Design: Corner/cross_cutting_layers/stale_expected_enrollee_version_blocks_the_superseding_assignment
        """
        agreement, first, second, enrollee, _original = (
            _member_placed_on_the_first_panel(api)
        )
        validate_success(
            _supersede_with_version(api, enrollee["id"], second["id"], 2), 201
        )

        assert_fields(
            read_enrollee(api, enrollee["id"]),
            {"assigned_physician_id": second["id"], "version": 3},
        )
        assert read_physician(api, first["id"])["panel_size"] == 0
        assert read_physician(api, second["id"])["panel_size"] == 1
        assert read_agreement(api, agreement["id"])["total_assigned_members"] == 1


def _physician_with_one_draft_scorecard(api):
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(api, max_panel_size=5)
    created = create_physician(api, agreement["id"])
    credential_physician(api, created["id"])
    activated = validate_success(
        api.set_physician_state(
            created["id"], state_payload("ACTIVE"), NETWORK_MANAGER_HEADERS
        ),
        200,
    )

    scorecard = validate_success(
        api.create_scorecard(
            scorecard_payload(
                created["id"], activated["version"], measurement_period="2026"
            ),
            IPA_ADMIN_HEADERS,
        ),
        201,
    )
    return agreement, created, activated, scorecard


class TestStalePhysicianVersionBlocksTheSupersedingScorecard:
    def test_each_credential_move_advances_the_physician_version(self, api):
        """PRD §3.2: "Both moves set the new `credential_status` and advance the physician's `version` by 1."

        Design: Corner/cross_cutting_layers/stale_expected_physician_version_blocks_the_superseding_scorecard
        """
        _agreement, created, activated, _scorecard = _physician_with_one_draft_scorecard(
            api
        )
        assert created["version"] == 1
        assert_fields(activated, {"credential_status": "ACTIVE", "version": 3})

    def test_the_first_scorecard_opens_in_draft_with_zeroed_outputs(self, api):
        """PRD §3.8: "A new scorecard begins in `status` `DRAFT` with `composite_score_bps` 0 and `withhold_release_bps` 0."

        Design: Corner/cross_cutting_layers/stale_expected_physician_version_blocks_the_superseding_scorecard
        """
        _agreement, created, _activated, scorecard = _physician_with_one_draft_scorecard(
            api
        )
        assert_fields(
            scorecard,
            {
                "physician_id": created["id"],
                "measurement_period": "2026",
                "status": "DRAFT",
                "composite_score_bps": 0,
                "withhold_release_bps": 0,
                "version": 1,
            },
        )

    def test_creating_it_repoints_the_physician_and_advances_its_version(self, api):
        """PRD §3.8: "Creating it has two side effects on its surroundings: any earlier scorecard for the same physician and the same `measurement_period` that is still in `DRAFT` moves to `SUPERSEDED`, advancing that scorecard's `version` by 1; and the physician's `latest_scorecard_period` is updated to the new `measurement_period`, advancing the physician's `version` by 1."

        Design: Corner/cross_cutting_layers/stale_expected_physician_version_blocks_the_superseding_scorecard
        """
        _agreement, created, activated, _scorecard = _physician_with_one_draft_scorecard(
            api
        )
        assert_fields(
            read_physician(api, created["id"]),
            {"latest_scorecard_period": "2026", "version": activated["version"] + 1},
        )

    def test_replaying_the_pre_scorecard_version_is_rejected_as_stale(self, api):
        """PRD §2.8: "If that value does not equal the physician's current `version`, the create is rejected with `ERR_STALE_PHYSICIAN_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/stale_expected_physician_version_blocks_the_superseding_scorecard
        """
        _agreement, created, activated, scorecard = _physician_with_one_draft_scorecard(
            api
        )

        validate_error(
            api.create_scorecard(
                scorecard_payload(
                    created["id"], activated["version"], measurement_period="2026"
                ),
                IPA_ADMIN_HEADERS,
            ),
            ERR_STALE_PHYSICIAN_VERSION,
            412,
        )
        assert read_scorecard(api, scorecard["id"])["status"] == "DRAFT"
        assert read_physician(api, created["id"])["version"] == activated["version"] + 1

    def test_the_refreshed_version_supersedes_the_earlier_draft(self, api):
        """PRD §2.8: "Here too the guard is a stale-version check rather than a uniqueness conflict: a newer scorecard for the same physician and the same `measurement_period` legitimately supersedes the prior one, so without the check a writer working from an outdated read would silently supersede a scorecard it never saw."

        Design: Corner/cross_cutting_layers/stale_expected_physician_version_blocks_the_superseding_scorecard
        """
        _agreement, created, _activated, scorecard = _physician_with_one_draft_scorecard(
            api
        )
        fresh = physician_version(api, created["id"])

        successor = validate_success(
            api.create_scorecard(
                scorecard_payload(created["id"], fresh, measurement_period="2026"),
                IPA_ADMIN_HEADERS,
            ),
            201,
        )
        assert_fields(successor, {"status": "DRAFT", "measurement_period": "2026"})

        superseded = read_scorecard(api, scorecard["id"])
        assert_fields(
            superseded,
            {"status": "SUPERSEDED", "version": scorecard["version"] + 1},
        )
        assert read_physician(api, created["id"])["version"] == fresh + 1


def _pool_with_one_paid_claim_below_the_attachment(api):
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        stop_loss_attachment_cents=10000,
        reinsurance_recovery_bps=9000,
        professional_pool_share_bps=10000,
        institutional_pool_share_bps=0,
        quality_withhold_bps=0,
        max_panel_size=5,
    )
    physician = create_active_physician(api, agreement["id"])
    pool = create_pool(api, agreement["id"], pool_type="PROFESSIONAL")
    enrollee = create_enrollee(api, agreement["id"], external_member_id="CU-0001")
    assign_enrollee(api, enrollee["id"], physician["id"])

    first_claim = build_paid_claim(
        api,
        agreement["id"],
        enrollee["id"],
        physician["id"],
        6000,
        service_date="2026-04-10T00:00:00Z",
    )
    return agreement, physician, pool, enrollee, first_claim


def _pay_a_second_claim(api, agreement_id, enrollee_id, physician_id):
    return build_paid_claim(
        api,
        agreement_id,
        enrollee_id,
        physician_id,
        5000,
        service_date="2026-04-20T00:00:00Z",
    )


def _open_recovery(api, pool_id, enrollee_id):
    return api.create_recovery(
        recovery_payload(pool_id, enrollee_id), CLAIMS_EXAMINER_HEADERS
    )


class TestAttachmentIsCumulativeAcrossClaims:
    def test_the_first_payment_accumulates_without_piercing_the_attachment(self, api):
        """PRD §3.6: "Third, because the pool's paid ledger moved, the enrollee's `cumulative_paid_claims_cents` increases by the same amount, and when that enrollee's paid total within this pool comes to strictly exceed the agreement's `stop_loss_attachment_cents` for the first time, the pool's `stop_loss_eligible_enrollee_count` increases by 1."

        Design: Corner/cross_cutting_layers/stop_loss_attachment_is_cumulative_across_claims_and_resets_on_void
        """
        _agreement, _physician, pool, enrollee, _claim = (
            _pool_with_one_paid_claim_below_the_attachment(api)
        )

        assert read_enrollee(api, enrollee["id"])["cumulative_paid_claims_cents"] == 6000
        assert_fields(
            read_pool(api, pool["id"]),
            {"paid_claims_cents": 6000, "stop_loss_eligible_enrollee_count": 0},
        )

    def test_a_recovery_below_the_attachment_point_is_refused(self, api):
        """PRD §2.10: "A recovery may be created only when the enrollee's paid-claim total in the pool strictly exceeds the agreement's `stop_loss_attachment_cents`; exactly at the attachment point the excess is zero and the create is refused."

        Design: Corner/cross_cutting_layers/stop_loss_attachment_is_cumulative_across_claims_and_resets_on_void
        """
        _agreement, _physician, pool, enrollee, _claim = (
            _pool_with_one_paid_claim_below_the_attachment(api)
        )

        validate_error(
            _open_recovery(api, pool["id"], enrollee["id"]),
            ERR_STOP_LOSS_NOT_ATTACHED,
            422,
        )

    def test_the_second_payment_carries_the_member_past_the_attachment(self, api):
        """PRD §3.7: "`recovery_cents` is `excess_cents` multiplied by the agreement's `reinsurance_recovery_bps` as a proportion of 10000, rounded half up to whole cents in a single rounding step."

        Design: Corner/cross_cutting_layers/stop_loss_attachment_is_cumulative_across_claims_and_resets_on_void
        """
        agreement, physician, pool, enrollee, _claim = (
            _pool_with_one_paid_claim_below_the_attachment(api)
        )
        _pay_a_second_claim(api, agreement["id"], enrollee["id"], physician["id"])

        assert (
            read_enrollee(api, enrollee["id"])["cumulative_paid_claims_cents"] == 11000
        )
        assert_fields(
            read_pool(api, pool["id"]),
            {"paid_claims_cents": 11000, "stop_loss_eligible_enrollee_count": 1},
        )

        recovery = validate_success(_open_recovery(api, pool["id"], enrollee["id"]), 201)
        assert_fields(recovery, expected_recovery_figures(11000, 10000, 9000))
        assert recovery["recovery_cents"] == 900

    def test_voiding_the_second_claim_removes_exactly_what_it_added(self, api):
        """PRD §3.6: "The void removes exactly what the payment added: the pool's `paid_claims_cents` decreases by `paid_cents`, the enrollee's `cumulative_paid_claims_cents` decreases by `paid_cents`, and only then is `paid_cents` itself cleared to null."

        Design: Corner/cross_cutting_layers/stop_loss_attachment_is_cumulative_across_claims_and_resets_on_void
        """
        agreement, physician, pool, enrollee, _claim = (
            _pool_with_one_paid_claim_below_the_attachment(api)
        )
        second = _pay_a_second_claim(
            api, agreement["id"], enrollee["id"], physician["id"]
        )
        validate_success(_open_recovery(api, pool["id"], enrollee["id"]), 201)

        voided = validate_success(
            api.set_claim_state(
                second["id"], state_payload("VOIDED"), CLAIMS_EXAMINER_HEADERS
            ),
            200,
        )
        assert_fields(voided, {"status": "VOIDED", "paid_cents": None})
        assert read_enrollee(api, enrollee["id"])["cumulative_paid_claims_cents"] == 6000
        assert_fields(
            read_pool(api, pool["id"]),
            {"paid_claims_cents": 6000, "stop_loss_eligible_enrollee_count": 0},
        )

    def test_after_the_void_a_new_recovery_is_refused_while_the_filed_one_keeps_its_snapshot(
        self, api
    ):
        """PRD §3.7: "`excess_cents` is `eligible_paid_cents` less `attachment_cents`, floored at zero."

        Design: Corner/cross_cutting_layers/stop_loss_attachment_is_cumulative_across_claims_and_resets_on_void
        """
        agreement, physician, pool, enrollee, _claim = (
            _pool_with_one_paid_claim_below_the_attachment(api)
        )
        second = _pay_a_second_claim(
            api, agreement["id"], enrollee["id"], physician["id"]
        )
        filed = validate_success(_open_recovery(api, pool["id"], enrollee["id"]), 201)
        validate_success(
            api.set_claim_state(
                second["id"], state_payload("VOIDED"), CLAIMS_EXAMINER_HEADERS
            ),
            200,
        )

        validate_error(
            _open_recovery(api, pool["id"], enrollee["id"]),
            ERR_STOP_LOSS_NOT_ATTACHED,
            422,
        )
        assert_fields(
            validate_success(
                api.get_recovery(filed["id"], CLAIMS_EXAMINER_HEADERS), 200
            ),
            {
                "attachment_cents": 10000,
                "eligible_paid_cents": 11000,
                "excess_cents": 1000,
                "recovery_cents": 900,
            },
        )
