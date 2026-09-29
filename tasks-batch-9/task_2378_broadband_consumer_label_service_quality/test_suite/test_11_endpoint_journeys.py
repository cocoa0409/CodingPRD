"""Multi-step endpoint journeys.

Four journeys across the flat endpoint surface: the plan catalogue's
create-read-update shape with its child listings, the two directions from which
an archived disclosure is readable, the channel-selective and notice-type
selective posture gate, and the regulator docket that links to a complaint.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, api_client
from test_helpers.factories import (
    build_disclosure_payload,
    build_plan_amendment_payload,
    build_plan_change_notice_payload,
    build_regulator_inquiry_payload,
)
from test_helpers.fixtures import (
    ReferenceEnvironment,
    build_reference_environment,
    create_subscriber_account,
    file_complaint,
    record_disclosure,
)
from test_helpers.test_users import (
    COMPLAINT_ANALYST_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    NETWORK_ENGINEER_HEADERS,
    REGULATORY_LIAISON_HEADERS,
    RETAIL_AGENT_HEADERS,
)
from test_helpers.types import (
    ComplaintState,
    DisclosureChannel,
    FeeLabelCategory,
    LabelPosture,
    NoticeState,
    NoticeType,
    PricingPhase,
    PublicationState,
    RegulatorInquiryState,
    SubscriptionState,
)

# ---------------------------------------------------------------------------
# Fixture literals of the shared world, recomputed nowhere in the test bodies.
# ---------------------------------------------------------------------------

#: The reference plan's five fee lines, in the ascending `created_at` order the
#: itemisation walks.
REFERENCE_FEE_CODES = [
    "EQUIP_RENTAL",
    "NETWORK_ACCESS",
    "REG_RECOVERY",
    "STATE_USF",
    "INSTALL",
]

#: Figures pinned on the reference plan's published label.
PINNED_MONTHLY_TOTAL_POST_PROMO_CENTS = 10628
PINNED_NET_MONTHLY_INTRO_CENTS = 3766
PINNED_NET_MONTHLY_POST_PROMO_CENTS = 7628

#: A second account enrolled exactly six thirty-day months before the clock, so
#: that its pricing phase has already left the promotion behind.
POST_PROMO_SERVICE_START = "2026-03-05T00:00:00Z"

#: The instant a notice takes effect: thirty-four whole days past the clock.
NOTICE_EFFECTIVE_DATE = "2026-10-05T00:00:00Z"
EXPECTED_NOTICE_DAYS = 34
EXPECTED_ETF_DISCLOSED_CENTS = 12000

#: The date the disputed shortfall was observed, inside the label's window.
SERVICE_OBSERVED_DATE = "2026-09-02T12:00:00Z"


# ---------------------------------------------------------------------------
# Setup chains unique to this file
# ---------------------------------------------------------------------------


def _amend_data_allowance(env: ReferenceEnvironment) -> Tuple[int, Any]:
    """Raise the disclosed allowance — no price field moves — and report the
    plan `version` observed immediately before the amendment."""
    version_before = validate_success(
        api_client.get_service_plan(env.plan_id, COMPLIANCE_OFFICER_HEADERS)
    )["version"]
    payload = build_plan_amendment_payload(
        change_justification="Raise the disclosed data allowance",
        data_allowance_gb=2000,
        overage_rate_cents_per_gb=900,
    )
    response = api_client.amend_service_plan(
        env.plan_id, payload, COMPLIANCE_OFFICER_HEADERS
    )
    return version_before, response


def _raise_monthly_price(env: ReferenceEnvironment) -> Dict[str, Any]:
    """Amend the post-promotional charge, which drifts the disclosure."""
    payload = build_plan_amendment_payload(
        change_justification="Post-promotional rate increase",
        monthly_price_cents=8999,
    )
    return validate_success(
        api_client.amend_service_plan(env.plan_id, payload, COMPLIANCE_OFFICER_HEADERS)
    )


def _three_disclosures(
    env: ReferenceEnvironment,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Two disclosures for the introductory account and one for a second
    account already past the promotion, all against the same published label."""
    second_account = create_subscriber_account(
        env.plan_id, service_start_date=POST_PROMO_SERVICE_START
    )
    point_of_sale = record_disclosure(
        env.account_id, channel=DisclosureChannel.POINT_OF_SALE.value
    )
    portal = record_disclosure(
        env.account_id, channel=DisclosureChannel.ACCOUNT_PORTAL.value
    )
    second_portal = record_disclosure(
        second_account["id"], channel=DisclosureChannel.ACCOUNT_PORTAL.value
    )
    return second_account, point_of_sale, portal, second_portal


