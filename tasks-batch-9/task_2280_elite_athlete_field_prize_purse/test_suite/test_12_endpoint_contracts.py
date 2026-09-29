"""Endpoint shapes: the one partial update, and the two closing action endpoints."""
from test_helpers import (
    ApiErrorId,
    DIRECTOR,
    FINANCE,
    FINANCE_PAYER,
    LIAISON,
    SANCTIONING,
    TECHNICAL,
    api_client,
    certify_edition_results,
    certify_result,
    compute_awards,
    create_athlete_payload,
    disqualify_result,
    enter_result,
    get_success_data,
    list_awards,
    read_athlete,
    read_edition,
    read_result,
    setup_cleared_test,
    setup_edition_with_certified_results,
    setup_raced_edition,
    submit_record_package,
    validate_error,
    validate_paginated,
    validate_success,
)

ELITE_MALE_STANDARD = {"division": "ELITE", "gender": "MALE",
                       "max_qualifying_seconds": 8_100,
                       "bib_range_start": 11, "bib_range_end": 20}
SUB_ELITE_MALE_STANDARD = {"division": "SUB_ELITE", "gender": "MALE",
                           "max_qualifying_seconds": 9_000,
                           "bib_range_start": 200, "bib_range_end": 210}
OVERALL_MALE_FIRST = {"category": "OVERALL", "gender": "MALE", "place": 1,
                      "amount_cents": 1_000_000}
RACE_MORNING = "2026-11-01T09:00:00Z"


def _registered_athlete():
    """One athlete registered from the default clock with a full tax profile."""
    return api_client.create_athlete(
        create_athlete_payload(
            full_name="Crud Carla", country_code="KEN", gender="FEMALE",
            birth_date="1994-02-14", tax_residency_country="KEN",
            w8ben_on_file=False, treaty_withholding_bps=0, whereabouts_filed=True,
        ),
        DIRECTOR,
    )


def test_an_athlete_is_created_read_back_and_then_partially_updated():
    """Registration echoes what was sent, the read is identical, and the first patch
    increments the version once.

    PRD §2.5: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp
    refreshed on every mutation, and `version`, a system-managed integer that starts at 1
    on creation and increases by one on every mutation — including mutations that only
    change derived fields such as an edition's committed or allocated cents." PRD §3.2
    describes the partial update: "A `FinanceOfficer` may later revise the withholding
    profile — `tax_residency_country`, `w8ben_on_file` and `treaty_withholding_bps` are
    each independently updatable — which increments the athlete's `version`". PRD §2.4
    fixes the instant every stamp is taken from: the logical clock "begins at the fixed
    instant `2026-08-01T00:00:00Z`".

    Design: Corner/endpoints/corner_endpoint_athlete_crud_create_read_patch_reread
    """
    created = validate_success(_registered_athlete(), 201)
    assert created["full_name"] == "Crud Carla"
    assert created["country_code"] == "KEN"
    assert created["gender"] == "FEMALE"
    assert created["birth_date"] == "1994-02-14"
    assert created["tax_residency_country"] == "KEN"
    assert created["w8ben_on_file"] is False
    assert created["treaty_withholding_bps"] == 0
    assert created["whereabouts_filed"] is True
    assert created["version"] == 1
    assert created["created_at"] == "2026-08-01T00:00:00.000Z"
    assert created["updated_at"] == "2026-08-01T00:00:00.000Z"

    stored = read_athlete(created["id"], TECHNICAL)
    assert stored["full_name"] == "Crud Carla"
    assert stored["country_code"] == "KEN"
    assert stored["whereabouts_filed"] is True
    assert stored["version"] == 1

    patched = get_success_data(
        api_client.update_tax_profile(
            created["id"], {"w8ben_on_file": True, "treaty_withholding_bps": 500},
            FINANCE,
        )
    )
    assert patched["w8ben_on_file"] is True
    assert patched["treaty_withholding_bps"] == 500
    assert patched["version"] == 2

    reread = read_athlete(created["id"], FINANCE)
    assert reread["w8ben_on_file"] is True
    assert reread["treaty_withholding_bps"] == 500
    assert reread["tax_residency_country"] == "KEN", (
        "the patch carried no residency key, so the stored residency is untouched"
    )


