"""Social needs, community referrals, the closed loop and the barrier cascade."""
import pytest

from test_helpers import (
    ApiErrorId, PROGRAM_ADMIN, assert_referral, assert_social_need,
    close_loop_as_care_manager, close_loop_as_partner, create_referral_payload,
    create_touch_payload, decide_referral, identify_social_need,
    make_care_manager_headers, make_community_partner_headers, read_care_plan,
    read_community_resource, read_goal, read_referral, read_social_need,
    register_resource, send_referral, set_clock, set_consent,
    setup_referral_scenario, validate_error, validate_paginated, validate_success,
)


def _fork_join_scenario(external_member_id="MBR-7001"):
    scenario = setup_referral_scenario(
        program_overrides={"name": "Closed Loop Program",
                           "required_credential_levels": ["CHW"]},
        manager_overrides={"full_name": "Rita Nolan"},
        member_overrides={"external_member_id": external_member_id,
                          "full_name": "Tom Reed", "birth_date": "1949-12-01",
                          "social_data_consent_status": "GRANTED"},
        goal_specs=[{"domain": "CLINICAL", "description": "Reduce ED use"}],
        resource_overrides={"name": "Bayside Food Bank", "served_domains": ["FOOD"],
                            "concurrent_slot_capacity": 2},
        need_overrides={"domain": "FOOD", "severity": "SEVERE"},
    )
    care_manager_id = scenario["care_manager"]["id"]
    scenario["second_need"] = identify_social_need(
        scenario["enrollment"]["id"], care_manager_id,
        domain="FOOD", severity="MODERATE",
    )
    scenario["declined_referral"] = send_referral(
        scenario["social_need"]["id"], scenario["resource"]["id"], care_manager_id,
        service_start_at="2026-08-10T09:00:00Z",
        service_end_at="2026-08-10T12:00:00Z",
    )
    scenario["accepted_referral"] = send_referral(
        scenario["second_need"]["id"], scenario["resource"]["id"], care_manager_id,
        service_start_at="2026-08-11T09:00:00Z",
        service_end_at="2026-08-11T12:00:00Z",
    )
    decide_referral(scenario["accepted_referral"]["id"], scenario["resource"]["id"],
                    "ACCEPT")
    return scenario


def test_declining_a_referral_releases_the_resource_slot_immediately(api):
    """PRD §3.8: "`ACCEPT` moves the referral to `ACCEPTED` and stamps
    `decision_at`; the slot occupation is retained, because both `SENT` and
    `ACCEPTED` occupy, and `open_referral_count` is unchanged."
    PRD §3.8: "`DECLINE` requires a present, non-empty `decline_reason`, moves the
    referral to `DECLINED`, stamps `decision_at`, stores the reason, and —
    diverging sharply from the accept branch — releases the slot immediately and
    decrements the organization's `open_referral_count` by one, so a referral
    whose interval overlaps the declined one is accepted from that moment on."

    Design: Difficulty/non_linear_state_machine/referral_fork_join_declined_branch_reaches_closed_unmet
    """
    scenario = _fork_join_scenario()
    resource_id = scenario["resource"]["id"]
    assert read_community_resource(resource_id)["open_referral_count"] == 2

    data = validate_success(
        api.decide_referral(
            scenario["declined_referral"]["id"],
            {"decision": "DECLINE",
             "decline_reason": "No pantry slots in that window."},
            make_community_partner_headers(resource_id),
        )
    )
    assert_referral(data)
    assert data["status"] == "DECLINED"
    assert data["decline_reason"] == "No pantry slots in that window."
    assert read_community_resource(resource_id)["open_referral_count"] == 1
    assert read_referral(scenario["accepted_referral"]["id"])["status"] == "ACCEPTED"


