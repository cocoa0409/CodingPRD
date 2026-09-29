"""Cross-cutting layers and the consistency model.

Two optimistic-concurrency write endpoints share one plan version counter, the
label lifecycle reconciles three derived pointers forwards and backwards, and
every cascade a write triggers is observable on the very next read.
"""

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, api_client
from test_helpers.assertions import (
    assert_account_ledger,
    assert_label_dimensions,
    assert_posture,
)
from test_helpers.constants import (
    PEAK_HOUR_MEDIAN_DOWNLOAD_MARGIN,
    PEAK_HOUR_MEDIAN_UPLOAD_MARGIN,
    REFERENCE_NOW,
)
from test_helpers.factories import (
    build_attestation_payload,
    build_label_version_payload,
    build_plan_amendment_payload,
    build_uphold_payload,
    build_withdraw_label_payload,
)
from test_helpers.fixtures import (
    ReferenceEnvironment,
    add_verified_translation,
    build_reference_environment,
    certify_attestation,
    create_investigated_complaint,
    create_measurement_probe,
    create_published_methodology,
    create_reference_plan,
    current_plan_version,
    draft_label,
    record_test_run,
    set_clock,
)
from test_helpers.test_users import (
    COMPLAINT_ANALYST_HEADERS,
    COMPLIANCE_OFFICER_2_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    NETWORK_ENGINEER_HEADERS,
)
from test_helpers.types import (
    CreditBasis,
    LabelPosture,
    PublicationState,
    RemediationCreditStatus,
    SubstantiationStatus,
    TranslationStatus,
)

# ---------------------------------------------------------------------------
# Literals pinned by the reference world
# ---------------------------------------------------------------------------

#: The repriced post-promotional base charge used by the amendment below.
REPRICED_MONTHLY_PRICE_CENTS = 8999
#: The gross post-promotional monthly total the redrafted label must carry once
#: the itemisation is recomputed against the repriced base charge.
REPRICED_MONTHLY_TOTAL_POST_PROMO_CENTS = 11681

#: The successor label's display window opens a month after the incumbent's.
SUCCESSOR_EFFECTIVE_FROM = "2026-10-01T00:00:00Z"
#: The logical clock every chain below runs at, with three fractional digits as
#: the server writes its own `*_at` timestamps.
REFERENCE_NOW_MILLIS = "2026-09-01T00:00:00.000Z"

#: The date the disputed shortfall was observed, inside the label's window.
OBSERVED_DATE = "2026-09-02T12:00:00Z"
#: 240.00 claimed against 120 measured is a ratio of exactly one half.
EXPECTED_SHORTFALL_RATIO = 0.5000
EXPECTED_SEVERITY = "SEVERE"
#: 3766 net intro cents x 0.5000 x 15/30 days = 941.5, rounded half up.
EXPECTED_CREDIT_CENTS = 942


# ---------------------------------------------------------------------------
# Module-private setup chains
# ---------------------------------------------------------------------------