def test_the_tax_profile_patch_cannot_reach_identity_or_availability():
    """A second patch moves only the residency and leaves everything else alone.

    PRD §3.2 scopes the update to three fields: "A `FinanceOfficer` may later revise the
    withholding profile — `tax_residency_country`, `w8ben_on_file` and
    `treaty_withholding_bps` are each independently updatable — which increments the
    athlete's `version`". Identity and availability are set at registration only: a
    `country_code` is required "as an ISO 3166-1 alpha-3 nationality code", and
    "`whereabouts_filed` also defaults to false and records whether the athlete has filed
    anti-doping whereabouts and availability information."

    Design: Corner/endpoints/corner_endpoint_athlete_crud_create_read_patch_reread
    """
    athlete = validate_success(_registered_athlete(), 201)
    get_success_data(
        api_client.update_tax_profile(
            athlete["id"], {"w8ben_on_file": True, "treaty_withholding_bps": 500},
            FINANCE,
        )
    )

    moved_abroad = get_success_data(
        api_client.update_tax_profile(
            athlete["id"], {"tax_residency_country": "GBR"}, FINANCE
        )
    )
    assert moved_abroad["tax_residency_country"] == "GBR"
    assert moved_abroad["w8ben_on_file"] is True
    assert moved_abroad["treaty_withholding_bps"] == 500
    assert moved_abroad["version"] == 3

    seen_by_the_liaison = read_athlete(athlete["id"], LIAISON)
    assert seen_by_the_liaison["full_name"] == "Crud Carla"
    assert seen_by_the_liaison["country_code"] == "KEN"
    assert seen_by_the_liaison["gender"] == "FEMALE"
    assert seen_by_the_liaison["birth_date"] == "1994-02-14"
    assert seen_by_the_liaison["whereabouts_filed"] is True


def _certified_field_with_two_open_claims():
    """Two ELITE finishers holding `CLAIMED` claims and one SUB_ELITE finisher whose
    claim was never raised."""
    return setup_edition_with_certified_results(
        [
            {"gun_seconds": 7_400, "net_seconds": 7_398,
             "athlete_overrides": {"country_code": "USA"},
             "performance_overrides": {"performance_seconds": 7_900}},
            {"gun_seconds": 7_500, "net_seconds": 7_498,
             "athlete_overrides": {"country_code": "USA"},
             "performance_overrides": {"performance_seconds": 7_910}},
            {"division": "SUB_ELITE", "gun_seconds": 8_600, "net_seconds": 8_598,
             "athlete_overrides": {"country_code": "USA"},
             "performance_overrides": {"performance_seconds": 8_800}},
        ],
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD, SUB_ELITE_MALE_STANDARD],
        race_clock=RACE_MORNING,
        name="Record Gate Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )


def test_a_package_needs_an_eligible_claim_and_may_be_lodged_only_once():
    """A sub-elite result is ineligible, the first elite package is stored, and the
    second is a state error.

    PRD §3.7: "A `TechnicalOfficial` lodges the ratification package with the
    sanctioning body, supplying a `sanctioning_submission_ref`; this is admitted only for
    a result whose `certification_status` is `CERTIFIED`, whose division is not
    `SUB_ELITE`, and whose claim stands in `CLAIMED` or in `REJECTED` — a rejected package
    may be corrected and lodged again, moving `REJECTED → SUBMITTED`. A claim in `NONE`
    was never raised and is refused with `ERR_RECORD_CLAIM_NOT_ELIGIBLE`, while a claim
    already `SUBMITTED` or already `RATIFIED` is refused earlier with
    `ERR_INVALID_RECORD_CLAIM_STATE`, per the precedence note in §2.11." PRD §3.7 also
    fixes the effect: "Lodging stores the reference and moves the claim
    `CLAIMED → SUBMITTED`".

    Design: Corner/endpoints/corner_endpoint_record_submission_conditional_action_gates
    """
    scenario = _certified_field_with_two_open_claims()
    alpha, _beta, gamma = scenario["entrants"]

    ineligible = api_client.submit_record_package(
        gamma["result"]["id"], {"sanctioning_submission_ref": "PKG-SUB-ELITE"}, TECHNICAL
    )
    validate_error(ineligible, ApiErrorId.ERR_RECORD_CLAIM_NOT_ELIGIBLE.value, 422)

    lodged = submit_record_package(alpha["result"]["id"], "PKG-A1")
    assert lodged["record_claim_status"] == "SUBMITTED"
    assert lodged["sanctioning_submission_ref"] == "PKG-A1"
    assert lodged["certification_status"] == "CERTIFIED"

    again = api_client.submit_record_package(
        alpha["result"]["id"], {"sanctioning_submission_ref": "PKG-A2"}, TECHNICAL
    )
    validate_error(again, ApiErrorId.ERR_INVALID_RECORD_CLAIM_STATE.value, 409)
    assert read_result(alpha["result"]["id"])["sanctioning_submission_ref"] == "PKG-A1"


