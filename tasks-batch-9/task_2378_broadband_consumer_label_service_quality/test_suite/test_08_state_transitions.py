"""State transitions: initial states, valid edges, refused edges, terminal
states and the side effects a transition carries onto neighbouring records.
"""

from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, api_client
from test_helpers.assertions import (
    assert_account_ledger,
    assert_evidence_sample_total,
    assert_label_dimensions,
    assert_posture,
)
from test_helpers.constants import (
    PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD,
    REFERENCE_NOW,
)
from test_helpers.factories import (
    build_complaint_payload,
    build_dismiss_payload,
    build_label_version_payload,
    build_methodology_document_payload,
    build_plan_change_notice_payload,
    build_regulator_inquiry_payload,
    build_reopen_payload,
    build_request_info_payload,
    build_subscriber_account_payload,
    build_test_run_payload,
    build_translation_payload,
    build_triage_payload,
    build_uphold_payload,
    build_withdraw_complaint_payload,
    build_withdraw_label_payload,
)
from test_helpers.fixtures import (
    add_translation,
    add_verified_translation,
    create_measurement_probe,
    create_methodology_document,
    create_plan_change_notice,
    create_published_label,
    create_published_methodology,
    create_reference_plan,
    create_service_plan,
    draft_label,
    file_complaint,
    investigate_complaint,
    read_complaint,
    read_label,
    read_plan_change_notice,
    read_service_plan,
    read_subscriber_account,
    record_disclosure,
    set_clock,
    triage_complaint,
    uphold_complaint,
)
from test_helpers.test_users import (
    COMPLAINT_ANALYST_HEADERS,
    COMPLIANCE_OFFICER_2_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    LOCALIZATION_SPECIALIST_2_HEADERS,
    NETWORK_ENGINEER_HEADERS,
    REGULATORY_LIAISON_HEADERS,
    RETAIL_AGENT_HEADERS,
    make_operator_headers,
    make_subscriber_headers,
)
from test_helpers.types import (
    AllegationType,
    AttestationStatus,
    ComplaintResolution,
    ComplaintSeverity,
    ComplaintState,
    CreditBasis,
    LabelPosture,
    MethodologyDocumentStatus,
    NoticeState,
    NoticeType,
    PricingPhase,
    PublicationState,
    RegulatorInquiryState,
    SubscriptionState,
    SubstantiationStatus,
    TestRunStatus,
    TranslationStatus,
    UserRole,
)

# The reference world's own literals, as the shared scenario pins them.
REFERENCE_STAMP = "2026-09-01T00:00:00.000Z"
DAY_AFTER_REFERENCE_NOW = "2026-09-02T00:00:00Z"
SERVICE_OBSERVED_DATE = "2026-09-02T12:00:00Z"
SUCCESSOR_EFFECTIVE_FROM = "2026-10-01T00:00:00Z"
SUCCESSOR_STAMP = "2026-10-01T00:00:00.000Z"

INTRO_GROSS_CENTS = 6766
INTRO_NET_CENTS = 3766
POST_PROMO_GROSS_CENTS = 10628
POST_PROMO_NET_CENTS = 7628
PRORATA_CREDIT_CENTS = 942
ETF_DISCLOSED_CENTS = 12000
REFERENCE_SAMPLE_COUNT = 6
SEVERE_SHORTFALL_RATIO = 0.5000
THIRD_OFFICER_HEADERS = make_operator_headers("co-3", UserRole.COMPLIANCE_OFFICER.value)
THIRD_SPECIALIST_HEADERS = make_operator_headers(
    "loc-3", UserRole.LOCALIZATION_SPECIALIST.value
)


def _instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant, however many fractional digits it
    carries."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _assert_same_instant(actual, expected: str, field: str) -> None:
    assert actual is not None, f"{field} should be set"
    assert _instant(actual) == _instant(expected), (
        f"{field}: expected the instant {expected}, got {actual}"
    )


