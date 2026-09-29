"""Rejection conditions on the authentication, filing, publication and notice paths."""

from typing import Any, Dict

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, api_client
from test_helpers.assertions import (
    assert_label_dimensions,
    assert_posture,
    itemization_amount,
    itemized_fee_codes,
)
from test_helpers.constants import REFERENCE_NOW
from test_helpers.factories import (
    build_fixed_fee_payload,
    build_service_plan_payload,
)
from test_helpers.fixtures import (
    ReferenceEnvironment,
    acknowledge_notice,
    add_fee_line,
    add_verified_translation,
    create_certified_attestation,
    create_measurement_probe,
    create_plan_change_notice,
    create_published_methodology,
    create_regulator_inquiry,
    draft_label,
    file_complaint,
    invalidate_test_run,
    read_label,
    read_regulator_inquiry,
    read_service_plan,
    read_subscriber_account,
    record_test_run,
    set_clock,
)
from test_helpers.test_users import (
    COMPLAINT_ANALYST_HEADERS,
    COMPLIANCE_OFFICER_2_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    REGULATORY_LIAISON_HEADERS,
    RETAIL_AGENT_HEADERS,
)
from test_helpers.types import (
    ComplaintState,
    FeeAppliesDuring,
    FilingType,
    ItemizationPhase,
    LabelPosture,
    NoticeState,
    NoticeType,
    PublicationState,
    RegulatorInquiryState,
    SubscriptionState,
    SubstantiationStatus,
    UserRole,
)

# ---------------------------------------------------------------------------
# Deliberately malformed header dictionaries.
#
# Every well-formed request carries both `X-User-ID` and `X-User-Role`; these
# omit one of them, or declare a capacity outside the seven recognised roles.
# ---------------------------------------------------------------------------

HEADERS_WITHOUT_USER_ID: Dict[str, str] = {
    "X-User-Role": UserRole.COMPLIANCE_OFFICER.value,
    "Content-Type": "application/json",
}
HEADERS_WITHOUT_USER_ROLE: Dict[str, str] = {
    "X-User-ID": "co-1",
    "Content-Type": "application/json",
}
HEADERS_WITH_UNRECOGNISED_ROLE: Dict[str, str] = {
    "X-User-ID": "aud-1",
    "X-User-Role": "Auditor",
    "Content-Type": "application/json",
}
HEADERS_WITHOUT_USER_ID_AND_UNRECOGNISED_ROLE: Dict[str, str] = {
    "X-User-Role": "Auditor",
    "Content-Type": "application/json",
}


# ---------------------------------------------------------------------------
# Setup chains unique to this module.
# ---------------------------------------------------------------------------


def _open_docket_over(environment: ReferenceEnvironment) -> Dict[str, Any]:
    """A complaint in `INTAKE` disputing the published label, and a docket in
    `RECEIVED` against that complaint."""
    complaint = file_complaint(
        environment.account_id,
        environment.label_id,
        service_observed_date="2026-09-02T12:00:00Z",
        narrative="Evening download far below the label",
    )
    inquiry = create_regulator_inquiry(complaint["id"])
    return {"complaint": complaint, "inquiry": inquiry}


def _create_plan_without_intro_price() -> Dict[str, Any]:
    """A plan whose introductory price is absent, so it has no introductory
    phase for an `INTRO_ONLY` fee line to be itemised under."""
    payload = build_service_plan_payload(
        display_name="Fiber 300 no promotion",
        monthly_price_cents=7999,
        early_termination_fee_cents=0,
        required_locales=["en-US"],
        discount_program_eligible=False,
    )
    for omitted in (
        "intro_price_cents",
        "intro_term_months",
        "data_allowance_gb",
        "overage_rate_cents_per_gb",
        "etf_proration_policy",
    ):
        payload.pop(omitted, None)
    return get_success_data(
        api_client.create_service_plan(payload, COMPLIANCE_OFFICER_HEADERS)
    )