def test_a_decision_needs_a_submitted_claim_and_a_dq_shuts_the_claim_down():
    """A decision on an unsubmitted claim is a state error, and after disqualification
    the certification precondition is what fails.

    PRD §3.7: "Both require the claim to be `SUBMITTED`, and ratification additionally
    requires the result to still be `CERTIFIED`; otherwise the request is refused with
    `ERR_INVALID_RECORD_CLAIM_STATE`." A disqualification closes the claim: "Because the
    result is disqualified, a record claim in `CLAIMED` or `SUBMITTED` moves to
    `REJECTED` — the cross-dimension coupling between the two state dimensions." A
    package may then only be lodged "for a result whose `certification_status` is
    `CERTIFIED`", and PRD §2.11 priority 8 names that failure
    `ERR_RESULT_NOT_CERTIFIED`. Results may be "listed and filtered on
    `race_edition_id`, `athlete_id`, `invitation_id`, `division`, `certification_status`
    and `record_claim_status`".

    Design: Corner/endpoints/corner_endpoint_record_submission_conditional_action_gates
    """
    scenario = _certified_field_with_two_open_claims()
    alpha, beta, _gamma = scenario["entrants"]
    submit_record_package(alpha["result"]["id"], "PKG-A1")

    premature = api_client.decide_record_claim(
        beta["result"]["id"],
        {"decision": "RATIFIED", "decision_note": "decided without a package"},
        SANCTIONING,
    )
    validate_error(premature, ApiErrorId.ERR_INVALID_RECORD_CLAIM_STATE.value, 409)

    struck = disqualify_result(beta["result"]["id"], "COURSE_CUTTING")
    assert struck["certification_status"] == "DISQUALIFIED"
    assert struck["dq_reason"] == "COURSE_CUTTING"
    assert struck["record_claim_status"] == "REJECTED"

    after_dq = api_client.submit_record_package(
        beta["result"]["id"], {"sanctioning_submission_ref": "PKG-B1"}, TECHNICAL
    )
    validate_error(after_dq, ApiErrorId.ERR_RESULT_NOT_CERTIFIED.value, 409)

    live, meta = validate_paginated(
        api_client.list_race_results(
            TECHNICAL, {"race_edition_id": scenario["edition"]["id"],
                        "record_claim_status": "SUBMITTED"}
        )
    )
    assert meta["total_count"] == 1
    assert live[0]["id"] == alpha["result"]["id"]


def _two_provisional_results_and_a_cleared_winner():
    """A `RACED` edition with two uncertified results and an in-competition clearance
    for the faster runner."""
    scenario = setup_raced_edition(
        [
            {"gun_seconds": 7_400, "net_seconds": 7_398,
             "athlete_overrides": {"country_code": "USA"},
             "performance_overrides": {"performance_seconds": 7_900}},
            {"gun_seconds": 7_500, "net_seconds": 7_498,
             "athlete_overrides": {"country_code": "USA"},
             "performance_overrides": {"performance_seconds": 7_910}},
        ],
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        race_clock=RACE_MORNING,
        name="Settle Gate Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=8_000_000,
        bonus_pool_cap_cents=0,
        course_record_male_seconds=7_000,
    )
    winner = scenario["entrants"][0]
    setup_cleared_test(
        winner["athlete"]["id"], scenario["edition"]["id"],
        test_type="IN_COMPETITION", window_start_at=RACE_MORNING,
        window_end_at="2026-11-01T18:00:00Z", sample_code="S-SG-A",
        collect_at=RACE_MORNING, collected_sample_ref="COC-SG-A",
    )
    for entrant in scenario["entrants"]:
        entrant["result"] = enter_result(
            scenario["edition"]["id"], entrant["invitation"]["id"],
            gun_seconds=entrant["gun_seconds"], net_seconds=entrant["net_seconds"],
        )
    return scenario


def test_the_edition_cannot_certify_while_one_result_is_still_provisional():
    """The pass refuses twice and succeeds only once both results are adjudicated.

    PRD §3.7: "It is admitted only when no result of the edition is still `PROVISIONAL`
    and at least one result is `CERTIFIED`; a still-provisional result or an empty
    certified set is refused with `ERR_RESULTS_NOT_ALL_ADJUDICATED`." The pass is
    described as "the `TechnicalOfficial`'s pass over the whole result set, moving it
    `RACED → RESULTS_CERTIFIED`".

    Design: Corner/endpoints/corner_endpoint_settle_purse_action_endpoint_preconditions
    """
    scenario = _two_provisional_results_and_a_cleared_winner()
    edition_id = scenario["edition"]["id"]
    winner, runner_up = scenario["entrants"]

    nothing_adjudicated = api_client.certify_results(edition_id, TECHNICAL)
    validate_error(nothing_adjudicated,
                   ApiErrorId.ERR_RESULTS_NOT_ALL_ADJUDICATED.value, 409)

    certify_result(winner["result"]["id"])
    one_still_open = api_client.certify_results(edition_id, TECHNICAL)
    validate_error(one_still_open,
                   ApiErrorId.ERR_RESULTS_NOT_ALL_ADJUDICATED.value, 409)

    certify_result(runner_up["result"]["id"])
    closed = certify_edition_results(edition_id)
    assert closed["status"] == "RESULTS_CERTIFIED"