class TestNewlyCreatedRowsStartInDeclaredInitialStates:
    """Every machine mints its rows in the declared initial state."""

    def test_new_service_plan_starts_restricted_before_any_label_is_published(
        self, reference_environment
    ):
        """A plan with no published label is restricted, while the reference
        plan whose label is published reads open.

        PRD: "A new plan starts with `label_posture` set to `RESTRICTED`,
        `evidence_sample_total` at 0, `upheld_complaint_count` at 0,
        `price_disclosure_drift` false, `active_label_version_id` null,
        `last_price_change_at` null and `version` at 1."

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        fresh = create_service_plan()

        assert_posture(fresh, LabelPosture.RESTRICTED.value)
        assert_evidence_sample_total(fresh, 0)
        assert fresh["upheld_complaint_count"] == 0, "no complaint has been upheld yet"
        assert fresh["price_disclosure_drift"] is False, "a new plan has not drifted"
        assert fresh["active_label_version_id"] is None, "no label is published yet"
        assert fresh["last_price_change_at"] is None, "no price has changed yet"
        assert fresh["version"] == 1, "version starts at 1"

        assert_posture(reference_environment.plan, LabelPosture.OPEN.value)

    def test_new_methodology_document_starts_draft(self):
        """A freshly authored methodology document is unpublished.

        PRD: "It begins with `status` set to `DRAFT` and `published_at` null."

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        set_clock(REFERENCE_NOW)

        response = api_client.create_methodology_document(
            build_methodology_document_payload(), NETWORK_ENGINEER_HEADERS
        )

        document = validate_success(response, expected_status=201)
        assert document["status"] == MethodologyDocumentStatus.DRAFT.value, (
            "a new methodology document begins in DRAFT"
        )
        assert document["published_at"] is None, "published_at is null until publication"
        assert document["version"] == 1, "version starts at 1"

    def test_new_test_run_starts_included_in_the_evidence_pool(self):
        """A recorded run joins the evidence pool without an explicit trigger.

        PRD: "The run's `sample_count` is fixed at creation as the number of
        elements supplied, and the run opens with `status` `INCLUDED`,
        `invalidated_at` null, `invalidation_reason` null."

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        set_clock(REFERENCE_NOW)
        plan = create_reference_plan()
        methodology = create_published_methodology()
        probe = create_measurement_probe()

        response = api_client.create_test_run(
            build_test_run_payload(probe["id"], plan["id"], methodology["id"]),
            NETWORK_ENGINEER_HEADERS,
        )

        run = validate_success(response, expected_status=201)
        assert run["status"] == TestRunStatus.INCLUDED.value, (
            "a recorded run opens INCLUDED"
        )
        assert run["sample_count"] == REFERENCE_SAMPLE_COUNT, (
            "sample_count is fixed at creation from the supplied array"
        )
        assert run["invalidated_at"] is None, "invalidated_at is null on a new run"
        assert run["invalidation_reason"] is None, (
            "invalidation_reason is null on a new run"
        )
        assert_evidence_sample_total(
            read_service_plan(plan["id"]), REFERENCE_SAMPLE_COUNT
        )

    def test_new_label_version_starts_draft_and_pending_evidence(self):
        """The two label dimensions start independently, with no pinned claim.

        PRD: "It opens with `publication_state` `DRAFT` and
        `substantiation_status` `PENDING_EVIDENCE`, and with `attestation_id`,
        `typical_download_mbps`, `typical_upload_mbps`, `typical_latency_ms` and
        `methodology_url_snapshot` all null, `published_by_user_id`,
        `published_at`, `archived_at` and `withdrawn_at` null,
        `price_disclosure_drift` false and `verified_locale_count` at 0."

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        set_clock(REFERENCE_NOW)
        plan = create_reference_plan()

        response = api_client.create_label_version(
            build_label_version_payload(plan["id"], REFERENCE_NOW, plan["version"]),
            COMPLIANCE_OFFICER_HEADERS,
        )

        label = validate_success(response, expected_status=201)
        assert_label_dimensions(
            label,
            PublicationState.DRAFT.value,
            SubstantiationStatus.PENDING_EVIDENCE.value,
        )
        assert label["version_seq"] == 1, "the plan's first label is version_seq 1"
        assert label["attestation_id"] is None, "no attestation is pinned on a draft"
        assert label["typical_download_mbps"] is None, "the claim is not pinned yet"
        assert label["typical_upload_mbps"] is None, "the claim is not pinned yet"
        assert label["typical_latency_ms"] is None, "the claim is not pinned yet"
        assert label["methodology_url_snapshot"] is None, "no methodology is snapshotted"
        assert label["published_by_user_id"] is None, "nobody has published it"
        assert label["published_at"] is None, "published_at is null on a draft"
        assert label["archived_at"] is None, "archived_at is null on a draft"
        assert label["withdrawn_at"] is None, "withdrawn_at is null on a draft"
        assert label["price_disclosure_drift"] is False, "a new draft has not drifted"
        assert label["verified_locale_count"] == 0, "no locale is verified yet"
        assert label["created_by_user_id"] == "co-1", (
            "the drafting officer's id is recorded on the label"
        )

    def test_new_label_translation_starts_draft_and_unverified(self):
        """A newly added translation is unverified and records its author.

        PRD: "The translation opens with `status` `DRAFT`,
        `verified_by_user_id` and `verified_at` null, and records its author's
        `X-User-ID` in `created_by_user_id`."

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        set_clock(REFERENCE_NOW)
        plan = create_reference_plan()
        label = draft_label(plan["id"])

        response = api_client.create_label_translation(
            label["id"],
            build_translation_payload(locale="en-US"),
            make_operator_headers("loc-1", UserRole.LOCALIZATION_SPECIALIST.value),
        )

        translation = validate_success(response, expected_status=201)
        assert translation["status"] == TranslationStatus.DRAFT.value, (
            "a new translation opens in DRAFT"
        )
        assert translation["verified_by_user_id"] is None, "nobody has verified it"
        assert translation["verified_at"] is None, "verified_at is null until verified"
        assert translation["created_by_user_id"] == "loc-1", (
            "the authoring specialist's id is recorded on the translation"
        )

    def test_new_subscriber_account_starts_active_with_an_empty_ledger(self):
        """An enrolled account has no credits and no disclosure history.

        PRD: "The account opens with `subscription_state` `ACTIVE`,
        `credit_balance_cents` at 0, `remediation_count` at 0, `audit_flag`
        false and `last_disclosed_label_version_id` null."

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        set_clock(REFERENCE_NOW)
        plan = create_reference_plan()

        response = api_client.create_subscriber_account(
            build_subscriber_account_payload(plan["id"], REFERENCE_NOW),
            RETAIL_AGENT_HEADERS,
        )

        account = validate_success(response, expected_status=201)
        assert account["subscription_state"] == SubscriptionState.ACTIVE.value, (
            "a new account opens ACTIVE"
        )
        assert_account_ledger(account, 0, 0)
        assert account["last_disclosed_label_version_id"] is None, (
            "no label has been disclosed to the account yet"
        )

    def test_new_complaint_starts_in_intake_with_no_assessment(
        self, reference_environment
    ):
        """A filed complaint carries no assessment and no counters.

        PRD: "A complaint opens with `state` `INTAKE`, `resolution` `NONE`,
        `severity` `NONE`, `shortfall_ratio` null, `reopened_count` at 0,
        `investigation_cycles` at 0, `evidence_gap` false and
        `remediation_credit_cents` at 0, with `triaged_at`, `sla_due_at`,
        `resolved_at`, `resolution_note`, `info_request_note` and
        `credit_basis` all null."

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        env = reference_environment

        response = api_client.create_complaint(
            build_complaint_payload(
                env.account_id,
                env.label_id,
                SERVICE_OBSERVED_DATE,
                affected_days=4,
                narrative="Evening speeds well below the label",
                measured_download_mbps=150,
            ),
            COMPLAINT_ANALYST_HEADERS,
        )

        complaint = validate_success(response, expected_status=201)
        assert complaint["state"] == ComplaintState.INTAKE.value, (
            "a filed complaint opens in INTAKE"
        )
        assert complaint["resolution"] == ComplaintResolution.NONE.value
        assert complaint["severity"] == ComplaintSeverity.NONE.value
        assert complaint["shortfall_ratio"] is None, "no assessment has run yet"
        assert complaint["reopened_count"] == 0
        assert complaint["investigation_cycles"] == 0
        assert complaint["evidence_gap"] is False
        assert complaint["remediation_credit_cents"] == 0
        assert complaint["triaged_at"] is None
        assert complaint["sla_due_at"] is None
        assert complaint["resolved_at"] is None
        assert complaint["resolution_note"] is None
        assert complaint["info_request_note"] is None
        assert complaint["credit_basis"] is None

    def test_new_regulator_inquiry_starts_received_with_no_filings(
        self, reference_environment
    ):
        """A newly opened docket has neither branch on record.

        PRD: "The docket opens in state `RECEIVED` with `filed_late` false,
        both `technical_packet_filed_at` and `resolution_report_filed_at` null,
        both `technical_evidence_ref` and `resolution_report_ref` null, and
        `closure_note` and `closed_at` null."

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        env = reference_environment
        complaint = file_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=SERVICE_OBSERVED_DATE,
            affected_days=4,
            measured_download_mbps=150,
        )

        response = api_client.create_regulator_inquiry(
            build_regulator_inquiry_payload(complaint["id"]),
            REGULATORY_LIAISON_HEADERS,
        )

        inquiry = validate_success(response, expected_status=201)
        assert inquiry["state"] == RegulatorInquiryState.RECEIVED.value, (
            "a new docket opens in RECEIVED"
        )
        assert inquiry["filed_late"] is False
        assert inquiry["technical_packet_filed_at"] is None
        assert inquiry["resolution_report_filed_at"] is None
        assert inquiry["technical_evidence_ref"] is None
        assert inquiry["resolution_report_ref"] is None
        assert inquiry["closure_note"] is None
        assert inquiry["closed_at"] is None