def test_declined_branch_joins_the_accept_branch_at_closed_unmet(api):
    """PRD §3.8: "A referral in `ACCEPTED` is closed by the receiving
    organization; a referral in `DECLINED` is closed by the sending care manager,
    who is the one who knows the service never happened."
    PRD §3.8: "From `DECLINED` with `SERVICE_NOT_DELIVERED`, the referral also
    becomes `CLOSED_UNMET` and the need also escalates, but `open_referral_count`
    is **not** decremented a second time, because the decline already released
    that slot."
    PRD §3.8: "Every closure stamps `closed_at` and computes `loop_closure_hours`
    as the whole number of hours from `sent_at` to `closed_at`, truncating any
    partial hour toward zero, and increments the organization's `closed_loop_count`
    by one."

    Design: Difficulty/non_linear_state_machine/referral_fork_join_declined_branch_reaches_closed_unmet
    """
    scenario = _fork_join_scenario(external_member_id="MBR-7002")
    resource_id = scenario["resource"]["id"]
    care_manager_id = scenario["care_manager"]["id"]
    declined_id = scenario["declined_referral"]["id"]

    decide_referral(declined_id, resource_id, "DECLINE",
                    decline_reason="No pantry slots in that window.")

    data = validate_success(
        api.close_referral_loop(
            declined_id,
            {"resolution": "SERVICE_NOT_DELIVERED",
             "outcome_note": "Member referred elsewhere."},
            make_care_manager_headers(care_manager_id),
        )
    )
    assert data["status"] == "CLOSED_UNMET"
    assert data["loop_closure_hours"] == 0

    resource = read_community_resource(resource_id)
    assert resource["open_referral_count"] == 1, (
        "the decline already released the slot; closure must not decrement twice"
    )
    assert resource["closed_loop_count"] == 1

    escalated = read_social_need(scenario["social_need"]["id"])
    assert escalated["status"] == "UNMET_ESCALATED"
    assert escalated["escalation_count"] == 1
    assert read_social_need(scenario["second_need"]["id"])["status"] == "REFERRED"


def _barrier_scenario(external_member_id="MBR-9001"):
    scenario = setup_referral_scenario(
        program_overrides={"name": "SDOH Loop Program",
                           "required_credential_levels": ["LCSW"],
                           "referral_loop_days": 30},
        manager_overrides={"full_name": "Marta Diaz"},
        reviewer_overrides={"full_name": "Paul Vos"},
        member_overrides={"external_member_id": external_member_id,
                          "full_name": "Rae Kim", "birth_date": "1980-02-02",
                          "social_data_consent_status": "GRANTED"},
        goal_specs=[{"domain": "FOOD", "description": "Secure weekly food supply",
                     "target_date": "2026-11-01"},
                    {"domain": "CLINICAL", "description": "A1c below 8"}],
        resource_overrides={"name": "Harborview Pantry", "served_domains": ["FOOD"],
                            "concurrent_slot_capacity": 3},
        need_overrides={"domain": "FOOD", "severity": "SEVERE"},
        plan_title="SDOH plan",
    )
    assert scenario["plan"]["compliance_posture"] == "COMPLIANT"
    assert scenario["plan"]["at_risk_goal_count"] == 0
    scenario["referral"] = send_referral(
        scenario["social_need"]["id"], scenario["resource"]["id"],
        scenario["care_manager"]["id"],
        service_start_at="2026-08-05T09:00:00Z",
        service_end_at="2026-08-05T11:00:00Z",
    )
    decide_referral(scenario["referral"]["id"], scenario["resource"]["id"], "ACCEPT")
    return scenario


def test_unmet_closure_escalates_the_need_and_flags_the_matching_goal(api):
    """PRD §3.8: "From `ACCEPTED` with `SERVICE_NOT_DELIVERED`, the referral
    becomes `CLOSED_UNMET`, the organization's `open_referral_count` likewise
    drops by one, and the social need moves from `REFERRED` to `UNMET_ESCALATED`,
    starting the barrier cascade below."
    PRD §3.8: "Hop one sets the need's `status` to `UNMET_ESCALATED` and increases
    its `escalation_count` by one. Hop two, caused by hop one, finds every goal
    whose `domain` equals this need's `domain`, whose `status` is `OPEN`, and
    which sits on the `ACTIVE` care plan of this need's enrollment, and moves each
    from `OPEN` to `AT_RISK` with `barrier_flag` set to true."

    Design: Difficulty/transitive_cascade/referral_unmet_barrier_cascade_depth_three_on_matching_domain
    """
    scenario = _barrier_scenario()
    resource_id = scenario["resource"]["id"]

    data = validate_success(
        api.close_referral_loop(
            scenario["referral"]["id"],
            {"resolution": "SERVICE_NOT_DELIVERED",
             "outcome_note": "Member did not attend the pantry appointment."},
            make_community_partner_headers(resource_id),
        )
    )
    assert data["status"] == "CLOSED_UNMET"

    need = read_social_need(scenario["social_need"]["id"])
    assert_social_need(need)
    assert need["status"] == "UNMET_ESCALATED"
    assert need["escalation_count"] == 1

    food_goal = read_goal(scenario["goals"][0]["id"])
    assert food_goal["status"] == "AT_RISK"
    assert food_goal["barrier_flag"] is True

    resource = read_community_resource(resource_id)
    assert resource["open_referral_count"] == 0
    assert resource["closed_loop_count"] == 1


