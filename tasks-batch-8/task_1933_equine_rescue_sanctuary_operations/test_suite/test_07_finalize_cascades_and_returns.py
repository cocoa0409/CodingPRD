"""Finalization cascades, follow-up visits, and the failed-follow-up return."""
import pytest

from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    assert_same_instant,
    appointment_payload,
    make_adopter_headers,
    get_horse, set_clock, register_adopter, register_sponsor,
    create_sponsorship, get_sponsor, get_sponsorship, submit_application,
    start_review, pass_home_check, get_application, create_stall, assign_stall,
    setup_approved_application, setup_finalized_adoption, finalize_at,
    follow_up_visits_for, feed_summary_entry,
)

INTAKE = TEST_USERS["intake_headers"]
OFFICER_1 = TEST_USERS["officer_1_headers"]
OFFICER_2 = TEST_USERS["officer_2_headers"]


def _setup_finalize_with_cascade_targets():
    """Horse (fee 100000) with ACTIVE 5000 sponsorship (sponsor's only), MAIN_BARN
    stall assignment, and a competing UNDER_REVIEW application; APPROVED + paid.
    Ordering matters: the sponsorship, stall assignment, and competing
    application are all created while the horse is still ADOPTABLE, before the
    primary application is approved."""
    from test_helpers import (
        setup_application_home_check_passed, approve_and_pay,
    )
    bundle = setup_application_home_check_passed(
        horse_overrides={"name": "H", "age_years": 8,
                         "training_level": "TRAINED_RIDDEN"})
    sponsor = register_sponsor(name="SP", contact_email="sp@x.com")
    sponsorship = create_sponsorship(sponsor["id"], bundle["horse"]["id"], 5000,
                                     activate=True)
    stall = create_stall(stall_code="M-01", barn_zone="MAIN_BARN")
    assignment = assign_stall(bundle["horse"]["id"], stall["id"],
                              "2026-08-15T00:00:00Z", "2026-08-20T00:00:00Z")
    ad2 = register_adopter(full_name="Ad Two", contact_email="a2@x.com",
                           experience_level="NOVICE", has_stall_facility=False)
    app2 = submit_application(ad2["id"], bundle["horse"]["id"],
                              "2026-08-22T00:00:00Z")
    start_review(app2["id"])
    bundle["application"] = approve_and_pay(bundle)
    assert bundle["application"]["quoted_fee_cents"] == 100000
    bundle.update({"sponsor": sponsor, "sponsorship": sponsorship,
                   "assignment": assignment, "app2": get_application(app2["id"])})
    return bundle


class TestFinalizeSponsorCascade:
    def test_finalize_cascades_horse_sponsorship_sponsor(self):
        """PRD §3.5: "it moves to `ADOPTED`, its `current_location` becomes
        `OFFSITE_ADOPTED`, its `active_application_id` clears to null, and its
        `version` increments."
        PRD §3.5: "Every sponsorship of the horse in `PLEDGED`, `ACTIVE`, or
        `LAPSED` completes with `completion_reason` `ADOPTED`, and each such
        completion recomputes the sponsor's standing"
        PRD §3.6: "`ACTIVE` while the sponsor holds at least one sponsorship in
        `PLEDGED`, `ACTIVE`, or `LAPSED`, and `INACTIVE` otherwise"

        Design: Difficulty/transitive_cascade/adoption_finalize_sponsor_cascade
        """
        bundle = _setup_finalize_with_cascade_targets()
        finalize_at(bundle, "2026-08-18T00:00:00Z")

        horse = get_horse(bundle["horse"]["id"])
        assert horse["status"] == "ADOPTED"
        assert horse["current_location"] == "OFFSITE_ADOPTED"
        assert horse["active_application_id"] is None

        sponsorship = get_sponsorship(bundle["sponsorship"]["id"])
        assert sponsorship["status"] == "COMPLETED"
        assert sponsorship["completion_reason"] == "ADOPTED"

        sponsor = get_sponsor(bundle["sponsor"]["id"])
        assert sponsor["status"] == "INACTIVE", (
            "sponsor's last non-terminal sponsorship completed")

    def test_finalize_autorejects_competitor_and_ends_stall(self):
        """PRD §3.5: "Every other application for the same horse sitting in
        `SUBMITTED`, `UNDER_REVIEW`, `HOME_CHECK_SCHEDULED`, or
        `HOME_CHECK_PASSED` is auto-rejected with `decision_reason`
        `SUPERSEDED_BY_FINALIZED_ADOPTION`."
        PRD §3.5: "Its `ACTIVE` stall assignment ends with `end_date` set to the
        application's `proposed_pickup_date`."

        Design: Difficulty/transitive_cascade/adoption_finalize_sponsor_cascade
        """
        bundle = _setup_finalize_with_cascade_targets()
        finalize_at(bundle, "2026-08-18T00:00:00Z")

        app2 = get_application(bundle["app2"]["id"])
        assert app2["status"] == "REJECTED"
        assert app2["decision_reason"] == "SUPERSEDED_BY_FINALIZED_ADOPTION"

        assignment = validate_success(api_client.get_stall_assignment(
            bundle["assignment"]["id"], INTAKE))
        assert assignment["status"] == "ENDED"
        assert_same_instant(assignment["end_date"], "2026-08-20T00:00:00Z")