def _build_intro_only_fee_world() -> Dict[str, Any]:
    """A measured, translated draft label on a plan carrying one `INTRO_ONLY`
    monthly recurring fee and no introductory price."""
    set_clock(REFERENCE_NOW)

    plan = _create_plan_without_intro_price()
    add_fee_line(
        plan["id"],
        build_fixed_fee_payload(
            "PROMO_EQUIP",
            1000,
            applies_during=FeeAppliesDuring.INTRO_ONLY.value,
            description="Promotional equipment rental",
        ),
    )

    methodology = create_published_methodology()
    probe = create_measurement_probe(market_code="US-TX-DAL", max_concurrent_windows=1)
    record_test_run(probe["id"], plan["id"], methodology["id"])
    create_certified_attestation(plan["id"], methodology["id"])

    label = draft_label(plan["id"], effective_from=REFERENCE_NOW)
    add_verified_translation(label["id"], locale="en-US")

    return {"plan": read_service_plan(plan["id"]), "label": read_label(label["id"])}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "malformed_headers",
    [
        pytest.param(HEADERS_WITHOUT_USER_ID, id="no_x_user_id"),
        pytest.param(HEADERS_WITHOUT_USER_ROLE, id="no_x_user_role"),
        pytest.param(HEADERS_WITH_UNRECOGNISED_ROLE, id="unrecognised_role"),
    ],
)
def test_malformed_auth_headers_are_rejected_before_the_plan_is_created(
    api, clock, malformed_headers
):
    """Neither an absent header nor an unrecognised capacity may open a plan.

    PRD: "A request missing either header, or naming a role that is not one of
    the seven recognised roles, is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/missing_or_unrecognised_auth_headers_return_unauthenticated
    """
    clock(REFERENCE_NOW)
    payload = build_service_plan_payload(
        display_name="No auth plan",
        advertised_download_mbps=100,
        advertised_upload_mbps=50,
        monthly_price_cents=5000,
        early_termination_fee_cents=0,
        required_locales=["en-US"],
    )

    rejected = api.create_service_plan(payload, malformed_headers)
    validate_error(rejected, ApiErrorId.ERR_UNAUTHENTICATED.value)

    # The rejected request persisted nothing: the same globally unique
    # `plan_code` is still free for a properly authenticated officer.
    accepted = api.create_service_plan(payload, COMPLIANCE_OFFICER_HEADERS)
    created = validate_success(accepted, expected_status=201)
    assert created["plan_code"] == payload["plan_code"], (
        "the properly authenticated create should own the plan_code the "
        "unauthenticated attempt failed to claim"
    )