def test_barrier_cascade_leaves_goals_in_other_domains_untouched(api):
    """PRD §3.8: "Hop three, caused by hop two, increases that plan's
    `at_risk_goal_count` by one for each such goal and sets its
    `compliance_posture` to `AT_RISK` where it had been `COMPLIANT`."
    PRD §3.5: "**Compliance posture** is a derived summary of the plan's health,
    recomputed whenever anything that feeds it changes. It reads `DEFICIENT`
    whenever the plan's `status` is `SUSPENDED`. Otherwise it reads `AT_RISK`
    whenever `at_risk_goal_count` is 1 or more. Otherwise it reads `COMPLIANT`."

    Design: Difficulty/transitive_cascade/referral_unmet_barrier_cascade_depth_three_on_matching_domain
    """
    scenario = _barrier_scenario(external_member_id="MBR-9002")

    close_loop_as_partner(scenario["referral"]["id"], scenario["resource"]["id"],
                          "SERVICE_NOT_DELIVERED",
                          "Member did not attend the pantry appointment.")

    clinical_goal = read_goal(scenario["goals"][1]["id"])
    assert clinical_goal["status"] == "OPEN", (
        "hop two is keyed on the domain match, not a fan-out over every goal"
    )
    assert clinical_goal["barrier_flag"] is False

    plan = read_care_plan(scenario["plan"]["id"])
    assert plan["at_risk_goal_count"] == 1
    assert plan["compliance_posture"] == "AT_RISK"
    assert plan["status"] == "ACTIVE"


def _consent_ladder_scenario(external_member_id, contract_status):
    scenario = setup_referral_scenario(
        program_overrides={"name": "Consent Ladder Program",
                           "required_credential_levels": ["LCSW"]},
        manager_overrides={"full_name": "Marta Diaz"},
        member_overrides={"external_member_id": external_member_id,
                          "full_name": "Gus Hale", "birth_date": "1957-01-15",
                          "social_data_consent_status": "GRANTED"},
        goal_specs=[{"domain": "CLINICAL", "description": "Consent ladder goal"}],
        resource_overrides={"name": "Unsigned Pantry", "served_domains": ["FOOD"],
                            "concurrent_slot_capacity": 5,
                            "contract_status": contract_status},
        need_overrides={"domain": "FOOD", "severity": "MODERATE"},
    )
    revoked = set_consent(scenario["member"]["id"], "REVOKED")
    assert revoked["social_data_consent_status"] == "REVOKED"
    return scenario


