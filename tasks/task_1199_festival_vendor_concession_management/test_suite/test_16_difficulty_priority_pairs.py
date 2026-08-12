"""Difficulty: priority_pair_validation_conflict — the §2.10 gauntlet orders dual failures."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_application,
    advance_festival,
    api_client,
    book_reservation,
    confirm_assignment,
    create_slot,
    create_vendor,
    decide_application,
    get_application,
    provision_assignment,
    record_inspection,
    release_assignment,
    set_clock,
    setup_confirmed_assignment,
    setup_open_festival,
    start_review,
    submit_application,
    validate_error,
)

VM = TEST_USERS["vendor_manager_headers"]
OPS = TEST_USERS["ops_headers"]


class TestStateVsSafetyOnActivate:
    def test_released_assignment_activate_reports_state_error(self, api):
        """PRD §2.10: "Eighth, state-machine legality of the requested transition,
        including terminal-state lockdown, together with request-shape validity —
        missing required fields, malformed values, and enum violations surface as
        `ERR_INVALID_REQUEST` (HTTP 400), while an illegal transition surfaces as
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409) (8)."
        PRD §2.10: "Tenth, the public-safety pre-open inspection gate (10)."
        PRD §2.10: "A failure at any step stops evaluation and returns that
        step's error."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_activate
        """
        scen = setup_confirmed_assignment(name="Prio Fest A")
        asg_id = scen["assignment"]["id"]
        provision_assignment(asg_id)
        set_clock(scen["festival"]["event_start"])
        advance_festival(scen["festival"]["id"], "LIVE")
        release_assignment(asg_id)
        # Dual violation: RELEASED has no activate transition (priority 8) AND no
        # HEALTH_PREOPEN inspection exists (priority 10). The state error wins.
        resp = api.activate_assignment(asg_id, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_confirmed_assignment_without_inspection_reports_safety_error(self, api):
        """PRD §3.4: "The latest `HEALTH_PREOPEN` inspection for the assignment —
        latest meaning the greatest `created_at` — must have `result` `PASS`; if
        no pre-open inspection exists, or the latest one is `CONDITIONAL_PASS` or
        `FAIL`, activation is rejected with `ERR_PREOPEN_INSPECTION_MISSING`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_activate
        """
        scen = setup_confirmed_assignment(name="Prio Fest A2")
        asg_id = scen["assignment"]["id"]
        provision_assignment(asg_id)
        set_clock(scen["festival"]["event_start"])
        advance_festival(scen["festival"]["id"], "LIVE")
        # Single violation: CONFIRMED may activate (priority 8 passes); only the
        # priority-10 safety gate can fail.
        resp = api.activate_assignment(asg_id, OPS)
        validate_error(resp, ApiErrorId.ERR_PREOPEN_INSPECTION_MISSING)


def _setup_locked_overlap():
    """CURATED festival; CONFIRMED assignment holds r1 in slot S1 08:00-11:00;
    slot S2 windows 10:00-12:00 (overlaps r1)."""
    scen = setup_confirmed_assignment(name="Prio Fest B")
    s1 = create_slot(scen["festival"]["id"], gate="GATE_A",
                     window_start="2026-07-10T08:00:00Z", window_end="2026-07-10T11:00:00Z")
    s2 = create_slot(scen["festival"]["id"], gate="GATE_B",
                     window_start="2026-07-10T10:00:00Z", window_end="2026-07-10T12:00:00Z")
    book_reservation(scen["assignment"]["id"], s1["id"], vehicle_count=1)
    scen.update({"s1": s1, "s2": s2})
    return scen


class TestTemporalVsConstraintOnBook:
    def test_locked_and_overlapping_booking_reports_slot_locked(self, api):
        """PRD §2.10: "Eleventh, temporal clock rules (11)."
        PRD §2.10: "Twelfth, resource constraints — category exclusivity and
        caps, booth availability, outlet and hookup fit, zone budgets, slot
        capacity, window overlap, and the review-round limit (12)."
        PRD §2.10: "A failure at any step stops evaluation and returns that
        step's error."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_on_reservation_book
        """
        scen = _setup_locked_overlap()
        set_clock("2026-07-10T08:30:00Z")  # past S2's lock horizon (10:00 - 120min = 08:00)
        # Dual violation: past the lock horizon (11) AND overlaps r1 (12).
        resp = api.create_reservation(
            {"assignment_id": scen["assignment"]["id"], "slot_id": scen["s2"]["id"],
             "vehicle_count": 1},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_LOCKED)

    def test_pre_lock_overlapping_booking_reports_window_overlap(self, api):
        """PRD §3.5: "overlap exists exactly when the existing window starts
        before the new window ends and the new window starts before the existing
        window ends, under half-open semantics where adjacency (one window's
        close equal to the other's open) is not an overlap; a violation is
        rejected with `ERR_VEHICLE_WINDOW_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_on_reservation_book
        """
        scen = _setup_locked_overlap()  # clock still at the default — pre-lock
        # Single violation: only the geometric overlap can fire.
        resp = api.create_reservation(
            {"assignment_id": scen["assignment"]["id"], "slot_id": scen["s2"]["id"],
             "vehicle_count": 1},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_WINDOW_OVERLAP)


class TestConstraintVsFiscalOnAccept:
    def test_capped_and_termless_accept_reports_category_cap(self, api):
        """PRD §2.10: "Twelfth, resource constraints — category exclusivity and
        caps, booth availability, outlet and hookup fit, zone budgets, slot
        capacity, window overlap, and the review-round limit (12)."
        PRD §2.10: "Thirteenth, fiscal checks — fee-term completeness, positive
        amounts, and optimistic-concurrency freshness (13)."
        PRD §2.10: "A failure at any step stops evaluation and returns that
        step's error."
        PRD §3.2: "if the number of the festival's already-accepted applications
        in the same category has reached `category_cap_per_category`, the
        decision is rejected with `ERR_CATEGORY_CAP_REACHED`."

        Design: Difficulty/priority_pair_validation_conflict/constraint_vs_fiscal_on_decide_accept
        """
        scen = setup_open_festival(name="Prio Fest C", cap=1)
        fest_id = scen["festival"]["id"]
        va = create_vendor(legal_name="Cap A LLC", contact_email="a@cap.com")
        vb = create_vendor(legal_name="Cap B LLC", contact_email="b@cap.com")
        appa = submit_application(va, fest_id, category="FOOD_HOT")
        appb = submit_application(vb, fest_id, category="FOOD_HOT")
        start_review(appa["id"])
        accept_application(appa["id"], "FLAT_FEE", flat_fee_cents=50000)  # cap consumed
        start_review(appb["id"])
        # Dual violation: cap reached (12) AND no curated terms supplied (13).
        resp = api.decide_application(appb["id"], {"decision": "ACCEPTED"}, VM)
        validate_error(resp, ApiErrorId.ERR_CATEGORY_CAP_REACHED)
        assert get_application(appb["id"])["status"] == "UNDER_REVIEW"

    def test_uncapped_termless_accept_reports_fee_terms(self, api):
        """PRD §3.2: "acceptance is rejected with `ERR_FEE_TERMS_INCOMPLETE`
        (HTTP 400) when the set is incomplete".

        Design: Difficulty/priority_pair_validation_conflict/constraint_vs_fiscal_on_decide_accept
        """
        scen = setup_open_festival(name="Prio Fest C2", cap=2)
        vendor = create_vendor(legal_name="Cap Solo LLC")
        app = submit_application(vendor, scen["festival"]["id"], category="FOOD_HOT")
        start_review(app["id"])
        # Single violation: cap 2 not reached; only the termless ACCEPT can fail.
        resp = api.decide_application(app["id"], {"decision": "ACCEPTED"}, VM)
        validate_error(resp, ApiErrorId.ERR_FEE_TERMS_INCOMPLETE)