def _intake_complaint(env: ReferenceEnvironment) -> Dict[str, Any]:
    """A complaint left in `INTAKE`, disputing the published label."""
    return file_complaint(
        env.account_id,
        env.label_id,
        service_observed_date=SERVICE_OBSERVED_DATE,
        narrative="Evening download far below the label",
        measured_download_mbps=120,
    )


# ---------------------------------------------------------------------------
# The plan catalogue: create, read, update and child listings
# ---------------------------------------------------------------------------


class TestPlanCatalogueJourney:
    def test_non_price_amendment_bumps_the_version_without_drifting_disclosure(self):
        """Raising the data allowance is an update that leaves the price alone.

        PRD: "When the amendment changes any of `monthly_price_cents`,
        `intro_price_cents`, `intro_term_months` or `early_termination_fee_cents`,
        the plan's `price_disclosure_drift` is set to true, the same flag is set
        to true on the plan's published label — because what the consumer can
        currently see no longer matches the plan of record — and
        `last_price_change_at` is set to the logical clock."

        PRD: "The amendment then recomputes the plan's disclosure posture and
        increments the plan's `version`."

        Design: Corner/endpoints/plan_catalogue_create_read_update_and_child_list
        """
        env = build_reference_environment()

        version_before, response = _amend_data_allowance(env)
        amended = validate_success(response)

        assert amended["data_allowance_gb"] == 2000, (
            "the amendment must record the new disclosed allowance"
        )
        assert amended["overage_rate_cents_per_gb"] == 900, (
            "the amendment must record the new overage rate"
        )
        assert amended["version"] == version_before + 1, (
            f"the amendment increments version: expected {version_before + 1}, "
            f"got {amended['version']}"
        )
        assert amended["price_disclosure_drift"] is False, (
            "data_allowance_gb is not one of the four price fields, so no drift"
        )
        assert amended["last_price_change_at"] is None, (
            "last_price_change_at only moves when a price field changes"
        )

        reread = validate_success(
            api_client.get_service_plan(env.plan_id, RETAIL_AGENT_HEADERS)
        )
        assert reread["label_posture"] == LabelPosture.OPEN.value, (
            "with a substantiated published label and no drift the posture is OPEN"
        )
        assert reread["active_label_version_id"] == env.label_id, (
            "the published label is still the plan's active disclosure"
        )
        assert reread["price_disclosure_drift"] is False
        assert reread["last_price_change_at"] is None

    def test_published_label_keeps_its_pinned_figures_across_the_amendment(self):
        """The consumer-visible label is not rewritten by a plan update.

        PRD: "Whether or not a price moved, the amendment recomputes the
        itemisation, the discount benefit and both first-year totals for every
        label of the plan whose `publication_state` is `DRAFT`; published,
        archived and withdrawn labels keep the figures pinned on them."

        Design: Corner/endpoints/plan_catalogue_create_read_update_and_child_list
        """
        env = build_reference_environment()

        _amend_data_allowance(env)

        label = validate_success(
            api_client.get_label_version(env.label_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert label["publication_state"] == PublicationState.PUBLISHED.value, (
            "the label under test must be the published one"
        )
        assert (
            label["monthly_total_post_promo_cents"]
            == PINNED_MONTHLY_TOTAL_POST_PROMO_CENTS
        ), (
            "a published label keeps its pinned post-promotional monthly total: "
            f"expected {PINNED_MONTHLY_TOTAL_POST_PROMO_CENTS}, "
            f"got {label['monthly_total_post_promo_cents']}"
        )
        assert label["net_monthly_intro_cents"] == PINNED_NET_MONTHLY_INTRO_CENTS, (
            "a published label keeps its pinned introductory net: "
            f"expected {PINNED_NET_MONTHLY_INTRO_CENTS}, "
            f"got {label['net_monthly_intro_cents']}"
        )

    def test_fee_lines_and_the_probe_read_back_over_their_child_endpoints(self):
        """The plan's fee block lists in itemisation order and filters by block.

        PRD: "Fee lines can be listed for a plan in ascending `created_at` order
        — the same order the itemisation walks — optionally narrowed by
        `label_category`."

        PRD: "All resources except a `LabelDisclosure` additionally carry
        `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of
        the record — and `version`, an integer that starts at 1 on creation and
        increments by one on every mutation, including mutations the server
        performs on its own initiative when reconciling a derived field."

        Design: Corner/endpoints/plan_catalogue_create_read_update_and_child_list
        """
        env = build_reference_environment()

        rows, meta = validate_paginated(
            api_client.list_fee_line_items(env.plan_id, COMPLAINT_ANALYST_HEADERS)
        )
        assert meta["total_count"] == 5, (
            f"the plan has five fee lines, got total_count {meta['total_count']}"
        )
        assert [row["fee_code"] for row in rows] == REFERENCE_FEE_CODES, (
            "fee lines list in ascending created_at order: "
            f"expected {REFERENCE_FEE_CODES}, got {[r['fee_code'] for r in rows]}"
        )

        recurring, recurring_meta = validate_paginated(
            api_client.list_fee_line_items(
                env.plan_id,
                COMPLAINT_ANALYST_HEADERS,
                params={"label_category": FeeLabelCategory.MONTHLY_RECURRING.value},
            )
        )
        assert recurring_meta["total_count"] == 3, (
            "three of the five fee lines are itemised under MONTHLY_RECURRING, "
            f"got total_count {recurring_meta['total_count']}"
        )
        assert all(
            row["label_category"] == FeeLabelCategory.MONTHLY_RECURRING.value
            for row in recurring
        ), "the label_category filter must return only that block's lines"

        one_time, one_time_meta = validate_paginated(
            api_client.list_fee_line_items(
                env.plan_id,
                COMPLAINT_ANALYST_HEADERS,
                params={
                    "label_category": FeeLabelCategory.ONE_TIME.value,
                    "limit": 5,
                    "offset": 0,
                },
            )
        )
        assert one_time_meta["total_count"] == 1, (
            "exactly one fee line is itemised under ONE_TIME, "
            f"got total_count {one_time_meta['total_count']}"
        )
        assert one_time_meta["has_more"] is False, (
            "a single matching record inside a limit of five leaves nothing beyond"
        )
        assert one_time[0]["fee_code"] == "INSTALL"

        probe = validate_success(
            api_client.get_measurement_probe(env.probe_id, NETWORK_ENGINEER_HEADERS)
        )
        assert probe["probe_code"] == env.probe["probe_code"]
        assert probe["panel_size"] == 75, "the registered panel size reads back"
        assert probe["max_concurrent_windows"] == 2, (
            "the registered aggregate capacity reads back"
        )
        assert probe["version"] == 1, (
            "the probe was never mutated, so its version is still 1"
        )


# ---------------------------------------------------------------------------
# The disclosure archive, read per account and per label
# ---------------------------------------------------------------------------


class TestDisclosureHistoryBothDirections:
    def test_account_history_lists_only_that_accounts_disclosures(self):
        """An account's own disclosure history, whole and channel-filtered.

        PRD: "An account's disclosure history is listable, including disclosures
        of labels since archived, optionally narrowed by `channel`."

        PRD: "The disclosure then records `label_version_id` as the selected
        label, `disclosed_label_version_seq` as that label's `version_seq`,
        `disclosed_net_monthly_cents` as the phase-appropriate figure — the
        label's `net_monthly_intro_cents` when the account's `pricing_phase` is
        `INTRO` and its `net_monthly_post_promo_cents` otherwise, copied as whole
        cents with no re-rounding — and `disclosed_by_user_id` as the acting
        `X-User-ID`."

        Design: Corner/endpoints/disclosure_history_readable_from_both_directions
        """
        env = build_reference_environment()
        _, point_of_sale, portal, second_portal = _three_disclosures(env)

        rows, meta = validate_paginated(
            api_client.list_account_label_disclosures(
                env.account_id, REGULATORY_LIAISON_HEADERS
            )
        )
        assert meta["total_count"] == 2, (
            "the introductory account has two disclosures of its own, "
            f"got total_count {meta['total_count']}"
        )
        assert {row["id"] for row in rows} == {point_of_sale["id"], portal["id"]}, (
            "the per-account read must not reach a sibling account's disclosure"
        )
        assert second_portal["id"] not in {row["id"] for row in rows}

        for row in rows:
            assert (
                row["disclosed_net_monthly_cents"] == PINNED_NET_MONTHLY_INTRO_CENTS
            ), (
                "an INTRO account is disclosed the introductory net: "
                f"expected {PINNED_NET_MONTHLY_INTRO_CENTS}, "
                f"got {row['disclosed_net_monthly_cents']}"
            )
            assert row["disclosed_label_version_seq"] == 1, (
                "the archived copy of the label's version_seq travels with the row"
            )

        filtered, filtered_meta = validate_paginated(
            api_client.list_account_label_disclosures(
                env.account_id,
                REGULATORY_LIAISON_HEADERS,
                params={"channel": DisclosureChannel.POINT_OF_SALE.value},
            )
        )
        assert filtered_meta["total_count"] == 1, (
            "one of the account's two disclosures was made at point of sale, "
            f"got total_count {filtered_meta['total_count']}"
        )
        assert filtered[0]["id"] == point_of_sale["id"]

    def test_label_read_spans_every_account_disclosed_that_label(self):
        """The same rows read from the label side, heterogeneous by phase.

        PRD: "Disclosure events recorded against a single label can also be
        listed for archival and regulator evidence, optionally narrowed by
        `channel`."

        PRD: "The disclosure then records `label_version_id` as the selected
        label, `disclosed_label_version_seq` as that label's `version_seq`,
        `disclosed_net_monthly_cents` as the phase-appropriate figure — the
        label's `net_monthly_intro_cents` when the account's `pricing_phase` is
        `INTRO` and its `net_monthly_post_promo_cents` otherwise, copied as whole
        cents with no re-rounding — and `disclosed_by_user_id` as the acting
        `X-User-ID`."

        Design: Corner/endpoints/disclosure_history_readable_from_both_directions
        """
        env = build_reference_environment()
        second_account, _, portal, second_portal = _three_disclosures(env)

        page, meta = validate_paginated(
            api_client.list_label_version_disclosures(
                env.label_id,
                COMPLIANCE_OFFICER_HEADERS,
                params={"limit": 2, "offset": 0},
            )
        )
        assert meta["total_count"] == 3, (
            "every disclosure of every account on that label is counted, "
            f"got total_count {meta['total_count']}"
        )
        assert meta["has_more"] is True, (
            "three matching rows at a limit of two leave a record beyond the page"
        )
        assert len(page) == 2, f"the page holds two rows, got {len(page)}"

        by_channel, channel_meta = validate_paginated(
            api_client.list_label_version_disclosures(
                env.label_id,
                COMPLIANCE_OFFICER_HEADERS,
                params={"channel": DisclosureChannel.ACCOUNT_PORTAL.value},
            )
        )
        assert channel_meta["total_count"] == 2, (
            "two of the label's three disclosures were served in the portal, "
            f"got total_count {channel_meta['total_count']}"
        )
        assert {row["id"] for row in by_channel} == {
            portal["id"],
            second_portal["id"],
        }, "the per-label channel filter spans both accounts"

        post_promo_row = next(
            row for row in by_channel if row["id"] == second_portal["id"]
        )
        assert (
            post_promo_row["disclosed_net_monthly_cents"]
            == PINNED_NET_MONTHLY_POST_PROMO_CENTS
        ), (
            "the account past its promotion is disclosed the post-promotional net: "
            f"expected {PINNED_NET_MONTHLY_POST_PROMO_CENTS}, "
            f"got {post_promo_row['disclosed_net_monthly_cents']}"
        )
        assert post_promo_row["label_version_id"] == env.label_id, (
            "both figures were disclosed off the very same label"
        )

        second_read = validate_success(
            api_client.get_subscriber_account(
                second_account["id"], COMPLIANCE_OFFICER_HEADERS
            )
        )
        assert second_read["last_disclosed_label_version_id"] == env.label_id
        assert second_read["pricing_phase"] == PricingPhase.POST_PROMO.value, (
            "six whole thirty-day months have elapsed against a six-month promotion"
        )


# ---------------------------------------------------------------------------
# The posture gate is channel- and notice-type-selective
# ---------------------------------------------------------------------------


class TestRestrictedPostureIsSelective:
    def test_point_of_sale_refused_while_the_portal_channel_stays_open(self):
        """A drifted price closes the sales counter, not the account portal.

        PRD: "Otherwise, if the plan's `price_disclosure_drift` is true, the
        posture is `RESTRICTED`."

        PRD: "`RESTRICTED` blocks a disclosure whose `channel` is
        `POINT_OF_SALE` and a notice whose `notice_type` is `PRICE_INCREASE`,
        answering `ERR_PLAN_POSTURE_RESTRICTED` (409), while `ACCOUNT_PORTAL`
        disclosures and `PLAN_CHANGE` notices continue to be accepted."

        Design: Corner/endpoints/point_of_sale_disclosure_blocked_while_the_price_drifts
        """
        env = build_reference_environment()

        while_open = validate_success(
            api_client.record_label_disclosure(
                env.account_id,
                build_disclosure_payload(
                    channel=DisclosureChannel.POINT_OF_SALE.value
                ),
                RETAIL_AGENT_HEADERS,
            ),
            expected_status=201,
        )
        assert (
            while_open["disclosed_net_monthly_cents"] == PINNED_NET_MONTHLY_INTRO_CENTS
        ), "the point-of-sale surface is open while the posture is OPEN"

        drifted = _raise_monthly_price(env)
        assert drifted["price_disclosure_drift"] is True, (
            "amending monthly_price_cents drifts the disclosure"
        )
        assert drifted["label_posture"] == LabelPosture.RESTRICTED.value, (
            "a drifted price on a substantiated published label restricts the plan"
        )

        refused = api_client.record_label_disclosure(
            env.account_id,
            build_disclosure_payload(channel=DisclosureChannel.POINT_OF_SALE.value),
            RETAIL_AGENT_HEADERS,
        )
        validate_error(refused, ApiErrorId.ERR_PLAN_POSTURE_RESTRICTED.value)

        portal = validate_success(
            api_client.record_label_disclosure(
                env.account_id,
                build_disclosure_payload(
                    channel=DisclosureChannel.ACCOUNT_PORTAL.value
                ),
                RETAIL_AGENT_HEADERS,
            ),
            expected_status=201,
        )
        assert (
            portal["disclosed_net_monthly_cents"] == PINNED_NET_MONTHLY_INTRO_CENTS
        ), (
            "the portal channel keeps serving the pinned introductory net: "
            f"expected {PINNED_NET_MONTHLY_INTRO_CENTS}, "
            f"got {portal['disclosed_net_monthly_cents']}"
        )

    def test_price_increase_notice_refused_while_a_plan_change_notice_lands(self):
        """The same restriction sorts notices by type, not by account.

        PRD: "`RESTRICTED` blocks a disclosure whose `channel` is
        `POINT_OF_SALE` and a notice whose `notice_type` is `PRICE_INCREASE`,
        answering `ERR_PLAN_POSTURE_RESTRICTED` (409), while `ACCOUNT_PORTAL`
        disclosures and `PLAN_CHANGE` notices continue to be accepted."

        PRD: "Creating the notice records `notice_days` as the whole number of
        days between the logical clock at creation and the `effective_date` — the
        span in seconds divided by 86,400 and rounded down — copies the account's
        current `plan_id` into `source_plan_id` as a denormalised record of the
        plan being left (never client-supplied), and takes
        `disclosed_net_monthly_cents` from the target plan's published label,
        specifically that label's `net_monthly_post_promo_cents`."

        Design: Corner/endpoints/point_of_sale_disclosure_blocked_while_the_price_drifts
        """
        env = build_reference_environment()
        _raise_monthly_price(env)

        refused = api_client.create_plan_change_notice(
            build_plan_change_notice_payload(
                env.account_id,
                env.plan_id,
                NOTICE_EFFECTIVE_DATE,
                notice_type=NoticeType.PRICE_INCREASE.value,
                reason="Rate increase notice",
            ),
            RETAIL_AGENT_HEADERS,
        )
        validate_error(refused, ApiErrorId.ERR_PLAN_POSTURE_RESTRICTED.value)

        untouched = validate_success(
            api_client.get_subscriber_account(env.account_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert untouched["subscription_state"] == SubscriptionState.ACTIVE.value, (
            "the refused PRICE_INCREASE notice must leave the account ACTIVE"
        )

        notice = validate_success(
            api_client.create_plan_change_notice(
                build_plan_change_notice_payload(
                    env.account_id,
                    env.plan_id,
                    NOTICE_EFFECTIVE_DATE,
                    notice_type=NoticeType.PLAN_CHANGE.value,
                    reason="Consumer-requested plan change",
                ),
                RETAIL_AGENT_HEADERS,
            ),
            expected_status=201,
        )
        assert notice["notice_type"] == NoticeType.PLAN_CHANGE.value
        assert notice["notice_days"] == EXPECTED_NOTICE_DAYS, (
            f"notice_days: expected {EXPECTED_NOTICE_DAYS}, "
            f"got {notice['notice_days']}"
        )
        assert notice["etf_disclosed_cents"] == EXPECTED_ETF_DISCLOSED_CENTS, (
            "the prorated schedule has not decayed at all yet: expected "
            f"{EXPECTED_ETF_DISCLOSED_CENTS}, got {notice['etf_disclosed_cents']}"
        )
        assert notice["state"] == NoticeState.SENT.value

        after = validate_success(
            api_client.get_subscriber_account(env.account_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert after["subscription_state"] == SubscriptionState.PENDING_CHANGE.value, (
            "the accepted notice moves the account into the pending-change posture"
        )


# ---------------------------------------------------------------------------
# The regulator docket's link to a complaint
# ---------------------------------------------------------------------------


class TestRegulatorInquiryComplaintLink:
    def test_docket_requires_the_referenced_complaint_to_exist(self):
        """An unknown complaint is a not-found that writes nothing.

        PRD: "Each entity has its own not-found code, all of them 404:
        `ERR_SERVICE_PLAN_NOT_FOUND` (for a plan named by a path segment or by
        `plan_id` or `target_plan_id`), `ERR_METHODOLOGY_DOCUMENT_NOT_FOUND`,
        `ERR_MEASUREMENT_PROBE_NOT_FOUND` (for a `probe_id` that names nothing),
        `ERR_TEST_RUN_NOT_FOUND`, `ERR_ATTESTATION_NOT_FOUND`,
        `ERR_LABEL_VERSION_NOT_FOUND` (for a path segment or a
        `disputed_label_version_id`), `ERR_TRANSLATION_NOT_FOUND`,
        `ERR_SUBSCRIBER_ACCOUNT_NOT_FOUND` (for a path segment or an
        `account_id`), `ERR_COMPLAINT_NOT_FOUND` (for a path segment or a
        `complaint_id`), `ERR_REMEDIATION_CREDIT_NOT_FOUND`,
        `ERR_REGULATOR_INQUIRY_NOT_FOUND` and
        `ERR_PLAN_CHANGE_NOTICE_NOT_FOUND`."

        Design: Corner/endpoints/regulator_inquiry_links_a_docket_to_a_complaint
        """
        env = build_reference_environment()
        complaint = _intake_complaint(env)

        payload = build_regulator_inquiry_payload(complaint["id"])
        docket_number = payload["docket_number"]

        rejected = api_client.create_regulator_inquiry(
            dict(payload, complaint_id=NON_EXISTENT_UUID), REGULATORY_LIAISON_HEADERS
        )
        validate_error(rejected, ApiErrorId.ERR_COMPLAINT_NOT_FOUND.value)

        created = validate_success(
            api_client.create_regulator_inquiry(payload, REGULATORY_LIAISON_HEADERS),
            expected_status=201,
        )
        assert created["docket_number"] == docket_number, (
            "the rejected call wrote no row, so its docket number was still free"
        )
        assert created["complaint_id"] == complaint["id"]

    def test_docket_opens_received_and_is_findable_by_its_complaint(self):
        """An INTAKE complaint is a legal docket target; the docket starts empty.

        PRD: "The docket opens in state `RECEIVED` with `filed_late` false, both
        `technical_packet_filed_at` and `resolution_report_filed_at` null, both
        `technical_evidence_ref` and `resolution_report_ref` null, and
        `closure_note` and `closed_at` null."

        PRD: "Dockets are readable individually and listable with filters on
        `complaint_id` and `state`."

        Design: Corner/endpoints/regulator_inquiry_links_a_docket_to_a_complaint
        """
        env = build_reference_environment()
        complaint = _intake_complaint(env)

        inquiry = validate_success(
            api_client.create_regulator_inquiry(
                build_regulator_inquiry_payload(complaint["id"]),
                REGULATORY_LIAISON_HEADERS,
            ),
            expected_status=201,
        )
        assert inquiry["complaint_id"] == complaint["id"], (
            "the docket carries the complaint it enquires into"
        )
        assert inquiry["state"] == RegulatorInquiryState.RECEIVED.value
        assert inquiry["technical_packet_filed_at"] is None
        assert inquiry["resolution_report_filed_at"] is None
        assert inquiry["filed_late"] is False

        by_complaint, complaint_meta = validate_paginated(
            api_client.list_regulator_inquiries(
                COMPLAINT_ANALYST_HEADERS, params={"complaint_id": complaint["id"]}
            )
        )
        assert complaint_meta["total_count"] == 1, (
            "one docket enquires into this complaint, "
            f"got total_count {complaint_meta['total_count']}"
        )
        assert by_complaint[0]["id"] == inquiry["id"]

        by_state, state_meta = validate_paginated(
            api_client.list_regulator_inquiries(
                NETWORK_ENGINEER_HEADERS,
                params={
                    "complaint_id": complaint["id"],
                    "state": RegulatorInquiryState.RECEIVED.value,
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert state_meta["total_count"] == 1, (
            "the freshly opened docket matches the RECEIVED filter, "
            f"got total_count {state_meta['total_count']}"
        )
        assert state_meta["has_more"] is False
        assert by_state[0]["id"] == inquiry["id"]

        read_back = validate_success(
            api_client.get_regulator_inquiry(inquiry["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert read_back["state"] == RegulatorInquiryState.RECEIVED.value

        complaint_after = validate_success(
            api_client.get_complaint(complaint["id"], COMPLAINT_ANALYST_HEADERS)
        )
        assert complaint_after["state"] == ComplaintState.INTAKE.value, (
            "opening a docket drives no complaint transition"
        )
