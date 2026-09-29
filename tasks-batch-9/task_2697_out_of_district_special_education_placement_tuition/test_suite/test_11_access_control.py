"""
Access control: the role gate, the two segregation-of-duties pairs, the scope
narrowing on the entity-backed roles and the top five rungs of the refusal ladder.

Every refusal here is asserted by its declared error identifier and its declared
HTTP status, and each test also proves that the refused call moved nothing.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_OUT_OF_SCOPE,
    ERR_PLACEMENT_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STUDENT_NOT_FOUND,
    ERR_UNAUTHENTICATED,
)
from test_helpers.fixtures import (
    build_reference_data,
    build_simple_billing_cycle,
    create_invoice,
    file_claim,
    list_rows,
    make_proposed_placement,
    make_school,
    make_student,
    read_account,
    read_decision,
    read_placement,
    read_school,
    read_student,
)
from test_helpers.test_users import (
    COORDINATOR_HEADERS,
    FISCAL_OFFICER_2_HEADERS,
    FISCAL_OFFICER_HEADERS,
    HEARING_ADJUDICATOR_HEADERS,
    NO_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    TEAM_CHAIR_2_HEADERS,
    TEAM_CHAIR_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    USER_FISCAL_OFFICER,
    USER_FISCAL_OFFICER_2,
    USER_TEAM_CHAIR,
    USER_TEAM_CHAIR_2,
    make_parent_guardian_headers,
    make_school_billing_agent_headers,
)

ACTIVATION_INSTANT = "2026-09-01T08:00:00Z"
FILING_INSTANT = "2026-11-02T09:00:00Z"
MISSING_UUID = "00000000-0000-0000-0000-0000000000f1"
MISSING_STUDENT_UUID = "00000000-0000-0000-0000-0000000000f2"
MISSING_PLACEMENT_UUID = "00000000-0000-0000-0000-0000000000ff"
SETTLED_CENTS = 654400
DISPUTE_REASON = "Day count disagrees with the district calendar."
AMENDED_DAYS = 19


class TestEveryRoleReachesItsOwnOperations:
    """The positive half of the role gate: one workflow touched by seven roles."""

    def test_each_role_performs_the_operations_it_owns(self, api):
        """
        A continuous workflow in which every role acts only where it has authority
        and every call succeeds.

        PRD: "A `PlacementCoordinator` is the district placement-office case manager and owns the operational lifecycle: registering students, drafting decisions, proposing placements, proposing service addenda, requesting and releasing transportation, verifying attendance, accepting progress reports and drafting transition plans."

        Design: Corner/rbac/each_role_exercises_its_own_exclusive_and_shared_operations
        """
        ref = build_reference_data(api)
        decision = validate_success(
            api.create_placement_decision(
                f.placement_decision_payload(ref["student"]["id"]), COORDINATOR_HEADERS
            ),
            201,
        )
        validate_success(
            api.submit_placement_decision(decision["id"], COORDINATOR_HEADERS)
        )

        approved = validate_success(
            api.approve_placement_decision(
                decision["id"], TEAM_CHAIR_HEADERS, f.reviewer_notes_payload(
                    "Team concurs."
                )
            )
        )
        assert approved["status"] == "APPROVED"

        placement = validate_success(
            api.create_placement(
                f.placement_payload(
                    ref["student"]["id"],
                    ref["school"]["id"],
                    decision["id"],
                    ref["schedule"]["id"],
                    ref["account"]["id"],
                ),
                COORDINATOR_HEADERS,
            ),
            201,
        )
        assert placement["status"] == "PROPOSED"

        contracted = validate_success(
            api.execute_contract(placement["id"], FISCAL_OFFICER_HEADERS)
        )
        assert contracted["status"] == "CONTRACTED"

        validate_success(api.set_clock(ACTIVATION_INSTANT, SYSTEM_ADMIN_HEADERS))
        active = validate_success(
            api.activate_placement(placement["id"], COORDINATOR_HEADERS)
        )
        assert active["status"] == "ACTIVE"

        validate_success(api.set_clock(FILING_INSTANT, SYSTEM_ADMIN_HEADERS))
        record = validate_success(
            api.create_attendance_record(
                f.attendance_record_payload(placement["id"]), ref["school_headers"]
            ),
            201,
        )
        disputed = validate_success(
            api.verify_attendance_record(
                record["id"],
                f.verify_attendance_payload("DISPUTE", dispute_reason=DISPUTE_REASON),
                COORDINATOR_HEADERS,
            )
        )
        assert disputed["status"] == "DISPUTED"

        amended = validate_success(
            api.amend_attendance_record(
                record["id"],
                f.amend_attendance_payload(
                    days_enrolled=AMENDED_DAYS,
                    days_attended=AMENDED_DAYS,
                    days_absent_unexcused=0,
                ),
                ref["school_headers"],
            )
        )
        assert amended["status"] == "SUBMITTED"
        assert amended["amendment_round"] == 1
        assert amended["days_enrolled"] == AMENDED_DAYS

        consented = validate_success(
            api.patch_medicaid_consent(
                ref["student"]["id"],
                f.medicaid_consent_payload(),
                ref["parent_headers"],
            )
        )
        assert consented["medicaid_eligible"] is True
        assert consented["medicaid_consent_on_file"] is True

        school = validate_success(
            api.patch_school_approval_status(
                ref["school"]["id"],
                f.approval_status_payload("PROVISIONAL"),
                SYSTEM_ADMIN_HEADERS,
            )
        )
        assert school["approval_status"] == "PROVISIONAL"

        read = validate_success(
            api.get_placement(placement["id"], HEARING_ADJUDICATOR_HEADERS)
        )
        assert read["id"] == placement["id"]


class TestNoRoleCrossesAnotherRolesBoundary:
    """The negative half: six crossings, each refused at the role rung."""

    def test_six_forbidden_operations_are_all_refused_and_change_nothing(self, api):
        """
        Each caller holds a real role that simply does not authorise the target
        operation, including the platform operator aiming at a placement.

        PRD: "When the headers are well formed but the declared role is not among those authorised for the target operation, the rejection is `ERR_ROLE_NOT_PERMITTED` (403)."

        Design: Corner/rbac/no_role_cannot_reach_another_roles_exclusive_operation
        """
        ref = build_reference_data(api)
        placement = make_proposed_placement(api, ref)
        decision_id = placement["_decision_id"]
        parent_headers = ref["parent_headers"]

        validate_error(
            api.execute_contract(placement["id"], ref["school_headers"]),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.create_placement(
                f.placement_payload(
                    ref["student"]["id"],
                    ref["school"]["id"],
                    decision_id,
                    ref["schedule"]["id"],
                    ref["account"]["id"],
                    start_date="2027-01-04",
                    contracted_instructional_days=100,
                ),
                HEARING_ADJUDICATOR_HEADERS,
            ),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.execute_contract(placement["id"], SYSTEM_ADMIN_HEADERS),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.return_decision_for_revision(
                decision_id, f.reviewer_notes_payload("Reopen."), COORDINATOR_HEADERS
            ),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.execute_contract(MISSING_PLACEMENT_UUID, parent_headers),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.patch_school_approval_status(
                ref["school"]["id"],
                f.approval_status_payload("REVOKED"),
                FISCAL_OFFICER_HEADERS,
            ),
            ERR_ROLE_NOT_PERMITTED,
        )

        unchanged = read_placement(api, placement["id"])
        assert unchanged["status"] == "PROPOSED"
        assert unchanged["version"] == 1
        assert read_decision(api, decision_id)["status"] == "APPROVED"
        assert read_school(api, ref["school"]["id"])["approval_status"] == "APPROVED"


class TestSegregationOfDuties:
    """Both frozen-identity comparisons, each satisfied by a second human."""

    def test_the_invoice_verifier_cannot_approve_its_own_payment(self, api):
        """
        A fiscal officer who priced the invoice is barred from paying it, while a
        second officer holding the identical role settles it.

        PRD: "Approving a placement decision requires an acting user different from the decision's `authored_by_user_id`; approving payment on a tuition invoice requires an acting user different from that invoice's `verified_by_user_id`."

        Design: Corner/rbac/the_user_who_verified_an_invoice_may_not_approve_its_payment
        """
        world = build_simple_billing_cycle(api)
        invoice = create_invoice(
            api,
            world,
            world["placement"]["id"],
            world["record"]["id"],
            SETTLED_CENTS,
        )
        verified = validate_success(
            api.verify_tuition_invoice(
                invoice["id"], f.verify_invoice_payload("ENROLLMENT"),
                FISCAL_OFFICER_HEADERS,
            )
        )
        assert verified["verification_status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == USER_FISCAL_OFFICER

        validate_error(
            api.approve_invoice_payment(invoice["id"], FISCAL_OFFICER_HEADERS),
            ERR_SEGREGATION_OF_DUTIES,
        )

        paid = validate_success(
            api.approve_invoice_payment(invoice["id"], FISCAL_OFFICER_2_HEADERS)
        )
        assert paid["payment_status"] == "PAID"
        assert paid["settled_amount_cents"] == SETTLED_CENTS
        assert paid["verified_by_user_id"] == USER_FISCAL_OFFICER
        assert paid["approved_by_user_id"] == USER_FISCAL_OFFICER_2

        account = read_account(api, world["account"]["id"])
        assert account["disbursed_cents"] == SETTLED_CENTS

    def test_the_decision_author_cannot_approve_its_own_decision(self, api):
        """
        A team chair who authored the decision is barred from approving it, and the
        refused attempt leaves the record in review.

        PRD: "It likewise requires an acting user whose identifier differs from `authored_by_user_id` — a violation here is the first of the two segregation-of-duties comparisons and yields `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/the_user_who_authored_a_decision_may_not_approve_it
        """
        ref = build_reference_data(api)
        decision = validate_success(
            api.create_placement_decision(
                f.placement_decision_payload(ref["student"]["id"]), TEAM_CHAIR_HEADERS
            ),
            201,
        )
        submitted = validate_success(
            api.submit_placement_decision(decision["id"], TEAM_CHAIR_HEADERS)
        )
        assert submitted["status"] == "TEAM_REVIEW"
        assert submitted["authored_by_user_id"] == USER_TEAM_CHAIR

        validate_error(
            api.approve_placement_decision(
                decision["id"],
                TEAM_CHAIR_HEADERS,
                f.reviewer_notes_payload("Self approval attempt."),
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )
        blocked = read_decision(api, decision["id"])
        assert blocked["status"] == "TEAM_REVIEW"
        assert blocked["version"] == submitted["version"]

        approved = validate_success(
            api.approve_placement_decision(
                decision["id"],
                TEAM_CHAIR_2_HEADERS,
                f.reviewer_notes_payload("Independent review complete."),
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["reviewed_by_user_id"] == USER_TEAM_CHAIR_2
        assert approved["authored_by_user_id"] == USER_TEAM_CHAIR


class TestEntityBackedScope:
    """An entity-backed actor sees its own rows and nothing else."""

    def test_a_guardian_and_an_agent_are_confined_to_their_own_rows(self, api):
        """
        The owning guardian reads its claim; every crossing of the ownership line —
        a read, two writes and a school-side read — is refused as out of scope.

        PRD: "When `X-User-Role` is `ParentGuardian`, `X-User-ID` is the `id` of the acting `Student`; ownership checks on any resource that resolves to a student compare that resource's student reference to `X-User-ID`, and a cross-student read or write is likewise refused with `ERR_OUT_OF_SCOPE`."

        Design: Corner/rbac/an_entity_backed_actor_cannot_reach_rows_outside_its_own_scope
        """
        ref = build_reference_data(api)
        other_student = make_student(api, full_name="Yaroslav Tinubu")
        other_school = make_school(
            api,
            name="Ridgeline Preparatory",
            state_approval_id="SA-9902",
            residential_capable=False,
        )
        other_parent = make_parent_guardian_headers(other_student["id"])
        other_agent = make_school_billing_agent_headers(other_school["id"])
        claim = file_claim(api, ref)

        owned = validate_success(
            api.get_reimbursement_claim(claim["id"], ref["parent_headers"])
        )
        assert owned["status"] == "FILED"

        validate_error(
            api.get_reimbursement_claim(claim["id"], other_parent), ERR_OUT_OF_SCOPE
        )
        validate_error(
            api.create_reimbursement_claim(
                f.reimbursement_claim_payload(
                    ref["student"]["id"],
                    ref["account"]["id"],
                    claimed_tuition_cents=500000,
                    claimed_transport_cents=0,
                    claimed_instructional_days=40,
                ),
                other_parent,
            ),
            ERR_OUT_OF_SCOPE,
        )
        validate_error(
            api.patch_medicaid_consent(
                ref["student"]["id"], f.medicaid_consent_payload(), other_parent
            ),
            ERR_OUT_OF_SCOPE,
        )
        validate_error(
            api.get_rate_schedule(ref["schedule"]["id"], other_agent),
            ERR_OUT_OF_SCOPE,
        )

        rows, meta = list_rows(
            api.list_reimbursement_claims(
                other_parent, {"student_id": other_student["id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert read_student(api, ref["student"]["id"])[
            "medicaid_consent_on_file"
        ] is False


class TestRefusalLadderTopRungs:
    """The first five rungs, each demanded by a request that breaks several."""

    def test_authentication_role_path_shape_and_body_reference_in_order(self, api):
        """
        Five requests, each dropping exactly one defect from the one before, so the
        answer walks the ladder down one rung at a time.

        PRD: "The refusal ladder is **total**: the system evaluates rules in the order below and always returns the error belonging to the earliest rung that is violated, never a later one."

        Design: Corner/validations/priority_ladder_returns_401_unauthenticated_then_403_then_404_before_any_400
        """
        ref = build_reference_data(api)
        placement = make_proposed_placement(api, ref)

        validate_error(
            api.execute_contract(MISSING_UUID, NO_HEADERS, {"unexpected_field": 7}),
            ERR_UNAUTHENTICATED,
        )
        validate_error(
            api.execute_contract(MISSING_UUID, ref["school_headers"]),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.execute_contract(MISSING_UUID, FISCAL_OFFICER_HEADERS),
            ERR_PLACEMENT_NOT_FOUND,
        )

        malformed = f.placement_payload(
            MISSING_STUDENT_UUID,
            ref["school"]["id"],
            placement["_decision_id"],
            ref["schedule"]["id"],
            ref["account"]["id"],
        )
        malformed.pop("placement_type")
        validate_error(
            api.create_placement(malformed, COORDINATOR_HEADERS), ERR_INVALID_REQUEST
        )

        validate_error(
            api.create_reimbursement_claim(
                f.reimbursement_claim_payload(
                    MISSING_STUDENT_UUID,
                    ref["account"]["id"],
                    claimed_tuition_cents=500000,
                    claimed_transport_cents=0,
                    claimed_instructional_days=40,
                ),
                ref["parent_headers"],
            ),
            ERR_STUDENT_NOT_FOUND,
        )

        unchanged = read_placement(api, placement["id"])
        assert unchanged["status"] == "PROPOSED"
        assert unchanged["version"] == 1
        _rows, meta = list_rows(
            api.list_reimbursement_claims(
                ref["parent_headers"], {"student_id": ref["student"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_an_unusable_role_header_beats_a_malformed_student_body(self, api):
        """
        An unauthenticated create is refused on authentication alone, so no shape
        information about the body ever leaks back.

        PRD: "If either header is absent or empty, or if `X-User-Role` is not exactly one of the seven role names below, the request is rejected with `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/validations/unauthenticated_student_create_rejected_before_any_other_check
        """
        payload = f.student_payload(
            full_name="Tova Halvorsen", disability_category="NOT_A_CATEGORY"
        )
        payload.pop("district_of_residence")

        validate_error(
            api.create_student(payload, UNKNOWN_ROLE_HEADERS), ERR_UNAUTHENTICATED
        )

        _rows, meta = list_rows(api.list_students(SYSTEM_ADMIN_HEADERS))
        assert meta["total_count"] == 0