def test_consent_check_precedes_the_contracting_check(api):
    """PRD §2.6: "**Safety and consent rules** — consent
    (`ERR_CONSENT_NOT_GRANTED`), documentation (`ERR_DOCUMENTATION_REQUIRED`),
    credential authorisation (`ERR_CREDENTIAL_NOT_AUTHORIZED`) and state licensure
    (`ERR_STATE_LICENSURE_MISMATCH`), evaluated in that relative order."
    PRD §2.6: "**Referential business rules** — contracting status
    (`ERR_RESOURCE_NOT_CONTRACTED`), then domain and geography match
    (`ERR_RESOURCE_DOMAIN_MISMATCH`), then duplicate enrollment
    (`ERR_DUPLICATE_ACTIVE_ENROLLMENT`), then same-manager transfer
    (`ERR_TRANSFER_TO_SAME_MANAGER`), then the graduation precondition
    (`ERR_GOALS_NOT_MET`), then stratification presence
    (`ERR_STRATIFICATION_REQUIRED`), then program tier minimum
    (`ERR_RISK_TIER_BELOW_PROGRAM_MINIMUM`)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_when_consent_revoked_and_resource_uncontracted
    """
    scenario = _consent_ladder_scenario("MBR-1201", "NOT_CONTRACTED")

    response = api.create_referral(
        create_referral_payload(
            scenario["social_need"]["id"], scenario["resource"]["id"],
            service_start_at="2026-08-12T09:00:00Z",
            service_end_at="2026-08-12T11:00:00Z",
        ),
        make_care_manager_headers(scenario["care_manager"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CONSENT_NOT_GRANTED.value)
    assert response.status_code == 422
    assert read_social_need(scenario["social_need"]["id"])["status"] == "IDENTIFIED"
    assert read_community_resource(
        scenario["resource"]["id"]
    )["open_referral_count"] == 0


def test_restoring_consent_exposes_the_contracting_rejection(api):
    """PRD §3.8: "The receiving organization's `contract_status` must be
    `CONTRACTED`; a `NOT_CONTRACTED` or `SUSPENDED` organization receives nothing
    new, and the attempt returns `ERR_RESOURCE_NOT_CONTRACTED`."
    PRD §3.1: "Either plan operations or the member's care manager may toggle it
    later by supplying a replacement `social_data_consent_status`, which
    overwrites the stored value and increments the member's `version`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_when_consent_revoked_and_resource_uncontracted
    """
    scenario = _consent_ladder_scenario("MBR-1202", "NOT_CONTRACTED")
    care_manager_headers = make_care_manager_headers(scenario["care_manager"]["id"])
    payload = create_referral_payload(
        scenario["social_need"]["id"], scenario["resource"]["id"],
        service_start_at="2026-08-12T09:00:00Z",
        service_end_at="2026-08-12T11:00:00Z",
    )

    blocked = api.create_referral(payload, care_manager_headers)
    validate_error(blocked, ApiErrorId.ERR_CONSENT_NOT_GRANTED.value)

    set_consent(scenario["member"]["id"], "GRANTED")

    unmasked = api.create_referral(payload, care_manager_headers)
    validate_error(unmasked, ApiErrorId.ERR_RESOURCE_NOT_CONTRACTED.value)
    assert unmasked.status_code == 422
    assert read_social_need(scenario["social_need"]["id"])["status"] == "IDENTIFIED"


def _consent_gate_scenario(external_member_id):
    return setup_referral_scenario(
        program_overrides={"name": "Consent Gate Program",
                           "required_credential_levels": ["CHW"]},
        manager_overrides={"full_name": "Sol Vega"},
        member_overrides={"external_member_id": external_member_id,
                          "full_name": "Ura Bell", "birth_date": "1985-06-06",
                          "social_data_consent_status": "REVOKED"},
        goal_specs=[{"domain": "CLINICAL", "description": "Consent gate goal"}],
        resource_overrides={"name": "Shelter Alliance",
                            "served_domains": ["HOUSING"],
                            "concurrent_slot_capacity": 4},
        need_overrides={"domain": "HOUSING", "severity": "SEVERE"},
    )


def test_referral_is_refused_while_the_member_consent_is_revoked(api):
    """PRD §3.1: "Consent matters because it gates the moment social-need data
    would leave the plan: a member whose consent reads `REVOKED` cannot have a
    referral sent on their behalf, and the attempt is refused with
    `ERR_CONSENT_NOT_GRANTED`."
    PRD §3.8: "The need opens in `IDENTIFIED` with `escalation_count` at 0,
    `identified_at` stamped from the logical clock, and `resolved_at` null."

    Design: Difficulty/cross_entity_state_dependency/referral_gated_by_member_consent_status
    """
    scenario = _consent_gate_scenario("MBR-1901")
    assert scenario["social_need"]["status"] == "IDENTIFIED"

    response = api.create_referral(
        create_referral_payload(
            scenario["social_need"]["id"], scenario["resource"]["id"],
            service_start_at="2026-08-15T09:00:00Z",
            service_end_at="2026-08-15T12:00:00Z",
        ),
        make_care_manager_headers(scenario["care_manager"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CONSENT_NOT_GRANTED.value)
    assert response.status_code == 422

    _, meta = validate_paginated(
        api.list_referrals(PROGRAM_ADMIN,
                           params={"social_need_id": scenario["social_need"]["id"]})
    )
    assert meta["total_count"] == 0


def test_referral_succeeds_once_the_member_consent_is_restored(api):
    """PRD §3.8: "A persisted referral opens in `SENT` with `sent_at` stamped from
    the logical clock, `decision_at`, `decline_reason`, `outcome_note`,
    `closed_at` and `loop_closure_hours` all null. It increments the
    organization's `open_referral_count` by one, and it moves the social need to
    `REFERRED` — from `IDENTIFIED` on a first attempt, or from `UNMET_ESCALATED`
    when a previously failed loop is being tried again."
    PRD §3.8: "The sending care manager's `X-User-ID` is recorded as
    `sent_by_care_manager_id`."

    Design: Difficulty/cross_entity_state_dependency/referral_gated_by_member_consent_status
    """
    scenario = _consent_gate_scenario("MBR-1902")
    care_manager_id = scenario["care_manager"]["id"]
    headers = make_care_manager_headers(care_manager_id)
    payload = create_referral_payload(
        scenario["social_need"]["id"], scenario["resource"]["id"],
        service_start_at="2026-08-15T09:00:00Z",
        service_end_at="2026-08-15T12:00:00Z",
    )

    blocked = api.create_referral(payload, headers)
    validate_error(blocked, ApiErrorId.ERR_CONSENT_NOT_GRANTED.value)

    restored = set_consent(scenario["member"]["id"], "GRANTED", headers)
    assert restored["social_data_consent_status"] == "GRANTED"

    data = validate_success(api.create_referral(payload, headers), 201)
    assert_referral(data)
    assert data["status"] == "SENT"
    assert data["sent_by_care_manager_id"] == care_manager_id
    assert read_social_need(scenario["social_need"]["id"])["status"] == "REFERRED"
    assert read_community_resource(
        scenario["resource"]["id"]
    )["open_referral_count"] == 1


def _slot_capacity_scenario(external_member_id):
    scenario = setup_referral_scenario(
        program_overrides={"name": "Slot Capacity Program",
                           "required_credential_levels": ["CHW"]},
        manager_overrides={"full_name": "Sol Vega"},
        member_overrides={"external_member_id": external_member_id,
                          "full_name": "Ola Reyes", "birth_date": "1981-01-01",
                          "social_data_consent_status": "GRANTED"},
        goal_specs=[{"domain": "CLINICAL", "description": "Slot capacity goal"}],
        resource_overrides={"name": "Two Slot Pantry", "served_domains": ["FOOD"],
                            "concurrent_slot_capacity": 2},
        need_overrides={"domain": "FOOD", "severity": "SEVERE"},
    )
    care_manager_id = scenario["care_manager"]["id"]
    enrollment_id = scenario["enrollment"]["id"]
    scenario["needs"] = [scenario["social_need"]] + [
        identify_social_need(enrollment_id, care_manager_id, domain="FOOD",
                             severity=severity)
        for severity in ("MODERATE", "MODERATE", "LOW")
    ]
    scenario["referral_a"] = send_referral(
        scenario["needs"][0]["id"], scenario["resource"]["id"], care_manager_id,
        service_start_at="2026-08-10T09:00:00Z",
        service_end_at="2026-08-10T12:00:00Z",
    )
    scenario["referral_b"] = send_referral(
        scenario["needs"][1]["id"], scenario["resource"]["id"], care_manager_id,
        service_start_at="2026-08-10T10:00:00Z",
        service_end_at="2026-08-10T14:00:00Z",
    )
    return scenario


def test_third_overlapping_referral_exceeds_the_slot_capacity(api):
    """PRD §3.8: "The instants probed are the candidate's own `service_start_at`
    together with each occupant's `service_start_at` that falls strictly inside
    the candidate's interval. At each probe instant, count the candidate itself as
    one, add every occupant whose `service_start_at` is at or before the probe and
    whose `service_end_at` is strictly after it, and if that total ever exceeds the
    organization's `concurrent_slot_capacity`, reject the referral with
    `ERR_RESOURCE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/community_resource_half_open_capacity_accepts_adjacent_referral
    """
    scenario = _slot_capacity_scenario("MBR-2201")

    response = api.create_referral(
        create_referral_payload(
            scenario["needs"][2]["id"], scenario["resource"]["id"],
            service_start_at="2026-08-10T11:00:00Z",
            service_end_at="2026-08-10T13:00:00Z",
        ),
        make_care_manager_headers(scenario["care_manager"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RESOURCE_CAPACITY_EXCEEDED.value)
    assert response.status_code == 409
    assert read_social_need(scenario["needs"][2]["id"])["status"] == "IDENTIFIED"
    assert read_referral(scenario["referral_a"]["id"])["status"] == "SENT"
    assert read_referral(scenario["referral_b"]["id"])["status"] == "SENT"


def test_referral_starting_at_an_occupants_end_instant_is_accepted(api):
    """PRD §3.8: "Because the intervals are half-open, an occupant whose
    `service_end_at` equals the candidate's `service_start_at` never counts, so
    exact adjacency is always accepted no matter how small the capacity."
    PRD §3.8: "The organization's capacity is checked on plain half-open intervals
    with no buffer of any kind, which is deliberately different geometry from the
    care-manager calendar."

    Design: Difficulty/resource_temporal_overlap/community_resource_half_open_capacity_accepts_adjacent_referral
    """
    scenario = _slot_capacity_scenario("MBR-2202")

    data = validate_success(
        api.create_referral(
            create_referral_payload(
                scenario["needs"][3]["id"], scenario["resource"]["id"],
                service_start_at="2026-08-10T12:00:00Z",
                service_end_at="2026-08-10T14:00:00Z",
            ),
            make_care_manager_headers(scenario["care_manager"]["id"]),
        ),
        201,
    )
    assert data["status"] == "SENT"
    assert read_community_resource(
        scenario["resource"]["id"]
    )["open_referral_count"] == 3


def test_resolving_the_need_returns_the_barrier_goal_to_open(api):
    """PRD §3.8: "From `ACCEPTED` with `SERVICE_DELIVERED`, the referral becomes
    `CLOSED_MET`, the organization's `open_referral_count` drops by one, and the
    social need moves from `REFERRED` to `RESOLVED` with `resolved_at` stamped."
    PRD §3.8: "A need moving from `REFERRED` to `RESOLVED` returns every goal in
    the same `domain` on the same enrollment that currently sits in `AT_RISK` back
    to `OPEN`, clearing its `barrier_flag` to false — but only when no other social
    need on that enrollment in the same `domain` remains in `UNMET_ESCALATED`."
    PRD §3.8: "Each restored goal decrements the plan's `at_risk_goal_count` by
    one, and the plan's `compliance_posture` is recomputed afterwards."

    Design: Corner/state_machines/social_need_resolution_returns_barrier_goal_to_open
    """
    scenario = setup_referral_scenario(
        program_overrides={"name": "Barrier Reversal Program",
                           "required_credential_levels": ["CHW"]},
        manager_overrides={"full_name": "Sol Vega"},
        reviewer_overrides={"full_name": "Ann Poe"},
        member_overrides={"external_member_id": "MBR-4901", "full_name": "Bar Rier",
                          "birth_date": "1983-03-23",
                          "social_data_consent_status": "GRANTED"},
        goal_specs=[{"domain": "FOOD", "description": "Stable food access"}],
        resource_overrides={"name": "Reversal Pantry", "served_domains": ["FOOD"],
                            "concurrent_slot_capacity": 3},
        need_overrides={"domain": "FOOD", "severity": "SEVERE"},
        plan_title="Barrier plan",
    )
    need_id = scenario["social_need"]["id"]
    resource_id = scenario["resource"]["id"]
    care_manager_id = scenario["care_manager"]["id"]

    first = send_referral(need_id, resource_id, care_manager_id,
                          service_start_at="2026-08-05T09:00:00Z",
                          service_end_at="2026-08-05T11:00:00Z")
    decide_referral(first["id"], resource_id, "ACCEPT")
    close_loop_as_partner(first["id"], resource_id, "SERVICE_NOT_DELIVERED",
                          "Missed first appointment.")

    barrier_goal = read_goal(scenario["goal"]["id"])
    assert barrier_goal["status"] == "AT_RISK"
    assert barrier_goal["barrier_flag"] is True

    second = send_referral(need_id, resource_id, care_manager_id,
                           service_start_at="2026-08-12T09:00:00Z",
                           service_end_at="2026-08-12T11:00:00Z")
    assert read_social_need(need_id)["status"] == "REFERRED"
    decide_referral(second["id"], resource_id, "ACCEPT")

    closed = validate_success(
        api.close_referral_loop(
            second["id"],
            {"resolution": "SERVICE_DELIVERED",
             "outcome_note": "Weekly grocery box started."},
            make_community_partner_headers(resource_id),
        )
    )
    assert closed["status"] == "CLOSED_MET"

    resolved = read_social_need(need_id)
    assert resolved["status"] == "RESOLVED"
    assert resolved["escalation_count"] == 1
    assert resolved["resolved_at"] == "2026-08-01T00:00:00.000Z"

    restored = read_goal(scenario["goal"]["id"])
    assert restored["status"] == "OPEN"
    assert restored["barrier_flag"] is False

    plan = read_care_plan(scenario["plan"]["id"])
    assert plan["at_risk_goal_count"] == 0
    assert plan["compliance_posture"] == "COMPLIANT"

    resource = read_community_resource(resource_id)
    assert resource["closed_loop_count"] == 2
    assert resource["open_referral_count"] == 0


def test_referral_to_a_resource_outside_the_domain_is_rejected(api):
    """PRD §3.8: "The need's `domain` must appear in the organization's
    `served_domains` and the member's `state_code` must appear in its
    `service_state_codes`, else `ERR_RESOURCE_DOMAIN_MISMATCH`."

    Design: Corner/validations/referral_to_resource_outside_domain_returns_resource_domain_mismatch
    """
    scenario = setup_referral_scenario(
        program_overrides={"name": "Domain Mismatch Program",
                           "required_credential_levels": ["CHW"]},
        manager_overrides={"full_name": "Sol Vega"},
        member_overrides={"external_member_id": "MBR-7301", "full_name": "Dom Dara",
                          "birth_date": "1970-01-01",
                          "social_data_consent_status": "GRANTED"},
        goal_specs=[{"domain": "CLINICAL", "description": "Domain mismatch goal"}],
        resource_overrides={"name": "Housing Only", "served_domains": ["HOUSING"],
                            "concurrent_slot_capacity": 5},
        need_overrides={"domain": "FOOD", "severity": "MODERATE"},
    )

    response = api.create_referral(
        create_referral_payload(
            scenario["social_need"]["id"], scenario["resource"]["id"],
            service_start_at="2026-08-10T09:00:00Z",
            service_end_at="2026-08-10T11:00:00Z",
        ),
        make_care_manager_headers(scenario["care_manager"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RESOURCE_DOMAIN_MISMATCH.value)
    assert response.status_code == 422
    assert read_social_need(scenario["social_need"]["id"])["status"] == "IDENTIFIED"


def test_window_shape_errors_on_touch_and_referral_creation(api):
    """PRD §3.6: "The window must be well formed, with `scheduled_end_at` strictly
    after `scheduled_start_at`, else `ERR_TOUCH_WINDOW_INVALID`; and it must not be
    in the past, meaning `scheduled_start_at` is at or after the logical clock's
    current instant, else `ERR_TOUCH_WINDOW_IN_PAST`."
    PRD §3.8: "The service interval must be well formed, with `service_end_at`
    strictly after `service_start_at`, else `ERR_SERVICE_WINDOW_INVALID`, and must
    not be in the past, meaning `service_start_at` is at or after the logical
    clock, else `ERR_SERVICE_WINDOW_IN_PAST`."

    Design: Corner/errors/window_shape_errors_on_touch_and_referral_creation
    """
    scenario = setup_referral_scenario(
        program_overrides={"name": "Window Shape Program",
                           "required_credential_levels": ["RN"]},
        member_overrides={"external_member_id": "MBR-8501", "full_name": "Win Wes",
                          "birth_date": "1970-01-01",
                          "social_data_consent_status": "GRANTED"},
        goal_specs=[{"domain": "FOOD", "description": "Window goal"}],
        resource_overrides={"name": "Window Pantry", "served_domains": ["FOOD"],
                            "concurrent_slot_capacity": 5},
        need_overrides={"domain": "FOOD", "severity": "MODERATE"},
        plan_title="Window plan",
    )
    care_manager_id = scenario["care_manager"]["id"]
    headers = make_care_manager_headers(care_manager_id)
    set_clock("2026-08-15T00:00:00Z")

    zero_length_touch = api.create_touch(
        create_touch_payload(scenario["enrollment"]["id"], care_manager_id,
                             scheduled_start_at="2026-08-20T10:00:00Z",
                             scheduled_end_at="2026-08-20T10:00:00Z"),
        headers,
    )
    validate_error(zero_length_touch, ApiErrorId.ERR_TOUCH_WINDOW_INVALID.value)
    assert zero_length_touch.status_code == 422

    reversed_service = api.create_referral(
        create_referral_payload(scenario["social_need"]["id"],
                                scenario["resource"]["id"],
                                service_start_at="2026-08-20T10:00:00Z",
                                service_end_at="2026-08-20T09:00:00Z"),
        headers,
    )
    validate_error(reversed_service, ApiErrorId.ERR_SERVICE_WINDOW_INVALID.value)
    assert reversed_service.status_code == 422

    past_service = api.create_referral(
        create_referral_payload(scenario["social_need"]["id"],
                                scenario["resource"]["id"],
                                service_start_at="2026-08-10T09:00:00Z",
                                service_end_at="2026-08-10T11:00:00Z"),
        headers,
    )
    validate_error(past_service, ApiErrorId.ERR_SERVICE_WINDOW_IN_PAST.value)
    assert past_service.status_code == 422

    assert read_social_need(scenario["social_need"]["id"])["status"] == "IDENTIFIED"


def test_referral_lifecycle_state_errors_on_decision_and_closure(api):
    """PRD §3.8: "Only the receiving organization decides, supplying a `decision`
    of `ACCEPT` or `DECLINE`, and only on a referral in `SENT` — anything else is
    `ERR_REFERRAL_NOT_SENT`."
    PRD §3.8: "A referral in any other status cannot be closed at all, and the
    attempt returns `ERR_REFERRAL_LOOP_NOT_CLOSABLE`."
    PRD §3.8: "The need itself must be referable — its `status` must be
    `IDENTIFIED` or `UNMET_ESCALATED`, else `ERR_SOCIAL_NEED_NOT_REFERABLE` — and
    it may not already carry another referral in `SENT` or `ACCEPTED`, else
    `ERR_DUPLICATE_OPEN_REFERRAL`."

    Design: Corner/errors/referral_lifecycle_state_errors_on_decision_and_close_loop
    """
    scenario = setup_referral_scenario(
        program_overrides={"name": "Referral State Program",
                           "required_credential_levels": ["CHW"]},
        manager_overrides={"full_name": "Sol Vega"},
        member_overrides={"external_member_id": "MBR-8701", "full_name": "Loop Lin",
                          "birth_date": "1970-01-01",
                          "social_data_consent_status": "GRANTED"},
        goal_specs=[{"domain": "CLINICAL", "description": "Referral state goal"}],
        resource_overrides={"name": "Loop Pantry", "served_domains": ["FOOD"],
                            "concurrent_slot_capacity": 5},
        need_overrides={"domain": "FOOD", "severity": "MODERATE"},
    )
    need_id = scenario["social_need"]["id"]
    resource_id = scenario["resource"]["id"]
    care_manager_id = scenario["care_manager"]["id"]
    referral = send_referral(need_id, resource_id, care_manager_id,
                             service_start_at="2026-08-10T09:00:00Z",
                             service_end_at="2026-08-10T11:00:00Z")

    too_early = api.close_referral_loop(
        referral["id"],
        {"resolution": "SERVICE_DELIVERED", "outcome_note": "Too early."},
        make_care_manager_headers(care_manager_id),
    )
    validate_error(too_early, ApiErrorId.ERR_REFERRAL_LOOP_NOT_CLOSABLE.value)
    assert too_early.status_code == 409

    decide_referral(referral["id"], resource_id, "ACCEPT")

    decided_twice = api.decide_referral(
        referral["id"],
        {"decision": "DECLINE", "decline_reason": "Changed mind."},
        make_community_partner_headers(resource_id),
    )
    validate_error(decided_twice, ApiErrorId.ERR_REFERRAL_NOT_SENT.value)
    assert decided_twice.status_code == 409

    closed = close_loop_as_partner(referral["id"], resource_id, "SERVICE_DELIVERED",
                                   "Groceries delivered.")
    assert closed["status"] == "CLOSED_MET"
    assert read_social_need(need_id)["status"] == "RESOLVED"

    after_resolution = api.create_referral(
        create_referral_payload(need_id, resource_id,
                                service_start_at="2026-08-20T09:00:00Z",
                                service_end_at="2026-08-20T11:00:00Z"),
        make_care_manager_headers(care_manager_id),
    )
    validate_error(after_resolution, ApiErrorId.ERR_SOCIAL_NEED_NOT_REFERABLE.value)
    assert after_resolution.status_code == 409