class TestFailedFollowupReturnCascade:
    def _setup_adopted_then_failed_visit(self):
        bundle = setup_finalized_adoption(
            horse_overrides={"name": "H", "sex": "GELDING", "age_years": 8,
                             "training_level": "TRAINED_RIDDEN"})
        assert bundle["application"]["final_fee_cents"] == 100000
        visits = follow_up_visits_for(bundle["application"]["id"])
        day30 = next(v for v in visits if v["visit_type"] == "DAY_30")
        set_clock("2026-08-20T00:00:00Z")  # within 90 days of finalize
        get_success_data(api_client.complete_follow_up_visit(
            day30["id"], {"outcome": "FAILED",
                          "findings": "horse underweight, no shelter"},
            OFFICER_1))
        return bundle

    def test_failed_followup_returns_application_with_refund(self):
        """PRD §3.5: "Link one moves the application `FINALIZED` →
        `RETURN_COMPLETED`, records `decision_reason` as
        `RETURNED_AFTER_FAILED_FOLLOW_UP`, and computes `refund_cents`: when the
        logical now is within 90 days of `finalized_at`, the refund is half of
        `final_fee_cents` rounded half up; later than that, it is one quarter of
        `final_fee_cents` rounded half up."

        Design: Difficulty/transitive_cascade/failed_followup_return_cascade
        """
        bundle = self._setup_adopted_then_failed_visit()
        app = get_application(bundle["application"]["id"])
        assert app["status"] == "RETURN_COMPLETED"
        assert app["decision_reason"] == "RETURNED_AFTER_FAILED_FOLLOW_UP"
        assert app["refund_cents"] == 50000, "50% of 100000 within 90 days"

    def test_failed_followup_returns_horse_to_quarantine(self):
        """PRD §3.5: "Link two moves the horse `ADOPTED` → `REHABILITATION` and
        sets its `current_location` to `QUARANTINE_STALL`, incrementing
        `version`."
        PRD §3.5: "Link three auto-creates a fresh `ACTIVE` quarantine protocol
        for the returned horse with `min_days` 14, `reason` `AUTO_RETURN`, and
        `start_date` at now."
        PRD §3.5: "Link four cancels every remaining `SCHEDULED` follow-up visit
        of the same application, moving each to `CANCELLED`."

        Design: Difficulty/transitive_cascade/failed_followup_return_cascade
        """
        bundle = self._setup_adopted_then_failed_visit()
        horse = get_horse(bundle["horse"]["id"])
        assert horse["status"] == "REHABILITATION"
        assert horse["current_location"] == "QUARANTINE_STALL"

        from test_helpers import protocols_for
        protocols = protocols_for(horse["id"])
        assert len(protocols) == 2
        auto = protocols[-1]  # created_at ascending: the new protocol is last
        assert auto["status"] == "ACTIVE"
        assert auto["reason"] == "AUTO_RETURN"
        assert auto["min_days"] == 14

        visits = follow_up_visits_for(bundle["application"]["id"])
        remaining = [v for v in visits if v["visit_type"] in ("DAY_90", "DAY_180")]
        assert all(v["status"] == "CANCELLED" for v in remaining)