class TestPublishMethodologyMovesDocumentToPublished:
    """The single methodology transition, and the gate it opens."""

    def test_publishing_a_methodology_stamps_it_and_bumps_its_version(self):
        """Publication is a compliance officer's act on an engineer's document.

        PRD: "Publication sets `published_at` to the logical clock and
        increments the document's `version`."

        Design: Corner/state_machines/publish_methodology_moves_document_to_published
        """
        set_clock(REFERENCE_NOW)
        document = create_methodology_document()

        response = api_client.publish_methodology_document(
            document["id"], COMPLIANCE_OFFICER_HEADERS
        )

        published = validate_success(response)
        assert published["status"] == MethodologyDocumentStatus.PUBLISHED.value, (
            "the document moves DRAFT to PUBLISHED"
        )
        assert published["published_at"] == REFERENCE_STAMP, (
            "published_at is taken from the logical clock"
        )
        assert published["version"] == 2, "publication increments the version"

    def test_only_a_published_methodology_may_back_a_measurement_run(self):
        """The transition is the gate a run has to pass.

        PRD: "`PUBLISHED` is terminal: only a published document may back a
        measurement run or an attestation, and a run or attestation that cites
        a document still in `DRAFT` is rejected with
        `ERR_METHODOLOGY_NOT_PUBLISHED`."

        Design: Corner/state_machines/publish_methodology_moves_document_to_published
        """
        set_clock(REFERENCE_NOW)
        plan = create_reference_plan()
        probe = create_measurement_probe()
        document = create_methodology_document()
        run_payload = build_test_run_payload(probe["id"], plan["id"], document["id"])

        too_early = api_client.create_test_run(run_payload, NETWORK_ENGINEER_HEADERS)
        validate_error(too_early, ApiErrorId.ERR_METHODOLOGY_NOT_PUBLISHED.value)

        api_client.publish_methodology_document(
            document["id"], COMPLIANCE_OFFICER_HEADERS
        )
        accepted = api_client.create_test_run(run_payload, NETWORK_ENGINEER_HEADERS)

        run = validate_success(accepted, expected_status=201)
        assert run["status"] == TestRunStatus.INCLUDED.value, (
            "the run citing the now-published document is admitted"
        )
        assert run["sample_count"] == REFERENCE_SAMPLE_COUNT
        assert_evidence_sample_total(
            read_service_plan(plan["id"]), REFERENCE_SAMPLE_COUNT
        )


class TestRepublishingAPublishedMethodologyIsRejected:
    """`PUBLISHED` is terminal, so the second publish is a rejection."""

    def test_second_publish_is_rejected_and_does_not_restamp_the_document(self):
        """A second attempt is refused rather than treated as a no-op success.

        PRD: "The transition from `DRAFT` to `PUBLISHED` requires that the
        document still be `DRAFT` (a second attempt answers
        `ERR_METHODOLOGY_ALREADY_PUBLISHED`) and that its peak window still be
        well-formed, with the exclusive end hour strictly greater than the
        inclusive start hour."

        Design: Corner/state_machines/republishing_a_published_methodology_is_rejected
        """
        set_clock(REFERENCE_NOW)
        document = create_published_methodology()
        set_clock(DAY_AFTER_REFERENCE_NOW)

        response = api_client.publish_methodology_document(
            document["id"], COMPLIANCE_OFFICER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_METHODOLOGY_ALREADY_PUBLISHED.value)
        reread = validate_success(
            api_client.get_methodology_document(
                document["id"], COMPLIANCE_OFFICER_HEADERS
            )
        )
        assert reread["published_at"] == REFERENCE_STAMP, (
            "published_at is not restamped to the advanced clock"
        )
        assert reread["version"] == 2, "the rejected call did not mutate the document"


