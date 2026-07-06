"""Registration, confirmation, withdrawal, the waitlist, and seat-ledger reconciliation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_registration, assert_seat_ledger_nonnegative,
    setup_open_cohort, register_learner, confirm_learner, register_and_confirm,
    lock_cohort, current_cohort_version, set_clock,
    make_learner_headers, make_facilitator_headers, TEST_USERS,
)

COORD = TEST_USERS["scheduling_coordinator_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


def test_seat_counts_reconcile_on_confirm(api):
    """PRD §3.5: "On confirm, `seats_reserved` decreases by one and `seats_confirmed` increases
    by one, and the `seat_price_cents` is locked according to the seat-price rule of §3.6."

    Design: Corner/cross_cutting_complexity_layers/derived_field_seat_counts_reconcile_on_confirm
    """
    ctx = setup_open_cohort(version_overrides={"per_seat_cents": 10000, "min_seats": 1})
    coh_id = ctx["cohort"]["id"]
    reg = register_learner(coh_id, "df@example.com")
    confirm_learner(reg["id"], "df@example.com")
    cohort = validate_success(api.get_cohort(coh_id, COORD))
    assert cohort["seats_reserved"] == 0
    assert cohort["seats_confirmed"] == 1
    assert_seat_ledger_nonnegative(cohort)


def test_confirm_immediate_consistency(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return
    the created or updated resource object in the data field." PRD §3.5: "Confirming a seat moves
    a registration from `ENROLLED` to `CONFIRMED` and is performed by the `Learner`."

    Design: Corner/consistency_model/immediate_seat_counts_visible_in_same_response
    """
    ctx = setup_open_cohort(version_overrides={"per_seat_cents": 10000, "min_seats": 1})
    reg = register_learner(ctx["cohort"]["id"], "im@example.com")
    data = validate_success(api.confirm_registration(reg["id"], make_learner_headers("im@example.com")))
    assert data["status"] == "CONFIRMED"


def test_duplicate_registration_rejected(api):
    """PRD §3.5: "A duplicate `learner_email` already registered (non-terminally) in the cohort
    is rejected with `ERR_DUPLICATE_REGISTRATION`."

    Design: Corner/validations/duplicate_registration_email_in_cohort
    """
    ctx = setup_open_cohort(version_overrides={"per_seat_cents": 10000, "min_seats": 1})
    coh_id = ctx["cohort"]["id"]
    register_learner(coh_id, "dup@example.com", "Dup1")
    resp = api.create_registration(
        coh_id, {"learner_email": "dup@example.com", "learner_name": "Dup2"}, COORD,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGISTRATION.value)


def test_enroll_after_deadline_window_closed(api):
    """PRD §3.5: "Registration is permitted only while the logical clock is before
    `enroll_deadline`; a later attempt is rejected with `ERR_ENROLL_WINDOW_CLOSED`."

    Design: Corner/validations/enroll_after_deadline_window_closed
    """
    ctx = setup_open_cohort(
        cohort_overrides={"starts_at": "2026-07-14T09:00:00Z", "ends_at": "2026-07-14T11:00:00Z",
                          "enroll_deadline": "2026-07-13T00:00:00Z"},
        version_overrides={"per_seat_cents": 10000, "min_seats": 1},
    )
    set_clock("2026-07-13T01:00:00Z")  # after deadline, before starts_at
    resp = api.create_registration(
        ctx["cohort"]["id"], {"learner_email": "wn@example.com", "learner_name": "WN"}, COORD,
    )
    validate_error(resp, ApiErrorId.ERR_ENROLL_WINDOW_CLOSED.value)


def test_cohort_full_then_waitlist_full(api):
    """PRD §3.5: "if seats are full and the waitlist is at capacity, the request is rejected with
    `ERR_WAITLIST_FULL`."

    Design: Corner/validations/cohort_full_then_waitlist_full
    """
    ctx = setup_open_cohort(
        seat_capacity=1, waitlist_capacity=1,
        version_overrides={"per_seat_cents": 10000, "min_seats": 1},
    )
    coh_id = ctx["cohort"]["id"]
    register_learner(coh_id, "f1@example.com")  # ENROLLED, seat full
    register_learner(coh_id, "f2@example.com")  # WAITLISTED, waitlist full
    resp = api.create_registration(
        coh_id, {"learner_email": "f3@example.com", "learner_name": "F3"}, COORD,
    )
    validate_error(resp, ApiErrorId.ERR_WAITLIST_FULL.value)


def test_shared_registration_create_allowed_for_both_roles(api):
    """PRD §3.5: "A `Learner` (or a `SchedulingCoordinator` acting on their behalf) registers by
    supplying a `learner_email`, unique among the non-terminal registrations of that cohort, and
    a `learner_name`."

    Design: Corner/rbac/shared_registration_create_allowed_for_both_roles
    """
    ctx = setup_open_cohort(version_overrides={"per_seat_cents": 10000, "min_seats": 1})
    coh_id = ctx["cohort"]["id"]
    register_learner(coh_id, "sh1@example.com")  # via SchedulingCoordinator
    data = validate_success(
        api.create_registration(
            coh_id, {"learner_email": "sh2@example.com", "learner_name": "SH2"},
            make_learner_headers("sh2@example.com"),
        ),
        expected_status=201,
    )
    assert_registration(data)
    assert data["status"] == "ENROLLED"


