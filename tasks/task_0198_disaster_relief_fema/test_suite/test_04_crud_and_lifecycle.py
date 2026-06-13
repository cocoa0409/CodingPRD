"""Breadth coverage: entity CRUD, identity/defaults/computed fields, FK existence,
listing/pagination, state-machine initial states, invalid transitions, terminal
lockdown, cascades, and lifecycle transitions. (Corner queue: entities,
state_machines, calculations sections.)
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    api_client, TEST_USERS, ApiErrorId, ZERO_UUID,
    make_caseworker_headers, make_inspector_headers,
    create_declaration_payload, create_inspector_payload, create_applicant_payload,
    create_dob_record_payload,
    setup_program, setup_scheduled_assessment, setup_approved_case,
    setup_disbursing_case_with_late_dob_recoupment,
    get_line_item, disburse, current_case_version,
)

ADMIN = TEST_USERS["program_admin_headers"]
CW = TEST_USERS["caseworker_headers"]


# ─── entities ──────────────────────────────────────────────────────────────
def test_create_declaration_returns_201_open(api):
    """PRD §3.1: "A declaration is born `OPEN`."
    PRD §4: "Operations that create a new resource return `201 Created`."

    POST /declarations returns 201 with status OPEN and a server-minted UUID id.

    Design: Corner/entities/create_declaration_returns_201_with_fields
    """
    get_success_data(api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, ADMIN))
    data = validate_success(
        api_client.create_declaration(create_declaration_payload(title="DR-E1"), ADMIN),
        expected_status=201,
    )
    assert data["status"] == "OPEN", data["status"]
    assert is_valid_uuid(data["id"]), data["id"]


def test_get_declaration_returns_stored_entity(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    PRD §3.1: "a per-household financial-assistance cap `ihp_max_grant_cents`".

    GET /declarations/{id} returns the same ihp_max_grant_cents persisted at create.

    Design: Corner/entities/get_declaration_returns_stored_entity
    """
    get_success_data(api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, ADMIN))
    created = get_success_data(api_client.create_declaration(
        create_declaration_payload(title="DR-E2", ihp_max_grant_cents=4_250_000), ADMIN))
    data = validate_success(api_client.get_declaration(created["id"], CW))
    assert data["ihp_max_grant_cents"] == 4_250_000, data["ihp_max_grant_cents"]


def test_list_declarations_paginated_envelope(api):
    """PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."

    GET /declarations returns a paginated array envelope with total_count and has_more.

    Design: Corner/entities/list_declarations_paginated_envelope
    """
    get_success_data(api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, ADMIN))
    get_success_data(api_client.create_declaration(create_declaration_payload(title="DR-E3"), ADMIN))
    data, meta = validate_paginated(api_client.list_declarations(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] >= 1, meta["total_count"]
    assert isinstance(meta["has_more"], bool)
    assert len(data) <= 1, len(data)


def test_get_applicant_nonexistent_returns_404(api):
    """PRD §2.5: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected with the not-found error specific to that
    resource type — `ERR_DECLARATION_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`,
    `ERR_CASEWORKER_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`, ... — each carrying HTTP 404."

    GET /applicants/{nonexistent} -> ERR_APPLICANT_NOT_FOUND (404).

    Design: Corner/entities/get_applicant_nonexistent_returns_404
    """
    resp = api_client.get_applicant(ZERO_UUID, CW)
    validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_FOUND.value)