class TestFollowUpCreation:
    def test_followup_visits_auto_created_at_finalize(self):
        """PRD §3.5: "Finally, three follow-up visits are auto-created for the
        application: `visit_type` `DAY_30`, `DAY_90`, and `DAY_180`, each
        `SCHEDULED`, with `scheduled_date` set 30, 90, and 180 days after
        `finalized_at` respectively."

        Design: Corner/state_machines/followup_visits_auto_created_at_finalize
        """
        bundle = setup_finalized_adoption(
            horse_overrides={"name": "H", "age_years": 6})
        visits = follow_up_visits_for(bundle["application"]["id"])
        assert len(visits) == 3
        assert all(v["status"] == "SCHEDULED" for v in visits)
        by_type = {v["visit_type"]: v["scheduled_date"] for v in visits}
        expected = {
            "DAY_30": "2026-09-17T00:00:00Z",
            "DAY_90": "2026-11-16T00:00:00Z",
            "DAY_180": "2027-02-14T00:00:00Z",
        }
        assert set(by_type) == set(expected)
        for visit_type, expected_iso in expected.items():
            assert_same_instant(by_type[visit_type], expected_iso)

    def test_followup_visit_passed_simple(self):
        """PRD §3.5: "An `AdoptionOfficer` completes a `SCHEDULED` visit — the
        owning application must be `FINALIZED` (`ERR_INVALID_STATE`) — supplying
        an `outcome` of `PASSED` or `FAILED` with optional `findings`; the visit
        moves to `COMPLETED` with `completed_at` stamped. A `PASSED` outcome ends
        there."

        Design: Corner/state_machines/followup_visit_passed_simple
        """
        bundle = setup_finalized_adoption(
            horse_overrides={"name": "H", "age_years": 6})
        visits = follow_up_visits_for(bundle["application"]["id"])
        day30 = next(v for v in visits if v["visit_type"] == "DAY_30")
        set_clock("2026-09-17T00:00:00Z")
        done = validate_success(api_client.complete_follow_up_visit(
            day30["id"], {"outcome": "PASSED", "findings": "horse thriving"},
            OFFICER_1))
        assert done["status"] == "COMPLETED"
        assert done["outcome"] == "PASSED"

        app = get_application(bundle["application"]["id"])
        assert app["status"] == "FINALIZED"
        assert get_horse(bundle["horse"]["id"])["status"] == "ADOPTED"
        remaining = [v for v in follow_up_visits_for(bundle["application"]["id"])
                     if v["id"] != day30["id"]]
        assert len(remaining) == 2
        assert all(v["status"] == "SCHEDULED" for v in remaining)


class TestPairFinalize:
    def test_pair_finalize_adopts_both_horses(self):
        """PRD §3.5: "When the pair flag is set, the bonded companion moves
        `ADOPTABLE` → `ADOPTED` with the same sponsorship and stall cascades."

        Design: Corner/state_machines/pair_finalize_adopts_both_horses
        """
        from test_helpers import (
            register_vet, intake_horse, complete_medical_pass,
            clear_active_protocol, release_horse,
        )
        vet_id = register_vet()
        h2 = intake_horse(name="H2", sex="GELDING", estimated_weight_lbs=800,
                          age_years=20, body_condition_score=5,
                          training_level="GREEN")
        complete_medical_pass(h2["id"], at="2026-08-14T12:00:00Z")
        clear_active_protocol(h2["id"], vet_id, at="2026-08-15T00:00:00Z")
        release_horse(h2["id"], "ADOPTABLE")
        h1 = intake_horse(name="H1", sex="MARE", estimated_weight_lbs=1000,
                          age_years=8, body_condition_score=5,
                          training_level="TRAINED_RIDDEN",
                          bonded_companion_id=h2["id"])
        complete_medical_pass(h1["id"], at="2026-08-27T12:00:00Z")
        clear_active_protocol(h1["id"], vet_id, at="2026-08-29T00:00:00Z")
        release_horse(h1["id"], "ADOPTABLE")

        sponsor = register_sponsor(name="SP", contact_email="sp@x.com")
        sponsorship = create_sponsorship(sponsor["id"], h2["id"], 4000,
                                         activate=True)

        adopter = register_adopter(full_name="Ad Pair", contact_email="ap@x.com")
        app = submit_application(adopter["id"], h1["id"],
                                 pickup="2026-09-05T00:00:00Z", pair=True)
        start_review(app["id"])
        pass_home_check(app["id"], scheduled_date="2026-08-29T10:00:00Z")
        approved = get_success_data(api_client.approve_application(
            app["id"], OFFICER_2))
        assert approved["quoted_fee_cents"] == 93750
        get_success_data(api_client.pay_application_fee(
            app["id"], {"amount_cents": 93750},
            make_adopter_headers(adopter["id"])))

        set_clock("2026-09-01T00:00:00Z")  # exactly approved_at + 72h
        finalized = validate_success(api_client.finalize_application(
            app["id"], OFFICER_2))
        assert finalized["status"] == "FINALIZED"

        assert get_horse(h1["id"])["status"] == "ADOPTED"
        h2_after = get_horse(h2["id"])
        assert h2_after["status"] == "ADOPTED"
        assert h2_after["current_location"] == "OFFSITE_ADOPTED"
        s2 = get_sponsorship(sponsorship["id"])
        assert s2["status"] == "COMPLETED"
        assert s2["completion_reason"] == "ADOPTED"