def test_confirm_while_cohort_not_open_rejected(api):
    """PRD §3.5: "Confirming a seat moves a registration from `ENROLLED` to `CONFIRMED` and is
    performed by the `Learner`. Confirmation requires the cohort to be `OPEN`, failing otherwise
    with `ERR_COHORT_NOT_OPEN`."

    Design: Corner/errors/confirm_while_cohort_not_open_rejected
    """
    ctx = setup_open_cohort(
        seat_capacity=2,
        version_overrides={"per_seat_cents": 10000, "min_seats": 1},
    )
    coh_id = ctx["cohort"]["id"]
    register_and_confirm(coh_id, "no1@example.com")  # satisfies min_seats
    reg2 = register_learner(coh_id, "no2@example.com")  # left ENROLLED
    lock_cohort(coh_id)  # cohort now LOCKED, not OPEN
    resp = api.confirm_registration(reg2["id"], make_learner_headers("no2@example.com"))
    validate_error(resp, ApiErrorId.ERR_COHORT_NOT_OPEN.value)


def test_mark_attendance_cohort_not_running_rejected(api):
    """PRD §3.5: "Marking attendance moves a registration from `CONFIRMED` to `ATTENDED` and is
    performed by a `Facilitator`; it requires the cohort to be `RUNNING` or `DELIVERED`, failing
    otherwise with `ERR_COHORT_NOT_RUNNING`."

    Design: Corner/errors/mark_attendance_cohort_not_running_rejected
    """
    ctx = setup_open_cohort(version_overrides={"per_seat_cents": 10000, "min_seats": 1})
    coh_id = ctx["cohort"]["id"]
    reg = register_and_confirm(coh_id, "nr@example.com")
    lock_cohort(coh_id)  # LOCKED, not RUNNING
    fac_headers = make_facilitator_headers(ctx["facilitator"]["id"])
    resp = api.mark_attendance(reg["id"], fac_headers)
    validate_error(resp, ApiErrorId.ERR_COHORT_NOT_RUNNING.value)