def test_create_applicant_missing_required_field_422(api):
    """PRD §3.2: "Registration captures the `declaration_id` the household is
    registering under, the `household_name` of the head of household, the
    `household_size` (which must be at least 1), the self-reported `annual_income_cents`
    (which must be at least 0 and later feeds the SBA income test), the `damage_date` on
    which the disaster damage occurred, and three self-reported loss figures that drive
    the provisional award: `reported_repair_cost_cents`, `reported_personal_property_cents`,
    and `reported_rental_months` (each at least 0)."
    PRD §3.12: "Last of all comes generic field-level request validation — types, enum
    membership, required fields, non-negative amounts, and end-after-start ordering —
    which yields `ERR_INVALID_REQUEST`."

    Omitting household_size (a required input field) -> ERR_INVALID_REQUEST (422).

    Design: Corner/entities/create_applicant_missing_required_field_422
    """
    get_success_data(api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, ADMIN))
    decl = get_success_data(api_client.create_declaration(create_declaration_payload(title="DR-E5"), ADMIN))
    payload = create_applicant_payload(decl["id"], household_name="NoSize")
    del payload["household_size"]
    resp = api_client.create_applicant(payload, CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_inspector_travel_buffer_default_applied(api):
    """PRD §3.1: "An `Inspector` is created with a `full_name` and a `badge_number` that
    must be unique across all inspectors, plus an optional `travel_buffer_minutes` that
    defaults to 30 and expresses the minimum gap the inspector needs between two
    appointments."

    Creating an inspector without travel_buffer_minutes applies the default 30.

    Design: Corner/entities/inspector_travel_buffer_default_applied
    """
    data = validate_success(
        api_client.create_inspector(
            create_inspector_payload(full_name="Default Insp", badge_number="INS-DEF"), ADMIN),
        expected_status=201,
    )
    assert data["travel_buffer_minutes"] == 30, data["travel_buffer_minutes"]


def test_applicant_total_dob_initialized_to_zero(api):
    """PRD §3.2: "A newly registered applicant starts in `REGISTERED` with
    `total_dob_cents` initialized to 0."

    total_dob_cents is a server-reconciled field that begins at 0 at registration.

    Design: Corner/entities/applicant_total_dob_computed_ignores_client_input
    """
    get_success_data(api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, ADMIN))
    decl = get_success_data(api_client.create_declaration(create_declaration_payload(title="DR-E7"), ADMIN))
    data = validate_success(
        api_client.create_applicant(
            create_applicant_payload(decl["id"], household_name="Comp Household"), CW),
        expected_status=201,
    )
    assert data["total_dob_cents"] == 0, data["total_dob_cents"]


