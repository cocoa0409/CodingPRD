"""License lifecycle (activate / extend / terminate / expire), delivery-batch
spec cycle, takedown-notice scheduling, and the logical clock."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_slot,
    advance_clock,
    assert_delivery_batch,
    assert_same_instant,
    create_and_deliver_batch,
    create_delivery_batch_payload,
    create_direct_license,
    get_license,
    get_success_data,
    list_notices_for_license,
    resubmit_delivery_batch_payload,
    setup_catalog,
    validate_error,
    validate_success,
)

RM = TEST_USERS["rights_manager_headers"]


def _license_with_default_window(workspace, slot, **kwargs):
    """EXECUTED FLAT_FEE 10000 license on [2026-08-01, 2027-01-01)."""
    defaults = dict(
        license_start="2026-08-01T00:00:00Z",
        license_end="2027-01-01T00:00:00Z",
        flat_fee_cents=10000,
    )
    defaults.update(kwargs)
    return create_direct_license(slot["id"], workspace["platform"]["id"], **defaults)


class TestActivationGates:
    def test_rejected_batch_does_not_permit_activation(self, api):
        """PRD §3.6: "And there must exist a `DeliveryBatch` for this license with `delivery_status` `DELIVERED`, otherwise `ERR_DELIVERY_INCOMPLETE` (422)."
        PRD §3.7: "On a failure — one or more required profiles absent, or a metadata spec mismatch — the batch moves to `REJECTED`, `missing_profiles` lists exactly the required profiles absent from the manifest, `attempt_count` increments by one, and `submitted_at` is stamped."

        Design: Difficulty/cross_entity_state_dependency/license_activation_requires_delivered_batch
        """
        workspace = setup_catalog(required_asset_profiles=["4K_HDR"])
        slot = add_slot(workspace)
        license_agreement = _license_with_default_window(workspace, slot)
        batch = get_success_data(api.create_delivery_batch(
            create_delivery_batch_payload(
                license_agreement["id"], asset_manifest=["HD_ONLY"],
            ),
            RM,
        ))
        rejected = validate_success(api.submit_delivery_batch(batch["id"], RM), 200)
        assert rejected["delivery_status"] == "REJECTED"

        resp = api.activate_license(license_agreement["id"], RM)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_INCOMPLETE, 422)

    def test_activation_succeeds_once_batch_delivered(self, api):
        """PRD §3.6: "A `RightsManager` activates an `EXECUTED` license once two preconditions hold, and the license must be `EXECUTED` at all, otherwise `ERR_LICENSE_NOT_EXECUTABLE` (409). The logical clock must have reached `license_start`, otherwise `ERR_LICENSE_NOT_STARTED` (422). And there must exist a `DeliveryBatch` for this license with `delivery_status` `DELIVERED`, otherwise `ERR_DELIVERY_INCOMPLETE` (422). Activation moves the license to `ACTIVE` and stamps `activated_at` with the logical clock."

        Design: Difficulty/cross_entity_state_dependency/license_activation_requires_delivered_batch
        """
        workspace = setup_catalog(required_asset_profiles=["4K_HDR"])
        slot = add_slot(workspace)
        license_agreement = _license_with_default_window(workspace, slot)
        batch = get_success_data(api.create_delivery_batch(
            create_delivery_batch_payload(
                license_agreement["id"], asset_manifest=["HD_ONLY"],
            ),
            RM,
        ))
        get_success_data(api.submit_delivery_batch(batch["id"], RM))
        get_success_data(api.resubmit_delivery_batch(
            batch["id"],
            resubmit_delivery_batch_payload(["4K_HDR"], "MEC-2.3"),
            RM,
        ))
        delivered = validate_success(api.submit_delivery_batch(batch["id"], RM), 200)
        assert delivered["delivery_status"] == "DELIVERED"

        activated = validate_success(api.activate_license(license_agreement["id"], RM), 200)
        assert activated["license_status"] == "ACTIVE"
        assert_same_instant(
            activated["activated_at"], "2026-08-01T00:00:00Z", "activated_at"
        )

    def test_activate_before_window_start_returns_422(self, api):
        """PRD §3.6: "The logical clock must have reached `license_start`, otherwise `ERR_LICENSE_NOT_STARTED` (422)."

        Design: Corner/validations/activate_before_window_start_returns_422
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        license_agreement = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-10-01T00:00:00Z",
            license_end="2027-01-01T00:00:00Z",
            flat_fee_cents=10000,
        )
        create_and_deliver_batch(license_agreement["id"], workspace["platform"])

        resp = api.activate_license(license_agreement["id"], RM)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_STARTED, 422)

    def test_license_activate_twice_returns_409(self, api):
        """PRD §3.6: "A `RightsManager` activates an `EXECUTED` license once two preconditions hold, and the license must be `EXECUTED` at all, otherwise `ERR_LICENSE_NOT_EXECUTABLE` (409)."

        Design: Corner/state_machines/license_activate_twice_returns_409
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        license_agreement = _license_with_default_window(workspace, slot)
        create_and_deliver_batch(license_agreement["id"], workspace["platform"])

        activated = validate_success(api.activate_license(license_agreement["id"], RM), 200)
        assert activated["license_status"] == "ACTIVE"

        resp = api.activate_license(license_agreement["id"], RM)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_EXECUTABLE, 409)


class TestDeliveryBatchCycle:
    def test_batch_reject_resubmit_deliver_status_cycle(self, api):
        """PRD §3.7: "The intended cycle is `QUEUED` to `REJECTED` to `QUEUED` and then, on a successful submit, to `DELIVERED`; there is deliberately no direct `REJECTED`-to-`DELIVERED` shortcut."
        PRD §3.7: "The batch begins in `QUEUED` with `attempt_count` 0 and both `submitted_at` and `delivered_at` null."

        Design: Difficulty/non_linear_state_machine/delivery_batch_reject_resubmit_cycle
        """
        workspace = setup_catalog(required_asset_profiles=["4K_HDR", "CC_EN"])
        slot = add_slot(workspace)
        license_agreement = _license_with_default_window(workspace, slot)
        batch = get_success_data(api.create_delivery_batch(
            create_delivery_batch_payload(
                license_agreement["id"], asset_manifest=["4K_HDR"],
            ),
            RM,
        ))
        assert_delivery_batch(batch)
        assert batch["delivery_status"] == "QUEUED"
        assert batch["attempt_count"] == 0

        rejected = validate_success(api.submit_delivery_batch(batch["id"], RM), 200)
        assert rejected["delivery_status"] == "REJECTED"

        requeued = validate_success(api.resubmit_delivery_batch(
            batch["id"],
            resubmit_delivery_batch_payload(["4K_HDR", "CC_EN"], "MEC-2.3"),
            RM,
        ), 200)
        assert requeued["delivery_status"] == "QUEUED", (
            "resubmit returns the batch to QUEUED; the cycle edge is not terminal"
        )

        delivered = validate_success(api.submit_delivery_batch(batch["id"], RM), 200)
        assert delivered["delivery_status"] == "DELIVERED"

    def test_missing_profiles_and_attempt_count_across_cycle(self, api):
        """PRD §3.7: "On a failure — one or more required profiles absent, or a metadata spec mismatch — the batch moves to `REJECTED`, `missing_profiles` lists exactly the required profiles absent from the manifest, `attempt_count` increments by one, and `submitted_at` is stamped."
        PRD §3.7: "Resubmission — allowed only from `REJECTED`, with `DELIVERED` terminal and any other state rejected with `ERR_BATCH_INVALID_STATE` — replaces `asset_manifest` and `metadata_spec_version` with the request values, resets `missing_profiles` to empty, and returns the batch to `QUEUED`."

        Design: Difficulty/non_linear_state_machine/delivery_batch_reject_resubmit_cycle
        """
        workspace = setup_catalog(required_asset_profiles=["4K_HDR", "CC_EN"])
        slot = add_slot(workspace)
        license_agreement = _license_with_default_window(workspace, slot)
        batch = get_success_data(api.create_delivery_batch(
            create_delivery_batch_payload(
                license_agreement["id"], asset_manifest=["4K_HDR"],
            ),
            RM,
        ))

        rejected = validate_success(api.submit_delivery_batch(batch["id"], RM), 200)
        assert rejected["missing_profiles"] == ["CC_EN"], (
            "missing_profiles lists exactly the required profiles absent from the manifest"
        )
        assert rejected["attempt_count"] == 1

        get_success_data(api.resubmit_delivery_batch(
            batch["id"],
            resubmit_delivery_batch_payload(["4K_HDR", "CC_EN"], "MEC-2.3"),
            RM,
        ))
        delivered = validate_success(api.submit_delivery_batch(batch["id"], RM), 200)
        assert delivered["attempt_count"] == 2, (
            "attempt_count accumulates across the reject/resubmit loop"
        )
        assert delivered["missing_profiles"] == []

    def test_batch_submit_after_delivered_returns_409(self, api):
        """PRD §3.7: "Only a `QUEUED` batch may be submitted; attempting to submit a batch in any other state is rejected with `ERR_BATCH_INVALID_STATE` (409)."

        Design: Corner/state_machines/batch_submit_after_delivered_returns_409
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        license_agreement = _license_with_default_window(workspace, slot)
        batch = create_and_deliver_batch(license_agreement["id"], workspace["platform"])
        assert batch["delivery_status"] == "DELIVERED"

        resp = api.submit_delivery_batch(batch["id"], RM)
        validate_error(resp, ApiErrorId.ERR_BATCH_INVALID_STATE, 409)

    def test_batch_resubmit_from_queued_returns_409(self, api):
        """PRD §3.7: "Resubmission — allowed only from `REJECTED`, with `DELIVERED` terminal and any other state rejected with `ERR_BATCH_INVALID_STATE` — replaces `asset_manifest` and `metadata_spec_version` with the request values, resets `missing_profiles` to empty, and returns the batch to `QUEUED`."

        Design: Corner/state_machines/batch_resubmit_from_queued_returns_409
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        license_agreement = _license_with_default_window(workspace, slot)
        batch = get_success_data(api.create_delivery_batch(
            create_delivery_batch_payload(license_agreement["id"]),
            RM,
        ))
        assert batch["delivery_status"] == "QUEUED"

        resp = api.resubmit_delivery_batch(
            batch["id"],
            resubmit_delivery_batch_payload(["4K_HDR", "CC_EN"], "MEC-2.3"),
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_BATCH_INVALID_STATE, 409)
        current = get_success_data(api.get_delivery_batch(batch["id"], RM))
        assert current["delivery_status"] == "QUEUED"


class TestTerminationAndExpiry:
    def test_daily_proration_credit(self, api):
        """PRD §3.6: "Under `DAILY_PRORATION`, the credit is the credit basis multiplied by the ratio of remaining seconds to total seconds — where remaining seconds is the greater of zero and `license_end` minus the termination instant, and total seconds is the greater of one and `license_end` minus `license_start` — rounded half up to integer cents."
        PRD §3.6: "The credit basis is `allocated_fee_cents` — the post-discount fee, which is 0 for `REVENUE_SHARE` licenses."

        Design: Difficulty/dual_variant_calc/termination_credit_proration_divergence
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        license_agreement = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2026-10-30T00:00:00Z",
            flat_fee_cents=900000, proration_mode="DAILY_PRORATION",
        )
        advance_clock("2026-09-20T00:00:00Z")

        terminated = validate_success(api.terminate_license(license_agreement["id"], RM), 200)
        assert terminated["license_status"] == "TERMINATED"
        # 40 remaining days of a 90-day window: round(900000 * 40/90).
        assert terminated["termination_credit_cents"] == 400000

    def test_monthly_proration_credit(self, api):
        """PRD §3.6: "Under `MONTHLY_PRORATION`, the credit is the credit basis multiplied by the ratio of whole remaining 30-day blocks to the total number of 30-day blocks rounded up — that is, remaining days floored to blocks of 30 divided by total days ceiled to blocks of 30 — rounded half up to integer cents, and the credit is 0 whenever the remaining days contain no whole 30-day block."

        Design: Difficulty/dual_variant_calc/termination_credit_proration_divergence
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        license_agreement = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2026-10-30T00:00:00Z",
            flat_fee_cents=900000, proration_mode="MONTHLY_PRORATION",
        )
        advance_clock("2026-09-20T00:00:00Z")

        terminated = validate_success(api.terminate_license(license_agreement["id"], RM), 200)
        assert terminated["license_status"] == "TERMINATED"
        # 40 remaining days hold 1 whole 30-day block; ceil(90/30) = 3 blocks total.
        assert terminated["termination_credit_cents"] == 300000

    def test_license_terminate_from_expired_returns_409(self, api):
        """PRD §2.5: "The expiry rule is uniform: a resource expires when the logical clock is greater than or equal to its end instant — intervals are half-open, so at exactly the end instant the resource is expired."
        PRD §3.6: "Termination is permitted from `EXECUTED` or `ACTIVE`; attempting it on an `EXPIRED` or `TERMINATED` license is rejected with `ERR_LICENSE_ALREADY_TERMINAL` (409)."

        Design: Corner/state_machines/license_terminate_from_expired_returns_409
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        license_agreement = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2026-09-01T00:00:00Z",
            flat_fee_cents=10000,
        )

        sweep = advance_clock("2026-09-01T00:00:00Z")
        assert sweep["licenses_expired"] == 1, (
            "at exactly license_end the half-open expiry rule expires the license"
        )

        resp = api.terminate_license(license_agreement["id"], RM)
        validate_error(resp, ApiErrorId.ERR_LICENSE_ALREADY_TERMINAL, 409)

    def test_sweep_expires_license_and_executes_notice(self, api):
        """PRD §2.5: "Every `LicenseAgreement` in `EXECUTED` or `ACTIVE` whose `license_end` is at or before the new clock value moves to `EXPIRED`; each such license's `SCHEDULED` notice moves to `EXECUTED`; and each expired exclusive license triggers slot-encumbrance re-evaluation followed by the line-unblock cascade on offered packages."
        PRD §2.5: "The clock-advance response reports the new clock value as `current_utc` alongside sweep tallies: `slots_expired`, `licenses_expired`, `licenses_terminated`, `packages_expired`, and `notices_executed`."
        PRD §3.10: "When a license expires under the sweep or is terminated early, its `SCHEDULED` notice moves to `EXECUTED` with `executed_at` set to the logical clock."

        Design: Corner/calculations/sweep_expires_license_and_executes_notice
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        license_agreement = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2026-09-15T00:00:00Z",
            flat_fee_cents=10000,
        )

        sweep = advance_clock("2026-10-01T00:00:00Z")
        assert_same_instant(sweep["current_utc"], "2026-10-01T00:00:00Z", "current_utc")
        assert sweep["licenses_expired"] == 1
        assert sweep["notices_executed"] == 1
        assert sweep["slots_expired"] == 0
        assert sweep["licenses_terminated"] == 0
        assert sweep["packages_expired"] == 0

        assert get_license(license_agreement["id"])["license_status"] == "EXPIRED"
        notices = list_notices_for_license(license_agreement["id"])
        assert len(notices) == 1
        assert notices[0]["notice_status"] == "EXECUTED"
        assert_same_instant(
            notices[0]["scheduled_for"], "2026-09-15T00:00:00Z",
            "notice scheduled_for",
        )
        assert_same_instant(
            notices[0]["executed_at"], "2026-10-01T00:00:00Z", "notice executed_at"
        )


class TestExtension:
    def test_extend_with_stale_version_returns_412(self, api):
        """PRD §2.7: "Both requests must carry `expected_license_version`, a non-optional field equal to the license's current `version` as last observed by the client. If the value does not match the license's current `version` — because another booked report or a prior extension has advanced the version since the client last read the license — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/extend_with_stale_version_returns_412
        """
        workspace = setup_catalog()
        slot = add_slot(workspace, sellable_to="2027-12-01T00:00:00Z")
        license_agreement = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2026-12-01T00:00:00Z",
            flat_fee_cents=10000,
        )
        stale_version = license_agreement["version"]

        extended = validate_success(
            api.extend_license(
                license_agreement["id"], "2027-06-01T00:00:00Z", stale_version, RM,
            ),
            200,
        )
        assert_same_instant(
            extended["license_end"], "2027-06-01T00:00:00Z", "license_end"
        )

        resp = api.extend_license(
            license_agreement["id"], "2027-09-01T00:00:00Z", stale_version, RM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        assert_same_instant(
            get_license(license_agreement["id"])["license_end"],
            "2027-06-01T00:00:00Z",
            "license_end after stale extend",
        )

    def test_extend_cancels_and_replaces_takedown_notice(self, api):
        """PRD §3.6: "On success `license_end` is replaced, `holdback_until` is recomputed, the license's `SCHEDULED` takedown notice moves to `CANCELLED`, and a replacement notice is created `SCHEDULED` at the new end."
        PRD §3.10: "When a license is extended, its `SCHEDULED` notice moves to `CANCELLED` and a replacement notice is created `SCHEDULED` at the new end."

        Design: Corner/cross_cutting_layers/extend_cancels_and_replaces_takedown_notice
        """
        workspace = setup_catalog()
        slot = add_slot(workspace, sellable_to="2027-12-01T00:00:00Z")
        license_agreement = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2026-12-01T00:00:00Z",
            flat_fee_cents=10000,
        )

        get_success_data(api.extend_license(
            license_agreement["id"], "2027-06-01T00:00:00Z",
            license_agreement["version"], RM,
        ))

        notices = list_notices_for_license(license_agreement["id"])
        assert len(notices) == 2, (
            "after extension the license keeps one cancelled and one replacement notice"
        )
        cancelled = [n for n in notices if n["notice_status"] == "CANCELLED"]
        scheduled = [n for n in notices if n["notice_status"] == "SCHEDULED"]
        assert len(cancelled) == 1 and len(scheduled) == 1
        assert_same_instant(
            cancelled[0]["scheduled_for"], "2026-12-01T00:00:00Z",
            "cancelled notice scheduled_for",
        )
        assert_same_instant(
            scheduled[0]["scheduled_for"], "2027-06-01T00:00:00Z",
            "replacement notice scheduled_for",
        )

    def test_license_extend_from_terminated_returns_409(self, api):
        """PRD §3.6: "A `RightsManager` may extend a license only while it is `EXECUTED` or `ACTIVE`, otherwise `ERR_LICENSE_NOT_EXTENDABLE` (409)."

        Design: Corner/state_machines/license_extend_from_terminated_returns_409
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        license_agreement = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2026-12-01T00:00:00Z",
            flat_fee_cents=10000,
        )
        terminated = validate_success(api.terminate_license(license_agreement["id"], RM), 200)

        resp = api.extend_license(
            license_agreement["id"], "2027-06-01T00:00:00Z",
            terminated["version"], RM,
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_EXTENDABLE, 409)

    def test_license_mutation_increments_version(self, api):
        """PRD §2.4: "`version` is an integer that increments by exactly one on every mutation of the resource, including mutations caused by cascading side effects."

        Design: Corner/cross_cutting_layers/license_mutation_increments_version
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        license_agreement = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2026-12-01T00:00:00Z",
            flat_fee_cents=10000,
        )
        created_version = license_agreement["version"]

        terminated = validate_success(api.terminate_license(license_agreement["id"], RM), 200)
        assert terminated["version"] == created_version + 1, (
            "terminate must advance the license version by exactly one"
        )


class TestLogicalClock:
    def test_clock_regression_rejected(self, api):
        """PRD §2.5: "The clock is monotonic: a target earlier than the current logical clock is rejected with `ERR_CLOCK_REGRESSION` (422)."

        Design: Corner/validations/clock_regression_rejected
        """
        resp = api.set_clock("2026-07-01T00:00:00Z", RM)
        validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION, 422)
