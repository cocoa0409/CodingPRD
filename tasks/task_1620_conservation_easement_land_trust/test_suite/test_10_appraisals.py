"""Appraisals and tax-deduction substantiation: engagement buffer, delivery
anchoring, certification window, appraiser independence, and the two deduction
variants (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    create_engaged_appraisal,
    create_recorded_easement,
    deliver_appraisal,
    deliver_appraisal_payload,
    make_appraiser_headers,
    setup_delivered_appraisal,
    validate_error,
    validate_success,
)


def _get_appraisal(api, appraisal_id, headers):
    return validate_success(api.get_appraisal(appraisal_id, headers), 200)


class TestDeliveryRules:
    def test_appraisal_double_deliver_rejected(self, api, trust_admin_headers):
        """PRD §3.8: "Delivery belongs to the engaged appraiser alone: a caller
        whose `X-User-ID` does not match `appraiser_user_id` is rejected with
        `ERR_NOT_ENGAGED_APPRAISER`, and delivery from any state other than
        `ENGAGED` is rejected with `ERR_INVALID_APPRAISAL_STATE`."

        Design: Corner/state_machines/appraisal_double_deliver_rejected
        """
        ctx = setup_delivered_appraisal(
            appraiser_user_id="appr-1", before_value_cents=90000000,
            after_value_cents=55000000,
        )
        appraisal = ctx["appraisal"]
        assert appraisal["status"] == "DELIVERED"

        resp = api.deliver_appraisal(
            appraisal["id"],
            deliver_appraisal_payload(before_value_cents=91000000,
                                      after_value_cents=56000000),
            make_appraiser_headers("appr-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_APPRAISAL_STATE)
        after = _get_appraisal(api, appraisal["id"], trust_admin_headers)
        assert after["status"] == "DELIVERED"
        assert after["before_value_cents"] == 90000000
        assert after["after_value_cents"] == 55000000

    def test_deliver_by_other_appraiser_rejected(self, api, trust_admin_headers):
        """PRD §3.8: "Delivery belongs to the engaged appraiser alone: a caller
        whose `X-User-ID` does not match `appraiser_user_id` is rejected with
        `ERR_NOT_ENGAGED_APPRAISER`"
        PRD §2.11: "delivering an appraisal is restricted to the engagement's
        `appraiser_user_id` (`ERR_NOT_ENGAGED_APPRAISER`, 403)."

        Design: Corner/errors/deliver_by_other_appraiser_rejected
        """
        ctx = create_recorded_easement(name="E-NA", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED"})
        appraisal = create_engaged_appraisal(
            ctx["easement"]["id"], appraiser_user_id="appr-1",
            effective_on="2026-08-15", gift_on="2026-09-01",
        )
        resp = api.deliver_appraisal(
            appraisal["id"],
            deliver_appraisal_payload(before_value_cents=90000000,
                                      after_value_cents=55000000),
            make_appraiser_headers("appr-2"),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_ENGAGED_APPRAISER)
        assert _get_appraisal(api, appraisal["id"], trust_admin_headers)["status"] == "ENGAGED"


class TestEngagementBuffer:
    def test_appraisal_engagement_short_gap_rejected(self, api, coordinator_headers):
        """PRD §3.8: "One appraiser may not hold overlapping engagements on the
        same easement: if another appraisal with the same `appraiser_user_id`
        and `easement_id` is `ENGAGED` or `DELIVERED` and its `effective_on`
        lies less than 365 days from the new one, creation is rejected with
        `ERR_APPRAISAL_ENGAGEMENT_OVERLAP` (409); a gap of exactly 365 days is
        allowed."

        Design: Difficulty/resource_temporal_overlap/appraisal_engagement_365_day_buffer
        """
        ctx = create_recorded_easement(name="E-OV2", parcel_acreage=500,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        easement_id = ctx["easement"]["id"]
        first = create_engaged_appraisal(
            easement_id, appraiser_user_id="appr-1",
            effective_on="2026-03-01", gift_on="2026-04-01",
        )
        assert first["status"] == "ENGAGED"

        # 2026-03-01 -> 2026-12-01 is 275 days: inside the buffer.
        resp = api.create_appraisal(
            {
                "easement_id": easement_id,
                "appraiser_user_id": "appr-1",
                "effective_on": "2026-12-01",
                "gift_on": "2027-01-15",
                "contiguous_enhancement_applies": False,
            },
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_APPRAISAL_ENGAGEMENT_OVERLAP)

    def test_appraisal_engagement_exactly_365_days_allowed(self, api, coordinator_headers):
        """PRD §3.8: "if another appraisal with the same `appraiser_user_id` and
        `easement_id` is `ENGAGED` or `DELIVERED` and its `effective_on` lies
        less than 365 days from the new one, creation is rejected with
        `ERR_APPRAISAL_ENGAGEMENT_OVERLAP` (409); a gap of exactly 365 days is
        allowed."

        Design: Difficulty/resource_temporal_overlap/appraisal_engagement_365_day_buffer
        """
        ctx = create_recorded_easement(name="E-OV2B", parcel_acreage=500,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        easement_id = ctx["easement"]["id"]
        create_engaged_appraisal(
            easement_id, appraiser_user_id="appr-1",
            effective_on="2026-03-01", gift_on="2026-04-01",
        )

        # 2026-03-01 -> 2027-03-01 is exactly 365 days: allowed.
        second = validate_success(
            api.create_appraisal(
                {
                    "easement_id": easement_id,
                    "appraiser_user_id": "appr-1",
                    "effective_on": "2027-03-01",
                    "gift_on": "2027-04-01",
                    "contiguous_enhancement_applies": False,
                },
                coordinator_headers,
            ),
            201,
        )
        assert second["status"] == "ENGAGED"


class TestCertification:
    def test_appraiser_conflict_with_baseline_preparer(self, api, coordinator_headers,
                                                       trust_admin_headers):
        """PRD §3.8: "And the appraiser must be independent of the baseline: an
        `appraiser_user_id` matching the easement baseline report's
        `prepared_by_user_id` is rejected with `ERR_APPRAISER_CONFLICT` (422)."

        Design: Corner/errors/appraiser_conflict_with_baseline_preparer
        """
        # Clean substantiation window at the default clock (gift 2026-09-01,
        # effective 2026-08-15), so only the independence check can fire.
        ctx = setup_delivered_appraisal(
            appraiser_user_id="staff-prep-1", effective_on="2026-08-15",
            gift_on="2026-09-01", before_value_cents=90000000,
            after_value_cents=55000000, preparer="staff-prep-1",
        )
        resp = api.certify_appraisal(ctx["appraisal"]["id"], coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_APPRAISER_CONFLICT)
        after = _get_appraisal(api, ctx["appraisal"]["id"], trust_admin_headers)
        assert after["status"] == "DELIVERED"

    def test_non_positive_deduction_rejected(self, api, coordinator_headers):
        """PRD §3.8: "The computed deduction must be positive, else
        `ERR_NON_POSITIVE_DEDUCTION` (422)."
        PRD §3.8: "Under the standard variant — `contiguous_enhancement_applies`
        false — `deductible_value_cents` is simply the before value less the
        after value, and `enhancement_value_cents` is ignored entirely; a
        difference of zero or less fails the positive-deduction check."

        Design: Corner/errors/non_positive_deduction_rejected
        """
        ctx = setup_delivered_appraisal(
            appraiser_user_id="appr-1", effective_on="2026-08-15",
            gift_on="2026-09-01", before_value_cents=55000000,
            after_value_cents=90000000,
        )
        resp = api.certify_appraisal(ctx["appraisal"]["id"], coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_NON_POSITIVE_DEDUCTION)

    def test_appraiser_cannot_certify_own_appraisal(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "POST `/stewardship/appraisals/{appraisalId}/certify` ...
        StewardshipCoordinator".

        Design: Corner/rbac/appraiser_cannot_certify_own_appraisal
        """
        ctx = setup_delivered_appraisal(
            appraiser_user_id="appr-1", effective_on="2026-08-15",
            gift_on="2026-09-01",
        )
        resp = api.certify_appraisal(
            ctx["appraisal"]["id"], make_appraiser_headers("appr-1")
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_certify_temporal_window_beats_appraiser_conflict(self, api,
                                                              coordinator_headers,
                                                              trust_admin_headers):
        """PRD §2.9: "Validations run in a fixed order, and an earlier failure
        masks every later check."
        PRD §2.9: "10. Temporal windows — `ERR_MONITOR_WINDOW_OVERLAP` and
        `ERR_APPRAISAL_ENGAGEMENT_OVERLAP` (409); `ERR_NOTICE_WINDOW_VIOLATION`
        and `ERR_SUBSTANTIATION_WINDOW_EXPIRED` (422). 11. Referential
        independence — `ERR_APPRAISER_CONFLICT` (422) and
        `ERR_NOT_CURRENT_LANDOWNER` (403)."
        PRD §3.8: "The substantiation window must hold — `effective_on` no
        earlier than sixty days before `gift_on`, and the clock date no later
        than 240 days after `gift_on`, both boundaries inclusive — else
        `ERR_SUBSTANTIATION_WINDOW_EXPIRED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/certify_temporal_window_beats_appraiser_conflict
        """
        # gift_on 2025-11-01 + 240 days = 2026-06-29 < default clock 2026-08-01:
        # the window has expired AND the appraiser prepared the baseline.
        ctx = setup_delivered_appraisal(
            appraiser_user_id="staff-prep-1", effective_on="2025-12-15",
            gift_on="2025-11-01", before_value_cents=90000000,
            after_value_cents=55000000, preparer="staff-prep-1",
        )
        resp = api.certify_appraisal(ctx["appraisal"]["id"], coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_SUBSTANTIATION_WINDOW_EXPIRED)

        after = _get_appraisal(api, ctx["appraisal"]["id"], trust_admin_headers)
        assert after["status"] == "DELIVERED"
        assert after.get("deductible_value_cents") is None

    def test_certify_appraiser_conflict_when_window_clean(self, api, coordinator_headers):
        """PRD §2.9: "Validations run in a fixed order, and an earlier failure
        masks every later check."
        PRD §3.8: "And the appraiser must be independent of the baseline: an
        `appraiser_user_id` matching the easement baseline report's
        `prepared_by_user_id` is rejected with `ERR_APPRAISER_CONFLICT` (422)."

        Design: Difficulty/priority_pair_validation_conflict/certify_temporal_window_beats_appraiser_conflict
        """
        # Same conflict, but the window holds at the default clock
        # (gift 2026-09-01, effective 2026-08-15 >= gift - 60 days), so the
        # referential check is the one that fires.
        ctx = setup_delivered_appraisal(
            appraiser_user_id="staff-prep-1", effective_on="2026-08-15",
            gift_on="2026-09-01", before_value_cents=90000000,
            after_value_cents=55000000, preparer="staff-prep-1",
        )
        resp = api.certify_appraisal(ctx["appraisal"]["id"], coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_APPRAISER_CONFLICT)


class TestDeductionVariants:
    def test_appraisal_deduction_standard_variant(self, api, coordinator_headers):
        """PRD §3.8: "Under the standard variant —
        `contiguous_enhancement_applies` false — `deductible_value_cents` is
        simply the before value less the after value, and
        `enhancement_value_cents` is ignored entirely"
        PRD §3.8: "On certification the computed `deductible_value_cents` is
        frozen onto the appraisal and the status becomes `CERTIFIED`."

        Design: Difficulty/dual_variant_calc/appraisal_deduction_standard_vs_enhancement_adjusted
        """
        ctx = setup_delivered_appraisal(
            appraiser_user_id="appr-1", effective_on="2026-08-15",
            gift_on="2026-09-01", contiguous_enhancement_applies=False,
            before_value_cents=90000000, after_value_cents=55000000,
            enhancement_value_cents=12000000,
        )
        certified = validate_success(
            api.certify_appraisal(ctx["appraisal"]["id"], coordinator_headers), 200
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["deductible_value_cents"] == 35000000, (
            "standard variant ignores the enhancement value entirely"
        )

    def test_appraisal_deduction_enhancement_adjusted_variant(self, api,
                                                              coordinator_headers):
        """PRD §3.8: "Under the enhancement-adjusted variant — the flag true —
        the enhancement value is subtracted as well, with the result floored at
        zero"
        PRD §3.8: "The same delivered numbers can therefore legitimately produce
        different deductibles under the two variants."

        Design: Difficulty/dual_variant_calc/appraisal_deduction_standard_vs_enhancement_adjusted
        """
        ctx = create_recorded_easement(name="E-DV2", parcel_acreage=500,
                                       matrix={"AGRICULTURE": "PERMITTED"},
                                       preparer="staff-prep-1")
        easement_id = ctx["easement"]["id"]

        standard = create_engaged_appraisal(
            easement_id, appraiser_user_id="appr-1", effective_on="2026-08-15",
            gift_on="2026-09-01", contiguous_enhancement_applies=False,
        )
        adjusted = create_engaged_appraisal(
            easement_id, appraiser_user_id="appr-2", effective_on="2026-08-15",
            gift_on="2026-09-01", contiguous_enhancement_applies=True,
        )
        deliver_appraisal(standard["id"], "appr-1", before_value_cents=90000000,
                          after_value_cents=55000000,
                          enhancement_value_cents=12000000)
        deliver_appraisal(adjusted["id"], "appr-2", before_value_cents=90000000,
                          after_value_cents=55000000,
                          enhancement_value_cents=12000000)

        certified_standard = validate_success(
            api.certify_appraisal(standard["id"], coordinator_headers), 200
        )
        certified_adjusted = validate_success(
            api.certify_appraisal(adjusted["id"], coordinator_headers), 200
        )
        assert certified_standard["deductible_value_cents"] == 35000000
        assert certified_adjusted["deductible_value_cents"] == 23000000
        assert (
            certified_standard["deductible_value_cents"]
            - certified_adjusted["deductible_value_cents"]
            == 12000000
        ), "the variants diverge by exactly the enhancement value"
