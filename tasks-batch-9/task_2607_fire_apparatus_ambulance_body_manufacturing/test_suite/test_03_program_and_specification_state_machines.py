"""Program posture and specification review-cycle state machines.

Covers the operator-driven program hops, the single-shot nature of each of them,
the terminal lockdown of a closed program, the DRAFT-only write window on a
specification, and the once-only disposition of a compliance response.
"""

from test_helpers import (
    ComplianceDisposition,
    ComplianceResponse,
    ErrorCode,
    ProgramStatus,
    SpecificationStatus,
    SuspensionReason,
    add_clause,
    assert_spec_scores,
    create_draft_specification,
    create_program,
    file_compliance_entry,
    make_body_engineer_headers,
    make_purchasing_officer_headers,
    read_program,
    validate_error,
    validate_success,
)


def test_activate_suspend_and_reactivate_each_bump_the_program_version(api,
                                                                      admin_headers):
    """Three operator hops walk DRAFT to ACTIVE to SUSPENDED and back.

    PRD 3.1: "Activating a program takes `status` from `DRAFT` to `ACTIVE`,
    clears `suspension_reason` to null and increments the program's `version`".
    PRD 3.1: "Suspending an `ACTIVE` program takes it to `SUSPENDED` with
    `suspension_reason` set to `MANUAL`."
    PRD 3.1: "Each of these four transitions increments the program's `version`
    by one."

    Design: Corner/state_machines/program_lifecycle_manual_suspension_and_reactivation
    """
    program = create_program(api, name="Lifecycle program")
    created_at = program["created_at"]

    activated = validate_success(api.activate_program(program["id"], admin_headers))
    assert activated["status"] == ProgramStatus.ACTIVE.value, activated
    assert activated["suspension_reason"] is None, activated
    assert activated["version"] == 2, activated

    suspended = validate_success(api.suspend_program(program["id"], admin_headers))
    assert suspended["status"] == ProgramStatus.SUSPENDED.value, suspended
    assert suspended["suspension_reason"] == SuspensionReason.MANUAL.value, suspended
    assert suspended["version"] == 3, suspended

    reactivated = validate_success(api.reactivate_program(program["id"], admin_headers))
    assert reactivated["status"] == ProgramStatus.ACTIVE.value, reactivated
    assert reactivated["suspension_reason"] is None, reactivated
    assert reactivated["version"] == 4, reactivated

    for row in (activated, suspended, reactivated):
        assert row["committed_cents"] == 0, row
        assert row["created_at"] == created_at, row


def test_a_program_starts_in_draft_and_activate_is_single_shot(api, admin_headers):
    """The second activate and a reactivate from ACTIVE are both state failures.

    PRD 3.1: "only a `DRAFT` program may be activated, and only while a program
    is `ACTIVE` may unit orders be awarded against it or production started on
    its units."
    PRD 2.9: "The program is in the state the requested operation allows —
    `DRAFT` to activate, `ACTIVE` to suspend, `SUSPENDED` to reactivate, `ACTIVE`
    to close".

    Design: Corner/state_machines/program_initial_state_and_duplicate_activate_rejected
    """
    program = create_program(api, name="Idempotency program")

    initial = validate_success(api.get_program(program["id"], admin_headers))
    assert initial["status"] == ProgramStatus.DRAFT.value, initial
    assert initial["version"] == 1, initial

    activated = validate_success(api.activate_program(program["id"], admin_headers))
    assert activated["status"] == ProgramStatus.ACTIVE.value, activated
    assert activated["version"] == 2, activated

    validate_error(
        api.activate_program(program["id"], admin_headers),
        ErrorCode.ERR_INVALID_PROGRAM_STATE,
        409,
    )
    assert read_program(api, program["id"])["version"] == 2

    validate_error(
        api.reactivate_program(program["id"], admin_headers),
        ErrorCode.ERR_INVALID_PROGRAM_STATE,
        409,
    )
    still = read_program(api, program["id"])
    assert still["status"] == ProgramStatus.ACTIVE.value, still
    assert still["version"] == 2, still