class TestComplaintTriggersAbsentFromTheTransitionListRejected:
    """For each complaint state, the triggers that are not edges out of it."""

    @pytest.mark.parametrize("trigger", ["investigate", "request_info"])
    def test_investigation_triggers_are_refused_from_intake(
        self, reference_environment, trigger
    ):
        """`INTAKE` has no investigation edge; only triage and withdraw.

        PRD: "Each of these three transitions requires its own from-state and
        otherwise answers `ERR_COMPLAINT_INVALID_STATE`."

        Design: Corner/state_machines/complaint_triggers_absent_from_the_transition_list_rejected
        """
        env = reference_environment
        complaint = file_complaint(
            env.account_id, env.label_id, service_observed_date=SERVICE_OBSERVED_DATE
        )

        if trigger == "investigate":
            response = api_client.investigate_complaint(
                complaint["id"], COMPLAINT_ANALYST_HEADERS
            )
        else:
            response = api_client.request_complaint_info(
                complaint["id"],
                build_request_info_payload(
                    info_request_note="Please share your router model"
                ),
                COMPLAINT_ANALYST_HEADERS,
            )

        validate_error(response, ApiErrorId.ERR_COMPLAINT_INVALID_STATE.value)
        reread = read_complaint(complaint["id"])
        assert reread["state"] == ComplaintState.INTAKE.value, (
            "the refused trigger left the complaint in INTAKE"
        )
        assert reread["investigation_cycles"] == 0, (
            "a refused trigger increments no counter"
        )
        assert reread["info_request_note"] is None, "no note was recorded"

    def test_triage_is_refused_from_triaged(self, reference_environment):
        """Triage is an `INTAKE` edge only, so triaging twice is refused.

        PRD: "Triage is a `ComplaintAnalyst`'s act carrying a `priority_note`,
        and it moves the complaint `INTAKE → TRIAGED`; from any other state it
        answers `ERR_COMPLAINT_INVALID_STATE`."

        Design: Corner/state_machines/complaint_triggers_absent_from_the_transition_list_rejected
        """
        env = reference_environment
        complaint = file_complaint(
            env.account_id, env.label_id, service_observed_date=SERVICE_OBSERVED_DATE
        )
        triaged = triage_complaint(complaint["id"])

        response = api_client.triage_complaint(
            complaint["id"],
            build_triage_payload(priority_note="Triaged twice"),
            COMPLAINT_ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_COMPLAINT_INVALID_STATE.value)
        reread = read_complaint(complaint["id"])
        assert reread["state"] == ComplaintState.TRIAGED.value, (
            "the complaint stays TRIAGED"
        )
        assert reread["triaged_at"] == triaged["triaged_at"], (
            "the refused second triage did not restamp triaged_at"
        )
        assert reread["sla_due_at"] == triaged["sla_due_at"], (
            "the refused second triage did not restart the response clock"
        )

    @pytest.mark.parametrize("from_state", ["INTAKE", "TRIAGED"])
    def test_resolution_is_refused_before_the_investigation_is_open(
        self, reference_environment, from_state
    ):
        """Only `UNDER_INVESTIGATION` accepts a resolution.

        PRD: "Either resolution requires the complaint to be
        `UNDER_INVESTIGATION`, and otherwise answers
        `ERR_COMPLAINT_INVALID_STATE`."

        Design: Corner/state_machines/complaint_triggers_absent_from_the_transition_list_rejected
        """
        env = reference_environment
        complaint = file_complaint(
            env.account_id, env.label_id, service_observed_date=SERVICE_OBSERVED_DATE
        )
        if from_state == "TRIAGED":
            triage_complaint(complaint["id"])
            payload = build_uphold_payload(resolution_note="Not yet investigated")
        else:
            payload = build_dismiss_payload(resolution_note="Premature")

        response = api_client.resolve_complaint(
            complaint["id"], payload, COMPLAINT_ANALYST_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_COMPLAINT_INVALID_STATE.value)
        reread = read_complaint(complaint["id"])
        assert reread["state"] == from_state, (
            "the refused resolution left the complaint where it was"
        )
        assert reread["resolution"] == ComplaintResolution.NONE.value
        assert reread["resolved_at"] is None, "nothing was resolved"
        assert reread["remediation_credit_cents"] == 0, "no credit was computed"

    def test_reopen_is_refused_on_an_upheld_complaint(self, reference_environment):
        """`UPHELD` is terminal; only `DISMISSED` accepts a reopen.

        PRD: "Reopening from any state other than `DISMISSED` answers
        `ERR_COMPLAINT_INVALID_STATE`."

        Design: Corner/state_machines/complaint_triggers_absent_from_the_transition_list_rejected
        """
        env = reference_environment
        complaint = file_complaint(
            env.account_id, env.label_id, service_observed_date=SERVICE_OBSERVED_DATE
        )
        triage_complaint(complaint["id"])
        investigate_complaint(complaint["id"])
        upheld = uphold_complaint(
            complaint["id"], credit_basis=CreditBasis.PRORATA_DAYS.value
        )

        response = api_client.reopen_complaint(
            complaint["id"],
            build_reopen_payload(reopen_reason="Reopen an upheld complaint"),
            COMPLAINT_ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_COMPLAINT_INVALID_STATE.value)
        reread = read_complaint(complaint["id"])
        assert reread["state"] == ComplaintState.UPHELD.value, "the finding stands"
        assert reread["severity"] == ComplaintSeverity.SEVERE.value
        assert float(reread["shortfall_ratio"]) == pytest.approx(
            SEVERE_SHORTFALL_RATIO, abs=0.0001
        )
        assert reread["remediation_credit_cents"] == PRORATA_CREDIT_CENTS, (
            "the pro-rata credit on the introductory net charge"
        )
        assert reread["reopened_count"] == 0, "the refused reopen incremented nothing"
        assert reread["investigation_cycles"] == upheld["investigation_cycles"], (
            "the refused reopen left the investigation counter alone"
        )
        assert read_service_plan(env.plan_id)["upheld_complaint_count"] == 1


class TestWithdrawnComplaintAcceptsNoFurtherTrigger:
    """`WITHDRAWN` is terminal and admits nothing afterwards."""

    def test_subscriber_withdraws_a_triaged_complaint(self, reference_environment):
        """Withdrawal from `TRIAGED` behaves like the other three.

        PRD: "All four withdrawals behave identically: `state` and `resolution`
        both become `WITHDRAWN` and `resolved_at` is set to the logical clock."

        Design: Corner/state_machines/withdrawn_complaint_accepts_no_further_trigger
        """
        env = reference_environment
        complaint = file_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=SERVICE_OBSERVED_DATE,
            headers=env.subscriber_headers,
            allegation_type=AllegationType.RELIABILITY_OUTAGE.value,
            affected_days=9,
            narrative="Repeated evening outages",
        )
        triage_complaint(complaint["id"])

        response = api_client.withdraw_complaint(
            complaint["id"],
            build_withdraw_complaint_payload(
                withdraw_reason="Service restored, dropping the complaint"
            ),
            env.subscriber_headers,
        )

        withdrawn = validate_success(response)
        assert withdrawn["state"] == ComplaintState.WITHDRAWN.value
        assert withdrawn["resolution"] == ComplaintResolution.WITHDRAWN.value
        assert withdrawn["resolved_at"] == REFERENCE_STAMP, (
            "resolved_at is taken from the logical clock"
        )

    @pytest.mark.parametrize(
        "trigger", ["investigate", "resolve", "reopen", "withdraw_again"]
    )
    def test_withdrawn_complaint_refuses_every_further_trigger(
        self, reference_environment, trigger
    ):
        """Nothing moves a withdrawn complaint.

        PRD: "`UPHELD` and `WITHDRAWN` are the complaint's terminal states."

        Design: Corner/state_machines/withdrawn_complaint_accepts_no_further_trigger
        """
        env = reference_environment
        complaint = file_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=SERVICE_OBSERVED_DATE,
            headers=env.subscriber_headers,
            allegation_type=AllegationType.RELIABILITY_OUTAGE.value,
            affected_days=9,
        )
        triage_complaint(complaint["id"])
        api_client.withdraw_complaint(
            complaint["id"],
            build_withdraw_complaint_payload(),
            env.subscriber_headers,
        )

        if trigger == "investigate":
            response = api_client.investigate_complaint(
                complaint["id"], COMPLAINT_ANALYST_HEADERS
            )
        elif trigger == "resolve":
            response = api_client.resolve_complaint(
                complaint["id"],
                build_uphold_payload(
                    credit_basis=CreditBasis.FLAT_SEVERITY_TIER.value,
                    resolution_note="Too late",
                ),
                COMPLAINT_ANALYST_HEADERS,
            )
        elif trigger == "reopen":
            response = api_client.reopen_complaint(
                complaint["id"],
                build_reopen_payload(reopen_reason="Consumer changed their mind"),
                COMPLAINT_ANALYST_HEADERS,
            )
        else:
            response = api_client.withdraw_complaint(
                complaint["id"],
                build_withdraw_complaint_payload(withdraw_reason="Withdraw again"),
                env.subscriber_headers,
            )

        validate_error(response, ApiErrorId.ERR_COMPLAINT_INVALID_STATE.value)
        reread = read_complaint(complaint["id"])
        assert reread["state"] == ComplaintState.WITHDRAWN.value, (
            "the complaint stays WITHDRAWN"
        )
        assert reread["resolution"] == ComplaintResolution.WITHDRAWN.value

    def test_a_withdrawal_issues_no_credit_and_is_not_an_upheld_finding(
        self, reference_environment
    ):
        """A withdrawal leaves the ledger and the plan's tally at zero.

        PRD: "`ServicePlan.upheld_complaint_count` is the count of complaints
        whose account is subscribed to that plan and whose `state` is
        `UPHELD`."

        Design: Corner/state_machines/withdrawn_complaint_accepts_no_further_trigger
        """
        env = reference_environment
        complaint = file_complaint(
            env.account_id,
            env.label_id,
            service_observed_date=SERVICE_OBSERVED_DATE,
            headers=env.subscriber_headers,
            allegation_type=AllegationType.RELIABILITY_OUTAGE.value,
            affected_days=9,
        )
        triage_complaint(complaint["id"])

        response = api_client.withdraw_complaint(
            complaint["id"],
            build_withdraw_complaint_payload(),
            env.subscriber_headers,
        )

        validate_success(response)
        credits_response = api_client.list_complaint_remediation_credits(
            complaint["id"], COMPLIANCE_OFFICER_HEADERS
        )
        credits, meta = validate_paginated(credits_response)
        assert meta["total_count"] == 0, "a withdrawal creates no remediation credit"
        assert credits == [], "no credit row exists for a withdrawn complaint"
        assert_account_ledger(read_subscriber_account(env.account_id), 0, 0)
        assert read_service_plan(env.plan_id)["upheld_complaint_count"] == 0, (
            "a withdrawal is not an upheld finding"
        )


