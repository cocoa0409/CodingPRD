"""Individual notification: the gates, the notice period and manager scripting."""

from test_helpers import (
    ALICE,
    BEN,
    BEN_CLASS_B,
    CARLA,
    DAN,
    TEST_USERS,
    ApiErrorId,
    federal_rule_payload,
    ny_state_rule_payload,
    price_offer,
    read_analysis,
    read_plan,
    read_selection,
    read_site,
    rescind,
    run_and_clear_analysis,
    setup_approved_scenario,
    setup_offer_ready_scenario,
    setup_selected_scenario,
    submit_for_review,
    validate_error,
    validate_success,
)

LEAD = TEST_USERS["lead_headers"]
NY_RULES = (federal_rule_payload(), ny_state_rule_payload())


class TestNoticeDeliveryRequiresAnApprovedPlan:
    """A selection-local green light is not enough; the parent plan gates it."""

    def test_delivery_is_refused_while_the_plan_sits_in_legal_review(self, api):
        """PRD 3.7: "Before a notice may be delivered for a selection, three
        conditions must hold: the plan's `approval_status` must be `APPROVED`,
        failing which the request is refused with `ERR_PLAN_NOT_APPROVED`; the
        plan's latest adverse-impact analysis must stand in `CLEARED` status,
        failing which it is refused with `ERR_IMPACT_ANALYSIS_NOT_CLEARED`; and
        the delivery must satisfy the notice-period and scripting rules below."

        Design: Difficulty/cross_entity_state_dependency/notice_delivery_blocked_while_plan_is_not_approved
        """
        scn = setup_selected_scenario(
            people=(ALICE, BEN_CLASS_B), propose_only_indexes=(1,)
        )
        run_and_clear_analysis(scn["plan"]["id"])
        submit_for_review(scn["plan"]["id"])

        response = api.deliver_notice(
            scn["selection_by_index"][0]["id"],
            {"script_code": "MANAGER_SCRIPT_STANDARD"},
            LEAD,
        )
        validate_error(response, ApiErrorId.ERR_PLAN_NOT_APPROVED.value)
        assert response.status_code == 422
        assert read_plan(scn["plan"]["id"])["approval_status"] == "IN_LEGAL_REVIEW"

    def test_the_refused_delivery_leaves_the_selection_untouched(self, api):
        """PRD 3.7: "Recording it moves `notice_status` from `NOT_DELIVERED` to
        `DELIVERED`, stamps `notice_delivered_utc` from the logical clock,
        records the supplied script as `notice_script_code`, and derives
        `notice_days_before_separation` as the number of whole calendar days from
        the date part of `notice_delivered_utc` to the selection's
        `proposed_separation_date`."
        PRD 3.7: "Before a notice may be delivered for a selection, three
        conditions must hold: the plan's `approval_status` must be `APPROVED`,
        failing which the request is refused with `ERR_PLAN_NOT_APPROVED`; the
        plan's latest adverse-impact analysis must stand in `CLEARED` status,
        failing which it is refused with `ERR_IMPACT_ANALYSIS_NOT_CLEARED`; and
        the delivery must satisfy the notice-period and scripting rules below."

        Design: Difficulty/cross_entity_state_dependency/notice_delivery_blocked_while_plan_is_not_approved
        """
        scn = setup_selected_scenario(
            people=(ALICE, BEN_CLASS_B), propose_only_indexes=(1,)
        )
        run_and_clear_analysis(scn["plan"]["id"])
        submit_for_review(scn["plan"]["id"])
        selection_id = scn["selection_by_index"][0]["id"]

        api.deliver_notice(
            selection_id, {"script_code": "MANAGER_SCRIPT_STANDARD"}, LEAD
        )

        selection = read_selection(selection_id)
        assert selection["status"] == "SELECTED"
        assert selection["notice_status"] == "NOT_DELIVERED"
        assert selection["notice_delivered_utc"] is None
        assert selection["notice_script_code"] is None
        assert selection["notice_days_before_separation"] is None


