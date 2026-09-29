"""Authentication, authorization, the contract-party binding and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assess_and_dispute_penalty,
    create_contract_payload,
    make_building_manager_headers,
    make_contractor_headers,
    open_renegotiation,
    read_contract,
    read_penalty,
    read_round,
    read_visit,
    run_callback_cycle,
    schedule_and_perform_visit,
    set_clock,
    setup_contract_scoring_fifty,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_request_without_auth_headers_is_unauthenticated(api, anonymous_headers):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the
    five role names defined below spelled exactly, the request is rejected with
    `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/rbac/request_missing_x_user_role_header_returns_unauthenticated
    """
    payload = create_contract_payload(
        building_name="Rb Six",
        building_address="7 Rb St",
        building_manager_user_id="bm-r6",
        contractor_user_id="sc-r6",
    )
    validate_error(
        api.create_contract(payload, anonymous_headers),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    rows, meta = validate_paginated(api.list_contracts(TEST_USERS["admin_headers"]))
    assert meta["total_count"] == 0, "an unauthenticated request must write nothing"
    assert rows == []


def test_authorization_is_decided_before_the_body_is_validated(api, inspector_headers):
    """PRD §2.7: "The presented role appears in the called endpoint's authorised-role
    list, otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
    PRD §3.1: "Every program begins with a service contract drafted by a
    `ProgramAdministrator`."
    PRD §2.7: "Checks are applied strictly in the sequence below and **the first
    check that fails determines the response**; no later check is consulted."

    Design: Corner/validations/state_inspector_cannot_create_a_contract_returns_unauthorized
    """
    payload = create_contract_payload(
        building_name="Val Two",
        building_address="2 Val St",
        building_manager_user_id="bm-v2",
        contractor_user_id="sc-v2",
    )
    payload.pop("monthly_base_fee_cents")

    error = validate_error(
        api.create_contract(payload, inspector_headers),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_VALIDATION.value, (
        "authorization is checked before body schema, so the missing field is not reported"
    )


def test_contractor_may_not_verify_the_visit_it_performed(api):
    """PRD §3.2: "Verification is the `BuildingManager`'s move and drives
    `PERFORMED → VERIFIED`, stamping `verified_at` and `verified_by_user_id`."
    PRD §2.1: "If both headers are well formed but the declared role is not among
    the roles authorised for the endpoint being called, the request is rejected with
    `ERR_UNAUTHORIZED` and HTTP 403."

    Design: Corner/rbac/contractor_cannot_verify_a_visit_returns_unauthorized
    """
    program = setup_program(
        ["CAR-R1"],
        building_name="Rb One",
        building_address="1 Rb St",
        building_manager_user_id="bm-r1",
        contractor_user_id="sc-r1",
    )
    visit = schedule_and_perform_visit(program, program.car_id(), "2026-08", "2026-08-10")

    validate_error(
        api.verify_visit(visit["id"], program.contractor_headers),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    assert read_visit(visit["id"])["status"] == "PERFORMED"


def test_building_manager_of_another_contract_cannot_dispute_this_visit(api):
    """PRD §2.1: "When `X-User-Role` is `BuildingManager`, `X-User-ID` must equal the
    governing `ServiceContract`'s `building_manager_user_id`; when `X-User-Role` is
    `ServiceContractor`, `X-User-ID` must equal that contract's
    `contractor_user_id`. A mismatch is rejected with `ERR_NOT_CONTRACT_PARTY` and
    HTTP 403."
    PRD §3.2: "When the work does not measure up, the same `BuildingManager` disputes
    it instead, driving `PERFORMED → DISPUTED` with a `dispute_reason` recorded on
    the visit and `rework_count` incremented by 1."

    Design: Corner/rbac/building_manager_of_another_contract_cannot_dispute_this_visit
    """
    program_a = setup_program(
        ["CAR-R2"],
        building_name="Rb Two A",
        building_address="2 Rb St",
        building_manager_user_id="bm-r2",
        contractor_user_id="sc-r2",
    )
    setup_program(
        building_name="Rb Two B",
        building_address="3 Rb St",
        building_manager_user_id="bm-other",
        contractor_user_id="sc-other",
    )
    visit = schedule_and_perform_visit(
        program_a, program_a.car_id(), "2026-08", "2026-08-10"
    )

    error = validate_error(
        api.dispute_visit(
            visit["id"],
            {"dispute_reason": "not my building"},
            make_building_manager_headers("bm-other"),
        ),
        ApiErrorId.ERR_NOT_CONTRACT_PARTY.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value, (
        "the role is authorised; only the identity binding fails"
    )

    stored = read_visit(visit["id"])
    assert stored["status"] == "PERFORMED"
    assert stored["rework_count"] == 0


def test_a_user_holding_both_party_ids_cannot_verify_its_own_visit(api):
    """PRD §2.6: "Verifying a maintenance visit requires an `X-User-ID` different
    from the visit's `performed_by_user_id`."
    PRD §3.2: "and the verifying `X-User-ID` must differ from the recorded
    `performed_by_user_id`, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/one_person_holding_both_party_ids_cannot_verify_own_visit
    """
    program = setup_program(
        ["CAR-R5"],
        building_name="Rb Five",
        building_address="6 Rb St",
        building_manager_user_id="dual-1",
        contractor_user_id="dual-1",
    )
    visit = schedule_and_perform_visit(program, program.car_id(), "2026-08", "2026-08-10")
    assert visit["performed_by_user_id"] == "dual-1"
    assert visit["missing_task_codes"] == []

    validate_error(
        api.verify_visit(visit["id"], make_building_manager_headers("dual-1")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    stored = read_visit(visit["id"])
    assert stored["status"] == "PERFORMED"
    assert stored["verified_by_user_id"] is None


def test_assessing_administrator_may_not_resolve_the_same_penalty(api):
    """PRD §2.6: "Resolving a disputed penalty requires an `X-User-ID` different from
    that assessment's `assessed_by_user_id`."
    PRD §3.8: "Resolution is then a `ProgramAdministrator`'s decision, and it must be
    a *different* administrator than the one recorded in `assessed_by_user_id`."
    PRD §3.8: "`DISPUTED → UPHELD` leaves `penalty_balance_cents` unchanged — the
    penalty stands."

    Design: Corner/rbac/the_assessing_administrator_cannot_resolve_the_same_penalty
    """
    program = setup_program(
        ["CAR-R3"],
        building_name="Rb Three",
        building_address="4 Rb St",
        building_manager_user_id="bm-r3",
        contractor_user_id="sc-r3",
        monthly_base_fee_cents=480_000,
    )
    run_callback_cycle(
        program,
        program.car_id(),
        reported_at="2026-08-04T09:00:00Z",
        arrived_at="2026-08-04T11:00:00Z",
        out_of_service=False,
        resolution_note="late",
    )
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)
    penalty = assess_and_dispute_penalty(program, "2026-08", "disputed")
    assert penalty["assessed_by_user_id"] == "pa-1"

    validate_error(
        api.resolve_penalty(
            penalty["id"],
            {"resolution": "WAIVED", "resolution_note": "self-waiver attempt"},
            program.admin_headers,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    assert read_penalty(penalty["id"])["status"] == "DISPUTED"

    resolved = validate_success(
        api.resolve_penalty(
            penalty["id"],
            {"resolution": "UPHELD", "resolution_note": "independent review"},
            program.second_admin_headers,
        )
    )
    assert resolved["status"] == "UPHELD"
    assert resolved["resolved_by_user_id"] == "pa-2"
    assert read_contract(program.contract_id)["penalty_balance_cents"] == 25_000


def test_round_opener_may_not_accept_its_own_proposal(api):
    """PRD §2.6: "Countering or accepting a renegotiation round requires an
    `X-User-ID` different from that round's `opened_by_user_id` — a party may not
    negotiate with itself in either direction."
    PRD §3.9: "Either party may accept an `OPEN` round while the contract is
    `UNDER_RENEGOTIATION`, provided the acting `X-User-ID` differs from that round's
    `opened_by_user_id` — a party cannot accept its own proposal. The round moves
    `OPEN → ACCEPTED` with `accepted_by_user_id` stamped, and the contract is
    rewritten from the proposal: `monthly_base_fee_cents` takes
    `proposed_monthly_fee_cents`, `callback_response_minutes` takes
    `proposed_callback_response_minutes`, and `scope_type` takes
    `proposed_scope_type`."

    Design: Corner/rbac/the_round_opener_cannot_accept_their_own_proposal
    """
    program = setup_contract_scoring_fifty(
        car_code="CAR-R4",
        manager_user_id="bm-r4",
        contractor_user_id="sc-r4",
        building_name="Rb Four",
        building_address="5 Rb St",
    )
    opened = open_renegotiation(
        program,
        proposed_monthly_fee_cents=330_000,
        proposed_callback_response_minutes=45,
        proposed_scope_type="FULL_MAINTENANCE",
    )
    assert opened["opened_by_user_id"] == "bm-r4"

    validate_error(
        api.accept_renegotiation(opened["id"], make_building_manager_headers("bm-r4")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    assert read_round(opened["id"])["status"] == "OPEN"
    assert read_contract(program.contract_id)["monthly_base_fee_cents"] == 400_000

    accepted = validate_success(
        api.accept_renegotiation(opened["id"], make_contractor_headers("sc-r4"))
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_by_user_id"] == "sc-r4"

    contract = read_contract(program.contract_id)
    assert contract["monthly_base_fee_cents"] == 330_000
    assert contract["status"] == "ACTIVE"