def test_authentication_outranks_existence_authorisation_and_request_shape(
    api, reference_environment: ReferenceEnvironment
):
    """A 401 surfaces even where a 404, a 403 and a 400 also apply.

    PRD: "When several rules could reject the same request, the system evaluates
    them in the fixed order below and returns the first failure it finds."

    Design: Corner/errors/missing_or_unrecognised_auth_headers_return_unauthenticated
    """
    version_before = read_service_plan(reference_environment.plan_id)["version"]

    # A read of a plan that does not exist: authentication precedes existence.
    validate_error(
        api.get_service_plan(NON_EXISTENT_UUID, HEADERS_WITH_UNRECOGNISED_ROLE),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    # An amendment that is also unauthorised, malformed and aimed at a
    # nonexistent plan: authentication precedes all three.
    validate_error(
        api.amend_service_plan(
            NON_EXISTENT_UUID,
            {"change_justification": ""},
            HEADERS_WITHOUT_USER_ID_AND_UNRECOGNISED_ROLE,
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    # A properly authenticated caller is unaffected by the rejections.
    plan_after = validate_success(
        api.get_service_plan(reference_environment.plan_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert plan_after["version"] == version_before, (
        "the rejected requests must not have mutated the plan"
    )


# ---------------------------------------------------------------------------
# Regulator filings on a label that lost its substantiation
# ---------------------------------------------------------------------------


class TestTechnicalPacketOnUnsubstantiatedLabel:
    """The docket deadlocks once the run behind the disputed label is withdrawn."""

    def test_technical_packet_refused_after_the_disputed_label_loses_substantiation(
        self, api, reference_environment: ReferenceEnvironment
    ):
        """Withdrawing the run leaves the docket with no fileable technical branch.

        PRD: "A `TECHNICAL_PACKET` filing may only be made when the label
        disputed by the docket's complaint still stands up technically: its
        `attestation_id` must be non-null *and* its `substantiation_status` must
        be `SUBSTANTIATED`, or the filing is rejected with
        `ERR_LABEL_NOT_SUBSTANTIATED_FOR_FILING`."

        Design: Corner/errors/technical_packet_filing_on_an_unsubstantiated_label_rejected
        """
        docket = _open_docket_over(reference_environment)
        inquiry_id = docket["inquiry"]["id"]

        invalidate_test_run(
            reference_environment.run_id,
            reason="Panel calibration fault found after the fact",
        )

        label = read_label(reference_environment.label_id)
        assert_label_dimensions(
            label,
            PublicationState.PUBLISHED.value,
            SubstantiationStatus.UNSUBSTANTIATED.value,
        )
        assert_posture(
            read_service_plan(reference_environment.plan_id),
            LabelPosture.FROZEN.value,
        )

        rejected = api.file_inquiry_filing(
            inquiry_id,
            {
                "filing_type": FilingType.TECHNICAL_PACKET.value,
                "evidence_ref": "EV-2026-0300-A",
                "summary": "Speed test evidence packet",
            },
            REGULATORY_LIAISON_HEADERS,
        )
        validate_error(
            rejected, ApiErrorId.ERR_LABEL_NOT_SUBSTANTIATED_FOR_FILING.value
        )

        inquiry = read_regulator_inquiry(inquiry_id)
        assert inquiry["state"] == RegulatorInquiryState.RECEIVED.value, (
            "a refused filing drives no transition"
        )
        assert inquiry["technical_packet_filed_at"] is None, (
            "technical_packet_filed_at stays null when the branch is refused"
        )

    def test_docket_cannot_close_on_the_resolution_report_branch_alone(
        self, api, reference_environment: ReferenceEnvironment
    ):
        """One branch never satisfies the join, so closure stays inadmissible.

        PRD: "Closing the docket carries a `closure_note` and is only admissible
        from `RESPONSE_COMPLETE`; a docket still in `RECEIVED` or
        `EVIDENCE_ASSEMBLY` answers `ERR_INQUIRY_FILINGS_INCOMPLETE`."

        Design: Corner/errors/technical_packet_filing_on_an_unsubstantiated_label_rejected
        """
        docket = _open_docket_over(reference_environment)
        complaint_id = docket["complaint"]["id"]
        inquiry_id = docket["inquiry"]["id"]

        invalidate_test_run(
            reference_environment.run_id,
            reason="Panel calibration fault found after the fact",
        )
        validate_error(
            api.file_inquiry_filing(
                inquiry_id,
                {
                    "filing_type": FilingType.TECHNICAL_PACKET.value,
                    "evidence_ref": "EV-2026-0300-A",
                    "summary": "Speed test evidence packet",
                },
                REGULATORY_LIAISON_HEADERS,
            ),
            ApiErrorId.ERR_LABEL_NOT_SUBSTANTIATED_FOR_FILING.value,
        )

        # Closure from RECEIVED, with neither branch on record.
        validate_error(
            api.close_regulator_inquiry(
                inquiry_id,
                {"closure_note": "Attempting to close without filings"},
                REGULATORY_LIAISON_HEADERS,
            ),
            ApiErrorId.ERR_INQUIRY_FILINGS_INCOMPLETE.value,
        )

        # Carry the complaint to a terminal state so the other branch is fileable.
        get_success_data(
            api.triage_complaint(
                complaint_id,
                {"priority_note": "Proceeding despite the evidence gap"},
                COMPLAINT_ANALYST_HEADERS,
            )
        )
        get_success_data(
            api.investigate_complaint(complaint_id, COMPLAINT_ANALYST_HEADERS)
        )
        dismissed = get_success_data(
            api.resolve_complaint(
                complaint_id,
                {
                    "finding": "DISMISSED",
                    "resolution_note": "No substantiated shortfall on record",
                },
                COMPLAINT_ANALYST_HEADERS,
            )
        )
        assert dismissed["state"] == ComplaintState.DISMISSED.value

        filed = validate_success(
            api.file_inquiry_filing(
                inquiry_id,
                {
                    "filing_type": FilingType.RESOLUTION_REPORT.value,
                    "evidence_ref": "EV-2026-0300-R",
                    "summary": "Resolution report",
                },
                REGULATORY_LIAISON_HEADERS,
            )
        )
        assert filed["state"] == RegulatorInquiryState.EVIDENCE_ASSEMBLY.value, (
            "the first filing to arrive moves the docket out of RECEIVED"
        )
        assert filed["resolution_report_filed_at"] == "2026-09-01T00:00:00.000Z"
        assert filed["technical_packet_filed_at"] is None

        # Closure from EVIDENCE_ASSEMBLY, with the technical branch unreachable.
        validate_error(
            api.close_regulator_inquiry(
                inquiry_id,
                {"closure_note": "Still missing the technical packet"},
                REGULATORY_LIAISON_HEADERS,
            ),
            ApiErrorId.ERR_INQUIRY_FILINGS_INCOMPLETE.value,
        )

        inquiry = read_regulator_inquiry(inquiry_id)
        assert inquiry["state"] == RegulatorInquiryState.EVIDENCE_ASSEMBLY.value
        assert inquiry["filed_late"] is False, (
            "filed_late is only decided at the join the docket never reaches"
        )
        assert inquiry["closed_at"] is None


# ---------------------------------------------------------------------------
# Fee itemisation completeness at publication
# ---------------------------------------------------------------------------


class TestFeeItemizationIncompleteBlocksPublish:
    """An `INTRO_ONLY` recurring fee on a plan with no promotion has no home."""

    def test_publish_refused_while_an_intro_only_fee_is_itemised_nowhere(self, api):
        """The label would silently omit a recurring charge, so it may not go live.

        PRD: "The last of these catches, for example, an `INTRO_ONLY` recurring
        fee on a plan that has no introductory price: the line exists but no
        phase itemises it, so the label would silently omit a recurring charge."

        Design: Corner/errors/fee_itemization_incomplete_blocks_publish
        """
        world = _build_intro_only_fee_world()
        label = world["label"]

        assert label["monthly_total_intro_cents"] is None, (
            "the introductory phase is omitted entirely when intro_price_cents is null"
        )
        assert label["monthly_total_post_promo_cents"] == 7999
        assert "PROMO_EQUIP" not in itemized_fee_codes(label), (
            "an INTRO_ONLY line enters no phase of the itemisation"
        )

        rejected = api.publish_label_version(
            label["id"], COMPLIANCE_OFFICER_2_HEADERS
        )
        validate_error(rejected, ApiErrorId.ERR_FEE_ITEMIZATION_INCOMPLETE.value)

        assert_label_dimensions(
            read_label(label["id"]),
            PublicationState.DRAFT.value,
            SubstantiationStatus.PENDING_EVIDENCE.value,
        )
        assert read_service_plan(world["plan"]["id"])["active_label_version_id"] is None

    def test_plan_amendment_gives_the_intro_only_fee_a_home_and_unblocks_publish(
        self, api
    ):
        """The fix is a plan amendment: it recomputes the draft and publication clears.

        PRD: "Whether or not a price moved, the amendment recomputes the
        itemisation, the discount benefit and both first-year totals for every
        label of the plan whose `publication_state` is `DRAFT`; published,
        archived and withdrawn labels keep the figures pinned on them."

        Design: Corner/errors/fee_itemization_incomplete_blocks_publish
        """
        world = _build_intro_only_fee_world()
        plan_id = world["plan"]["id"]
        label_id = world["label"]["id"]

        validate_error(
            api.publish_label_version(label_id, COMPLIANCE_OFFICER_2_HEADERS),
            ApiErrorId.ERR_FEE_ITEMIZATION_INCOMPLETE.value,
        )

        validate_success(
            api.amend_service_plan(
                plan_id,
                {
                    "change_justification": "Introduce a six-month promotional rate",
                    "intro_price_cents": 4999,
                    "intro_term_months": 6,
                },
                COMPLIANCE_OFFICER_HEADERS,
            )
        )

        recomputed = read_label(label_id)
        assert recomputed["monthly_total_intro_cents"] == 5999
        assert recomputed["net_monthly_intro_cents"] == 5999
        assert recomputed["monthly_total_post_promo_cents"] == 7999
        assert recomputed["first_year_total_promo_weighted_cents"] == 83988
        assert recomputed["first_year_total_post_promo_cents"] == 95988

        published = validate_success(
            api.publish_label_version(label_id, COMPLIANCE_OFFICER_2_HEADERS)
        )
        assert_label_dimensions(
            published,
            PublicationState.PUBLISHED.value,
            SubstantiationStatus.SUBSTANTIATED.value,
        )
        assert (
            itemization_amount(
                published, "PROMO_EQUIP", ItemizationPhase.INTRO.value
            )
            == 1000
        )

        plan = read_service_plan(plan_id)
        assert plan["active_label_version_id"] == label_id
        assert plan["price_disclosure_drift"] is False, (
            "publication clears the drift the amendment raised"
        )
        assert_posture(plan, LabelPosture.OPEN.value)


# ---------------------------------------------------------------------------
# One outstanding notice locks the account
# ---------------------------------------------------------------------------


class TestSecondNoticeWhileChangePending:
    """A second notice is refused until the first one is effected."""

    def test_second_notice_refused_while_the_account_change_is_pending(
        self, api, reference_environment: ReferenceEnvironment
    ):
        """The outstanding notice holds the account out of `ACTIVE`.

        PRD: "The account's `subscription_state` must be `ACTIVE`; an account
        that already has a notice outstanding answers
        `ERR_ACCOUNT_CHANGE_ALREADY_PENDING`."

        Design: Corner/errors/second_notice_while_a_change_is_pending_rejected
        """
        account_id = reference_environment.account_id
        plan_id = reference_environment.plan_id

        first = validate_success(
            api.create_plan_change_notice(
                {
                    "account_id": account_id,
                    "target_plan_id": plan_id,
                    "notice_type": NoticeType.PRICE_INCREASE.value,
                    "effective_date": "2026-10-01T00:00:00Z",
                    "reason": "First notice",
                },
                RETAIL_AGENT_HEADERS,
            ),
            expected_status=201,
        )
        assert first["state"] == NoticeState.SENT.value
        assert (
            read_subscriber_account(account_id)["subscription_state"]
            == SubscriptionState.PENDING_CHANGE.value
        )

        rejected = api.create_plan_change_notice(
            {
                "account_id": account_id,
                "target_plan_id": plan_id,
                "notice_type": NoticeType.PRICE_INCREASE.value,
                "effective_date": "2026-10-15T00:00:00Z",
                "reason": "Second notice while the first is outstanding",
            },
            RETAIL_AGENT_HEADERS,
        )
        validate_error(rejected, ApiErrorId.ERR_ACCOUNT_CHANGE_ALREADY_PENDING.value)

        _, meta = validate_paginated(
            api.list_plan_change_notices(
                RETAIL_AGENT_HEADERS, params={"account_id": account_id}
            )
        )
        assert meta["total_count"] == 1, (
            "the refused notice was never recorded against the account"
        )

    def test_pending_lock_releases_only_through_the_date_gated_effect(
        self, api, reference_environment: ReferenceEnvironment
    ):
        """Effecting needs both the acknowledgement and the effective date.

        PRD: "Effecting the notice is a `RetailAgent`'s act; the notice must be
        `ACKNOWLEDGED`, or the request answers `ERR_NOTICE_INVALID_STATE`, and
        the logical clock must have reached the `effective_date`, or it answers
        `ERR_NOTICE_NOT_DUE`."

        Design: Corner/errors/second_notice_while_a_change_is_pending_rejected
        """
        account_id = reference_environment.account_id
        plan_id = reference_environment.plan_id

        notice = create_plan_change_notice(
            account_id,
            plan_id,
            "2026-10-01T00:00:00Z",
            notice_type=NoticeType.PRICE_INCREASE.value,
            reason="First notice",
        )

        # From SENT the state precondition fails before the due-date check.
        validate_error(
            api.effect_plan_change_notice(notice["id"], RETAIL_AGENT_HEADERS),
            ApiErrorId.ERR_NOTICE_INVALID_STATE.value,
        )

        acknowledge_notice(notice["id"], account_id)

        # ACKNOWLEDGED, but the clock has not reached the effective date.
        validate_error(
            api.effect_plan_change_notice(notice["id"], RETAIL_AGENT_HEADERS),
            ApiErrorId.ERR_NOTICE_NOT_DUE.value,
        )

        set_clock("2026-10-01T00:00:00Z")
        effected = validate_success(
            api.effect_plan_change_notice(notice["id"], RETAIL_AGENT_HEADERS)
        )
        assert effected["state"] == NoticeState.EFFECTED.value
        assert effected["effected_at"] == "2026-10-01T00:00:00.000Z"
        assert (
            read_subscriber_account(account_id)["subscription_state"]
            == SubscriptionState.ACTIVE.value
        )

        released = validate_success(
            api.create_plan_change_notice(
                {
                    "account_id": account_id,
                    "target_plan_id": plan_id,
                    "notice_type": NoticeType.PRICE_INCREASE.value,
                    "effective_date": "2026-11-05T00:00:00Z",
                    "reason": "Notice after the lock is released",
                },
                RETAIL_AGENT_HEADERS,
            ),
            expected_status=201,
        )
        assert released["notice_days"] == 35
        assert released["etf_disclosed_cents"] == 10000