def _instant(value: Optional[str]) -> datetime:
    """Parse a server timestamp so two spellings of one instant compare equal."""
    assert value is not None, "expected a timestamp, got null"
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _measured_plan_without_attestation() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A plan with its five fee lines and one recorded run, but no attestation
    and no label yet, so both concurrency-protected creates are still ahead.

    Returns the plan and the published methodology document.
    """
    set_clock(REFERENCE_NOW)
    plan = create_reference_plan()
    methodology = create_published_methodology()
    probe = create_measurement_probe()
    record_test_run(probe["id"], plan["id"], methodology["id"])
    return plan, methodology


def _amend_monthly_price(plan_id: str) -> Dict[str, Any]:
    """Reprice the plan between a client's read and its write."""
    return get_success_data(
        api_client.amend_service_plan(
            plan_id,
            build_plan_amendment_payload(
                change_justification="Repricing between the read and the write",
                monthly_price_cents=REPRICED_MONTHLY_PRICE_CENTS,
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )


def _published_label_with_draft_successor() -> Tuple[ReferenceEnvironment, Dict[str, Any]]:
    """The reference world plus a second, still-drafted label carrying its own
    verified `en-US` translation, ready to displace the incumbent."""
    env = build_reference_environment()
    successor = draft_label(env.plan_id, effective_from=SUCCESSOR_EFFECTIVE_FROM)
    add_verified_translation(successor["id"], locale="en-US")
    return env, successor


def _investigated_speed_complaint() -> Tuple[ReferenceEnvironment, Dict[str, Any]]:
    """The reference world plus one complaint walked to `UNDER_INVESTIGATION`,
    which is the only state a resolution may be taken from."""
    env = build_reference_environment()
    complaint = create_investigated_complaint(
        env.account_id,
        env.label_id,
        service_observed_date=OBSERVED_DATE,
        affected_days=15,
        measured_download_mbps=120,
    )
    return env, complaint


# ---------------------------------------------------------------------------
# cross_cutting_complexity_layers
# ---------------------------------------------------------------------------


class TestStalePlanVersionOnBothOccWriteEndpoints:
    """Both concurrency-protected creates read the same plan version counter."""

    def test_attestation_create_with_a_version_captured_before_the_amendment_is_refused(
        self,
    ):
        """A plan version read before a repricing no longer buys an attestation.

        PRD: "If that value does not equal the plan's current `version`, the
        create is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_plan_version_rejected_on_both_occ_write_endpoints
        """
        plan, methodology = _measured_plan_without_attestation()
        plan_id = plan["id"]

        stale_version = current_plan_version(plan_id)
        _amend_monthly_price(plan_id)

        response = api_client.create_performance_attestation(
            build_attestation_payload(plan_id, methodology["id"], stale_version),
            NETWORK_ENGINEER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_STALE_PLAN_VERSION.value)

        fresh_version = current_plan_version(plan_id)
        assert fresh_version == stale_version + 1, (
            "the amendment must have incremented the plan version exactly once, "
            f"from {stale_version} to {fresh_version}"
        )

        _, meta = validate_paginated(
            api_client.list_performance_attestations(
                NETWORK_ENGINEER_HEADERS, params={"plan_id": plan_id}
            )
        )
        assert meta["total_count"] == 0, (
            "the refused create must have left no PerformanceAttestation row behind"
        )

    def test_label_create_with_a_version_captured_before_the_amendment_is_refused(self):
        """The same stale version is refused on the label endpoint too.

        PRD: "Creating a `LabelVersion` likewise requires
        `expected_plan_version` as a non-optional body field carrying the
        client's last observed `version` of the plan named by `plan_id`, and a
        mismatch with the plan's current `version` is rejected with
        `ERR_STALE_PLAN_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_plan_version_rejected_on_both_occ_write_endpoints
        """
        plan, _ = _measured_plan_without_attestation()
        plan_id = plan["id"]

        stale_version = current_plan_version(plan_id)
        _amend_monthly_price(plan_id)

        response = api_client.create_label_version(
            build_label_version_payload(plan_id, REFERENCE_NOW, stale_version),
            COMPLIANCE_OFFICER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_STALE_PLAN_VERSION.value)

        reread = validate_success(
            api_client.get_service_plan(plan_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert reread["active_label_version_id"] is None, (
            "the refused create must not have given the plan an active label"
        )
        assert reread["version"] == stale_version + 1, (
            "only the accepted amendment advanced the plan version"
        )

        _, meta = validate_paginated(
            api_client.list_label_versions(
                COMPLIANCE_OFFICER_HEADERS, params={"plan_id": plan_id}
            )
        )
        assert meta["total_count"] == 0, (
            "the refused create must have left no LabelVersion row behind"
        )

    def test_an_accepted_attestation_create_bumps_the_version_it_just_consumed(self):
        """A client cannot reuse the version its own accepted write advanced.

        PRD: "Creating an attestation, drafting a label, publishing a label,
        withdrawing a label, amending a plan, certifying an attestation that
        re-substantiates a published label, and upholding a complaint each
        increment `ServicePlan.version` as well."

        Design: Corner/cross_cutting_complexity_layers/stale_plan_version_rejected_on_both_occ_write_endpoints
        """
        plan, methodology = _measured_plan_without_attestation()
        plan_id = plan["id"]

        stale_version = current_plan_version(plan_id)
        _amend_monthly_price(plan_id)
        fresh_version = current_plan_version(plan_id)
        assert fresh_version == stale_version + 1

        attestation = validate_success(
            api_client.create_performance_attestation(
                build_attestation_payload(plan_id, methodology["id"], fresh_version),
                NETWORK_ENGINEER_HEADERS,
            ),
            expected_status=201,
        )
        assert round(float(attestation["download_margin_pct"]), 4) == round(
            PEAK_HOUR_MEDIAN_DOWNLOAD_MARGIN, 4
        ), (
            "the retried attestation must compute the peak-hour download margin, "
            f"got {attestation['download_margin_pct']}"
        )
        assert round(float(attestation["upload_margin_pct"]), 4) == round(
            PEAK_HOUR_MEDIAN_UPLOAD_MARGIN, 4
        )
        certify_attestation(attestation["id"])

        next_version = current_plan_version(plan_id)
        assert next_version == fresh_version + 1, (
            "the attestation create is itself a plan write, so the version the "
            f"client just used ({fresh_version}) is already spent, got {next_version}"
        )

        replayed = api_client.create_label_version(
            build_label_version_payload(plan_id, REFERENCE_NOW, fresh_version),
            COMPLIANCE_OFFICER_HEADERS,
        )
        validate_error(replayed, ApiErrorId.ERR_STALE_PLAN_VERSION.value)

        label = validate_success(
            api_client.create_label_version(
                build_label_version_payload(plan_id, REFERENCE_NOW, next_version),
                COMPLIANCE_OFFICER_HEADERS,
            ),
            expected_status=201,
        )
        assert (
            label["monthly_total_post_promo_cents"]
            == REPRICED_MONTHLY_TOTAL_POST_PROMO_CENTS
        ), (
            "the accepted draft must itemise against the post-amendment base "
            f"charge, got {label['monthly_total_post_promo_cents']}"
        )


class TestDerivedPointersAcrossTheLabelLifecycle:
    """The active pointer, the predecessor's window and both verified-locale
    counts are reconciled forwards by the publish and backwards by the
    withdrawal."""

    def test_publishing_the_successor_moves_the_active_pointer_and_archives_the_predecessor(
        self,
    ):
        """The incumbent is archived and its open-ended window is truncated.

        PRD: "It archives the plan's previous published label: that
        predecessor's `publication_state` becomes `ARCHIVED`, its `archived_at`
        is set to the logical clock, and its `effective_until` is truncated to
        the new label's `effective_from` when it was previously null or later
        than that instant."

        Design: Corner/cross_cutting_complexity_layers/derived_pointers_reconcile_across_the_label_lifecycle
        """
        env, successor = _published_label_with_draft_successor()

        before = validate_success(
            api_client.get_service_plan(env.plan_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert before["active_label_version_id"] == env.label_id, (
            "the incumbent label must be the plan's active label before the "
            "successor is published"
        )
        incumbent_before = validate_success(
            api_client.get_label_version(env.label_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert incumbent_before["effective_until"] is None, (
            "the incumbent's display window is open-ended before the successor "
            "displaces it"
        )

        validate_success(
            api_client.publish_label_version(
                successor["id"], COMPLIANCE_OFFICER_2_HEADERS
            )
        )

        after = validate_success(
            api_client.get_service_plan(env.plan_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert after["active_label_version_id"] == successor["id"], (
            "publishing the successor must move the plan's active pointer onto it"
        )

        incumbent_after = validate_success(
            api_client.get_label_version(env.label_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert_label_dimensions(
            incumbent_after,
            PublicationState.ARCHIVED.value,
            SubstantiationStatus.SUBSTANTIATED.value,
        )
        assert _instant(incumbent_after["effective_until"]) == _instant(
            SUCCESSOR_EFFECTIVE_FROM
        ), (
            "the archived predecessor's window must be truncated to the "
            f"successor's effective_from, got {incumbent_after['effective_until']}"
        )
        assert _instant(incumbent_after["archived_at"]) == _instant(
            REFERENCE_NOW_MILLIS
        ), (
            "archived_at must be the logical clock, got "
            f"{incumbent_after['archived_at']}"
        )

    def test_withdrawing_the_successor_restores_every_pointer_to_its_pre_successor_value(
        self,
    ):
        """The compensation leaves no drift on any of the three pointers.

        PRD: "Withdrawal sets `publication_state` to `WITHDRAWN` and
        `withdrawn_at` to the logical clock, then restores the predecessor it
        displaced: among the same plan's labels whose `publication_state` is
        `ARCHIVED`, ranked by `version_seq` descending with `created_at`
        ascending as the tie-break, the first one is returned to
        `publication_state` `PUBLISHED`, its `archived_at` is cleared, and its
        `effective_until` is restored to the value it held before publication
        truncated it."

        Design: Corner/cross_cutting_complexity_layers/derived_pointers_reconcile_across_the_label_lifecycle
        """
        env, successor = _published_label_with_draft_successor()

        version_before = current_plan_version(env.plan_id)

        validate_success(
            api_client.publish_label_version(
                successor["id"], COMPLIANCE_OFFICER_2_HEADERS
            )
        )
        validate_success(
            api_client.withdraw_label_version(
                successor["id"],
                build_withdraw_label_payload(
                    reason="Successor withdrawn after a disclosure defect was found"
                ),
                COMPLIANCE_OFFICER_HEADERS,
            )
        )

        plan = validate_success(
            api_client.get_service_plan(env.plan_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert plan["active_label_version_id"] == env.label_id, (
            "withdrawing the successor must hand the active pointer back to the "
            "predecessor it displaced"
        )
        assert plan["version"] == version_before + 2, (
            "the publish and the withdrawal are one plan write each, so the "
            f"version must be {version_before + 2}, got {plan['version']}"
        )

        restored = validate_success(
            api_client.get_label_version(env.label_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert_label_dimensions(
            restored,
            PublicationState.PUBLISHED.value,
            SubstantiationStatus.SUBSTANTIATED.value,
        )
        assert restored["effective_until"] is None, (
            "the restored predecessor's effective_until must return to the "
            f"open-ended value it held before publication, got "
            f"{restored['effective_until']}"
        )
        assert restored["archived_at"] is None, (
            "the restored predecessor's archived_at must be cleared, got "
            f"{restored['archived_at']}"
        )

        withdrawn = validate_success(
            api_client.get_label_version(successor["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert withdrawn["publication_state"] == PublicationState.WITHDRAWN.value, (
            "the successor must end in WITHDRAWN, got "
            f"{withdrawn['publication_state']}"
        )
        assert _instant(withdrawn["withdrawn_at"]) == _instant(REFERENCE_NOW_MILLIS), (
            f"withdrawn_at must be the logical clock, got {withdrawn['withdrawn_at']}"
        )

    def test_verified_locale_count_tracks_the_verified_translations_of_both_labels(self):
        """Neither label's verified-locale count moves as the pointers swing.

        PRD: "`LabelVersion.verified_locale_count` is the number of
        translations on that label whose `status` is `VERIFIED`."

        Design: Corner/cross_cutting_complexity_layers/derived_pointers_reconcile_across_the_label_lifecycle
        """
        env, successor = _published_label_with_draft_successor()

        for label_id in (env.label_id, successor["id"]):
            label = validate_success(
                api_client.get_label_version(label_id, COMPLIANCE_OFFICER_HEADERS)
            )
            assert label["verified_locale_count"] == 1, (
                f"label {label_id} carries one verified locale before the "
                f"successor publish, got {label['verified_locale_count']}"
            )

        validate_success(
            api_client.publish_label_version(
                successor["id"], COMPLIANCE_OFFICER_2_HEADERS
            )
        )
        validate_success(
            api_client.withdraw_label_version(
                successor["id"],
                build_withdraw_label_payload(
                    reason="Successor withdrawn after a disclosure defect was found"
                ),
                COMPLIANCE_OFFICER_HEADERS,
            )
        )

        for label_id in (env.label_id, successor["id"]):
            label = validate_success(
                api_client.get_label_version(label_id, COMPLIANCE_OFFICER_HEADERS)
            )
            assert label["verified_locale_count"] == 1, (
                f"label {label_id} still carries one verified locale after the "
                f"publish and the withdrawal, got {label['verified_locale_count']}"
            )
            rows, meta = validate_paginated(
                api_client.list_label_translations(
                    label_id,
                    COMPLIANCE_OFFICER_HEADERS,
                    params={"status": TranslationStatus.VERIFIED.value},
                )
            )
            assert meta["total_count"] == label["verified_locale_count"], (
                "the VERIFIED-filtered translation list must agree with "
                f"verified_locale_count on label {label_id}"
            )
            assert all(
                row["status"] == TranslationStatus.VERIFIED.value for row in rows
            ), "the status filter must return VERIFIED translations only"


# ---------------------------------------------------------------------------
# consistency_model
# ---------------------------------------------------------------------------


class TestEveryCascadeIsVisibleInTheSameResponse:
    """Resolving a complaint publishes its whole cascade immediately: no retry,
    no sleep and no re-read loop is ever needed."""

    def test_the_resolve_response_already_carries_the_assessment_and_the_credit(self):
        """The computed credit arrives in the body of the write itself.

        PRD: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field." "Under `PRORATA_DAYS` the raw figure is the base multiplied by
        the complaint's `shortfall_ratio`, multiplied by the lesser of the
        complaint's `affected_days` and thirty days, divided by thirty."

        Design: Corner/consistency_model/every_cascade_is_visible_in_the_same_response
        """
        _, complaint = _investigated_speed_complaint()

        resolved = validate_success(
            api_client.resolve_complaint(
                complaint["id"],
                build_uphold_payload(
                    credit_basis=CreditBasis.PRORATA_DAYS.value,
                    resolution_note=(
                        "Shortfall confirmed against the pinned typical speed"
                    ),
                ),
                COMPLAINT_ANALYST_HEADERS,
            )
        )

        assert resolved["state"] == "UPHELD", (
            f"the resolve response must already read UPHELD, got {resolved['state']}"
        )
        assert resolved["resolution"] == "UPHELD", (
            f"resolution must already read UPHELD, got {resolved['resolution']}"
        )
        assert round(float(resolved["shortfall_ratio"]), 4) == round(
            EXPECTED_SHORTFALL_RATIO, 4
        ), (
            "the shortfall ratio must be computed in the same response, got "
            f"{resolved['shortfall_ratio']}"
        )
        assert resolved["severity"] == EXPECTED_SEVERITY, (
            f"severity must be {EXPECTED_SEVERITY}, got {resolved['severity']}"
        )
        assert resolved["remediation_credit_cents"] == EXPECTED_CREDIT_CENTS, (
            "the computed credit must be on the resolve response with no second "
            f"read, got {resolved['remediation_credit_cents']}"
        )
        assert resolved["credit_basis"] == CreditBasis.PRORATA_DAYS.value

    def test_the_issued_credit_is_listable_on_the_first_read_after_the_resolve(self):
        """The ledger row exists the instant the resolve returns.

        PRD: "A remediation credit is created carrying `complaint_id` naming
        this complaint, `account_id` copied from the complaint's own account (a
        denormalised copy, never client-supplied), `basis` copied from the
        complaint's `credit_basis`, `amount_cents` set to the computed amount
        and immutable thereafter, `status` `ISSUED`, and `issued_by_user_id`
        set to the resolving analyst's `X-User-ID`, with `voided_by_user_id`,
        `voided_at` and `void_reason` all null."

        Design: Corner/consistency_model/every_cascade_is_visible_in_the_same_response
        """
        env, complaint = _investigated_speed_complaint()

        validate_success(
            api_client.resolve_complaint(
                complaint["id"],
                build_uphold_payload(
                    credit_basis=CreditBasis.PRORATA_DAYS.value,
                    resolution_note=(
                        "Shortfall confirmed against the pinned typical speed"
                    ),
                ),
                COMPLAINT_ANALYST_HEADERS,
            )
        )

        rows, meta = validate_paginated(
            api_client.list_complaint_remediation_credits(
                complaint["id"], COMPLAINT_ANALYST_HEADERS
            )
        )
        assert meta["total_count"] == 1, (
            "exactly one credit must be visible on the first listing after the "
            f"resolve, got {meta['total_count']}"
        )
        credit = rows[0]
        assert credit["amount_cents"] == EXPECTED_CREDIT_CENTS, (
            f"the credit amount must be {EXPECTED_CREDIT_CENTS} cents, got "
            f"{credit['amount_cents']}"
        )
        assert credit["status"] == RemediationCreditStatus.ISSUED.value
        assert credit["basis"] == CreditBasis.PRORATA_DAYS.value
        assert credit["complaint_id"] == complaint["id"]
        assert credit["account_id"] == env.account_id, (
            "the credit carries a denormalised copy of the complaint's account"
        )

        direct = validate_success(
            api_client.get_remediation_credit(credit["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert direct["amount_cents"] == EXPECTED_CREDIT_CENTS, (
            "the direct read of the credit agrees with the listing immediately"
        )
        assert direct["voided_by_user_id"] is None
        assert direct["voided_at"] is None
        assert direct["void_reason"] is None

    def test_the_account_ledger_and_the_plan_posture_need_no_second_read(self):
        """Both aggregates are already reconciled when the resolve returns.

        PRD: "The account's `credit_balance_cents` is recomputed as the sum of
        `amount_cents` over that account's credits whose `status` is `ISSUED`,
        `remediation_count` as the count of those same rows, and the account's
        `version` is incremented."

        Design: Corner/consistency_model/every_cascade_is_visible_in_the_same_response
        """
        env, complaint = _investigated_speed_complaint()

        validate_success(
            api_client.resolve_complaint(
                complaint["id"],
                build_uphold_payload(
                    credit_basis=CreditBasis.PRORATA_DAYS.value,
                    resolution_note=(
                        "Shortfall confirmed against the pinned typical speed"
                    ),
                ),
                COMPLAINT_ANALYST_HEADERS,
            )
        )

        account = validate_success(
            api_client.get_subscriber_account(
                env.account_id, COMPLIANCE_OFFICER_HEADERS
            )
        )
        assert_account_ledger(account, EXPECTED_CREDIT_CENTS, 1)

        plan = validate_success(
            api_client.get_service_plan(env.plan_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert plan["upheld_complaint_count"] == 1, (
            "the plan's upheld count must already read 1, got "
            f"{plan['upheld_complaint_count']}"
        )
        assert_posture(plan, LabelPosture.OPEN.value)
