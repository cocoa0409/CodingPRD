"""Exclusive operations, the one read every role shares, and segregation of duties."""
from test_helpers import (
    ANALYST,
    ApiClient,
    ApiErrorId,
    assert_pagination_meta,
    cast_vote,
    complaint_payload,
    make_applicant_headers,
    make_board_member_headers,
    make_investigator_headers,
    make_monitoring_coordinator_headers,
    make_system_admin_headers,
    mint_license,
    monitoring_agreement_payload,
    nurse_payload,
    record_hearing_event,
    reread_license,
    reread_proceeding,
    seed_active_license,
    seed_atd_offered_complaint,
    seed_board,
    seed_nurse,
    seed_proceeding,
    seed_referred_complaint,
    seed_referred_context,
    seed_screened_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_only_licensure_staff_may_mint_a_credential(api: ApiClient):
    """PRD §3.3: "Once an application stands at `APPROVED`, a `LicensureAnalyst`
    mints the credential."

    PRD §2.11: "The caller's role is authorised for the endpoint — otherwise
    `ERR_FORBIDDEN_ROLE`."

    PRD §4: "| POST | `/licenses` | Mint the credential from an APPROVED
    application; nurse, board, credential type, APRN role and base license are
    copied from the application | LicensureAnalyst |"

    Design: Corner/rbac/investigator_cannot_mint_a_license_returns_forbidden_role
    """
    ctx = seed_screened_application(api)
    before = validate_success(api.get_license_application(ctx["application_id"], ANALYST))
    assert before["status"] == "APPROVED", (
        f"The application itself is ready to be minted, got {before['status']}"
    )

    refused = api.create_license({"source_application_id": ctx["application_id"]},
                                 make_investigator_headers("inv-r1"))

    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    _, meta = validate_paginated(
        api.list_licenses(ANALYST, params={"nurse_id": ctx["nurse_id"]})
    )
    assert meta["total_count"] == 0, (
        f"The refusal is about the caller, so no credential exists, got "
        f"{meta['total_count']}"
    )
    after = validate_success(api.get_license_application(ctx["application_id"], ANALYST))
    assert after["status"] == "APPROVED"
    assert after["version"] == before["version"], (
        "A refused call at the role gate mutates nothing"
    )
    minted = mint_license(api, ctx["application_id"])
    assert minted["license_status"] == "ACTIVE", (
        "The identical call by the authorised role succeeds"
    )


def test_a_nurse_may_not_open_a_complaint_even_against_her_own_credential(
    api: ApiClient,
):
    """PRD §3.6: "An `Investigator` intakes a complaint against a credential."

    PRD §2.11: "The caller's role is authorised for the endpoint — otherwise
    `ERR_FORBIDDEN_ROLE`."

    PRD §2.11: "When the caller is an `Applicant`, the ownership chain of §2.1
    resolves to the caller — otherwise `ERR_NOT_RESOURCE_OWNER`."

    PRD §2.1: "On creates, the same comparison is made against the `nurse_id`
    supplied in the body, or against the nurse reached through the `license_id`
    supplied in the body."

    Design: Corner/rbac/applicant_cannot_open_a_complaint_returns_forbidden_role
    """
    ctx = seed_active_license(api)

    refused = api.create_complaint(
        complaint_payload(ctx["license_id"], complainant_type="SELF_REPORT"),
        ctx["applicant_headers"],
    )

    error = validate_error(refused, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert error["error_id"] != ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, (
        "The role gate answers before the ownership gate, even though this caller "
        "does own the credential named in the body"
    )
    _, meta = validate_paginated(
        api.list_complaints(make_investigator_headers(),
                            params={"license_id": ctx["license_id"]})
    )
    assert meta["total_count"] == 0, (
        f"No complaint was intaken, got {meta['total_count']}"
    )
    assert reread_license(api, ctx["license_id"])["encumbrance_status"] == "CLEAR", (
        "The credential's encumbrance dimension never moved"
    )


def test_the_monitoring_coordinator_may_not_create_an_identity_record(api: ApiClient):
    """PRD §3.2: "A nurse identity record is created by a `LicensureAnalyst`, and
    the returned `id` is what that nurse subsequently presents as `X-User-ID`."

    PRD §2.11: "The caller's role is authorised for the endpoint — otherwise
    `ERR_FORBIDDEN_ROLE`."

    PRD §4: "| POST | `/nurses` | Create the nurse identity record an Applicant then
    acts as; the returned identifier is the `X-User-ID` that Applicant presents |
    LicensureAnalyst |"

    Design: Corner/rbac/monitoring_coordinator_cannot_create_a_nurse_returns_forbidden_role
    """
    board = seed_board(api)
    payload = nurse_payload(board["id"], full_name="Kim Vance", birth_year=1991,
                            ssn_last4="3310", declared_primary_state="OH")

    refused = api.create_nurse(payload, make_monitoring_coordinator_headers("mc-r3"))

    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    rows, meta = validate_paginated(api.list_board_nurses(board["id"], ANALYST))
    assert rows == [], "No identity record appeared under the board"
    assert_pagination_meta(meta, 10, 0, 0, False)

    created = validate_success(api.create_nurse(payload, ANALYST), 201)
    assert created["full_name"] == "Kim Vance"
    assert created["status"] == "ACTIVE", (
        "The identical payload is well formed; only the caller was wrong"
    )


def test_every_declared_role_may_read_one_nurse_and_only_staff_may_list_them(
    api: ApiClient,
):
    """PRD §4: "| GET | `/nurses/{id}` | Read one nurse record including the fee
    ledger fields | SystemAdmin, LicensureAnalyst, Investigator, BoardMember,
    MonitoringCoordinator, Applicant |"

    PRD §4: "| GET | `/state-board-configs/{id}/nurses` | List the nurses whose
    declared primary state of residence maps to this board | SystemAdmin,
    LicensureAnalyst, Investigator, BoardMember |"

    PRD §2.1: "The comparison walks whatever chain reaches a nurse: the `Nurse`
    record's own `id` when the nurse resource is addressed directly; `nurse_id` for
    a licence application, a credential, or a monitoring agreement; the credential's
    `nurse_id` reached through a renewal's `license_id`; and the credential's
    `nurse_id` reached through a continuing-education record's
    `renewal_application_id` and then that renewal's `license_id`."

    Design: Corner/rbac/nurse_read_is_a_shared_operation_across_every_declared_role
    """
    board = seed_board(api)
    nurse = seed_nurse(api, board["id"])
    readers = [
        make_system_admin_headers("sa-r4"),
        ANALYST,
        make_investigator_headers("inv-r4"),
        make_board_member_headers("bm-r4"),
        make_monitoring_coordinator_headers("mc-r4"),
        make_applicant_headers(nurse["id"]),
    ]

    reads = [validate_success(api.get_nurse(nurse["id"], headers))
             for headers in readers]

    assert [record["full_name"] for record in reads] == ["Dana Reed"] * 6, (
        "Every declared role reaches the same record, the nurse herself included"
    )
    assert {record["version"] for record in reads} == {1}, (
        "Six reads bumped nothing"
    )
    refused = api.list_board_nurses(board["id"],
                                    make_monitoring_coordinator_headers("mc-r4"))
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_the_presiding_member_is_struck_from_the_panel_and_may_not_vote(
    api: ApiClient,
):
    """PRD §3.8: "Segregation of duties is applied at creation and is not negotiable
    afterwards: the calling board member's identity becomes
    `presiding_member_user_id` and is **removed** from `seated_member_user_ids` if it
    appears there, so the presiding member is never part of the panel that votes."

    PRD §2.11: "The caller casting a panel ballot is not the proceeding's presiding
    member — otherwise `ERR_PRESIDING_MEMBER_CANNOT_VOTE`."

    PRD §3.8: "The proceeding takes `status` `NOTICED`, stamps `noticed_at` from the
    logical clock, starts `continuance_count` at 0, `votes` as an empty array,
    `sanction_floor_tier` and `adopted_sanction_tier` at `NONE`, and
    `ordered_restriction_codes` as an empty array with `order_issued_at` null."

    Design: Corner/rbac/presiding_member_voting_in_its_own_proceeding_returns_presiding_member_cannot_vote
    """
    ctx = seed_referred_context(api)
    proceeding = seed_proceeding(
        api, ctx["complaint_id"], ["bm-sod1", "bm-sod2", "bm-sod3", "bm-sod4"],
        presiding_user_id="bm-sod1",
    )
    assert proceeding["presiding_member_user_id"] == "bm-sod1"
    assert proceeding["seated_member_user_ids"] == ["bm-sod2", "bm-sod3", "bm-sod4"], (
        f"The creator was struck from the panel, got "
        f"{proceeding['seated_member_user_ids']}"
    )
    convened = record_hearing_event(api, proceeding["id"], "CONVENE",
                                    presiding_user_id="bm-sod1")
    assert convened["status"] == "HEARING_CONVENED", (
        "Three unrecused seats are exactly quorum"
    )

    refused = api.cast_vote(proceeding["id"], {"proposed_sanction_tier": "REVOCATION"},
                            make_board_member_headers("bm-sod1"))

    validate_error(refused, ApiErrorId.ERR_PRESIDING_MEMBER_CANNOT_VOTE.value)
    stored = reread_proceeding(api, proceeding["id"])
    assert stored["votes"] == []
    assert stored["adopted_sanction_tier"] == "NONE", (
        "Nothing has been tallied yet"
    )
    accepted = cast_vote(api, proceeding["id"], "bm-sod2", "REVOCATION")
    assert len(accepted["votes"]) == 1, (
        "The identical ballot from a seated member is accepted"
    )


def test_the_member_who_approved_a_diversion_agreement_may_not_judge_that_nurse(
    api: ApiClient,
):
    """PRD §3.8: "Recusals are computed at the same moment:
    `recused_member_user_ids` is populated with every seated member whose identity
    appears as `approved_by_user_id` on any monitoring agreement of the complaint's
    nurse — a board member who once offered this nurse a diversion agreement cannot
    sit in judgement of them."

    PRD §2.11: "The caller casting a panel ballot is seated on the panel and has not
    approved a monitoring agreement for the nurse in question — otherwise
    `ERR_VOTER_CONFLICT_OF_INTEREST`."

    PRD §3.8: "Two conditions must hold: the `hearing_date` current at the moment of
    the convene call must sit at or after `noticed_at` advanced by
    `notice_period_days`, refused otherwise with `ERR_NOTICE_PERIOD_NOT_MET`; and the
    panel must have quorum, meaning the count of `seated_member_user_ids` less
    `recused_member_user_ids` must be at least 3, refused otherwise with
    `ERR_QUORUM_NOT_MET`."

    Design: Corner/rbac/monitoring_approver_voting_on_the_same_nurse_returns_voter_conflict_of_interest
    """
    ctx = seed_active_license(api)
    diverted = seed_atd_offered_complaint(api, ctx["license_id"])
    assert diverted["status"] == "ATD_OFFERED"
    agreement = validate_success(
        api.create_monitoring_agreement(
            monitoring_agreement_payload(ctx["nurse_id"], diverted["id"]),
            make_board_member_headers("bm-appr"),
        ),
        201,
    )
    assert agreement["approved_by_user_id"] == "bm-appr"
    later = seed_referred_complaint(
        api, ctx["license_id"], evidence_overrides={"custodian_code": "ST-LUKE"},
        violation_category="PRACTICE_STANDARD", employer_custodian_codes=["ST-LUKE"],
    )
    proceeding = seed_proceeding(
        api, later["id"], ["bm-appr", "bm-clean1", "bm-clean2", "bm-clean3"],
        presiding_user_id="bm-pres",
    )
    assert proceeding["recused_member_user_ids"] == ["bm-appr"], (
        f"The approver is recused at creation, got "
        f"{proceeding['recused_member_user_ids']}"
    )
    convened = record_hearing_event(api, proceeding["id"], "CONVENE",
                                    presiding_user_id="bm-pres")
    assert convened["status"] == "HEARING_CONVENED", (
        "Four seats less one recusal still reaches quorum"
    )

    refused = api.cast_vote(proceeding["id"], {"proposed_sanction_tier": "PROBATION"},
                            make_board_member_headers("bm-appr"))

    error = validate_error(refused, ApiErrorId.ERR_VOTER_CONFLICT_OF_INTEREST.value)
    assert error["error_id"] != ApiErrorId.ERR_PRESIDING_MEMBER_CANNOT_VOTE.value, (
        "The conflicted member is seated, not presiding"
    )
    assert reread_proceeding(api, proceeding["id"])["votes"] == []
    cast_vote(api, proceeding["id"], "bm-clean1", "PROBATION")
    tallied = cast_vote(api, proceeding["id"], "bm-clean2", "PROBATION")
    assert len(tallied["votes"]) == 2, (
        "Members with no monitoring history vote freely"
    )
    untouched = validate_success(
        api.get_monitoring_agreement(agreement["id"], make_board_member_headers("bm-appr"))
    )
    assert untouched["status"] == "OFFERED", (
        "The refused ballot left the agreement alone"
    )
