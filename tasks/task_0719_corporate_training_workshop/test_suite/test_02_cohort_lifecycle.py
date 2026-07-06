"""Cohort scheduling, opening preconditions, and delivery lifecycle."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_cohort, assert_facilitator,
    create_program, create_draft_version, create_approved_version, create_facilitator,
    create_scheduled_cohort, setup_open_cohort, register_and_confirm, register_learner,
    lock_cohort, current_cohort_version, set_clock,
    make_facilitator_headers, TEST_USERS,
)
from test_helpers import api_client

DESIGNER = TEST_USERS["program_designer_headers"]
COORD = TEST_USERS["scheduling_coordinator_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


def test_cohort_initial_state(api):
    """PRD §3.3: "A new cohort begins in `SCHEDULED` state with all three seat counters at 0 and
    its `version` at 1."

    Design: Corner/state_machines/cohort_initial_state_is_scheduled
    """
    _, version = create_approved_version()
    fac = create_facilitator(certified_categories=["TECHNICAL"], email="facin@example.com")
    data = validate_success(
        api.create_cohort(
            {"program_version_id": version["id"], "lead_facilitator_id": fac["id"],
             "seat_capacity": 3, "delivery_mode": "VIRTUAL",
             "starts_at": "2026-07-04T09:00:00Z", "ends_at": "2026-07-04T11:00:00Z",
             "enroll_deadline": "2026-07-03T00:00:00Z"},
            COORD,
        ),
        expected_status=201,
    )
    assert_cohort(data)
    assert data["status"] == "SCHEDULED"
    assert data["seats_reserved"] == 0
    assert data["seats_confirmed"] == 0
    assert data["seats_waitlisted"] == 0
    assert data["version"] == 1


def test_facilitator_default_status_active(api):
    """PRD §3.2: "An optional `travel_base_cents` records the flat travel reimbursement in cents
    charged whenever this facilitator leads an onsite or hybrid cohort; it defaults to 0. A
    facilitator starts `ACTIVE` and can be moved to `SUSPENDED`."

    Design: Corner/entities/create_facilitator_default_status_active
    """
    data = validate_success(
        api.create_facilitator(
            {"full_name": "Def Fac", "email": "deffac@example.com",
             "certified_categories": ["TECHNICAL"]},
            COORD,
        ),
        expected_status=201,
    )
    assert_facilitator(data)
    assert data["status"] == "ACTIVE"
    assert data["travel_base_cents"] == 0


def test_open_requires_program_version_approved(api):
    """PRD §3.3: "The referenced program version must be `APPROVED`, or the open fails with
    `ERR_VERSION_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/cohort_open_requires_program_version_approved
    """
    prog = create_program()
    ver = create_draft_version(prog["id"], per_seat_cents=10000)
    api.submit_program_version(ver["id"], DESIGNER)  # left IN_REVIEW, never approved
    fac = create_facilitator(certified_categories=["TECHNICAL"], email="facd@example.com")
    cohort = create_scheduled_cohort(ver["id"], fac["id"], delivery_mode="VIRTUAL")
    resp = api.open_cohort(cohort["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_VERSION_NOT_APPROVED.value)


def test_open_unapproved_version_distinct_from_approved_path(api):
    """PRD §3.3: "Opening a cohort advances it from `SCHEDULED` to `OPEN` and is the gate that
    lets registrations begin." PRD §3.3: "The referenced program version must be `APPROVED`, or
    the open fails with `ERR_VERSION_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/cohort_open_requires_program_version_approved
    """
    prog = create_program(category="SALES", delivery_mode="VIRTUAL")
    ver = create_draft_version(prog["id"], per_seat_cents=10000)
    # not even submitted -> still DRAFT
    fac = create_facilitator(certified_categories=["SALES"], email="facd2@example.com")
    cohort = create_scheduled_cohort(ver["id"], fac["id"], delivery_mode="VIRTUAL")
    resp = api.open_cohort(cohort["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_VERSION_NOT_APPROVED.value)


def test_facilitator_not_certified_beats_budget_on_open(api):
    """PRD §3.3: "The lead facilitator must be `ACTIVE` and must list the program's category
    among their certified categories, or the open fails with `ERR_FACILITATOR_NOT_CERTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/facilitator_not_certified_beats_budget_on_open
    """
    _, ver = create_approved_version(category="TECHNICAL", delivery_mode="VIRTUAL")
    contract = validate_success(
        api.create_contract({"client_name": "Sponsor", "budget_cents": 1}, FINANCE),
        expected_status=201,
    )
    fac = create_facilitator(certified_categories=["TECHNICAL"], email="facz@example.com")
    cohort = create_scheduled_cohort(ver["id"], fac["id"], delivery_mode="VIRTUAL",
                                     contract_id=contract["id"])
    api.suspend_facilitator(fac["id"], COORD)
    resp = api.open_cohort(cohort["id"], COORD)
    # safety check (priority 7) precedes any fiscal check; the tiny budget is never reached.
    validate_error(resp, ApiErrorId.ERR_FACILITATOR_NOT_CERTIFIED.value)


def test_open_suspended_lead_rejected(api):
    """PRD §3.3: "The lead facilitator must be `ACTIVE` and must list the program's category
    among their certified categories, or the open fails with `ERR_FACILITATOR_NOT_CERTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/facilitator_not_certified_beats_budget_on_open
    """
    _, ver = create_approved_version(category="TECHNICAL", delivery_mode="VIRTUAL")
    fac = create_facilitator(certified_categories=["TECHNICAL"], email="facz2@example.com")
    cohort = create_scheduled_cohort(ver["id"], fac["id"], delivery_mode="VIRTUAL")
    api.suspend_facilitator(fac["id"], COORD)
    resp = api.open_cohort(cohort["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_FACILITATOR_NOT_CERTIFIED.value)


def test_delivery_mode_mismatch_on_open(api):
    """PRD §3.3: "The cohort's delivery mode must be compatible with the program's delivery mode
    — a `HYBRID` program accepts a cohort of any mode, whereas a `VIRTUAL` program rejects an
    `ONSITE` cohort and an `ONSITE` program rejects a `VIRTUAL` cohort — or the open fails with
    `ERR_DELIVERY_MODE_MISMATCH`."

    Design: Corner/validations/delivery_mode_mismatch_on_open
    """
    prog = create_program(category="TECHNICAL", delivery_mode="VIRTUAL")
    ver = create_draft_version(prog["id"], per_seat_cents=10000)
    api.submit_program_version(ver["id"], DESIGNER)
    api.approve_program_version(ver["id"], DESIGNER)
    fac = create_facilitator(certified_categories=["TECHNICAL"], email="facmm@example.com")
    cohort = create_scheduled_cohort(ver["id"], fac["id"], delivery_mode="ONSITE")
    resp = api.open_cohort(cohort["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_MODE_MISMATCH.value)


def test_lock_from_scheduled_invalid_state(api):
    """PRD §2.9: "for any state-transition endpoint, the target resource must currently be in a
    state from which the requested transition is defined; otherwise the request is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/cohort_lock_from_scheduled_invalid_state
    """
    _, ver = create_approved_version()
    fac = create_facilitator(certified_categories=["TECHNICAL"], email="faciv@example.com")
    cohort = create_scheduled_cohort(ver["id"], fac["id"], delivery_mode="VIRTUAL")
    resp = api.lock_cohort(cohort["id"], cohort["version"], COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_start_before_starts_at_rejected(api):
    """PRD §3.3: "Starting a cohort advances it from `LOCKED` to `RUNNING` and requires the
    logical clock to have reached `starts_at` (the clock must be at or after `starts_at`),
    failing otherwise with `ERR_BEFORE_START`."

    Design: Corner/state_machines/cohort_start_before_starts_at_rejected
    """
    ctx = setup_open_cohort(
        cohort_overrides={"starts_at": "2026-07-05T09:00:00Z", "ends_at": "2026-07-05T11:00:00Z",
                          "enroll_deadline": "2026-07-04T00:00:00Z"},
        version_overrides={"per_seat_cents": 10000, "min_seats": 1},
    )
    coh_id = ctx["cohort"]["id"]
    register_and_confirm(coh_id, "er@example.com")
    lock_cohort(coh_id)
    # clock still at default 2026-03-01, well before starts_at
    resp = api.start_cohort(coh_id, COORD)
    validate_error(resp, ApiErrorId.ERR_BEFORE_START.value)


def test_deliver_before_end_rejected(api):
    """PRD §3.3: "Delivering a cohort advances it from `RUNNING` to `DELIVERED` and requires the
    clock to have reached `ends_at` (at or after `ends_at`), failing otherwise with
    `ERR_BEFORE_END`."

    Design: Corner/errors/deliver_before_end_rejected
    """
    ctx = setup_open_cohort(
        cohort_overrides={"starts_at": "2026-07-26T09:00:00Z", "ends_at": "2026-07-26T11:00:00Z",
                          "enroll_deadline": "2026-07-25T00:00:00Z"},
        version_overrides={"per_seat_cents": 10000, "min_seats": 1},
    )
    coh_id = ctx["cohort"]["id"]
    register_and_confirm(coh_id, "be@example.com")
    lock_cohort(coh_id)
    set_clock("2026-07-26T09:00:00Z")
    api.start_cohort(coh_id, COORD)
    resp = api.deliver_cohort(coh_id, COORD)  # clock at starts_at, before ends_at
    validate_error(resp, ApiErrorId.ERR_BEFORE_END.value)


def test_deliver_settles_attendance(api):
    """PRD §3.3: "The deliver transition settles attendance: every registration still in
    `CONFIRMED` with no attendance mark is moved to `NO_SHOW`, and any remaining `CONFIRMED`
    registration that was marked attended is moved to `ATTENDED`."

    Design: Corner/state_machines/deliver_settles_attendance_confirmed_to_no_show
    """
    ctx = setup_open_cohort(
        delivery_mode="ONSITE", category="TECHNICAL",
        cohort_overrides={"starts_at": "2026-07-07T09:00:00Z", "ends_at": "2026-07-07T13:00:00Z",
                          "enroll_deadline": "2026-07-06T00:00:00Z"},
        version_overrides={"per_seat_cents": 10000, "min_seats": 1},
    )
    coh_id = ctx["cohort"]["id"]
    reg1 = register_and_confirm(coh_id, "s1@example.com")
    reg2 = register_and_confirm(coh_id, "s2@example.com")
    lock_cohort(coh_id)
    set_clock("2026-07-07T09:00:00Z")
    api.start_cohort(coh_id, COORD)
    fac_headers = make_facilitator_headers(ctx["facilitator"]["id"])
    api.mark_attendance(reg1["id"], fac_headers)
    set_clock("2026-07-07T13:00:00Z")
    api.deliver_cohort(coh_id, COORD)
    assert validate_success(api.get_registration(reg1["id"], COORD))["status"] == "ATTENDED"
    assert validate_success(api.get_registration(reg2["id"], COORD))["status"] == "NO_SHOW"


def test_min_seats_not_met_on_lock(api):
    """PRD §3.3: "Independently, `seats_confirmed` must be at least the program version's
    `min_seats`, or the lock is rejected with `ERR_MIN_SEATS_NOT_MET`."

    Design: Corner/validations/min_seats_not_met_on_lock
    """
    ctx = setup_open_cohort(
        seat_capacity=5,
        version_overrides={"per_seat_cents": 10000, "min_seats": 2},
    )
    coh_id = ctx["cohort"]["id"]
    # no confirmed registrations -> seats_confirmed (0) < min_seats (2)
    v = current_cohort_version(coh_id)
    resp = api.lock_cohort(coh_id, v, COORD)
    validate_error(resp, ApiErrorId.ERR_MIN_SEATS_NOT_MET.value)


def test_open_branches_lock_or_cancel(api):
    """PRD §3.3: "Locking a cohort closes enrollment and advances it from `OPEN` to `LOCKED`."
    PRD §3.3: "Cancelling a cohort is available from both `OPEN` and `LOCKED` and drives the
    three-level cascade specified in §2.6, voiding invoices and releasing any contract
    reservation; the cohort itself moves to `CANCELLED`."

    Design: Difficulty/non_linear_state_machine/cohort_open_branches_lock_or_cancel
    """
    _, ver = create_approved_version(category="COMPLIANCE", delivery_mode="VIRTUAL",
                                     version_overrides={"per_seat_cents": 20000, "min_seats": 1})
    fac = create_facilitator(certified_categories=["COMPLIANCE"], email="facc_branch@example.com")
    coh_a = create_scheduled_cohort(ver["id"], fac["id"], delivery_mode="VIRTUAL", seat_capacity=3,
                                    starts_at="2026-05-10T09:00:00Z", ends_at="2026-05-10T12:00:00Z",
                                    enroll_deadline="2026-05-09T00:00:00Z")
    coh_b = create_scheduled_cohort(ver["id"], fac["id"], delivery_mode="VIRTUAL", seat_capacity=3,
                                    starts_at="2026-05-11T09:00:00Z", ends_at="2026-05-11T12:00:00Z",
                                    enroll_deadline="2026-05-10T00:00:00Z")
    api.open_cohort(coh_a["id"], COORD)
    api.open_cohort(coh_b["id"], COORD)
    register_and_confirm(coh_a["id"], "ax@example.com")
    reg_b = register_and_confirm(coh_b["id"], "bx@example.com")
    # Branch 1: lock cohort A -> LOCKED with a PROVISIONAL invoice.
    locked = lock_cohort(coh_a["id"])
    assert locked["status"] == "LOCKED"
    from test_helpers import invoice_by_variant
    assert invoice_by_variant(coh_a["id"], "PROVISIONAL") is not None
    # Branch 2: cancel cohort B -> CANCELLED, registration cascaded to CANCELLED.
    cancelled = validate_success(api.cancel_cohort(coh_b["id"], COORD))
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api.get_registration(reg_b["id"], COORD))["status"] == "CANCELLED"


def test_cancel_branch_from_open_cascades_registrations(api):
    """PRD §3.3: "Cancelling a cohort is available from both `OPEN` and `LOCKED` and drives the
    three-level cascade specified in §2.6, voiding invoices and releasing any contract
    reservation; the cohort itself moves to `CANCELLED`." PRD §2.6: "every non-terminal
    `Registration` of that cohort transitions to `CANCELLED`."

    Design: Difficulty/non_linear_state_machine/cohort_open_branches_lock_or_cancel
    """
    ctx = setup_open_cohort(category="COMPLIANCE",
                            version_overrides={"per_seat_cents": 20000, "min_seats": 1})
    coh_id = ctx["cohort"]["id"]
    reg = register_and_confirm(coh_id, "branch2@example.com")
    cancelled = validate_success(api.cancel_cohort(coh_id, COORD))
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api.get_registration(reg["id"], COORD))["status"] == "CANCELLED"


def test_lock_stale_version_returns_412(api):
    """PRD §2.7: "If a confirm or withdraw has bumped the cohort's version since the coordinator
    last read it — meaning the lock request is acting on a stale view of the seat ledger — the
    lock is rejected with `ERR_STALE_COHORT_VERSION` (HTTP 412)."

    Design: Corner/state_machines/cohort_lock_stale_version_returns_412
    """
    ctx = setup_open_cohort(version_overrides={"per_seat_cents": 10000, "min_seats": 1})
    coh_id = ctx["cohort"]["id"]
    pre_version = current_cohort_version(coh_id)  # observed before the confirm
    reg = register_learner(coh_id, "oc@example.com")
    # confirm by the learner bumps Cohort.version, so pre_version is now stale
    from test_helpers import confirm_learner
    confirm_learner(reg["id"], "oc@example.com")
    resp = api.lock_cohort(coh_id, pre_version, COORD)  # carrying stale version
    validate_error(resp, ApiErrorId.ERR_STALE_COHORT_VERSION.value)
