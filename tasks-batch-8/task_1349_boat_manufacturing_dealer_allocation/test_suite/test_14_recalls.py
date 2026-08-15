"""Recall campaigns and notices: serial band validation, issue fan-out,
auto-close posture, both remedy paths, and the certification hold cycle
(PRD §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_recall_campaign,
    assert_recall_notice,
    create_campaign,
    create_recall_campaign_payload,
    get_campaign_by_id,
    get_hull,
    issue_campaign,
    list_notices,
    remedy_notice,
    setup_certified_hull,
    setup_issued_campaign,
    setup_registered_hull,
    submit_claim,
    approve_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["compliance_officer_headers"]
ANY = TEST_USERS["any_headers"]


class TestCampaignDraft:
    def test_serial_range_must_be_ordered(self, api):
        """PRD §3.9: "A `ComplianceOfficer` drafts a recall campaign with a
        unique `campaign_code` such as RC-2026-014, a `severity` of
        `SAFETY_STOP`, `SAFETY_STANDARD`, or `EMISSIONS`, the target
        `model_code` and `model_year`, and an inclusive serial band from
        `hin_serial_start` (at least 1) through `hin_serial_end` (no less than
        the start)."
        PRD §2.9: "Body schema and field domains: required fields present;
        enum values valid; dates well-formed with start not after end; a
        production run's `build_week_end` exactly seven days after its
        `build_week_start`; amounts non-negative; `hin_serial_start` not greater
        than `hin_serial_end`; a `BOAT_SHOW`-sourced order carries a
        `show_event_id` while other sources must not; `option_package_ids`, when
        provided on an amendment, is non-empty; and no duplicate option
        identifiers appear within one order — any violation is
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/recall_campaign_serial_range_must_be_ordered
        """
        resp = api.create_recall_campaign(
            create_recall_campaign_payload(
                campaign_code="RC-1", hin_serial_start=10, hin_serial_end=5
            ),
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCampaignIssue:
    def test_issue_on_already_issued_rejected(self, api):
        """PRD §3.9: "Issuing the campaign — permitted only from `DRAFT`,
        otherwise `ERR_CAMPAIGN_NOT_DRAFT` — fans out notices."

        Design: Corner/state_machines/recall_campaign_issue_on_already_issued_rejected
        """
        campaign = create_campaign(
            api, campaign_code="RC-1", model_code="NOSUCH", model_year=2099
        )
        issue_campaign(api, campaign["id"])
        resp = api.issue_recall_campaign(campaign["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_DRAFT)

    def test_zero_match_issue_auto_closes(self, api):
        """PRD §3.9: "A campaign whose criteria match nothing — zero notices —
        auto-transitions straight from `ISSUED` to `CLOSED` at issue."

        Design: Corner/state_machines/campaign_zero_match_auto_closes
        """
        campaign = create_campaign(
            api, campaign_code="RC-ZERO", severity="EMISSIONS",
            model_code="NOSUCH", model_year=2099,
        )
        issued = issue_campaign(api, campaign["id"])
        assert_recall_campaign(issued)
        assert issued["notice_count"] == 0
        assert issued["open_notice_count"] == 0
        assert issued["status"] == "CLOSED", "zero-match issue auto-closes"

    def test_campaign_closes_when_last_notice_remediated(self, api):
        """PRD §3.9: "Thereafter, the campaign auto-transitions `ISSUED` →
        `CLOSED` whenever `open_notice_count` reaches zero through remedies,
        incrementing the campaign's `version`"

        Design: Corner/state_machines/campaign_closes_when_last_notice_remediated
        """
        world = setup_certified_hull(api, with_options=False)
        campaign, notices = setup_issued_campaign(api, world, serial_start=1,
                                                  serial_end=5)
        assert campaign["status"] == "ISSUED"
        assert campaign["notice_count"] == 1
        assert campaign["open_notice_count"] == 1
        remedy_notice(api, notices[0]["id"])
        after = get_campaign_by_id(api, campaign["id"])
        assert after["open_notice_count"] == 0
        assert after["status"] == "CLOSED", "auto-close at zero open notices"


class TestNoticeRemedy:
    def test_remedy_on_remediated_rejected(self, api):
        """PRD §3.9: "Two symmetric remedy paths close a notice, and both
        require it to be `NOTIFIED` — anything else fails with
        `ERR_INVALID_NOTICE_STATE`."

        Design: Corner/state_machines/recall_notice_remedy_on_remediated_rejected
        """
        world = setup_certified_hull(api, with_options=False)
        campaign, notices = setup_issued_campaign(api, world, serial_start=1,
                                                  serial_end=5)
        remedy_notice(api, notices[0]["id"])
        resp = api.remedy_recall_notice(notices[0]["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_NOTICE_STATE)


class TestCertificationHoldCycle:
    def test_hold_cycle_certified_hold_certified(self, api):
        """PRD §3.9: "Every hull whose model's `model_code` equals the
        campaign's, whose model's `model_year` matches, whose `serial_no` falls
        within the closed band from `hin_serial_start` to `hin_serial_end`, and
        whose `certification_status` is `CERTIFIED` receives a `RecallNotice`
        born `NOTIFIED` with `notified_at` stamped from the clock, and the hull
        itself flips `CERTIFIED` → `RECALL_HOLD` with a version increment"
        PRD §3.9: "The plant path is a direct remedy by a `ComplianceOfficer`,
        intended for hulls not yet retailed: the notice transitions to
        `REMEDIED` with `remedy_path` `PLANT_REMEDY` and `remedied_at` from the
        clock."
        PRD §3.9: "Either path then applies the same cascade: the hull's hold
        lifts `RECALL_HOLD` → `CERTIFIED` if and only if no other `NOTIFIED`
        notice remains for that hull — while any open notice persists, so does
        the hold — the campaign's `open_notice_count` decrements by one, and
        the campaign closes automatically at zero."

        The certification dimension cycles UNCERTIFIED -> CERTIFIED ->
        RECALL_HOLD -> CERTIFIED.

        Design: Difficulty/non_linear_state_machine/hull_certification_recall_hold_cycle
        """
        world = setup_certified_hull(api, with_options=False)
        hull_id = world["hull"]["id"]
        assert world["hull"]["certification_status"] == "CERTIFIED"
        campaign, notices = setup_issued_campaign(api, world, serial_start=1,
                                                  serial_end=1)
        assert len(notices) == 1
        assert get_hull(api, hull_id)["certification_status"] == "RECALL_HOLD"
        notice = remedy_notice(api, notices[0]["id"])
        assert_recall_notice(notice)
        assert notice["status"] == "REMEDIED"
        assert notice["remedy_path"] == "PLANT_REMEDY"
        assert get_hull(api, hull_id)["certification_status"] == "CERTIFIED", (
            "remedying the last open notice lifts the hold — cycle closed"
        )

    def test_hold_cycle_is_repeatable(self, api):
        """PRD §3.9: "the hull itself flips `CERTIFIED` → `RECALL_HOLD` with a
        version increment — which blocks any pending delivery of that hull
        until remedy."
        PRD §3.9: "Either path then applies the same cascade: the hull's hold
        lifts `RECALL_HOLD` → `CERTIFIED` if and only if no other `NOTIFIED`
        notice remains for that hull — while any open notice persists, so does
        the hold"

        A second campaign re-enters RECALL_HOLD after the first cycle closed,
        and a second remedy returns the hull to CERTIFIED: the cycle is a true
        loop, not a one-shot.

        Design: Difficulty/non_linear_state_machine/hull_certification_recall_hold_cycle
        """
        world = setup_certified_hull(api, with_options=False)
        hull_id = world["hull"]["id"]
        for _ in range(2):
            campaign, notices = setup_issued_campaign(api, world, serial_start=1,
                                                      serial_end=1)
            assert len(notices) == 1
            assert get_hull(api, hull_id)["certification_status"] == "RECALL_HOLD"
            remedy_notice(api, notices[0]["id"])
            assert get_hull(api, hull_id)["certification_status"] == "CERTIFIED"


class TestRecallClaimCascade:
    def test_claim_approve_remedies_notice_and_closes_campaign(self, api):
        """PRD §3.8: "A recall-linked approval also remedies the recall: the
        linked notice transitions `NOTIFIED` → `REMEDIED` with `remedy_path`
        `WARRANTY_CLAIM` and `remedied_at` from the clock; the hull's
        `RECALL_HOLD` lifts back to `CERTIFIED` if and only if no other
        `NOTIFIED` notice remains for that hull; the campaign's
        `open_notice_count` decrements by one; and a campaign whose count
        reaches zero automatically closes."

        Design: Corner/cross_cutting_layers/cascading_recall_claim_approve_remedies_notice_and_closes_campaign
        """
        world = setup_registered_hull(api, with_options=False, sale_date="2026-08-02")
        campaign, notices = setup_issued_campaign(api, world, serial_start=1,
                                                  serial_end=1)
        assert len(notices) == 1
        notice_id = notices[0]["id"]
        assert get_hull(api, world["hull"]["id"])["certification_status"] == "RECALL_HOLD"
        claim = submit_claim(
            api, world["registration"]["id"], world["dealer"],
            defect_description="recall remedy", labor_hours=1.0,
            parts_cents=10000, recall_notice_id=notice_id,
        )
        approve_claim(api, claim["id"])
        notice = validate_success(api.get_recall_notice(notice_id, ANY), 200)
        assert notice["status"] == "REMEDIED", "hop 1: notice remedied"
        assert notice["remedy_path"] == "WARRANTY_CLAIM"
        assert get_hull(api, world["hull"]["id"])["certification_status"] == "CERTIFIED", (
            "hop 2: hold lifted, last open notice"
        )
        after = get_campaign_by_id(api, campaign["id"])
        assert after["open_notice_count"] == 0, "hop 3: counter decremented"
        assert after["status"] == "CLOSED", "hop 4: campaign auto-closes at zero"


class TestRecallNotFound:
    def test_campaign_not_found_on_issue(self, api):
        """PRD §2.9: "Path identifiers exist, validated left to right along the
        URL — the first missing resource yields its `ERR_{RESOURCE}_NOT_FOUND`:
        `ERR_DEALER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_HULL_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`,
        `ERR_RUN_NOT_FOUND`, or `ERR_MODEL_NOT_FOUND`."

        Design: Corner/errors/error_campaign_not_found_triggerable
        """
        resp = api.issue_recall_campaign(NON_EXISTENT_UUID, OFFICER)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND)

    def test_notice_not_found_on_remedy(self, api):
        """PRD §2.9: "Path identifiers exist, validated left to right along the
        URL — the first missing resource yields its `ERR_{RESOURCE}_NOT_FOUND`:
        `ERR_DEALER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_HULL_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`,
        `ERR_RUN_NOT_FOUND`, or `ERR_MODEL_NOT_FOUND`."

        Design: Corner/errors/error_notice_not_found_triggerable
        """
        resp = api.remedy_recall_notice(NON_EXISTENT_UUID, OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_FOUND)