class TestLabelAttestationAndTranslationWrongStateTriggersRejected:
    """Wrong-from-state triggers on the label-side machines."""

    def test_publishing_an_already_published_label_is_refused(
        self, reference_environment
    ):
        """Publication requires a draft, whoever the acting officer is.

        PRD: "The label's `publication_state` must be `DRAFT`, or the request
        answers `ERR_LABEL_INVALID_STATE`."

        Design: Corner/state_machines/label_attestation_and_translation_wrong_state_triggers_rejected
        """
        env = reference_environment

        response = api_client.publish_label_version(
            env.label_id, THIRD_OFFICER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_LABEL_INVALID_STATE.value)
        reread = read_label(env.label_id)
        assert reread["publication_state"] == PublicationState.PUBLISHED.value, (
            "the label stays PUBLISHED"
        )
        assert reread["published_by_user_id"] == "co-2", (
            "the original publisher is not overwritten"
        )
        assert reread["published_at"] == REFERENCE_STAMP, (
            "published_at is not restamped"
        )

    def test_certifying_an_already_certified_attestation_is_refused(
        self, reference_environment
    ):
        """Only a draft attestation may be certified.

        PRD: "It requires that the attestation still be `DRAFT`, or the request
        answers `ERR_ATTESTATION_INVALID_STATE`; that `pooled_sample_count` be
        at least the pinned `min_samples_required`, with an inclusive boundary,
        or the request answers `ERR_INSUFFICIENT_SAMPLES`; and that both
        `download_margin_pct` and `upload_margin_pct` be at least 0.80 — again
        an inclusive boundary, so exactly 0.8000 passes — or the request
        answers `ERR_SUBSTANTIATION_MARGIN_NOT_MET`."

        Design: Corner/state_machines/label_attestation_and_translation_wrong_state_triggers_rejected
        """
        env = reference_environment
        set_clock(DAY_AFTER_REFERENCE_NOW)

        response = api_client.certify_performance_attestation(
            env.attestation_id, COMPLIANCE_OFFICER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_ATTESTATION_INVALID_STATE.value)
        reread = env.reload_attestation()
        assert reread["status"] == AttestationStatus.CERTIFIED.value, (
            "the attestation stays CERTIFIED"
        )
        assert reread["certified_at"] == REFERENCE_STAMP, (
            "certified_at is not restamped to the advanced clock"
        )

    def test_verifying_an_already_verified_translation_is_refused(self):
        """Verification is a draft-translation edge only.

        PRD: "The translation must still be `DRAFT`, or the request answers
        `ERR_TRANSLATION_INVALID_STATE`; the parent label's
        `publication_state` must still be `DRAFT`, or it answers
        `ERR_LABEL_INVALID_STATE`, because translations are settled before the
        disclosure goes live and not after; and the verifying `X-User-ID` must
        differ from the translation's `created_by_user_id`, or it answers
        `ERR_SOD_SELF_REVIEW`."

        Design: Corner/state_machines/label_attestation_and_translation_wrong_state_triggers_rejected
        """
        set_clock(REFERENCE_NOW)
        plan = create_reference_plan()
        label = draft_label(plan["id"])
        verified = add_verified_translation(label["id"], locale="en-US")

        response = api_client.verify_label_translation(
            label["id"], verified["id"], THIRD_SPECIALIST_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_TRANSLATION_INVALID_STATE.value)
        translations, _ = validate_paginated(
            api_client.list_label_translations(label["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        again = next(row for row in translations if row["id"] == verified["id"])
        assert again["status"] == TranslationStatus.VERIFIED.value
        assert again["verified_by_user_id"] == "loc-2", (
            "the original verifier is not overwritten"
        )
        assert read_label(label["id"])["verified_locale_count"] == 1, (
            "the refused verify did not increment the verified locale count"
        )

    def test_verifying_a_translation_under_a_published_label_is_refused(
        self, reference_environment
    ):
        """A translation left unverified at publication can never be verified.

        PRD: "The parent label's `publication_state` must still be `DRAFT`:
        translations may neither be added to nor verified under a label that
        has already been published, archived or withdrawn, and an attempt
        answers `ERR_LABEL_INVALID_STATE`."

        Design: Corner/state_machines/label_attestation_and_translation_wrong_state_triggers_rejected
        """
        env = reference_environment
        successor = draft_label(env.plan_id, effective_from=SUCCESSOR_EFFECTIVE_FROM)
        add_verified_translation(successor["id"], locale="en-US")
        spanish = add_translation(
            successor["id"],
            locale="es-MX",
            translated_summary="Etiqueta en espanol agregada antes de la publicacion",
        )
        validate_success(
            api_client.publish_label_version(
                successor["id"], COMPLIANCE_OFFICER_2_HEADERS
            )
        )

        response = api_client.verify_label_translation(
            successor["id"], spanish["id"], LOCALIZATION_SPECIALIST_2_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_LABEL_INVALID_STATE.value)
        translations, _ = validate_paginated(
            api_client.list_label_translations(
                successor["id"], COMPLIANCE_OFFICER_HEADERS
            )
        )
        spanish_again = next(row for row in translations if row["id"] == spanish["id"])
        assert spanish_again["status"] == TranslationStatus.DRAFT.value, (
            "the Spanish translation is still unverified"
        )
        assert read_label(successor["id"])["verified_locale_count"] == 1, (
            "only the English locale counts as verified"
        )

    def test_withdrawing_a_draft_label_is_refused(self, reference_environment):
        """Withdrawal has no draft source state.

        PRD: "The label's `publication_state` must be `PUBLISHED`, or the
        request answers `ERR_LABEL_INVALID_STATE`."

        Design: Corner/state_machines/label_attestation_and_translation_wrong_state_triggers_rejected
        """
        env = reference_environment
        draft = draft_label(env.plan_id, effective_from=SUCCESSOR_EFFECTIVE_FROM)

        response = api_client.withdraw_label_version(
            draft["id"],
            build_withdraw_label_payload(reason="Withdraw a draft"),
            COMPLIANCE_OFFICER_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_LABEL_INVALID_STATE.value)
        reread = read_label(draft["id"])
        assert reread["publication_state"] == PublicationState.DRAFT.value, (
            "the draft is untouched"
        )
        assert reread["withdrawn_at"] is None, "nothing was withdrawn"


class TestPublishingASuccessorArchivesThePredecessor:
    """Publication fires the archival side effect in the same request."""

    def test_publishing_version_two_archives_version_one(self, reference_environment):
        """The predecessor is archived and its open window truncated.

        PRD: "It archives the plan's previous published label: that
        predecessor's `publication_state` becomes `ARCHIVED`, its `archived_at`
        is set to the logical clock, and its `effective_until` is truncated to
        the new label's `effective_from` when it was previously null or later
        than that instant."

        Design: Corner/state_machines/publishing_a_successor_archives_the_predecessor
        """
        env = reference_environment
        successor = draft_label(env.plan_id, effective_from=SUCCESSOR_EFFECTIVE_FROM)
        add_verified_translation(successor["id"], locale="en-US")

        response = api_client.publish_label_version(
            successor["id"], COMPLIANCE_OFFICER_2_HEADERS
        )

        published = validate_success(response)
        assert_label_dimensions(
            published,
            PublicationState.PUBLISHED.value,
            SubstantiationStatus.SUBSTANTIATED.value,
        )
        assert published["version_seq"] == 2, "the successor is version_seq 2"
        assert published["attestation_id"] == env.attestation_id, (
            "the same certified attestation is pinned again"
        )
        assert float(published["typical_download_mbps"]) == pytest.approx(
            PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD, abs=0.01
        )

        predecessor = read_label(env.label_id)
        assert predecessor["publication_state"] == PublicationState.ARCHIVED.value
        assert predecessor["archived_at"] == REFERENCE_STAMP, (
            "archived_at is taken from the logical clock"
        )
        _assert_same_instant(
            predecessor["effective_until"],
            SUCCESSOR_EFFECTIVE_FROM,
            "effective_until",
        )
        _assert_same_instant(
            predecessor["effective_from"], REFERENCE_NOW, "effective_from"
        )
        assert predecessor["monthly_total_intro_cents"] == INTRO_GROSS_CENTS
        assert predecessor["net_monthly_intro_cents"] == INTRO_NET_CENTS
        assert predecessor["monthly_total_post_promo_cents"] == POST_PROMO_GROSS_CENTS
        assert predecessor["net_monthly_post_promo_cents"] == POST_PROMO_NET_CENTS

        plan = read_service_plan(env.plan_id)
        assert plan["active_label_version_id"] == successor["id"], (
            "the plan's active label pointer moves to the successor"
        )
        assert_posture(plan, LabelPosture.OPEN.value)
        validate_success(
            api_client.get_label_version(env.label_id, COMPLIANCE_OFFICER_HEADERS)
        )

    def test_the_archived_label_keeps_the_disclosure_it_served(
        self, reference_environment
    ):
        """Archival is not deletion: the disclosure history survives it.

        PRD: "Disclosures already recorded against the archived label stay
        readable and keep their `disclosed_label_version_seq`."

        Design: Corner/state_machines/publishing_a_successor_archives_the_predecessor
        """
        env = reference_environment
        disclosure = record_disclosure(env.account_id)
        successor = draft_label(env.plan_id, effective_from=SUCCESSOR_EFFECTIVE_FROM)
        add_verified_translation(successor["id"], locale="en-US")

        response = api_client.publish_label_version(
            successor["id"], COMPLIANCE_OFFICER_2_HEADERS
        )

        validate_success(response)
        rows, _ = validate_paginated(
            api_client.list_label_version_disclosures(
                env.label_id, COMPLIANCE_OFFICER_HEADERS
            )
        )
        retained = next(row for row in rows if row["id"] == disclosure["id"])
        assert retained["label_version_id"] == env.label_id, (
            "the disclosure still points at the archived label"
        )
        assert retained["disclosed_label_version_seq"] == 1, (
            "the disclosure keeps the sequence number it was served"
        )
        assert retained["disclosed_net_monthly_cents"] == INTRO_NET_CENTS, (
            "the introductory net charge the consumer actually saw"
        )


class TestWithdrawingAPublishedLabelRestoresItsArchivedPredecessor:
    """Withdrawal undoes the archival side effect with no drift."""

    def test_withdrawal_restores_the_predecessor_and_its_open_window(
        self, reference_environment
    ):
        """The predecessor returns to published with its window un-truncated.

        PRD: "Withdrawal sets `publication_state` to `WITHDRAWN` and
        `withdrawn_at` to the logical clock, then restores the predecessor it
        displaced: among the same plan's labels whose `publication_state` is
        `ARCHIVED`, ranked by `version_seq` descending with `created_at`
        ascending as the tie-break, the first one is returned to
        `publication_state` `PUBLISHED`, its `archived_at` is cleared, and its
        `effective_until` is restored to the value it held before publication
        truncated it."

        Design: Corner/state_machines/withdrawing_a_published_label_restores_its_archived_predecessor
        """
        env = reference_environment
        successor = create_published_label(
            env.plan_id, effective_from=SUCCESSOR_EFFECTIVE_FROM
        )

        response = api_client.withdraw_label_version(
            successor["id"],
            build_withdraw_label_payload(
                reason="Successor published with the wrong effective date"
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )

        withdrawn = validate_success(response)
        assert withdrawn["publication_state"] == PublicationState.WITHDRAWN.value
        assert withdrawn["withdrawn_at"] == REFERENCE_STAMP, (
            "withdrawn_at is taken from the logical clock"
        )

        restored = read_label(env.label_id)
        assert restored["publication_state"] == PublicationState.PUBLISHED.value, (
            "the predecessor is published again"
        )
        assert restored["archived_at"] is None, "archived_at is cleared"
        assert restored["effective_until"] is None, (
            "effective_until is restored to the open-ended value it held before"
        )
        assert_label_dimensions(
            restored,
            PublicationState.PUBLISHED.value,
            SubstantiationStatus.SUBSTANTIATED.value,
        )
        assert restored["attestation_id"] == env.attestation_id, (
            "the pinned attestation is untouched by the round trip"
        )

        plan = read_service_plan(env.plan_id)
        assert plan["active_label_version_id"] == env.label_id, (
            "the plan pointer follows the restored label back"
        )
        assert plan["price_disclosure_drift"] is False
        assert_posture(plan, LabelPosture.OPEN.value)

    def test_withdrawing_the_last_label_leaves_the_plan_without_one(
        self, reference_environment
    ):
        """With no archived predecessor there is nothing to restore.

        PRD: "The plan's `active_label_version_id` is then set to the restored
        label's `id`, or to null when there was nothing to restore, the plan's
        posture is recomputed, and the plan's `version` is incremented."

        Design: Corner/state_machines/withdrawing_a_published_label_restores_its_archived_predecessor
        """
        env = reference_environment
        successor = create_published_label(
            env.plan_id, effective_from=SUCCESSOR_EFFECTIVE_FROM
        )
        validate_success(
            api_client.withdraw_label_version(
                successor["id"],
                build_withdraw_label_payload(),
                COMPLIANCE_OFFICER_HEADERS,
            )
        )

        response = api_client.withdraw_label_version(
            env.label_id,
            build_withdraw_label_payload(reason="No successor left to display"),
            COMPLIANCE_OFFICER_HEADERS,
        )

        withdrawn = validate_success(response)
        assert withdrawn["publication_state"] == PublicationState.WITHDRAWN.value
        plan = read_service_plan(env.plan_id)
        assert plan["active_label_version_id"] is None, (
            "no archived predecessor remained to restore"
        )
        assert_posture(plan, LabelPosture.RESTRICTED.value)


class TestNoticeEffectMovesTheAccountAndRecomputesThePhase:
    """One notice drives the notice machine and the account machine."""

    def test_notice_creation_records_the_period_and_the_disclosed_net(
        self, reference_environment
    ):
        """The notice denormalises the plan being left and the disclosed net.

        PRD: "Creating the notice records `notice_days` as the whole number of
        days between the logical clock at creation and the `effective_date` —
        the span in seconds divided by 86,400 and rounded down — copies the
        account's current `plan_id` into `source_plan_id` as a denormalised
        record of the plan being left (never client-supplied), and takes
        `disclosed_net_monthly_cents` from the target plan's published label,
        specifically that label's `net_monthly_post_promo_cents`."

        Design: Corner/state_machines/notice_effect_moves_the_account_and_recomputes_the_phase
        """
        env = reference_environment

        response = api_client.create_plan_change_notice(
            build_plan_change_notice_payload(
                env.account_id,
                env.plan_id,
                SUCCESSOR_EFFECTIVE_FROM,
                notice_type=NoticeType.PRICE_INCREASE.value,
                reason="Promotional period ends",
            ),
            RETAIL_AGENT_HEADERS,
        )

        notice = validate_success(response, expected_status=201)
        assert notice["state"] == NoticeState.SENT.value, "the notice opens in SENT"
        assert notice["notice_days"] == 30, "thirty whole days to the effective date"
        assert notice["source_plan_id"] == env.plan_id, (
            "source_plan_id records the plan being left"
        )
        assert notice["disclosed_net_monthly_cents"] == POST_PROMO_NET_CENTS, (
            "the target plan's published label net_monthly_post_promo_cents"
        )
        assert notice["acknowledged_at"] is None
        assert notice["effected_at"] is None

    def test_notice_creation_moves_the_account_to_pending_change(
        self, reference_environment
    ):
        """Creating the notice flips the account's own machine.

        PRD: "It also moves the account from `ACTIVE` to `PENDING_CHANGE` and
        increments the account's `version`."

        Design: Corner/state_machines/notice_effect_moves_the_account_and_recomputes_the_phase
        """
        env = reference_environment
        before = read_subscriber_account(env.account_id)
        assert before["subscription_state"] == SubscriptionState.ACTIVE.value

        response = api_client.create_plan_change_notice(
            build_plan_change_notice_payload(
                env.account_id,
                env.plan_id,
                SUCCESSOR_EFFECTIVE_FROM,
                notice_type=NoticeType.PRICE_INCREASE.value,
                reason="Promotional period ends",
            ),
            RETAIL_AGENT_HEADERS,
        )

        validate_success(response, expected_status=201)
        after = read_subscriber_account(env.account_id)
        assert after["subscription_state"] == SubscriptionState.PENDING_CHANGE.value, (
            "the account is in a pending-change posture"
        )
        assert after["version"] > before["version"], (
            "moving the account increments its version"
        )

    def test_notice_discloses_the_prorated_etf_of_the_plan_being_left(
        self, reference_environment
    ):
        """No introductory month has elapsed, so the whole fee is disclosed.

        PRD: "Under `PRORATED_MONTHLY` it decays with the introductory term:
        take the whole number of thirty-day months elapsed between the
        account's `service_start_date` and the logical clock (the elapsed
        seconds divided by 2,592,000, rounded down), subtract that from the
        source plan's `intro_term_months` and treat any negative result as zero
        to obtain the remaining months, then multiply the source plan's
        `early_termination_fee_cents` by those remaining months, divide by the
        source plan's `intro_term_months` — or by 1 when that term is 0 — and
        round half up to a whole number of cents."

        Design: Corner/state_machines/notice_effect_moves_the_account_and_recomputes_the_phase
        """
        env = reference_environment

        response = api_client.create_plan_change_notice(
            build_plan_change_notice_payload(
                env.account_id,
                env.plan_id,
                SUCCESSOR_EFFECTIVE_FROM,
                notice_type=NoticeType.PRICE_INCREASE.value,
                reason="Promotional period ends",
            ),
            RETAIL_AGENT_HEADERS,
        )

        notice = validate_success(response, expected_status=201)
        assert notice["etf_disclosed_cents"] == ETF_DISCLOSED_CENTS, (
            "six remaining introductory months out of six leave the fee whole"
        )

    def test_subscriber_acknowledgement_stamps_the_notice(self, reference_environment):
        """Acknowledgement is the account holder's act from `SENT`.

        PRD: "Only the `Subscriber` who owns the account may acknowledge, and
        only from `SENT`; an attempt from any other state answers
        `ERR_NOTICE_INVALID_STATE`, and an attempt by a subscriber whose
        `X-User-ID` does not equal the notice's `account_id` answers
        `ERR_ACCOUNT_SCOPE_VIOLATION`."

        Design: Corner/state_machines/notice_effect_moves_the_account_and_recomputes_the_phase
        """
        env = reference_environment
        notice = create_plan_change_notice(
            env.account_id,
            env.plan_id,
            SUCCESSOR_EFFECTIVE_FROM,
            notice_type=NoticeType.PRICE_INCREASE.value,
            reason="Promotional period ends",
        )

        response = api_client.acknowledge_plan_change_notice(
            notice["id"], make_subscriber_headers(env.account_id)
        )

        acknowledged = validate_success(response)
        assert acknowledged["state"] == NoticeState.ACKNOWLEDGED.value
        assert acknowledged["acknowledged_at"] == REFERENCE_STAMP, (
            "acknowledged_at is taken from the logical clock"
        )

    def test_effecting_a_notice_waits_for_its_effective_date(
        self, reference_environment
    ):
        """The effect edge is gated on the clock reaching the effective date.

        PRD: "Effecting the notice is a `RetailAgent`'s act; the notice must be
        `ACKNOWLEDGED`, or the request answers `ERR_NOTICE_INVALID_STATE`, and
        the logical clock must have reached the `effective_date`, or it answers
        `ERR_NOTICE_NOT_DUE`."

        Design: Corner/state_machines/notice_effect_moves_the_account_and_recomputes_the_phase
        """
        env = reference_environment
        notice = create_plan_change_notice(
            env.account_id,
            env.plan_id,
            SUCCESSOR_EFFECTIVE_FROM,
            notice_type=NoticeType.PRICE_INCREASE.value,
            reason="Promotional period ends",
        )
        api_client.acknowledge_plan_change_notice(
            notice["id"], make_subscriber_headers(env.account_id)
        )

        too_early = api_client.effect_plan_change_notice(
            notice["id"], RETAIL_AGENT_HEADERS
        )
        validate_error(too_early, ApiErrorId.ERR_NOTICE_NOT_DUE.value)
        assert (
            read_plan_change_notice(notice["id"])["state"]
            == NoticeState.ACKNOWLEDGED.value
        ), "the refused effect left the notice ACKNOWLEDGED"

        set_clock(SUCCESSOR_EFFECTIVE_FROM)
        due = api_client.effect_plan_change_notice(notice["id"], RETAIL_AGENT_HEADERS)

        effected = validate_success(due)
        assert effected["state"] == NoticeState.EFFECTED.value
        assert effected["effected_at"] == SUCCESSOR_STAMP, (
            "effected_at is taken from the advanced logical clock"
        )

    def test_effecting_returns_the_account_to_active_and_recomputes_the_phase(
        self, reference_environment
    ):
        """A price-increase notice leaves the account on the same plan.

        PRD: "Effecting sets `state` to `EFFECTED` and `effected_at` to the
        logical clock; on a `PLAN_CHANGE` notice it moves the account's
        `plan_id` to the notice's `target_plan_id`; it returns the account's
        `subscription_state` from `PENDING_CHANGE` to `ACTIVE`; and it
        recomputes the account's `pricing_phase` against whichever plan the
        account now holds."

        Design: Corner/state_machines/notice_effect_moves_the_account_and_recomputes_the_phase
        """
        env = reference_environment
        notice = create_plan_change_notice(
            env.account_id,
            env.plan_id,
            SUCCESSOR_EFFECTIVE_FROM,
            notice_type=NoticeType.PRICE_INCREASE.value,
            reason="Promotional period ends",
        )
        api_client.acknowledge_plan_change_notice(
            notice["id"], make_subscriber_headers(env.account_id)
        )
        set_clock(SUCCESSOR_EFFECTIVE_FROM)

        response = api_client.effect_plan_change_notice(
            notice["id"], RETAIL_AGENT_HEADERS
        )

        validate_success(response)
        account = read_subscriber_account(env.account_id)
        assert account["subscription_state"] == SubscriptionState.ACTIVE.value, (
            "the account returns to ACTIVE"
        )
        assert account["plan_id"] == env.plan_id, (
            "a PRICE_INCREASE notice does not move the account to target_plan_id"
        )
        assert account["pricing_phase"] == PricingPhase.INTRO.value, (
            "one elapsed thirty-day month is still below the six-month term"
        )

    def test_acknowledging_an_effected_notice_is_refused(self, reference_environment):
        """`EFFECTED` is terminal for the notice machine.

        PRD: "The notice then walks `SENT → ACKNOWLEDGED → EFFECTED`, with
        `EFFECTED` terminal."

        Design: Corner/state_machines/notice_effect_moves_the_account_and_recomputes_the_phase
        """
        env = reference_environment
        notice = create_plan_change_notice(
            env.account_id,
            env.plan_id,
            SUCCESSOR_EFFECTIVE_FROM,
            notice_type=NoticeType.PRICE_INCREASE.value,
            reason="Promotional period ends",
        )
        api_client.acknowledge_plan_change_notice(
            notice["id"], make_subscriber_headers(env.account_id)
        )
        set_clock(SUCCESSOR_EFFECTIVE_FROM)
        api_client.effect_plan_change_notice(notice["id"], RETAIL_AGENT_HEADERS)

        response = api_client.acknowledge_plan_change_notice(
            notice["id"], make_subscriber_headers(env.account_id)
        )

        validate_error(response, ApiErrorId.ERR_NOTICE_INVALID_STATE.value)
        reread = read_plan_change_notice(notice["id"])
        assert reread["state"] == NoticeState.EFFECTED.value, (
            "the notice stays EFFECTED"
        )
        assert reread["effected_at"] == SUCCESSOR_STAMP, (
            "the refused acknowledgement changed nothing"
        )