class TestClearanceGateOutranksTheNoticePeriodGate:
    """One delivery breaches both rules; the lower ladder number decides."""

    @staticmethod
    def _scenario():
        scn = setup_approved_scenario(
            people=(ALICE, BEN, CARLA, DAN),
            state_code="NY",
            rules=NY_RULES,
            select_indexes=(0, 2, 3),
            propose_only_indexes=(),
            via_batch=True,
            separation_date="2026-08-25",
            plan_name="2026 Q3 NY Restructuring",
            decisional_unit_name="NY HQ Operations",
            justification="Three eliminated roles documented.",
        )
        rescind(
            scn["selection_by_index"][3]["id"],
            "Reassigned to a retained requisition.",
        )
        return scn

    def test_the_stale_analysis_decides_the_response(self, api):
        """PRD 2.6: "When a request violates more than one rule, exactly one
        error is returned, and it is always the violation with the lowest
        priority number in the ladder below. This ordering is normative: a test
        that supplies a request breaching both rule 12 and rule 23 must receive
        rule 12's error identifier."
        PRD 2.6: "Adverse-impact clearance — `ERR_IMPACT_ANALYSIS_NOT_CLEARED`
        (422) on `POST /reduction-plans/{id}/legal-decision` carrying the approve
        decision, on `POST /selections/{id}/deliver-notice`, and on
        `POST /severance-offers`."
        PRD 2.6: "Sufficient individual notice period —
        `ERR_NOTICE_PERIOD_INSUFFICIENT` (422) on
        `POST /selections/{id}/deliver-notice`."

        Design: Difficulty/priority_pair_validation_conflict/safety_check_beats_temporal_check_on_notice_delivery_with_stale_analysis
        """
        scn = self._scenario()

        response = api.deliver_notice(
            scn["selection_by_index"][0]["id"],
            {"script_code": "MANAGER_SCRIPT_UNION"},
            LEAD,
        )
        error = validate_error(
            response, ApiErrorId.ERR_IMPACT_ANALYSIS_NOT_CLEARED.value
        )
        assert response.status_code == 422
        assert error["error_id"] != ApiErrorId.ERR_NOTICE_PERIOD_INSUFFICIENT.value

    def test_both_violations_really_are_live_at_the_moment_of_the_call(self, api):
        """PRD 3.5: "A cleared analysis does not stay cleared through changes to
        the underlying pool: whenever a selection of the plan subsequently enters
        `SELECTED`, `EXEMPTED` or `RESCINDED`, every `CLEARED` analysis of the
        plan moves `CLEARED → STALE` with its `version` incremented by 1."
        PRD 3.7: "When `notice_days_before_separation` is less than the site's
        `required_notice_days`, the delivery is refused with
        `ERR_NOTICE_PERIOD_INSUFFICIENT` — unless the caller passes
        `acknowledge_short_notice` as true, in which case the delivery is
        accepted and the selection's `short_notice_acknowledged` flag is set to
        true to record that the shortfall was taken knowingly."

        Design: Difficulty/priority_pair_validation_conflict/safety_check_beats_temporal_check_on_notice_delivery_with_stale_analysis
        """
        scn = self._scenario()

        assert read_analysis(scn["analysis"]["id"])["status"] == "STALE"
        site = read_site(scn["site"]["id"])
        assert site["state_loss_count"] == 2
        assert site["required_notice_days"] == 90, (
            "delivery on 2026-08-01 for a 2026-08-25 separation is only 24 days"
        )

        api.deliver_notice(
            scn["selection_by_index"][0]["id"],
            {"script_code": "MANAGER_SCRIPT_UNION"},
            LEAD,
        )
        assert (
            read_selection(scn["selection_by_index"][0]["id"])["notice_status"]
            == "NOT_DELIVERED"
        )


def test_delivery_at_exactly_the_required_days_needs_no_acknowledgement(api):
    """PRD 3.7: "A delivery at or beyond the required number of days is always
    accepted and leaves `short_notice_acknowledged` false."
    PRD 3.7: "Recording it moves `notice_status` from `NOT_DELIVERED` to
    `DELIVERED`, stamps `notice_delivered_utc` from the logical clock, records
    the supplied script as `notice_script_code`, and derives
    `notice_days_before_separation` as the number of whole calendar days from the
    date part of `notice_delivered_utc` to the selection's
    `proposed_separation_date`."

    Design: Corner/validations/notice_delivered_at_exactly_the_required_days_needs_no_acknowledgement
    """
    scn = setup_approved_scenario(
        people=(ALICE, BEN, CARLA),
        state_code="NY",
        rules=NY_RULES,
        select_indexes=(0, 2),
        propose_only_indexes=(),
        via_batch=True,
        separation_date="2026-10-30",
        plan_name="2026 Q4 NY Restructuring",
        decisional_unit_name="NY HQ Operations",
    )
    assert read_site(scn["site"]["id"])["required_notice_days"] == 90

    delivered = validate_success(
        api.deliver_notice(
            scn["selection_by_index"][0]["id"],
            {"script_code": "MANAGER_SCRIPT_UNION"},
            LEAD,
        )
    )
    assert delivered["notice_days_before_separation"] == 90
    assert delivered["short_notice_acknowledged"] is False
    assert delivered["notice_status"] == "DELIVERED"
    assert delivered["notice_delivered_utc"] == "2026-08-01T00:00:00.000Z"
    assert delivered["notice_script_code"] == "MANAGER_SCRIPT_UNION"