def test_dob_record_invalid_source_type_enum_422(api):
    """PRD §3.5: "A `ProgramAdmin` or `Caseworker` records one with the `applicant_id`,
    the `source_type` (one of `INSURANCE`, `SBA_LOAN`, `CHARITY`, `OTHER_FEDERAL`), the
    `amount_cents` (at least 0), and `received_at`, the instant the benefit was received
    or settled, which determines whether it counts as known at award time or as a late
    arrival."
    PRD §3.12: "Last of all comes generic field-level request validation — types, enum
    membership, required fields, non-negative amounts, and end-after-start ordering —
    which yields `ERR_INVALID_REQUEST`."

    source_type outside the enum -> ERR_INVALID_REQUEST (422).

    Design: Corner/entities/applicant_invalid_enum_source_type_on_dob_422
    """
    get_success_data(api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, ADMIN))
    decl = get_success_data(api_client.create_declaration(create_declaration_payload(title="DR-E9"), ADMIN))
    applicant = get_success_data(api_client.create_applicant(
        create_applicant_payload(decl["id"], household_name="Enum Household"), CW))
    resp = api_client.create_dob_record(
        create_dob_record_payload(applicant["id"], source_type="LOTTERY",
                                  amount_cents=100_000, received_at="2026-02-01T00:00:00Z"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_award_line_items_read_only_filtered_list_empty(api):
    """PRD §4: the award-line-items resource exposes only "GET
    `/disaster-relief/award-line-items` | List award line items" and "GET
    `/disaster-relief/award-line-items/{id}` | Get an award line item" — no client
    create/update/delete endpoint.
    PRD §2.5: "List endpoints support reverse-reachability filters by foreign key.
    Applicants may be filtered by `declaration_id`; assessments by `applicant_id` or
    `inspector_id`; IHP cases by `applicant_id`, `assessment_id`, or
    `determined_by_caseworker_id`; award line items by `ihp_case_id`".

    A filtered list for a non-existent case returns 200 with an empty array, confirming
    award line items are discoverable only by the read-only filtered GET.

    Design: Corner/entities/award_line_item_immutable_no_update_endpoint
    """
    data, meta = validate_paginated(
        api_client.list_award_line_items(CW, params={"ihp_case_id": ZERO_UUID}))
    assert data == [], data
    assert meta["total_count"] == 0, meta["total_count"]


def test_applicant_requires_existing_declaration_parent(api):
    """PRD §2.5: "Existence is validated left to right: any resource `id` appearing in
    the path is checked first, then any required foreign-key field in the request body,
    in declaration order."
    PRD §2.5: the not-found error for a declaration FK is `ERR_DECLARATION_NOT_FOUND`,
    "each carrying HTTP 404."

    POST /applicants with a non-existent declaration_id -> ERR_DECLARATION_NOT_FOUND.

    Design: Corner/entities/applicant_requires_existing_declaration_parent
    """
    get_success_data(api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, ADMIN))
    resp = api_client.create_applicant(
        create_applicant_payload(ZERO_UUID, household_name="Orphan"), CW)
    validate_error(resp, ApiErrorId.ERR_DECLARATION_NOT_FOUND.value)


def test_list_applicants_filtered_by_declaration(api):
    """PRD §2.5: "List endpoints support reverse-reachability filters by foreign key.
    Applicants may be filtered by `declaration_id`".
    PRD §2.5: "All business resources are peer collections under `/disaster-relief`;
    the URL hierarchy never nests one business resource inside another."

    GET /applicants?declaration_id resolves the FK reverse path; every element belongs
    to that declaration.

    Design: Corner/entities/flat_fk_reverse_list_applicants_by_declaration
    """
    get_success_data(api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, ADMIN))
    decl = get_success_data(api_client.create_declaration(create_declaration_payload(title="DR-FK"), ADMIN))
    get_success_data(api_client.create_applicant(
        create_applicant_payload(decl["id"], household_name="Fk Household"), CW))
    data, _ = validate_paginated(api_client.list_applicants(ADMIN, params={"declaration_id": decl["id"]}))
    assert len(data) >= 1, len(data)
    for a in data:
        assert a["declaration_id"] == decl["id"], a["declaration_id"]


# ─── state_machines ────────────────────────────────────────────────────────
def test_applicant_initial_state_registered(api):
    """PRD §3.2: "A newly registered applicant starts in `REGISTERED` with
    `total_dob_cents` initialized to 0."

    A freshly registered applicant has status REGISTERED.

    Design: Corner/state_machines/applicant_initial_state_registered
    """
    get_success_data(api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, ADMIN))
    decl = get_success_data(api_client.create_declaration(create_declaration_payload(title="DR-SM1"), ADMIN))
    data = validate_success(
        api_client.create_applicant(
            create_applicant_payload(decl["id"], household_name="Sm1 Household"), CW),
        expected_status=201,
    )
    assert data["status"] == "REGISTERED", data["status"]


def test_verify_scheduled_assessment_invalid_transition(api):
    """PRD §3.2: "A `Caseworker` then verifies the inspected assessment, advancing it
    `INSPECTED → VERIFIED`; this requires the assessment to be `INSPECTED` (otherwise
    `ERR_ASSESSMENT_NOT_INSPECTED`)."

    Verifying a still-SCHEDULED (never inspected) assessment -> ERR_ASSESSMENT_NOT_INSPECTED.

    Design: Corner/state_machines/verify_assessment_not_inspected_invalid_transition
    """
    ctx = setup_scheduled_assessment(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-SM2"},
        inspector_badge="INS-SM2", cw_employee_id="CW-SM2",
        applicant_overrides={"household_name": "Sm2 Household"},
    )
    resp = api_client.verify_assessment(ctx["assessment"]["id"], ctx["caseworker_headers"])
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_INSPECTED.value)