class TestFinalizedTerminalAndFeedExclusion:
    def test_finalized_terminal_resident_gating_and_feed_exclusion(self):
        """PRD §2.8: "The same lockdown logic applies to the terminal states of
        the other state machines — a `COMPLETED` or `CANCELLED` appointment, home
        check, or follow-up visit; a `COMPLETED` evaluation; a `CLEARED` protocol;
        an `ENDED` stall assignment; a `FINALIZED`, `RETURN_COMPLETED`,
        `REJECTED`, or `WITHDRAWN` application; a `COMPLETED` or `SUPERSEDED`
        rehabilitation plan; a `SUPERSEDED` or `CLOSED` care plan; a `COMPLETED`
        or `CANCELLED` sponsorship; a `RECEIVED` purchase order; a `COMPLETED` or
        `NO_SHOW` shift; an `EXECUTED` or `OVERRIDDEN` euthanasia case — none
        accepts further transitions, and attempts fail with `ERR_INVALID_STATE`."
        PRD §2.8: "Resident posture gates the booking of care appointments, the
        confirmation of those appointments, and the creation, activation, and
        reinstatement of sponsorships; breaches surface as
        `ERR_HORSE_NOT_RESIDENT`."
        PRD §3.7: "Demand comes from residents only — horses in every status
        except `ADOPTED` and `DECEASED`."
        PRD §3.7: "When a feed type's daily demand is zero, both figures are null
        and `reorder_required` is false."

        Design: Corner/state_machines/finalized_terminal_resident_gating_and_feed_exclusion
        """
        bundle = setup_approved_application(
            horse_overrides={"name": "H", "age_years": 8,
                             "body_condition_score": 3,
                             "training_level": "TRAINED_RIDDEN"})
        before = feed_summary_entry("GRASS_HAY")
        assert before["daily_demand_lbs"] == pytest.approx(8.75, abs=1e-9)

        finalize_at(bundle, "2026-08-18T00:00:00Z")
        app_id = bundle["application"]["id"]

        resp_reject = api_client.reject_application(
            app_id, {"reason": "second thoughts"}, OFFICER_1)
        validate_error(resp_reject, ApiErrorId.ERR_INVALID_STATE, 409)
        resp_withdraw = api_client.withdraw_application(
            app_id, {}, make_adopter_headers(bundle["adopter"]["id"]))
        validate_error(resp_withdraw, ApiErrorId.ERR_INVALID_STATE, 409)

        resp_book = api_client.create_care_service_appointment(
            appointment_payload(bundle["horse"]["id"], bundle["vet_id"],
                                service_type="VET_EXAM",
                                scheduled_start="2026-08-19T09:00:00Z",
                                scheduled_end="2026-08-19T09:45:00Z"),
            INTAKE)
        validate_error(resp_book, ApiErrorId.ERR_HORSE_NOT_RESIDENT, 409)

        after = feed_summary_entry("GRASS_HAY")
        assert after["daily_demand_lbs"] == pytest.approx(0.0, abs=1e-9)
        assert after["days_of_supply_tight"] is None
        assert after["days_of_supply_committed"] is None
        assert after["reorder_required"] is False
