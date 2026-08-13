"""Applications: source shape rules, floorplan referential integrity, screening
thresholds, the screening gate on decisions, rescreen loop, deposits, withdrawal."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_leasable_application,
    create_agent,
    create_application,
    create_contacted_inquiry,
    create_floorplan,
    create_property,
    create_waitlist_entry,
    decide_application,
    get_application,
    make_leasing_agent_headers,
    rescreen_application,
    setup_site,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["property_manager_headers"]


class TestApplicationSourceShape:
    def test_application_source_ambiguous_rejected(self, api):
        """PRD §3.5: "An application is opened from exactly one source: an
        `inquiry_id` or a `waitlist_entry_id`. Supplying both, or neither, is
        rejected with `ERR_APPLICATION_SOURCE_AMBIGUOUS` (HTTP 400)."

        Design: Corner/validations/application_source_ambiguous_rejected
        """
        site = setup_site()
        agent_id = site["agent"]["id"]
        inquiry = create_contacted_inquiry(
            site["property"]["id"], agent_id,
            floorplan_id=site["floorplan"]["id"], contact_name="AM",
            contact_email="am@x.com", source="PHONE")
        f_zero = create_floorplan(site["property"]["id"], name="Future",
                                  total_units=0)
        entry = create_waitlist_entry(f_zero["id"], agent_id, contact_name="WE",
                                      contact_email="we@x.com")

        resp = api.create_application(
            {"inquiry_id": inquiry["id"], "waitlist_entry_id": entry["id"],
             "floorplan_id": site["floorplan"]["id"], "applicant_name": "Ambig",
             "applicant_email": "am@x.com", "annual_income_cents": 9000000,
             "credit_score": 750},
            make_leasing_agent_headers(agent_id))
        validate_error(resp, ApiErrorId.ERR_APPLICATION_SOURCE_AMBIGUOUS, 400)

    def test_application_floorplan_mismatch_rejected(self, api):
        """PRD §3.5: "In both cases the payload's `floorplan_id` must equal the
        source's floorplan; a mismatch is rejected with
        `ERR_APPLICATION_FLOORPLAN_MISMATCH` (HTTP 422)."

        Design: Corner/validations/application_floorplan_mismatch_rejected
        """
        site = setup_site()
        agent_id = site["agent"]["id"]
        other = create_floorplan(site["property"]["id"], name="2BR", bedrooms=2,
                                 base_rent_cents=300000)
        inquiry = create_contacted_inquiry(
            site["property"]["id"], agent_id,
            floorplan_id=site["floorplan"]["id"], contact_name="MM",
            contact_email="mm@x.com")

        resp = api.create_application(
            {"inquiry_id": inquiry["id"], "floorplan_id": other["id"],
             "applicant_name": "MM App", "applicant_email": "mm@x.com",
             "annual_income_cents": 9000000, "credit_score": 750},
            make_leasing_agent_headers(agent_id))
        validate_error(resp, ApiErrorId.ERR_APPLICATION_FLOORPLAN_MISMATCH, 422)
        data, _ = validate_paginated(
            api.list_applications(PM, params={"inquiry_id": inquiry["id"]}))
        assert data == [], "a rejected creation must not persist an application"


class TestScreeningRecommendation:
    def test_screening_credit_band_boundaries(self, api):
        """PRD §3.5: "When income qualifies and the score is at least 620 but below
        700, the recommendation is `CONDITION`, with exactly 620 landing here."
        PRD §3.5: "In every other case — income short of the threshold, or a score
        below 620 — the recommendation is `DENY`."

        Design: Corner/calculations/screening_credit_band_boundaries
        """
        site = setup_site(floorplan_overrides={"total_units": 3})
        agent_id = site["agent"]["id"]
        inquiry1 = create_contacted_inquiry(
            site["property"]["id"], agent_id,
            floorplan_id=site["floorplan"]["id"], contact_name="C620",
            contact_email="c620@x.com")
        inquiry2 = create_contacted_inquiry(
            site["property"]["id"], agent_id,
            floorplan_id=site["floorplan"]["id"], contact_name="C619",
            contact_email="c619@x.com")

        # Income leg comfortably satisfied (9000000 >= 3 * 12 * 200000).
        at_floor = create_application(site["floorplan"]["id"], agent_id,
                                      inquiry_id=inquiry1["id"], credit_score=620,
                                      applicant_name="Six Twenty",
                                      applicant_email="c620@x.com")
        below_floor = create_application(site["floorplan"]["id"], agent_id,
                                         inquiry_id=inquiry2["id"], credit_score=619,
                                         applicant_name="Six Nineteen",
                                         applicant_email="c619@x.com")
        assert at_floor["recommendation"] == "CONDITION", \
            "620 is the inclusive CONDITION floor"
        assert below_floor["recommendation"] == "DENY"

    def test_screening_income_exactly_three_x_rent_qualifies(self, api):
        """PRD §3.5: "Income qualifies when `annual_income_cents` is at least three
        times the annualized rent — three times twelve times
        `monthly_rent_snapshot_cents` — and income landing exactly at that threshold
        qualifies."
        PRD §3.5: "When income qualifies and `credit_score` is at least 700, the
        recommendation is `APPROVE`, with a score of exactly 700 eligible."
        PRD §3.5: "At creation the server pins `monthly_rent_snapshot_cents`: when
        the floorplan has a `PUBLISHED` offer, the snapshot is that offer's
        `effective_monthly_rent_cents`; otherwise it is the floorplan's
        `base_rent_cents`."

        Design: Difficulty/boundary_precision_check/screening_income_exactly_three_x_rent_qualifies
        """
        site = setup_site()  # base rent 200000, no published offer
        agent_id = site["agent"]["id"]
        inquiry = create_contacted_inquiry(
            site["property"]["id"], agent_id,
            floorplan_id=site["floorplan"]["id"], contact_name="T1",
            contact_email="t1@x.com")
        application = create_application(
            site["floorplan"]["id"], agent_id, inquiry_id=inquiry["id"],
            annual_income_cents=7200000, credit_score=700,
            applicant_name="Exact", applicant_email="t1@x.com")
        # 7200000 == 3 * 12 * 200000: the inclusive threshold qualifies.
        assert application["monthly_rent_snapshot_cents"] == 200000
        assert application["recommendation"] == "APPROVE"

    def test_screening_income_one_cent_below_threshold_denies(self, api):
        """PRD §3.5: "Income qualifies when `annual_income_cents` is at least three
        times the annualized rent — three times twelve times
        `monthly_rent_snapshot_cents` — and income landing exactly at that threshold
        qualifies."
        PRD §3.5: "In every other case — income short of the threshold, or a score
        below 620 — the recommendation is `DENY`."

        Design: Difficulty/boundary_precision_check/screening_income_exactly_three_x_rent_qualifies
        """
        site = setup_site()
        agent_id = site["agent"]["id"]
        inquiry = create_contacted_inquiry(
            site["property"]["id"], agent_id,
            floorplan_id=site["floorplan"]["id"], contact_name="T2",
            contact_email="t2@x.com")
        application = create_application(
            site["floorplan"]["id"], agent_id, inquiry_id=inquiry["id"],
            annual_income_cents=7199999, credit_score=700,
            applicant_name="Below", applicant_email="t2@x.com")
        # One cent below 3 * 12 * 200000 fails the income leg outright.
        assert application["recommendation"] == "DENY"


class TestDecisions:
    def test_screening_deny_blocks_approval_decision(self, api):
        """PRD §3.5: "The screening gate stands between recommendation and decision:
        deciding `APPROVED` or `APPROVED_WITH_CONDITIONS` while the recommendation
        is `DENY` is rejected with `ERR_SCREENING_BLOCKS_APPROVAL` (HTTP 422) — no
        approval may override a denial recommendation."

        Design: Corner/validations/screening_deny_blocks_approval_decision
        """
        site = setup_site()
        bundle = add_leasable_application(site, decision=None,
                                          app_overrides={"credit_score": 500})
        application = bundle["application"]
        assert application["recommendation"] == "DENY"

        resp = api.decide_application(application["id"], "APPROVED", PM)
        validate_error(resp, ApiErrorId.ERR_SCREENING_BLOCKS_APPROVAL, 422)
        assert get_application(application["id"])["status"] == "SCREENING", \
            "a blocked decision leaves the application untouched"

        denied = decide_application(application["id"], "DENIED")
        assert denied["status"] == "DENIED", \
            "the gate is conditional on the decision value: DENIED proceeds"

    def test_decide_from_approved_returns_invalid_state(self, api):
        """PRD §3.5: "Decision-making belongs to the `PropertyManager`, who submits
        a `decision` of `APPROVED`, `APPROVED_WITH_CONDITIONS`, or `DENIED` against
        an application in `SCREENING` (any other state is
        `ERR_APPLICATION_INVALID_STATE`)."

        Design: Corner/state_machines/decide_from_approved_returns_invalid_state
        """
        site = setup_site()
        bundle = add_leasable_application(site, decision="APPROVED")

        resp = api.decide_application(bundle["application"]["id"], "DENIED", PM)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)
        assert get_application(bundle["application"]["id"])["status"] == "APPROVED"

    def test_withdraw_from_denied_returns_invalid_state(self, api):
        """PRD §3.5: "Withdrawal is permitted from `SCREENING` or
        `APPROVED_WITH_CONDITIONS` and lands the application in the terminal
        `WITHDRAWN` state; from anywhere else the request is
        `ERR_APPLICATION_INVALID_STATE`."

        Design: Corner/state_machines/withdraw_from_denied_returns_invalid_state
        """
        site = setup_site()
        bundle = add_leasable_application(site, decision="DENIED",
                                          app_overrides={"credit_score": 500})
        assert bundle["application"]["status"] == "DENIED"

        resp = api.withdraw_application(
            bundle["application"]["id"],
            make_leasing_agent_headers(site["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)
        assert get_application(bundle["application"]["id"])["status"] == "DENIED"


class TestDepositBoundary:
    def test_deposit_exact_boundary_clears_conditions(self, api):
        """PRD §3.5: "Alternatively, a `LeasingAgent` or `PropertyManager` records a
        condition-clearing payment by submitting `deposit_paid_cents`; the payment is
        added to the accumulated paid total, and when the total reaches at least
        `required_deposit_cents` the application advances to `CONDITIONS_CLEARED`."
        PRD §3.5: "A payment that would leave the accumulated total below the
        requirement is rejected with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402)."
        PRD §3.5: "`APPROVED_WITH_CONDITIONS` sets it to two months of the snapshot
        rent;"

        Design: Corner/validations/deposit_exact_boundary_clears_conditions
        """
        site = setup_site()
        agent_id = site["agent"]["id"]
        bundle = add_leasable_application(
            site, decision="APPROVED_WITH_CONDITIONS",
            app_overrides={"annual_income_cents": 8000000, "credit_score": 650})
        application = bundle["application"]
        assert application["required_deposit_cents"] == 400000  # 2x the 200000 snapshot

        # One cent short: rejected and not accumulated.
        resp = api.clear_application_conditions(application["id"], 399999,
                                                make_leasing_agent_headers(agent_id))
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT, 402)
        after_fail = get_application(application["id"])
        assert after_fail["deposit_paid_cents"] == 0
        assert after_fail["status"] == "APPROVED_WITH_CONDITIONS"

        # Exactly the requirement: the application advances.
        cleared = validate_success(api.clear_application_conditions(
            application["id"], 400000, make_leasing_agent_headers(agent_id)))
        assert cleared["status"] == "CONDITIONS_CLEARED"
        assert cleared["deposit_paid_cents"] == 400000


class TestRescreenLoop:
    def test_rescreen_recomputes_recommendation_and_resets_deposit(self, api):
        """PRD §3.5: "A `PropertyManager` may re-screen the application with fresh
        `annual_income_cents` and `credit_score`, cycling it from
        `APPROVED_WITH_CONDITIONS` back to `SCREENING`: the recommendation is
        recomputed from the new figures against the unchanged
        `monthly_rent_snapshot_cents` — re-screening does not re-resolve the offer —
        `required_deposit_cents` resets to null, and the accumulated
        `deposit_paid_cents` resets to 0."

        Design: Difficulty/non_linear_state_machine/application_rescreen_loop_recomputes_recommendation
        """
        site = setup_site()
        bundle = add_leasable_application(
            site, decision="APPROVED_WITH_CONDITIONS",
            app_overrides={"annual_income_cents": 8000000, "credit_score": 650})
        application = bundle["application"]
        assert application["recommendation"] == "CONDITION"
        assert application["required_deposit_cents"] == 400000

        rescreened = rescreen_application(application["id"], 8000000, 720)
        assert rescreened["status"] == "SCREENING"
        assert rescreened["recommendation"] == "APPROVE", \
            "credit 720 with qualifying income flips CONDITION to APPROVE"
        assert rescreened["required_deposit_cents"] is None
        assert rescreened["deposit_paid_cents"] == 0
        assert rescreened["monthly_rent_snapshot_cents"] == 200000

    def test_rescreen_loop_replaces_conditional_deposit(self, api):
        """PRD §3.5: "A decision of `APPROVED` sets `required_deposit_cents` to one
        month of the snapshot rent; `APPROVED_WITH_CONDITIONS` sets it to two months
        of the snapshot rent; `DENIED` is terminal and sets no deposit."
        PRD §3.5: "A `PropertyManager` may re-screen the application with fresh
        `annual_income_cents` and `credit_score`, cycling it from
        `APPROVED_WITH_CONDITIONS` back to `SCREENING`: the recommendation is
        recomputed from the new figures against the unchanged
        `monthly_rent_snapshot_cents` — re-screening does not re-resolve the offer —
        `required_deposit_cents` resets to null, and the accumulated
        `deposit_paid_cents` resets to 0."

        Design: Difficulty/non_linear_state_machine/application_rescreen_loop_recomputes_recommendation
        """
        site = setup_site()
        bundle = add_leasable_application(
            site, decision="APPROVED_WITH_CONDITIONS",
            app_overrides={"annual_income_cents": 8000000, "credit_score": 650})
        application = bundle["application"]
        conditional_deposit = application["required_deposit_cents"]

        rescreen_application(application["id"], 8000000, 720)
        decided = decide_application(application["id"], "APPROVED")
        assert decided["status"] == "APPROVED"
        assert decided["required_deposit_cents"] == 200000
        assert conditional_deposit == 400000, \
            "the cycle replaced the persisted 2x conditional deposit with 1x standard"