def test_forbidden_role_beats_invalid_state_on_confirm(api):
    """PRD §2.9: "Role authorization is checked second, yielding `ERR_FORBIDDEN_ROLE` when the
    acting role may not perform the operation." PRD §2.9: "These global checks always precede the
    domain-specific guards described in §3."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_invalid_state_on_confirm
    """
    ctx = setup_open_cohort(version_overrides={"per_seat_cents": 10000, "min_seats": 1})
    coh_id = ctx["cohort"]["id"]
    reg = register_and_confirm(coh_id, "c1@example.com")  # already CONFIRMED
    # A FinanceManager may not confirm (not in the confirm RBAC list); auth (403) must win over
    # the ERR_INVALID_STATE (409) the already-confirmed registration would otherwise raise.
    resp = api.confirm_registration(reg["id"], FINANCE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_forbidden_role_confirm_on_enrolled(api):
    """PRD §2.9: "Role authorization is checked second, yielding `ERR_FORBIDDEN_ROLE` when the
    acting role may not perform the operation."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_invalid_state_on_confirm
    """
    ctx = setup_open_cohort(version_overrides={"per_seat_cents": 10000, "min_seats": 1})
    reg = register_learner(ctx["cohort"]["id"], "c2@example.com")  # ENROLLED
    resp = api.confirm_registration(reg["id"], FINANCE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


class TestWithdrawalPromotion:
    def test_withdraw_frees_seat_promotes_waitlist(self, api):
        """PRD §3.5: "Withdrawing an `ENROLLED` registration moves it to `WITHDRAWN` and
        decreases `seats_reserved` by one; withdrawing a `CONFIRMED` registration moves it to
        `WITHDRAWN` and decreases `seats_confirmed` by one. In both cases, once the seat is freed
        the system promotes the earliest `WAITLISTED` registration of that cohort (ordered by
        `created_at` ascending), if any exists."

        Design: Difficulty/transitive_cascade/withdraw_frees_seat_promotes_waitlist
        """
        ctx = setup_open_cohort(
            seat_capacity=1, waitlist_capacity=2,
            version_overrides={"per_seat_cents": 10000, "min_seats": 1},
        )
        coh_id = ctx["cohort"]["id"]
        reg_w1 = register_and_confirm(coh_id, "w1@example.com")  # seat full
        reg_w2 = register_learner(coh_id, "w2@example.com")      # WAITLISTED
        validate_success(api.withdraw_registration(reg_w1["id"], make_learner_headers("w1@example.com")))
        assert validate_success(api.get_registration(reg_w1["id"], COORD))["status"] == "WITHDRAWN"
        assert validate_success(api.get_registration(reg_w2["id"], COORD))["status"] == "ENROLLED"
        cohort = validate_success(api.get_cohort(coh_id, COORD))
        assert cohort["seats_confirmed"] == 0
        assert cohort["seats_reserved"] == 1
        assert cohort["seats_waitlisted"] == 0

    def test_withdraw_promotes_earliest_waitlisted_by_created_at(self, api):
        """PRD §3.5: "once the seat is freed the system promotes the earliest `WAITLISTED`
        registration of that cohort (ordered by `created_at` ascending), if any exists."

        Design: Difficulty/transitive_cascade/withdraw_frees_seat_promotes_waitlist
        """
        ctx = setup_open_cohort(
            seat_capacity=1, waitlist_capacity=2,
            version_overrides={"per_seat_cents": 10000, "min_seats": 1},
        )
        coh_id = ctx["cohort"]["id"]
        held = register_and_confirm(coh_id, "held@example.com")  # seat full
        first_wl = register_learner(coh_id, "wl_first@example.com")   # earliest waitlisted
        second_wl = register_learner(coh_id, "wl_second@example.com")  # later waitlisted
        validate_success(api.withdraw_registration(held["id"], make_learner_headers("held@example.com")))
        assert validate_success(api.get_registration(first_wl["id"], COORD))["status"] == "ENROLLED"
        assert validate_success(api.get_registration(second_wl["id"], COORD))["status"] == "WAITLISTED"

    def test_withdraw_promotion_conserves_total_occupancy(self, api):
        """PRD §3.5: "once the seat is freed the system promotes the earliest `WAITLISTED`
        registration of that cohort (ordered by `created_at` ascending), if any exists." PRD §3.5:
        "the earliest waitlisted registration transitions from `WAITLISTED` to `ENROLLED`,
        decreasing `seats_waitlisted` by one and increasing `seats_reserved` by one."

        Design: Difficulty/compensating_invariant/withdraw_promotion_conserves_total_occupancy
        """
        ctx = setup_open_cohort(
            category="SALES", pricing_model="PER_SEAT",
            seat_capacity=1, waitlist_capacity=1,
            version_overrides={"per_seat_cents": 10000, "min_seats": 1},
        )
        coh_id = ctx["cohort"]["id"]
        reg_o1 = register_and_confirm(coh_id, "o1@example.com")  # occupancy = 1 (confirmed)
        reg_o2 = register_learner(coh_id, "o2@example.com")      # WAITLISTED
        before = validate_success(api.get_cohort(coh_id, COORD))
        assert before["seats_reserved"] + before["seats_confirmed"] == 1
        validate_success(api.withdraw_registration(reg_o1["id"], make_learner_headers("o1@example.com")))
        after = validate_success(api.get_cohort(coh_id, COORD))
        assert after["seats_reserved"] + after["seats_confirmed"] == 1, "occupancy conserved"
        assert after["seats_waitlisted"] == 0
        assert validate_success(api.get_registration(reg_o2["id"], COORD))["status"] == "ENROLLED"


def test_withdraw_enrolled_promotion_conserves_occupancy(api):
    """PRD §3.5: "Withdrawing an `ENROLLED` registration moves it to `WITHDRAWN` and decreases
    `seats_reserved` by one". PRD §3.5: "the earliest waitlisted registration transitions from
    `WAITLISTED` to `ENROLLED`, decreasing `seats_waitlisted` by one and increasing
    `seats_reserved` by one."

    Design: Difficulty/compensating_invariant/withdraw_promotion_conserves_total_occupancy
    """
    ctx = setup_open_cohort(
        seat_capacity=1, waitlist_capacity=1,
        version_overrides={"per_seat_cents": 10000, "min_seats": 1},
    )
    coh_id = ctx["cohort"]["id"]
    enrolled = register_learner(coh_id, "en1@example.com")  # occupancy = 1 (reserved)
    waitlisted = register_learner(coh_id, "en2@example.com")  # WAITLISTED
    before = validate_success(api.get_cohort(coh_id, COORD))
    assert before["seats_reserved"] + before["seats_confirmed"] == 1
    validate_success(api.withdraw_registration(enrolled["id"], make_learner_headers("en1@example.com")))
    after = validate_success(api.get_cohort(coh_id, COORD))
    assert after["seats_reserved"] + after["seats_confirmed"] == 1, "occupancy conserved"
    assert validate_success(api.get_registration(waitlisted["id"], COORD))["status"] == "ENROLLED"


def test_cancel_voids_and_cancels_registration(api):
    """PRD §2.6: "When a cohort in `OPEN` or `LOCKED` state is cancelled, the system performs a
    three-level cascade in order. First (level one), every non-terminal `Registration` of that
    cohort transitions to `CANCELLED`."

    Design: Corner/cross_cutting_complexity_layers/cascade_cancel_voids_invoice_and_cancels_registration
    """
    ctx = setup_open_cohort(version_overrides={"per_seat_cents": 10000, "min_seats": 1})
    coh_id = ctx["cohort"]["id"]
    reg = register_learner(coh_id, "cs@example.com")  # never locked -> no invoice
    coh = validate_success(api.cancel_cohort(coh_id, COORD))
    assert coh["status"] == "CANCELLED"
    assert validate_success(api.get_registration(reg["id"], COORD))["status"] == "CANCELLED"