def test_deny_already_approved_case_invalid_state(api):
    """PRD §3.4: "Both actions require the case to be `ELIGIBILITY_PENDING` (otherwise
    `ERR_CASE_NOT_PENDING`)".

    Denying an already-AWARD_APPROVED case -> ERR_CASE_NOT_PENDING.

    Design: Corner/state_machines/deny_case_already_approved_invalid_state
    """
    ctx = setup_approved_case(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-SM3"},
        inspector_badge="INS-SM3", cw_employee_id="CW-SM3",
        applicant_overrides={"household_name": "Sm3 Household"},
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 1_000_000,
            "verified_personal_property_cents": 500_000, "verified_rental_months": 3,
        },
        monthly_fmr_cents=100_000,
    )
    resp = api_client.deny_ihp_case(ctx["case"]["id"], ctx["caseworker_headers"])
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_PENDING.value)


def test_reverse_already_reversed_dob_terminal_lockdown(api):
    """PRD §3.5: "A `ProgramAdmin` may reverse a `RECORDED` DOB record, moving it
    `RECORDED → REVERSED`; this requires the record to be `RECORDED` (otherwise
    `ERR_DOB_NOT_RECORDED`)."

    A DobRecord already in terminal REVERSED cannot be reversed again ->
    ERR_DOB_NOT_RECORDED.

    Design: Corner/state_machines/reverse_already_reversed_dob_terminal_lockdown
    """
    get_success_data(api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, ADMIN))
    decl = get_success_data(api_client.create_declaration(create_declaration_payload(title="DR-SM4"), ADMIN))
    applicant = get_success_data(api_client.create_applicant(
        create_applicant_payload(decl["id"], household_name="Sm4 Household"), CW))
    dob = get_success_data(api_client.create_dob_record(
        create_dob_record_payload(applicant["id"], source_type="CHARITY",
                                  amount_cents=200_000, received_at="2026-02-01T00:00:00Z"), ADMIN))
    get_success_data(api_client.reverse_dob_record(dob["id"], ADMIN))
    resp = api_client.reverse_dob_record(dob["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_DOB_NOT_RECORDED.value)


def test_withdraw_applicant_cancels_scheduled_assessment(api):
    """PRD §3.2: "A household that has not yet progressed can be withdrawn by a
    `Caseworker` or `ProgramAdmin`, moving the applicant to `WITHDRAWN`. Withdrawal is
    permitted only while the applicant is `REGISTERED` or `INSPECTION_SCHEDULED`
    (otherwise `ERR_APPLICANT_NOT_WITHDRAWABLE`), and as a side effect any `SCHEDULED`
    `DamageAssessment` belonging to that applicant is transitioned to `CANCELLED`, which
    frees the inspector's calendar slot."

    Withdrawing an INSPECTION_SCHEDULED applicant moves it to WITHDRAWN and cascades the
    SCHEDULED assessment to CANCELLED.

    Design: Corner/state_machines/withdraw_applicant_cancels_scheduled_assessment_cascade
    """
    ctx = setup_scheduled_assessment(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-SM5"},
        inspector_badge="INS-SM5", cw_employee_id="CW-SM5",
        applicant_overrides={"household_name": "Sm5 Household"},
    )
    app_id = ctx["applicant"]["id"]
    asm_id = ctx["assessment"]["id"]
    app = validate_success(api_client.withdraw_applicant(app_id, ctx["caseworker_headers"]))
    assert app["status"] == "WITHDRAWN", app["status"]
    asm = get_success_data(api_client.get_assessment(asm_id, ctx["inspector_headers"]))
    assert asm["status"] == "CANCELLED", asm["status"]


def test_recoupment_satisfied_when_recovery_reaches_debt(api):
    """PRD §3.9: "A `ProgramAdmin` records recoveries against an established debt. Each
    recovery adds its `amount_cents` to the recoupment's `recovered_cents`. When
    cumulative `recovered_cents` reaches or exceeds `debt_amount_cents`, the recoupment
    advances `ESTABLISHED → SATISFIED`."

    Recording recovery 600,000 against a 600,000 LATE_DOB debt moves the recoupment to
    SATISFIED.

    Design: Corner/state_machines/recoupment_satisfied_when_recovery_reaches_debt
    """
    ctx = setup_disbursing_case_with_late_dob_recoupment(
        decl_overrides={"title": "DR-SM6"}, inspector_badge="INS-SM6", cw_employee_id="CW-SM6")
    recoup_id = ctx["recoupment"]["id"]
    recoup = validate_success(api_client.record_recovery(recoup_id, {"amount_cents": 600_000}, ADMIN))
    assert recoup["recovered_cents"] == 600_000, recoup["recovered_cents"]
    assert recoup["status"] == "SATISFIED", recoup["status"]


def test_close_case_blocked_with_open_recoupment(api):
    """PRD §3.9: "A `Caseworker` or `ProgramAdmin` closes a case, moving it
    `DISBURSING → CLOSED`; this requires the case to be `DISBURSING` (otherwise
    `ERR_CASE_NOT_DISBURSING`) and requires that no `Recoupment` on the case is in
    `ESTABLISHED` status (otherwise `ERR_OPEN_RECOUPMENT`)."

    Closing a DISBURSING case while an ESTABLISHED LATE_DOB recoupment exists ->
    ERR_OPEN_RECOUPMENT.

    Design: Corner/state_machines/close_case_blocked_with_open_recoupment
    """
    ctx = setup_disbursing_case_with_late_dob_recoupment(
        decl_overrides={"title": "DR-SM7"}, inspector_badge="INS-SM7", cw_employee_id="CW-SM7")
    resp = api_client.close_ihp_case(ctx["case"]["id"], ctx["caseworker_headers"])
    validate_error(resp, ApiErrorId.ERR_OPEN_RECOUPMENT.value)


# ─── calculations ──────────────────────────────────────────────────────────
def test_sba_referral_loss_threshold_qualifies_pass(api):
    """PRD §3.7: "The referral is eligibility-gated: it is permitted only if the
    applicant's `annual_income_cents` is at or below the income ceiling of $75,000
    (7,500,000 cents), or the verified total loss is strictly greater than the loss
    threshold of $30,000 (3,000,000 cents). The verified total loss is the sum of the
    assessment's `verified_repair_cost_cents` and `verified_personal_property_cents`."
    PRD §3.7: "On a successful create the verified total loss is snapshotted into
    `referred_loss_cents` and the referral is born `REFERRED`."

    Income 8,000,000 (> ceiling) but verified loss 3,000,001 (> threshold) qualifies:
    REFERRED with referred_loss_cents 3,000,001.

    Design: Corner/calculations/sba_referral_loss_threshold_qualifies_pass
    """
    ctx = setup_approved_case(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-CA1"},
        inspector_badge="INS-CA1", cw_employee_id="CW-CA1",
        applicant_overrides={
            "household_name": "Ca1 Household", "household_size": 2,
            "annual_income_cents": 8_000_000,
            "reported_repair_cost_cents": 2_000_001,
            "reported_personal_property_cents": 1_000_000, "reported_rental_months": 0,
        },
        inspect_overrides={
            "habitability": "HABITABLE",
            "verified_repair_cost_cents": 2_000_001,
            "verified_personal_property_cents": 1_000_000, "verified_rental_months": 0,
        },
        monthly_fmr_cents=100_000,
    )
    cw_h = ctx["caseworker_headers"]
    data = validate_success(
        api_client.create_sba_referral({"ihp_case_id": ctx["case"]["id"]}, cw_h),
        expected_status=201,
    )
    assert data["status"] == "REFERRED", data["status"]
    assert data["referred_loss_cents"] == 3_000_001, data["referred_loss_cents"]
