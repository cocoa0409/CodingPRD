"""Split-carcass ownership, cut instructions, and fabrication gates.

Covers share fraction domain rules, over/under-allocation, the
create/delete-share invariant, the finalize state gate, the one-sheet-per-share
rule, yield feasibility, the submit-revise cycle with OCC, fabrication
preconditions and priority ordering, and sheet lockdown.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_share,
    add_share_payload,
    book_and_confirm,
    create_and_submit_cut_sheet,
    create_capacity_day,
    create_cut_sheet,
    create_customer,
    finalize_split,
    get_cut_sheet,
    get_share,
    get_share_cut_sheet,
    get_success_data,
    make_customer_headers,
    process_animal_to_hanging,
    revise_cut_sheet_payload,
    set_logical_clock,
    setup_finalized_single_share,
    setup_hanging_animal,
    submit_cut_sheet,
    validate_error,
    validate_success,
)

OP = TEST_USERS["operator_headers"]


class TestShareDomainRules:
    def test_share_fraction_over_precision_returns_invalid_request(self, api):
        """PRD §2.8: "numeric domains respected ... `share_fraction` greater
        than 0 and at most 1.0 with no more than three decimal places ...
        Any well-formedness failure is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/share_fraction_over_precision_returns_invalid_request
        """
        scenario = setup_hanging_animal()
        customer = scenario["customer"]
        resp = api.add_share(
            scenario["animal"]["id"],
            add_share_payload(customer["id"], 0.3335, "OWNER_USE"),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_split_over_allocated_rejected(self, api):
        """PRD §3.4: "Adding a share that would push the animal's fraction sum
        above 1.0 is rejected with `ERR_SPLIT_OVER_ALLOCATED`."

        Design: Corner/validations/split_over_allocated_rejected
        """
        scenario = setup_hanging_animal()
        customer = scenario["customer"]
        animal_id = scenario["animal"]["id"]
        add_share(animal_id, customer["id"], 0.6, as_customer_id=customer["id"])
        resp = api.add_share(
            animal_id,
            add_share_payload(customer["id"], 0.5, "OWNER_USE"),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SPLIT_OVER_ALLOCATED, expected_status=422)
        remaining = get_success_data(
            api.list_shares(OP, params={"animal_id": animal_id})
        )
        assert len(remaining) == 1
        assert remaining[0]["share_fraction"] == 0.6


class TestShareCreateDeleteInvariant:
    def _setup_hanging_300(self):
        c1 = create_customer("Ann Orr", "555-0101", "ann@x.com")
        c2 = create_customer("Bob Venn", "555-0102", "bob@x.com")
        day = create_capacity_day("2026-08-20", 1)
        _appointment, animals = book_and_confirm(c1["id"], day["id"], "HOG", 1)
        animal = process_animal_to_hanging(animals[0]["id"], "TAG-H1", 400.0, 300.0)
        return c1, c2, animal

    def test_share_delete_restores_unallocated_fraction(self, api):
        """PRD §3.4: "While the split is still being worked out, a `PENDING`
        share may be removed — the booking customer or staff deletes it, the
        animal's allocated fraction decreases accordingly, and the response
        carries no content."
        PRD §3.4: "only when the fractions across the animal's shares sum to
        exactly 1.0, with a shortfall rejected as `ERR_SPLIT_UNDER_ALLOCATED`."

        Design: Difficulty/compensating_invariant/share_create_delete_roundtrip_preserves_unallocated_fraction
        """
        c1, _c2, animal = self._setup_hanging_300()
        share = add_share(animal["id"], c1["id"], 0.5, as_customer_id=c1["id"])
        removed = api.delete_share(share["id"], make_customer_headers(c1["id"]))
        assert removed.status_code == 204, (
            "share removal returns 204 No Content (PRD §4)"
        )
        # The create+delete round trip leaves zero fraction allocated.
        resp = api.finalize_shares(animal["id"], OP)
        validate_error(resp, ApiErrorId.ERR_SPLIT_UNDER_ALLOCATED,
                       expected_status=422)
        unchanged = get_success_data(api.get_animal(animal["id"], OP))
        assert unchanged["hanging_weight_lbs"] == 300.0, (
            "share churn must not disturb the recorded hanging weight"
        )

    def test_finalize_allocates_weights_summing_to_hanging(self, api):
        """PRD §3.4: "each share's `share_hanging_weight_lbs` is computed as
        the animal's `hanging_weight_lbs` multiplied by the share's
        `share_fraction`, rounded half-up to one decimal place, share by share
        in creation order ... so the allocated weights sum to the hanging
        weight exactly."

        Design: Difficulty/compensating_invariant/share_create_delete_roundtrip_preserves_unallocated_fraction
        """
        c1, c2, animal = self._setup_hanging_300()
        # A deleted 0.5 share leaves no residue on the split.
        stale = add_share(animal["id"], c1["id"], 0.5, as_customer_id=c1["id"])
        api.delete_share(stale["id"], make_customer_headers(c1["id"]))
        s1 = add_share(animal["id"], c1["id"], 0.6, as_customer_id=c1["id"])
        s2 = add_share(animal["id"], c2["id"], 0.4, as_customer_id=c1["id"])
        finalize_split(animal["id"])
        share1 = get_share(s1["id"])
        share2 = get_share(s2["id"])
        assert share1["status"] == "CONFIRMED"
        assert share2["status"] == "CONFIRMED"
        assert share1["share_hanging_weight_lbs"] == 180.0
        assert share2["share_hanging_weight_lbs"] == 120.0
        total = share1["share_hanging_weight_lbs"] + share2["share_hanging_weight_lbs"]
        assert total == 300.0, "allocated weights sum to the hanging weight exactly"


class TestFinalizeGate:
    def test_finalize_rejected_before_hanging(self, api):
        """PRD §3.4: "Finalizing the split is a staff action taken once the
        animal is `HANGING` — attempting it earlier fails with
        `ERR_INVALID_STATE`".

        Design: Difficulty/cross_entity_state_dependency/finalize_requires_animal_hanging
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 1)
        _appointment, animals = book_and_confirm(customer["id"], day["id"], "HOG", 1)
        animal_id = animals[0]["id"]
        # Receive and slaughter only — the animal is SLAUGHTERED, not HANGING.
        get_success_data(
            api.receive_animal(animal_id, {"tag_id": "TAG-H1",
                                           "live_weight_lbs": 280.0}, OP)
        )
        get_success_data(api.slaughter_animal(animal_id, OP))
        add_share(animal_id, customer["id"], 1.0, as_customer_id=customer["id"])
        resp = api.finalize_shares(animal_id, OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_finalize_after_weigh_allocates_hanging_weight(self, api):
        """PRD §3.4: "Finalizing the split is a staff action taken once the
        animal is `HANGING` ... Finalization turns every `PENDING` share
        `CONFIRMED`" and computes each share's `share_hanging_weight_lbs`.

        Design: Difficulty/cross_entity_state_dependency/finalize_requires_animal_hanging
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 1)
        _appointment, animals = book_and_confirm(customer["id"], day["id"], "HOG", 1)
        animal_id = animals[0]["id"]
        process_animal_to_hanging(animal_id, "TAG-H1", 280.0, 200.0)
        share = add_share(animal_id, customer["id"], 1.0,
                          as_customer_id=customer["id"])
        finalize_split(animal_id)
        share_after = get_share(share["id"])
        assert share_after["status"] == "CONFIRMED"
        assert share_after["share_hanging_weight_lbs"] == 200.0


class TestCutSheetRules:
    def test_second_cut_sheet_rejected(self, api):
        """PRD §3.4: "a second sheet for the same share is refused with
        `ERR_CUT_SHEET_EXISTS`."

        Design: Corner/validations/second_cut_sheet_rejected
        """
        scenario = setup_finalized_single_share()
        customer = scenario["customer"]
        share_id = scenario["share"]["id"]
        create_cut_sheet(share_id, customer["id"], grind_pct=30,
                         package_weight_lbs=2.0)
        resp = api.create_cut_sheet(
            share_id,
            {"grind_pct": 20, "package_weight_lbs": 1.0},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CUT_SHEET_EXISTS, expected_status=409)
        original = get_share_cut_sheet(share_id)
        assert original["grind_pct"] == 30, "original sheet must be unchanged"

    def test_grind_over_max_submit_rejected(self, api):
        """PRD §3.4: "a `grind_pct` above 60 percent of the share's trimmable
        weight cannot be physically met, so submission with such a value is
        rejected with `ERR_YIELD_INFEASIBLE`."

        Design: Corner/validations/grind_over_max_submit_rejected
        """
        scenario = setup_finalized_single_share()
        customer = scenario["customer"]
        # grind_pct 70 is within the 0..100 input domain, so the DRAFT is
        # created; the feasibility rule fires at submit.
        sheet = create_cut_sheet(scenario["share"]["id"], customer["id"],
                                 grind_pct=70, package_weight_lbs=2.0)
        resp = api.submit_cut_sheet(sheet["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_YIELD_INFEASIBLE, expected_status=422)
        assert get_cut_sheet(sheet["id"])["status"] == "DRAFT"


class TestCutSheetCycle:
    def _setup_draft_sheet(self):
        scenario = setup_finalized_single_share()
        customer = scenario["customer"]
        sheet = create_cut_sheet(scenario["share"]["id"], customer["id"],
                                 grind_pct=30, package_weight_lbs=2.0)
        return customer, sheet

    def test_cut_sheet_submit_revise_returns_to_draft(self, api):
        """PRD §3.4: "revising ... when issued against a `SUBMITTED` sheet —
        returns the sheet to `DRAFT` so it must be submitted anew".
        PRD §2.5: "`version` — an integer that starts at creation and
        increments by exactly 1 on every mutation".

        Design: Difficulty/non_linear_state_machine/cut_sheet_submit_revise_resubmit_cycle
        """
        customer, sheet = self._setup_draft_sheet()
        v_create = sheet["version"]
        submitted = submit_cut_sheet(sheet["id"], customer["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["version"] == v_create + 1
        revised = validate_success(
            api.revise_cut_sheet(
                sheet["id"],
                revise_cut_sheet_payload(submitted["version"], grind_pct=25),
                make_customer_headers(customer["id"]),
            )
        )
        assert revised["status"] == "DRAFT", (
            "revising a SUBMITTED sheet returns it to DRAFT"
        )
        assert revised["grind_pct"] == 25, "revision applies provided fields"
        assert revised["version"] == submitted["version"] + 1

    def test_cut_sheet_resubmit_after_revise_completes_cycle(self, api):
        """PRD §3.4: "This submit–revise cycle can repeat freely until the
        animal enters fabrication."

        Design: Difficulty/non_linear_state_machine/cut_sheet_submit_revise_resubmit_cycle
        """
        customer, sheet = self._setup_draft_sheet()
        v1 = submit_cut_sheet(sheet["id"], customer["id"])["version"]
        v2 = validate_success(
            api.revise_cut_sheet(
                sheet["id"], revise_cut_sheet_payload(v1, grind_pct=25),
                make_customer_headers(customer["id"]),
            )
        )["version"]
        resubmitted = submit_cut_sheet(sheet["id"], customer["id"])
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["version"] == v2 + 1
        final = get_cut_sheet(sheet["id"])
        assert final["status"] == "SUBMITTED"
        assert final["grind_pct"] == 25

    def test_occ_stale_revise_rejected_412(self, api):
        """PRD §2.7: "Revising a cut sheet likewise requires
        `expected_cut_sheet_version` matching the cut sheet's current
        `version` — revision is legitimate from both of its non-terminal
        states, so a stale client would otherwise silently overwrite newer
        instructions — and a mismatch is rejected with the same
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_revise_rejected_412
        """
        customer, sheet = self._setup_draft_sheet()
        current_version = sheet["version"]
        stale = api.revise_cut_sheet(
            sheet["id"],
            revise_cut_sheet_payload(current_version - 1, grind_pct=25),
            make_customer_headers(customer["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        assert get_cut_sheet(sheet["id"])["grind_pct"] == 30, (
            "stale revision must not overwrite instructions"
        )
        data = validate_success(
            api.revise_cut_sheet(
                sheet["id"],
                revise_cut_sheet_payload(current_version, grind_pct=25),
                make_customer_headers(customer["id"]),
            )
        )
        assert data["grind_pct"] == 25
        assert data["version"] == current_version + 1

    def test_cut_sheet_locked_rejects_submit(self, api):
        """PRD §3.5: "every `SUBMITTED` cut sheet of its shares locks to
        `LOCKED`, ending the revision cycle."
        PRD §3.4: "Submission requires the share to still be in `PENDING` or
        `CONFIRMED` — once fabrication has begun the attempt fails with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cut_sheet_locked_rejects_submit
        """
        scenario = setup_finalized_single_share()
        customer = scenario["customer"]
        sheet = create_and_submit_cut_sheet(scenario["share"]["id"], customer["id"])
        set_logical_clock("2026-08-04T00:00:00Z")
        get_success_data(api.start_fabrication(scenario["animal"]["id"], OP))
        assert get_cut_sheet(sheet["id"])["status"] == "LOCKED"
        resp = api.submit_cut_sheet(sheet["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_cut_sheet(sheet["id"])["status"] == "LOCKED"


class TestFabricationGates:
    def test_start_fab_without_finalize_rejected(self, api):
        """PRD §3.5: "The split must be finalized — at least one `CONFIRMED`
        share covering a fraction sum of exactly 1.0 — else
        `ERR_SPLIT_NOT_FINALIZED`."

        Design: Corner/validations/start_fab_without_finalize_rejected
        """
        scenario = setup_hanging_animal()
        customer = scenario["customer"]
        animal_id = scenario["animal"]["id"]
        add_share(animal_id, customer["id"], 1.0, as_customer_id=customer["id"])
        # Share stays PENDING: finalize was never called.
        set_logical_clock("2026-08-04T00:00:00Z")
        resp = api.start_fabrication(animal_id, OP)
        validate_error(resp, ApiErrorId.ERR_SPLIT_NOT_FINALIZED,
                       expected_status=409)
        assert get_success_data(api.get_animal(animal_id, OP))["status"] == "HANGING"

    def test_min_hang_boundary_two_days_rejected_three_days_ok(self, api):
        """PRD §3.5: "The carcass must have aged enough: the current logical
        time must be at least three full days past `weighed_at`, else
        `ERR_MIN_HANG_NOT_MET`."

        Design: Corner/validations/min_hang_boundary_two_days_rejected_three_days_ok
        """
        scenario = setup_finalized_single_share()
        customer = scenario["customer"]
        create_and_submit_cut_sheet(scenario["share"]["id"], customer["id"])
        animal_id = scenario["animal"]["id"]
        # weighed_at is the default instant 2026-08-01T00:00:00Z.
        set_logical_clock("2026-08-03T00:00:00Z")  # only two full days past
        resp = api.start_fabrication(animal_id, OP)
        validate_error(resp, ApiErrorId.ERR_MIN_HANG_NOT_MET, expected_status=422)
        assert get_success_data(api.get_animal(animal_id, OP))["status"] == "HANGING"
        set_logical_clock("2026-08-04T00:00:00Z")  # exactly three full days
        data = validate_success(api.start_fabrication(animal_id, OP))
        assert data["status"] == "CUTTING"

    def test_start_fab_blocked_by_draft_cut_sheet(self, api):
        """PRD §3.5: "every `CONFIRMED` share of the animal must have its cut
        sheet in `SUBMITTED` status, else `ERR_CUT_SHEET_MISSING` — a sheet
        left in `DRAFT` blocks the knife just as surely as a missing one."

        Design: Difficulty/cross_entity_state_dependency/start_fab_requires_all_cut_sheets_submitted
        """
        c1 = create_customer("Ann Orr", "555-0101", "ann@x.com")
        c2 = create_customer("Bob Venn", "555-0102", "bob@x.com")
        day = create_capacity_day("2026-08-20", 1)
        _appointment, animals = book_and_confirm(c1["id"], day["id"], "BEEF", 1)
        animal = process_animal_to_hanging(animals[0]["id"], "TAG-A1", 1200.0, 700.0)
        s1 = add_share(animal["id"], c1["id"], 0.5, as_customer_id=c1["id"])
        s2 = add_share(animal["id"], c2["id"], 0.5, as_customer_id=c1["id"])
        finalize_split(animal["id"])
        create_and_submit_cut_sheet(s1["id"], c1["id"])
        create_cut_sheet(s2["id"], c2["id"], grind_pct=40, package_weight_lbs=1.5)
        # Share 2's sheet is still DRAFT; hang time is satisfied.
        set_logical_clock("2026-08-04T00:00:00Z")
        resp = api.start_fabrication(animal["id"], OP)
        validate_error(resp, ApiErrorId.ERR_CUT_SHEET_MISSING, expected_status=422)

    def test_start_fab_locks_submitted_sheets(self, api):
        """PRD §3.5: "When all three hold, the animal moves from `HANGING` to
        `CUTTING` and every `SUBMITTED` cut sheet of its shares locks to
        `LOCKED`, ending the revision cycle."

        Design: Difficulty/cross_entity_state_dependency/start_fab_requires_all_cut_sheets_submitted
        """
        c1 = create_customer("Ann Orr", "555-0101", "ann@x.com")
        c2 = create_customer("Bob Venn", "555-0102", "bob@x.com")
        day = create_capacity_day("2026-08-20", 1)
        _appointment, animals = book_and_confirm(c1["id"], day["id"], "BEEF", 1)
        animal = process_animal_to_hanging(animals[0]["id"], "TAG-A1", 1200.0, 700.0)
        s1 = add_share(animal["id"], c1["id"], 0.5, as_customer_id=c1["id"])
        s2 = add_share(animal["id"], c2["id"], 0.5, as_customer_id=c1["id"])
        finalize_split(animal["id"])
        sheet1 = create_and_submit_cut_sheet(s1["id"], c1["id"])
        sheet2 = create_cut_sheet(s2["id"], c2["id"], grind_pct=40,
                                  package_weight_lbs=1.5)
        set_logical_clock("2026-08-04T00:00:00Z")
        resp = api.start_fabrication(animal["id"], OP)
        validate_error(resp, ApiErrorId.ERR_CUT_SHEET_MISSING, expected_status=422)
        # Once the second sheet is submitted, the gate clears.
        submit_cut_sheet(sheet2["id"], c2["id"])
        data = validate_success(api.start_fabrication(animal["id"], OP))
        assert data["status"] == "CUTTING"
        assert get_cut_sheet(sheet1["id"])["status"] == "LOCKED"
        assert get_cut_sheet(sheet2["id"])["status"] == "LOCKED"

    def test_start_fab_wrong_state_reports_state_error(self, api):
        """PRD §2.8: "then state-transition legality including terminal-state
        lockdown (`ERR_INVALID_STATE`, HTTP 409) ... then referential
        completeness (missing cut sheets, unapproved labels)" — the state
        check is evaluated before the referential cut-sheet check.

        Design: Difficulty/priority_pair_validation_conflict/start_fab_wrong_state_beats_missing_cut_sheet
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 1)
        _appointment, animals = book_and_confirm(customer["id"], day["id"], "HOG", 1)
        animal_id = animals[0]["id"]
        get_success_data(
            api.receive_animal(animal_id, {"tag_id": "TAG-H1",
                                           "live_weight_lbs": 280.0}, OP)
        )
        get_success_data(api.slaughter_animal(animal_id, OP))
        # SLAUGHTERED (not HANGING) AND no cut sheets exist at all.
        resp = api.start_fabrication(animal_id, OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_start_fab_wrong_state_leaves_animal_unchanged(self, api):
        """PRD §2.8: "then state-transition legality including terminal-state
        lockdown (`ERR_INVALID_STATE`, HTTP 409)".
        PRD §3.5: "the animal moves from `HANGING` to `CUTTING`" — only when
        the preconditions hold; a rejected start leaves the animal in place.

        Design: Difficulty/priority_pair_validation_conflict/start_fab_wrong_state_beats_missing_cut_sheet
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 1)
        _appointment, animals = book_and_confirm(customer["id"], day["id"], "HOG", 1)
        animal_id = animals[0]["id"]
        get_success_data(
            api.receive_animal(animal_id, {"tag_id": "TAG-H1",
                                           "live_weight_lbs": 280.0}, OP)
        )
        slaughtered = get_success_data(api.slaughter_animal(animal_id, OP))
        resp = api.start_fabrication(animal_id, OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = get_success_data(api.get_animal(animal_id, OP))
        assert after["status"] == "SLAUGHTERED"
        assert after["version"] == slaughtered["version"], (
            "a rejected transition must not mutate the animal"
        )
