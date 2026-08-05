"""The encounter's two independent axes and the employer-visible projection."""

from test_helpers import (
    ApiErrorId,
    api_client,
    add_completed_visit,
    amend_encounter,
    assert_employer_disclosure_payload,
    assert_visit,
    grant_authorization,
    read_visit,
    release_disclosure,
    revoke_authorization,
    setup_clinic,
    setup_completed_visit,
    validate_error,
    validate_success,
)


def test_completion_forks_chargeable_party_on_visit_type():
    """PRD §3.5: "Completion is where the visit learns who pays, and the answer forks
    cleanly on `visit_type`. A `PRIMARY_CARE` encounter sets `chargeable_party` to
    `HEALTH_PLAN`; an `OCC_HEALTH` encounter sets it to `EMPLOYER_DIRECT`, because the
    employer commissioned it directly; a `WELLNESS` encounter sets it to
    `WELLNESS_BUDGET`. Alongside it the server writes `consumes_benefit_entitlement`,
    which is true **only** for `PRIMARY_CARE` — occupational-health and wellness
    encounters deliberately do not draw down the member's health-plan benefit, which
    is a large part of why employers run them on site. Completion also refreshes the
    participant's `completed_visit_count`."
    PRD §3.5: "A `PRIMARY_CARE` encounter moves `WALLED → NOT_DISCLOSABLE`
    **regardless of authorization** — primary care is never disclosable to an employer
    at the individual level, and a participant's grant cannot make it so; from that
    point the employer disclosure read on that visit is refused with
    `ERR_DISCLOSURE_NOT_PERMITTED` forever."
    PRD §3.5: "An `OCC_HEALTH` or `WELLNESS` encounter completed while the
    participant's `authorization_status` is `NOT_REQUESTED` or `REVOKED` moves
    `WALLED → SUPPRESSED` instead, and no disclosure channel is ever opened for that
    visit — a later grant does not reopen it."

    Design: Corner/entities/visit_computed_chargeable_party_forks_on_visit_type
    """
    world = setup_completed_visit(
        visit_type="PRIMARY_CARE",
        employer={"legal_name": "Payer Co", "employer_code": "PAY"},
        site={"site_name": "PAY Clinic"},
        eligibility={"subscriber_external_id": "S-3201", "member_external_id": "M-3201"},
        participant={"display_name": "Pay Tester"},
        completion={"clinical_note": "Routine primary care"},
    )
    primary = world.visit
    assert_visit(primary)
    assert primary["chargeable_party"] == "HEALTH_PLAN"
    assert primary["consumes_benefit_entitlement"] is True
    assert primary["disclosure_status"] == "NOT_DISCLOSABLE"

    _, occ = add_completed_visit(
        world,
        world.participant_id,
        "2026-06-08T09:30:00Z",
        "OCC_HEALTH",
        fitness_conclusion="FIT_FOR_DUTY",
    )
    assert occ["chargeable_party"] == "EMPLOYER_DIRECT"
    assert occ["consumes_benefit_entitlement"] is False
    assert occ["disclosure_status"] == "SUPPRESSED", (
        "authorization was never granted, so the occupational-health encounter is suppressed"
    )

    participant = validate_success(
        api_client.get_participant(world.participant_id, world.employer_headers)
    )
    assert participant["authorization_status"] == "NOT_REQUESTED"
    assert participant["completed_visit_count"] == 2