def test_a_closed_program_refuses_every_further_transition(api, admin_headers):
    """Close is terminal, and even the sweep is refused afterwards.

    PRD 3.1: "Closing an `ACTIVE` program takes it to the terminal `CLOSED`
    state".
    PRD 3.1: "it may be run against a program that is either `ACTIVE` or
    `SUSPENDED` — any other program posture is refused with
    `ERR_INVALID_PROGRAM_STATE`."

    Design: Corner/state_machines/closed_program_rejects_every_further_transition
    """
    program = create_program(api, name="Closure program")
    validate_success(api.activate_program(program["id"], admin_headers))

    closed = validate_success(api.close_program(program["id"], admin_headers))
    assert closed["status"] == ProgramStatus.CLOSED.value, closed
    assert closed["version"] == 3, closed

    for call in (
        api.activate_program,
        api.suspend_program,
        api.reactivate_program,
        api.close_program,
        api.ops_run,
    ):
        validate_error(
            call(program["id"], admin_headers),
            ErrorCode.ERR_INVALID_PROGRAM_STATE,
            409,
        )

    frozen = read_program(api, program["id"])
    assert frozen["status"] == ProgramStatus.CLOSED.value, frozen
    assert frozen["version"] == 3, frozen


def test_clause_and_compliance_writes_are_open_only_while_the_spec_is_draft(api,
                                                                           admin_headers):
    """Review entry needs a clause, and freezes both write channels until rework.

    PRD 3.2: "Clauses are appended one at a time, and only while the
    specification is `DRAFT`; an attempt against a specification in any other
    status is refused with `ERR_INVALID_SPEC_STATE`."
    PRD 3.2: "requires the specification to hold at least one clause (an empty
    specification is refused with `ERR_SPEC_HAS_NO_CLAUSES`)".
    PRD 3.2: "Sending the document back for rework takes `UNDER_REVIEW` to
    `DRAFT`, increments `revision_number` by one and increments `version`."

    Design: Corner/state_machines/specification_review_cycle_and_clause_write_window
    """
    author = make_purchasing_officer_headers("po-author")
    program = create_program(api, name="Review cycle program")
    spec = create_draft_specification(api, program["id"], title="Review cycle spec")

    validate_error(
        api.submit_specification_for_review(spec["id"], author),
        ErrorCode.ERR_SPEC_HAS_NO_CLAUSES,
        422,
    )
    empty = validate_success(api.get_specification(spec["id"], admin_headers))
    assert empty["status"] == SpecificationStatus.DRAFT.value, empty
    assert empty["version"] == 1, empty

    first_clause = add_clause(api, spec["id"], clause_code="C1", category="PUMP",
                              requirement_text="1500 gpm single stage pump",
                              mandatory=True, is_restrictive=False)
    with_clause = validate_success(api.get_specification(spec["id"], admin_headers))
    assert_spec_scores(with_clause, restrictive_ratio=0.00, clause_count=1,
                       mandatory_clause_count=1)
    assert with_clause["version"] == 2, with_clause

    under_review = validate_success(
        api.submit_specification_for_review(spec["id"], author)
    )
    assert under_review["status"] == SpecificationStatus.UNDER_REVIEW.value, under_review
    assert under_review["version"] == 3, under_review

    validate_error(
        api.add_clause(
            spec["id"],
            {"clause_code": "C2", "category": "ELECTRICAL",
             "requirement_text": "Load manager required", "mandatory": True,
             "is_restrictive": False},
            author,
        ),
        ErrorCode.ERR_INVALID_SPEC_STATE,
        409,
    )
    assert validate_success(
        api.get_specification(spec["id"], admin_headers)
    )["clause_count"] == 1

    validate_error(
        api.create_compliance_entry(
            {"specification_id": spec["id"], "clause_id": first_clause["id"],
             "response": ComplianceResponse.COMPLY.value},
            make_body_engineer_headers(),
        ),
        ErrorCode.ERR_INVALID_SPEC_STATE,
        409,
    )

    reworked = validate_success(api.rework_specification(spec["id"], author))
    assert reworked["status"] == SpecificationStatus.DRAFT.value, reworked
    assert reworked["version"] == 4, reworked

    validate_error(
        api.rework_specification(spec["id"], author),
        ErrorCode.ERR_INVALID_SPEC_STATE,
        409,
    )

    second_clause = validate_success(
        api.add_clause(
            spec["id"],
            {"clause_code": "C2", "category": "ELECTRICAL",
             "requirement_text": "Load manager required", "mandatory": True,
             "is_restrictive": False},
            author,
        ),
        201,
    )
    assert second_clause["clause_code"] == "C2", second_clause
    final = validate_success(api.get_specification(spec["id"], admin_headers))
    assert final["clause_count"] == 2, final
    assert final["version"] == 5, final


