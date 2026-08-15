"""Sanctuary care plans, sponsorship funding, and end-of-life governance."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    assert_same_instant,
    sponsorship_payload, sanctuary_care_plan_payload,
    make_veterinarian_headers, make_sponsor_headers,
    get_horse, set_clock, register_sponsor, create_sponsorship,
    get_care_plan, create_care_plan, setup_sanctuary_horse,
    setup_released_horse, register_vet, propose_case, certify_case,
    authorize_case, get_case, create_stall, assign_stall, book_appointment,
    get_sponsor, get_sponsorship,
)

DIRECTOR = TEST_USERS["director_headers"]
INTAKE = TEST_USERS["intake_headers"]


class TestCarePlanVariantDivergence:
    def test_straight_line_plan_exact_values(self):
        """PRD §3.6: "Each breed class carries an assumed lifespan: 25 years for
        `LIGHT`, 22 for `DRAFT`, 28 for `PONY`. The plan's `projected_months` is
        the horse's remaining lifespan expressed in months — the breed lifespan
        in years minus the horse's `age_years`, multiplied by twelve."
        PRD §3.6: "Under the `STRAIGHT_LINE` variant, care costs a flat 38500
        cents per month: `monthly_cost_cents` is 38500 and
        `total_lifetime_cost_cents` is the projected months times 38500, with no
        mortality weighting — which is why its totals exceed the actuarial figure
        for young horses."

        Design: Difficulty/dual_variant_calc/care_plan_actuarial_vs_straight_line_divergence
        """
        bundle = setup_sanctuary_horse(
            {"name": "H", "sex": "GELDING", "age_years": 10,
             "breed_class": "LIGHT", "body_condition_score": 5})
        plan = create_care_plan(bundle["horse"]["id"], "STRAIGHT_LINE")
        assert plan["projected_months"] == 180, "(25 - 10) * 12"
        assert plan["monthly_cost_cents"] == 38500
        assert plan["total_lifetime_cost_cents"] == 6930000

    def test_actuarial_plan_diverges_and_supersedes(self):
        """PRD §3.6: "Under the `ACTUARIAL` variant, the projection walks month by
        month. The monthly cost depends on the horse's age band at the start of
        that month: 38500 cents under 15 years, 45200 from 15 through 19, 52800
        from 20 through 24, and 61500 at 25 or older."
        PRD §3.6: "The weighted monthly costs are summed, intermediate survival
        and cost values are never rounded, and only the final sum is rounded half
        up to integer cents to become `total_lifetime_cost_cents`;
        `monthly_cost_cents` is that total divided by the projected months,
        rounded half up to integer cents."
        PRD §3.6: "Creating a new plan supersedes the horse's existing plan in
        `DRAFT` or `APPROVED`, moving it to `SUPERSEDED`, and bumps the horse's
        `version`."

        Design: Difficulty/dual_variant_calc/care_plan_actuarial_vs_straight_line_divergence
        """
        bundle = setup_sanctuary_horse(
            {"name": "H", "sex": "GELDING", "age_years": 10,
             "breed_class": "LIGHT", "body_condition_score": 5})
        horse_id = bundle["horse"]["id"]
        plan1 = create_care_plan(horse_id, "STRAIGHT_LINE")
        plan2 = create_care_plan(horse_id, "ACTUARIAL")
        assert plan2["projected_months"] == 180
        assert plan2["total_lifetime_cost_cents"] == 6059405
        assert plan2["monthly_cost_cents"] == 33663
        assert plan2["total_lifetime_cost_cents"] != plan1["total_lifetime_cost_cents"], (
            "variants diverge on identical horse data")
        assert get_care_plan(plan1["id"])["status"] == "SUPERSEDED"


def _setup_approved_care_plan():
    bundle = setup_sanctuary_horse(
        {"name": "H", "sex": "GELDING", "age_years": 10})
    plan = create_care_plan(bundle["horse"]["id"], "STRAIGHT_LINE")
    get_success_data(api_client.approve_sanctuary_care_plan(
        plan["id"], DIRECTOR))
    return bundle, get_care_plan(plan["id"])


class TestCarePlanFundingBoundary:

    def test_coverage_one_cent_below_stays_partially_funded(self):
        """PRD §3.6: "`UNFUNDED` when coverage is zero, `PARTIALLY_FUNDED` when
        coverage is above zero but below `monthly_cost_cents`, and `FUNDED` when
        coverage reaches or exceeds `monthly_cost_cents`."
        PRD §3.6: "`funding_coverage_cents` is the sum of `monthly_pledge_cents`
        over the horse's `ACTIVE` sponsorships — `PLEDGED` and `LAPSED` pledges do
        not count — recomputed on every sponsorship mutation, starting from 0."

        Design: Difficulty/boundary_precision_check/care_plan_funding_exactly_at_monthly_cost
        """
        bundle, plan = _setup_approved_care_plan()
        horse_id = bundle["horse"]["id"]
        sp1 = register_sponsor(name="SP1", contact_email="s1@x.com")
        create_sponsorship(sp1["id"], horse_id, 20000, activate=True)
        sp2 = register_sponsor(name="SP2", contact_email="s2@x.com")
        create_sponsorship(sp2["id"], horse_id, 18499, activate=True)
        plan_after = get_care_plan(plan["id"])
        assert plan_after["funding_coverage_cents"] == 38499
        assert plan_after["funding_status"] == "PARTIALLY_FUNDED", (
            "one cent below monthly_cost_cents (38500) does not fund")

    def test_coverage_exactly_at_monthly_cost_funded(self):
        """PRD §3.6: "`UNFUNDED` when coverage is zero, `PARTIALLY_FUNDED` when
        coverage is above zero but below `monthly_cost_cents`, and `FUNDED` when
        coverage reaches or exceeds `monthly_cost_cents`."

        Design: Difficulty/boundary_precision_check/care_plan_funding_exactly_at_monthly_cost
        """
        bundle, plan = _setup_approved_care_plan()
        horse_id = bundle["horse"]["id"]
        sp1 = register_sponsor(name="SP1", contact_email="s1@x.com")
        create_sponsorship(sp1["id"], horse_id, 20000, activate=True)
        sp2 = register_sponsor(name="SP2", contact_email="s2@x.com")
        s2 = create_sponsorship(sp2["id"], horse_id, 18499, activate=True)
        get_success_data(api_client.cancel_sponsorship(s2["id"], {}, DIRECTOR))
        create_sponsorship(sp2["id"], horse_id, 18500, activate=True)
        plan_after = get_care_plan(plan["id"])
        assert plan_after["funding_coverage_cents"] == 38500
        assert plan_after["funding_status"] == "FUNDED", (
            "exact equality funds: coverage >= monthly_cost_cents")


class TestCoverageCompensation:
    def _setup_plan_with_pledge(self):
        bundle, plan = _setup_approved_care_plan()
        sp = register_sponsor(name="SP", contact_email="sp@x.com")
        sponsorship = create_sponsorship(sp["id"], bundle["horse"]["id"], 20000)
        return bundle, plan, sp, sponsorship

    def test_activate_lapse_reinstate_coverage_roundtrip(self):
        """PRD §3.6: "`funding_coverage_cents` is the sum of `monthly_pledge_cents`
        over the horse's `ACTIVE` sponsorships — `PLEDGED` and `LAPSED` pledges do
        not count — recomputed on every sponsorship mutation, starting from 0."
        PRD §3.6: "Lapsing (`ACTIVE` → `LAPSED`) is a `SanctuaryDirector`-only act
        and draws coverage back down by the pledge, since a lapsed pledge no
        longer counts. Reinstatement (`LAPSED` → `ACTIVE`) — again the owning
        sponsor or the director, with the same ownership and residency checks —
        adds the pledge back into coverage."

        Design: Difficulty/compensating_invariant/care_plan_coverage_compensation
        """
        bundle, plan, sp, s1 = self._setup_plan_with_pledge()
        assert get_care_plan(plan["id"])["funding_coverage_cents"] == 0
        assert get_care_plan(plan["id"])["funding_status"] == "UNFUNDED"

        get_success_data(api_client.activate_sponsorship(
            s1["id"], make_sponsor_headers(sp["id"])))
        mid = get_care_plan(plan["id"])
        assert mid["funding_coverage_cents"] == 20000
        assert mid["funding_status"] == "PARTIALLY_FUNDED"

        get_success_data(api_client.lapse_sponsorship(s1["id"], DIRECTOR))
        assert get_care_plan(plan["id"])["funding_coverage_cents"] == 0

        get_success_data(api_client.reinstate_sponsorship(
            s1["id"], make_sponsor_headers(sp["id"])))
        assert get_care_plan(plan["id"])["funding_coverage_cents"] == 20000

    def test_cancel_returns_coverage_to_zero(self):
        """PRD §3.6: "Cancellation accepts a sponsorship from `PLEDGED`, `ACTIVE`,
        or `LAPSED` into `CANCELLED`, is open to the owning sponsor or the
        director, accepts an optional free-text `cancellation_reason` (the
        euthanasia cascade uses the fixed value `HORSE_DECEASED`), recomputes
        sponsor status in all three branches, and subtracts the pledge from
        coverage only when the cancelled sponsorship had been `ACTIVE`."

        Design: Difficulty/compensating_invariant/care_plan_coverage_compensation
        """
        bundle, plan, sp, s1 = self._setup_plan_with_pledge()
        get_success_data(api_client.activate_sponsorship(
            s1["id"], make_sponsor_headers(sp["id"])))
        assert get_care_plan(plan["id"])["funding_coverage_cents"] == 20000
        get_success_data(api_client.cancel_sponsorship(s1["id"], {}, DIRECTOR))
        final = get_care_plan(plan["id"])
        assert final["funding_coverage_cents"] == 0
        assert final["funding_status"] == "UNFUNDED", (
            "cancel compensates activate exactly: coverage == SUM(ACTIVE pledges)")


class TestCarePlanExactMathAndOcc:
    def test_actuarial_age22_exact(self):
        """PRD §3.6: "Under the `ACTUARIAL` variant, the projection walks month by
        month. The monthly cost depends on the horse's age band at the start of
        that month: 38500 cents under 15 years, 45200 from 15 through 19, 52800
        from 20 through 24, and 61500 at 25 or older. Survival follows an annual
        rate chosen the same way: 0.97 under 20 years, 0.89 from 20 through 24,
        and 0.78 at 25 or older."
        PRD §3.6: "The plan's `projected_months` is the horse's remaining lifespan
        expressed in months — the breed lifespan in years minus the horse's
        `age_years`, multiplied by twelve."

        Design: Corner/calculations/actuarial_age22_exact
        """
        bundle = setup_sanctuary_horse(
            {"name": "H", "sex": "GELDING", "age_years": 22,
             "estimated_weight_lbs": 900, "body_condition_score": 4})
        plan = create_care_plan(bundle["horse"]["id"], "ACTUARIAL")
        assert plan["projected_months"] == 36, "(25 - 22) * 12"
        assert plan["total_lifetime_cost_cents"] == 1596322
        assert plan["monthly_cost_cents"] == 44342

    def test_occ_care_plan_stale_version(self):
        """PRD §2.6: "If the supplied value does not equal the horse's current
        `version` at the moment of the write, the request is rejected as stale
        with `ERR_STALE_HORSE_VERSION` (HTTP 412): the caller's view predates the
        latest plan supersession — or some other horse mutation — and must be
        refreshed before retrying."
        PRD §3.6: "Creating a new plan supersedes the horse's existing plan in
        `DRAFT` or `APPROVED`, moving it to `SUPERSEDED`, and bumps the horse's
        `version`."

        Design: Corner/cross_cutting_layers/occ_care_plan_stale_version
        """
        bundle = setup_sanctuary_horse(
            {"name": "H", "sex": "GELDING", "age_years": 10})
        horse_id = bundle["horse"]["id"]
        stale_version = get_horse(horse_id)["version"]

        plan_a = create_care_plan(horse_id, "STRAIGHT_LINE")
        resp = api_client.create_sanctuary_care_plan(
            sanctuary_care_plan_payload(horse_id, stale_version,
                                        variant="ACTUARIAL"),
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_STALE_HORSE_VERSION, 412)

        fresh_version = get_horse(horse_id)["version"]
        plan_b = get_success_data(api_client.create_sanctuary_care_plan(
            sanctuary_care_plan_payload(horse_id, fresh_version,
                                        variant="ACTUARIAL"),
            DIRECTOR), 201)
        assert plan_b["status"] == "DRAFT"
        assert plan_b["total_lifetime_cost_cents"] == 6059405
        assert get_care_plan(plan_a["id"])["status"] == "SUPERSEDED"


class TestSponsorshipPledgeMinimum:
    def test_pledge_minimum_boundary(self):
        """PRD §3.6: "`monthly_pledge_cents` must be at least 2500 cents
        (`ERR_PLEDGE_BELOW_MINIMUM`). The new sponsorship is `PLEDGED`, and the
        sponsor's status recomputes, turning `ACTIVE`."

        Design: Corner/validations/pledge_minimum_boundary
        """
        from test_helpers import intake_horse
        horse = intake_horse()  # QUARANTINE is still a resident posture
        sponsor = register_sponsor(name="SP", contact_email="sp@x.com")
        resp = api_client.create_sponsorship(
            sponsorship_payload(sponsor["id"], horse["id"],
                                monthly_pledge_cents=2499),
            make_sponsor_headers(sponsor["id"]))
        validate_error(resp, ApiErrorId.ERR_PLEDGE_BELOW_MINIMUM, 422)
        ok = validate_success(api_client.create_sponsorship(
            sponsorship_payload(sponsor["id"], horse["id"],
                                monthly_pledge_cents=2500),
            make_sponsor_headers(sponsor["id"])), 201)
        assert ok["status"] == "PLEDGED"


class TestEuthanasiaGovernance:
    def test_euthanasia_full_path_deceased_lockdown(self):
        """PRD §3.9: "Execution stamps `executed_at`, moves the case to
        `EXECUTED`, and fires the deceased cascade on the horse: the horse moves
        to `DECEASED`, its `prior_status` clears to null, its `current_location`
        becomes `NOT_APPLICABLE`, and its `version` increments; every sponsorship
        of the horse in `PLEDGED`, `ACTIVE`, or `LAPSED` is cancelled with
        `cancellation_reason` `HORSE_DECEASED`, each cancellation triggering a
        sponsor-status recompute; every care plan of the horse in `DRAFT` or
        `APPROVED` closes; every appointment of the horse in `REQUESTED` or
        `CONFIRMED` is cancelled with `cancellation_reason` `HORSE_DECEASED`; and
        its `ACTIVE` stall assignment ends with `end_date` set to the logical
        now."
        PRD §2.8: "`DECEASED` is a terminal state with total lockdown: no
        transitions leave it, and every mutation endpoint targeting a deceased
        horse fails with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/euthanasia_full_path_deceased_lockdown
        """
        vet1 = register_vet("Dr V1")
        vet2 = register_vet("Dr V2")
        bundle = setup_sanctuary_horse(
            {"name": "H", "age_years": 18, "body_condition_score": 4},
            vet_id=vet1)
        horse_id = bundle["horse"]["id"]
        plan = create_care_plan(horse_id, "STRAIGHT_LINE")
        sponsor = register_sponsor(name="SP", contact_email="sp@x.com")
        sponsorship = create_sponsorship(sponsor["id"], horse_id, 3000,
                                         activate=True)
        stall = create_stall(stall_code="M-09", barn_zone="MAIN_BARN")
        assignment = assign_stall(horse_id, stall["id"], "2026-08-15T00:00:00Z")
        appt = book_appointment(horse_id, vet1, service_type="VET_EXAM",
                                scheduled_start="2026-08-20T09:00:00Z",
                                scheduled_end="2026-08-20T09:45:00Z")

        case = propose_case(horse_id, vet1, suffering_score=5,
                            clinical_summary="chronic laminitis")
        certify_case(case["id"], vet2)
        authorize_case(case["id"])
        set_clock("2026-08-18T00:00:00Z")  # exactly authorized_at + 72h
        executed = validate_success(api_client.execute_euthanasia_case(
            case["id"], make_veterinarian_headers(vet1)))
        assert executed["status"] == "EXECUTED"
        assert_same_instant(executed["executed_at"], "2026-08-18T00:00:00Z")

        horse = get_horse(horse_id)
        assert horse["status"] == "DECEASED"
        assert horse["current_location"] == "NOT_APPLICABLE"

        s_after = get_sponsorship(sponsorship["id"])
        assert s_after["status"] == "CANCELLED"
        assert s_after["cancellation_reason"] == "HORSE_DECEASED"
        assert get_sponsor(sponsor["id"])["status"] == "INACTIVE"

        assert get_care_plan(plan["id"])["status"] == "CLOSED"

        appt_after = validate_success(
            api_client.get_care_service_appointment(appt["id"], INTAKE))
        assert appt_after["status"] == "CANCELLED"
        assert appt_after["cancellation_reason"] == "HORSE_DECEASED"

        sa_after = validate_success(
            api_client.get_stall_assignment(assignment["id"], INTAKE))
        assert sa_after["status"] == "ENDED"
        assert_same_instant(sa_after["end_date"], "2026-08-18T00:00:00Z")

        resp = api_client.patch_horse(
            horse_id, {"body_condition_score": 5}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_euthanasia_emergency_bypasses_cooling_off(self):
        """PRD §3.9: "When the case's `suffering_score` is 8 or higher and the
        certifier passes `emergency_attestation` as true, the case's
        `emergency_certified` flag becomes true — and only that combination sets
        it."
        PRD §3.9: "the case must be `AUTHORIZED` (`ERR_INVALID_STATE`), at least
        72 hours must have elapsed since `authorized_at` unless the case is
        `emergency_certified` — which bypasses the wait entirely —
        (`ERR_COOLING_OFF_ACTIVE`)"

        Design: Corner/state_machines/euthanasia_emergency_bypasses_cooling_off
        """
        vet1 = register_vet("Dr V1")
        vet2 = register_vet("Dr V2")
        bundle = setup_released_horse(
            "REHABILITATION",
            {"name": "H", "age_years": 19, "body_condition_score": 3},
            vet_id=vet1)
        horse_id = bundle["horse"]["id"]
        case = propose_case(horse_id, vet1, suffering_score=9,
                            clinical_summary="acute colic, unrelenting pain")
        certified = certify_case(case["id"], vet2, decision="CONCUR",
                                 emergency_attestation=True)
        assert certified["emergency_certified"] is True
        authorize_case(case["id"])
        # Clock unmoved since authorize: zero cooling-off elapsed.
        executed = validate_success(api_client.execute_euthanasia_case(
            case["id"], make_veterinarian_headers(vet2)))
        assert executed["status"] == "EXECUTED"
        assert get_horse(horse_id)["status"] == "DECEASED"

    def test_euthanasia_dissent_and_overturn_restore_prior_status(self):
        """PRD §3.9: "Dissenting — a `decision` of `DISSENT`, under the same
        duty-segregation guard — moves the case `PROPOSED` → `OVERRIDDEN` and
        restores the horse as described for overturn below."
        PRD §3.9: "overturning — with a `reason` recorded on the case as
        `overturn_reason` — moves a `PROPOSED` or `CERTIFIED` case to `OVERRIDDEN`
        (`ERR_INVALID_STATE` from any other state) and restores the horse."
        PRD §3.9: "Restoration reads the captured `prior_status`: the horse's
        `status` returns to it, `prior_status` clears to null, `current_location`
        is restored by prior status — `REHAB_PADDOCK` for `REHABILITATION`,
        `MAIN_PASTURE` for `ADOPTABLE`, `MAIN_PASTURE` for `ADOPTION_PENDING`,
        `SANCTUARY_PASTURE` for `SANCTUARY` — and the horse's `version`
        increments."

        Design: Corner/state_machines/euthanasia_dissent_and_overturn_restore_prior_status
        """
        vet1 = register_vet("Dr V1")
        vet2 = register_vet("Dr V2")
        bundle = setup_sanctuary_horse(
            {"name": "H", "sex": "GELDING", "age_years": 18,
             "estimated_weight_lbs": 950, "body_condition_score": 4},
            vet_id=vet1)
        horse_id = bundle["horse"]["id"]

        case1 = propose_case(horse_id, vet1, suffering_score=6,
                             clinical_summary="case one")
        overridden1 = certify_case(case1["id"], vet2, decision="DISSENT")
        assert overridden1["status"] == "OVERRIDDEN"
        horse = get_horse(horse_id)
        assert horse["status"] == "SANCTUARY"
        assert horse["prior_status"] is None
        assert horse["current_location"] == "SANCTUARY_PASTURE"

        case2 = propose_case(horse_id, vet1, suffering_score=7,
                             clinical_summary="case two")
        certify_case(case2["id"], vet2, decision="CONCUR")
        overturned = validate_success(api_client.overturn_euthanasia_case(
            case2["id"], {"reason": "board review disagrees"}, DIRECTOR))
        assert overturned["status"] == "OVERRIDDEN"
        horse2 = get_horse(horse_id)
        assert horse2["status"] == "SANCTUARY"
        assert horse2["prior_status"] is None
        assert horse2["current_location"] == "SANCTUARY_PASTURE"

    def test_duty_segregation_euthanasia_certify(self):
        """PRD §3.9: "Concurring — a `decision` of `CONCUR` — moves the case
        `PROPOSED` → `CERTIFIED`; the certifier's `X-User-ID` must differ from the
        case's `proposing_practitioner_id` (`ERR_DUTY_SEGREGATION`) and must
        reference an active practitioner of specialty `VETERINARIAN`
        (`ERR_FORBIDDEN`); the case records the certifier in
        `certifying_practitioner_id`."

        Design: Corner/validations/duty_segregation_euthanasia_certify
        """
        vet1 = register_vet("Dr V1")
        vet2 = register_vet("Dr V2")
        bundle = setup_released_horse(
            "REHABILITATION",
            {"name": "H", "sex": "GELDING", "age_years": 17,
             "body_condition_score": 4},
            vet_id=vet1)
        case = propose_case(bundle["horse"]["id"], vet1, suffering_score=6,
                            clinical_summary="navicular")
        resp = api_client.certify_euthanasia_case(
            case["id"], {"decision": "CONCUR", "emergency_attestation": False},
            make_veterinarian_headers(vet1))
        validate_error(resp, ApiErrorId.ERR_DUTY_SEGREGATION, 422)

        certified = validate_success(api_client.certify_euthanasia_case(
            case["id"], {"decision": "CONCUR", "emergency_attestation": False},
            make_veterinarian_headers(vet2)))
        assert certified["status"] == "CERTIFIED"
        assert certified["certifying_practitioner_id"] == vet2