def _one_computed_award_on_a_certified_edition():
    """Certify both results, close the edition and generate its single place prize."""
    scenario = _two_provisional_results_and_a_cleared_winner()
    edition_id = scenario["edition"]["id"]
    for entrant in scenario["entrants"]:
        certify_result(entrant["result"]["id"])
    certify_edition_results(edition_id)
    computed = compute_awards(edition_id)
    assert computed["purse_allocated_cents"] == 1_000_000
    assert computed["purse_unallocated_cents"] == 7_000_000
    awards, meta = list_awards({"race_edition_id": edition_id, "status": "COMPUTED"})
    assert meta["total_count"] == 1
    scenario["award"] = awards[0]
    return scenario


def test_the_purse_settles_only_once_its_single_award_has_been_paid():
    """`COMPUTED` blocks settlement, `APPROVED` still blocks it, and `PAID` releases it.

    PRD §3.8: "It is admitted only when every prize award of the edition stands in
    `PAID`, `VOID` or `CLAWBACK_PENDING` — an award still in `COMPUTED` or `APPROVED`
    blocks it with `ERR_AWARDS_NOT_ALL_SETTLED` — and only when no result of the edition
    still has a record claim in `SUBMITTED`." PRD §3.8 also fixes the two acts:
    "Approval is the first of two `FinanceOfficer` acts on an individual award and moves
    it `COMPUTED → APPROVED`." and "Payment moves the award `APPROVED → PAID`, supplies a
    `payment_reference` which is stored, records the acting operator in
    `paid_by_user_id` and stamps `paid_at` from the logical clock."

    Design: Corner/endpoints/corner_endpoint_settle_purse_action_endpoint_preconditions
    """
    scenario = _one_computed_award_on_a_certified_edition()
    edition_id = scenario["edition"]["id"]
    award_id = scenario["award"]["id"]

    while_computed = api_client.settle_purse(edition_id, FINANCE)
    validate_error(while_computed, ApiErrorId.ERR_AWARDS_NOT_ALL_SETTLED.value, 409)

    approved = get_success_data(api_client.approve_prize_award(award_id, FINANCE))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "fin-approve-1"

    while_approved = api_client.settle_purse(edition_id, FINANCE)
    validate_error(while_approved, ApiErrorId.ERR_AWARDS_NOT_ALL_SETTLED.value, 409)

    paid = get_success_data(
        api_client.pay_prize_award(award_id, {"payment_reference": "TRSY-SG-1"},
                                   FINANCE_PAYER)
    )
    assert paid["status"] == "PAID"
    assert paid["paid_by_user_id"] == "fin-pay-2"
    assert paid["paid_at"] == "2026-11-01T09:00:00.000Z"
    assert paid["payment_reference"] == "TRSY-SG-1"

    settled = get_success_data(api_client.settle_purse(edition_id, FINANCE))
    assert settled["status"] == "PURSE_SETTLED"
    assert settled["purse_allocated_cents"] == 1_000_000
    assert settled["purse_unallocated_cents"] == 7_000_000
    assert read_edition(edition_id)["status"] == "PURSE_SETTLED"


def test_the_officer_who_approved_the_award_may_not_pay_it():
    """Payment by the recorded approver is refused, and the award stays approved.

    PRD §3.8: "Payment may only be performed by a different operator than the one
    recorded in `approved_by_user_id`; the same identifier attempting both halves is
    refused with `ERR_SEGREGATION_OF_DUTIES`." PRD §2.11 priority 11 confirms the code
    and its status: "The `FinanceOfficer` paying an award must not be the operator
    recorded in `approved_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (403). This
    guards the pay operation only."

    Design: Corner/endpoints/corner_endpoint_settle_purse_action_endpoint_preconditions
    """
    scenario = _one_computed_award_on_a_certified_edition()
    award_id = scenario["award"]["id"]
    approved = get_success_data(api_client.approve_prize_award(award_id, FINANCE))
    assert approved["approved_by_user_id"] == "fin-approve-1"

    self_payment = api_client.pay_prize_award(
        award_id, {"payment_reference": "TRSY-SG-1"}, FINANCE
    )
    validate_error(self_payment, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    unpaid, _meta = list_awards({"race_edition_id": scenario["edition"]["id"],
                                "status": "APPROVED"})
    assert len(unpaid) == 1
    assert unpaid[0]["paid_by_user_id"] is None
    assert unpaid[0]["paid_at"] is None
