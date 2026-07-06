"""Program catalog CRUD and the ProgramVersion authoring lifecycle."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, assert_program, assert_program_version,
    create_program, create_draft_version, create_approved_version,
    TEST_USERS,
)

DESIGNER = TEST_USERS["program_designer_headers"]


def test_create_program_defaults(api):
    """PRD §3.1: "A new program begins in `DRAFT` status with its `active_version_id` set to
    null." PRD §3.1: "`ceu_credits`, the Continuing Education Units awarded on a passing
    outcome, which defaults to 0" PRD §3.1: "`is_custom`, a boolean that defaults to false".

    Design: Corner/entities/create_program_returns_201_with_defaults
    """
    data = validate_success(
        api.create_program(
            {"title": "Intro", "category": "LEADERSHIP", "delivery_mode": "VIRTUAL"},
            DESIGNER,
        ),
        expected_status=201,
    )
    assert_program(data)
    assert data["status"] == "DRAFT"
    assert data["ceu_credits"] == 0
    assert data["is_custom"] is False
    assert data["active_version_id"] is None


def test_get_program_returns_stored_entity(api):
    """PRD §3.1: "A `ProgramDesigner` opens the catalog by creating a `Program`, supplying a
    `title`, a `category` that is one of `LEADERSHIP`, `TECHNICAL`, `COMPLIANCE`, or `SALES`".

    Design: Corner/entities/get_program_returns_stored_entity
    """
    created = create_program(category="TECHNICAL", delivery_mode="HYBRID", title="Stored Prog")
    data = validate_success(api.get_program(created["id"], DESIGNER))
    assert data["title"] == "Stored Prog"
    assert data["category"] == "TECHNICAL"


def test_list_programs_paginated_envelope(api):
    """PRD §2.3: "Every list response includes the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_programs_paginated_envelope
    """
    create_program(category="SALES", title="P1")
    create_program(category="SALES", title="P2")
    data, meta = validate_paginated(api.list_programs(DESIGNER, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_get_program_not_found(api):
    """PRD §2.9: "the existence of every resource referenced by the path or body is verified
    left-to-right; the first identifier that does not resolve to an existing resource produces
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_program_not_found_returns_404
    """
    resp = api.get_program("00000000-0000-4000-8000-000000000000", DESIGNER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_program_version_missing_pricing_model(api):
    """PRD §2.9: "A malformed body, a missing required field, or a value of the wrong type or
    outside an enum is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_program_version_missing_required_field
    """
    prog = create_program()
    resp = api.create_program_version(
        {"program_id": prog["id"], "version_label": "v1", "duration_hours": 4},
        DESIGNER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_cohort_create_invalid_reference_program_not_version(api):
    """PRD §2.9: "on create endpoints that carry foreign-key body fields, each foreign key must
    reference a resource of the correct type — for example, a `program_version_id` must resolve
    to a `ProgramVersion` — and a wrong-type or wrong-lifecycle reference yields
    `ERR_INVALID_REFERENCE` (HTTP 422)."

    Design: Corner/entities/cohort_create_invalid_reference_program_not_version
    """
    from test_helpers import create_facilitator, TEST_USERS as TU
    prog = create_program()
    fac = create_facilitator(certified_categories=["TECHNICAL"], email="facref@example.com")
    resp = api.create_cohort(
        {
            "program_version_id": prog["id"],
            "lead_facilitator_id": fac["id"],
            "seat_capacity": 3,
            "delivery_mode": "VIRTUAL",
            "starts_at": "2026-07-03T09:00:00Z",
            "ends_at": "2026-07-03T11:00:00Z",
            "enroll_deadline": "2026-07-02T00:00:00Z",
        },
        TU["scheduling_coordinator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE.value)


# ---------------------------------------------------------------------------
# ProgramVersion authoring loop (cyclic state machine)
# ---------------------------------------------------------------------------
class TestVersionLifecycle:
    def test_design_revision_cycle(self, api):
        """PRD §3.1: "A designer submits a draft version for review, moving it from `DRAFT` to
        `IN_REVIEW`." PRD §3.1: "From `IN_REVIEW`, the designer may request changes, sending the
        version back from `IN_REVIEW` to `DRAFT` for another revision pass". PRD §3.1: "Approving
        a version transitions it from `IN_REVIEW` to `APPROVED`."

        Design: Difficulty/non_linear_state_machine/program_version_design_revision_cycle
        """
        prog = create_program(category="LEADERSHIP")
        ver = create_draft_version(prog["id"], pricing_model="PER_SEAT", per_seat_cents=30000,
                                   duration_hours=6)
        st1 = validate_success(api.submit_program_version(ver["id"], DESIGNER))
        assert st1["status"] == "IN_REVIEW"
        st2 = validate_success(api.request_changes_program_version(ver["id"], DESIGNER))
        assert st2["status"] == "DRAFT", "request-changes loops back to DRAFT"
        st3 = validate_success(api.submit_program_version(ver["id"], DESIGNER))
        assert st3["status"] == "IN_REVIEW"
        st4 = validate_success(api.approve_program_version(ver["id"], DESIGNER))
        assert st4["status"] == "APPROVED"

    def test_design_cycle_intermediate_states(self, api):
        """PRD §3.1: "this is the loop that lets a version be refined repeatedly before
        approval." PRD §3.1: "From `IN_REVIEW`, the designer may request changes, sending the
        version back from `IN_REVIEW` to `DRAFT` for another revision pass".

        Design: Difficulty/non_linear_state_machine/program_version_design_revision_cycle
        """
        prog = create_program(category="LEADERSHIP")
        ver = create_draft_version(prog["id"], per_seat_cents=30000)
        assert ver["status"] == "DRAFT"
        submitted = validate_success(api.submit_program_version(ver["id"], DESIGNER))
        assert submitted["status"] == "IN_REVIEW"
        back = validate_success(api.request_changes_program_version(ver["id"], DESIGNER))
        assert back["status"] == "DRAFT"

    def test_approve_supersedes_prior_version(self, api):
        """PRD §3.1: "if another version of the same program was already `APPROVED`, that prior
        version is automatically moved to `SUPERSEDED`". PRD §3.1: "the program's
        `active_version_id` is set to point at the newly approved version's id, and if the
        program was still in `DRAFT` its `status` advances to `PUBLISHED`."

        Design: Corner/state_machines/approve_supersedes_prior_version_crossentity
        """
        prog = create_program()
        v1 = create_draft_version(prog["id"], per_seat_cents=10000)
        api.submit_program_version(v1["id"], DESIGNER)
        api.approve_program_version(v1["id"], DESIGNER)
        v2 = create_draft_version(prog["id"], per_seat_cents=12000, version_label="v2",
                                  duration_hours=3)
        api.submit_program_version(v2["id"], DESIGNER)
        api.approve_program_version(v2["id"], DESIGNER)
        v1_after = validate_success(api.get_program_version(v1["id"], DESIGNER))
        assert v1_after["status"] == "SUPERSEDED"
        prog_after = validate_success(api.get_program(prog["id"], DESIGNER))
        assert prog_after["active_version_id"] == v2["id"]
        assert prog_after["status"] == "PUBLISHED"

    def test_double_submit_rejected(self, api):
        """PRD §2.9: "for any state-transition endpoint, the target resource must currently be in
        a state from which the requested transition is defined; otherwise the request is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/program_version_double_submit_idempotency_rejected
        """
        prog = create_program()
        ver = create_draft_version(prog["id"], per_seat_cents=10000)
        api.submit_program_version(ver["id"], DESIGNER)
        resp = api.submit_program_version(ver["id"], DESIGNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_pricing_incomplete_on_submit(self, api):
        """PRD §3.1: "under `PER_SEAT`, `per_seat_cents` must be greater than 0, and under
        `FLAT`, `flat_fee_cents` must be greater than 0. An incomplete pricing configuration is
        rejected with `ERR_PRICING_INCOMPLETE` (HTTP 422)."

        Design: Corner/validations/pricing_incomplete_on_submit_per_seat_missing_price
        """
        prog = create_program()
        ver = validate_success(
            api.create_program_version(
                {"program_id": prog["id"], "version_label": "v1", "duration_hours": 2,
                 "pricing_model": "PER_SEAT", "min_seats": 1},
                DESIGNER,
            ),
            expected_status=201,
        )
        resp = api.submit_program_version(ver["id"], DESIGNER)
        validate_error(resp, ApiErrorId.ERR_PRICING_INCOMPLETE.value)

    def test_approve_retired_program_rejected(self, api):
        """PRD §3.1: "Approval is blocked when the owning program is `RETIRED`, in which case the
        request is rejected with `ERR_PROGRAM_RETIRED`."

        Design: Corner/errors/approve_retired_program_version_rejected
        """
        prog = create_program()
        ver = create_draft_version(prog["id"], per_seat_cents=10000)
        api.submit_program_version(ver["id"], DESIGNER)
        api.retire_program(prog["id"], DESIGNER)
        resp = api.approve_program_version(ver["id"], DESIGNER)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_RETIRED.value)
