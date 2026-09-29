"""Registry creation, initial states, and the identity gate of PRD §2.1.

Every request carries an acting identity and a declared capacity; this module
covers what the registries mint on creation, the initial state of each
lifecycle, and the five ways a caller can be turned away before any business
rule is reached.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_ONE_HEADERS,
    CANONICAL_CLOCK,
    CANONICAL_CLOCK_RENDERED,
    OFFICER_ALPHA_HEADERS,
    OFFICER_ALPHA_USER_ID,
    OFFICER_BETA_HEADERS,
    OFFICER_BETA_USER_ID,
    ApiErrorId,
    add_taxpayer,
    assert_fields,
    assert_list_total,
    draft_agreement,
    enforcement_action_payload,
    make_headers,
    make_representative_headers,
    make_taxpayer_headers,
    open_enforcement_case,
    pre_clearance_payload,
    program_payload,
    read_agreement,
    read_program,
    register_representative,
    register_taxpayer,
    remit_payment,
    ROLE_TAXPAYER,
    draft_return,
    headers_without_role,
    set_clock,
    setup_drafted_agreement,
    setup_executed_agreement,
    setup_program_with_taxpayer,
    taxpayer_payload,
    validate_error,
    validate_success,
)

UNKNOWN_TAXPAYER_ID = "00000000-0000-4000-8000-0000000000ff"
UNKNOWN_PROGRAM_ID = "00000000-0000-4000-8000-0000000000aa"


class TestRegistryCreation:
    """`POST /amnesty/taxpayers` and the fields the server owns (PRD §3.2)."""

    def test_client_supplied_score_and_tier_are_ignored_on_registration(self, api):
        """The registry mints the scoring fields itself and ignores the request.

        PRD §3.2: "Every newly registered taxpayer starts with an
        `escalation_tier` of `T0`, a `compliance_behavior_score` of 100, a
        `nonparticipant_flag` of false, and `open_case_count`,
        `open_enforcement_action_count` and `nonfiler_period_count` all at 0."

        PRD §2.9: "The derived counters and totals named on programs, taxpayers
        and agreements are not free-standing state that clients may set"

        Design: Corner/Table 1 Entities/computed_taxpayer_score_input_ignored_on_creation
        """
        set_clock(api, CANONICAL_CLOCK)

        taxpayer = validate_success(
            api.create_taxpayer(
                taxpayer_payload(
                    legal_name="Sable Creek Mills Inc",
                    tin_last4="7781",
                    compliance_behavior_score=40,
                    escalation_tier="T2",
                    nonparticipant_flag=True,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert_fields(
            taxpayer,
            legal_name="Sable Creek Mills Inc",
            compliance_behavior_score=100,
            escalation_tier="T0",
            nonparticipant_flag=False,
        )


class TestInitialStates:
    """The initial state of every lifecycle the PRD declares (PRD §3)."""

    def test_every_entity_enters_in_its_declared_initial_state(self, api):
        """One sweep over the initial state each workflow declares.

        PRD §3.2: "The case is created with `status` `OPEN`, `closed_at` null,
        and `opened_by_user_id` set from the acting auditor's `X-User-ID`"

        PRD §3.2: "A `Representative` is registered with a `firm_name` and a
        `bar_number` — its state bar or CPA licence number — and begins with
        `status` `ACTIVE`."

        PRD §3.3: "The server sets `representative_id` from the submitting
        representative's `X-User-ID`, leaves `disclosed_taxpayer_id` null, sets
        `status` to `SUBMITTED`, and initialises `round_index` and
        `counter_count` to 0"

        PRD §3.5: "The return records the owning `agreement_id` from the path,
        enters with `status` `DRAFT`, and holds `filed_at`, `accrual_end_date`,
        `penalty_rate_applied` and `assessed_by_user_id` null"

        PRD §3.6: "The payment is created with `status` `APPLIED`, `received_at`
        stamped with the current instant, and `reversal_reason` null."

        PRD §3.9: "The action is created with `status` `DRAFT`, `origin`
        `MANUAL`, `created_by_user_id` set from the drafting auditor,
        `issued_by_user_id`, `issued_at` and `abatement_reason` null."

        Design: Corner/Table 2 State Machines/every_entity_starts_in_its_declared_initial_state
        """
        ctx = setup_executed_agreement(
            api,
            program_overrides={"installment_max_count": 12},
            taxpayer_overrides={
                "legal_name": "Quarry Bend Aggregates LLC",
                "tin_last4": "1102",
            },
        )
        assert_fields(read_program(api, ctx["program"]["id"]), status="OPEN")
        assert_fields(ctx["agreement"], status="EXECUTED")

        case = open_enforcement_case(
            api,
            ctx["taxpayer"]["id"],
            case_type="COLLECTION",
            tax_type="EXCISE_FUEL",
            opened_at="2026-05-04",
        )
        assert_fields(case, status="OPEN", closed_at=None)

        representative = register_representative(
            api, firm_name="Ostrand Advisory", bar_number="BAR-90014"
        )
        assert_fields(representative, status="ACTIVE")

        pre_clearance = validate_success(
            api.create_pre_clearance(
                pre_clearance_payload(
                    ctx["program"]["id"],
                    anonymous_alias="CLIENT-11",
                    estimated_liability_cents=700000,
                    earliest_unfiled_period_start="2024-07-01",
                ),
                make_representative_headers(representative["id"]),
            ),
            201,
        )
        assert_fields(
            pre_clearance,
            status="SUBMITTED",
            screening_result=None,
            round_index=0,
            counter_count=0,
            disclosed_taxpayer_id=None,
        )

        disclosure_return = draft_return(api, ctx)
        assert_fields(disclosure_return, status="DRAFT", filed_at=None)

        payment = remit_payment(api, ctx, 105000, payment_reference="DOWN-1")
        assert_fields(payment, status="APPLIED", unapplied_delta_cents=105000)

        action = validate_success(
            api.create_enforcement_action(
                enforcement_action_payload(
                    ctx["taxpayer"]["id"],
                    ctx["program"]["id"],
                    300000,
                    action_type="NOTICE",
                ),
                AUDITOR_ONE_HEADERS,
            ),
            201,
        )
        assert_fields(
            action, status="DRAFT", origin="MANUAL", issued_by_user_id=None
        )


class TestRoleAuthorization:
    """Header well-formedness and the role table of PRD §2.1 and §4."""

    def test_missing_role_header_is_unauthenticated_before_any_lookup(self, api):
        """Authentication decides first, so the 404 never surfaces.

        PRD §2.1: "Every request must carry two identity headers: `X-User-ID`,
        naming the acting user, and `X-User-Role`, declaring the capacity in
        which that user acts. If either header is absent, or if `X-User-Role` is
        not exactly one of the five recognized role names, the request is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD §2.6: "When more than one rule would reject a request, the rules are
        evaluated in strictly ascending precedence order and the **first**
        violation decides the response."

        Design: Corner/Table 7 RBAC/missing_x_role_header_returns_unauthenticated
        """
        set_clock(api, CANONICAL_CLOCK)

        response = api.get_program(UNKNOWN_PROGRAM_ID, headers_without_role())
        validate_error(response, ApiErrorId.UNAUTHENTICATED)
        assert response.json()["data"]["error_id"] != ApiErrorId.PROGRAM_NOT_FOUND

    def test_taxpayer_role_may_not_design_a_program(self, api):
        """The role table decides before the payload is ever validated.

        PRD §2.1: "When the headers are well formed but the declared role is not
        authorized for the operation being attempted, the rejection is
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/Table 7 RBAC/taxpayer_role_cannot_create_a_program
        """
        set_clock(api, CANONICAL_CLOCK)
        taxpayer = register_taxpayer(
            api, legal_name="Ashgrove Hardware LLC", tin_last4="1010"
        )

        validate_error(
            api.create_program(
                program_payload(name="Rogue Program"),
                make_taxpayer_headers(taxpayer["id"]),
            ),
            ApiErrorId.FORBIDDEN_ROLE,
        )
        assert_list_total(api.list_programs(ADMIN_HEADERS), 0)

    def test_entity_backed_identity_that_resolves_to_no_row_is_forbidden(self, api):
        """An unknown `X-User-ID` under an allowed role is an identity failure.

        PRD §2.1: "For these two entity-backed roles, an `X-User-ID` that does
        not resolve to an existing row of the backing entity is rejected with
        `ERR_IDENTITY_NOT_RECOGNIZED` (HTTP 403)."

        Design: Corner/Table 7 RBAC/entity_backed_role_with_an_unknown_identity_returns_forbidden
        """
        set_clock(api, CANONICAL_CLOCK)
        register_taxpayer(api, legal_name="Ashgrove Hardware LLC", tin_last4="1010")

        validate_error(
            api.list_agreements(make_headers(UNKNOWN_TAXPAYER_ID, ROLE_TAXPAYER)),
            ApiErrorId.IDENTITY_NOT_RECOGNIZED,
        )

    def test_one_taxpayer_may_not_address_another_taxpayers_agreement(self, api):
        """Ownership separates two callers who hold the identical role.

        PRD §2.1: "Ownership is enforced narrowly. A `Taxpayer` may only address
        agreements, returns, payment plans and payments whose `taxpayer_id` is
        its own `X-User-ID`."

        PRD §2.1: "Violations produce `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/Table 7 RBAC/taxpayer_cannot_read_another_taxpayers_agreement
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Cedar Point Supply Inc",
                "tin_last4": "3311",
            },
        )
        peer = add_taxpayer(
            api, ctx, legal_name="Rill Hollow Trading LLC", tin_last4="7722"
        )
        agreement_id = ctx["agreement"]["id"]

        validate_error(
            api.get_agreement(agreement_id, make_taxpayer_headers(peer["id"])),
            ApiErrorId.NOT_RESOURCE_OWNER,
        )

        owned = validate_success(
            api.get_agreement(agreement_id, ctx["taxpayer_headers"])
        )
        assert_fields(owned, taxpayer_id=ctx["taxpayer"]["id"])

    def test_the_drafting_officer_may_not_sign_the_draft(self, api):
        """Segregation of duties compares user ids, not roles.

        PRD §2.1: "The officer whose `X-User-ID` equals an agreement's
        `drafted_by_user_id` may not execute that agreement, and the auditor
        whose `X-User-ID` equals an enforcement action's `created_by_user_id`
        may not issue that action. Either violation is
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        PRD §3.4: "Executing sets `status` to `EXECUTED`, records
        `executed_by_user_id` and stamps `executed_at` with the current instant"

        Design: Corner/Table 7 RBAC/segregation_of_duties_rejects_the_drafting_officer_as_signer
        """
        ctx = setup_drafted_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Wren Meadow Farms LLC",
                "tin_last4": "8844",
            },
        )
        agreement_id = ctx["agreement"]["id"]

        validate_error(
            api.execute_agreement(agreement_id, OFFICER_ALPHA_HEADERS),
            ApiErrorId.SEGREGATION_OF_DUTIES,
        )
        still_drafted = read_agreement(api, agreement_id)
        assert_fields(
            still_drafted, status="DRAFTED", executed_by_user_id=None, version=1
        )

        executed = validate_success(
            api.execute_agreement(agreement_id, OFFICER_BETA_HEADERS)
        )
        assert_fields(
            executed,
            status="EXECUTED",
            drafted_by_user_id=OFFICER_ALPHA_USER_ID,
            executed_by_user_id=OFFICER_BETA_USER_ID,
            executed_at=CANONICAL_CLOCK_RENDERED,
        )
        assert_fields(read_program(api, ctx["program"]["id"]), participant_count=1)


def test_owner_sees_exactly_its_own_agreement_in_the_collection(api):
    """The owning taxpayer's own agreement is visible to it.

    PRD §2.1: "A `Taxpayer` may only address agreements, returns, payment plans
    and payments whose `taxpayer_id` is its own `X-User-ID`."

    Design: Corner/Table 7 RBAC/taxpayer_cannot_read_another_taxpayers_agreement
    """
    ctx = setup_program_with_taxpayer(
        api,
        taxpayer_overrides={
            "legal_name": "Cedar Point Supply Inc",
            "tin_last4": "3311",
        },
    )
    draft_agreement(api, ctx)

    rows = assert_list_total(
        api.list_agreements(
            ADMIN_HEADERS, {"taxpayer_id": ctx["taxpayer"]["id"]}
        ),
        1,
    )
    assert rows[0]["taxpayer_id"] == ctx["taxpayer"]["id"]
