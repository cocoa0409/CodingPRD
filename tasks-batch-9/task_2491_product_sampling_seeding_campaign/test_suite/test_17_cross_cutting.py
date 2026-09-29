"""Cross-cutting layers: version pinning on a parent row and a threshold probed from both sides."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers import (
    assert_rate,
    campaign_manager_headers,
    fulfillment_ops_headers,
    moderator_a_headers,
)
from test_helpers.api_errors import (
    ERR_STALE_CAMPAIGN_VERSION,
    ERR_STALE_ENROLLMENT_VERSION,
)
from test_helpers.fixtures import KitSpec


SINGLE_HERO_KIT = (KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),)
CLUSTER_ADDRESS = "H-CLUSTER"
OLD_ACCOUNT_OPENED_AT = "2025-06-01T00:00:00Z"
YOUNG_ACCOUNT_OPENED_AT = "2026-07-25T00:00:00Z"
SECOND_WAVE_START = "2026-08-03T00:00:00Z"
SECOND_WAVE_END = "2026-08-04T00:00:00Z"


class TestLiftAnalysisVersionPinning:
    """The full pin-reject-refresh-retry cycle against the campaign row."""

    def test_replaying_the_observed_campaign_version_is_refused_then_the_refreshed_one_works(
        self, api
    ):
        """PRD §2.5: "The optimistic-concurrency field in the request body equals the
        parent row's current `version` — otherwise `ERR_STALE_CAMPAIGN_VERSION` or
        `ERR_STALE_ENROLLMENT_VERSION` (412), as described in §2.8. Applies to
        lift-analysis creation and shipment allocation."

        PRD §2.8: "Creating a lift analysis through `POST /lift-analyses` requires
        `expected_campaign_version`, carrying the client's last observed `version`
        of the target `Campaign`. If that value does not equal the campaign's
        current `version`, the request is rejected with
        `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412)."

        PRD §3.9: "Each analysis is a dated snapshot rather than a mutable record,
        so a new one retires its predecessors: every existing analysis of the same
        campaign whose `superseded` is false has it set to true before the new row
        is stored with `superseded` false and `computed_at` stamped from the logical
        clock."

        PRD §3.9: "The request also increases the campaign's `version` by 1, which
        is what makes a second request carrying the same `expected_campaign_version`
        fail with `ERR_STALE_CAMPAIGN_VERSION`."

        PRD §3.9: "Under `ITT` — intent-to-treat — the treated group is every
        enrollment of the campaign whose `holdout_flag` is false and whose
        `screening_status` is `SCREEN_PASSED`, whether or not a sample ever reached
        them."

        PRD §3.9: "`power_status` is `INSUFFICIENT_POWER` when the holdout group is
        empty or the treated group holds fewer than 3 enrollments, and `MEASURED`
        otherwise; an underpowered analysis still reports all of its numbers, and
        the status is the caveat attached to them rather than a refusal to compute."

        PRD §3.9: "First, `diverted_unit_count` is taken as the campaign's
        `substantiated_diversion_count` and `effective_sample_count` as the
        campaign's `delivered_sample_count` less that diverted count — the samples
        that actually did their job."

        PRD §3.9: "Step two selects `penalty_rate_pct` **from that step-one figure
        and from nothing else**: 10 percent when the base cost per sample is below
        500 cents, 20 percent when it is below 1500 cents, and 35 percent at 1500
        cents or above."

        PRD §3.9: "Step four computes `adjusted_cost_per_sample_cents` as the
        campaign's `budget_committed_cents` plus `diversion_penalty_cents`, divided
        by `effective_sample_count` and rounded half-up to a whole cent, and zero
        when `effective_sample_count` is zero or negative."

        Design: Corner/cross_cutting_complexity_layers/occ_lift_analysis_rejects_stale_expected_campaign_version
        """
        world = fx.screening_open_campaign(
            api,
            kit_specs=SINGLE_HERO_KIT,
            name="OCC Lift",
            objective_type="AWARENESS",
        )
        panelist = fx.create_panelist(api, display_name="OC Two")
        enrollment = fx.create_enrollment(api, world.campaign_id, panelist["id"])
        enrollment = fx.screen_enrollment(api, enrollment["id"])
        assert enrollment["screening_status"] == "SCREEN_PASSED"
        assert enrollment["holdout_flag"] is False
        fx.activate_sampling(api, world.campaign_id)
        fx.open_review_window(api, world.campaign_id)

        observed_version = fx.get_campaign(api, world.campaign_id)["version"]

        first = validate_success(
            api.create_lift_analysis(
                campaign_manager_headers(),
                campaign_id=world.campaign_id,
                variant="ITT",
                expected_campaign_version=observed_version,
            ),
            201,
        )

        assert first["treated_count"] == 1
        assert first["holdout_count"] == 0
        assert_rate(first["treated_conversion_rate"], 0.0, "treated_conversion_rate")
        assert_rate(first["holdout_conversion_rate"], 0.0, "holdout_conversion_rate")
        assert_rate(first["lift_pct"], 0.0, "lift_pct")
        assert first["power_status"] == "INSUFFICIENT_POWER"
        assert first["effective_sample_count"] == 0
        assert first["base_cost_per_sample_cents"] == 0
        assert first["penalty_rate_pct"] == 10
        assert first["diversion_penalty_cents"] == 0
        assert first["adjusted_cost_per_sample_cents"] == 0

        validate_error(
            api.create_lift_analysis(
                campaign_manager_headers(),
                campaign_id=world.campaign_id,
                variant="ITT",
                expected_campaign_version=observed_version,
            ),
            ERR_STALE_CAMPAIGN_VERSION,
            412,
        )

        refreshed_version = fx.get_campaign(api, world.campaign_id)["version"]
        assert refreshed_version == observed_version + 1

        second = validate_success(
            api.create_lift_analysis(
                campaign_manager_headers(),
                campaign_id=world.campaign_id,
                variant="ITT",
                expected_campaign_version=refreshed_version,
            ),
            201,
        )
        assert second["id"] != first["id"]

        superseded = validate_success(
            api.get_lift_analysis(campaign_manager_headers(), first["id"])
        )
        assert superseded["superseded"] is True
        current = validate_success(
            api.get_lift_analysis(campaign_manager_headers(), second["id"])
        )
        assert current["superseded"] is False

        rows, meta = validate_paginated(
            api.list_lift_analyses(campaign_manager_headers(), campaign_id=world.campaign_id)
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}


class TestAllocationVersionPinning:
    """The same pin on a different parent, and what a rung-12 refusal leaves behind."""

    def test_the_pre_screen_enrollment_version_is_stale_and_writes_nothing(self, api):
        """PRD §2.8: "Allocating a sample shipment through `POST /sample-shipments`
        requires `expected_enrollment_version`, carrying the client's last observed
        `version` of the target `Enrollment`. If that value does not equal the
        enrollment's current `version`, the request is rejected with
        `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412)."

        PRD §2.5: "And because version pinning sits at rung 12, a stale write is
        reported as a stale version even when the business rules further down the
        ladder would also have refused it."

        PRD §3.4: "Every evaluated screen increases `screen_attempt_count` by 1,
        refreshes the panelist's `fraud_risk_score_screening` and
        `last_risk_scored_at`, snapshots that freshly computed score onto the
        enrollment as `fraud_score_at_screening`, and increases the enrollment's
        `version` by 1 — and it does all of this whether the outcome is a pass or a
        fail."

        PRD §3.6: "The shipment's `committed_cost_cents` is the campaign's current
        `kit_assembly_unit_cost_cents` plus the `freight_cents_per_kit` of the
        center that owns the shipment's wave."

        PRD §3.6: "The wave's `planned_unit_count` then grows by `kit_unit_total`
        and its `version` by 1; the campaign's `allocated_sample_count` grows by 1,
        its `cost_per_sample_provisional_cents` is refreshed and its `version` grows
        by 1; and the enrollment's `version` grows by 1, which is what makes a
        second allocation attempt with the same `expected_enrollment_version` fail
        as stale."

        PRD §3.6: "Every debited line moves that many units out of
        `units_available` and into `units_reserved` and has its `version` increased
        by 1."

        Design: Corner/cross_cutting_complexity_layers/occ_allocation_rejects_stale_expected_enrollment_version
        """
        world = fx.screening_open_campaign(
            api, kit_specs=SINGLE_HERO_KIT, name="OCC Allocate"
        )
        panelist = fx.create_panelist(api, display_name="OA One")
        enrollment = fx.create_enrollment(api, world.campaign_id, panelist["id"])
        pre_screen_version = enrollment["version"]
        screened = fx.screen_enrollment(api, enrollment["id"])
        post_screen_version = screened["version"]
        assert screened["screening_status"] == "SCREEN_PASSED"
        assert post_screen_version == pre_screen_version + 1

        fx.activate_sampling(api, world.campaign_id)
        center = fx.create_center(api, name="North Pick Center", zone_code="Z-NORTH")
        wave = fx.create_wave(api, center["id"])

        validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=enrollment["id"],
                fulfillment_wave_id=wave["id"],
                expected_enrollment_version=pre_screen_version,
            ),
            ERR_STALE_ENROLLMENT_VERSION,
            412,
        )

        line = fx.get_kit_line(api, world.kit_line_id(0))
        assert line["units_available"] == 10
        assert line["units_reserved"] == 0
        assert fx.get_wave(api, wave["id"])["planned_unit_count"] == 0
        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["allocated_sample_count"] == 0
        assert campaign["budget_committed_cents"] == 0

        shipment = validate_success(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=enrollment["id"],
                fulfillment_wave_id=wave["id"],
                expected_enrollment_version=post_screen_version,
            ),
            201,
        )
        assert shipment["status"] == "ALLOCATED"
        assert shipment["kit_unit_total"] == 1
        assert shipment["committed_cost_cents"] == 583

        line = fx.get_kit_line(api, world.kit_line_id(0))
        assert line["units_available"] == 9
        assert line["units_reserved"] == 1
        assert fx.get_wave(api, wave["id"])["planned_unit_count"] == 1
        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["allocated_sample_count"] == 1
        assert campaign["budget_committed_cents"] == 583
        assert campaign["cost_per_sample_provisional_cents"] == 583
        assert (
            fx.get_enrollment(api, enrollment["id"])["version"]
            == post_screen_version + 1
        )


class TestReshipAfterALoss:
    """The obligation axis walked backwards by an allocation that carries the pin."""

    def test_the_reship_names_the_lost_shipment_and_resets_the_obligation(self, api):
        """PRD §3.6: "The recovery path from a loss is a reship, and it is an
        ordinary allocation carrying `supersedes_shipment_id`. It returns the
        enrollment's obligation axis `FORFEITED → NONE`, which requires that the
        enrollment's `screening_status` is still `SCREEN_PASSED` and that the
        superseded shipment's own `status` is `LOST`; the obligation axis then loops
        forward again through `SAMPLE_SENT` when the new wave releases."

        PRD §3.6: "Reporting a loss moves the shipment `SHIPPED → LOST` and
        refreshes `cost_per_sample_final_cents`; it advances the enrollment's
        obligation axis `SAMPLE_SENT → FORFEITED` **only when no other shipment of
        that enrollment is still in `ALLOCATED`, `SHIPPED` or `DELIVERED`** — a
        panelist with a live parallel shipment still owes their review, so the
        obligation stays where it is."

        PRD §3.6: "Its population is every shipment of the campaign — that is,
        every shipment whose enrollment belongs to the campaign — whose `status` is
        `ALLOCATED`, `SHIPPED`, `DELIVERED` or `LOST`; `CANCELLED` shipments are
        excluded entirely."

        PRD §3.6: "A `LOST` shipment therefore stays in the numerator and leaves
        the denominator: its cost was really incurred but it delivered nothing."

        PRD §3.6: "Every shipment of the released wave still in `ALLOCATED` moves to
        `SHIPPED` with `shipped_at` stamped from the logical clock; each such
        shipment's mapped units move from `units_reserved` to `units_shipped` on
        every kit line named in its `reserved_line_units`, with each line's
        `version` increased by 1; the wave's `shipped_unit_count` takes on the units
        that just shipped while its `planned_unit_count` returns to zero; and each
        affected enrollment's obligation axis advances `NONE → SAMPLE_SENT`."

        Design: Corner/cross_cutting_complexity_layers/occ_reship_accepts_the_current_enrollment_version_after_a_lost_shipment
        """
        world = fx.sampling_active_campaign(
            api,
            panelist_count=1,
            kit_specs=SINGLE_HERO_KIT,
            center_overrides={"name": "North Pick Center", "zone_code": "Z-NORTH"},
            name="Reship OCC",
        )
        first_shipment = fx.allocate_shipment(
            api, world.enrollment_id(0), world.wave_id
        )
        fx.lock_wave(api, world.wave_id)
        fx.release_wave(api, world.wave_id)
        fx.report_shipment_lost(api, first_shipment["id"])

        second_wave = fx.create_wave(
            api,
            world.center_id,
            window_start=SECOND_WAVE_START,
            window_end=SECOND_WAVE_END,
        )
        before = fx.get_enrollment(api, world.enrollment_id(0))
        assert before["obligation_status"] == "FORFEITED"
        current_version = before["version"]

        reship = validate_success(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(0),
                fulfillment_wave_id=second_wave["id"],
                expected_enrollment_version=current_version,
                supersedes_shipment_id=first_shipment["id"],
            ),
            201,
        )

        assert reship["status"] == "ALLOCATED"
        assert reship["supersedes_shipment_id"] == first_shipment["id"]
        assert reship["committed_cost_cents"] == 583
        assert fx.get_shipment(api, first_shipment["id"])["status"] == "LOST"

        enrollment = fx.get_enrollment(api, world.enrollment_id(0))
        assert enrollment["obligation_status"] == "NONE"
        assert enrollment["screening_status"] == "SCREEN_PASSED"
        assert enrollment["version"] == current_version + 1

        line = fx.get_kit_line(api, world.kit_line_id(0))
        assert line["units_available"] == 8
        assert line["units_reserved"] == 1
        assert line["units_shipped"] == 1

        released = fx.get_wave(api, world.wave_id)
        assert released["status"] == "RELEASED"
        assert released["shipped_unit_count"] == 1
        assert released["planned_unit_count"] == 0

        planned = fx.get_wave(api, second_wave["id"])
        assert planned["status"] == "PLANNED"
        assert planned["planned_unit_count"] == 1

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["allocated_sample_count"] == 2
        assert campaign["budget_committed_cents"] == 1166
        assert campaign["cost_per_sample_provisional_cents"] == 583
        assert campaign["cost_per_sample_final_cents"] == 0


class TestScreeningThresholdFromBothSides:
    """One flagged referrer and one shared address, with only the account age moving."""

    def test_a_score_of_exactly_the_threshold_fails_while_a_lower_one_passes(self, api):
        """PRD §3.4: "the just-recomputed `fraud_risk_score_screening` is at least
        55.0 — reason `FRAUD_SCORE_TOO_HIGH`, the threshold being inclusive so that
        a score of exactly 55.0 fails;"

        PRD §3.4: "Past those gates the operation always succeeds as an HTTP 200 —
        **a failed screen is not an error response.** It is a 200 whose returned
        enrollment carries `screening_status` `SCREEN_FAILED` and a
        `screening_failure_reason`."

        PRD §3.3: "That collision count is capped at three, and the address term is
        18 points multiplied by the capped count and divided by three — that is, 6
        points for one collision, 12 for two, and the full 18 for three or more."

        PRD §3.3: "The system takes the difference between the logical clock's
        current instant and `account_opened_at`, converts it to whole days by
        discarding any partial day, and adds 22 points when that whole-day age is
        strictly below 30 days. An account that is exactly 30 days old or older
        contributes nothing."

        PRD §3.3: "When `referred_by_panelist_id` is set and the referring
        panelist's own `integrity_status` is `FLAGGED` or `BANNED`, 15 points are
        added. An organic signup, or a referral from a `CLEAR` panelist,
        contributes nothing."

        PRD §3.3: "The address term is multiplied by 1.5 before summation, and two
        additional terms join."

        PRD §3.3: "An on-demand or investigation-triggered `AUDIT` rescore also
        applies the flagging rule: when the resulting `fraud_risk_score_audit` is at
        least 55.0 and the panelist is currently `CLEAR`, their `integrity_status`
        becomes `FLAGGED`."

        Design: Corner/cross_cutting_complexity_layers/screening_score_at_the_inclusive_flag_threshold_fails_the_screen
        """
        world = fx.screening_open_campaign(
            api, kit_specs=SINGLE_HERO_KIT, name="Threshold Probe"
        )
        fx.address_cluster_panelists(
            api,
            3,
            address_hash=CLUSTER_ADDRESS,
            account_opened_at=OLD_ACCOUNT_OPENED_AT,
        )
        referrer = fx.create_panelist(
            api,
            display_name="Referrer R",
            address_hash=CLUSTER_ADDRESS,
            account_opened_at=YOUNG_ACCOUNT_OPENED_AT,
        )

        referrer_enrollment = fx.create_enrollment(
            api, world.campaign_id, referrer["id"]
        )
        referrer_enrollment = fx.screen_enrollment(api, referrer_enrollment["id"])
        assert referrer_enrollment["screening_status"] == "SCREEN_PASSED"

        fx.activate_sampling(api, world.campaign_id)
        center = fx.create_center(api, name="North Pick Center", zone_code="Z-NORTH")
        wave = fx.create_wave(api, center["id"])
        shipment = fx.allocate_shipment(api, referrer_enrollment["id"], wave["id"])
        case = fx.open_diversion_case(
            api,
            referrer["id"],
            shipment["id"],
            signal_type="ADDRESS_CLUSTER",
            evidence_note="Four accounts share one address hash.",
            headers=moderator_a_headers(),
        )
        fx.investigate_case(api, case["id"], headers=moderator_a_headers())

        flagged = fx.get_panelist(api, referrer["id"])
        assert flagged["integrity_status"] == "FLAGGED"
        assert_rate(flagged["fraud_risk_score_screening"], 40.0, "referrer screening")
        assert_rate(flagged["fraud_risk_score_audit"], 64.0, "referrer audit")

        at_threshold = fx.create_panelist(
            api,
            display_name="Probe P",
            address_hash=CLUSTER_ADDRESS,
            account_opened_at=YOUNG_ACCOUNT_OPENED_AT,
            referred_by_panelist_id=referrer["id"],
        )
        below_threshold = fx.create_panelist(
            api,
            display_name="Probe Q",
            address_hash=CLUSTER_ADDRESS,
            account_opened_at="2026-01-01T00:00:00Z",
            referred_by_panelist_id=referrer["id"],
        )
        failing_enrollment = fx.create_enrollment(
            api, world.campaign_id, at_threshold["id"]
        )
        passing_enrollment = fx.create_enrollment(
            api, world.campaign_id, below_threshold["id"]
        )

        failed = validate_success(
            api.screen_enrollment(campaign_manager_headers(), failing_enrollment["id"])
        )
        passed = validate_success(
            api.screen_enrollment(campaign_manager_headers(), passing_enrollment["id"])
        )

        assert failed["screening_status"] == "SCREEN_FAILED"
        assert failed["screening_failure_reason"] == "FRAUD_SCORE_TOO_HIGH"
        assert_rate(failed["fraud_score_at_screening"], 55.0, "score at screening")
        assert failed["screen_attempt_count"] == 1

        assert passed["screening_status"] == "SCREEN_PASSED"
        assert passed["screening_failure_reason"] is None
        assert_rate(passed["fraud_score_at_screening"], 33.0, "score at screening")
        assert passed["screen_attempt_count"] == 1

        probe = fx.get_panelist(api, at_threshold["id"])
        assert_rate(probe["fraud_risk_score_screening"], 55.0, "probe screening")
        assert probe["integrity_status"] == "CLEAR"
        peer = fx.get_panelist(api, below_threshold["id"])
        assert_rate(peer["fraud_risk_score_screening"], 33.0, "peer screening")
