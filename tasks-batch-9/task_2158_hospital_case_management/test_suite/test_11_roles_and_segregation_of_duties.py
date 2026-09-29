"""Authentication, the endpoint role lists, entity-backed ownership, and the two
four-eyes controls."""
from test_helpers import (
    CASE_MANAGER,
    PLATFORM_ADMIN,
    SECOND_CASE_MANAGER,
    SECOND_UR_NURSE,
    UR_NURSE,
    ApiErrorId,
    episode_payload,
    make_discharge_coordinator_headers,
    make_liaison_headers,
    make_payer_rep_headers,
    mark_episode_ready,
    open_barrier,
    read_barriers,
    read_episode,
    read_offer,
    read_provider,
    record_bundle,
    seed_patient,
    seed_payer,
    seed_provider,
    set_logical_clock,
    setup_choice_pending_referral,
    setup_screened_episode,
    submit_authorization,
    validate_error,
    validate_success,
)

UNUSED_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
LAKESIDE = {
    "name": "Lakeside Choice", "coinsurance_pct": 0.200,
    "snf_auth_required": False, "hh_auth_required": False, "auth_expiry_days": 30,
}


def test_a_request_without_the_two_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to this API must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the role that principal is
    acting in. When either header is absent, or when `X-User-Role` is not one of the six
    declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This
    check runs before anything else — before path resolution, before body parsing, before
    any state inspection."

    Design: Corner/rbac/missing_x_user_headers_returns_unauthenticated
    """
    set_logical_clock("2026-08-01T00:00:00Z")

    response = api.get_raw(f"/episodes/{UNUSED_UUID}")

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert response.json()["data"]["error_id"] != "ERR_EPISODE_NOT_FOUND", (
        "authentication runs before path resolution, so the unused id never surfaces"
    )


def test_a_platform_admin_may_not_open_a_case_management_episode(api):
    """PRD §2.1: "Once authentication succeeds, the acting role is matched against the
    roles authorized for the requested operation (see the endpoint table in §4); a role
    that is not listed for an operation receives `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "A `PlatformAdmin` owns the operational registry. It seeds payers, patients,
    post-acute providers, network contracts and transport vehicles, drives the logical
    clock, and reads throughput reports — but it holds no clinical authority whatsoever: it
    cannot screen a patient, cannot place one, cannot decide an authorization, and cannot
    discharge."

    Design: Corner/rbac/platform_admin_cannot_create_episode_returns_forbidden_role
    """
    payer = seed_payer(name="Lakeside Choice", coinsurance_pct=0.200)
    patient = seed_patient(
        payer["id"], mrn="MRN-F001", full_name="Fay Duarte", date_of_birth="1950-01-01",
        prior_admissions_180d=0, lives_alone=False, has_pcp=True,
    )
    body = episode_payload(patient["id"])

    refused = api.create_episode(body, PLATFORM_ADMIN)

    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    from test_helpers import validate_paginated

    _, meta = validate_paginated(api.list_episodes(PLATFORM_ADMIN))
    assert meta["total_count"] == 0

    accepted = validate_success(api.create_episode(body, CASE_MANAGER), 201)
    assert accepted["case_status"] == "ADMITTED", (
        "the very same body is admissible for a CaseManager"
    )


def test_a_liaison_may_not_withdraw_another_providers_offer(api):
    """PRD §2.1: "When `X-User-Role` is `PostAcuteLiaison`, `X-User-ID` is the `id` of the
    acting `PostAcuteProvider`; ownership checks compare the resource's provider
    foreign-key field to `X-User-ID`, so creating a bed offer requires the offering
    `provider_id` to be `X-User-ID`, and withdrawing an offer requires that offer's
    `provider_id` to be `X-User-ID`. When either of these two entity-backed roles acts on a
    resource it does not own, the request is rejected with `ERR_NOT_OWNER` (HTTP 403)."
    PRD §3.4: "A liaison may withdraw its own outstanding offer, which moves it to
    `WITHDRAWN`, decrements that provider's `held_bed_units`, and makes the hold interval
    immediately reusable; withdrawing an offer that belongs to another provider is
    `ERR_NOT_OWNER`, and withdrawing one that is no longer `OFFERED` is
    `ERR_INVALID_OFFER_STATE`."

    Design: Corner/rbac/liaison_cannot_withdraw_another_providers_offer_returns_not_owner
    """
    env = setup_choice_pending_referral(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-F002", "full_name": "Gil Espino", "date_of_birth": "1949-02-02",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        offer={"daily_rate_cents": 30000},
    )

    refused = api.withdraw_offer(
        env["offer"]["id"], make_liaison_headers(env["provider_b"]["id"])
    )

    validate_error(refused, ApiErrorId.ERR_NOT_OWNER, 403)
    assert read_offer(env["offer"]["id"])["status"] == "OFFERED"
    assert read_provider(env["provider_a"]["id"])["held_bed_units"] == 1

    accepted = validate_success(
        api.withdraw_offer(env["offer"]["id"], make_liaison_headers(env["provider_a"]["id"]))
    )
    assert accepted["status"] == "WITHDRAWN"


def test_a_payer_representative_may_not_decide_another_payers_authorization(api):
    """PRD §2.1: "When `X-User-Role` is `PayerRepresentative`, `X-User-ID` is the `id` of
    the acting `Payer`; ownership checks on any resource that references a `Payer` compare
    the resource's payer foreign-key field to `X-User-ID`, so deciding an authorization
    requires `X-User-ID` to equal that authorization's `payer_id`."
    PRD §3.6: "Only the `PayerRepresentative` whose `X-User-ID` equals the request's
    `payer_id` may decide it; anyone else in that role receives `ERR_NOT_OWNER`."
    PRD §3.6: "The request's `payer_id` is never supplied by the caller: it is copied at
    create time from the episode's patient's `primary_payer_id`."

    Design: Corner/rbac/payer_representative_cannot_decide_another_payers_authorization
    """
    other_payer = seed_payer(name="Payer B", coinsurance_pct=0.150, snf_auth_required=True)
    env = setup_screened_episode(
        payer={"name": "Payer A", "coinsurance_pct": 0.200, "snf_auth_required": True},
        patient={
            "mrn": "MRN-F003", "full_name": "Hal Ferreira", "date_of_birth": "1948-03-03",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    cedar = seed_provider(name="Cedar SNF", bed_unit_codes=["UNIT-A"])
    authorization = submit_authorization(
        env["episode"]["id"], cedar["id"], level_of_care="SNF",
        requested_days=14, billed_daily_rate_cents=30000,
    )

    response = api.decide_authorization(
        authorization["id"], {"decision": "APPROVE"}, make_payer_rep_headers(other_payer["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_OWNER, 403)
    after = validate_success(api.get_authorization(authorization["id"], CASE_MANAGER))
    assert after["status"] == "SUBMITTED"
    assert after["approved_days"] is None
    assert after["payer_id"] == env["payer"]["id"]
    assert read_episode(env["episode"]["id"])["authorized_days_total"] == 0


def test_a_case_manager_may_never_waive_a_barrier(api):
    """PRD §2.10: "Separately, waiving is restricted by role as well as by identity: only a
    `UtilizationReviewNurse` may waive, and a `CaseManager` attempting a waiver is refused
    with `ERR_WAIVER_ROLE_REQUIRED` (HTTP 403) even though the same endpoint admits that
    role for every other barrier transition. The role check precedes the identity check, so
    a `CaseManager` who also opened the barrier sees `ERR_WAIVER_ROLE_REQUIRED`."

    Design: Corner/rbac/case_manager_cannot_waive_barrier_returns_waiver_role_required
    """
    env = setup_screened_episode(
        payer={"name": "Lakeside Choice", "coinsurance_pct": 0.200},
        patient={
            "mrn": "MRN-F004", "full_name": "Ivy Gomes", "date_of_birth": "1947-04-04",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    barrier = open_barrier(
        env["episode"]["id"], barrier_code="TRANSPORT", severity="MEDIUM",
        delay_reason_code="AWAITING_TRANSPORT",
    )
    assert barrier["opened_by_user_id"] == "cm-alpha"

    refused = api.change_barrier_status(
        barrier["id"], {"to_status": "WAIVED"}, SECOND_CASE_MANAGER
    )

    validate_error(refused, ApiErrorId.ERR_WAIVER_ROLE_REQUIRED, 403)
    assert refused.json()["data"]["error_id"] != "ERR_SEGREGATION_OF_DUTIES", (
        "cm-gamma did not open the barrier, so only the role check can fire"
    )
    current = read_barriers(env["episode"]["id"])[0]
    assert current["status"] == "OPEN"
    assert current["clock_stop_at"] is None

    accepted = validate_success(
        api.change_barrier_status(barrier["id"], {"to_status": "WAIVED"}, UR_NURSE)
    )
    assert accepted["status"] == "WAIVED"


def test_a_nurse_may_not_waive_the_barrier_she_opened_herself(api):
    """PRD §2.10: "Segregation of duties is enforced at two points, both under
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The `DischargeCoordinator` performing a
    discharge must have an `X-User-ID` different from the episode's
    `marked_ready_by_user_id`. The `UtilizationReviewNurse` waiving a barrier must have an
    `X-User-ID` different from that barrier's `opened_by_user_id`."
    PRD §3.3: "A waiver does more than close the current interval — it erases the barrier
    from the delay accounting entirely, including intervals that had already been closed
    before the waiver."

    Design: Corner/rbac/barrier_opener_cannot_waive_own_barrier_returns_segregation_of_duties
    """
    env = setup_screened_episode(
        payer={"name": "Lakeside Choice", "coinsurance_pct": 0.200},
        patient={
            "mrn": "MRN-F005", "full_name": "Jed Haile", "date_of_birth": "1946-05-05",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    barrier = validate_success(
        api.create_barrier(
            env["episode"]["id"],
            {"barrier_code": "GUARDIANSHIP", "severity": "HIGH",
             "delay_reason_code": "AWAITING_FAMILY"},
            UR_NURSE,
        ),
        201,
    )
    assert barrier["opened_by_user_id"] == "ur-beta"

    refused = api.change_barrier_status(barrier["id"], {"to_status": "WAIVED"}, UR_NURSE)

    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    assert read_barriers(env["episode"]["id"])[0]["status"] == "OPEN"

    accepted = validate_success(
        api.change_barrier_status(barrier["id"], {"to_status": "WAIVED"}, SECOND_UR_NURSE)
    )
    assert accepted["status"] == "WAIVED"
    episode = read_episode(env["episode"]["id"])
    assert episode["barrier_posture"] == "CLEAR"
    assert episode["avoidable_delay_hours"] == 0.0


def test_the_operator_who_declared_readiness_may_not_execute_the_discharge(api):
    """PRD §2.10: "Segregation of duties is enforced at two points, both under
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The `DischargeCoordinator` performing a
    discharge must have an `X-User-ID` different from the episode's
    `marked_ready_by_user_id`."
    PRD §3.8: "The acting `X-User-ID` must differ from the episode's
    `marked_ready_by_user_id`, or the refusal is `ERR_SEGREGATION_OF_DUTIES` — the
    four-eyes control that keeps one operator from both declaring and executing a
    discharge."

    Design: Corner/rbac/discharge_by_the_operator_who_marked_ready_returns_segregation_of_duties
    """
    env = setup_screened_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-F006", "full_name": "Kai Idris", "date_of_birth": "1945-06-06",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    record_bundle(env["episode"]["id"], pcp_followup_booked=True)
    ready = mark_episode_ready(env["episode"]["id"], "HOME_SELF_CARE")
    assert ready["marked_ready_by_user_id"] == "cm-alpha"

    refused = api.discharge_episode(
        env["episode"]["id"], make_discharge_coordinator_headers("cm-alpha")
    )

    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    blocked = read_episode(env["episode"]["id"])
    assert blocked["case_status"] == "READY_FOR_DISCHARGE"
    assert blocked["discharged_at"] is None

    discharged = validate_success(
        api.discharge_episode(
            env["episode"]["id"], make_discharge_coordinator_headers("dc-beta")
        )
    )
    assert discharged["case_status"] == "DISCHARGED"