def test_a_disposition_may_be_written_once_and_only_from_a_draft_spec(api,
                                                                     admin_headers):
    """Accepting one of two pending exceptions lifts the strict score alone.

    PRD 3.3: "The entry may only be disposed while its own `disposition` is
    `PENDING` *and* its parent specification is still `DRAFT`; otherwise the call
    is refused with `ERR_INVALID_ENTRY_STATE`."
    PRD 3.3: "Accepting an `EXCEPTION` or `ALTERNATE` response is the *only* way
    the strict score can count that clause as compliant".

    Design: Corner/state_machines/compliance_disposition_is_single_shot_and_rescores_both_variants
    """
    author = make_purchasing_officer_headers("po-author")
    program = create_program(api, name="Disposition program")
    spec = create_draft_specification(api, program["id"], title="Disposition spec")
    clause_one = add_clause(api, spec["id"], clause_code="C1", category="PUMP",
                            requirement_text="1500 gpm single stage pump",
                            mandatory=True, is_restrictive=False)
    clause_two = add_clause(api, spec["id"], clause_code="C2", category="AERIAL",
                            requirement_text="105 ft rear mount aerial",
                            mandatory=True, is_restrictive=False)
    entry_one = file_compliance_entry(
        api, spec["id"], clause_one["id"],
        response=ComplianceResponse.EXCEPTION.value,
        exception_text="Offering 1250 gpm two stage pump",
    )
    entry_two = file_compliance_entry(
        api, spec["id"], clause_two["id"],
        response=ComplianceResponse.EXCEPTION.value,
        exception_text="Offering 100 ft rear mount",
    )

    before = validate_success(api.get_specification(spec["id"], admin_headers))
    assert_spec_scores(before, strict=0.00, provisional=100.00)

    disposed = validate_success(
        api.dispose_compliance_entry(
            entry_one["id"],
            {"disposition": ComplianceDisposition.ACCEPTED.value,
             "disposition_note": "Equivalent capacity accepted"},
            author,
        )
    )
    assert disposed["disposition"] == ComplianceDisposition.ACCEPTED.value, disposed
    assert disposed["disposition_note"] == "Equivalent capacity accepted", disposed
    assert disposed["version"] == 2, disposed

    rescored = validate_success(api.get_specification(spec["id"], admin_headers))
    assert_spec_scores(rescored, strict=50.00, provisional=100.00)

    validate_error(
        api.dispose_compliance_entry(
            entry_one["id"],
            {"disposition": ComplianceDisposition.REJECTED.value},
            author,
        ),
        ErrorCode.ERR_INVALID_ENTRY_STATE,
        409,
    )
    unchanged = validate_success(
        api.get_compliance_entry(entry_one["id"], admin_headers)
    )
    assert unchanged["disposition"] == ComplianceDisposition.ACCEPTED.value, unchanged
    assert unchanged["version"] == 2, unchanged

    validate_success(api.submit_specification_for_review(spec["id"], author))
    validate_error(
        api.dispose_compliance_entry(
            entry_two["id"],
            {"disposition": ComplianceDisposition.ACCEPTED.value},
            author,
        ),
        ErrorCode.ERR_INVALID_ENTRY_STATE,
        409,
    )
    sibling = validate_success(
        api.get_compliance_entry(entry_two["id"], admin_headers)
    )
    assert sibling["disposition"] == ComplianceDisposition.PENDING.value, sibling
