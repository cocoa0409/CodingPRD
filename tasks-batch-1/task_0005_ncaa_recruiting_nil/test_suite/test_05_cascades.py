"""Cascade claims: depth-2 cascade triggered by eligibility denial, and
depth-3 cascade triggered by sustaining a booster incident that pushes a
program to POSTSEASON_BAN (PRD §3.2, §3.4, §3.7).
"""
from test_helpers import (
    validate_success,
    setup_program_with_certified_athlete,
    create_draft_offer, send_offer,
    submit_certification, deny_certification,
    report_and_sustain_incident,
    create_program, create_student_athlete,
    setup_certified_athlete,
    TEST_USERS,
)


# ─── Difficulty: transitive_cascade / depth-3 booster-sustain cascade ──


def test_booster_sustain_postseason_ban_cascade_withdraws_sent_offers(api):
    """PRD §3.7: "If the recomputed `penalty_tier` is `POSTSEASON_BAN`,
    the system extends the cascade one further link: every
    `ScholarshipOffer` for that `program_id` whose `status` is currently
    `SENT` is auto-transitioned to `WITHDRAWN` by the system. Each such
    cascade-withdrawal decrements the program's `slots_committed` by 1
    (refreshing `updated_at` and incrementing the program's `version` on
    each), refreshes the offer's `updated_at`, and increments the
    offer's `version`."
    PRD §3.7: "Otherwise (a total of 15 or more), the tier is
    `POSTSEASON_BAN`."

    Design: Difficulty/transitive_cascade/booster_sustain_postseason_ban_cascade_depth3
    """
    # weight 15 from one incident with alleged_value >= 2,500,000 cents.
    program, athlete = setup_program_with_certified_athlete(
        sport_code="FOOTBALL", scholarship_slot_cap=85,
    )
    offer = create_draft_offer(program["id"], athlete["id"], annual_value_cents=6_000_000)
    send_offer(offer["id"], program["version"])

    program_after_send = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert program_after_send["slots_committed"] == 1
    assert program_after_send["penalty_tier"] == "NONE"

    report_and_sustain_incident(
        program_after_send, athlete,
        alleged_value_cents=5_000_000, booster_name="Big Donor",
    )

    final_program = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert final_program["penalty_tier"] == "POSTSEASON_BAN"
    assert final_program["slots_committed"] == 0

    final_offer = validate_success(
        api.get_scholarship_offer(offer["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert final_offer["status"] == "WITHDRAWN"


def test_booster_sustain_under_ban_floor_does_not_withdraw_offers(api):
    """PRD §3.7: "If the recomputed `penalty_tier` is `POSTSEASON_BAN`,
    the system extends the cascade one further link: every
    `ScholarshipOffer` for that `program_id` whose `status` is currently
    `SENT` is auto-transitioned to `WITHDRAWN` by the system."
    PRD §3.7: "Otherwise, if the total is strictly less than 5, the tier
    is `LEVEL_I`."

    Design: Difficulty/transitive_cascade/booster_sustain_postseason_ban_cascade_depth3
    """
    # A weight-3 incident leaves the tier at LEVEL_I; SENT offer must NOT
    # cascade-withdraw.
    program, athlete = setup_program_with_certified_athlete(
        sport_code="FOOTBALL", scholarship_slot_cap=85,
    )
    offer = create_draft_offer(program["id"], athlete["id"], annual_value_cents=6_000_000)
    send_offer(offer["id"], program["version"])
    program_after_send = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )

    report_and_sustain_incident(
        program_after_send, athlete, alleged_value_cents=100_000,
    )

    final_program = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert final_program["penalty_tier"] == "LEVEL_I"
    assert final_program["slots_committed"] == 1

    offer_after = validate_success(
        api.get_scholarship_offer(offer["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert offer_after["status"] == "SENT"


# ─── Difficulty: transitive_cascade / depth-2 eligibility-deny cascade ─


def test_eligibility_denial_cascades_sent_offer_to_withdrawn_and_releases_slot(api):
    """PRD §3.2: "Specifically: every `ScholarshipOffer` for that
    `student_athlete_id` whose `status` is `DRAFT` or `SENT`
    auto-transitions to `WITHDRAWN`; each cascade-driven withdrawal
    increments the offer's `version` and refreshes its `updated_at`."
    PRD §3.2: "For each offer whose prior status was `SENT`, the cascade
    also decrements the issuing program's `slots_committed` by 1,
    refreshes the program's `updated_at`, and increments the program's
    `version`"
    PRD §3.2: "When a certification transitions `PENDING → DENIED`, the
    athlete's `eligibility_status` flips to `INELIGIBLE` and every
    outstanding scholarship offer for that athlete is forcibly withdrawn
    by the system."

    Design: Difficulty/transitive_cascade/eligibility_deny_cascade_withdraws_offers_depth2
    """
    program, athlete = setup_program_with_certified_athlete(
        sport_code="BASEBALL", scholarship_slot_cap=11,
    )
    offer = create_draft_offer(program["id"], athlete["id"], annual_value_cents=4_000_000)
    send_offer(offer["id"], program["version"])
    program_after_send = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert program_after_send["slots_committed"] == 1

    # PRD §3.2 supports re-certification flow: a NEW certification submitted
    # for this already-certified athlete starts PENDING; denying it flips
    # the athlete to INELIGIBLE and cascades.
    cert2 = submit_certification(athlete["id"])
    deny_certification(cert2["id"], denial_reason="AMATEURISM_LOST")

    athlete_after = validate_success(
        api.get_student_athlete(athlete["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert athlete_after["eligibility_status"] == "INELIGIBLE"

    offer_after = validate_success(
        api.get_scholarship_offer(offer["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert offer_after["status"] == "WITHDRAWN"

    program_final = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert program_final["slots_committed"] == 0


def test_eligibility_denial_cascades_draft_offer_without_slot_change(api):
    """PRD §3.2: "For each offer whose prior status was `DRAFT`, no slot
    change occurs because a `DRAFT` offer was never committed in the
    first place."
    PRD §3.2: "every `ScholarshipOffer` for that `student_athlete_id`
    whose `status` is `DRAFT` or `SENT` auto-transitions to `WITHDRAWN`"

    Design: Difficulty/transitive_cascade/eligibility_deny_cascade_withdraws_offers_depth2
    """
    # Athlete is uncertified; their PENDING cert can be denied, cascading
    # a DRAFT offer to WITHDRAWN with no slot effect.
    program = create_program(sport_code="BASEBALL", school_name="DraftCascade U",
                             scholarship_slot_cap=11)
    athlete = create_student_athlete(sport_code="BASEBALL", full_name="Draft Athlete")

    draft = create_draft_offer(program["id"], athlete["id"], annual_value_cents=3_000_000)
    assert draft["status"] == "DRAFT"

    program_before = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert program_before["slots_committed"] == 0

    cert = submit_certification(athlete["id"])
    deny_certification(cert["id"], denial_reason="GPA_BELOW_MIN")

    offer_after = validate_success(
        api.get_scholarship_offer(draft["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert offer_after["status"] == "WITHDRAWN"

    program_after = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert program_after["slots_committed"] == 0