def test_union_notice_states_accept_only_the_union_script(api):
    """PRD 3.7: "Whenever the state mini-WARN rule applying to that employee's
    site lists `UNION_NOTICE` among its `required_content_codes`, the only
    acceptable `script_code` is `MANAGER_SCRIPT_UNION`; a delivery using either
    of the other two scripts in such a jurisdiction is refused with
    `ERR_SCRIPT_JURISDICTION_MISMATCH`. Where the state rule does not require
    union notice, all three scripts are acceptable."

    Design: Corner/errors/error_script_jurisdiction_mismatch_in_a_union_notice_state
    """
    scn = setup_approved_scenario(
        people=(ALICE, BEN_CLASS_B),
        state_code="NY",
        rules=NY_RULES,
        select_indexes=(0,),
        propose_only_indexes=(1,),
        plan_name="2026 Q4 NY Restructuring",
        decisional_unit_name="NY HQ Operations",
    )
    selection_id = scn["selection_by_index"][0]["id"]

    refused = api.deliver_notice(
        selection_id, {"script_code": "MANAGER_SCRIPT_STANDARD"}, LEAD
    )
    validate_error(refused, ApiErrorId.ERR_SCRIPT_JURISDICTION_MISMATCH.value)
    assert refused.status_code == 422

    accepted = validate_success(
        api.deliver_notice(selection_id, {"script_code": "MANAGER_SCRIPT_UNION"}, LEAD)
    )
    assert accepted["notice_status"] == "DELIVERED"
    assert accepted["notice_script_code"] == "MANAGER_SCRIPT_UNION"
    assert read_site(scn["site"]["id"])["required_notice_days"] == 0
    assert read_selection(selection_id)["notice_days_before_separation"] == 122


def test_acknowledged_short_notice_prices_the_notice_pay_offset(api):
    """PRD 3.7: "When `notice_days_before_separation` is less than the site's
    `required_notice_days`, the delivery is refused with
    `ERR_NOTICE_PERIOD_INSUFFICIENT` — unless the caller passes
    `acknowledge_short_notice` as true, in which case the delivery is accepted
    and the selection's `short_notice_acknowledged` flag is set to true to record
    that the shortfall was taken knowingly."
    PRD 3.8: "`notice_shortfall_days` is the site's `required_notice_days` less
    the selection's `notice_days_before_separation`, with any negative result
    reported as 0; where the site is not triggered its requirement is 0, and
    where the notice is undelivered the actual figure is treated as 0."
    PRD 3.8: "The daily rate is the weekly rate divided by 7 and rounded half up
    to whole cents"

    Design: Corner/calculations/acknowledged_short_notice_drives_the_notice_pay_offset
    """
    scn = setup_offer_ready_scenario(
        people=(ALICE, BEN, CARLA),
        state_code="NY",
        rules=NY_RULES,
        select_indexes=(0, 2),
        propose_only_indexes=(),
        via_batch=True,
        separation_date="2026-09-15",
        plan_name="2026 Q3 NY Restructuring",
        decisional_unit_name="NY HQ Operations",
        justification="Compressed timeline documented.",
        notify_indexes=(),
    )
    assert read_site(scn["site"]["id"])["required_notice_days"] == 90
    selection_id = scn["selection_by_index"][0]["id"]

    delivered = validate_success(
        api.deliver_notice(
            selection_id,
            {"script_code": "MANAGER_SCRIPT_UNION", "acknowledge_short_notice": True},
            LEAD,
        )
    )
    assert delivered["notice_days_before_separation"] == 45
    assert delivered["short_notice_acknowledged"] is True

    offer = price_offer(selection_id, "STANDARD")
    assert offer["notice_shortfall_days"] == 45
    assert offer["weekly_rate_cents"] == 167308
    assert offer["base_severance_cents"] == 2676928
    assert offer["notice_pay_offset_cents"] == 1075545, "23901 cents a day times 45"
    assert offer["benefit_subsidy_months"] == 9
    assert offer["benefit_subsidy_cents"] == 526500
    assert offer["outplacement_fee_cents"] == 350000
    assert offer["total_separation_cost_cents"] == 4628973