def test_starting_a_completed_visit_is_rejected():
    """PRD §3.5: "Starting the encounter moves it `CHECKED_IN → IN_PROGRESS` and has
    no effect on anything outside the visit."
    PRD §2.6: "The target resource stands in a state from which the requested
    transition is declared in this document, and the transition's own caps are
    respected — the alternative-standard reassignment cap, the visit amendment cap and
    the reporting-period restatement cap all report here. Otherwise
    `ERR_INVALID_STATE`, HTTP 409."
    PRD §2.4: "A request that is rejected by any rung of the validation ladder writes
    nothing at all — no counters move, no cascade fires, no `version` advances, and no
    partial state survives the rejection."

    Design: Corner/state_machines/visit_start_from_completed_state_rejected
    """
    world = setup_completed_visit(
        employer={"legal_name": "State Co", "employer_code": "STA"},
        site={"site_name": "STA Clinic"},
        eligibility={"subscriber_external_id": "S-3501", "member_external_id": "M-3501"},
        participant={"display_name": "State Tester"},
        completion={"clinical_note": "Done"},
    )
    before_version = world.visit["version"]

    validate_error(
        api_client.start_visit(world.visit_id, world.clinician_headers),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    after = read_visit(world.visit_id, world.clinician_id)
    assert after["encounter_status"] == "COMPLETED"
    assert after["version"] == before_version, "the rejected start advanced the version"


def test_fourth_amendment_rejected_at_the_amendment_cap():
    """PRD §3.5: "**Amending** a completed encounter is how late clinical corrections
    are recorded. It moves the visit `COMPLETED → AMENDED` the first time and then
    loops `AMENDED → AMENDED`, and it is capped at three amendments: `amendment_count`
    rises by one on each success and a fourth attempt is refused with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/visit_fourth_amendment_rejected_at_amendment_cap
    """
    world = setup_completed_visit(
        employer={"legal_name": "Amend Co", "employer_code": "AMD"},
        site={"site_name": "AMD Clinic"},
        eligibility={"subscriber_external_id": "S-3601", "member_external_id": "M-3601"},
        participant={"display_name": "Amend Tester"},
        completion={"clinical_note": "v0"},
    )

    current = world.visit
    for note in ("v1", "v2", "v3"):
        current = amend_encounter(
            world.visit_id, world.clinician_id, current["version"], clinical_note=note
        )
        assert current["encounter_status"] == "AMENDED"

    validate_error(
        api_client.amend_visit(
            world.visit_id,
            {"expected_visit_version": current["version"], "clinical_note": "v4"},
            world.clinician_headers,
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    final = read_visit(world.visit_id, world.clinician_id)
    assert final["amendment_count"] == 3
    assert final["clinical_note"] == "v3"


def test_amendment_leaves_the_disclosure_axis_where_it_stands():
    """PRD §3.5: "Check-in creates a `Visit`, and a visit is tracked on **two axes
    that advance independently of one another**."
    PRD §3.5: "Amending does **not** touch the disclosure axis: a visit sitting at
    `FITNESS_RELEASED` stays released while its clinical content is revised."

    Design: Difficulty/non_linear_state_machine/visit_encounter_and_disclosure_axes_advance_independently
    """
    world = setup_completed_visit(
        visit_type="OCC_HEALTH",
        authorization="GRANT",
        employer={"legal_name": "Parallel Axes Co", "employer_code": "PAX"},
        site={"site_name": "PAX On-Site Clinic", "daily_slot_capacity": 8},
        eligibility={"subscriber_external_id": "S-7001", "member_external_id": "M-7001"},
        participant={"display_name": "Kit Alvarez"},
        completion={
            "fitness_conclusion": "FIT_FOR_DUTY",
            "clinical_note": "Post-offer screening",
        },
    )
    assert world.visit["disclosure_status"] == "RELEASE_PENDING"

    amended = amend_encounter(
        world.visit_id,
        world.clinician_id,
        world.visit["version"],
        clinical_note="Corrected note",
    )

    assert amended["encounter_status"] == "AMENDED"
    assert amended["disclosure_status"] == "RELEASE_PENDING", (
        "the disclosure axis must not move when the clinical axis does"
    )
    assert amended["amendment_count"] == 1


def test_disclosure_release_leaves_the_encounter_axis_where_it_stands():
    """PRD §3.5: "Check-in creates a `Visit`, and a visit is tracked on **two axes
    that advance independently of one another**."
    PRD §3.5: "And it forks on `visit_type`: an `OCC_HEALTH` visit — which must by now
    carry a non-null `fitness_conclusion` — moves `RELEASE_PENDING → FITNESS_RELEASED`,
    while a `WELLNESS` visit moves `RELEASE_PENDING → PARTICIPATION_RELEASED`."

    Design: Difficulty/non_linear_state_machine/visit_encounter_and_disclosure_axes_advance_independently
    """
    world = setup_completed_visit(
        visit_type="OCC_HEALTH",
        authorization="GRANT",
        employer={"legal_name": "Parallel Axes Co", "employer_code": "PAX"},
        site={"site_name": "PAX On-Site Clinic", "daily_slot_capacity": 8},
        eligibility={"subscriber_external_id": "S-7001", "member_external_id": "M-7001"},
        participant={"display_name": "Kit Alvarez"},
        completion={
            "fitness_conclusion": "FIT_FOR_DUTY",
            "clinical_note": "Post-offer screening",
        },
    )
    amended = amend_encounter(
        world.visit_id,
        world.clinician_id,
        world.visit["version"],
        clinical_note="Corrected note",
    )

    released = release_disclosure(world.visit_id, world.clinician_id)

    assert released["disclosure_status"] == "FITNESS_RELEASED"
    assert released["encounter_status"] == "AMENDED", (
        "releasing a disclosure must not move the clinical axis"
    )
    assert released["amendment_count"] == amended["amendment_count"] == 1


def test_employer_disclosure_of_primary_care_visit_not_permitted():
    """PRD §3.5: "A `PRIMARY_CARE` encounter moves `WALLED → NOT_DISCLOSABLE`
    **regardless of authorization** — primary care is never disclosable to an employer
    at the individual level, and a participant's grant cannot make it so; from that
    point the employer disclosure read on that visit is refused with
    `ERR_DISCLOSURE_NOT_PERMITTED` forever."
    PRD §3.5: "It requires the visit to stand at `RELEASE_PENDING`; a visit at
    `WALLED`, `NOT_DISCLOSABLE` or `SUPPRESSED`, or one already released, is refused
    with `ERR_DISCLOSURE_NOT_PERMITTED`."

    Design: Corner/endpoints/employer_disclosure_on_a_primary_care_visit_not_permitted
    """
    world = setup_completed_visit(
        visit_type="PRIMARY_CARE",
        authorization="GRANT",
        employer={"legal_name": "Disclose Co", "employer_code": "DSC"},
        site={"site_name": "DSC Clinic"},
        eligibility={"subscriber_external_id": "S-5001", "member_external_id": "M-5001"},
        participant={"display_name": "Dsc Tester"},
        completion={"clinical_note": "Private primary-care encounter"},
    )
    assert world.visit["disclosure_status"] == "NOT_DISCLOSABLE"

    validate_error(
        api_client.get_employer_disclosure(world.visit_id, world.employer_headers),
        ApiErrorId.ERR_DISCLOSURE_NOT_PERMITTED.value,
        422,
    )
    validate_error(
        api_client.release_visit_disclosure(world.visit_id, world.clinician_headers),
        ApiErrorId.ERR_DISCLOSURE_NOT_PERMITTED.value,
        422,
    )


def _released_pair():
    """One participant with an OCC_HEALTH and a WELLNESS encounter, both released."""
    world = setup_clinic(
        employer={"legal_name": "Northwind Manufacturing", "employer_code": "NWM"},
        site={"site_name": "Northwind On-Site Clinic", "daily_slot_capacity": 8},
        contract={"quota_visits_total": 50},
        coverage_role="OCC_HEALTH",
        eligibility={"subscriber_external_id": "S-1001", "member_external_id": "M-1001"},
        participant={"display_name": "Ana Silva"},
    )
    grant_authorization(world.participant_id)
    world = setup_completed_visit(
        visit_type="OCC_HEALTH",
        scheduled_start="2026-06-08T09:00:00Z",
        visit_clock="2026-06-08T11:00:00Z",
        world=world,
        completion={"fitness_conclusion": "FIT_WITH_RESTRICTIONS"},
    )
    world.occ_visit = release_disclosure(world.visit_id, world.clinician_id)
    _, wellness = add_completed_visit(
        world,
        world.participant_id,
        "2026-06-08T10:00:00Z",
        "WELLNESS",
        clinical_note="Wellness coaching session",
    )
    world.wellness_visit = release_disclosure(wellness["id"], world.clinician_id)
    return world


def test_occ_health_disclosure_returns_the_fitness_conclusion():
    """PRD §3.5: "On a visit at `FITNESS_RELEASED` the payload carries `visit_id`,
    `visit_type`, `service_date`, `disclosure_status`, the visit's actual
    `fitness_conclusion`, `participation_recorded` set to true, and
    `clinical_detail_included` set to false."
    PRD §3.5: "The visit's `clinical_note` never appears in this payload under any
    status whatsoever."

    Design: Difficulty/dual_variant_calc/employer_disclosure_occ_health_conclusion_vs_wellness_participation_only
    """
    world = _released_pair()
    assert world.occ_visit["disclosure_status"] == "FITNESS_RELEASED"

    payload = validate_success(
        api_client.get_employer_disclosure(
            world.occ_visit["id"], world.employer_headers
        )
    )
    assert_employer_disclosure_payload(
        payload, "FITNESS_RELEASED", "FIT_WITH_RESTRICTIONS"
    )
    assert payload["visit_id"] == world.occ_visit["id"]
    assert payload["visit_type"] == "OCC_HEALTH"


def test_wellness_disclosure_reports_participation_with_null_conclusion():
    """PRD §3.5: "On a visit at `PARTICIPATION_RELEASED` the payload carries the same
    seven keys but `fitness_conclusion` is **null even when the visit row happens to
    hold a conclusion value** — a wellness encounter tells the employer that the
    member participated and nothing more — with `participation_recorded` true and
    `clinical_detail_included` false."
    PRD §3.5: "The visit's `clinical_note` never appears in this payload under any
    status whatsoever."

    Design: Difficulty/dual_variant_calc/employer_disclosure_occ_health_conclusion_vs_wellness_participation_only
    """
    world = _released_pair()
    assert world.wellness_visit["disclosure_status"] == "PARTICIPATION_RELEASED"

    payload = validate_success(
        api_client.get_employer_disclosure(
            world.wellness_visit["id"], world.employer_headers
        )
    )
    assert_employer_disclosure_payload(payload, "PARTICIPATION_RELEASED", None)
    assert payload["visit_type"] == "WELLNESS"
    assert payload["visit_id"] == world.wellness_visit["id"]


def test_revocation_suppresses_pending_visit_and_blocks_its_release():
    """PRD §3.3: "A revoke from `GRANTED` moves the axis to `REVOKED`, stamps
    `authorization_revoked_at` with the clock instant, and reaches across to the
    participant's visits: every visit whose `disclosure_status` is `WALLED` or
    `RELEASE_PENDING` moves to `SUPPRESSED`."
    PRD §3.5: "It requires the participant's `authorization_status` to be `GRANTED` at
    that moment; if the participant has revoked in the meantime the release is refused
    with `ERR_AUTHORIZATION_REVOKED`, and because rung 13 sits above rung 14 an
    attempt that fails both reports the revocation."

    Design: Difficulty/cross_entity_state_dependency/disclosure_release_depends_on_participant_authorization_state
    """
    world = setup_completed_visit(
        visit_type="OCC_HEALTH",
        authorization="GRANT",
        employer={"legal_name": "Authorization Co", "employer_code": "AUT"},
        site={"site_name": "AUT On-Site Clinic", "daily_slot_capacity": 8},
        contract={"quota_visits_total": 20},
        eligibility={"subscriber_external_id": "S-1701", "member_external_id": "M-1701"},
        participant={"display_name": "Auth Tester"},
        completion={"fitness_conclusion": "NOT_FIT"},
    )
    assert world.visit["disclosure_status"] == "RELEASE_PENDING"

    revoked = revoke_authorization(world.participant_id)
    assert revoked["authorization_status"] == "REVOKED"
    assert revoked["authorization_revoked_at"] is not None

    suppressed = read_visit(world.visit_id, world.clinician_id)
    assert suppressed["disclosure_status"] == "SUPPRESSED"

    validate_error(
        api_client.release_visit_disclosure(world.visit_id, world.clinician_headers),
        ApiErrorId.ERR_AUTHORIZATION_REVOKED.value,
        403,
    )


def test_revocation_leaves_an_already_released_visit_readable():
    """PRD §3.3: "**Revocation is prospective only.** Visits already sitting at
    `FITNESS_RELEASED` or `PARTICIPATION_RELEASED` are left untouched — a disclosure
    the employer has already lawfully received is never retracted — and this
    non-firing branch is as much a part of the specification as the firing one."
    PRD §3.5: "One subtlety is deliberate: this read does **not** re-consult the
    participant's current `authorization_status`. A disclosure that was lawfully
    released stays readable afterwards even if the participant later revokes, which is
    the read-side counterpart to revocation being prospective only."

    Design: Difficulty/cross_entity_state_dependency/disclosure_release_depends_on_participant_authorization_state
    """
    world = setup_completed_visit(
        visit_type="OCC_HEALTH",
        authorization="GRANT",
        employer={"legal_name": "Authorization Co", "employer_code": "AUT"},
        site={"site_name": "AUT On-Site Clinic", "daily_slot_capacity": 8},
        contract={"quota_visits_total": 20},
        eligibility={"subscriber_external_id": "S-1701", "member_external_id": "M-1701"},
        participant={"display_name": "Auth Tester"},
        completion={"fitness_conclusion": "FIT_FOR_DUTY"},
    )
    released = release_disclosure(world.visit_id, world.clinician_id)
    assert released["disclosure_status"] == "FITNESS_RELEASED"

    _, second = add_completed_visit(
        world,
        world.participant_id,
        "2026-06-08T10:00:00Z",
        "OCC_HEALTH",
        fitness_conclusion="NOT_FIT",
    )
    assert second["disclosure_status"] == "RELEASE_PENDING"

    revoke_authorization(world.participant_id)

    untouched = read_visit(world.visit_id, world.clinician_id)
    assert untouched["disclosure_status"] == "FITNESS_RELEASED"
    still_readable = validate_success(
        api_client.get_employer_disclosure(world.visit_id, world.employer_headers)
    )
    assert still_readable["fitness_conclusion"] == "FIT_FOR_DUTY"

    suppressed = read_visit(second["id"], world.clinician_id)
    assert suppressed["disclosure_status"] == "SUPPRESSED"
